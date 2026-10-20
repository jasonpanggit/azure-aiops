from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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


def test_paas_detail_uses_public_projection_but_preserves_internal_payload(tmp_path: Path) -> None:
    service = _service()
    scope = Scope.from_mapping({"subscription": ["sub-a"]})
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        inventory_provider=lambda: service,
    )
    group = service.paas_collection(scope)["data"]["groups"][0]
    internal = service.paas_detail(group["key"], scope)
    assert internal is not None
    assert internal["data"]["resources"][0]["properties"] == {"secret": "internal"}
    response = TestClient(create_app(context), raise_server_exceptions=False).get(
        f"/api/v1/inventory/paas/{group['key']}",
        params={"subscription": "sub-a"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    payload = response.json()
    rows = payload["data"]["resources"]
    assert len(rows) == 1
    assert not ({"properties", "tags", "tenant_id", "provider_payload_json"} & rows[0].keys())
    assert "internal" not in response.text
    assert rows[0]["resource_id"] == internal["data"]["resources"][0]["resource_id"]
    assert payload["data"]["generation_id"] == service.generation_id
    assert payload["scope"] == scope.to_dict()
    assert payload["pagination"]["total"] == internal["total"]
    assert InventoryReadPort(service).get_resource(
        scope, rows[0]["resource_id"],
    )["properties"] == {"secret": "internal"}


def test_inventory_tools_and_group_executor_share_http_public_projection(tmp_path: Path) -> None:
    from api.routers.copilot import CanonicalInventorySelector, _inventory_executor
    from operations.orchestration_contract import OrchestrationResult, SnapshotCoverage
    from operations.tools import call_tool

    service = _service()
    foreign_ids = [
        f"/subscriptions/sub-b/resourceGroups/foreign/providers/Microsoft.Network/virtualNetworks/vnet/subnets/subnet-{i}"
        for i in range(2)
    ]
    nested_properties = {
        "backendAddressPools": [{
            "properties": {"loadBalancerBackendAddresses": [
                {"properties": {"subnet": {"id": resource_id}}}
                for resource_id in foreign_ids
            ]},
        }],
    }
    observation = service.snapshot.resource_observations[0]
    service = InventoryService(replace(
        service.snapshot,
        resource_observations=(replace(
            observation,
            resource_type="microsoft.network/loadbalancers",
            provider_payload=nested_properties,
            tags={"private": "raw"},
        ), replace(
            observation,
            resource_id=foreign_ids[0],
            subscription_id="sub-b",
            provider_payload={},
        )),
    ))
    scope = Scope.from_mapping({"subscription": ["sub-a"]})
    port = InventoryReadPort(service)
    context = SimpleNamespace(
        provider_runtime=None,
        resolve_provider=lambda name: port if name == "inventory_read_port" else service,
    )
    internal = port.list_resources(scope, family="paas")["resources"]
    assert internal[0]["properties"] == nested_properties
    assert all(port.get_resource(scope, resource_id) is None for resource_id in foreign_ids)
    api_context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        inventory_provider=lambda: service,
    )
    response = TestClient(create_app(api_context), raise_server_exceptions=False).get(
        "/api/v1/inventory/resources",
        params={"subscription": "sub-a", "family": "paas"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200
    expected = response.json()["data"]["resources"]
    assert len(expected) == 1
    tool = call_tool(
        "inventory_resources", {"family": "paas"}, context=context, scope=scope,
    )
    assert tool.status == "ok"
    assert tool.data["resources"] == expected
    assert tool.data["total"] == 1
    group = service.paas_collection(scope)["data"]["groups"][0]
    selector = CanonicalInventorySelector(family="paas", resource_selector=f"group:{group['key']}")
    grouped = _inventory_executor(selector)(
        "inventory_resources", {}, context=context, scope=scope,
    )
    assert grouped.status == "ok"
    assert grouped.data["resources"] == expected
    assert grouped.data["total"] == 1
    for data in (tool.data, grouped.data):
        assert "properties" not in data["resources"][0]
        assert "tags" not in data["resources"][0]
        assert all(resource_id not in str(data) for resource_id in foreign_ids)
    assert all(row["subscription_id"] == "sub-a" for row in internal)
    assert port.list_resources(scope, family="paas")["resources"][0]["properties"] == nested_properties
    assert port.list_resources(scope, family="paas")["resources"][0]["tags"] == {"private": "raw"}
    usage = {
        "agent_name": "operations-copilot",
        "agent_version": "5",
        "model": "reported-model",
        "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    }
    public_answer = OrchestrationResult(
        status="ok",
        policy_status="accepted",
        selected_specialists=["inventory-data-health"],
        selected_tools=["inventory_resources"],
        tool_results=[{
            "tool": "inventory_resources",
            "status": grouped.status,
            "data": grouped.data,
        }],
        coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=True),
        thread_id=f"thr-{'a' * 32}",
        thread_revision=1,
        synthesis={"provider_usage": usage},
    ).model_dump(mode="json")
    assert public_answer["synthesis"]["provider_usage"] == usage
    answer_resources = public_answer["tool_results"][0]["data"]["resources"]
    assert answer_resources == expected
    assert all(resource_id not in str(public_answer) for resource_id in foreign_ids)
    assert "properties" not in answer_resources[0]
    assert "tags" not in answer_resources[0]


def test_list_containment_requires_scope() -> None:
    port = InventoryReadPort(_service())
    try:
        port.list_containment(None)
    except TypeError:
        pass
    else:
        raise AssertionError("list_containment(None) should raise TypeError")


def test_public_legacy_answer_projection_preserves_reported_provider_usage() -> None:
    from api.routers.multi_agent import _project_deterministic_activation

    usage = {
        "agent_name": "operations-copilot",
        "agent_version": "5",
        "model": "reported-model",
        "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    }
    ledger = {
        "selected_agents": [],
        "agent_runs": [],
        "synthesis": {"provider_usage": usage},
        "evaluation": {"provider_usage": usage},
    }

    projected = _project_deterministic_activation(ledger, context=SimpleNamespace())

    assert projected["synthesis"]["provider_usage"] == usage
    assert projected["evaluation"]["provider_usage"] == usage
    assert ledger["synthesis"]["provider_usage"] == usage
    assert ledger["evaluation"]["provider_usage"] == usage


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
