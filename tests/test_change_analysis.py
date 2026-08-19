from change_scenario import change_engine


def test_change_analysis_explains_actor_time_risk_drift_and_business_context():
    finding = change_engine().analyze()["findings"][0]

    assert finding["change"]["change_id"] == "CHG-100"
    assert finding["change"]["changed_by"] == "platform.engineer@example.com"
    assert finding["change"]["changed_at"] == "2026-08-18T12:00:00Z"
    assert finding["resource"]["name"] == "vm-payments"
    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail Checkout"
    assert finding["risk_score"] >= 75
    assert finding["risk_level"] == "Critical"
    assert finding["configuration_drift"]["drifted"] is True
    assert finding["configuration_drift"]["fields"] == ["publicNetworkAccess", "sku"]
    assert finding["compliance_score"] < 100
    assert finding["read_only"] is True


def test_every_change_finding_is_explainable_and_advisory():
    for finding in change_engine().analyze()["findings"]:
        assert finding["evidence"]
        assert finding["risk_factors"]
        assert 0 <= finding["confidence"] <= 0.95
        assert finding["recommended_action"]["advisory_only"] is True
