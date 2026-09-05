"""Tests for firewall/NSG tightening analysis and design gap detection."""

from __future__ import annotations

import json

from network_scenario import (
    PROD_SUB,
    PROD_SUBNET,
    PROD_VNET,
    UAT_SUB,
    UAT_SUBNET,
    UAT_VNET,
    network_rows,
)

from network import (
    NetworkDesignPolicy,
    NetworkIntelligenceService,
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


def _private_link_row(
    resource_id: str,
    name: str,
    subscription_id: str,
    connection_id: str,
    resource_type: str,
) -> dict:
    payload = {
        "id": resource_id,
        "name": name,
        "entityType": "Resource",
        "subscriptionId": subscription_id,
        "connection_id": connection_id,
        "resourceType": resource_type,
        "publicNetworkAccess": "Enabled",
    }
    return {
        "subscription_id": subscription_id,
        "resource_id": resource_id,
        "entity_type": "Resource",
        "name": name,
        "payload_json": json.dumps(payload),
    }


class TestScopeIsolation:
    @staticmethod
    def _service() -> NetworkIntelligenceService:
        prod_storage = (
            f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/"
            "microsoft.storage/storageaccounts/stpayments"
        )
        foreign_vault = (
            f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/"
            "microsoft.keyvault/vaults/kv-foreign"
        )
        rows = [
            *network_rows(),
            _private_link_row(
                prod_storage,
                "stpayments",
                PROD_SUB,
                "conn-prod",
                "Microsoft.Storage/storageAccounts",
            ),
            _private_link_row(
                foreign_vault,
                "kv-foreign",
                UAT_SUB,
                "conn-uat",
                "Microsoft.KeyVault/vaults",
            ),
        ]
        return NetworkIntelligenceService.from_rows(
            rows,
            semantic_relationships=(
                {
                    "subject_id": PROD_VNET,
                    "object_id": PROD_SUBNET,
                    "predicate": "hosts",
                },
                {
                    "subject_id": UAT_VNET,
                    "object_id": UAT_SUBNET,
                    "predicate": "hosts",
                },
            ),
        )

    def test_scoped_gaps_never_include_another_subscription(self) -> None:
        scoped = self._service().scoped(NetworkScope(subscription_ids=(PROD_SUB,)))

        assert all(gap.subscription_id == PROD_SUB for gap in scoped.gaps)
        assert not any(gap.resource_name == "kv-foreign" for gap in scoped.gaps)

    def test_scoped_private_link_resources_and_counts_are_filtered(self) -> None:
        scoped = self._service().scoped(NetworkScope(subscription_ids=(PROD_SUB,)))

        assert {item.subscription_id for item in scoped.snapshot.private_link_resources} == {
            PROD_SUB
        }
        assert scoped.snapshot.counts()["private_link_resources"] == 1

    def test_scoped_semantic_relationships_keep_only_in_scope_endpoints(self) -> None:
        scoped = self._service().scoped(NetworkScope(subscription_ids=(PROD_SUB,)))

        assert scoped.semantic_relationships == (
            {
                "subject_id": PROD_VNET,
                "object_id": PROD_SUBNET,
                "predicate": "hosts",
            },
        )

    def test_in_scope_private_endpoint_still_protects_its_target(self) -> None:
        scoped = self._service().scoped(NetworkScope(subscription_ids=(PROD_SUB,)))

        missing = [
            gap
            for gap in scoped.gaps
            if gap.category == "missing_private_endpoint"
        ]
        assert not any(gap.resource_name == "stpayments" for gap in missing)


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

    def test_explicit_rule_policy_is_declared(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        "rule_id": "internet-via-firewall",
                        "name": "Internet access must traverse the firewall",
                        "enabled": False,
                    }
                ]
            }
        )
        assert policy.is_declared
        assert not policy.rule_enabled("internet-via-firewall")

    def test_missing_policy_file_is_not_an_error(self) -> None:
        from network import load_design_policy

        policy = load_design_policy("/nonexistent/network-design.yaml")
        assert not policy.is_declared


