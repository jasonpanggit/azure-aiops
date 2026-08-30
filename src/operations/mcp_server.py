"""Bounded, read-only Model Context Protocol adapter for Operations.

This module deliberately owns protocol concerns only.  Authentication and
effective scope are supplied by the API route; execution remains in the
existing governed ``call_tool`` registry.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

LOGGER = logging.getLogger("aiops.mcp")
MCP_VERSION = "2025-06-18"
MAX_MESSAGE_BYTES = 128 * 1024
MAX_ARGUMENT_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MAX_CALLS = 100_000  # Coarse per-process circuit breaker, not a per-caller
# limiter (real per-caller throttling lives in APIM's rate-limit-by-key /
# quota-by-key policies). This only exists to bound a single container's
# lifetime tool-call volume before a restart; keep it high enough that no
# legitimate multi-tool-call agent turn can ever exhaust it.
MAX_TOOL_NAME = 64

REVIEWED_TOOLS = (
    "network_topology",
    "hub_dependents",
    "traffic_flow",
    "firewall_nsg_gaps",
    "business_service_context",
    "application_context",
    "impact_context",
    "fabric_iq_relationships",
    "fabric_iq_topology",
    "fabric_iq_policy_context",
    "cve_exposure",
    "cve_detail",
    "cve_attack_path",
    "incidents",
    "remediation_plans",
    "remediation_opportunities",
)


class MCPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("jsonrpc")
    @classmethod
    def jsonrpc_version(cls, value: str) -> str:
        if value != "2.0":
            raise ValueError("jsonrpc must be 2.0")
        return value


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=256)
    subject: str | None = Field(default=None, min_length=1, max_length=512)
    vnet_id: str | None = Field(default=None, min_length=1, max_length=512)
    source: str | None = Field(default=None, min_length=1, max_length=512)
    destination: str | None = Field(default=None, min_length=1, max_length=512)
    port: int | None = Field(default=None, ge=1, le=65535)
    protocol: str | None = Field(default=None, min_length=1, max_length=16)
    business_service: str | None = Field(default=None, min_length=1, max_length=512)
    cve_id: str | None = Field(default=None, min_length=1, max_length=64)
    incident_id: str | None = Field(default=None, min_length=1, max_length=256)


_REQUIRED: dict[str, tuple[str, ...]] = {
    "hub_dependents": ("vnet_id",),
    "traffic_flow": ("source", "destination"),
    "business_service_context": ("name",),
    "application_context": ("name",),
    "impact_context": ("subject",),
    "fabric_iq_relationships": ("subject",),
    "fabric_iq_topology": ("subject",),
    "fabric_iq_policy_context": ("subject",),
    "cve_detail": ("cve_id",),
    "cve_attack_path": ("cve_id",),
}

# Optional (non-required) arguments per tool, kept separate from _REQUIRED so
# a tool can accept a field without forcing the caller to supply it.
_OPTIONAL: dict[str, tuple[str, ...]] = {
    "cve_exposure": ("business_service",),
    "incidents": ("incident_id",),
}


def _schema(name: str) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field in _REQUIRED.get(name, ()) + _OPTIONAL.get(name, ()):
        properties[field] = {"type": "string", "minLength": 1, "maxLength": 512}
    if name == "traffic_flow":
        properties.update({
            "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            "protocol": {"type": "string", "minLength": 1, "maxLength": 16},
        })
    return {
        "type": "object",
        "properties": properties,
        "required": list(_REQUIRED.get(name, ())),
        "additionalProperties": False,
    }


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": f"Governed read-only Operations tool: {name}.",
            "inputSchema": _schema(name),
        }
        for name in REVIEWED_TOOLS
    ]


def _error(code: int, message: str, request_id: Any = None) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _safe_size(value: Any, maximum: int) -> bool:
    try:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode())
    except (TypeError, ValueError):
        return False


class MCPServer:
    """Per-process bounded dispatcher.  It contains no provider access."""

    def __init__(self) -> None:
        self.calls = 0
        self.audit_entries: list[dict[str, Any]] = []

    def handle(
        self,
        payload: Mapping[str, Any],
        *,
        context: Any,
        principal: Any,
        scope: Any,
        correlation_id: str,
    ) -> dict[str, Any]:
        request_id = payload.get("id")
        if not _safe_size(payload, MAX_MESSAGE_BYTES):
            return _error(-32600, "MCP message exceeds size limit", request_id)
        try:
            request = MCPRequest.model_validate(payload)
        except ValidationError:
            return _error(-32600, "Invalid MCP request", request_id)
        if self.calls >= MAX_CALLS and request.method == "tools/call":
            return {
                "jsonrpc": "2.0", "id": request.id,
                "result": {
                    "content": [{"type": "text", "text": "MCP call budget exhausted"}],
                    "isError": True,
                },
            }

        if request.method == "initialize":
            requested = str(request.params.get("protocolVersion") or MCP_VERSION)
            supported = requested if requested in {MCP_VERSION, "2024-11-05", "2025-03-26"} else MCP_VERSION
            return {
                "jsonrpc": "2.0", "id": request.id,
                "result": {
                    "protocolVersion": supported,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "aiops-operations", "version": "1.0.0"},
                },
            }
        if request.method == "tools/list":
            return {"jsonrpc": "2.0", "id": request.id, "result": {"tools": tool_definitions()}}
        if request.method != "tools/call":
            return _error(-32601, "Unsupported MCP method", request.id)

        name = str(request.params.get("name") or "")
        arguments = request.params.get("arguments") or {}

        def _tool_error(message: str) -> dict[str, Any]:
            # MCP reserves JSON-RPC-level errors for protocol failures; tool
            # execution problems (bad args, unknown tool) must be reported as
            # a normal result with isError=true so MCP clients that only ever
            # parse result.content[0] (e.g. the Foundry .NET MCP SDK) don't
            # choke on a missing `result` key.
            return {
                "jsonrpc": "2.0", "id": request.id,
                "result": {
                    "content": [{"type": "text", "text": message}],
                    "isError": True,
                },
            }

        if name not in REVIEWED_TOOLS:
            return _tool_error("Unknown or unauthorized tool")
        if not isinstance(arguments, Mapping) or not _safe_size(arguments, MAX_ARGUMENT_BYTES):
            return _tool_error("Invalid or oversized tool arguments")
        # LLM tool callers commonly send an empty string for an optional
        # field to mean "no filter" rather than omitting the key entirely.
        # Treat blank strings the same as an absent argument so a
        # perfectly-reasonable model call isn't rejected as invalid.
        cleaned_arguments = {
            key: value for key, value in arguments.items()
            if not (isinstance(value, str) and value.strip() == "")
        }
        try:
            validated = ToolArguments.model_validate(cleaned_arguments)
            args = validated.model_dump(exclude_none=True)
            missing = [field for field in _REQUIRED.get(name, ()) if field not in args]
        except ValidationError:
            return _tool_error("Invalid tool arguments")

        if missing:
            # A missing required argument is a normal outcome, not an error.
            #
            # Foundry aborts the entire run with HTTP 400 when a tool result
            # carries isError=true, so returning an error here meant one
            # speculative call destroyed the whole investigation: asked "what
            # is the root cause of the latest incident?", the governance
            # specialist calls business_service_context with no service name --
            # there isn't one in the question -- and the operator got a bare
            # "Foundry narration unavailable" instead of an answer.
            #
            # Reporting "no subject" as a successful empty result lets the
            # model see that the call yielded nothing and carry on with the
            # tools that did return evidence. The tool still never executes
            # without its arguments, so nothing is under-scoped.
            return {
                "jsonrpc": "2.0", "id": request.id,
                "result": {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "status": "empty",
                            "tool": name,
                            "missing_arguments": missing,
                            "detail": (
                                f"{name} needs {', '.join(missing)} and none was "
                                "supplied, so no lookup was performed. Use a tool "
                                "that does not need a subject, or name one."
                            ),
                        }),
                    }],
                    "isError": False,
                },
            }

        self.calls += 1
        started = time.monotonic()
        # Lazy import avoids making the API package import its application
        # while the governed registry is itself being imported.
        from operations.tools import STATUS_DENIED, ToolResult, call_tool

        result: ToolResult = call_tool(name, args, context=context, scope=scope)
        output = result.to_dict()
        if not _safe_size(output, MAX_RESPONSE_BYTES):
            result = ToolResult(status=STATUS_DENIED, warning="Tool response exceeded the MCP response budget")
            output = result.to_dict()
        self.audit_entries.append({
            "correlation_id": correlation_id,
            "actor": getattr(principal, "subject", ""),
            "scope": scope.to_dict(),
            "tool": name,
            "status": result.status,
            "evidence": output.get("evidence", []),
        })
        LOGGER.info(
            "mcp_tool_call correlation_id=%s actor=%s scope=%s tool=%s status=%s duration_ms=%.0f",
            correlation_id, getattr(principal, "subject", ""), scope.to_dict(), name,
            result.status, (time.monotonic() - started) * 1000,
        )
        return {
            "jsonrpc": "2.0", "id": request.id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(output)}],
                "isError": result.status in {STATUS_DENIED},
                "structuredContent": output,
            },
        }


__all__ = ["MCP_VERSION", "REVIEWED_TOOLS", "MCPServer", "tool_definitions"]
