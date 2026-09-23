"""Query the published Gold-grounding Fabric Data Agent via MCP tools/call."""

from __future__ import annotations

import json
import time

import httpx

MCP_TOOLS_CALL_TIMEOUT_SECONDS = 20.0
MAX_RETRIES = 0


class GoldGroundingUnavailable(RuntimeError):
    """The Gold-grounding Data Agent could not be queried."""


def query_gold_grounding(
    *, workspace_id: str, data_agent_id: str, tool_name: str, question: str, token: str
) -> dict:
    """Call the Data Agent MCP endpoint and return its result payload."""
    url = (
        f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}"
        f"/dataagents/{data_agent_id}/agent"
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": {"userQuestion": question}},
    }

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=MCP_TOOLS_CALL_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt <= MAX_RETRIES:
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            raise GoldGroundingUnavailable(
                f"Gold-grounding Data Agent unreachable after {attempt} attempts"
            ) from last_error

        result = body.get("result", {})
        if result.get("isError"):
            content = result.get("content") or [{}]
            raise GoldGroundingUnavailable(str(content[0].get("text", "unknown MCP error")))
        return result

    raise GoldGroundingUnavailable("unreachable")  # pragma: no cover