class TestPolicyRules:
    def test_default_policy_has_the_two_seed_rules(self) -> None:
        policy = NetworkDesignPolicy()
        assert policy.rule_enabled("internet-via-firewall")
        assert policy.rule_enabled("nsg-override-default-outbound")
        assert policy.rule("internet-via-firewall") is not None
        assert policy.rule("nonexistent-rule") is None

    def test_disabling_firewall_rule_suppresses_firewall_bypass_gaps(self) -> None:
        enabled = build_service(network_rows())
        assert [gap for gap in enabled.gaps if gap.category == "firewall_bypass"]

        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [{"rule_id": "internet-via-firewall", "name": "x", "enabled": False}]}
        )
        assert not policy.rule_enabled("internet-via-firewall")
        disabled = NetworkIntelligenceService.from_rows(network_rows(), policy=policy)
        assert not [gap for gap in disabled.gaps if gap.category == "firewall_bypass"]
        assert not [gap for gap in disabled.gaps if gap.category == "missing_udr"]

    def test_from_mapping_merges_overrides_with_built_in_defaults(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [{"rule_id": "internet-via-firewall", "name": "x", "enabled": False}]}
        )
        # The un-overridden built-in rule is still present and still enabled.
        assert policy.rule_enabled("nsg-override-default-outbound")
        assert len(policy.rules) == 2

    def test_nsg_without_an_outbound_override_is_a_gap(self) -> None:
        snapshot = _rule(direction="Inbound")
        gaps = [
            gap
            for gap in NetworkIntelligenceService(snapshot).gaps
            if gap.category == "nsg_default_outbound"
        ]
        assert gaps
        assert gaps[0].severity == "high"

    def test_nsg_with_an_explicit_outbound_override_is_not_a_gap(self) -> None:
        override = NetworkSecurityRule(
            resource_id="/nsg/a/securityrules/deny-internet-out",
            name="deny-internet-out",
            nsg_id="/nsg/a",
            priority=100,
            direction="Outbound",
            access="Deny",
            protocol="*",
            source_address="*",
            destination_address="Internet",
            destination_port="*",
        )
        nsg = NetworkSecurityGroup(
            resource_id="/nsg/a",
            name="a",
            subnet_ids=("/vnet/a/subnets/s",),
            rules=(override,),
        )
        gaps = [
            gap
            for gap in NetworkIntelligenceService(NetworkSnapshot(nsgs=(nsg,))).gaps
            if gap.category == "nsg_default_outbound"
        ]
        assert not gaps

    def test_disabling_nsg_rule_suppresses_the_gap(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {"rule_id": "nsg-override-default-outbound", "name": "x", "enabled": False}
                ]
            }
        )
        snapshot = _rule(direction="Inbound")
        gaps = [
            gap
            for gap in NetworkIntelligenceService(snapshot, policy=policy).gaps
            if gap.category == "nsg_default_outbound"
        ]
        assert not gaps


class TestScoping:
    def test_scope_narrows_results_to_one_connection(self) -> None:
        service = build_service(network_rows())
        scoped = service.scoped(NetworkScope(connection_ids=("conn-uat",))).analyze()
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
        scoped = service.scoped(NetworkScope(connection_ids=("conn-uat",))).analyze()
        assert scoped.topology.connection_ids == ("conn-uat",)
        assert scoped.topology.snapshot.counts()["vnets"] == 1
        assert service.analyze().topology.snapshot.counts()["vnets"] == 3

    def test_scope_preserves_the_observation_stamp(self) -> None:
        service = build_service(network_rows())
        scoped = service.scoped(NetworkScope(connection_ids=("conn-uat",))).analyze()
        assert scoped.topology.snapshot.observed_at == service.snapshot.observed_at
        assert scoped.topology.snapshot.observed_at

    def test_environment_scope_filters_findings(self) -> None:
        service = build_service(network_rows())
        scoped = service.scoped(NetworkScope(environments=("uat",))).analyze()
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


