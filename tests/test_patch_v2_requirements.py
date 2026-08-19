from __future__ import annotations

from patch_scenario import patch_engine

from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from intelligence.patch.patch_intelligence import (
    CriticalUpdate,
    Installation,
    MaintenanceWindow,
    MissingUpdate,
    PatchBaseline,
    Policy,
    ResourceCompliance,
    SecurityUpdate,
    Update,
)

MODULES = (
    "patch_intelligence",
    "patch_analyzer",
    "patch_correlator",
    "patch_priority_engine",
    "patch_risk_engine",
    "compliance_engine",
    "patch_trend_engine",
    "patch_summary_engine",
    "patch_context_builder",
)

COMMANDS = {
    "Analyze Patch Compliance",
    "Show Security Exposure",
    "Show Critical Patch Failures",
    "Show High Risk Applications",
    "Show Business Risk",
    "Generate Patch Report",
    "Generate Executive Brief",
    "Show Priority Remediation Candidates",
}


def test_exact_patch_modules_and_data_model_contract():
    for module in MODULES:
        __import__(f"intelligence.patch.{module}")
    assert all(
        model is not None
        for model in (
            Update,
            Installation,
            MissingUpdate,
            CriticalUpdate,
            SecurityUpdate,
            ResourceCompliance,
            MaintenanceWindow,
            Policy,
            PatchBaseline,
        )
    )


def test_compliance_priority_exposure_and_explainability_contracts():
    analysis = patch_engine().analyze()
    compliance = analysis["compliance"]

    assert {
        "overall",
        "subscriptions",
        "applications",
        "business_services",
        "environments",
        "resources",
    } <= compliance.keys()
    assert {
        "resource_count",
        "unpatched_resource_count",
        "missing_critical_updates",
        "missing_security_updates",
        "compliance_score",
        "patch_success_percent",
        "patch_failure_percent",
        "risk_level",
    } <= compliance["overall"].keys()

    assert analysis["exposure"]["high_risk_workloads"]
    assert "security_patch_debt" in analysis["exposure"]
    assert "vulnerable_applications" in analysis["exposure"]
    assert "business_exposure" in analysis["exposure"]
    for finding in analysis["findings"]:
        assert finding["priority"] in {
            "Priority 1",
            "Priority 2",
            "Priority 3",
            "Priority 4",
        }
        assert finding["evidence"]
        assert finding["affected_resources"]
        assert finding["business_impact"]
        assert finding["risk_justification"]
        assert finding["priority_reasoning"]
        assert finding["recommended_action"]
        assert 0 <= finding["confidence_score"] <= 1


def test_trends_reports_commands_and_read_only_contract():
    engine = patch_engine()
    trends = engine.analyze()["trends"]
    assert {"7_day", "30_day"} <= trends.keys()
    for window in (trends["7_day"], trends["30_day"]):
        assert {
            "patch_success_trend",
            "patch_failure_trend",
            "compliance_trend",
            "risk_trend",
            "recurring_failures",
            "chronic_offenders",
        } <= window.keys()

    for report_type in (
        "Executive Patch Summary",
        "Security Exposure Summary",
        "Compliance Overview",
        "Patch Risk Dashboard",
        "Business Service Exposure Dashboard",
        "Monthly Risk Report",
        "Executive Brief",
    ):
        report = engine.report(report_type)
        assert report["headline"]
        assert report["read_only"] is True

    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert COMMANDS <= registered
    assert engine.analyze()["read_only"] is True
