"""Nine-dimension isolation for Network and its downstream consumers."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from network_scenario import PROD_SUB, UAT_SUB

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.routers.governance import _network_sections
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network.models import (
    AzureFirewall,
    NetworkGateway,
    NetworkSnapshot,
    PrivateDnsZone,
    VNet,
)
from network.service import NetworkIntelligenceService, NetworkScope
from onboarding.service import SubscriptionOnboardingService
from operations.tools import STATUS_OK, _network_scope, call_tool

TOKEN = "network-dimensions-fixture-token"
DIMENSIONS = {
    "subscription_connection": ("conn-prod",),
    "subscription": (PROD_SUB,),
    "environment": ("prod",),
    "business_service": ("payments",),
    "application": ("checkout",),
    "owner": ("platform-owner",),
    "support_team": ("platform",),
    "region": ("eastus",),
    "criticality": ("high",),
}
ATTRIBUTES = {
    "connection_id": "conn-prod",
    "subscriptionId": PROD_SUB,
    "environmentName": "prod",
    "businessServiceName": "payments",
    "applicationName": "checkout",
    "ownerName": "platform-owner",
    "supportTeam": "platform",
    "region": "eastus",
    "location": "eastus",
    "criticality": "high",
}
FOREIGN = {
    "subscription_connection": {"connection_id": "conn-other"},
    "subscription": {"subscriptionId": UAT_SUB},
    "environment": {"environmentName": "uat"},
    "business_service": {"businessServiceName": "other"},
    "application": {"applicationName": "other"},
    "owner": {"ownerName": "other"},
    "support_team": {"supportTeam": "other"},
    "region": {"region": "westus"},
    "criticality": {"criticality": "low"},
}
GRANT_DIMENSIONS = {"subscription", "business_service"}


def _vnet_id(name: str, subscription: str = PROD_SUB) -> str:
    return (
        f"/subscriptions/{subscription}/resourcegroups/rg/providers/"
        f"microsoft.network/virtualnetworks/{name}"
    )


def _service() -> NetworkIntelligenceService:
    rows: list[dict[str, Any]] = []
    cases = [
        ("matching", {}),
        *FOREIGN.items(),
        (
            "unknown",
            {"supportTeam": "", "region": "", "location": "", "criticality": ""},
        ),
    ]
    for index, (name, override) in enumerate(cases):
        attributes = {**ATTRIBUTES, **override}
        vnet_id = _vnet_id(name, attributes["subscriptionId"])
        for entity_type, resource_id in (
            ("VNet", vnet_id),
            ("Subnet", f"{vnet_id}/subnets/app"),
        ):
            rows.append(
                {
                    "resource_id": resource_id,
                    "entity_type": entity_type,
                    "payload_json": json.dumps(
                        {
                            **attributes,
                            "id": resource_id,
                            "name": name,
                            "vnetId": vnet_id,
                            "addressPrefixes": [f"10.{index}.0.0/24"],
                        }
                    ),
                }
            )
    return NetworkIntelligenceService.from_rows(rows)


class _Context:
    provider_runtime = None
    hybrid_network_provider = None

    def resolve_provider(self, name: str, **kwargs: Any):
        del kwargs
        return _service() if name == "network" else None


def _client(tmp_path, *, restricted: bool) -> TestClient:
    grant_scope = (
        Scope.from_mapping(
            {key: value for key, value in DIMENSIONS.items() if key in GRANT_DIMENSIONS}
        )
        if restricted
        else Scope()
    )
    principal = Principal(
        subject="network-reader@example.com",
        grants=(Grant("reader", grant_scope),),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator({TOKEN: principal}),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_provider=_service,
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _query_dimensions(*, restricted: bool) -> list[tuple[str, str]]:
    return [
        (dimension, value)
        for dimension, values in DIMENSIONS.items()
        if not restricted or dimension not in GRANT_DIMENSIONS
        for value in values
    ]


def _assert_matching_resources(
    resources: list[dict[str, Any]], *, prefix: str = ""
) -> None:
    vnet_id = _vnet_id("matching")
    assert {row["id"] for row in resources} == {
        f"{prefix}{vnet_id}",
        f"{prefix}{vnet_id}/subnets/app",
    }


def test_canonical_projection_retains_all_nine_dimensions_and_tool_fallback() -> None:
    selection = Scope.from_mapping(DIMENSIONS)
    projected = NetworkScope.from_dimensions(selection.dimensions)
    assert projected == NetworkScope(
        connection_ids=("conn-prod",),
        subscription_ids=(PROD_SUB,),
        environments=("prod",),
        business_services=("payments",),
        applications=("checkout",),
        owners=("platform-owner",),
        support_teams=("platform",),
        regions=("eastus",),
        criticalities=("high",),
    )
    assert _network_scope(selection, default_subscription_ids=(UAT_SUB,)) == projected
    no_subscription = Scope.from_mapping(
        {key: value for key, value in DIMENSIONS.items() if key != "subscription"}
    )
    assert (
        _network_scope(no_subscription, default_subscription_ids=(PROD_SUB,))
        == projected
    )
    assert NetworkScope.from_dimensions({"region": ("westus", "eastus")}).regions == (
        "eastus",
        "westus",
    )


def test_projection_rejects_unknown_dimensions_instead_of_widening() -> None:
    with pytest.raises(
        ValueError, match="Unsupported network scope dimensions: future"
    ):
        NetworkScope.from_dimensions({"future": ("restricted",)})


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_each_dimension_filters_resources_before_topology(dimension: str) -> None:
    selection = NetworkScope.from_dimensions({dimension: DIMENSIONS[dimension]})
    scoped = _service().scoped(selection)
    assert any(item.name == "matching" for item in scoped.snapshot.vnets)
    assert not any(item.name == dimension for item in scoped.snapshot.vnets)
    assert not any(item.name == dimension for item in scoped.snapshot.subnets)


def test_combined_dimensions_exclude_unknown_metadata_and_preserve_native_location() -> (
    None
):
    service = _service()
    declared_region = next(
        item for item in service.snapshot.vnets if item.name == "region"
    )
    assert declared_region.location == "eastus"
    assert declared_region.region == "westus"
    scoped = service.scoped(NetworkScope.from_dimensions(DIMENSIONS))
    assert [item.name for item in scoped.snapshot.vnets] == ["matching"]
    assert [item.name for item in scoped.snapshot.subnets] == ["matching"]
    assert scoped.analyze().summary()["isolated_vnet_count"] == 1
    assert NetworkScope.from_dimensions({}).is_empty
    assert len(service.scoped(NetworkScope()).snapshot.vnets) == 11


@pytest.mark.parametrize("dimension", ["support_team", "region", "criticality"])
def test_missing_metadata_does_not_match_a_selected_dimension(dimension: str) -> None:
    selection = NetworkScope.from_dimensions({dimension: DIMENSIONS[dimension]})
    unknown = VNet(resource_id=_vnet_id("unknown"), name="unknown")
    assert not selection.is_empty
    assert not selection.matches(unknown)
    assert selection.filter_snapshot(NetworkSnapshot(vnets=(unknown,))).vnets == ()


@pytest.mark.parametrize(
    "metadata",
    [
        {"support_team": "Platform", "region": "westus", "criticality": "high"},
        {
            "support_team_name": "Platform",
            "location": "eastus",
            "severity_tier": "high",
        },
        {"supportTeam": "Platform", "location": "eastus", "criticality": "high"},
        {
            "location": "eastus",
            "tags": {"SUPPORTTEAM": "Platform", "CRITICALITY": "high"},
        },
    ],
)
def test_resource_metadata_accepts_canonical_columns_and_tag_aliases(metadata) -> None:
    resource = NetworkIntelligenceService.from_rows(
        [{"entity_type": "VNet", "resource_id": _vnet_id("metadata"), **metadata}]
    ).snapshot.vnets[0]
    assert resource.support_team == "Platform"
    assert resource.criticality == "high"
    assert resource.region == metadata.get("region", metadata.get("location", ""))
    assert resource.to_dict()["support_team"] == "Platform"
    assert resource.to_dict()["criticality"] == "high"
    assert resource.to_dict()["region"] == resource.region
    assert NetworkScope(support_teams=("PLATFORM",), criticalities=("HIGH",)).matches(
        resource
    )


@pytest.mark.parametrize("restricted", [False, True], ids=["query", "grant-plus-query"])
def test_rest_topology_enforces_all_dimensions(tmp_path, restricted: bool) -> None:
    response = _client(tmp_path, restricted=restricted).get(
        "/api/v1/network/topology",
        params=[*_query_dimensions(restricted=restricted), ("view", "full")],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    _assert_matching_resources(response.json()["data"]["topology"]["resources"])
    assert response.json()["data"]["summary"]["isolated_vnet_count"] == 1


@pytest.mark.parametrize(
    ("dimension", "other_value", "other_subscription"),
    [("region", "westus", PROD_SUB), ("subscription", UAT_SUB, UAT_SUB)],
)
def test_repeated_dimensions_union_values_without_dropping_other_constraints(
    tmp_path,
    dimension: str,
    other_value: str,
    other_subscription: str,
) -> None:
    response = _client(tmp_path, restricted=False).get(
        "/api/v1/network/topology",
        params=[
            *_query_dimensions(restricted=False),
            (dimension, other_value),
            ("view", "full"),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    expected_vnets = {_vnet_id("matching"), _vnet_id(dimension, other_subscription)}
    assert {row["id"] for row in response.json()["data"]["topology"]["resources"]} == (
        expected_vnets
        | {f"{resource_id}/subnets/app" for resource_id in expected_vnets}
    )
    assert response.json()["data"]["summary"]["isolated_vnet_count"] == 2


@pytest.mark.parametrize(
    "dimension", ["matching", "support_team", "region", "criticality"]
)
def test_scoped_flow_resolves_only_matching_endpoints(tmp_path, dimension: str) -> None:
    source = f"{_vnet_id(dimension)}/subnets/app"
    response = _client(tmp_path, restricted=True).get(
        "/api/v1/network/traffic-flow",
        params=[
            *_query_dimensions(restricted=True),
            ("source", source),
            ("destination", "Internet"),
        ],
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["source"]["subnet_id"] == (source if dimension == "matching" else "")
    if dimension != "matching":
        assert result["verdict"] == "indeterminate"
        assert result["unknowns"]


def test_network_tools_and_governance_use_the_same_complete_projection() -> None:
    selection = Scope.from_mapping(DIMENSIONS)
    tool = call_tool("network_topology", {}, context=_Context(), scope=selection)
    assert tool.status == STATUS_OK
    assert tool.data["summary"]["isolated_vnet_count"] == 1
    sections = _network_sections(_Context(), selection, "network", [])
    assert sections["summary"]["isolated_vnet_count"] == 1
    assert all(
        row["id"].startswith(_vnet_id("matching"))
        for row in sections["topology"]["resources"]
    )


def test_twin_network_projection_obeys_principal_dimensions(tmp_path) -> None:
    response = _client(tmp_path, restricted=True).get(
        "/api/v1/twin/graph",
        params=_query_dimensions(restricted=True),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    resources = [
        item
        for item in response.json()["data"]["entities"]
        if item["kind"] == "resource"
    ]
    _assert_matching_resources(resources, prefix="resource:")


def test_derived_shared_services_preserve_all_scope_attributes() -> None:
    hub_id = _vnet_id("hub")
    metadata = {
        "subscription_id": PROD_SUB,
        "connection_id": "conn-prod",
        "environment": "prod",
        "business_service": "payments",
        "application": "checkout",
        "owner": "platform-owner",
        "support_team": "platform",
        "location": "eastus",
        "region": "westus",
        "criticality": "high",
    }
    snapshot = NetworkSnapshot(
        vnets=(VNet(resource_id=hub_id, name="hub", **metadata),),
        firewalls=(
            AzureFirewall(
                resource_id=f"{hub_id}/fw", name="fw", vnet_id=hub_id, **metadata
            ),
        ),
        gateways=(
            NetworkGateway(
                resource_id=f"{hub_id}/vpn",
                name="vpn",
                entity_type="VpnGateway",
                vnet_id=hub_id,
                **metadata,
            ),
        ),
        private_dns_zones=(
            PrivateDnsZone(
                resource_id=f"{hub_id}/dns",
                name="dns",
                linked_vnet_ids=(hub_id,),
                **metadata,
            ),
        ),
    )
    services = NetworkIntelligenceService(snapshot).topology.shared_services
    assert {service.service_kind for service in services} == {
        "firewall",
        "vpn",
        "private_dns",
    }
    selection = NetworkScope.from_dimensions({**DIMENSIONS, "region": ("westus",)})
    assert all(selection.matches(service) for service in services)
    assert all(service.location == "eastus" for service in services)
