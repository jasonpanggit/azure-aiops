from __future__ import annotations

import base64
import json
import math

import pytest

from fabric.config import FabricRuntimeConfig
from intelligence.incident.incident_intelligence import IncidentIntelligence
from semantic.query_cache import QueryCache
from semantic.semantic_engine import SemanticEngine
from semantic.semantic_models import (
    RiskAssessment,
    RiskInputs,
    RiskScorer,
    SemanticEntity,
)
from semantic.validator import Validator


def test_semantic_engine_bounds_require_exact_positive_integers():
    scenario = {
        "entities": [],
        "relationships": [],
        "inventory": [],
        "compliance": [],
        "security": [],
        "cost": [],
    }
    for name, value in (
        ("max_results", True),
        ("max_traversal_nodes", 1.5),
        ("max_traversal_depth", 0),
        ("max_traversal_depth", 257),
        ("max_source_rows", 0),
        ("max_serialized_bytes", -1),
    ):
        with pytest.raises((TypeError, ValueError)):
            SemanticEngine.from_rows(**scenario, **{name: value})


def test_semantic_cache_rejects_boolean_fractional_and_nonfinite_bounds():
    for kwargs in (
        {"max_entries": True},
        {"max_entries": 1.5},
        {"ttl_seconds": True},
        {"ttl_seconds": math.nan},
        {"ttl_seconds": math.inf},
    ):
        with pytest.raises((TypeError, ValueError)):
            QueryCache(**kwargs)


def test_risk_inputs_and_score_boundaries_validate_exact_types():
    with pytest.raises((TypeError, ValueError)):
        RiskScorer().score(RiskInputs(missing_owner=1))
    with pytest.raises((TypeError, ValueError)):
        RiskScorer().score(RiskInputs(advisor_recommendation_count=True))
    with pytest.raises((TypeError, ValueError)):
        RiskScorer.level_for(True)
    with pytest.raises((TypeError, ValueError)):
        RiskScorer.level_for(101)


def test_snapshot_validation_rejects_malformed_collections_and_confidence():
    with pytest.raises((TypeError, ValueError)):
        SemanticEngine.from_rows(entities={}, relationships=[])

    entities = [
        {"resource_id": "a", "entity_type": "Application", "name": "A"},
        {"resource_id": "b", "entity_type": "Service", "name": "B"},
    ]
    relationship = {
        "resource_id": "r",
        "subject_id": "a",
        "subject_type": "Application",
        "predicate": "implements",
        "object_id": "b",
        "object_type": "Service",
        "confidence": True,
    }
    report = Validator().validate_snapshot(entities, [relationship])
    assert not report.passed
    assert any("confidence" in error for error in report.errors)


def test_duplicate_security_facts_do_not_inflate_operational_risk():
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    entities = [
        {
            "resource_id": resource_id,
            "entity_type": "VirtualMachine",
            "name": "vm",
        },
        {"resource_id": "owner", "entity_type": "Owner", "name": "Team"},
    ]
    relationships = [
        {
            "resource_id": "owned",
            "subject_id": resource_id,
            "subject_type": "VirtualMachine",
            "predicate": "owned_by",
            "object_id": "owner",
            "object_type": "Owner",
        }
    ]
    finding = {
        "target_resource_id": resource_id,
        "title": "CVE-X",
        "severity": "high",
    }
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        inventory=[{"resource_id": resource_id, "name": "vm"}],
        security=[finding, dict(finding)],
    )
    risk = semantic.risk_context("vm", subject_type="VirtualMachine")["risk"]
    assert risk["factors"]["security_findings"] == 20


def test_public_semantic_output_sanitizes_encoded_identifiers_and_mapping_keys():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b32encode(arm_id.encode()).decode()
    semantic = SemanticEngine.from_rows(
        entities=[
            {
                "resource_id": "resource-1",
                "entity_type": "VirtualMachine",
                "name": encoded,
            }
        ],
        relationships=[],
        inventory=[{"resource_id": "resource-1", "name": encoded}],
    )
    result = semantic.resource_context(encoded, subject_type="VirtualMachine")
    serialized = json.dumps(result).casefold()
    assert encoded.casefold() not in serialized
    assert "secret-rg" not in serialized


