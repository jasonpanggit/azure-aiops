"""Measured topology scale baselines and Phase 12 performance gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import combinations
from time import perf_counter

import pytest

import network.topology as topology_module
from network.models import NetworkSnapshot, VNet, VNetPeering
from network.topology import (
    SUMMARY_BYTE_CEILING,
    SUMMARY_MIN_NODES,
    SUMMARY_NODE_CAP,
    SUMMARY_SMALL_BYTE_CEILING,
    SUMMARY_SMALL_NODE_CAP,
    build_topology,
)
from tests.network_scale_fixtures import (
    EstateShape,
    build_estate,
    enterprise_estate,
    g4_baseline_estate,
    mid_estate,
    small_estate,
)

# G-1 is the RESEARCH-fixed summary budget for the small estate.
G1_NODE_CAP = 200
G1_BYTE_CEILING = 250_000

# G-2 deliberately matches the UI full-detail guard. At the measured lean
# summary rate of 963 bytes/node, 1,500 nodes require about 1.44 MB. A 2 MB
# ceiling leaves roughly 38% for edges/evidence while remaining 1.65x below
# the measured 3.3 MB uncapped enterprise summary.
G2_NODE_CAP = 1_500
G2_BYTE_CEILING = 2_000_000

G3_BUILD_SECONDS = 1.0


@dataclass(frozen=True)
class PayloadMeasurement:
    nodes: int
    edges: int
    serialized_bytes: int


def _client_node_ids(payload: dict) -> set[str]:
    """Mirror the resource graph's case-insensitive node identity rules."""
    node_ids = {
        str(resource["id"]).casefold()
        for resource in payload.get("resources", [])
    }
    node_ids.update(
        str(peer_id).casefold()
        for peer_id in payload.get("unresolved_peer_vnet_ids", [])
        if peer_id
    )
    node_ids.update(
        str(peer.get("vnet_id") or "").casefold()
        for peer in payload.get("unresolved_peers", [])
        if peer.get("vnet_id")
    )
    for link in payload.get("links", []):
        local_id = str(link.get("local_vnet_id") or "").casefold()
        remote_id = str(link.get("remote_vnet_id") or "").casefold()
        if local_id in node_ids and remote_id:
            node_ids.add(remote_id)
    return node_ids


def _client_group_ids(payload: dict, node_ids: set[str]) -> set[str]:
    """Mirror the subscription compound nodes created by the web client."""
    subscription_ids = {
        str(resource.get("subscription_id") or "").casefold()
        for resource in payload.get("resources", [])
        if str(resource.get("id") or "").casefold() in node_ids
        and resource.get("subscription_id")
    }
    for node_id in node_ids:
        segments = node_id.strip("/").split("/")
        if len(segments) > 1 and segments[0] == "subscriptions":
            subscription_ids.add(segments[1])
    return {f"subscription:{subscription_id}" for subscription_id in subscription_ids}


def _measure_payload(
    snapshot: NetworkSnapshot,
    *,
    detail: str = "full",
) -> PayloadMeasurement:
    payload = build_topology(snapshot).to_dict(detail=detail)
    return PayloadMeasurement(
        nodes=len(payload["resources"]),
        edges=len(payload["relationships"]),
        serialized_bytes=len(json.dumps(payload)),
    )


@pytest.mark.parametrize(
    ("builder", "vnets", "subnets", "nsgs", "rules"),
    [
        (small_estate, 20, 60, 40, 1_000),
        (mid_estate, 60, 360, 150, 4_500),
        (enterprise_estate, 200, 1_600, 600, 24_000),
    ],
)
def test_fixtures_build_expected_shapes(
    builder: Callable[[], NetworkSnapshot],
    vnets: int,
    subnets: int,
    nsgs: int,
    rules: int,
) -> None:
    snapshot = builder()

    assert len(snapshot.vnets) == vnets
    assert len(snapshot.subnets) == subnets
    assert len(snapshot.nsgs) == nsgs
    assert sum(len(nsg.rules) for nsg in snapshot.nsgs) == rules
    assert snapshot.route_tables
    assert snapshot.firewall_policies
    assert snapshot.firewall_collections
    assert snapshot.private_endpoints
    assert snapshot.private_dns_zones
    assert snapshot.private_link_resources


