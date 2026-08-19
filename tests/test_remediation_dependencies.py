from remediation_scenario import remediation_planner


def test_dependency_analysis_includes_business_and_technical_context():
    plan = remediation_planner().generate_plans()["plans"][0]
    dependencies = plan["dependencies"]

    assert dependencies["affected_applications"] == ["Payments API"]
    assert dependencies["affected_services"] == ["Checkout"]
    assert dependencies["owners"] == ["Payments Product Owner"]
    assert dependencies["support_teams"] == ["Payments SRE"]
    assert dependencies["upstream_dependencies"] == ["API Gateway"]
    assert dependencies["downstream_dependencies"] == [
        "Ledger Writer",
        "Order Processor",
    ]
    assert dependencies["dependency_count"] == 3
    assert dependencies["traversal_bounded"] is True
