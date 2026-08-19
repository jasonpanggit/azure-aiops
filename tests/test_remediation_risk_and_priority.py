from remediation_scenario import remediation_planner


def test_risk_assessment_is_explainable_and_bounded():
    plan = remediation_planner().generate_plans()["plans"][0]
    assessment = plan["risk_assessment"]

    for field in (
        "execution_risk",
        "operational_risk",
        "business_risk",
        "service_impact_risk",
    ):
        assert 0 <= assessment[field]["score"] <= 100
        assert assessment[field]["level"] in {"Low", "Moderate", "High", "Critical"}
        assert assessment[field]["drivers"]
    assert assessment["overall_risk"]["score"] <= 100


def test_priority_one_combines_reduction_criticality_dependencies_and_history():
    plans = remediation_planner().generate_plans()["plans"]
    payments = next(plan for plan in plans if plan["resource"]["name"] == "vm-payments")

    assert payments["priority"] == "Priority 1"
    assert payments["priority_score"] >= 75
    assert set(payments["priority_factors"]) >= {
        "expected_risk_reduction",
        "service_criticality",
        "dependency_count",
        "incident_history",
    }
