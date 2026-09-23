from __future__ import annotations

import json

import httpx
import pytest

from fabric.gold_grounding_client import (
    MAX_RETRIES,
    GoldGroundingUnavailable,
    query_gold_grounding,
)
from operations.gold_grounding_metrics import GoldGroundingMetrics


def _response(payload: dict, status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://api.fabric.microsoft.com/v1/mcp/workspaces/w/dataagents/a/agent")
    return httpx.Response(status_code, request=request, json=payload)


def test_query_gold_grounding_returns_result_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict, dict, float]] = []

    def fake_post(url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
        calls.append((url, json, headers, timeout))
        return _response({"result": {"isError": False, "content": [{"type": "text", "text": "ok"}]}})

    monkeypatch.setattr("fabric.gold_grounding_client.httpx.post", fake_post)

    result = query_gold_grounding(
        workspace_id="workspace-id",
        data_agent_id="agent-id",
        tool_name="DataAgent_gold_grounding_agent",
        question="what changed?",
        token="delegated-token",
    )

    assert result == {"isError": False, "content": [{"type": "text", "text": "ok"}]}
    assert len(calls) == 1
    assert calls[0][0].endswith("/mcp/workspaces/workspace-id/dataagents/agent-id/agent")
    assert calls[0][1]["method"] == "tools/call"
    assert calls[0][1]["params"]["name"] == "DataAgent_gold_grounding_agent"
    assert calls[0][1]["params"]["arguments"] == {"userQuestion": "what changed?"}
    assert calls[0][2]["Authorization"] == "Bearer delegated-token"


def test_query_gold_grounding_retries_http_errors_then_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_post(*_args, **_kwargs) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("network down")

    monkeypatch.setattr("fabric.gold_grounding_client.httpx.post", fake_post)
    monkeypatch.setattr("fabric.gold_grounding_client.time.sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(
        GoldGroundingUnavailable,
        match=f"Gold-grounding Data Agent unreachable after {MAX_RETRIES + 1} attempts",
    ):
        query_gold_grounding(
            workspace_id="workspace-id",
            data_agent_id="agent-id",
            tool_name="tool",
            question="q",
            token="delegated-token",
        )

    assert attempts["count"] == MAX_RETRIES + 1
    assert sleeps == []


def test_query_gold_grounding_fails_closed_on_json_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    calls = {"count": 0}

    class _BadJsonResponse:
        def raise_for_status(self) -> None:  # pragma: no cover - simple stub
            return None

        def json(self) -> dict:
            raise json.JSONDecodeError("bad", "{}", 0)

    def fake_post(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _BadJsonResponse()
        return _response({"result": {"isError": False, "content": [{"type": "text", "text": "ok"}]}})

    monkeypatch.setattr("fabric.gold_grounding_client.httpx.post", fake_post)
    monkeypatch.setattr("fabric.gold_grounding_client.time.sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(
        GoldGroundingUnavailable,
        match="unreachable after 1 attempts",
    ):
        query_gold_grounding(
            workspace_id="workspace-id",
            data_agent_id="agent-id",
            tool_name="tool",
            question="q",
            token="delegated-token",
        )

    assert calls["count"] == 1
    assert sleeps == []


def test_query_gold_grounding_raises_immediately_on_mcp_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    def fake_post(*_args, **_kwargs) -> httpx.Response:
        attempts["count"] += 1
        return _response(
            {
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "run failed before producing a result"}],
                }
            }
        )

    monkeypatch.setattr("fabric.gold_grounding_client.httpx.post", fake_post)

    with pytest.raises(GoldGroundingUnavailable, match="run failed before producing a result"):
        query_gold_grounding(
            workspace_id="workspace-id",
            data_agent_id="agent-id",
            tool_name="tool",
            question="q",
            token="delegated-token",
        )
    assert attempts["count"] == 1


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

    metrics.record_query(
        degraded=True,
        degraded_reason="this-reason-string-is-deliberately-longer-than-forty-characters",
        citation_count=3,
        duration_ms=12.5,
    )
    expected_reason = "this-reason-string-is-deliberately-longer-than-forty-characters"[:40]

    assert meter.created_counters["gold_grounding.queries"].calls == [
        (1, {"degraded": "True"})
    ]
    assert meter.created_histograms["gold_grounding.query.duration"].calls == [
        (12.5, {"degraded": "True"})
    ]
    assert meter.created_histograms["gold_grounding.citations.count"].calls == [
        (3, None)
    ]
    assert meter.created_counters["gold_grounding.degraded"].calls == [
        (1, {"reason": expected_reason})
    ]
