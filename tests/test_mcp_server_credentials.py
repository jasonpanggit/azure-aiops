"""Unit tests for MCP server credential resolution and registry lookup."""

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from mcp_server.app import (
    MCPServerState,
    MpcServerConfig,
    SubscriptionNotOnboardedError,
    app,
)
from onboarding.credentials import SecretNotFoundError
from onboarding.registry import ConnectionNotFoundError
from ontology.subscription_connection import SubscriptionConnection, CredentialReference


@pytest.fixture
def mock_registry():
    """Create a mock ConnectionRegistry with test connections."""
    mock = MagicMock()
    
    # Create test subscription connections
    conn1 = SubscriptionConnection(
        connection_id="demo-sub",
        name="Demo Subscription",
        subscription_id="12345678-1234-1234-1234-123456789012",
        tenant_id="87654321-4321-4321-4321-210987654321",
        credential=CredentialReference(
            credential_id="demo-sub-cred",
            secret_ref="akv://aiopsdevcpkh/secrets/demo-sub-cred"
        ),
        is_active=True,
    )
    
    conn2 = SubscriptionConnection(
        connection_id="prod-sub",
        name="Production Subscription",
        subscription_id="87654321-4321-4321-4321-210987654321",
        tenant_id="87654321-4321-4321-4321-210987654321",
        credential=CredentialReference(
            credential_id="prod-sub-cred",
            secret_ref="akv://aiopsdevcpkh/secrets/prod-sub-cred"
        ),
        is_active=True,
    )
    
    mock.load.return_value = {
        "demo-sub": conn1,
        "prod-sub": conn2,
    }
    
    return mock


@pytest.fixture
def mock_secret_provider():
    """Create a mock SecretProvider for credential resolution."""
    mock = MagicMock()
    mock.name = "keyvault"
    
    def supports(secret_ref):
        return secret_ref and secret_ref.startswith("akv://")
    
    def resolve(secret_ref):
        # Return a mock SPN credential
        if "demo-sub" in secret_ref:
            return json.dumps({
                "clientId": "demo-client-id",
                "clientSecret": "demo-secret",
                "subscriptionId": "12345678-1234-1234-1234-123456789012",
            })
        elif "prod-sub" in secret_ref:
            return json.dumps({
                "clientId": "prod-client-id",
                "clientSecret": "prod-secret",
                "subscriptionId": "87654321-4321-4321-4321-210987654321",
            })
        else:
            raise SecretNotFoundError(f"Secret not found: {secret_ref}")
    
    mock.supports.side_effect = supports
    mock.resolve.side_effect = resolve
    
    return mock


class TestMCPServerStateCredentialResolution:
    """Test credential resolution from AKV."""

    def test_resolve_credential_success(self, mock_registry, mock_secret_provider):
        """Test successful credential resolution for onboarded subscription."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )
        
        state = MCPServerState(config)
        state.registry = mock_registry
        state.secret_provider = mock_secret_provider
        state._load_connections()
        
        # Resolve credential for demo subscription
        cred = state.resolve_credential("12345678-1234-1234-1234-123456789012")
        
        # Should return SPN credential as JSON string
        cred_dict = json.loads(cred)
        assert cred_dict["clientId"] == "demo-client-id"
        assert cred_dict["subscriptionId"] == "12345678-1234-1234-1234-123456789012"

    def test_resolve_credential_subscription_not_found(self, mock_registry, mock_secret_provider):
        """Test error when subscription is not onboarded."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )
        
        state = MCPServerState(config)
        state.registry = mock_registry
        state.secret_provider = mock_secret_provider
        state._load_connections()
        
        # Try to resolve credential for non-existent subscription
        with pytest.raises(SubscriptionNotOnboardedError) as exc_info:
            state.resolve_credential("99999999-9999-9999-9999-999999999999")
        
        assert "not onboarded" in str(exc_info.value)

    def test_resolve_credential_secret_resolution_fails(self, mock_registry, mock_secret_provider):
        """Test error when AKV resolution fails."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )
        
        state = MCPServerState(config)
        state.registry = mock_registry
        
        # Mock secret provider that fails
        failing_provider = MagicMock()
        failing_provider.supports.return_value = True
        failing_provider.resolve.side_effect = SecretNotFoundError("Vault access denied")
        state.secret_provider = failing_provider
        state._load_connections()
        
        # Try to resolve credential
        with pytest.raises(SecretNotFoundError):
            state.resolve_credential("12345678-1234-1234-1234-123456789012")

    def test_resolve_credential_case_insensitive_lookup(self, mock_registry, mock_secret_provider):
        """Test that subscription_id lookup is case-insensitive."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )
        
        state = MCPServerState(config)
        state.registry = mock_registry
        state.secret_provider = mock_secret_provider
        state._load_connections()
        
        # Look up with uppercase variant
        cred = state.resolve_credential("12345678-1234-1234-1234-123456789012".upper())
        cred_dict = json.loads(cred)
        assert cred_dict["clientId"] == "demo-client-id"


