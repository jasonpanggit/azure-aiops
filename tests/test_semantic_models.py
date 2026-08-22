from __future__ import annotations

from semantic.semantic_models import SemanticContext, SemanticEntity
from semantic.semantic_registry import SemanticRegistry
from semantic.semantic_validator import SemanticValidator


def test_default_registry_contains_all_domain_models():
    registry = SemanticRegistry.default()

    assert set(registry.names()) == {
        "Application",
        "Service",
        "Infrastructure",
        "Compliance",
        "Patching",
        "Ownership",
        "BusinessImpact",
        "ResourceHealth",
        "OperationalRisk",
        "Dependencies",
        "Lifecycle",
        "Cost",
        "Security",
        "Network",
    }
    assert registry.get("Application").sources == (
        "ontology_entities",
        "ontology_relationships",
        "inventory",
        "compliance",
    )
    assert {name: registry.get(name).model_type.__name__ for name in registry.names()} == {
        "Application": "ApplicationKnowledge",
        "Service": "ServiceKnowledge",
        "Infrastructure": "InfrastructureKnowledge",
        "Compliance": "ComplianceKnowledge",
        "Patching": "PatchingKnowledge",
        "Ownership": "OwnershipKnowledge",
        "BusinessImpact": "BusinessImpactKnowledge",
        "ResourceHealth": "ResourceHealthKnowledge",
        "OperationalRisk": "OperationalRiskKnowledge",
        "Dependencies": "DependenciesKnowledge",
        "Lifecycle": "LifecycleKnowledge",
        "Cost": "CostKnowledge",
        "Security": "SecurityKnowledge",
        "Network": "NetworkKnowledge",
    }
    model = registry.build(
        "Application",
        SemanticEntity("Application", "Payments"),
        {"infrastructure": ["vm1"], "unrelated": "drop"},
    )
    assert model.facts == {"infrastructure": ["vm1"]}


def test_semantic_context_is_compact_and_validated():
    context = SemanticContext(
        context_type="resource",
        subject=SemanticEntity("VirtualMachine", "vm1", "active"),
        sections={"ownership": [{"name": "ops@example.com", "entity_type": "Owner"}]},
        freshness="2026-08-17T00:00:00Z",
        knowledge_version="source-run-1",
    )

    payload = context.to_dict()
    report = SemanticValidator().validate_context(payload)

    assert report.passed
    assert payload["subject"] == {
        "entity_type": "VirtualMachine",
        "name": "vm1",
        "lifecycle_status": "active",
    }
    assert "payload_json" not in str(payload)


def test_semantic_validator_rejects_dangling_ontology_relationships():
    report = SemanticValidator().validate_snapshot(
        [
            {
                "resource_id": "entity-1",
                "entity_type": "Resource",
                "name": "entity-1",
                "lifecycle_status": "active",
            }
        ],
        [
            {
                "resource_id": "relationship-1",
                "subject_id": "entity-1",
                "subject_type": "Resource",
                "object_id": "missing",
                "object_type": "Resource",
                "predicate": "contains",
                "lifecycle_status": "active",
            }
        ],
    )

    assert not report.passed
    assert report.errors == ("dangling relationship: relationship-1",)


def test_semantic_validator_rejects_duplicates_and_missing_contract_fields():
    report = SemanticValidator().validate_snapshot(
        [
            {"resource_id": "x", "entity_type": "Resource", "name": "first"},
            {"resource_id": "x", "entity_type": "Resource", "name": "second"},
            {"resource_id": "y", "entity_type": "", "name": ""},
        ],
        [
            {
                "resource_id": "r",
                "subject_id": "x",
                "object_id": "y",
                "predicate": "",
            },
            {
                "resource_id": "r",
                "subject_id": "x",
                "object_id": "y",
                "predicate": "contains",
            },
        ],
    )

    assert not report.passed
    assert "duplicate entity_id: x" in report.errors
    assert "duplicate relationship_id: r" in report.errors
    assert "entity missing required fields: y" in report.errors
    assert "relationship missing predicate: r" in report.errors


def test_semantic_validator_requires_relationship_id_and_endpoint_types():
    report = SemanticValidator().validate_snapshot(
        [
            {"resource_id": "a", "entity_type": "Application", "name": "A"},
            {"resource_id": "b", "entity_type": "Service", "name": "B"},
        ],
        [
            {
                "subject_id": "a",
                "predicate": "implements",
                "object_id": "b",
            }
        ],
    )

    assert not report.passed
    assert "relationship missing resource_id: unknown" in report.errors
    assert "relationship missing subject_type: unknown" in report.errors
    assert "relationship missing object_type: unknown" in report.errors


def test_semantic_validator_rejects_dangling_operational_facts():
    report = SemanticValidator().validate_snapshot(
        [{"resource_id": "known", "entity_type": "Resource", "name": "Known"}],
        [],
        security=[
            {
                "target_resource_id": "ghost",
                "title": "Finding",
                "severity": "high",
            }
        ],
    )

    assert not report.passed
    assert report.errors == ("security fact has dangling target: 0",)


def test_semantic_validator_rejects_facts_without_domain_content():
    report = SemanticValidator().validate_snapshot(
        [{"resource_id": "known", "entity_type": "Resource", "name": "Known"}],
        [],
        compliance=[{"assessed_resource_id": "known"}],
    )

    assert not report.passed
    assert report.errors == ("compliance fact missing content: 0",)


def test_semantic_validator_rejects_blank_domain_content():
    report = SemanticValidator().validate_snapshot(
        [{"resource_id": "known", "entity_type": "Resource", "name": "Known"}],
        [],
        compliance=[{"assessed_resource_id": "known", "status": ""}],
        security=[{"target_resource_id": "known", "title": [], "severity": {}}],
    )

    assert not report.passed
    assert "compliance fact missing content: 0" in report.errors
    assert "security fact missing content: 0" in report.errors
