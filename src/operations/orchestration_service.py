"""Canonical governed orchestration service for the Inventory tracer."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid
from collections import Counter, OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from api.errors import ApiError
from api.scope import Scope
from operations import maf_orchestrator
from operations.copilot_canary_authorization import CanaryAuthorizationError
from operations.cve_response import (
    canonical_cve_id,
    deterministic_cve_narrative,
)
from operations.foundry_agent import (
    FoundryAgentError,
    FoundryCircuitOpenError,
    FoundryResponseContractError,
    executive_synthesis_input,
    is_highest_risk_compliance_question,
    normalize_cited_findings,
    validate_executive_synthesis,
)

_LOGGER = logging.getLogger(__name__)
from operations.investigation_thread_store import (
    OBSERVATION_CURRENT,
    OBSERVATION_HISTORICAL,
    InvestigationThread,
    InvestigationThreadStore,
    ThreadNotFound,
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
    investigation_thread_store,
    scope_within,
)
from operations.maf_orchestrator import (
    CopilotRolloutDecision,
    build_deterministic_fallback,
    select_specialists_for_turn,
)
from operations.mcp_server import validate_tool_arguments
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    AzureEntityRef,
    CandidatePlan,
    CanonicalEvidenceSnapshot,
    Citation,
    DomainEntityRef,
    EvidenceSnapshotV2,
    InvestigationRequest,
    ObservationRef,
    OrchestrationResult,
    SnapshotCoverage,
    SnapshotEvidence,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import OrchestrationPolicy, PolicyViolation
from operations.page_context import select_browser_evidence_for_retention
from operations.specialist_manifest import (
    PageMapping,
    SpecialistDefinition,
    load_specialist_manifest,
)
from operations.tools import (
    STATUS_DENIED,
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    ToolResult,
    call_tool,
)

Planner = Callable[[InvestigationRequest], CandidatePlan | Mapping[str, Any]]
Executor = Callable[..., ToolResult]
_MAX_LEGACY_SESSIONS = 2_000
_legacy_session_lock = threading.Lock()
_legacy_session_threads: OrderedDict[tuple[str, str], str] = OrderedDict()
_STABLE_QUESTION_ROUTES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "incident",
        "incident",
        (
            r"\bincident(?:s)?\b",
            r"\boutage(?:s)?\b",
            r"\balert(?:s)?\b",
            r"\broot cause\b",
            r"\btimeline\b",
        ),
    ),
    (
        "vulnerability",
        "vulnerability",
        (
            r"\bcve(?:s)?\b",
            r"\bvulnerab\w*\b",
            r"\bexploit\w*\b",
            r"\bexposure\b",
            r"\battack path\b",
        ),
    ),
    (
        "governance",
        "governance",
        (
            r"\bowner(?:s|ship)?\b",
            r"\bgovernance\b",
            r"\bapprov\w*\b",
            r"\bpolicy\b",
            r"\bcompliance\b",
        ),
    ),
    (
        "network",
        "network",
        (
            r"\bnetwork\b",
            r"\btraffic\b",
            r"\bfirewall\b",
            r"\bnsg\b",
            r"\broute(?:s|d|ing)?\b",
            r"\breach(?:able|ability)?\b",
            r"\btopology\b",
        ),
    ),
)


class PlannerUnavailableError(RuntimeError):
    """The configured planner adapter cannot currently produce a proposal."""


class PlannerTimeoutError(TimeoutError):
    """The configured planner adapter exceeded its bounded response time."""


def _caused_by_timeout(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, TimeoutError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _default_executor(
    name: str,
    arguments: Mapping[str, Any],
    *,
    context: Any,
    scope: Scope,
) -> ToolResult:
    return call_tool(name, arguments, context=context, scope=scope)


def _fallback_candidate(request: InvestigationRequest) -> CandidatePlan:
    """Construct a keyword-selected deterministic fallback.

    Delegates to ``build_deterministic_fallback`` so the same keyword
    selection and page-constraint logic produces a candidate that passes
    the identical policy validator applied to model-proposed plans.
    """
    return build_deterministic_fallback(request, load_specialist_manifest())


def _preferred_page_kind(specialist: SpecialistDefinition) -> PageMapping:
    """Return the stable primary page mapping for a selected specialist."""

    return specialist.page_mappings[0]


_FABRIC_CLAIM_SOURCES = {
    "medallion_layer": "fabric/medallion-layers",
    "fabric_manifest": "fabric/manifest",
    "fabric_governance": "fabric/governance",
    "fabric_capacity": "fabric/capabilities",
}

_INVENTORY_PAGE_CONTRACT = {
    "inventory:os": (
        "os",
        "inventory/os_observations",
        "os_group",
    ),
    "inventory:software": (
        "software",
        "inventory/software_observations",
        "software_group",
    ),
    "inventory:azure": (
        "paas",
        "inventory/resource_observations",
        "azure_group",
    ),
}


def inventory_starter_kind(question: str) -> str | None:
    normalized = " ".join(question.casefold().split()).rstrip("?.! ")
    if normalized == "review visible inventory health":
        return "health"
    if normalized == "where is inventory coverage incomplete":
        return "coverage"
    return None


def _nonnegative_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def valid_inventory_page_snapshot(snapshot: EvidenceSnapshotV2) -> bool:
    """Validate the exact bounded Inventory page-observation contract."""

    contract = _INVENTORY_PAGE_CONTRACT.get(snapshot.page_id)
    if snapshot.page_kind != "inventory" or contract is None:
        return False
    family, source, claim_type = contract
    if (
        snapshot.coverage.visible_count == 0
    ):
        if len(snapshot.evidence) != 1:
            return False
        item = snapshot.evidence[0]
        context = item.data.get("inventory_context")
        return (
            item.source == source
            and item.claim_type == "page_context"
            and item.status == STATUS_EMPTY
            and isinstance(item.entity, ObservationRef)
            and item.entity.source == source
            and item.entity.source_key == item.source_key
            and item.source_key == (
                f"page-context:{'azure' if family == 'paas' else family}"
            )
            and isinstance(context, Mapping)
            and context.get("tab") == (
                "azure" if family == "paas" else family
            )
            and item.data.get("selected") is False
            and item.data.get("mutation_authorized") is False
            and not item.direct
            and not item.actionable
        )
    if (
        len(snapshot.evidence) > 50
        or len(snapshot.evidence) != snapshot.coverage.visible_count
        or snapshot.coverage.visible_count > snapshot.coverage.total_count
    ):
        return False
    identities: set[str] = set()
    expected_kind = {
        "os": "os_group",
        "software": "software_group",
        "paas": "azure_group",
    }[family]
    for item in snapshot.evidence:
        data = item.data
        context = data.get("inventory_context")
        identity = item.source_key.casefold()
        if (
            item.source != source
            or item.claim_type != claim_type
            or item.status not in {"ok", "partial"}
            or not item.direct
            or item.actionable
            or not item.observed_at
            or not identity
            or identity in identities
            or not isinstance(item.entity, DomainEntityRef)
            or item.entity.namespace != "inventory"
            or item.entity.kind != expected_kind
            or item.entity.source_key != item.source_key
            or not isinstance(context, Mapping)
            or context.get("tab") != (
                "azure" if family == "paas" else family
            )
            or not isinstance(data.get("selected"), bool)
            or data.get("mutation_authorized") is not False
        ):
            return False
        identities.add(identity)

        if family == "os":
            os_name = str(data.get("os_name") or "").strip()
            os_version = str(data.get("os_version") or "").strip()
            days_remaining = data.get("days_remaining")
            if (
                not os_name
                or not os_version
                or item.source_key != f"{os_name}|{os_version}"
                or not _nonnegative_int(data.get("machine_count"))
                or not isinstance(data.get("source_types"), list)
                or not data["source_types"]
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in data["source_types"]
                )
                or len(data["source_types"]) != len(set(data["source_types"]))
                or not str(data.get("lifecycle_status") or "").strip()
                or not (
                    days_remaining is None
                    or (
                        isinstance(days_remaining, int)
                        and not isinstance(days_remaining, bool)
                    )
                )
                or not isinstance(data.get("review_required"), bool)
            ):
                return False
        elif family == "software":
            name = str(data.get("software_name") or "").strip()
            version = str(data.get("software_version") or "").strip()
            counts = (
                data.get("install_count"),
                data.get("linked_count"),
                data.get("unlinked_count"),
            )
            if (
                not name
                or not version
                or item.source_key != f"{name}|{version}"
                or not all(_nonnegative_int(value) for value in counts)
                or counts[1] + counts[2] != counts[0]
            ):
                return False
        else:
            resource_type = str(data.get("resource_type") or "").strip()
            sku = str(data.get("sku") or "")
            tier = str(data.get("tier") or "")
            expected_key = "|".join(
                (
                    resource_type.replace("/", ":"),
                    sku or "Unknown",
                    tier or "Unknown",
                )
            )
            if (
                not resource_type
                or item.source_key != expected_key
                or not _nonnegative_int(data.get("resource_count"))
            ):
                return False
    return True


def _inventory_page_authority(
    snapshot: EvidenceSnapshotV2,
    tool_results: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    contract = _INVENTORY_PAGE_CONTRACT.get(snapshot.page_id)
    if not valid_inventory_page_snapshot(snapshot) or contract is None:
        return None
    family = contract[0]
    matching = [
        result
        for result in tool_results
        if (
            result.get("specialist_id") == "inventory_data_health"
            and result.get("tool") == "inventory_resources"
            and isinstance(result.get("arguments"), Mapping)
            and result["arguments"].get("family") == family
            and result.get("status") in {STATUS_OK, STATUS_EMPTY}
            and isinstance(result.get("data"), Mapping)
        )
    ]
    if len(matching) != 1:
        return None
    data = matching[0]["data"]
    total = data.get("total")
    group_total = data.get("group_total")
    groups = data.get("groups")
    observed_at = str(data.get("observed_at") or "")
    query_version = str(data.get("query_version") or "")
    if (
        not _nonnegative_int(total)
        or not _nonnegative_int(group_total)
        or not isinstance(groups, list)
        or group_total != snapshot.coverage.total_count
        or not observed_at
        or not query_version
        or any(item.observed_at != observed_at for item in snapshot.evidence)
    ):
        return None

    by_key = {
        str(group.get("key") or ""): group
        for group in groups
        if isinstance(group, Mapping) and group.get("key")
    }
    if len(by_key) != len(groups):
        return None
    if snapshot.coverage.visible_count == 0:
        return data
    fields = (
        (
            "os_name",
            "os_version",
            "machine_count",
            "source_types",
            "lifecycle_status",
            "support_end",
            "days_remaining",
            "review_required",
        )
        if family == "os"
        else (
                "software_name",
                "software_version",
                "install_count",
                "linked_count",
                "unlinked_count",
                "source_types",
                "publishers",
        )
        if family == "software"
        else ("resource_type", "sku", "tier", "resource_count")
    )
    for item in snapshot.evidence:
        group = by_key.get(item.source_key)
        if group is None:
            return None
        for key in fields:
            if group.get(key) != item.data.get(key):
                return None

    resources = data.get("resources")
    if family == "software" and resources is None:
        resources = []
    if not isinstance(resources, list):
        return None
    resource_ids: set[str] = set()
    for resource in resources:
        if not isinstance(resource, Mapping):
            return None
        resource_id = str(resource.get("resource_id") or "").casefold()
        if (
            not resource_id
            or resource_id in resource_ids
            or resource.get("family") != family
        ):
            return None
        resource_ids.add(resource_id)
    if len(resources) > total:
        return None
    return data


def _valid_fabric_observation(item: SnapshotEvidence) -> bool:
    source = _FABRIC_CLAIM_SOURCES.get(item.claim_type)
    if (
        source is None
        or item.status not in {"ok", "partial"}
        or item.source != source
        or not isinstance(item.entity, ObservationRef)
        or item.entity.source != source
        or item.entity.source_key != item.source_key
    ):
        return False
    data = item.data
    if item.claim_type == "medallion_layer":
        layer = str(data.get("layer") or "").casefold()
        healthy = data.get("healthy")
        total = data.get("total")
        return (
            layer in {"bronze", "silver", "gold"}
            and item.source_key == layer
            and isinstance(healthy, int)
            and not isinstance(healthy, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
            and 0 <= healthy <= total
        )
    if item.claim_type == "fabric_manifest":
        return item.source_key == str(data.get("projection_name") or "")
    if item.claim_type == "fabric_governance":
        values = (
            data.get("ownership_gap_count"),
            data.get("tag_gap_count"),
            data.get("referential_integrity_blockers"),
        )
        return item.source_key == "fabric-governance" and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for value in values
        )
    return item.source_key == "fabric-capacity"


def _fabric_starter_kind(question: str) -> str | None:
    normalized = " ".join(question.casefold().split()).rstrip("?.! ")
    if normalized == "how healthy are the bronze, silver, and gold layers":
        return "layers"
    if normalized == "which datasets have governance or lineage gaps":
        return "gaps"
    return None


def _resource_health_starter_kind(question: str) -> str | None:
    if question == "What incidents relate to these resources?":
        return "incidents"
    if question == "Which services are impacted by resource pressure?":
        return "services"
    if question == "Search resource utilization anomalies.":
        return "anomalies"
    return None


def _valid_resource_health_observation(item: SnapshotEvidence) -> bool:
    data = item.data
    cpu_percent = data.get("cpu_percent")
    if not (
        cpu_percent is None
        or (
            isinstance(cpu_percent, (int, float))
            and not isinstance(cpu_percent, bool)
            and math.isfinite(cpu_percent)
            and 0 <= cpu_percent <= 100
        )
    ):
        return False
    expected_status = (
        "unknown"
        if cpu_percent is None
        else "critical"
        if cpu_percent >= 90
        else "warning"
        if cpu_percent >= 70
        else "healthy"
    )
    return (
        item.claim_type == "resource_utilization"
        and item.status in {"ok", "partial"}
        and item.source == "resource-health/metrics"
        and isinstance(item.entity, AzureEntityRef)
        and item.entity.resource_id == item.resource_id
        and item.source_key.casefold() == item.resource_id.casefold()
        and item.direct
        and item.observed_at != ""
        and str(data.get("resource_name") or "").strip() != ""
        and str(data.get("resource_type") or "").strip() != ""
        and str(data.get("status") or "").casefold() == expected_status
        and data.get("actionable") is False
        and data.get("mutation_authorized") is False
        and all(
            value is None
            or (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 <= value <= 100
            )
            for value in (
                cpu_percent,
                data.get("memory_percent"),
                data.get("disk_free_percent"),
            )
        )
        and isinstance(data.get("series_point_count"), int)
        and not isinstance(data.get("series_point_count"), bool)
        and data["series_point_count"] >= 0
        and isinstance(data.get("unavailable_metrics"), list)
        and all(
            isinstance(value, str)
            for value in data["unavailable_metrics"]
        )
    )


def _question_route(
    question: str,
    *,
    hint_tool: str,
) -> tuple[PageMapping, SpecialistDefinition | None]:
    """Resolve a question or tool hint to one manifest-backed page identity."""

    manifest = load_specialist_manifest()
    if hint_tool:
        for specialist in manifest.specialists:
            if hint_tool in specialist.operations_mcp_tools:
                return _preferred_page_kind(specialist), specialist

    lowered = question.casefold()
    for page_kind, specialist_id, patterns in _STABLE_QUESTION_ROUTES:
        if any(re.search(pattern, lowered) for pattern in patterns):
            return page_kind, manifest.require(specialist_id)

    catalog = tuple(
        type(
            "_CatalogEntry",
            (),
            {"id": specialist.id, "keywords": specialist.intent_examples},
        )()
        for specialist in manifest.specialists
    )
    dedicated_page = "__dedicated_question__"
    decision = select_specialists_for_turn(
        page_kind=dedicated_page,
        question=question,
        page_specialists={
            dedicated_page: tuple(
                specialist.id
                for specialist in manifest.specialists
                if specialist.id != "executive_summary"
                and specialist.operations_mcp_tools
            )
        },
        catalog=catalog,
        limit=1,
    )
    if decision.selected_ids and decision.strategy != "page_fallback":
        specialist = manifest.require(decision.selected_ids[0])
        return _preferred_page_kind(specialist), specialist
    return "copilot", None


def _legacy_session_thread(
    session_id: str,
    principal_subject: str,
) -> str | None:
    if not session_id:
        return None
    key = (principal_subject, session_id)
    with _legacy_session_lock:
        store = investigation_thread_store()
        thread_id = (
            store.resolve_legacy_binding(
                session_id,
                principal_subject,
            )
            if store.is_durable
            else _legacy_session_threads.get(key)
        )
        if thread_id is not None:
            _legacy_session_threads[key] = thread_id
        if thread_id is not None:
            _legacy_session_threads.move_to_end(key)
        return thread_id


def _legacy_session_thread_for_execution(
    session_id: str,
    principal_subject: str,
    scope: Scope,
) -> str | None:
    """Atomically bind a first legacy turn to one canonical thread."""

    if not session_id:
        return None
    key = (principal_subject, session_id)
    with _legacy_session_lock:
        store = investigation_thread_store()
        thread_id = (
            store.resolve_legacy_binding(session_id, principal_subject)
            if store.is_durable
            else _legacy_session_threads.get(key)
        )
        if thread_id is None:
            thread_id = _adopt_or_create_thread(
                session_id,
                principal_subject,
                scope,
            )
            thread_id = store.bind_legacy_session(
                session_id,
                principal_subject,
                thread_id,
            )
            _legacy_session_threads[key] = thread_id
            while len(_legacy_session_threads) > _MAX_LEGACY_SESSIONS:
                _legacy_session_threads.popitem(last=False)
        else:
            _legacy_session_threads.move_to_end(key)
        return thread_id


def _adopt_or_create_thread(
    session_id: str,
    principal_subject: str,
    scope: Scope,
) -> str:
    """Adopt an active legacy conversation, or start an empty thread.

    The import is opportunistic: an operator who is mid-conversation when the
    canonical path takes over keeps their context instead of silently starting
    over. The legacy store is only read -- its turns are copied and stamped
    historical -- so old records stay byte-for-byte as they were written.
    """

    try:
        from operations.investigation import conversation_store

        legacy_turns = conversation_store().history(session_id, principal_subject)
    except Exception:  # noqa: BLE001 - continuity import is never load-bearing.
        legacy_turns = []
    if legacy_turns:
        imported = investigation_thread_store().import_legacy_turns(
            principal_subject,
            scope,
            legacy_turns,
        )
        if imported is not None:
            return imported.thread_id
    return investigation_thread_store().create(principal_subject, scope).thread_id


def _remember_legacy_session_thread(
    session_id: str,
    principal_subject: str,
    thread_id: str,
) -> None:
    if not session_id:
        return
    key = (principal_subject, session_id)
    with _legacy_session_lock:
        thread_id = investigation_thread_store().bind_legacy_session(
            session_id,
            principal_subject,
            thread_id,
        )
        _legacy_session_threads[key] = thread_id
        _legacy_session_threads.move_to_end(key)
        while len(_legacy_session_threads) > _MAX_LEGACY_SESSIONS:
            _legacy_session_threads.popitem(last=False)


def _forget_legacy_session_thread(
    session_id: str,
    principal_subject: str,
) -> None:
    if not session_id:
        return
    investigation_thread_store().forget_legacy_binding(
        session_id,
        principal_subject,
    )
    with _legacy_session_lock:
        _legacy_session_threads.pop((principal_subject, session_id), None)


_EXECUTIVE_INTENT_PATTERNS: tuple[str, ...] = (
    r"\bexecutive\b",
    r"\bexec summary\b",
    r"\bleadership\b",
    r"\bbrief(?:ing)?\s+(?:for|the)\b",
    r"\bboard\b",
    r"\bcross[- ]domain\b",
    r"\boverall (?:posture|picture|risk)\b",
)


@dataclass(frozen=True)
class SynthesisDecision:
    """Deterministic admission verdict for one turn."""

    admitted: bool
    reason: str
    domain_count: int


@dataclass(frozen=True)
class ExecutiveSynthesis:
    """What conditional synthesis produced, including why it did not run."""

    status: str
    reason: str
    domain_count: int
    claims: list[dict[str, Any]] = field(default_factory=list)
    warning: str = ""
    used_retained_evidence: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "deterministic"
    narration: str = ""
    agent: str = ""
    #: Controlled-vocabulary reason the narrator did not answer, distinct
    #: from ``reason`` (the admission decision). Populated only on the
    #: narration-provider-related degrade paths so operators can tell a
    #: local wall-clock budget cutoff apart from a genuine Foundry timeout,
    #: an unreachable/errored provider, or a malformed response -- without
    #: reading free-text ``warning`` strings. Empty when narration was not
    #: attempted for an unrelated reason (e.g. admission was declined) or
    #: when it succeeded.
    degraded_reason: str = ""
    #: Wall-clock seconds the narrator was actually given for this call
    #: (0.0 when narration was skipped before ever being attempted). Lets
    #: operators see whether a timeout was caused by an exhausted local
    #: budget (small value) versus the provider itself being slow despite
    #: a full budget.
    narration_budget_seconds: float = 0.0
    provider_error_class: str = ""
    provider_error_reason: str = ""


@dataclass(frozen=True)
class OrchestrationTurn:
    """One canonical result plus the synthesis outcome that accompanied it."""

    result: OrchestrationResult
    synthesis: ExecutiveSynthesis


def _executive_synthesis_payload(
    synthesis: ExecutiveSynthesis,
) -> dict[str, Any]:
    """Project executive synthesis diagnostics into the API response."""

    return {
        "status": synthesis.status,
        "reason": synthesis.reason,
        "domain_count": synthesis.domain_count,
        "claims": synthesis.claims,
        "warning": synthesis.warning,
        "mode": synthesis.mode,
        "narration": synthesis.narration,
        "agent": synthesis.agent,
        "degraded_reason": synthesis.degraded_reason,
        "narration_budget_seconds": synthesis.narration_budget_seconds,
        "provider_error_class": synthesis.provider_error_class,
        "provider_error_reason": synthesis.provider_error_reason,
        "used_retained_evidence": synthesis.used_retained_evidence,
    }


def _narration_fallback_warning(
    *,
    narrator_state: str,
    fallback_detail: str,
    specialist_provider_unavailable: bool,
) -> str:
    if narrator_state == "timeout":
        return f"Foundry narration timed out; {fallback_detail}."
    if narrator_state == "unavailable":
        return f"Foundry narration provider is unavailable; {fallback_detail}."
    if specialist_provider_unavailable:
        return (
            "Foundry narration is not configured; one or more specialist "
            f"providers are unavailable; {fallback_detail}."
        )
    return f"Foundry narration is not configured; {fallback_detail}."


def _narration_failure_details(exc: BaseException) -> tuple[str, str]:
    """Classify a provider failure without retaining uncontrolled text."""

    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 8:
        chain.append(current)
        current = current.__cause__
    if any(isinstance(item, FoundryResponseContractError) for item in chain):
        return "contract_error", "response_contract"
    if any(isinstance(item, FoundryCircuitOpenError) for item in chain):
        return "foundry_circuit_open", "circuit_open"
    if any(isinstance(item, TimeoutError) for item in chain):
        return "timeout_error", "timeout"
    for item in chain:
        status = getattr(item, "code", None)
        if status in {401, 403}:
            return "http_error", "authorization"
        if status == 429:
            return "http_error", "rate_limited"
        if isinstance(status, int) and status >= 500:
            return "http_error", "provider_service"
        if isinstance(status, int) and status >= 400:
            return "http_error", "request_rejected"
    class_names = {type(item).__name__ for item in chain}
    if class_names & {"ClientAuthenticationError", "CredentialUnavailableError"}:
        return "credential_error", "identity"
    if any(isinstance(item, ConnectionError) for item in chain):
        return "connection_error", "connectivity"
    if class_names & {"JSONDecodeError", "ValidationError"}:
        return "contract_error", "response_contract"
    if isinstance(exc, FoundryAgentError):
        return "foundry_agent_error", "provider_error"
    if isinstance(exc, AttributeError):
        return "attribute_error", "response_state"
    if isinstance(exc, TypeError):
        return "type_error", "response_contract"
    if isinstance(exc, ValueError):
        return "value_error", "response_contract"
    return "other", "provider_error"


def _log_narration_failure(
    exc: BaseException,
    *,
    budget_seconds: float | None,
) -> tuple[str, str]:
    error_class, reason = _narration_failure_details(exc)
    _LOGGER.warning(
        "foundry narration degraded",
        extra={
            "provider_error_class": error_class,
            "provider_error_reason": reason,
            "narration_budget_bucket": (
                "none"
                if budget_seconds is None
                else "lt_1s"
                if budget_seconds < 1
                else "lt_10s"
                if budget_seconds < 10
                else "gte_10s"
            ),
        },
    )
    return error_class, reason


def executive_synthesis_decision(
    question: str,
    findings: Sequence[Mapping[str, Any]],
) -> SynthesisDecision:
    """Decide, before any model is contacted, whether aggregation is warranted.

    A second model call is only worth its latency, cost, and fabrication risk
    when there is actually something to reconcile: either the operator asked
    for an executive view outright, or two different domains produced material
    findings that cite evidence. One domain restating itself is not synthesis,
    and no cited findings leave synthesis nothing honest to say.
    """

    domains = {
        str(item.get("specialist_id") or "")
        for item in findings
        if isinstance(item, Mapping) and item.get("evidence_refs")
    }
    domains.discard("")
    domain_count = len(domains)
    if not domain_count:
        return SynthesisDecision(False, "no_cited_findings", 0)
    lowered = str(question or "").casefold()
    if any(re.search(pattern, lowered) for pattern in _EXECUTIVE_INTENT_PATTERNS):
        return SynthesisDecision(True, "explicit_intent", domain_count)
    if domain_count >= 2:
        return SynthesisDecision(True, "multi_domain", domain_count)
    return SynthesisDecision(False, "single_domain", domain_count)


def snapshot_claim_freshness(snapshot: EvidenceSnapshotV2) -> str:
    """Conservatively classify claim freshness from supplied source states."""

    statuses = {item.status for item in snapshot.freshness}
    if not statuses:
        return "unknown"
    if statuses == {"fresh"}:
        return "fresh"
    if "unavailable" in statuses:
        return "unavailable"
    if "stale" in statuses:
        return "stale"
    return "partial"


_INVENTORY_EXCLUDED_PAGES = frozenset({"connections", "connections_fabric"})


def _drop_page_irrelevant_results(
    page_kind: str | None,
    tool_results: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Drop specialist results that answer a different question than the page.

    Connections pages publish their own registry/fabric truth; a tenant
    inventory result's empty 0/0 coverage contradicts what the operator sees.
    """

    if page_kind not in _INVENTORY_EXCLUDED_PAGES:
        return list(tool_results)
    return [
        item
        for item in tool_results
        if str(item.get("tool") or "") != "inventory_resources"
    ]


