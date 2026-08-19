from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from lifecycle_scenario import lifecycle_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence
from intelligence.lifecycle.lifecycle_trend_engine import LifecycleTrendEngine
from semantic.semantic_engine import SemanticEngine


def test_executive_reports_are_distinct_read_only_and_cio_ready():
    engine = lifecycle_engine()
    report_types = (
        "Executive Lifecycle Summary",
        "Modernization Exposure Report",
        "Business Risk Report",
        "Application Risk Report",
        "Technology Debt Report",
        "Executive Modernization Brief",
    )

    focuses = []
    for report_type in report_types:
        report = engine.report(report_type)
        assert report["headline"]
        assert report["focus"]
        assert report["priority_candidates"]
        assert report["freshness"] == "2026-08-18T00:00:00Z"
        assert report["read_only"] is True
        focuses.append(report["focus"])
    assert len({str(focus) for focus in focuses}) == len(report_types)


def test_lifecycle_trends_cover_30_90_and_180_day_windows():
    trends = lifecycle_engine().query("Show lifecycle trends")["result"]

    assert set(trends) == {"30_day", "90_day", "180_day"}
    assert trends["30_day"]["trend"] in {"Improving", "Stable", "Degrading"}
    for window in trends.values():
        assert set(window) == {
            "observation_count",
            "new_eol_discoveries",
            "risk_score_change",
            "modernization_progress_events",
            "lifecycle_debt_reduction",
            "trend",
        }


def test_same_second_ingestion_runs_remain_distinct_trend_snapshots():
    observed_at = "2026-08-18T00:00:00Z"
    history = [
        {
            "resource_key": "resource-1",
            "observed_at": observed_at,
            "ingestion_run_id": "run-1",
            "risk_score": 90,
            "lifecycle_status": "EOL",
        },
        {
            "resource_key": "resource-1",
            "observed_at": observed_at,
            "ingestion_run_id": "run-2",
            "risk_score": 10,
            "lifecycle_status": "Supported",
        },
    ]
    trends = LifecycleTrendEngine().calculate(
        history,
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )
    reversed_trends = LifecycleTrendEngine().calculate(
        list(reversed(history)),
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert trends["30_day"]["risk_score_change"] == -80
    assert trends["30_day"]["trend"] == "Improving"
    assert reversed_trends["30_day"] == trends["30_day"]


def test_lifecycle_telemetry_records_required_metrics():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.analysis_duration = Instrument()
            self.catalog_freshness = Instrument()
            self.risk_latency = Instrument()
            self.business_impact_latency = Instrument()
            self.executive_report_duration = Instrument()

    telemetry = Telemetry()
    engine = lifecycle_engine(telemetry=telemetry)
    engine.analyze()
    engine.report("Executive Lifecycle Summary")

    assert telemetry.analysis_duration.records
    assert telemetry.catalog_freshness.records
    assert telemetry.risk_latency.records
    assert telemetry.business_impact_latency.records
    assert telemetry.executive_report_duration.records


def test_lifecycle_agent_commands_are_bounded_read_only_and_advisory():
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        lifecycle_intelligence=lifecycle_engine(),
    )
    commands = (
        "Analyze Lifecycle Risk",
        "Show EOL Systems",
        "Show High Risk Systems",
        "Show Modernization Candidates",
        "Show Business Services At Risk",
        "Generate Lifecycle Report",
        "Generate Executive Modernization Brief",
        "Show Lifecycle Trends",
    )

    for command in commands:
        result = operations.analyze(
            command, "Enterprise", subject_type="LifecyclePortfolio"
        )
        assert result["subject"] == {
            "name": "Enterprise",
            "entity_type": "LifecyclePortfolio",
        }
        assert result["conclusions"]
        assert result["read_only"] is True
        assert all(item["advisory_only"] for item in result["recommendations"])

    with pytest.raises(ValueError, match="pre-authorized enterprise lifecycle portfolio"):
        operations.analyze(
            "Show EOL Systems", "sub-finance", subject_type="Subscription"
        )


def test_lifecycle_agent_never_exposes_raw_subscription_identifier():
    raw_subscription_id = "5ef7423a-80d9-4c44-ae0f-058600202e4a"
    engine = LifecycleIntelligence(
        resources=[
            {
                "resource_key": "resource-1",
                "name": "server-1",
                "subscription": raw_subscription_id,
                "product": "Unknown OS",
                "version": "1",
            }
        ],
        catalog=[],
        history=[],
        freshness="2026-08-18T00:00:00Z",
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        lifecycle_intelligence=engine,
    )

    result = operations.analyze(
        "Generate Lifecycle Report", "Enterprise", subject_type="LifecyclePortfolio"
    )

    assert raw_subscription_id not in json.dumps(result)
