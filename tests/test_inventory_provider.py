from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.scope import Scope
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


def _write_payload(payload: dict) -> str:
    path = Path("/tmp/inventory-empty-success-test.json")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)
