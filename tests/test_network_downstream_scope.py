"""Scope-isolation regressions for network consumers outside the REST router."""

from __future__ import annotations

import importlib
import json
from typing import Any

from fastapi.testclient import TestClient
from network_scenario import PROD_SUB, PROD_SUBNET, PROD_VNET, UAT_SUB, network_rows

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network.service import NetworkIntelligenceService, NetworkScope
from onboarding.service import SubscriptionOnboardingService
from operations.tools import STATUS_OK, call_tool

TOKEN = "network-downstream-token-0123456789"
PROD_NIC = (
    f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/"
    "microsoft.network/networkinterfaces/nic-prod-1"
)
PROD_LB = (
    f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/"
    "microsoft.network/loadbalancers/lb-prod"
)


def _foreign_private_link_row() -> dict[str, Any]:
    resource_id = (
        f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/"
        "microsoft.keyvault/vaults/kv-foreign"
    )
    payload = {
        "id": resource_id,
        "name": "kv-foreign",
        "entityType": "Resource",
        "subscriptionId": UAT_SUB,
        "connection_id": "conn-uat",
        "resourceType": "Microsoft.KeyVault/vaults",
        "publicNetworkAccess": "Enabled",
    }
    return {
        "subscription_id": UAT_SUB,
        "resource_id": resource_id,
        "entity_type": "Resource",
        "name": "kv-foreign",
        "payload_json": json.dumps(payload),
    }


def _scoped_service() -> NetworkIntelligenceService:
    return NetworkIntelligenceService.from_rows(
        [*network_rows(), _foreign_private_link_row()],
        semantic_relationships=(
            {
                "subject_id": PROD_VNET,
                "object_id": PROD_SUBNET,
                "predicate": "hosts",
            },
        ),
    )


class _Context:
    provider_runtime = None
    hybrid_network_provider = None

    def __init__(self, service: NetworkIntelligenceService) -> None:
        self.service = service

    def resolve_provider(self, name: str):
        return self.service if name == "network" else None


def _assert_scoped_rows(rows: list[dict[str, Any]]) -> None:
    assert all(row.get("subscription_id", "") in {"", PROD_SUB} for row in rows)
    assert not any(row.get("resource_name") == "kv-foreign" for row in rows)


def test_agent_network_tools_inherit_service_scope_isolation() -> None:
    context = _Context(_scoped_service())
    scope = Scope.from_mapping({"subscription": [PROD_SUB]})

    topology = call_tool("network_topology", {}, context=context, scope=scope)
    analysis = call_tool("firewall_nsg_gaps", {}, context=context, scope=scope)

    assert topology.status == STATUS_OK
    assert analysis.status == STATUS_OK
    _assert_scoped_rows(topology.data["topology"]["resources"])
    _assert_scoped_rows(analysis.data["gaps"])
    _assert_scoped_rows(analysis.data["rule_findings"])


def _twin_client(tmp_path) -> TestClient:
    principal = Principal(
        subject="network-reader@example.com",
        grants=(
            Grant(
                "reader",
                Scope.from_mapping({"subscription": [PROD_SUB]}),
            ),
        ),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator({TOKEN: principal}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=_scoped_service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def test_digital_twin_router_inherits_service_scope_isolation(tmp_path) -> None:
    response = _twin_client(tmp_path).get(
        "/api/v1/twin/graph",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    resources = [
        entity
        for entity in response.json()["data"]["entities"]
        if entity["kind"] == "resource"
    ]
    assert resources
    assert all(
        entity["properties"].get("subscription", "") in {"", PROD_SUB}
        for entity in resources
    )


def test_azure_mcp_server_is_only_a_relay_for_network_topology() -> None:
    mcp_relay = importlib.import_module("mcp_server.app")

    assert not hasattr(mcp_relay, "TOOL_REGISTRY")
    assert not any(
        "network" in route.path or "topology" in route.path
        for route in mcp_relay.app.routes
    )


def _load_balancer_rows() -> list[dict[str, Any]]:
    payload = {
        "id": PROD_LB,
        "name": "lb-prod",
        "entityType": "LoadBalancer",
        "subscriptionId": PROD_SUB,
        "connection_id": "conn-prod",
        "vnetId": PROD_VNET,
        "subnetId": PROD_SUBNET,
        "backendResourceIds": [PROD_NIC],
    }
    return [
        *network_rows(),
        {
            "subscription_id": PROD_SUB,
            "resource_id": PROD_LB,
            "entity_type": "LoadBalancer",
            "name": "lb-prod",
            "payload_json": json.dumps(payload),
        },
    ]


def test_scoped_semantic_provenance_preserves_deduplicated_lb_edges() -> None:
    rows = _load_balancer_rows()
    baseline = NetworkIntelligenceService.from_rows(rows)
    with_semantics = NetworkIntelligenceService.from_rows(
        rows,
        semantic_relationships=(
            {
                "subject_id": PROD_VNET,
                "object_id": PROD_SUBNET,
                "predicate": "hosts",
            },
            {
                "subject_id": PROD_LB,
                "object_id": PROD_NIC,
                "predicate": "loadBalances",
            },
        ),
    )
    scoped = with_semantics.scoped(NetworkScope(subscription_ids=(PROD_SUB,)))

    baseline_relationships = baseline.scoped(
        NetworkScope(subscription_ids=(PROD_SUB,))
    ).topology.to_dict()["relationships"]
    scoped_relationships = scoped.topology.to_dict()["relationships"]

    assert {item["relationship_type"] for item in scoped_relationships} == {
        item["relationship_type"] for item in baseline_relationships
    }
    baseline_lb_edges = {
        (item["source"], item["target"], item["relationship_type"])
        for item in baseline_relationships
        if item["source"] == PROD_LB.casefold()
        or item["target"] == PROD_LB.casefold()
    }
    lb_edges = [
        item
        for item in scoped_relationships
        if item["source"] == PROD_LB.casefold()
        or item["target"] == PROD_LB.casefold()
    ]
    assert {
        (item["source"], item["target"], item["relationship_type"])
        for item in lb_edges
    } == baseline_lb_edges
    assert len({item["id"] for item in lb_edges}) == len(lb_edges)
