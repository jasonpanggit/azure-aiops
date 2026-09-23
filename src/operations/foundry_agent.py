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

import asyncio
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from operations.foundry_candidate_catalog import validated_candidate_catalog
from operations.maf_orchestrator import reviewed_specialists_for_page
from operations.mcp_server import tool_definitions
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    CandidatePlan,
    InvestigationRequest,
)
from operations.specialist_manifest import load_specialist_manifest

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
_SPECIALIST_MANIFEST = load_specialist_manifest()
SPECIALIST_IDS = _SPECIALIST_MANIFEST.specialist_ids
DEFAULT_TIMEOUT_SECONDS = 60.0
SPECIALIST_CONTRACT_VERSION = "network-finding.v1"
EXECUTIVE_SPECIALIST_ID = "executive_summary"
MAX_SYNTHESIS_FINDINGS = 25
MAX_RETAINED_SYNTHESIS_EVIDENCE = 50
MAX_CONTEXT_CHARS = 24_000
_MAX_CONTEXT_CHARS = MAX_CONTEXT_CHARS
_NETWORK_TOPOLOGY_COUNT_FIELDS = frozenset({
    "hub_count",
    "spoke_count",
    "isolated_vnet_count",
    "peering_count",
    "cross_subscription_peering_count",
    "unhealthy_peering_count",
    "shared_service_count",
    "connection_count",
    "gap_count",
    "rule_finding_count",
    "projected_full_node_count",
})
_MUTATION_WORDS = ("delete", "create", "update", "modify", "execute", "apply", "remediate")
_MUTATION_WORD_PATTERN = re.compile(
    rf"\b(?:{'|'.join(_MUTATION_WORDS)})\b",
    re.IGNORECASE,
)
_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def _version_pinning_required() -> bool:
    return (
        os.environ.get("AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED", "").strip().casefold()
        in _TRUE_ENV_VALUES
    )

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
_FOUNDRY_CALL_EXECUTOR = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="foundry-call",
)


def _set_response_socket_timeout(response: Any, timeout: float) -> None:
    """Narrow the active HTTP socket timeout as the wall-clock budget shrinks."""

    socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if socket is not None:
        socket.settimeout(max(0.001, timeout))


