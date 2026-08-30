"""Shared curated-snapshot fixture for the D-04a comparison (Pitfall 3).

One VNet/Subnet/NSG raw-ARG-shaped snapshot, structured to feed both arms
identically:

- This repo's real Fabric-native ``topology_pipeline.derive_edges()``
  (this plan, 08-02).
- AIOps's real ``SemanticEngine.from_rows()`` / ``Normalizer`` engine
  (08-03's comparison harness).

Kept as a single source of truth so neither arm can be fed a
conveniently-shaped fixture that flatters its own output (Pitfall 3: shared
fixture, not per-arm fixtures).
"""

from __future__ import annotations

from typing import Any

OBSERVED_AT = "2026-08-27T00:00:00Z"

_SUBSCRIPTION_ID = "11111111-1111-1111-1111-111111111111"
_RESOURCE_GROUP = f"/subscriptions/{_SUBSCRIPTION_ID}/resourcegroups/rg-topology-fixture"

VNET_ID = f"{_RESOURCE_GROUP}/providers/microsoft.network/virtualnetworks/vnet-fixture"
SUBNET_ID = f"{VNET_ID}/subnets/subnet-fixture"
NSG_ID = f"{_RESOURCE_GROUP}/providers/microsoft.network/networksecuritygroups/nsg-fixture"


def topology_comparison_scenario() -> dict[str, list[dict[str, Any]]]:
    """Returns raw ARG-shaped rows keyed by AIOps's ``payload`` dataset names.

    Both arms consume this same dict: the Fabric pipeline via
    ``topology_pipeline.derive_edges()``, AIOps via
    ``Normalizer._normalize_network()`` (directly, or through the
    read-port adapter proven in 08-01).
    """
    return {
        "network_vnets": [
            {
                "id": VNET_ID,
                "name": "vnet-fixture",
                "type": "microsoft.network/virtualnetworks",
                "tenantId": "22222222-2222-2222-2222-222222222222",
                "subscriptionId": _SUBSCRIPTION_ID,
                "tags": {"environment": "fixture"},
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.10.0.0/16"]},
                    "subnets": [
                        {
                            "id": SUBNET_ID,
                            "name": "subnet-fixture",
                            "properties": {
                                "addressPrefix": "10.10.1.0/24",
                                "networkSecurityGroup": {"id": NSG_ID},
                            },
                        }
                    ],
                    "virtualNetworkPeerings": [],
                },
            }
        ],
        "network_security_groups": [
            {
                "id": NSG_ID,
                "name": "nsg-fixture",
                "type": "microsoft.network/networksecuritygroups",
                "tenantId": "22222222-2222-2222-2222-222222222222",
                "subscriptionId": _SUBSCRIPTION_ID,
                "tags": {"environment": "fixture"},
                "properties": {
                    "securityRules": [
                        {
                            "id": f"{NSG_ID}/securityRules/allow-https",
                            "name": "allow-https",
                            "properties": {
                                "priority": 100,
                                "direction": "Inbound",
                                "access": "Allow",
                                "protocol": "Tcp",
                                "sourceAddressPrefix": "10.10.0.0/16",
                                "destinationAddressPrefix": "10.10.1.0/24",
                                "sourcePortRange": "*",
                                "destinationPortRange": "443",
                                "description": "Allow HTTPS within the fixture VNet",
                            },
                        }
                    ],
                    "defaultSecurityRules": [
                        {
                            "id": f"{NSG_ID}/defaultSecurityRules/DenyAllInBound",
                            "name": "DenyAllInBound",
                            "properties": {
                                "priority": 65500,
                                "direction": "Inbound",
                                "access": "Deny",
                                "protocol": "*",
                                "sourceAddressPrefix": "*",
                                "destinationAddressPrefix": "*",
                                "sourcePortRange": "*",
                                "destinationPortRange": "*",
                                "description": "Default deny-all-inbound",
                            },
                        }
                    ],
                },
            }
        ],
        "network_interfaces": [],
        "network_route_tables": [],
        "network_firewalls": [],
        "network_firewall_policies": [],
        "network_private_endpoints": [],
        "network_private_dns_zones": [],
        "network_gateways": [],
        "network_load_balancers": [],
    }


#: NSG rule rows already flattened to the ``network_normalize.py:198-251``
#: shape, for the flow-log join stage (Task 2 / D-11).
def nsg_rule_rows() -> list[dict[str, Any]]:
    from onboarding.network_normalize import normalize_nsg

    row = topology_comparison_scenario()["network_security_groups"][0]
    base = {
        "id": row["id"],
        "name": row["name"],
        "tenantId": row["tenantId"],
        "subscriptionId": row["subscriptionId"],
        "sourceSystem": "arg:Resources",
        "sourceId": row["id"],
        "createdTimestamp": OBSERVED_AT,
        "lastObservedTimestamp": OBSERVED_AT,
        "schemaVersion": "1.0.0",
    }
    _, rules = normalize_nsg(base, row, OBSERVED_AT)
    return rules


__all__ = [
    "NSG_ID",
    "OBSERVED_AT",
    "SUBNET_ID",
    "VNET_ID",
    "nsg_rule_rows",
    "topology_comparison_scenario",
]
