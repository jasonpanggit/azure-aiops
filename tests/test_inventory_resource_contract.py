from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from storage.datasets import DatasetStore


PAYLOADS = (
    {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Web/sites/app-1",
        "name": "app-1",
        "type": "Microsoft.Web/sites",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {"Environment": "prod"},
        "sku": {"name": "P1v3", "tier": "PremiumV3"},
        "properties": {
            "state": "Running",
            "siteConfig": {
                "linuxFxVersion": "PYTHON|3.11",
                "appSettings": [{"name": "WEBSITE_RUN_FROM_PACKAGE", "value": "1"}],
            },
            "hostNames": ["app-1.azurewebsites.net"],
        },
    },
    {
        "id": "/subscriptions/sub-a/resourceGroups/data/providers/Microsoft.Sql/servers/sql-1/databases/db-1",
        "name": "db-1",
        "type": "Microsoft.Sql/servers/databases",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "data",
        "location": "australiaeast",
        "tags": {"tier": "gold"},
        "sku": {"name": "GP_Gen5_2"},
        "properties": {
            "status": "Online",
            "currentSku": {"tier": "GeneralPurpose"},
            "collation": "SQL_Latin1_General_CP1_CI_AS",
            "zoneRedundant": False,
        },
    },
)


def test_resource_observation_round_trips_nested_payload_via_jsonl_and_parquet(
    tmp_path: Path,
) -> None:
    from intelligence.inventory.fabric_contracts import fabric_table_for_logical_name
    from intelligence.inventory.models import ResourceObservation

    observations = [
        ResourceObservation.from_provider_row(
            row,
            family="paas",
            observed_at="2026-08-26T06:00:00Z",
            ingestion_run_id="run-1",
            query_version="resource-observation-v1",
        )
        for row in PAYLOADS
    ]
    rows = [item.to_fabric_row() for item in observations]
    from intelligence.inventory.fabric_publication import InventoryFabricPublisher

    store = DatasetStore(tmp_path)
    table_name = fabric_table_for_logical_name("inventory/resource_observations")
    InventoryFabricPublisher(store).publish(
        {"inventory/resource_observations": rows},
        query_results={},
        run_metadata={"runId": "run-1", "status": "completed"},
    )

    jsonl_rows = store.read_dataset("inventory/resource_observations")
    parquet_rows = pq.read_table(
        (tmp_path / "current" / table_name).with_suffix(".parquet")
    ).to_pylist()

    jsonl_payloads = {
        row["resource_id"]: ResourceObservation.from_fabric_row(row).provider_payload
        for row in jsonl_rows
    }
    parquet_payloads = {
        row["resource_id"]: ResourceObservation.from_fabric_row(row).provider_payload
        for row in parquet_rows
    }
    expected = {row["id"]: row["properties"] for row in PAYLOADS}
    assert jsonl_payloads == expected
    assert parquet_payloads == expected


def test_resource_observation_schema_has_identity_scope_projection_and_payload_columns() -> None:
    from fabric.schema_registry import schema_for
    from intelligence.inventory.fabric_contracts import fabric_table_for_logical_name

    schema = schema_for(fabric_table_for_logical_name("inventory/resource_observations"))

    assert {
        "tenant_id",
        "subscription_id",
        "resource_id",
        "resource_group",
        "location",
        "resource_type",
        "family",
        "sku",
        "tier",
        "runtime",
        "provisioning_state",
        "source_type",
        "source_table",
        "observed_at",
        "query_version",
        "ingestion_run_id",
        "change_version",
        "provider_payload_json",
        "provenance_json",
    } <= set(schema.names)


