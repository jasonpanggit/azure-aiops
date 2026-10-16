from __future__ import annotations

import re
from pathlib import Path

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

TOKEN = "inventory-read-port-token"


def _service() -> InventoryService:
    return InventoryService(
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
                },
                {
                    "resource_id": "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-b",
                    "machine_name": "vm-b",
                    "source_type": "azure_vm",
                    "os_name": "Windows",
                    "os_version": "Unknown",
                    "subscription_id": "sub-b",
                    "resource_group": "rg",
                    "environment": "prod",
                    "observed_at": "2026-08-26T06:00:00Z",
                    "source_status": "ready",
                    "evidence": [],
                },
            ],
            "resource_observations": [
                {
                    "tenant_id": "tenant-a",
                    "subscription_id": "sub-a",
                    "resource_id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Web/sites/app",
                    "timestamp": "2026-08-26T06:00:00Z",
                    "change_version": "v1",
                    "ingestion_run_id": "run-1",
                    "resource_name": "app",
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
                    "provider_payload_json": "{\"secret\":\"internal\"}",
                    "tags_json": "{}",
                    "provenance_json": "{}",
                }
            ],
            "software_source_status": {"logs": {"state": "degraded", "error": "timeout"}},
        }
    )


def test_read_port_scope_family_type_and_lookup_semantics() -> None:
    port = InventoryReadPort(_service())
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    listed = port.list_resources(scope)
    narrowed = port.list_resources(scope, family="paas", resource_type="microsoft.web/sites")
    absent = port.get_resource(scope, "missing")
    out_of_scope = port.get_resource(
        scope,
        "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-b",
    )

    assert {row["family"] for row in listed["resources"]} == {"os", "paas"}
    assert [row["resource_name"] for row in narrowed["resources"]] == ["app"]
    assert absent is None
    assert out_of_scope is None
    assert listed["family_availability"]["software"]["state"] == "degraded"
    assert listed["observed_at"] == "2026-08-26T06:00:00Z"
    assert listed["query_version"] == "inventory-os-v1"
    assert narrowed["group_total"] == 1
    assert narrowed["groups"][0]["key"] == "microsoft.web:sites|P1v3|PremiumV3"


def test_api_cross_family_route_matches_read_port(tmp_path: Path) -> None:
    service = _service()
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        inventory_provider=lambda: service,
    )
    response = TestClient(create_app(context), raise_server_exceptions=False).get(
        "/api/v1/inventory/resources",
        params={"subscription": "sub-a", "limit": 100},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    internal = InventoryReadPort(service).list_resources(
        Scope.from_mapping({"subscription": ["sub-a"]}), limit=100
    )["resources"]
    assert response.json()["data"]["resources"] == [
        {"environment": "", **{key: value for key, value in row.items() if key not in {"tags", "properties", "tenant_id"}}}
        for row in internal
    ]
    assert internal[1]["properties"] == {"secret": "internal"}
    assert "internal" not in response.text


def test_list_containment_returns_strict_parent_chain() -> None:
    port = InventoryReadPort(_service())
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    rows = port.list_containment(scope)

    by_id = {row["id"]: row for row in rows}
    subscription_id = "/subscriptions/sub-a"
    rg_id = "/subscriptions/sub-a/resourcegroups/rg"
    assert subscription_id in by_id
    assert by_id[subscription_id]["kind"] == "subscription"
    assert by_id[subscription_id]["parent_id"] is None
    assert rg_id in by_id
    assert by_id[rg_id]["kind"] == "resource_group"
    assert by_id[rg_id]["parent_id"] == subscription_id


def test_list_containment_requires_scope() -> None:
    port = InventoryReadPort(_service())
    try:
        port.list_containment(None)
    except TypeError:
        pass
    else:
        raise AssertionError("list_containment(None) should raise TypeError")


def test_get_resource_includes_containment_sub_object() -> None:
    port = InventoryReadPort(_service())
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    resolved = port.get_resource(
        scope,
        "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Web/sites/app",
    )

    assert resolved is not None
    containment = resolved["containment"]
    assert containment["subscription_id"] == "/subscriptions/sub-a"
    assert containment["resource_group_id"] == "/subscriptions/sub-a/resourcegroups/rg"
    assert containment["management_group_id"] is None


def test_get_resource_without_resource_group_resolves_subscription_only_containment() -> None:
    service = InventoryService(
        {
            "observations": [],
            "resource_observations": [
                {
                    "tenant_id": "tenant-a",
                    "subscription_id": "sub-a",
                    "resource_id": "/subscriptions/sub-a/providers/Microsoft.Resources/deployments/dep",
                    "timestamp": "2026-08-26T06:00:00Z",
                    "change_version": "v1",
                    "ingestion_run_id": "run-1",
                    "resource_name": "dep",
                    "resource_type": "microsoft.resources/deployments",
                    "resource_group": "",
                    "location": "australiaeast",
                    "family": "paas",
                    "sku": "",
                    "tier": "",
                    "runtime": "",
                    "provisioning_state": "Succeeded",
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
        }
    )
    port = InventoryReadPort(service)
    scope = Scope.from_mapping({"subscription": ["sub-a"]})

    resolved = port.get_resource(
        scope,
        "/subscriptions/sub-a/providers/Microsoft.Resources/deployments/dep",
    )

    assert resolved is not None
    containment = resolved["containment"]
    assert containment["subscription_id"] == "/subscriptions/sub-a"
    assert containment["resource_group_id"] is None


def test_guard_no_direct_inventory_dataset_reads_outside_inventory() -> None:
    offenders: list[str] = []
    for path in Path("src").rglob("*.py"):
        if "src/intelligence/inventory/" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"read_dataset\(\s*['\"]inventory/", text):
            offenders.append(str(path))
    assert offenders == []


def test_guard_aiops_has_no_inventory_lifecycle_ownership_symbols() -> None:
    allowed = {"src/onboarding/cli.py"}
    patterns = re.compile(
        r"_fetch_software_inventory|normalize_configuration_data|_inventory_specs|"
        r"inventory/(os|software|resource)_observations|inventory_source_status|"
        r"inventory_software|inventory_resource|inventory_os"
    )
    offenders = []
    for path in Path("src/onboarding").rglob("*.py"):
        if str(path) in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if patterns.search(text):
            offenders.append(str(path))
    assert offenders == []
