from remediation_scenario import remediation_planner


def test_dependency_analysis_includes_business_and_technical_context():
    plan = remediation_planner().generate_plans()["plans"][0]
    dependencies = plan["dependencies"]

    assert dependencies["affected_applications"] == ["Payroll"]
    assert dependencies["affected_services"] == ["Employee Pay"]
    assert dependencies["owners"] == ["Payroll Owner"]
    assert dependencies["support_teams"] == ["Enterprise Apps"]
    assert dependencies["upstream_dependencies"] == ["Identity"]
    assert dependencies["downstream_dependencies"] == ["Payroll Database"]
    assert dependencies["dependency_count"] == 2
    assert dependencies["traversal_bounded"] is True
