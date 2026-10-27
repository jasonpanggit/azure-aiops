import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.specialist_manifest import load_specialist_manifest

TOKEN = "mcp-test-token-0123456789"
SUB = "11111111-1111-1111-1111-111111111111"


def client(tmp_path, *, subject="mcp-user", specialist_id=""):
    grant = Grant.from_mapping(
        {
            "role": "reader",
            "scope": {"subscription": [SUB]},
            "mcp_specialist_id": specialist_id,
        }
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "registry"),
        authenticator=StaticTokenAuthenticator({
            TOKEN: Principal(subject, grants=(grant,))
        }),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def test_initialize_and_exact_read_only_catalog(tmp_path):
    response = client(tmp_path).post(
        "/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26"}}, headers=auth())
    assert response.json()["result"]["protocolVersion"] == "2025-03-26"
    listed = client(tmp_path).post(
        "/api/v1/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=auth()
    ).json()["result"]["tools"]
    assert [tool["name"] for tool in listed] == [
        "network_topology", "hub_dependents", "traffic_flow", "firewall_nsg_gaps",
        "business_service_context", "application_context", "impact_context",
        "fabric_iq_relationships", "fabric_iq_topology", "fabric_iq_policy_context",
        "cve_exposure", "cve_detail", "cve_attack_path",
        "defender_alerts", "defender_attack_paths", "defender_secure_score",
        "incidents", "defender_remediation_cases", "remediation_business_decision",
        "remediation_plans", "remediation_opportunities",
        "inventory_resources", "kb_detail", "patch_priorities", "risk_context", "search",
    ]
    manifest = load_specialist_manifest()
    specialist_union = {
        tool
        for grants in manifest.operations_mcp_grants().values()
        for tool in grants
    }
    assert {tool["name"] for tool in listed} == set(manifest.legacy_operations_mcp_tools)
    assert specialist_union - {tool["name"] for tool in listed} == {
        "governance_summary", "identity_summary", "finops_summary",
    }
    assert all("azure_mcp" not in json.dumps(tool).casefold() for tool in listed)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("inventory_resources", {}),
        ("kb_detail", {"kb_id": "KB5123099"}),
        ("patch_priorities", {}),
        ("risk_context", {"subject": "/subscriptions/example/resourceGroups/rg"}),
        ("search", {"query": "recent configuration changes"}),
    ],
)
def test_generic_catalog_accepts_reviewed_read_only_calls(tmp_path, tool, arguments):
    response = client(tmp_path).post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": tool,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        headers=auth(),
    )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False


def test_specialist_catalogs_remain_exactly_bounded(tmp_path):
    manifest = load_specialist_manifest()

    for specialist in manifest.specialists:
        listed = client(
            tmp_path,
            subject=f"{specialist.id}-subject",
            specialist_id=specialist.id,
        ).post(
            "/api/v1/mcp",
            json={"jsonrpc": "2.0", "id": specialist.id, "method": "tools/list"},
            headers=auth(),
        ).json()["result"]["tools"]

        assert tuple(tool["name"] for tool in listed) == specialist.operations_mcp_tools
        assert specialist.azure_mcp_tools == ()


@pytest.mark.parametrize(
    ("specialist_id", "tool"),
    [
        ("finops", "finops_summary"),
        ("governance", "governance_summary"),
        ("identity_access", "identity_summary"),
    ],
)
@pytest.mark.parametrize("caller_specialist", ["", "network"])
def test_summary_tools_reject_generic_or_foreign_callers_before_dispatch(
    tmp_path, monkeypatch, specialist_id, tool, caller_specialist,
):
    from operations import tools

    dispatched = []
    monkeypatch.setattr(tools, "call_tool", lambda *args, **kwargs: dispatched.append(args))
    c = client(tmp_path, specialist_id=caller_specialist)
    listed = c.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"specialist_id": specialist_id},
        },
        headers=auth(),
    )
    assert listed.status_code == 200
    assert tool not in {entry["name"] for entry in listed.json()["result"]["tools"]}

    response = c.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": tool,
                "specialist_id": specialist_id,
                "arguments": {},
            },
        },
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    assert dispatched == []


