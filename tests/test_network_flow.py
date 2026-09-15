"""Tests for traffic-flow validation.

Covers the MVP questions: can UAT reach PROD, which rules decide it, and
which spokes bypass the firewall.
"""

from __future__ import annotations

from dataclasses import replace

from network_scenario import PROD_SUBNET, UAT_NSG, UAT_SUBNET, network_rows

from network import (
    FlowQuery,
    NetworkIntelligenceService,
    NetworkSecurityRule,
    build_service,
)
from network.flow import VERDICT_ALLOWED, VERDICT_DENIED, VERDICT_INDETERMINATE


def _service():
    return build_service(network_rows())


def _flow(source: str, destination: str, port: int, protocol: str = "Tcp"):
    return _service().validate_flow(
        FlowQuery(source=source, destination=destination, port=port, protocol=protocol)
    )


class TestReachability:
    def test_uat_can_reach_prod_sql_and_names_the_rule(self) -> None:
        result = _flow("10.2.0.10", "10.1.0.10", 1433)
        assert result.verdict == VERDICT_ALLOWED
        deciding = [hop.rule_name for hop in result.hops if hop.stage == "destination_ingress"]
        assert deciding == ["allow-uat-sql"]

    def test_every_hop_is_explained(self) -> None:
        result = _flow("10.2.0.10", "10.1.0.10", 1433)
        assert result.hops
        for hop in result.hops:
            assert hop.reason, f"hop {hop.stage}/{hop.control} has no explanation"
            assert hop.control_id

    def test_denied_when_no_rule_permits_the_port(self) -> None:
        result = _flow("10.1.0.10", "10.2.0.10", 9999, protocol="Tcp")
        assert result.verdict == VERDICT_DENIED

    def test_firewall_denies_unmatched_internet_egress(self) -> None:
        result = _flow("10.1.0.10", "8.8.8.8", 443)
        assert result.verdict == VERDICT_DENIED
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops and firewall_hops[0].decision == "deny"

    def test_path_summary_is_human_readable(self) -> None:
        result = _flow("10.2.0.10", "10.1.0.10", 1433)
        assert "=>" in result.path_summary
        assert result.verdict in result.path_summary