class TestMCPServerStateConnectionLoading:
    """Test connection registry loading."""

    def test_load_connections_success(self, mock_registry):
        """Test successful loading of connections from registry."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )

        state = MCPServerState(config)
        state.registry = mock_registry
        state._load_connections()

        assert len(state.connections) == 2
        assert "demo-sub" in state.connections
        assert "prod-sub" in state.connections

    def test_load_connections_empty_registry(self):
        """Test loading when registry is empty."""
        config = MpcServerConfig(
            aiops_home="/tmp/test",
            akv_name="aiopsdevcpkh",
        )

        mock_registry = MagicMock()
        mock_registry.load.return_value = {}

        state = MCPServerState(config)
        state.registry = mock_registry
        state._load_connections()

        assert len(state.connections) == 0

    def test_health_endpoint_returns_numeric_connection_count(self, mock_registry):
        """Health endpoint should return a JSON count, not a string-only payload."""
        state = MCPServerState(MpcServerConfig(aiops_home="/tmp/test", akv_name="aiopsdevcpkh"))
        state.registry = mock_registry
        state._load_connections()

        import mcp_server.app as mcp_app
        mcp_app._state = state
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["vault"] == "aiopsdevcpkh"
        assert isinstance(body["connections_loaded"], int)
        assert body["connections_loaded"] == 2

    def test_native_mcp_endpoint_relays_only_gateway_identity_context(self, monkeypatch):
        """Native MCP traffic must reach the governed executor through the ACA relay."""
        import mcp_server.app as mcp_app

        upstream = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": "tools", "result": {"tools": []}},
            )
        )
        monkeypatch.setenv("AIOPS_OPERATIONS_MCP_URL", "https://api.test/api/v1/mcp")
        monkeypatch.setenv("AIOPS_GATEWAY_ASSERTION", "test-gateway-assertion")
        monkeypatch.setattr(mcp_app, "_post_upstream", upstream)

        response = TestClient(app).post(
            "/",
            json={"jsonrpc": "2.0", "id": "tools", "method": "tools/list"},
            headers={
                "Authorization": "Bearer caller-token-must-not-forward",
                "X-Correlation-ID": "relay-test",
                "X-MS-Client-Principal-Name": "foundry-project",
                "X-MS-Client-Principal-Roles": "reader",
                "X-AIOps-Scope": "caller-controlled",
                "X-AIOps-Gateway-Assertion": "test-gateway-assertion",
            },
        )

        assert response.status_code == 200
        assert response.json()["result"] == {"tools": []}
        args, kwargs = upstream.await_args
        headers = args[2] if len(args) > 2 else kwargs.get("headers")
        assert headers == {
            "x-correlation-id": "relay-test",
            "x-ms-client-principal-name": "foundry-project",
            "x-ms-client-principal-roles": "reader",
            "X-AIOps-Gateway-Assertion": "test-gateway-assertion",
            "Content-Type": "application/json",
        }
