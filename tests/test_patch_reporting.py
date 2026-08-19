from __future__ import annotations

import pytest
from patch_scenario import patch_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def test_all_executive_patch_reports_are_read_only_and_actionable():
    engine = patch_engine()
    report_types = (
        "Executive Patch Summary",
        "Security Exposure Summary",
        "Compliance Overview",
        "Patch Risk Dashboard",
        "Business Service Exposure Dashboard",
        "Monthly Risk Report",
        "Executive Brief",
    )

    for report_type in report_types:
        report = engine.report(report_type)
        assert report["headline"]
        assert report["priority_remediation_candidates"]
        assert report["freshness"] == "2026-08-18T00:00:00Z"
        assert report["read_only"] is True


def test_patch_agent_commands_use_the_intelligence_engine_and_remain_advisory_only():
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()), patch_intelligence=patch_engine()
    )
    commands = (
        "Analyze Patch Compliance",
        "Analyze Security Exposure",
        "Show Security Exposure",
        "Show Critical Patch Failures",
        "Show High Risk Applications",
        "Show Business Risk",
        "Generate Patch Report",
        "Generate Executive Brief",
        "Executive Brief",
        "Show Priority Remediation Candidates",
    )

    for command in commands:
        result = operations.analyze(command, "Enterprise", subject_type="PatchPortfolio")
        assert result["subject"] == {
            "name": "Enterprise",
            "entity_type": "PatchPortfolio",
        }
        assert result["conclusions"]
        assert result["read_only"] is True
        assert all(item["advisory_only"] is True for item in result["recommendations"])

    with pytest.raises(ValueError, match="pre-authorized enterprise portfolio"):
        operations.analyze(
            "Show Business Risk", "sub-finance", subject_type="Subscription"
        )


def test_patch_telemetry_records_all_required_calculation_metrics():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.compliance_duration = Instrument()
            self.analysis_latency = Instrument()
            self.trend_latency = Instrument()
            self.freshness = Instrument()
            self.risk_duration = Instrument()
            self.business_impact_duration = Instrument()

    telemetry = Telemetry()
    engine = patch_engine(telemetry=telemetry)
    engine.analyze()
    engine.business_impact()

    assert telemetry.compliance_duration.records
    assert telemetry.analysis_latency.records
    assert telemetry.trend_latency.records
    assert telemetry.freshness.records
    assert telemetry.risk_duration.records
    assert telemetry.business_impact_duration.records
