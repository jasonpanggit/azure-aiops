from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from hermes_arg_connector.config import ConnectorConfig
from intelligence.inventory.pipeline import InventoryPipeline
from intelligence.inventory.service import InventoryService
from storage.datasets import DatasetStore

TOKEN = "inventory-paas-token"


class _ResourceSource:
    def list_subscriptions(self) -> list[dict]:
        return [{"subscriptionId": "sub-a"}, {"subscriptionId": "sub-b"}]

    def fetch(self, specs, subscription_ids):
        rows = [
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg-app/providers/Microsoft.Web/sites/app-1",
                "name": "app-1",
                "type": "microsoft.web/sites",
                "tenantId": "tenant-a",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg-app",
                "location": "australiaeast",
                "tags": {"Environment": "prod"},
                "sku": {"name": "P1v3", "tier": "PremiumV3"},
                "properties": {
                    "state": "Running",
                    "siteConfig": {"linuxFxVersion": "PYTHON|3.11"},
                },
            },
            {
                "id": "/subscriptions/sub-b/resourceGroups/rg-data/providers/Microsoft.Sql/servers/sql-1/databases/db-1",
                "name": "db-1",
                "type": "microsoft.sql/servers/databases",
                "tenantId": "tenant-a",
                "subscriptionId": "sub-b",
                "resourceGroup": "rg-data",
                "location": "australiaeast",
                "sku": {"name": "GP_Gen5_2"},
                "properties": {"status": "Online", "currentSku": {"tier": "GeneralPurpose"}},
            },
            {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
                "name": "vm-1",
                "type": "microsoft.compute/virtualmachines",
                "subscriptionId": "sub-a",
                "resourceGroup": "rg",
                "tags": {},
                "osType": "Windows",
            },
        ]
        return {
            spec.name: (
                rows
                if spec.name == "inventory_resources"
                else [rows[2]]
                if spec.name == "inventory_native_vm_os"
                else []
            )
            for spec in specs
        }


def _service(tmp_path: Path) -> InventoryService:
    pipeline = InventoryPipeline(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a", "sub-b")),
        source=_ResourceSource(),
        clock=lambda: datetime(2026, 8, 26, 6, tzinfo=UTC),
    )
    result = pipeline.refresh()
    assert result.manifest["fabricTables"]["inventory/resource_observations"] == (
        "inventory_resource_observations"
    )
    return InventoryService.from_store(DatasetStore(tmp_path))


def _client(service: InventoryService) -> TestClient:
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_provider=lambda: service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_paas_refresh_writes_fabric_table_and_excludes_vm_arc(tmp_path: Path) -> None:
    service = _service(tmp_path)
    rows = [row.to_api_dict() for row in service.snapshot.resource_observations]

    assert {row["resource_type"] for row in rows} == {
        "microsoft.web/sites",
        "microsoft.sql/servers/databases",
    }
    assert all("microsoft.compute/virtualmachines" != row["resource_type"] for row in rows)
    assert "provider_payload_json" not in json.dumps(rows)


def test_paas_grouped_route_is_scoped_evidence_wrapped_and_paginated(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    response = client.get(
        "/api/v1/inventory/paas",
        params={"subscription": "sub-a", "limit": 10},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == {"subscription": ["sub-a"]}
    assert body["pagination"]["total"] == 1
    assert body["evidence"][0]["source_table"] == "inventory/resource_observations"
    assert body["data"]["source_status"]["paas"]["state"] == "ready"
    assert body["data"]["groups"][0]["key"] == "microsoft.web:sites|P1v3|PremiumV3"


def test_paas_scope_excludes_out_of_scope_subscription(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    response = client.get(
        "/api/v1/inventory/paas",
        params={"subscription": "sub-c"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["groups"] == []


def test_paas_drilldown_rejects_path_keys_and_filters_scope(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    invalid = client.get(
        "/api/v1/inventory/paas/microsoft.web/sites|P1v3|PremiumV3",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    valid = client.get(
        "/api/v1/inventory/paas/microsoft.web%3Asites%7CP1v3%7CPremiumV3",
        params={"subscription": "sub-a"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    assert valid.json()["pagination"]["total"] == 1
    assert "provider_payload" not in json.dumps(valid.json())


def test_cross_family_route_returns_multiple_scoped_families_without_payload(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    response = client.get(
        "/api/v1/inventory/resources",
        params={"subscription": "sub-a", "limit": 20},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {row["family"] for row in body["data"]["resources"]} == {"os", "paas"}
    assert body["pagination"]["total"] == 2
    assert "provider_payload" not in json.dumps(body)
