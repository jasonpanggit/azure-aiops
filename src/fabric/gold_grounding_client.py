"""Query the published Gold-grounding Data Agent within one cancellable budget."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from fabric_pipelines.gold_grounding_contract import GoldGroundingStatus

MCP_TOOLS_CALL_TIMEOUT_SECONDS = 30.0
_REQUEST_ID = 1


@dataclass(frozen=True)
class GoldGroundingQueryResult:
    """Classified Data Agent transport result."""

    status: GoldGroundingStatus
    payload: dict[str, Any] | None = None
    reason: str = ""


async def query_gold_grounding(
    *,
    workspace_id: str,
    data_agent_id: str,
    tool_name: str,
    question: str,
    token: str,
    http_client: httpx.AsyncClient | None = None,
) -> GoldGroundingQueryResult:
    """Call the Data Agent once under a cancellable wall-clock deadline."""
    url = (
        f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}"
        f"/dataagents/{data_agent_id}/agent"
    )
    payload = {
        "jsonrpc": "2.0",
        "id": _REQUEST_ID,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"userQuestion": question}},
    }
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(
        timeout=httpx.Timeout(MCP_TOOLS_CALL_TIMEOUT_SECONDS)
    )
    try:
        async with asyncio.timeout(MCP_TOOLS_CALL_TIMEOUT_SECONDS):
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
    except TimeoutError:
        return GoldGroundingQueryResult(
            GoldGroundingStatus.TIMEOUT,
            reason="Gold-grounding Data Agent exceeded the 30-second request budget",
        )
    except httpx.HTTPError:
        return GoldGroundingQueryResult(
            GoldGroundingStatus.UNAVAILABLE,
            reason="Gold-grounding Data Agent transport is unavailable",
        )
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code in {401, 403}:
        return GoldGroundingQueryResult(
            GoldGroundingStatus.DENIED,
            reason="Gold-grounding Data Agent denied the request",
        )
    try:
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError:
        return GoldGroundingQueryResult(
            GoldGroundingStatus.UNAVAILABLE,
            reason="Gold-grounding Data Agent returned an unavailable response",
        )
    except json.JSONDecodeError:
        return GoldGroundingQueryResult(
            GoldGroundingStatus.MALFORMED,
            reason="Gold-grounding Data Agent returned malformed JSON",
        )

    if not isinstance(body, dict):
        return _malformed("non-object JSON-RPC envelope")
    if body.get("jsonrpc") != "2.0" or body.get("id") != _REQUEST_ID:
        return _malformed("uncorrelated JSON-RPC envelope")
    has_result = "result" in body
    has_error = "error" in body
    if has_result == has_error:
        return _malformed("JSON-RPC envelope must contain exactly one result or error")
    if has_error:
        error = body.get("error")
        text = (
            str(error.get("message") or "unknown JSON-RPC error")
            if isinstance(error, dict)
            else "unknown JSON-RPC error"
        )
        return GoldGroundingQueryResult(_error_status(text), reason=text)

    result = body.get("result")
    if not isinstance(result, dict):
        return _malformed("response result is not an object")
    if result.get("isError"):
        content = result.get("content") or [{}]
        first = content[0] if isinstance(content, list) and content else {}
        text = (
            str(first.get("text") or "unknown MCP error")
            if isinstance(first, dict)
            else str(first or "unknown MCP error")
        )
        return GoldGroundingQueryResult(_error_status(text), reason=text)
    content = result.get("content")
    if (
        not isinstance(content, list)
        or not content
        or any(not isinstance(item, (dict, str)) for item in content)
    ):
        return _malformed("response content is missing or invalid")
    return GoldGroundingQueryResult(GoldGroundingStatus.SUCCESS, payload=result)


def _malformed(detail: str) -> GoldGroundingQueryResult:
    return GoldGroundingQueryResult(
        GoldGroundingStatus.MALFORMED,
        reason=f"Gold-grounding Data Agent returned {detail}",
    )


def _error_status(text: str) -> GoldGroundingStatus:
    normalized = text.casefold()
    if any(word in normalized for word in ("denied", "forbidden", "unauthorized")):
        return GoldGroundingStatus.DENIED
    if "timeout" in normalized or "timed out" in normalized:
        return GoldGroundingStatus.TIMEOUT
    return GoldGroundingStatus.UNAVAILABLE


__all__ = [
    "MCP_TOOLS_CALL_TIMEOUT_SECONDS",
    "GoldGroundingQueryResult",
    "query_gold_grounding",
]
