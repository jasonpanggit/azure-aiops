"""Native HTTP MCP transport over the governed Operations tool registry."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from operations.autonomous_investigation import ledger_store, run_context_investigation
from operations.mcp_server import MCPServer, MAX_MESSAGE_BYTES
from operations.page_context import PageSnapshot

from ..dependencies import Context, CurrentPrincipal, ReadScope
from ..errors import ApiError, ErrorCode

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])
_SERVER = MCPServer()


@router.post("", summary="Operations MCP Streamable HTTP endpoint")
async def mcp(
    request: Request,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> JSONResponse:
    raw = await request.body()
    correlation_id = getattr(request.state, "correlation_id", "") or uuid.uuid4().hex
    if len(raw) > MAX_MESSAGE_BYTES:
        return JSONResponse(
            status_code=413,
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "MCP message exceeds size limit"}},
        )
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON"}})
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "MCP request must be an object"}})
    response = _SERVER.handle(
        payload, context=context, principal=principal, scope=scope,
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=200, content=response)


class SnapshotRequest(BaseModel):
    snapshot: PageSnapshot


@router.post("/snapshots", summary="Submit and ledger an exact page snapshot")
def submit_snapshot(
    payload: SnapshotRequest,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    try:
        payload.snapshot.validate_effective_scope(scope)
    except ValueError as exc:
        raise ApiError(ErrorCode.FORBIDDEN, str(exc)) from exc
    ledger = run_context_investigation(
        payload.snapshot, context=context, scope=scope,
        principal_subject=principal.subject,
    )
    ledger["snapshot"] = payload.snapshot.model_dump(mode="json")
    ledger_store().add(ledger)
    return ledger


@router.get("/snapshots/{ledger_id}/replay", summary="Replay a submitted page snapshot ledger")
def replay_snapshot(
    ledger_id: str,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
) -> dict[str, Any]:
    ledger = ledger_store().get(ledger_id, principal.subject)
    if ledger is None or "snapshot" not in ledger:
        raise ApiError(ErrorCode.NOT_FOUND, "Snapshot ledger not found")
    # Replay is intentionally a byte-for-byte read of the recorded observation;
    # it never invokes providers or silently rehydrates current page state.
    return ledger
