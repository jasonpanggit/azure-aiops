import json

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService

TOKEN = "mcp-test-token-0123456789"
SUB = "11111111-1111-1111-1111-111111111111"


def client(tmp_path):
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "registry"),
        authenticator=StaticTokenAuthenticator({
            TOKEN: Principal("mcp-user", grants=(Grant("reader", Scope.from_mapping({"subscription": [SUB]})),))
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
    ]


def test_unknown_tool_is_an_error(tmp_path):
    """An unknown tool is a genuine caller mistake and stays isError."""
    c = client(tmp_path)
    unknown = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "delete_everything", "arguments": {}}}, headers=auth())
    assert unknown.json()["result"]["isError"] is True


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
