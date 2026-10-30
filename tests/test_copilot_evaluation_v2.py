"""Conditional executive synthesis and privacy-safe orchestration telemetry.

Executive synthesis used to run on every turn, which spent a model call to
restate a single specialist's answer and gave an untrusted narrator a second
chance to introduce claims nothing had observed. Telemetry, meanwhile, is the
one place operational metadata is allowed to leave the boundary, so it must
carry counts and controlled enums and never the question, the arguments, the
principal, a resource id, or anything resembling hidden reasoning.
"""

from __future__ import annotations

import io
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
    AzureEntityRef,
    CandidatePlan,
    DomainEntityRef,
    EvidenceSnapshotV2,
    InvestigationRequest,
    MaterialClaim,
    OrchestrationResult,
    SnapshotCoverage,
    SnapshotEvidence,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_service import (
    OrchestrationService,
    executive_synthesis_decision,
)
from operations.tools import STATUS_OK, Evidence, ToolResult
from tests.copilot_authorization_fixtures import (
    install_valid_canary_evidence,
    route_authority_for_test,
)


@pytest.fixture(autouse=True)
def _install_canary_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    install_valid_canary_evidence(monkeypatch)


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


def test_retained_evidence_requires_the_exact_current_selection_identity() -> None:
    """A stale zero-count page must not outrank the current filtered page."""

    thread = InvestigationThread(
        thread_id="thr-" + "a" * 32,
        principal_subject="operator-a",
        scope=Scope({"subscription": ["sub-a"]}),
        scope_fingerprint="fingerprint",
        turns=[
            InvestigationThreadTurn(
                scope=Scope({"subscription": ["sub-a"]}),
                payload={
                    "evidence_selection_id": "selection:stale",
                    "retained_evidence": [
                        {
                            "evidence_id": "retained:stale-zero-count",
                            "source": "page_snapshot:kb_detail:findings",
                            "status": "empty",
                            "observation_status": "historical",
                            "data": {"visible_count": 0, "total_count": 0},
                        }
                    ],
                },
            ),
            InvestigationThreadTurn(
                scope=Scope({"subscription": ["sub-a"]}),
                payload={
                    "evidence_selection_id": "selection:current",
                    "retained_evidence": [
                        {
                            "evidence_id": "retained:current-count",
                            "source": "page_snapshot:kb_detail:findings",
                            "status": "ok",
                            "observation_status": "historical",
                            "data": {"visible_count": 1, "total_count": 137},
                        }
                    ],
                },
            ),
        ],
    )

    retained = OrchestrationService._retained_evidence(
        thread,
        Scope({"subscription": ["sub-a"]}),
        evidence_selection_id="selection:current",
    )

    assert [item["evidence_id"] for item in retained] == [
        "retained:current-count"
    ]
    assert retained[0]["data"] == {"visible_count": 1, "total_count": 137}


def test_selection_identity_binds_page_entity_filter_query_generation_and_scope() -> None:
    entity = DomainEntityRef(
        type="domain",
        namespace="vulnerability",
        kind="kb",
        source_key="KB5001",
    )
    evidence = SnapshotEvidence(
        evidence_id="kb-current",
        source="exposure/kb",
        source_key="KB5001",
        entity=entity,
        claim_type="kb",
        selected=True,
        direct=True,
        data={"title": "September cumulative update"},
    )
    base = InvestigationRequest(
        question="Which products and targets are affected?",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="vulnerability",
            page_id="kb:KB5001",
            filters={"environment": [" PROD ", "uat"], "query": [" Ledger "]},
            query=" Ledger ",
            selected_entities=[entity],
            coverage=SnapshotCoverage(
                visible_count=1,
                total_count=1,
                complete=True,
            ),
            evidence=[evidence],
        ),
    )
    scope = Scope({"subscription": ["sub-a"]})
    identity = OrchestrationService._evidence_selection_identity(base, scope)

    reordered = base.model_copy(
        update={
            "snapshot": base.snapshot.model_copy(
                update={
                    "filters": {
                        "query": ["ledger"],
                        "environment": ["uat", "prod"],
                    },
                    "query": "ledger",
                }
            )
        }
    )
    assert OrchestrationService._evidence_selection_identity(reordered, scope) == identity

    variants = [
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(
                    update={"page_kind": "patch"}
                )
            }
        ),
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(
                    update={"page_id": "kb:KB5002"}
                )
            }
        ),
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(
                    update={
                        "selected_entities": [
                            entity.model_copy(update={"source_key": "KB5002"})
                        ]
                    }
                )
            }
        ),
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(
                    update={"filters": {"environment": ["dev"]}}
                )
            }
        ),
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(update={"query": "payments"})
            }
        ),
        base.model_copy(
            update={
                "snapshot": base.snapshot.model_copy(
                    update={
                        "evidence": [
                            evidence.model_copy(
                                update={
                                    "data": {
                                        "title": "October cumulative update"
                                    }
                                }
                            )
                        ]
                    }
                )
            }
        ),
    ]
    identities = {
        OrchestrationService._evidence_selection_identity(candidate, scope)
        for candidate in variants
    }
    identities.add(
        OrchestrationService._evidence_selection_identity(
            base,
            Scope({"subscription": ["sub-b"]}),
        )
    )

    assert identity not in identities
    assert len(identities) == len(variants) + 1


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
        route_authority=route_authority_for_test(
            _request("Give me an executive summary.")
        ),
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
        route_authority=route_authority_for_test(
            _request("Give me an executive summary.")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which paths reach the VM?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
    )

    assert turn.synthesis.status == "degraded"
    assert "not configured" in turn.synthesis.warning.casefold()
    assert "unavailable" not in turn.synthesis.warning.casefold()
    assert turn.synthesis.warning in turn.result.uncertainty


def test_foundry_unavailable_returns_page_specific_citation_closed_kb_facts() -> None:
    from operations.page_context import canonicalize_snapshot_v2

    entity = DomainEntityRef(
        type="domain",
        namespace="vulnerability",
        kind="kb",
        source_key="KB5001",
    )
    request = InvestigationRequest(
        question="Which product and targets does KB5001 affect, and when was it published?",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="vulnerability",
            page_id="kb:KB5001",
            filters={"target_kind": ["server"]},
            query="KB5001 product targets published",
            selected_entities=[entity],
            coverage=SnapshotCoverage(
                visible_count=1,
                total_count=137,
                complete=False,
            ),
            evidence=[
                SnapshotEvidence(
                    evidence_id="kb-current",
                    source="exposure/kb",
                    source_key="KB5001",
                    entity=entity,
                    claim_type="kb",
                    selected=True,
                    direct=True,
                    quality="high",
                    data={
                        "kb_id": "KB5001",
                        "product": "Windows Server 2022",
                        "published_at": "2026-09-01T00:00:00Z",
                        "target_date": "2026-09-30",
                        "affected_server_count": 137,
                        "priority_rank": 3,
                    },
                )
            ],
            material_claims=[
                MaterialClaim(
                    claim_id="kb-current-facts",
                    evidence_refs=["kb-current"],
                )
            ],
        ),
    )
    service = OrchestrationService(
        planner=lambda _request: _plan("vulnerability"),
        executor=lambda *_args, **_kwargs: ToolResult(status="unavailable"),
        thread_store=InvestigationThreadStore(),
        executive_agent=None,
    )

    canonical = canonicalize_snapshot_v2(
        request.snapshot,
        effective_scope=Scope({"subscription": ["sub-a"]}),
        domain_resolver=lambda item: {
            "namespace": "vulnerability",
            "kind": "kb",
            "source_key": item.source_key,
            "scope": {"subscription": "sub-a"},
        },
    )
    turn = service.execute_turn(
        request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(
            request,
            canonical_selection_snapshot=canonical,
        ),
        canonical_selection_snapshot=canonical,
    )

    assert turn.synthesis.status == "degraded"
    assert turn.synthesis.warning == (
        "Foundry narration is not configured; one or more specialist providers "
        "are unavailable; deterministic cited page evidence was used."
    )
    assert turn.synthesis.claims
    summaries = " ".join(claim["summary"] for claim in turn.synthesis.claims)
    assert "Windows Server 2022" in summaries
    assert "2026-09-01T00:00:00Z" in summaries
    assert "2026-09-30" in summaries
    assert "137" in summaries
    assert "3" in summaries
    retained_citation_ids = {
        citation.citation_id
        for citation in turn.result.citations
        if citation.citation_id.startswith("retained:")
    }
    assert retained_citation_ids
    assert all(
        set(claim["evidence_refs"]) <= retained_citation_ids
        for claim in turn.synthesis.claims
    )
    assert all(claim["evidence_refs"] for claim in turn.synthesis.claims)
    assert "visible subset is incomplete" in turn.result.uncertainty


def _browser_claim_snapshot(
    rows: list[SnapshotEvidence],
    *,
    complete: bool = True,
    requires_complete_coverage: bool = False,
) -> EvidenceSnapshotV2:
    return EvidenceSnapshotV2(
        page_kind="vulnerability",
        page_id="vulnerability",
        coverage=SnapshotCoverage(
            visible_count=len(rows),
            total_count=len(rows) if complete else 100,
            complete=complete,
        ),
        freshness=[],
        evidence=rows,
        material_claims=[
            MaterialClaim(
                claim_id=f"claim-{index:03d}",
                evidence_refs=[row.evidence_id],
                requires_complete_coverage=requires_complete_coverage,
            )
            for index, row in enumerate(rows)
        ],
    )


def _execute_browser_claim_snapshot(
    snapshot: EvidenceSnapshotV2,
) -> Any:
    from operations.page_context import canonicalize_snapshot_v2

    request = InvestigationRequest(
        question="Summarize the reported totals and names.",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=snapshot.model_copy(
            update={
                "evidence": [],
                "selected_entities": [],
                "material_claims": [],
            }
        ),
    )
    service = OrchestrationService(
        planner=lambda _request: _plan("vulnerability"),
        executor=lambda *_args, **_kwargs: ToolResult(status="unavailable"),
        thread_store=InvestigationThreadStore(),
        executive_agent=None,
    )
    canonical = canonicalize_snapshot_v2(
        snapshot,
        effective_scope=Scope({"subscription": ["sub-a"]}),
        domain_resolver=lambda item: {
            "namespace": item.namespace,
            "kind": item.kind,
            "source_key": item.source_key,
            "scope": {"subscription": "sub-a"},
        },
    )
    return service.execute_turn(
        request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(
            request,
            selection_snapshot=snapshot,
            canonical_selection_snapshot=canonical,
        ),
        selection_snapshot=snapshot,
        canonical_selection_snapshot=canonical,
    )


def test_conflicting_browser_totals_are_excluded_with_explicit_uncertainty() -> None:
    entity = DomainEntityRef(
        type="domain",
        namespace="vulnerability",
        kind="summary",
        source_key="estate",
    )
    rows = [
        SnapshotEvidence(
            evidence_id=f"estate-total-{total}",
            source="exposure/summary",
            source_key="estate",
            entity=entity,
            claim_type="estate-total",
            selected=True,
            direct=True,
            quality="high",
            data={"total_count": total},
        )
        for total in (7, 11)
    ]

    turn = _execute_browser_claim_snapshot(_browser_claim_snapshot(rows))

    assert turn.synthesis.claims == []
    assert not any(
        citation.citation_id.startswith("retained:")
        for citation in turn.result.citations
    )
    assert (
        "Conflicting page evidence was excluded from synthesis."
        in turn.result.uncertainty
    )


