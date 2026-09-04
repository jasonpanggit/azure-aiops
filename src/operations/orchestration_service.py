"""Canonical governed orchestration service for the Inventory tracer."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError

from api.scope import Scope
from operations.investigation_thread_store import (
    InvestigationThreadStore,
    investigation_thread_store,
)
from operations.orchestration_contract import (
    CandidatePlan,
    Citation,
    InvestigationRequest,
    OrchestrationResult,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import OrchestrationPolicy, PolicyViolation
from operations.specialist_manifest import INVENTORY_DATA_HEALTH_ID
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


def _default_executor(
    name: str,
    arguments: Mapping[str, Any],
    *,
    context: Any,
    scope: Scope,
) -> ToolResult:
    return call_tool(name, arguments, context=context, scope=scope)


def _fallback_candidate(request: InvestigationRequest) -> CandidatePlan:
    return CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=[
                            item.evidence_id for item in request.snapshot.evidence
                        ],
                    )
                ],
            )
        ],
        estimated_tokens=0,
        max_wall_seconds=5,
    )


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

        for step in candidate.steps:
            selected_specialists.append(step.specialist_id)
            for call in step.tool_calls:
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
                tool_results.append(
                    {
                        "specialist_id": step.specialist_id,
                        "tool": call.tool,
                        **result.to_dict(),
                    }
                )
                for index, evidence in enumerate(result.evidence):
                    citations.append(
                        Citation(
                            citation_id=f"tool:{call.tool}:{index}",
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
        except TimeoutError:
            return self._validated_fallback(
                request,
                effective_scope,
                "planner_timeout",
            )
        except ConnectionError:
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
        return [
            Citation(
                citation_id=item.evidence_id,
                source=item.source,
                status=item.status,
                observed_at=item.observed_at,
                resource_id=item.resource_id,
            )
            for item in request.snapshot.evidence
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


__all__ = ["OrchestrationService"]
