from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from api.scope import Scope
from hermes_arg_connector.normalize import Normalizer
from hermes_arg_connector.queries import QueryCatalog
from hermes_arg_connector.storage import DatasetStore
from intelligence.inventory import InventoryService
from intelligence.lifecycle import EOLCatalog

FIXTURE = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"


def _scope(**kwargs: list[str]) -> Scope:
    return Scope.from_mapping(kwargs)


@pytest.fixture
def service() -> InventoryService:
    return InventoryService.from_fixture(
        FIXTURE,
        catalog=EOLCatalog.default(),
    )


def test_fixture_groups_native_and_arc_after_scope_filter(service: InventoryService) -> None:
    result = service.collection(_scope(subscription=["sub-a"]))

    groups = {row["key"]: row for row in result["data"]["groups"]}
    windows = groups["Windows Server|2019"]
    assert windows["machine_count"] == 2
    assert list(windows["source_types"]) == ["arc", "azure_vm"]
    assert "sub-b" not in json.dumps(result)
    assert result["data"]["source_status"]["azure_vm"]["row_count"] == 2


def test_detail_is_exact_resource_join_and_preserves_environment(service: InventoryService) -> None:
    result = service.detail("Windows Server|2019", _scope(subscription=["sub-a"]))

    assert result is not None
    assert [row["resource_id"] for row in result["data"]["machines"]] == [
        "/subscriptions/sub-a/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/web-01",
        "/subscriptions/sub-a/resourceGroups/rg-prod/providers/Microsoft.HybridCompute/machines/shared-name",
    ]
    assert {row["source_type"] for row in result["data"]["machines"]} == {"azure_vm", "arc"}
    assert all(row["environment"] == "prod" for row in result["data"]["machines"])
    assert all(row["evidence"] for row in result["data"]["machines"])
    assert len({row["resource_id"] for row in result["data"]["machines"]}) == 2


def test_unknown_lifecycle_requires_review(service: InventoryService) -> None:
    result = service.detail("Windows Server|2099-preview", _scope(subscription=["sub-a"]))

    assert result is not None
    machine = result["data"]["machines"][0]
    assert machine["lifecycle_status"] == "Unknown"
    assert machine["support_end"] is None
    assert machine["review_required"] is True


def test_scope_is_applied_before_group_counts_and_pagination(service: InventoryService) -> None:
    result = service.collection(_scope(subscription=["sub-b"]), offset=0, limit=1)

    assert result["total"] == 1
    assert result["data"]["groups"][0]["machine_count"] == 1
    assert result["data"]["requested_scope"] == {"subscription": ["sub-b"]}


def test_source_failure_is_not_successful_empty(service: InventoryService) -> None:
    result = service.collection(Scope.unrestricted())

    assert result["data"]["source_status"]["arc"]["state"] == "partial"
    assert result["data"]["source_status"]["arc"]["error"]
    assert any("partial" in warning for warning in result["warnings"])


def test_empty_success_is_distinct_from_unavailable() -> None:
    empty = InventoryService(
        [
            {
                "resource_id": "vm-1",
                "machine_name": "vm-1",
                "source_type": "azure_vm",
                "os_name": "Windows Server",
                "os_version": "2019",
                "subscription_id": "sub-a",
                "resource_group": "rg",
                "environment": "prod",
                "observed_at": "2026-08-25T10:00:00Z",
                "source_status": "ready",
                "evidence": [],
            }
        ]
    )
    assert empty.source_status()["azure_vm"]["state"] == "ready"

    payload = {"source_status": {"azure_vm": {"state": "unavailable", "error": "timeout"}, "arc": "ready"}}
    unavailable = InventoryService.from_fixture(_write_payload(payload))
    assert unavailable.collection(Scope.unrestricted())["data"]["source_status"]["azure_vm"]["state"] == "unavailable"


