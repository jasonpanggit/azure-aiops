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
import time
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from operations.autonomous_investigation import ledger_store, run_context_investigation
from operations.foundry_agent import FoundryAgentError
from operations.investigation import (
    conversation_store,
    run_investigation,
    tool_catalog,
)
from operations.investigation_thread_store import ThreadNotFound
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    CandidatePlan,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_contract import (
    InvestigationRequest as CanonicalInvestigationRequest,
)
from operations.orchestration_policy import PolicyViolation
from operations.orchestration_service import OrchestrationService
from operations.page_context import PageSnapshot
from operations.specialist_manifest import INVENTORY_DATA_HEALTH_ID
from operations.tools import (
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    ToolResult,
    call_tool,
)

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, Evidence, envelope
from ..scope import Scope, scope_attributes

logger = logging.getLogger("aiops.api.copilot")
audit_logger = logging.getLogger("aiops.api.copilot.audit")

router = APIRouter(prefix="/api/v1", tags=["copilot"])

SOURCE_ENGINE = "semantic.SemanticEngine"
NARRATION_ENGINE = "operations.FoundryPromptAgent"

# Per-turn wall-clock budget for the whole investigation (planning + every
# tool call + narration). A question that cannot be answered inside this
# budget is reported as partial rather than left to hang the request.
INVESTIGATION_TIMEOUT_SECONDS = 20.0

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
    """Versioned canonical request plus an optional policy-checked hint."""

    hint: CanonicalPlanHint | None = None


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
        {**raw_data, "total": total}
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
        if validated.family in {"os", "paas"} and not resource_selector.startswith("group:"):
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
        subscription_ids = list(scope.values("subscription"))
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
    if payload.tool and payload.tool not in tool_catalog_names():
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            f"Unknown tool {payload.tool!r}",
            details={"supported_tools": sorted(tool_catalog_names())},
        )

    started = time.monotonic()
    investigation = run_investigation(
        question,
        context=context,
        scope=scope,
        principal=principal,
        hint_tool=payload.tool or None,
        hint_args=payload.tool_arguments,
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
    ledger = run_context_investigation(
        snapshot,
        context=context,
        scope=scope,
        principal_subject=principal.subject,
    )
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
    try:
        selector = _inventory_selector(browser_snapshot)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={"field": "snapshot.evidence"},
        ) from exc
    request = request.model_copy(
        update={
            "snapshot": browser_snapshot.model_copy(
                update={
                    "coverage": browser_snapshot.coverage.model_copy(
                        update={"complete": False}
                    ),
                    "freshness": [
                        item.model_copy(update={"status": "unavailable"})
                        for item in browser_snapshot.freshness
                    ],
                    # Browser rows select relevant governed tools but are never
                    # promoted into server citations or persisted as authority.
                    "evidence": [],
                }
            )
        }
    )
    specialist_id = (
        payload.hint.specialist_id
        if payload.hint is not None
        else INVENTORY_DATA_HEALTH_ID
    )
    tool = payload.hint.tool if payload.hint is not None else "inventory_resources"
    derived_arguments = selector.tool_arguments()
    hint_arguments = dict(payload.hint.arguments) if payload.hint is not None else {}
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

    try:
        result = OrchestrationService(
            planner=planner,
            executor=_inventory_executor(selector),
        ).execute(
            request,
            context=context,
            principal_subject=principal.subject,
            effective_scope=scope,
        )
    except PolicyViolation as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            str(exc),
            details={"field": "requested_scope", "reason": exc.code},
        ) from exc
    except ThreadNotFound as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Investigation thread not found",
            details={"field": "thread_id"},
        ) from exc

    result_data = result.model_dump(mode="json")
    result_data["citations"] = [
        citation
        for citation in result_data["citations"]
        if citation["citation_id"].startswith("tool:")
    ]
    return envelope(
        result_data,
        scope=scope.to_dict(),
        warnings=list(result.uncertainty),
    )


@router.get("/copilot/history/{session_id}", summary="Bounded conversation history")
def history(session_id: str, context: Context, scope: ReadScope, principal: CurrentPrincipal) -> dict[str, Any]:
    """Prior turns for one caller's session -- never visible to another principal."""
    turns = conversation_store().history(session_id, principal.subject)
    return envelope({"session_id": session_id, "turns": turns}, scope=scope.to_dict())


def tool_catalog_names() -> set[str]:
    return {entry["name"] for entry in tool_catalog()}
