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
    ]


def test_unknown_and_malformed_calls_are_protocol_errors(tmp_path):
    c = client(tmp_path)
    unknown = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "delete_everything", "arguments": {}}}, headers=auth())
    assert unknown.json()["error"]["code"] == -32602
    malformed = c.post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "traffic_flow", "arguments": {"source": "a"}}}, headers=auth())
    assert malformed.json()["error"]["code"] == -32602


def test_unauthenticated_request_is_rejected(tmp_path):
    assert client(tmp_path).post("/api/v1/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
