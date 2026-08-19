from __future__ import annotations

from patch_scenario import patch_engine


def test_patch_risk_combines_vulnerability_operational_and_business_factors():
    findings = patch_engine().analyze()["findings"]
    payroll = next(item for item in findings if item["application"] == "Payroll")
    storefront = next(item for item in findings if item["application"] == "Storefront")

    assert payroll["risk_score"] > storefront["risk_score"]
    assert payroll["risk_level"] == "Critical"
    assert set(payroll["risk_factors"]) == {
        "business_criticality",
        "application_impact",
        "patch_age",
        "patch_severity",
        "missing_critical_patches",
        "security_findings",
        "advisor_recommendations",
        "ownership_gap",
        "evidence_uncertainty",
    }
    assert payroll["risk_score"] == sum(payroll["risk_factors"].values())


def test_exposure_ranks_most_vulnerable_application_and_subscription():
    exposure = patch_engine().query("Show vulnerable applications")["result"]
    subscription_risk = patch_engine().analyze()["exposure"]["subscription_patch_risk"]

    assert exposure[0]["name"] == "Payroll"
    assert subscription_risk[0]["name"] == "sub-finance"


def test_critical_patch_failures_filter_on_failed_update_severity():
    failures = patch_engine().query("Show critical patch failures")["result"]

    assert [item["resource"]["name"] for item in failures] == ["vm-payroll-01"]
    assert failures[0]["failed_critical_update_count"] == 1
