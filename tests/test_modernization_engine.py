from __future__ import annotations

from lifecycle_scenario import lifecycle_engine


def test_modernization_recommendation_contains_priority_impact_reduction_and_complexity():
    payroll = next(
        item
        for item in lifecycle_engine().analyze()["findings"]
        if item["application"] == "Payroll"
    )
    recommendation = payroll["modernization_recommendation"]

    assert recommendation["priority"] == "Priority 1"
    assert recommendation["impact"] == "Critical"
    assert recommendation["risk_reduction"] == 40
    assert recommendation["complexity_estimate"] == "High"
    assert recommendation["recommended_action"] == "Upgrade to Windows Server 2025"
    assert recommendation["evidence"]
    assert recommendation["lifecycle_status"] == "EOL"
    assert recommendation["risk_drivers"]
    assert recommendation["advisory_only"] is True


def test_unknown_product_recommendation_does_not_invent_upgrade_path():
    unknown = next(
        item
        for item in lifecycle_engine().analyze()["findings"]
        if item["resource"]["name"] == "arc-unknown"
    )["modernization_recommendation"]

    assert unknown["confidence"] == 0
    assert unknown["complexity_estimate"] == "Unknown"
    assert unknown["risk_reduction"] == 0
    assert "Validate the product/version" in unknown["recommended_action"]
