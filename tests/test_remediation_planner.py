from remediation_scenario import remediation_planner


def test_planner_generates_complete_approval_ready_plans_from_catalog():
    result = remediation_planner().generate_plans()

    assert result["read_only"] is True
    assert result["execution_performed"] is False
    assert len(result["plans"]) >= 3
    plan = result["plans"][0]
    assert plan["plan_id"].startswith("RMP-")
    assert plan["status"] == "Draft - Approval Required"
    assert plan["execution_steps"]
    assert plan["evidence"]
    assert plan["risk_drivers"]
    assert plan["recommended_action"]["advisory_only"] is True
    assert plan["execution_authorized"] is False


def test_opportunities_cover_patch_lifecycle_configuration_and_predictive_risk():
    opportunities = remediation_planner().identify_opportunities()["opportunities"]
    kinds = {row["opportunity_type"] for row in opportunities}

    assert "Patch and vulnerability debt" in kinds
    assert "Lifecycle and modernization debt" in kinds
    assert "Configuration and policy debt" in kinds
    assert any(row["predictive_risk_score"] >= 75 for row in opportunities)
