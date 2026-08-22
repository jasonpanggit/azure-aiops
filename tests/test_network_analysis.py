"""Tests for firewall/NSG tightening analysis and design gap detection."""

from __future__ import annotations

from network_scenario import network_rows

from network import (
    NetworkDesignPolicy,
    NetworkScope,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
    analyze_rules,
    build_service,
)
from network.design import ApprovedPeering


def _findings():
    return build_service(network_rows()).rule_findings


def _by_category(category: str):
    return [item for item in _findings() if item.category == category]


def _rule(**kwargs) -> NetworkSnapshot:
    defaults = {
        "resource_id": "/nsg/a/securityrules/r",
        "name": "r",
        "nsg_id": "/nsg/a",
        "priority": 100,
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "Tcp",
        "source_address": "10.0.0.0/24",
        "destination_address": "10.0.1.0/24",
        "destination_port": "443",
    }
    defaults.update(kwargs)
    nsg = NetworkSecurityGroup(
        resource_id="/nsg/a",
        name="a",
        subnet_ids=("/vnet/a/subnets/s",),
        rules=(NetworkSecurityRule(**defaults),),
        tags={"owner": "team@example.com"},
    )
    return NetworkSnapshot(nsgs=(nsg,))


class TestInternetExposure:
    def test_internet_inbound_rdp_is_flagged(self) -> None:
        findings = _by_category("internet_inbound")
        assert any(finding.rule_name == "allow-rdp-any" for finding in findings)

    def test_rdp_exposure_is_flagged_as_a_sensitive_port(self) -> None:
        findings = _by_category("sensitive_port_exposure")
        assert any("RDP" in finding.detail for finding in findings)

    def test_internet_inbound_on_a_sensitive_port_is_critical(self) -> None:
        findings = [
            item
            for item in _findings()
            if item.rule_name == "allow-rdp-any" and item.category == "internet_inbound"
        ]
        assert findings and findings[0].severity == "critical"

    def test_outbound_internet_is_not_flagged_as_inbound_exposure(self) -> None:
        snapshot = _rule(direction="Outbound", source_address="*", destination_address="*")
        assert not [f for f in analyze_rules(snapshot) if f.category == "internet_inbound"]


class TestAnyAnyRules:
    def test_any_any_allow_is_flagged(self) -> None:
        snapshot = _rule(
            source_address="*", destination_address="*", destination_port="*", protocol="*"
        )
        assert [f for f in analyze_rules(snapshot) if f.category == "any_any"]

    def test_any_any_deny_is_not_flagged(self) -> None:
        snapshot = _rule(
            access="Deny",
            source_address="*",
            destination_address="*",
            destination_port="*",
            protocol="*",
        )
        assert not [f for f in analyze_rules(snapshot) if f.category == "any_any"]

    def test_synthesized_defaults_are_never_flagged(self) -> None:
        """Azure's own defaults are not customer misconfiguration."""
        snapshot = NetworkSnapshot(
            nsgs=(
                NetworkSecurityGroup(
                    resource_id="/nsg/x", name="x", subnet_ids=("/vnet/x/subnets/s",)
                ),
            )
        )
        assert analyze_rules(snapshot) == ()


class TestWideSourceCidr:
    def test_broad_source_prefix_is_flagged(self) -> None:
        findings = _by_category("wide_source_cidr")
        assert any(finding.rule_name == "allow-uat-sql" for finding in findings)

    def test_narrow_source_is_not_flagged(self) -> None:
        snapshot = _rule(source_address="10.0.0.0/28")
        assert not [f for f in analyze_rules(snapshot) if f.category == "wide_source_cidr"]


class TestShadowedRules:
    def test_rule_fully_covered_by_a_higher_priority_rule_is_flagged(self) -> None:
        findings = _by_category("shadowed")
        assert any(finding.rule_name == "allow-https-narrow" for finding in findings)

    def test_no_shadow_claim_when_subsumption_is_uncertain(self) -> None:
        """A service tag makes coverage undecidable; silence beats a false claim."""
        nsg = NetworkSecurityGroup(
            resource_id="/nsg/a",
            name="a",
            tags={"owner": "t@example.com"},
            rules=(
                NetworkSecurityRule(
                    resource_id="/nsg/a/securityrules/high",
                    name="high",
                    nsg_id="/nsg/a",
                    priority=100,
                    source_address="Storage",
                    destination_address="*",
                    destination_port="443",
                ),
                NetworkSecurityRule(
                    resource_id="/nsg/a/securityrules/low",
                    name="low",
                    nsg_id="/nsg/a",
                    priority=200,
                    source_address="10.0.0.0/24",
                    destination_address="*",
                    destination_port="443",
                ),
            ),
        )
        snapshot = NetworkSnapshot(nsgs=(nsg,))
        assert not [f for f in analyze_rules(snapshot) if f.category == "shadowed"]


class TestCrossEnvironment:
    def test_uat_to_prod_is_flagged(self) -> None:
        findings = _by_category("cross_environment")
        assert findings
        assert any(finding.rule_name == "allow-uat-sql" for finding in findings)


class TestOwnership:
    def test_rule_without_an_owner_is_flagged(self) -> None:
        findings = _by_category("missing_owner")
        assert any(finding.rule_name == "allow-rdp-any" for finding in findings)

    def test_owned_rules_are_not_flagged(self) -> None:
        assert not [
            finding
            for finding in _by_category("missing_owner")
            if finding.rule_name == "allow-https"
        ]