def test_semantic_serialized_output_ceiling_fails_closed():
    semantic = SemanticEngine.from_rows(
        entities=[
            {
                "resource_id": "resource-1",
                "entity_type": "VirtualMachine",
                "name": "x" * 10_000,
            }
        ],
        relationships=[],
        inventory=[{"resource_id": "resource-1", "name": "x" * 10_000}],
        max_serialized_bytes=1024,
    )
    with pytest.raises(ValueError, match="output exceeds"):
        semantic.resource_context("x" * 10_000, subject_type="VirtualMachine")


def test_no_resource_evidence_returns_unknown_risk():
    semantic = SemanticEngine.from_rows(
        entities=[
            {
                "resource_id": "application-1",
                "entity_type": "Application",
                "name": "Lonely",
            }
        ],
        relationships=[],
    )
    risk = semantic.risk_context("Lonely", subject_type="Application")["risk"]
    assert risk["score"] is None
    assert risk["level"] == "Unknown"
    assert risk["factors"] == {}


def test_semantic_model_requires_valid_identity():
    with pytest.raises((TypeError, ValueError)):
        SemanticEntity("", "")


def test_semantic_runtime_configuration_exposes_strict_bounds(tmp_path):
    path = tmp_path / "fabric.yaml"
    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  semantic:
    max_results: 75
    max_traversal_nodes: 750
    max_traversal_depth: 24
    max_source_rows: 75000
    max_serialized_bytes: 750000
"""
    )
    config = FabricRuntimeConfig.load(path).semantic
    assert config.max_results == 75
    assert config.max_traversal_nodes == 750
    assert config.max_traversal_depth == 24
    assert config.max_source_rows == 75000
    assert config.max_serialized_bytes == 750000

    path.write_text(
        """
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  semantic:
    max_results: true
