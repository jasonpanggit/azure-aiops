"""Shared curated-snapshot fixture for the full AIOps operational-context-
graph comparison (extends the D-04a topology-only comparison in
``tests/topology_comparison_scenario.py`` to the complete ontology surface).

Covers every entity type in ``ontology.entity_builder``'s
``TAG_ENTITY_TYPES``/``RESOURCE_ENTITY_TYPES`` mapping tables and every
relationship predicate ``ontology.relationship_builder.RelationshipBuilder``
infers (structural inventory hierarchy, tag-derived business context,
subscription-connection lineage, management-group hierarchy, cost/patch/
advisor edges, and the full re-derived network topology edge set), so the
Fabric-native ``ontology_pipeline`` parity tests exercise the same breadth
AIOps itself does -- not just a VM + PatchAssessment + AdvisorRecommendation
sample.

Kept as a single source of truth (shared fixture, not per-arm fixtures) so
neither ``ontology_pipeline.derive_entities``/``derive_relationships`` nor
``EntityBuilder``/``RelationshipBuilder`` directly can be fed a conveniently
different-shaped fixture that flatters its own output.
"""

from __future__ import annotations

import json
from typing import Any

TIMESTAMP = "2026-08-27T00:00:00Z"

TENANT_ID = "tenant-1"
SUBSCRIPTION_ID = "sub-1"
MANAGEMENT_GROUP_ID = "/providers/microsoft.management/managementgroups/mg-root"

_RG = f"/subscriptions/{SUBSCRIPTION_ID}/resourcegroups/rg-ontology-fixture"

VM_ID = f"{_RG}/providers/microsoft.compute/virtualmachines/vm-fixture"
ARC_SERVER_ID = f"{_RG}/providers/microsoft.hybridcompute/machines/arc-fixture"
AKS_ID = f"{_RG}/providers/microsoft.containerservice/managedclusters/aks-fixture"
PATCH_ASSESSMENT_ID = f"{VM_ID}/patchassessmentresults/latest"
PATCH_INSTALLATION_ID = f"{VM_ID}/patchinstallationresults/latest"
ADVISOR_RECOMMENDATION_ID = f"{_RG}/providers/microsoft.advisor/recommendations/rec-fixture"
COST_ACTUAL_ID = f"{_RG}/providers/microsoft.costmanagement/costactuals/cost-fixture"

CONNECTION_ID = "conn-fixture-1"

VNET_ID = f"{_RG}/providers/microsoft.network/virtualnetworks/vnet-fixture"
SUBNET_ID = f"{VNET_ID}/subnets/subnet-fixture"
NSG_ID = f"{_RG}/providers/microsoft.network/networksecuritygroups/nsg-fixture"
ROUTE_TABLE_ID = f"{_RG}/providers/microsoft.network/routetables/rt-fixture"
NIC_ID = f"{_RG}/providers/microsoft.network/networkinterfaces/nic-fixture"
FIREWALL_ID = f"{_RG}/providers/microsoft.network/azurefirewalls/fw-fixture"
FIREWALL_POLICY_ID = f"{_RG}/providers/microsoft.network/firewallpolicies/fwpolicy-fixture"
PRIVATE_ENDPOINT_ID = f"{_RG}/providers/microsoft.network/privateendpoints/pe-fixture"
PRIVATE_DNS_ZONE_ID = f"{_RG}/providers/microsoft.network/privatednszones/dns-fixture"
NETWORK_GATEWAY_ID = f"{_RG}/providers/microsoft.network/virtualnetworkgateways/gw-fixture"
NAT_GATEWAY_ID = f"{_RG}/providers/microsoft.network/natgateways/natgw-fixture"
LOAD_BALANCER_ID = f"{_RG}/providers/microsoft.network/loadbalancers/lb-fixture"
MANAGED_ENV_ID = f"{_RG}/providers/microsoft.app/managedenvironments/cae-fixture"
PEER_VNET_ID = f"{_RG}/providers/microsoft.network/virtualnetworks/vnet-peer-fixture"
VNET_PEERING_ID = f"{VNET_ID}/virtualnetworkpeerings/peer-fixture"


def _row(**overrides: Any) -> dict[str, Any]:
    row = {
        "tenant_id": TENANT_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "resource_id": VM_ID,
        "timestamp": TIMESTAMP,
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "VirtualMachine",
        "name": "vm-fixture",
        "resource_type": "microsoft.compute/virtualmachines",
        "location": "eastus",
        "payload_json": "{}",
    }
    row.update(overrides)
    return row