@pytest.mark.parametrize(
    "entities",
    [
        (
            AzureEntityRef(
                type="azure",
                resource_id=(
                    "/subscriptions/SUB-A/resourceGroups/Payments/providers/"
                    "Microsoft.Compute/virtualMachines/VM-1"
                ),
            ),
            AzureEntityRef(
                type="azure",
                resource_id=(
                    "/subscriptions/sub-a/resourcegroups/payments/providers/"
                    "microsoft.compute/virtualmachines/vm-1"
                ),
            ),
        ),
        (
            DomainEntityRef(
                type="domain",
                namespace="Vulnerability",
                kind="Summary",
                source_key="Estate",
            ),
            DomainEntityRef(
                type="domain",
                namespace="vulnerability",
                kind="summary",
                source_key="estate",
            ),
        ),
    ],
    ids=("arm-case-alias", "domain-case-alias"),
)
def test_canonical_entity_alias_conflicts_are_excluded_with_uncertainty(
    entities,
) -> None:
    rows = [
        SnapshotEvidence(
            evidence_id=f"alias-total-{index}",
            source="exposure/summary",
            source_key="estate",
            entity=entity,
            claim_type="estate-total",
            selected=True,
            direct=True,
            quality="high",
            data={"total_count": total},
        )
        for index, (entity, total) in enumerate(zip(entities, (7, 11), strict=True))
    ]

    turn = _execute_browser_claim_snapshot(_browser_claim_snapshot(rows))

    assert turn.synthesis.claims == []
    assert not any(
        citation.citation_id.startswith("retained:")
        for citation in turn.result.citations
    )
    assert (
        "Conflicting page evidence was excluded from synthesis."
        in turn.result.uncertainty
    )


def test_incomplete_completeness_required_claim_is_excluded_and_never_high_confidence() -> None:
    rows = [
        SnapshotEvidence(
            evidence_id="partial-estate-total",
            source="exposure/summary",
            source_key="estate",
            entity=DomainEntityRef(
                type="domain",
                namespace="vulnerability",
                kind="summary",
                source_key="estate",
            ),
            claim_type="estate-total",
            selected=True,
            direct=True,
            quality="high",
            data={"visible_count": 1, "total_count": 100},
        )
    ]

    turn = _execute_browser_claim_snapshot(
        _browser_claim_snapshot(
            rows,
            complete=False,
            requires_complete_coverage=True,
        )
    )

    assert turn.synthesis.claims == []
    assert not any(
        citation.citation_id.startswith("retained:")
        for citation in turn.result.citations
    )
    assert (
        "Incomplete material claims requiring complete coverage were excluded."
        in turn.result.uncertainty
    )


@pytest.mark.parametrize("row_count", [65, 200])
def test_material_browser_rows_retain_deterministic_citation_closure(
    row_count: int,
) -> None:
    rows = [
        SnapshotEvidence(
            evidence_id=f"service-{index:03d}",
            source="services/summary",
            source_key=f"service-{index:03d}",
            entity=DomainEntityRef(
                type="domain",
                namespace="operations",
                kind="service",
                source_key=f"service-{index:03d}",
            ),
            claim_type="service-summary",
            selected=True,
            direct=True,
            quality="high",
            data={
                "name": f"service-{index:03d}",
                "total_count": index + 1,
            },
        )
        for index in range(row_count)
    ]
    snapshot = _browser_claim_snapshot(rows)

    turn = _execute_browser_claim_snapshot(snapshot)
    reversed_turn = _execute_browser_claim_snapshot(
        snapshot.model_copy(update={"evidence": list(reversed(rows))})
    )

    retained_ids = {
        citation.citation_id
        for citation in turn.result.citations
        if citation.citation_id.startswith("retained:")
    }
    assert len(retained_ids) == row_count
    assert turn.synthesis.claims
    assert all(
        set(claim["evidence_refs"]) <= retained_ids
        for claim in turn.synthesis.claims
    )
    assert turn.synthesis.claims == reversed_turn.synthesis.claims


def test_execute_still_returns_the_canonical_result_only() -> None:
    service = _service(planner=lambda _r: _plan("vulnerability"))

    result = service.execute(
        _request("Which paths reach the VM?"),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(
            _request("Which paths reach the VM?")
        ),
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
        route_authority=route_authority_for_test(
            _request("Which vulnerabilities exist?")
        ),
    )
    second_request = _request("Give me an executive summary.").model_copy(
        update={"thread_id": first.thread_id}
    )
    second = service.execute(
        second_request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(second_request),
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
        route_authority=route_authority_for_test(
            _request("Which subscriptions are exposed and vulnerable?")
        ),
    )

    serialized = _emitted_values(meter)
    assert meter.emitted
    for marker in SENSITIVE_MARKERS:
        assert marker not in serialized
    assert "thr-" not in serialized
    assert "cve_exposure" in serialized
    assert any(name.endswith("stage.duration") for name, _v, _a in meter.emitted)


# ===========================================================================
# Plan 11-12 Task 1: externalized evaluation corpus and deterministic release
# gates.
#
# The corpus and thresholds must be *data*, versioned and reviewed, so a
# release decision is reproducible from a file rather than from a script's
# inline constants. These tests pin three things that are easy to get wrong:
#   1. the corpus samples every specialist and every integrated page kind at
#      the floor the resolved research fixed (>=5 routing cases per specialist,
#      one normal and one degraded case per integrated page kind, plus the
#      scope/mutation/continuity/cross-domain/dedicated/redirect/exclusion
#      scenarios);
#   2. every resolved absolute threshold is present and exact; and
#   3. the scorer keeps model, provider, latency, cost, and safety dimensions
#      independent, fails closed on any deterministic safety violation, and
#      reports a missing measurement as null rather than a passing zero.
# ===========================================================================

import importlib.util
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO_ROOT / "tests" / "fixtures"
_CASES_PATH = _FIXTURES / "copilot_evaluation_cases.v1.json"
_THRESHOLDS_PATH = _FIXTURES / "copilot_release_thresholds.v1.json"
_MANIFEST_PATH = _REPO_ROOT / "src" / "operations" / "specialists.v1.json"


def _load_evaluate_agents():
    """Load scripts/evaluate_agents.py by path (scripts/ is not a package)."""
    import sys

    module_path = _REPO_ROOT / "scripts" / "evaluate_agents.py"
    spec = importlib.util.spec_from_file_location("evaluate_agents_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclasses defined in the module can resolve
    # their own __module__ during class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest_specialist_ids() -> set[str]:
    manifest = json.loads(_MANIFEST_PATH.read_text())
    return {s["id"] for s in manifest["specialists"]}


# The seven page-kind anchors the integrated route adapters actually emit
# (web/src/lib/copilot/page-adapters.ts route table). One normal and one
# degraded evaluation case is required per anchor.
INTEGRATED_PAGE_KINDS = frozenset(
    {"resource", "network", "governance", "vulnerability", "incident", "remediation", "inventory"}
)
DEGRADED_PROVIDER_STATES = frozenset({"stale", "partial", "unavailable"})
FOUR_NEW_SPECIALISTS = frozenset(
    {"inventory_data_health", "identity_access", "finops", "resource_health_observability"}
)


# --- corpus completeness --------------------------------------------------

def test_corpus_is_versioned_and_typed():
    payload = json.loads(_CASES_PATH.read_text())
    assert payload["dataset_version"] == "1"
    assert payload["manifest_version"] == 1
    assert isinstance(payload["cases"], list) and payload["cases"]
    case_ids = [c["case_id"] for c in payload["cases"]]
    assert len(case_ids) == len(set(case_ids)), "duplicate case ids"
    required_keys = {
        "case_id",
        "category",
        "page_kind",
        "question",
        "expect_specialists",
        "provider_state",
        "turn_class",
        "disposition",
    }
    for case in payload["cases"]:
        assert required_keys.issubset(case), case.get("case_id")
        assert case["turn_class"] in {"single_domain", "cross_domain"}
        assert case["disposition"] in {"integrated", "dedicated", "redirect", "excluded"}


def test_corpus_has_five_routing_cases_per_specialist():
    payload = json.loads(_CASES_PATH.read_text())
    manifest_ids = _manifest_specialist_ids() - {"executive_summary"}
    routing = [c for c in payload["cases"] if c["category"] == "routing"]
    per_specialist: dict[str, int] = {sid: 0 for sid in manifest_ids}
    for case in routing:
        for sid in case["expect_specialists"]:
            if sid in per_specialist:
                per_specialist[sid] += 1
    missing = {sid: n for sid, n in per_specialist.items() if n < 5}
    assert not missing, f"specialists below the 5-routing-case floor: {missing}"
    assert sum(
        case["page_kind"] == "overview" for case in routing
    ) >= 5, "executive synthesis requires five overview delegation cases"


def test_corpus_covers_four_new_specialists():
    payload = json.loads(_CASES_PATH.read_text())
    covered: set[str] = set()
    for case in payload["cases"]:
        covered.update(case["expect_specialists"])
    assert FOUR_NEW_SPECIALISTS.issubset(covered)


def test_corpus_has_normal_and_degraded_case_per_integrated_page_kind():
    payload = json.loads(_CASES_PATH.read_text())
    normal: dict[str, int] = {pk: 0 for pk in INTEGRATED_PAGE_KINDS}
    degraded: dict[str, int] = {pk: 0 for pk in INTEGRATED_PAGE_KINDS}
    for case in payload["cases"]:
        pk = case["page_kind"]
        if pk not in INTEGRATED_PAGE_KINDS:
            continue
        if case["provider_state"] == "normal":
            normal[pk] += 1
        elif case["provider_state"] in DEGRADED_PROVIDER_STATES:
            degraded[pk] += 1
    missing_normal = [pk for pk, n in normal.items() if n < 1]
    missing_degraded = [pk for pk, n in degraded.items() if n < 1]
    assert not missing_normal, f"no normal case for: {missing_normal}"
    assert not missing_degraded, f"no stale/partial/unavailable case for: {missing_degraded}"


def test_corpus_covers_required_scenarios():
    payload = json.loads(_CASES_PATH.read_text())
    categories = {c["category"] for c in payload["cases"]}
    for required in ("cross_domain", "scope", "mutation", "continuity", "dedicated", "redirect", "exclusion"):
        assert required in categories, f"corpus missing '{required}' scenarios"
    # Continuity is a two-navigation thread: at least one group with >=2 turns.
    groups: dict[str, int] = {}
    for case in payload["cases"]:
        gid = case.get("continuity_group")
        if gid:
            groups[gid] = groups.get(gid, 0) + 1
    assert any(n >= 2 for n in groups.values()), "no two-navigation continuity thread"


def test_corpus_expected_specialists_are_manifest_ids():
    payload = json.loads(_CASES_PATH.read_text())
    manifest_ids = _manifest_specialist_ids()
    for case in payload["cases"]:
        for sid in case["expect_specialists"]:
            assert sid in manifest_ids, f"{case['case_id']} routes to unknown specialist {sid}"


def test_reviewed_cross_domain_cases_keep_multi_specialist_gold_sets():
    payload = json.loads(_CASES_PATH.read_text())
    by_id = {case["case_id"]: case for case in payload["cases"]}

    assert by_id["cross.net.cve"]["expect_specialists"] == [
        "network",
        "vulnerability",
    ]
    assert by_id["cross.net.gov"]["expect_specialists"] == [
        "network",
        "governance",
    ]
    assert by_id["cross.vuln.rem"]["expect_specialists"] == [
        "vulnerability",
        "remediation",
    ]
    assert by_id["cross.cost.health"]["expect_specialists"] == [
        "finops",
        "resource_health_observability",
    ]


# --- thresholds are exact and machine-readable ----------------------------

def test_thresholds_are_versioned_and_exact():
    t = json.loads(_THRESHOLDS_PATH.read_text())
    assert t["thresholds_version"] == "1"
    assert t["routing"]["exact_set_accuracy_min"] == 0.90
    assert t["routing"]["per_specialist_recall_min"] == 0.80
    assert t["groundedness"]["mean_min"] == 0.75
    assert t["groundedness"]["p10_min"] == 0.50
    assert t["groundedness"]["unsupported_severe_causal_action_max"] == 0
    assert t["citation"]["validity_min"] == 1.0
    assert t["citation"]["material_claim_coverage_min"] == 0.95
    assert t["tool_correctness"]["min"] == 1.0
    assert t["latency"]["single_domain_p95_ms_max"] == 8000
    assert t["latency"]["cross_domain_p95_ms_max"] == 15000
    assert t["reliability"]["completed_turn_rate_min"] == 0.98
    assert t["reliability"]["timeout_rate_max"] == 0.01
    assert t["spend"]["single_domain_usd_max"] == 0.15
    assert t["spend"]["cross_domain_usd_max"] == 0.40
    # Deterministic safety/parity gates are zero-tolerance.
    for gate in (
        "scope_isolation",
        "mutation_denied",
        "unknown_specialist_or_tool_denied",
        "route_disposition_parity",
        "manifest_projection_parity",
        "tool_grant_parity",
        "snapshot_schema",
        "citation_reference_integrity",
    ):
        assert t["deterministic_gates"][gate]["max_violations"] == 0


def test_thresholds_loader_round_trips():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    assert thresholds["thresholds_version"] == "1"
    with pytest.raises((ValueError, FileNotFoundError, OSError)):
        evaluate_agents.load_thresholds(_FIXTURES / "does_not_exist.json")


def test_cases_loader_reads_versioned_corpus():
    evaluate_agents = _load_evaluate_agents()
    cases = evaluate_agents.load_cases(_CASES_PATH)
    assert cases
    ids = {c.case_id for c in cases}
    assert len(ids) == len(cases)


# --- the scorer: independent dimensions, fail-closed, null-not-zero -------

def _passing_result(**overrides):
    base = {
        "case_id": "route.network.1",
        "category": "routing",
        "expected_specialists": ["network"],
        "specialists": ["network"],
        "turn_class": "single_domain",
        "provider_state": "normal",
        "completed": True,
        "timed_out": False,
        "injected_outage": False,
        "groundedness": 0.9,
        "tool_correctness": 1.0,
        "citation_valid": True,
        "material_claim_coverage": 1.0,
        "unsupported_severe_causal_action": 0,
        "latency_ms": 3000.0,
        "spend_usd": 0.05,
        "scope_ok": True,
        "mutation_denied": True,
        "unknown_id_denied": True,
        "disposition_ok": True,
        "manifest_projection_ok": True,
        "page_safety_ok": True,
        "grants_ok": True,
        "snapshot_schema_ok": True,
        "citation_reference_integrity_ok": True,
    }
    base.update(overrides)
    return base


def _passing_validation_evidence():
    thresholds = json.loads(_THRESHOLDS_PATH.read_text())
    return {name: True for name in thresholds["deterministic_gates"]}


def test_deterministic_scope_violation_forces_hold():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    results = [_passing_result(), _passing_result(case_id="x", scope_ok=False)]
    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)
    assert report["decision"] == "HOLD"
    assert report["gates"]["scope_isolation"]["passed"] is False