class TestRuleRegistry:
    """Every rule drives its own check, and unbacked rules say so."""

    def _paas_rows(self):
        rows = network_rows()
        for name, kind in (
            ("stpayments", "microsoft.storage/storageaccounts"),
            ("kv-payments", "microsoft.keyvault/vaults"),
        ):
            resource_group = "rg-prod"
            rows.append(
                {
                    "tenant_id": "tenant-1",
                    "subscription_id": "sub-prod",
                    "resource_id": (
                        f"/subscriptions/sub-prod/resourcegroups/{resource_group}"
                        f"/providers/{kind}/{name}"
                    ),
                    "entity_type": "Resource",
                    "name": name,
                    "type": kind,
                    "timestamp": "2024-06-01T00:00:00+00:00",
                    "connection_id": "conn-prod",
                    "publicNetworkAccess": "Enabled",
                }
            )
        return rows

    def test_paas_resources_are_projected_onto_the_snapshot(self) -> None:
        service = NetworkIntelligenceService.from_rows(self._paas_rows())
        kinds = {
            item.service_kind for item in service.snapshot.private_link_resources
        }
        assert kinds == {"Storage", "Key Vault"}

    def test_resource_without_a_private_endpoint_is_flagged(self) -> None:
        service = NetworkIntelligenceService.from_rows(self._paas_rows())
        flagged = {
            gap.resource_name
            for gap in service.gaps
            if gap.category == "missing_private_endpoint"
        }
        # The storage account is already targeted by pe-storage; the key vault is not.
        assert "kv-payments" in flagged
        assert "stpayments" not in flagged

    def test_fabric_capacity_gap_is_suppressed_but_cognitive_account_remains(
        self,
    ) -> None:
        rows = network_rows()
        rows.extend(
            [
                _private_link_row(
                    (
                        "/subscriptions/sub-prod/resourcegroups/rg-data/providers/"
                        "Microsoft.Fabric/capacities/fabric-capacity"
                    ),
                    "fabric-capacity",
                    "sub-prod",
                    "conn-prod",
                    "Microsoft.Fabric/capacities",
                ),
                _private_link_row(
                    (
                        "/subscriptions/sub-prod/resourcegroups/rg-ai/providers/"
                        "Microsoft.CognitiveServices/accounts/foundry-tools"
                    ),
                    "foundry-tools",
                    "sub-prod",
                    "conn-prod",
                    "Microsoft.CognitiveServices/accounts",
                ),
            ]
        )

        gaps = [
            gap
            for gap in NetworkIntelligenceService.from_rows(rows).gaps
            if gap.category == "missing_private_endpoint"
        ]

        assert not any(gap.resource_name == "fabric-capacity" for gap in gaps)
        assert any(gap.resource_name == "foundry-tools" for gap in gaps)

    def test_disabling_the_rule_suppresses_its_gaps(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        "rule_id": "private-endpoints-preferred",
                        "name": "Private endpoints should be used when possible",
                        "enabled": False,
                    }
                ]
            }
        )
        service = NetworkIntelligenceService.from_rows(self._paas_rows(), policy=policy)
        assert not [
            gap for gap in service.gaps if gap.category == "missing_private_endpoint"
        ]

    def test_rule_parameters_narrow_the_scope(self) -> None:
        policy = NetworkDesignPolicy.from_mapping(
            {
                "rules": [
                    {
                        "rule_id": "private-endpoints-preferred",
                        "name": "Private endpoints",
                        "parameters": {"services": ["Storage"]},
                    }
                ]
            }
        )
        service = NetworkIntelligenceService.from_rows(self._paas_rows(), policy=policy)
        assert not [
            gap for gap in service.gaps if gap.resource_name == "kv-payments"
        ]

    def test_a_rule_with_no_check_is_reported_as_unevaluated(self) -> None:
        from network.gaps import NetworkGapAnalyzer

        policy = NetworkDesignPolicy.from_mapping(
            {"rules": [{"rule_id": "bring-your-own-rule", "name": "Custom"}]}
        )
        service = NetworkIntelligenceService.from_rows(network_rows(), policy=policy)
        analyzer = NetworkGapAnalyzer(service.snapshot, service.topology, policy)
        assert [rule.rule_id for rule in analyzer.unevaluated_rules()] == [
            "bring-your-own-rule"
        ]
        assert "bring-your-own-rule" not in NetworkGapAnalyzer.evaluable_rule_ids()


