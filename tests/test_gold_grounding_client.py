from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from fabric.gold_grounding_client import (
    GoldGroundingQueryResult,
    query_gold_grounding,
)
from fabric_pipelines.gold_grounding_contract import GoldGroundingStatus
from operations.gold_grounding_metrics import GoldGroundingMetrics


def _response(payload: object, status_code: int = 200) -> httpx.Response:
    request = httpx.Request(
        "POST",
        "https://api.fabric.microsoft.com/v1/mcp/workspaces/w/dataagents/a/agent",
    )
    return httpx.Response(status_code, request=request, json=payload)


def _client(payload: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: _response(payload))
    )


def _query(client: httpx.AsyncClient) -> GoldGroundingQueryResult:
    return asyncio.run(
        query_gold_grounding(
            workspace_id="workspace-id",
            data_agent_id="agent-id",
            tool_name="DataAgent_AI_Ops_Data_Agent",
            question="what changed?",
            token="delegated-token",
            http_client=client,
        )
    )


def test_query_gold_grounding_returns_one_correlated_result() -> None:
    result = _query(
        _client(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "ok"}],
                },
            }
        )
    )

    assert result == GoldGroundingQueryResult(
        GoldGroundingStatus.SUCCESS,
        payload={
            "isError": False,
            "content": [{"type": "text", "text": "ok"}],
        },
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"jsonrpc": "2.0", "id": 1, "result": []},
        {"id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}},
        {
            "jsonrpc": "1.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        },
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
            "error": {"message": "also failed"},
        },
        {"jsonrpc": "2.0", "id": 1, "result": {"content": {}}},
        {"jsonrpc": "2.0", "id": 1, "result": {"content": []}},
    ],
)
def test_query_gold_grounding_rejects_malformed_json_rpc(payload: object) -> None:
    assert _query(_client(payload)).status == GoldGroundingStatus.MALFORMED


def test_query_gold_grounding_classifies_json_rpc_error() -> None:
    result = _query(
        _client(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32001, "message": "request forbidden"},
            }
        )
    )

    assert result.status == GoldGroundingStatus.DENIED


def test_query_gold_grounding_classifies_mcp_error() -> None:
    result = _query(
        _client(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": True,
                    "content": ["request timed out"],
                },
            }
        )
    )

    assert result.status == GoldGroundingStatus.TIMEOUT


def test_query_gold_grounding_classifies_invalid_json() -> None:
    class _BadJsonResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            raise json.JSONDecodeError("bad", "{}", 0)

    class _Client:
        async def post(self, *_args, **_kwargs):
            return _BadJsonResponse()

    result = asyncio.run(
        query_gold_grounding(
            workspace_id="workspace-id",
            data_agent_id="agent-id",
            tool_name="tool",
            question="q",
            token="delegated-token",
            http_client=_Client(),
        )
    )

    assert result.status == GoldGroundingStatus.MALFORMED


def test_query_gold_grounding_cancels_under_wall_clock_budget() -> None:
    cancelled = False

    class _Client:
        async def post(self, *_args, **_kwargs):
            nonlocal cancelled
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled = True
                raise

    async def run():
        import fabric.gold_grounding_client as module

        original = module.MCP_TOOLS_CALL_TIMEOUT_SECONDS
        module.MCP_TOOLS_CALL_TIMEOUT_SECONDS = 0.01
        try:
            return await query_gold_grounding(
                workspace_id="workspace-id",
                data_agent_id="agent-id",
                tool_name="tool",
                question="q",
                token="delegated-token",
                http_client=_Client(),
            )
        finally:
            module.MCP_TOOLS_CALL_TIMEOUT_SECONDS = original

    result = asyncio.run(run())

    assert result.status == GoldGroundingStatus.TIMEOUT
    assert cancelled is True


def test_metrics_record_query_uses_only_low_cardinality_attributes() -> None:
    class _Counter:
        def __init__(self) -> None:
            self.calls: list[tuple[int, dict | None]] = []

        def add(self, value: int, attributes: dict | None = None) -> None:
            self.calls.append((value, attributes))

    class _Histogram:
        def __init__(self) -> None:
            self.calls: list[tuple[float, dict | None]] = []

        def record(self, value: float, attributes: dict | None = None) -> None:
            self.calls.append((value, attributes))

    class _Meter:
        def __init__(self) -> None:
            self.created_counters: dict[str, _Counter] = {}
            self.created_histograms: dict[str, _Histogram] = {}

        def create_counter(self, name: str, **_kwargs) -> _Counter:
            counter = _Counter()
            self.created_counters[name] = counter
            return counter

        def create_histogram(self, name: str, **_kwargs) -> _Histogram:
            histogram = _Histogram()
            self.created_histograms[name] = histogram
            return histogram

    meter = _Meter()
    metrics = GoldGroundingMetrics(meter=meter)
    reason = "this-reason-string-is-deliberately-longer-than-forty-characters"
    metrics.record_query(
        degraded=True,
        degraded_reason=reason,
        citation_count=3,
        duration_ms=12.5,
    )

    assert meter.created_counters["gold_grounding.queries"].calls == [
        (1, {"degraded": "True"})
    ]
    assert meter.created_histograms["gold_grounding.query.duration"].calls == [
        (12.5, {"degraded": "True"})
    ]
    assert meter.created_counters["gold_grounding.degraded"].calls == [
        (1, {"reason": reason[:40]})
    ]
