"""Canonical governed orchestration service for the Inventory tracer."""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from api.errors import ApiError
from api.scope import Scope
from operations.cve_response import (
    canonical_cve_id,
    deterministic_cve_narrative,
)
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
    ThreadStoreUnavailable,
    investigation_thread_store,
    scope_within,
)
from operations.maf_orchestrator import (
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
    OrchestrationResult,
    SnapshotCoverage,
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


def deterministic_network_claims(
    *,
    snapshot: EvidenceSnapshotV2 | None,
    tool_results: Sequence[Mapping[str, Any]],
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
    if network_claim is None:
        return []

    claims = [network_claim]
    covered_refs = set(network_claim["evidence_refs"])
    for finding in normalize_cited_findings(tool_results):
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
        claims.append(
            {
                "finding_id": f"direct:{finding['finding_id']}",
                "summary": (
                    f"The {specialist} specialist returned cited "
                    f"{finding.get('status') or 'unknown'!s} evidence for "
                    f"this investigation."
                ),
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
        max_wall_seconds: float | None = None,
        selection_snapshot: EvidenceSnapshotV2 | None = None,
        canonical_selection_snapshot: CanonicalEvidenceSnapshot | None = None,
    ) -> OrchestrationTurn:
        """Execute one canonical request after all authorization gates pass."""

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
        tool_results: list[dict[str, Any]] = []
        tool_statuses: list[str] = []
        citations = self._snapshot_citations(request)
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
            narrator_state=narrator_state,
        )
        if synthesis.warning:
            uncertainty = [*uncertainty, synthesis.warning]
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
            coverage=request.snapshot.coverage,
            citations=self._deduplicate_citations(citations),
            thread_id=thread.thread_id,
            thread_revision=thread.revision + 1,
            synthesis={
                "status": synthesis.status,
                "reason": synthesis.reason,
                "domain_count": synthesis.domain_count,
                "claims": synthesis.claims,
                "warning": synthesis.warning,
            },
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
        narrator_state: str = "configured",
    ) -> ExecutiveSynthesis:
        """Run at most one citation-closed aggregation call, or none at all."""

        findings = normalize_cited_findings(tool_results)
        decision = executive_synthesis_decision(question, findings)
        cve_claims = self._deterministic_cve_claims(
            question,
            snapshot=snapshot,
            tool_results=tool_results,
        )
        network_claims = deterministic_network_claims(
            snapshot=snapshot,
            tool_results=tool_results,
        )
        deterministic_claims = cve_claims or network_claims or self._deterministic_page_claims(
            question,
            snapshot=snapshot,
            retained_evidence=current_retained_evidence,
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
                        if network_claims
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
                "CVE" if cve_claims else "network" if network_claims else "page"
            )
            warning = {
                "timeout": (
                    f"Foundry narration timed out; deterministic cited "
                    f"{evidence_kind} evidence was used."
                ),
                "unavailable": (
                    f"Foundry narration provider is unavailable; deterministic "
                    f"cited {evidence_kind} evidence was used."
                ),
            }.get(
                narrator_state,
                f"Foundry narration is not configured; deterministic cited "
                f"{evidence_kind} evidence was used.",
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
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        if self.executive_agent is None:
            warning = {
                "timeout": (
                    "Foundry narration timed out; direct specialist findings and "
                    "retained current page evidence are shown instead."
                ),
                "unavailable": (
                    "Foundry narration provider is unavailable; direct specialist "
                    "findings and retained current page evidence are shown instead."
                ),
            }.get(
                narrator_state,
                "Foundry narration is not configured; direct specialist findings "
                "and retained current page evidence are shown instead.",
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
            )
            self._record_synthesis_metric(synthesis)
            return synthesis
        try:
            answer_kwargs = {
                "question": question,
                "context": synthesis_input,
            }
            if remaining_seconds is not None:
                answer_kwargs["timeout_seconds"] = remaining_seconds
            answer = self.executive_agent.answer(**answer_kwargs)
            claims = validate_executive_synthesis(
                getattr(answer, "text", ""),
                evidence_refs=evidence_refs,
            )
        except FoundryAgentError as exc:
            # A rejected or unreachable narrator must not remove the evidence
            # the specialists already produced, so the turn degrades to their
            # direct findings and says so rather than failing.
            synthesis = ExecutiveSynthesis(
                status="degraded",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=deterministic_claims,
                warning=(
                    "Foundry narration timed out; deterministic cited evidence is "
                    "shown instead."
                    if _caused_by_timeout(exc)
                    else "Foundry narration provider is unavailable; deterministic "
                    "cited evidence is shown instead."
                ),
                used_retained_evidence=[
                    dict(item) for item in current_retained_evidence
                ],
            )
        except TimeoutError:
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
            )
        except (AttributeError, ConnectionError, TypeError, ValueError):
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
            )
        else:
            used_refs = {
                str(ref)
                for claim in claims
                for ref in claim.get("evidence_refs") or []
            }
            synthesis = ExecutiveSynthesis(
                status="synthesized",
                reason=decision.reason,
                domain_count=decision.domain_count,
                claims=claims,
                used_retained_evidence=[
                    dict(item)
                    for item in synthesis_input["retained_evidence"]
                    if item.get("evidence_id") in used_refs
                ],
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
    def _deterministic_page_claims(
        question: str,
        *,
        snapshot: EvidenceSnapshotV2 | None,
        retained_evidence: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build direct factual claims only from citation-closed current rows."""

        if snapshot is None or not retained_evidence:
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
        if material_refs and not material_refs <= set(by_original_id):
            return []
        candidates = [
            item
            for item in retained_evidence
            if (
                not material_refs
                or str(item.get("original_evidence_id") or "") in material_refs
            )
            and (item.get("selected") or item.get("direct"))
        ]
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
    "snapshot_claim_freshness",
]
