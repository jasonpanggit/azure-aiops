from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.inventory.read_port import InventoryReadPort
from intelligence.inventory.service import InventoryService
from onboarding.service import SubscriptionOnboardingService

TOKEN = "inventory-asset-reader-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _service(count: int = 4) -> InventoryService:
    return InventoryService({
        "observations": [
            {
                "resource_id": f"/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-{index:05d}",
                "machine_name": f"vm-{index:05d}", "source_type": "azure_vm",
                "os_name": "Windows", "os_version": "2022", "subscription_id": sub,
                "resource_group": "rg", "environment": "prod",
                "observed_at": "2026-10-16T06:00:00Z", "source_status": "ready", "evidence": [],
            }
            for index in range(count)
            for sub in ("sub-a", "sub-b")
        ],
    })


def _client(service: InventoryService, tmp_path: Path) -> TestClient:
    context = ApiContext(
        authenticator=StaticTokenAuthenticator({
            TOKEN: Principal(subject="reader", grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]})),)),
        }),
        authorizer=Authorizer(), telemetry=ApiTelemetry(),
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        inventory_provider=lambda: service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_filters_facets_and_total_cover_authorized_rows_before_paging(tmp_path: Path) -> None:
    client = _client(_service(), tmp_path)
    response = client.get("/api/v1/inventory/resources", params={
        "q": "VM-00003", "resource_group": "RG", "resource_type": "Microsoft.Compute/VirtualMachines",
        "family": "os", "limit": 1,
    }, headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["data"]["resources"][0]["resource_name"] == "vm-00003"
    assert body["data"]["represented_count"] == 4
    assert body["data"]["facets"]["family"] == [{"value": "os", "count": 4}]
    assert body["data"]["family_availability"]["os"]["row_count"] == 4
    assert "sub-b" not in response.text


def test_filtered_total_and_facets_survive_an_empty_page(tmp_path: Path) -> None:
    client = _client(_service(), tmp_path)
    response = client.get("/api/v1/inventory/resources", params={"offset": 25, "limit": 25},
                          headers=AUTH)
    assert response.status_code == 200
    assert response.json()["data"]["resources"] == []
    assert response.json()["pagination"]["total"] == 4
    assert response.json()["data"]["facets"]["resource_group"] == [{"value": "rg", "count": 4}]


def test_exact_asset_read_is_scoped_case_insensitive_and_source_qualified(tmp_path: Path) -> None:
    client = _client(_service(), tmp_path)
    resource_id = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-00003"
    response = client.get("/api/v1/inventory/asset", params={"resource_id": resource_id.upper()},
                          headers=AUTH)
    assert response.status_code == 200, response.text
    row = response.json()["data"]["resource"]
    assert row["resource_id"] == resource_id
    assert row["os_version"] == "2022"
    assert row["source_type"] == "azure_vm"
    assert row["observed_at"] == "2026-10-16T06:00:00Z"
    assert row["containment"]["management_group_id"] is None
    assert row["containment"]["resource_group_id"] == "/subscriptions/sub-a/resourcegroups/rg"


def test_missing_and_out_of_scope_assets_have_the_same_absence_contract(tmp_path: Path) -> None:
    client = _client(_service(), tmp_path)
    responses = [
        client.get("/api/v1/inventory/asset", params={"resource_id": resource_id},
                   headers=AUTH)
        for resource_id in [
            "missing",
            "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-00000",
        ]
    ]
    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json()["error"]["message"] == responses[1].json()["error"]["message"]


@pytest.mark.parametrize("query", [
    {"resource_id": ""}, {"resource_id": "x" * 2049}, {"resource_id": "bad\x00identity"},
])
def test_invalid_asset_bookmarks_fail_explicitly(tmp_path: Path, query: dict[str, str]) -> None:
    client = _client(_service(), tmp_path)
    response = client.get(f"/api/v1/inventory/asset?{urlencode(query)}",
                          headers=AUTH)
    assert response.status_code in {400, 422}


def test_resource_filters_and_lookup_do_not_silently_truncate_after_ten_thousand() -> None:
    port = InventoryReadPort(_service(10_002))
    scope = Scope.from_mapping({"subscription": ["sub-a"]})
    listed = port.list_resources(scope, query="vm-10001", limit=1)
    assert listed["total"] == 1
    assert listed["represented_count"] == 10_002
    assert listed["resources"][0]["resource_name"] == "vm-10001"
    assert port.get_resource(scope, listed["resources"][0]["resource_id"]) is not None


def test_assets_require_authentication(tmp_path: Path) -> None:
    client = _client(_service(), tmp_path)
    assert client.get("/api/v1/inventory/asset?resource_id=missing").status_code == 401
    assert client.get("/api/v1/inventory/resources").status_code == 401
