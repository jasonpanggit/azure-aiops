from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from patch_scenario import patch_engine
from semantic_scenario import semantic_scenario

from fabric.config import FabricRuntimeConfig
from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from intelligence.incident.incident_intelligence import IncidentIntelligence
from operations.compliance_analyzer import ComplianceAnalyzer
from operations.context_router import SUPPORTED_COMMANDS
from operations.health_analyzer import HealthAnalyzer
from operations.impact_analyzer import ImpactAnalyzer
from operations.incident_analyzer import IncidentAnalyzer
from operations.operational_reasoner import OperationalReasoner
from operations.operational_summary import OperationalSummary
from operations.operations_agent import OperationsAgent
from operations.ownership_analyzer import OwnershipAnalyzer
from operations.recommendation_engine import RecommendationEngine
from semantic.semantic_engine import SemanticEngine


def test_operations_agent_bounds_require_exact_positive_integers():
    class Semantic:
        pass

    for name, value in (
        ("max_output_items", True),
        ("max_output_items", 0),
        ("max_serialized_bytes", 1.5),
        ("max_serialized_bytes", -1),
    ):
        with pytest.raises((TypeError, ValueError)):
            OperationsAgent(Semantic(), **{name: value})
    agent = OperationsAgent(
        Semantic(), max_output_items=25, max_serialized_bytes=250_000
    )
    assert agent.max_output_items == 25
    assert agent.max_serialized_bytes == 250_000


def test_operations_runtime_configuration_exposes_strict_output_bounds(tmp_path):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  operations_agent:
    max_output_items: 75
    max_serialized_bytes: 750000
"""
    )
    config = FabricRuntimeConfig.load(path).operations_agent
    assert config.max_output_items == 75
    assert config.max_serialized_bytes == 750000

    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  operations_agent:
    max_output_items: true
"""
    )
    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)


def test_public_operations_output_redacts_encoded_identifiers():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b64encode(arm_id.encode()).decode()

    class Semantic:
        def get_resource_context(self, *_args, **_kwargs):
            return {
                "context_type": "resource",
                "subject": {
                    "name": f"id={encoded}",
                    "entity_type": "VirtualMachine",
                },
                "sections": {},
                "section_metadata": {},
                "freshness": "2026-08-18T00:00:00Z",
                "knowledge_version": "semantic-test",
            }

    result = OperationsAgent(Semantic()).analyze("Analyze VM", "server")
    serialized = json.dumps(result).casefold()
    assert encoded.casefold() not in serialized
    assert "secret-rg" not in serialized


def test_operations_serialized_output_ceiling_fails_closed():
    class Semantic:
        def get_resource_context(self, *_args, **_kwargs):
            return {
                "context_type": "resource",
                "subject": {
                    "name": "x" * 10_000,
                    "entity_type": "VirtualMachine",
                },
                "sections": {},
                "section_metadata": {},
            }

    with pytest.raises(ValueError, match="output exceeds"):
        OperationsAgent(Semantic(), max_serialized_bytes=1024).analyze(
            "Analyze VM", "server"
        )


def test_missing_risk_evidence_remains_unknown_not_low():
    class Semantic:
        pass

    result = OperationalReasoner(Semantic()).analyze_context(
        {
            "context_type": "resource",
            "subject": {"name": "server", "entity_type": "VirtualMachine"},
            "sections": {},
            "section_metadata": {},
        },
        command="Analyze VM",
    )
    assert result["risk"]["score"] is None
    assert result["risk"]["level"] == "Unknown"


def test_core_analyzers_fail_closed_on_malformed_semantic_shapes():
    with pytest.raises((TypeError, ValueError)):
        HealthAnalyzer().analyze({"risk": {"score": True}, "sections": {}})
    with pytest.raises((TypeError, ValueError)):
        ComplianceAnalyzer().analyze(
            {"sections": {"compliance": {"failed_patch_count": True}}}
        )
    with pytest.raises((TypeError, ValueError)):
        OwnershipAnalyzer().analyze({"sections": {"ownership": "owner@example.com"}})
    with pytest.raises((TypeError, ValueError)):
        RecommendationEngine().generate(
            risk={"score": True},
            health={},
            compliance={"status": "unknown", "compliant": False},
            ownership={"coverage": "Unknown"},
            context={"sections": {}},
        )
    with pytest.raises((TypeError, ValueError)):
        ImpactAnalyzer(object(), max_results=True)

    class MalformedImpact:
        def get_impact_context(self, *_args, **_kwargs):
            return []

    with pytest.raises(TypeError):
        ImpactAnalyzer(MalformedImpact()).analyze("server")


