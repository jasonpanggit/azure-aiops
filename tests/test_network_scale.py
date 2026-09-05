"""Measured topology scale baselines and Phase 12 performance gates."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter

import pytest

from network.models import NetworkSnapshot
from network.topology import build_topology
from tests.network_scale_fixtures import (
    enterprise_estate,
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


def _measure_payload(snapshot: NetworkSnapshot) -> PayloadMeasurement:
    payload = build_topology(snapshot).to_dict()
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


@pytest.mark.skip(
    reason="Plan 12-07 adds detail=summary; enable against G1_NODE_CAP and G1_BYTE_CEILING"
)
def test_g1_small_summary_payload_budget() -> None:
    """Gate G-1 is activated by plan 12-07."""


@pytest.mark.skip(
    reason="Plan 12-07 adds enterprise summary truncation; enable against G2_NODE_CAP and G2_BYTE_CEILING"
)
def test_g2_enterprise_summary_payload_budget() -> None:
    """Gate G-2 is activated by plan 12-07."""
