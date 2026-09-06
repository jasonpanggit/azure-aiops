"""Phase 12 closing contracts for network topology downstream consumers."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from api.dependencies import Pagination
from api.routers.network import network_gaps, rule_findings
from api.routers.twin import graph as twin_graph
from api.scope import Scope
from network.models import NetworkSnapshot, VNet, VNetPeering
from network.service import NetworkIntelligenceService, NetworkScope
from network.topology import build_topology
from operations.mcp_server import MCPServer
from operations.tools import STATUS_OK, call_tool
from tests.network_baseline import (
    BASELINE_PATH,
    BaselineArtifactInvalidError,
    BaselineArtifactMissingError,
    capture_default_responses,
    load_baseline,
)
from tests.network_scale_fixtures import (
    EstateShape,
    build_estate,
    g4_baseline_estate,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPORT_COMPONENT = (
    REPOSITORY_ROOT / "web" / "src" / "components" / "network" / "TopologyGraph.tsx"
)

EXPECTED_ADDITIVE_KEYS = {
    (
        "topology",
        ("data", "topology", "counts", "dropped_relationships"),
        "12-03",
    ),
    ("topology", ("data", "topology", "flow_log_provenance"), "12-03"),
    ("topology", ("data", "topology", "unresolved_peers"), "12-03"),
    ("gaps", ("data", "coverage"), "12-07"),
    ("rule_findings", ("data", "coverage"), "12-07"),
    (
        "rule_findings",
        ("data", "findings", "*", "affected_resource_ids"),
        "12-07",
    ),
}
EXPECTED_EXPORT_KEYS = (
    "exported_at",
    "scope",
    "detail_level",
    "coverage",
    "filters",
    "evidence",
    "warnings",
    "knowledge_version",
    "graph_freshness",
    "topology",
)


class _NetworkContext:
    provider_runtime = None
    hybrid_network_provider = None
    hybrid_vulnerability_provider = None
    hybrid_incident_provider = None
    hybrid_remediation_provider = None

    def __init__(self, service: NetworkIntelligenceService) -> None:
        self.service = service

    def resolve_provider(
        self,
        name: str,
        optional: bool = False,
    ) -> NetworkIntelligenceService | None:
        if name == "network":
            return self.service
        if optional:
            return None
        raise AssertionError(f"unexpected provider requested: {name}")


def test_g4_default_routes_match_frozen_baseline_modulo_registered_additions() -> None:
    baseline = load_baseline()
    assert baseline["fixture"] == {
        "name": "g4_baseline_estate",
        "private_link_resource_count": 0,
        "frozen": True,
    }
    additions = {
        (
            item["endpoint"],
            tuple(item["path"]),
            item["introduced_by"],
        )
        for item in baseline["allowed_additive_keys"]
    }
    assert additions == EXPECTED_ADDITIVE_KEYS

    current = capture_default_responses(g4_baseline_estate())
    for endpoint in ("topology", "gaps", "rule_findings"):
        assert_endpoint_contract(endpoint, current[endpoint], baseline)


def test_g4_baseline_loading_fails_closed_for_missing_or_unreadable_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(BaselineArtifactMissingError, match="artifact is missing"):
        load_baseline(tmp_path / "missing.json")

    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{not-json", encoding="utf-8")
    with pytest.raises(BaselineArtifactInvalidError, match="could not be read"):
        load_baseline(unreadable)


def test_private_link_node_additions_require_registered_entity_types() -> None:
    shape = EstateShape(2, 2, 2, 3, 40)
    without_candidates = build_topology(
        build_estate(shape, include_private_link_resources=False)
    ).to_dict()
    with_candidates = build_topology(
        build_estate(shape, include_private_link_resources=True)
    ).to_dict()
    baseline = load_baseline()

    assert_registered_additive_nodes(
        without_candidates,
        with_candidates,
        baseline["allowed_additive_nodes"],
    )

    unexpected = {
        **without_candidates,
        "resources": [
            *without_candidates["resources"],
            {"id": "/subscriptions/sub-a/providers/example/widgets/new", "entity_type": "Widget"},
        ],
    }
    with pytest.raises(AssertionError, match=r"Widget.*not registered"):
        assert_registered_additive_nodes(
            without_candidates,
            unexpected,
            baseline["allowed_additive_nodes"],
        )


def test_wr11_legacy_unresolved_peer_ids_remain_beside_reasoned_entries() -> None:
    vnet_a = VNet(
        resource_id="/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/a",
        name="a",
        subscription_id="sub-a",
        resource_group="rg",
    )
    vnet_b = VNet(
        resource_id="/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/b",
        name="b",
        subscription_id="sub-b",
        resource_group="rg",
    )
    vnet_c_id = (
        "/subscriptions/sub-c/resourceGroups/rg/providers/"
        "Microsoft.Network/virtualNetworks/c"
    )
    peer_b = VNetPeering(
        resource_id=f"{vnet_a.resource_id}/virtualNetworkPeerings/to-b",
        name="to-b",
        subscription_id="sub-a",
        resource_group="rg",
        local_vnet_id=vnet_a.resource_id,
        remote_vnet_id=vnet_b.resource_id,
        peering_state="Connected",
    )
    peer_c = VNetPeering(
        resource_id=f"{vnet_a.resource_id}/virtualNetworkPeerings/to-c",
        name="to-c",
        subscription_id="sub-a",
        resource_group="rg",
        local_vnet_id=vnet_a.resource_id,
        remote_vnet_id=vnet_c_id,
        peering_state="Connected",
    )
    payload = NetworkIntelligenceService(
        NetworkSnapshot(vnets=(vnet_a, vnet_b), peerings=(peer_b, peer_c))
    ).scoped(NetworkScope(subscription_ids=("sub-a",))).topology.to_dict()

    assert payload["unresolved_peer_vnet_ids"] == [
        vnet_b.resource_id,
        vnet_c_id.casefold(),
    ]
    assert {
        (item["vnet_id"], item["peer_resolution"])
        for item in payload["unresolved_peers"]
    } == {
        (vnet_b.resource_id, "excluded_by_scope"),
        (vnet_c_id.casefold(), "not_ingested"),
    }


def test_agent_twin_and_mcp_consumers_process_the_scoped_final_payload() -> None:
    sub_a = "00000000-0000-0000-0000-000000000001"
    sub_b = "00000000-0000-0000-0000-000000000002"
    service = NetworkIntelligenceService(
        build_estate(
            EstateShape(20, 3, 40, 25, 1_330),
            subscription_ids=(sub_a, sub_b),
        )
    )
    context = _NetworkContext(service)
    scope = Scope.from_mapping({"subscription": [sub_a]})

    agent = call_tool("network_topology", {}, context=context, scope=scope)
    assert agent.status == STATUS_OK
    assert "Agent result bound 25" in agent.warning
    assert_final_topology_shape(agent.data["topology"], allowed_subscription=sub_a)

    twin = twin_graph(context, scope)
    twin_resources = [
        entity
        for entity in twin["data"]["entities"]
        if entity["kind"] == "resource"
    ]
    assert twin_resources
    assert all(
        entity["properties"].get("subscription", "") in {"", sub_a}
        for entity in twin_resources
    )

    mcp = MCPServer().handle(
        {
            "jsonrpc": "2.0",
            "id": "phase-12-contract",
            "method": "tools/call",
            "params": {"name": "network_topology", "arguments": {}},
        },
        context=context,
        principal=SimpleNamespace(subject="phase-12-contract"),
        scope=scope,
        correlation_id="phase-12-contract",
    )
    assert mcp["result"]["isError"] is False
    mcp_payload = mcp["result"]["structuredContent"]
    assert mcp_payload["status"] == STATUS_OK
    assert_final_topology_shape(
        mcp_payload["data"]["topology"],
        allowed_subscription=sub_a,
    )


def test_browser_export_contract_matches_the_plan_12_10_consumer() -> None:
    assert_export_contract(EXPORT_COMPONENT, EXPECTED_EXPORT_KEYS)


def test_g5_default_pages_report_coverage_and_envelope_warnings() -> None:
    service = NetworkIntelligenceService(
        build_estate(EstateShape(20, 3, 40, 25, 1_330))
    )
    context = _NetworkContext(service)
    scope = Scope.unrestricted()
    page = Pagination()

    gaps = network_gaps(
        context,
        scope,
        page,
        severity=None,
        category=None,
    )
    findings = rule_findings(
        context,
        scope,
        page,
        severity=None,
        category=None,
    )

    assert_collection_coverage(gaps, "gaps")
    assert_collection_coverage(findings, "findings")
