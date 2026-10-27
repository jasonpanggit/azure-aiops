"""Compatibility investigations preserve partial governed evidence."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context
from test_api_copilot_unified import _canonical_body
from test_observability_arg_reader import OBSERVED, SCOPE, ToolCtx, reader

from api.app import create_app
from api.evidence import Evidence
from api.scope import Scope
from operations import investigation
from operations.observability_scenarios import ALERT_DELIVERY_COVERAGE
from operations.tools import ToolResult


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "empty"),
        (["partial"], "partial"),
        (["partial", "ok"], "partial"),
        (["partial", "empty"], "partial"),
        (["partial", "unavailable"], "partial"),
        (["partial", "denied"], "partial"),
        (["ok"], "ok"),
        (["empty"], "empty"),
        (["unavailable"], "unavailable"),
        (["denied"], "denied"),
        (["ok", "unavailable"], "partial"),
        (["ok", "denied"], "partial"),
    ],
)
def test_investigation_preserves_partial_status(monkeypatch, statuses, expected):
    results = iter(
        ToolResult(
            status=status,
            data={},
            evidence=(
                (Evidence(source_engine="fixture", timestamp="2026-10-27T02:20:00Z"),)
                if status in {"ok", "partial"}
                else ()
            ),
            warning="Coverage is incomplete." if status == "partial" else "",
        )
        for status in statuses
    )
    monkeypatch.setattr(
        investigation, "call_tool", lambda *args, **kwargs: next(results)
    )

    result = investigation.run_investigation(
        "Review authorized evidence.",
        context=SimpleNamespace(),
        scope=Scope.unrestricted(),
        planned_calls=[("incidents", {}) for _ in statuses],
    )

    payload = result.to_dict()
    assert payload["fact_status"] == expected
    assert payload["mutation_authorized"] is False
    for call, status in zip(payload["tool_calls"], statuses, strict=True):
        assert call["status"] == status
    if "partial" in statuses:
        assert "incidents: Coverage is incomplete." in payload["uncertainty"]
        assert any(citation["status"] == "partial" for citation in payload["citations"])


def test_compatibility_wire_preserves_partial_tool_and_citation_status(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    monkeypatch.setattr(
        investigation,
        "call_tool",
        lambda *args, **kwargs: ToolResult(
            status="partial",
            data={"resources": []},
            evidence=(Evidence(source_engine="fixture.inventory"),),
            warning="Coverage is incomplete.",
        ),
    )
    response = TestClient(create_app(_context(tmp_path, None))).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=_canonical_body(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "partial"
    assert data["tool_results"][0]["status"] == "partial"
    assert data["citations"][0]["status"] == "partial"
    assert data["coverage"]["complete"] is False
    assert "inventory_resources: Coverage is incomplete." in data["uncertainty"]
    assert data["mutation_authorized"] is False


def test_real_alert_projection_preserves_partial_evidence_through_aggregation():
    result = investigation.run_investigation(
        "Review alert delivery coverage.",
        context=ToolCtx(reader()),
        scope=SCOPE,
        planned_calls=[("incidents", {"scenario": ALERT_DELIVERY_COVERAGE})],
    ).to_dict()

    assert result["fact_status"] == "partial"
    assert result["tool_calls"][0]["status"] == "partial"
    assert result["tool_calls"][0]["data"]["assessment"]["status"] == "partial"
    assert (
        result["tool_calls"][0]["data"]["assessment"]["alert_coverage"][
            "delivery_status"
        ]
        == "not_proven"
    )
    assert {citation["status"] for citation in result["citations"]} == {"partial"}
    assert result["tool_calls"][0]["evidence"][1]["timestamp"] == OBSERVED
    assert result["tool_calls"][0]["evidence"][2]["timestamp"] == OBSERVED
    assert result["mutation_authorized"] is False
