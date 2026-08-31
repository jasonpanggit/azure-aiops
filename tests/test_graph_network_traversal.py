"""Network reachability traversal over the ontology graph.

The pre-existing ``_impact`` traversal walks *structural* dependency edges and
answers "what breaks if this fails". It says nothing about whether a packet can
travel between two resources. These tests cover the reachability traversal,
which walks only network-carrying predicates.

The graphs here are constructed directly rather than driven through the
normalizer so that each test states exactly the topology it depends on.
"""

from __future__ import annotations

import pytest

from ontology.graph_queries import OntologyQueryService

SUB = "/subscriptions/sub-1/resourcegroups/rg-net/providers"
VNET = f"{SUB}/microsoft.network/virtualnetworks/vnet-hub".casefold()
SUBNET = f"{VNET}/subnets/app".casefold()
NIC = f"{SUB}/microsoft.network/networkinterfaces/nic-1".casefold()
VM = f"{SUB}/microsoft.compute/virtualmachines/vm-1".casefold()
GW = f"{SUB}/microsoft.network/virtualnetworkgateways/vpn-hub".casefold()
LB = f"{SUB}/microsoft.network/loadbalancers/lb-app".casefold()
ISOLATED = f"{SUB}/microsoft.compute/virtualmachines/vm-isolated".casefold()


def _entity(resource_id: str, entity_type: str, name: str) -> dict:
    # Derive resource_type from the id the way real ingestion does, so exposure
    # direction classification is exercised against realistic rows rather than a
    # placeholder that would always fall through to "unknown".
    parts = resource_id.split("/")
    resource_type = "/".join(parts[-3:-1]) if len(parts) >= 3 else "test/type"
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": entity_type,
        "name": name,
        "resource_type": resource_type,
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-17T00:00:00Z",
        "retired_at": "",
        "ontology_version": "1.0.0",
    }


def _rel(subject: str, predicate: str, obj: str, entities: list[dict]) -> dict:
    # subject_type/object_type are looked up rather than hardcoded so a
    # relationship can never disagree with the entity it points at.
    types = {row["resource_id"]: row["entity_type"] for row in entities}
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": f"{subject}|{predicate}|{obj}",
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "subject_id": subject,
        "subject_type": types[subject],
        "predicate": predicate,
        "object_id": obj,
        "object_type": types[obj],
        "source": "test",
        "confidence": 1.0,
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-17T00:00:00Z",
        "retired_at": "",
        "ontology_version": "1.0.0",
    }


def _service(**kwargs) -> OntologyQueryService:
    """A VM whose NIC sits in a subnet that egresses via a gateway.

    vm-1 -> nic-1 -> subnet app -> vnet-hub, and the subnet egresses via a
    gateway. vm-isolated exists but has no network edges at all.
    """
    entities = [
        _entity(VNET, "VNet", "vnet-hub"),
        _entity(SUBNET, "Subnet", "app"),
        _entity(NIC, "NetworkInterface", "nic-1"),
        _entity(VM, "VirtualMachine", "vm-1"),
        _entity(GW, "NetworkGateway", "vpn-hub"),
        _entity(ISOLATED, "VirtualMachine", "vm-isolated"),
    ]
    relationships = [
        _rel(VNET, "contains", SUBNET, entities),
        _rel(NIC, "attachedTo", SUBNET, entities),
        _rel(VM, "hasNetworkInterface", NIC, entities),
        _rel(SUBNET, "egressesVia", GW, entities),
    ]
    return OntologyQueryService(entities, relationships, **kwargs)


def test_reachability_walks_network_edges_from_a_workload():
    result = _service().answer("network reachable", entity="vm-1")

    names = {item["name"] for item in result["items"]}
    assert names == {"nic-1", "app", "vnet-hub", "vpn-hub"}


def test_reachability_records_the_path_that_reached_each_node():
    result = _service().answer("network reachable", entity="vm-1")
    by_name = {item["name"]: item for item in result["items"]}

    # The path is the evidence: it must name the actual predicates walked,
    # so a reviewer can confirm or refute the claim against Azure.
    assert by_name["nic-1"]["path"] == ["hasNetworkInterface"]
    assert by_name["nic-1"]["hops"] == 1
    assert by_name["app"]["path"] == ["hasNetworkInterface", "attachedTo"]
    assert by_name["vpn-hub"]["path"][-1] == "egressesVia"


def test_reachability_excludes_the_root_itself():
    result = _service().answer("network reachable", entity="vm-1")

    assert all(item["name"] != "vm-1" for item in result["items"])


def test_isolated_workload_reaches_nothing():
    result = _service().answer("network reachable", entity="vm-isolated")

    assert result["items"] == []
    assert result["count"] == 0


def test_exposure_reports_only_boundary_points_with_their_path():
    result = _service().answer("network exposure", entity="vm-1")

    assert [item["name"] for item in result["items"]] == ["vpn-hub"]
    item = result["items"][0]
    assert item["exposure"] == "reaches_boundary"
    assert item["direction"] == "inbound"
    assert item["path"] == ["hasNetworkInterface", "attachedTo", "egressesVia"]