def _read_response_until(response: Any, *, deadline: float) -> bytes:
    """Read one available chunk at a time without letting drip traffic reset expiry."""

    chunks: list[bytes] = []
    read_chunk = getattr(response, "read1", None) or response.read
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Foundry response exceeded its time budget")
        _set_response_socket_timeout(response, remaining)
        chunk = read_chunk(64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


class FoundryAgentError(RuntimeError):
    """The Foundry agent could not produce an answer."""


class FoundryResponseContractError(FoundryAgentError):
    """A returned answer failed local normalization or contract validation."""


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


def _agent_contract(agent_id: str) -> dict[str, Any]:
    """Return the manifest-derived validation contract for one specialist."""

    try:
        return _SPECIALIST_MANIFEST.output_contracts()[agent_id.casefold()]
    except KeyError as exc:
        raise FoundryAgentError(f"unknown specialist {agent_id!r}") from exc


def parse_specialist_findings(
    text: str,
    *,
    evidence_refs: set[str],
    resource_ids: set[str] | None = None,
    agent_id: str = "network",
    allow_remediation_summary: bool = False,
) -> list[dict[str, Any]]:
    """Validate the small, cited contract emitted by a specialist.

    Foundry is an untrusted narrator. This parser deliberately accepts no
    prose wrapper and requires every claim to point at evidence supplied by the
    local orchestrator. Each agent has domain-specific required fields.
    Executive synthesis may describe remediation in its summary; this never
    authorizes execution and its next check must still be read-only.
    """
    contract = _agent_contract(agent_id)
    required = contract["required"]
    
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise FoundryAgentError(f"{agent_id} specialist output is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"findings"}:
        raise FoundryAgentError(f"{agent_id} specialist output must contain only findings")
    findings = payload["findings"]
    if not isinstance(findings, list) or len(findings) > 25:
        raise FoundryAgentError(f"{agent_id} specialist findings are not bounded")
    
    validated: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != required:
            raise FoundryAgentError(
                f"{agent_id} specialist finding schema is invalid; expected {required}, got {set(finding)}"
            )
        if not isinstance(finding["finding_id"], str) or not finding["finding_id"].strip():
            raise FoundryAgentError(f"{agent_id} finding id is required")
        
        # Validate resource_ids if present (not required for incident, executive_summary)
        if "resource_ids" in required:
            if not isinstance(finding["resource_ids"], list) or any(
                not isinstance(value, str) or not value.startswith("/subscriptions/")
                for value in finding["resource_ids"]
            ):
                raise FoundryAgentError(f"{agent_id} finding resource IDs are invalid")
            if resource_ids is not None and not set(finding["resource_ids"]) <= resource_ids:
                raise FoundryAgentError(f"{agent_id} finding introduced an uncited resource")
        
        # Validate agent-specific domain fields
        refs = finding["evidence_refs"]
        if not isinstance(refs, list) or not refs or not set(refs) <= evidence_refs:
            raise FoundryAgentError(f"{agent_id} finding citation is missing or invalid")
        
        # Validate common fields
        if finding["confidence"] not in {"high", "medium", "low", "unknown"}:
            raise FoundryAgentError(f"{agent_id} finding confidence is invalid")
        if finding["freshness"] not in {"fresh", "stale", "partial", "unavailable", "unknown"}:
            raise FoundryAgentError(f"{agent_id} finding freshness is invalid")
        if not isinstance(finding["uncertainty"], list) or any(
            not isinstance(value, str) for value in finding["uncertainty"]
        ):
            raise FoundryAgentError(f"{agent_id} finding uncertainty is invalid")
        if not isinstance(finding["actionable"], bool) or not isinstance(finding["next_check"], str):
            raise FoundryAgentError(f"{agent_id} finding action contract is invalid")
        if len(finding["next_check"]) > 240 or not finding["next_check"].strip():
            raise FoundryAgentError(f"{agent_id} finding next check is not bounded")
        if not isinstance(finding["summary"], str) or not finding["summary"].strip():
            raise FoundryAgentError(f"{agent_id} finding summary is required")
        
        # Describing remediation is not executing it. Only the executive
        # narrative gets this exception; next_check and uncertainty stay strict.
        mutation_fields = finding
        if allow_remediation_summary and agent_id == EXECUTIVE_SPECIALIST_ID:
            mutation_fields = {
                key: value for key, value in finding.items() if key != "summary"
            }
        text_values = json.dumps(mutation_fields, ensure_ascii=False).casefold()
        if _MUTATION_WORD_PATTERN.search(text_values):
            raise FoundryAgentError(f"{agent_id} specialist output contains mutation instructions")
        
        validated.append(finding)
    return validated


def normalize_cited_findings(
    tool_results: Iterable[Mapping[str, Any]],
    *,
    selected_resource_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Project specialist tool results into normalized, cited findings.

    Executive synthesis is the one place a second model sees the output of the
    first, so it is given the smallest honest projection: who reported it, what
    status it carried, and which evidence identifiers back it. Tool arguments,
    raw provider payloads, and anything the specialist said about its own
    reasoning are dropped here rather than filtered later, because a field that
    is never assembled cannot leak. A result with no evidence is not a
    material finding and is omitted entirely.
    """

    def bounded_utf8(value: str, limit: int) -> str:
        encoded = value.encode("utf-8")
        return (
            value
            if len(encoded) <= limit
            else encoded[:limit].decode("utf-8", errors="ignore")
        )

    def bounded_text(value: Any, limit: int = 160) -> str:
        if not isinstance(value, str):
            return ""
        normalized = " ".join(value.split())
        if normalized.casefold().startswith("/subscriptions/"):
            return ""
        return bounded_utf8(normalized, limit)

    selected_ids = {
        resource_id.casefold()
        for resource_id in selected_resource_ids or set()
        if isinstance(resource_id, str) and resource_id.strip()
    }

    def hub_dependents_summary(data: Any) -> str:
        if not isinstance(data, Mapping):
            return ""
        hub_name = bounded_text(data.get("hub_name")) or "the requested hub"
        raw_count = data.get("dependent_count")
        dependent_count = (
            raw_count
            if isinstance(raw_count, int) and raw_count >= 0
            else 0
        )
        summary = f"Hub {hub_name} has {dependent_count} dependent VNets"
        summary += "."
        return bounded_utf8(summary, 2_000)

    def network_topology_summary(data: Any) -> str:
        if not isinstance(data, Mapping):
            return ""
        summary_data = data.get("summary")
        topology_data = data.get("topology")
        counts = summary_data if isinstance(summary_data, Mapping) else {}
        topology = topology_data if isinstance(topology_data, Mapping) else {}
        count_parts = [
            f"{key}={value}"
            for key, value in sorted(counts.items())
            if (
                isinstance(key, str)
                and key in _NETWORK_TOPOLOGY_COUNT_FIELDS
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            )
        ] if isinstance(counts, Mapping) else []
        selected_parts: list[str] = []
        emitted_selected_ids: set[str] = set()
        for collection, collection_role in (
            ("hubs", "hub"),
            ("spokes", "spoke"),
            ("isolated", "isolated"),
            ("resources", ""),
        ):
            rows = topology.get(collection)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                resource_id = str(
                    row.get("id") or row.get("vnet_id") or row.get("resource_id") or ""
                ).strip()
                normalized_resource_id = resource_id.casefold()
                if (
                    not resource_id
                    or normalized_resource_id not in selected_ids
                    or normalized_resource_id in emitted_selected_ids
                ):
                    continue
                name = bounded_text(row.get("name"))
                role = bounded_text(row.get("role")) or collection_role
                resource_type = bounded_text(
                    row.get("entity_type") or row.get("resource_type") or row.get("type")
                )
                peer_count = row.get("peer_count")
                fields = [
                    part
                    for part in (
                        f"name={name}" if name else "",
                        f"role={role}" if role else "",
                        f"type={resource_type}" if resource_type else "",
                        (
                            f"peer_count={peer_count}"
                            if (
                                isinstance(peer_count, int)
                                and not isinstance(peer_count, bool)
                                and peer_count >= 0
                            )
                            else ""
                        ),
                    )
                    if part
                ]
                if fields:
                    selected_parts.append("selected resource: " + ", ".join(fields))
                    emitted_selected_ids.add(normalized_resource_id)
                    break
        parts = [
            f"Topology counts: {', '.join(count_parts)}." if count_parts else "",
            *dict.fromkeys(selected_parts),
        ]
        return bounded_utf8(" ".join(part for part in parts if part), 2_000)

    findings: list[dict[str, Any]] = []
    for result in tool_results:
        if not isinstance(result, Mapping):
            continue
        specialist_id = str(result.get("specialist_id") or "")
        tool = str(result.get("tool") or "")
        call_id = str(result.get("call_id") or f"{specialist_id}:{tool}")
        refs = [
            # The orchestrator mints one citation per evidence row as
            # `tool:<call_id>:<index>`, so derive the same identifier here:
            # synthesis must cite what the result actually published, not a
            # parallel naming scheme that could never be closed against it.
            str(item.get("evidence_id") or f"tool:{call_id}:{index}")
            for index, item in enumerate(result.get("evidence") or [])
            if isinstance(item, Mapping)
        ]
        if not refs:
            continue
        status = str(result.get("status") or "")
        summary = (
            hub_dependents_summary(result.get("data"))
            if tool == "hub_dependents" and status == "ok"
            else network_topology_summary(result.get("data"))
            if tool == "network_topology" and status == "ok"
            else ""
        )
        findings.append(
            {
                "finding_id": call_id,
                "specialist_id": specialist_id,
                "status": status,
                "summary": summary or f"{specialist_id} reported {status} from {tool}.",
                "evidence_refs": refs,
                "observation_status": str(
                    result.get("observation_status") or "current"
                ),
            }
        )
        if len(findings) >= MAX_SYNTHESIS_FINDINGS:
            break
    return findings


def executive_synthesis_input(
    findings: Iterable[Mapping[str, Any]],
    *,
    retained_evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the bounded, citation-only context handed to executive synthesis.

    Retained evidence is carried so synthesis can reconcile this turn against
    what the thread already holds, but it is reduced to its identity, source,
    status, and observation status: continuity must not become a channel for
    replaying raw provider payloads into a second model.
    """

    payload: dict[str, list[dict[str, Any]]] = {
        "findings": [],
        "retained_evidence": [],
    }

    def fits(candidate: dict[str, list[dict[str, Any]]]) -> bool:
        return len(json.dumps(candidate, default=str, ensure_ascii=False)) <= (
            MAX_CONTEXT_CHARS
        )

    for item in list(findings)[:MAX_SYNTHESIS_FINDINGS]:
        if not isinstance(item, Mapping):
            continue
        finding = {
            "finding_id": str(item.get("finding_id") or ""),
            "specialist_id": str(item.get("specialist_id") or ""),
            "status": str(item.get("status") or ""),
            "summary": str(item.get("summary") or ""),
            "evidence_refs": [],
            "observation_status": str(item.get("observation_status") or "current"),
        }
        for ref in item.get("evidence_refs") or []:
            candidate = deepcopy(payload)
            candidate_finding = deepcopy(finding)
            candidate_finding["evidence_refs"].append(str(ref))
            candidate["findings"].append(candidate_finding)
            if not fits(candidate):
                break
            finding = candidate_finding
        if not finding["evidence_refs"]:
            continue
        candidate = deepcopy(payload)
        candidate["findings"].append(finding)
        if not fits(candidate):
            break
        payload = candidate

    for item in list(retained_evidence)[:MAX_RETAINED_SYNTHESIS_EVIDENCE]:
        if not isinstance(item, Mapping):
            continue
        retained = {
            "evidence_id": str(item.get("evidence_id") or ""),
            "source": str(item.get("source") or ""),
            "status": str(item.get("status") or ""),
            "observation_status": str(
                item.get("observation_status") or "historical"
            ),
        }
        candidate = deepcopy(payload)
        candidate["retained_evidence"].append(retained)
        if not fits(candidate):
            break
        payload = candidate
    return payload


def validate_executive_synthesis(
    text: str,
    *,
    evidence_refs: set[str],
) -> list[dict[str, Any]]:
    """Citation-close executive claims against the specialists' own references.

    The executive agent aggregates; it does not observe. Any claim pointing at
    an identifier no specialist reported is a fabrication regardless of how
    plausible it reads, so the whole synthesis is rejected rather than
    partially accepted.
    """

    try:
        return parse_specialist_findings(
            text,
            evidence_refs=set(evidence_refs),
            agent_id=EXECUTIVE_SPECIALIST_ID,
            allow_remediation_summary=True,
        )
    except (FoundryAgentError, TypeError, ValueError) as exc:
        raise FoundryResponseContractError(str(exc)) from exc


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
        agent_version = (
            os.environ.get(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "").strip()
            if specialist
            else os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
        )
        if _version_pinning_required() and not agent_version:
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
            agent_version=agent_version,
        )

    def _post_once(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        timeout = (
            self.timeout_seconds
            if timeout_seconds is None
            else min(self.timeout_seconds, max(0.001, timeout_seconds))
        )
        deadline = time.monotonic() + timeout
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
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = _read_response_until(response, deadline=deadline).decode("utf-8")
        except urllib.error.HTTPError as exc:
            try:
                detail = _read_response_until(
                    exc,
                    deadline=deadline,
                ).decode("utf-8", errors="replace")[:500]
            except TimeoutError as timeout_exc:
                raise _RetryableFoundryError(
                    "Foundry agent request exceeded its time budget"
                ) from timeout_exc
            if exc.code in _RETRYABLE_HTTP_STATUS:
                raise _RetryableFoundryError(
                    f"Foundry agent request failed with HTTP {exc.code}: {detail}"
                ) from exc
            raise FoundryAgentError(
                f"Foundry agent request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except TimeoutError as exc:
            raise _RetryableFoundryError(
                "Foundry agent request exceeded its time budget"
            ) from exc
        except urllib.error.URLError as exc:
            raise _RetryableFoundryError("Foundry agent endpoint is unreachable") from exc
        try:
            parsed = json.loads(body or "{}")
        except json.JSONDecodeError as exc:
            raise FoundryAgentError("Foundry agent returned a malformed response") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        versioned: bool = True,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.project_endpoint}{path}"
        if versioned:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}api-version={self.api_version}"

        # Short-circuit before doing any network I/O when the breaker is
        # open, so an ongoing Foundry outage costs one dict lookup instead of
        # a full timeout per concurrent request.
        self._breaker.before_call()

        attempt = 0
        deadline = (
            time.monotonic() + max(0.0, timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        while True:
            try:
                if deadline is None:
                    result = self._post_once(url, payload)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _RetryableFoundryError(
                            "Foundry agent request exceeded its time budget"
                        )
                    result = self._post_once(
                        url,
                        payload,
                        timeout_seconds=remaining,
                    )
            except _RetryableFoundryError as exc:
                attempt += 1
                if attempt > self.max_retries:
                    self._breaker.record_failure()
                    raise FoundryAgentError(str(exc)) from exc
                backoff = self.retry_backoff_seconds * (2 ** (attempt - 1))
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._breaker.record_failure()
                        raise FoundryAgentError(
                            "Foundry agent request exceeded its time budget"
                        ) from exc
                    backoff = min(backoff, remaining)
                self._sleep(backoff)
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

    def answer(
        self,
        *,
        question: str,
        context: Any,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentAnswer:
        """Narrate ``context`` in response to ``question``.

        The retrieved context is passed as JSON in the user turn rather than
        being appended to the agent's instructions, so the agent's governed
        system prompt (created at deploy time) cannot be overridden by anything
        that came out of the knowledge layer.
        """
        prompt = self.build_prompt(question, context)
        payload = {
            "agent_reference": {"type": "agent_reference", "name": self.agent_name},
            "input": [{"role": "user", "content": prompt}],
        }
        if self.agent_version:
            payload["agent_reference"]["version"] = self.agent_version
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max(1, int(max_output_tokens))
        if timeout_seconds is None:
            response = self._post("/openai/v1/responses", payload, versioned=False)
        else:
            budget = max(0.001, timeout_seconds)
            future = _FOUNDRY_CALL_EXECUTOR.submit(
                self._post,
                "/openai/v1/responses",
                payload,
                versioned=False,
                timeout_seconds=budget,
            )
            try:
                response = future.result(timeout=budget)
            except FutureTimeoutError as exc:
                future.cancel()
                raise FoundryAgentError(
                    "Foundry agent request exceeded its time budget"
                ) from exc
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
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentAnswer:
        """Request and strictly validate a specialist finding response."""
        answer = self.answer(
            question=question,
            context=context,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        # Parsing enforces strict validation as a side effect; the parsed
        # findings themselves are not needed by this contract check.
        parse_specialist_findings(
            answer.text,
            evidence_refs=evidence_refs,
            resource_ids=resource_ids,
            agent_id=self.specialist_id,
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


class MicrosoftAgentFrameworkFoundryAgent:
    """Invokes a Foundry hosted/prompt agent through Microsoft Agent Framework."""

    def __init__(
        self,
        *,
        project_endpoint: str,
        agent_name: str,
        agent_version: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        specialist_id: str = "network",
        agent_factory: Callable[..., Any] | None = None,
    ) -> None:
        endpoint = str(project_endpoint or "").strip().rstrip("/")
        name = str(agent_name or "").strip()
        if not endpoint or not name:
            raise FoundryAgentNotConfigured(
                "A Foundry project endpoint and agent name are both required"
            )
        self.project_endpoint = endpoint
        self.agent_name = name
        self.agent_version = agent_version
        self.timeout_seconds = timeout_seconds
        self.specialist_id = specialist_id
        self._agent_factory = agent_factory
        self._agent: Any | None = None

    @classmethod
    def from_env(
        cls,
        specialist_id: str | None = None,
        *,
        agent_factory: Callable[..., Any] | None = None,
    ) -> MicrosoftAgentFrameworkFoundryAgent | None:
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
        agent_version = (
            os.environ.get(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "").strip()
            if specialist
            else os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
        )
        if _version_pinning_required() and not agent_version:
            return None
        try:
            timeout = float(os.environ.get(ENV_TIMEOUT, "") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        return cls(
            project_endpoint=endpoint,
            agent_name=agent_name,
            agent_version=agent_version,
            timeout_seconds=timeout,
            specialist_id=specialist or "operations_copilot",
            agent_factory=agent_factory,
        )

    def _build_sdk_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        if self._agent_factory is not None:
            self._agent = self._agent_factory(
                project_endpoint=self.project_endpoint,
                agent_name=self.agent_name,
                agent_version=self.agent_version or None,
                allow_preview=True,
                timeout=self.timeout_seconds,
            )
            return self._agent
        try:
            from agent_framework.foundry import FoundryAgent as SdkFoundryAgent
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise FoundryAgentError(
                "Microsoft Agent Framework Foundry runtime is not installed"
            ) from exc
        self._agent = SdkFoundryAgent(
            project_endpoint=self.project_endpoint,
            agent_name=self.agent_name,
            agent_version=self.agent_version or None,
            credential=DefaultAzureCredential(),
            allow_preview=True,
            timeout=self.timeout_seconds,
        )
        return self._agent

    def validate_access(self) -> None:
        self._build_sdk_agent()

    async def _run_agent(self, prompt: str, *, max_output_tokens: int | None = None) -> Any:
        sdk_agent = self._build_sdk_agent()
        if max_output_tokens is None:
            return await sdk_agent.run(prompt)
        try:
            return await sdk_agent.run(prompt, max_output_tokens=max(1, int(max_output_tokens)))
        except TypeError:
            # Older Agent Framework runtime without max_output_tokens support.
            return await sdk_agent.run(prompt)

    def answer(
        self,
        *,
        question: str,
        context: Any,
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentAnswer:
        prompt = self.build_prompt(question, context)
        try:
            awaitable = self._run_agent(
                prompt,
                max_output_tokens=max_output_tokens,
            )
            if timeout_seconds is not None:
                awaitable = asyncio.wait_for(
                    awaitable,
                    timeout=min(
                        self.timeout_seconds,
                        max(0.001, timeout_seconds),
                    ),
                )
            response = _run_awaitable(awaitable)
        except Exception as exc:
            raise FoundryAgentError(
                "Microsoft Agent Framework Foundry agent request failed"
            ) from exc
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise FoundryAgentError("Microsoft Agent Framework agent returned an empty answer")
        return AgentAnswer(
            text=text,
            agent_name=self.agent_name,
            model="microsoft-agent-framework",
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
        max_output_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> AgentAnswer:
        answer = self.answer(
            question=question,
            context=context,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
        parse_specialist_findings(
            answer.text,
            evidence_refs=evidence_refs,
            resource_ids=resource_ids,
            agent_id=self.specialist_id,
        )
        return answer

    def build_prompt(self, question: str, context: Any) -> str:
        return _build_prompt(
            question=question,
            context=context,
            specialist_id=self.specialist_id,
        )


def select_foundry_agent_class(
    specialist_id: str | None = None,
    *,
    prefer_maf: bool,
    rest_agent_class: type[FoundryPromptAgent] = FoundryPromptAgent,
    maf_agent_class: type[MicrosoftAgentFrameworkFoundryAgent] = (
        MicrosoftAgentFrameworkFoundryAgent
    ),
) -> type[FoundryPromptAgent | MicrosoftAgentFrameworkFoundryAgent]:
    """Select a runtime that can enforce the configured immutable version.

    The preview Agent Framework path does not provide a stable wire-level
    guarantee that the configured provider version is sent on every request.
    Once Terraform activates an exact provider ID, use the REST client whose
    outbound ``agent_reference`` includes that ID. Executive synthesis also
    uses the REST path because it requires the strict response contract and
    bounded timeout supported by the Foundry responses endpoint. Unversioned
    legacy callers may continue using the preview path while it remains enabled.
    """

    specialist = (specialist_id or "").strip().casefold()
    if specialist == EXECUTIVE_SPECIALIST_ID:
        return rest_agent_class
    version = (
        os.environ.get(f"FOUNDRY_{specialist.upper()}_AGENT_VERSION", "").strip()
        if specialist
        else os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
    )
    if version:
        return rest_agent_class
    return maf_agent_class if prefer_maf else rest_agent_class


def _run_awaitable(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _compact_oversized_context_value(value: Any) -> Any:
    """Retain summary fields when one nested value cannot fit the prompt."""

    if isinstance(value, Mapping):
        return {
            str(key): _compact_oversized_context_value(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        if not value:
            return []
        compacted = [_compact_oversized_context_value(value[0])]
        if len(value) > 1:
            compacted.append(
                {"_truncation": f"{len(value) - 1} additional items omitted"}
            )
        return compacted
    if isinstance(value, str) and len(value) > 512:
        return f"{value[:496]}…(truncated)"
    return value


def _serialize_bounded_context(context: Any) -> str:
    """Serialize context as valid JSON without slicing through its structure."""

    serialized = json.dumps(context, default=str, ensure_ascii=False)
    if len(serialized) <= MAX_CONTEXT_CHARS:
        return serialized
    if not isinstance(context, Mapping):
        return json.dumps({"truncated": True}, ensure_ascii=False)

    bounded: dict[str, Any] = {"_truncation": "(truncated)"}
    for raw_key, value in context.items():
        key = str(raw_key)
        if isinstance(value, list):
            candidate = {**bounded, key: []}
            if len(
                json.dumps(candidate, default=str, ensure_ascii=False)
            ) > MAX_CONTEXT_CHARS:
                break
            bounded = candidate
            for item in value:
                candidate = deepcopy(bounded)
                candidate[key].append(item)
                candidate_serialized = json.dumps(
                    candidate,
                    default=str,
                    ensure_ascii=False,
                )
                if len(candidate_serialized) > MAX_CONTEXT_CHARS:
                    compacted_item = _compact_oversized_context_value(item)
                    candidate = deepcopy(bounded)
                    candidate[key].append(compacted_item)
                    candidate_serialized = json.dumps(
                        candidate,
                        default=str,
                        ensure_ascii=False,
                    )
                    if len(candidate_serialized) <= MAX_CONTEXT_CHARS:
                        bounded = candidate
                    continue
                bounded = candidate
            continue
        candidate = {**bounded, key: value}
        candidate_serialized = json.dumps(
            candidate,
            default=str,
            ensure_ascii=False,
        )
        if len(candidate_serialized) <= MAX_CONTEXT_CHARS:
            bounded = candidate
        else:
            break
    return json.dumps(bounded, default=str, ensure_ascii=False)


def _json_object_from_answer(text: str) -> dict[str, Any]:
    """Parse one strict JSON object from a coordinator response."""

    candidate = str(text or "").strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
            if candidate.casefold().startswith("json\n"):
                candidate = candidate[5:].strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise FoundryAgentError(
            "Operations Copilot coordinator returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise FoundryAgentError(
            "Operations Copilot coordinator must return one JSON object"
        )
    return payload


def _normalize_coordinator_findings(text: str) -> str:
    """Normalize benign model type drift before strict citation validation."""

    payload = _json_object_from_answer(text)
    rows = payload.get("findings")
    if not isinstance(rows, list):
        raise FoundryAgentError(
            "Operations Copilot coordinator synthesis omitted findings"
        )
    required = _SPECIALIST_MANIFEST.output_contracts()[
        EXECUTIVE_SPECIALIST_ID
    ]["required"]
    findings: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise FoundryAgentError(
                "Operations Copilot coordinator finding is not an object"
            )
        normalized = {key: row.get(key) for key in required}
        evidence_refs = normalized.get("evidence_refs")
        if isinstance(evidence_refs, str):
            normalized["evidence_refs"] = [evidence_refs]
        uncertainty = normalized.get("uncertainty")
        if isinstance(uncertainty, str):
            normalized["uncertainty"] = (
                [uncertainty.strip()] if uncertainty.strip() else []
            )
        elif uncertainty is None:
            normalized["uncertainty"] = []
        normalized["actionable"] = (
            normalized.get("actionable")
            if isinstance(normalized.get("actionable"), bool)
            else False
        )
        for key in ("confidence", "freshness"):
            if isinstance(normalized.get(key), str):
                normalized[key] = normalized[key].strip().casefold()
        if normalized.get("freshness") == "current":
            normalized["freshness"] = "unknown"
        findings.append(normalized)
    return json.dumps({"findings": findings}, ensure_ascii=False)


def is_highest_risk_compliance_question(
    page_kind: str,
    question: str,
) -> bool:
    """Return whether a turn requires retained Compliance risk coverage."""

    normalized = " ".join(question.casefold().replace("-", " ").split())
    return (
        page_kind == "compliance"
        and "highest risk" in normalized
        and "compliance" in normalized
    )


class FoundryCoordinatorPlanner:
    """Ask Operations Copilot for an untrusted typed delegation candidate."""

    def __init__(
        self,
        agent: Any,
        *,
        required_hint: Mapping[str, Any] | None = None,
    ) -> None:
        self.agent = agent
        self.required_hint = dict(required_hint or {})
        self.manifest = load_specialist_manifest()

    def _required_specialists(
        self,
        request: InvestigationRequest,
    ) -> tuple[str, ...]:
        if (
            not self.required_hint
            and is_highest_risk_compliance_question(
                request.snapshot.page_kind,
                request.question,
            )
        ):
            return ("vulnerability", "governance")
        return ()

    def __call__(self, request: InvestigationRequest) -> CandidatePlan:
        page_kind = request.snapshot.page_kind
        page_mapping = self.manifest.page_mapping_projection()
        tool_schemas = {
            definition["name"]: definition["inputSchema"]
            for definition in tool_definitions()
        }
        allowed_specialists = {}
        for specialist_id in reviewed_specialists_for_page(
            page_kind,
            page_mapping,
        ):
            specialist = self.manifest.require(specialist_id)
            allowed_specialists[specialist_id] = list(
                specialist.operations_tools_for_page(page_kind)
            )
        required_specialists = self._required_specialists(request)
        context = {
            "contract": {
                "steps": [{
                    "specialist_id": "allowed specialist id",
                    "tool_calls": [{
                        "tool": "allowed tool",
                        "arguments": {},
                        "citation_ids": ["allowed citation id"],
                        "mutation": False,
                    }],
                    "depends_on": [],
                }],
                "estimated_tokens": 0,
                "max_wall_seconds": 30,
                "mutation_intent": False,
            },
            "page_kind": page_kind,
            "page_id": request.snapshot.page_id,
            "allowed_policy_domains_and_local_tools": allowed_specialists,
            "allowed_tool_argument_schemas": {
                tool: tool_schemas[tool]
                for tools in allowed_specialists.values()
                for tool in tools
            },
            "execution_model": (
                "Operations Copilot proposes policy-domain/tool calls. "
                "Deterministic server policy authorizes them and the API "
                "executes governed local tools; specialist IDs do not claim "
                "that separate Foundry specialist agents ran."
            ),
            "allowed_citation_ids": [
                COVERAGE_CITATION_ID,
                *[item.evidence_id for item in request.snapshot.evidence],
            ],
            "required_hint": self.required_hint or None,
            "required_specialists": list(required_specialists),
            "coverage": request.snapshot.coverage.model_dump(mode="json"),
            "selected_entities": [
                item.model_dump(mode="json")
                for item in request.snapshot.selected_entities
            ],
        }
        planning_question = (
            "Return ONLY one JSON object matching contract. Select the smallest "
            "read-only specialist/tool plan that answers the operator question. "
            "Use only allowed specialist/tool pairs and allowed citation IDs. "
            "Never add mutation. If required_hint is present, include exactly "
            "that specialist, tool, and arguments.\n\n"
            f"OPERATOR QUESTION:\n{request.question}"
        )
        def request_plan(question: str) -> CandidatePlan:
            answer = self.agent.answer(
                question=question,
                context=context,
                max_output_tokens=2_000,
            )
            try:
                return CandidatePlan.model_validate(
                    _json_object_from_answer(getattr(answer, "text", ""))
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise FoundryAgentError(
                    "Operations Copilot coordinator returned an invalid candidate plan"
                ) from exc

        plan = request_plan(planning_question)
        plan = plan.model_copy(
            update={
                "steps": [
                    step.model_copy(
                        update={
                            "tool_calls": [
                                call.model_copy(update={"arguments": {}})
                                if not tool_schemas.get(call.tool, {}).get(
                                    "properties"
                                )
                                else call
                                for call in step.tool_calls
                            ]
                        }
                    )
                    for step in plan.steps
                ]
            }
        )
        selected = {step.specialist_id for step in plan.steps}
        missing = [
            specialist_id
            for specialist_id in required_specialists
            if specialist_id not in selected
        ]
        if missing:
            correction = (
                f"{planning_question}\n\nYour previous candidate was incomplete; "
                f"missing required specialists: {', '.join(missing)}. Return "
                "one corrected complete candidate."
            )
            plan = request_plan(correction)
            selected = {step.specialist_id for step in plan.steps}
            missing = [
                specialist_id
                for specialist_id in required_specialists
                if specialist_id not in selected
            ]
            if missing:
                raise FoundryAgentError(
                    "Operations Copilot coordinator plan is missing required "
                    f"specialists: {', '.join(missing)}"
                )
        if self.required_hint:
            calls = [
                (step.specialist_id, call.tool, dict(call.arguments))
                for step in plan.steps
                for call in step.tool_calls
            ]
            expected = (
                str(self.required_hint.get("specialist_id") or ""),
                str(self.required_hint.get("tool") or ""),
                dict(self.required_hint.get("arguments") or {}),
            )
            if calls != [expected]:
                raise FoundryAgentError(
                    "Operations Copilot coordinator changed the required page hint"
                )
        return plan


class FoundryCoordinatorSynthesisAgent:
    """Use Operations Copilot for citation-closed final answer synthesis."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def answer(
        self,
        *,
        question: str,
        context: Any,
        timeout_seconds: float | None = None,
    ) -> AgentAnswer:
        synthesis_question = (
            "Return ONLY JSON with shape {\"findings\":[...]}. Each finding must "
            "contain exactly finding_id, evidence_refs, confidence, uncertainty, "
            "freshness, actionable, next_check, summary. Answer the operator "
            "question directly, consolidate duplicate findings, and cite only "
            "evidence_refs present in context. In summary, describe the observed "
            "issue and remediation recommended by the cited evidence, for human "
            "review only; never claim a change was performed. Keep next_check "
            "strictly read-only (inspect, verify, or review); it must not instruct "
            "the operator to create, update, delete, modify, execute, apply, or "
            "remediate anything. Use one concise finding per material issue.\n\n"
            f"OPERATOR QUESTION:\n{question}"
        )
        answer = self.agent.answer(
            question=synthesis_question,
            context=context,
            max_output_tokens=3_000,
            timeout_seconds=timeout_seconds,
        )
        try:
            normalized = _normalize_coordinator_findings(answer.text)
        except (FoundryAgentError, TypeError, ValueError) as exc:
            raise FoundryResponseContractError(
                "Executive synthesis failed response normalization"
            ) from exc
        return AgentAnswer(
            text=normalized,
            agent_name=answer.agent_name,
            model=answer.model,
            grounded=answer.grounded,
            agent_version=answer.agent_version,
        )


def _build_prompt(
    *, question: str, context: Any, specialist_id: str = "network"
) -> str:
    """Frame the page context as a starting point, not a ceiling.

    The context is what the operator is currently looking at. It seeds the
    answer but must not bound it: an earlier revision said "using only the
    operational context below", which forbade the agent from calling its own
    governed MCP tools. Entity questions ("what depends on demo-vnet?") are
    then unanswerable whenever the pre-computed context happens to describe a
    different resource, and the run collapses into a findings dump. The tools
    are already scope-bound and allowlisted by APIM, so letting the agent
    reach for them is governed, not unbounded.
    """
    serialized = _serialize_bounded_context(context)
    if specialist_id == "operations_copilot":
        display_name = "Operations Copilot"
        purpose = "Coordinate bounded, cited operational analysis."
        operations_tools = "none (coordinator only)"
        optional_sources = "foundry"
    else:
        specialist = _SPECIALIST_MANIFEST.require(specialist_id)
        display_name = specialist.display_name
        purpose = specialist.purpose
        operations_tools = (
            ", ".join(specialist.operations_mcp_tools) or "none (aggregation only)"
        )
        optional_sources = (
            ", ".join(specialist.knowledge_policy.optional_sources) or "none"
        )
    return (
        f"You are the {display_name} specialist. "
        f"Purpose: {purpose}\n"
        f"Governed Operations MCP tools: {operations_tools}.\n"
        f"Optional enrichment sources: {optional_sources}. When an optional "
        "source is absent, report it as unavailable and continue with cited "
        "deterministic evidence; never invent a successful lookup.\n\n"
        "Answer the operator's "
        "question directly and specifically.\n\n"
        "The operational context below is what the operator currently has on "
        "screen. Treat it as a starting point. When it does not contain the "
        "answer, call your governed tools to retrieve what does - especially "
        "when the question names a resource that is absent from the context. "
        "Ground every claim in the context or in a tool result, and say so "
        "plainly when the answer cannot be established either way. Never "
        "speculate.\n\n"
        "Answer the question that was asked. Do not reply with an inventory "
        "of unrelated findings.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"PAGE CONTEXT (JSON):\n{serialized}"
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
    """Return active and validated-inactive metadata without changing dispatch."""
    endpoint = os.environ.get(ENV_PROJECT_ENDPOINT, "").strip()
    activation_source = (
        os.environ.get("AIOPS_SPECIALIST_ACTIVATION_SOURCE", "").strip()
        or "unconfigured"
    )
    version_pinning_required = _version_pinning_required()
    candidates = validated_candidate_catalog(_SPECIALIST_MANIFEST)
    entries: list[dict[str, Any]] = []
    for specialist in _SPECIALIST_MANIFEST.specialists:
        prefix = f"FOUNDRY_{specialist.id.upper()}_AGENT"
        name = os.environ.get(f"{prefix}_NAME", "").strip()
        version = os.environ.get(f"{prefix}_VERSION", "").strip()
        if not name and specialist.id == "network":
            name = os.environ.get(ENV_AGENT_NAME, "").strip()
            version = version or os.environ.get("FOUNDRY_AGENT_VERSION", "").strip()
        runtime_configured = bool(
            endpoint
            and name
            and (version or not version_pinning_required)
        )
        candidate = candidates.get(specialist.id)
        configured = bool(
            runtime_configured
            and activation_source in {"validated_promotion", "validated_rollback"}
        )
        status = (
            "active"
            if configured
            else "available_inactive"
            if candidate
            else "unavailable"
        )
        degraded_reason = ""
        if status == "available_inactive":
            degraded_reason = (
                "Validated Foundry candidate is available but inactive; "
                "deterministic execution remains selected."
            )
        elif not configured:
            if not endpoint:
                degraded_reason = "Foundry project endpoint is unavailable."
            elif not name:
                degraded_reason = "Foundry specialist name is unavailable."
            elif version_pinning_required and not version:
                degraded_reason = (
                    "Pinned Foundry specialist version is unavailable."
                )
            else:
                degraded_reason = "Foundry specialist activation is unavailable."
        entries.append(
            {
                "id": specialist.id,
                "name": name or specialist.foundry.name,
                "version": version or specialist.foundry.version,
                "model": specialist.foundry.model,
                "status": status,
                "configured": configured,
                "activation_source": activation_source,
                "version_pinning_required": version_pinning_required,
                "degraded_reason": degraded_reason,
                **({"candidate": candidate} if candidate else {}),
            }
        )
    return entries
