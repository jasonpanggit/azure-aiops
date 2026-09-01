from __future__ import annotations

from fabric_pipelines.topology_pipeline import derive_edges, to_topology_edge_row
from network import NetworkIntelligenceService
from network.models import NetworkSnapshot, PrivateDnsZone
from onboarding.graph_normalize import Normalizer
from onboarding.query_catalog import NETWORK_RESOURCE_TYPES

OBSERVED = "2026-09-01T00:00:00Z"
VNET_ID = "/subscriptions/Sub-A/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/VNet-A"
ZONE_ID = (
    "/subscriptions/Sub-A/resourceGroups/RG/providers/"
    "Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net"
)


def _subnet_id(name: str) -> str:
    return f"{VNET_ID}/subnets/{name}"


def _base(resource_id: str, name: str, resource_type: str, properties: dict) -> dict:
    return {
        "id": resource_id,
        "name": name,
        "type": resource_type,
        "tenantId": "tenant-a",
        "subscriptionId": "Sub-A",
        "resourceGroup": "RG",
        "location": "australiaeast",
        "tags": {},
        "properties": properties,
    }


def _raw_network_rows() -> list[dict]:
    subnet_names = (
        "AzureFirewallSubnet",
        "AzureBastionSubnet",
        "workloads",
        "private-endpoints",
    )
    rows = [
        _base(
            VNET_ID,
            "VNet-A",
            "microsoft.network/virtualnetworks",
            {
                "subnets": [
                    {
                        "id": _subnet_id(name),
                        "name": name,
                        "properties": {"addressPrefix": f"10.0.{index}.0/24"},
                    }
                    for index, name in enumerate(subnet_names)
                ]
            },
        ),
        _base(
            "/subscriptions/Sub-A/resourceGroups/RG/providers/Microsoft.Network/azureFirewalls/FW",
            "FW",
            "microsoft.network/azurefirewalls",
            {
                "ipConfigurations": [
                    {"properties": {"subnet": {"id": _subnet_id("AzureFirewallSubnet")}}}
                ]
            },
        ),
        _base(
            "/subscriptions/Sub-A/resourceGroups/RG/providers/Microsoft.Network/bastionHosts/Bastion",
            "Bastion",
            "microsoft.network/bastionhosts",
            {
                "ipConfigurations": [
                    {"properties": {"subnet": {"id": _subnet_id("AzureBastionSubnet")}}}
                ]
            },
        ),
        _base(
            "/subscriptions/Sub-A/resourceGroups/RG/providers/Microsoft.Network/networkInterfaces/NIC",
            "NIC",
            "microsoft.network/networkinterfaces",
            {
                "ipConfigurations": [
                    {"properties": {"subnet": {"id": _subnet_id("workloads")}}}
                ]
            },
        ),
        _base(
            "/subscriptions/Sub-A/resourceGroups/RG/providers/Microsoft.Network/privateEndpoints/PE",
            "PE",
            "microsoft.network/privateendpoints",
            {"subnet": {"id": _subnet_id("private-endpoints")}},
        ),
        _base(
            ZONE_ID,
            "privatelink.vaultcore.azure.net",
            "microsoft.network/privatednszones",
            {},
        ),
        _base(
            f"{ZONE_ID}/virtualNetworkLinks/link-a",
            "link-a",
            "microsoft.network/privatednszones/virtualnetworklinks",
            {"virtualNetwork": {"id": VNET_ID}},
        ),
    ]
    return rows


def _network_payload(rows: list[dict]) -> dict[str, list[dict]]:
    payload: dict[str, list[dict]] = {"resources": rows}
    for family, resource_types in NETWORK_RESOURCE_TYPES.items():
        accepted = {item.casefold() for item in resource_types}
        payload[family] = [
            row
            for row in rows
            if str(row.get("type") or "").casefold() in accepted
        ]
    return payload


