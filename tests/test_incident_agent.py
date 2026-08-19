from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pytest
from incident_scenario import incident_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from intelligence.incident.incident_intelligence import IncidentIntelligence
from semantic.semantic_engine import SemanticEngine


def test_incident_commands_are_bounded_read_only_and_advisory():
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        incident_intelligence=incident_engine(),
    )
    commands = (
        "Analyze Incident Causality",
        "Show Probable Root Causes",
        "Show Incident Blast Radius",
        "Show Correlated Incidents",
        "Show Recurring Incident Patterns",
        "Generate Incident Correlation Report",
        "Generate Incident Executive Brief",
    )

    for command in commands:
        result = operations.analyze(
            command, "Enterprise", subject_type="IncidentPortfolio"
        )
        serialized = json.dumps(result)
        assert result["subject"] == {
            "name": "Enterprise",
            "entity_type": "IncidentPortfolio",
        }
        assert result["read_only"] is True
        assert all(item["advisory_only"] for item in result["recommendations"])
        assert "/subscriptions/" not in serialized.casefold()

    with pytest.raises(ValueError, match="pre-authorized enterprise incident portfolio"):
        operations.analyze(
            "Analyze Incident Causality", "INC-100", subject_type="Incident"
        )


def test_incident_agent_redacts_identifiers_embedded_in_values():
    scenario = json.loads(
        Path("tests/fixtures/sample_incident_causality.json").read_text()
    )
    scenario["alerts"][0]["alert_id"] = (
        "/subscriptions/SECRET/resourceGroups/rg/providers/x/alerts/a1"
    )
    scenario["alerts"][0]["title"] = "TENANT-SECRET RUN-SECRET unavailable"
    secret_guid = "5ef7423a-80d9-4c44-ae0f-058600202e4a"
    encoded_arm = quote(
        quote(f"/subscriptions/{secret_guid}/resourceGroups/rg/providers/x/a")
    )
    scenario["alerts"][1]["alert_id"] = encoded_arm
    scenario["alerts"][1]["title"] = (
        f"Tenant ID: {secret_guid}; Subscription ID={secret_guid}; Run ID: {secret_guid}"
    )
    engine = IncidentIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        incident_intelligence=engine,
    )

    serialized = json.dumps(
        operations.analyze(
            "Analyze Incident Causality",
            "Enterprise",
            subject_type="IncidentPortfolio",
        )
    )

    assert "/subscriptions/secret" not in serialized.casefold()
    assert "tenant-secret" not in serialized.casefold()
    assert "run-secret" not in serialized.casefold()
    assert secret_guid not in serialized.casefold()
    assert "%252fsubscriptions" not in serialized.casefold()
