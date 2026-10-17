"""Operations Copilot route.

The Copilot is a *narration* layer over the Semantic Knowledge Layer, not a
second source of truth. One request does two things in order:

1. Retrieve governed operational context through :class:`SemanticEngine` — the
   same call the ``/search`` route makes, so the Copilot is subject to the
   identical scope filtering and evidence contract.
2. Ask the configured Azure AI Foundry prompt agent to narrate *only* that
   context.

If no agent is configured, or the agent call fails, the route still returns the
retrieved results and records a warning. A degraded answer with visible
evidence is strictly better than a 502 for an assistant surface.
"""

from __future__ import annotations

import logging
import re
import time
import uuid as _uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from operations.autonomous_investigation import ledger_store, run_context_investigation
from operations.cve_response import canonical_cve_id, deterministic_cve_narrative
from operations.foundry_agent import (
    FoundryAgentError,
    FoundryCoordinatorPlanner,
    FoundryCoordinatorSynthesisAgent,
)
from operations.investigation import (
    conversation_store,
    run_investigation,
    tool_catalog,
)
from operations.investigation_thread_store import (
    ThreadNotFound,
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
    investigation_thread_store,
)
from operations.maf_orchestrator import (
    CopilotRolloutDecision,
    build_deterministic_fallback,
    canonical_orchestration_enabled,
    copilot_rollout_decision,
)
from operations.mcp_server import validate_tool_arguments
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    AzureEntityRef,
    CandidatePlan,
    Citation,
    DomainEntityRef,
    EvidenceSnapshotV2,
    MaterialClaim,
    ObservationRef,
    OrchestrationResult,
    SnapshotCoverage,
    SnapshotEvidence,
    SnapshotFreshness,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_contract import (
    InvestigationRequest as CanonicalInvestigationRequest,
)
from operations.orchestration_policy import OrchestrationPolicy, PolicyViolation
from operations.orchestration_service import (
    OrchestrationService,
    deterministic_network_claims,
    execute_from_question,
    inventory_starter_kind,
    legacy_session_history,
    snapshot_claim_freshness,
    valid_inventory_page_snapshot,
)
from operations.page_context import PageSnapshot, canonicalize_snapshot_v2
from operations.specialist_manifest import (
    INVENTORY_DATA_HEALTH_ID,
    load_specialist_manifest,
)
from operations.tools import (
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    ToolResult,
    call_tool,
)

from ..dependencies import Context, CurrentPrincipal, ReadScope, live_subscription_ids
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

logger = logging.getLogger("aiops.api.copilot")
audit_logger = logging.getLogger("aiops.api.copilot.audit")

router = APIRouter(prefix="/api/v1", tags=["copilot"])

SOURCE_ENGINE = "semantic.SemanticEngine"
NARRATION_ENGINE = "operations.FoundryPromptAgent"
_OVERVIEW_OBSERVATION_SHAPES = {
    ("operations", "network_summary", "network/summary"),
    ("operations", "situation", "situations/visible"),
    (
        "operations",
        "vulnerability_summary",
        "vulnerability/summary",
    ),
    (
        "connections",
        "subscription_connection",
        "connections/visible",
    ),
}

# Per-turn wall-clock budget for the whole investigation (planning + every
# tool call + narration). A question that cannot be answered inside this
# budget is reported as partial rather than left to hang the request.
INVESTIGATION_TIMEOUT_SECONDS = 20.0

# Page kinds that have a valid mapping in the canonical EvidenceSnapshotV2
# contract.  Only these may route through _run_context_via_canonical; all
# others fall through to the legacy adapter to avoid masquerading as a
# different page.
CANONICAL_CONTEXT_PAGE_KINDS = frozenset(
    {"network", "vulnerability", "patch", "incident", "governance", "resource"}
)

# `SemanticEngine.search` returns its hits under `items`. `results` is accepted
# too so the route keeps working if the engine is ever normalized to the name
# used by the public API contract.
_RESULT_KEYS = ("items", "results")


class CopilotRequest(BaseModel):
    """A single Copilot turn."""

    question: str = Field(
        min_length=1,
        max_length=1024,
        description=(
            "An operational question. Retrieval is intent-driven (see /search); "
            "an unsupported intent is reported as a warning rather than answered "
            "from the model's own knowledge."
        ),
    )


class InvestigationRequest(BaseModel):
    """A multi-step Copilot turn: plan tools, execute, narrate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1024)
    session_id: str = Field(
        default="",
        max_length=128,
        description="Optional bounded conversation id, scoped to the caller.",
    )
    tool: str = Field(
        default="",
        max_length=64,
        description="Optional tool name a UI starter question already knows to call, bypassing the planner.",
    )
    tool_arguments: dict[str, Any] = Field(default_factory=dict)


class ContextInvestigationRequest(BaseModel):
    """Strict page snapshot submitted by a supported consumer page."""

    snapshot: PageSnapshot


class CanonicalPlanHint(BaseModel):
    """Untrusted UI routing preference validated by orchestration policy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    specialist_id: str = Field(min_length=1, max_length=80)
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CanonicalInvestigationPayload(CanonicalInvestigationRequest):
    """Canonical request plus an optional policy-checked browser hint."""

    snapshot: EvidenceSnapshotV2
    hint: CanonicalPlanHint | None = None


_AZURE_VNET_ID = re.compile(
    r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/"
    r"microsoft\.network/virtualnetworks/[^/]+/?$",
    flags=re.IGNORECASE,
)


def _validated_or_derived_network_hint(
    payload: CanonicalInvestigationPayload,
    snapshot: EvidenceSnapshotV2,
) -> CanonicalPlanHint | None:
    """Validate or derive selected-VNet dependency intent without widening."""

    hint = payload.hint
    is_hub_hint = hint is not None and hint.tool == "hub_dependents"
    if hint is not None and not is_hub_hint:
        return hint
    if is_hub_hint and hint.specialist_id != "network":
        raise ValueError(
            "hub_dependents hint requires the network specialist"
        )
    question = " ".join(payload.question.strip().casefold().split()).rstrip("?.")
    prefix = "what depends on "
    dependency_subject = (
        question.removeprefix(prefix).strip()
        if question.startswith(prefix)
        else ""
    )
    if snapshot.page_kind != "network" or (
        snapshot.page_id.casefold() != "network-topology"
    ):
        if is_hub_hint or dependency_subject:
            raise ValueError(
                "network dependency requests require network topology context"
            )
        return None
    selected_vnets = [
        entity
        for entity in snapshot.selected_entities
        if isinstance(entity, AzureEntityRef)
        and _AZURE_VNET_ID.fullmatch(entity.resource_id) is not None
    ]
    if is_hub_hint:
        if len(selected_vnets) != len(snapshot.selected_entities):
            raise ValueError(
                "network hub hint requires only selected Azure VNets"
            )
        hinted_vnet_id = hint.arguments.get("vnet_id")
        matching_vnets = [
            entity
            for entity in selected_vnets
            if isinstance(hinted_vnet_id, str)
            and hinted_vnet_id.casefold() == entity.resource_id.casefold()
        ]
        if len(matching_vnets) != 1:
            raise ValueError(
                "network hub hint must match exactly one selected Azure VNet"
            )
        return hint
    if not dependency_subject:
        return None
    if (
        len(selected_vnets) != 1
        or len(snapshot.selected_entities) != 1
    ):
        raise ValueError(
            "network dependency question requires exactly one selected Azure VNet"
        )
    selected = selected_vnets[0]
    vnet_name = selected.resource_id.rstrip("/").rsplit("/", 1)[-1].casefold()
    if dependency_subject not in {vnet_name, selected.resource_id.casefold()}:
        raise ValueError(
            "network dependency question must match the selected Azure VNet"
        )
    return CanonicalPlanHint(
        specialist_id="network",
        tool="hub_dependents",
        arguments={"vnet_id": selected.resource_id},
    )


def _validate_bound_cve_request(
    payload: CanonicalInvestigationPayload,
    snapshot: EvidenceSnapshotV2,
) -> None:
    """Reject stale or conflicting CVE identity before any tool can execute."""

    if (
        snapshot.page_kind not in {"cve_detail", "vulnerability"}
        or not snapshot.page_id.casefold().startswith("cve:")
    ):
        return
    page_cve = canonical_cve_id(snapshot.page_id.split(":", 1)[1])
    if not page_cve:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "CVE page context requires a canonical CVE identifier",
            details={"field": "snapshot.page_id"},
        )
    referenced = {
        value.upper()
        for value in re.findall(
            r"\bCVE-\d{4}-\d{4,}\b",
            payload.question,
            flags=re.IGNORECASE,
        )
    }
    hint_cve = ""
    hint_requires_exact_cve = False
    if payload.hint is not None:
        if payload.hint.tool in {"cve_detail", "cve_attack_path"}:
            hint_requires_exact_cve = True
            hint_cve = canonical_cve_id(
                payload.hint.arguments.get("cve_id")
            )
        elif payload.hint.tool == "cve_exposure":
            hint_requires_exact_cve = True
            hint_cve = canonical_cve_id(
                payload.hint.arguments.get("query")
            )
    filtered_cves = {
        canonical_cve_id(value)
        for value in snapshot.filters.get("weakness_id", ())
    }
    selected_cves = {
        canonical_cve_id(entity.source_key)
        for entity in snapshot.selected_entities
        if isinstance(entity, DomainEntityRef)
        and entity.namespace.casefold() == "vulnerability"
        and entity.kind.casefold() == "cve"
    }
    conflicting = (
        (referenced and referenced != {page_cve})
        or (hint_requires_exact_cve and not hint_cve)
        or (hint_cve and hint_cve != page_cve)
        or any(value and value != page_cve for value in filtered_cves)
        or any(value and value != page_cve for value in selected_cves)
    )
    if conflicting:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Requested CVE does not match the visible CVE page context",
            details={"field": "snapshot.page_id"},
        )