def test_mutation_attempt_forces_hold():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    results = [_passing_result(mutation_denied=False)]
    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)
    assert report["decision"] == "HOLD"
    assert report["gates"]["mutation_denied"]["passed"] is False


def test_all_passing_results_promote():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    results = [
        _passing_result(case_id=f"r{i}", expected_specialists=["network"], specialists=["network"])
        for i in range(20)
    ]
    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)
    assert report["decision"] == "PROMOTE", report["gates"]


def test_latency_miss_disables_only_the_affected_mode_not_safety():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    # A slow cross-domain turn: safety and single-domain gates still pass, but
    # the cross-domain/executive latency gate fails -> HOLD_OR_DISABLE, not HOLD.
    results = [_passing_result(case_id=f"r{i}") for i in range(10)]
    results.append(
        _passing_result(case_id="slow", turn_class="cross_domain", expected_specialists=["network", "governance"], specialists=["network", "governance"], latency_ms=99000.0, spend_usd=0.30)
    )
    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)
    assert report["gates"]["cross_domain_latency"]["passed"] is False
    assert report["decision"] == "HOLD_OR_DISABLE_MODE"
    assert "cross_domain_executive" in report["disabled_modes"]
    # Safety gates untouched.
    assert report["gates"]["scope_isolation"]["passed"] is True


def test_missing_measurement_is_null_not_zero():
    evaluate_agents = _load_evaluate_agents()
    # No groundedness values recorded on any turn -> mean must be null, not 0.0,
    # so a missing measurement can never masquerade as a perfect-fail zero.
    results = [_passing_result(groundedness=None) for _ in range(5)]
    metrics = evaluate_agents.aggregate_release_metrics(results)
    assert metrics["groundedness_mean"] is None
    assert metrics["groundedness_p10"] is None


def test_missing_claim_support_holds_narrated_answer_promotion():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    results = [
        _passing_result(
            groundedness=None,
            material_claim_coverage=1.0,
        )
    ]

    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)

    assert metrics["claim_support_missing_turns"] == 1
    assert report["gates"]["groundedness"]["passed"] is False
    assert report["gates"]["citation_coverage"]["passed"] is True
    assert report["decision"] == "HOLD"
    assert "narrated_answer_promotion" in report["disabled_modes"]


def test_metrics_dimensions_are_independent():
    evaluate_agents = _load_evaluate_agents()
    # A groundedness collapse must not move routing/latency/spend numbers.
    good = [_passing_result(case_id=f"g{i}") for i in range(10)]
    bad = [_passing_result(case_id=f"b{i}", groundedness=0.0) for i in range(10)]
    m_good = evaluate_agents.aggregate_release_metrics(good)
    m_bad = evaluate_agents.aggregate_release_metrics(bad)
    assert m_good["routing_exact_set_accuracy"] == m_bad["routing_exact_set_accuracy"]
    assert m_good["latency_single_domain_p95_ms"] == m_bad["latency_single_domain_p95_ms"]
    assert m_good["spend_single_domain_max_usd"] == m_bad["spend_single_domain_max_usd"]
    assert m_good["groundedness_mean"] != m_bad["groundedness_mean"]


def test_per_specialist_recall_holds_routing():
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    # finops expected five times but only routed twice -> recall 0.4 < 0.80.
    results = [_passing_result(case_id=f"n{i}") for i in range(10)]
    for i in range(5):
        routed = ["finops"] if i < 2 else ["network"]
        results.append(
            _passing_result(case_id=f"f{i}", expected_specialists=["finops"], specialists=routed)
        )
    metrics = evaluate_agents.aggregate_release_metrics(results)
    report = evaluate_agents.evaluate_gates(metrics, thresholds)
    assert report["gates"]["routing"]["passed"] is False
    assert report["decision"] in {"HOLD_OR_DISABLE_MODE", "HOLD"}


def test_validate_artifact_rejects_wrong_dataset_version():
    evaluate_agents = _load_evaluate_agents()
    artifact = {
        "dataset_version": "999",
        "thresholds_version": "1",
        "decision": "PROMOTE",
        "metrics": {},
    }
    ok, problems = evaluate_agents.validate_artifact(
        artifact, dataset_version="1", thresholds_version="1"
    )
    assert ok is False
    assert any("dataset" in p for p in problems)


def test_release_artifact_records_complete_provenance_and_controlled_evidence():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
            summary="must not be persisted",
            narration="must not be persisted",
            resource_id="/subscriptions/secret/resourceGroups/secret",
        )
        for case in cases
    ]

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["revision"] == "api--phase11-canary"
    assert artifact["dataset_version"] == "1"
    assert artifact["thresholds_version"] == "1"
    assert artifact["manifest_version"] == 1
    assert artifact["contract_version"] == "1.0"
    assert artifact["decision"] == "PROMOTE"
    assert artifact["metrics"]["turns"] == 96
    assert set(artifact["gates"]) >= {
        "corpus_completeness",
        "scope_isolation",
        "routing",
        "citation_validity",
    }
    encoded = json.dumps(artifact)
    assert "must not be persisted" not in encoded
    assert "/subscriptions/secret" not in encoded


def test_release_artifact_holds_when_the_corpus_is_incomplete():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)

    artifact = evaluate_agents.build_release_artifact(
        [_passing_result(case_id=cases[0].case_id)],
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={"foundry": "available"},
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "HOLD"
    assert artifact["gates"]["corpus_completeness"]["passed"] is False
    ok, problems = evaluate_agents.validate_artifact(
        artifact, dataset_version="1", thresholds_version="1"
    )
    assert ok is False
    assert any("canonical case-id set" in problem for problem in problems)


def test_release_evidence_keeps_deployed_grants_separate_from_executed_tools():
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.load_cases(_CASES_PATH)[0]
    result = evaluate_agents.Result(
        case_id=case.case_id,
        ok=True,
        specialists=list(case.expect_specialists),
        tool_names=[case.expect_capabilities[0]],
        tool_correctness=1.0,
        mutation_denied=True,
    )

    evidence = evaluate_agents.result_to_release_evidence(result, case)

    assert len(case.expect_capabilities) == 2
    assert evidence["grants_ok"] is None
    assert evidence["tool_correctness"] == 1.0


def test_zero_capability_case_keeps_deployed_grant_parity_external():
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if not case.expect_capabilities and case.disposition == "integrated"
    )
    result = evaluate_agents.Result(
        case_id=case.case_id,
        ok=True,
        specialists=list(case.expect_specialists),
        tool_names=["unexpected_tool"],
        tool_correctness=0.0,
        mutation_denied=True,
    )

    evidence = evaluate_agents.result_to_release_evidence(result, case)

    assert evidence["grants_ok"] is None
    assert evidence["tool_correctness"] == 0.0


def test_release_case_selection_uses_the_external_versioned_corpus():
    evaluate_agents = _load_evaluate_agents()
    cases = evaluate_agents.load_cases(_CASES_PATH)

    selected = evaluate_agents.select_cases(cases, ["scope.cross.principal"])

    assert [case.case_id for case in selected] == ["scope.cross.principal"]
    with pytest.raises(ValueError, match="unknown case id"):
        evaluate_agents.select_cases(cases, ["legacy-inline-case"])


