from __future__ import annotations

import json

from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder


def source_row(
    name: str,
    entity_type: str,
    resource_id: str,
    *,
    tags: dict[str, str] | None = None,
    resource_type: str = "",
    properties: dict | None = None,
) -> dict:
    payload = {
        "id": resource_id,
        "name": name,
        "tenantId": "tenant-1",
        "subscriptionId": "sub-1",
        "resourceGroup": "rg-prod",
        "resourceType": resource_type,
        "location": "eastus",
        "tags": tags or {},
        **(properties or {}),
    }
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id.casefold(),
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "source-v1",
        "ingestion_run_id": "run-1",
        "entity_type": entity_type,
        "name": name,
        "resource_type": resource_type,
        "location": "eastus",
        "payload_json": json.dumps(payload),
    }


def semantic_scenario() -> dict[str, list[dict]]:
    vm_payments_id = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/"
        "Microsoft.Compute/virtualMachines/vm-payments"
    )
    vm_identity_id = (
        "/subscriptions/sub-1/resourceGroups/rg-prod/providers/"
        "Microsoft.Compute/virtualMachines/vm-identity"
    )
    sources = [
        source_row(
            "vm-payments",
            "VirtualMachine",
            vm_payments_id,
            resource_type="microsoft.compute/virtualmachines",
            tags={
                "AppName": "Payments",
                "Environment": "Production",
                "BusinessUnit": "Retail",
                "CostCenter": "CC-42",
                "Owner": "ops@example.com",
                "SupportGroup": "SRE",
                "Service": "Checkout",
                "Criticality": "Critical",
                "DependsOn": "Identity",
            },
        ),
        source_row(
            "vm-identity",
            "VirtualMachine",
            vm_identity_id,
            resource_type="microsoft.compute/virtualmachines",
            tags={
                "AppName": "Identity",
                "Environment": "Production",
                "BusinessUnit": "Shared Platform",
                "Owner": "platform@example.com",
                "SupportGroup": "Platform",
                "Service": "Identity",
                "Criticality": "High",
            },
        ),
        source_row(
            "patch-payments",
            "PatchAssessment",
            "assessment-payments",
            resource_type="microsoft.compute/patchassessmentresults",
            properties={"targetResourceId": vm_payments_id, "status": "failed"},
        ),
        source_row(
            "advisor-payments",
            "AdvisorRecommendation",
            "advisor-payments",
            resource_type="microsoft.advisor/recommendations",
            properties={"targetResourceId": vm_payments_id, "impact": "High"},
        ),
    ]
    entities = EntityBuilder().build(sources, "run-1", "2026-08-17T00:00:00Z")
    relationships = RelationshipBuilder().build(entities, "run-1")
    inventory = [
        {
            "resource_id": vm_payments_id.casefold(),
            "name": "vm-payments",
            "entity_type": "VirtualMachine",
            "status": "degraded",
            "lifecycle_status": "active",
            "criticality": "Critical",
            "environment": "Production",
            "timestamp": "2026-08-17T00:00:00Z",
        },
        {
            "resource_id": vm_identity_id.casefold(),
            "name": "vm-identity",
            "entity_type": "VirtualMachine",
            "status": "available",
            "lifecycle_status": "active",
            "criticality": "High",
            "environment": "Production",
            "timestamp": "2026-08-17T00:00:00Z",
        },
    ]
    compliance = [
        {
            "assessed_resource_id": vm_payments_id.casefold(),
            "status": "failed",
            "failed_patch_count": 2,
            "timestamp": "2026-08-17T00:00:00Z",
        },
        {
            "assessed_resource_id": vm_identity_id.casefold(),
            "status": "compliant",
            "failed_patch_count": 0,
            "timestamp": "2026-08-17T00:00:00Z",
        },
    ]
    security = [
        {
            "target_resource_id": vm_payments_id.casefold(),
            "severity": "high",
            "title": "Open management port",
            "timestamp": "2026-08-17T00:00:00Z",
        }
    ]
    return {
        "entities": entities,
        "relationships": relationships,
        "inventory": inventory,
        "compliance": compliance,
        "security": security,
        "cost": [],
        "knowledge_version": "source-run-1",
        "freshness": "2026-08-17T00:00:00Z",
    }