def test_full_detail_payload_baseline_small() -> None:
    topology = build_topology(small_estate())
    payload = topology.to_dict()
    measurement = PayloadMeasurement(
        nodes=len(payload["resources"]),
        edges=len(payload["relationships"]),
        serialized_bytes=len(json.dumps(payload)),
    )

    # RESEARCH measured 1,330 nodes / 1,260 edges / 2.99 MB. The fixture
    # reproduces the node count exactly; broad edge/byte bands keep this a
    # regression detector rather than a serializer-format lock.
    assert measurement.nodes == 1_330
    assert topology.projected_full_node_count() == measurement.nodes
    assert 1_000 <= measurement.edges <= 1_600
    assert 2_000_000 <= measurement.serialized_bytes <= 5_000_000


@pytest.mark.parametrize(
    ("builder", "expected_nodes", "byte_band"),
    [
        (small_estate, 1_330, (2_000_000, 5_000_000)),
        (mid_estate, 6_930, (12_000_000, 30_000_000)),
        (enterprise_estate, 34_600, (60_000_000, 145_000_000)),
    ],
)
def test_full_detail_payload_baselines(
    builder: Callable[[], NetworkSnapshot],
    expected_nodes: int,
    byte_band: tuple[int, int],
) -> None:
    measurement = _measure_payload(builder())

    assert measurement.nodes == expected_nodes
    assert byte_band[0] <= measurement.serialized_bytes <= byte_band[1]


def test_enterprise_build_latency_budget() -> None:
    snapshot = enterprise_estate()

    started = perf_counter()
    topology = build_topology(snapshot)
    elapsed = perf_counter() - started

    assert topology.snapshot is snapshot
    assert elapsed < G3_BUILD_SECONDS


def test_summary_budgets_match_the_measured_contract() -> None:
    assert SUMMARY_SMALL_NODE_CAP == G1_NODE_CAP
    assert SUMMARY_SMALL_BYTE_CEILING == G1_BYTE_CEILING
    assert SUMMARY_NODE_CAP == G2_NODE_CAP
    assert SUMMARY_BYTE_CEILING == G2_BYTE_CEILING