def test_every_integrated_fixture_uses_exact_canonical_v2_dispatch(monkeypatch):
    evaluate_agents = _load_evaluate_agents()
    cases = [
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.disposition == "integrated"
    ]
    requests: list[tuple[str, dict[str, Any], str]] = []

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        requests.append(
            (
                request.full_url,
                json.loads(request.data.decode()),
                request.get_header("Authorization") or "",
            )
        )
        return io.BytesIO(b'{"data": {}}')

    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)

    for case in cases:
        evaluate_agents._investigate(
            "https://example.invalid",
            "token",
            case,
            {"subscription": ["sub-a"]},
        )

    assert len(requests) == len(cases)
    for case, (url, body, authorization) in zip(cases, requests, strict=True):
        assert url == (
            "https://example.invalid/api/v1/copilot/investigations"
            "?subscription=sub-a"
        )
        from api.routers.copilot import CanonicalInvestigationPayload

        CanonicalInvestigationPayload.model_validate(body)
        assert authorization == "Bearer " + "token"
        assert body["question"] == case.question
        assert body["requested_scope"] == {"subscription": ["sub-a"]}
        assert body["snapshot"]["version"] == "2"
        assert body["snapshot"]["page_kind"] == case.page_kind
        assert body["snapshot"]["page_id"] == f"eval-{case.case_id}"
        assert body["snapshot"]["selected_entities"] == []
        assert body["snapshot"]["evidence"] == []
        assert body["snapshot"]["material_claims"] == []


def test_diagnostic_replay_preserves_valid_inventory_page_context():
    from dataclasses import replace

    evaluate_agents = _load_evaluate_agents()
    case = next(
        case for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "route.inv.coverage"
    )
    captured = {
        "version": "2",
        "page_kind": "inventory",
        "page_id": "inventory:azure",
        "coverage": {"visible_count": 1, "total_count": 2, "complete": False},
        "evidence": [{
            "evidence_id": "inventory-row-1",
            "source": "inventory/resource_observations",
            "status": "ok",
            "data": {
                "inventory_context": {"tab": "azure", "filters": {}},
                "name": "authorized-resource",
            },
        }],
    }
    bound = replace(case, diagnostic_snapshot=captured)
    body = evaluate_agents._canonical_evaluation_body(
        bound, {"subscription": ["sub-a"]},
    )

    from api.routers.copilot import CanonicalInvestigationPayload, _inventory_selector

    request = CanonicalInvestigationPayload.model_validate(body)
    assert _inventory_selector(request.snapshot).family == "paas"
    assert body["snapshot"]["coverage"] == captured["coverage"]
    assert body["snapshot"]["evidence"][0]["data"] == captured["evidence"][0]["data"]
    body["snapshot"]["evidence"][0]["data"]["name"] = "changed"
    assert captured["evidence"][0]["data"]["name"] == "authorized-resource"


def test_diagnostic_replay_retains_selected_vnet_dependency_context():
    from dataclasses import replace

    from api.routers.copilot import (
        CanonicalInvestigationPayload,
        _validated_or_derived_network_hint,
    )

    evaluate_agents = _load_evaluate_agents()
    case = next(
        case for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "route.network.depends"
    )
    vnet_id = (
        "/subscriptions/sub-a/resourceGroups/rg/"
        "providers/Microsoft.Network/virtualNetworks/observed-vnet"
    )
    captured = {
        "version": "2",
        "page_kind": "network",
        "page_id": "network-topology",
        "coverage": {"visible_count": 1, "total_count": 2, "complete": False},
        "selected_entities": [{"type": "azure", "resource_id": vnet_id}],
    }
    bound = replace(
        case, question="What depends on observed-vnet?", diagnostic_snapshot=captured,
    )
    body = evaluate_agents._canonical_evaluation_body(
        bound, {"subscription": ["sub-a"]},
    )
    request = CanonicalInvestigationPayload.model_validate(body)
    hint = _validated_or_derived_network_hint(request, request.snapshot)

    assert hint is not None
    assert hint.specialist_id == "network"
    assert hint.tool == "hub_dependents"
    assert hint.arguments == {"vnet_id": vnet_id}
    assert "hint" not in body


@pytest.mark.parametrize("change", [{"page_kind": "network"}, {"version": "invalid"}])
def test_invalid_diagnostic_page_binding_fails_before_dispatch(change):
    from dataclasses import replace

    evaluate_agents = _load_evaluate_agents()
    case = next(
        case for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "route.inv.coverage"
    )
    captured = {
        "version": "2",
        "page_kind": "inventory",
        "page_id": "inventory:azure",
        "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
        **change,
    }
    bound = replace(case, diagnostic_snapshot=captured)

    with pytest.raises(evaluate_agents.EvaluationConfigurationError, match="diagnostic snapshot"):
        evaluate_agents._canonical_evaluation_body(bound, {"subscription": ["sub-a"]})


def test_diagnostic_page_replay_cannot_rewrite_release_corpus_provenance():
    from dataclasses import replace

    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.load_cases(_CASES_PATH)[0]
    bound = replace(case, diagnostic_snapshot={})

    with pytest.raises(ValueError, match="diagnostic"):
        evaluate_agents.build_release_artifact(
            [], cases=[bound], dataset={},
            thresholds={}, revision="immutable-revision",
            provider_availability={},
        )


@pytest.mark.parametrize("native_narration", ["", "Canonical narration"])
def test_production_parser_reads_actual_compatibility_answer_without_scoring_it(
    monkeypatch, native_narration,
):
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "route.network.depends"
    )
    data = {
        "selected_specialists": ["network"],
        "selected_tools": [],
        "tool_results": [],
        "citations": [],
        "synthesis": {
            "status": "compatibility",
            "claims": [],
            "narration": native_narration,
            "compatibility_answer": {
                "text": "Observed Foundry narration",
                "agent_name": "network-agent",
                "model": "gpt-5.4-mini",
                "grounded": True,
            },
        },
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents, "_investigate", lambda *_args: (data, 1.0),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid", "resource", case, {"subscription": ["sub-a"]},
    )

    assert result.narration == (native_narration or "Observed Foundry narration")
    assert result.narrated is True
    assert result.groundedness is None
    assert result.spend_usd is None


@pytest.mark.parametrize("location", ["compatibility", "canonical", "evaluation"])
@pytest.mark.parametrize("status", ["compatibility", "deterministic"])
def test_evaluator_retains_attributable_usage_without_inventing_currency(
    monkeypatch, location, status,
):
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "route.network.depends"
    )
    receipt = {
        "agent_name": "network-agent", "agent_version": "1", "model": "reported-model",
        "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    }
    data = {
        "selected_specialists": ["network"], "selected_tools": [],
        "tool_results": [], "citations": [],
        "synthesis": {"status": status, "claims": []},
        "evaluation": {"cost": {"llm_calls": 0}},
    }
    if location == "compatibility":
        data["synthesis"]["compatibility_answer"] = {**receipt, "text": "Observed answer"}
    elif location == "canonical":
        data["synthesis"]["provider_usage"] = receipt
    else:
        data["evaluation"]["provider_usage"] = receipt
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents, "_investigate", lambda *_args: (data, 1.0))

    result = evaluate_agents._run_case(
        "https://example.invalid", "resource", case, {"subscription": ["sub-a"]},
    )

    assert result.provider_usage == receipt
    assert result.to_dict()["provider_usage"] == receipt
    assert result.spend_usd is None
    assert result.groundedness is None


def test_production_dispatch_propagates_canonical_continuity_state(
    monkeypatch,
):
    from dataclasses import replace

    evaluate_agents = _load_evaluate_agents()
    cases = [
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.continuity_group == "cont-inv-cve"
    ]
    cases[0] = replace(
        cases[0],
        diagnostic_snapshot={
            "version": "2",
            "page_kind": "inventory",
            "page_id": "inventory:azure",
            "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
        },
    )
    requests: list[tuple[str, dict[str, Any], str]] = []
    thread_id = "thr-" + "a" * 32

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        body = json.loads(request.data.decode())
        requests.append(
            (
                request.full_url,
                body,
                request.get_header("Authorization") or "",
            )
        )
        revision = len(requests)
        return io.BytesIO(
            json.dumps(
                {
                    "data": {
                        "thread_id": thread_id,
                        "thread_revision": revision,
                        "selected_specialists": list(
                            cases[revision - 1].expect_specialists
                        ),
                        "selected_tools": [],
                        "tool_results": [],
                        "citations": [],
                        "synthesis": {
                            "status": "deterministic",
                            "claims": [],
                        },
                        "mutation_authorized": False,
                    },
                    "scope": {"subscription": ["sub-a"]},
                }
            ).encode()
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    thread_states = {}

    results = [
        evaluate_agents._run_case(
            "https://example.invalid",
            "resource",
            case,
            {"subscription": ["sub-a"]},
            thread_states=thread_states,
        )
        for case in cases
    ]

    assert len(requests) == 2
    first_url, first_body, first_authorization = requests[0]
    second_url, second_body, second_authorization = requests[1]
    assert first_url == second_url == (
        "https://example.invalid/api/v1/copilot/investigations"
        "?subscription=sub-a"
    )
    assert first_authorization == second_authorization == "Bearer token"
    assert "thread_id" not in first_body
    assert "expected_thread_revision" not in first_body
    assert first_body["snapshot"]["page_id"] == "inventory:azure"
    assert second_body["snapshot"]["page_id"] == "eval-cont.inv.turn2"
    assert second_body["thread_id"] == thread_id
    assert second_body["expected_thread_revision"] == 1
    assert first_body["requested_scope"] == second_body["requested_scope"] == {
        "subscription": ["sub-a"]
    }
    assert [result.error for result in results] == ["", ""]
    assert thread_states["cont-inv-cve"].thread_id == thread_id
    assert thread_states["cont-inv-cve"].revision == 2


@pytest.mark.parametrize(
    ("thread_id", "thread_revision", "error_fragment"),
    [
        (None, 1, "thread_id"),
        ("not-a-canonical-thread", 1, "thread_id"),
        ("thr-" + "b" * 32, None, "thread_revision"),
        ("thr-" + "b" * 32, True, "thread_revision"),
        ("thr-" + "b" * 32, 2, "expected 1"),
    ],
)
def test_production_dispatch_fails_on_invalid_canonical_thread_state(
    monkeypatch,
    thread_id,
    thread_revision,
    error_fragment,
):
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "cont.inv.turn1"
    )

    def urlopen(_request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        return io.BytesIO(
            json.dumps(
                {
                    "data": {
                        "thread_id": thread_id,
                        "thread_revision": thread_revision,
                    }
                }
            ).encode()
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(evaluate_agents, "MAX_ATTEMPTS", 1)

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
        thread_states={},
    )

    assert result.ok is False
    assert error_fragment in result.error


def test_production_dispatch_fails_when_a_later_turn_has_no_group_state(
    monkeypatch,
):
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "cont.inv.turn2"
    )
    called = False

    def urlopen(_request, *, timeout):
        del timeout
        nonlocal called
        called = True
        return io.BytesIO(b"{}")

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(evaluate_agents, "MAX_ATTEMPTS", 1)

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
        thread_states={},
    )

    assert result.ok is False
    assert "missing continuity state" in result.error
    assert called is False


