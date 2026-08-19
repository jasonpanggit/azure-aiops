from predictive_scenario import predictive_engine


def test_predictive_analysis_ranks_likely_failure_with_business_context():
    analysis = predictive_engine().analyze()
    top = analysis["predictions"][0]

    assert top["resource"]["name"] == "vm-payments"
    assert top["application"] == "Payments"
    assert top["business_service"] == "Retail Checkout"
    assert top["forecast_30_day"]["score"] >= 75
    assert top["forecast_30_day"]["level"] == "Critical"
    assert top["predicted_failure_modes"]
    assert top["evidence"]
    assert top["risk_drivers"]
    assert 0 <= top["confidence"] <= 0.95
    assert top["read_only"] is True


def test_predictions_never_claim_certainty_or_action():
    for prediction in predictive_engine().analyze()["predictions"]:
        assert prediction["prediction_status"] == "Evidence-backed forecast"
        assert prediction["recommended_action"]["advisory_only"] is True
        assert "will fail" not in prediction["explanation"].casefold()
        assert prediction["confidence"] < 1
