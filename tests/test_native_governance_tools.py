"""Native page evidence must use the same generation and scope as REST."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.errors import ApiError, ErrorCode
from api.governance_snapshot import (
    GovernanceSnapshot,
    finops_engine,
    identity_engine,
    spn_engine,
)
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.foundry_agent import AgentAnswer
from operations.maf_orchestrator import build_deterministic_fallback
from operations.mcp_server import (
    MCPServer,
    reviewed_tools_for_specialist,
    tool_definitions,
    validate_tool_arguments,
)
from operations.orchestration_contract import InvestigationRequest
from operations.specialist_manifest import load_specialist_manifest
from operations.tools import call_tool

TOOLS = ("identity_summary", "finops_summary", "governance_summary")
DIMENSIONS = (
    "business_service", "application", "environment", "subscription",
    "subscription_connection", "owner", "support_team", "region", "criticality",
)
OBSERVED = "2026-10-18T23:00:00Z"
TOKEN = "native-governance-reader-0123456789"


def _snapshot(*, assignments=True, finops=True, connections=True):
    entities = []
    registry = []
    for side in ("visible", "hidden"):
        scope_fields = dict.fromkeys(DIMENSIONS, side)
        if assignments:
            entities.append({
                "entity_type": "RoleAssignment",
                "payload_json": {
                    **scope_fields,
                    "principalId": f"{side}-principal",
                    "roleDefinitionName": "Owner",
                    "assignmentScope": f"/subscriptions/{side}",
                },
            })
        if finops:
            entities.append({
                "entity_type": "CostActual",
                "payload_json": {
                    **scope_fields,
                    "id": f"costactual://{side}/row",
                    "usageDate": "2026-10-18",
                    "cost": 123 if side == "visible" else 999,
                    "currency": "USD",
                },
            })
        if connections:
            registry.append({
                **scope_fields,
                "connection_id": side,
                "credential": {
                    "credential_id": f"{side}-credential",
                    "kind": "client_secret",
                    "secret_ref": f"never-prompt-{side}",
                },
            })
    return GovernanceSnapshot(
        entities, connections=registry, observed_at=OBSERVED,
    )


def _context(tmp_path, snapshot, *, scope=None, agent=None):
    principal = Principal(
        subject="reader@example.com",
        grants=(Grant("reader", scope or Scope()),),
    )
    return ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        authenticator=StaticTokenAuthenticator({TOKEN: principal}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        governance_generation_provider=lambda scope: snapshot,
        foundry_agent_provider=(lambda: agent) if agent else None,
        governance_agent_provider=(lambda: agent) if agent else None,
        executive_summary_agent_provider=(lambda: agent) if agent else None,
    )


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_native_tools_share_rest_projection_and_all_scope_dimensions(tmp_path, tool, dimension):
    snapshot = _snapshot()
    scope = Scope.from_mapping({dimension: ["visible"]})
    context = _context(tmp_path, snapshot)

    result = call_tool(tool, {}, context=context, scope=scope)

    expected = snapshot.scoped(scope)
    assert result.status == "ok"
    if tool in {"identity_summary", "governance_summary"}:
        assert result.data["identity"]["summary"] == identity_engine(expected).summary()
        assert result.data["identity"]["summary"]["assignment_count"] == 1
    if tool in {"finops_summary", "governance_summary"}:
        assert result.data["finops"]["summary"] == finops_engine(expected).summary()
        assert result.data["finops"]["summary"]["actual_spend"] == 123
    if tool == "governance_summary":
        assert result.data["service_principals"]["summary"] == spn_engine(expected).summary()
        assert result.data["service_principals"]["summary"]["credential_count"] == 1
    assert "hidden" not in json.dumps(result.to_dict())
    assert "never-prompt" not in json.dumps(result.to_dict())
    assert all(item.timestamp == OBSERVED for item in result.evidence)
    assert {item.source_table for item in result.evidence} == {"connection_generation_entities"}


@pytest.mark.parametrize("tool", TOOLS)
def test_native_tools_do_not_claim_missing_generation_as_empty(tmp_path, tool):
    snapshot = _snapshot()
    snapshot.generation_available = False
    context = _context(tmp_path, snapshot)

    result = call_tool(tool, {}, context=context, scope=Scope())

    assert result.status == "unavailable"
    assert result.data is None
    assert not result.evidence


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("error", [
    ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "generation unavailable"),
    OSError("storage unavailable"),
    ValueError("invalid generation"),
])
def test_native_provider_failure_is_never_fallback_success(tmp_path, tool, error, caplog):
    context = _context(tmp_path, _snapshot())

    def fail(scope):
        raise error

    context.governance_generation_provider = fail
    result = call_tool(tool, {}, context=context, scope=Scope())

    assert result.status == "unavailable"
    assert not result.evidence
    assert "tool_governance_snapshot_failed" in caplog.text


@pytest.mark.parametrize("tool", TOOLS)
def test_native_tools_report_successful_but_source_empty_read_honestly(tmp_path, tool):
    context = _context(tmp_path, _snapshot(assignments=False, finops=False, connections=False))

    result = call_tool(tool, {}, context=context, scope=Scope())

    assert result.status == "empty"
    assert result.data is None
    assert not result.evidence
    assert "synced" in result.warning


def test_native_governance_retains_unknown_identity_instead_of_zero(tmp_path):
    context = _context(tmp_path, _snapshot(assignments=False))
    result = call_tool("governance_summary", {}, context=context, scope=Scope())

    assert result.status == "ok"
    assert result.data["identity"] == {"status": "unavailable", "summary": None}
    assert "not a statement that no privileged access exists" in result.warning
    assert "does not establish policy compliance" in result.warning
    assert {item.source_engine for item in result.evidence} == {
        "intelligence.governance.FinOpsEngine",
        "intelligence.governance.SpnGovernanceEngine",
    }


def test_native_finops_retains_unknown_spend_not_zero(tmp_path):
    snapshot = GovernanceSnapshot([{
        "entity_type": "Resource",
        "payload_json": {"id": "/subscriptions/visible/resourceGroups/rg"},
    }], observed_at=OBSERVED)
    result = call_tool("finops_summary", {}, context=_context(tmp_path, snapshot), scope=Scope())

    assert result.status == "ok"
    summary = result.data["finops"]["summary"]
    assert "actual_spend" not in summary
    assert any(item["metric"] == "actual_spend" for item in summary["unavailable_metrics"])


def test_native_finops_discloses_currency_breakdown_bounds(tmp_path):
    snapshot = GovernanceSnapshot([
        {
            "entity_type": "CostActual",
            "payload_json": {
                "id": f"costactual://visible/{index}",
                "cost": 1,
                "currency": f"A{chr(65 + index // 26)}{chr(65 + index % 26)}",
            },
        }
        for index in range(30)
    ], observed_at=OBSERVED)
    result = call_tool("finops_summary", {}, context=_context(tmp_path, snapshot), scope=Scope())

    assert result.status == "ok"
    summary = result.data["finops"]["summary"]
    assert summary["actual_spend"] is None
    assert len(summary["actual_spend_currency_totals"]) == 25
    assert "showing 25 of 30" in result.warning


def test_native_identity_bounds_principal_details_without_truncating_totals(tmp_path):
    snapshot = GovernanceSnapshot([
        {
            "entity_type": "RoleAssignment",
            "payload_json": {
                "principalId": f"principal-{index}",
                "assignmentScope": "/subscriptions/visible",
            },
        }
        for index in range(30)
    ], observed_at=OBSERVED)
    result = call_tool("identity_summary", {}, context=_context(tmp_path, snapshot), scope=Scope())

    assert result.status == "ok"
    assert result.data["identity"]["summary"]["principal_count"] == 30
    assert len(result.data["identity"]["principals"]) == 25
    assert "identity.principals showing 25 of 30" in result.warning


@pytest.mark.parametrize(("consumer", "denied"), [
    (None, True), ("finops", True), ("ontology_curator", True),
    ("identity_access", False),
])
def test_native_mcp_tools_do_not_expand_unrelated_consumer_grants(tmp_path, consumer, denied):
    context = _context(tmp_path, _snapshot())
    response = MCPServer().handle(
        {
            "jsonrpc": "2.0", "id": "native",
            "method": "tools/call",
            "params": {"name": "identity_summary", "arguments": {}},
        },
        context=context,
        principal=Principal(subject="reader", grants=(Grant("reader"),)),
        scope=Scope.from_mapping({"subscription": ["visible"]}),
        correlation_id="native-test",
        specialist_id=consumer,
    )
    result = response["result"]
    assert bool(result.get("isError")) == denied
    if not denied:
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "ok"
        assert payload["data"]["identity"]["summary"]["assignment_count"] == 1


@pytest.mark.parametrize(("page", "specialist", "tool"), [
    ("governance", "governance", "governance_summary"),
    ("identity", "identity_access", "identity_summary"),
    ("finops", "finops", "finops_summary"),
])
def test_native_page_plans_and_mcp_grants_are_exact(page, specialist, tool):
    manifest = load_specialist_manifest()
    assert manifest.require(specialist).operations_tools_for_page(page)[0] == tool
    assert tool in reviewed_tools_for_specialist(specialist)
    assert validate_tool_arguments(tool, {}) == ({}, [])
    schema = next(item["inputSchema"] for item in tool_definitions() if item["name"] == tool)
    assert schema == {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    with pytest.raises(ValueError):
        validate_tool_arguments(tool, {"subscription": "hidden"})

    request = InvestigationRequest.model_validate({
        "question": "Summarize the current evidence",
        "requested_scope": {},
        "snapshot": {
            "page_kind": page, "page_id": page,
            "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
        },
    })
    plan = build_deterministic_fallback(request, manifest)
    assert [(step.specialist_id, call.tool) for step in plan.steps for call in step.tool_calls] == [
        (specialist, tool),
    ]


@pytest.mark.parametrize("tool", TOOLS)
def test_authenticated_native_investigation_narrows_before_model_context(tmp_path, tool):
    class Agent:
        def __init__(self):
            self.contexts = []

        def answer(self, *, question, context):
            self.contexts.append(context)
            return AgentAnswer(text="Observed native evidence.", agent_name="native-test")

    agent = Agent()
    context = _context(
        tmp_path, _snapshot(),
        scope=Scope.from_mapping({"subscription": ["visible"]}),
        agent=agent,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/copilot/investigate",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"question": "Summarize current evidence", "tool": tool, "tool_arguments": {}},
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["answer"]["text"] == "Observed native evidence."
    assert body["mutation_authorized"] is False
    assert body["citations"]
    assert agent.contexts[0]["facts"][0]["tool"] == tool
    assert "hidden" not in json.dumps(agent.contexts)
    assert "never-prompt" not in json.dumps(agent.contexts)


@pytest.mark.parametrize(("page", "tool"), [
    ("governance", "governance_summary"),
    ("identity", "identity_summary"),
    ("finops", "finops_summary"),
])
def test_authenticated_page_insights_use_native_evidence_without_hint(tmp_path, monkeypatch, page, tool):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")

    class Agent:
        def answer(self, *, question, context):
            assert context["facts"][0]["tool"] == tool
            assert "hidden" not in json.dumps(context)
            return AgentAnswer(
                text="Observed native page evidence.", agent_name="native-test",
                model="test-model", agent_version="1",
            )

    context = _context(
        tmp_path, _snapshot(), scope=Scope.from_mapping({"subscription": ["visible"]}),
        agent=Agent(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/copilot/investigations",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "question": "Give me a concise executive insight for this page.",
            "requested_scope": {"subscription": ["visible"]},
            "snapshot": {
                "page_kind": page, "page_id": page,
                "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    assert body["selected_tools"] == [tool]
    assert body["synthesis"]["compatibility_answer"]["text"] == "Observed native page evidence."
    assert body["synthesis"]["compatibility_answer"]["model"] == "test-model"
    assert body["citations"]
    assert body["mutation_authorized"] is False


@pytest.mark.parametrize(("page", "tool"), [
    ("governance", "governance_summary"),
    ("identity", "identity_summary"),
    ("finops", "finops_summary"),
])
@pytest.mark.parametrize("selection", ["observation", "selected_row", "selected_entity"])
def test_populated_native_page_observations_are_not_implicit_selections(
    tmp_path, monkeypatch, page, tool, selection,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")

    class Agent:
        def answer(self, *, question, context):
            assert "browser-spend-fiction" not in json.dumps(context)
            return AgentAnswer(
                text="Observed native evidence.", agent_name="native-test",
                model="test-model", agent_version="1",
            )

    context = _context(
        tmp_path, _snapshot(), scope=Scope.from_mapping({"subscription": ["visible"]}),
        agent=Agent(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    resource_id = "/subscriptions/visible/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    entity = {"type": "azure", "resource_id": resource_id}
    response = client.post(
        "/api/v1/copilot/investigations",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "question": "Give me a concise executive insight for this page.",
            "requested_scope": {"subscription": ["visible"]},
            "snapshot": {
                "page_kind": page, "page_id": page,
                "coverage": {"visible_count": 1, "total_count": 1, "complete": True},
                "selected_entities": [entity] if selection == "selected_entity" else [],
                "evidence": [{
                    "evidence_id": "finops:waste:vm", "source": "finops/waste",
                    "resource_id": resource_id, "entity": entity,
                    "direct": True, "selected": selection == "selected_row",
                    "data": {"value": "browser-spend-fiction"},
                }],
            },
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()["data"]
    if selection == "observation":
        assert body["selected_tools"] == [tool]
        assert body["synthesis"]["compatibility_answer"]["model"] == "test-model"
    else:
        assert tool not in body["selected_tools"]
    assert body["mutation_authorized"] is False