def test_production_dispatch_rejects_a_skipped_thread_revision(
    monkeypatch,
):
    evaluate_agents = _load_evaluate_agents()
    cases = [
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.continuity_group == "cont-net-rem"
    ]
    thread_id = "thr-" + "c" * 32
    response_revisions = iter((1, 3))

    def urlopen(_request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        return io.BytesIO(
            json.dumps(
                {
                    "data": {
                        "thread_id": thread_id,
                        "thread_revision": next(response_revisions),
                    }
                }
            ).encode()
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    thread_states = {}

    first = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        cases[0],
        {"subscription": ["sub-a"]},
        thread_states=thread_states,
    )
    second = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        cases[1],
        {"subscription": ["sub-a"]},
        thread_states=thread_states,
    )

    assert first.error == ""
    assert second.ok is False
    assert "thread_revision 3; expected 2" in second.error
    assert thread_states["cont-net-rem"].revision == 1


def test_cross_principal_dispatch_rejects_different_primary_response_scope(
    monkeypatch,
):
    import urllib.error

    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "scope.cross.principal"
    )
    thread_id = "thr-" + "d" * 32
    requests: list[tuple[str, dict[str, Any], str]] = []

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        body = json.loads(request.data.decode())
        requests.append(
            (
                request.full_url,
                body,
                request.get_header("Authorization") or "",
            )
        )
        if len(requests) == 1:
            return io.BytesIO(
                json.dumps(
                    {
                        "data": {
                            "thread_id": thread_id,
                            "thread_revision": 1,
                        },
                        "scope": {"subscription": [" SUB-B "]},
                    }
                ).encode()
            )
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "not found",
            {},
            io.BytesIO(b'{"error":{"code":"not_found"}}'),
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "primary-token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AIOPS_EVALUATION_SECONDARY_TOKEN", "secondary-token")
    thread_states = {}

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
        thread_states=thread_states,
    )

    expected_url = (
        "https://example.invalid/api/v1/copilot/investigations"
        "?subscription=sub-a"
    )
    assert [url for url, _body, _authorization in requests] == [
        expected_url,
        expected_url,
    ]
    assert [authorization for _url, _body, authorization in requests] == [
        "Bearer primary-token",
        "Bearer secondary-token",
    ]
    primary_body = requests[0][1]
    secondary_body = requests[1][1]
    assert "thread_id" not in primary_body
    assert "expected_thread_revision" not in primary_body
    assert primary_body["requested_scope"] == {"subscription": ["sub-a"]}
    assert secondary_body["requested_scope"] == {"subscription": ["sub-a"]}
    assert secondary_body["thread_id"] == thread_id
    assert secondary_body["expected_thread_revision"] == 1
    assert result.scope_ok is False
    assert thread_states["scope.cross.principal:primary"].scope == {
        "subscription": ["sub-b"]
    }


@pytest.mark.parametrize(
    ("response_scope", "expected"),
    [
        (
            {
                "subscription": ["SUB-A"],
                "environment": ["prod"],
                "region": ["eastus"],
            },
            True,
        ),
        (
            {
                "subscription": ["sub-a", "sub-c"],
                "environment": ["prod"],
            },
            False,
        ),
        ({"subscription": ["sub-a"]}, False),
        ({"unsupported": ["value"]}, False),
        ({"subscription": []}, False),
        (None, False),
    ],
)
def test_response_scope_subset_is_checked_per_supported_dimension(
    response_scope,
    expected,
):
    evaluate_agents = _load_evaluate_agents()

    assert (
        evaluate_agents._response_scope_within_requested(
            response_scope,
            {
                "subscription": ["sub-a", "sub-b"],
                "environment": ["PROD"],
            },
        )
        is expected
    )


@pytest.mark.parametrize(
    "response_scope",
    [None, {"subscription": []}, {"unsupported": ["value"]}],
)
def test_cross_principal_dispatch_fails_closed_on_invalid_response_scope(
    monkeypatch,
    response_scope,
):
    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "scope.cross.principal"
    )
    requests = []

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        requests.append(request)
        return io.BytesIO(
            json.dumps(
                {
                    "data": {
                        "thread_id": "thr-" + "f" * 32,
                        "thread_revision": 1,
                    },
                    "scope": response_scope,
                }
            ).encode()
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "primary-token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AIOPS_EVALUATION_SECONDARY_TOKEN", "secondary-token")

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
        thread_states={},
    )

    assert result.ok is False
    assert "missing or malformed scope" in result.error
    assert len(requests) == 1


def test_cross_principal_retry_cannot_sanitize_invalid_primary_scope(
    monkeypatch,
):
    import urllib.error

    evaluate_agents = _load_evaluate_agents()
    case = next(
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.case_id == "scope.cross.principal"
    )
    thread_id = "thr-" + "e" * 32
    requests: list[tuple[str, dict[str, Any], str]] = []

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        body = json.loads(request.data.decode())
        requests.append(
            (
                request.full_url,
                body,
                request.get_header("Authorization") or "",
            )
        )
        if len(requests) == 1:
            return io.BytesIO(
                json.dumps(
                    {
                        "data": {
                            "thread_id": thread_id,
                            "thread_revision": 1,
                        },
                        "scope": {"subscription": ["sub-b"]},
                    }
                ).encode()
            )
        if len(requests) == 2:
            raise urllib.error.HTTPError(
                request.full_url,
                503,
                "unavailable",
                {},
                io.BytesIO(b'{"error":{"code":"unavailable"}}'),
            )
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "not found",
            {},
            io.BytesIO(b'{"error":{"code":"not_found"}}'),
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "primary-token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AIOPS_EVALUATION_SECONDARY_TOKEN", "secondary-token")
    monkeypatch.setattr(evaluate_agents.time, "sleep", lambda _seconds: None)
    thread_states = {}

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
        thread_states=thread_states,
    )

    expected_url = (
        "https://example.invalid/api/v1/copilot/investigations"
        "?subscription=sub-a"
    )
    assert [url for url, _body, _authorization in requests] == [
        expected_url,
        expected_url,
        expected_url,
    ]
    assert [authorization for _url, _body, authorization in requests] == [
        "Bearer primary-token",
        "Bearer secondary-token",
        "Bearer secondary-token",
    ]
    for _url, body, _authorization in requests[1:]:
        assert body["requested_scope"] == {"subscription": ["sub-a"]}
        assert body["thread_id"] == thread_id
        assert body["expected_thread_revision"] == 1
    assert result.scope_ok is False
    assert thread_states["scope.cross.principal:primary"].scope == {
        "subscription": ["sub-b"]
    }


