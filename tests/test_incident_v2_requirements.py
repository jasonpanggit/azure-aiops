from __future__ import annotations

import json

from incident_scenario import incident_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from intelligence.incidents.blast_radius_engine import BlastRadiusEngine
from intelligence.incidents.causality_graph import CausalityGraph
from intelligence.incidents.event_timeline import EventTimelineEngine
from intelligence.incidents.incident_correlator import IncidentCorrelator
from intelligence.incidents.incident_engine import IncidentEngine
from intelligence.incidents.incident_summary import IncidentSummary
from intelligence.incidents.operational_patterns import OperationalPatterns
from intelligence.incidents.root_cause_engine import RootCauseEngine
from onboarding.plugin import OPERATIONS_AGENT_SCHEMA
from ontology.ontology_validator import OntologyValidator
from semantic.semantic_engine import SemanticEngine

REQUESTED_COMMANDS = (
    "Analyze Incident",
    "Explain Root Cause",
    "Show Blast Radius",
    "Show Dependency Chain",
    "Show Operational Timeline",
    "Show Recent Causes",
    "Show Repeated Operational Risks",
    "Generate Incident Report",
)


def test_exact_plural_incident_framework_modules_and_normalized_events():
    assert all(
        component is not None
        for component in (
            IncidentEngine,
            IncidentCorrelator,
            RootCauseEngine,
            BlastRadiusEngine,
            EventTimelineEngine,
            OperationalPatterns,
            IncidentSummary,
            CausalityGraph,
        )
    )
    timeline = EventTimelineEngine()
    events = timeline.normalize(
        incidents=[{"incident_id": "i", "started_at": "2026-08-18T12:00:00Z"}],
        alerts=[{"alert_id": "a", "fired_at": "2026-08-18T11:50:00Z", "source": "Advisor"}],
        changes=[
            {"change_id": "c1", "change_type": "Create", "changed_at": "2026-08-18T10:00:00Z"},
            {"change_id": "c2", "change_type": "Delete", "changed_at": "2026-08-18T10:10:00Z"},
            {"change_id": "c3", "change_type": "Update", "changed_at": "2026-08-18T10:20:00Z", "changed_fields": ["owner"]},
        ],
        patch=[
            {"finding_id": "p1", "status": "Failed", "observed_at": "2026-08-18T09:00:00Z"},
            {"finding_id": "p2", "status": "Succeeded", "observed_at": "2026-08-18T09:10:00Z"},
        ],
        lifecycle=[{"finding_id": "e", "status": "EOL", "observed_at": "2026-08-18T08:00:00Z"}],
    )
    event_types = {event["event_type"] for event in events}
    assert {
        "Incident",
        "Advisor Alert",
        "Resource Created",
        "Resource Deleted",
        "Ownership Change",
        "Patch Failure",
        "Patch Success",
        "OS EOL Threshold Crossed",
    } <= event_types


def test_incident_engine_adds_timeline_root_cause_blast_radius_and_business_impact():
    result = IncidentEngine.from_intelligence(incident_engine()).analyze()
    finding = result["findings"][0]

    assert finding["related_events"]
    assert finding["timeline"] == sorted(
        finding["timeline"], key=lambda event: (event["timestamp"], event["event_id"])
    )
    assert finding["reasoning_chain"]
    assert finding["root_cause_analysis"]["confirmed_cause"] is False
    assert finding["root_cause_analysis"]["probable_causes"]
    assert finding["blast_radius"]["dependency_tree"]
    assert finding["blast_radius"]["owners"] == ["ops@example.com"]
    assert finding["business_impact"]["applications"]
    assert finding["business_impact"]["business_services"]
    assert finding["business_impact"]["patch_score"] is not None
    assert finding["business_impact"]["lifecycle_score"] is not None


def test_patterns_and_audience_summaries_are_evidence_backed():
    engine = IncidentEngine.from_intelligence(incident_engine())
    result = engine.analyze()

    pattern_types = {row["pattern_type"] for row in result["operational_patterns"]}
    assert "Recurring Risk" in pattern_types
    patch_patterns = OperationalPatterns().detect(
        [
            {"event_type": "Patch Failure", "event_id": "p1", "_resource_key": "r1"},
            {"event_type": "Patch Failure", "event_id": "p2", "_resource_key": "r1"},
        ],
        [],
    )
    assert patch_patterns[0]["pattern_type"] == "Repeated Patch Failure"
    subscription_patterns = OperationalPatterns().detect(
        [],
        [
            {"incident": {"incident_id": "i1"}, "owner": "Team A", "subscription_alias": "Production"},
            {"incident": {"incident_id": "i2"}, "owner": "Team B", "subscription_alias": "Production"},
        ],
    )
    assert any(
        row["pattern_type"] == "Subscription Degradation"
        for row in subscription_patterns
    )
    summaries = result["summaries"]
    assert set(summaries) == {"engineer", "manager", "director", "cio"}
    assert all(summary["evidence"] for summary in summaries.values())
    assert all(
        {
            "technical_summary",
            "executive_summary",
            "root_cause_summary",
        }
        <= summary.keys()
        for summary in summaries.values()
    )


def test_incident_knowledge_projection_contains_required_valid_entities():
    engine = IncidentEngine.from_intelligence(incident_engine())
    engine.analyze()
    projection = engine.knowledge_projection()
    entity_types = {row["entity_type"] for row in projection["entities"]}

    assert {
        "Incident",
        "OperationalEvent",
        "RootCause",
        "RiskPattern",
        "BlastRadius",
        "DependencyChain",
        "OperationalFinding",
    } <= entity_types
    assert OntologyValidator().validate(
        projection["entities"], projection["relationships"]
    ).passed is True
    assert projection["read_only"] is True


def test_eight_agent_commands_are_registered_scoped_and_read_only():
    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert set(REQUESTED_COMMANDS) <= registered
    semantic = SemanticEngine.from_rows(**semantic_scenario())
    agent = OperationsAgent(semantic, incident_intelligence=incident_engine())

    incident_commands = REQUESTED_COMMANDS[:5]
    for command in incident_commands:
        result = agent.analyze(command, "INC-100", subject_type="Incident")
        serialized = json.dumps(result).casefold()
        assert result["read_only"] is True
        assert result["subject"]["entity_type"] == "Incident"
        assert "/subscriptions/" not in serialized
        assert "action_result" not in serialized

    for command in REQUESTED_COMMANDS[5:]:
        result = agent.analyze(
            command, "Enterprise", subject_type="IncidentPortfolio"
        )
        assert result["read_only"] is True
        if command == "Generate Incident Report":
            assert result["incident_intelligence"]["audience_summaries"]


def test_required_incident_telemetry_contract_exists():
    telemetry = incident_engine().telemetry

    assert telemetry.correlation_latency is not None
    assert telemetry.timeline_generation_duration is not None
    assert telemetry.blast_radius_generation_duration is not None
    assert telemetry.root_cause_analysis_duration is not None
    assert telemetry.knowledge_retrieval_latency is not None
    assert telemetry.pattern_detection_duration is not None
