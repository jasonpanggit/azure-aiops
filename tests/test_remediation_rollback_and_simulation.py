from remediation_scenario import remediation_planner


def test_every_plan_has_reversible_rollback_contract():
    for plan in remediation_planner().generate_plans()["plans"]:
        rollback = plan["rollback_plan"]
        assert rollback["preconditions"]
        assert rollback["rollback_actions"]
        assert rollback["validation_steps"]
        assert rollback["success_criteria"]
        assert rollback["failure_criteria"]
        assert rollback["reversible"] is True
        assert rollback["automatic_rollback"] is False


def test_simulation_estimates_reduction_without_execution():
    plan = remediation_planner().generate_plans()["plans"][0]
    simulation = plan["simulation_result"]

    assert 0 <= simulation["risk_reduction_percent"] <= 100
    assert 0 <= simulation["compliance_improvement_percent"] <= 100
    assert 0 <= simulation["lifecycle_exposure_reduction_percent"] <= 100
    assert 0 <= simulation["operational_debt_reduction_percent"] <= 100
    assert simulation["business_impact"] in {"Low", "Moderate", "High", "Critical"}
    assert simulation["simulation_only"] is True
    assert simulation["changes_executed"] is False
