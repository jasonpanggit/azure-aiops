from __future__ import annotations

from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from operations.operational_reasoner import OperationalReasoner
from operations.operational_summary import OperationalSummary
from semantic.semantic_engine import SemanticEngine

MODULES = (
    "operations_agent",
    "operational_reasoner",
    "context_router",
    "recommendation_engine",
    "incident_analyzer",
    "impact_analyzer",
    "health_analyzer",
    "compliance_analyzer",
    "ownership_analyzer",
    "operational_summary",
)

COMMANDS = {
    "Analyze VM",
    "Analyze Application",
    "Analyze Subscription",
    "Analyze Business Service",
    "Show Operational Risk",
    "Show Patch Compliance",
    "Show Health Summary",
    "Show Impact Summary",
    "Executive Summary",
}


def _agent(**kwargs) -> OperationsAgent:
    return OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        **kwargs,
    )


def test_exact_operations_core_modules_exist():
    for module in MODULES:
        __import__(f"operations.{module}")


def test_exact_operations_core_commands_are_registered_and_executable():
    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert COMMANDS <= registered

    operations = _agent()
    requests = (
        ("Analyze VM", "vm-payments", "VirtualMachine"),
        ("Analyze Application", "Payments", "Application"),
        ("Analyze Subscription", "sub-1", "Subscription"),
        ("Analyze Business Service", "Retail", "BusinessService"),
        ("Show Operational Risk", "vm-payments", "VirtualMachine"),
        ("Show Patch Compliance", "vm-payments", "VirtualMachine"),
        ("Show Health Summary", "Retail", "BusinessService"),
        ("Show Impact Summary", "vm-payments", "VirtualMachine"),
        ("Executive Summary", "Payments", "Application"),
    )
    for command, subject, subject_type in requests:
        result = operations.analyze(command, subject, subject_type=subject_type)
        assert result["command"] == command
        assert result["read_only"] is True
        assert result["conclusions"]
        for conclusion in result["conclusions"]:
            assert conclusion["evidence"]
            assert conclusion["data_sources"]
            assert conclusion["reasoning"]
            assert "risk_factors" in conclusion


def test_operational_domains_health_and_recommendation_contract():
    result = _agent().analyze("Analyze VM", "vm-payments")
    assert set(result["operational_domains"]) == {
        "Infrastructure Health",
        "Patch Compliance",
        "Security Exposure",
        "Ownership Coverage",
        "Application Dependencies",
        "Business Impact",
        "Operational Risk",
        "Cost Optimization",
        "Lifecycle Management",
        "Governance",
    }
    assert 0 <= result["health"]["score"] <= 100
    assert result["health"]["category"] in {
        "Healthy",
        "Warning",
        "Degraded",
        "Critical",
    }
    for item in result["recommendations"]:
        assert {
            "priority",
            "impact",
            "confidence",
            "rationale",
            "suggested_action",
            "evidence",
            "advisory_only",
        } <= item.keys()
        assert item["advisory_only"] is True
        assert 0 <= item["confidence"] <= 1


def test_health_scoring_supports_required_operational_scopes():
    operations = _agent()
    for subject, subject_type in (
        ("Checkout", "Service"),
        ("sub-1", "Subscription"),
        ("Production", "Environment"),
        ("Retail", "BusinessService"),
    ):
        result = operations.analyze(
            "Show Health Summary", subject, subject_type=subject_type
        )
        assert 0 <= result["health"]["score"] <= 100
        assert result["health"]["category"] in {
            "Healthy",
            "Warning",
            "Degraded",
            "Critical",
        }


def test_explicit_reasoning_workflows_use_semantic_layer_only():
    reasoner = OperationalReasoner(
        SemanticEngine.from_rows(**semantic_scenario())
    )
    patch = reasoner.analyze_patch_failure(
        "vm-payments", subject_type="VirtualMachine"
    )
    ownership = reasoner.analyze_ownership(
        "vm-payments", subject_type="VirtualMachine"
    )
    dependencies = reasoner.analyze_dependencies(
        "vm-payments", subject_type="VirtualMachine"
    )
    risk = reasoner.analyze_risk(
        "vm-payments", subject_type="VirtualMachine"
    )

    assert patch["compliance"]["status"] == "failed"
    assert patch["impact"]["impacted_applications"]
    assert ownership["coverage"] == "Covered"
    assert dependencies["impacted_applications"]
    assert risk["risk"]["level"] == "Critical"
    assert all(item["read_only"] is True for item in (patch, ownership, dependencies, risk))


def test_summary_generation_latency_is_recorded():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.analysis_duration = Instrument()
            self.recommendation_latency = Instrument()
            self.knowledge_retrieval_latency = Instrument()
            self.summary_generation_latency = Instrument()
            self.impact_duration = Instrument()
            self.context_generation_latency = Instrument()

    telemetry = Telemetry()
    _agent(telemetry=telemetry).analyze(
        "Executive Summary", "Payments", subject_type="Application"
    )
    assert telemetry.summary_generation_latency.records


def test_operational_summary_covers_required_technical_audiences():
    generator = OperationalSummary()
    expected = {
        "Analyze Subscription": "Subscription Summary",
        "Analyze Application": "Application Summary",
        "Analyze Business Service": "Service Summary",
        "Show Patch Compliance": "Patch Compliance Summary",
        "Generate Incident Context": "Incident Summary",
    }
    for command, summary_type in expected.items():
        summary = generator.generate(
            {
                "command": command,
                "subject": {"name": "subject", "entity_type": "Resource"},
                "risk": {"level": "Unknown"},
                "health": {"category": "Warning"},
                "recommendations": [],
                "conclusions": [],
            }
        )
        assert summary["summary_type"] == summary_type
