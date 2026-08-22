"""A realistic hub-spoke estate spanning three subscription connections.

Deliberately contains known defects so the analyzers have something to find:
a spoke that bypasses the firewall, a one-sided peering, a spoke-to-spoke
peering, an internet-facing RDP rule, a shadowed rule, and an unlinked
private DNS zone.
"""

from __future__ import annotations

import json
from typing import Any

TENANT = "tenant-1"
# Ontology rows carry an observation stamp; the API bands freshness from it.
OBSERVED_AT = "2024-06-01T00:00:00+00:00"

HUB_SUB = "sub-hub"
PROD_SUB = "sub-prod"
UAT_SUB = "sub-uat"

HUB_CONN = "conn-hub"
PROD_CONN = "conn-prod"
UAT_CONN = "conn-uat"

HUB_VNET = f"/subscriptions/{HUB_SUB}/resourcegroups/rg-hub/providers/microsoft.network/virtualnetworks/vnet-hub"
PROD_VNET = f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.network/virtualnetworks/vnet-prod"
UAT_VNET = f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/microsoft.network/virtualnetworks/vnet-uat"

FIREWALL_SUBNET = f"{HUB_VNET}/subnets/azurefirewallsubnet"
PROD_SUBNET = f"{PROD_VNET}/subnets/snet-app"
UAT_SUBNET = f"{UAT_VNET}/subnets/snet-app"

FIREWALL_ID = f"/subscriptions/{HUB_SUB}/resourcegroups/rg-hub/providers/microsoft.network/azurefirewalls/fw-hub"
FIREWALL_IP = "10.0.1.4"

PROD_NSG = f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.network/networksecuritygroups/nsg-prod"
UAT_NSG = f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/microsoft.network/networksecuritygroups/nsg-uat"

PROD_ROUTE_TABLE = f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.network/routetables/rt-prod"

FIREWALL_POLICY = f"/subscriptions/{HUB_SUB}/resourcegroups/rg-hub/providers/microsoft.network/firewallpolicies/fwp-hub"
FIREWALL_COLLECTION = f"{FIREWALL_POLICY}/rulecollections/allow-spoke-egress"