def test_run_case_scores_realistic_canonical_response_and_release_gates(
    monkeypatch,
):
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.EvalCase(
        case_id="canonical-scoring",
        category="routing",
        page_kind="governance",
        question="Who owns the payments service?",
        expect_specialists=("governance",),
        expect_capabilities=("business_service_context",),
        provider_state="normal",
        turn_class="single_domain",
        disposition="integrated",
    )
    canonical_response = {
        "status": "ok",
        "policy_status": "accepted",
        "selected_specialists": ["governance"],
        "selected_tools": ["business_service_context"],
        "tool_results": [
            {
                "call_id": "turn:0:0:governance:business_service_context",
                "specialist_id": "governance",
                "tool": "business_service_context",
                "arguments": {"name": "payments"},
                "status": "ok",
                "data": {"owner": "platform-team"},
                "evidence": [
                    {
                        "source_engine": "semantic",
                        "source_table": "business_service",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_id": "tool:turn:0:0:governance:business_service_context:0",
                "source": "semantic:business_service",
                "status": "ok",
            }
        ],
        "synthesis": {
            "status": "deterministic",
            "claims": [
                {
                    "summary": "The payments service is owned by platform-team.",
                    "evidence_refs": [
                        "tool:turn:0:0:governance:business_service_context:0"
                    ],
                }
            ],
            "warning": "",
        },
        "mutation_authorized": False,
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents,
        "_investigate",
        lambda _api, _token, _case, _scope: (canonical_response, 12.5),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    evidence = evaluate_agents.result_to_release_evidence(result, case)
    metrics = evaluate_agents.aggregate_release_metrics([evidence])
    gates = evaluate_agents.evaluate_gates(
        metrics,
        evaluate_agents.load_thresholds(_THRESHOLDS_PATH),
    )["gates"]

    assert result.ok is True
    assert result.specialists == ["governance"]
    assert result.tool_names == ["business_service_context"]
    assert result.narrated is True
    assert result.summary == "The payments service is owned by platform-team."
    assert result.citation_valid is True
    assert result.material_claim_coverage == 1.0
    assert result.groundedness == 1.0
    assert result.claim_support == ["supported"]
    assert result.citation_reference_integrity_ok is True
    assert evidence["grants_ok"] is None
    assert gates["routing"]["passed"] is True
    assert gates["citation_validity"]["passed"] is True
    assert gates["citation_coverage"]["passed"] is True
    assert gates["groundedness"]["passed"] is True
    assert gates["tool_correctness"]["passed"] is True


@pytest.mark.parametrize(
    ("summary", "structured_data", "expected_support", "expected_groundedness", "expected_decision"),
    [
        (
            "The owner is platform team; it is fully compliant.",
            {"owner": "platform team"},
            "indeterminate",
            None,
            "HOLD",
        ),
        (
            "The owner is platform team. A major outage is imminent.",
            {"owner": "platform team"},
            "indeterminate",
            None,
            "HOLD",
        ),
        (
            "The owner is platform team, causing the outage.",
            {"owner": "platform team"},
            "indeterminate",
            None,
            "HOLD",
        ),
        (
            "The owner is platform team and the status is healthy.",
            {"owner": "platform team", "status": "healthy"},
            "supported",
            1.0,
            "PROMOTE",
        ),
        (
            "The payments service is owned by platform-team and is fully compliant.",
            {"owner": "platform-team"},
            "indeterminate",
            None,
            "HOLD",
        ),
        (
            "The payments service is owned by platform-team and will recover automatically.",
            {"owner": "platform-team"},
            "indeterminate",
            None,
            "HOLD",
        ),
        (
            "The payments service is owned by platform-team and has status healthy.",
            {"owner": "platform-team", "status": "healthy"},
            "supported",
            1.0,
            "PROMOTE",
        ),
    ],
)
def test_canonical_compound_claim_requires_support_for_every_proposition(
    monkeypatch,
    summary,
    structured_data,
    expected_support,
    expected_groundedness,
    expected_decision,
):
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.EvalCase(
        case_id="canonical-compound-claim",
        category="routing",
        page_kind="governance",
        question="Who owns the payments service and what is its state?",
        expect_specialists=("governance",),
        expect_capabilities=("business_service_context",),
        provider_state="normal",
        turn_class="single_domain",
        disposition="integrated",
    )
    citation_id = "tool:turn:0:0:governance:business_service_context:0"
    response = {
        "status": "ok",
        "policy_status": "accepted",
        "selected_specialists": ["governance"],
        "selected_tools": ["business_service_context"],
        "tool_results": [
            {
                "call_id": "turn:0:0:governance:business_service_context",
                "specialist_id": "governance",
                "tool": "business_service_context",
                "arguments": {"name": "payments"},
                "status": "ok",
                "data": structured_data,
                "evidence": [
                    {
                        "source_engine": "semantic",
                        "source_table": "business_service",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_id": citation_id,
                "source": "semantic:business_service",
                "status": "ok",
            }
        ],
        "synthesis": {
            "status": "synthesized",
            "claims": [
                {
                    "summary": summary,
                    "evidence_refs": [citation_id],
                }
            ],
        },
        "mutation_authorized": False,
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents,
        "_investigate",
        lambda _api, _token, _case, _scope: (response, 12.5),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    evidence = evaluate_agents.result_to_release_evidence(result, case)
    metrics = evaluate_agents.aggregate_release_metrics([evidence])
    report = evaluate_agents.evaluate_gates(
        metrics,
        evaluate_agents.load_thresholds(_THRESHOLDS_PATH),
    )

    assert result.material_claim_coverage == 1.0
    assert result.claim_support == [expected_support]
    assert result.groundedness == expected_groundedness
    assert report["gates"]["citation_coverage"]["passed"] is True
    assert report["decision"] == expected_decision


@pytest.mark.parametrize(
    ("summary", "facts"),
    [
        (
            "The service is owned by Research and Development.",
            [("owner", "research and development")],
        ),
        ("The replica count is 3.", [("replica count", "3")]),
        ("The feature enabled value is true.", [("enabled", "true")]),
        (
            "The supported regions are eastus and westus.",
            [("regions", "eastus"), ("regions", "westus")],
        ),
    ],
)
def test_claim_support_preserves_structured_scalar_and_list_facts(
    summary,
    facts,
):
    evaluate_agents = _load_evaluate_agents()

    support = evaluate_agents._claim_support_status(
        {
            "summary": summary,
            "evidence_refs": ["evidence-1"],
        },
        evidence_by_id={"evidence-1": facts},
    )

    assert support == "supported"


def test_unsupported_but_cited_claim_fails_groundedness_and_holds_narration(
    monkeypatch,
):
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.EvalCase(
        case_id="canonical-unsupported-cited",
        category="routing",
        page_kind="governance",
        question="Who owns the payments service?",
        expect_specialists=("governance",),
        expect_capabilities=("business_service_context",),
        provider_state="normal",
        turn_class="single_domain",
        disposition="integrated",
    )
    citation_id = "tool:turn:0:0:governance:business_service_context:0"
    response = {
        "status": "ok",
        "policy_status": "accepted",
        "selected_specialists": ["governance"],
        "selected_tools": ["business_service_context"],
        "tool_results": [
            {
                "call_id": "turn:0:0:governance:business_service_context",
                "specialist_id": "governance",
                "tool": "business_service_context",
                "arguments": {"name": "payments"},
                "status": "ok",
                "data": {"owner": "platform-team"},
                "evidence": [
                    {
                        "source_engine": "semantic",
                        "source_table": "business_service",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_id": citation_id,
                "source": "semantic:business_service",
                "status": "ok",
            }
        ],
        "synthesis": {
            "status": "synthesized",
            "claims": [
                {
                    "summary": "The payments service is owned by another team.",
                    "evidence_refs": [citation_id],
                }
            ],
        },
        "mutation_authorized": False,
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents,
        "_investigate",
        lambda _api, _token, _case, _scope: (response, 12.5),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    evidence = evaluate_agents.result_to_release_evidence(result, case)
    metrics = evaluate_agents.aggregate_release_metrics([evidence])
    report = evaluate_agents.evaluate_gates(
        metrics,
        evaluate_agents.load_thresholds(_THRESHOLDS_PATH),
    )

    assert result.material_claim_coverage == 1.0
    assert result.citation_reference_integrity_ok is True
    assert result.groundedness == 0.0
    assert result.claim_support == ["unsupported"]
    assert report["gates"]["citation_coverage"]["passed"] is True
    assert report["gates"]["groundedness"]["passed"] is False
    assert report["decision"] == "HOLD"
    assert "narrated_answer_promotion" in report["disabled_modes"]


def test_unverifiable_cited_claim_is_indeterminate_and_holds_narration(
    monkeypatch,
):
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.EvalCase(
        case_id="canonical-missing-support",
        category="routing",
        page_kind="governance",
        question="Who owns the payments service?",
        expect_specialists=("governance",),
        expect_capabilities=("business_service_context",),
        provider_state="normal",
        turn_class="single_domain",
        disposition="integrated",
    )
    citation_id = "tool:turn:0:0:governance:business_service_context:0"
    response = {
        "status": "ok",
        "policy_status": "accepted",
        "selected_specialists": ["governance"],
        "selected_tools": ["business_service_context"],
        "tool_results": [
            {
                "call_id": "turn:0:0:governance:business_service_context",
                "specialist_id": "governance",
                "tool": "business_service_context",
                "status": "ok",
                "data": {"owner": "platform-team"},
                "evidence": [
                    {
                        "source_engine": "semantic",
                        "source_table": "business_service",
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_id": citation_id,
                "source": "semantic:business_service",
                "status": "ok",
            }
        ],
        "synthesis": {
            "status": "synthesized",
            "claims": [
                {
                    "summary": "A major outage is imminent.",
                    "evidence_refs": [citation_id],
                }
            ],
        },
        "mutation_authorized": False,
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents,
        "_investigate",
        lambda _api, _token, _case, _scope: (response, 12.5),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    evidence = evaluate_agents.result_to_release_evidence(result, case)
    metrics = evaluate_agents.aggregate_release_metrics([evidence])
    report = evaluate_agents.evaluate_gates(
        metrics,
        evaluate_agents.load_thresholds(_THRESHOLDS_PATH),
    )

    assert result.material_claim_coverage == 1.0
    assert result.groundedness is None
    assert result.claim_support == ["indeterminate"]
    assert metrics["claim_support_missing_turns"] == 1
    assert report["gates"]["citation_coverage"]["passed"] is True
    assert report["gates"]["groundedness"]["passed"] is False
    assert report["decision"] == "HOLD"


def test_canonical_response_computes_deterministic_safety_signals(monkeypatch):
    evaluate_agents = _load_evaluate_agents()
    case = evaluate_agents.EvalCase(
        case_id="canonical-safety",
        category="scope",
        page_kind="governance",
        question="Who owns this resource?",
        expect_specialists=("governance",),
        expect_capabilities=("business_service_context",),
        provider_state="normal",
        turn_class="single_domain",
        disposition="integrated",
        safety={"scope_isolation": True, "mutation_denied": True},
    )
    resource_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/vm-1"
    )
    response = {
        "_response_scope": {"subscription": ["sub-a"]},
        "status": "ok",
        "policy_status": "accepted",
        "selected_specialists": ["governance"],
        "selected_tools": ["business_service_context"],
        "tool_results": [
            {
                "call_id": "call-1",
                "specialist_id": "governance",
                "tool": "business_service_context",
                "arguments": {"name": "payments"},
                "status": "ok",
                "data": {
                    "owner": "payments",
                    "resource_id": resource_id,
                },
                "evidence": [
                    {
                        "source_engine": "semantic",
                        "source_table": "entities",
                        "resource_id": resource_id,
                    }
                ],
            }
        ],
        "citations": [
            {
                "citation_id": "tool:call-1:0",
                "source": "semantic:entities",
                "status": "ok",
                "resource_id": resource_id,
            }
        ],
        "synthesis": {
            "status": "deterministic",
            "claims": [
                {
                    "summary": "The resource is owned by payments.",
                    "evidence_refs": ["tool:call-1:0"],
                }
            ],
        },
        "mutation_authorized": False,
    }
    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(
        evaluate_agents,
        "_investigate",
        lambda _api, _token, _case, _scope: (response, 5.0),
    )

    result = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )

    assert result.scope_ok is True
    assert result.unknown_id_denied is True
    assert result.disposition_ok is True
    assert result.manifest_projection_ok is True
    assert result.tool_correctness == 1.0
    assert result.groundedness == 1.0
    assert result.spend_usd == 0.0

    response["selected_specialists"] = ["unreviewed-specialist"]
    unsafe = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    assert unsafe.unknown_id_denied is False
    assert unsafe.manifest_projection_ok is False

    response["selected_specialists"] = ["governance"]
    response["tool_results"][0]["data"] = {
        "id": (
            "/subscriptions/sub-b/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/secret"
        )
    }
    leaked = evaluate_agents._run_case(
        "https://example.invalid",
        "resource",
        case,
        {"subscription": ["sub-a"]},
    )
    assert leaked.scope_ok is False


def test_dedicated_cases_use_production_contracts_and_two_principals(
    monkeypatch,
):
    import urllib.error
    import urllib.parse

    evaluate_agents = _load_evaluate_agents()
    cases = {
        case.case_id: case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.disposition == "dedicated"
    }
    requests: list[tuple[str, str, dict[str, Any] | None, str]] = []
    thread_id = "thr-" + "a" * 32

    def response(data):
        return io.BytesIO(
            json.dumps(
                {
                    "data": data,
                    "scope": {"subscription": ["sub-a"]},
                }
            ).encode()
        )

    def urlopen(request, *, timeout):
        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        body = json.loads(request.data.decode()) if request.data else None
        request_path = urllib.parse.urlparse(request.full_url).path
        requests.append(
            (
                request.full_url,
                request.method,
                body,
                request.get_header("Authorization") or "",
            )
        )
        if (
            request_path.endswith("/api/v1/copilot/investigations")
            and body
            and body.get("thread_id")
        ):
            assert body["thread_id"] == thread_id
            assert body["expected_thread_revision"] == 1
            assert (
                request.get_header("Authorization")
                == "Bearer secondary-token"
            )
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "not found",
                {},
                io.BytesIO(b'{"error":{"code":"not_found"}}'),
            )
        if request_path.endswith("/api/v1/copilot/investigations"):
            return response(
                {
                    "thread_id": thread_id,
                    "thread_revision": 1,
                }
            )
        if request_path.endswith("/api/v1/agents/investigations"):
            return response(
                {
                    "selected_agents": [{"id": "incident"}],
                    "tool_calls": [
                        {
                            "specialist_id": "incident",
                            "tool": "incidents",
                            "status": "ok",
                            "evidence": [],
                        }
                    ],
                    "synthesis": {
                        "status": "deterministic",
                        "claims": [],
                    },
                    "evaluation": {
                        "groundedness": 1.0,
                        "cost": {"llm_calls": 0},
                    },
                }
            )
        if request_path.endswith("/api/v1/agents/catalog"):
            manifest = json.loads(_MANIFEST_PATH.read_text())
            return response(
                {
                    "agents": [
                        {"id": specialist["id"]}
                        for specialist in manifest["specialists"]
                    ]
                }
            )
        return response(
            {
                "tool_calls": [],
                "synthesis": {
                    "status": "deterministic",
                    "claims": [],
                },
                "evaluation": {
                    "groundedness": 1.0,
                    "cost": {"llm_calls": 0},
                },
            }
        )

    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AIOPS_EVALUATION_SECONDARY_TOKEN", "secondary-token")
    thread_states = {}

    results = {
        case_id: evaluate_agents._investigate(
            "https://example.invalid",
            "primary-token",
            case,
            {"subscription": ["sub-a"]},
            thread_states=thread_states,
        )[0]
        for case_id, case in cases.items()
    }

    assert (
        results["scope.cross.principal"]["_cross_principal_denied"]
        is True
    )
    assert (
        thread_states["scope.cross.principal:primary"].thread_id
        == thread_id
    )
    assert (
        thread_states["scope.cross.principal:primary"].revision
        == 1
    )
    assert results["dedicated.investigate"]["selected_specialists"] == [
        "incident"
    ]
    assert results["dedicated.agents"]["selected_specialists"] == []
    assert any(
        urllib.parse.urlparse(url).path.endswith("/api/v1/copilot/investigate")
        and method == "POST"
        for url, method, _body, _authorization in requests
    )
    assert any(
        urllib.parse.urlparse(url).path.endswith("/api/v1/agents/investigations")
        and method == "POST"
        for url, method, _body, _authorization in requests
    )
    assert any(
        urllib.parse.urlparse(url).path.endswith("/api/v1/agents/catalog")
        and method == "GET"
        for url, method, _body, _authorization in requests
    )
    assert sum(
        urllib.parse.urlparse(url).path.endswith(
            "/api/v1/copilot/investigations"
        )
        for url, _method, _body, _authorization in requests
    ) == 2
    principal_headers = {
        authorization
        for url, _method, _body, authorization in requests
        if urllib.parse.urlparse(url).path.endswith(
            "/api/v1/copilot/investigations"
        )
    }
    assert len(principal_headers) == 2
    assert all(principal_headers)


def test_full_canonical_corpus_real_planner_can_promote(monkeypatch):
    from operations.maf_orchestrator import build_deterministic_fallback
    from operations.orchestration_contract import (
        EvidenceSnapshotV2,
        InvestigationRequest,
        SnapshotCoverage,
    )
    from operations.specialist_manifest import load_specialist_manifest

    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    cases = evaluate_agents.load_cases(_CASES_PATH)
    manifest = load_specialist_manifest()

    def investigate(_api, _token, case):
        request = InvestigationRequest(
            question=case.question,
            requested_scope={"subscription": ["sub-a"]},
            snapshot=EvidenceSnapshotV2(
                page_kind=case.page_kind,
                page_id=case.case_id,
                coverage=SnapshotCoverage(
                    visible_count=0,
                    total_count=0,
                    complete=False,
                ),
            ),
        )
        candidate = build_deterministic_fallback(request, manifest)
        steps = candidate.steps if candidate is not None else []
        calls = [
            {
                "call_id": f"{index}:0:{step.specialist_id}:{step.tool_calls[0].tool}",
                "specialist_id": step.specialist_id,
                "tool": step.tool_calls[0].tool,
                "arguments": step.tool_calls[0].arguments,
                "status": "ok",
                "data": {"status": "observed"},
                "evidence": [
                    {
                        "source_engine": "test",
                        "source_table": step.specialist_id,
                        "resource_id": "",
                    }
                ],
            }
            for index, step in enumerate(steps)
        ]
        citations = [
            {
                "citation_id": f"tool:{call['call_id']}:0",
                "source": f"test:{call['specialist_id']}",
                "status": "ok",
            }
            for call in calls
        ]
        claims = [
            {
                "summary": f"{call['specialist_id']} status is observed.",
                "evidence_refs": [f"tool:{call['call_id']}:0"],
            }
            for call in calls
        ]
        return (
            {
                "_response_scope": {"subscription": ["sub-a"]},
                "status": "ok",
                "policy_status": "accepted",
                "selected_specialists": [
                    step.specialist_id for step in steps
                ],
                "selected_tools": [call["tool"] for call in calls],
                "tool_results": calls,
                "citations": citations,
                "synthesis": {
                    "status": "deterministic",
                    "claims": claims,
                },
                "mutation_authorized": False,
            },
            5.0,
        )

    cases_by_id = {case.case_id: case for case in cases}
    thread_id = "thr-" + "b" * 32

    def response(data):
        return io.BytesIO(
            json.dumps(
                {
                    "data": data,
                    "scope": {"subscription": ["sub-a"]},
                }
            ).encode()
        )

    def urlopen(request, *, timeout):
        import urllib.error
        import urllib.parse

        assert timeout == evaluate_agents.REQUEST_TIMEOUT_SECONDS
        body = json.loads(request.data.decode()) if request.data else None
        request_path = urllib.parse.urlparse(request.full_url).path
        if request_path.endswith("/api/v1/copilot/investigations"):
            if body.get("thread_id"):
                raise urllib.error.HTTPError(
                    request.full_url,
                    404,
                    "not found",
                    {},
                    io.BytesIO(b'{"error":{"code":"not_found"}}'),
                )
            case_id = body["snapshot"]["page_id"].removeprefix("eval-")
            if case_id == "scope.cross.principal":
                return response(
                    {
                        "thread_id": thread_id,
                        "thread_revision": 1,
                    }
                )
            return response(
                investigate(
                    "https://example.invalid",
                    "primary-token",
                    cases_by_id[case_id],
                )[0]
            )
        if request_path.endswith("/api/v1/agents/investigations"):
            return response(
                {
                    "selected_agents": [{"id": "incident"}],
                    "tool_calls": [
                        {
                            "specialist_id": "incident",
                            "tool": "incidents",
                            "status": "ok",
                            "evidence": [],
                        }
                    ],
                    "synthesis": {
                        "status": "deterministic",
                        "claims": [],
                    },
                    "evaluation": {
                        "groundedness": 1.0,
                        "cost": {"llm_calls": 0},
                    },
                }
            )
        if request_path.endswith("/api/v1/agents/catalog"):
            return response(
                {
                    "agents": [
                        {"id": specialist.id}
                        for specialist in manifest.specialists
                    ]
                }
            )
        return response(
            {
                "tool_calls": [],
                "synthesis": {
                    "status": "deterministic",
                    "claims": [],
                },
                "evaluation": {
                    "groundedness": 1.0,
                    "cost": {"llm_calls": 0},
                },
            }
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("AIOPS_EVALUATION_SECONDARY_TOKEN", "secondary-token")
    results = []
    for case in cases:
        if case.disposition not in {"redirect", "excluded"}:
            result = evaluate_agents._run_case(
                "https://example.invalid",
                "resource",
                case,
                {"subscription": ["sub-a"]},
            )
        else:
            result = evaluate_agents.Result(
                case_id=case.case_id,
                ok=True,
                specialists=list(case.expect_specialists),
                expected_specialists=list(case.expect_specialists),
                groundedness=1.0,
                tool_correctness=1.0,
                narrated=True,
                latency_ms=5.0,
                tool_names=[],
                citation_valid=True,
                material_claim_coverage=1.0,
                citation_reference_integrity_ok=True,
                mutation_denied=True,
                spend_usd=0.0,
                scope_ok=True,
                unknown_id_denied=True,
                disposition_ok=True,
                manifest_projection_ok=True,
                page_safety_ok=True,
                snapshot_schema_ok=True,
                unsupported_severe_causal_action=0,
                orchestration_runtime="static_route_disposition",
            )
        results.append(evaluate_agents.result_to_release_evidence(result, case))

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=evaluate_agents.load_thresholds(_THRESHOLDS_PATH),
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "PROMOTE", artifact["gates"]
    assert all(
        gate["passed"]
        for gate in artifact["gates"].values()
    )


def test_snapshot_schema_gate_only_applies_to_context_snapshot_pages():
    evaluate_agents = _load_evaluate_agents()
    context_snapshot_pages = {
        "network",
        "vulnerability",
        "patch",
        "incident",
        "governance",
        "resource",
    }
    cases = [
        case
        for case in evaluate_agents.load_cases(_CASES_PATH)
        if case.disposition == "integrated"
    ]

    applicable_case_ids = evaluate_agents._deterministic_applicable_case_ids(cases)[
        "snapshot_schema"
    ]
    for case in cases:
        evidence = evaluate_agents.result_to_release_evidence(
            evaluate_agents.Result(
                case_id=case.case_id,
                ok=True,
                specialists=list(case.expect_specialists),
                expected_specialists=list(case.expect_specialists),
            ),
            case,
        )
        if case.page_kind in context_snapshot_pages:
            assert case.case_id in applicable_case_ids
            assert evidence["snapshot_schema_ok"] is True, case.case_id
        else:
            assert case.case_id not in applicable_case_ids
            assert evidence["snapshot_schema_ok"] is None, case.case_id


def test_main_release_run_executes_cases_from_the_external_corpus(
    tmp_path, monkeypatch
):
    import sys

    evaluate_agents = _load_evaluate_agents()
    source = json.loads(_CASES_PATH.read_text())
    dataset = tmp_path / "cases.json"
    dataset.write_text(json.dumps(source))
    artifact = tmp_path / "baseline.json"
    runtime_e2e_result = tmp_path / "runtime-e2e.json"
    validation_evidence = tmp_path / "validation-evidence.json"
    runtime_e2e_result.write_text(
        json.dumps(
            {
                "status": "passed",
                "revision": "api--phase11-canary",
                "rollout_mode": "canary",
                "promotion": "promote",
                "checks": {
                    "live_specialist_parity": True,
                    "offline_specialist_parity": True,
                    "runtime_readiness": True,
                    "scoped_topology_isolation": True,
                },
            }
        )
    )
    seen: list[str] = []

    dispatched_thread_states = None

    def run_case(
        _api,
        _resource,
        case,
        requested_scope,
        *,
        thread_states,
    ):
        nonlocal dispatched_thread_states
        assert requested_scope == {"subscription": ["sub-a"]}
        if dispatched_thread_states is None:
            dispatched_thread_states = thread_states
        assert thread_states is dispatched_thread_states
        seen.append(case.case_id)
        return evaluate_agents.Result(
            case_id=case.case_id,
            ok=True,
            specialists=list(case.expect_specialists),
            expected_specialists=list(case.expect_specialists),
            groundedness=0.9,
            tool_correctness=1.0,
            latency_ms=25.0,
            citation_valid=True,
            material_claim_coverage=1.0,
            citation_reference_integrity_ok=True,
            mutation_denied=True,
            tool_names=[],
            spend_usd=0.05,
            scope_ok=True,
            unknown_id_denied=True,
            disposition_ok=True,
            manifest_projection_ok=True,
            page_safety_ok=True,
            snapshot_schema_ok=True,
            unsupported_severe_causal_action=0,
        )

    monkeypatch.setattr(evaluate_agents, "_token", lambda _resource: "token")
    monkeypatch.setattr(evaluate_agents, "_run_case", run_case)
    monkeypatch.setattr(evaluate_agents, "PAUSE_BETWEEN_CASES_SECONDS", 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluate_agents.py",
            "--dataset",
            str(dataset),
            "--thresholds",
            str(_THRESHOLDS_PATH),
            "--revision",
            "api--phase11-canary",
            "--subscription",
            "sub-a",
            "--provider",
            "foundry=available",
            "--provider",
            "operations_mcp=available",
            "--provider",
            "azure_mcp=available",
            "--runtime-e2e-result",
            str(runtime_e2e_result),
            "--validation-evidence-out",
            str(validation_evidence),
            "--out",
            str(artifact),
        ],
    )

    assert evaluate_agents.main() == 0
    assert seen == [
        case["case_id"]
        for case in source["cases"]
        if case["disposition"] not in {"redirect", "excluded"}
    ]
    payload = json.loads(artifact.read_text())
    assert [item["case_id"] for item in payload["case_evidence"]] == [
        case["case_id"] for case in source["cases"]
    ]
    assert payload["decision"] == "PROMOTE"
    assert all(json.loads(validation_evidence.read_text())["gates"].values())


def test_validate_artifact_rejects_promote_with_omitted_release_gates():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = json.loads(_THRESHOLDS_PATH.read_text())
    digest = lambda value: __import__("hashlib").sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact = {
        "dataset_version": "1",
        "thresholds_version": "1",
        "manifest_version": 1,
        "contract_version": "1.0",
        "dataset_sha256": digest(dataset),
        "thresholds_sha256": digest(thresholds),
        "revision": "api--phase11-canary",
        "provider_availability": {
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        "metrics": {},
        "validation_evidence": {},
        "case_evidence": [],
        "decision": "PROMOTE",
        "gates": {"corpus_completeness": {"passed": True}},
    }

    ok, problems = evaluate_agents.validate_artifact(
        artifact, dataset_version="1", thresholds_version="1"
    )

    assert ok is False
    assert any("missing required gates" in problem for problem in problems)


def test_release_artifact_holds_when_any_live_case_lacks_spend():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
            spend_usd=None if index == 0 else 0.05,
        )
        for index, case in enumerate(cases)
    ]

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "HOLD_OR_DISABLE_MODE"
    assert artifact["gates"]["measurement_completeness"]["passed"] is False
    assert artifact["gates"]["measurement_completeness"]["observed"][
        "missing_spend_case_ids"
    ] == [cases[0].case_id]


def test_missing_page_safety_measurement_forces_hold():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    target = next(case for case in cases if case.disposition == "integrated")
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
            page_safety_ok=None if case.case_id == target.case_id else True,
        )
        for case in cases
    ]

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "HOLD"
    gate = artifact["gates"]["page_safe_specialist_routing"]
    assert gate["passed"] is False
    assert gate["observed"]["missing_case_ids"] == [target.case_id]


def test_release_artifact_rejects_boolean_spend_values():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
            spend_usd=False,
        )
        for case in cases
    ]

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "HOLD_OR_DISABLE_MODE"
    assert artifact["gates"]["measurement_completeness"]["passed"] is False


def test_external_boolean_cannot_override_missing_scope_case_evidence():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
            scope_ok=None if case.case_id == "scope.cross.principal" else True,
        )
        for case in cases
    ]

    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )

    assert artifact["decision"] == "HOLD"
    assert artifact["gates"]["scope_isolation"]["passed"] is False
    assert artifact["gates"]["scope_isolation"]["observed"]["missing_case_ids"] == [
        "scope.cross.principal"
    ]


def test_validate_artifact_recomputes_decision_from_case_evidence():
    evaluate_agents = _load_evaluate_agents()
    dataset = json.loads(_CASES_PATH.read_text())
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    results = [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
        )
        for case in cases
    ]
    artifact = evaluate_agents.build_release_artifact(
        results,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision="api--phase11-canary",
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=_passing_validation_evidence(),
    )
    scope_case = next(
        item
        for item in artifact["case_evidence"]
        if item["case_id"] == "scope.cross.subscription"
    )
    scope_case["scope_ok"] = False

    ok, problems = evaluate_agents.validate_artifact(
        artifact, dataset_version="1", thresholds_version="1"
    )

    assert ok is False
    assert any("recomputed evidence" in problem for problem in problems)