def _has_substantive_findings(
    findings: Sequence[Mapping[str, Any]],
    retained_evidence: Sequence[Mapping[str, Any]] = (),
) -> bool:
    """Whether any finding carries current observed evidence, not metadata.

    Unavailable, failed, or empty specialist results and page coverage
    counters describe what could not be observed; narrating over them only
    produces low-value claims about configuration rather than state.
    """

    for finding in findings:
        if str(finding.get("status") or "") != STATUS_OK:
            continue
        refs = [str(ref) for ref in finding.get("evidence_refs") or []]
        if any(not ref.endswith(":coverage") for ref in refs):
            return True
    return any(
        str(item.get("status") or STATUS_OK) == STATUS_OK
        and not str(item.get("source") or "").endswith(":coverage")
        for item in retained_evidence
    )


def _complete_empty_page_kind(
    snapshot: EvidenceSnapshotV2,
) -> str | None:
    if not snapshot.coverage.complete or snapshot.coverage.total_count != 0:
        return None
    page = (snapshot.page_kind, snapshot.page_id)
    if page == ("situations", "situations"):
        return "situations"
    if page == ("changes", "changes"):
        return "changes"
    return None


def _is_unsubmitted_predeploy_snapshot(
    snapshot: EvidenceSnapshotV2 | None,
) -> bool:
    return (
        snapshot is not None
        and snapshot.page_kind == "changes_predeploy"
        and snapshot.page_id == "predeploy"
        and snapshot.coverage.visible_count == 0
        and snapshot.coverage.total_count == 0
        and not snapshot.coverage.complete
        and not snapshot.selected_entities
        and not snapshot.material_claims
        and bool(snapshot.freshness)
        and all(item.status == "unavailable" for item in snapshot.freshness)
    )