def _payload(**overrides: Any) -> str:
    base = {
        "tenantId": TENANT_ID,
        "subscriptionId": SUBSCRIPTION_ID,
        "resourceGroup": "rg-ontology-fixture",
    }
    base.update(overrides)
    return json.dumps(base, sort_keys=True)


def ontology_comparison_scenario() -> list[dict[str, Any]]:
    """Returns raw inventory-shaped rows (``resource_id``/``payload_json``
    envelope, matching what ``EntityBuilder.build``/``ontology_pipeline.
    derive_entities`` both consume) covering the full AIOps ontology
    surface: every ``TAG_ENTITY_TYPES``/``RESOURCE_ENTITY_TYPES`` entity
    type, subscription-connection lineage (with health/environment/
    application/business-service edges), management-group hierarchy,
    dependency-tag edges, cost/patch/advisor edges, and the complete
    network-topology predicate set.
    """
    rows: list[dict[str, Any]] = []

    # -- Management group + subscription hierarchy (owns/contains). --------
    rows.append(
        _row(
            resource_id=MANAGEMENT_GROUP_ID,
            entity_type="ManagementGroup",
            resource_type="microsoft.management/managementgroups",
            name="mg-root",
            payload_json=json.dumps(
                {"id": MANAGEMENT_GROUP_ID, "name": "mg-root", "tenantId": TENANT_ID}, sort_keys=True
            ),
        )
    )
    rows.append(
        _row(
            resource_id=f"/subscriptions/{SUBSCRIPTION_ID}",
            entity_type="Subscription",
            resource_type="microsoft.resources/subscriptions",
            name=SUBSCRIPTION_ID,
            payload_json=json.dumps(
                {
                    "id": f"/subscriptions/{SUBSCRIPTION_ID}",
                    "name": SUBSCRIPTION_ID,
                    "tenantId": TENANT_ID,
                    "subscriptionId": SUBSCRIPTION_ID,
                    "managementGroupAncestorsChain": [{"name": "mg-root"}],
                },
                sort_keys=True,
            ),
        )
    )

    # -- Subscription connection: health + environment/application/
    #    business-service lineage (mapped_to/runs/supports/deployed_in/
    #    contains/owns edges), mirrors test_entity_builder.py's connection
    #    coverage. ------------------------------------------------------
    rows.append(
        _row(
            resource_id="",
            entity_type="SubscriptionConnection",
            resource_type="",
            name="",
            connection_id=CONNECTION_ID,
            connection_name="Payments Landing Zone Connection",
            connection_health_status="Healthy",
            environment_name="Production",
            application_name="Payments API",
            business_service_name="Retail Banking",
            payload_json="{}",
        )
    )

    # -- Assets (VirtualMachine/ArcServer/KubernetesCluster) with full tag
    #    coverage exercising every TAG_ENTITY_TYPES mapping plus dependency
    #    tags. --------------------------------------------------------
    full_tags = {
        "AppName": "Payments API",
        "Environment": "Production",
        "BusinessUnit": "Retail",
        "BusinessService": "Retail Banking",
        "CostCenter": "CC-42",
        "Owner": "ops@example.com",
        "SupportGroup": "SRE",
        "SupportTeam": "Core Platform",
        "Service": "Checkout",
        "ServiceName": "Checkout Service",
        "SubscriptionConnection": CONNECTION_ID,
        "DependsOn": "Identity API, Ledger API",
    }
    rows.append(
        _row(
            resource_id=VM_ID,
            entity_type="VirtualMachine",
            resource_type="microsoft.compute/virtualmachines",
            name="vm-fixture",
            payload_json=_payload(id=VM_ID, name="vm-fixture", tags=full_tags),
        )
    )
    rows.append(
        _row(
            resource_id=ARC_SERVER_ID,
            entity_type="Resource",
            resource_type="microsoft.hybridcompute/machines",
            name="arc-fixture",
            payload_json=_payload(id=ARC_SERVER_ID, name="arc-fixture", tags={"AppName": "Payments API"}),
        )
    )
    rows.append(
        _row(
            resource_id=AKS_ID,
            entity_type="Resource",
            resource_type="microsoft.containerservice/managedclusters",
            name="aks-fixture",
            payload_json=_payload(id=AKS_ID, name="aks-fixture", tags={"AppName": "Payments API"}),
        )
    )

    # -- PatchAssessment / PatchInstallation / AdvisorRecommendation /
    #    CostActual -- assessedBy/impacts-analog edges (evaluates/
    #    records_installation_for/affects/incurs_cost). -----------------
    rows.append(
        _row(
            resource_id=PATCH_ASSESSMENT_ID,
            entity_type="PatchAssessment",
            resource_type="microsoft.compute/virtualmachines/patchassessmentresults",
            name="latest",
            payload_json=_payload(targetResourceId=VM_ID),
        )
    )
    rows.append(
        _row(
            resource_id=PATCH_INSTALLATION_ID,
            entity_type="PatchInstallation",
            resource_type="microsoft.compute/virtualmachines/patchinstallationresults",
            name="latest",
            payload_json=_payload(targetResourceId=VM_ID),
        )
    )
    rows.append(
        _row(
            resource_id=ADVISOR_RECOMMENDATION_ID,
            entity_type="AdvisorRecommendation",
            resource_type="microsoft.advisor/recommendations",
            name="rec-fixture",
            payload_json=_payload(targetResourceId=VM_ID),
        )
    )
    rows.append(
        _row(
            resource_id=COST_ACTUAL_ID,
            entity_type="CostActual",
            resource_type="microsoft.costmanagement/costactuals",
            name="cost-fixture",
            payload_json=_payload(resourceId=VM_ID),
        )
    )

    # -- Full network topology (contains/hasPeering/protectedBy/routedBy/
    #    egressesVia/peersWith/hasRule/hasRoute/attachedTo/
    #    hasNetworkInterface/enforcesPolicy/hasRuleCollection/
    #    exposesPrivately/resolvesFor/loadBalances/hosts). ----------------
    rows.append(
        _row(
            resource_id=VNET_ID,
            entity_type="VNet",
            resource_type="microsoft.network/virtualnetworks",
            name="vnet-fixture",
            payload_json=_payload(subnetIds=[SUBNET_ID], peeringIds=[VNET_PEERING_ID]),
        )
    )
    rows.append(
        _row(
            resource_id=PEER_VNET_ID,
            entity_type="VNet",
            resource_type="microsoft.network/virtualnetworks",
            name="vnet-peer-fixture",
            payload_json=_payload(subnetIds=[], peeringIds=[]),
        )
    )
    rows.append(
        _row(
            resource_id=VNET_PEERING_ID,
            entity_type="VNetPeering",
            resource_type="",
            name="peer-fixture",
            payload_json=_payload(remoteVnetId=PEER_VNET_ID, peeringState="Connected", allowForwardedTraffic=True),
        )
    )
    rows.append(
        _row(
            resource_id=SUBNET_ID,
            entity_type="Subnet",
            resource_type="",
            name="subnet-fixture",
            payload_json=_payload(vnetId=VNET_ID, nsgId=NSG_ID, routeTableId=ROUTE_TABLE_ID, natGatewayId=NAT_GATEWAY_ID),
        )
    )
    rows.append(
        _row(
            resource_id=NAT_GATEWAY_ID,
            entity_type="NetworkGateway",
            resource_type="microsoft.network/natgateways",
            name="natgw-fixture",
            payload_json=_payload(id=NAT_GATEWAY_ID, name="natgw-fixture"),
        )
    )
    rows.append(
        _row(
            resource_id=NSG_ID,
            entity_type="NetworkSecurityGroup",
            resource_type="microsoft.network/networksecuritygroups",
            name="nsg-fixture",
            payload_json=_payload(ruleIds=[f"{NSG_ID}/securityrules/allow-https"]),
        )
    )
    rows.append(
        _row(
            resource_id=f"{NSG_ID}/securityrules/allow-https",
            entity_type="NetworkSecurityRule",
            resource_type="",
            name="allow-https",
            payload_json=_payload(
                nsgId=NSG_ID,
                priority=100,
                direction="Inbound",
                access="Allow",
                protocol="Tcp",
            ),
        )
    )
    rows.append(
        _row(
            resource_id=ROUTE_TABLE_ID,
            entity_type="RouteTable",
            resource_type="microsoft.network/routetables",
            name="rt-fixture",
            payload_json=_payload(routeIds=[f"{ROUTE_TABLE_ID}/routes/default"]),
        )
    )
    rows.append(
        _row(
            resource_id=f"{ROUTE_TABLE_ID}/routes/default",
            entity_type="Route",
            resource_type="",
            name="default",
            payload_json=_payload(routeTableId=ROUTE_TABLE_ID, addressPrefix="0.0.0.0/0", nextHopType="Internet"),
        )
    )
    rows.append(
        _row(
            resource_id=NIC_ID,
            entity_type="NetworkInterface",
            resource_type="microsoft.network/networkinterfaces",
            name="nic-fixture",
            payload_json=_payload(nsgId=NSG_ID, subnetId=SUBNET_ID, attachedResourceId=VM_ID, privateIps=["10.10.1.4"]),
        )
    )
    rows.append(
        _row(
            resource_id=FIREWALL_ID,
            entity_type="AzureFirewall",
            resource_type="microsoft.network/azurefirewalls",
            name="fw-fixture",
            payload_json=_payload(subnetId=SUBNET_ID, policyId=FIREWALL_POLICY_ID),
        )
    )
    rows.append(
        _row(
            resource_id=FIREWALL_POLICY_ID,
            entity_type="FirewallPolicy",
            resource_type="microsoft.network/firewallpolicies",
            name="fwpolicy-fixture",
            payload_json=_payload(firewallIds=[FIREWALL_ID]),
        )
    )
    rows.append(
        _row(
            resource_id=f"{FIREWALL_POLICY_ID}/rulecollections/rc-fixture",
            entity_type="FirewallRuleCollection",
            resource_type="",
            name="rc-fixture",
            payload_json=_payload(
                policyId=FIREWALL_POLICY_ID,
                priority=100,
                action="Allow",
                collectionType="FilterCollection",
                ruleIds=[f"{FIREWALL_POLICY_ID}/rulecollections/rc-fixture/rules/rule-fixture"],
            ),
        )
    )
    rows.append(
        _row(
            resource_id=f"{FIREWALL_POLICY_ID}/rulecollections/rc-fixture/rules/rule-fixture",
            entity_type="FirewallRule",
            resource_type="",
            name="rule-fixture",
            payload_json=_payload(
                collectionId=f"{FIREWALL_POLICY_ID}/rulecollections/rc-fixture",
                ruleType="NetworkRule",
                action="Allow",
            ),
        )
    )
    rows.append(
        _row(
            resource_id=PRIVATE_ENDPOINT_ID,
            entity_type="PrivateEndpoint",
            resource_type="microsoft.network/privateendpoints",
            name="pe-fixture",
            payload_json=_payload(subnetId=SUBNET_ID, targetResourceId=VM_ID, connectionState="Approved"),
        )
    )
    rows.append(
        _row(
            resource_id=PRIVATE_DNS_ZONE_ID,
            entity_type="PrivateDnsZone",
            resource_type="microsoft.network/privatednszones",
            name="dns-fixture",
            payload_json=_payload(linkedVnetIds=[VNET_ID]),
        )
    )
    rows.append(
        _row(
            resource_id=NETWORK_GATEWAY_ID,
            entity_type="NetworkGateway",
            resource_type="microsoft.network/virtualnetworkgateways",
            name="gw-fixture",
            payload_json=_payload(subnetId=SUBNET_ID, gatewayType="Vpn", sku="VpnGw1"),
        )
    )
    rows.append(
        _row(
            resource_id=MANAGED_ENV_ID,
            entity_type="Resource",
            resource_type="microsoft.app/managedenvironments",
            name="cae-fixture",
            payload_json=_payload(id=MANAGED_ENV_ID, name="cae-fixture"),
        )
    )
    rows.append(
        _row(
            resource_id=LOAD_BALANCER_ID,
            entity_type="LoadBalancer",
            resource_type="microsoft.network/loadbalancers",
            name="lb-fixture",
            payload_json=json.dumps(
                {
                    "tenantId": TENANT_ID,
                    "subscriptionId": SUBSCRIPTION_ID,
                    "subnetId": SUBNET_ID,
                    "sku": "Standard",
                    "backendResourceIds": [NIC_ID],
                    "tags": {"aca-managed-env-id": MANAGED_ENV_ID},
                },
                sort_keys=True,
            ),
        )
    )

    return rows


__all__ = [
    "ADVISOR_RECOMMENDATION_ID",
    "AKS_ID",
    "ARC_SERVER_ID",
    "COST_ACTUAL_ID",
    "FIREWALL_ID",
    "FIREWALL_POLICY_ID",
    "LOAD_BALANCER_ID",
    "MANAGED_ENV_ID",
    "MANAGEMENT_GROUP_ID",
    "NAT_GATEWAY_ID",
    "NETWORK_GATEWAY_ID",
    "NIC_ID",
    "NSG_ID",
    "PATCH_ASSESSMENT_ID",
    "PATCH_INSTALLATION_ID",
    "PEER_VNET_ID",
    "PRIVATE_DNS_ZONE_ID",
    "PRIVATE_ENDPOINT_ID",
    "ROUTE_TABLE_ID",
    "SUBNET_ID",
    "SUBSCRIPTION_ID",
    "TENANT_ID",
    "TIMESTAMP",
    "VM_ID",
    "VNET_ID",
    "VNET_PEERING_ID",
    "ontology_comparison_scenario",
]
