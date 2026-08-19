from __future__ import annotations

from lifecycle_scenario import lifecycle_engine

from intelligence.lifecycle.lifecycle_risk_engine import LifecycleRiskEngine


def test_lifecycle_risk_is_bounded_deterministic_and_explainable():
    payroll = next(
        item
        for item in lifecycle_engine().analyze()["findings"]
        if item["application"] == "Payroll"
    )

    assert payroll["risk_score"] == 84
    assert payroll["risk_level"] == "Critical"
    assert payroll["risk_score"] == sum(payroll["risk_factors"].values())
    assert set(payroll["risk_factors"]) == {
        "support_timeline",
        "patch_noncompliance",
        "external_exposure",
        "business_criticality",
        "ownership_gap",
        "production_environment",
        "catalog_match_missing",
    }


def test_lifecycle_risk_levels_cover_zero_to_one_hundred():
    engine = LifecycleRiskEngine()

    assert engine.level_for(0) == "Low"
    assert engine.level_for(25) == "Moderate"
    assert engine.level_for(50) == "High"
    assert engine.level_for(75) == "Critical"
    result = engine.calculate(
        context={
            "patch_compliance": 0,
            "internet_exposed": True,
            "business_criticality": "Critical",
            "ownership_coverage": False,
            "environment": "Production",
        },
        classification={"status": "EOL"},
    )
    assert result["score"] == 100