def _bounded_overview_observation(
    item: SnapshotEvidence,
) -> SnapshotEvidence | None:
    """Sanitize one allowlisted Overview aggregate as a page observation."""

    entity = item.entity
    if (
        not isinstance(entity, DomainEntityRef)
        or entity.source_key.casefold() != item.source_key.casefold()
        or item.claim_type.casefold() != entity.kind.casefold()
        or item.selected
        or not item.direct
        or item.actionable
        or item.data.get("mutation_authorized") is not False
        or str(item.data.get("claim_type") or "").casefold()
        != item.claim_type.casefold()
        or str(item.data.get("source_key") or "").casefold()
        != item.source_key.casefold()
    ):
        return None
    claim_type = item.claim_type.casefold()
    rank_data: dict[str, Any]
    if claim_type == "network_summary":
        count = item.data.get("gap_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        rank_data = {"gap_count": count}
    elif claim_type == "vulnerability_summary":
        count = item.data.get("internet_exposed_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        rank_data = {"internet_exposed_count": count}
    elif claim_type == "situation":
        priority = str(item.data.get("priority") or "").strip().upper()
        if priority not in {"P1", "P2", "P3"}:
            return None
        rank_data = {"priority": priority}
    else:
        health_status = str(
            item.data.get("health_status") or ""
        ).strip().casefold()
        sync_status = str(
            item.data.get("sync_status") or ""
        ).strip().casefold()
        if (
            health_status
            not in {
                "healthy",
                "unhealthy",
                "warning",
                "failed",
                "stale",
                "onboarding_blocked",
                "disabled",
                "unknown",
            }
            or not sync_status
            or len(sync_status) > 32
        ):
            return None
        rank_data = {
            "health_status": health_status,
            "sync_status": sync_status,
        }
    observation = ObservationRef(
        type="observation",
        source=item.source,
        source_key=item.source_key,
    )
    return item.model_copy(
        update={
            "entity": observation,
            "data": {
                **rank_data,
                "entity": observation.model_dump(mode="json"),
                "source_key": item.source_key,
                "claim_type": claim_type,
                "selected": False,
                "actionable": False,
                "mutation_authorized": False,
            },
        }
    )


def _with_bounded_overview_observations(
    snapshot: EvidenceSnapshotV2,
) -> EvidenceSnapshotV2:
    """Normalize bounded Overview pseudo-entities before canonicalization."""

    if (
        snapshot.page_kind != "overview"
        or snapshot.page_id != "operations-overview"
    ):
        return snapshot
    evidence: list[SnapshotEvidence] = []
    for item in snapshot.evidence:
        entity = item.entity
        is_overview_shape = (
            isinstance(entity, DomainEntityRef)
            and (
                entity.namespace.casefold(),
                entity.kind.casefold(),
                item.source.casefold(),
            )
            in _OVERVIEW_OBSERVATION_SHAPES
        )
        if not is_overview_shape:
            evidence.append(item)
            continue
        converted = _bounded_overview_observation(item)
        if converted is not None:
            evidence.append(converted)
    evidence_ids = {item.evidence_id for item in evidence}
    return snapshot.model_copy(
        update={
            "evidence": evidence,
            "material_claims": [
                claim
                for claim in snapshot.material_claims
                if set(claim.evidence_refs) <= evidence_ids
            ],
        }
    )


def _without_unresolved_domain_evidence(
    snapshot: EvidenceSnapshotV2,
) -> EvidenceSnapshotV2:
    """Drop unresolved browser domain identities when semantic is unavailable."""

    snapshot = _with_bounded_overview_observations(snapshot)
    evidence = [
        item
        for item in snapshot.evidence
        if not isinstance(item.entity, DomainEntityRef)
    ]
    selected_entities = [
        entity
        for entity in snapshot.selected_entities
        if not isinstance(entity, DomainEntityRef)
    ]
    excluded_domain_evidence = (
        len(evidence) != len(snapshot.evidence)
        or len(selected_entities) != len(snapshot.selected_entities)
    )
    evidence_ids = {item.evidence_id for item in evidence}
    return snapshot.model_copy(
        update={
            "coverage": (
                snapshot.coverage.model_copy(update={"complete": False})
                if excluded_domain_evidence
                else snapshot.coverage
            ),
            "selected_entities": selected_entities,
            "evidence": evidence,
            "material_claims": [
                claim
                for claim in snapshot.material_claims
                if set(claim.evidence_refs) <= evidence_ids
            ],
        }
    )


class CanonicalInventorySelector(BaseModel):
    """Bounded server selector derived from untrusted Inventory page context."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    family: Literal["os", "software", "paas"]
    resource_selector: str | None = Field(default=None, min_length=1, max_length=240)

    def tool_arguments(self) -> dict[str, str]:
        arguments = {"family": self.family}
        if self.resource_selector:
            arguments["resource_type"] = self.resource_selector
        return arguments


_HIDDEN = object()

_INVENTORY_SOURCE_TABS = {
    "inventory/os_observations": "os",
    "inventory/software_observations": "software",
    "inventory/resource_observations": "azure",
}
_INVENTORY_PAGE_TABS = {
    "inventory:os": "os",
    "inventory:software": "software",
    "inventory:azure": "azure",
}
_MAX_SERVER_EVIDENCE = 255


def _bounded_selector_text(
    value: Any,
    *,
    field: str,
    max_length: int = 120,
) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length or any(
        character in text for character in ("\x00", "\r", "\n")
    ):
        raise ValueError(f"invalid inventory selector {field}")
    return text


def _inventory_selector(snapshot: Any) -> CanonicalInventorySelector:
    """Derive a bounded selector without treating browser rows as evidence."""

    page_tab = _INVENTORY_PAGE_TABS.get(snapshot.page_id)
    inferred_tabs: set[str] = set()
    selected_rows: list[Mapping[str, Any]] = []
    filters: dict[str, str] | None = None

    for item in snapshot.evidence:
        inferred_tab = _INVENTORY_SOURCE_TABS.get(item.source)
        if inferred_tab is None:
            raise ValueError("unsupported inventory evidence source")
        inferred_tabs.add(inferred_tab)
        data = item.data
        raw_context = data.get("inventory_context")
        if not isinstance(raw_context, Mapping):
            raise TypeError("inventory evidence is missing bounded page context")
        claimed_tab = raw_context.get("tab")
        if claimed_tab != inferred_tab:
            raise ValueError("inventory tab conflicts with evidence shape")
        raw_filters = raw_context.get("filters")
        if not isinstance(raw_filters, Mapping) or len(raw_filters) > 16:
            raise ValueError("inventory filters are invalid")
        normalized_filters = {
            _bounded_selector_text(key, field="filter name", max_length=64):
            _bounded_selector_text(value, field=f"filter {key}", max_length=160)
            for key, value in raw_filters.items()
        }
        if filters is not None and filters != normalized_filters:
            raise ValueError("inventory evidence carries conflicting filters")
        filters = normalized_filters
        if data.get("selected") is True:
            selected_rows.append(data)

    if len(inferred_tabs) > 1 or len(selected_rows) > 1:
        raise ValueError("inventory selector is ambiguous")
    inferred_tab = next(iter(inferred_tabs), None)
    if page_tab and inferred_tab and page_tab != inferred_tab:
        raise ValueError("inventory page conflicts with evidence shape")
    tab = page_tab or inferred_tab
    if tab is None:
        raise ValueError("inventory selector cannot be inferred")

    selector: str | None = None
    selected = selected_rows[0] if selected_rows else None
    active_filters = filters or {}
    if tab == "os":
        os_name = selected.get("os_name") if selected else active_filters.get("os_name")
        os_version = selected.get("os_version") if selected else active_filters.get("os_version")
        if os_name and os_version and os_name != "all" and os_version != "all":
            selector = "group:" + "|".join((
                _bounded_selector_text(os_name, field="os_name"),
                _bounded_selector_text(os_version, field="os_version"),
            ))
        family = "os"
    elif tab == "software":
        software_name = (
            selected.get("software_name")
            if selected
            else active_filters.get("software")
        )
        software_version = selected.get("software_version") if selected else None
        if (
            software_name
            and software_version
            and software_name != "all"
            and software_version != "all"
        ):
            selector = "group:" + "|".join((
                _bounded_selector_text(software_name, field="software_name"),
                _bounded_selector_text(software_version, field="software_version"),
            ))
        family = "software"
    else:
        if selected:
            selector = "group:" + "|".join((
                _bounded_selector_text(
                    selected.get("resource_type"),
                    field="resource_type",
                    max_length=160,
                ).replace("/", ":"),
                _bounded_selector_text(selected.get("sku") or "Unknown", field="sku"),
                _bounded_selector_text(selected.get("tier") or "Unknown", field="tier"),
            ))
        else:
            resource_type = active_filters.get("resource_type")
            if resource_type and resource_type != "all":
                selector = "type:" + _bounded_selector_text(
                    resource_type,
                    field="resource_type",
                    max_length=160,
                )
        family = "paas"

    return CanonicalInventorySelector(
        family=family,
        resource_selector=selector,
    )


def _server_inventory_result(result: Mapping[str, Any] | None) -> ToolResult:
    if result is None:
        return ToolResult(status=STATUS_EMPTY)
    raw_evidence = [
        item
        for item in result.get("evidence", [])
        if isinstance(item, Mapping)
    ]
    evidence = tuple(
        Evidence(
            source_engine=str(item.get("source_engine") or "InventoryService"),
            source_table=str(item.get("source_table") or ""),
            timestamp=str(item.get("timestamp") or ""),
            resource_id=str(item.get("resource_id") or ""),
            confidence=str(item.get("confidence") or CONFIDENCE_HIGH),
        )
        for item in raw_evidence[:_MAX_SERVER_EVIDENCE]
    )
    warnings = [
        str(item).strip()
        for item in result.get("warnings", [])
        if str(item).strip()
    ]
    if len(raw_evidence) > _MAX_SERVER_EVIDENCE:
        warnings.append(
            "Server evidence truncated to "
            f"{_MAX_SERVER_EVIDENCE} of {len(raw_evidence)} records"
        )
    total = int(result.get("total") or 0)
    raw_data = result.get("data")
    data = (
        {
            **raw_data,
            "total": total,
            **(
                {"group_total": total}
                if isinstance(raw_data.get("groups"), list)
                else {}
            ),
        }
        if isinstance(raw_data, Mapping)
        else {"items": raw_data, "total": total}
    )
    return ToolResult(
        status=STATUS_OK if total else STATUS_EMPTY,
        data=data,
        evidence=evidence,
        warning="; ".join(warnings),
    )


def _inventory_executor(
    selector: CanonicalInventorySelector,
):
    """Execute only the policy-approved inventory call with server-side scope."""

    derived_arguments = selector.tool_arguments()

    def execute(
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: Any,
        scope: Scope,
    ) -> ToolResult:
        if name != "inventory_resources":
            return call_tool(name, arguments, context=context, scope=scope)
        effective_arguments = dict(arguments) or derived_arguments
        validated = CanonicalInventorySelector(
            family=effective_arguments.get("family"),
            resource_selector=effective_arguments.get("resource_type"),
        )
        resource_selector = validated.resource_selector or ""
        if (
            validated.family in {"os", "software", "paas"}
            and not resource_selector.startswith("group:")
        ):
            tool_arguments: dict[str, str] = {"family": validated.family}
            if resource_selector.startswith("type:"):
                tool_arguments["resource_type"] = resource_selector.removeprefix("type:")
            return call_tool(
                name,
                tool_arguments,
                context=context,
                scope=scope,
            )

        try:
            service = context.resolve_provider("inventory")
            if validated.family == "software":
                if resource_selector.startswith("group:"):
                    name_value, version = resource_selector.removeprefix("group:").split("|", 1)
                    result = service.software_detail(
                        name_value,
                        version,
                        scope,
                        offset=0,
                        limit=25,
                    )
                else:
                    result = service.software_collection(scope, offset=0, limit=25)
            elif validated.family == "os":
                result = service.detail(
                    resource_selector.removeprefix("group:"),
                    scope,
                    offset=0,
                    limit=25,
                )
            else:
                result = service.paas_detail(
                    resource_selector.removeprefix("group:"),
                    scope,
                    offset=0,
                    limit=25,
                )
            return _server_inventory_result(result)
        except ApiError as exc:
            return ToolResult(status=STATUS_UNAVAILABLE, warning=exc.message)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("canonical_inventory_provider_failed error=%s", exc)
            return ToolResult(
                status=STATUS_UNAVAILABLE,
                warning="The scoped inventory provider failed to answer",
            )

    return execute


def _canonical_plan_preview(
    *,
    planner: Any,
    request: CanonicalInvestigationRequest,
    scope: Scope,
) -> tuple[dict[str, Any], bool]:
    """Resolve canonical planning and policy without model or tool execution."""

    policy = OrchestrationPolicy()
    policy_validated = True
    try:
        proposal = planner(request)
        candidate = (
            proposal
            if isinstance(proposal, CandidatePlan)
            else CandidatePlan.model_validate(proposal)
        )
        candidate = policy.validate(
            request=request,
            candidate=candidate,
            effective_scope=scope,
        )
        policy_status = "accepted"
        fallback_reason = ""
    except PolicyViolation as exc:
        policy_validated = False
        fallback_reason = f"candidate_rejected:{exc.code}"
        candidate = build_deterministic_fallback(
            request,
            load_specialist_manifest(),
        )
        if candidate is not None:
            candidate = policy.validate(
                request=request,
                candidate=candidate,
                effective_scope=scope,
            )
        policy_status = "fallback"
    except (TypeError, ValueError):
        policy_validated = False
        fallback_reason = "planner_parse_error"
        candidate = build_deterministic_fallback(
            request,
            load_specialist_manifest(),
        )
        if candidate is not None:
            candidate = policy.validate(
                request=request,
                candidate=candidate,
                effective_scope=scope,
            )
        policy_status = "fallback"
    except (ConnectionError, FoundryAgentError, TimeoutError):
        policy_validated = False
        fallback_reason = "planner_unavailable"
        candidate = build_deterministic_fallback(
            request,
            load_specialist_manifest(),
        )
        if candidate is not None:
            candidate = policy.validate(
                request=request,
                candidate=candidate,
                effective_scope=scope,
            )
        policy_status = "fallback"

    return (
        {
            "policy_status": policy_status,
            "fallback_reason": (
                fallback_reason
                if candidate is not None
                else "no_safe_tool_arguments"
            ),
            "selected_specialists": (
                [step.specialist_id for step in candidate.steps]
                if candidate is not None
                else []
            ),
            "selected_tools": (
                [
                    call.tool
                    for step in candidate.steps
                    for call in step.tool_calls
                ]
                if candidate is not None
                else []
            ),
            "plan_outcome": (
                "planned" if candidate is not None else "no_safe_plan"
            ),
            "external_io": {
                "tool_calls": 0,
                "model_or_narration_calls": 0,
            },
        },
        policy_validated,
    )


def _execute_retained_compatibility(
    *,
    payload: CanonicalInvestigationPayload,
    request: CanonicalInvestigationRequest,
    context: Any,
    scope: Scope,
    principal: Any,
    planned_candidate: CandidatePlan | None = None,
) -> OrchestrationResult:
    """Serve the retained deterministic investigation path on the v2 wire."""

    requested_scope = OrchestrationPolicy().validate_request(request, scope)
    hint_tool = payload.hint.tool if payload.hint is not None else None
    if hint_tool and hint_tool not in {
        str(item.get("name") or "") for item in tool_catalog()
    }:
        raise PolicyViolation("unknown_tool", hint_tool)

    store = investigation_thread_store()
    if request.thread_id:
        thread = store.authorize(
            request.thread_id,
            principal.subject,
            requested_scope,
            expected_revision=request.expected_thread_revision,
        )
    else:
        thread = store.create(principal.subject, requested_scope)
    planned_calls: list[tuple[str, dict[str, Any]]] | None = None
    planned_specialists: list[str] = []
    if payload.hint is None:
        candidate = planned_candidate or build_deterministic_fallback(
            request,
            load_specialist_manifest(),
        )
        planned_calls = []
        for step in candidate.steps if candidate is not None else ():
            for call in step.tool_calls:
                planned_calls.append((call.tool, dict(call.arguments)))
                planned_specialists.append(step.specialist_id)
    investigation = run_investigation(
        request.question,
        context=context,
        scope=requested_scope,
        principal=principal,
        hint_tool=hint_tool,
        hint_args=(
            dict(payload.hint.arguments)
            if payload.hint is not None
            else None
        ),
        planned_calls=planned_calls,
        page_kind=f"{request.snapshot.page_kind}_page",
    )

    tool_results: list[dict[str, Any]] = []
    citations: list[Citation] = []
    next_revision = thread.revision + 1
    selected_specialists: list[str] = []
    for call_index, call in enumerate(investigation.calls):
        call_id = (
            f"{thread.thread_id}:rev-{next_revision}:compatibility:"
            f"{call_index}:{call.tool}"
        )
        specialist_id = (
            payload.hint.specialist_id
            if payload.hint is not None and call.tool == payload.hint.tool
            else planned_specialists[call_index]
            if call_index < len(planned_specialists)
            else ""
        )
        if specialist_id and specialist_id not in selected_specialists:
            selected_specialists.append(specialist_id)
        tool_results.append(
            {
                "call_id": call_id,
                "specialist_id": specialist_id,
                "tool": call.tool,
                "arguments": dict(call.arguments),
                **call.result.to_dict(),
            }
        )
        citations.extend(
            Citation(
                citation_id=f"tool:{call_id}:{evidence_index}",
                source=(
                    evidence.source_engine
                    if not evidence.source_table
                    else f"{evidence.source_engine}:{evidence.source_table}"
                ),
                status=call.result.status,
                observed_at=evidence.timestamp,
                resource_id=evidence.resource_id,
            )
            for evidence_index, evidence in enumerate(call.result.evidence)
        )

    compatibility_claims: list[dict[str, Any]] = []
    compatibility_warning = ""
    page_cve = (
        canonical_cve_id(request.snapshot.page_id.split(":", 1)[1])
        if request.snapshot.page_kind == "cve_detail"
        and request.snapshot.page_id.casefold().startswith("cve:")
        else ""
    )
    hinted_cve = (
        canonical_cve_id(payload.hint.arguments.get("cve_id"))
        if payload.hint is not None and payload.hint.tool == "cve_detail"
        else ""
    )
    if investigation.answer is None and page_cve and hinted_cve == page_cve:
        exact_call = next(
            (
                item
                for item in tool_results
                if item["tool"] == "cve_detail"
                and item["status"] == STATUS_OK
                and canonical_cve_id(item["arguments"].get("cve_id")) == page_cve
            ),
            None,
        )
        if exact_call is not None:
            narrative = deterministic_cve_narrative(
                page_cve,
                detail_data=exact_call.get("data"),
                snapshot_coverage=request.snapshot.coverage.model_dump(
                    mode="json"
                ),
                source_statuses={
                    item.source: item.status
                    for item in request.snapshot.freshness
                },
            )
            evidence_refs = [
                citation.citation_id
                for citation in citations
                if citation.citation_id.startswith(
                    f"tool:{exact_call['call_id']}:"
                )
            ]
            if narrative and evidence_refs:
                freshness = snapshot_claim_freshness(request.snapshot)
                uncertainty = (
                    []
                    if request.snapshot.coverage.complete
                    else ["visible subset is incomplete"]
                )
                if freshness != "fresh":
                    uncertainty.append(
                        f"CVE source freshness is {freshness}."
                    )
                compatibility_claims = [
                    {
                        "finding_id": f"compatibility:{page_cve.casefold()}",
                        "summary": narrative,
                        "evidence_refs": evidence_refs,
                        "confidence": (
                            "high"
                            if request.snapshot.coverage.complete
                            else "medium"
                        ),
                        "freshness": freshness,
                        "uncertainty": uncertainty,
                    }
                ]
                compatibility_warning = (
                    "Foundry narration is not configured; deterministic cited "
                    "CVE evidence was used."
                )
    if investigation.answer is None and not compatibility_claims:
        compatibility_claims = deterministic_network_claims(
            snapshot=request.snapshot,
            tool_results=tool_results,
        )
        if compatibility_claims:
            compatibility_warning = (
                "Foundry narration is not configured; deterministic cited "
                "network evidence was used."
            )

    result = OrchestrationResult(
        status=investigation.fact_status,
        policy_status="fallback",
        fallback_reason="compatibility_rollout",
        selected_specialists=selected_specialists,
        selected_tools=[call.tool for call in investigation.calls],
        tool_results=tool_results,
        uncertainty=list(investigation.warnings),
        coverage=request.snapshot.coverage,
        citations=citations,
        thread_id=thread.thread_id,
        thread_revision=next_revision,
        synthesis={
            "status": (
                "compatibility"
                if investigation.answer is not None
                else "degraded"
            ),
            "reason": "retained_compatibility",
            "domain_count": int(bool(compatibility_claims)),
            "claims": compatibility_claims,
            "warning": compatibility_warning,
            "compatibility_answer": investigation.answer,
        },
    )
    updated = store.append(
        thread.thread_id,
        principal.subject,
        requested_scope,
        {
            "question": request.question,
            **result.model_dump(mode="json"),
        },
        expected_revision=thread.revision,
    )
    return result.model_copy(update={"thread_revision": updated.revision})


def _shadow_comparison(
    *,
    compatibility: OrchestrationResult,
    canonical: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare normalized plans without repeating tool or model execution."""

    compatibility_plan = {
        "plan_outcome": (
            "planned"
            if compatibility.selected_tools
            else "no_safe_plan"
        ),
        "fallback_reason": compatibility.fallback_reason,
        "selected_specialists": None,
        "selected_tools": list(compatibility.selected_tools),
    }
    canonical_plan = dict(canonical)
    matches: dict[str, bool | None] = {
        "plan_outcome": (
            compatibility_plan["plan_outcome"]
            == canonical_plan["plan_outcome"]
        ),
        # The retained planner has no canonical specialist-policy concept.
        "selected_specialists": None,
        "selected_tools": (
            compatibility_plan["selected_tools"]
            == canonical_plan["selected_tools"]
        ),
    }
    return {
        "compatibility": compatibility_plan,
        "canonical": canonical_plan,
        "matches": matches,
        "divergent_fields": [
            field
            for field, matches_value in matches.items()
            if matches_value is False
        ],
    }


def _filter_scoped(value: Any, scope: Scope) -> Any:
    """Recursively drop entities the caller is not entitled to see.

    Applied to the *whole* retrieval payload, not just the top-level hit list:
    the engine nests entities under several keys, and a filter that only walked
    one of them would leak out-of-scope facts into the model prompt.
    """
    if isinstance(value, dict):
        attributes = scope_attributes(value)
        if attributes and not scope.matches(attributes):
            return _HIDDEN
        return {
            key: filtered
            for key, child in value.items()
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        }
    if isinstance(value, list):
        return [
            filtered
            for child in value
            if (filtered := _filter_scoped(child, scope)) is not _HIDDEN
        ]
    return value


def _results_of(payload: dict[str, Any]) -> list[Any]:
    """Extract the hit list under whichever key the engine used."""
    for key in _RESULT_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


@router.post("/copilot/ask", summary="Ask the Operations Copilot")
def ask(payload: CopilotRequest, context: Context, scope: ReadScope) -> dict[str, Any]:
    """Answer an operational question from governed context.

    Returns the retrieved rows alongside the narrated answer so the UI can show
    both the prose and the underlying evidence.
    """
    question = payload.question.strip()
    warnings: list[str] = []

    try:
        subscription_ids = live_subscription_ids(context, scope)
        live_search = question.casefold().strip().startswith("show list of") and (
            "vm" in question.casefold() or "server" in question.casefold()
        )
        if (
            context.hybrid_search_provider is not None
            and subscription_ids
            and live_search
        ):
            retrieved = context.hybrid_search_provider(question, subscription_ids)
        else:
            retrieved = context.semantic().search(question)
    except ApiError:
        raise
    except (LookupError, ValueError) as exc:
        # An unsupported intent is a legitimate, expected outcome; report it as
        # a bounded 400 with the supported list rather than letting the model
        # answer a question the knowledge layer cannot ground.
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc) or "The Copilot cannot ground this question in operational context",
            details={"question": question},
        ) from exc

    # Filter the entire payload before anything is shown or sent to the model,
    # so out-of-scope facts never reach either the caller or Foundry.
    filtered = _filter_scoped(retrieved, scope)
    grounding: dict[str, Any] = filtered if isinstance(filtered, dict) else {}
    results = _results_of(grounding)

    answer: dict[str, Any] | None = None
    agent = context.foundry_agent()
    if agent is None:
        warnings.append(
            "No Foundry prompt agent is configured; returning retrieved context "
            "without a narrated answer."
        )
    else:
        try:
            answer = agent.answer(question=question, context=grounding).to_dict()
        except FoundryAgentError as exc:
            # Never fail the turn on the narration layer: retrieval already
            # produced a usable, fully-evidenced answer.
            logger.warning("foundry_agent_unavailable error=%s", exc)
            if context.provider_runtime is not None:
                context.provider_runtime.record_failure("copilot", exc)
            warnings.append(
                "The Foundry prompt agent could not be reached; showing "
                "retrieved context only."
            )

    evidence = [
        Evidence.from_context(
            retrieved,
            source_engine=SOURCE_ENGINE,
            source_table="ontology_entities",
            confidence=CONFIDENCE_MEDIUM,
        )
    ]
    if answer is not None:
        evidence.append(
            Evidence(
                source_engine=NARRATION_ENGINE,
                source_table=str(answer.get("agent_name") or ""),
                timestamp=str(retrieved.get("freshness") or ""),
                # The narration is a restatement of medium-confidence retrieval;
                # it can never be more trustworthy than the facts it summarizes.
                confidence=CONFIDENCE_MEDIUM,
            )
        )

    return envelope(
        {
            "question": question,
            "intent": retrieved.get("intent"),
            "results": results,
            "answer": answer,
        },
        evidence=evidence,
        scope=scope.to_dict(),
        knowledge_version=str(retrieved.get("knowledge_version") or ""),
        warnings=warnings,
    )


