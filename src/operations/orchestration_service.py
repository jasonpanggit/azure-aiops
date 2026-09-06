"""Canonical governed orchestration service for the Inventory tracer."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from api.scope import Scope
from operations.foundry_agent import (
    FoundryAgentError,
    executive_synthesis_input,
    normalize_cited_findings,
    validate_executive_synthesis,
)
from operations.investigation_thread_store import (
    OBSERVATION_CURRENT,
    OBSERVATION_HISTORICAL,
    InvestigationThread,
    InvestigationThreadStore,
    ThreadNotFound,
    ThreadRevisionConflict,
    investigation_thread_store,
)
from operations.maf_orchestrator import (
    build_deterministic_fallback,
    select_specialists_for_turn,
)
from operations.mcp_server import validate_tool_arguments
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
    decision = select_specialists_for_turn(
        page_kind="investigate",
        question=question,
        page_specialists=manifest.page_mapping_projection(),
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
        thread_id = _legacy_session_threads.get(key)
        if thread_id is None:
            thread_id = investigation_thread_store().resolve_legacy_binding(
                session_id,
                principal_subject,
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
        thread_id = _legacy_session_threads.get(key)
        if thread_id is None:
            thread_id = _adopt_or_create_thread(
                session_id,
                principal_subject,
                scope,
            )
            thread_id = investigation_thread_store().bind_legacy_session(
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


@dataclass(frozen=True)
class OrchestrationTurn:
    """One canonical result plus the synthesis outcome that accompanied it."""

    result: OrchestrationResult
    synthesis: ExecutiveSynthesis


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
        executive_agent: Any = None,
        telemetry: Any = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.policy = policy or OrchestrationPolicy()
        self.thread_store = thread_store or investigation_thread_store()
        self.clock = clock
        self.executive_agent = executive_agent
        self.telemetry = telemetry

    def execute(
        self,
        request: InvestigationRequest,
        *,
        context: Any,
        principal_subject: str,
        effective_scope: Scope,
        max_wall_seconds: float | None = None,
    ) -> OrchestrationResult:
        """Execute one canonical request and return only the canonical result."""

        return self.execute_turn(
            request,
            context=context,
            principal_subject=principal_subject,
            effective_scope=effective_scope,
            max_wall_seconds=max_wall_seconds,
        ).result

    def execute_turn(
        self,
        request: InvestigationRequest,
        *,
        context: Any,
        principal_subject: str,
        effective_scope: Scope,
        max_wall_seconds: float | None = None,
    ) -> OrchestrationTurn:
        """Execute one canonical request after all authorization gates pass."""

        if self.telemetry is None:
            api_telemetry = getattr(context, "telemetry", None)
            self.telemetry = getattr(api_telemetry, "orchestration", None)
        if self.executive_agent is None:
            resolver = getattr(context, "foundry_agent", None)
            if callable(resolver):
                try:
                    self.executive_agent = resolver()
                except (ConnectionError, FoundryAgentError, TimeoutError):
                    self.executive_agent = None

        requested_scope = self.policy.validate_request(request, effective_scope)
        if request.thread_id:
            thread = self.thread_store.authorize(
                request.thread_id,
                principal_subject,
                requested_scope,
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
        wall_seconds = min(
            candidate.max_wall_seconds,
            self.policy.limits.max_wall_seconds,
        )
        if max_wall_seconds is not None:
            wall_seconds = min(wall_seconds, max(0.0, max_wall_seconds))
        deadline = started + wall_seconds
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
                self._record_delegation_metric(
                    specialist_id=step.specialist_id,
                    tool=call.tool,
                    status=result.status,
                    policy_status=policy_status,
                    started=started,
                    evidence_count=len(result.evidence),
                )
                call_id = (
                    f"{step_index}:{call_index}:{step.specialist_id}:{call.tool}"
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
        synthesis = self._synthesize(
            request.question,
            tool_results,
            retained_evidence=self._retained_evidence(thread),
        )
        if synthesis.warning:
            uncertainty = [*uncertainty, synthesis.warning]
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
            coverage=request.snapshot.coverage,
            citations=self._deduplicate_citations(citations),
            thread_id=thread.thread_id,
            thread_revision=thread.revision + 1,
        )
        return OrchestrationTurn(
            result=self._record_turn(
                thread,
                principal_subject=principal_subject,
                requested_scope=requested_scope,
                question=request.question,
                result=result,
            ),
            synthesis=synthesis,
        )

    # -- conditional executive synthesis ----------------------------------

    @staticmethod
    def _retained_evidence(thread: InvestigationThread) -> list[dict[str, Any]]:
        """Project the thread's retained citations for synthesis reconciliation.

        Only identity, source, status, and observation status travel: carried
        evidence exists so synthesis can say "this was true an hour ago", not
        so a second model can re-read raw provider payloads.
        """

        retained: list[dict[str, Any]] = []
        for turn in thread.turns:
            for citation in turn.payload.get("citations") or []:
                if not isinstance(citation, Mapping):
                    continue
                retained.append(
                    {
                        "evidence_id": str(citation.get("citation_id") or ""),
                        "source": str(citation.get("source") or ""),
                        "status": str(citation.get("status") or ""),
                        "observation_status": OBSERVATION_HISTORICAL,
                    }
                )
        return retained

    def _synthesize(
        self,
        question: str,
        tool_results: Sequence[Mapping[str, Any]],
        *,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> ExecutiveSynthesis:
        """Run at most one citation-closed aggregation call, or none at all."""

        findings = normalize_cited_findings(tool_results)
        decision = executive_synthesis_decision(question, findings)
        if not decision.admitted:
            synthesis = ExecutiveSynthesis(
                status="skipped",
                reason=decision.reason,
                domain_count=decision.domain_count,
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if self.executive_agent is None:
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was unavailable; direct specialist "
                    "findings are shown instead."
                ),
            )
            self._record_synthesis_metric(synthesis)
            return synthesis

        stage_started = self.clock() if self.telemetry is not None else 0.0
        evidence_refs = {
            ref for finding in findings for ref in finding["evidence_refs"]
        }
        try:
            answer = self.executive_agent.answer(
                question=question,
                context=executive_synthesis_input(
                    findings,
                    retained_evidence=retained_evidence,
                ),
            )
            claims = validate_executive_synthesis(
                getattr(answer, "text", ""),
                evidence_refs=evidence_refs,
            )
        except FoundryAgentError:
            # A rejected or unreachable narrator must not remove the evidence
            # the specialists already produced, so the turn degrades to their
            # direct findings and says so rather than failing.
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was withheld; direct specialist "
                    "findings are shown instead."
                ),
            )
        except (AttributeError, ConnectionError, TimeoutError, TypeError, ValueError):
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                warning=(
                    "Executive synthesis was withheld; direct specialist "
                    "findings are shown instead."
                ),
            )
        else:
            synthesis = ExecutiveSynthesis(
                status="synthesized",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=claims,
            )
        self._record_stage_metric("synthesis", stage_started)
        self._record_synthesis_metric(synthesis)
        return synthesis

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
        )

    def _record_turn(
        self,
        thread: InvestigationThread,
        *,
        principal_subject: str,
        requested_scope: Scope,
        question: str,
        result: OrchestrationResult,
    ) -> OrchestrationResult:
        """Append one turn under optimistic concurrency and report the outcome.

        Two tabs on the same thread are a normal thing for an operator to do,
        so a superseded revision is reconciled once against the current record
        rather than failing the turn. The reconciliation is stated in
        ``uncertainty`` so the caller knows its revision was not the one it
        read.
        """

        payload = {"question": question, **result.model_dump(mode="json")}
        try:
            updated = self.thread_store.append(
                thread.thread_id,
                principal_subject,
                requested_scope,
                payload,
                expected_revision=thread.revision,
            )
        except ThreadRevisionConflict as conflict:
            updated = self.thread_store.append(
                thread.thread_id,
                principal_subject,
                requested_scope,
                payload,
                expected_revision=conflict.current_revision,
            )
            return result.model_copy(
                update={
                    "thread_revision": updated.revision,
                    "uncertainty": [
                        *result.uncertainty,
                        "A concurrent turn superseded this thread revision.",
                    ],
                }
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
            max_wall_seconds=max_wall_seconds,
        )

    try:
        result = _execute(request)
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
    "execute_from_question",
    "executive_synthesis_decision",
    "legacy_session_history",
]