class TestEvidence:
    def test_every_finding_explains_its_basis(self) -> None:
        for finding in _findings():
            assert finding.detail, f"{finding.category} finding has no detail"
            assert finding.recommendation
            assert finding.severity in {"critical", "high", "medium", "low", "info"}

    def test_findings_serialize_for_the_api(self) -> None:
        payload = _findings()[0].to_dict()
        assert payload["category"]
        assert payload["severity"]
        assert payload["rule_id"]
        assert payload["control_id"]
        assert payload["evidence"]


class TestGaps:
    def _gaps(self, category: str):
        return [gap for gap in build_service(network_rows()).gaps if gap.category == category]

    def test_spoke_without_a_udr_is_a_firewall_bypass(self) -> None:
        assert self._gaps("firewall_bypass")

    def test_missing_udr_is_reported(self) -> None:
        assert self._gaps("missing_udr")

    def test_one_sided_peering_is_an_asymmetric_routing_risk(self) -> None:
        assert self._gaps("asymmetric_routing_risk")

    def test_private_endpoint_without_a_linked_zone_is_a_dns_gap(self) -> None:
        assert self._gaps("dns_dependency_gap")

    def test_firewall_rule_matching_no_observed_subnet_is_orphaned(self) -> None:
        gaps = self._gaps("orphan_firewall_rule")
        assert any("legacy-app" in gap.resource_name for gap in gaps)

    def test_public_ip_on_a_spoke_nic_is_a_bypass(self) -> None:
        gaps = self._gaps("firewall_bypass")
        assert any("public IP" in gap.title for gap in gaps)

    def test_every_gap_carries_evidence_and_a_recommendation(self) -> None:
        for gap in build_service(network_rows()).gaps:
            assert gap.detail
            assert gap.recommendation
            assert gap.severity in {"critical", "high", "medium", "low", "info"}


class TestDesignPolicy:
    def test_absent_policy_is_a_valid_state(self) -> None:
        policy = NetworkDesignPolicy()
        assert not policy.is_declared

    def test_undeclared_policy_does_not_claim_unapproved_peerings(self) -> None:
        service = build_service(network_rows())
        assert not service.policy.is_declared
        unapproved = [gap for gap in service.gaps if gap.category == "unapproved_peering"]
        # Spoke-to-spoke is unapproved by hub-spoke convention, not by policy.
        for gap in unapproved:
            assert "spoke" in gap.detail.lower() or "hub" in gap.detail.lower()

    def test_declared_policy_approves_listed_peerings(self) -> None:
        policy = NetworkDesignPolicy(
            approved_peerings=(ApprovedPeering(source="vnet-prod", target="vnet-uat"),),
        )
        assert policy.is_declared
        assert policy.peering_is_approved("vnet-prod", "vnet-uat")
        assert not policy.peering_is_approved("vnet-prod", "vnet-other")

    def test_policy_round_trips_through_a_mapping(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "hub_vnets": ["vnet-hub"],
                "approved_peerings": [{"source": "vnet-hub", "target": "vnet-prod"}],
            }
        )
        assert policy.is_declared
        assert policy.declares_hub("vnet-hub")
        assert policy.peering_is_approved("vnet-hub", "vnet-prod")

    def test_missing_policy_file_is_not_an_error(self) -> None:
        from network import load_design_policy

        policy = load_design_policy("/nonexistent/network-design.yaml")
        assert not policy.is_declared


class TestScoping:
    def test_scope_narrows_results_to_one_connection(self) -> None:
        service = build_service(network_rows())
        scoped = service.analyze(NetworkScope(connection_ids=("conn-uat",)))
        assert scoped.topology.classifications
        for item in scoped.topology.classifications:
            assert item.connection_id == "conn-uat"

    def test_empty_scope_returns_everything(self) -> None:
        service = build_service(network_rows())
        assert len(service.analyze().topology.classifications) == 3

    def test_scope_narrows_the_underlying_snapshot_not_just_the_classifications(
        self,
    ) -> None:
        """The topology summary is derived from the snapshot, so leaving the
        snapshot unscoped would report estate-wide counts and connection IDs
        to a caller who may only see one connection."""
        service = build_service(network_rows())
        scoped = service.analyze(NetworkScope(connection_ids=("conn-uat",)))
        assert scoped.topology.connection_ids == ("conn-uat",)
        assert scoped.topology.snapshot.counts()["vnets"] == 1
        assert service.analyze().topology.snapshot.counts()["vnets"] == 3

    def test_scope_preserves_the_observation_stamp(self) -> None:
        service = build_service(network_rows())
        scoped = service.analyze(NetworkScope(connection_ids=("conn-uat",)))
        assert scoped.topology.snapshot.observed_at == service.snapshot.observed_at
        assert scoped.topology.snapshot.observed_at

    def test_environment_scope_filters_findings(self) -> None:
        service = build_service(network_rows())
        scoped = service.analyze(NetworkScope(environments=("uat",)))
        for finding in scoped.rule_findings:
            assert finding.environment in {"uat", ""}


class TestSummary:
    def test_summary_reports_the_mvp_headline_numbers(self) -> None:
        summary = build_service(network_rows()).analyze().summary()
        assert summary["hub_count"] == 1
        assert summary["spoke_count"] == 2
        assert summary["gap_count"] > 0
        assert summary["rule_finding_count"] > 0
        assert summary["intended_design_declared"] is False
        assert summary["cross_subscription_peering_count"] > 0
