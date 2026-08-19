from __future__ import annotations

from datetime import UTC, datetime

from patch_scenario import patch_engine

from intelligence.patch.patch_compliance_engine import PatchComplianceEngine


def test_compliance_rolls_up_resource_application_service_environment_and_subscription():
    compliance = patch_engine().query("Show patch compliance")["result"]

    assert compliance["overall"]["resource_count"] == 3
    assert compliance["overall"]["unpatched_resource_count"] == 2
    assert compliance["overall"]["missing_critical_updates"] == 2
    assert compliance["overall"]["missing_security_updates"] == 3
    assert compliance["subscriptions"][0]["name"] == "sub-finance"
    assert {item["name"] for item in compliance["applications"]} == {
        "Payroll",
        "Storefront",
        "Catalog Dev",
    }
    assert {item["name"] for item in compliance["business_services"]} == {
        "HR Services",
        "Digital Commerce",
    }
    assert {item["name"] for item in compliance["environments"]} == {
        "Production",
        "Development",
    }
    assert all(0 <= item["compliance_score"] <= 100 for item in compliance["applications"])


def test_resource_compliance_evaluates_governed_patch_policy_and_debt():
    findings = patch_engine().analyze()["findings"]
    payroll = next(item for item in findings if item["application"] == "Payroll")
    development = next(item for item in findings if item["application"] == "Catalog Dev")

    assert payroll["patch_policy"] == "Production baseline"
    assert payroll["policy_compliant"] is False
    assert payroll["compliance_debt"] == 90
    assert development["patch_policy"] == "Development baseline"
    assert development["policy_compliant"] is True
    assert development["compliance_debt"] == 0


def test_missing_assessment_is_unknown_not_healthy_or_compliant():
    result = PatchComplianceEngine().resource_compliance(
        None, [], now=datetime(2026, 8, 18, tzinfo=UTC)
    )

    assert result["status"] == "unknown"
    assert result["evidence_coverage"] == "Missing"
    assert result["compliance_score"] < 50
    assert result["unpatched"] is None


def test_old_successful_patch_does_not_create_current_patch_age_or_severity_debt():
    result = PatchComplianceEngine().resource_compliance(
        {"status": "compliant"},
        [
            {
                "status": "succeeded",
                "severity": "Critical",
                "published_at": "2020-01-01T00:00:00Z",
            }
        ],
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert result["patch_age_days"] == 0
    assert result["highest_severity"] == "Unknown"
    assert result["compliance_score"] == 100


def test_unknown_installation_outcome_prevents_healthy_compliance():
    result = PatchComplianceEngine().resource_compliance(
        {"status": "compliant"},
        [{"status": "unknown", "severity": "Critical"}],
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert result["evidence_coverage"] == "Partial"
    assert result["unknown_installation_count"] == 1
    assert result["compliance_score"] == 40
    assert result["unpatched"] is None