class TestFirewallBypass:
    def test_spoke_without_a_udr_bypasses_the_firewall(self) -> None:
        result = _flow("10.2.0.10", "8.8.8.8", 443)
        assert result.verdict == VERDICT_ALLOWED
        assert not [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert any("firewall" in item for item in result.missing_enforcement_points)

    def test_spoke_with_a_udr_traverses_the_firewall(self) -> None:
        result = _flow("10.1.0.10", "8.8.8.8", 443)
        assert any(hop.control == "azure_firewall" for hop in result.hops)
        assert any(hop.control == "route_table" for hop in result.hops)

    def test_cross_vnet_without_forced_routing_is_reported(self) -> None:
        result = _flow("10.2.0.10", "10.1.0.10", 1433)
        assert any("crosses VNet" in item for item in result.missing_enforcement_points)

    def test_manual_internet_destination_with_a_default_route_traverses_the_firewall(
        self,
    ) -> None:
        """A 0.0.0.0/0 UDR to the firewall must apply to a manually entered
        "Internet" destination the same way it applies to a concrete public
        IP -- otherwise the routing hop reports "allow" while the panel
        claims the firewall was bypassed, contradicting itself."""
        result = _flow(PROD_SUBNET, "internet", 443)

        route_hop = next(hop for hop in result.hops if hop.control == "route_table")
        assert route_hop.rule_name == "default-to-fw"
        assert any(hop.control == "azure_firewall" for hop in result.hops)
        assert not any("firewall" in item for item in result.missing_enforcement_points)


class TestDefaultRuleSemantics:
    def test_intra_estate_egress_uses_allowvnetoutbound(self) -> None:
        result = _flow("10.2.0.10", "10.1.0.10", 1433)
        egress = next(hop for hop in result.hops if hop.stage == "source_egress")
        assert egress.rule_name == "AllowVnetOutBound"
        assert egress.decision == "allow"

    def test_internet_egress_uses_allowinternetoutbound(self) -> None:
        result = _flow("10.2.0.10", "8.8.8.8", 443)
        egress = next(hop for hop in result.hops if hop.stage == "source_egress")
        assert egress.rule_name == "AllowInternetOutBound"


class TestUncertainty:
    def test_unresolvable_endpoint_is_indeterminate_not_allowed(self) -> None:
        result = _flow("does-not-exist", "10.1.0.10", 443)
        assert result.verdict == VERDICT_INDETERMINATE
        assert result.unknowns

    def test_indeterminate_is_never_reported_as_allowed(self) -> None:
        result = _flow("does-not-exist", "also-missing", 443)
        assert not result.is_allowed

    def test_indeterminate_result_explains_unknown_control_decisions(self) -> None:
        service = _service()
        unresolved_rule = NetworkSecurityRule(
            resource_id=f"{UAT_NSG}/securityrules/unresolved-storage",
            name="unresolved-storage",
            nsg_id=UAT_NSG,
            priority=50,
            direction="Outbound",
            access="Allow",
            protocol="Tcp",
            source_address="*",
            destination_address="Storage",
            destination_port="443",
        )
        nsgs = tuple(
            replace(nsg, rules=(unresolved_rule, *nsg.rules))
            if nsg.resource_id == UAT_NSG
            else nsg
            for nsg in service.snapshot.nsgs
        )
        result = NetworkIntelligenceService(
            replace(service.snapshot, nsgs=nsgs)
        ).validate_flow(
            FlowQuery(source=UAT_SUBNET, destination="Internet", port=443)
        )

        unknown_hops = [hop for hop in result.hops if hop.decision == "unknown"]
        assert len(unknown_hops) == 1
        assert result.verdict == VERDICT_INDETERMINATE
        assert result.unknowns == (unknown_hops[0].reason,)

    def test_indeterminate_result_explains_when_no_path_was_observed(self) -> None:
        service = build_service([])
        result = service.validate_flow(
            FlowQuery(source="Internet", destination="Internet", port=443)
        )

        assert result.verdict == VERDICT_INDETERMINATE
        assert result.source_endpoint.resolved
        assert result.destination_endpoint.resolved
        assert result.unknowns == (
            "no ordered enforcement path could be established from the observed controls",
        )


class TestEndpointResolution:
    def test_subnet_id_resolves(self) -> None:
        result = _flow(UAT_SUBNET, PROD_SUBNET, 1433)
        assert result.source_endpoint.resolved
        assert result.destination_endpoint.resolved

    def test_public_ip_resolves_as_internet(self) -> None:
        result = _flow("10.1.0.10", "8.8.8.8", 443)
        assert result.destination_endpoint.is_internet
        assert result.destination_endpoint.resolved

    def test_selected_subnet_to_manual_internet_traces_egress(self) -> None:
        result = _flow(UAT_SUBNET, "internet", 443)

        assert result.source_endpoint.subnet_id == UAT_SUBNET.casefold()
        assert result.destination_endpoint.is_internet
        assert result.destination_endpoint.resolved
        assert result.verdict == VERDICT_ALLOWED
        assert not result.unknowns
        assert any(hop.stage == "source_egress" for hop in result.hops)
        assert "could not be resolved" not in result.path_summary

    def test_selected_subnet_to_public_fqdn_resolves_as_external(self) -> None:
        result = _flow(UAT_SUBNET, "www.google.com", 443)

        assert result.destination_endpoint.name == "www.google.com"
        assert result.destination_endpoint.is_internet
        assert result.destination_endpoint.resolved
        assert result.verdict == VERDICT_ALLOWED
        assert not result.unknowns

    def test_manual_internet_source_remains_a_resolved_endpoint(self) -> None:
        result = _flow("Internet", PROD_SUBNET, 443)

        assert result.source_endpoint.is_internet
        assert result.source_endpoint.resolved
        assert result.destination_endpoint.subnet_id == PROD_SUBNET.casefold()
        assert not any(
            "source 'Internet' could not be resolved" in item
            for item in result.unknowns
        )

    def test_private_ip_resolves_to_its_subnet(self) -> None:
        result = _flow("10.1.0.10", "8.8.8.8", 443)
        assert result.source_endpoint.subnet_id == PROD_SUBNET.casefold()
        assert result.source_endpoint.environment == "prod"


class TestSerialization:
    def test_result_serializes_for_the_api(self) -> None:
        payload = _flow("10.2.0.10", "10.1.0.10", 1433).to_dict()
        assert payload["verdict"] == VERDICT_ALLOWED
        assert payload["hops"]
        assert payload["source"]["is_internet"] is False

    def test_batch_validation(self) -> None:
        results = _service().validate_flows(
            [
                FlowQuery(source="10.2.0.10", destination="10.1.0.10", port=1433),
                FlowQuery(source="10.1.0.10", destination="8.8.8.8", port=443),
            ]
        )
        assert len(results) == 2