def test_nat_gateway_is_reported_as_egress_not_ingress():
    # The ontology collapses NAT gateways and VPN gateways into one
    # NetworkGateway type, but a NAT gateway is an outbound path. Reporting it
    # as inbound exposure would be a false positive a reviewer has to disprove.
    nat = f"{SUB}/microsoft.network/natgateways/nat-1".casefold()
    entities = [
        _entity(SUBNET, "Subnet", "app"),
        _entity(nat, "NetworkGateway", "nat-1"),
    ]
    service = OntologyQueryService(entities, [_rel(SUBNET, "egressesVia", nat, entities)])

    items = service.answer("network exposure", entity="app")["items"]

    assert [item["direction"] for item in items] == ["outbound"]


def test_unclassifiable_boundary_is_reported_as_unknown_not_dropped():
    # An unclassifiable boundary is a finding a reviewer should see. Silently
    # dropping it would turn missing data into an implicit "safe" verdict.
    odd = f"{SUB}/contoso.custom/edgedevices/edge-1".casefold()
    entities = [
        _entity(SUBNET, "Subnet", "app"),
        _entity(odd, "NetworkGateway", "edge-1"),
    ]
    service = OntologyQueryService(entities, [_rel(SUBNET, "egressesVia", odd, entities)])

    items = service.answer("network exposure", entity="app")["items"]

    assert [item["direction"] for item in items] == ["unknown"]


def test_exposure_is_empty_when_no_boundary_is_reachable():
    # Absence of a path is not proof of safety; it is simply the absence of a
    # finding. The query must not invent a "secure" verdict.
    result = _service().answer("network exposure", entity="vm-isolated")

    assert result["items"] == []


def test_reachability_does_not_follow_structural_dependency_edges():
    """depends_on is not a network path.

    Two applications may depend on each other while being network-isolated.
    Treating dependency as reachability would manufacture false exposure.
    """
    app_a = "app-a"
    app_b = "app-b"
    entities = [
        _entity(app_a, "Application", "app-a"),
        _entity(app_b, "Application", "app-b"),
    ]
    relationships = [_rel(app_a, "depends_on", app_b, entities)]
    service = OntologyQueryService(entities, relationships)

    assert service.answer("network reachable", entity="app-a")["items"] == []


def test_peering_is_traversed_in_both_directions():
    spoke = f"{SUB}/microsoft.network/virtualnetworks/vnet-spoke".casefold()
    peering = f"{SUB}/microsoft.network/virtualnetworks/vnet-hub/peerings/p1".casefold()
    entities = [
        _entity(VNET, "VNet", "vnet-hub"),
        _entity(spoke, "VNet", "vnet-spoke"),
        _entity(peering, "VNetPeering", "p1"),
    ]
    relationships = [
        _rel(VNET, "hasPeering", peering, entities),
        _rel(peering, "peersWith", spoke, entities),
    ]
    service = OntologyQueryService(entities, relationships)

    names = {item["name"] for item in service.answer("network reachable", entity="vnet-hub")["items"]}
    assert "vnet-spoke" in names


def test_traversal_bound_is_reported_rather_than_silently_truncating():
    result = _service(max_traversal_nodes=2).answer("network reachable", entity="vm-1")

    # Fewer nodes are returned, but the caller is told the answer is partial.
    assert result["truncated"] is True


def test_results_do_not_leak_tenant_identifiers():
    result = _service().answer("network reachable", entity="vm-1")

    # An Azure resource id embeds the subscription GUID, so traversal answers
    # must stay on the same projection contract as every other query: names and
    # types only, never raw inventory identifiers.
    leaky = {"resource_id", "tenant_id", "subscription_id", "payload_json"}
    for item in result["items"]:
        assert not leaky & set(item)
    assert {item["name"] for item in result["items"]}


def test_private_endpoint_exposure_path_reaches_the_backing_resource():
    pe = f"{SUB}/microsoft.network/privateendpoints/pe-sql".casefold()
    sql = f"{SUB}/microsoft.sql/servers/sql-1".casefold()
    entities = [
        _entity(SUBNET, "Subnet", "app"),
        _entity(pe, "PrivateEndpoint", "pe-sql"),
        _entity(sql, "SqlServer", "sql-1"),
    ]
    relationships = [
        _rel(pe, "attachedTo", SUBNET, entities),
        _rel(pe, "exposesPrivately", sql, entities),
    ]
    service = OntologyQueryService(entities, relationships)

    names = {item["name"] for item in service.answer("network reachable", entity="app")["items"]}
    assert names == {"pe-sql", "sql-1"}


def test_unknown_question_lists_network_queries_in_its_guidance():
    with pytest.raises(ValueError, match="network exposure"):
        _service().answer("what is the meaning of life")
