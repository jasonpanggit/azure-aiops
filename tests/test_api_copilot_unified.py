from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context

from api.app import create_app
from api.evidence import Evidence
from api.scope import Scope
from operations.foundry_agent import FoundryAgentError
from operations.investigation_thread_store import (
    InvestigationThreadStore,
    ThreadNotFound,
)
from operations.orchestration_contract import (
    CandidatePlan,
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
    SnapshotEvidence,
    SnapshotFreshness,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import PolicyViolation
from operations.orchestration_service import (
    OrchestrationService,
    PlannerUnavailableError,
)
from operations.specialist_manifest import INVENTORY_DATA_HEALTH_ID
from operations.tools import STATUS_OK, ToolResult


def _request(*, thread_id: str | None = None) -> InvestigationRequest:
    return InvestigationRequest(
        question="Show inventory resources and data health.",
        requested_scope={"subscription": ["sub-a"]},
        thread_id=thread_id,
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(visible_count=1, total_count=2, complete=False),
            freshness=[
                SnapshotFreshness(
                    source="inventory",
                    observed_at="2026-09-01T00:00:00Z",
                    status="stale",
                )
            ],
            evidence=[
                SnapshotEvidence(
                    evidence_id="inventory:visible",
                    source="inventory-page",
                    status="ok",
                    observed_at="2026-09-01T00:00:00Z",
                    data={"visible": 1},
                )
            ],
        ),
    )


def _candidate(**overrides) -> CandidatePlan:
    payload = {
        "steps": [
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=["inventory:visible"],
                    )
                ],
            )
        ],
        "estimated_tokens": 500,
        "max_wall_seconds": 5,
    }
    payload.update(overrides)
    return CandidatePlan.model_validate(payload)


def _result() -> ToolResult:
    return ToolResult(
        status=STATUS_OK,
        data={
            "resources": [{"id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"}],
            "total": 1,
        },
        evidence=(
            Evidence(
                source_engine="intelligence.inventory.InventoryReadPort",
                source_table="inventory/resource_observations",
                resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                confidence="high",
            ),
        ),
    )


def test_canonical_inventory_tracer_returns_citations_uncertainty_and_thread():
    calls: list[tuple[str, dict[str, object], dict[str, list[str]]]] = []

    def execute(name, arguments, *, context, scope):
        calls.append((name, dict(arguments), scope.to_dict()))
        return _result()

    store = InvestigationThreadStore()
    service = OrchestrationService(
        planner=lambda request: _candidate(),
        executor=execute,
        thread_store=store,
    )
    result = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "accepted"
    assert result.fallback_reason == ""
    assert result.selected_specialists == [INVENTORY_DATA_HEALTH_ID]
    assert result.selected_tools == ["inventory_resources"]
    assert calls == [
        ("inventory_resources", {}, {"subscription": ["sub-a"]})
    ]
    assert result.coverage.complete is False
    assert "visible subset is incomplete" in result.uncertainty
    assert "inventory freshness is stale" in result.uncertainty
    assert {item.citation_id for item in result.citations} >= {
        "inventory:visible",
        "tool:0:0:inventory_data_health:inventory_resources:0",
    }
    assert result.thread_id.startswith("thr-")
    assert result.thread_revision == 1
    assert store.history(
        result.thread_id,
        "operator-a",
        Scope({"subscription": ["sub-a"]}),
    )


