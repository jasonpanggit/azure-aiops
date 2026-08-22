"""Tests for the network data model, addressing primitives, and loader."""

from __future__ import annotations

from network_scenario import (
    FIREWALL_COLLECTION,
    FIREWALL_ID,
    PROD_NSG,
    PROD_SUBNET,
    PROD_VNET,
    network_rows,
)

from network import (
    AddressSpec,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    PortSpec,
    ProtocolSpec,
    load_network_snapshot,
)
from network.addressing import SENSITIVE_PORTS
from network.models import DEFAULT_SECURITY_RULES


class TestAddressSpec:
    def test_wildcard_is_any(self) -> None:
        for token in ("*", "Any", "", "any"):
            assert AddressSpec.parse(token).is_any

    def test_cidr_membership(self) -> None:
        spec = AddressSpec.parse("10.1.0.0/16")
        assert spec.contains_address("10.1.5.9") is True
        assert spec.contains_address("10.2.5.9") is False

    def test_service_tag_is_undecidable_not_false(self) -> None:
        """The core safety property: unknown must never collapse to a match."""
        spec = AddressSpec.parse("Storage")
        assert spec.service_tag == "storage"
        assert spec.contains_address("10.1.0.4") is None

    def test_zero_route_covers_all_addresses(self) -> None:
        assert AddressSpec.parse("0.0.0.0/0").covers_all_addresses
        assert AddressSpec.parse("0.0.0.0/0").is_internet
        assert not AddressSpec.parse("10.0.0.0/8").covers_all_addresses

    def test_prefix_length_is_none_for_tags(self) -> None:
        assert AddressSpec.parse("10.0.0.0/8").prefix_length == 8
        assert AddressSpec.parse("VirtualNetwork").prefix_length is None

    def test_subnet_containment(self) -> None:
        spec = AddressSpec.parse("10.0.0.0/8")
        assert spec.contains_address("10.1.0.0/16") is True
        assert spec.contains_address("192.168.0.0/16") is False

    def test_ipv4_and_ipv6_do_not_cross_match(self) -> None:
        assert AddressSpec.parse("10.0.0.0/8").contains_address("2001:db8::1") is False


class TestPortSpec:
    def test_single_port(self) -> None:
        assert PortSpec.parse("443").contains(443) is True
        assert PortSpec.parse("443").contains(80) is False

    def test_range_and_list(self) -> None:
        assert PortSpec.parse("100-200").contains(150) is True
        assert PortSpec.parse("100-200").contains(250) is False
        assert PortSpec.parse("80,443").contains(443) is True

    def test_wildcard_matches_everything(self) -> None:
        spec = PortSpec.parse("*")
        assert spec.is_any
        assert spec.contains(1) is True
        assert spec.contains(65535) is True


class TestProtocolSpec:
    def test_wildcard_matches_any_protocol(self) -> None:
        assert ProtocolSpec.parse("*").matches("Tcp")
        assert ProtocolSpec.parse("Any").matches("Udp")

    def test_specific_protocol_is_case_insensitive(self) -> None:
        assert ProtocolSpec.parse("Tcp").matches("TCP")
        assert not ProtocolSpec.parse("Tcp").matches("Udp")


class TestDefaultSecurityRules:
    def test_defaults_are_synthesized_when_absent(self) -> None:
        nsg = NetworkSecurityGroup(resource_id="/nsg/a", name="a")
        assert not nsg.has_observed_defaults
        assert len(nsg.effective_rules()) == len(DEFAULT_SECURITY_RULES)
        assert all(rule.is_default for rule in nsg.effective_rules())

    def test_observed_defaults_are_not_duplicated(self) -> None:
        observed = NetworkSecurityRule(
            resource_id="/nsg/a/securityrules/denyallinbound",
            name="DenyAllInBound",
            nsg_id="/nsg/a",
            priority=65500,
            direction="Inbound",
            access="Deny",
            is_default=True,
        )
        nsg = NetworkSecurityGroup(resource_id="/nsg/a", name="a", rules=(observed,))
        assert nsg.has_observed_defaults
        assert nsg.effective_rules() == (observed,)

    def test_rules_evaluate_in_ascending_priority(self) -> None:
        nsg = NetworkSecurityGroup(resource_id="/nsg/a", name="a")
        inbound = nsg.ordered_rules(direction="Inbound")
        assert [rule.priority for rule in inbound] == sorted(rule.priority for rule in inbound)
        assert inbound[-1].name == "DenyAllInBound"


class TestSensitivePorts:
    def test_covers_the_ports_the_mvp_must_flag(self) -> None:
        for port in (22, 3389, 1433, 5432, 3306):
            assert port in SENSITIVE_PORTS


class TestLoader:
    def test_loads_every_entity_family(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        counts = snapshot.counts()
        assert counts["vnets"] == 3
        assert counts["subnets"] == 3
        assert counts["nsgs"] == 2
        assert counts["nsg_rules"] == 4
        assert counts["peerings"] == 5
        assert counts["firewalls"] == 1
        assert counts["private_endpoints"] == 1

    def test_sub_resources_nest_under_parents(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        nsg = next(n for n in snapshot.nsgs if n.resource_id == PROD_NSG.casefold())
        assert {rule.name for rule in nsg.rules} == {
            "allow-https",
            "allow-https-narrow",
            "allow-uat-sql",
        }
        collection = snapshot.firewall_collections[0]
        assert collection.resource_id == FIREWALL_COLLECTION.casefold()
        assert len(collection.rules) == 2

    def test_identifiers_are_casefolded(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        for vnet in snapshot.vnets:
            assert vnet.resource_id == vnet.resource_id.casefold()

    def test_business_context_survives_the_round_trip(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        vnet = next(v for v in snapshot.vnets if v.resource_id == PROD_VNET.casefold())
        assert vnet.business_service == "Payments"
        assert vnet.environment == "prod"
        assert vnet.connection_id == "conn-prod"

    def test_subnet_links_to_nsg_and_route_table(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        subnet = next(s for s in snapshot.subnets if s.resource_id == PROD_SUBNET.casefold())
        assert subnet.nsg_id == PROD_NSG.casefold()
        assert subnet.route_table_id

    def test_firewall_private_ip_is_preserved(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        firewall = snapshot.firewalls[0]
        assert firewall.resource_id == FIREWALL_ID.casefold()
        assert firewall.private_ip == "10.0.1.4"

    def test_empty_input_is_a_valid_empty_snapshot(self) -> None:
        snapshot = load_network_snapshot([])
        assert snapshot.counts()["vnets"] == 0
        assert snapshot.connection_ids() == ()

    def test_unknown_entity_types_are_ignored_not_fatal(self) -> None:
        snapshot = load_network_snapshot(
            [{"entity_type": "NotANetworkThing", "resource_id": "/x", "name": "x"}]
        )
        assert snapshot.counts()["vnets"] == 0

    def test_connection_ids_span_every_onboarded_subscription(self) -> None:
        snapshot = load_network_snapshot(network_rows())
        assert set(snapshot.connection_ids()) == {"conn-hub", "conn-prod", "conn-uat"}
