from __future__ import annotations

from lifecycle_scenario import lifecycle_engine


def test_business_impact_correlates_server_application_service_owner_and_team():
    payroll = next(
        item
        for item in lifecycle_engine().analyze()["findings"]
        if item["resource"]["name"] == "vm-payroll-legacy"
    )

    assert payroll["resource"] == {
        "name": "vm-payroll-legacy",
        "entity_type": "VirtualMachine",
    }
    assert payroll["application"] == "Payroll"
    assert payroll["business_service"] == "Finance Operations"
    assert payroll["owner"] == "finance-platform@example.com"
    assert payroll["support_team"] == "Finance SRE"
    assert payroll["business_impact"] == "Critical"


def test_lifecycle_exposure_rolls_up_all_required_operational_dimensions():
    exposure = lifecycle_engine().analyze()["exposure"]

    assert exposure["total_eol_assets"] == 2
    assert exposure["assets_with_no_upgrade_plan"] == 1
    assert exposure["lifecycle_debt_score"] == 250
    assert exposure["business_services_at_risk"] == 3
    assert set(exposure) >= {
        "by_subscription",
        "by_business_service",
        "by_environment",
        "by_application",
        "by_region",
        "by_operating_system",
    }
    assert exposure["by_business_service"][0]["name"] == "Finance Operations"
