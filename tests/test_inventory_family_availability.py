from __future__ import annotations

from intelligence.inventory.registry import InventoryFamily, InventoryFamilyRegistry
from intelligence.inventory.service import InventoryService


def test_os_serves_when_paas_absent_and_family_reports_unavailable() -> None:
    service = InventoryService(
        {
            "observations": [
                {
                    "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                    "machine_name": "vm",
                    "source_type": "azure_vm",
                    "os_name": "Windows",
                    "os_version": "Unknown",
                    "subscription_id": "sub-a",
                    "resource_group": "rg",
                    "environment": "prod",
                    "observed_at": "2026-08-26T06:00:00Z",
                    "source_status": "ready",
                    "evidence": [],
                }
            ]
        }
    )

    availability = service.family_availability()

    assert availability["os"]["state"] == "ready"
    assert availability["paas"]["state"] == "unavailable"


def test_paas_and_os_serve_when_software_is_degraded() -> None:
    service = InventoryService(
        {
            "observations": [
                {
                    "resource_id": "vm-1",
                    "machine_name": "vm-1",
                    "source_type": "azure_vm",
                    "os_name": "Windows",
                    "os_version": "Unknown",
                    "subscription_id": "sub-a",
                    "resource_group": "rg",
                    "environment": "prod",
                    "observed_at": "2026-08-26T06:00:00Z",
                    "source_status": "ready",
                    "evidence": [],
                }
            ],
            "resource_observations": [
                {
                    "tenant_id": "tenant-a",
                    "subscription_id": "sub-a",
                    "resource_id": "app-1",
                    "timestamp": "2026-08-26T06:00:00Z",
                    "change_version": "v1",
                    "ingestion_run_id": "run-1",
                    "resource_name": "app-1",
                    "resource_type": "microsoft.web/sites",
                    "resource_group": "rg",
                    "location": "australiaeast",
                    "family": "paas",
                    "sku": "P1v3",
                    "tier": "PremiumV3",
                    "runtime": "PYTHON|3.11",
                    "provisioning_state": "Running",
                    "os_name": "",
                    "os_version": "",
                    "source_type": "arg",
                    "source_table": "Resources",
                    "observed_at": "2026-08-26T06:00:00Z",
                    "query_version": "resource-observation-v1",
                    "provider_payload_json": "{}",
                    "tags_json": "{}",
                    "provenance_json": "{}",
                }
            ],
            "software_source_status": {"logs": {"state": "degraded", "error": "timeout"}},
        }
    )

    availability = service.family_availability()

    assert availability["os"]["state"] == "ready"
    assert availability["paas"]["state"] == "ready"
    assert availability["software"]["state"] == "degraded"


def test_registry_family_appears_in_availability_report() -> None:
    service = InventoryService([])
    registry = InventoryFamilyRegistry(
        [
            InventoryFamily(
                family="custom",
                logical_dataset="inventory/custom",
                fabric_table="inventory_custom",
                status_dataset="inventory/source_status",
                source_types=("custom",),
                observation_type="resource",
                scope_fields=("subscription_id",),
            )
        ]
    )

    assert service.family_availability(registry=registry)["custom"]["state"] == "unavailable"