def test_default_executor_uses_scoped_governed_inventory_read_port():
    observed: list[dict[str, list[str]]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            observed.append(scope.to_dict())
            assert family is None
            assert resource_type is None
            assert limit == 25
            return {
                "resources": [
                    {
                        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                        "subscription": "sub-a",
                    }
                ],
                "total": 1,
            }

    class Context:
        provider_runtime = None

        def resolve_provider(self, name):
            return InventoryPort() if name == "inventory_read_port" else None

    result = OrchestrationService().execute(
        _request(),
        context=Context(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert observed == [{"subscription": ["sub-a"]}]
    assert result.selected_tools == ["inventory_resources"]
    assert result.tool_results[0]["status"] == STATUS_OK
    assert result.mutation_authorized is False


@pytest.mark.parametrize(
    ("planner", "reason"),
    [
        (lambda request: (_ for _ in ()).throw(TimeoutError()), "planner_timeout"),
        (lambda request: (_ for _ in ()).throw(ValueError("bad JSON")), "planner_parse_error"),
        (lambda request: (_ for _ in ()).throw(ConnectionError()), "planner_unavailable"),
        (
            lambda request: (_ for _ in ()).throw(PlannerUnavailableError()),
            "planner_unavailable",
        ),
        (
            lambda request: (_ for _ in ()).throw(FoundryAgentError("offline")),
            "planner_unavailable",
        ),
        (None, "planner_unavailable"),
    ],
)
def test_planner_failure_uses_validated_deterministic_fallback(planner, reason):
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    result = OrchestrationService(planner=planner, executor=execute).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "fallback"
    assert result.fallback_reason == reason
    assert calls == ["inventory_resources"]
    assert result.citations


def test_rejected_candidate_executes_only_the_validated_fallback():
    calls: list[str] = []
    rejected = _candidate(mutation_intent=True)

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    result = OrchestrationService(
        planner=lambda request: rejected,
        executor=execute,
    ).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.fallback_reason == "candidate_rejected:mutation_forbidden"
    assert calls == ["inventory_resources"]


def test_foreign_principal_cannot_continue_thread_and_causes_zero_calls():
    calls: list[str] = []

    def execute(name, arguments, *, context, scope):
        calls.append(name)
        return _result()

    store = InvestigationThreadStore()
    service = OrchestrationService(executor=execute, thread_store=store)
    first = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    calls.clear()

    with pytest.raises(ThreadNotFound):
        service.execute(
            _request(thread_id=first.thread_id),
            context=object(),
            principal_subject="operator-b",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert calls == []


def test_thread_history_rechecks_current_scope():
    store = InvestigationThreadStore()
    thread = store.create("operator-a", Scope({"subscription": ["sub-a"]}))
    store.append(
        thread.thread_id,
        "operator-a",
        Scope({"subscription": ["sub-a"]}),
        {"status": "ok"},
    )

    with pytest.raises(ThreadNotFound):
        store.history(
            thread.thread_id,
            "operator-a",
            Scope({"subscription": ["sub-b"]}),
        )


def test_scope_narrowing_redacts_wider_historical_turns():
    store = InvestigationThreadStore()
    broad = Scope({"subscription": ["sub-a", "sub-b"]})
    narrow = Scope({"subscription": ["sub-a"]})
    thread = store.create("operator-a", broad)
    store.append(
        thread.thread_id,
        "operator-a",
        broad,
        {
            "status": "ok",
            "tool_results": [{"data": {"subscription": "sub-b", "secret": "b-only"}}],
            "citations": [{"resource_id": "/subscriptions/sub-b/resourceGroups/rg"}],
        },
    )
    store.append(
        thread.thread_id,
        "operator-a",
        narrow,
        {"status": "ok", "tool_results": [{"data": {"subscription": "sub-a"}}]},
    )

    history = store.history(thread.thread_id, "operator-a", narrow)

    assert history[0]["status"] == "historical_scope_restricted"
    assert history[0]["tool_results"] == []
    assert "b-only" not in str(history)
    assert history[1]["tool_results"][0]["data"]["subscription"] == "sub-a"


def test_empty_snapshot_fallback_uses_canonical_coverage_citation():
    request = _request().model_copy(
        update={
            "snapshot": EvidenceSnapshotV2(
                page_kind="inventory",
                page_id="inventory",
                coverage=SnapshotCoverage(
                    visible_count=0,
                    total_count=0,
                    complete=True,
                ),
            )
        }
    )

    result = OrchestrationService(executor=lambda *args, **kwargs: _result()).execute(
        request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert result.policy_status == "fallback"
    assert "snapshot:coverage" in {
        citation.citation_id for citation in result.citations
    }


def test_repeated_tool_calls_retain_distinct_citations():
    candidate = CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=["inventory:visible"],
                    ),
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={"family": "paas"},
                        citation_ids=["inventory:visible"],
                    ),
                ],
            )
        ],
        estimated_tokens=500,
        max_wall_seconds=5,
    )
    result = OrchestrationService(
        planner=lambda request: candidate,
        executor=lambda *args, **kwargs: _result(),
    ).execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    tool_citations = [
        citation.citation_id
        for citation in result.citations
        if citation.citation_id.startswith("tool:")
    ]
    assert tool_citations == [
        "tool:0:0:inventory_data_health:inventory_resources:0",
        "tool:0:1:inventory_data_health:inventory_resources:0",
    ]


def test_wall_clock_budget_stops_before_tool_io():
    ticks = iter([0.0, 6.0])
    calls: list[str] = []
    service = OrchestrationService(
        planner=lambda request: _candidate(),
        executor=lambda name, arguments, *, context, scope: calls.append(name),
        clock=lambda: next(ticks),
    )

    result = service.execute(
        _request(),
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )

    assert calls == []
    assert result.status == "partial"
    assert "orchestration wall-clock budget exhausted" in result.uncertainty


