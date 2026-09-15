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
from network.models import FirewallRule, FirewallRuleCollection


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


class TestFirewallRuleEvaluation:
    """The firewall hop must reason from observed rules, not stop at the
    first rule referencing an IP group or FQDN.

    These fixtures add extra rule collections on top of the base scenario's
    firewall so each case can isolate one aspect of Azure's evaluation
    semantics: priority order, protocol/port pre-filtering, and FQDN
    matching for a manually entered public hostname vs. the generic
    ``Internet`` tag.
    """

    @staticmethod
    def _service_with_collections(*collections: FirewallRuleCollection):
        service = build_service(network_rows())
        return NetworkIntelligenceService(
            replace(
                service.snapshot,
                firewall_collections=(*service.snapshot.firewall_collections, *collections),
            )
        )

    def test_a_rule_referencing_an_fqdn_for_a_different_port_does_not_cause_unknown(
        self,
    ) -> None:
        """A collection with an FQDN-only rule that plainly does not apply
        to this port must not poison the result; the definite deny below it
        must still be reported."""
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/fqdn-other-port",
            name="fqdn-other-port",
            priority=90,
            action="Allow",
            collection_type="ApplicationRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/fqdn-other-port/rules/allow-updates",
                    name="allow-updates",
                    rule_type="ApplicationRule",
                    action="Allow",
                    protocols=["Https"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["*.contoso.com"],
                    destination_ports=["80"],
                ),
            ),
        )
        service = self._service_with_collections(collection)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="internet", port=22, protocol="Tcp")
        )
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops
        assert firewall_hops[0].decision == "deny"
        assert "no firewall rule matched" in firewall_hops[0].reason

    def test_a_definite_higher_priority_result_is_not_erased_by_a_later_unresolved_rule(
        self,
    ) -> None:
        """A collection evaluated first that definitely allows the flow must
        win even though a later, lower-priority collection references an
        unresolved IP group."""
        allow_first = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/allow-first",
            name="allow-first",
            priority=10,
            action="Allow",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/allow-first/rules/allow-mgmt",
                    name="allow-mgmt",
                    rule_type="NetworkRule",
                    action="Allow",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["*"],
                    destination_ports=["9443"],
                ),
            ),
        )
        unresolved_later = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/unresolved-later",
            name="unresolved-later",
            priority=900,
            action="Deny",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/unresolved-later/rules/deny-group",
                    name="deny-group",
                    rule_type="NetworkRule",
                    action="Deny",
                    protocols=["Tcp"],
                    source_ip_groups=["ipg-untrusted"],
                    destination_addresses=["*"],
                    destination_ports=["9443"],
                ),
            ),
        )
        service = self._service_with_collections(allow_first, unresolved_later)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="internet", port=9443, protocol="Tcp")
        )
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops
        assert firewall_hops[0].decision == "allow"
        assert firewall_hops[0].rule_name == "allow-mgmt"

    def test_an_unresolved_higher_priority_rule_keeps_the_verdict_indeterminate(
        self,
    ) -> None:
        """The mirror image: when the *earlier* (higher-priority) rule is the
        one that cannot be resolved, a later definite match must not erase
        the genuine uncertainty -- Azure would have evaluated the earlier
        rule first, and we cannot tell whether it already decided the flow."""
        unresolved_first = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/unresolved-first",
            name="unresolved-first",
            priority=10,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/unresolved-first/rules/allow-fqdn",
                    name="allow-fqdn",
                    rule_type="NetworkRule",
                    action="Allow",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["*.contoso.com"],
                    destination_ports=["443"],
                ),
            ),
        )
        definite_later = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/definite-later",
            name="definite-later",
            priority=900,
            action="Allow",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/definite-later/rules/allow-any",
                    name="allow-any",
                    rule_type="NetworkRule",
                    action="Allow",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["*"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(unresolved_first, definite_later)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="internet", port=443, protocol="Tcp")
        )
        assert result.verdict == VERDICT_INDETERMINATE
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops and firewall_hops[0].decision == "unknown"

    def test_a_manually_entered_public_fqdn_matches_an_application_rule(self) -> None:
        """A caller who types a real hostname gets a definite answer from
        the FQDN-scoped rule that covers it."""
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/app-contoso",
            name="app-contoso",
            priority=20,
            action="Allow",
            collection_type="ApplicationRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/app-contoso/rules/allow-contoso",
                    name="allow-contoso",
                    rule_type="ApplicationRule",
                    action="Allow",
                    protocols=["Https"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["*.contoso.com"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(collection)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="app.contoso.com", port=443, protocol="Tcp")
        )
        assert result.verdict == VERDICT_ALLOWED
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops
        assert firewall_hops[0].decision == "allow"
        assert firewall_hops[0].rule_name == "allow-contoso"

    def test_a_concrete_fqdn_skips_unmatched_service_tags_before_matching_fqdn(
        self,
    ) -> None:
        """A known hostname must not be blocked by earlier service-tag
        destinations in the same collection when a later FQDN selector
        exactly covers it."""
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/live-network-rules",
            name="network-rules",
            priority=100,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/live-network-rules/rules/arc",
                    name="Arc",
                    rule_type="NetworkRule",
                    protocols=["Any"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=[
                        "AzureActiveDirectory",
                        "AzureTrafficManager",
                        "AzureResourceManager",
                        "AzureArcInfrastructure",
                        "Storage",
                        "AzureFrontDoor.Frontend",
                        "AzureMonitor",
                    ],
                    destination_ports=["*"],
                ),
                FirewallRule(
                    resource_id="/fwp/rulecollections/live-network-rules/rules/google",
                    name="Google",
                    rule_type="NetworkRule",
                    protocols=["Any"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["www.google.com"],
                    destination_ports=["*"],
                ),
            ),
        )
        base_service = build_service(network_rows())
        service = NetworkIntelligenceService(
            replace(base_service.snapshot, firewall_collections=(collection,))
        )

        result = service.validate_flow(
            FlowQuery(
                source=PROD_SUBNET,
                destination="www.google.com",
                port=443,
                protocol="Tcp",
            )
        )

        assert result.verdict == VERDICT_ALLOWED
        firewall_hop = next(hop for hop in result.hops if hop.control == "azure_firewall")
        assert firewall_hop.decision == "allow"
        assert firewall_hop.rule_name == "Google"

    def test_a_concrete_fqdn_does_not_skip_an_uncertain_prior_collection(
        self,
    ) -> None:
        uncertain_deny = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/unresolved-service-tag",
            name="unresolved-service-tag",
            priority=100,
            action="Deny",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/unresolved-service-tag/rules/azure",
                    name="AzureService",
                    rule_type="NetworkRule",
                    protocols=["Any"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["AzureCloud"],
                    destination_ports=["*"],
                ),
            ),
        )
        later_allow = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/google",
            name="google",
            priority=200,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/google/rules/google",
                    name="Google",
                    rule_type="NetworkRule",
                    protocols=["Any"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["www.google.com"],
                    destination_ports=["*"],
                ),
            ),
        )
        service = self._service_with_collections(uncertain_deny, later_allow)

        result = service.validate_flow(
            FlowQuery(
                source=PROD_SUBNET,
                destination="www.google.com",
                port=443,
                protocol="Tcp",
            )
        )

        assert result.verdict == VERDICT_INDETERMINATE
        firewall_hop = next(
            hop for hop in result.hops if hop.control == "azure_firewall"
        )
        assert firewall_hop.decision == "unknown"

    def test_a_manually_entered_public_fqdn_that_does_not_match_falls_through(
        self,
    ) -> None:
        """A hostname outside the rule's FQDN list is a definite non-match
        for that rule, not an unknown -- evaluation must continue and reach
        the default deny."""
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/app-contoso-2",
            name="app-contoso-2",
            priority=20,
            action="Allow",
            collection_type="ApplicationRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/app-contoso-2/rules/allow-contoso",
                    name="allow-contoso",
                    rule_type="ApplicationRule",
                    action="Allow",
                    protocols=["Https"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["*.contoso.com"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(collection)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="example.com", port=443, protocol="Tcp")
        )
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops
        assert firewall_hops[0].decision == "deny"
        assert "no firewall rule matched" in firewall_hops[0].reason

    def test_generic_internet_never_falsely_matches_an_fqdn_only_rule(self) -> None:
        """Generic ``Internet`` names no specific host, so an FQDN rule that
        would otherwise apply must report indeterminate, never a false
        allow."""
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/app-contoso-3",
            name="app-contoso-3",
            priority=20,
            action="Allow",
            collection_type="ApplicationRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/app-contoso-3/rules/allow-contoso",
                    name="allow-contoso",
                    rule_type="ApplicationRule",
                    action="Allow",
                    protocols=["Https"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["*.contoso.com"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(collection)
        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="internet", port=443, protocol="Tcp")
        )
        assert result.verdict == VERDICT_INDETERMINATE
        firewall_hops = [hop for hop in result.hops if hop.control == "azure_firewall"]
        assert firewall_hops and firewall_hops[0].decision == "unknown"
        assert not any(hop.decision == "allow" for hop in firewall_hops)
        assert firewall_hops[0].rule_analysis
        observed = next(
            item
            for item in firewall_hops[0].rule_analysis
            if item.rule_name == "allow-contoso"
        )
        assert observed.rule_name == "allow-contoso"
        assert observed.group_priority == 0
        assert observed.destinations == ("FQDN: *.contoso.com",)
        assert observed.applicability == "specific_destination_required"
        assert "specific host" in firewall_hops[0].reason

    def test_generic_internet_matches_a_broad_default_address_rule(self) -> None:
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/allow-all-internet",
            name="allow-all-internet",
            priority=20,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/allow-all-internet/rules/allow-all",
                    name="allow-all",
                    rule_type="NetworkRule",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["0.0.0.0/0"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(collection)

        result = service.validate_flow(
            FlowQuery(
                source=PROD_SUBNET,
                destination="internet",
                port=443,
                protocol="Tcp",
            )
        )

        firewall_hop = next(
            hop for hop in result.hops if hop.control == "azure_firewall"
        )
        assert firewall_hop.decision == "allow"
        assert firewall_hop.rule_name == "allow-all"

    def test_generic_internet_does_not_assume_a_specific_public_cidr_misses(
        self,
    ) -> None:
        collection = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/public-cidr",
            name="public-cidr",
            priority=20,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/public-cidr/rules/allow-dns",
                    name="allow-dns",
                    rule_type="NetworkRule",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["8.8.8.0/24"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(collection)

        result = service.validate_flow(
            FlowQuery(
                source=PROD_SUBNET,
                destination="internet",
                port=443,
                protocol="Tcp",
            )
        )

        assert result.verdict == VERDICT_INDETERMINATE
        firewall_hop = next(
            hop for hop in result.hops if hop.control == "azure_firewall"
        )
        assert firewall_hop.decision == "unknown"
        observed = next(
            item
            for item in firewall_hop.rule_analysis
            if item.rule_name == "allow-dns"
        )
        assert observed.applicability == "specific_destination_required"

    def test_network_rules_are_processed_before_application_rules(self) -> None:
        application_allow = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/application-first-by-number",
            name="application-first-by-number",
            priority=10,
            action="Allow",
            collection_type="ApplicationRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/application-first-by-number/rules/allow-app",
                    name="allow-app",
                    rule_type="ApplicationRule",
                    action="Allow",
                    protocols=["Https"],
                    source_addresses=["10.1.0.0/16"],
                    destination_fqdns=["app.contoso.com"],
                    destination_ports=["443"],
                ),
            ),
        )
        network_deny = FirewallRuleCollection(
            resource_id="/fwp/rulecollections/network-later-by-number",
            name="network-later-by-number",
            priority=900,
            action="Deny",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollections/network-later-by-number/rules/deny-network",
                    name="deny-network",
                    rule_type="NetworkRule",
                    action="Deny",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["*"],
                    destination_ports=["443"],
                ),
            ),
        )
        service = self._service_with_collections(application_allow, network_deny)

        result = service.validate_flow(
            FlowQuery(
                source=PROD_SUBNET,
                destination="app.contoso.com",
                port=443,
                protocol="Tcp",
            )
        )

        firewall = next(hop for hop in result.hops if hop.control == "azure_firewall")
        assert firewall.decision == "deny"
        assert firewall.rule_name == "deny-network"

    def test_rule_collection_group_priority_orders_collections_within_a_type(self) -> None:
        lower_priority_group = FirewallRuleCollection(
            resource_id="/fwp/rulecollectiongroups/200/rulecollections/allow",
            name="allow-later-group",
            group_priority=200,
            priority=100,
            action="Allow",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollectiongroups/200/rulecollections/allow/rules/allow",
                    name="allow-later-group",
                    rule_type="NetworkRule",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["*"],
                    destination_ports=["443"],
                ),
            ),
        )
        higher_priority_group = FirewallRuleCollection(
            resource_id="/fwp/rulecollectiongroups/100/rulecollections/deny",
            name="deny-earlier-group",
            group_priority=100,
            priority=900,
            action="Deny",
            collection_type="NetworkRuleCollection",
            rules=(
                FirewallRule(
                    resource_id="/fwp/rulecollectiongroups/100/rulecollections/deny/rules/deny",
                    name="deny-earlier-group",
                    rule_type="NetworkRule",
                    protocols=["Tcp"],
                    source_addresses=["10.1.0.0/16"],
                    destination_addresses=["*"],
                    destination_ports=["443"],
                ),
            ),
        )
        base_service = build_service(network_rows())
        service = NetworkIntelligenceService(
            replace(
                base_service.snapshot,
                firewall_collections=(lower_priority_group, higher_priority_group),
            )
        )

        result = service.validate_flow(
            FlowQuery(source=PROD_SUBNET, destination="internet", port=443, protocol="Tcp")
        )

        firewall = next(hop for hop in result.hops if hop.control == "azure_firewall")
        assert firewall.decision == "deny"
        assert firewall.rule_name == "deny-earlier-group"


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
