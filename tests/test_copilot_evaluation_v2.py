"""Conditional executive synthesis and privacy-safe orchestration telemetry.

Executive synthesis used to run on every turn, which spent a model call to
restate a single specialist's answer and gave an untrusted narrator a second
chance to introduce claims nothing had observed. Telemetry, meanwhile, is the
one place operational metadata is allowed to leave the boundary, so it must
carry counts and controlled enums and never the question, the arguments, the
principal, a resource id, or anything resembling hidden reasoning.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import api.telemetry as telemetry_module
from api.scope import Scope
from api.telemetry import ApiTelemetry, OrchestrationTelemetry
from operations.foundry_agent import (
    EXECUTIVE_SPECIALIST_ID,
    FoundryAgentError,
    executive_synthesis_input,
    normalize_cited_findings,
    validate_executive_synthesis,
)
from operations.investigation_thread_store import (
    InvestigationThread,
    InvestigationThreadStore,
    InvestigationThreadTurn,
    ThreadRevisionConflict,
)
from operations.orchestration_contract import (
    CandidatePlan,
    EvidenceSnapshotV2,
    InvestigationRequest,
    OrchestrationResult,
    SnapshotCoverage,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_service import (
    OrchestrationService,
    executive_synthesis_decision,
)
from operations.tools import STATUS_OK, Evidence, ToolResult

SENSITIVE_MARKERS = (
    "Which subscriptions",
    "operator-a",
    "/subscriptions/",
    "resource_group",
    "chain of thought",
    "because I reasoned",
    "sk-secret",
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class RecordingInstrument:
    def __init__(self, name: str, sink: list[tuple[str, float, dict[str, Any]]]) -> None:
        self.name = name
        self._sink = sink

    def add(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        self._sink.append((self.name, value, dict(attributes or {})))

    def record(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        self._sink.append((self.name, value, dict(attributes or {})))


class RecordingMeter:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, float, dict[str, Any]]] = []

    def _instrument(self, name: str, *args: Any, **kwargs: Any) -> RecordingInstrument:
        return RecordingInstrument(name, self.emitted)

    create_counter = _instrument
    create_histogram = _instrument
    create_up_down_counter = _instrument
    create_observable_gauge = _instrument


class RecordingExecutive:
    """Executive agent double that records how often it is invoked."""

    def __init__(self, text: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.text = text

    def answer(self, *, question: str, context: Any, **_: Any) -> Any:
        self.calls.append({"question": question, "context": context})
        text = self.text or json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "exec:1",
                        "summary": "Two domains agree the workload is exposed.",
                        "evidence_refs": [
                            context["findings"][0]["evidence_refs"][0]
                        ],
                        "confidence": "high",
                        "freshness": "fresh",
                        "uncertainty": [],
                        "actionable": True,
                        "next_check": "Confirm the firewall rule owner.",
                    }
                ]
            }
        )

        class _Answer:
            pass

        _Answer.text = text
        _Answer.agent_name = EXECUTIVE_SPECIALIST_ID
        _Answer.model = "test-model"
        _Answer.grounded = True
        _Answer.agent_version = "1"

        return _Answer()


def _tool_results() -> list[dict[str, Any]]:
    return [
        {
            "call_id": "0:0:network:network_paths",
            "specialist_id": "network",
            "tool": "network_paths",
            "arguments": {"resource_id": "/subscriptions/sub-a/rg/vm-1"},
            "status": STATUS_OK,
            "data": {"raw": "sk-secret dump", "rows": [1, 2, 3]},
            "warning": "",
            "evidence": [
                {
                    "evidence_id": "tool:0:0:network:network_paths:0",
                    "source": "network",
                    "resource_id": "/subscriptions/sub-a/rg/vm-1",
                }
            ],
        },
        {
            "call_id": "1:0:vulnerability:vulnerability_findings",
            "specialist_id": "vulnerability",
            "tool": "vulnerability_findings",
            "arguments": {"cve": "CVE-2026-1"},
            "status": STATUS_OK,
            "data": {"rationale": "because I reasoned about it"},
            "warning": "",
            "evidence": [
                {
                    "evidence_id": "tool:1:0:vulnerability:vulnerability_findings:0",
                    "source": "vulnerability",
                    "resource_id": "/subscriptions/sub-a/rg/vm-1",
                }
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Normalized synthesis input
# ---------------------------------------------------------------------------


def test_normalized_findings_carry_citations_and_drop_raw_payloads() -> None:
    findings = normalize_cited_findings(_tool_results())

    assert [item["specialist_id"] for item in findings] == ["network", "vulnerability"]
    assert findings[0]["evidence_refs"] == ["tool:0:0:network:network_paths:0"]
    serialized = json.dumps(findings)
    assert "sk-secret" not in serialized
    assert "because I reasoned" not in serialized
    assert "arguments" not in serialized
    for item in findings:
        assert set(item) == {
            "finding_id",
            "specialist_id",
            "status",
            "summary",
            "evidence_refs",
            "observation_status",
        }


def test_findings_without_citations_are_not_material() -> None:
    uncited = [
        {
            "call_id": "0:0:network:network_paths",
            "specialist_id": "network",
            "tool": "network_paths",
            "status": STATUS_OK,
            "evidence": [],
        }
    ]

    assert normalize_cited_findings(uncited) == []


def test_synthesis_input_is_only_findings_and_retained_evidence() -> None:
    payload = executive_synthesis_input(
        normalize_cited_findings(_tool_results()),
        retained_evidence=[
            {
                "evidence_id": "thread:prior:0",
                "source": "network",
                "status": "ok",
                "observation_status": "historical",
                "data": {"raw": "sk-secret"},
            }
        ],
    )

    assert set(payload) == {"findings", "retained_evidence"}
    serialized = json.dumps(payload)
    assert "sk-secret" not in serialized
    assert "prompt" not in serialized
    assert "rationale" not in serialized
    assert payload["retained_evidence"][0]["observation_status"] == "historical"


def test_retained_evidence_is_filtered_by_current_scope() -> None:
    thread = InvestigationThread(
        thread_id="thr-" + "a" * 32,
        principal_subject="operator-a",
        scope=Scope({"subscription": ["sub-a"]}),
        scope_fingerprint="fingerprint",
        turns=[
            InvestigationThreadTurn(
                scope=Scope({"subscription": ["sub-a", "sub-b"]}),
                payload={
                    "citations": [
                        {"citation_id": "wide", "source": "inventory", "status": "ok"}
                    ]
                },
            ),
            InvestigationThreadTurn(
                scope=Scope({"subscription": ["sub-a"]}),
                payload={
                    "citations": [
                        {"citation_id": "narrow", "source": "inventory", "status": "ok"}
                    ]
                },
            ),
        ],
    )

    retained = OrchestrationService._retained_evidence(
        thread,
        Scope({"subscription": ["sub-a"]}),
    )

    assert [item["original_evidence_id"] for item in retained] == ["narrow"]
    assert retained[0]["evidence_id"].startswith(f"retained:{thread.thread_id}:")


def test_repeated_retained_snapshot_ids_are_qualified_per_turn() -> None:
    thread = InvestigationThread(
        thread_id="thr-" + "a" * 32,
        principal_subject="operator-a",
        scope=Scope({"subscription": ["sub-a"]}),
        scope_fingerprint="fingerprint",
        turns=[
            InvestigationThreadTurn(
                scope=Scope({"subscription": ["sub-a"]}),
                recorded_at=1.0,
                payload={
                    "citations": [
                        {
                            "citation_id": "snapshot:coverage",
                            "source": source,
                            "status": status,
                        }
                    ],
                },
            )
            for source, status in (
                ("page_snapshot:inventory:coverage", "partial"),
                ("page_snapshot:vulnerability:coverage", "ok"),
            )
        ],
    )

    retained = OrchestrationService._retained_evidence(
        thread,
        Scope({"subscription": ["sub-a"]}),
    )

    assert len({item["evidence_id"] for item in retained}) == 2
    assert {
        item["original_evidence_id"] for item in retained
    } == {"snapshot:coverage"}
    assert {item["source"] for item in retained} == {
        "page_snapshot:inventory:coverage",
        "page_snapshot:vulnerability:coverage",
    }


def test_executive_claim_can_cite_authorized_retained_evidence() -> None:
    executive = RecordingExecutive(
        text=json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "exec:retained",
                        "summary": "Prior scoped evidence remains relevant.",
                        "evidence_refs": ["thread:prior:0"],
                        "confidence": "medium",
                        "freshness": "stale",
                        "uncertainty": [],
                        "actionable": False,
                        "next_check": "Recheck the prior observation.",
                    }
                ]
            }
        )
    )
    service = _service(executive_agent=executive)

    synthesis = service._synthesize(
        "Give me an executive summary.",
        _tool_results(),
        retained_evidence=[
            {
                "evidence_id": "thread:prior:0",
                "source": "network",
                "status": "ok",
                "observation_status": "historical",
            }
        ],
    )

    assert synthesis.status == "synthesized"
    assert synthesis.claims[0]["evidence_refs"] == ["thread:prior:0"]


def test_executive_rejects_retained_citation_not_transmitted_to_provider() -> None:
    retained = [
        {
            "evidence_id": f"thread:prior:{index}",
            "source": "network",
            "status": "ok",
            "observation_status": "historical",
        }
        for index in range(51)
    ]
    executive = RecordingExecutive(
        text=json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "exec:truncated",
                        "summary": "Cites evidence outside the provider payload.",
                        "evidence_refs": ["thread:prior:50"],
                        "confidence": "medium",
                        "freshness": "stale",
                        "uncertainty": [],
                        "actionable": False,
                        "next_check": "Recheck the prior observation.",
                    }
                ]
            }
        )
    )
    service = _service(executive_agent=executive)

    synthesis = service._synthesize(
        "Give me an executive summary.",
        _tool_results(),
        retained_evidence=retained,
    )

    assert len(executive.calls[0]["context"]["retained_evidence"]) == 50
    assert synthesis.status == "degraded"
    assert synthesis.claims == []


def test_synthesis_is_skipped_when_specialists_exhaust_wall_clock_budget() -> None:
    class Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    executive = RecordingExecutive()

    def executor(name, arguments, *, context, scope):
        clock.now = 5.0
        return _executor(name, arguments, context=context, scope=scope)

    service = OrchestrationService(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executor=executor,
        thread_store=InvestigationThreadStore(),
        clock=clock,
        executive_agent=executive,
    )

    turn = service.execute_turn(
        _request("Give me an executive summary."),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert executive.calls == []
    assert turn.synthesis.status == "degraded"
    assert "wall-clock budget" in turn.synthesis.warning


def test_synthesis_provider_timeout_is_bounded_to_remaining_budget() -> None:
    class TimedExecutive(RecordingExecutive):
        def answer(self, *, question: str, context: Any, **kwargs: Any) -> Any:
            self.calls.append(
                {"question": question, "context": context, "kwargs": kwargs}
            )
            return super().answer(question=question, context=context)

    executive = TimedExecutive()
    service = _service(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executive_agent=executive,
    )

    service.execute_turn(
        _request("Give me an executive summary."),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        max_wall_seconds=0.5,
    )

    assert 0 < executive.calls[0]["kwargs"]["timeout_seconds"] <= 0.5


# ---------------------------------------------------------------------------
# Citation closure
# ---------------------------------------------------------------------------


def test_executive_claims_must_cite_specialist_evidence() -> None:
    text = json.dumps(
        {
            "findings": [
                {
                    "finding_id": "exec:1",
                    "summary": "Reachable and vulnerable.",
                    "evidence_refs": ["tool:0:0:network:network_paths:0"],
                    "confidence": "high",
                    "freshness": "fresh",
                    "uncertainty": [],
                    "actionable": True,
                    "next_check": "Confirm the firewall rule owner.",
                }
            ]
        }
    )

    claims = validate_executive_synthesis(
        text,
        evidence_refs={"tool:0:0:network:network_paths:0"},
    )

    assert [claim["finding_id"] for claim in claims] == ["exec:1"]


def test_uncited_executive_claim_is_rejected() -> None:
    text = json.dumps(
        {
            "findings": [
                {
                    "finding_id": "exec:1",
                    "summary": "Invented a third domain.",
                    "evidence_refs": ["tool:9:9:invented:invented:0"],
                    "confidence": "high",
                    "freshness": "fresh",
                    "uncertainty": [],
                    "actionable": True,
                    "next_check": "None.",
                }
            ]
        }
    )

    with pytest.raises(FoundryAgentError):
        validate_executive_synthesis(
            text,
            evidence_refs={"tool:0:0:network:network_paths:0"},
        )


# ---------------------------------------------------------------------------
# Admission predicate
# ---------------------------------------------------------------------------


def test_single_domain_turn_is_not_admitted() -> None:
    findings = normalize_cited_findings(_tool_results()[:1])
    decision = executive_synthesis_decision("Which paths reach the VM?", findings)

    assert decision.admitted is False
    assert decision.reason == "single_domain"
    assert decision.domain_count == 1


def test_two_cited_domains_are_admitted() -> None:
    decision = executive_synthesis_decision(
        "Which paths reach the VM?",
        normalize_cited_findings(_tool_results()),
    )

    assert decision.admitted is True
    assert decision.reason == "multi_domain"
    assert decision.domain_count == 2


def test_explicit_executive_intent_is_admitted_on_one_domain() -> None:
    decision = executive_synthesis_decision(
        "Give me an executive summary for leadership.",
        normalize_cited_findings(_tool_results()[:1]),
    )

    assert decision.admitted is True
    assert decision.reason == "explicit_intent"


def test_multi_domain_without_cited_findings_is_not_admitted() -> None:
    decision = executive_synthesis_decision("Executive summary please", [])

    assert decision.admitted is False
    assert decision.reason == "no_cited_findings"


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------


def _request(question: str) -> InvestigationRequest:
    return InvestigationRequest(
        question=question,
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="vulnerability",
            page_id="vulnerability",
            coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=True),
        ),
    )


def _plan(*specialists: str) -> CandidatePlan:
    tools = {
        "vulnerability": "cve_exposure",
        "patch": "remediation_plans",
    }
    return CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id=specialist,
                tool_calls=[
                    ToolCallCandidate(
                        tool=tools[specialist],
                        arguments={},
                        citation_ids=["snapshot:coverage"],
                    )
                ],
            )
            for specialist in specialists
        ],
        estimated_tokens=0,
        max_wall_seconds=5,
        mutation_intent=False,
    )


def _executor(name, arguments, *, context, scope):
    return ToolResult(
        status=STATUS_OK,
        data={"rows": 1},
        evidence=(
            Evidence(
                source_engine=name.split("_")[0],
                resource_id="/subscriptions/sub-a/rg/vm-1",
                timestamp="2026-09-01T00:00:00Z",
            ),
        ),
    )


def _service(**kwargs: Any) -> OrchestrationService:
    return OrchestrationService(
        executor=_executor,
        thread_store=InvestigationThreadStore(),
        **kwargs,
    )


def test_single_domain_turn_makes_zero_executive_calls() -> None:
    executive = RecordingExecutive()
    service = _service(planner=lambda _r: _plan("vulnerability"), executive_agent=executive)

    turn = service.execute_turn(
        _request("Which paths reach the VM?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert executive.calls == []
    assert turn.synthesis.status == "skipped"
    assert turn.synthesis.reason == "single_domain"
    assert turn.result.status == STATUS_OK


def test_qualifying_turn_makes_exactly_one_executive_call() -> None:
    executive = RecordingExecutive()
    service = _service(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executive_agent=executive,
    )

    turn = service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert len(executive.calls) == 1
    assert turn.synthesis.status == "synthesized"
    assert turn.synthesis.claims
    context = json.dumps(executive.calls[0]["context"])
    assert set(json.loads(context)) == {"findings", "retained_evidence"}
    assert "arguments" not in context


def test_invalid_executive_citations_degrade_to_specialist_findings() -> None:
    executive = RecordingExecutive(
        text=json.dumps(
            {
                "findings": [
                    {
                        "finding_id": "exec:1",
                        "summary": "Invented a claim.",
                        "evidence_refs": ["tool:9:9:invented:invented:0"],
                        "confidence": "high",
                        "freshness": "fresh",
                        "uncertainty": [],
                        "actionable": True,
                        "next_check": "None.",
                    }
                ]
            }
        )
    )
    service = _service(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executive_agent=executive,
    )

    turn = service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert len(executive.calls) == 1
    assert turn.synthesis.status == "degraded"
    assert turn.synthesis.claims == []
    assert turn.synthesis.warning
    assert turn.synthesis.warning in turn.result.uncertainty
    assert len(turn.result.tool_results) == 2


def test_unavailable_executive_degrades_without_failing_the_turn() -> None:
    class BrokenExecutive:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        def answer(self, **_: Any) -> Any:
            raise FoundryAgentError("executive unavailable")

    service = _service(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executive_agent=BrokenExecutive(),
    )

    turn = service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert turn.synthesis.status == "degraded"
    assert turn.result.status == STATUS_OK
    assert turn.synthesis.warning in turn.result.uncertainty


def test_runtime_context_supplies_executive_and_telemetry() -> None:
    meter = RecordingMeter()
    executive = RecordingExecutive()

    class RuntimeContext:
        telemetry = type(
            "Telemetry",
            (),
            {"orchestration": OrchestrationTelemetry(meter=meter)},
        )()

        @staticmethod
        def specialist_agent(specialist_id: str) -> RecordingExecutive:
            assert specialist_id == EXECUTIVE_SPECIALIST_ID
            return executive

    service = _service(planner=lambda _r: _plan("vulnerability", "patch"))
    turn = service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=RuntimeContext(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert len(executive.calls) == 1
    assert turn.synthesis.status == "synthesized"
    assert meter.emitted


def test_admitted_synthesis_without_runtime_agent_degrades() -> None:
    service = _service(planner=lambda _r: _plan("vulnerability", "patch"))

    turn = service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert turn.synthesis.status == "degraded"
    assert turn.synthesis.warning in turn.result.uncertainty


def test_execute_still_returns_the_canonical_result_only() -> None:
    service = _service(planner=lambda _r: _plan("vulnerability"))

    result = service.execute(
        _request("Which paths reach the VM?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.thread_id.startswith("thr-")
    assert result.thread_revision == 1
    assert result.synthesis
    assert result.synthesis["status"] == "skipped"


def test_cas_retry_persists_committed_revision_and_reconciliation_warning() -> None:
    class ConflictThenCommitStore:
        def __init__(self) -> None:
            self.calls = 0
            self.persisted: dict[str, Any] = {}

        def append(self, *_args: Any, **_kwargs: Any) -> InvestigationThread:
            self.calls += 1
            if self.calls == 1:
                raise ThreadRevisionConflict(current_revision=4)
            self.persisted = _args[3]
            return InvestigationThread(
                thread_id="thr-" + "a" * 32,
                principal_subject="operator-a",
                scope=Scope({"subscription": ["sub-a"]}),
                scope_fingerprint="fingerprint",
                revision=5,
            )

    store = ConflictThenCommitStore()
    service = OrchestrationService(thread_store=store)
    thread = InvestigationThread(
        thread_id="thr-" + "a" * 32,
        principal_subject="operator-a",
        scope=Scope({"subscription": ["sub-a"]}),
        scope_fingerprint="fingerprint",
        revision=0,
    )
    result = OrchestrationResult(
        status=STATUS_OK,
        policy_status="accepted",
        coverage=SnapshotCoverage(visible_count=0, total_count=0, complete=True),
        citations=[],
        thread_id=thread.thread_id,
        thread_revision=1,
    )

    reconciled = service._record_turn(
        thread,
        principal_subject="operator-a",
        requested_scope=thread.scope,
        question="What changed?",
        result=result,
    )

    assert reconciled.thread_revision == 5
    assert store.persisted["thread_revision"] == 5
    assert store.persisted["uncertainty"] == [
        "A concurrent turn superseded this thread revision."
    ]


def test_turn_ids_do_not_collide_and_used_retained_citations_are_returned() -> None:
    class RetainedExecutive:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def answer(self, *, question: str, context: Any, **_: Any) -> Any:
            self.calls.append({"question": question, "context": context})
            retained_id = next(
                item["evidence_id"]
                for item in context["retained_evidence"]
                if item["evidence_id"].startswith("retained:")
            )
            text = json.dumps(
                {
                    "findings": [
                        {
                            "finding_id": "exec:retained",
                            "summary": "Prior evidence remains relevant.",
                            "evidence_refs": [retained_id],
                            "confidence": "medium",
                            "freshness": "stale",
                            "uncertainty": [],
                            "actionable": False,
                            "next_check": "Recheck prior evidence.",
                        }
                    ]
                }
            )
            return type(
                "Answer",
                (),
                {
                    "text": text,
                    "agent_name": EXECUTIVE_SPECIALIST_ID,
                    "model": "test",
                    "grounded": True,
                    "agent_version": "1",
                },
            )()

    executive = RetainedExecutive()
    store = InvestigationThreadStore()
    service = OrchestrationService(
        planner=lambda _r: _plan("vulnerability"),
        executor=_executor,
        thread_store=store,
        executive_agent=executive,
    )
    first = service.execute(
        _request("Which vulnerabilities exist?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    second_request = _request("Give me an executive summary.").model_copy(
        update={"thread_id": first.thread_id}
    )
    second = service.execute(
        second_request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    first_tool_id = next(
        item.citation_id for item in first.citations if item.citation_id.startswith("tool:")
    )
    second_tool_id = next(
        item.citation_id for item in second.citations
        if item.citation_id.startswith("tool:") and item.citation_id != first_tool_id
    )
    retained_id = next(
        item.citation_id
        for item in second.citations
        if item.citation_id.startswith("retained:")
    )
    assert first.thread_id in first_tool_id
    assert first_tool_id != second_tool_id
    assert first_tool_id not in {item.citation_id for item in second.citations}
    assert first.thread_id in retained_id
    assert second.synthesis["claims"][0]["evidence_refs"] == [retained_id]


# ---------------------------------------------------------------------------
# Telemetry privacy
# ---------------------------------------------------------------------------


def _emitted_values(meter: RecordingMeter) -> str:
    return json.dumps(
        [
            {"name": name, "value": value, "attributes": attributes}
            for name, value, attributes in meter.emitted
        ]
    )


def test_orchestration_telemetry_is_attached_to_the_api_telemetry() -> None:
    telemetry = ApiTelemetry(meter=RecordingMeter())

    assert isinstance(telemetry.orchestration, OrchestrationTelemetry)


def test_delegation_and_stage_metrics_are_low_cardinality() -> None:
    meter = RecordingMeter()
    telemetry = OrchestrationTelemetry(meter=meter)

    telemetry.record_delegation(
        stage="specialist",
        specialist_id="network",
        tool="network_paths",
        status=STATUS_OK,
        policy_status="accepted",
        duration_ms=12.5,
    )
    telemetry.record_stage_latency(stage="synthesis", duration_ms=44.0)
    telemetry.record_budget(outcome="exhausted", duration_ms=5000.0)
    telemetry.record_evidence(status="ok", observation_status="historical", count=3)
    telemetry.record_synthesis(decision="multi_domain", status="synthesized", domain_count=2)
    telemetry.record_thread(outcome="continued", durability="durable")

    assert meter.emitted
    for _name, value, attributes in meter.emitted:
        assert isinstance(value, int | float)
        for key, attribute in attributes.items():
            assert isinstance(key, str)
            assert isinstance(attribute, str | int | bool)
            if isinstance(attribute, str):
                assert len(attribute) <= 64


def test_telemetry_rejects_uncontrolled_values() -> None:
    meter = RecordingMeter()
    telemetry = OrchestrationTelemetry(meter=meter)

    telemetry.record_delegation(
        stage="Which subscriptions are exposed?",
        specialist_id="operator-a",
        tool="/subscriptions/sub-a/resource_group/rg",
        status="sk-secret",
        policy_status="because I reasoned",
        duration_ms=1.0,
    )
    telemetry.record_fallback(reason="candidate_rejected:mutation_forbidden")
    telemetry.record_fallback(reason="/subscriptions/sub-a/rg")
    telemetry.record_evidence(
        status="chain of thought",
        observation_status="sk-secret",
        count=1,
    )
    telemetry.record_thread(outcome="operator-a", durability="/subscriptions/sub-a")
    telemetry.record_synthesis(
        decision="because I reasoned",
        status="chain of thought",
        domain_count=1,
    )

    serialized = _emitted_values(meter)
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
    assert "other" in serialized
    assert "mutation_forbidden" in serialized


def test_telemetry_manifest_failure_degrades_to_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meter = RecordingMeter()
    telemetry_module._manifest_vocabulary.cache_clear()
    monkeypatch.setattr(
        telemetry_module,
        "load_specialist_manifest",
        lambda: (_ for _ in ()).throw(ValueError("invalid manifest")),
    )
    try:
        telemetry = OrchestrationTelemetry(meter=meter)
        telemetry.record_delegation(
            stage="specialist",
            specialist_id="network",
            tool="network_paths",
            status=STATUS_OK,
            policy_status="accepted",
            duration_ms=1,
        )
    finally:
        telemetry_module._manifest_vocabulary.cache_clear()

    attributes = meter.emitted[0][2]
    assert attributes["specialist_id"] == "other"
    assert attributes["tool"] == "other"


def test_service_emits_only_controlled_orchestration_attributes() -> None:
    meter = RecordingMeter()
    telemetry = OrchestrationTelemetry(meter=meter)
    service = _service(
        planner=lambda _r: _plan("vulnerability", "patch"),
        executive_agent=RecordingExecutive(),
        telemetry=telemetry,
    )

    service.execute_turn(
        _request("Which subscriptions are exposed and vulnerable?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    serialized = _emitted_values(meter)
    assert meter.emitted
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
    assert "thr-" not in serialized
    assert "cve_exposure" in serialized
    assert any(name.endswith("stage.duration") for name, _v, _a in meter.emitted)
