from change_scenario import change_engine


def test_drift_and_compliance_cover_expected_configuration_and_baselines():
    analysis = change_engine().analyze()
    compliance = analysis["compliance"][0]

    assert compliance["resource"]["name"] == "vm-payments"
    assert compliance["configuration_compliant"] is False
    assert compliance["policy_deviation_count"] == 1
    assert compliance["security_deviation_count"] == 1
    assert compliance["compliance_score"] == 40


def test_unknown_expected_configuration_is_not_reported_compliant():
    engine = change_engine()
    engine.context_builder._resources[next(iter(engine.context_builder._resources))]["expected_configuration"] = {}

    compliance = engine.analyze()["compliance"][0]

    assert compliance["configuration_compliant"] is None
    assert compliance["evidence_status"] == "Unknown"