@router.get("/copilot/tools", summary="Governed toolset the Copilot may call")
def tools(context: Context, scope: ReadScope) -> dict[str, Any]:
    """The tool contracts, for docs and for the UI's starter-question hints."""
    return envelope({"tools": tool_catalog()}, scope=scope.to_dict())


def _investigate_via_canonical(
    question: str,
    *,
    started: float,
    context: Any,
    scope: Any,
    principal: Any,
    session_id: str,
    hint_tool: str,
    hint_arguments: Mapping[str, Any],
    rollout_decision: CopilotRolloutDecision,
) -> dict[str, Any]:
    """Route ``/copilot/investigate`` through the canonical OrchestrationService.

    Translates the question to a canonical ``InvestigationRequest``, invokes
    ``OrchestrationService.execute`` via the shared adapter, and projects the
    result back to the legacy investigation wire shape so existing consumers
    see the same ``question``/``tool_calls``/``fact_status``/``warnings``
    contract.  Session continuity uses the canonical thread, not the legacy
    ``ConversationStore``.
    """
    try:
        result = execute_from_question(
            question,
            scope=scope,
            context=context,
            principal_subject=principal.subject,
            rollout_decision=rollout_decision,
            session_id=session_id,
            hint_tool=hint_tool,
            hint_arguments=hint_arguments,
        )
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation continuity is temporarily unavailable",
        ) from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Investigation thread changed; retry the request",
        ) from exc
    duration_ms = (time.monotonic() - started) * 1000.0
    if duration_ms > INVESTIGATION_TIMEOUT_SECONDS * 1000.0:
        logger.warning(
            "copilot_investigation_over_budget duration_ms=%.0f question_len=%d",
            duration_ms,
            len(question),
        )
    audit_logger.info(
        "copilot_investigation subject=%s tools=%s statuses=%s fact_status=%s duration_ms=%.0f",
        principal.subject,
        result.selected_tools,
        [tr["status"] for tr in result.tool_results],
        result.status,
        duration_ms,
    )
    projected: dict[str, Any] = {
        "question": question,
        "tool_calls": [
            {
                "tool": tr["tool"],
                "arguments": dict(tr.get("arguments") or {}),
                "status": tr["status"],
                "data": tr.get("data"),
                "evidence": list(tr.get("evidence", ())),
                "warning": tr.get("warning", ""),
            }
            for tr in result.tool_results
        ],
        "answer": None,
        "fact_status": result.status,
        "warnings": list(result.uncertainty),
        "contract_version": result.contract_version,
        "thread_id": result.thread_id,
        "thread_revision": result.thread_revision,
        "synthesis": result.synthesis,
        "policy_status": result.policy_status,
        "fallback_reason": result.fallback_reason,
        "coverage": result.coverage.model_dump(mode="json"),
        "citations": [
            citation.model_dump(mode="json") for citation in result.citations
        ],
    }
    evidence: list[Evidence] = []
    for tr in result.tool_results:
        for ev in tr.get("evidence", ()):
            evidence.append(
                Evidence(
                    source_engine=str(ev.get("source_engine", "")),
                    source_table=str(ev.get("source_table", "")),
                    timestamp=str(ev.get("timestamp", "")),
                    resource_id=str(ev.get("resource_id", "")),
                    confidence=str(ev.get("confidence", CONFIDENCE_MEDIUM)),
                )
            )
    return envelope(
        projected,
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=list(result.uncertainty),
    )


