from remediation_scenario import remediation_planner


def test_approval_engine_applies_configurable_policies_and_stages():
    plan = remediation_planner().generate_plans()["plans"][0]
    approvals = plan["approval_requirements"]
    roles = {row["role"] for row in approvals}
    stages = {row["stage"] for row in approvals}

    assert {"Change Manager", "Application Owner", "Service Owner", "Support Team"} <= roles
    assert {"Development", "Test", "UAT", "Production"} <= stages
    assert all(row["status"] == "Required - Not Approved" for row in approvals)
    assert all(row["approval_evidence_required"] for row in approvals)


def test_nonproduction_plan_does_not_invent_production_owner_approvals():
    plans = remediation_planner().generate_plans()["plans"]
    test_plan = next(plan for plan in plans if plan["resource"]["name"] == "vm-catalog-test")
    roles = {row["role"] for row in test_plan["approval_requirements"]}

    assert "Change Manager" not in roles
    assert "Application Owner" not in roles