def test_native_and_arc_queries_are_versioned_and_independent() -> None:
    specs = {spec.name: spec for spec in QueryCatalog().build(None)}

    native = specs["inventory_native_vm_os"]
    arc = specs["inventory_arc_os"]
    assert native.version == "inventory-native-vm-os-v1"
    assert arc.version == "inventory-arc-os-v1"
    assert native.query != arc.query
    assert "imageVersion" in native.query
    assert "osVersion" in arc.query
    assert "| order by id asc" in native.query
    assert "| order by id asc" in arc.query


def test_generated_inventory_rows_preserve_source_identity_and_image_uncertainty(
    tmp_path: Path,
) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    graph = Normalizer().normalize(
        {
            "inventory_native_vm_os": fixture["inventory_native_vm_os"],
            "inventory_arc_os": fixture["inventory_arc_os"],
        },
        datetime.fromisoformat("2026-08-25T10:00:00+00:00"),
        run_id="inventory-run",
        requested_scope={"subscription": ["sub-a", "sub-b"]},
    )

    native = next(row for row in graph.inventory_observations if row["source_type"] == "azure_vm")
    arc = next(row for row in graph.inventory_observations if row["source_type"] == "arc")
    assert native["os_version"] == "Unknown"
    assert native["image_sku"] == "2019-Datacenter"
    assert native["image_version"] == "latest"
    assert native["environment"] == "prod"
    assert arc["os_name"] == "Ubuntu"
    assert arc["os_version"] == "22.04"
    assert arc["environment"] == "prod"
    assert native["resource_id"].startswith("/subscriptions/sub-a/")
    assert native["evidence"][0]["query_version"] == "inventory-native-vm-os-v1"

    store = DatasetStore(tmp_path)
    store.publish(graph, {}, {"runId": "inventory-run", "status": "completed"})
    loaded = InventoryService.from_store(store)
    assert loaded is not None
    result = loaded.detail("Windows Server|2019", Scope.from_mapping({"subscription": ["sub-a"]}))
    assert result is not None
    assert [row["source_type"] for row in result["data"]["machines"]] == ["arc"]


def test_inventory_latest_state_deduplicates_by_exact_source_and_resource() -> None:
    payload = {
        "query_version": "inventory-os-v1",
        "observations": [
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                "name": "vm",
                "type": "microsoft.compute/virtualMachines",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "tags": {"ENV": "stage", "EnvironmentName": "prod"},
                "osName": "Windows",
                "osVersion": "2022",
                "observed_at": "2026-08-25T09:00:00Z",
            },
            {
                "id": "/SUBSCRIPTIONS/SUB-A/RESOURCEGROUPS/rg/providers/Microsoft.Compute/virtualMachines/vm",
                "name": "vm",
                "type": "microsoft.compute/virtualMachines",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "tags": {"ENV": "stage", "EnvironmentName": "prod"},
                "osName": "Windows",
                "osVersion": "2025",
                "observed_at": "2026-08-25T10:00:00Z",
            },
        ],
    }
    service = InventoryService(payload)
    assert len(service.snapshot.observations) == 1
    row = service.snapshot.observations[0]
    assert row.os_version == "2025"
    assert row.environment == "stage"


def test_failed_inventory_family_remains_visible_without_erasing_other_family() -> None:
    graph = Normalizer().normalize(
        {
            "inventory_native_vm_os": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
                    "name": "vm",
                    "type": "microsoft.compute/virtualMachines",
                    "subscriptionId": "sub-a",
                    "resourceGroup": "rg",
                    "tags": {},
                    "osType": "Windows",
                }
            ],
            "inventory_arc_os": [
                {
                    "status": "failed",
                    "provider_status": "failed",
                    "error": "Arc query timed out",
                }
            ],
        },
        datetime.fromisoformat("2026-08-25T10:00:00+00:00"),
        run_id="inventory-failure-run",
    )
    statuses = {row["source_type"]: row for row in graph.inventory_source_status}
    assert len(graph.inventory_observations) == 1
    assert statuses["azure_vm"]["state"] == "ready"
    assert statuses["arc"]["state"] == "degraded"
    assert statuses["arc"]["error"] == "Arc query timed out"


def _write_payload(payload: dict) -> str:
    path = Path("/tmp/inventory-empty-success-test.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)
