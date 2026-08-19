from __future__ import annotations

from lifecycle_scenario import lifecycle_engine

from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from intelligence.lifecycle.eol_catalog import EOLCatalog
from intelligence.lifecycle.lifecycle_intelligence import LifecycleTelemetry

REQUESTED_MODULES = (
    "lifecycle_intelligence",
    "eol_catalog",
    "lifecycle_analyzer",
    "lifecycle_risk_engine",
    "modernization_engine",
    "lifecycle_trend_engine",
    "lifecycle_context_builder",
    "lifecycle_summary_engine",
)

REQUESTED_COMMANDS = {
    "Analyze Lifecycle Risk",
    "Show EOL Systems",
    "Show High Risk Systems",
    "Show Modernization Candidates",
    "Show Business Services At Risk",
    "Generate Lifecycle Report",
    "Generate Executive Modernization Brief",
    "Show Lifecycle Trends",
}


def test_exact_lifecycle_modules_and_authoritative_catalog_contract():
    for module in REQUESTED_MODULES:
        __import__(f"intelligence.lifecycle.{module}")

    rows = EOLCatalog.default().rows()
    products = {row["product"] for row in rows}
    assert {
        "Windows Server",
        "Ubuntu",
        "Red Hat Enterprise Linux",
        "Debian",
        "SQL Server",
        "Azure Stack HCI",
        "Azure Local",
        "Kubernetes",
    } <= products
    assert len(rows) >= 25
    assert all(
        {
            "release_date",
            "mainstream_support_end",
            "extended_support_end",
            "last_update_date",
            "recommended_upgrade_path",
            "source_url",
        }
        <= row.keys()
        for row in rows
    )


def test_findings_expose_requested_classification_risk_and_explainability():
    findings = lifecycle_engine().analyze()["findings"]
    statuses = {finding["lifecycle_classification"] for finding in findings}

    assert "Expired" in statuses
    assert "Unknown" in statuses
    for finding in findings:
        assert 0 <= finding["risk_score"] <= 100
        assert finding["risk_level"] in {"Low", "Moderate", "High", "Critical"}
        assert finding["evidence"]
        assert "business_impact" in finding
        assert "confidence" in finding
        assert "risk_drivers" in finding
        assert finding["modernization_recommendation"]["advisory_only"] is True


def test_exposure_trends_reports_and_commands_cover_requested_contracts():
    engine = lifecycle_engine()
    analysis = engine.analyze()

    assert {
        "total_eol_assets",
        "assets_within_12_months_of_eol",
        "assets_with_no_upgrade_plan",
        "business_services_at_risk",
        "lifecycle_debt_score",
        "by_subscription",
        "by_business_service",
        "by_environment",
        "by_application",
        "by_region",
        "by_operating_system",
    } <= analysis["exposure"].keys()
    assert set(analysis["trends"]) == {"30_day", "90_day", "180_day"}

    for report_type in (
        "Executive Lifecycle Summary",
        "Modernization Exposure Report",
        "Business Risk Report",
        "Application Risk Report",
        "Technology Debt Report",
    ):
        report = engine.report(report_type)
        assert report["read_only"] is True
        assert report["headline"]

    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert REQUESTED_COMMANDS <= registered


def test_lifecycle_telemetry_exposes_requested_instrument_names():
    telemetry = LifecycleTelemetry()

    assert telemetry.analysis_duration is not None
    assert telemetry.catalog_freshness is not None
    assert telemetry.risk_calculation_latency is telemetry.risk_latency
    assert telemetry.impact_correlation_latency is telemetry.business_impact_latency
    assert telemetry.report_generation_duration is telemetry.executive_report_duration