@pytest.mark.parametrize(
    ("field", "value"),
    [("case_evidence", [None]), ("gates", {"routing": None})],
)
def test_validate_artifact_rejects_malformed_nested_values(field, value):
    evaluate_agents = _load_evaluate_agents()
    artifact = {
        "dataset_version": "1",
        "thresholds_version": "1",
        "revision": "api--phase11-canary",
        "case_evidence": [],
        "gates": {},
    }
    artifact[field] = value

    ok, problems = evaluate_agents.validate_artifact(
        artifact, dataset_version="1", thresholds_version="1"
    )

    assert ok is False
    assert any("malformed" in problem for problem in problems)


def _complete_case_evidence(evaluate_agents, cases):
    return [
        _passing_result(
            case_id=case.case_id,
            category=case.category,
            expected_specialists=list(case.expect_specialists),
            specialists=list(case.expect_specialists),
            turn_class=case.turn_class,
            provider_state=case.provider_state,
        )
        for case in cases
    ]


def _passing_runtime_result(revision):
    return {
        "status": "passed",
        "revision": revision,
        "rollout_mode": "canary",
        "promotion": "promote",
        "checks": {
            "live_specialist_parity": True,
            "offline_specialist_parity": True,
            "runtime_readiness": True,
            "scoped_topology_isolation": True,
        },
    }


