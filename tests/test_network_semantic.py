"""Proves network topology is traversable from the Semantic Knowledge Layer.

The Operations API must never read ARG or the network engine's own snapshot
directly. These tests drive the genuine ingestion chain -- Normalizer ->
EntityBuilder -> RelationshipBuilder -> SemanticIndexes -> SemanticEngine --
and assert the network context is derived entirely from the semantic graph.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from test_network_ontology import PEER_VNET_ID, SQL_ID, VNET_ID, _full_payload

from fabric.dataset_mapper import _entity_row
from hermes_arg_connector.normalize import Normalizer
from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder
from semantic.semantic_engine import SemanticEngine
from semantic.semantic_indexes import SemanticIndexes
from semantic.semantic_query import SemanticIntent, SemanticQuery
from semantic.semantic_registry import SemanticRegistry

OBSERVED = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def graph():
    normalized = Normalizer().normalize(_full_payload(), OBSERVED)
    rows = [
        _entity_row(row, entity_type, "run-1")
        for entity_type, entities in normalized.entities.items()
        for row in entities
    ]
    entities = EntityBuilder().build(rows, "run-1")
    return entities, RelationshipBuilder().build(entities, "run-1")


@pytest.fixture(scope="module")
def indexes(graph) -> SemanticIndexes:
    entities, relationships = graph
    return SemanticIndexes(entities, relationships)


@pytest.fixture(scope="module")
def engine(indexes) -> SemanticEngine:
    return SemanticEngine(
        indexes, knowledge_version="v1", freshness="2026-08-01T00:00:00Z"
    )


class TestRelationshipDerivation:
    """The ontology graph is rebuilt from entities, so normalizer edges do not
    survive into it. These assert the network edges are re-derived.
    """

    def test_network_edges_reach_the_ontology_graph(self, graph):
        _, relationships = graph
        assert [row for row in relationships if row["source"] == "network"]

    @pytest.mark.parametrize(
        "triple",
        [
            ("VNet", "contains", "Subnet"),
            ("VNet", "hasPeering", "VNetPeering"),
            ("VNetPeering", "peersWith", "VNet"),
            ("Subnet", "protectedBy", "NetworkSecurityGroup"),
            ("Subnet", "routedBy", "RouteTable"),
            ("Subnet", "egressesVia", "NetworkGateway"),
            ("NetworkSecurityGroup", "hasRule", "NetworkSecurityRule"),
            ("RouteTable", "hasRoute", "Route"),
            ("NetworkInterface", "protectedBy", "NetworkSecurityGroup"),
            ("NetworkInterface", "attachedTo", "Subnet"),
            ("AzureFirewall", "attachedTo", "Subnet"),
            ("AzureFirewall", "enforcesPolicy", "FirewallPolicy"),
            ("FirewallPolicy", "hasRuleCollection", "FirewallRuleCollection"),
            ("FirewallRuleCollection", "hasRule", "FirewallRule"),
            ("PrivateEndpoint", "attachedTo", "Subnet"),
            ("PrivateDnsZone", "resolvesFor", "VNet"),
            ("LoadBalancer", "attachedTo", "Subnet"),
            ("NetworkGateway", "attachedTo", "Subnet"),
        ],
        ids=lambda triple: "-".join(triple),
    )
    def test_topology_triple_is_derived(self, graph, triple):
        _, relationships = graph
        derived = {
            (row["subject_type"], row["predicate"], row["object_type"])
            for row in relationships
        }
        assert triple in derived

    def test_derived_edges_are_not_self_referential(self, graph):
        _, relationships = graph
        for row in relationships:
            assert row["subject_id"] != row["object_id"]

    def test_network_relationship_edges_carry_troubleshooting_payloads(self, graph):
        _, relationships = graph
        rule_edge = next(
            row
            for row in relationships
            if row["predicate"] == "hasRule" and row["object_type"] == "FirewallRule"
        )
        route_edge = next(row for row in relationships if row["predicate"] == "hasRoute")
        assert json.loads(rule_edge["payload_json"])["destinationPorts"]
        assert json.loads(route_edge["payload_json"])["nextHopType"]


class TestTraversalHelpers:
    def test_subnets_for_vnet(self, indexes):
        assert indexes.subnets_for_vnet(VNET_ID)

    def test_peered_vnets_resolves_the_remote_vnet(self, indexes):
        assert indexes.peered_vnets(VNET_ID) == [PEER_VNET_ID]

    def test_peered_vnets_is_symmetric(self, indexes):
        """The remote side has no peering resource of its own, yet must still
        see the hub -- the traversal walks the peering edge inbound.
        """
        assert VNET_ID in indexes.peered_vnets(PEER_VNET_ID)

    def test_a_vnet_is_never_its_own_peer(self, indexes):
        assert VNET_ID not in indexes.peered_vnets(VNET_ID)

    def test_nsg_and_rules_are_reachable_from_a_subnet(self, indexes):
        subnet_id = indexes.subnets_for_vnet(VNET_ID)[0]
        nsgs = indexes.nsg_for_subnet(subnet_id)
        assert nsgs
        assert indexes.rules_for_nsg(nsgs[0])

    def test_routes_are_reachable_from_a_subnet(self, indexes):
        subnet_id = indexes.subnets_for_vnet(VNET_ID)[0]
        tables = indexes.route_table_for_subnet(subnet_id)
        assert tables
        assert indexes.routes_for_table(tables[0])

    def test_firewall_rules_traverse_policy_and_collection(self, indexes):
        firewall_id = indexes.by_type["AzureFirewall"][0]
        policies = indexes.policies_for_firewall(firewall_id)
        assert policies
        assert indexes.firewall_rules_for_policy(policies[0])

    def test_private_endpoint_target_edge_needs_the_target_ingested(self, indexes):
        """The SQL server the endpoint fronts lives outside this payload.

        The ontology drops edges whose endpoints are not both present, so the
        traversal is correctly empty rather than dangling.
        """
        assert indexes.private_endpoints_for_target(SQL_ID) == []

    def test_dns_zone_resolves_its_linked_vnet(self, indexes):
        zone_id = indexes.by_type["PrivateDnsZone"][0]
        assert indexes.vnets_for_dns_zone(zone_id) == [VNET_ID]

    def test_unknown_connection_yields_no_vnets(self, indexes):
        """A missing connection must return empty, not raise -- callers pass
        user-supplied identifiers.
        """
        assert indexes.vnets_for_connection("no-such-connection") == []

    def test_helpers_tolerate_unknown_ids(self, indexes):
        for helper in (
            indexes.subnets_for_vnet,
            indexes.peerings_for_vnet,
            indexes.peered_vnets,
            indexes.nsg_for_subnet,
            indexes.rules_for_nsg,
            indexes.route_table_for_subnet,
            indexes.routes_for_table,
            indexes.policies_for_firewall,
            indexes.firewall_rules_for_policy,
            indexes.vnets_for_dns_zone,
            indexes.private_endpoints_for_target,
            indexes.resources_for_subnet,
        ):
            assert helper("/no/such/id") == []


class TestNetworkContext:
    def test_context_type_is_network(self, engine):
        assert engine.get_network_context("vnet-hub")["context_type"] == "network"

    def test_context_resolves_by_arm_id(self, engine):
        assert engine.get_network_context(VNET_ID)["context_type"] == "network"

    @pytest.mark.parametrize(
        "section",
        [
            "vnets",
            "subnets",
            "peerings",
            "security_groups",
            "security_rules",
            "route_tables",
            "routes",
            "firewalls",
            "firewall_rule_collections",
            "firewall_rules",
            "private_endpoints",
            "dns_zones",
        ],
    )
    def test_section_is_populated(self, engine, section):
        """NetworkKnowledge.section_names must declare every section or
        DomainKnowledge.build drops it silently.
        """
        assert engine.get_network_context("vnet-hub")["sections"][section]

    def test_topology_summary_reports_enforcement(self, engine):
        topology = engine.get_network_context("vnet-hub")["sections"]["topology"]
        assert topology["traverses_firewall"] is True
        assert topology["has_private_dns"] is True
        assert topology["peer_count"] == 1

    def test_context_exposes_rule_and_route_details_for_troubleshooting(self, engine):
        sections = engine.get_network_context("vnet-hub")["sections"]
        nsg = sections["security_groups"][0]
        firewall = sections["firewalls"][0]
        route_table = sections["route_tables"][0]
        assert nsg["details"]["rules"]
        assert firewall["details"]["rules"]
        assert route_table["details"]["routes"]
        assert sections["security_rules"][0]["details"]["destination_port"]
        assert sections["firewall_rules"][0]["details"]["destination_ports"]
        assert sections["routes"][0]["details"]["next_hop_type"]

    def test_spoke_without_firewall_reports_no_enforcement(self, engine):
        topology = engine.get_network_context("vnet-spoke")["sections"]["topology"]
        assert topology["traverses_firewall"] is False
        assert topology["subnet_count"] == 0

    def test_context_carries_freshness_and_version(self, engine):
        context = engine.get_network_context("vnet-hub")
        assert context["freshness"] == "2026-08-01T00:00:00Z"
        assert context["knowledge_version"]

    def test_section_metadata_reports_totals(self, engine):
        metadata = engine.get_network_context("vnet-hub")["section_metadata"]
        assert metadata["subnets"]["count"] == 1
        assert metadata["subnets"]["truncated"] is False

    def test_unknown_vnet_raises_lookup_error(self, engine):
        with pytest.raises(LookupError):
            engine.get_network_context("no-such-vnet")

    def test_alias_matches_the_getter(self, engine):
        assert engine.network_context("vnet-hub") == engine.get_network_context(
            "vnet-hub"
        )

    def test_repeated_calls_are_cached_and_stable(self, engine):
        assert engine.get_network_context("vnet-hub") == engine.get_network_context(
            "vnet-hub"
        )


class TestQueryRouting:
    @pytest.mark.parametrize(
        "question",
        ["network context", "vnet context", "show the network topology"],
    )
    def test_question_parses_to_network_intent(self, question):
        query = SemanticQuery.parse(question, subject="vnet-hub")
        assert query.intent is SemanticIntent.NETWORK_CONTEXT

    def test_engine_dispatches_the_network_intent(self, engine):
        result = engine.query("network context", subject="vnet-hub")
        assert result["context_type"] == "network"

    def test_help_text_mentions_network(self):
        with pytest.raises(ValueError, match="network context"):
            SemanticQuery.parse("something entirely unsupported")


class TestRegistry:
    def test_network_model_is_registered(self):
        assert "Network" in SemanticRegistry.default().names()
