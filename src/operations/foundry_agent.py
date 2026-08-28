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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

ENV_PROJECT_ENDPOINT = "FOUNDRY_PROJECT_ENDPOINT"
ENV_AGENT_NAME = "FOUNDRY_AGENT_NAME"
ENV_API_VERSION = "FOUNDRY_API_VERSION"
ENV_TIMEOUT = "FOUNDRY_TIMEOUT_SECONDS"
ENV_MAX_RETRIES = "FOUNDRY_MAX_RETRIES"
ENV_CIRCUIT_THRESHOLD = "FOUNDRY_CIRCUIT_BREAKER_THRESHOLD"
ENV_CIRCUIT_RESET_SECONDS = "FOUNDRY_CIRCUIT_BREAKER_RESET_SECONDS"

# The Foundry "projects (new)" data plane is versioned with the literal string
# `v1`, not a date. See the Microsoft quickstart sample for prompt agents.
DEFAULT_API_VERSION = "v1"
SPECIALIST_IDS = (
    "network",
    "vulnerability",
    "patch",
    "incident",
    "change",
    "governance",
    "remediation",
    "executive_summary",
)
DEFAULT_TIMEOUT_SECONDS = 60.0
SPECIALIST_CONTRACT_VERSION = "network-finding.v1"
_MUTATION_WORDS = ("delete", "create", "update", "modify", "execute", "apply", "remediate")

# Entra scope for the Foundry data plane. Distinct from the ARM scope: an ARM
# token is rejected by the agents endpoint.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"

# Tokens are cached until shortly before expiry. The renewal margin absorbs
# clock skew and in-flight request latency.
_TOKEN_RENEWAL_MARGIN_SECONDS = 300.0

# Reliability defaults (SLO-driven; see docs/pilot/RELIABILITY.md). Retries
# are bounded and only cover transient network/5xx failures -- a malformed
# response or an empty answer is a content problem, not a transport one, and
# retrying it would not help. The circuit breaker exists so a Foundry outage
# degrades every request to retrieval-only immediately (bounded latency)
# instead of every concurrent request separately paying the full retry/
# timeout budget against a dependency that is already down.
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5
DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS = 60.0

# HTTP status codes worth retrying: request-rate/backpressure and transient
# upstream failures. 4xx client errors (bad prompt, auth) are not retried.
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


class FoundryAgentError(RuntimeError):
    """The Foundry agent could not produce an answer."""


class FoundryAgentNotConfigured(FoundryAgentError):
    """No Foundry agent is configured for this deployment."""


class FoundryCircuitOpenError(FoundryAgentError):
    """The circuit breaker is open; the Foundry call was short-circuited."""


class _RetryableFoundryError(FoundryAgentError):
    """A transient failure worth retrying (network error or 5xx/429)."""