def test_single_corpus_evidence_emits_revision_bound_validation_atomically(tmp_path):
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    revision = "api--phase11-canary"
    destination = tmp_path / "validation-evidence.json"

    evidence = evaluate_agents.emit_runtime_validation_evidence(
        _passing_runtime_result(revision),
        case_evidence=_complete_case_evidence(evaluate_agents, cases),
        cases=cases,
        revision=revision,
        thresholds=thresholds,
        destination=destination,
    )

    assert json.loads(destination.read_text()) == evidence
    assert evidence == {
        "revision": revision,
        "runtime_checks": {
            "live_specialist_parity": True,
            "offline_specialist_parity": True,
            "runtime_readiness": True,
            "scoped_topology_isolation": True,
        },
        "gates": {
            name: True
            for name in sorted(thresholds["deterministic_gates"])
        },
    }
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda payload: payload.update(revision="api--wrong-revision"),
            "revision does not match",
        ),
        (
            lambda payload: payload["checks"].pop("runtime_readiness"),
            "exact runtime check set",
        ),
        (
            lambda payload: payload["checks"].update(runtime_readiness=1),
            "boolean values",
        ),
        (
            lambda payload: payload.update(status="failed"),
            "status must be 'passed'",
        ),
        (
            lambda payload: payload.update(rollout_mode="shadow"),
            "rollout_mode must be 'canary'",
        ),
    ],
)
def test_runtime_e2e_validation_evidence_fails_closed_without_replacing_output(
    tmp_path, mutate, match
):
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    revision = "api--phase11-canary"
    destination = tmp_path / "validation-evidence.json"
    destination.write_text('{"preserved": true}\n')
    runtime_result = _passing_runtime_result(revision)
    mutate(runtime_result)

    with pytest.raises(ValueError, match=match):
        evaluate_agents.emit_runtime_validation_evidence(
            runtime_result,
            case_evidence=_complete_case_evidence(evaluate_agents, cases),
            cases=cases,
            revision=revision,
            thresholds=thresholds,
            destination=destination,
        )

    assert json.loads(destination.read_text()) == {"preserved": True}


def test_parity_pass_cannot_make_unproven_mutation_gate_true(tmp_path):
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    dataset = json.loads(_CASES_PATH.read_text())
    cases = evaluate_agents.load_cases(_CASES_PATH)
    case_evidence = _complete_case_evidence(evaluate_agents, cases)
    mutation_case_ids = {
        case.case_id for case in cases if case.safety.get("mutation_denied")
    }
    target = next(
        result
        for result in case_evidence
        if result["case_id"] in mutation_case_ids
    )
    target["mutation_denied"] = False
    revision = "api--phase11-canary"
    evidence = evaluate_agents.emit_runtime_validation_evidence(
        _passing_runtime_result(revision),
        case_evidence=case_evidence,
        cases=cases,
        revision=revision,
        thresholds=thresholds,
        destination=tmp_path / "validation-evidence.json",
    )
    artifact = evaluate_agents.build_release_artifact(
        case_evidence,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision=revision,
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=evidence["gates"],
    )

    assert evidence["runtime_checks"]["live_specialist_parity"] is True
    assert evidence["gates"]["mutation_denied"] is False
    assert artifact["decision"] == "HOLD"


def test_blocked_live_parity_only_fails_parity_dependent_gates(tmp_path):
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    cases = evaluate_agents.load_cases(_CASES_PATH)
    revision = "api--phase11-canary"
    runtime_result = _passing_runtime_result(revision)
    runtime_result["checks"]["live_specialist_parity"] = False
    runtime_result["promotion"] = "hold"

    evidence = evaluate_agents.emit_runtime_validation_evidence(
        runtime_result,
        case_evidence=_complete_case_evidence(evaluate_agents, cases),
        cases=cases,
        revision=revision,
        thresholds=thresholds,
        destination=tmp_path / "validation-evidence.json",
    )

    assert evidence["gates"]["manifest_projection_parity"] is False
    assert evidence["gates"]["tool_grant_parity"] is False
    assert evidence["gates"]["mutation_denied"] is True
    assert evidence["gates"]["citation_reference_integrity"] is True


def test_missing_case_proof_yields_false_gate_and_hold(tmp_path):
    evaluate_agents = _load_evaluate_agents()
    thresholds = evaluate_agents.load_thresholds(_THRESHOLDS_PATH)
    dataset = json.loads(_CASES_PATH.read_text())
    cases = evaluate_agents.load_cases(_CASES_PATH)
    case_evidence = _complete_case_evidence(evaluate_agents, cases)
    citation_case_ids = {
        case.case_id
        for case in cases
        if case.disposition in {"integrated", "dedicated"}
    }
    target = next(
        result
        for result in case_evidence
        if result["case_id"] in citation_case_ids
    )
    target["citation_reference_integrity_ok"] = None
    revision = "api--phase11-canary"
    evidence = evaluate_agents.emit_runtime_validation_evidence(
        _passing_runtime_result(revision),
        case_evidence=case_evidence,
        cases=cases,
        revision=revision,
        thresholds=thresholds,
        destination=tmp_path / "validation-evidence.json",
    )
    artifact = evaluate_agents.build_release_artifact(
        case_evidence,
        cases=cases,
        dataset=dataset,
        thresholds=thresholds,
        revision=revision,
        provider_availability={
            "foundry": "available",
            "operations_mcp": "available",
            "azure_mcp": "available",
        },
        validation_evidence=evidence["gates"],
    )

    assert evidence["gates"]["citation_reference_integrity"] is False
    assert artifact["decision"] == "HOLD"


def test_runtime_e2e_requires_revision_before_live_commands(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "API_URL": "https://offline.invalid",
            "WEB_URL": "https://offline.invalid",
            "API_TOKEN": "not-a-token",
            "HUB_CONNECTION_ID": "hub",
            "SPOKE_CONNECTION_ID": "spoke",
            "AIOPS_ARG_CONFIG": str(tmp_path / "arg.yaml"),
            "AIOPS_FABRIC_CONFIG": str(tmp_path / "fabric.yaml"),
        }
    )
    env.pop("COPILOT_DEPLOYED_REVISION", None)

    result = subprocess.run(
        ["bash", str(_REPO_ROOT / "infra/scripts/validate-runtime-e2e.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "COPILOT_DEPLOYED_REVISION" in result.stderr