def deterministic_network_claims(
    *,
    snapshot: EvidenceSnapshotV2 | None,
    tool_results: Sequence[Mapping[str, Any]],
    selected_resource_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Summarize cited firewall findings without optional model narration."""

    if snapshot is None or snapshot.page_kind not in {"network", "compliance"}:
        return []
    network_claim: dict[str, Any] | None = None
    for result in tool_results:
        if (
            result.get("tool") != "firewall_nsg_gaps"
            or result.get("status") != STATUS_OK
            or not isinstance(result.get("data"), Mapping)
        ):
            continue
        data = result["data"]
        gaps = [
            row for row in data.get("gaps", [])
            if isinstance(row, Mapping)
        ]
        findings = [
            row for row in data.get("rule_findings", [])
            if isinstance(row, Mapping)
        ]
        call_id = str(result.get("call_id") or "")
        evidence_refs = [
            f"tool:{call_id}:{index}"
            for index, item in enumerate(result.get("evidence") or [])
            if isinstance(item, Mapping)
        ]
        if not evidence_refs:
            continue
        rows = sorted(
            [*gaps, *findings],
            key=lambda row: (
                {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
                    str(row.get("severity") or "").casefold(),
                    4,
                ),
                str(row.get("title") or ""),
            ),
        )
        highlights = []
        for row in rows[:5]:
            title = str(
                row.get("title")
                or row.get("detail")
                or row.get("gap_id")
                or row.get("finding_id")
                or "Unnamed network finding"
            ).strip()
            severity = str(row.get("severity") or "unknown").strip().casefold()
            resource = str(
                row.get("resource_name")
                or row.get("rule_name")
                or row.get("control")
                or row.get("resource_id")
                or ""
            ).strip()
            detail = str(row.get("detail") or "").strip()
            recommendation = str(row.get("recommendation") or "").strip()
            subject = f"**{resource}**: " if resource else ""
            explanation = f" {detail}" if detail else ""
            next_step = (
                f" Recommended next step: {recommendation}"
                if recommendation
                else ""
            )
            highlights.append(
                f"- {subject}{title} ({severity}).{explanation}{next_step}"
            )
        inspection_only = (
            bool(gaps)
            and not findings
            and all(
                str(row.get("category") or "").casefold()
                == "firewall_bypass"
                for row in gaps
            )
        )
        if inspection_only:
            path_label = (
                "inspection-bypass path"
                if len(gaps) == 1
                else "inspection-bypass paths"
            )
            summary = (
                f"Network evidence identifies **{len(gaps)} {path_label}** "
                "in the current scope."
            )
        else:
            gap_label = "architecture gap" if len(gaps) == 1 else "architecture gaps"
            finding_label = (
                "firewall/NSG rule finding"
                if len(findings) == 1
                else "firewall/NSG rule findings"
            )
            summary = (
                f"Network evidence reports **{len(gaps)} {gap_label}** and "
                f"**{len(findings)} {finding_label}**."
            )
        if highlights:
            summary += "\n\n" + "\n".join(highlights)
        uncertainty = (
            []
            if snapshot.coverage.complete
            else ["Visible page coverage is incomplete."]
        )
        network_claim = {
                "finding_id": (
                    "network:"
                    + hashlib.sha256(
                        f"{call_id}:{'|'.join(evidence_refs)}".encode()
                    ).hexdigest()[:24]
                ),
                "summary": summary[:1000],
                "evidence_refs": evidence_refs,
                "confidence": (
                    "high" if snapshot.coverage.complete else "medium"
                ),
                "freshness": snapshot_claim_freshness(snapshot),
                "uncertainty": uncertainty,
                "actionable": False,
                "next_check": (
                    "Review the cited scoped network findings before changing "
                    "firewall, route, or NSG policy."
                ),
            }
        break

    # A missing firewall_nsg_gaps claim does not mean there is nothing cite-
    # worthy on this page: successful Network findings such as network_topology
    # still carry rich, citation-closed evidence (hubs, spokes, shared
    # services, resources) and must still surface as deterministic claims when
    # optional model narration is unavailable or times out. Bailing out here
    # unconditionally silently dropped that evidence even though it was fully
    # populated, so the fallback loop below always runs regardless of whether
    # a firewall claim was built.
    claims: list[dict[str, Any]] = [network_claim] if network_claim is not None else []
    covered_refs: set[str] = (
        set(network_claim["evidence_refs"]) if network_claim is not None else set()
    )
    # Tools whose normalized finding summary is already a rich, self-describing
    # projection of the tool's own data (see normalize_cited_findings) rather
    # than a generic templated sentence. Prefer that richer, still
    # citation-closed summary over the generic fallback text for these tools.
    rich_summary_tools = {"network_topology", "hub_dependents"}
    call_id_to_tool = {
        str(
            result.get("call_id")
            or f"{result.get('specialist_id')}:{result.get('tool')}"
        ): str(result.get("tool") or "")
        for result in tool_results
        if isinstance(result, Mapping)
    }
    for finding in normalize_cited_findings(
        tool_results,
        selected_resource_ids=selected_resource_ids,
    ):
        evidence_refs = [
            str(reference)
            for reference in finding.get("evidence_refs") or []
        ]
        if not evidence_refs or covered_refs.intersection(evidence_refs):
            continue
        specialist = str(finding.get("specialist_id") or "specialist").replace(
            "_",
            " ",
        )
        tool_name = call_id_to_tool.get(str(finding.get("finding_id") or ""), "")
        rich_summary = str(finding.get("summary") or "").strip()
        summary = (
            rich_summary
            if tool_name in rich_summary_tools and rich_summary
            else (
                f"The {specialist} specialist returned cited "
                f"{finding.get('status') or 'unknown'!s} evidence for "
                f"this investigation."
            )
        )
        claims.append(
            {
                "finding_id": f"direct:{finding['finding_id']}",
                "summary": summary,
                "evidence_refs": evidence_refs,
                "confidence": "medium",
                "freshness": "unknown",
                "uncertainty": [
                    "The cited specialist result does not report independent freshness."
                ],
                "actionable": False,
                "next_check": (
                    "Review the cited specialist evidence before making an "
                    "operational decision."
                ),
            }
        )
    return claims


def retained_network_page_claims(
    *,
    snapshot: EvidenceSnapshotV2 | None,
    retained_evidence: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Promote current retained Network page rows into cited findings.

    The network_topology tool returns aggregate posture counts. The Network
    page, however, already supplies resource-level gap/rule/firewall-bypass
    rows with observed issues and recommended remediations. Keep those rows in
    the same citation-closed synthesis channel as tool findings so the
    executive narrator can name resources without inventing uncited detail.
    """

    if snapshot is None or snapshot.page_kind != "network":
        return []
    rows: list[Mapping[str, Any]] = []
    for item in retained_evidence:
        claim_type = str(item.get("claim_type") or "").casefold()
        if claim_type not in {"network_gap", "rule_finding", "firewall_bypass"}:
            continue
        evidence_id = str(item.get("evidence_id") or "")
        data = item.get("data")
        if not evidence_id or not isinstance(data, Mapping):
            continue
        rows.append(item)
    if not rows:
        return []

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def row_key(item: Mapping[str, Any]) -> tuple[int, str, str]:
        data = item.get("data")
        assert isinstance(data, Mapping)
        return (
            severity_rank.get(str(item.get("severity") or "").casefold(), 4),
            str(data.get("source_key") or data.get("rule_name") or ""),
            str(item.get("evidence_id") or ""),
        )

    evidence_refs: list[str] = []
    highlights: list[str] = []
    for item in sorted(rows, key=row_key)[:8]:
        data = item["data"]
        assert isinstance(data, Mapping)
        evidence_id = str(item.get("evidence_id") or "")
        evidence_refs.append(evidence_id)
        claim_type = str(item.get("claim_type") or "").casefold()
        severity = str(item.get("severity") or "unknown").casefold()
        resource = str(
            data.get("resource_name")
            or data.get("rule_name")
            or data.get("name")
            or item.get("resource_id")
            or ""
        ).strip()
        issue = str(
            data.get("issue")
            or data.get("finding")
            or data.get("title")
            or ""
        ).strip()
        recommendation = str(data.get("recommendation") or "").strip()
        prefix = {
            "network_gap": "gap",
            "rule_finding": "rule finding",
            "firewall_bypass": "firewall bypass",
        }.get(claim_type, "network finding")
        subject = f"{resource}: " if resource else ""
        next_step = (
            f" Recommended remediation: {recommendation}"
            if recommendation
            else ""
        )
        highlights.append(
            f"- {prefix} ({severity}) — {subject}{issue}.{next_step}"
        )
    if not evidence_refs:
        return []

    counts = Counter(str(item.get("claim_type") or "") for item in rows)
    summary = (
        "Network page evidence supplies resource-level findings: "
        f"{counts.get('network_gap', 0)} gaps, "
        f"{counts.get('rule_finding', 0)} rule findings, and "
        f"{counts.get('firewall_bypass', 0)} firewall-bypass findings."
    )
    if highlights:
        summary += "\n\n" + "\n".join(highlights)
    uncertainty = (
        []
        if snapshot.coverage.complete
        else ["Visible page coverage is incomplete."]
    )
    return [
        {
            "finding_id": (
                "network-page:"
                + hashlib.sha256("|".join(evidence_refs).encode()).hexdigest()[:24]
            ),
            "summary": summary[:2000],
            "evidence_refs": evidence_refs,
            "confidence": "high" if snapshot.coverage.complete else "medium",
            "freshness": snapshot_claim_freshness(snapshot),
            "uncertainty": uncertainty,
            "actionable": False,
            "next_check": (
                "Review the cited retained Network page rows before changing "
                "private endpoint, firewall, route, or NSG policy."
            ),
        }
    ]


class OrchestrationService:
    """Execute a fully validated plan and persist only authorized result state."""

    def __init__(
        self,
        *,
        planner: Planner | None = None,
        fallback_planner: Planner | None = None,
        executor: Executor = _default_executor,
        policy: OrchestrationPolicy | None = None,
        thread_store: InvestigationThreadStore | None = None,
        clock: Callable[[], float] = time.monotonic,
        executive_agent: Any = None,
        telemetry: Any = None,
        always_synthesize: bool = False,
    ) -> None:
        self.planner = planner
        self.fallback_planner = fallback_planner
        self.executor = executor
        self.policy = policy or OrchestrationPolicy()
        self.thread_store = thread_store or investigation_thread_store()
        self.clock = clock
        self.executive_agent = executive_agent
        self.telemetry = telemetry
        self.always_synthesize = always_synthesize

    def execute(
        self,
        request: InvestigationRequest,
        *,
        context: Any,
        principal_subject: str,
        effective_scope: Scope,
        stable_key: str | None = None,
        route_authority: object | None = None,
        max_wall_seconds: float | None = None,
        selection_snapshot: EvidenceSnapshotV2 | None = None,
        canonical_selection_snapshot: CanonicalEvidenceSnapshot | None = None,
    ) -> OrchestrationResult:
        """Execute one canonical request and return only the canonical result."""

        return self.execute_turn(
            request,
            context=context,
            principal_subject=principal_subject,
            effective_scope=effective_scope,
            stable_key=stable_key,
            route_authority=route_authority,
            max_wall_seconds=max_wall_seconds,
            selection_snapshot=selection_snapshot,
            canonical_selection_snapshot=canonical_selection_snapshot,
        ).result

    def execute_turn(
        self,
        request: InvestigationRequest,
        *,
        context: Any,
        principal_subject: str,
        effective_scope: Scope,
        stable_key: str | None = None,
        route_authority: object | None = None,
        max_wall_seconds: float | None = None,
        selection_snapshot: EvidenceSnapshotV2 | None = None,
        canonical_selection_snapshot: CanonicalEvidenceSnapshot | None = None,
    ) -> OrchestrationTurn:
        """Execute one canonical request after all authorization gates pass."""

        if route_authority is not None:
            raise CanaryAuthorizationError(
                "caller-supplied canonical route authority is not accepted"
            )
        maf_orchestrator.authorize_canonical_execution(
            request=request,
            principal_subject=principal_subject,
            stable_key=stable_key or principal_subject,
            selection_snapshot=selection_snapshot,
            canonical_selection_snapshot=canonical_selection_snapshot,
        )
        if self.telemetry is None:
            api_telemetry = getattr(context, "telemetry", None)
            self.telemetry = getattr(api_telemetry, "orchestration", None)
        narrator_state = (
            "configured" if self.executive_agent is not None else "not_configured"
        )
        if self.executive_agent is None:
            resolver = getattr(context, "specialist_agent", None)
            if callable(resolver):
                try:
                    self.executive_agent = resolver("executive_summary")
                except TimeoutError:
                    narrator_state = "timeout"
                    self.executive_agent = None
                except (ApiError, ConnectionError, FoundryAgentError):
                    narrator_state = "unavailable"
                    self.executive_agent = None
                else:
                    narrator_state = (
                        "configured"
                        if self.executive_agent is not None
                        else "not_configured"
                    )

        requested_scope = self.policy.validate_request(request, effective_scope)
        page_snapshot = selection_snapshot or request.snapshot
        self._validate_page_snapshot_scope(
            page_snapshot,
            requested_scope,
            domains_authorized=canonical_selection_snapshot is not None,
        )
        if (
            page_snapshot.page_id == "resource-health"
            and page_snapshot.page_kind != "resource_health"
        ):
            raise PolicyViolation("page_not_granted", page_snapshot.page_kind)
        evidence_selection_id = self._evidence_selection_identity(
            request.model_copy(update={"snapshot": page_snapshot}),
            requested_scope,
        )
        if page_snapshot.page_kind == "inventory":
            current_retained_evidence, retained_uncertainty = [], []
        elif canonical_selection_snapshot is not None:
            current_retained_evidence, retained_uncertainty = (
                self._current_authorized_evidence_with_uncertainty(
                    page_snapshot,
                    canonical_selection_snapshot,
                    evidence_selection_id=evidence_selection_id,
                )
            )
        else:
            current_retained_evidence, retained_uncertainty = (
                self._current_retained_evidence_with_uncertainty(
                    page_snapshot,
                    evidence_selection_id=evidence_selection_id,
                )
            )
        if request.thread_id:
            thread = self.thread_store.authorize(
                request.thread_id,
                principal_subject,
                requested_scope,
                expected_revision=request.expected_thread_revision,
            )
            thread_outcome = "continued"
        else:
            thread = self.thread_store.create(principal_subject, requested_scope)
            thread_outcome = "created"
        self._record_thread_metric(thread_outcome, thread.durability)
        started = self.clock()
        candidate, policy_status, fallback_reason = self._resolve_candidate(
            request,
            effective_scope,
        )
        execution_started = self.clock()
        wall_seconds = min(
            candidate.max_wall_seconds if candidate is not None else 5,
            self.policy.limits.max_wall_seconds,
        )
        if max_wall_seconds is not None:
            wall_seconds = min(wall_seconds, max(0.0, max_wall_seconds))
        deadline = execution_started + wall_seconds
        # Narration must not inherit the tool-execution budget. A candidate
        # plan declares `max_wall_seconds` to bound its own governed tool
        # calls (often a few seconds); reusing that same shrinking deadline
        # for the downstream Foundry narration call starves the narrator of
        # nearly all of the wall-clock budget the moment tool execution
        # consumes any of it, regardless of how much time the pinned agent
        # is actually provisioned and validated for (published manifests use
        # timeout_seconds up to the policy ceiling). Narration instead gets
        # its own budget measured from the same execution_started instant,
        # up to the full governance-approved ceiling (still capped by any
        # caller-supplied outer request timeout).
        narration_wall_seconds = self.policy.limits.max_wall_seconds
        if max_wall_seconds is not None:
            narration_wall_seconds = min(
                narration_wall_seconds, max(0.0, max_wall_seconds)
            )
        narration_deadline = execution_started + narration_wall_seconds
        tool_results: list[dict[str, Any]] = []
        tool_statuses: list[str] = []
        citations = self._snapshot_citations(request)
        citations[0] = self._snapshot_citations(
            request.model_copy(update={"snapshot": page_snapshot})
        )[0]
        citations.extend(
            Citation(
                citation_id=str(item["evidence_id"]),
                source=str(item["source"]),
                status=str(item["status"]),
                observed_at=str(item.get("observed_at") or ""),
                resource_id=str(item.get("resource_id") or ""),
            )
            for item in current_retained_evidence
        )
        selected_specialists: list[str] = []
        selected_tools: list[str] = []
        budget_exhausted = False
        turn_qualifier = (
            f"{thread.thread_id}:rev-{thread.revision + 1}:turn-{uuid.uuid4().hex}"
        )

        for step_index, step in enumerate(candidate.steps if candidate else ()):
            selected_specialists.append(step.specialist_id)
            for call_index, call in enumerate(step.tool_calls):
                if self.clock() >= deadline:
                    budget_exhausted = True
                    break
                selected_tools.append(call.tool)
                result = self.executor(
                    call.tool,
                    call.arguments,
                    context=context,
                    scope=requested_scope,
                )
                if not isinstance(result, ToolResult):
                    raise TypeError("orchestration executor must return ToolResult")
                tool_statuses.append(result.status)
                self._record_delegation_metric(
                    specialist_id=step.specialist_id,
                    tool=call.tool,
                    status=result.status,
                    policy_status=policy_status,
                    started=started,
                    evidence_count=len(result.evidence),
                )
                call_id = (
                    f"{turn_qualifier}:{step_index}:{call_index}:"
                    f"{step.specialist_id}:{call.tool}"
                )
                tool_results.append(
                    {
                        "call_id": call_id,
                        "specialist_id": step.specialist_id,
                        "tool": call.tool,
                        "arguments": dict(call.arguments),
                        **result.to_dict(),
                    }
                )
                for index, evidence in enumerate(result.evidence):
                    result_data = (
                        result.data
                        if isinstance(result.data, Mapping)
                        else {}
                    )
                    citations.append(
                        Citation(
                            citation_id=f"tool:{call_id}:{index}",
                            source=(
                                evidence.source_engine
                                if not evidence.source_table
                                else f"{evidence.source_engine}:{evidence.source_table}"
                            ),
                            status=result.status,
                            observed_at=evidence.timestamp,
                            query_version=str(
                                result_data.get("query_version") or ""
                            ),
                            resource_id=evidence.resource_id,
                        )
                    )
                if self.clock() >= deadline:
                    budget_exhausted = True
                    break
            if budget_exhausted:
                break

        connection_rows = [
            item
            for item in page_snapshot.evidence
            if item.claim_type == "subscription_connection"
        ]
        exact_connections_contract = (
            page_snapshot.page_kind == "connections"
            and page_snapshot.page_id == "connections"
            and (
                page_snapshot.coverage.total_count == 0
                or len(connection_rows) == page_snapshot.coverage.visible_count
            )
            and all(
                item.source == "connections/registry"
                and isinstance(item.entity, ObservationRef)
                and item.entity.source == "connections/registry"
                for item in connection_rows
            )
        )
        authorized_connections_truth = (
            exact_connections_contract
            and canonical_selection_snapshot is not None
            and canonical_selection_snapshot.classification in {"ready", "empty"}
            and canonical_selection_snapshot.coverage.visible_count
            == page_snapshot.coverage.visible_count
            and canonical_selection_snapshot.coverage.total_count
            == page_snapshot.coverage.total_count
            and canonical_selection_snapshot.coverage.complete
            == page_snapshot.coverage.complete
        )
        fabric_rows = [
            item
            for item in page_snapshot.evidence
            if item.claim_type in _FABRIC_CLAIM_SOURCES
        ]
        layer_rows = [
            item for item in fabric_rows if item.claim_type == "medallion_layer"
        ]
        manifest_rows = [
            item for item in fabric_rows if item.claim_type == "fabric_manifest"
        ]
        governance_rows = [
            item for item in fabric_rows if item.claim_type == "fabric_governance"
        ]
        capacity_rows = [
            item for item in fabric_rows if item.claim_type == "fabric_capacity"
        ]
        exact_fabric_contract = (
            page_snapshot.page_kind == "connections_fabric"
            and page_snapshot.page_id == "fabric-medallion"
            and len(layer_rows) == 3
            and {
                str(item.data.get("layer") or "").casefold()
                for item in layer_rows
            }
            == {"bronze", "silver", "gold"}
            and len(manifest_rows) == page_snapshot.coverage.visible_count
            and len({item.source_key for item in manifest_rows})
            == len(manifest_rows)
            and len(governance_rows) <= 1
            and len(capacity_rows) <= 1
            and all(_valid_fabric_observation(item) for item in fabric_rows)
        )
        authorized_fabric_truth = (
            exact_fabric_contract
            and canonical_selection_snapshot is not None
            and canonical_selection_snapshot.classification in {"ready", "empty"}
            and canonical_selection_snapshot.coverage.visible_count
            == page_snapshot.coverage.visible_count
            and canonical_selection_snapshot.coverage.total_count
            == page_snapshot.coverage.total_count
            and canonical_selection_snapshot.coverage.complete
            == page_snapshot.coverage.complete
        )
        resource_health_rows = [
            item
            for item in page_snapshot.evidence
            if item.claim_type == "resource_utilization"
        ]
        resource_metric_coverage_rows = [
            item
            for item in page_snapshot.evidence
            if item.claim_type == "resource_metric_coverage"
        ]
        exact_resource_health_contract = (
            page_snapshot.page_kind == "resource_health"
            and page_snapshot.page_id == "resource-health"
            and len(resource_health_rows) == page_snapshot.coverage.visible_count
            and len(resource_metric_coverage_rows) == 1
            and len({item.resource_id for item in resource_health_rows})
            == len(resource_health_rows)
            and len({
                str(item.data.get("resource_name") or "").casefold()
                for item in resource_health_rows
            })
            == len(resource_health_rows)
            and all(
                _valid_resource_health_observation(item)
                for item in resource_health_rows
            )
            and all(
                item.status in {"ok", "partial"}
                and item.source == "resource-health/metrics"
                and isinstance(item.entity, ObservationRef)
                and item.entity.source == "resource-health/metrics"
                and item.entity.source_key == item.source_key == "metric-coverage"
                and isinstance(item.data.get("unavailable_metrics"), list)
                and isinstance(item.data.get("warnings"), list)
                and isinstance(item.data.get("cached"), bool)
                for item in resource_metric_coverage_rows
            )
        )
        accepted_resource_health_observations = (
            exact_resource_health_contract
            and canonical_selection_snapshot is not None
            and canonical_selection_snapshot.classification in {"ready", "empty"}
            and canonical_selection_snapshot.coverage.visible_count
            == page_snapshot.coverage.visible_count
            and canonical_selection_snapshot.coverage.total_count
            == page_snapshot.coverage.total_count
            and canonical_selection_snapshot.coverage.complete
            == page_snapshot.coverage.complete
        )
        inventory_authority = (
            _inventory_page_authority(
                page_snapshot,
                tool_results,
            )
            if page_snapshot.page_kind == "inventory"
            else None
        )
        accepted_inventory_observations = inventory_authority is not None
        if inventory_authority is not None:
            current_retained_evidence = self._current_exact_inventory_evidence(
                page_snapshot,
                evidence_selection_id=evidence_selection_id,
                observed_at=str(inventory_authority["observed_at"]),
                query_version=str(inventory_authority["query_version"]),
            )
            citations.extend(
                Citation(
                    citation_id=str(item["evidence_id"]),
                    source=str(item["source"]),
                    status=str(item["status"]),
                    observed_at=str(item.get("observed_at") or ""),
                    query_version=str(item.get("query_version") or ""),
                    resource_id=str(item.get("resource_id") or ""),
                )
                for item in current_retained_evidence
            )
        authorized_page_truth = (
            authorized_connections_truth
            or authorized_fabric_truth
            or accepted_resource_health_observations
            or accepted_inventory_observations
        )
        uncertainty_request = (
            request.model_copy(update={"snapshot": page_snapshot})
            if (
                authorized_page_truth
                or _complete_empty_page_kind(page_snapshot) is not None
            )
            else request
        )
        if (
            page_snapshot.page_kind == "investigate"
            and canonical_selection_snapshot is not None
        ):
            # The planning snapshot intentionally masks browser freshness as
            # unavailable. Keep that mask for planning, but do not expose it
            # as observed source truth in the response.
            uncertainty_request = uncertainty_request.model_copy(
                update={
                    "snapshot": uncertainty_request.snapshot.model_copy(
                        update={"freshness": []}
                    )
                }
            )
        uncertainty = self._uncertainty(
            uncertainty_request,
            tool_results,
            budget_exhausted=budget_exhausted,
        )
        if (
            page_snapshot.page_kind == "investigate"
            and canonical_selection_snapshot is not None
        ):
            retained_uncertainty = [
                warning
                for warning in retained_uncertainty
                if " freshness is " not in warning
            ]
            uncertainty.extend(
                self._canonical_retained_freshness_uncertainty(
                    canonical_selection_snapshot,
                    current_retained_evidence,
                )
            )
        if candidate is None:
            uncertainty.append(
                "No safe page tool call could be formed from validated snapshot context."
            )
        uncertainty.extend(retained_uncertainty)
        status = self._result_status(
            tool_statuses,
            uncertainty,
            budget_exhausted=budget_exhausted,
        )
        retained_evidence = self._retained_evidence(
            thread,
            requested_scope,
            evidence_selection_id=evidence_selection_id,
        )
        synthesis = self._synthesize(
            request.question,
            tool_results,
            retained_evidence=retained_evidence,
            current_retained_evidence=current_retained_evidence,
            snapshot=page_snapshot,
            deadline=deadline,
            narration_deadline=narration_deadline,
            narrator_state=narrator_state,
            fabric_page_truth_authorized=authorized_fabric_truth,
            resource_health_page_observations_accepted=(
                accepted_resource_health_observations
            ),
            inventory_page_observations_accepted=(
                accepted_inventory_observations
            ),
            selected_resource_ids={
                entity.resource_id
                for entity in page_snapshot.selected_entities
                if isinstance(entity, AzureEntityRef)
            },
        )
        if synthesis.warning:
            uncertainty = [*uncertainty, synthesis.warning]
        uncertainty = self._bounded_uncertainty(uncertainty)
        citations.extend(
            Citation(
                citation_id=str(item["evidence_id"]),
                source=str(item["source"]),
                status=str(item["status"]),
            )
            for item in synthesis.used_retained_evidence
        )
        budget_exhausted = budget_exhausted or self.clock() >= deadline
        self._record_budget_metric(budget_exhausted, started)
        if policy_status == "fallback":
            self._record_fallback_metric(fallback_reason)
        result = OrchestrationResult(
            status=status,
            policy_status=policy_status,
            fallback_reason=fallback_reason,
            selected_specialists=selected_specialists,
            selected_tools=selected_tools,
            tool_results=tool_results,
            uncertainty=uncertainty,
            coverage=(
                page_snapshot.coverage
                if (
                    authorized_page_truth
                    or _complete_empty_page_kind(page_snapshot) is not None
                )
                else request.snapshot.coverage
            ),
            citations=self._deduplicate_citations(citations),
            thread_id=thread.thread_id,
            thread_revision=thread.revision + 1,
            synthesis=_executive_synthesis_payload(synthesis),
        )
        return OrchestrationTurn(
            result=self._record_turn(
                thread,
                principal_subject=principal_subject,
                requested_scope=requested_scope,
                question=request.question,
                result=result,
                reconcile_conflict=request.expected_thread_revision is None,
                evidence_selection_id=evidence_selection_id,
                evidence_generation_id=(
                    page_snapshot.content_generation_id()
                ),
                retained_evidence=current_retained_evidence,
            ),
            synthesis=synthesis,
        )

    # -- conditional executive synthesis ----------------------------------

    @staticmethod
    def _retained_evidence(
        thread: InvestigationThread,
        current_scope: Scope,
        *,
        evidence_selection_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Project the thread's retained citations for synthesis reconciliation.

        Exact-selection retained page facts stay available to deterministic
        synthesis. The optional model projection still strips those facts in
        ``executive_synthesis_input`` and receives only citation metadata.
        """

        retained: list[dict[str, Any]] = []
        for turn in thread.turns:
            if not scope_within(turn.scope, current_scope):
                continue
            if (
                evidence_selection_id is not None
                and turn.payload.get("evidence_selection_id")
                != evidence_selection_id
            ):
                continue
            retained_payload = turn.payload.get("retained_evidence")
            if isinstance(retained_payload, list):
                for item in retained_payload:
                    if not isinstance(item, Mapping):
                        continue
                    evidence_id = str(item.get("evidence_id") or "")
                    if not evidence_id:
                        continue
                    retained.append(
                        {
                            "evidence_id": evidence_id,
                            "source": str(item.get("source") or ""),
                            "status": str(item.get("status") or ""),
                            "observation_status": OBSERVATION_HISTORICAL,
                            **(
                                {"data": dict(item["data"])}
                                if isinstance(item.get("data"), Mapping)
                                else {}
                            ),
                        }
                    )
                continue
            turn_revision = int(turn.payload.get("thread_revision") or 0)
            turn_identity = (
                f"rev-{turn_revision}"
                if turn_revision > 0
                else "turn-"
                + uuid.uuid5(
                    uuid.NAMESPACE_OID,
                    (
                        f"{thread.thread_id}:{turn.recorded_at}:"
                        + json.dumps(
                            turn.payload,
                            default=str,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    ),
                ).hex
            )
            for citation_index, citation in enumerate(
                turn.payload.get("citations") or []
            ):
                if not isinstance(citation, Mapping):
                    continue
                original_id = str(citation.get("citation_id") or "")
                if not original_id:
                    continue
                citation_token = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    original_id,
                ).hex[:16]
                retained.append(
                    {
                        "evidence_id": (
                            f"retained:{thread.thread_id}:{turn_identity}:"
                            f"citation-{citation_index}:{citation_token}"
                        ),
                        "original_evidence_id": original_id,
                        "source": str(citation.get("source") or ""),
                        "status": str(citation.get("status") or ""),
                        "observation_status": OBSERVATION_HISTORICAL,
                    }
                )
        return retained

    @staticmethod
    def _validate_page_snapshot_scope(
        snapshot: EvidenceSnapshotV2,
        current_scope: Scope,
        *,
        domains_authorized: bool = False,
    ) -> None:
        """Reject Azure page observations outside the authorized read scope."""

        entities = [
            *snapshot.selected_entities,
            *[
                item.entity
                for item in snapshot.evidence
                if item.entity is not None
            ],
        ]
        for entity in entities:
            if isinstance(entity, DomainEntityRef):
                if not domains_authorized:
                    raise PolicyViolation(
                        "unresolved_domain_entity",
                        "domain page evidence requires server resolution",
                    )
                continue
            if not isinstance(entity, AzureEntityRef):
                continue
            parts = [
                part.casefold()
                for part in entity.resource_id.split("/")
                if part
            ]
            attributes = {"subscription": parts[1]}
            if len(parts) >= 4 and parts[2] == "resourcegroups":
                attributes["resource_group"] = parts[3]
            if not current_scope.matches(attributes):
                raise PolicyViolation(
                    "scope_widening",
                    "page evidence is outside the effective read scope",
                )

    @staticmethod
    def _current_retained_evidence(
        snapshot: EvidenceSnapshotV2,
        *,
        evidence_selection_id: str,
    ) -> list[dict[str, Any]]:
        """Retain bounded scalar page facts under server-minted citation IDs."""

        retained, _ = OrchestrationService._current_retained_evidence_with_uncertainty(
            snapshot,
            evidence_selection_id=evidence_selection_id,
        )
        return retained

    @staticmethod
    def _current_exact_inventory_evidence(
        snapshot: EvidenceSnapshotV2,
        *,
        evidence_selection_id: str,
        observed_at: str,
        query_version: str,
    ) -> list[dict[str, Any]]:
        """Mint current citations after exact Inventory/tool parity succeeds."""

        retained: list[dict[str, Any]] = []
        for item in snapshot.evidence:
            data = OrchestrationService._bounded_page_facts(item.data)
            if (
                not data
                and item.claim_type == "page_context"
                and snapshot.coverage.visible_count == 0
            ):
                data = {
                    "visible_count": 0,
                    "total_count": snapshot.coverage.total_count,
                }
            if not data:
                continue
            citation_seed = f"{evidence_selection_id}:{item.evidence_id}".encode()
            retained.append(
                {
                    "evidence_id": (
                        "retained:"
                        + hashlib.sha256(citation_seed).hexdigest()[:32]
                    ),
                    "original_evidence_id": item.evidence_id,
                    "source": f"page_snapshot:inventory:{item.source}",
                    "status": item.status,
                    "observed_at": observed_at,
                    "query_version": query_version,
                    "resource_id": item.resource_id,
                    "observation_status": OBSERVATION_CURRENT,
                    "claim_type": item.claim_type,
                    "selected": item.selected,
                    "direct": item.direct,
                    "quality": item.quality,
                    "severity": item.severity,
                    "data": data,
                }
            )
        return retained

    @staticmethod
    def _current_retained_evidence_with_uncertainty(
        snapshot: EvidenceSnapshotV2,
        *,
        evidence_selection_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Select admissible page facts, then mint bounded server citations."""

        selection = select_browser_evidence_for_retention(snapshot)
        retained: list[dict[str, Any]] = []
        for item in selection.evidence:
            data = OrchestrationService._bounded_page_facts(item.data)
            if not data:
                continue
            citation_seed = f"{evidence_selection_id}:{item.evidence_id}".encode()
            citation_id = (
                "retained:"
                + hashlib.sha256(citation_seed).hexdigest()[:32]
            )
            retained.append(
                {
                    "evidence_id": citation_id,
                    "original_evidence_id": item.evidence_id,
                    "source": (
                        f"page_snapshot:{snapshot.page_kind}:{item.source}"
                    ),
                    "status": item.status,
                    "observed_at": item.observed_at,
                    "resource_id": item.resource_id,
                    "observation_status": OBSERVATION_CURRENT,
                    "claim_type": item.claim_type,
                    "selected": item.selected,
                    "direct": item.direct,
                    "quality": item.quality,
                    "severity": item.severity,
                    "data": data,
                }
            )
        return retained, list(selection.uncertainty)

    @staticmethod
    def _current_authorized_evidence_with_uncertainty(
        snapshot: EvidenceSnapshotV2,
        canonical_snapshot: CanonicalEvidenceSnapshot,
        *,
        evidence_selection_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Mint retained citations only from server-resolved canonical rows."""

        incomplete_claims = {
            claim.claim_id
            for claim in snapshot.material_claims
            if claim.requires_complete_coverage and not snapshot.coverage.complete
        }
        admissible_refs = {
            reference
            for claim in snapshot.material_claims
            if claim.claim_id not in incomplete_claims
            for reference in claim.evidence_refs
        }
        conflicting_ids = {
            conflict.stable_id for conflict in canonical_snapshot.conflicts
        }
        retained: list[dict[str, Any]] = []
        for item in canonical_snapshot.evidence:
            if (
                item.stable_id in conflicting_ids
                or item.status not in {"ok", "partial"}
                or not admissible_refs.intersection(item.evidence_refs)
            ):
                continue
            data = OrchestrationService._bounded_page_facts(item.data)
            if not data:
                continue
            original_id = min(
                admissible_refs.intersection(item.evidence_refs)
            )
            citation_seed = f"{evidence_selection_id}:{original_id}".encode()
            retained.append(
                {
                    "evidence_id": (
                        "retained:"
                        + hashlib.sha256(citation_seed).hexdigest()[:32]
                    ),
                    "original_evidence_id": original_id,
                    "source": (
                        f"page_snapshot:{snapshot.page_kind}:{item.source}"
                    ),
                    "status": item.status,
                    "observed_at": item.observed_at,
                    "resource_id": (
                        item.entity_key.removeprefix("azure:")
                        if item.entity_key.startswith("azure:")
                        else ""
                    ),
                    "observation_status": OBSERVATION_CURRENT,
                    "claim_type": item.claim_type,
                    "selected": item.selected,
                    "direct": item.direct,
                    "quality": item.quality,
                    "severity": item.severity,
                    "data": data,
                }
            )
        return retained, list(
            dict.fromkeys(
                [
                    *canonical_snapshot.uncertainty,
                    *(
                        [
                            (
                                "Incomplete material claims requiring complete "
                                "coverage were excluded."
                            )
                        ]
                        if incomplete_claims
                        else []
                    ),
                    *(
                        ["Conflicting page evidence was excluded from synthesis."]
                        if canonical_snapshot.conflicts
                        else []
                    ),
                    *canonical_snapshot.insufficiency_reasons,
                ]
            )
        )

    @staticmethod
    def _canonical_retained_freshness_uncertainty(
        canonical_snapshot: CanonicalEvidenceSnapshot,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[str]:
        """Describe only source freshness that survived canonical retention."""

        retained_refs = {
            str(item.get("original_evidence_id") or "")
            for item in retained_evidence
            if item.get("original_evidence_id")
        }
        priority = {
            "fresh": 0,
            "partial": 1,
            "stale": 2,
            "unknown": 3,
            "unavailable": 4,
        }
        by_source: dict[str, str] = {}
        for item in canonical_snapshot.evidence:
            if not retained_refs.intersection(item.evidence_refs):
                continue
            current = by_source.get(item.source)
            if current is None or priority[item.freshness] > priority[current]:
                by_source[item.source] = item.freshness
        messages = [
            f"{source} freshness is {status}"
            for source, status in sorted(
                by_source.items(),
                key=lambda item: (-priority[item[1]], item[0]),
            )
            if status != "fresh"
        ]
        if len(messages) <= 12:
            return messages
        omitted = len(messages) - 11
        return [
            *messages[:11],
            (
                f"{omitted} additional retained sources have non-fresh "
                "evidence; review retained citations for details."
            ),
        ]

    @staticmethod
    def _bounded_uncertainty(values: Sequence[str]) -> list[str]:
        """Deduplicate and cap public uncertainty within the wire contract."""

        unique = list(dict.fromkeys(value for value in values if value))
        if len(unique) <= 32:
            return unique
        omitted = len(unique) - 31
        return [
            *unique[:31],
            f"{omitted} additional uncertainty records were omitted.",
        ]

    @staticmethod
    def _bounded_page_facts(data: Mapping[str, Any]) -> dict[str, Any]:
        retained: dict[str, Any] = {}
        for key, value in sorted(data.items()):
            normalized_key = str(key).strip()
            if not normalized_key or normalized_key in {
                "actionable",
                "claim_type",
                "entity",
                "mutation_authorized",
                "selected",
                "source_key",
            }:
                continue
            if (
                value is None
                or isinstance(value, (bool, int))
                or (isinstance(value, float) and math.isfinite(value))
                or (isinstance(value, str) and len(value) <= 512)
            ):
                retained[normalized_key] = value
            elif (
                isinstance(value, list)
                and len(value) <= 16
                and all(
                    item is None
                    or isinstance(item, (bool, int, str))
                    or (isinstance(item, float) and math.isfinite(item))
                    for item in value
                )
            ):
                retained[normalized_key] = list(value)
            if len(retained) >= 16:
                break
        return retained

    @staticmethod
    def _evidence_selection_identity(
        request: InvestigationRequest,
        current_scope: Scope,
    ) -> str:
        """Bind retained evidence to one normalized authorized page selection."""

        snapshot = request.snapshot
        selected_entities = sorted(
            (
                item.model_dump(mode="json")
                for item in snapshot.selected_entities
            ),
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
        payload = {
            "page_kind": snapshot.page_kind,
            "page_id": snapshot.page_id,
            "selected_entities": selected_entities,
            "filters": {
                " ".join(str(key).strip().casefold().split()): sorted(
                    {
                        " ".join(str(item).strip().casefold().split())
                        for item in values
                        if str(item).strip()
                    }
                )
                for key, values in sorted(snapshot.filters.items())
                if str(key).strip()
            },
            "query": " ".join(snapshot.query.strip().casefold().split()),
            "generation_id": snapshot.content_generation_id(),
            "authorized_scope": current_scope.to_dict(),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return f"selection:{hashlib.sha256(encoded).hexdigest()}"

    def _synthesize(
        self,
        question: str,
        tool_results: Sequence[Mapping[str, Any]],
        *,
        retained_evidence: Sequence[Mapping[str, Any]],
        current_retained_evidence: Sequence[Mapping[str, Any]] = (),
        snapshot: EvidenceSnapshotV2 | None = None,
        deadline: float | None = None,
        narration_deadline: float | None = None,
        narrator_state: str = "configured",
        fabric_page_truth_authorized: bool = False,
        resource_health_page_observations_accepted: bool = False,
        inventory_page_observations_accepted: bool = False,
        selected_resource_ids: set[str] | None = None,
    ) -> ExecutiveSynthesis:
        """Run at most one citation-closed aggregation call, or none at all."""

        specialist_provider_unavailable = any(
            str(item.get("status") or "") == STATUS_UNAVAILABLE
            for item in tool_results
        )
        tool_results = _drop_page_irrelevant_results(
            snapshot.page_kind if snapshot is not None else None,
            tool_results,
        )
        findings = normalize_cited_findings(
            tool_results,
            selected_resource_ids=selected_resource_ids,
        )
        decision = executive_synthesis_decision(question, findings)
        cve_claims = self._deterministic_cve_claims(
            question,
            snapshot=snapshot,
            tool_results=tool_results,
        )
        patch_claims = self._deterministic_patch_claims(
            snapshot=snapshot,
            tool_results=tool_results,
        )
        network_claims = deterministic_network_claims(
            snapshot=snapshot,
            tool_results=tool_results,
            selected_resource_ids=selected_resource_ids,
        )
        network_page_claims = retained_network_page_claims(
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        remediation_claims = self._deterministic_remediation_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        fabric_starter_kind = _fabric_starter_kind(question)
        resource_health_starter_kind = _resource_health_starter_kind(question)
        inventory_starter = inventory_starter_kind(question)
        page_claims = (
            []
            if (
                snapshot is not None
                and (
                    (
                        snapshot.page_kind == "connections_fabric"
                        and fabric_starter_kind is not None
                    )
                    or (
                        snapshot.page_kind == "resource_health"
                        and resource_health_starter_kind is not None
                    )
                    or (
                        snapshot.page_kind == "inventory"
                        and inventory_starter is not None
                    )
                )
            )
            else self._deterministic_page_claims(
                question,
                snapshot=snapshot,
                retained_evidence=current_retained_evidence,
            )
        )
        service_status_claims = self._deterministic_service_status_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        twin_status_claims = self._deterministic_twin_status_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        overview_ranking_claims = self._deterministic_overview_ranking_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        finops_savings_claims = self._deterministic_finops_savings_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        )
        fabric_claims = self._deterministic_fabric_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        ) if fabric_page_truth_authorized else []
        resource_health_claims = self._deterministic_resource_health_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        ) if resource_health_page_observations_accepted else []
        inventory_claims = self._deterministic_inventory_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
        ) if inventory_page_observations_accepted else []
        if (
            snapshot is not None
            and snapshot.page_kind == "inventory"
            and inventory_starter is not None
            and not inventory_page_observations_accepted
        ):
            synthesis = ExecutiveSynthesis(
                status="skipped",
                reason="inventory_page_evidence_not_authorized",
                domain_count=1,
                claims=[],
                warning=(
                    "Inventory page evidence is incomplete or failed exact "
                    "page-to-tool parity; no deterministic claim was made."
                ),
                used_retained_evidence=[],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if (
            snapshot is not None
            and snapshot.page_kind == "resource_health"
            and resource_health_starter_kind is not None
            and not resource_health_page_observations_accepted
        ):
            synthesis = ExecutiveSynthesis(
                status="skipped",
                reason="resource_health_page_evidence_not_authorized",
                domain_count=1,
                claims=[],
                warning=(
                    "Resource Health page evidence is incomplete or failed "
                    "identity validation; no deterministic claim was made."
                ),
                used_retained_evidence=[],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if (
            snapshot is not None
            and snapshot.page_kind == "connections_fabric"
            and fabric_starter_kind is not None
            and not fabric_page_truth_authorized
        ):
            synthesis = ExecutiveSynthesis(
                status="skipped",
                reason="fabric_page_evidence_not_authorized",
                domain_count=1,
                claims=[],
                warning=(
                    "Fabric page evidence is incomplete or failed identity "
                    "validation; no deterministic claim was made."
                ),
                used_retained_evidence=[],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if _is_unsubmitted_predeploy_snapshot(snapshot) and page_claims:
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_predeploy_no_assessment",
                domain_count=1,
                claims=page_claims,
                used_retained_evidence=[],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if fabric_claims:
            used_refs = {
                str(reference)
                for claim in fabric_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_fabric_page_evidence",
                domain_count=1,
                claims=fabric_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if resource_health_claims:
            used_refs = {
                str(reference)
                for claim in resource_health_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_resource_health_page_evidence",
                domain_count=1,
                claims=resource_health_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if inventory_claims:
            used_refs = {
                str(reference)
                for claim in inventory_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_inventory_page_evidence",
                domain_count=1,
                claims=inventory_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if overview_ranking_claims:
            used_refs = {
                str(reference)
                for claim in overview_ranking_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_overview_ranking",
                domain_count=4,
                claims=overview_ranking_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if finops_savings_claims:
            used_refs = {
                str(reference)
                for claim in finops_savings_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_finops_savings",
                domain_count=1,
                claims=finops_savings_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        highest_risk_compliance = (
            snapshot is not None
            and is_highest_risk_compliance_question(
                snapshot.page_kind,
                question,
            )
        )
        deterministic_claims = (
            [*page_claims, *network_page_claims, *network_claims][:8]
            if highest_risk_compliance and page_claims
            else (
                cve_claims
                or patch_claims
                or network_page_claims
                or network_claims
                or remediation_claims
                or page_claims
            )
        )
        for claim in deterministic_claims:
            evidence_refs = [
                str(reference)
                for reference in claim.get("evidence_refs") or []
            ]
            if not evidence_refs:
                continue
            findings.append(
                {
                    "finding_id": str(claim.get("finding_id") or ""),
                    "specialist_id": (
                        "network"
                        if network_page_claims or network_claims
                        else "patch"
                        if patch_claims
                        else "vulnerability"
                        if cve_claims
                        else "page_evidence"
                    ),
                    "status": STATUS_OK,
                    "summary": str(claim.get("summary") or ""),
                    "evidence_refs": evidence_refs,
                    "observation_status": str(
                        claim.get("freshness") or "unknown"
                    ),
                }
            )
        if highest_risk_compliance and page_claims:
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_page_evidence",
                domain_count=max(1, decision.domain_count),
                claims=deterministic_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if service_status_claims:
            used_refs = {
                str(reference)
                for claim in service_status_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_service_status",
                domain_count=1,
                claims=service_status_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if twin_status_claims:
            used_refs = {
                str(reference)
                for claim in twin_status_claims
                for reference in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_twin_status",
                domain_count=1,
                claims=twin_status_claims,
                used_retained_evidence=[
                    dict(item)
                    for item in current_retained_evidence
                    if str(item.get("evidence_id") or "") in used_refs
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if patch_claims:
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_patch_catalog",
                domain_count=1,
                claims=patch_claims,
                used_retained_evidence=[],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if remediation_claims:
            synthesis = ExecutiveSynthesis(
                status="deterministic",
                reason="deterministic_remediation_workflow",
                domain_count=1,
                claims=remediation_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if self.always_synthesize and (findings or deterministic_claims):
            decision = SynthesisDecision(
                admitted=True,
                reason="operations_copilot_coordinator",
                domain_count=max(
                    1,
                    len({
                        str(item.get("specialist_id") or "")
                        for item in findings
                        if item.get("specialist_id")
                    }),
                ),
            )
        if deterministic_claims and self.executive_agent is None:
            evidence_kind = (
                "CVE"
                if cve_claims
                else "network"
                if network_page_claims or network_claims
                else "page"
            )
            warning = _narration_fallback_warning(
                narrator_state=narrator_state,
                fallback_detail=(
                    f"deterministic cited {evidence_kind} evidence was used"
                ),
                specialist_provider_unavailable=specialist_provider_unavailable,
            )
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason="deterministic_page_evidence",
                domain_count=max(1, decision.domain_count),
                claims=deterministic_claims,
                warning=warning,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if not decision.admitted:
            synthesis = ExecutiveSynthesis(
                status="deterministic" if deterministic_claims else "skipped",
                reason=(
                    "deterministic_page_evidence"
                    if deterministic_claims
                    else decision.reason
                ),
                domain_count=max(
                    int(bool(deterministic_claims)),
                    decision.domain_count,
                ),
                claims=deterministic_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if not deterministic_claims and not _has_substantive_findings(
            findings,
            current_retained_evidence,
        ):
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was skipped because no specialist "
                    "returned current observed evidence; only configuration "
                    "or coverage metadata was available."
                ),
                claims=[],
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason="no_substantive_evidence",
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if deadline is not None and self.clock() >= deadline:
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was skipped because the canonical "
                    "wall-clock budget was exhausted."
                ),
                claims=deterministic_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason="budget_exhausted",
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if self.executive_agent is None:
            warning = _narration_fallback_warning(
                narrator_state=narrator_state,
                fallback_detail=(
                    "direct specialist findings and retained current page "
                    "evidence are shown instead"
                ),
                specialist_provider_unavailable=specialist_provider_unavailable,
            )
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=warning,
                claims=deterministic_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason=narrator_state,
            )
            self._record_synthesis_metric(synthesis)
            return synthesis

        stage_started = self.clock()
        synthesis_input = executive_synthesis_input(
            findings,
            retained_evidence=retained_evidence,
        )
        evidence_refs = {
            ref
            for finding in synthesis_input["findings"]
            for ref in finding["evidence_refs"]
        }
        evidence_refs.update(
            str(item.get("evidence_id") or "")
            for item in synthesis_input["retained_evidence"]
            if item.get("evidence_id")
        )
        # `deadline` is the tool-execution wall-clock budget: if the
        # specialists already burned through the entire turn budget, the
        # turn is out of time altogether and synthesis is skipped outright
        # (regardless of how much of the separate narration ceiling remains).
        remaining_seconds = (
            max(0.0, deadline - self.clock())
            if deadline is not None
            else None
        )
        if remaining_seconds is not None and remaining_seconds <= 0:
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was skipped because the canonical "
                    "wall-clock budget was exhausted."
                ),
                claims=deterministic_claims,
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason="budget_exhausted",
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        # When synthesis does proceed, the timeout actually handed to the
        # provider is bounded by `narration_deadline` -- narration's own,
        # governance-sized budget -- not by whatever sliver of the (much
        # smaller) tool-execution budget happens to remain.
        narration_remaining_seconds = (
            max(0.0, narration_deadline - self.clock())
            if narration_deadline is not None
            else remaining_seconds
        )
        try:
            answer_kwargs = {
                "question": question,
                "context": synthesis_input,
            }
            if narration_remaining_seconds is not None:
                answer_kwargs["timeout_seconds"] = narration_remaining_seconds
            answer = self.executive_agent.answer(**answer_kwargs)
            claims = validate_executive_synthesis(
                getattr(answer, "text", ""),
                evidence_refs=evidence_refs,
            )
        except FoundryAgentError as exc:
            # A rejected or unreachable narrator must not remove the evidence
            # the specialists already produced, so the turn degrades to their
            # direct findings and says so rather than failing.
            caused_by_timeout = _caused_by_timeout(exc)
            error_class, error_reason = _log_narration_failure(
                exc,
                budget_seconds=narration_remaining_seconds,
            )
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=deterministic_claims,
                warning=(
                    "Foundry narration timed out; deterministic cited evidence is "
                    "shown instead."
                    if caused_by_timeout
                    else (
                        "Foundry narration failed response validation; deterministic "
                        "cited evidence is shown instead."
                        if error_reason == "response_contract"
                        else "Foundry narration provider is unavailable; deterministic "
                        "cited evidence is shown instead."
                    )
                ),
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason=(
                    "timeout" if caused_by_timeout
                    else "response_contract" if error_reason == "response_contract"
                    else "unavailable"
                ),
                narration_budget_seconds=narration_remaining_seconds or 0.0,
                provider_error_class=error_class,
                provider_error_reason=error_reason,
            )
        except TimeoutError as exc:
            error_class, error_reason = _log_narration_failure(
                exc,
                budget_seconds=narration_remaining_seconds,
            )
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=deterministic_claims,
                warning=(
                    "Foundry narration timed out; deterministic cited evidence is "
                    "shown instead."
                ),
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason="timeout",
                narration_budget_seconds=narration_remaining_seconds or 0.0,
                provider_error_class=error_class,
                provider_error_reason=error_reason,
            )
        except (AttributeError, ConnectionError, TypeError, ValueError) as exc:
            error_class, error_reason = _log_narration_failure(
                exc,
                budget_seconds=narration_remaining_seconds,
            )
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=deterministic_claims,
                warning=(
                    "Foundry narration provider is unavailable; deterministic cited "
                    "evidence is shown instead."
                ),
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
                degraded_reason="unavailable",
                narration_budget_seconds=narration_remaining_seconds or 0.0,
                provider_error_class=error_class,
                provider_error_reason=error_reason,
            )
        else:
            used_refs = {
                str(ref)
                for claim in claims
                for ref in claim.get("evidence_refs") or []
            }
            used_retained_by_id: dict[str, dict[str, Any]] = {}
            for item in [
                *synthesis_input["retained_evidence"],
                *current_retained_evidence,
            ]:
                if not isinstance(item, Mapping):
                    continue
                evidence_id = str(item.get("evidence_id") or "")
                if evidence_id in used_refs and evidence_id not in used_retained_by_id:
                    used_retained_by_id[evidence_id] = dict(item)
            synthesis = ExecutiveSynthesis(
                status="synthesized",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=claims,
                used_retained_evidence=list(used_retained_by_id.values()),
                mode="foundry",
                narration="\n\n".join(
                    str(claim.get("summary") or "").strip()
                    for claim in claims
                    if str(claim.get("summary") or "").strip()
                ),
                agent=str(getattr(answer, "agent_name", "") or "").strip(),
                narration_budget_seconds=narration_remaining_seconds or 0.0,
            )
        self._record_stage_metric("synthesis", stage_started)
        self._record_synthesis_metric(synthesis)
        return synthesis

    @staticmethod
    def _deterministic_cve_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        tool_results: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build one exact-CVE claim from governed tool payloads and citations."""

        if (
            snapshot is None
            or snapshot.page_kind != "cve_detail"
            or not snapshot.page_id.casefold().startswith("cve:")
        ):
            return []
        cve_id = canonical_cve_id(snapshot.page_id.split(":", 1)[1])
        mentioned = {
            match.upper()
            for match in re.findall(
                r"\bCVE-\d{4}-\d{4,}\b",
                question,
                flags=re.IGNORECASE,
            )
        }
        if not cve_id or (mentioned and mentioned != {cve_id}):
            return []

        detail_data: Any = None
        exposure_data: Any = None
        exposure_status = ""
        evidence_refs: list[str] = []
        for result in tool_results:
            tool = str(result.get("tool") or "")
            arguments = result.get("arguments")
            if not isinstance(arguments, Mapping):
                continue
            if tool == "cve_detail":
                if canonical_cve_id(arguments.get("cve_id")) != cve_id:
                    continue
                detail_data = result.get("data")
            elif tool == "cve_exposure":
                if canonical_cve_id(arguments.get("query")) != cve_id:
                    continue
                exposure_data = result.get("data")
                exposure_status = str(result.get("status") or "")
            else:
                continue
            call_id = str(result.get("call_id") or "")
            evidence_refs.extend(
                str(item.get("evidence_id") or f"tool:{call_id}:{index}")
                for index, item in enumerate(result.get("evidence") or [])
                if isinstance(item, Mapping)
            )

        evidence_refs = list(dict.fromkeys(ref for ref in evidence_refs if ref))
        if not evidence_refs:
            return []
        narrative = deterministic_cve_narrative(
            cve_id,
            detail_data=detail_data,
            exposure_data=exposure_data,
            exposure_status=exposure_status,
            snapshot_coverage=snapshot.coverage.model_dump(mode="json"),
            source_statuses={
                record.source: record.status
                for record in snapshot.freshness
            },
        )
        if not narrative:
            return []
        freshness = snapshot_claim_freshness(snapshot)
        uncertainty = (
            [] if snapshot.coverage.complete else ["visible subset is incomplete"]
        )
        if freshness != "fresh":
            uncertainty.append(f"CVE source freshness is {freshness}.")
        return [
            {
                "finding_id": (
                    "cve:"
                    + hashlib.sha256(
                        f"{cve_id}:{'|'.join(evidence_refs)}".encode()
                    ).hexdigest()[:24]
                ),
                "summary": narrative,
                "evidence_refs": evidence_refs,
                "confidence": (
                    "high" if snapshot.coverage.complete else "medium"
                ),
                "freshness": freshness,
                "uncertainty": uncertainty,
                "actionable": False,
                "next_check": "Review the cited scoped CVE evidence before remediation.",
            }
        ]

    @staticmethod
    def _deterministic_patch_claims(
        *,
        snapshot: EvidenceSnapshotV2 | None,
        tool_results: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build exact patch/KB claims from dedicated server-corpus tools."""

        if snapshot is None or snapshot.page_kind not in {
            "patch",
            "patch_priorities",
            "kb_detail",
        }:
            return []
        for result in tool_results:
            tool = str(result.get("tool") or "")
            if tool not in {"patch_priorities", "kb_detail"}:
                continue
            if result.get("status") != STATUS_OK:
                continue
            data = result.get("data")
            if not isinstance(data, Mapping):
                continue
            call_id = str(result.get("call_id") or "")
            evidence_refs = [
                str(item.get("evidence_id") or f"tool:{call_id}:{index}")
                for index, item in enumerate(result.get("evidence") or [])
                if isinstance(item, Mapping)
            ]
            if not evidence_refs:
                continue
            warning = str(result.get("warning") or "").strip()
            freshness = snapshot_claim_freshness(snapshot)
            uncertainty = []
            if not snapshot.coverage.complete:
                uncertainty.append("Visible patch coverage is incomplete.")
            if freshness != "fresh":
                uncertainty.append(f"Patch source freshness is {freshness}.")
            if warning:
                uncertainty.append(warning)

            if tool == "patch_priorities":
                top = data.get("top_priority")
                if not isinstance(top, Mapping):
                    continue
                kb_id = str(top.get("kb_id") or "").strip()
                product = str(top.get("product") or "").strip()
                published_at = str(top.get("published_at") or "").strip()
                action = str(top.get("recommended_action") or "").strip()
                if not all((kb_id, product, published_at, action)):
                    uncertainty.append(
                        "Top-KB catalog metadata is incomplete; missing facts were not inferred."
                    )
                ranking_basis = str(data.get("ranking_basis") or "").strip()
                summary = (
                    f"The server patch corpus ranks **{kb_id or 'an unknown KB'}** "
                    f"first with priority score **{top.get('priority_score', 'unknown')}** "
                    f"and expected risk reduction "
                    f"**{top.get('expected_risk_reduction', 'unknown')}**. "
                    f"Ranking basis: {ranking_basis or 'server-defined priority order'}. "
                    f"It covers **{top.get('cve_count', 0)} CVEs**, "
                    f"**{top.get('affected_server_count', 0)} servers**, "
                    f"**{top.get('affected_application_count', 0)} applications**, "
                    f"and **{top.get('affected_business_service_count', 0)} business services**. "
                    f"Affected product: **{product or 'unknown'}**. "
                    f"Publication date: **{published_at or 'unknown'}**. "
                    f"Recommended action: {action or 'unavailable'}"
                )
            else:
                kb_id = str(data.get("kb_id") or "").strip()
                product = str(
                    data.get("product") or data.get("title") or ""
                ).strip()
                published_at = str(data.get("published_at") or "").strip()
                summary = (
                    f"The server KB catalog reports **{kb_id or 'an unknown KB'}** "
                    f"for **{product or 'an unknown product'}**, published "
                    f"**{published_at or 'on an unknown date'}**, with severity "
                    f"**{data.get('severity', 'Unknown')}** and "
                    f"**{data.get('cve_count', 0)} associated CVEs**. "
                    f"Current affected-server count: "
                    f"**{data.get('affected_server_count', 0)}**."
                )

            return [
                {
                    "finding_id": (
                        "patch:"
                        + hashlib.sha256(
                            f"{tool}:{'|'.join(evidence_refs)}".encode()
                        ).hexdigest()[:24]
                    ),
                    "summary": summary[:1000],
                    "evidence_refs": list(dict.fromkeys(evidence_refs)),
                    "confidence": (
                        "high"
                        if snapshot.coverage.complete and not uncertainty
                        else "medium"
                    ),
                    "freshness": freshness,
                    "uncertainty": list(dict.fromkeys(uncertainty)),
                    "actionable": False,
                    "next_check": (
                        "Refresh and review the cited server KB/patch corpus "
                        "before approving or executing remediation."
                    ),
                }
            ]
        return []

    @staticmethod
    def _deterministic_fabric_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Answer Fabric starters from exact retained page facts."""

        if (
            snapshot is None
            or snapshot.page_kind != "connections_fabric"
            or snapshot.page_id != "fabric-medallion"
        ):
            return []
        starter_kind = _fabric_starter_kind(question)
        layer_question = starter_kind == "layers"
        gap_question = starter_kind == "gaps"
        freshness_priority = {
            "fresh": 0,
            "partial": 1,
            "stale": 2,
            "unavailable": 3,
        }

        def source_freshness(source: str) -> str:
            statuses = [
                item.status
                for item in snapshot.freshness
                if item.source == source
            ]
            return max(
                statuses,
                default="unavailable",
                key=freshness_priority.get,
            )

        def retained_rows(claim_type: str, source: str):
            return [
                item
                for item in retained_evidence
                if (
                    item.get("claim_type") == claim_type
                    and item.get("source")
                    == f"page_snapshot:{snapshot.page_kind}:{source}"
                    and item.get("evidence_id")
                    and isinstance(item.get("data"), Mapping)
                )
            ]

        if layer_question:
            by_layer: dict[str, Mapping[str, Any]] = {}
            for item in retained_rows(
                "medallion_layer",
                "fabric/medallion-layers",
            ):
                data = item["data"]
                layer = str(data.get("layer") or "").casefold()
                healthy = data.get("healthy")
                total = data.get("total")
                if (
                    layer not in {"bronze", "silver", "gold"}
                    or not isinstance(healthy, int)
                    or isinstance(healthy, bool)
                    or not isinstance(total, int)
                    or isinstance(total, bool)
                    or healthy < 0
                    or total < 0
                    or healthy > total
                ):
                    continue
                if layer in by_layer:
                    return []
                by_layer[layer] = item
            if set(by_layer) != {"bronze", "silver", "gold"}:
                return []
            claims = []
            for layer in ("bronze", "silver", "gold"):
                item = by_layer[layer]
                data = item["data"]
                healthy = data["healthy"]
                total = data["total"]
                summary = (
                    f"{layer.title()} is healthy-empty with 0 healthy of 0 "
                    "total datasets; this does not establish an outage."
                    if total == 0
                    else (
                        f"{layer.title()} layer health is {healthy} of {total} "
                        "datasets healthy."
                    )
                )
                freshness = source_freshness("fabric/medallion-layers")
                claims.append(
                    {
                        "finding_id": f"fabric:{layer}-layer-health",
                        "summary": summary,
                        "evidence_refs": [str(item["evidence_id"])],
                        "confidence": (
                            "high"
                            if (
                                item.get("status") == STATUS_OK
                                and freshness == "fresh"
                                and snapshot.coverage.complete
                            )
                            else "medium"
                        ),
                        "freshness": freshness,
                        "uncertainty": (
                            []
                            if freshness == "fresh"
                            else [f"Fabric {layer} evidence freshness is {freshness}"]
                        ),
                        "actionable": False,
                        "next_check": (
                            "Refresh the cited Fabric layer evidence before "
                            "drawing a deployment or remediation conclusion."
                        ),
                    }
                )
            return claims

        if gap_question:
            governance_rows = retained_rows(
                "fabric_governance",
                "fabric/governance",
            )
            capacity_rows = retained_rows(
                "fabric_capacity",
                "fabric/capabilities",
            )
            claims = []
            if len(governance_rows) == 1:
                item = governance_rows[0]
                data = item["data"]
                values = [
                    data.get("ownership_gap_count"),
                    data.get("tag_gap_count"),
                    data.get("referential_integrity_blockers"),
                ]
                if all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in values
                ):
                    freshness = source_freshness("fabric/governance")
                    claims.append(
                        {
                            "finding_id": "fabric:governance-gaps",
                            "summary": (
                                f"Fabric governance reports {values[0]} ownership "
                                f"gaps, {values[1]} tag gaps, and {values[2]} "
                                "referential-integrity blockers. These are "
                                "aggregate counts; the retained page evidence "
                                "does not identify which individual datasets "
                                "have those gaps."
                            ),
                            "evidence_refs": [str(item["evidence_id"])],
                            "confidence": (
                                "high"
                                if (
                                    item.get("status") == STATUS_OK
                                    and freshness == "fresh"
                                    and snapshot.coverage.complete
                                )
                                else "medium"
                            ),
                            "freshness": freshness,
                            "uncertainty": [
                                "Dataset-level governance attribution is unavailable."
                            ],
                            "actionable": False,
                            "next_check": (
                                "Inspect cited dataset-level governance evidence "
                                "before assigning remediation."
                            ),
                        }
                    )
            if len(capacity_rows) == 1:
                item = capacity_rows[0]
                data = item["data"]
                lineage_present = bool(str(data.get("lineage_ref") or "").strip())
                freshness = source_freshness("fabric/capabilities")
                claims.append(
                    {
                        "finding_id": "fabric:lineage-coverage",
                        "summary": (
                            "A native Fabric lineage reference is available, but "
                            "the retained page evidence does not enumerate "
                            "dataset-level lineage gaps."
                            if lineage_present
                            else (
                                "No native Fabric lineage reference is available "
                                "in the retained page evidence, so dataset-level "
                                "lineage gaps cannot be identified."
                            )
                        ),
                        "evidence_refs": [str(item["evidence_id"])],
                        "confidence": (
                            "high"
                            if (
                                item.get("status") == STATUS_OK
                                and freshness == "fresh"
                                and snapshot.coverage.complete
                            )
                            else "medium"
                        ),
                        "freshness": freshness,
                        "uncertainty": [
                            "Dataset-level lineage-gap evidence is unavailable."
                        ],
                        "actionable": False,
                        "next_check": (
                            "Open the cited native lineage view before drawing "
                            "a dataset-level lineage conclusion."
                        ),
                    }
                )
            return claims
        return []

    @staticmethod
    def _deterministic_resource_health_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Answer the three Resource Health starters from exact page facts."""

        if (
            snapshot is None
            or snapshot.page_kind != "resource_health"
            or snapshot.page_id != "resource-health"
        ):
            return []
        starter_kind = _resource_health_starter_kind(question)
        if starter_kind is None:
            return []

        resource_rows = [
            item
            for item in retained_evidence
            if (
                item.get("claim_type") == "resource_utilization"
                and item.get("source")
                == "page_snapshot:resource_health:resource-health/metrics"
                and item.get("evidence_id")
                and isinstance(item.get("data"), Mapping)
            )
        ]
        coverage_rows = [
            item
            for item in retained_evidence
            if (
                item.get("claim_type") == "resource_metric_coverage"
                and item.get("source")
                == "page_snapshot:resource_health:resource-health/metrics"
                and item.get("evidence_id")
                and isinstance(item.get("data"), Mapping)
            )
        ]
        if (
            len(resource_rows) != snapshot.coverage.visible_count
            or len(coverage_rows) != 1
        ):
            return []

        statuses = {"healthy": 0, "warning": 0, "critical": 0, "unknown": 0}
        by_resource_id: dict[str, Mapping[str, Any]] = {}
        resource_names: set[str] = set()
        for item in resource_rows:
            data = item["data"]
            name = str(data.get("resource_name") or "").strip()
            status = str(data.get("status") or "").casefold()
            resource_id = str(item.get("resource_id") or "").casefold()
            if (
                not name
                or status not in statuses
                or not resource_id
                or resource_id in by_resource_id
                or name.casefold() in resource_names
            ):
                return []
            statuses[status] += 1
            by_resource_id[resource_id] = item
            resource_names.add(name.casefold())

        freshness_priority = {
            "fresh": 0,
            "partial": 1,
            "stale": 2,
            "unavailable": 3,
        }
        freshness = max(
            (
                item.status
                for item in snapshot.freshness
                if item.source == "resource-health/metrics"
            ),
            default="unavailable",
            key=freshness_priority.get,
        )
        evidence_refs = sorted(
            str(item["evidence_id"]) for item in resource_rows
        )
        coverage_ref = str(coverage_rows[0]["evidence_id"])
        coverage_data = coverage_rows[0]["data"]
        unavailable_metrics = sorted(
            {
                str(value)
                for value in coverage_data.get("unavailable_metrics") or []
                if str(value)
            }
        )
        metric_uncertainty = [
            (
                f"{metric} is unavailable in the retained page snapshot; "
                "absence is not treated as zero."
            )
            for metric in unavailable_metrics
        ]
        counts = (
            f"{len(resource_rows)} utilization observations: "
            f"{statuses['healthy']} healthy, {statuses['warning']} warning, "
            f"{statuses['critical']} critical, and {statuses['unknown']} unknown"
        )
        common = {
            # Canonicalization proves scope and identity, not the truth of
            # browser-supplied metric values. These remain observations.
            "confidence": "medium",
            "freshness": freshness,
            "actionable": False,
            "next_check": (
                "Refresh Resource Health and correlate separate Azure "
                "availability, Service Health, or service-mapping evidence "
                "before taking action."
            ),
        }

        if starter_kind == "incidents":
            return [{
                "finding_id": "resource-health:incident-correlation",
                "summary": (
                    f"The retained Resource Health page reports {counts}. "
                    "It contains no incident records, Azure availability-status "
                    "records, or Service Health advisory correlation, so no "
                    "incident relationship can be established."
                ),
                "evidence_refs": [*evidence_refs, coverage_ref],
                "uncertainty": [
                    *metric_uncertainty,
                    (
                        "Incident, Azure availability-status, and Service Health "
                        "advisory evidence are outside this retained page snapshot."
                    ),
                ],
                **common,
            }]

        if starter_kind == "services":
            return [{
                "finding_id": "resource-health:service-impact",
                "summary": (
                    f"The retained Resource Health page reports {counts}. "
                    "No service-to-resource mapping or service-impact record is "
                    "present, so no impacted service can be named from this "
                    "snapshot."
                ),
                "evidence_refs": [*evidence_refs, coverage_ref],
                "uncertainty": [
                    *metric_uncertainty,
                    "Service-to-resource impact mapping is unavailable.",
                ],
                **common,
            }]

        unknown_rows = [
            item
            for item in resource_rows
            if str(item["data"].get("status") or "").casefold() == "unknown"
        ]
        unknown_detail = ""
        if unknown_rows:
            names = ", ".join(sorted(
                str(item["data"]["resource_name"])
                for item in unknown_rows
            ))
            unknown_detail = (
                f" {names} is unknown because the retained page has no CPU "
                "observation; unknown is not treated as unhealthy or as zero."
            )
        warning_or_critical = [
            item
            for item in resource_rows
            if str(item["data"].get("status") or "").casefold()
            in {"warning", "critical"}
        ]
        anomaly_detail = (
            (
                " No anomaly determination is possible because retained "
                "Resource Health coverage is incomplete or unavailable."
            )
            if (
                not resource_rows
                and (
                    not snapshot.coverage.complete
                    or freshness == "unavailable"
                )
            )
            else (
                " No retained resource is classified as warning or critical, "
                "but coverage is partial, so unretained resources are not "
                "assessed."
            )
            if not snapshot.coverage.complete and not warning_or_critical
            else " No resource is classified as warning or critical."
            if not warning_or_critical
            else " Resource pressure classifications are: " + "; ".join(
                (
                    f"{item['data']['resource_name']} is "
                    f"{item['data']['status']} at "
                    f"{item['data']['cpu_percent']}% CPU"
                )
                for item in sorted(
                    warning_or_critical,
                    key=lambda row: str(row["resource_id"]),
                )
            )
            + (
                ". Retained classifications cover only the visible subset."
                if not snapshot.coverage.complete
                else "."
            )
        )
        return [{
            "finding_id": "resource-health:utilization-anomalies",
            "summary": (
                f"The retained Resource Health page reports {counts}. "
                f"{anomaly_detail}{unknown_detail}"
            ),
            "evidence_refs": [*evidence_refs, coverage_ref],
            "uncertainty": metric_uncertainty,
            **common,
        }]

    @staticmethod
    def _deterministic_inventory_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Answer exact Inventory starters from parity-checked page facts."""

        if (
            snapshot is None
            or snapshot.page_kind != "inventory"
            or snapshot.page_id not in _INVENTORY_PAGE_CONTRACT
        ):
            return []
        starter_kind = inventory_starter_kind(question)
        if starter_kind is None:
            return []
        family, source, claim_type = _INVENTORY_PAGE_CONTRACT[snapshot.page_id]
        rows = [
            item
            for item in retained_evidence
            if (
                item.get("claim_type") == claim_type
                and item.get("source") == f"page_snapshot:inventory:{source}"
                and item.get("evidence_id")
                and isinstance(item.get("data"), Mapping)
            )
        ]
        if len(rows) != snapshot.coverage.visible_count:
            return []
        freshness = snapshot_claim_freshness(snapshot)
        evidence_refs = sorted(str(item["evidence_id"]) for item in rows)
        if not evidence_refs and snapshot.coverage.visible_count == 0:
            evidence_refs = [
                str(item["evidence_id"])
                for item in retained_evidence
                if (
                    item.get("claim_type") == "page_context"
                    and item.get("source")
                    == f"page_snapshot:inventory:{source}"
                    and item.get("evidence_id")
                )
            ]
        if not evidence_refs:
            return []
        unit = {
            "os": "OS groups",
            "software": "software groups",
            "paas": "Azure resource groups",
        }[family]
        coverage_text = (
            f"complete at {snapshot.coverage.visible_count} of "
            f"{snapshot.coverage.total_count} {unit}"
            if snapshot.coverage.complete
            else (
                f"partial at {snapshot.coverage.visible_count} visible of "
                f"{snapshot.coverage.total_count} {unit}"
            )
        )
        common = {
            "confidence": "medium",
            "freshness": freshness,
            "evidence_refs": evidence_refs[:32],
            "actionable": False,
            "next_check": (
                "Refresh the cited Inventory source and review the exact "
                "resource identities before taking governed action."
            ),
        }
        uncertainty = (
            []
            if snapshot.coverage.complete and freshness == "fresh"
            else [
                *(
                    []
                    if snapshot.coverage.complete
                    else ["Visible Inventory coverage is incomplete."]
                ),
                *(
                    []
                    if freshness == "fresh"
                    else [f"Inventory evidence freshness is {freshness}."]
                ),
            ]
        )
        if starter_kind == "coverage":
            return [{
                "finding_id": f"inventory:{family}-coverage",
                "summary": (
                    f"Visible Inventory coverage is {coverage_text}. "
                    "This describes the retained page grouping and its "
                    "parity-checked scoped Inventory read; it does not imply "
                    "coverage for unavailable source families."
                ),
                "uncertainty": uncertainty,
                **common,
            }]

        if family == "os":
            lifecycle_counts: dict[str, int] = {}
            machine_count = 0
            for item in rows:
                data = item["data"]
                count = int(data["machine_count"])
                machine_count += count
                status = str(data["lifecycle_status"])
                lifecycle_counts[status] = lifecycle_counts.get(status, 0) + count
            lifecycle = ", ".join(
                f"{count} {status}"
                for status, count in sorted(lifecycle_counts.items())
            )
            summary = (
                f"The retained Inventory view contains {len(rows)} OS groups "
                f"representing {machine_count} machines ({lifecycle} by "
                "lifecycle status). These are inventory and lifecycle facts, "
                "not live availability or utilization health."
            )
        elif family == "software":
            installs = sum(int(item["data"]["install_count"]) for item in rows)
            unlinked = sum(int(item["data"]["unlinked_count"]) for item in rows)
            summary = (
                f"The retained Inventory view contains {len(rows)} software "
                f"groups representing {installs} installations, including "
                f"{unlinked} unlinked installations. This is software "
                "inventory coverage, not vulnerability or runtime health."
            )
        else:
            resources = sum(int(item["data"]["resource_count"]) for item in rows)
            resource_types = len({
                str(item["data"]["resource_type"]).casefold()
                for item in rows
            })
            summary = (
                f"The retained Inventory view contains {len(rows)} Azure "
                f"resource groups representing {resources} resources across "
                f"{resource_types} resource types. This is inventory coverage, "
                "not live Resource Health status."
            )
        return [{
            "finding_id": f"inventory:{family}-visible-health",
            "summary": summary,
            "uncertainty": [
                *uncertainty,
                (
                    "Live availability, utilization, and Service Health "
                    "evidence are outside this Inventory snapshot."
                ),
            ],
            **common,
        }]

    @staticmethod
    def _deterministic_page_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build direct factual claims only from citation-closed current rows."""

        if snapshot is None:
            return []
        if _is_unsubmitted_predeploy_snapshot(snapshot):
            return [{
                "finding_id": "page:predeploy-no-assessment",
                "summary": (
                    "No pre-deployment assessment is loaded or submitted in "
                    "this view, so predicted risk, impacted services, and "
                    "governed remediation requirements cannot be determined."
                ),
                "evidence_refs": [COVERAGE_CITATION_ID],
                "confidence": "low",
                "freshness": "unavailable",
                "uncertainty": [
                    (
                        "Assessment evidence is unavailable because no "
                        "assessment result exists to analyze."
                    )
                ],
                "actionable": False,
                "next_check": (
                    "Submit and review a proposed-change assessment before "
                    "drawing any impact, risk, or remediation conclusion."
                ),
            }]
        empty_page_kind = _complete_empty_page_kind(snapshot)
        if empty_page_kind is not None:
            freshness = snapshot_claim_freshness(snapshot)
            if empty_page_kind == "changes":
                summary = (
                    "No correlated changes are visible near active situations "
                    "in the current authorized scope. This does not establish "
                    "that no changes occurred."
                )
                uncertainty = [
                    "Temporal proximity is correlation, not causation."
                ]
                if freshness != "fresh":
                    uncertainty.append(
                        f"Changes evidence freshness is {freshness}"
                    )
                next_check = (
                    "Refresh the cited incident timeline evidence before "
                    "drawing a change-correlation conclusion."
                )
            else:
                freshness_caveat = (
                    ""
                    if freshness == "fresh"
                    else (
                        " This does not confirm source health because Situations "
                        f"evidence freshness is {freshness}."
                    )
                )
                summary = (
                    "No active situations are visible in the current authorized "
                    f"scope.{freshness_caveat}"
                )
                uncertainty = (
                    []
                    if freshness == "fresh"
                    else [f"Situations evidence freshness is {freshness}"]
                )
                next_check = (
                    "Refresh the Situations source before treating the empty "
                    "queue as a source-health confirmation."
                )
            return [{
                "finding_id": f"page:{empty_page_kind}-empty",
                "summary": summary,
                "evidence_refs": [COVERAGE_CITATION_ID],
                "confidence": "high" if freshness == "fresh" else "low",
                "freshness": freshness,
                "uncertainty": uncertainty,
                "actionable": False,
                "next_check": next_check,
            }]
        if not retained_evidence:
            return []
        by_original_id = {
            str(item.get("original_evidence_id") or ""): item
            for item in retained_evidence
            if item.get("original_evidence_id")
        }
        material_refs = {
            reference
            for claim in snapshot.material_claims
            if (
                snapshot.coverage.complete
                or not claim.requires_complete_coverage
            )
            for reference in claim.evidence_refs
        }
        retained_material_refs = material_refs.intersection(by_original_id)
        candidates = [
            item
            for item in retained_evidence
            if (
                not material_refs
                or str(item.get("original_evidence_id") or "")
                in retained_material_refs
            )
            and (item.get("selected") or item.get("direct"))
        ]
        severity_priority = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
            "unknown": 4,
        }

        def retained_severity(item: Mapping[str, Any]) -> str:
            severity = str(item.get("severity") or "unknown").casefold()
            if severity != "unknown":
                return severity
            data = item.get("data")
            if isinstance(data, Mapping):
                reported = str(data.get("severity") or "").casefold()
                if reported in severity_priority:
                    return reported
            return "unknown"

        candidates.sort(
            key=lambda item: (
                severity_priority.get(
                    retained_severity(item),
                    4,
                ),
                str(item.get("evidence_id") or ""),
            )
        )
        question_terms = {
            term
            for term in re.findall(r"[a-z0-9][a-z0-9_.-]+", question.casefold())
            if len(term) > 2
        }
        material_markers = (
            "count",
            "total",
            "visible",
            "rank",
            "priority",
            "score",
            "date",
            "_at",
            "product",
            "target",
            "version",
            "kb_id",
            "cve_id",
            "title",
            "name",
            "severity",
            "detail",
            "resource",
            "owner",
            "type",
            "affected_traffic",
            "vulnerability_exposure",
            "application",
            "business_service",
        )
        claims: list[dict[str, Any]] = []
        for item in candidates:
            data = item.get("data")
            if not isinstance(data, Mapping):
                continue
            facts: list[tuple[str, Any]] = []
            for key, value in sorted(data.items()):
                normalized_key = str(key).casefold()
                value_text = (
                    ", ".join(str(part) for part in value)
                    if isinstance(value, list)
                    else str(value)
                ).strip()
                if not value_text:
                    continue
                if not (
                    any(marker in normalized_key for marker in material_markers)
                    or any(term in normalized_key for term in question_terms)
                    or any(term in value_text.casefold() for term in question_terms)
                ):
                    continue
                facts.append((str(key), value_text))
                if len(facts) >= 8:
                    break
            if not facts:
                continue
            subject = (
                str(data.get("kb_id") or data.get("title") or "").strip()
                or snapshot.page_id
            )
            rendered = "; ".join(
                f"{key.replace('_', ' ')} {value}"
                for key, value in facts
            )
            evidence_id = str(item.get("evidence_id") or "")
            if not evidence_id:
                continue
            uncertainty = []
            if not snapshot.coverage.complete:
                uncertainty.append("visible subset is incomplete")
            claims.append(
                {
                    "finding_id": (
                        "page:"
                        + hashlib.sha256(evidence_id.encode()).hexdigest()[:24]
                    ),
                    "summary": (
                        f"The current {snapshot.page_id} page reports for "
                        f"{subject}: {rendered}."
                    )[:1000],
                    "evidence_refs": [evidence_id],
                    "confidence": (
                        "high"
                        if (
                            item.get("quality") == "high"
                            and item.get("status") == STATUS_OK
                            and snapshot.coverage.complete
                        )
                        else "medium"
                    ),
                    "freshness": (
                        "fresh"
                        if item.get("status") == STATUS_OK
                        else "partial"
                    ),
                    "uncertainty": uncertainty,
                    "actionable": False,
                    "next_check": "Recheck the cited page evidence after refresh.",
                }
            )
            if len(claims) >= 8:
                break
        return claims

    @staticmethod
    def _deterministic_service_status_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Preserve cited service degradation truth without model paraphrase."""

        if snapshot is None or snapshot.page_kind != "service_detail":
            return []
        lowered = " ".join(question.casefold().split())
        if any(term in lowered for term in ("depend", "impact", "blast radius")):
            requested_section = "impact"
        elif "risk" in lowered:
            requested_section = "risk"
        else:
            return []

        for item in retained_evidence:
            if str(item.get("claim_type") or "") != "service_section_status":
                continue
            data = item.get("data")
            if not isinstance(data, Mapping):
                continue
            if (
                str(data.get("section") or "").casefold() != requested_section
                or str(data.get("availability") or "").casefold() != "unavailable"
            ):
                continue
            detail = str(data.get("detail") or "").strip()
            evidence_id = str(item.get("evidence_id") or "")
            if not detail or not evidence_id:
                continue
            return [{
                "finding_id": (
                    "service-status:"
                    + hashlib.sha256(evidence_id.encode()).hexdigest()[:24]
                ),
                "summary": detail,
                "evidence_refs": [evidence_id],
                "confidence": "high",
                "freshness": "fresh",
                "uncertainty": [
                    "The requested service section is unavailable."
                ],
                "actionable": False,
                "next_check": (
                    "Refresh the cited service section before drawing a "
                    "dependency or risk conclusion."
                ),
            }]
        return []

    @staticmethod
    def _deterministic_twin_status_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Answer Twin coverage/risk questions from exact retained page status."""

        if snapshot is None or snapshot.page_kind != "twin":
            return []
        lowered = " ".join(question.casefold().split())
        if "risk" in lowered:
            detail_field = "risk_detail"
        elif any(
            term in lowered
            for term in (
                "affected",
                "business service",
                "depend",
                "impact",
                "topology",
            )
        ):
            detail_field = "dependency_detail"
        else:
            return []

        for item in retained_evidence:
            if str(item.get("claim_type") or "") != "twin_status":
                continue
            data = item.get("data")
            if not isinstance(data, Mapping):
                continue
            detail = str(data.get(detail_field) or "").strip()
            evidence_id = str(item.get("evidence_id") or "")
            if not detail or not evidence_id:
                continue
            return [{
                "finding_id": (
                    "twin-status:"
                    + hashlib.sha256(evidence_id.encode()).hexdigest()[:24]
                ),
                "summary": detail,
                "evidence_refs": [evidence_id],
                "confidence": "medium",
                "freshness": "fresh",
                "uncertainty": (
                    ["The current Twin has no relationship evidence."]
                    if (
                        detail_field == "dependency_detail"
                        and int(data.get("relationship_count") or 0) == 0
                    )
                    else []
                ),
                "actionable": False,
                "next_check": (
                    "Refresh the cited Twin snapshot before drawing a "
                    "dependency, impact, or risk conclusion."
                ),
            }]
        return []

    @staticmethod
    def _deterministic_finops_savings_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Aggregate cited savings by business service before optional narration."""

        if (
            snapshot is None
            or snapshot.page_kind != "finops"
            or snapshot.page_id != "finops"
            or not retained_evidence
        ):
            return []
        if question.strip() != "Which business services own the most savings?":
            return []

        grouped: dict[
            tuple[str, str],
            list[tuple[float, str]],
        ] = {}
        display_names: dict[tuple[str, str], tuple[str, str]] = {}
        for item in retained_evidence:
            if str(item.get("claim_type") or "").casefold() != "savings_opportunity":
                continue
            if str(item.get("status") or "") not in {STATUS_OK, "partial"}:
                continue
            data = item.get("data")
            if not isinstance(data, Mapping):
                continue
            service = str(data.get("business_service") or "").strip()
            currency = str(data.get("currency") or "").strip()
            amount = data.get("annual_savings")
            evidence_id = str(item.get("evidence_id") or "")
            if (
                not service
                or not currency
                or not evidence_id
                or isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or not math.isfinite(float(amount))
                or float(amount) < 0
            ):
                continue
            key = (service.casefold(), currency.casefold())
            display_names.setdefault(key, (service, currency))
            grouped.setdefault(key, []).append((float(amount), evidence_id))
        if not grouped:
            return []
        if len({currency for _service, currency in grouped}) != 1:
            return []
        if any(len(values) > 5 for values in grouped.values()):
            return []

        ranked = sorted(
            grouped.items(),
            key=lambda item: (
                -math.fsum(amount for amount, _reference in item[1]),
                item[0],
            ),
        )
        if (
            len(ranked) > 1
            and math.isclose(
                math.fsum(amount for amount, _reference in ranked[0][1]),
                math.fsum(amount for amount, _reference in ranked[1][1]),
            )
        ):
            return []
        key, values = ranked[0]
        ordered = sorted(values, key=lambda item: (-item[0], item[1]))
        service, currency = display_names[key]
        total = math.fsum(amount for amount, _reference in ordered)

        def render_amount(value: float) -> str:
            return format(value, ".15g")

        evidence_refs = [reference for _amount, reference in ordered]
        rendered_values = " + ".join(
            f"{currency} {render_amount(amount)}" for amount, _reference in ordered
        )
        freshness = snapshot_claim_freshness(snapshot)
        uncertainty = []
        if not snapshot.coverage.complete:
            uncertainty.append("visible subset is incomplete")
        if freshness != "fresh":
            uncertainty.append(f"FinOps evidence freshness is {freshness}")
        return [
            {
                "finding_id": (
                    "finops:"
                    + hashlib.sha256("|".join(evidence_refs).encode()).hexdigest()[:24]
                ),
                "summary": (
                    f"The current FinOps page shows business service {service} "
                    "owns the most identified annual savings: "
                    f"{rendered_values} = {currency} {render_amount(total)} "
                    f"across {len(ordered)} quantified opportunities."
                ),
                "evidence_refs": evidence_refs,
                "confidence": "high" if snapshot.coverage.complete else "medium",
                "freshness": freshness,
                "uncertainty": uncertainty,
                "actionable": False,
                "next_check": (
                    "Refresh the cited FinOps opportunities before using the "
                    "aggregate in a financial decision."
                ),
            }
        ]

    @staticmethod
    def _deterministic_overview_ranking_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Rank the four visible Overview signals from retained page facts."""

        if (
            snapshot is None
            or snapshot.page_id != "operations-overview"
            or snapshot.page_kind not in {"overview", "resource"}
            or not retained_evidence
        ):
            return []
        lowered = " ".join(question.casefold().split())
        if not (
            "needs attention" in lowered
            or re.search(r"\brank(?:ed|ing|s)?\b", lowered)
            or "most important issue" in lowered
        ):
            return []

        evidence_refs: list[str] = []
        uncertainty: list[str] = []
        network_values: list[int] = []
        vulnerability_values: list[int] = []
        p1_situations = 0
        unhealthy_connections = 0

        def count_value(value: Any) -> int | None:
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            return value if value >= 0 else None

        for item in retained_evidence:
            data = item.get("data")
            evidence_id = str(item.get("evidence_id") or "")
            if not isinstance(data, Mapping) or not evidence_id:
                continue
            claim_type = str(
                item.get("claim_type") or data.get("claim_type") or ""
            ).casefold()
            if claim_type == "network_summary":
                value = count_value(data.get("gap_count"))
                if value is not None:
                    network_values.append(value)
                    evidence_refs.append(evidence_id)
            elif claim_type == "vulnerability_summary":
                value = count_value(data.get("internet_exposed_count"))
                if value is not None:
                    vulnerability_values.append(value)
                    evidence_refs.append(evidence_id)
            elif claim_type == "situation":
                evidence_refs.append(evidence_id)
                if str(data.get("priority") or "").casefold() == "p1":
                    p1_situations += 1
            elif claim_type == "subscription_connection":
                evidence_refs.append(evidence_id)
                if (
                    str(data.get("health_status") or "").casefold() == "stale"
                    or str(data.get("sync_status") or "").casefold() == "failed"
                ):
                    unhealthy_connections += 1

        def single_summary_value(
            values: Sequence[int],
            *,
            signal: str,
        ) -> int | None:
            distinct = sorted(set(values))
            if len(distinct) == 1:
                return distinct[0]
            if len(distinct) > 1:
                uncertainty.append(
                    f"Conflicting retained {signal} counts were excluded."
                )
            else:
                uncertainty.append(
                    f"The retained Overview {signal} count is unavailable."
                )
            return None

        network_control_gaps = single_summary_value(
            network_values,
            signal="network control gap",
        )
        internet_reachable_cves = single_summary_value(
            vulnerability_values,
            signal="internet-reachable CVE",
        )
        counts: list[tuple[str, str, int | None]] = [
            ("Priority situations", "P1 situations", p1_situations),
            (
                "Internet exposure",
                "internet-reachable CVEs",
                internet_reachable_cves,
            ),
            ("Network control", "network control gaps", network_control_gaps),
            ("Data health", "unhealthy connections", unhealthy_connections),
        ]
        available = [item for item in counts if item[2] is not None]
        if not available:
            return []

        comparison = "; ".join(
            (
                f"{value} {count_label}"
                if value is not None
                else f"{count_label} unavailable"
            )
            for _domain, count_label, value in counts
        )
        highest_count = max(value for _domain, _label, value in available)
        tied = [
            item for item in available if item[2] == highest_count
        ]
        if highest_count == 0 and len(available) == len(counts):
            ranking = (
                "No domain ranks above another: all four visible counts are 0."
            )
        elif len(tied) == 1:
            domain, count_label, value = tied[0]
            ranking = (
                f"{domain} is the single top visible domain with "
                f"{value} {count_label}."
            )
        else:
            domain, _count_label, value = tied[0]
            tied_domains = ", ".join(item[0] for item in tied)
            ranking = (
                f"{domain} is selected as the single top visible domain at "
                f"{value} by stable domain order because {tied_domains} tie "
                "for the highest visible count."
            )

        unavailable_sources = [
            f"{item.source} ({item.status})"
            for item in snapshot.freshness
            if item.status != "fresh"
        ]
        if unavailable_sources:
            uncertainty.append(
                "Overview sources are degraded or unavailable: "
                + ", ".join(unavailable_sources)
                + "."
            )
        if not snapshot.coverage.complete:
            uncertainty.insert(0, "visible subset is incomplete")
        ranking_basis = (
            "Ranking basis: highest available visible count across the four "
            "Overview signals"
            if len(available) < len(counts)
            else (
                "Ranking basis: highest visible count across the four "
                "Overview signals"
            )
        )
        summary = (
            f"{ranking} Visible comparison: {comparison}. {ranking_basis}. "
            "This ranking is read-only and does not approve or execute any action."
        )
        citation_ids = list(dict.fromkeys(evidence_refs))
        if not citation_ids:
            return []
        return [
            {
                "finding_id": (
                    "overview-ranking:"
                    + hashlib.sha256(
                        "|".join(citation_ids).encode()
                    ).hexdigest()[:24]
                ),
                "summary": summary[:1000],
                "evidence_refs": citation_ids,
                "confidence": "medium" if uncertainty else "high",
                "freshness": "partial" if uncertainty else "fresh",
                "uncertainty": list(dict.fromkeys(uncertainty)),
                "actionable": False,
                "next_check": (
                    "Refresh the Overview sources and compare the same four "
                    "visible counts before making a governed decision."
                ),
            }
        ]

    @staticmethod
    def _deterministic_remediation_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Answer safest-step questions from the current governed workflow."""

        lowered = question.casefold()
        if (
            snapshot is None
            or snapshot.page_kind != "remediation"
            or not all(marker in lowered for marker in ("safest", "next", "step"))
        ):
            return []

        plan_evidence = next(
            (
                item
                for item in retained_evidence
                if item.get("claim_type") == "remediation_plan"
                and (item.get("selected") or item.get("direct"))
                and isinstance(item.get("data"), Mapping)
            ),
            None,
        )
        if plan_evidence is None:
            return []
        data = plan_evidence["data"]
        recommended_step = str(data.get("recommended_step") or "").strip()
        evidence_id = str(plan_evidence.get("evidence_id") or "").strip()
        if not recommended_step or not evidence_id:
            return []

        step_label = recommended_step.replace("_", " ")
        title = str(data.get("title") or snapshot.page_id).strip()
        summary = (
            f"The current workflow's safest next governed step is "
            f"**{step_label}** for **{title}**."
        )
        approval_current = data.get("approval_current") is True
        approval_status = str(data.get("approval_status") or "").strip()
        if not approval_current:
            summary += (
                f" Current approval is {approval_status or 'not current'} "
                "and is not current."
            )

        raw_blockers = data.get("workflow_blockers")
        blockers = (
            [
                str(blocker).strip()
                for blocker in raw_blockers
                if str(blocker).strip()
            ]
            if isinstance(raw_blockers, list)
            else []
        )
        if blockers:
            rendered_blockers = []
            for blocker in blockers:
                step, separator, code = blocker.partition(":")
                if not separator:
                    code, step = blocker, ""
                label = code.replace("_", " ")
                rendered_blockers.append(
                    f"{label} at {step.replace('_', ' ')}"
                    if step
                    else label
                )
            summary += (
                " Current workflow blockers: "
                + ", ".join(rendered_blockers)
                + "."
            )
        summary += (
            " This advisory answer does not approve or execute remediation; "
            "review, approval, and any mutation remain in the governed "
            "operator workflow."
        )

        next_checks = {
            "manual_review": (
                "Have an authorized human review the cited plan and blockers."
            ),
            "review": "Review the cited plan impact and blockers.",
            "approve": (
                "Have an authorized approver review the exact snapshot and "
                "record the required decision."
            ),
            "run": (
                "Have an authorized operator revalidate and manually confirm "
                "the approved snapshot before any run."
            ),
            "verify": (
                "Review the provider verification and reconciliation state; "
                "do not rerun or change the plan from Copilot."
            ),
        }
        uncertainty = (
            []
            if snapshot.coverage.complete
            else ["Visible remediation-plan coverage is incomplete."]
        )
        return [{
            "finding_id": (
                "remediation:"
                + hashlib.sha256(evidence_id.encode()).hexdigest()[:24]
            ),
            "summary": summary[:1000],
            "evidence_refs": [evidence_id],
            "confidence": (
                "high"
                if (
                    plan_evidence.get("quality") == "high"
                    and plan_evidence.get("status") == STATUS_OK
                    and snapshot.coverage.complete
                )
                else "medium"
            ),
            "freshness": (
                "fresh"
                if plan_evidence.get("status") == STATUS_OK
                else "partial"
            ),
            "uncertainty": uncertainty,
            "actionable": False,
            "next_check": next_checks.get(
                recommended_step,
                "Review the cited workflow state with an authorized operator.",
            ),
        }]

    # -- telemetry --------------------------------------------------------

    def _record_delegation_metric(
        self,
        *,
        specialist_id: str,
        tool: str,
        status: str,
        policy_status: str,
        started: float,
        evidence_count: int,
    ) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_delegation(
            stage="specialist",
            specialist_id=specialist_id,
            tool=tool,
            status=status,
            policy_status=policy_status,
            duration_ms=(self.clock() - started) * 1000.0,
        )
        if evidence_count:
            self.telemetry.record_evidence(
                status=status,
                observation_status=OBSERVATION_CURRENT,
                count=evidence_count,
            )

    def _record_stage_metric(self, stage: str, started: float) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_stage_latency(
            stage=stage,
            duration_ms=(self.clock() - started) * 1000.0,
        )

    def _record_budget_metric(self, exhausted: bool, started: float) -> None:
        if self.telemetry is None:
            return
        duration_ms = (self.clock() - started) * 1000.0
        self.telemetry.record_budget(
            outcome="exhausted" if exhausted else "within_budget",
            duration_ms=duration_ms,
        )
        self.telemetry.record_stage_latency(stage="total", duration_ms=duration_ms)

    def _record_fallback_metric(self, reason: str) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_fallback(reason=reason or "none")

    def _record_synthesis_metric(self, synthesis: ExecutiveSynthesis) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_synthesis(
            decision=synthesis.reason,
            status=synthesis.status,
            domain_count=synthesis.domain_count,
            degraded_reason=synthesis.degraded_reason,
            narration_budget_seconds=synthesis.narration_budget_seconds,
            provider_error_class=synthesis.provider_error_class,
            provider_error_reason=synthesis.provider_error_reason,
        )

    def _record_thread_metric(self, outcome: str, durability: str) -> None:
        if self.telemetry is None:
            return
        self.telemetry.record_thread(outcome=outcome, durability=durability)

    def unsupported(
        self,
        request: InvestigationRequest,
        *,
        principal_subject: str,
        effective_scope: Scope,
        reason: str = "unsupported_intent",
    ) -> OrchestrationResult:
        """Persist an explicitly unsupported no-I/O turn."""

        requested_scope = self.policy.validate_request(request, effective_scope)
        if request.thread_id:
            thread = self.thread_store.authorize(
                request.thread_id,
                principal_subject,
                requested_scope,
                expected_revision=request.expected_thread_revision,
            )
        else:
            thread = self.thread_store.create(principal_subject, requested_scope)
        result = OrchestrationResult(
            status=STATUS_UNAVAILABLE,
            policy_status="fallback",
            fallback_reason=reason,
            uncertainty=["No supported specialist intent matched the question."],
            coverage=request.snapshot.coverage,
            citations=self._snapshot_citations(request),
            thread_id=thread.thread_id,
            thread_revision=thread.revision + 1,
        )
        return self._record_turn(
            thread,
            principal_subject=principal_subject,
            requested_scope=requested_scope,
            question=request.question,
            result=result,
            reconcile_conflict=request.expected_thread_revision is None,
        )

    def _record_turn(
        self,
        thread: InvestigationThread,
        *,
        principal_subject: str,
        requested_scope: Scope,
        question: str,
        result: OrchestrationResult,
        reconcile_conflict: bool = True,
        evidence_selection_id: str = "",
        evidence_generation_id: str = "",
        retained_evidence: Sequence[Mapping[str, Any]] = (),
    ) -> OrchestrationResult:
        """Append one turn under optimistic concurrency and report the outcome.

        Legacy callers without an expected revision reconcile one concurrent
        append for compatibility. CAS-bearing callers fail closed instead:
        after they have named the revision they observed, silently appending
        to a newer revision would violate that request contract.
        """

        payload = {
            "question": question,
            **result.model_dump(mode="json"),
            **(
                {"evidence_selection_id": evidence_selection_id}
                if evidence_selection_id
                else {}
            ),
            **(
                {"evidence_generation_id": evidence_generation_id}
                if evidence_generation_id
                else {}
            ),
            **(
                {
                    "retained_evidence": [
                        dict(item) for item in retained_evidence
                    ]
                }
                if retained_evidence
                else {}
            ),
        }
        try:
            updated = self.thread_store.append(
                thread.thread_id,
                principal_subject,
                requested_scope,
                payload,
                expected_revision=thread.revision,
            )
        except ThreadRevisionConflict as conflict:
            if not reconcile_conflict:
                raise
            reconciliation_warning = (
                "A concurrent turn superseded this thread revision."
            )
            reconciled = result.model_copy(
                update={
                    "thread_revision": conflict.current_revision + 1,
                    "uncertainty": [
                        *result.uncertainty,
                        reconciliation_warning,
                    ],
                }
            )
            reconciled_payload = {
                "question": question,
                **reconciled.model_dump(mode="json"),
                **(
                    {"evidence_selection_id": evidence_selection_id}
                    if evidence_selection_id
                    else {}
                ),
                **(
                    {"evidence_generation_id": evidence_generation_id}
                    if evidence_generation_id
                    else {}
                ),
                **(
                    {
                        "retained_evidence": [
                            dict(item) for item in retained_evidence
                        ]
                    }
                    if retained_evidence
                    else {}
                ),
            }
            updated = self.thread_store.append(
                thread.thread_id,
                principal_subject,
                requested_scope,
                reconciled_payload,
                expected_revision=conflict.current_revision,
            )
            return reconciled.model_copy(
                update={"thread_revision": updated.revision}
            )
        return result.model_copy(update={"thread_revision": updated.revision})

    def _resolve_candidate(
        self,
        request: InvestigationRequest,
        effective_scope: Scope,
    ) -> tuple[CandidatePlan | None, str, str]:
        if self.planner is None:
            return self._validated_fallback(
                request,
                effective_scope,
                "planner_unavailable",
            )
        try:
            proposal = self.planner(request)
            candidate = (
                proposal
                if isinstance(proposal, CandidatePlan)
                else CandidatePlan.model_validate(proposal)
            )
        except (PlannerTimeoutError, TimeoutError):
            return self._validated_fallback(
                request,
                effective_scope,
                "planner_timeout",
            )
        except (ConnectionError, FoundryAgentError, PlannerUnavailableError):
            return self._validated_fallback(
                request,
                effective_scope,
                "planner_unavailable",
            )
        except (TypeError, ValueError, ValidationError):
            return self._validated_fallback(
                request,
                effective_scope,
                "planner_parse_error",
            )
        try:
            return (
                self.policy.validate(
                    request=request,
                    candidate=candidate,
                    effective_scope=effective_scope,
                ),
                "accepted",
                "",
            )
        except PolicyViolation as exc:
            return self._validated_fallback(
                request,
                effective_scope,
                f"candidate_rejected:{exc.code}",
            )

    def _validated_fallback(
        self,
        request: InvestigationRequest,
        effective_scope: Scope,
        reason: str,
    ) -> tuple[CandidatePlan | None, str, str]:
        fallback = (
            self.fallback_planner(request)
            if self.fallback_planner is not None
            else _fallback_candidate(request)
        )
        if fallback is None:
            return None, "fallback", "no_safe_tool_arguments"
        validated = self.policy.validate(
            request=request,
            candidate=fallback,
            effective_scope=effective_scope,
        )
        return validated, "fallback", reason

    @staticmethod
    def _snapshot_citations(request: InvestigationRequest) -> list[Citation]:
        coverage = request.snapshot.coverage
        coverage_status = (
            STATUS_EMPTY
            if coverage.complete and coverage.total_count == 0
            else STATUS_OK
            if coverage.complete
            else "partial"
        )
        return [
            Citation(
                citation_id=COVERAGE_CITATION_ID,
                source=f"page_snapshot:{request.snapshot.page_kind}:coverage",
                status=coverage_status,
            ),
            *[
            Citation(
                citation_id=item.evidence_id,
                source=item.source,
                status=item.status,
                observed_at=item.observed_at,
                resource_id=item.resource_id,
            )
            for item in request.snapshot.evidence
            ],
        ]

    @staticmethod
    def _deduplicate_citations(citations: list[Citation]) -> list[Citation]:
        retained: dict[str, Citation] = {}
        for citation in citations:
            retained.setdefault(citation.citation_id, citation)
        return list(retained.values())

    @staticmethod
    def _uncertainty(
        request: InvestigationRequest,
        tool_results: Sequence[Mapping[str, Any]],
        *,
        budget_exhausted: bool,
    ) -> list[str]:
        uncertainty: list[str] = []
        if budget_exhausted:
            uncertainty.append("orchestration wall-clock budget exhausted")
        if not request.snapshot.coverage.complete:
            uncertainty.append("visible subset is incomplete")
        for item in request.snapshot.freshness:
            if item.status != "fresh":
                uncertainty.append(f"{item.source} freshness is {item.status}")
        for result in tool_results:
            status = str(result.get("status") or "")
            if status in {STATUS_UNAVAILABLE, STATUS_DENIED}:
                specialist = str(
                    result.get("specialist_id") or "unknown specialist"
                ).replace("_", " ")
                tool = str(result.get("tool") or "unknown tool")
                warning = " ".join(
                    str(result.get("warning") or "").split()
                )[:240]
                message = f"{specialist} {tool} tool status is {status}"
                if warning:
                    message += f": {warning}"
                uncertainty.append(message)
        return list(dict.fromkeys(uncertainty))

    @staticmethod
    def _result_status(
        tool_statuses: list[str],
        uncertainty: list[str],
        *,
        budget_exhausted: bool,
    ) -> str:
        if budget_exhausted:
            return "partial"
        if not tool_statuses or all(status == STATUS_UNAVAILABLE for status in tool_statuses):
            return STATUS_UNAVAILABLE
        if all(status == STATUS_DENIED for status in tool_statuses):
            return STATUS_DENIED
        if all(status == STATUS_EMPTY for status in tool_statuses):
            return STATUS_EMPTY
        if uncertainty or any(status != STATUS_OK for status in tool_statuses):
            return "partial"
        return STATUS_OK


def execute_from_question(
    question: str,
    *,
    scope: Scope,
    context: Any,
    principal_subject: str,
    rollout_decision: CopilotRolloutDecision,
    session_id: str = "",
    hint_tool: str = "",
    hint_arguments: Mapping[str, Any] | None = None,
    max_wall_seconds: float | None = None,
) -> OrchestrationResult:
    """Canonical orchestration adapter for question-only legacy routes.

    Intent and optional hints select a real manifest page identity before
    deterministic policy validates the candidate. Legacy session IDs map to
    opaque, principal-scoped canonical threads and never become authority.
    """

    def _safe_executor(
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: Any,
        scope: Scope,
    ) -> ToolResult:
        try:
            return call_tool(name, arguments, context=context, scope=scope)
        except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
            return ToolResult(
                status=STATUS_UNAVAILABLE,
                warning="Tool unavailable in canonical question mode",
            )

    page_kind, hinted_specialist = _question_route(
        question,
        hint_tool=hint_tool,
    )
    request = InvestigationRequest(
        question=question,
        requested_scope=scope.to_dict(),
        thread_id=_legacy_session_thread_for_execution(
            session_id,
            principal_subject,
            scope,
        ),
        snapshot=EvidenceSnapshotV2(
            page_kind=page_kind,
            page_id="copilot",
            coverage=SnapshotCoverage(
                visible_count=0,
                total_count=0,
                complete=False,
            ),
        ),
    )
    planner: Planner | None = None
    validated_hint_arguments: dict[str, Any] | None = None
    invalid_hint_reason = ""
    if hint_tool and hinted_specialist is not None:
        specialist_id = hinted_specialist.id
        try:
            validated_hint_arguments, _ = validate_tool_arguments(
                hint_tool,
                dict(hint_arguments or {}),
            )
        except ValueError:
            invalid_hint_reason = (
                "missing_required_arguments"
                if not hint_arguments
                else "invalid_hint_arguments"
            )

        def _hint_planner(_request: InvestigationRequest) -> CandidatePlan:
            return CandidatePlan(
                steps=[
                    SpecialistStep(
                        specialist_id=specialist_id,
                        tool_calls=[
                            ToolCallCandidate(
                                tool=hint_tool,
                                arguments=validated_hint_arguments or {},
                                citation_ids=[COVERAGE_CITATION_ID],
                            )
                        ],
                    )
                ],
                estimated_tokens=0,
                max_wall_seconds=5,
                mutation_intent=False,
            )

        planner = _hint_planner

    service = OrchestrationService(planner=planner, executor=_safe_executor)

    def _supports_empty_arguments(specialist: SpecialistDefinition) -> bool:
        for tool in specialist.operations_mcp_tools:
            try:
                validate_tool_arguments(tool, {})
            except ValueError:
                continue
            return True
        return False

    def _execute(active_request: InvestigationRequest) -> OrchestrationResult:
        if invalid_hint_reason:
            return service.unsupported(
                active_request,
                principal_subject=principal_subject,
                effective_scope=scope,
                reason=invalid_hint_reason,
            )
        if hinted_specialist is None and (not hint_tool or page_kind == "copilot"):
            reason = "unsupported_tool_hint" if hint_tool else "unsupported_intent"
            return service.unsupported(
                active_request,
                principal_subject=principal_subject,
                effective_scope=scope,
                reason=reason,
            )
        if (
            not hint_tool
            and hinted_specialist is not None
            and not _supports_empty_arguments(hinted_specialist)
        ):
            return service.unsupported(
                active_request,
                principal_subject=principal_subject,
                effective_scope=scope,
                reason="missing_required_arguments",
            )
        return service.execute(
            active_request,
            context=context,
            principal_subject=principal_subject,
            effective_scope=scope,
            stable_key=principal_subject,
            max_wall_seconds=max_wall_seconds,
        )

    try:
        result = _execute(request)
    except ThreadStoreUnavailable:
        raise
    except ThreadNotFound:
        _forget_legacy_session_thread(session_id, principal_subject)
        result = _execute(
            request.model_copy(
                update={
                    "thread_id": _legacy_session_thread_for_execution(
                        session_id,
                        principal_subject,
                        scope,
                    )
                }
            )
        )
        result = result.model_copy(
            update={
                "uncertainty": [
                    *result.uncertainty,
                    "Legacy session continuity was reset after reauthorization.",
                ]
            }
        )
    _remember_legacy_session_thread(
        session_id,
        principal_subject,
        result.thread_id,
    )
    return result


def legacy_session_history(
    session_id: str,
    *,
    principal_subject: str,
    scope: Scope,
) -> list[dict[str, Any]]:
    """Read canonical turns associated with a principal-owned legacy session."""

    thread_id = _legacy_session_thread(session_id, principal_subject)
    if thread_id is None:
        return []
    try:
        return investigation_thread_store().history(
            thread_id,
            principal_subject,
            scope,
        )
    except ThreadStoreUnavailable:
        raise
    except ThreadNotFound:
        _forget_legacy_session_thread(session_id, principal_subject)
        return []


__all__ = [
    "ExecutiveSynthesis",
    "OrchestrationService",
    "OrchestrationTurn",
    "PlannerTimeoutError",
    "PlannerUnavailableError",
    "SynthesisDecision",
    "deterministic_network_claims",
    "execute_from_question",
    "executive_synthesis_decision",
    "legacy_session_history",
    "retained_network_page_claims",
    "snapshot_claim_freshness",
]