def test_resource_observation_rejects_assessment_domain_fields() -> None:
    from intelligence.inventory.fabric_contracts import validate_inventory_dataset
    from intelligence.inventory.models import ResourceObservation

    row = ResourceObservation.from_provider_row(
        PAYLOADS[0],
        family="paas",
        observed_at="2026-08-26T06:00:00Z",
        ingestion_run_id="run-1",
    ).to_fabric_row()

    report = validate_inventory_dataset(
        "inventory/resource_observations",
        [{**row, "health_status": "healthy"}],
    )

    assert any(failure["rule"] == "assessment_fields" for failure in report.failures)


def test_machine_observation_converts_to_resource_observation_without_payload_leak() -> None:
    from intelligence.inventory.models import MachineObservation, ResourceObservation

    machine = MachineObservation.from_mapping(
        {
            "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            "name": "vm-1",
            "type": "microsoft.compute/virtualMachines",
            "subscriptionId": "sub-a",
            "resourceGroup": "rg",
            "tags": {},
            "osType": "Windows",
            "observed_at": "2026-08-26T06:00:00Z",
        }
    )
    before = machine.to_dict()
    resource = ResourceObservation.from_machine_observation(
        machine,
        provider_payload={"nested": {"value": [1, {"two": True}]}},
        ingestion_run_id="run-1",
    )
    leaked = json.dumps(before)

    assert machine.to_dict() == before
    assert resource.resource_id == machine.resource_id
    assert resource.os_name == machine.os_name
    assert "provider_payload" not in before
    assert "provider_payload_json" not in leaked


def test_resource_observation_payload_is_mutation_isolated() -> None:
    from intelligence.inventory.models import ResourceObservation

    payload = {"nested": {"items": [{"name": "before"}]}}
    observation = ResourceObservation.from_provider_row(
        {"id": "resource-1", "subscriptionId": "sub-a", "properties": payload},
        family="generic",
        observed_at="2026-08-26T06:00:00Z",
        ingestion_run_id="run-1",
    )
    returned = observation.provider_payload
    returned["nested"]["items"][0]["name"] = "after"

    assert observation.provider_payload["nested"]["items"][0]["name"] == "before"


def test_family_registry_rejects_duplicate_logical_and_fabric_tables() -> None:
    from intelligence.inventory.registry import InventoryFamily, InventoryFamilyRegistry

    family = InventoryFamily(
        family="copy",
        logical_dataset="inventory/os_observations",
        fabric_table="inventory_resource_observations",
        status_dataset="inventory/source_status",
        source_types=("azure_vm",),
        observation_type="machine",
        scope_fields=("subscription_id",),
        raw_payload_internal_only=True,
    )
    with pytest.raises(ValueError, match="logical dataset"):
        InventoryFamilyRegistry([family, family])
    with pytest.raises(ValueError, match="Fabric table"):
        InventoryFamilyRegistry(
            [
                family,
                InventoryFamily(
                    family="other",
                    logical_dataset="inventory/other",
                    fabric_table="inventory_resource_observations",
                    status_dataset="inventory/source_status",
                    source_types=("other",),
                    observation_type="resource",
                    scope_fields=("subscription_id",),
                    raw_payload_internal_only=True,
                ),
            ]
        )


def test_default_family_registry_binds_current_families_to_fabric_contracts() -> None:
    from intelligence.inventory.fabric_contracts import fabric_table_for_logical_name
    from intelligence.inventory.registry import default_inventory_registry

    registry = default_inventory_registry()
    os_family = registry.family("os")
    software_family = registry.family("software")
    resource_family = registry.family("resource")

    assert os_family.logical_dataset == "inventory/os_observations"
    assert os_family.status_dataset == "inventory/source_status"
    assert os_family.fabric_table == fabric_table_for_logical_name("inventory/os_observations")
    assert software_family.logical_dataset == "inventory/software_observations"
    assert software_family.status_dataset == "inventory/software_source_status"
    assert software_family.fabric_table == fabric_table_for_logical_name(
        "inventory/software_observations"
    )
    assert {"azure_vm", "arc", "logs"} <= registry.source_types
    assert resource_family.raw_payload_internal_only is True
