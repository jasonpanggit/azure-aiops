"""Azure AI Foundry prompt agent client for the Operations Copilot.

The Copilot answers in two stages, and the split is deliberate:

1. **Retrieval** is done by the Semantic Knowledge Layer, exactly as every
   other read route does it. Facts come from the governed ontology snapshot.
2. **Narration** is done by a Foundry *prompt agent*, which is given only the
   retrieved context and is instructed to answer strictly from it.

The model therefore never invents inventory. If retrieval returns nothing the
Copilot says so rather than letting the model fill the gap, which is what the
UI's "will not do: invent unsupported answers" trust boundary promises.

Foundry prompt agents have no ARM/Terraform resource type — they are created
through the data plane (see ``infra/scripts/create-foundry-agent.sh``). This
module only *invokes* an already-provisioned agent, so a missing or
misconfigured agent degrades to retrieval-only answers instead of failing the
request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

ENV_PROJECT_ENDPOINT = "FOUNDRY_PROJECT_ENDPOINT"
ENV_AGENT_NAME = "FOUNDRY_AGENT_NAME"
ENV_API_VERSION = "FOUNDRY_API_VERSION"
ENV_TIMEOUT = "FOUNDRY_TIMEOUT_SECONDS"

# The Foundry "projects (new)" data plane is versioned with the literal string
# `v1`, not a date. See the Microsoft quickstart sample for prompt agents.
DEFAULT_API_VERSION = "v1"
DEFAULT_TIMEOUT_SECONDS = 60.0

# Entra scope for the Foundry data plane. Distinct from the ARM scope: an ARM
# token is rejected by the agents endpoint.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"

# Tokens are cached until shortly before expiry. The renewal margin absorbs
# clock skew and in-flight request latency.
_TOKEN_RENEWAL_MARGIN_SECONDS = 300.0


class FoundryAgentError(RuntimeError):
    """The Foundry agent could not produce an answer."""


class FoundryAgentNotConfigured(FoundryAgentError):
    """No Foundry agent is configured for this deployment."""


@dataclass(frozen=True)
class AgentAnswer:
    """A narrated answer plus the provenance needed to render it honestly."""

    text: str
    agent_name: str
    model: str = ""
    grounded: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "agent_name": self.agent_name,
            "model": self.model,
            "grounded": self.grounded,
        }


class _TokenProvider:
    """Caches an Entra access token for the Foundry data plane.

    ``DefaultAzureCredential`` resolves the Container App's managed identity in
    Azure and falls back to the developer's CLI login locally, so the same code
    path works in both places without a secret.
    """

    def __init__(self, scope: str = FOUNDRY_SCOPE) -> None:
        self._scope = scope
        self._lock = threading.Lock()
        self._token = ""
        self._expires_on = 0.0
        self._credential: Any | None = None

    def _get_credential(self) -> Any:
        if self._credential is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise FoundryAgentError(
                    "azure-identity is required to call the Foundry agent"
                ) from exc
            self._credential = DefaultAzureCredential()
        return self._credential

    def token(self) -> str:
        with self._lock:
            now = time.time()
            if self._token and now < self._expires_on - _TOKEN_RENEWAL_MARGIN_SECONDS:
                return self._token
            try:
                acquired = self._get_credential().get_token(self._scope)
            except Exception as exc:
                raise FoundryAgentError(
                    "Could not acquire an Entra token for the Foundry data plane"
                ) from exc
            self._token = acquired.token
            self._expires_on = float(acquired.expires_on)
            return self._token


class FoundryPromptAgent:
    """Invokes a Foundry prompt agent over the data-plane REST API.

    ``urllib`` is used rather than the ``azure-ai-projects`` SDK to keep the API
    image free of an extra dependency whose only use would be two HTTP calls.
    The wire contract is small and stable, and every failure is translated into
    a :class:`FoundryAgentError` the router can degrade on.
    """

    def __init__(
        self,
        *,
        project_endpoint: str,
        agent_name: str,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        token_provider: _TokenProvider | None = None,
    ) -> None:
        endpoint = str(project_endpoint or "").strip().rstrip("/")
        name = str(agent_name or "").strip()
        if not endpoint or not name:
            raise FoundryAgentNotConfigured(
                "A Foundry project endpoint and agent name are both required"
            )
        self.project_endpoint = endpoint
        self.agent_name = name
        self.api_version = api_version or DEFAULT_API_VERSION
        self.timeout_seconds = timeout_seconds
        self._tokens = token_provider or _TokenProvider()

    @classmethod
    def from_env(cls) -> FoundryPromptAgent | None:
        """Build from the environment, or ``None`` when unconfigured.

        Returning ``None`` (rather than raising) is what lets a deployment run
        without Foundry: the Copilot then answers with retrieval only.
        """
        endpoint = os.environ.get(ENV_PROJECT_ENDPOINT, "").strip()
        agent_name = os.environ.get(ENV_AGENT_NAME, "").strip()
        if not endpoint or not agent_name:
            return None
        try:
            timeout = float(os.environ.get(ENV_TIMEOUT, "") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        return cls(
            project_endpoint=endpoint,
            agent_name=agent_name,
            api_version=os.environ.get(ENV_API_VERSION, "").strip()
            or DEFAULT_API_VERSION,
            timeout_seconds=timeout,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.project_endpoint}{path}"
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}api-version={self.api_version}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._tokens.token()}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise FoundryAgentError(
                f"Foundry agent request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise FoundryAgentError(
                "Foundry agent endpoint is unreachable"
            ) from exc
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise FoundryAgentError("Foundry agent returned a malformed response") from exc
        return parsed if isinstance(parsed, dict) else {}

    def validate_access(self) -> None:
        """Verify the configured identity can acquire a Foundry data-plane token."""
        self._tokens.token()

    def answer(self, *, question: str, context: Any) -> AgentAnswer:
        """Narrate ``context`` in response to ``question``.

        The retrieved context is passed as JSON in the user turn rather than
        being appended to the agent's instructions, so the agent's governed
        system prompt (created at deploy time) cannot be overridden by anything
        that came out of the knowledge layer.
        """
        prompt = _build_prompt(question=question, context=context)
        response = self._post(
            f"/agents/{self.agent_name}/responses",
            {"input": [{"role": "user", "content": prompt}], "stream": False},
        )
        text = _extract_text(response)
        if not text:
            raise FoundryAgentError("Foundry agent returned an empty answer")
        return AgentAnswer(
            text=text,
            agent_name=self.agent_name,
            model=str(response.get("model") or ""),
            grounded=True,
        )


# Cap the grounding payload. A very large context both costs tokens and pushes
# the governed instructions out of the model's attention; the knowledge layer
# already bounds its own results, this is a second, hard ceiling.
_MAX_CONTEXT_CHARS = 24_000


def _build_prompt(*, question: str, context: Any) -> str:
    """Frame the retrieved context as the only admissible evidence."""
    serialized = json.dumps(context, default=str, ensure_ascii=False)
    if len(serialized) > _MAX_CONTEXT_CHARS:
        serialized = serialized[:_MAX_CONTEXT_CHARS] + "\u2026(truncated)"
    return (
        "Answer the operator's question using only the operational context "
        "below. It was retrieved from the governed knowledge graph. If the "
        "context does not contain the answer, say so explicitly and do not "
        "speculate.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"OPERATIONAL CONTEXT (JSON):\n{serialized}"
    )


def _extract_text(response: dict[str, Any]) -> str:
    """Pull assistant text out of a Foundry responses payload.

    The response shape carries the text under ``output[].content[].text``.
    ``output_text`` is honoured first because the service also emits that
    convenience field, and both are tolerated so a benign additive change to
    the wire format does not break the Copilot.
    """
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if isinstance(direct, list):
        joined = "\n".join(str(part) for part in direct if str(part).strip())
        if joined.strip():
            return joined.strip()

    fragments: list[str] = []
    for item in response.get("output") or ():
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            fragments.append(content)
            continue
        for part in content or ():
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, dict):
                    text = text.get("value")
                if isinstance(text, str) and text.strip():
                    fragments.append(text)
            elif isinstance(part, str) and part.strip():
                fragments.append(part)
    return "\n".join(fragments).strip()
