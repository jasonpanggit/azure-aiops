"""Phase 12 closing contracts for network topology downstream consumers."""

from __future__ import annotations

import json
import re
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
    BaselineArtifactInvalidError,
    BaselineArtifactMissingError,
    capture_default_responses,
    load_baseline,
    without_allowed_additive_keys,
)
from tests.network_scale_fixtures import (
    EstateShape,
    build_estate,
    enterprise_estate,
    g4_baseline_estate,
    small_estate,
)
from tests.test_network_scale import (
    G1_BYTE_CEILING,
    G1_NODE_CAP,
    G2_BYTE_CEILING,
    G2_NODE_CAP,
    G3_BUILD_SECONDS,
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


def _serialized(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _first_difference(expected: Any, actual: Any, path: str = "$") -> str:
    if type(expected) is not type(actual):
        return (
            f"{path} changed type from {type(expected).__name__} "
            f"to {type(actual).__name__}"
        )
    if isinstance(expected, dict):
        missing = sorted(set(expected) - set(actual))
        if missing:
            return f"{path} is missing key {missing[0]!r}"
        added = sorted(set(actual) - set(expected))
        if added:
            return f"{path} has unregistered additive key {added[0]!r}"
        for key in expected:
            if expected[key] != actual[key]:
                return _first_difference(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path} changed length from {len(expected)} to {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            if expected_item != actual_item:
                return _first_difference(
                    expected_item,
                    actual_item,
                    f"{path}[{index}]",
                )
    elif expected != actual:
        return f"{path} changed from {expected!r} to {actual!r}"
    return f"{path} differs"


def assert_endpoint_contract(
    endpoint: str,
    current_record: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    recorded = baseline["endpoints"][endpoint]
    current_body = json.loads(current_record["body"])
    normalized = without_allowed_additive_keys(
        endpoint,
        current_body,
        baseline["allowed_additive_keys"],
    )
    expected_body = json.loads(recorded["body"])
    normalized_serialized = _serialized(normalized)

    assert sorted(normalized) == recorded["top_level_keys"], (
        f"G-4 {endpoint} top-level keys differ: "
        f"expected {recorded['top_level_keys']!r}, got {sorted(normalized)!r}"
    )
    assert len(normalized_serialized.encode("utf-8")) == recorded["byte_length"], (
        f"G-4 {endpoint} byte length differs: expected "
        f"{recorded['byte_length']}, got "
        f"{len(normalized_serialized.encode('utf-8'))}"
    )
    assert normalized == expected_body, (
        f"G-4 {endpoint} body differs after registered additions were removed: "
        f"{_first_difference(expected_body, normalized)}"
    )
    assert normalized_serialized == recorded["body"], (
        f"G-4 {endpoint} serialized body is not byte-identical"
    )


def assert_registered_additive_nodes(
    before: dict[str, Any],
    after: dict[str, Any],
    registrations: list[dict[str, Any]],
) -> None:
    before_ids = {str(item["id"]).casefold() for item in before["resources"]}
    registered_types: dict[str, str] = {}
    for entry in registrations:
        entity_type = str(entry.get("entity_type") or "")
        introduced_by = str(entry.get("introduced_by") or "")
        assert entity_type and introduced_by, (
            "allowed_additive_nodes entries require entity_type and introduced_by"
        )
        registered_types[entity_type] = introduced_by

    for node in after["resources"]:
        if str(node["id"]).casefold() in before_ids:
            continue
        entity_type = str(node.get("entity_type") or "")
        assert entity_type in registered_types, (
            f"additive node type {entity_type or '<missing>'!r} is not registered "
            "with its introducing plan"
        )


def assert_final_topology_shape(
    topology: dict[str, Any],
    *,
    allowed_subscription: str,
) -> None:
    assert {
        "counts",
        "flow_log_provenance",
        "resources",
        "relationships",
        "unresolved_peer_vnet_ids",
        "unresolved_peers",
    } <= set(topology)
    assert len(topology["resources"]) <= 25
    assert all(
        resource.get("subscription_id", "") in {"", allowed_subscription}
        for resource in topology["resources"]
    )
    assert all(
        peer["peer_resolution"]
        in {"not_ingested", "excluded_by_scope", "observed"}
        for peer in topology["unresolved_peers"]
    )


def assert_export_contract(path: Path, expected_keys: tuple[str, ...]) -> None:
    source = path.read_text(encoding="utf-8")
    function_start = source.index("export function buildTopologyExport(")
    function_end = source.index("\nlet lastExportSecond", function_start)
    export_source = source[function_start:function_end]
    positions = []
    for key in expected_keys:
        match = re.search(rf"(?m)^    {re.escape(key)}(?:\s*:|,)", export_source)
        assert match is not None, f"browser export is missing top-level key {key!r}"
        positions.append(match.start())

    assert positions == sorted(positions), (
        "browser export keys do not match the Plan 12-10 order"
    )
    assert (
        'extension: "json" | "png"' in source
        and "filename: `network-topology-${segment}.${extension}`" in source
    ), "browser export filename no longer matches network-topology-YYYYMMDD-HHmmss"


def assert_collection_coverage(response: dict[str, Any], collection: str) -> None:
    coverage = response["data"]["coverage"]
    assert set(coverage) == {"total", "returned", "truncated"}
    assert coverage["returned"] == len(response["data"][collection])
    assert coverage["returned"] <= coverage["total"]
    assert coverage["truncated"] is (
        coverage["returned"] < coverage["total"]
    )
    if coverage["truncated"]:
        assert response.get("warnings"), (
            f"bounded {collection} response omitted its envelope warning"
        )
        assert any(
            "truncat" in warning.casefold() or "showing" in warning.casefold()
            for warning in response["warnings"]
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
    assert_final_topology_shape(agent.data["topology"], allowed_subscription=sub_a)

    bounded_analysis = call_tool(
        "firewall_nsg_gaps",
        {},
        context=context,
        scope=scope,
    )
    assert bounded_analysis.status == STATUS_OK
    assert "Agent result bound 25" in bounded_analysis.warning
    assert len(bounded_analysis.data["gaps"]) <= 25
    assert len(bounded_analysis.data["rule_findings"]) <= 25

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


def test_g1_g2_and_g3_run_against_their_assigned_fixtures() -> None:
    measurements = measure_scale_gates(
        small_estate(),
        enterprise_estate(),
    )

    assert measurements["g1"]["nodes"] <= G1_NODE_CAP
    assert measurements["g1"]["serialized_bytes"] <= G1_BYTE_CEILING

    assert measurements["g2"]["truncated"] is True
    assert measurements["g2"]["nodes"] <= G2_NODE_CAP
    assert measurements["g2"]["serialized_bytes"] <= G2_BYTE_CEILING

    assert measurements["g3"]["p95_seconds"] < G3_BUILD_SECONDS
    assert measurements["g3"]["multiple_of_plan_12_02_baseline"] <= (
        G3_BUILD_SECONDS / measurements["g3"]["baseline_seconds"]
    )


def test_g5_enterprise_default_pages_are_bounded_and_warn() -> None:
    service = NetworkIntelligenceService(enterprise_estate())
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

    assert gaps["data"]["coverage"]["truncated"] is True
    assert findings["data"]["coverage"]["truncated"] is True
    assert_collection_coverage(gaps, "gaps")
    assert_collection_coverage(findings, "findings")