def test_g4_default_detail_is_byte_identical_to_the_pre_change_contract() -> None:
    """Gate G-4 runs before the summary gates and locks the additive default."""
    topology = build_topology(g4_baseline_estate())
    default_payload = topology.to_dict()
    explicit_full_payload = topology.to_dict(detail="full")
    canonical = json.dumps(
        default_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    assert default_payload == explicit_full_payload
    assert len(canonical) == 111_155
    assert hashlib.sha256(canonical).hexdigest() == (
        "86d8d899a856e64b9aca1974471e6cf8eee4d4abc2dbad02b26930a6a0091440"
    )


def test_g1_small_summary_payload_budget() -> None:
    """Gate G-1 asserts both visible node count and serialized byte cost."""
    payload = build_topology(small_estate()).to_dict(detail="summary")
    resource_types = {item["entity_type"] for item in payload["resources"]}
    controls = {
        item["entity_type"]: item
        for item in payload["resources"]
        if item["entity_type"]
        in {
            "NetworkSecurityGroup",
            "RouteTable",
            "AzureFirewall",
            "FirewallPolicy",
            "FirewallRuleCollection",
        }
    }

    node_ids = _client_node_ids(payload)
    assert len(node_ids) + len(_client_group_ids(payload, node_ids)) <= G1_NODE_CAP
    assert len(json.dumps(payload)) <= G1_BYTE_CEILING
    assert resource_types.isdisjoint(
        {"NetworkSecurityRule", "Route", "FirewallRule"}
    )
    assert "rules" not in controls["NetworkSecurityGroup"]["details"]
    assert "routes" not in controls["RouteTable"]["details"]
    assert "rules" not in controls["AzureFirewall"]["details"]
    assert "rule_collections" not in controls["FirewallPolicy"]["details"]
    assert "rules" not in controls["FirewallRuleCollection"]["details"]


def test_g2_enterprise_summary_payload_budget() -> None:
    """Gate G-2 proves the enterprise response is bounded and honest."""
    payload = build_topology(enterprise_estate()).to_dict(detail="summary")

    node_ids = _client_node_ids(payload)
    assert len(node_ids) + len(_client_group_ids(payload, node_ids)) <= G2_NODE_CAP
    assert len(json.dumps(payload)) <= G2_BYTE_CEILING
    assert payload["coverage"]["total"] > G2_NODE_CAP
    assert payload["coverage"]["returned"] == len(payload["resources"])
    assert payload["coverage"]["truncated"] is True


def test_summary_node_budget_includes_unresolved_and_group_nodes() -> None:
    """Client-added peer and subscription nodes share the 1,500-node budget."""
    vnets = tuple(
        VNet(
            resource_id=f"/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-{index}",
            name=f"vnet-{index}",
            subscription_id="sub-a",
            resource_group="rg",
        )
        for index in range(800)
    )
    peerings = tuple(
        VNetPeering(
            resource_id=f"{vnet.resource_id}/virtualNetworkPeerings/to-ghost-{index}",
            name=f"to-ghost-{index}",
            subscription_id="sub-a",
            resource_group="rg",
            local_vnet_id=vnet.resource_id,
            remote_vnet_id=(
                "/subscriptions/sub-z/resourceGroups/rg/providers/"
                f"Microsoft.Network/virtualNetworks/ghost-{index}"
            ),
            peering_state="Connected",
        )
        for index, vnet in enumerate(vnets)
    )

    payload = build_topology(
        NetworkSnapshot(vnets=vnets, peerings=peerings)
    ).to_dict(detail="summary")
    node_ids = _client_node_ids(payload)

    assert len(node_ids) + len(_client_group_ids(payload, node_ids)) <= SUMMARY_NODE_CAP
    assert len(json.dumps(payload).encode()) <= SUMMARY_BYTE_CEILING
    assert payload["coverage"]["collections"]["unresolved_peer_vnet_ids"][
        "truncated"
    ] is True


def test_dense_mesh_summary_bounds_the_complete_serialized_payload() -> None:
    """A dense peering mesh keeps useful nodes while every collection is bounded."""
    snapshot = build_estate(EstateShape(100, 3, 200, 20, 10_000))
    peerings = tuple(
        VNetPeering(
            resource_id=(
                f"{local.resource_id}/virtualNetworkPeerings/to-{remote.name}"
            ),
            name=f"{local.name}-to-{remote.name}",
            subscription_id=local.subscription_id,
            resource_group=local.resource_group,
            connection_id=local.connection_id,
            local_vnet_id=local.resource_id,
            remote_vnet_id=remote.resource_id,
            peering_state="Connected",
        )
        for local, remote in combinations(snapshot.vnets, 2)
    )
    snapshot = replace(snapshot, peerings=peerings)

    payload = build_topology(snapshot).to_dict(detail="summary")
    serialized_bytes = len(json.dumps(payload).encode())
    link_coverage = payload["coverage"]["collections"]["links"]

    assert len(peerings) == 4_950
    assert SUMMARY_MIN_NODES <= len(payload["resources"]) <= SUMMARY_NODE_CAP
    assert serialized_bytes <= SUMMARY_BYTE_CEILING
    assert link_coverage["total"] == len(peerings)
    assert 0 < link_coverage["returned"] < link_coverage["total"]
    assert payload["coverage"]["collections"]["relationships"]["returned"] > 0


def test_topology_projection_is_computed_once_per_response(monkeypatch) -> None:
    topology = build_topology(small_estate())
    calls = 0
    original = topology_module._topology_resources

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(topology_module, "_topology_resources", counted)

    topology.to_dict(detail="summary")

    assert calls == 1
