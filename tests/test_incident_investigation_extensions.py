from __future__ import annotations

from intelligence.incidents.blast_radius_engine import BlastRadiusEngine
from intelligence.incidents.event_timeline import EventTimelineEngine
from intelligence.incidents.root_cause_engine import RootCauseEngine
from network.models import (
    NetworkInterface,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
    Subnet,
    VNet,
)
from network.service import NetworkIntelligenceService


def test_timeline_normalizes_network_and_cve_events():
    timeline = EventTimelineEngine()
    events = timeline.normalize(
        network_changes=[
            {
                "change_id": "NET-1",
                "changed_at": "2026-08-18T11:30:00Z",
                "summary": "Firewall policy updated",
                "changed_fields": ["firewallPolicy"],
            },
            {
                "change_id": "NET-2",
                "changed_at": "2026-08-18T11:31:00Z",
                "summary": "NSG rule added",
                "changed_fields": ["securityRules"],
            },
        ],
        cve_exposures=[
            {
                "finding_id": "CVE-1",
                "observed_at": "2026-08-18T10:00:00Z",
                "summary": "CVE-2026-0001 exposed",
            }
        ],
    )
    event_types = {event["event_type"] for event in events}
    assert {"Firewall Rule Change", "NSG Change", "CVE Exposure"} <= event_types


def test_root_cause_reports_contradictions_unknowns_and_next_steps():
    finding = {
        "resource": {"name": "vm-payments"},
        "owner": "Unknown",
        "support_team": "Unknown",
        "probable_causes": [
            {
                "evidence_id": "CHG-1",
                "evidence_type": "Resource Change",
                "classification": "Probable cause",
                "confidence": 0.9,
                "observed_at": "2026-08-18T11:40:00Z",
                "summary": "Configuration changed",
                "evidence": ["target match +35"],
            }
        ],
        "contributing_factors": [
            {
                "evidence_id": "ALT-1",
                "evidence_type": "Alert",
                "classification": "Contributing factor",
                "confidence": 0.5,
                "summary": "Availability alert",
                "evidence": ["temporal proximity +25"],
            }
        ],
        "impacted_applications": ["Payments"],
        "incident": {"started_at": "2026-08-18T12:00:00Z"},
    }
    timeline = [
        {
            "event_id": "PATCH-OK",
            "event_type": "Patch Success",
            "timestamp": "2026-08-18T12:05:00Z",
            "summary": "Patch installed successfully",
            "source": "Patch",
            "evidence": [],
        }
    ]
    result = RootCauseEngine().analyze(finding, timeline)
    assert result["contradicting_evidence"]
    assert "owner_not_mapped:vm-payments" in result["unknowns"]
    assert any("Review" in step or "Confirm" in step for step in result["next_steps"])


def test_blast_radius_surfaces_network_context():
    snapshot = NetworkSnapshot(
        vnets=(
            VNet(
                resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet-prod",
                name="vnet-prod",
                subscription_id="sub-1",
                connection_id="conn-1",
            ),
        ),
        subnets=(
            Subnet(
                resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet-prod/subnets/app",
                name="app",
                subscription_id="sub-1",
                connection_id="conn-1",
                vnet_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet-prod",
                nsg_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/nsg-app",
                address_prefixes=("10.0.0.0/24",),
            ),
        ),
        nics=(
            NetworkInterface(
                resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/networkinterfaces/nic-payments",
                name="nic-payments",
                subscription_id="sub-1",
                connection_id="conn-1",
                subnet_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/virtualnetworks/vnet-prod/subnets/app",
                nsg_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/nsg-app",
                attached_resource_id="/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments",
                private_ips=("10.0.0.4",),
            ),
        ),
        nsgs=(
            NetworkSecurityGroup(
                resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/nsg-app",
                name="nsg-app",
                subscription_id="sub-1",
                connection_id="conn-1",
                rules=(
                    NetworkSecurityRule(
                        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.network/networksecuritygroups/nsg-app/securityrules/rule1",
                        name="allow-web",
                        subscription_id="sub-1",
                        connection_id="conn-1",
                        access="Allow",
                        direction="Inbound",
                        priority=100,
                        source_address="*",
                        destination_address="*",
                        destination_port="443",
                    ),
                ),
            ),
        ),
    )
    service = NetworkIntelligenceService(snapshot)
    finding = {
        "_resource_key": "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments",
        "resource": {"name": "vm-payments"},
        "impacted_applications": ["Payments"],
        "impacted_services": ["Checkout API"],
        "impacted_business_services": ["Retail Checkout"],
        "owner": "ops@example.com",
        "support_team": "Payments SRE",
        "downstream_dependents": ["Checkout API"],
        "upstream_dependencies": ["API Gateway"],
    }
    result = BlastRadiusEngine(network_lookup=lambda: service).analyze(finding)
    assert result["subscriptions"] == ["sub-1"]
    assert result["nsg_impact"]
    assert result["downstream_services"] == ["Checkout API"]
