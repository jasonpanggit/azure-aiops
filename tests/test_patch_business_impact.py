from __future__ import annotations

from patch_scenario import patch_engine


def test_patch_failure_correlates_resource_to_business_ownership_chain():
    impacts = patch_engine().query("Show business impact")["result"]
    payroll = next(item for item in impacts if item["application"] == "Payroll")

    assert payroll == {
        "patch_failure": True,
        "resource": {"name": "vm-payroll-01", "entity_type": "VirtualMachine"},
        "application": "Payroll",
        "business_service": "HR Services",
        "owner": "hr-platform@example.com",
        "support_team": "HR Operations",
        "impact_level": "Critical",
        "blast_radius": {
            "affected_resource_count": 1,
            "affected_resources": ["vm-payroll-01"],
            "application_count": 1,
            "business_service_count": 1,
            "service_count": 0,
        },
    }


def test_business_service_exposure_identifies_most_exposed_service():
    exposure = patch_engine().analyze()["exposure"]["business_exposure"]

    assert exposure[0]["name"] == "HR Services"
    assert exposure[0]["risk_score"] >= 75
