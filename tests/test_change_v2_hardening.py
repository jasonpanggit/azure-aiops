from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pytest
from change_scenario import change_engine

from intelligence.change.change_intelligence import ChangeIntelligence


def fixture():
    return json.loads(Path("tests/fixtures/sample_change_intelligence.json").read_text())


def build(data, **kwargs):
    return ChangeIntelligence.from_snapshot(
        **data,
        **kwargs,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )


def test_missing_authorization_stays_unknown_and_unapproved_query_requires_false():
    engine = change_engine()
    finding = engine.analyze()["findings"][0]

    assert finding["change"]["authorized"] is None
    assert engine.query("Show unapproved changes")["result"] == []

    engine.changes[0]["authorized"] = False
    assert engine.query("Show unapproved changes")["result"]


@pytest.mark.parametrize("value", [1, "true", [], {}])
def test_malformed_authorization_fails_closed(value):
    data = fixture()
    data["resource_changes"][0]["authorized"] = value

    with pytest.raises(TypeError, match="authorized"):
        build(data)


def test_previous_current_state_identifiers_are_recursively_sanitized():
    data = fixture()
    arm = data["resources"][0]["resource_key"]
    encoded = arm
    for _ in range(25):
        encoded = quote(encoded)
    data["resource_changes"][0]["previous_state"] = {"value": encoded}
    data["resource_changes"][0]["current_state"] = {"value": encoded}

    serialized = json.dumps(build(data).analyze()).casefold()

    assert "/subscriptions/" not in serialized
    assert "%2fsubscriptions" not in serialized


def test_projection_totals_are_independent_of_output_limit_and_remain_valid():
    counts = []
    for limit in (1, 2, 100):
        projection = change_engine(max_output_items=limit).knowledge_projection()
        counts.append(projection["collection_metadata"]["entities"]["count"])
        assert len(projection["entities"]) <= limit
        assert len(projection["relationships"]) <= limit
    assert len(set(counts)) == 1


def test_timeline_counts_are_calculated_before_truncation():
    engine = change_engine(max_output_items=1)
    timeline = engine.timelines()["24_hour"]

    assert timeline["change_count"] == 4
    assert len(timeline["changes"]) == 1
    assert timeline["collection_metadata"] == {
        "count": 4,
        "returned": 1,
        "truncated": True,
    }


def test_reports_include_executive_governance_and_risk_views():
    engine = change_engine()
    for report in (
        "Executive Governance Report",
        "Change Risk Report",
        "Executive Change Brief",
    ):
        result = engine.report(report)
        assert result["read_only"] is True
        assert result["headline"]
