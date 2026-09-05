"""Measured topology scale baselines and Phase 12 performance gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

import pytest

import network.topology as topology_module
from network.models import NetworkSnapshot
from network.topology import build_topology
from tests.network_scale_fixtures import (
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
    measurement = _measure_payload(small_estate())

    # RESEARCH measured 1,330 nodes / 1,260 edges / 2.99 MB. The fixture
    # reproduces the node count exactly; broad edge/byte bands keep this a
    # regression detector rather than a serializer-format lock.
    assert measurement.nodes == 1_330
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


def test_g2_budgets_are_declared() -> None:
    assert G1_NODE_CAP == 200
    assert G1_BYTE_CEILING == 250_000
    assert G2_NODE_CAP == 1_500
    assert G2_BYTE_CEILING == 2_000_000


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

    assert len(payload["resources"]) <= G1_NODE_CAP
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

    assert len(payload["resources"]) <= G2_NODE_CAP
    assert len(json.dumps(payload)) <= G2_BYTE_CEILING
    assert payload["coverage"] == {
        "total": 2_600,
        "returned": len(payload["resources"]),
        "truncated": True,
    }


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
