"""Exact offline Package C evidence, authorization and canonical-ledger regressions."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.scope import Scope
from intelligence.incidents.incident_engine import IncidentEngine
from operations.incident_scenarios import incident_projection, investigate
from operations.mcp_server import validate_tool_arguments
from operations.tools import call_tool
from semantic.live_operations import LiveIncidentEngine

ROOT = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/app"
DEPENDENT = ROOT + "-dependent"
FOREIGN = ROOT.replace("sub-a", "sub-secret")
START = "2026-10-25T10:00:00Z"
END = "2026-10-25T11:00:00Z"
NOW = "2026-10-25T12:00:00Z"
ARGS = {"scenario": "recent_change", "resource_id": ROOT, "since": START, "until": END}
SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})


def context_fixture(*, changes=True, alerts=True, dependencies=None):
    reads, authorizations = [], []
    identities = {
        value.casefold(): {
            "resource_id": value,
            "subscription_id": "sub-a",
            "resource_type": "microsoft.compute/virtualmachines",
        }
        for value in (ROOT, DEPENDENT)
    }

    def authorize(scope, resource):
        authorizations.append(resource)
        return identities.get(resource.casefold()) if scope == SCOPE else None

    engine = IncidentEngine.from_snapshot(
        resources=[
            {
                "resource_key": ROOT,
                "name": "app",
                "downstream_dependents": dependencies
                or [DEPENDENT, FOREIGN, "Unresolved name"],
            }
        ],
        incidents=[],
        alerts=[
            {
                "alert_id": "active",
                "resource_key": ROOT,
                "fired_at": "2026-10-25T10:15:00Z",
                "status": "Fired",
            },
            {
                "alert_id": "recovered",
                "resource_key": ROOT,
                "fired_at": "2026-10-25T10:30:00Z",
                "status": "Resolved",
            },
            {
                "alert_id": "dependent",
                "resource_key": DEPENDENT,
                "fired_at": "2026-10-25T10:20:00Z",
                "status": "Fired",
            },
            {
                "alert_id": "foreign",
                "resource_key": FOREIGN,
                "fired_at": "2026-10-25T10:20:00Z",
                "status": "Fired",
            },
        ]
        if alerts
        else [],
        resource_changes=[],
        patch_findings=[],
        lifecycle_findings=[],
        history=[],
        freshness=NOW,
        now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    change = SimpleNamespace(
        freshness=NOW,
        changes=[
            {
                "change_id": "relevant",
                "resource_key": ROOT,
                "changed_at": "2026-10-25T10:10:00Z",
                "previous_state": {"password": "secret-before"},
                "current_state": {"password": "secret-after"},
                "summary": "SECRET-UNSAFE-SUMMARY",
            },
            {
                "change_id": "after-symptom",
                "resource_key": ROOT,
                "changed_at": "2026-10-25T10:40:00Z",
            },
            {
                "change_id": "unrelated-coincident",
                "resource_key": FOREIGN,
                "changed_at": "2026-10-25T10:10:00Z",
            },
            {
                "change_id": "out-of-window",
                "resource_key": ROOT,
                "changed_at": "2026-10-25T09:59:59Z",
            },
        ]
        if changes
        else [],
    )

    def resolve(name):
        reads.append(name)
        return {"change": change, "incidents": engine}.get(name)

    context = SimpleNamespace(
        resolve_provider=resolve,
        provider_runtime=None,
        inventory_read_port=lambda: SimpleNamespace(get_resource=authorize),
    )
    return context, reads, authorizations, engine, change


def review(context, **updates):
    return call_tool("incidents", {**ARGS, **updates}, context=context, scope=SCOPE)


def test_exact_scoped_timeline_ranking_counterevidence_and_redaction():
    context, reads, auth, _, _ = context_fixture()
    result = review(context)
    data = result.data["investigation"]
    assert reads == ["change", "incidents"]
    assert auth == [ROOT]  # Recent-change investigation never traverses neighbors.
    assert [(row["kind"], row["timestamp"][11:16]) for row in data["timeline"]] == [
        ("change", "10:10"),
        ("alert", "10:15"),
        ("alert", "10:30"),
        ("change", "10:40"),
    ]
    assert len(data["hypotheses"]) == 2
    first, second = data["hypotheses"]
    assert first["rank"] == 1
    assert first["ranking_basis"] == "same-resource change preceding supplied symptom"
    assert first["counterevidence"] == [data["timeline"][2]["evidence_ref"]]
    assert second["ranking_basis"] == "change only"
    assert second["counterevidence"] == [
        data["timeline"][1]["evidence_ref"],
        data["timeline"][2]["evidence_ref"],
    ]
    assert all(row["causality"] == "not_established" for row in data["hypotheses"])
    assert all(row["confidence"] == "low" for row in data["hypotheses"])
    assert data["status"] == "partial"
    assert data["coverage"]["health"]["status"] == "unavailable"
    assert not any(section["complete"] for section in data["coverage"].values())
    serialized = json.dumps(result.to_dict())
    for forbidden in (
        "secret-before",
        "secret-after",
        "SECRET-UNSAFE-SUMMARY",
        "password",
        FOREIGN,
        "Unresolved name",
    ):
        assert forbidden not in serialized
    assert len(result.evidence) == 2


def test_impact_distinguishes_known_dependency_from_unproven_outage():
    context, reads, _, _, _ = context_fixture()
    result = review(context, scenario="incident_impact")
    impact = result.data["investigation"]["impact"]
    assert reads == ["change", "incidents"]
    assert len(impact) == 1
    assert impact[0]["resource_id"] == DEPENDENT
    assert impact[0]["relationship"] == "known_projection_dependency"
    assert impact[0]["impact"] == "observed_symptom"
    assert impact[0]["confirmed_outage"] is False
    assert len(impact[0]["supporting_evidence"]) == 2
    context, _, _, _, _ = context_fixture(alerts=False)
    possible = review(context, scenario="incident_impact").data["investigation"][
        "impact"
    ][0]
    assert possible["impact"] == "inferred_possible_impact"
    assert possible["confirmed_outage"] is False


def test_no_change_and_conflicting_evidence_are_not_healthy_or_causal():
    context, _, _, _, _ = context_fixture(changes=False)
    data = review(context).data["investigation"]
    assert data["hypotheses"] == []
    assert data["status"] == "partial"
    assert any(
        "No selected-resource change observed" in item for item in data["unknowns"]
    )
    assert any("Conflicting" in item for item in data["unknowns"])
    assert data["next_checks"]


def test_dependency_recovery_is_not_counterevidence_for_another_resource_change():
    context, _, _, engine, _ = context_fixture()
    engine.intelligence.evidence.append(
        {
            **engine.intelligence.evidence[1],
            "resource_key": DEPENDENT.casefold(),
            "evidence_id": "dependent-recovered",
        }
    )
    # Scenario facts must not inherit existing broader causal classifications.
    engine.report = lambda: pytest.fail("Do not import precomputed causal conclusions")
    data = review(context, scenario="incident_impact").data["investigation"]
    root_recovery = next(
        row
        for row in data["timeline"]
        if row["resource_id"].casefold() == ROOT.casefold()
        and row["status"] == "resolved"
    )
    dependent_recovery = next(
        row
        for row in data["timeline"]
        if row["resource_id"].casefold() == DEPENDENT.casefold()
        and row["status"] == "resolved"
    )
    assert data["hypotheses"][0]["counterevidence"] == [root_recovery["evidence_ref"]]
    assert data["impact"][0]["counterevidence"] == [dependent_recovery["evidence_ref"]]


def test_missing_providers_remains_unavailable_with_coverage_receipt():
    context, _, _, _, _ = context_fixture()
    context.resolve_provider = lambda name: None
    result = review(context)
    assert result.status == "unavailable"
    data = result.data["investigation"]
    assert data["status"] == "unavailable"
    assert data["timeline"] == data["hypotheses"] == data["impact"] == []
    assert all(
        row["status"] in {"unavailable", "not_requested"}
        for row in data["coverage"].values()
    )
    assert result.evidence[0].timestamp == ""  # No invented provider observation.


def test_live_alert_adapter_never_fabricates_target_or_provider_timestamp():
    live = LiveIncidentEngine(
        (
            {
                "id": "missing-time",
                "properties": {"essentials": {"targetResource": ROOT}},
            },
            {
                "id": "missing-target",
                "properties": {"essentials": {"startDateTime": START}},
            },
            {
                "id": "good",
                "properties": {
                    "essentials": {
                        "targetResource": ROOT,
                        "startDateTime": START,
                        "monitorCondition": "Fired",
                    }
                },
            },
            {
                "id": "invalid-time",
                "properties": {
                    "essentials": {
                        "targetResource": ROOT,
                        "startDateTime": "not-a-time",
                    }
                },
            },
        ),
        NOW,
    )
    projection = incident_projection(live)
    result = investigate(
        ARGS,
        identity={"resource_id": ROOT},
        changes=None,
        incidents=projection,
        authorize=lambda _: None,
    )
    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["timestamp"] == "2026-10-25T10:00:00+00:00"
    assert any("missing/invalid timestamps" in row for row in result["unknowns"])
    assert result["coverage"]["alerts"]["complete"] is False


@pytest.mark.parametrize(
    "updates",
    [
        {"scenario": "invented"},
        {"resource_id": "/not-an-arm-id"},
        {"since": ""},
        {"since": "2026-10-25T10:00:00"},
        {"until": START},
        {"until": "2026-11-25T10:00:00Z"},
        {"incident_id": "mix-record"},
        {
            "since": "0001-01-01T00:00:00+23:59",
            "until": "0001-01-01T01:00:00+23:59",
        },
        {
            "since": "9999-12-31T22:00:00-23:59",
            "until": "9999-12-31T23:00:00-23:59",
        },
        {
            "since": "9999-12-31T23:00:00+00:00",
            "until": "9999-12-31T23:59:59-23:59",
        },
    ],
)
def test_invalid_window_or_resource_is_denied_before_any_read(updates):
    context, reads, auth, _, _ = context_fixture()
    assert review(context, **updates).status == "denied"
    assert reads == auth == []
    with pytest.raises(ValueError):
        validate_tool_arguments("incidents", {**ARGS, **updates})


@pytest.mark.parametrize(
    "since,until",
    [
        ("0001-01-01T23:59:00+23:59", "0001-01-02T00:59:00+23:59"),
        ("9999-12-30T23:00:00-23:59", "9999-12-31T00:00:00-23:59"),
    ],
)
def test_valid_near_boundary_offsets_preserve_window_validation(since, until):
    from operations.incident_scenarios import validate_parameters

    arguments = {**ARGS, "since": since, "until": until}
    validated, missing = validate_tool_arguments("incidents", arguments)
    assert validated == arguments
    assert missing == []
    _, start, end = validate_parameters(arguments)
    assert start.tzinfo == end.tzinfo == UTC
    assert (end - start).total_seconds() == 3600


@pytest.mark.parametrize("canonical", [True, False])
@pytest.mark.parametrize(
    "since,until",
    [
        ("0001-01-01T00:00:00+23:59", "0001-01-01T01:00:00+23:59"),
        ("9999-12-31T22:00:00-23:59", "9999-12-31T23:00:00-23:59"),
        ("9999-12-31T23:00:00+00:00", "9999-12-31T23:59:59-23:59"),
    ],
)
def test_boundary_overflow_api_rejected_before_evidence_access(
    tmp_path, monkeypatch, canonical, since, until
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    if not canonical:
        monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    context = _context(tmp_path, None)
    acquired = []
    context.inventory_read_port_provider = lambda: acquired.append("inventory")
    context.change_provider = lambda: acquired.append("change")
    context.hybrid_incident_provider = lambda _: acquired.append("incidents")
    context.incident_history_read_port_provider = lambda: acquired.append("history")
    response = TestClient(create_app(context), raise_server_exceptions=False).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json={
            "contract_version": "1",
            "question": "Investigate selected resource and window",
            "requested_scope": SCOPE.to_dict(),
            "snapshot": {
                "version": "2",
                "page_kind": "changes",
                "page_id": "incident-change-investigation",
                "selected_entities": [{"type": "azure", "resource_id": ROOT}],
                "filters": {"since": [since], "until": [until]},
                "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
                "evidence": [],
            },
            "hint": {
                "specialist_id": "change",
                "tool": "incidents",
                "arguments": {**ARGS, "since": since, "until": until},
            },
        },
    )
    assert response.status_code == 400, response.text
    assert acquired == []


def test_out_of_scope_resource_denied_before_evidence_acquisition():
    context, reads, _, _, _ = context_fixture()
    result = review(context, resource_id=FOREIGN)
    assert result.status == "denied"
    assert result.data is None
    assert reads == []


def test_rejected_explicit_scenario_never_falls_back_to_scope_wide_incidents():
    from operations.orchestration_contract import (
        CandidatePlan,
        EvidenceSnapshotV2,
        InvestigationRequest,
        SnapshotCoverage,
        SpecialistStep,
        ToolCallCandidate,
    )
    from operations.orchestration_service import OrchestrationService

    request = InvestigationRequest(
        question="Investigate a change",
        requested_scope=SCOPE.to_dict(),
        snapshot=EvidenceSnapshotV2(
            page_kind="changes",
            page_id="scenario",
            coverage=SnapshotCoverage(visible_count=0, total_count=0, complete=False),
        ),
    )
    proposal = CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id="change",
                tool_calls=[
                    ToolCallCandidate(
                        tool="incidents",
                        arguments=ARGS,
                        citation_ids=["snapshot:coverage"],
                    )
                ],
            )
        ]
    )
    fallback_calls = []
    service = OrchestrationService(
        planner=lambda _: proposal,
        fallback_planner=lambda _: fallback_calls.append("unsafe") or proposal,
    )
    candidate, policy_status, reason = service._resolve_candidate(request, SCOPE)
    assert candidate is None
    assert policy_status == "fallback"
    assert reason == "candidate_rejected:invalid_arguments"
    assert fallback_calls == []


def test_dependency_cycles_and_large_graph_are_bounded_to_ten_direct_checks():
    context, _, auth, _, _ = context_fixture(
        dependencies=[ROOT, DEPENDENT]
        + [ROOT + f"-z-child-{index}" for index in range(20)]
    )
    data = review(context, scenario="incident_impact").data["investigation"]
    assert len(auth) <= 11
    assert len(data["impact"]) == 1
    assert data["coverage"]["dependencies"]["max_depth"] == 1
    assert any("truncated" in row for row in data["unknowns"])


def test_timeline_and_hypothesis_caps_preserve_closed_returned_evidence():
    context, _, _, _, change = context_fixture(alerts=False)
    change.changes = [
        {
            "change_id": f"change-{index}",
            "resource_key": ROOT,
            "changed_at": "2026-10-25T10:10:00Z",
        }
        for index in range(70)
    ]
    data = review(context).data["investigation"]
    assert len(data["timeline"]) == 50
    assert len(data["hypotheses"]) == 10
    assert [row["rank"] for row in data["hypotheses"]] == list(range(1, 11))
    refs = {row["evidence_ref"] for row in data["timeline"]}
    assert all(
        set(row["supporting_evidence"] + row["counterevidence"]) <= refs
        for row in data["hypotheses"]
    )
    assert "_score" not in json.dumps(data)
    assert any("Timeline truncated" in row for row in data["unknowns"])


@pytest.mark.parametrize(
    "scenario,owner,page",
    [
        ("recent_change", "change", "changes"),
        ("incident_impact", "incident", "changes"),
        ("incident_impact", "resource_health_observability", "resource_health"),
    ],
)
@pytest.mark.parametrize("canonical", [True, False])
def test_canonical_api_one_collection_shared_drawer_and_retained_ledger(
    tmp_path, monkeypatch, scenario, owner, page, canonical
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, StubAgent, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    if not canonical:
        monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    fixture, reads, _, incident, change = context_fixture()
    agent = StubAgent()
    context = _context(tmp_path, agent)
    context.inventory_read_port_provider = fixture.inventory_read_port
    context.hybrid_incident_provider = lambda subscriptions: (
        reads.append("incidents"),
        incident,
    )[1]
    context.change_provider = lambda: (reads.append("change"), change)[1]
    client = TestClient(create_app(context), raise_server_exceptions=False)
    payload = {
        "contract_version": "1",
        "question": "Investigate selected resource and window",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": page,
            "page_id": "incident-change-investigation",
            "selected_entities": [{"type": "azure", "resource_id": ROOT}],
            "filters": {"since": [START], "until": [END]},
            "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
            "evidence": [],
        },
        "hint": {
            "specialist_id": owner,
            "tool": "incidents",
            "arguments": {**ARGS, "scenario": scenario},
        },
    }
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=payload,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert reads == ["change", "incidents"]
    assert data["selected_tools"] == ["incidents"]
    assert data["selected_specialists"] == [owner]
    assert data["mutation_authorized"] is False
    assert data["tool_results"][0]["data"]["investigation"]["scenario_id"] == scenario
    assert agent.calls == []  # Optional narration cannot turn proximity into causality.
    if canonical:
        assert data["synthesis"]["status"] == "deterministic"
        assert data["synthesis"]["mode"] == "deterministic"
        assert "not causality" in data["synthesis"]["claims"][0]["summary"]
        refs = data["synthesis"]["claims"][0]["evidence_refs"]
        assert set(refs) <= {row["citation_id"] for row in data["citations"]}
    else:
        assert data["synthesis"]["compatibility_answer"]["model"] == "deterministic"
        assert "not causality" in data["synthesis"]["compatibility_answer"]["text"]
    assert data["thread_id"] and data["thread_revision"] >= 1
    assert FOREIGN not in response.text
    retained = client.get(
        f"/api/v1/copilot/threads/{data['thread_id']}/history?subscription=sub-a",
        headers=HEADERS,
    )
    assert retained.status_code == 200, retained.text
    assert (
        retained.json()["data"]["turns"][0]["tool_results"][0]["data"]["investigation"][
            "scenario_id"
        ]
        == scenario
    )
    # A mismatched window must fail before falling back to a broader incidents read.
    reads.clear()
    payload["hint"]["arguments"]["since"] = "2026-10-25T10:01:00Z"
    denied = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=payload,
    )
    assert denied.status_code == 400, denied.text
    assert reads == []
    payload["hint"]["arguments"]["since"] = START
    payload["hint"]["specialist_id"] = "network"
    foreign_tool = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=payload,
    )
    assert foreign_tool.status_code == 400, foreign_tool.text
    assert reads == []  # Denial precedes handler/provider access in both rollout modes.
