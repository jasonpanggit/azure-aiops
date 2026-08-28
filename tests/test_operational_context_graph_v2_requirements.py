from __future__ import annotations

import importlib
import json
from pathlib import Path

from semantic_scenario import semantic_scenario

from agents.operations.context_router import ContextRouter
from agents.operations.operations_agent import OperationsAgent
from onboarding.plugin import OPERATIONS_AGENT_SCHEMA
from ontology.entity_builder import EntityBuilder
from ontology.graph_queries import OntologyQueryService
from ontology.ontology_sync import OntologyGraphSynchronizer
from ontology.relationship_builder import RelationshipBuilder
from ontology.sync_validator import SyncValidator
from semantic.semantic_engine import SemanticEngine

REQUIRED_MODULES = (
    "ontology.ontology_manager",
    "ontology.entity_builder",
    "ontology.relationship_builder",
    "ontology.publisher",
    "ontology.sync_validator",
)
REQUIRED_ENTITY_TYPES = {
    "Tenant",
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    "VirtualMachine",
    "ArcServer",
    "KubernetesCluster",
    "PatchAssessment",
    "AdvisorRecommendation",
    "Application",
    "Service",
    "Environment",
    "BusinessService",
    "BusinessFunction",
    "Owner",
    "SupportTeam",
}


def source(
    resource_id: str,
    entity_type: str,
    *,
    resource_type: str = "",
    name: str = "",
    payload: dict | None = None,
) -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": "2026-08-19T00:00:00Z",
        "change_version": "source-v1",
        "ingestion_run_id": "source-run",
        "entity_type": entity_type,
        "name": name or resource_id.rsplit("/", 1)[-1],
        "resource_type": resource_type,
        "location": "eastus",
        "payload_json": json.dumps(payload or {}),
    }


def graph():
    vm_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"
    arc_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/arc1"
    aks_id = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1"
    vm_payload = {
        "id": vm_id,
        "name": "vm1",
        "tenantId": "tenant-1",
        "subscriptionId": "sub-1",
        "resourceGroup": "rg",
        "tags": {
            "AppName": "Payments",
            "Environment": "Production",
            "BusinessUnit": "Retail",
            "CostCenter": "CC-42",
            "Owner": "payments@example.com",
            "SupportGroup": "Payments SRE",
            "Service": "Checkout",
            "DependsOn": "Identity",
        },
    }
    rows = [
        source(
            "/providers/Microsoft.Management/managementGroups/root",
            "ManagementGroup",
            resource_type="microsoft.management/managementgroups",
            name="root",
            payload={"tenantId": "tenant-1"},
        ),
        source(
            "/subscriptions/sub-1",
            "Subscription",
            name="sub-1",
            payload={
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
                "managementGroupAncestorsChain": [{"name": "root"}],
            },
        ),
        source(
            vm_id,
            "VirtualMachine",
            resource_type="microsoft.compute/virtualmachines",
            name="vm1",
            payload=vm_payload,
        ),
        source(
            arc_id,
            "ArcServer",
            resource_type="microsoft.hybridcompute/machines",
            name="arc1",
            payload={
                "id": arc_id,
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
                "resourceGroup": "rg",
            },
        ),
        source(
            aks_id,
            "Resource",
            resource_type="microsoft.containerservice/managedclusters",
            name="aks1",
            payload={
                "id": aks_id,
                "tenantId": "tenant-1",
                "subscriptionId": "sub-1",
                "resourceGroup": "rg",
            },
        ),
        source(
            "patch-1",
            "PatchAssessment",
            name="patch-1",
            payload={"targetResourceId": vm_id, "status": "failed"},
        ),
        source(
            "advisor-1",
            "AdvisorRecommendation",
            name="advisor-1",
            payload={"targetResourceId": vm_id, "category": "Cost"},
        ),
    ]
    entities = EntityBuilder().build(rows, "run-1", "2026-08-19T00:00:00Z")
    relationships = RelationshipBuilder().build(entities, "run-1")
    return entities, relationships


def test_exact_ontology_modules_and_enterprise_entity_contract():
    for module in REQUIRED_MODULES:
        assert importlib.import_module(module)

    entities, _ = graph()
    assert REQUIRED_ENTITY_TYPES <= {row["entity_type"] for row in entities}
    assert all(row["lineage_json"] and row["change_version"] for row in entities)


def test_required_operational_relationships_are_discovered():
    _, relationships = graph()
    triples = {
        (row["subject_type"], row["predicate"], row["object_type"])
        for row in relationships
    }
    assert {
        ("Tenant", "owns", "Subscription"),
        ("ManagementGroup", "contains", "Subscription"),
        ("Subscription", "contains", "ResourceGroup"),
        ("ResourceGroup", "contains", "VirtualMachine"),
        ("VirtualMachine", "member_of", "Application"),
        ("ArcServer", "managed_by", "Subscription"),
        ("AdvisorRecommendation", "affects", "VirtualMachine"),
        ("PatchAssessment", "evaluates", "VirtualMachine"),
        ("BusinessService", "owns", "Application"),
        ("SupportTeam", "supports", "Application"),
    } <= triples


def test_incremental_sync_generates_all_five_context_views_and_health():
    entities, relationships = graph()
    result = OntologyGraphSynchronizer(SyncValidator()).synchronize(
        entities,
        relationships,
        ontology_version="version-1",
        timestamp="2026-08-19T00:00:00Z",
    )
    assert {
        "application_context",
        "infrastructure_context",
        "subscription_context",
        "compliance_context",
        "business_context",
    } <= set(result.views)
    assert {
        "entity_count",
        "relationship_count",
        "orphan_resources",
        "missing_ownership",
        "missing_tags",
        "synchronization_errors",
    } <= set(result.health)
    assert result.quality_report["passed"] is True


def test_query_layer_answers_success_criteria_and_requested_queries():
    entities, relationships = graph()
    query = OntologyQueryService(entities, relationships)
    checks = (
        ("Which applications are affected by patch failures?", "", "Application"),
        ("Who owns this VM?", "vm1", "Owner"),
        ("What resources belong to Service X?", "Checkout", "VirtualMachine"),
        ("What is impacted if this server fails?", "vm1", "BusinessService"),
        ("Show dependencies for Application X", "Payments", "Application"),
        ("Which business service owns this application?", "Payments", "BusinessService"),
    )
    for question, entity, expected_type in checks:
        result = query.answer(question, entity=entity)
        assert expected_type in {row["entity_type"] for row in result["items"]}


def test_agent_skill_and_required_documentation_artifacts_exist():
    assert Path("skills/operational-context-graph/SKILL.md").is_file()
    for path in (
        "docs/ontology-architecture.md",
        "docs/ontology-model.md",
        "docs/FABRIC_ONTOLOGY_DEPLOYMENT.md",
        "docs/ONTOLOGY_RUNBOOK.md",
        "docs/operational-context-graph-architecture.html",
    ):
        assert Path(path).is_file(), path

    command = "Find Resources With Missing Ownership"
    assert command in OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    assert ContextRouter().route(command).context_kind == "search"
    assert command in Path("skills/operational-context-graph/SKILL.md").read_text()
    response = OperationsAgent(SemanticEngine.from_rows(**semantic_scenario())).analyze(
        command, "Enterprise"
    )
    assert response["read_only"] is True
    assert response["subject"]["entity_type"] == "OperationalPortfolio"