"""
    )
    with pytest.raises((TypeError, ValueError)):
        FabricRuntimeConfig.load(path)


def test_semantic_rejects_malformed_freshness_and_fact_types():
    with pytest.raises(ValueError, match="freshness"):
        SemanticEngine.from_rows(
            entities=[], relationships=[], freshness="not-a-timestamp"
        )

    report = Validator().validate_snapshot(
        [{"resource_id": "r", "entity_type": "Resource", "name": "R"}],
        [],
        compliance=[
            {
                "assessed_resource_id": "r",
                "status": "failed",
                "failed_patch_count": True,
            }
        ],
    )
    assert not report.passed
    assert any("failed_patch_count" in error for error in report.errors)


def test_semantic_public_mapping_key_collisions_fail_closed():
    arm_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/secret-rg/providers/Microsoft.Compute/virtualMachines/vm"
    encoded = base64.b32encode(arm_id.encode()).decode()
    safe_key = IncidentIntelligence._safe_identifier(encoded, "field")

    class Scorer:
        def score(self, _inputs):
            return RiskAssessment(100, "Critical", {encoded: 1, safe_key: 99})

    semantic = SemanticEngine.from_rows(
        entities=[
            {"resource_id": "r", "entity_type": "VirtualMachine", "name": "vm"}
        ],
        relationships=[],
        inventory=[{"resource_id": "r", "name": "vm"}],
        scorer=Scorer(),
    )
    with pytest.raises(ValueError, match="key collision"):
        semantic.risk_context("vm", subject_type="VirtualMachine")


def test_shared_cache_is_isolated_by_snapshot_identity():
    cache = QueryCache()

    def engine(environment):
        return SemanticEngine.from_rows(
            entities=[
                {"resource_id": "r", "entity_type": "VirtualMachine", "name": "vm"}
            ],
            relationships=[],
            inventory=[
                {"resource_id": "r", "name": "vm", "environment": environment}
            ],
            knowledge_version="same-version",
            cache=cache,
        )

    production = engine("Production")
    development = engine("Development")
    assert production.resource_context("vm")["sections"][
        "operational_classification"
    ]["environment"] == "Production"
    assert development.resource_context("vm")["sections"][
        "operational_classification"
    ]["environment"] == "Development"


def test_application_security_filter_runs_before_result_truncation():
    entities = [
        {"resource_id": "app", "entity_type": "Application", "name": "App"},
        {"resource_id": "a", "entity_type": "VirtualMachine", "name": "a"},
        {"resource_id": "z", "entity_type": "VirtualMachine", "name": "z"},
    ]
    relationships = [
        {
            "resource_id": f"host-{resource}",
            "subject_id": "app",
            "subject_type": "Application",
            "predicate": "hosted_on",
            "object_id": resource,
            "object_type": "VirtualMachine",
        }
        for resource in ("a", "z")
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        inventory=[{"resource_id": "a", "name": "a"}, {"resource_id": "z", "name": "z"}],
        security=[{"target_resource_id": "z", "title": "CVE-Z", "severity": "high"}],
        max_results=1,
    )
    context = semantic.application_context("App")
    assert context["sections"]["security_findings"][0]["resource"]["name"] == "z"


def test_dependency_queries_enforce_traversal_budget():
    entities = [
        {"resource_id": f"app-{index}", "entity_type": "Application", "name": f"App {index}"}
        for index in range(5)
    ]
    relationships = [
        {
            "resource_id": f"depends-{index}",
            "subject_id": f"app-{index}",
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": f"app-{index + 1}",
            "object_type": "Application",
        }
        for index in range(4)
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        max_traversal_nodes=1,
    )
    result = semantic.query("Show upstream dependencies", subject="App 0")
    assert len(result["items"]) == 1
    assert result["truncated"] is True


def test_validator_rejects_malformed_entity_relationship_and_fact_fields():
    malformed_entity = Validator().validate_snapshot(
        [{"resource_id": 789, "entity_type": 123, "name": 456}], []
    )
    assert not malformed_entity.passed

    entities = [
        {"resource_id": "a", "entity_type": "Application", "name": "A"},
        {"resource_id": "b", "entity_type": "Service", "name": "B"},
    ]
    malformed_relationship = Validator().validate_snapshot(
        entities,
        [
            {
                "resource_id": "r",
                "subject_id": "a",
                "subject_type": "Application",
                "predicate": 123,
                "object_id": "b",
                "object_type": "Service",
            }
        ],
    )
    assert not malformed_relationship.passed

    facts = Validator().validate_snapshot(
        [{"resource_id": "r", "entity_type": "Resource", "name": "R"}],
        [],
        inventory=[{"resource_id": "r", "status": {"bad": 1}}],
        security=[{"target_resource_id": "r", "impact": {"bad": 1}}],
        cost=[{"target_resource_id": "r", "currency": ["USD"]}],
    )
    assert not facts.passed


def test_duplicate_cost_facts_are_deduplicated():
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    row = {"target_resource_id": resource_id, "amount": 10.0, "currency": "USD"}
    semantic = SemanticEngine.from_rows(
        entities=[
            {"resource_id": "sub", "entity_type": "Subscription", "name": "sub"},
            {"resource_id": resource_id, "entity_type": "VirtualMachine", "name": "vm"},
        ],
        relationships=[],
        inventory=[{"resource_id": resource_id, "name": "vm"}],
        cost=[row, dict(row)],
    )
    assert len(semantic.subscription_context("sub")["sections"]["cost"]) == 1


def test_exact_search_api_and_mixed_case_arm_subscription_view():
    resource_id = "/subscriptions/sub/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/VM"
    semantic = SemanticEngine.from_rows(
        entities=[
            {"resource_id": "sub", "entity_type": "Subscription", "name": "sub"},
            {"resource_id": resource_id, "entity_type": "VirtualMachine", "name": "vm"},
        ],
        relationships=[],
        inventory=[{"resource_id": resource_id, "name": "vm"}],
    )
    assert semantic.subscription_context("sub")["sections"]["resource_count"] == 1
    assert semantic.search("Find servers with failed patches")["intent"] == "semantic_search"


def test_nested_security_findings_respect_result_bound():
    semantic = SemanticEngine.from_rows(
        entities=[
            {"resource_id": "r", "entity_type": "Resource", "name": "R"}
        ],
        relationships=[],
        inventory=[{"resource_id": "r", "name": "R"}],
        security=[
            {
                "target_resource_id": "r",
                "title": f"finding-{index}",
                "severity": "high",
            }
            for index in range(7)
        ],
        max_results=2,
    )
    result = semantic.resource_context("R")
    assert len(result["sections"]["security_findings"]) == 2
    assert result["section_metadata"]["security_findings"] == {
        "count": 7,
        "returned": 2,
        "truncated": True,
    }


@pytest.mark.parametrize(
    "entities,relationships",
    [
        ([{"resource_id": "r", "entity_type": "Resource", "name": "R", "lifecycle_status": False}], []),
        (
            [
                {"resource_id": "a", "entity_type": "Application", "name": "A"},
                {"resource_id": "b", "entity_type": "Service", "name": "B"},
            ],
            [
                {
                    "resource_id": "edge",
                    "subject_id": "a",
                    "subject_type": "Application",
                    "predicate": "implements",
                    "object_id": "b",
                    "object_type": "Service",
                    "lifecycle_status": False,
                }
            ],
        ),
        ([{"resource_id": "r", "entity_type": "Resource", "name": "R", "location": {"bad": 1}}], []),
    ],
)
def test_snapshot_rejects_malformed_lifecycle_and_optional_entity_fields(
    entities, relationships
):
    with pytest.raises(ValueError):
        SemanticEngine.from_rows(entities=entities, relationships=relationships)


def test_validator_rejects_adjacent_malformed_fact_types_and_target_fallbacks():
    entity = [{"resource_id": "r", "entity_type": "Resource", "name": "R"}]
    assert not Validator().validate_snapshot(
        entity, [], inventory=[{"resource_id": "r", "criticality": True, "name": "R"}]
    ).passed
    assert not Validator().validate_snapshot(
        entity,
        [],
        cost=[{"target_resource_id": "r", "amount": -1, "currency": "USD"}],
    ).passed
    for label, row in (
        ("compliance", {"assessed_resource_id": False, "resource_id": "r", "status": "failed"}),
        ("security", {"target_resource_id": False, "resource_id": "r", "title": "finding"}),
        ("cost", {"target_resource_id": False, "resource_id": "r", "amount": 1}),
    ):
        report = Validator().validate_snapshot(entity, [], **{label: [row]})
        assert not report.passed, label


def test_canonical_relationship_and_numeric_cost_duplicates_do_not_inflate():
    entities = [
        {"resource_id": "sub", "entity_type": "Subscription", "name": "sub"},
        {
            "resource_id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
            "entity_type": "VirtualMachine",
            "name": "vm",
        },
    ]
    relationship = {
        "subject_id": "sub",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": entities[1]["resource_id"],
        "object_type": "VirtualMachine",
    }
    report = Validator().validate_snapshot(
        entities,
        [{"resource_id": "EDGE", **relationship}, {"resource_id": "edge", **relationship}],
    )
    assert not report.passed

    resource_id = entities[1]["resource_id"]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=[],
        inventory=[{"resource_id": resource_id, "name": "vm"}],
        cost=[
            {"target_resource_id": resource_id, "amount": 10, "currency": "USD"},
            {"target_resource_id": resource_id, "amount": 10.0, "currency": "USD"},
        ],
    )
    assert len(semantic.subscription_context("sub")["sections"]["cost"]) == 1


def test_risk_assessment_unknown_score_and_level_are_consistent():
    with pytest.raises(ValueError):
        RiskAssessment(None, "Low")
    with pytest.raises(ValueError):
        RiskAssessment(0, "Unknown")


def test_impact_direct_application_fanout_respects_traversal_bound():
    entities = [
        {"resource_id": "r", "entity_type": "Resource", "name": "R"},
        *[
            {"resource_id": f"app-{index}", "entity_type": "Application", "name": f"App {index}"}
            for index in range(5)
        ],
    ]
    relationships = [
        {
            "resource_id": f"member-{index}",
            "subject_id": "r",
            "subject_type": "Resource",
            "predicate": "member_of",
            "object_id": f"app-{index}",
            "object_type": "Application",
        }
        for index in range(5)
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        inventory=[{"resource_id": "r", "name": "R"}],
        max_traversal_nodes=2,
    )
    result = semantic.impact_context("R", subject_type="Resource")
    assert len(result["impacted_applications"]) <= 2
    assert result["truncated"] is True


def test_deep_impact_chain_respects_depth_bound_without_recursion_error():
    entities = [
        {
            "resource_id": f"app-{index}",
            "entity_type": "Application",
            "name": f"App {index}",
        }
        for index in range(1100)
    ]
    relationships = [
        {
            "resource_id": f"depends-{index}",
            "subject_id": f"app-{index + 1}",
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": f"app-{index}",
            "object_type": "Application",
        }
        for index in range(1099)
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        max_traversal_nodes=2000,
        max_traversal_depth=16,
    )
    result = semantic.impact_context("App 0", subject_type="Application")
    assert result["truncated"] is True

    node = result["tree"]
    depth = 0
    while node.get("children"):
        dependency = next(
            (
                child
                for child in node["children"]
                if child.get("relation") == "downstream_dependency"
            ),
            None,
        )
        if dependency is None:
            break
        depth += 1
        node = dependency
    assert depth <= 16


def test_case_alias_evidence_and_complete_governed_fact_types_fail_closed():
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm"
    entities = [
        {"resource_id": "sub", "entity_type": "Subscription", "name": "sub"},
        {"resource_id": resource_id, "entity_type": "VirtualMachine", "name": "vm"},
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=[],
        inventory=[{"resource_id": resource_id, "name": "vm"}],
        security=[
            {
                "target_resource_id": resource_id,
                "title": "CVE-X",
                "severity": "HIGH",
                "source": "Scanner",
            },
            {
                "target_resource_id": resource_id.upper(),
                "title": "cve-x",
                "severity": "high",
                "source": "scanner",
            },
        ],
        cost=[
            {"target_resource_id": resource_id, "amount": 10, "currency": "USD"},
            {"target_resource_id": resource_id.upper(), "amount": 10.0, "currency": "usd"},
        ],
    )
    assert len(semantic.resource_context("vm")["sections"]["security_findings"]) == 1
    assert len(semantic.subscription_context("sub")["sections"]["cost"]) == 1

    entity = [{"resource_id": "r", "entity_type": "Resource", "name": "R"}]
    for field_name, value in (
        ("resource_group", {}),
        ("vm_size", True),
        ("ingestion_run_id", True),
    ):
        report = Validator().validate_snapshot(
            entity,
            [],
            inventory=[{"resource_id": "r", "name": "R", field_name: value}],
        )
        assert not report.passed, field_name
    for field_name, value in (
        ("available_updates", True),
        ("available_updates", -1),
        ("missing_critical_updates", 1.5),
        ("missing_security_updates", math.nan),
    ):
        report = Validator().validate_snapshot(
            entity,
            [],
            compliance=[
                {
                    "assessed_resource_id": "r",
                    "status": "failed",
                    field_name: value,
                }
            ],
        )
        assert not report.passed, field_name