def _row(
    entity_type: str,
    resource_id: str,
    name: str,
    *,
    subscription_id: str,
    connection_id: str,
    environment: str = "",
    business_service: str = "",
    application: str = "",
    tags: dict[str, str] | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Builds an ontology-shaped row with a JSON payload, as the loader expects."""
    body = {
        "id": resource_id,
        "name": name,
        "entityType": entity_type,
        "subscriptionId": subscription_id,
        "connection_id": connection_id,
        "environment_name": environment,
        "business_service_name": business_service,
        "application_name": application,
        "tags": tags or {},
        **payload,
    }
    return {
        "tenant_id": TENANT,
        "subscription_id": subscription_id,
        "resource_id": resource_id,
        "entity_type": entity_type,
        "name": name,
        "timestamp": OBSERVED_AT,
        "payload_json": json.dumps(body),
    }


def network_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    rows.append(
        _row(
            "VNet",
            HUB_VNET,
            "vnet-hub",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            environment="prod",
            business_service="Platform",
            addressSpaces=["10.0.0.0/16"],
            subnetIds=[FIREWALL_SUBNET],
            dnsServers=[],
        )
    )
    rows.append(
        _row(
            "Subnet",
            FIREWALL_SUBNET,
            "AzureFirewallSubnet",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            environment="prod",
            vnetId=HUB_VNET,
            addressPrefixes=["10.0.1.0/24"],
        )
    )
    rows.append(
        _row(
            "AzureFirewall",
            FIREWALL_ID,
            "fw-hub",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            environment="prod",
            vnetId=HUB_VNET,
            subnetId=FIREWALL_SUBNET,
            policyId=FIREWALL_POLICY,
            privateIp=FIREWALL_IP,
            skuTier="Premium",
        )
    )
    rows.append(
        _row(
            "FirewallPolicy",
            FIREWALL_POLICY,
            "fwp-hub",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            firewallIds=[FIREWALL_ID],
        )
    )
    rows.append(
        _row(
            "FirewallRuleCollection",
            FIREWALL_COLLECTION,
            "allow-spoke-egress",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            policyId=FIREWALL_POLICY,
            priority=100,
            action="Allow",
            tags={"owner": "platform@example.com"},
        )
    )
    rows.append(
        _row(
            "FirewallRule",
            f"{FIREWALL_COLLECTION}/rules/allow-prod-to-internet",
            "allow-prod-to-internet",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            collectionId=FIREWALL_COLLECTION,
            ruleType="NetworkRule",
            action="Allow",
            protocols=["TCP"],
            sourceAddresses=["10.1.0.0/16"],
            destinationAddresses=["10.2.0.0/16"],
            destinationPorts=["443"],
            tags={"owner": "platform@example.com"},
        )
    )
    # Stale rule: 192.168.50.0/24 matches no observed subnet.
    rows.append(
        _row(
            "FirewallRule",
            f"{FIREWALL_COLLECTION}/rules/legacy-app",
            "legacy-app",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            collectionId=FIREWALL_COLLECTION,
            ruleType="NetworkRule",
            action="Allow",
            protocols=["TCP"],
            sourceAddresses=["10.1.0.0/16"],
            destinationAddresses=["192.168.50.0/24"],
            destinationPorts=["8080"],
            tags={"owner": "platform@example.com"},
        )
    )

    rows.append(
        _row(
            "VNet",
            PROD_VNET,
            "vnet-prod",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            business_service="Payments",
            addressSpaces=["10.1.0.0/16"],
            subnetIds=[PROD_SUBNET],
        )
    )
    rows.append(
        _row(
            "Subnet",
            PROD_SUBNET,
            "snet-app",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            business_service="Payments",
            vnetId=PROD_VNET,
            addressPrefixes=["10.1.0.0/24"],
            nsgId=PROD_NSG,
            routeTableId=PROD_ROUTE_TABLE,
        )
    )
    rows.append(
        _row(
            "RouteTable",
            PROD_ROUTE_TABLE,
            "rt-prod",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            subnetIds=[PROD_SUBNET],
        )
    )
    rows.append(
        _row(
            "Route",
            f"{PROD_ROUTE_TABLE}/routes/default-to-fw",
            "default-to-fw",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            routeTableId=PROD_ROUTE_TABLE,
            addressPrefix="0.0.0.0/0",
            nextHopType="VirtualAppliance",
            nextHopIp=FIREWALL_IP,
        )
    )
    rows.append(
        _row(
            "NetworkSecurityGroup",
            PROD_NSG,
            "nsg-prod",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            business_service="Payments",
            subnetIds=[PROD_SUBNET],
            tags={"owner": "payments@example.com"},
        )
    )
    rows.append(
        _row(
            "NetworkSecurityRule",
            f"{PROD_NSG}/securityrules/allow-https",
            "allow-https",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            nsgId=PROD_NSG,
            priority=100,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            sourceAddress="10.0.0.0/8",
            destinationAddress="10.1.0.0/24",
            destinationPort="443",
            tags={"owner": "payments@example.com"},
        )
    )
    # Shadowed by allow-https: narrower source, same port, lower priority.
    rows.append(
        _row(
            "NetworkSecurityRule",
            f"{PROD_NSG}/securityrules/allow-https-narrow",
            "allow-https-narrow",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            nsgId=PROD_NSG,
            priority=200,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            sourceAddress="10.2.0.0/24",
            destinationAddress="10.1.0.0/24",
            destinationPort="443",
            tags={"owner": "payments@example.com"},
        )
    )
    # UAT (10.2.0.0/16) reaching PROD SQL: cross-environment.
    rows.append(
        _row(
            "NetworkSecurityRule",
            f"{PROD_NSG}/securityrules/allow-uat-sql",
            "allow-uat-sql",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            nsgId=PROD_NSG,
            priority=300,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            sourceAddress="10.2.0.0/16",
            destinationAddress="10.1.0.0/24",
            destinationPort="1433",
            tags={"owner": "payments@example.com"},
        )
    )

    rows.append(
        _row(
            "VNet",
            UAT_VNET,
            "vnet-uat",
            subscription_id=UAT_SUB,
            connection_id=UAT_CONN,
            environment="uat",
            business_service="Payments",
            addressSpaces=["10.2.0.0/16"],
            subnetIds=[UAT_SUBNET],
        )
    )
    # No route table -> firewall bypass + missing UDR.
    rows.append(
        _row(
            "Subnet",
            UAT_SUBNET,
            "snet-app",
            subscription_id=UAT_SUB,
            connection_id=UAT_CONN,
            environment="uat",
            business_service="Payments",
            vnetId=UAT_VNET,
            addressPrefixes=["10.2.0.0/24"],
            nsgId=UAT_NSG,
        )
    )
    rows.append(
        _row(
            "NetworkSecurityGroup",
            UAT_NSG,
            "nsg-uat",
            subscription_id=UAT_SUB,
            connection_id=UAT_CONN,
            environment="uat",
            subnetIds=[UAT_SUBNET],
        )
    )
    # Internet-facing RDP with no owner tag anywhere.
    rows.append(
        _row(
            "NetworkSecurityRule",
            f"{UAT_NSG}/securityrules/allow-rdp-any",
            "allow-rdp-any",
            subscription_id=UAT_SUB,
            connection_id=UAT_CONN,
            environment="uat",
            nsgId=UAT_NSG,
            priority=100,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            sourceAddress="*",
            destinationAddress="*",
            destinationPort="3389",
        )
    )
    rows.append(
        _row(
            "NetworkInterface",
            f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/microsoft.network/networkinterfaces/nic-uat-1",
            "nic-uat-1",
            subscription_id=UAT_SUB,
            connection_id=UAT_CONN,
            environment="uat",
            subnetId=UAT_SUBNET,
            privateIps=["10.2.0.10"],
            publicIps=[
                f"/subscriptions/{UAT_SUB}/resourcegroups/rg-uat/providers/microsoft.network/publicipaddresses/pip-uat-1"
            ],
        )
    )
    rows.append(
        _row(
            "NetworkInterface",
            f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.network/networkinterfaces/nic-prod-1",
            "nic-prod-1",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            business_service="Payments",
            subnetId=PROD_SUBNET,
            privateIps=["10.1.0.10"],
        )
    )

    for local, remote, sub, conn, state in (
        (HUB_VNET, PROD_VNET, HUB_SUB, HUB_CONN, "Connected"),
        (PROD_VNET, HUB_VNET, PROD_SUB, PROD_CONN, "Connected"),
        (HUB_VNET, UAT_VNET, HUB_SUB, HUB_CONN, "Connected"),
        (UAT_VNET, HUB_VNET, UAT_SUB, UAT_CONN, "Connected"),
        # One-sided spoke-to-spoke peering: asymmetric AND unapproved.
        (PROD_VNET, UAT_VNET, PROD_SUB, PROD_CONN, "Connected"),
    ):
        rows.append(
            _row(
                "VNetPeering",
                f"{local}/virtualnetworkpeerings/to-{remote.rsplit('/', 1)[-1]}",
                f"to-{remote.rsplit('/', 1)[-1]}",
                subscription_id=sub,
                connection_id=conn,
                localVnetId=local,
                remoteVnetId=remote,
                peeringState=state,
                allowForwardedTraffic=True,
                allowGatewayTransit=local == HUB_VNET,
                allowVirtualNetworkAccess=True,
            )
        )

    zone_id = f"/subscriptions/{HUB_SUB}/resourcegroups/rg-hub/providers/microsoft.network/privatednszones/privatelink.blob.core.windows.net"
    rows.append(
        _row(
            "PrivateDnsZone",
            zone_id,
            "privatelink.blob.core.windows.net",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            zoneName="privatelink.blob.core.windows.net",
            linkedVnetIds=[HUB_VNET],
            recordCount=3,
        )
    )
    # Endpoint in PROD, zone only linked to HUB -> DNS dependency gap.
    rows.append(
        _row(
            "PrivateEndpoint",
            f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.network/privateendpoints/pe-storage",
            "pe-storage",
            subscription_id=PROD_SUB,
            connection_id=PROD_CONN,
            environment="prod",
            business_service="Payments",
            subnetId=PROD_SUBNET,
            targetResourceId=f"/subscriptions/{PROD_SUB}/resourcegroups/rg-prod/providers/microsoft.storage/storageaccounts/stpayments",
            groupIds=["blob"],
            privateDnsZoneIds=[zone_id],
            connectionState="Approved",
        )
    )

    rows.append(
        _row(
            "VpnGateway",
            f"/subscriptions/{HUB_SUB}/resourcegroups/rg-hub/providers/microsoft.network/virtualnetworkgateways/vpngw-hub",
            "vpngw-hub",
            subscription_id=HUB_SUB,
            connection_id=HUB_CONN,
            environment="prod",
            vnetId=HUB_VNET,
            subnetId=f"{HUB_VNET}/subnets/gatewaysubnet",
            gatewayType="Vpn",
            sku="VpnGw1",
        )
    )

    return rows