class TestObservedTraffic:
    """Findings that only exist because live flow logs were ingested.

    Every case here pins the same principle: absence of observation is not
    evidence of absence. Only edges tagged with the live data source may
    produce a finding, so a curated fixture can never masquerade as
    measured traffic.
    """

    @staticmethod
    def _snapshot() -> NetworkSnapshot:
        nsg = NetworkSecurityGroup(
            resource_id="/nsg/obs",
            name="obs",
            subnet_ids=("/vnet/a/subnets/s",),
            rules=(
                NetworkSecurityRule(
                    resource_id="/nsg/obs/securityrules/allow-unused",
                    name="allow-unused",
                    nsg_id="/nsg/obs",
                    priority=100,
                    direction="Inbound",
                    access="Allow",
                    protocol="Tcp",
                    source_address="10.0.0.0/24",
                    destination_address="10.0.1.0/24",
                    destination_port="8080",
                ),
                NetworkSecurityRule(
                    resource_id="/nsg/obs/securityrules/deny-probe",
                    name="deny-probe",
                    nsg_id="/nsg/obs",
                    priority=200,
                    direction="Inbound",
                    access="Deny",
                    protocol="Tcp",
                    source_address="Internet",
                    destination_address="10.0.1.0/24",
                    destination_port="22",
                ),
            ),
            tags={"owner": "team@example.com"},
        )
        return NetworkSnapshot(nsgs=(nsg,))

    @staticmethod
    def _edge(rule_id: str, verdict: str, *, live: bool = True) -> dict:
        from network.tightening import LIVE_FLOW_DATA_SOURCE

        return {
            "predicate": "trafficObserved",
            "object": rule_id,
            "attributes": {
                "allowedVsObserved": verdict,
                "dataSource": LIVE_FLOW_DATA_SOURCE if live else "fixture",
            },
        }

    def _categories(self, findings) -> set[str]:
        return {finding.category for finding in findings}

    def test_no_flow_data_produces_no_observed_findings(self) -> None:
        findings = analyze_rules(self._snapshot())
        assert "observed_traffic" not in self._categories(findings)

    def test_fixture_sourced_edges_do_not_count_as_observation(self) -> None:
        """Curated data must never be mistaken for measured traffic."""
        edges = [
            self._edge("/nsg/obs/securityrules/deny-probe", "denied_and_blocked", live=False)
        ]
        findings = analyze_rules(self._snapshot(), edges)
        assert "observed_traffic" not in self._categories(findings)

    def test_allow_rule_with_no_observed_traffic_is_flagged(self) -> None:
        edges = [self._edge("/nsg/obs/securityrules/deny-probe", "denied_and_blocked")]
        findings = analyze_rules(self._snapshot(), edges)
        unused = [
            finding
            for finding in findings
            if finding.category == "observed_traffic"
            and finding.rule_name == "allow-unused"
        ]
        assert len(unused) == 1
        assert unused[0].evidence["observed_flow_count"] == 0

    def test_an_exercised_allow_rule_is_not_flagged(self) -> None:
        edges = [self._edge("/nsg/obs/securityrules/allow-unused", "allowed_and_observed")]
        findings = analyze_rules(self._snapshot(), edges)
        assert not [
            finding
            for finding in findings
            if finding.category == "observed_traffic"
            and finding.rule_name == "allow-unused"
        ]

    def test_deny_rule_hit_by_traffic_is_reported(self) -> None:
        edges = [
            self._edge("/nsg/obs/securityrules/deny-probe", "denied_and_blocked"),
            self._edge("/nsg/obs/securityrules/deny-probe", "denied_and_blocked"),
        ]
        findings = analyze_rules(self._snapshot(), edges)
        attempts = [
            finding
            for finding in findings
            if finding.category == "observed_traffic"
            and finding.rule_name == "deny-probe"
            and "hit by" in finding.title.casefold()
        ]
        assert len(attempts) == 1
        assert attempts[0].evidence["denied_flow_count"] == 2

    def test_traffic_contradicting_a_deny_rule_is_high_severity(self) -> None:
        """An overridden deny rule is a contradiction, not just a signal."""
        edges = [
            self._edge(
                "/nsg/obs/securityrules/deny-probe", "denied_but_traffic_observed"
            )
        ]
        findings = analyze_rules(self._snapshot(), edges)
        conflicts = [
            finding
            for finding in findings
            if finding.category == "observed_traffic"
            and finding.rule_name == "deny-probe"
            and "observed as allowed" in finding.title.casefold()
        ]
        assert len(conflicts) == 1
        assert conflicts[0].severity == "high"