def test_widened_request_scope_causes_zero_calls():
    calls: list[str] = []
    request = _request().model_copy(
        update={"requested_scope": {"subscription": ["sub-a", "sub-b"]}}
    )
    service = OrchestrationService(
        executor=lambda name, arguments, *, context, scope: calls.append(name)
    )

    with pytest.raises(PolicyViolation, match="scope_widening"):
        service.execute(
            request,
            context=object(),
            principal_subject="operator-a",
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert calls == []


def _canonical_body(**overrides):
    body = {
        "contract_version": "1",
        "question": "Show inventory resources and data health.",
        "requested_scope": {"subscription": ["sub-a"]},
        "snapshot": {
            "version": "2",
            "page_kind": "inventory",
            "page_id": "inventory",
            "coverage": {
                "visible_count": 1,
                "total_count": 2,
                "complete": False,
            },
            "freshness": [
                {
                    "source": "inventory",
                    "observed_at": "2026-09-01T00:00:00Z",
                    "status": "partial",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "inventory:os:stable",
                    "source": "inventory/os_observations",
                    "status": "ok",
                    "observed_at": "2026-09-01T00:00:00Z",
                    "resource_id": "inventory://os/Windows%20Server%7C2019",
                    "data": {"machine_count": 1},
                }
            ],
        },
        "hint": {
            "specialist_id": INVENTORY_DATA_HEALTH_ID,
            "tool": "inventory_resources",
            "arguments": {},
        },
    }
    body.update(overrides)
    return body


def test_authenticated_canonical_route_preserves_governed_result(tmp_path):
    observed_scopes: list[dict[str, list[str]]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            observed_scopes.append(scope.to_dict())
            return {
                "resources": [
                    {
                        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/"
                        "Microsoft.Compute/virtualMachines/vm-1"
                    }
                ],
                "total": 1,
            }

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    assert client.post(
        "/api/v1/copilot/investigations",
        json=_canonical_body(),
    ).status_code == 401

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=_canonical_body(),
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert observed_scopes == [{"subscription": ["sub-a"]}]
    assert data["policy_status"] == "accepted"
    assert data["fallback_reason"] == ""
    assert data["coverage"] == {
        "visible_count": 1,
        "total_count": 2,
        "complete": False,
    }
    assert "visible subset is incomplete" in data["uncertainty"]
    assert {citation["citation_id"] for citation in data["citations"]} >= {
        "snapshot:coverage",
    }
    assert "inventory:os:stable" not in {
        citation["citation_id"] for citation in data["citations"]
    }
    assert data["thread_id"].startswith("thr-")
    assert data["mutation_authorized"] is False


def test_canonical_route_validates_hints_and_scope_before_tool_io(tmp_path):
    calls: list[dict[str, list[str]]] = []

    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            calls.append(scope.to_dict())
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)

    invalid_hint = _canonical_body(
        hint={
            "specialist_id": "remediation",
            "tool": "inventory_resources",
            "arguments": {},
        }
    )
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=invalid_hint,
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["data"]["policy_status"] == "fallback"
    assert response.json()["data"]["fallback_reason"].startswith("candidate_rejected:")
    assert response.json()["data"]["selected_specialists"] == [
        INVENTORY_DATA_HEALTH_ID
    ]
    assert calls == [{"subscription": ["sub-a"]}]

    widened = _canonical_body(
        requested_scope={"subscription": ["sub-a", "sub-b"]}
    )
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=widened,
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert calls == [{"subscription": ["sub-a"]}]


def test_canonical_route_rejects_browser_authority_assertions(tmp_path):
    context = _context(tmp_path, None)
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"]["authorized"] = True

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 400


def test_canonical_route_never_promotes_browser_observations_to_authority(
    tmp_path,
):
    class InventoryPort:
        def list_resources(self, scope, *, family, resource_type, limit):
            return {"resources": [], "total": 0}

    context = _context(tmp_path, None)
    context.inventory_read_port_provider = lambda: InventoryPort()
    client = TestClient(create_app(context), raise_server_exceptions=False)
    body = _canonical_body()
    body["snapshot"]["coverage"] = {
        "visible_count": 1,
        "total_count": 1,
        "complete": True,
    }
    body["snapshot"]["freshness"][0]["status"] = "fresh"
    body["snapshot"]["evidence"][0]["resource_id"] = (
        "/subscriptions/sub-b/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/untrusted"
    )

    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        json=body,
        headers=HEADERS,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["coverage"] == {
        "visible_count": 1,
        "total_count": 1,
        "complete": False,
    }
    assert "visible subset is incomplete" in data["uncertainty"]
    assert "inventory freshness is unavailable" in data["uncertainty"]
    assert "inventory:os:stable" not in {
        citation["citation_id"] for citation in data["citations"]
    }