class _CircuitBreaker:
    """Minimal open/closed circuit breaker guarding the Foundry endpoint.

    Half-open probing is intentionally omitted: the reset window itself acts
    as the probe interval, and the next call after it elapses is allowed
    through and re-opens the circuit immediately on failure. This keeps the
    breaker's behavior easy to reason about and test without a third state.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD,
        reset_seconds: float = DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._reset_seconds = max(0.0, reset_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0

    def before_call(self) -> None:
        with self._lock:
            if self._failures < self._failure_threshold:
                return
            elapsed = self._clock() - self._opened_at
            if elapsed < self._reset_seconds:
                raise FoundryCircuitOpenError(
                    "Foundry agent circuit breaker is open after repeated "
                    "failures; degrading to retrieval-only"
                )
            # Reset window elapsed: allow one probing call through by
            # resetting the failure count. A renewed failure re-opens it.
            self._failures = 0

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._failures < self._failure_threshold:
                return False
            return (self._clock() - self._opened_at) < self._reset_seconds


@dataclass(frozen=True)
class AgentAnswer:
    """A narrated answer plus the provenance needed to render it honestly."""

    text: str
    agent_name: str
    model: str = ""
    grounded: bool = True
    agent_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "agent_name": self.agent_name,
            "model": self.model,
            "grounded": self.grounded,
            "agent_version": self.agent_version,
        }


def parse_specialist_findings(
    text: str,
    *,
    evidence_refs: set[str],
    resource_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Validate the small, cited contract emitted by a specialist.

    Foundry is an untrusted narrator.  This parser deliberately accepts no
    prose wrapper and requires every claim to point at evidence supplied by the
    local orchestrator.
    """
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise FoundryAgentError("Foundry specialist output is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"findings"}:
        raise FoundryAgentError("Foundry specialist output must contain only findings")
    findings = payload["findings"]
    if not isinstance(findings, list) or len(findings) > 25:
        raise FoundryAgentError("Foundry specialist findings are not bounded")
    validated: list[dict[str, Any]] = []
    required = {
        "finding_id", "resource_ids", "check_id", "policy_id", "evidence_refs",
        "confidence", "uncertainty", "freshness", "actionable", "next_check", "summary",
    }
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != required:
            raise FoundryAgentError("Foundry specialist finding schema is invalid")
        if not isinstance(finding["finding_id"], str) or not finding["finding_id"].strip():
            raise FoundryAgentError("Foundry finding id is required")
        if not isinstance(finding["resource_ids"], list) or any(
            not isinstance(value, str) or not value.startswith("/subscriptions/")
            for value in finding["resource_ids"]
        ):
            raise FoundryAgentError("Foundry finding resource IDs are invalid")
        if resource_ids is not None and not set(finding["resource_ids"]) <= resource_ids:
            raise FoundryAgentError("Foundry finding introduced an uncited resource")
        refs = finding["evidence_refs"]
        if not isinstance(refs, list) or not refs or not set(refs) <= evidence_refs:
            raise FoundryAgentError("Foundry finding citation is missing or invalid")
        if finding["confidence"] not in {"high", "medium", "low", "unknown"}:
            raise FoundryAgentError("Foundry finding confidence is invalid")
        if finding["freshness"] not in {"fresh", "stale", "partial", "unavailable", "unknown"}:
            raise FoundryAgentError("Foundry finding freshness is invalid")
        if not isinstance(finding["uncertainty"], list) or any(
            not isinstance(value, str) for value in finding["uncertainty"]
        ):
            raise FoundryAgentError("Foundry finding uncertainty is invalid")
        if not isinstance(finding["actionable"], bool) or not isinstance(finding["next_check"], str):
            raise FoundryAgentError("Foundry finding action contract is invalid")
        if len(finding["next_check"]) > 240 or not finding["next_check"].strip():
            raise FoundryAgentError("Foundry finding next check is not bounded")
        if not isinstance(finding["summary"], str) or not finding["summary"].strip():
            raise FoundryAgentError("Foundry finding summary is required")
        text_values = json.dumps(finding, ensure_ascii=False).casefold()
        if any(word in text_values for word in _MUTATION_WORDS):
            raise FoundryAgentError("Foundry specialist output contains mutation instructions")
        validated.append(finding)
    return validated


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
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        circuit_breaker: _CircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
        specialist_id: str = "network",
        agent_version: str = "",
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
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._breaker = circuit_breaker or _CircuitBreaker()
        self._sleep = sleep
        self.specialist_id = specialist_id
        self.agent_version = agent_version

    @classmethod
    def from_env(cls, specialist_id: str | None = None) -> FoundryPromptAgent | None:
        """Build from the environment, or ``None`` when unconfigured.

        Returning ``None`` (rather than raising) is what lets a deployment run
        without Foundry: the Copilot then answers with retrieval only.
        """
        endpoint = os.environ.get(ENV_PROJECT_ENDPOINT, "").strip()
        specialist = (specialist_id or "").strip().casefold()
        specialist_name = (
            os.environ.get(f"FOUNDRY_{specialist.upper()}_AGENT_NAME", "").strip()
            if specialist
            else ""
        )
        agent_name = specialist_name or os.environ.get(ENV_AGENT_NAME, "").strip()
        if not endpoint or not agent_name:
            return None
        try:
            timeout = float(os.environ.get(ENV_TIMEOUT, "") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        try:
            max_retries = int(os.environ.get(ENV_MAX_RETRIES, "") or DEFAULT_MAX_RETRIES)
        except ValueError:
            max_retries = DEFAULT_MAX_RETRIES
        try:
            circuit_threshold = int(
                os.environ.get(ENV_CIRCUIT_THRESHOLD, "")
                or DEFAULT_CIRCUIT_BREAKER_THRESHOLD
            )
        except ValueError:
            circuit_threshold = DEFAULT_CIRCUIT_BREAKER_THRESHOLD
        try:
            circuit_reset = float(
                os.environ.get(ENV_CIRCUIT_RESET_SECONDS, "")
                or DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS
            )
        except ValueError:
            circuit_reset = DEFAULT_CIRCUIT_BREAKER_RESET_SECONDS
        return cls(
            project_endpoint=endpoint,
            agent_name=agent_name,
            api_version=os.environ.get(ENV_API_VERSION, "").strip()
            or DEFAULT_API_VERSION,
            timeout_seconds=timeout,
            max_retries=max_retries,
            circuit_breaker=_CircuitBreaker(
                failure_threshold=circuit_threshold, reset_seconds=circuit_reset
            ),
            specialist_id=specialist or "network",
            agent_version=(
                os.environ.get(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "").strip()
                if specialist
                else os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
            ),
        )

    def _post_once(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
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
            if exc.code in _RETRYABLE_HTTP_STATUS:
                raise _RetryableFoundryError(
                    f"Foundry agent request failed with HTTP {exc.code}: {detail}"
                ) from exc
            raise FoundryAgentError(
                f"Foundry agent request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise _RetryableFoundryError("Foundry agent endpoint is unreachable") from exc
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise FoundryAgentError("Foundry agent returned a malformed response") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _post(self, path: str, payload: dict[str, Any], *, versioned: bool = True) -> dict[str, Any]:
        url = f"{self.project_endpoint}{path}"
        if versioned:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}api-version={self.api_version}"

        # Short-circuit before doing any network I/O when the breaker is
        # open, so an ongoing Foundry outage costs one dict lookup instead of
        # a full timeout per concurrent request.
        self._breaker.before_call()

        attempt = 0
        while True:
            try:
                result = self._post_once(url, payload)
            except _RetryableFoundryError as exc:
                attempt += 1
                if attempt > self.max_retries:
                    self._breaker.record_failure()
                    raise FoundryAgentError(str(exc)) from exc
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                continue
            except FoundryAgentError:
                self._breaker.record_failure()
                raise
            else:
                self._breaker.record_success()
                return result

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
        prompt = self.build_prompt(question, context)
        response = self._post(
            "/openai/v1/responses",
            {
                "agent_reference": {"type": "agent_reference", "name": self.agent_name},
                "input": [{"role": "user", "content": prompt}],
            },
            versioned=False,
        )
        text = _extract_text(response)
        if not text:
            raise FoundryAgentError("Foundry agent returned an empty answer")
        return AgentAnswer(
            text=text,
            agent_name=self.agent_name,
            model=str(response.get("model") or ""),
            grounded=True,
            agent_version=self.agent_version,
        )

    def answer_findings(
        self,
        *,
        question: str,
        context: Any,
        evidence_refs: set[str],
        resource_ids: set[str] | None = None,
    ) -> AgentAnswer:
        """Request and strictly validate a specialist finding response."""
        answer = self.answer(question=question, context=context)
        findings = parse_specialist_findings(
            answer.text, evidence_refs=evidence_refs, resource_ids=resource_ids
        )
        return AgentAnswer(
            text=answer.text,
            agent_name=answer.agent_name,
            model=answer.model,
            grounded=True,
            agent_version=self.agent_version,
        )

    def build_prompt(self, question: str, context: Any) -> str:
        """Expose the bounded, evidence-only prompt for contract testing."""
        return _build_prompt(
            question=question,
            context=context,
            specialist_id=self.specialist_id,
        )


# Cap the grounding payload. A very large context both costs tokens and pushes
# the governed instructions out of the model's attention; the knowledge layer
# already bounds its own results, this is a second, hard ceiling.
_MAX_CONTEXT_CHARS = 24_000


def _build_prompt(
    *, question: str, context: Any, specialist_id: str = "network"
) -> str:
    """Frame the retrieved context as the only admissible evidence."""
    serialized = json.dumps(context, default=str, ensure_ascii=False)
    if len(serialized) > _MAX_CONTEXT_CHARS:
        serialized = serialized[:_MAX_CONTEXT_CHARS] + "\u2026(truncated)"
    return (
        f"You are the {specialist_id} specialist. "
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


def specialist_catalog() -> list[dict[str, Any]]:
    """Return independent release metadata without claiming unavailable agents exist."""
    endpoint = os.environ.get(ENV_PROJECT_ENDPOINT, "").strip()
    entries: list[dict[str, Any]] = []
    for specialist in SPECIALIST_IDS:
        prefix = f"FOUNDRY_{specialist.upper()}_AGENT"
        name = os.environ.get(f"{prefix}_NAME", "").strip()
        version = os.environ.get(f"{prefix}_VERSION", "").strip()
        if not name and specialist == "network":
            name = os.environ.get(ENV_AGENT_NAME, "").strip()
            version = version or os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
        entries.append(
            {
                "id": specialist,
                "name": name,
                "version": version,
                "status": "ready" if endpoint and name and version else "unavailable",
                "configured": bool(endpoint and name and version),
            }
        )
    return entries
