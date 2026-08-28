"""Guards the network layer's ontology and Fabric registration.

The normalizer, the ontology entity classifier and the Fabric dataset mapper
are three independent lists that must agree. Nothing fails loudly when they
drift -- an unregistered entity type simply never reaches a Delta table -- so
these tests assert the agreement explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fabric.dataset_mapper import ONTOLOGY_ENTITY_TYPES, ONTOLOGY_RELATIONSHIP_TYPES
from onboarding.graph_normalize import Normalizer
from onboarding.network_normalize import NETWORK_ENTITY_TYPES, normalize_nic
from ontology.entity_builder import RESOURCE_ENTITY_TYPES

OBSERVED = datetime(2026, 8, 1, tzinfo=UTC)

SUB = "sub-1"
RG = f"/subscriptions/{SUB}/resourcegroups/rg-net"
VNET_ID = f"{RG}/providers/microsoft.network/virtualnetworks/vnet-hub"
PEER_VNET_ID = f"{RG}/providers/microsoft.network/virtualnetworks/vnet-spoke"
SUBNET_ID = f"{VNET_ID}/subnets/app"
NSG_ID = f"{RG}/providers/microsoft.network/networksecuritygroups/nsg-app"
RT_ID = f"{RG}/providers/microsoft.network/routetables/rt-app"
NIC_ID = f"{RG}/providers/microsoft.network/networkinterfaces/nic-1"
VM_ID = f"{RG}/providers/microsoft.compute/virtualmachines/vm-1"
FW_ID = f"{RG}/providers/microsoft.network/azurefirewalls/fw-hub"
POLICY_ID = f"{RG}/providers/microsoft.network/firewallpolicies/fw-policy"
PE_ID = f"{RG}/providers/microsoft.network/privateendpoints/pe-sql"
SQL_ID = f"{RG}/providers/microsoft.sql/servers/sql-1"
ZONE_ID = f"{RG}/providers/microsoft.network/privatednszones/privatelink.database.windows.net"
GW_ID = f"{RG}/providers/microsoft.network/virtualnetworkgateways/vpn-hub"
NAT_ID = f"{RG}/providers/microsoft.network/natgateways/nat-1"
LB_ID = f"{RG}/providers/microsoft.network/loadbalancers/lb-app"


def _row(resource_id: str, name: str, arm_type: str, properties: dict) -> dict:
    return {
        "id": resource_id,
        "name": name,
        "type": arm_type,
        "subscriptionId": SUB,
        "resourceGroup": "rg-net",
        "tenantId": "tenant-1",
        "location": "eastus",
        "tags": {},
        "properties": properties,
    }


def _full_payload() -> dict:
    """An ARG payload exercising every network entity type and predicate."""
    return {
        "network_vnets": [
            _row(
                VNET_ID,
                "vnet-hub",
                "microsoft.network/virtualNetworks",
                {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {
                            "id": SUBNET_ID,
                            "name": "app",
                            "properties": {
                                "addressPrefix": "10.0.1.0/24",
                                "networkSecurityGroup": {"id": NSG_ID},
                                "routeTable": {"id": RT_ID},
                                "natGateway": {"id": NAT_ID},
                            },
                        }
                    ],
                    "virtualNetworkPeerings": [
                        {
                            "id": f"{VNET_ID}/virtualnetworkpeerings/to-spoke",
                            "name": "to-spoke",
                            "properties": {
                                "remoteVirtualNetwork": {"id": PEER_VNET_ID},
                                "peeringState": "Connected",
                            },
                        }
                    ],
                },
            ),
            _row(
                PEER_VNET_ID,
                "vnet-spoke",
                "microsoft.network/virtualNetworks",
                {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}},
            ),
        ],
        "network_security_groups": [
            _row(
                NSG_ID,
                "nsg-app",
                "microsoft.network/networkSecurityGroups",
                {
                    "securityRules": [
                        {
                            "id": f"{NSG_ID}/securityrules/allow-https",
                            "name": "allow-https",
                            "properties": {
                                "priority": 100,
                                "direction": "Inbound",
                                "access": "Allow",
                                "protocol": "Tcp",
                                "sourceAddressPrefix": "10.0.0.0/8",
                                "destinationAddressPrefix": "*",
                                "destinationPortRange": "443",
                            },
                        }
                    ]
                },
            )
        ],
        "network_route_tables": [
            _row(
                RT_ID,
                "rt-app",
                "microsoft.network/routeTables",
                {
                    "routes": [
                        {
                            "id": f"{RT_ID}/routes/default",
                            "name": "default",
                            "properties": {
                                "addressPrefix": "0.0.0.0/0",
                                "nextHopType": "VirtualAppliance",
                                "nextHopIpAddress": "10.0.0.4",
                            },
                        }
                    ]
                },
            )
        ],
        "network_interfaces": [
            _row(
                NIC_ID,
                "nic-1",
                "microsoft.network/networkInterfaces",
                {
                    "networkSecurityGroup": {"id": NSG_ID},
                    "virtualMachine": {"id": VM_ID},
                    "ipConfigurations": [
                        {
                            "name": "ipconfig1",
                            "properties": {
                                "privateIPAddress": "10.0.1.4",
                                "subnet": {"id": SUBNET_ID},
                            },
                        }
                    ],
                },
            )
        ],
        "network_firewalls": [
            _row(
                FW_ID,
                "fw-hub",
                "microsoft.network/azureFirewalls",
                {
                    "firewallPolicy": {"id": POLICY_ID},
                    "ipConfigurations": [
                        {
                            "name": "cfg",
                            "properties": {
                                "subnet": {"id": SUBNET_ID},
                                "privateIPAddress": "10.0.0.4",
                            },
                        }
                    ],
                },
            )
        ],
        "network_firewall_policies": [
            _row(
                POLICY_ID,
                "fw-policy",
                "microsoft.network/firewallPolicies",
                {"threatIntelMode": "Alert"},
            ),
            _row(
                f"{POLICY_ID}/rulecollectiongroups/default",
                "default",
                "microsoft.network/firewallPolicies/ruleCollectionGroups",
                {
                    "priority": 100,
                    "ruleCollections": [
                        {
                            "name": "allow-web",
                            "priority": 200,
                            "action": {"type": "Allow"},
                            "rules": [
                                {
                                    "name": "web",
                                    "ruleType": "NetworkRule",
                                    "sourceAddresses": ["10.0.0.0/8"],
                                    "destinationAddresses": ["*"],
                                    "destinationPorts": ["443"],
                                    "ipProtocols": ["TCP"],
                                }
                            ],
                        }
                    ],
                },
            ),
        ],
        "network_private_endpoints": [
            _row(
                PE_ID,
                "pe-sql",
                "microsoft.network/privateEndpoints",
                {
                    "subnet": {"id": SUBNET_ID},
                    "privateLinkServiceConnections": [
                        {"properties": {"privateLinkServiceId": SQL_ID}}
                    ],
                },
            )
        ],
        "network_private_dns_zones": [
            _row(
                ZONE_ID,
                "privatelink.database.windows.net",
                "microsoft.network/privateDnsZones",
                {},
            ),
            _row(
                f"{ZONE_ID}/virtualnetworklinks/hub-link",
                "hub-link",
                "microsoft.network/privateDnsZones/virtualNetworkLinks",
                {"virtualNetwork": {"id": VNET_ID}},
            ),
        ],
        "network_gateways": [
            _row(
                GW_ID,
                "vpn-hub",
                "microsoft.network/virtualNetworkGateways",
                {
                    "gatewayType": "Vpn",
                    "ipConfigurations": [{"properties": {"subnet": {"id": SUBNET_ID}}}],
                },
            ),
            _row(NAT_ID, "nat-1", "microsoft.network/natGateways", {}),
        ],
        "network_load_balancers": [
            _row(
                LB_ID,
                "lb-app",
                "microsoft.network/loadBalancers",
                {
                    "frontendIPConfigurations": [
                        {"name": "fe", "properties": {"subnet": {"id": SUBNET_ID}}}
                    ],
                    "backendAddressPools": [
                        {
                            "name": "pool",
                            "properties": {
                                "backendIPConfigurations": [{"id": f"{NIC_ID}/ipconfigurations/ipconfig1"}]
                            },
                        }
                    ],
                },
            )
        ],
    }


@pytest.fixture(scope="module")
def graph():
    return Normalizer().normalize(_full_payload(), OBSERVED)


@pytest.fixture(scope="module")
def emitted_types(graph) -> set[str]:
    return {name for name, rows in graph.entities.items() if rows}


@pytest.fixture(scope="module")
def emitted_triples(graph) -> set[tuple[str, str, str]]:
    index = {}
    for name, rows in graph.entities.items():
        for row in rows:
            index[row["id"]] = name
    triples = set()
    for edge in graph.relationships:
        subject = index.get(edge["subjectId"])
        obj = index.get(edge["objectId"])
        if subject and obj:
            triples.add((subject, edge["predicate"], obj))
    return triples


class TestPayloadCoverage:
    def test_payload_exercises_every_network_entity_type(self, emitted_types):
        """The fixture must be complete or the drift tests prove nothing."""
        assert set(NETWORK_ENTITY_TYPES) <= emitted_types


class TestEntityRegistration:
    def test_every_network_entity_type_is_registered_for_fabric(self):
        missing = set(NETWORK_ENTITY_TYPES) - set(ONTOLOGY_ENTITY_TYPES)
        assert not missing, f"unregistered in dataset_mapper: {sorted(missing)}"

    def test_every_emitted_entity_type_is_registered_for_fabric(self, emitted_types):
        missing = emitted_types - set(ONTOLOGY_ENTITY_TYPES)
        assert not missing, f"unregistered in dataset_mapper: {sorted(missing)}"

    def test_registered_entity_types_are_unique(self):
        assert len(ONTOLOGY_ENTITY_TYPES) == len(set(ONTOLOGY_ENTITY_TYPES))


class TestRelationshipRegistration:
    def test_every_emitted_triple_is_registered(self, emitted_triples):
        missing = emitted_triples - set(ONTOLOGY_RELATIONSHIP_TYPES)
        assert not missing, f"unregistered triples: {sorted(missing)}"

    def test_registered_triples_are_unique(self):
        assert len(ONTOLOGY_RELATIONSHIP_TYPES) == len(set(ONTOLOGY_RELATIONSHIP_TYPES))

    @pytest.mark.parametrize(
        "triple",
        [
            ("VNet", "contains", "Subnet"),
            ("VNet", "hasPeering", "VNetPeering"),
            ("VNetPeering", "peersWith", "VNet"),
            ("Subnet", "protectedBy", "NetworkSecurityGroup"),
            ("Subnet", "routedBy", "RouteTable"),
            ("NetworkSecurityGroup", "hasRule", "NetworkSecurityRule"),
            ("RouteTable", "hasRoute", "Route"),
            ("AzureFirewall", "enforcesPolicy", "FirewallPolicy"),
            ("FirewallPolicy", "hasRuleCollection", "FirewallRuleCollection"),
            ("FirewallRuleCollection", "hasRule", "FirewallRule"),
            ("PrivateDnsZone", "resolvesFor", "VNet"),
        ],
        ids=lambda triple: "-".join(triple),
    )
    def test_core_topology_triple_is_emitted(self, emitted_triples, triple):
        """These edges are what the topology builder traverses."""
        assert triple in emitted_triples


class TestResourceClassification:
    def test_top_level_network_types_classify_to_network_entities(self):
        for arm_type in (
            "microsoft.network/virtualnetworks",
            "microsoft.network/networksecuritygroups",
            "microsoft.network/azurefirewalls",
            "microsoft.network/privateendpoints",
        ):
            assert arm_type in RESOURCE_ENTITY_TYPES

    def test_classified_network_types_are_registered_entities(self):
        network = {
            value
            for key, value in RESOURCE_ENTITY_TYPES.items()
            if key.startswith("microsoft.network/")
        }
        assert network <= set(ONTOLOGY_ENTITY_TYPES)

    def test_sub_resources_do_not_inherit_the_parent_arm_type(self, graph):
        """A subnet is not a virtualNetwork.

        Sub-resources inherit their parent's business context but must not
        inherit its ``resourceType`` -- the ontology classifier keys on that
        field and would relabel every subnet as its parent VNet.
        """
        for entity_type in ("Subnet", "VNetPeering", "NetworkSecurityRule", "Route"):
            for row in graph.entities[entity_type]:
                assert not row.get("resourceType"), entity_type

    def test_sub_resources_still_inherit_business_context(self, graph):
        for row in graph.entities["Subnet"]:
            assert row["subscriptionId"] == SUB


class TestNicAttachment:
    """A NIC is only useful in a topology once it points at what it serves."""

    def test_vm_nic_attaches_to_its_virtual_machine(self):
        nic = normalize_nic({}, {"properties": {"virtualMachine": {"id": VM_ID}}}, OBSERVED)
        assert nic["attachedResourceId"] == VM_ID

    def test_private_endpoint_nic_attaches_to_its_endpoint(self):
        """A private endpoint NIC has no VM, so it would otherwise look orphaned."""
        endpoint_id = f"{RG}/providers/microsoft.network/privateendpoints/pe-1"
        nic = normalize_nic({}, {"properties": {"privateEndpoint": {"id": endpoint_id}}}, OBSERVED)
        assert nic["attachedResourceId"] == endpoint_id

    def test_unattached_nic_reports_no_workload(self):
        assert normalize_nic({}, {"properties": {}}, OBSERVED)["attachedResourceId"] == ""
