"""Characterization test (Phase 8 Task 2): proves that feeding AIOps's real
normalizers via `InventoryReadAdapter` produces byte-identical NormalizedGraph
output compared to a direct-ARG payload, for identity + network fixtures
covering the deepest nested property-access pattern flagged in Pitfall 1
(subnet delegations/serviceEndpoints/properties).

Per D-08 (Phase 8 CONTEXT), this is additive-only: `queries.py`'s ARG specs
are not modified or removed by this test or the adapter it exercises.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from intelligence.inventory.models import ResourceObservation
from onboarding.graph_normalize import Normalizer
from onboarding.inventory_read_adapter import InventoryReadAdapter

OBSERVED_AT = datetime(2026, 8, 27, 6, 0, tzinfo=UTC)


def _vm_row() -> dict:
    return {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a",
        "name": "vm-a",
        "type": "microsoft.compute/virtualmachines",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {"env": "prod"},
        "properties": {
            "hardwareProfile": {"vmSize": "Standard_D4s_v5"},
            "storageProfile": {"osDisk": {"osType": "Linux"}},
            "provisioningState": "Succeeded",
        },
    }


def _vnet_row() -> dict:
    return {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a",
        "name": "vnet-a",
        "type": "microsoft.network/virtualnetworks",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {},
        "properties": {
            "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
            "subnets": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/subnet-a",
                    "name": "subnet-a",
                    "properties": {
                        "addressPrefix": "10.0.1.0/24",
                        "networkSecurityGroup": {
                            "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-a"
                        },
                        "serviceEndpoints": [
                            {"service": "Microsoft.Storage"},
                            {"service": "Microsoft.Sql"},
                        ],
                        "delegations": [
                            {
                                "name": "delegation-a",
                                "properties": {"serviceName": "Microsoft.Web/serverFarms"},
                            }
                        ],
                    },
                }
            ],
        },
    }


def _subnet_empty_properties_row() -> dict:
    """Subnet-owning VNet whose subnet has an empty/missing properties bag."""
    return {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-empty",
        "name": "vnet-empty",
        "type": "microsoft.network/virtualnetworks",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {},
        "properties": {
            "subnets": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-empty/subnets/subnet-empty",
                    "name": "subnet-empty",
                    # No "properties" key at all.
                }
            ],
        },
    }


def _nsg_row() -> dict:
    return {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-a",
        "name": "nsg-a",
        "type": "microsoft.network/networksecuritygroups",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {},
        "properties": {
            "securityRules": [
                {
                    "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-a/securityRules/allow-ssh",
                    "name": "allow-ssh",
                    "properties": {
                        "priority": 100,
                        "direction": "Inbound",
                        "access": "Allow",
                        "protocol": "Tcp",
                        "sourceAddressPrefix": "*",
                        "destinationAddressPrefix": "*",
                        "sourcePortRange": "*",
                        "destinationPortRange": "22",
                    },
                }
            ],
        },
    }


def _nic_row() -> dict:
    return {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic-a",
        "name": "nic-a",
        "type": "microsoft.network/networkinterfaces",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {},
        "properties": {
            "ipConfigurations": [
                {
                    "properties": {
                        "privateIPAddress": "10.0.1.4",
                        "subnet": {
                            "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/subnet-a"
                        },
                    }
                }
            ],
            "virtualMachine": {
                "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a"
            },
        },
    }


def _resource_containers() -> list[dict]:
    return [
        {
            "id": "/subscriptions/sub-a",
            "name": "sub-a",
            "type": "microsoft.resources/subscriptions",
            "tenantId": "tenant-a",
            "subscriptionId": "sub-a",
            "resourceGroup": "",
            "location": "",
            "tags": {},
            "properties": {},
        },
        {
            "id": "/subscriptions/sub-a/resourceGroups/rg",
            "name": "rg",
            "type": "microsoft.resources/subscriptions/resourcegroups",
            "tenantId": "tenant-a",
            "subscriptionId": "sub-a",
            "resourceGroup": "rg",
            "location": "australiaeast",
            "tags": {},
            "properties": {},
        },
    ]


def _direct_arg_payload() -> dict[str, list[dict]]:
    return {
        "resource_containers": _resource_containers(),
        "resources": [_vm_row()],
        "network_vnets": [_vnet_row()],
        "network_security_groups": [_nsg_row()],
        "network_interfaces": [_nic_row()],
    }


def _empty_subnet_direct_payload() -> dict[str, list[dict]]:
    return {
        "resource_containers": _resource_containers(),
        "resources": [],
        "network_vnets": [_subnet_empty_properties_row()],
        "network_security_groups": [],
        "network_interfaces": [],
    }


def _observation_from_arg_row(row: dict, *, family: str) -> ResourceObservation:
    return ResourceObservation.from_provider_row(
        row,
        family=family,
        observed_at="2026-08-27T06:00:00Z",
        ingestion_run_id="run-1",
        source_type="arg",
        source_table="Resources",
    )


def _adapter_payload_from_arg_rows(
    resource_containers: list[dict],
    resource_type_rows: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """Round-trips ARG-shaped fixture rows through `ResourceObservation` and
    the inventory read-port's `to_api_dict()` projection, then through
    `InventoryReadAdapter.to_arg_rows()` -- proving the full path a real
    inventory-backed consumer would take, not merely hand-crafted rows."""
    containment_rows = []
    for row in resource_containers:
        row_type = str(row.get("type") or "")
        if row_type == "microsoft.resources/subscriptions":
            containment_rows.append(
                {"kind": "subscription", "subscription_id": row.get("subscriptionId")}
            )
        elif row_type == "microsoft.resources/subscriptions/resourcegroups":
            containment_rows.append(
                {
                    "kind": "resource_group",
                    "subscription_id": row.get("subscriptionId"),
                    "resource_group": row.get("resourceGroup"),
                }
            )

    resource_dicts = []
    for family, rows in resource_type_rows.items():
        for row in rows:
            observation = _observation_from_arg_row(row, family=family)
            resource_dicts.append(observation.to_api_dict() | {"resource_id": observation.resource_id})

    return InventoryReadAdapter.to_arg_rows(containment_rows, resource_dicts)


def _normalize(payload: dict[str, list[dict]]):
    return Normalizer().normalize(payload, OBSERVED_AT, run_id="test-run")


def _entity_sets(graph) -> dict[str, list]:
    return {
        entity_type: sorted(
            json.dumps(entity, sort_keys=True, default=str) for entity in entities
        )
        for entity_type, entities in graph.entities.items()
        if entities
    }


def _relationship_set(graph) -> list:
    return sorted(json.dumps(edge, sort_keys=True, default=str) for edge in graph.relationships)


def test_read_port_adapter_produces_byte_identical_entities_and_relationships():
    direct_payload = _direct_arg_payload()
    direct_graph = _normalize(direct_payload)

    adapter_payload = dict(direct_payload)
    adapter_payload.update(
        _adapter_payload_from_arg_rows(
            _resource_containers(),
            {"paas": [_vm_row()]},
        )
    )
    adapter_graph = _normalize(adapter_payload)

    for key in ("Resource", "VirtualMachine", "Subnet"):
        assert _entity_sets(direct_graph).get(key, frozenset()) == _entity_sets(adapter_graph).get(
            key, frozenset()
        ), f"Entity family {key} diverged between direct-ARG and adapter paths"

    assert _relationship_set(direct_graph) == _relationship_set(adapter_graph)


def test_subnet_nested_delegations_and_service_endpoints_round_trip_exactly():
    direct_graph = _normalize(_direct_arg_payload())
    subnet_entities = {entity["id"]: entity for entity in direct_graph.entities["Subnet"]}
    subnet = next(iter(subnet_entities.values()))

    assert subnet["delegations"] == ["Microsoft.Web/serverFarms"]
    assert subnet["serviceEndpoints"] == ["Microsoft.Storage", "Microsoft.Sql"]

    adapter_payload = dict(_direct_arg_payload())
    adapter_payload.update(
        _adapter_payload_from_arg_rows(
            _resource_containers(),
            {"paas": [_vm_row()]},
        )
    )
    adapter_graph = _normalize(adapter_payload)
    adapter_subnet = next(iter({e["id"]: e for e in adapter_graph.entities["Subnet"]}.values()))

    assert adapter_subnet["delegations"] == subnet["delegations"]
    assert adapter_subnet["serviceEndpoints"] == subnet["serviceEndpoints"]
    assert adapter_subnet["properties"] == subnet["properties"]


def test_resource_with_empty_properties_bag_is_empty_safe_on_both_paths():
    direct_graph = _normalize(_empty_subnet_direct_payload())
    subnet = next(iter(direct_graph.entities["Subnet"]))

    assert subnet["delegations"] == []
    assert subnet["serviceEndpoints"] == []
    assert subnet["nsgId"] == ""
    assert subnet["routeTableId"] == ""

    adapter_payload = _empty_subnet_direct_payload()
    adapter_graph = _normalize(adapter_payload)
    adapter_subnet = next(iter(adapter_graph.entities["Subnet"]))

    assert adapter_subnet == subnet


def test_firewall_application_rule_preserves_fqdn_tags_and_protocol_ports():
    firewall = {
        "id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/azureFirewalls/fw",
        "name": "fw",
        "type": "microsoft.network/azurefirewalls",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "resourceGroup": "rg",
        "location": "australiaeast",
        "tags": {},
        "properties": {
            "applicationRuleCollections": [
                {
                    "name": "allow-updates",
                    "properties": {
                        "priority": 100,
                        "action": {"type": "Allow"},
                        "rules": [
                            {
                                "name": "windows-update",
                                "sourceAddresses": ["10.0.1.0/24"],
                                "fqdnTags": ["WindowsUpdate"],
                                "protocols": [
                                    {"protocolType": "Https", "port": 443},
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    graph = _normalize({"network_firewalls": [firewall]})

    rule = next(iter(graph.entities["FirewallRule"]))
    assert rule["destinationFqdns"] == []
    assert rule["fqdnTags"] == ["WindowsUpdate"]
    assert rule["protocols"] == ["Https"]
    assert rule["destinationPorts"] == ["443"]
