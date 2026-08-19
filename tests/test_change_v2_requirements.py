from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from change_scenario import change_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from intelligence.change.baseline_engine import BaselineEngine
from intelligence.change.change_classifier import ChangeClassifier
from intelligence.change.change_collector import ChangeCollector
from intelligence.change.change_correlator import ChangeCorrelator
from intelligence.change.change_intelligence import ChangeIntelligence
from intelligence.change.change_summary import ChangeSummary
from intelligence.change.configuration_drift import DriftDetectionEngine
from ontology.ontology_validator import OntologyValidator
from semantic.semantic_engine import SemanticEngine

REQUESTED_COMMANDS = (
    "Analyze Changes",
    "Show Resource Changes",
    "Show Configuration Drift",
    "Show Policy Violations",
    "Show High Risk Changes",
    "Show Unapproved Changes",
    "Generate Change Report",
    "Show Change Timeline",
    "Explain Incident Changes",
    "Generate Risk Report",
)


def scenario():
    return json.loads(Path("tests/fixtures/sample_change_intelligence.json").read_text())


def test_exact_change_framework_modules_and_collection_classification():
    assert all(
        component is not None
        for component in (
            BaselineEngine,
            ChangeClassifier,
            ChangeCollector,
            ChangeCorrelator,
            ChangeSummary,
            DriftDetectionEngine,
        )
    )
    collected = ChangeCollector().collect(
        {
            "resource_changes": [
                {
                    "change_id": "c1",
                    "changed_fields": ["securityRules"],
                    "source": "Azure Resource Graph ResourceChanges",
                }
            ]
        }
    )
    assert collected[0]["category"] == "Network"
    assert ChangeClassifier().classify(
        {"changed_fields": ["roleAssignments"]}
    ) == "Identity"


def test_baseline_framework_supports_required_enterprise_resource_types():
    engine = BaselineEngine()
    required = {
        "VirtualMachine",
        "ArcServer",
        "NetworkSecurityGroup",
        "VirtualNetwork",
        "Subnet",
        "AzureFirewall",
        "RouteTable",
        "ApplicationGateway",
        "KeyVault",
        "StorageAccount",
        "SqlDatabase",
        "AksCluster",
        "AzureLocal",
    }
    assert required <= engine.SUPPORTED_RESOURCE_TYPES
    baseline = engine.create(
        baseline_id="BASE-1",
        resource_type="NetworkSecurityGroup",
        required_state={"publicAccess": "Disabled"},
        compliance_rules=["No internet ingress"],
        ownership_metadata={"owner": "Network Team"},
    )
    assert baseline["entity_type"] == "ConfigurationBaseline"
    assert baseline["auditable"] is True


def test_drift_engine_detects_security_network_identity_ownership_tag_and_policy_drift():
    result = DriftDetectionEngine().detect(
        expected={
            "owner": "team-a",
            "requiredTags": {"environment": "prod"},
            "nsgRules": [],
            "firewallOpen": False,
            "managedIdentity": "identity-a",
            "privateEndpoint": "pe-a",
            "policyExemption": False,
        },
        observed={
            "owner": None,
            "requiredTags": {},
            "nsgRules": ["Allow-Internet"],
            "firewallOpen": True,
            "managedIdentity": None,
            "privateEndpoint": None,
            "policyExemption": True,
        },
    )
    assert {
        "Ownership Drift",
        "Required Tag Removal",
        "NSG Rule Added",
        "Firewall Opened",
        "Managed Identity Removed",
        "Private Endpoint Removed",
        "Policy Exemption",
    } <= set(result["drift_types"])
    assert result["previous_state"]
    assert result["current_state"]
    assert result["evidence"]


def test_change_event_model_authorization_risk_explainability_and_compliance_aggregates():
    data = scenario()
    data["resources"][0]["dependency_count"] = 4
    data["resource_changes"][0].update(
        previous_state={"publicNetworkAccess": "Disabled"},
        current_state={"publicNetworkAccess": "Enabled"},
        approval_reference="CAB-2026-100",
        authorized=True,
    )
    engine = ChangeIntelligence.from_snapshot(
        **data, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )
    result = engine.analyze()
    finding = next(
        row for row in result["findings"] if row["change"]["change_id"] == "CHG-100"
    )

    assert finding["change"]["authorized"] is True
    assert finding["change"]["approval_reference"] == "CAB-2026-100"
    assert finding["previous_state"] == {"publicNetworkAccess": "Disabled"}
    assert finding["current_state"] == {"publicNetworkAccess": "Enabled"}
    assert finding["reasoning"]
    assert finding["risk_justification"]
    assert finding["business_impact"]
    assert finding["related_incidents"]
    assert finding["risk_factors"]["dependency_count"] > 0
    assert result["application_compliance"]
    assert result["business_service_compliance"]
    assert result["subscription_compliance"]


def test_timelines_and_incident_pattern_analysis_cover_required_windows():
    engine = change_engine()
    timelines = engine.timelines()

    assert set(timelines) == {"24_hour", "7_day", "30_day", "90_day"}
    assert timelines["24_hour"]["change_count"] >= 1
    incident = engine.explain_incident_changes()
    assert incident["changes_before_incidents"]
    assert incident["common_change_patterns"]
    assert incident["recurring_failure_causing_changes"]
    assert incident["confirmed_cause"] is False


def test_change_knowledge_projection_is_valid_and_contains_required_entities():
    data = scenario()
    data["resource_changes"][0].update(
        authorized=True, approval_reference="CAB-100"
    )
    data["network_changes"][0].update(authorized=False)
    engine = ChangeIntelligence.from_snapshot(
        **data, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )
    engine.analyze()
    projection = engine.knowledge_projection()
    entity_types = {row["entity_type"] for row in projection["entities"]}

    assert {
        "ChangeEvent",
        "ConfigurationBaseline",
        "ConfigurationDrift",
        "PolicyDeviation",
        "SecurityDeviation",
        "AuthorizedChange",
        "UnapprovedChange",
    } <= entity_types
    assert OntologyValidator().validate(
        projection["entities"], projection["relationships"]
    ).passed is True
    assert projection["read_only"] is True


def test_ten_agent_commands_are_registered_read_only_and_bounded():
    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert set(REQUESTED_COMMANDS) <= registered
    semantic = SemanticEngine.from_rows(**semantic_scenario())
    agent = OperationsAgent(semantic, change_intelligence=change_engine())

    for command in REQUESTED_COMMANDS:
        result = agent.analyze(
            command, "Enterprise", subject_type="ChangePortfolio"
        )
        serialized = json.dumps(result).casefold()
        assert result["read_only"] is True
        assert result["subject"]["entity_type"] == "ChangePortfolio"
        assert "/subscriptions/" not in serialized
        assert "action_result" not in serialized


def test_required_change_telemetry_contract_exists():
    telemetry = change_engine().telemetry

    assert telemetry.change_processing_duration is not None
    assert telemetry.drift_detection_duration is not None
    assert telemetry.risk_calculation_duration is not None
    assert telemetry.baseline_comparison_duration is not None
    assert telemetry.timeline_generation_duration is not None
