"""Canonical governed orchestration service for the Inventory tracer."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from api.scope import Scope
from operations.foundry_agent import FoundryAgentError
from operations.investigation_thread_store import (
    InvestigationThreadStore,
    ThreadNotFound,
    investigation_thread_store,
)
from operations.maf_orchestrator import (
    build_deterministic_fallback,
    select_specialists_for_turn,
)
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
    CandidatePlan,
    Citation,
    EvidenceSnapshotV2,
    InvestigationRequest,
    OrchestrationResult,
    SnapshotCoverage,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import OrchestrationPolicy, PolicyViolation
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


class PlannerUnavailableError(RuntimeError):
    """The configured planner adapter cannot currently produce a proposal."""


class PlannerTimeoutError(TimeoutError):
    """The configured planner adapter exceeded its bounded response time."""


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

    catalog = tuple(
        type(
            "_CatalogEntry",
            (),
            {"id": specialist.id, "keywords": specialist.intent_examples},
        )()
        for specialist in manifest.specialists
    )
    decision = select_specialists_for_turn(
        page_kind="investigate",
        question=question,
        page_specialists=manifest.page_mapping_projection(),
        catalog=catalog,
        limit=1,
    )
    if decision.selected_ids:
        specialist = manifest.require(decision.selected_ids[0])
        return _preferred_page_kind(specialist), specialist
    return "investigate", None


def _legacy_session_thread(
    session_id: str,
    principal_subject: str,
) -> str | None:
    if not session_id:
        return None
    key = (principal_subject, session_id)
    with _legacy_session_lock:
        thread_id = _legacy_session_threads.get(key)
        if thread_id is not None:
            _legacy_session_threads.move_to_end(key)
        return thread_id


def _remember_legacy_session_thread(
    session_id: str,
    principal_subject: str,
    thread_id: str,
) -> None:
    if not session_id:
        return
    key = (principal_subject, session_id)
    with _legacy_session_lock:
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
    with _legacy_session_lock:
        _legacy_session_threads.pop((principal_subject, session_id), None)


class OrchestrationService:
    """Execute a fully validated plan and persist only authorized result state."""

    def __init__(
        self,
        *,
        planner: Planner | None = None,
        executor: Executor = _default_executor,
        policy: OrchestrationPolicy | None = None,
        thread_store: InvestigationThreadStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.policy = policy or OrchestrationPolicy()
        self.thread_store = thread_store or investigation_thread_store()
        self.clock = clock

    def execute(
        self,
        request: InvestigationRequest,
        *,
        context: Any,
        principal_subject: str,
        effective_scope: Scope,
    ) -> OrchestrationResult:
        """Execute one canonical request after all authorization gates pass."""

        requested_scope = self.policy.validate_request(request, effective_scope)
        if request.thread_id:
            thread = self.thread_store.authorize(
                request.thread_id,
                principal_subject,
                requested_scope,
            )
        else:
            thread = self.thread_store.create(principal_subject, requested_scope)

        started = self.clock()
        candidate, policy_status, fallback_reason = self._resolve_candidate(
            request,
            effective_scope,
        )
        deadline = started + min(
            candidate.max_wall_seconds,
            self.policy.limits.max_wall_seconds,
        )
        tool_results: list[dict[str, Any]] = []
        tool_statuses: list[str] = []
        citations = self._snapshot_citations(request)
        selected_specialists: list[str] = []
        selected_tools: list[str] = []
        budget_exhausted = False

        for step_index, step in enumerate(candidate.steps):
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
                call_id = (
                    f"{step_index}:{call_index}:{step.specialist_id}:{call.tool}"
                )
                tool_results.append(
                    {
                        "call_id": call_id,
                        "specialist_id": step.specialist_id,
                        "tool": call.tool,
                        **result.to_dict(),
                    }
                )
                for index, evidence in enumerate(result.evidence):
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
                            resource_id=evidence.resource_id,
                        )
                    )
                if self.clock() >= deadline:
                    budget_exhausted = True
                    break
            if budget_exhausted:
                break

        uncertainty = self._uncertainty(
            request,
            tool_statuses,
            budget_exhausted=budget_exhausted,
        )
        status = self._result_status(
            tool_statuses,
            uncertainty,
            budget_exhausted=budget_exhausted,
        )
        result = OrchestrationResult(
            status=status,
            policy_status=policy_status,
            fallback_reason=fallback_reason,
            selected_specialists=selected_specialists,
            selected_tools=selected_tools,
            tool_results=tool_results,
            uncertainty=uncertainty,
            coverage=request.snapshot.coverage,
            citations=self._deduplicate_citations(citations),
            thread_id=thread.thread_id,
            thread_revision=thread.revision + 1,
        )
        updated = self.thread_store.append(
            thread.thread_id,
            principal_subject,
            requested_scope,
            result.model_dump(mode="json"),
        )
        return result.model_copy(update={"thread_revision": updated.revision})

    def _resolve_candidate(
        self,
        request: InvestigationRequest,
        effective_scope: Scope,
    ) -> tuple[CandidatePlan, str, str]:
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
    ) -> tuple[CandidatePlan, str, str]:
        fallback = _fallback_candidate(request)
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
        tool_statuses: list[str],
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
        for status in tool_statuses:
            if status in {STATUS_UNAVAILABLE, STATUS_DENIED}:
                uncertainty.append(f"inventory tool status is {status}")
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
    session_id: str = "",
    hint_tool: str = "",
    hint_arguments: Mapping[str, Any] | None = None,
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
        thread_id=_legacy_session_thread(session_id, principal_subject),
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
    if hint_tool:
        manifest = load_specialist_manifest()
        specialist_id = (
            hinted_specialist.id
            if hinted_specialist is not None
            else next(
                specialist_id
                for specialist_id in manifest.page_mapping_projection()[page_kind]
                if specialist_id != "executive_summary"
            )
        )

        def _hint_planner(_request: InvestigationRequest) -> CandidatePlan:
            return CandidatePlan(
                steps=[
                    SpecialistStep(
                        specialist_id=specialist_id,
                        tool_calls=[
                            ToolCallCandidate(
                                tool=hint_tool,
                                arguments=dict(hint_arguments or {}),
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
    try:
        result = service.execute(
            request,
            context=context,
            principal_subject=principal_subject,
            effective_scope=scope,
        )
    except ThreadNotFound:
        _forget_legacy_session_thread(session_id, principal_subject)
        result = service.execute(
            request.model_copy(update={"thread_id": None}),
            context=context,
            principal_subject=principal_subject,
            effective_scope=scope,
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
    except ThreadNotFound:
        _forget_legacy_session_thread(session_id, principal_subject)
        return []


__all__ = [
    "OrchestrationService",
    "PlannerTimeoutError",
    "PlannerUnavailableError",
    "execute_from_question",
    "legacy_session_history",
]
