from __future__ import annotations

from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def agent() -> OperationsAgent:
    return OperationsAgent(SemanticEngine.from_rows(**semantic_scenario()))


def test_domain_commands_generate_named_operational_summaries():
    operations = agent()
    cases = (
        ("Analyze Subscription", "sub-1", "", "Subscription Summary"),
        ("Analyze Application", "Payments", "", "Application Summary"),
        ("Analyze Business Service", "Retail", "", "Service Summary"),
        ("Analyze Patch Compliance", "vm-payments", "", "Patch Compliance Summary"),
        ("Analyze Operational Risk", "vm-payments", "", "Risk Summary"),
        ("Analyze VM", "vm-payments", "", "VM Summary"),
        (
            "Show Health Summary",
            "Retail",
            "BusinessService",
            "Health Summary",
        ),
        (
            "Show Impact Summary",
            "vm-payments",
            "VirtualMachine",
            "Impact Summary",
        ),
        (
            "Generate Executive Summary",
            "Payments",
            "Application",
            "Executive Risk Summary",
        ),
    )

    for command, subject, subject_type, summary_type in cases:
        result = operations.analyze(command, subject, subject_type=subject_type)
        assert result["summary"]["summary_type"] == summary_type
        assert result["summary"]["headline"]
        assert result["summary"]["read_only"] is True


def test_executive_summary_contains_prioritized_advisory_actions():
    result = agent().analyze(
        "Generate Executive Summary", "Payments", subject_type="Application"
    )

    assert result["summary"]["priority_actions"]
    assert all(
        recommendation["advisory_only"]
        for recommendation in result["recommendations"]
    )
