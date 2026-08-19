from predictive_scenario import predictive_engine


def test_application_and_service_aggregates_expose_operational_debt():
    analysis = predictive_engine().analyze()
    applications = analysis["applications"]
    services = analysis["business_services"]

    assert applications[0]["name"] == "Payments"
    assert applications[0]["instability_score"] >= 75
    assert applications[0]["operational_debt_score"] > 0
    assert services[0]["elevated_resource_count"] >= 1
    assert services[0]["forecast_level"] in {"High", "Critical"}


def test_ownership_gap_is_explicit_predictive_driver():
    payroll = next(row for row in predictive_engine().analyze()["predictions"] if row["resource"]["name"] == "arc-payroll")
    assert payroll["owner"] == "Unknown"
    assert "ownership_gap" in payroll["risk_drivers"]
    assert payroll["feature_contributions"]["ownership_gap"] > 0
