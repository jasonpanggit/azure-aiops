from __future__ import annotations

from dataclasses import replace

from network_scale_fixtures import small_estate

import network.service as network_service_module
from api.evidence import classify_freshness
from fabric_pipelines.topology_pipeline import derive_edges, to_topology_edge_row
from network import NetworkIntelligenceService, load_network_snapshot
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
            (
                "/subscriptions/sub-a/resourcegroups/rg/providers/"
                "microsoft.network/azurefirewalls/fw"
            ),
            _subnet_id("AzureFirewallSubnet").casefold(),
        ),
        (
            (
                "/subscriptions/sub-a/resourcegroups/rg/providers/"
                "microsoft.network/bastionhosts/bastion"
            ),
            _subnet_id("AzureBastionSubnet").casefold(),
        ),
        (
            (
                "/subscriptions/sub-a/resourcegroups/rg/providers/"
                "microsoft.network/networkinterfaces/nic"
            ),
            _subnet_id("workloads").casefold(),
        ),
        (
            (
                "/subscriptions/sub-a/resourcegroups/rg/providers/"
                "microsoft.network/privateendpoints/pe"
            ),
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


def test_mixed_case_estate_preserves_subnet_containment_edges() -> None:
    snapshot = small_estate(mixed_case_ids=True)
    payload = NetworkIntelligenceService(snapshot).topology.to_dict()
    relationships = {
        (item["source"], item["relationship_type"], item["target"])
        for item in payload["relationships"]
    }

    assert all(
        (subnet.vnet_id, "contains", subnet.resource_id) in relationships
        for subnet in snapshot.subnets
    )


def test_mixed_case_subnet_endpoint_reference_is_authoritative() -> None:
    snapshot = small_estate(mixed_case_ids=True)
    endpoint = snapshot.private_endpoints[0]
    snapshot = replace(
        snapshot,
        private_endpoints=(replace(endpoint, subnet_id=""),),
    )
    payload = NetworkIntelligenceService(snapshot).topology.to_dict()
    relationships = {
        (item["source"], item["relationship_type"], item["target"])
        for item in payload["relationships"]
    }

    assert (
        snapshot.subnets[0].resource_id,
        "hosts",
        endpoint.resource_id,
    ) in relationships


def test_mixed_case_semantic_relationship_endpoints_are_normalized() -> None:
    snapshot = small_estate()
    source = snapshot.vnets[0].resource_id
    target = snapshot.subnets[0].resource_id
    service = NetworkIntelligenceService(
        snapshot,
        semantic_relationships=(
            {
                "subject_id": source.upper(),
                "object_id": target.upper(),
                "predicate": "hosts",
            },
        ),
    )

    assert service.semantic_relationships[0]["subject_id"] == source
    assert service.semantic_relationships[0]["object_id"] == target
    assert any(
        item["source"] == source
        and item["target"] == target
        and item["relationship_type"] == "hosts"
        for item in service.topology.to_dict()["relationships"]
    )


def test_consistent_topology_reports_no_dropped_relationships() -> None:
    payload = NetworkIntelligenceService(small_estate()).topology.to_dict()

    assert payload["counts"]["dropped_relationships"] == {}
    assert payload.get("warnings", []) == []


def test_dangling_relationship_is_counted_without_disclosing_endpoint_ids() -> None:
    snapshot = small_estate()
    missing_endpoint_id = (
        "/subscriptions/SECRET/resourceGroups/PRIVATE/providers/"
        "Microsoft.Network/privateEndpoints/Missing"
    )
    subnet = replace(
        snapshot.subnets[0],
        private_endpoint_ids=(missing_endpoint_id,),
    )
    snapshot = replace(snapshot, subnets=(subnet, *snapshot.subnets[1:]))

    payload = NetworkIntelligenceService(snapshot).topology.to_dict()

    assert payload["counts"]["dropped_relationships"]["hosts"] == 1
    assert payload["warnings"]
    warning_text = " ".join(payload["warnings"])
    assert "hosts" in warning_text
    assert missing_endpoint_id.casefold() not in warning_text.casefold()


def test_snapshot_observation_backfills_unstamped_ontology_rows() -> None:
    row = {
        "entity_type": "VNet",
        "resource_id": VNET_ID,
        "name": "VNet-A",
        "payload_json": "{}",
    }

    service = NetworkIntelligenceService.from_rows([row], observed_at=OBSERVED)

    assert service.snapshot.observed_at == OBSERVED
    assert classify_freshness(service.snapshot.observed_at) in {
        "fresh",
        "aging",
        "stale",
    }


def test_semantic_resolves_for_edge_is_projected() -> None:
    snapshot = small_estate()
    zone = snapshot.private_dns_zones[0]
    vnet = snapshot.vnets[0]
    service = NetworkIntelligenceService(
        snapshot,
        semantic_relationships=(
            {
                "subject_id": zone.resource_id,
                "object_id": vnet.resource_id,
                "predicate": "resolvesFor",
            },
        ),
    )

    assert any(
        item["source"] == zone.resource_id
        and item["target"] == vnet.resource_id
        and item["relationship_type"] == "resolves_for"
        for item in service.topology.to_dict()["relationships"]
    )


def test_parentless_virtual_network_link_warns_without_dangling_edge() -> None:
    link_row = _base(
        f"{ZONE_ID}/virtualNetworkLinks/orphan",
        "orphan",
        "microsoft.network/privatednszones/virtualnetworklinks",
        {"virtualNetwork": {"id": VNET_ID}},
    )

    graph = Normalizer().normalize(
        _network_payload([link_row]),
        _observed_datetime(),
    )

    assert not [
        item
        for item in graph.relationships
        if str(item.get("predicate") or "").casefold() == "resolvesfor"
    ]
    assert any("parent zone" in warning.casefold() for warning in graph.warnings)


def test_flow_observations_are_forwarded_and_provenance_is_three_state(
    monkeypatch,
) -> None:
    flow_edge = {
        "subject_id": "/flow/1",
        "object_id": "/rule/1",
        "predicate": "trafficObserved",
        "attributes": {"dataSource": "traffic_analytics"},
    }
    forwarded: list[tuple[dict, ...]] = []

    def _capture(snapshot, flow_observations=None, **kwargs):
        del snapshot, kwargs
        forwarded.append(tuple(flow_observations or ()))
        return ()

    monkeypatch.setattr(network_service_module, "analyze_rules", _capture)

    absent = NetworkIntelligenceService(NetworkSnapshot())
    present = NetworkIntelligenceService(
        NetworkSnapshot(),
        semantic_relationships=(flow_edge,),
    )
    analyzed = NetworkIntelligenceService(
        NetworkSnapshot(),
        semantic_relationships=(flow_edge,),
        flow_observations=(flow_edge,),
    )

    assert absent.topology.to_dict()["flow_log_provenance"] == {
        "state": "not_ingested",
        "observed_flow_count": 0,
    }
    assert present.topology.to_dict()["flow_log_provenance"] == {
        "state": "ingested_not_analyzed",
        "observed_flow_count": 1,
    }
    assert analyzed.rule_findings == ()
    assert forwarded == [(flow_edge,)]
    assert analyzed.topology.to_dict()["flow_log_provenance"] == {
        "state": "analyzed",
        "observed_flow_count": 1,
    }


def test_loader_ignores_invalid_timestamps_and_compares_normalized_instants() -> None:
    rows = [
        {
            "entity_type": "VNet",
            "resource_id": "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/a",
            "name": "a",
            "observed_at": "not-a-date",
            "payload_json": "{}",
        },
        {
            "entity_type": "VNet",
            "resource_id": "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/b",
            "name": "b",
            "observed_at": "2026-09-06T02:00:00+01:00",
            "payload_json": "{}",
        },
        {
            "entity_type": "VNet",
            "resource_id": "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/c",
            "name": "c",
            "observed_at": "2026-09-06T00:30:00Z",
            "payload_json": "{}",
        },
    ]

    snapshot = load_network_snapshot(
        rows,
        observed_at="also-not-a-date",
    )

    assert snapshot.observed_at == "2026-09-06T01:00:00Z"


def _observed_datetime():
    from datetime import UTC, datetime

    return datetime(2026, 9, 1, tzinfo=UTC)