@router.post("/copilot/investigate", summary="Multi-step Operations Copilot investigation")
def investigate(
    payload: InvestigationRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Answer an operational question via a bounded tool-calling loop.

    Unlike ``/copilot/ask`` (single retrieval call), this plans up to
    :data:`MAX_TOOL_CALLS` governed tool invocations -- topology, traffic-flow,
    CVE exposure, incidents, remediation, and ontology context -- executes
    each one scope-filtered, and narrates the aggregate. Every tool call's
    status and evidence is returned alongside the narration so a caller can
    audit exactly what was observed vs. inferred vs. unavailable.
    """
    question = payload.question.strip()
    started = time.monotonic()
    validated_arguments: dict[str, Any] = {}
    known_tools = tool_catalog_names()
    rollout = copilot_rollout_decision(stable_key=principal.subject)
    canonical_enabled = canonical_orchestration_enabled(
        stable_key=principal.subject,
        decision=rollout,
    )

    if payload.tool in known_tools:
        try:
            validated_arguments, _ = validate_tool_arguments(
                payload.tool,
                payload.tool_arguments,
            )
        except ValueError as exc:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                f"Invalid arguments for tool {payload.tool!r}",
                details={"tool": payload.tool},
            ) from exc
    elif payload.tool:
        validated_arguments = dict(payload.tool_arguments)
    elif payload.tool_arguments:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Tool arguments require a tool hint",
        )

    if canonical_enabled:
        return _investigate_via_canonical(
            question,
            started=started,
            context=context,
            scope=scope,
            principal=principal,
            session_id=payload.session_id,
            hint_tool=payload.tool,
            hint_arguments=validated_arguments,
            rollout_decision=rollout,
        )

    if payload.tool and payload.tool not in known_tools:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown tool {payload.tool!r}",
            details={"supported_tools": sorted(known_tools)},
        )

    investigation = run_investigation(
        question,
        context=context,
        scope=scope,
        principal=principal,
        hint_tool=payload.tool or None,
        hint_args=validated_arguments,
    )
    duration_ms = (time.monotonic() - started) * 1000.0
    if duration_ms > INVESTIGATION_TIMEOUT_SECONDS * 1000.0:
        logger.warning(
            "copilot_investigation_over_budget duration_ms=%.0f question_len=%d",
            duration_ms,
            len(question),
        )

    if payload.session_id:
        conversation_store().record(payload.session_id, principal.subject, investigation)

    # Audit trail: which tools ran, their outcome, and who asked -- never the
    # question text or tool payloads, to avoid a secret sink in application
    # logs while still letting an operator reconstruct tool-selection behavior.
    audit_logger.info(
        "copilot_investigation subject=%s tools=%s statuses=%s fact_status=%s duration_ms=%.0f",
        principal.subject,
        [call.tool for call in investigation.calls],
        [call.result.status for call in investigation.calls],
        investigation.fact_status,
        duration_ms,
    )

    evidence: list[Evidence] = []
    for call in investigation.calls:
        evidence.extend(call.result.evidence)
    if investigation.answer is not None:
        evidence.append(
            Evidence(
                source_engine=NARRATION_ENGINE,
                source_table=str(investigation.answer.get("agent_name") or ""),
                confidence=CONFIDENCE_MEDIUM,
            )
        )

    return envelope(
        investigation.to_dict(),
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=list(investigation.warnings),
    )


MAX_CLAIM_EVIDENCE_REFS = 32


def _page_row_text(row: Any, field: str, *, limit: int) -> str:
    """Read one bounded string field from a submitted page row payload."""

    data = getattr(row, "data", None)
    value = data.get(field) if isinstance(data, Mapping) else None
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    return normalized if 0 < len(normalized) <= limit else ""


def _page_material_claims(
    evidence: Sequence[SnapshotEvidence],
) -> list[MaterialClaim]:
    """Assert submitted page rows so evidence retention can admit them.

    Retention only keeps rows referenced by a material claim, so a bridge that
    submits no claims silently discards every page row and leaves synthesis
    with aggregate tool counts alone.  A row naming a specific resource is an
    independent per-resource observation that stays true under partial
    coverage.  A row without a resource identity is an aggregate whose truth
    depends on observing every row, so it stays gated on complete coverage.
    """

    admissible = [row for row in evidence if row.status in ("ok", "partial")]
    claims: list[MaterialClaim] = []
    for prefix, requires_complete_coverage, rows in (
        (
            "page-observation",
            False,
            [row for row in admissible if row.resource_id],
        ),
        (
            "page-aggregate",
            True,
            [row for row in admissible if not row.resource_id],
        ),
    ):
        for offset in range(0, len(rows), MAX_CLAIM_EVIDENCE_REFS):
            chunk = rows[offset : offset + MAX_CLAIM_EVIDENCE_REFS]
            claims.append(
                MaterialClaim(
                    claim_id=(
                        f"{prefix}-{offset // MAX_CLAIM_EVIDENCE_REFS + 1}"
                    ),
                    evidence_refs=[row.evidence_id for row in chunk],
                    requires_complete_coverage=requires_complete_coverage,
                )
            )
    return claims


def _run_context_via_canonical(
    snapshot: PageSnapshot,
    *,
    context: Any,
    scope: Any,
    principal: Any,
    principal_subject: str,
    rollout_decision: CopilotRolloutDecision,
) -> dict[str, Any]:
    """Thin canonical adapter: route a context investigation through OrchestrationService.

    Translates the PageSnapshot's actual page kind, submitted evidence,
    freshness, and selected resources into the canonical v2 contract when the
    page kind has a valid canonical mapping.  Selects specialists through the
    canonical proposal→policy→execution loop rather than hardcoding a single
    specialist.  Projects a complete legacy ledger preserving canonical
    findings, evidence, citations, status, and warnings.

    Only called when ``snapshot.page_kind in CANONICAL_CONTEXT_PAGE_KINDS``;
    unsupported page kinds are routed through ``run_context_investigation``
    by the caller.
    """

    # Translate PageSnapshot evidence rows into canonical SnapshotEvidence
    canonical_evidence = [
        SnapshotEvidence(
            evidence_id=row.evidence_id,
            source=row.section,
            status=(
                row.status
                if row.status in ("ok", "empty", "partial", "unavailable", "denied")
                else "ok"
            ),
            observed_at=getattr(row, "observed_at", ""),
            resource_id=getattr(row, "resource_id", ""),
            source_key=_page_row_text(row, "source_key", limit=256),
            claim_type=_page_row_text(row, "claim_type", limit=128)
            or "observation",
            data=getattr(row, "data", {}),
        )
        for row in snapshot.evidence
    ]

    # Translate PageSnapshot freshness into canonical SnapshotFreshness
    canonical_freshness = [
        SnapshotFreshness(
            source=rec.source,
            observed_at=rec.observed_at,
            status=rec.status,
        )
        for rec in snapshot.freshness
    ]

    # Translate selected resources into Azure entity references
    canonical_entities = [
        AzureEntityRef(type="azure", resource_id=res.resource_id)
        for res in snapshot.selected_resources
    ]

    canonical_snapshot = EvidenceSnapshotV2(
        page_kind=snapshot.page_kind,
        page_id=snapshot.page_id,
        coverage=SnapshotCoverage(
            visible_count=len(snapshot.evidence),
            total_count=len(snapshot.evidence),
            complete=False,
        ),
        evidence=canonical_evidence,
        freshness=canonical_freshness,
        selected_entities=canonical_entities,
        material_claims=_page_material_claims(canonical_evidence),
    )
    request = CanonicalInvestigationRequest(
        question=snapshot.question,
        requested_scope=scope.to_dict(),
        snapshot=canonical_snapshot,
    )

    def _safe_executor(
        name: str,
        arguments: Mapping[str, Any],
        *,
        context: Any,
        scope: Any,
    ) -> ToolResult:
        try:
            return call_tool(
                name,
                arguments,
                context=context,
                scope=scope,
                principal=principal,
            )
        except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
            return ToolResult(
                status=STATUS_UNAVAILABLE,
                warning="Tool unavailable in context canonical mode",
            )

    selected_vnet_id = next(
        (
            resource.resource_id
            for resource in snapshot.selected_resources
            if (
                resource.resource_type.casefold()
                == "microsoft.network/virtualnetworks"
            )
        ),
        "",
    )

    def _selected_vnet_plan(
        _: CanonicalInvestigationRequest,
    ) -> CandidatePlan:
        return CandidatePlan(
            steps=[
                SpecialistStep(
                    specialist_id="network",
                    tool_calls=[
                        ToolCallCandidate(
                            tool="network_topology",
                            arguments={},
                            citation_ids=[COVERAGE_CITATION_ID],
                        ),
                        ToolCallCandidate(
                            tool="hub_dependents",
                            arguments={"vnet_id": selected_vnet_id},
                            citation_ids=[COVERAGE_CITATION_ID],
                        ),
                    ],
                )
            ]
        )

    executive_agent = _canonical_synthesis_agent(context)

    # Canonical proposal→policy→execution loop (no hardcoded planner)
    result = OrchestrationService(
        executor=_safe_executor,
        planner=_selected_vnet_plan if (
            snapshot.page_kind == "network" and selected_vnet_id
        ) else None,
        executive_agent=executive_agent,
        always_synthesize=True,
    ).execute(
        request,
        context=context,
        principal_subject=principal_subject,
        effective_scope=scope,
        stable_key=principal_subject,
    )

    now = datetime.now(UTC).isoformat(timespec="seconds")
    selected_agents = [
        {"id": specialist_id}
        for specialist_id in result.selected_specialists
    ]
    tool_calls = [
        {
            "call_id": tr.get("call_id", ""),
            "tool": tr["tool"],
            "status": tr["status"],
            "data": tr.get("data"),
            "warning": tr.get("warning", ""),
            "specialist_id": tr.get("specialist_id", ""),
            "evidence": list(tr.get("evidence", ())),
            "operation": "delegate",
        }
        for tr in result.tool_results
    ]
    agent_runs = [
        {
            "agent_id": specialist_id,
            "status": (
                "not_started"
                if not any(
                    call["specialist_id"] == specialist_id
                    for call in tool_calls
                )
                else "partial"
                if any(
                    call["status"] != STATUS_OK
                    for call in tool_calls
                    if call["specialist_id"] == specialist_id
                )
                else STATUS_OK
            ),
            "tool_calls": [
                call
                for call in tool_calls
                if call["specialist_id"] == specialist_id
            ],
        }
        for specialist_id in result.selected_specialists
    ]
    citations = [
        citation.model_dump(mode="json")
        for citation in result.citations
    ]
    synthesis = dict(result.synthesis or {})
    synthesis_mode = str(synthesis.get("mode") or "deterministic")
    narration = str(synthesis.get("narration") or "").strip()
    if not narration:
        narration = "\n\n".join(
            str(claim.get("summary") or "").strip()
            for claim in synthesis.get("claims") or []
            if isinstance(claim, Mapping) and str(claim.get("summary") or "").strip()
        )
    synthesis_agent = str(synthesis.get("agent") or "").strip()
    return {
        "contract_version": result.contract_version,
        "ledger_id": f"ctx-{_uuid.uuid4().hex[:12]}",
        "objective": snapshot.question,
        "scope": scope.to_dict(),
        "created_by": principal_subject,
        "created_at": now,
        "updated_at": now,
        "status": (
            "synthesized" if result.status in ("ok", "empty") else result.status
        ),
        "page_kind": snapshot.page_kind,
        "orchestration": {
            "runtime": "canonical",
            "strategy": "canonical_service",
            "selected_ids": result.selected_specialists,
            "policy_status": result.policy_status,
            "fallback_reason": result.fallback_reason,
        },
        "selected_agents": selected_agents,
        "agent_runs": agent_runs,
        "tool_calls": tool_calls,
        "findings": [
            {
                "finding_id": tr.get("call_id", ""),
                "tool": tr["tool"],
                "specialist_id": tr.get("specialist_id", ""),
                "status": tr["status"],
                "data": tr.get("data"),
                "citation_ids": [
                    citation["citation_id"]
                    for citation in citations
                    if citation["citation_id"].startswith(
                        f"tool:{tr.get('call_id', '')}:"
                    )
                ],
            }
            for tr in result.tool_results
            if tr.get("data")
        ],
        "synthesis": {
            "mode": synthesis_mode,
            "narration": narration,
            "synthesis_mode": synthesis_mode,
            "synthesis_agent": synthesis_agent,
            "status": result.status,
            "policy_status": result.policy_status,
            "fallback_reason": result.fallback_reason,
            "coverage": result.coverage.model_dump(mode="json"),
            "uncertainty": list(result.uncertainty),
            "executive": synthesis,
        },
        "synthesis_mode": synthesis_mode,
        "synthesis_agent": synthesis_agent,
        "citations": citations,
        "warnings": list(result.uncertainty),
        "stop_reason": "reassessed",
        "human_controls": {
            "available_actions": [
                "request_more_evidence",
                "approve_plan",
                "stop_investigation",
            ]
        },
        "decisions": [],
        "approvals": [],
        "thread_id": result.thread_id,
    }


@router.post(
    "/copilot/investigate-context",
    summary="Investigate the exact state shown on a supported page",
)
def investigate_context(
    payload: ContextInvestigationRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Validate, analyze, and ledger a bounded contextual investigation."""
    snapshot = payload.snapshot
    try:
        snapshot.validate_effective_scope(scope)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={"field": "snapshot.scope"},
        ) from exc
    rollout = copilot_rollout_decision(stable_key=principal.subject)
    canonical_enabled = canonical_orchestration_enabled(
        stable_key=principal.subject,
        decision=rollout,
    )
    try:
        if (
            canonical_enabled
            and snapshot.page_kind in CANONICAL_CONTEXT_PAGE_KINDS
        ):
            ledger = _run_context_via_canonical(
                snapshot,
                context=context,
                scope=scope,
                principal=principal,
                principal_subject=principal.subject,
                rollout_decision=rollout,
            )
        else:
            ledger = run_context_investigation(
                snapshot,
                context=context,
                scope=scope,
                principal_subject=principal.subject,
                principal=principal,
            )
            if canonical_enabled:
                ledger.setdefault("warnings", []).append(
                    f"Canonical context adapter unavailable for {snapshot.page_kind}; "
                    "used the explicit legacy rollback path."
                )
                ledger["orchestration"] = {
                    **dict(ledger.get("orchestration") or {}),
                    "fallback_reason": "unsupported_canonical_page_kind",
                }
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation continuity is temporarily unavailable",
        ) from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Investigation thread changed; retry the request",
        ) from exc
    ledger_store().add(ledger)
    evidence = [
        Evidence(
            source_engine="operations.PageSnapshot",
            source_table=f"page_snapshot:{snapshot.page_kind}",
            resource_id=row.resource_id,
            timestamp=row.observed_at,
            confidence=CONFIDENCE_MEDIUM,
        )
        for row in snapshot.evidence
    ]
    return envelope(
        ledger,
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=list(ledger["warnings"]),
    )