def test_raw_arg_rows_build_all_reported_network_links() -> None:
    service = NetworkIntelligenceService.from_arg_rows(
        _raw_network_rows(),
        observed_at=OBSERVED,
    )
    relationships = {
        (row["source"], row["relationship_type"], row["target"])
        for row in service.topology.to_dict()["relationships"]
    }

    expected_attachments = {
        (
            "/subscriptions/sub-a/resourcegroups/rg/providers/"
            "microsoft.network/azurefirewalls/fw",
            _subnet_id("AzureFirewallSubnet").casefold(),
        ),
        (
            "/subscriptions/sub-a/resourcegroups/rg/providers/"
            "microsoft.network/bastionhosts/bastion",
            _subnet_id("AzureBastionSubnet").casefold(),
        ),
        (
            "/subscriptions/sub-a/resourcegroups/rg/providers/"
            "microsoft.network/networkinterfaces/nic",
            _subnet_id("workloads").casefold(),
        ),
        (
            "/subscriptions/sub-a/resourcegroups/rg/providers/"
            "microsoft.network/privateendpoints/pe",
            _subnet_id("private-endpoints").casefold(),
        ),
    }
    for resource_id, subnet_id in expected_attachments:
        assert (resource_id, "attached_to", subnet_id) in relationships
        assert (subnet_id, "hosts", resource_id) in relationships

    assert (ZONE_ID.casefold(), "serves", VNET_ID.casefold()) in relationships


def test_private_endpoint_dns_zone_group_child_enriches_parent() -> None:
    endpoint_id = (
        "/subscriptions/Sub-A/resourceGroups/RG/providers/"
        "Microsoft.Network/privateEndpoints/PE"
    )
    child = _base(
        f"{endpoint_id}/privateDnsZoneGroups/default",
        "default",
        "microsoft.network/privateendpoints/privatednszonegroups",
        {
            "privateDnsZoneConfigs": [
                {
                    "name": "zone",
                    "properties": {"privateDnsZoneId": ZONE_ID},
                }
            ]
        },
    )
    graph = Normalizer().normalize(
        _network_payload(
            [
                _base(
                    endpoint_id,
                    "PE",
                    "microsoft.network/privateendpoints",
                    {"subnet": {"id": _subnet_id("private-endpoints")}},
                ),
                child,
            ]
        ),
        _observed_datetime(),
    )

    endpoints = graph.entities["PrivateEndpoint"]
    assert len(endpoints) == 1
    assert endpoints[0]["privateDnsZoneIds"] == [ZONE_ID.casefold()]


def test_fabric_derivation_preserves_canonical_dns_links() -> None:
    _, edges = derive_edges(
        {
            "network_vnets": [
                _base(
                    VNET_ID,
                    "VNet-A",
                    "microsoft.network/virtualnetworks",
                    {},
                )
            ],
            "network_private_dns_zones": [
                {
                    **_base(
                        ZONE_ID,
                        "privatelink.vaultcore.azure.net",
                        "microsoft.network/privatednszones",
                        {},
                    ),
                    "linkedVnetIds": [VNET_ID],
                }
            ],
        },
        observed=OBSERVED,
    )
    triples = {
        (row["subject_id"], row["predicate"], row["object_id"])
        for row in (to_topology_edge_row(edge) for edge in edges)
    }
    assert (ZONE_ID.casefold(), "resolvesFor", VNET_ID.casefold()) in triples


def test_unlinked_private_dns_zone_produces_zone_level_gap() -> None:
    zone = PrivateDnsZone(
        resource_id=ZONE_ID,
        name="privatelink.vaultcore.azure.net",
    )
    service = NetworkIntelligenceService(
        NetworkSnapshot(private_dns_zones=(zone,))
    )

    gaps = [
        gap
        for gap in service.gaps
        if gap.category == "dns_dependency_gap"
    ]
    assert len(gaps) == 1
    assert gaps[0].resource_id == ZONE_ID.casefold()
    assert gaps[0].resource_type == "PrivateDnsZone"


def test_linked_private_dns_zone_has_no_zone_level_gap() -> None:
    zone = PrivateDnsZone(
        resource_id=ZONE_ID,
        name="privatelink.vaultcore.azure.net",
        linked_vnet_ids=(VNET_ID,),
    )
    service = NetworkIntelligenceService(
        NetworkSnapshot(private_dns_zones=(zone,))
    )

    assert not [
        gap
        for gap in service.gaps
        if gap.category == "dns_dependency_gap"
    ]


def _observed_datetime():
    from datetime import UTC, datetime

    return datetime(2026, 9, 1, tzinfo=UTC)
