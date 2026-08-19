from __future__ import annotations

from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def test_incident_context_correlates_impact_ownership_risk_and_patch_evidence():
    agent = OperationsAgent(SemanticEngine.from_rows(**semantic_scenario()))

    result = agent.analyze(
        "Generate Incident Context",
        "vm-payments",
        subject_type="VirtualMachine",
    )
    incident = result["incident_context"]

    assert [row["name"] for row in incident["impacted_applications"]] == [
        "Payments"
    ]
    assert incident["owners"][0]["name"] == "ops@example.com"
    assert incident["support_teams"][0]["name"] == "SRE"
    assert incident["business_services"][0]["name"] == "Retail"
    assert incident["impacted_services"][0]["name"] == "Checkout"
    assert incident["blast_radius"]["application_count"] == 1
    assert incident["open_risks"]["level"] == "Critical"
    assert incident["risk"]["level"] == "Critical"
    assert incident["health"]["category"] in {
        "Healthy",
        "Warning",
        "Degraded",
        "Critical",
    }
    assert incident["patch_status"]["status"] == "failed"
    assert incident["advisor_findings"]
    assert incident["security_findings"]
    assert incident["affected_users_estimate"] == {
        "value": None,
        "basis": "No governed affected-user estimate is available in semantic evidence.",
    }
    assert incident["read_only"] is True
    assert result["recommendations"]
    assert all(item["advisory_only"] for item in result["recommendations"])
