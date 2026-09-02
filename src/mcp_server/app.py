"""FastAPI MCP server for centralized Azure tool execution with per-subscription SPN management."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from onboarding.credentials import KeyVaultSecretProvider, SecretNotFoundError
from onboarding.registry import ConnectionRegistry

logger = logging.getLogger(__name__)
UPSTREAM_MCP_URL_ENV = "AIOPS_OPERATIONS_MCP_URL"
GATEWAY_ASSERTION_ENV = "AIOPS_GATEWAY_ASSERTION"
_RELAY_HEADERS = (
    "x-correlation-id",
    "x-ms-client-principal-name",
    "x-ms-client-principal-roles",
)

app = FastAPI(
    title="Azure MCP Server",
    description="Centralized MCP server for specialist agents with per-subscription SPN management",
    version="1.0.0",
)


@dataclass
class MpcServerConfig:
    """Configuration for MCP server startup."""

    aiops_home: str
    akv_name: str
    subscription_ids: list[str] | None = None


class MCPToolRequest(BaseModel):
    """Request to execute an MCP tool."""

    subscription_id: str = Field(..., description="Azure subscription ID")
    tool_name: str = Field(..., description="Name of the MCP tool to execute")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class MCPToolResponse(BaseModel):
    """Response from executing an MCP tool."""

    success: bool
    result: Any = None
    error: str | None = None


class SubscriptionNotOnboardedError(Exception):
    """Raised when a subscription is not in the connection registry."""



class MCPServerState:
    """Runtime state for the MCP server."""

    def __init__(self, config: MpcServerConfig):
        self.config = config
        self.registry = ConnectionRegistry(config.aiops_home)
        # KeyVaultSecretProvider uses the vault name from the secret_ref
        # (e.g., akv://vault-name/secrets/...), so we don't pass it here
        self.secret_provider = KeyVaultSecretProvider()
        self._load_connections()

    def _load_connections(self) -> None:
        """Load subscription connections from registry."""
        try:
            connections = self.registry.load()
            self.connections = connections
            logger.info(f"Loaded {len(connections)} subscription connections from registry")
            for conn_id, conn in connections.items():
                logger.debug(
                    f"  {conn_id}: subscription={conn.subscription_id}, "
                    f"credential_ref={conn.credential.secret_ref}"
                )
        except Exception as e:
            logger.error(f"Failed to load subscription connections: {e}")
            raise

    def resolve_credential(self, subscription_id: str) -> str:
        """Resolve the SPN credential for a subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            Resolved SPN credential (JSON string or raw secret value)

        Raises:
            SubscriptionNotOnboardedError: If subscription not in registry
            SecretNotFoundError: If credential cannot be resolved from AKV
        """
        # Find connection by subscription_id
        connection = None
        for conn in self.connections.values():
            if conn.subscription_id.casefold() == subscription_id.casefold():
                connection = conn
                break

        if not connection:
            raise SubscriptionNotOnboardedError(
                f"Subscription '{subscription_id}' is not onboarded. "
                f"Available subscriptions: {', '.join(c.subscription_id for c in self.connections.values())}"
            )

        # Resolve secret_ref via KeyVaultSecretProvider
        try:
            secret_ref = connection.credential.secret_ref
            if not self.secret_provider.supports(secret_ref):
                raise SecretNotFoundError(
                    f"Secret provider does not support reference type: {secret_ref}"
                )
            credential = self.secret_provider.resolve(secret_ref)
            return credential
        except SecretNotFoundError as e:
            logger.error(f"Failed to resolve credential for {subscription_id}: {e}")
            raise


# Global state (initialized on startup)
_state: MCPServerState | None = None


def get_state() -> MCPServerState:
    """Get the global MCP server state."""
    if _state is None:
        raise RuntimeError("MCP server state not initialized")
    return _state


def init_state(config: MpcServerConfig) -> None:
    """Initialize global MCP server state."""
    global _state
    _state = MCPServerState(config)


@app.on_event("startup")
async def startup() -> None:
    """Initialize server on startup."""
    config = MpcServerConfig(
        aiops_home=os.getenv("AIOPS_HOME", "/app/data"),
        akv_name=os.getenv("AIOPS_AKV_NAME", "aiopsdevcpkh"),
        subscription_ids=os.getenv("AIOPS_SUBSCRIPTION_IDS", "").split(",")
        if os.getenv("AIOPS_SUBSCRIPTION_IDS")
        else None,
    )
    logger.info(f"Initializing MCP server with config: {config}")
    init_state(config)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    try:
        state = get_state()
        return {
            "status": "healthy",
            "connections_loaded": len(state.connections),
            "vault": state.config.akv_name,
        }
    except Exception as e:  # noqa: BLE001 - health endpoint must report any failure
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")


@app.post("/tool")
async def execute_tool(request: MCPToolRequest) -> MCPToolResponse:
    """Execute an MCP tool for a subscription.

    This endpoint is typically called by APIM proxy, which forwards requests
    from specialist Foundry agents.

    Args:
        request: Tool request with subscription_id, tool_name, and arguments

    Returns:
        MCPToolResponse with success/error result

    Raises:
        HTTPException: On validation or execution failures
    """
    state = get_state()

    # Validate subscription and resolve credential
    try:
        state.resolve_credential(request.subscription_id)
    except SubscriptionNotOnboardedError as e:
        logger.warning(f"Subscription not onboarded: {e}")
        raise HTTPException(
            status_code=400,
            detail=str(e),
        ) from e
    except SecretNotFoundError as e:
        logger.error(f"Failed to resolve credential: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Unable to resolve credential for subscription: {e}",
        ) from e

    # TODO: Dispatch tool call to azure-mcp-server library with resolved credential
    # For now, return a placeholder that shows the contract works
    logger.info(
        f"Tool request: subscription={request.subscription_id}, "
        f"tool={request.tool_name}, args={request.arguments}"
    )

    try:
        # Placeholder: actual tool dispatch will be implemented
        result = {
            "tool_name": request.tool_name,
            "subscription_id": request.subscription_id,
            "status": "dispatch_not_yet_implemented",
        }
        return MCPToolResponse(success=True, result=result)
    except Exception as e:  # noqa: BLE001 - tool dispatch must report any failure
        return MCPToolResponse(success=False, error=str(e))


@app.get("/subscriptions")
async def list_subscriptions() -> dict[str, Any]:
    """List onboarded subscriptions and their connection details.

    Redacts secret_ref for security (only shows vault name, not secret name).
    """
    state = get_state()
    subscriptions = []
    for conn_id, conn in state.connections.items():
        subscriptions.append(
            {
                "connection_id": conn_id,
                "subscription_id": conn.subscription_id,
                "tenant_id": conn.tenant_id,
                "vault_name": state.config.akv_name,
                "is_active": conn.is_active,
            }
        )
    return {"count": len(subscriptions), "subscriptions": subscriptions}


def _upstream_headers(request: Request) -> dict[str, str]:
    """Build the bounded identity context sent to the governed MCP executor."""
    headers = {
        name: value
        for name in _RELAY_HEADERS
        if (value := request.headers.get(name))
    }
    headers["X-AIOps-Gateway-Assertion"] = os.environ[GATEWAY_ASSERTION_ENV]
    headers["Content-Type"] = "application/json"
    return headers


async def _post_upstream(
    url: str, body: bytes, headers: dict[str, str]
) -> httpx.Response:
    """Send one MCP request to the governed Operations MCP executor."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(url, content=body, headers=headers)