def _canonical_synthesis_agent(context: Any) -> Any | None:
    """Resolve final narration independently of the planning coordinator."""

    try:
        narrator = context.specialist_agent("executive_summary")
    except (ApiError, ConnectionError, FoundryAgentError, TimeoutError) as exc:
        logger.warning(
            "canonical executive narrator unavailable",
            extra={
                "provider_role": "executive_summary",
                "exception_class": type(exc).__name__,
            },
        )
        return None
    if narrator is None:
        return None
    return FoundryCoordinatorSynthesisAgent(narrator)


@router.post(
    "/copilot/investigations",
    summary="Run a canonical governed Operations Copilot investigation",
)
def investigate_canonical(
    payload: CanonicalInvestigationPayload,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Authorize a versioned request and invoke only the canonical service."""

    request = CanonicalInvestigationRequest.model_validate(
        payload.model_dump(exclude={"hint"})
    )
    browser_snapshot = request.snapshot
    _validate_bound_cve_request(payload, browser_snapshot)
    exact_inventory_starter = (
        browser_snapshot.page_kind == "inventory"
        and inventory_starter_kind(payload.question) is not None
    )
    if (
        exact_inventory_starter
        and not valid_inventory_page_snapshot(browser_snapshot)
    ):
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Inventory page evidence failed the exact bounded contract",
            details={"field": "snapshot"},
        )
    unresolved_domain_evidence_excluded = False
    try:
        semantic = context.resolve_provider(
            "semantic",
            optional=True,
        )
        semantic_unavailable = semantic is None
        selected_inventory_domain_unresolved = (
            exact_inventory_starter
            and any(
                isinstance(entity, DomainEntityRef)
                for entity in browser_snapshot.selected_entities
            )
        )
        has_domain_evidence = any(
            isinstance(entity, DomainEntityRef)
            for entity in [
                *browser_snapshot.selected_entities,
                *[
                    item.entity
                    for item in browser_snapshot.evidence
                    if item.entity is not None
                ],
            ]
        )
        unresolved_domain_evidence_excluded = (
            selected_inventory_domain_unresolved
            or (
                semantic_unavailable
                and not exact_inventory_starter
                and has_domain_evidence
            )
        )
        selection_snapshot = (
            _without_unresolved_domain_evidence(browser_snapshot)
            if (
                semantic_unavailable
                and not exact_inventory_starter
            )
            or selected_inventory_domain_unresolved
            else _with_bounded_overview_observations(browser_snapshot)
        )
        resolved_domains: dict[
            tuple[str, str, str],
            tuple[dict[str, Any], DomainEntityRef],
        ] = {}

        def resolve_domain_entity(
            entity: DomainEntityRef,
        ) -> Mapping[str, Any] | None:
            key = (
                entity.namespace.casefold(),
                entity.kind.casefold(),
                entity.source_key.casefold(),
            )
            cached = resolved_domains.get(key)
            if cached is not None:
                return cached[0]
            if semantic is None:
                return None
            try:
                entity_id = semantic.indexes.resolve(entity.source_key)
            except (LookupError, ValueError):
                return None
            public = semantic.indexes.public(entity_id)
            entity_type = str(public.get("entity_type") or "").strip()
            resolved_scope = scope_attributes(public)
            if not entity_type or not resolved_scope:
                return None
            resolution = {
                "namespace": "semantic",
                "kind": entity_type,
                "source_key": entity_id,
                "scope": resolved_scope,
            }
            resolved_domains[key] = (
                resolution,
                DomainEntityRef(
                    type="domain",
                    namespace="semantic",
                    kind=entity_type,
                    source_key=entity_id,
                ),
            )
            return resolution

        # The strict Pydantic contract above validates every browser row and
        # byte/list bound. Resolve retained domain identities against the
        # server's semantic index before either planning or retained synthesis.
        canonical_browser_snapshot = (
            canonicalize_snapshot_v2(
                selection_snapshot,
                effective_scope=scope,
                domain_resolver=resolve_domain_entity,
            )
            if browser_snapshot.page_kind != "inventory"
            else None
        )
        planning_entities: list[AzureEntityRef | DomainEntityRef] = []
        planning_entity_ids: set[str] = set()
        for entity in [
            *selection_snapshot.selected_entities,
            *[
                (
                    item.entity
                    if isinstance(item.entity, AzureEntityRef)
                    else AzureEntityRef(type="azure", resource_id=item.resource_id)
                )
                for item in selection_snapshot.evidence
                if (
                    item.selected or item.direct
                )
                and (
                    isinstance(item.entity, AzureEntityRef)
                    or item.resource_id.startswith("/")
                )
            ],
        ]:
            if isinstance(entity, DomainEntityRef):
                resolved = resolved_domains.get(
                    (
                        entity.namespace.casefold(),
                        entity.kind.casefold(),
                        entity.source_key.casefold(),
                    )
                )
                if resolved is None:
                    resolution = resolve_domain_entity(entity)
                    if (
                        resolution is None
                        or not scope.matches(resolution["scope"])
                    ):
                        raise ValueError(
                            "snapshot entity is outside the effective read scope"
                        )
                    resolved = resolved_domains.get(
                        (
                            entity.namespace.casefold(),
                            entity.kind.casefold(),
                            entity.source_key.casefold(),
                        )
                    )
                if resolved is None:
                    raise ValueError("snapshot domain entity could not be resolved")
                entity = resolved[1]
            if isinstance(entity, AzureEntityRef):
                key = f"azure:{entity.resource_id.casefold()}"
            else:
                key = (
                    f"domain:{entity.namespace.casefold()}:"
                    f"{entity.kind.casefold()}:{entity.source_key.casefold()}"
                )
            if key in planning_entity_ids:
                continue
            planning_entity_ids.add(key)
            planning_entities.append(entity)
            if len(planning_entities) == 50:
                break
        planning_snapshot = selection_snapshot.model_copy(
            update={
                "page_kind": selection_snapshot.page_kind,
                "coverage": selection_snapshot.coverage.model_copy(
                    update={"complete": False}
                ),
                "freshness": [
                    item.model_copy(update={"status": "unavailable"})
                    for item in selection_snapshot.freshness
                ],
                "selected_entities": planning_entities,
                "evidence": [],
                "material_claims": [],
            }
        )
        if browser_snapshot.page_kind == "inventory":
            canonical_browser_snapshot = canonicalize_snapshot_v2(
                planning_snapshot,
                effective_scope=scope,
                domain_resolver=resolve_domain_entity,
            )
    except (TypeError, ValueError) as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={"field": "snapshot"},
        ) from exc
    request = request.model_copy(
        update={
            # Only scope-validated Azure identities survive into planning.
            # Browser facts remain non-authoritative and are passed separately
            # for citation-closed synthesis.
            "snapshot": planning_snapshot
        }
    )
    try:
        plan_hint = _validated_or_derived_network_hint(
            payload,
            browser_snapshot,
        )
    except ValueError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={
                "field": (
                    "hint.arguments.vnet_id"
                    if payload.hint is not None
                    else "question"
                )
            },
        ) from exc
    execution_payload = payload.model_copy(update={"hint": plan_hint})
    rollout = copilot_rollout_decision(stable_key=principal.subject)
    hint_candidate: CandidatePlan | None = None
    if browser_snapshot.page_kind == "inventory":
        try:
            selector = _inventory_selector(browser_snapshot)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                ErrorCode.INVALID_REQUEST,
                str(exc),
                details={"field": "snapshot.evidence"},
            ) from exc
        specialist_id = (
            plan_hint.specialist_id
            if plan_hint is not None
            else INVENTORY_DATA_HEALTH_ID
        )
        tool = (
            plan_hint.tool
            if plan_hint is not None
            else "inventory_resources"
        )
        derived_arguments = selector.tool_arguments()
        hint_arguments = (
            dict(plan_hint.arguments) if plan_hint is not None else {}
        )
        selector_conflict = any(
            key in hint_arguments and hint_arguments[key] != value
            for key, value in derived_arguments.items()
        )
        candidate_arguments = {
            **hint_arguments,
            **derived_arguments,
            **({"selector_conflict": True} if selector_conflict else {}),
        }
        planner = lambda _request: CandidatePlan(
            steps=[
                SpecialistStep(
                    specialist_id=specialist_id,
                    tool_calls=[
                        ToolCallCandidate(
                            tool=tool,
                            arguments=candidate_arguments,
                            citation_ids=[COVERAGE_CITATION_ID],
                        )
                    ],
                )
            ],
            estimated_tokens=0,
            max_wall_seconds=5,
        )
        executor = _inventory_executor(selector)
    else:
        planner = (
            (
                lambda _request: CandidatePlan(
                    steps=[
                        SpecialistStep(
                            specialist_id=plan_hint.specialist_id,
                            tool_calls=[
                                ToolCallCandidate(
                                    tool=plan_hint.tool,
                                    arguments=dict(plan_hint.arguments),
                                    citation_ids=[COVERAGE_CITATION_ID],
                                )
                            ],
                        )
                    ],
                    estimated_tokens=0,
                    max_wall_seconds=5,
                )
            )
            if plan_hint is not None
            else (
                lambda governed_request: build_deterministic_fallback(
                    governed_request,
                    load_specialist_manifest(),
                )
            )
        )
        hint_candidate = planner(request) if plan_hint is not None else None

        def executor(
            name: str,
            arguments: Mapping[str, Any],
            *,
            context: Any,
            scope: Any,
        ) -> ToolResult:
            try:
                return call_tool(
                    name,
                    arguments,
                    context=context,
                    scope=scope,
                    principal=principal,
                )
            except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
                return ToolResult(
                    status=STATUS_UNAVAILABLE,
                    warning="Tool unavailable in canonical page mode",
                )

    if (
        hint_candidate is None
        and (plan_hint is not None or browser_snapshot.page_kind == "inventory")
    ):
        hint_candidate = planner(request)
    coordinator = context.foundry_agent()
    coordinator_version = str(
        getattr(coordinator, "agent_version", "") or ""
    ).strip()
    coordinator_enabled = (
        coordinator is not None
        and str(getattr(coordinator, "agent_name", "")).strip()
        == "operations-copilot"
        and bool(coordinator_version)
        and coordinator_version not in {"1", "2", "3", "4"}
    )
    coordinator_synthesis = None
    required_candidate = hint_candidate
    if rollout.canonical_enabled and coordinator_enabled:
        required_hint = None
        if required_candidate is not None:
            required_step = required_candidate.steps[0]
            required_call = required_step.tool_calls[0]
            required_hint = {
                "specialist_id": required_step.specialist_id,
                "tool": required_call.tool,
                "arguments": dict(required_call.arguments),
            }
        planner = FoundryCoordinatorPlanner(
            coordinator,
            required_hint=required_hint,
        )
        coordinator_synthesis = _canonical_synthesis_agent(context)

    try:
        if plan_hint is not None and hint_candidate is not None:
            OrchestrationPolicy().validate(
                request=request,
                candidate=hint_candidate,
                effective_scope=scope,
            )
        if rollout.canonical_enabled:
            result = OrchestrationService(
                planner=planner,
                fallback_planner=(
                    (lambda _request: required_candidate)
                    if required_candidate is not None
                    else (
                        lambda governed_request: build_deterministic_fallback(
                            governed_request,
                            load_specialist_manifest(),
                        )
                    )
                ),
                executor=executor,
                executive_agent=coordinator_synthesis,
                always_synthesize=coordinator_synthesis is not None,
            ).execute(
                request,
                context=context,
                principal_subject=principal.subject,
                effective_scope=scope,
                stable_key=principal.subject,
                selection_snapshot=selection_snapshot,
                canonical_selection_snapshot=canonical_browser_snapshot,
            )
        else:
            result = _execute_retained_compatibility(
                payload=execution_payload,
                request=request,
                context=context,
                scope=scope,
                principal=principal,
                planned_candidate=required_candidate,
            )
    except PolicyViolation as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={"field": "requested_scope", "reason": exc.code},
        ) from exc
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation continuity is temporarily unavailable",
        ) from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Investigation thread changed; retry the request",
        ) from exc
    except ThreadNotFound as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Investigation thread not found",
            details={"field": "thread_id"},
        ) from exc

    if unresolved_domain_evidence_excluded:
        semantic_warning = (
            "Semantic identity resolution is unavailable; unresolved domain "
            "page evidence was excluded."
        )
        result = result.model_copy(
            update={
                "uncertainty": list(
                    dict.fromkeys([*result.uncertainty, semantic_warning])
                )
            }
        )

    if rollout.canonical_enabled and coordinator_enabled:
        result = result.model_copy(
            update={
                "synthesis": {
                    **(result.synthesis or {}),
                    "coordinator": {
                        "name": str(
                            getattr(coordinator, "agent_name", "")
                            or "operations-copilot"
                        ),
                        "version": str(
                            coordinator_version
                        ),
                        "planned": result.policy_status == "accepted",
                        "delegation_mode": "governed_local_tools",
                    },
                }
            }
        )

    shadow_validated = False
    shadow_reason = ""
    comparison: dict[str, Any] | None = None
    if rollout.shadow_enabled:
        canonical_preview, shadow_validated = _canonical_plan_preview(
            planner=planner,
            request=request,
            scope=scope,
        )
        comparison = _shadow_comparison(
            compatibility=result,
            canonical=canonical_preview,
        )
        if not shadow_validated:
            shadow_reason = str(canonical_preview["fallback_reason"])
        elif comparison["divergent_fields"]:
            shadow_reason = (
                "diverged:" + ",".join(comparison["divergent_fields"])
            )
        else:
            shadow_reason = "accepted"

    result_data = result.model_dump(mode="json")
    result_data["rollout"] = {
        "mode": rollout.mode,
        "canonical_enabled": rollout.canonical_enabled,
        "shadow_enabled": rollout.shadow_enabled,
        "shadow_validated": shadow_validated,
        "shadow_reason": shadow_reason,
        **(
            {
                "authorization_id": rollout.authorization_id,
                "authorization_manifest_sha256": (
                    rollout.authorization_manifest_sha256
                ),
            }
            if rollout.authorization_id
            else {}
        ),
    }
    if comparison is not None:
        result_data["rollout"]["comparison"] = comparison
        result_data["rollout"]["canonical_preview_external_io"] = (
            canonical_preview["external_io"]
        )
    synthesis_evidence_refs = {
        str(reference)
        for claim in (result_data.get("synthesis") or {}).get("claims", [])
        for reference in claim.get("evidence_refs", [])
    }
    result_data["citations"] = [
        citation
        for citation in result_data["citations"]
        if (
            (
                citation["citation_id"] == COVERAGE_CITATION_ID
                and COVERAGE_CITATION_ID in synthesis_evidence_refs
            )
            or citation["citation_id"].startswith(("tool:", "retained:"))
        )
    ]
    return envelope(
        result_data,
        scope=scope.to_dict(),
        warnings=list(result.uncertainty),
    )


@router.get("/copilot/threads", summary="Discover authorized retained investigation threads")
def retained_threads(
    context: Context, scope: ReadScope, principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=0, le=31)] = 0,
) -> dict[str, Any]:
    """List one bounded principal/scope-authorized storage page, without tools."""
    try:
        data = investigation_thread_store().list_owned(principal.subject, scope, page=page)
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Retained thread discovery is temporarily unavailable",
        ) from exc
    return envelope(data, scope=scope.to_dict(), warnings=[
        "Storage-order discovery is not chronological or a snapshot. Pages may be empty after authorization or expiry; reads do not renew retention.",
    ])


@router.get("/copilot/threads/{thread_id}/history", summary="Read exact retained historical turns")
def retained_thread_history(
    thread_id: str, context: Context, scope: ReadScope, principal: CurrentPrincipal,
    expected_revision: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Read one exact owned thread, without executing or renewing its lifetime."""
    if not re.fullmatch(r"thr-[a-f0-9]{32}", thread_id):
        raise ApiError(ErrorCode.NOT_FOUND, "Investigation thread not found")
    try:
        data = investigation_thread_store().read_snapshot(
            thread_id, principal.subject, scope, expected_revision=expected_revision,
        )
    except ThreadNotFound as exc:
        raise ApiError(ErrorCode.NOT_FOUND, "Investigation thread not found") from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Retained thread changed since the reviewed revision. No newer evidence was substituted.",
        ) from exc
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation history is temporarily unavailable",
        ) from exc
    return envelope(
        data, scope=scope.to_dict(),
        warnings=[
            (
                "Retained historical observations, not current evidence or resumed "
                "execution. Reading does not renew retention, rerun tools, change "
                "the active thread or authorize an operational action."
            )
        ],
    )


@router.get("/copilot/history/{session_id}", summary="Bounded conversation history")
def history(session_id: str, context: Context, scope: ReadScope, principal: CurrentPrincipal) -> dict[str, Any]:
    """Prior turns for one caller's session -- never visible to another principal."""
    try:
        turns = (
            legacy_session_history(
                session_id,
                principal_subject=principal.subject,
                scope=scope,
            )
            if canonical_orchestration_enabled(stable_key=principal.subject)
            else conversation_store().history(session_id, principal.subject)
        )
    except ThreadStoreUnavailable as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Investigation continuity is temporarily unavailable",
        ) from exc
    except ThreadRevisionConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "Investigation thread changed; retry the request",
        ) from exc
    return envelope({"session_id": session_id, "turns": turns}, scope=scope.to_dict())


def tool_catalog_names() -> set[str]:
    return {entry["name"] for entry in tool_catalog()}