def test_reasoner_rejects_malformed_context_collections():
    class Semantic:
        pass

    with pytest.raises(TypeError):
        OperationalReasoner(Semantic()).analyze_context(
            {
                "context_type": "resource",
                "subject": {"name": "server", "entity_type": "VirtualMachine"},
                "sections": {"applications": "not-a-list"},
                "section_metadata": {},
            },
            command="Analyze VM",
        )


def test_incident_context_uses_governed_affected_user_estimate_when_available():
    class Impact:
        def analyze(self, *_args, **_kwargs):
            return {
                "impacted_applications": [],
                "impacted_services": [],
                "impacted_business_services": [],
                "dependency_tree": {},
                "blast_radius": {},
                "evidence": {},
            }

    result = IncidentAnalyzer(Impact()).build(
        "server",
        {
            "subject": {"name": "server", "entity_type": "VirtualMachine"},
            "sections": {
                "affected_users_estimate": {
                    "value": 1250,
                    "basis": "Governed application telemetry projection",
                }
            },
        },
    )
    assert result["affected_users_estimate"] == {
        "value": 1250,
        "basis": "Governed application telemetry projection",
    }


def test_governance_findings_generate_advisory_recommendation():
    recommendations = RecommendationEngine().generate(
        risk={"score": 10, "level": "Low", "factors": {}},
        health={"score": 90},
        compliance={"status": "unknown", "compliant": False},
        ownership={"coverage": "Covered"},
        context={
            "sections": {
                "governance_findings": [
                    {"name": "Required production tag is missing"}
                ]
            }
        },
    )
    governance = next(
        item for item in recommendations if "governance" in item["evidence"]
    )
    assert governance["advisory_only"] is True
    assert governance["priority"] == "Medium"


def test_operational_summary_supports_incident_technical_summary():
    summary = OperationalSummary().generate(
        {
            "command": "Generate Incident Context",
            "subject": {"name": "server", "entity_type": "VirtualMachine"},
            "risk": {"level": "High"},
            "health": {"category": "Degraded"},
            "conclusions": [{"reasoning": "Observed patch failure", "evidence": [{}]}],
            "recommendations": [],
        }
    )
    assert summary["summary_type"] == "Incident Summary"
    assert summary["read_only"] is True


def test_public_operations_output_redacts_base32_identifiers():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b32encode(arm_id.encode()).decode()

    class Semantic:
        def get_resource_context(self, *_args, **_kwargs):
            return {
                "context_type": "resource",
                "subject": {"name": encoded, "entity_type": "VirtualMachine"},
                "sections": {},
                "section_metadata": {},
            }

    serialized = json.dumps(
        OperationsAgent(Semantic()).analyze("Analyze VM", "server")
    ).casefold()
    assert encoded.casefold() not in serialized


def test_empty_evidence_cannot_be_reported_healthy():
    result = HealthAnalyzer().analyze(
        {
            "risk": {
                "score": None,
                "level": "Unknown",
                "evidence_available": False,
            },
            "sections": {
                "resource_health": {},
                "compliance": {},
                "security_findings": [],
                "ownership": [{"name": "owner@example.com"}],
            },
        }
    )
    assert result["category"] != "Healthy"
    assert result["evidence_coverage"] != "Complete"
    assert result["unknowns"]


def test_impact_missing_risk_remains_unknown():
    class Semantic:
        def get_impact_context(self, *_args, **_kwargs):
            return {
                "root": {"name": "server", "entity_type": "VirtualMachine"},
                "impacted_applications": [],
                "impacted_business_services": [],
                "impacted_services": [],
            }

        def get_risk_context(self, *_args, **_kwargs):
            return {"risk": {}}

    result = ImpactAnalyzer(Semantic()).analyze("server")
    assert result["criticality"]["risk_level"] == "Unknown"


