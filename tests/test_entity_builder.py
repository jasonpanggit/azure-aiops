from __future__ import annotations

import json

from ontology.entity_builder import EntityBuilder


def resource(**overrides):
    row = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm1",
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "VirtualMachine",
        "name": "vm1",
        "resource_type": "microsoft.compute/virtualmachines",
        "location": "eastus",
        "payload_json": json.dumps({
            "id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "tenantId": "tenant-1",
            "subscriptionId": "sub-1",
            "resourceGroup": "rg",
            "tags": {
                "AppName": "Payments API",
                "Environment": "Production",
                "BusinessUnit": "Retail",
                "CostCenter": "CC-42",
                "Owner": "ops@example.com",
                "SupportGroup": "SRE",
                "Service": "Checkout",
            },
        }),
    }
    row.update(overrides)
    return row


def test_entity_builder_generates_structural_and_tag_entities_automatically():
    entities = EntityBuilder().build([resource()], "run-2")
    types = {row["entity_type"] for row in entities}

    assert {
        "Tenant",
        "Subscription",
        "ResourceGroup",
        "VirtualMachine",
        "Application",
        "Service",
        "Environment",
        "BusinessService",
        "BusinessFunction",
        "Owner",
        "SupportTeam",
    } <= types
    application = next(row for row in entities if row["entity_type"] == "Application")
    assert application["name"] == "Payments API"
    assert json.loads(application["lineage_json"])["source_resource_ids"] == [
        resource()["resource_id"].casefold()
    ]
    assert application["lifecycle_status"] == "active"


def test_business_context_entities_are_isolated_per_subscription():
    second = resource(
        subscription_id="sub-2",
        resource_id="/subscriptions/sub-2/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
    )
    payload = json.loads(second["payload_json"])
    payload["id"] = second["resource_id"]
    payload["name"] = "vm2"
    payload["subscriptionId"] = "sub-2"
    second["payload_json"] = json.dumps(payload)

    entities = EntityBuilder().build([resource(), second], "run-2")
    applications = [
        row
        for row in entities
        if row["entity_type"] == "Application" and row["name"] == "Payments API"
    ]

    assert len(applications) == 2
    assert {row["subscription_id"] for row in applications} == {"sub-1", "sub-2"}


def test_entity_builder_classifies_kubernetes_and_management_group_resources():
    rows = [
        resource(
            resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1",
            resource_type="microsoft.containerservice/managedclusters",
            entity_type="Resource",
            name="aks1",
            payload_json=json.dumps({"id": "aks1", "name": "aks1", "tenantId": "tenant-1", "subscriptionId": "sub-1"}),
        ),
        resource(
            resource_id="/providers/Microsoft.Management/managementGroups/mg1",
            resource_type="microsoft.management/managementgroups",
            entity_type="Resource",
            name="mg1",
            payload_json=json.dumps({"id": "/providers/Microsoft.Management/managementGroups/mg1", "name": "mg1", "tenantId": "tenant-1"}),
        ),
    ]

    types = {row["entity_type"] for row in EntityBuilder().build(rows, "run-2")}
    assert "KubernetesCluster" in types
    assert "ManagementGroup" in types