def test_real_ingest_edges_drive_observed_findings() -> None:
    """End-to-end: edges as flowlog_ingest actually emits them, not hand-rolled.

    The analyzer and the ingest module must agree on edge field names and
    verdict strings. Hand-written fixtures can silently drift from the real
    shape, so this test consumes genuine ``join_flow_logs_with_nsg_rules``
    output as the contract between the two.
    """
    from fabric_pipelines.flowlog_ingest import (
        FlowLogRecord,
        join_flow_logs_with_nsg_rules,
    )

    snapshot = NetworkSnapshot(
        nsgs=(
            NetworkSecurityGroup(
                resource_id="/nsg/e2e",
                name="e2e",
                subnet_ids=("/vnet/a/subnets/s",),
                rules=(
                    NetworkSecurityRule(
                        resource_id="rule-deny-ssh",
                        name="deny-ssh",
                        nsg_id="/nsg/e2e",
                        priority=100,
                        direction="Inbound",
                        access="Deny",
                        protocol="Tcp",
                        source_address="0.0.0.0/0",
                        destination_address="10.0.1.0/24",
                        destination_port="22",
                    ),
                ),
                tags={"owner": "team@example.com"},
            ),
        )
    )
    rules = [
        {
            "id": "rule-deny-ssh",
            "name": "deny-ssh",
            "protocol": "Tcp",
            "sourceAddress": "0.0.0.0/0",
            "destinationAddress": "10.0.1.0/24",
            "destinationPort": "22",
            "access": "Deny",
            "isDefault": False,
        }
    ]
    flows = [
        FlowLogRecord(
            source_address="203.0.113.9",
            destination_address="10.0.1.5",
            destination_port="22",
            protocol="Tcp",
            decision="Deny",
            observed_at="2024-01-01T00:00:00Z",
        )
    ]
    edges = join_flow_logs_with_nsg_rules(
        rules, flows, observed="2024-01-01T00:00:00Z", live=True
    )
    assert edges, "precondition: ingest must produce an edge"

    findings = analyze_rules(snapshot, edges, observation_window_days=7)
    observed = [f for f in findings if f.category == "observed_traffic"]
    assert len(observed) == 1
    assert observed[0].rule_name == "deny-ssh"
    assert observed[0].evidence["denied_flow_count"] == 1
    assert observed[0].evidence["observation_window_days"] == 7