def test_reasoner_rejects_malformed_risk_shape():
    class Semantic:
        pass

    with pytest.raises((TypeError, ValueError)):
        OperationalReasoner(Semantic()).analyze_context(
            {
                "context_type": "resource",
                "subject": {"name": "server", "entity_type": "VirtualMachine"},
                "risk": {"score": 10, "level": ["Critical"], "factors": {}},
                "sections": {},
                "section_metadata": {},
            },
            command="Analyze VM",
        )


def test_empty_findings_cannot_generate_supported_recommendations():
    with pytest.raises(ValueError, match="finding"):
        RecommendationEngine().generate(
            risk={"score": 0, "level": "Low", "factors": {}},
            health={},
            compliance={"status": "unknown", "compliant": False},
            ownership={"coverage": "Covered"},
            context={
                "sections": {
                    "security_findings": [{}],
                    "governance_findings": [{}],
                }
            },
        )


def test_duplicate_semantic_evidence_does_not_inflate_counts_or_deductions():
    finding = {"name": "CVE-X"}
    health = HealthAnalyzer().analyze(
        {
            "risk": {"score": 0, "level": "Low"},
            "sections": {"security_findings": [finding, dict(finding)]},
        }
    )
    assert health["deductions"]["security_exposure"] == 10

    row = {"status": "failed", "failed_patch_count": 2}
    compliance = ComplianceAnalyzer().analyze(
        {"sections": {"compliance": [row, dict(row)]}}
    )
    assert compliance["failed_patch_count"] == 2


def test_patch_compliance_aliases_share_core_vm_behavior_when_patch_layer_enabled():
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()),
        patch_intelligence=patch_engine(),
    )
    analyze = operations.analyze(
        "Analyze Patch Compliance", "vm-payments", subject_type="VirtualMachine"
    )
    show = operations.analyze(
        "Show Patch Compliance", "vm-payments", subject_type="VirtualMachine"
    )
    assert analyze["compliance"] == show["compliance"]
    assert analyze["subject"] == show["subject"]


def test_router_plugin_and_wheel_package_surfaces_are_aligned():
    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )
    assert registered == set(SUPPORTED_COMMANDS)
    assert '"src/operations"' in Path("pyproject.toml").read_text()


def test_public_operations_output_sanitizes_mapping_keys():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b32encode(arm_id.encode()).decode()

    class Semantic:
        def get_resource_context(self, *_args, **_kwargs):
            return {
                "context_type": "resource",
                "subject": {"name": "server", "entity_type": "VirtualMachine"},
                "risk": {
                    "score": 10,
                    "level": "Low",
                    "factors": {encoded: 10},
                    "evidence_available": True,
                },
                "sections": {},
                "section_metadata": {},
            }

    serialized = json.dumps(
        OperationsAgent(Semantic()).analyze("Analyze VM", "server")
    ).casefold()
    assert encoded.casefold() not in serialized
    assert "secret-rg" not in serialized


@pytest.mark.parametrize(
    "risk",
    [
        [],
        {"score": 1, "level": "Low", "factors": [], "evidence_available": True},
    ],
)
def test_falsy_malformed_risk_values_fail_closed(risk):
    class Semantic:
        pass

    with pytest.raises((TypeError, ValueError)):
        OperationalReasoner(Semantic()).analyze_context(
            {
                "context_type": "resource",
                "subject": {"name": "server", "entity_type": "VirtualMachine"},
                "risk": risk,
                "sections": {},
                "section_metadata": {},
            },
            command="Analyze VM",
        )


def test_public_key_sanitization_collisions_fail_closed():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b32encode(arm_id.encode()).decode()
    safe_key = IncidentIntelligence._safe_identifier(encoded, "field")

    class Semantic:
        def get_resource_context(self, *_args, **_kwargs):
            return {
                "context_type": "resource",
                "subject": {"name": "server", "entity_type": "VirtualMachine"},
                "risk": {
                    "score": 100,
                    "level": "Critical",
                    "factors": {encoded: 1, safe_key: 99},
                    "evidence_available": True,
                },
                "sections": {},
                "section_metadata": {},
            }

    with pytest.raises(ValueError, match="key collision"):
        OperationsAgent(Semantic()).analyze("Analyze VM", "server")