@pytest.mark.parametrize(
    ("specialist_id", "tool"),
    [
        ("finops", "finops_summary"),
        ("governance", "governance_summary"),
        ("identity_access", "identity_summary"),
    ],
)
def test_summary_tools_dispatch_only_for_trusted_specialist_grant(
    tmp_path, monkeypatch, specialist_id, tool,
):
    from operations import tools

    dispatched = []

    def call_tool(name, arguments, **kwargs):
        dispatched.append((name, kwargs["principal"].mcp_specialist_id()))
        return tools.ToolResult(status="empty")

    monkeypatch.setattr(tools, "call_tool", call_tool)
    response = client(tmp_path, specialist_id=specialist_id).post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        },
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    assert dispatched == [(tool, specialist_id)]


def test_unknown_tool_is_an_error(tmp_path):
    """An unknown tool is a genuine caller mistake and stays isError."""
    c = client(tmp_path)
    unknown = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "delete_everything", "arguments": {}}}, headers=auth())
    assert unknown.json()["result"]["isError"] is True


def test_inventory_specialist_gets_only_its_exact_manifest_grant(tmp_path):
    c = client(
        tmp_path,
        subject="11111111-2222-3333-4444-555555555555",
        specialist_id="inventory_data_health",
    )
    listed = c.post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=auth(),
    ).json()["result"]["tools"]
    assert [tool["name"] for tool in listed] == ["inventory_resources"]

    denied = c.post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "network_topology", "arguments": {}},
        },
        headers=auth(),
    )
    assert denied.json()["result"]["isError"] is True


def test_ontology_curator_gets_exact_read_only_catalog_with_strict_schemas(tmp_path):
    listed = client(
        tmp_path,
        subject="curator-service",
        specialist_id="ontology_curator",
    ).post(
        "/api/v1/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=auth(),
    ).json()["result"]["tools"]

    assert [tool["name"] for tool in listed] == [
        "list_changed_entities",
        "get_entity_evidence",
        "get_ontology_vocabulary",
        "search_relationship_history",
    ]
    for tool in listed:
        assert tool["inputSchema"]["additionalProperties"] is False
        assert "scope" not in tool["inputSchema"]["properties"]


def test_request_body_cannot_self_bind_noninteractive_consumer_grant(tmp_path):
    denied = client(tmp_path).post(
        "/api/v1/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "list_changed_entities",
                "arguments": {},
                "specialist_id": "ontology_curator",
            },
        },
        headers=auth(),
    )
    assert denied.json()["result"]["isError"] is True


def test_a_missing_required_argument_is_empty_not_an_error(tmp_path):
    """A missing argument must not abort the run.

    This assertion was inverted deliberately. Foundry aborts the entire
    response with HTTP 400 when any tool result carries isError=true, so
    reporting a missing argument as an error meant one speculative call
    destroyed the whole investigation: asked "what is the root cause of the
    latest incident?", the governance specialist calls
    business_service_context with no service name -- there is none in the
    question -- and the operator saw "Foundry narration unavailable" instead
    of an answer. Reproduced directly against the Responses API.

    The tool still never executes without its arguments; it reports that it
    had nothing to look up, so the model can move on to the tools that did
    return evidence.
    """
    c = client(tmp_path)
    response = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "traffic_flow", "arguments": {"source": "a"}}}, headers=auth())
    result = response.json()["result"]

    assert result["isError"] is False, "an isError result aborts the whole Foundry run"
    payload = json.loads(result["content"][0]["text"])
    assert payload["status"] == "empty"
    assert payload["missing_arguments"] == ["destination"]
    assert "destination" in payload["detail"]


def test_malformed_argument_types_are_still_an_error(tmp_path):
    """Only *absent* arguments are tolerated; bad ones remain errors."""
    c = client(tmp_path)
    response = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "traffic_flow", "arguments": {"source": {"not": "a string"},
                                                          "destination": "b"}}}, headers=auth())
    assert response.json()["result"]["isError"] is True


def test_unauthenticated_request_is_rejected(tmp_path):
    assert client(tmp_path).post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