async def _relay_mcp(request: Request) -> Response:
    """Relay APIM-authenticated MCP JSON-RPC to the governed tool executor."""
    expected_assertion = os.environ.get(GATEWAY_ASSERTION_ENV, "")
    inbound_assertion = request.headers.get("x-aiops-gateway-assertion", "")
    if not expected_assertion or not secrets.compare_digest(
        inbound_assertion, expected_assertion
    ):
        logger.warning("Rejected MCP request with invalid gateway assertion")
        return JSONResponse(
            status_code=401,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "Invalid gateway assertion"},
            },
        )

    upstream_url = os.getenv(UPSTREAM_MCP_URL_ENV, "").strip()
    if not upstream_url:
        logger.error("%s is not configured", UPSTREAM_MCP_URL_ENV)
        return JSONResponse(
            status_code=503,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32003, "message": "MCP upstream is unavailable"},
            },
        )

    try:
        upstream_response = await _post_upstream(
            upstream_url, await request.body(), _upstream_headers(request)
        )
    except httpx.RequestError as exc:
        logger.error("MCP upstream request failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32003, "message": "MCP upstream is unavailable"},
            },
        )

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get("content-type", "application/json"),
    )


@app.post("/")
@app.post("/mcp")
async def mcp_handler(request: Request) -> Response:
    """Serve the native MCP endpoint consumed by APIM and Foundry agents."""
    return await _relay_mcp(request)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
