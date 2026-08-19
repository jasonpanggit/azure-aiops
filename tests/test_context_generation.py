from __future__ import annotations

from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def agent() -> OperationsAgent:
    return OperationsAgent(SemanticEngine.from_rows(**semantic_scenario()))


def test_all_required_agent_commands_are_routable():
    operations = agent()
    cases = (
        ("Analyze VM", "vm-payments", ""),
        ("Analyze Application", "Payments", ""),
        ("Analyze Subscription", "sub-1", ""),
        ("Analyze Business Service", "Retail", ""),
        ("Analyze Operational Risk", "vm-payments", ""),
        ("Analyze Patch Compliance", "vm-payments", ""),
        ("Show Health Summary", "Retail", "BusinessService"),
        ("Show Impact Summary", "vm-payments", "VirtualMachine"),
        ("Generate Executive Summary", "Payments", "Application"),
        ("Generate Incident Context", "vm-payments", "VirtualMachine"),
    )

    for command, subject, subject_type in cases:
        result = operations.analyze(command, subject, subject_type=subject_type)
        assert result["command"] == command
        assert result["read_only"] is True


def test_environment_health_uses_semantic_environment_context():
    result = agent().analyze(
        "Show Health Summary", "Production", subject_type="Environment"
    )

    assert result["subject"] == {
        "entity_type": "Environment",
        "name": "Production",
        "lifecycle_status": "active",
    }
    assert result["health"]["score"] <= 100
    assert result["health"]["category"] in {
        "Healthy",
        "Warning",
        "Degraded",
        "Critical",
    }
    assert result["freshness"] == "2026-08-17T00:00:00Z"


def test_empty_service_health_is_warning_with_limited_evidence_not_healthy():
    semantic = SemanticEngine.from_rows(
        entities=[
            {
                "resource_id": "empty-service",
                "entity_type": "Service",
                "name": "Empty Service",
                "lifecycle_status": "active",
            }
        ],
        relationships=[],
    )

    result = OperationsAgent(semantic).analyze(
        "Show Health Summary", "Empty Service", subject_type="Service"
    )

    assert result["health"]["score"] == 60
    assert result["health"]["category"] == "Warning"
    assert result["health"]["evidence_coverage"] == "Limited"
    assert "resource_health" in result["health"]["unknowns"]
