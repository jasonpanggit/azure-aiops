"""Network topology data model.

Every resource the hub-spoke and traffic-flow analyses need, as frozen
dataclasses with ``from_mapping``/``to_dict`` in the same style as
``ontology.subscription_connection``. Each entity carries the
``connection_id`` that ingested it, so topology stitched across
independently onboarded subscriptions never loses provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .addressing import AddressSpec, PortSpec, ProtocolSpec

#: Entity type names published to the ontology.
NETWORK_ENTITY_TYPES: tuple[str, ...] = (
    "VNet",
    "Subnet",
    "NetworkInterface",
    "PrivateEndpoint",
    "PrivateDnsZone",
    "NetworkSecurityGroup",
    "NetworkSecurityRule",
    "RouteTable",
    "Route",
    "VNetPeering",
    "AzureFirewall",
    "FirewallPolicy",
    "FirewallRuleCollection",
    "FirewallRule",
    "ApplicationGateway",
    "LoadBalancer",
    "VpnGateway",
    "ExpressRouteGateway",
    "NatGateway",
    "Bastion",
    "DnsResolver",
    "SharedService",
)

#: ARM resource types that should normally be reached through Private Link,
#: mapped to a human-facing service name. These arrive from ARG under the
#: ontology's generic ``Resource`` entity type, so they are matched by ARM
#: type rather than entity type.
PRIVATE_LINK_RESOURCE_TYPES: dict[str, str] = {
    "microsoft.storage/storageaccounts": "Storage",
    "microsoft.keyvault/vaults": "Key Vault",
    "microsoft.sql/servers": "Azure SQL",
    "microsoft.dbforpostgresql/servers": "PostgreSQL",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL",
    "microsoft.dbformysql/servers": "MySQL",
    "microsoft.dbformysql/flexibleservers": "MySQL",
    "microsoft.documentdb/databaseaccounts": "Cosmos DB",
    "microsoft.containerregistry/registries": "Container Registry",
    "microsoft.servicebus/namespaces": "Service Bus",
    "microsoft.eventhub/namespaces": "Event Hubs",
    "microsoft.web/sites": "App Service",
    "microsoft.cognitiveservices/accounts": "Azure AI Services",
    "microsoft.fabric/capacities": "Microsoft Fabric",
}

# Fabric private-link controls apply to a tenant or workspace, not to an
# individual capacity resource. Keep the normalized ARM type and scope value
# shared by topology projection and gap analysis so they cannot drift.
FABRIC_CAPACITY_RESOURCE_TYPE = "microsoft.fabric/capacities"
FABRIC_PRIVATE_LINK_SCOPE = "tenant_or_workspace"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).casefold()


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    return ()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first(source: Any, *keys: str, default: Any = None) -> Any:
    """Reads the first present key, accepting snake_case and camelCase."""
    if not isinstance(source, dict):
        return default
    for key in keys:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return default


@dataclass(frozen=True)
class NetworkResource:
    """Fields shared by every network entity."""

    resource_id: str
    name: str
    entity_type: str
    subscription_id: str = ""
    resource_group: str = ""
    location: str = ""
    connection_id: str = ""
    environment: str = ""
    business_service: str = ""
    application: str = ""
    owner: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    support_team: str = field(default="", kw_only=True)
    region: str = field(default="", kw_only=True)
    criticality: str = field(default="", kw_only=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _lower(self.resource_id))
        object.__setattr__(self, "name", _text(self.name))
        object.__setattr__(self, "subscription_id", _lower(self.subscription_id))
        object.__setattr__(self, "resource_group", _lower(self.resource_group))
        object.__setattr__(self, "location", _lower(self.location))
        object.__setattr__(self, "connection_id", _text(self.connection_id))
        object.__setattr__(self, "support_team", _text(self.support_team))
        object.__setattr__(self, "region", _lower(self.region or self.location))
        object.__setattr__(self, "criticality", _text(self.criticality))
        object.__setattr__(self, "tags", {str(k): str(v) for k, v in _mapping(self.tags).items()})
        object.__setattr__(self, "properties", _mapping(self.properties))

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "subscription_id": self.subscription_id,
            "resource_group": self.resource_group,
            "location": self.location,
            "connection_id": self.connection_id,
            "environment": self.environment,
            "business_service": self.business_service,
            "application": self.application,
            "owner": self.owner,
            "support_team": self.support_team,
            "region": self.region,
            "criticality": self.criticality,
            "tags": dict(self.tags),
        }


@dataclass(frozen=True)
class Subnet(NetworkResource):
    entity_type: str = "Subnet"
    vnet_id: str = ""
    address_prefixes: tuple[str, ...] = ()
    nsg_id: str = ""
    route_table_id: str = ""
    nat_gateway_id: str = ""
    private_endpoint_ids: tuple[str, ...] = ()
    service_endpoints: tuple[str, ...] = ()
    delegations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "vnet_id", _lower(self.vnet_id))
        object.__setattr__(self, "nsg_id", _lower(self.nsg_id))
        object.__setattr__(self, "route_table_id", _lower(self.route_table_id))
        object.__setattr__(self, "nat_gateway_id", _lower(self.nat_gateway_id))
        object.__setattr__(self, "address_prefixes", _tuple(self.address_prefixes))
        object.__setattr__(
            self,
            "private_endpoint_ids",
            tuple(_lower(item) for item in _tuple(self.private_endpoint_ids)),
        )
        object.__setattr__(self, "service_endpoints", _tuple(self.service_endpoints))
        object.__setattr__(self, "delegations", _tuple(self.delegations))

    @property
    def is_gateway_subnet(self) -> bool:
        return self.name.casefold() in {"gatewaysubnet", "azurefirewallsubnet", "azurebastionsubnet"}

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "vnet_id": self.vnet_id,
            "address_prefixes": list(self.address_prefixes),
            "nsg_id": self.nsg_id,
            "route_table_id": self.route_table_id,
            "nat_gateway_id": self.nat_gateway_id,
            "private_endpoint_ids": list(self.private_endpoint_ids),
            "service_endpoints": list(self.service_endpoints),
        }


@dataclass(frozen=True)
class VNet(NetworkResource):
    entity_type: str = "VNet"
    address_spaces: tuple[str, ...] = ()
    subnet_ids: tuple[str, ...] = ()
    peering_ids: tuple[str, ...] = ()
    dns_servers: tuple[str, ...] = ()
    ddos_protection_enabled: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "address_spaces", _tuple(self.address_spaces))
        object.__setattr__(self, "subnet_ids", tuple(_lower(x) for x in _tuple(self.subnet_ids)))
        object.__setattr__(self, "peering_ids", tuple(_lower(x) for x in _tuple(self.peering_ids)))
        object.__setattr__(self, "dns_servers", _tuple(self.dns_servers))

    @property
    def uses_custom_dns(self) -> bool:
        return bool(self.dns_servers)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "address_spaces": list(self.address_spaces),
            "subnet_ids": list(self.subnet_ids),
            "peering_ids": list(self.peering_ids),
            "dns_servers": list(self.dns_servers),
            "ddos_protection_enabled": self.ddos_protection_enabled,
        }


@dataclass(frozen=True)
class NetworkInterface(NetworkResource):
    entity_type: str = "NetworkInterface"
    subnet_id: str = ""
    private_ips: tuple[str, ...] = ()
    public_ips: tuple[str, ...] = ()
    nsg_id: str = ""
    attached_resource_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "subnet_id", _lower(self.subnet_id))
        object.__setattr__(self, "nsg_id", _lower(self.nsg_id))
        object.__setattr__(self, "attached_resource_id", _lower(self.attached_resource_id))
        object.__setattr__(self, "private_ips", _tuple(self.private_ips))
        object.__setattr__(self, "public_ips", _tuple(self.public_ips))

    @property
    def has_public_ip(self) -> bool:
        return bool(self.public_ips)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "subnet_id": self.subnet_id,
            "private_ips": list(self.private_ips),
            "public_ips": list(self.public_ips),
            "nsg_id": self.nsg_id,
            "attached_resource_id": self.attached_resource_id,
        }


@dataclass(frozen=True)
class NetworkSecurityRule(NetworkResource):
    """A single NSG rule, with parsed address/port/protocol specs."""

    entity_type: str = "NetworkSecurityRule"
    nsg_id: str = ""
    priority: int = 0
    direction: str = "Inbound"
    access: str = "Allow"
    protocol: str = "*"
    source_address: str = "*"
    destination_address: str = "*"
    source_port: str = "*"
    destination_port: str = "*"
    description: str = ""
    is_default: bool = False
    configuration_observed: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "nsg_id", _lower(self.nsg_id))
        object.__setattr__(self, "direction", _text(self.direction) or "Inbound")
        object.__setattr__(self, "access", _text(self.access) or "Allow")

    @property
    def source_spec(self) -> AddressSpec:
        return AddressSpec.parse(self.source_address)

    @property
    def destination_spec(self) -> AddressSpec:
        return AddressSpec.parse(self.destination_address)

    @property
    def destination_port_spec(self) -> PortSpec:
        return PortSpec.parse(self.destination_port)

    @property
    def source_port_spec(self) -> PortSpec:
        return PortSpec.parse(self.source_port)

    @property
    def protocol_spec(self) -> ProtocolSpec:
        return ProtocolSpec.parse(self.protocol)

    @property
    def is_allow(self) -> bool:
        return self.access.casefold() == "allow"

    @property
    def is_inbound(self) -> bool:
        return self.direction.casefold() == "inbound"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "nsg_id": self.nsg_id,
            "priority": self.priority,
            "direction": self.direction,
            "access": self.access,
            "protocol": self.protocol,
            "source_address": self.source_address,
            "destination_address": self.destination_address,
            "source_port": self.source_port,
            "destination_port": self.destination_port,
            "description": self.description,
            "is_default": self.is_default,
        }


#: Azure's implicit default security rules, applied to every NSG.
#: Source: Microsoft Learn, "Default security rules".
DEFAULT_SECURITY_RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "AllowVnetInBound",
        "priority": 65000,
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "*",
        "source_address": "VirtualNetwork",
        "destination_address": "VirtualNetwork",
    },
    {
        "name": "AllowAzureLoadBalancerInBound",
        "priority": 65001,
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "*",
        "source_address": "AzureLoadBalancer",
        "destination_address": "*",
    },
    {
        "name": "DenyAllInBound",
        "priority": 65500,
        "direction": "Inbound",
        "access": "Deny",
        "protocol": "*",
        "source_address": "*",
        "destination_address": "*",
    },
    {
        "name": "AllowVnetOutBound",
        "priority": 65000,
        "direction": "Outbound",
        "access": "Allow",
        "protocol": "*",
        "source_address": "VirtualNetwork",
        "destination_address": "VirtualNetwork",
    },
    {
        "name": "AllowInternetOutBound",
        "priority": 65001,
        "direction": "Outbound",
        "access": "Allow",
        "protocol": "*",
        "source_address": "*",
        "destination_address": "Internet",
    },
    {
        "name": "DenyAllOutBound",
        "priority": 65500,
        "direction": "Outbound",
        "access": "Deny",
        "protocol": "*",
        "source_address": "*",
        "destination_address": "*",
    },
)


def _synthesize_default_rules(nsg_id: str) -> tuple[NetworkSecurityRule, ...]:
    return tuple(
        NetworkSecurityRule(
            resource_id=f"{nsg_id}/defaultsecurityrules/{spec['name'].casefold()}",
            name=str(spec["name"]),
            nsg_id=nsg_id,
            is_default=True,
            description="Synthesized Azure default rule (not observed in ingested data)",
            **{k: v for k, v in spec.items() if k != "name"},
        )
        for spec in DEFAULT_SECURITY_RULES
    )


@dataclass(frozen=True)
class NetworkSecurityGroup(NetworkResource):
    entity_type: str = "NetworkSecurityGroup"
    rules: tuple[NetworkSecurityRule, ...] = ()
    subnet_ids: tuple[str, ...] = ()
    nic_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "subnet_ids", tuple(_lower(x) for x in _tuple(self.subnet_ids)))
        object.__setattr__(self, "nic_ids", tuple(_lower(x) for x in _tuple(self.nic_ids)))
        object.__setattr__(self, "rules", tuple(self.rules))

    @property
    def has_observed_defaults(self) -> bool:
        return any(rule.is_default for rule in self.rules)

    def effective_rules(self) -> tuple[NetworkSecurityRule, ...]:
        """Observed rules plus Azure's implicit defaults when they were not ingested.

        Azure applies the default rules to every NSG whether or not a query
        projected ``defaultSecurityRules``. Evaluating without them would
        report every unmatched flow as denied — including outbound traffic
        that Azure actually permits — so they are synthesized when absent.
        """
        if self.has_observed_defaults:
            return self.rules
        return self.rules + _synthesize_default_rules(self.resource_id)

    def ordered_rules(self, *, direction: str = "") -> tuple[NetworkSecurityRule, ...]:
        """Rules in Azure evaluation order (ascending priority)."""
        selected = [
            rule
            for rule in self.effective_rules()
            if not direction or rule.direction.casefold() == direction.casefold()
        ]
        return tuple(sorted(selected, key=lambda rule: (rule.priority, rule.name)))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "subnet_ids": list(self.subnet_ids),
            "nic_ids": list(self.nic_ids),
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class Route(NetworkResource):
    """A user-defined route (UDR) inside a route table."""

    entity_type: str = "Route"
    route_table_id: str = ""
    address_prefix: str = ""
    next_hop_type: str = ""
    next_hop_ip: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "route_table_id", _lower(self.route_table_id))

    @property
    def is_default_route(self) -> bool:
        return self.address_prefix.strip() in {"0.0.0.0/0", "::/0"}

    @property
    def forces_appliance(self) -> bool:
        return self.next_hop_type.casefold() in {"virtualappliance", "virtualnetworkgateway"}

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "route_table_id": self.route_table_id,
            "address_prefix": self.address_prefix,
            "next_hop_type": self.next_hop_type,
            "next_hop_ip": self.next_hop_ip,
        }


@dataclass(frozen=True)
class RouteTable(NetworkResource):
    entity_type: str = "RouteTable"
    routes: tuple[Route, ...] = ()
    subnet_ids: tuple[str, ...] = ()
    disable_bgp_route_propagation: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "subnet_ids", tuple(_lower(x) for x in _tuple(self.subnet_ids)))
        object.__setattr__(self, "routes", tuple(self.routes))

    @property
    def default_route(self) -> Route | None:
        for route in self.routes:
            if route.is_default_route:
                return route
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "subnet_ids": list(self.subnet_ids),
            "disable_bgp_route_propagation": self.disable_bgp_route_propagation,
            "routes": [route.to_dict() for route in self.routes],
        }


@dataclass(frozen=True)
class VNetPeering(NetworkResource):
    entity_type: str = "VNetPeering"
    local_vnet_id: str = ""
    remote_vnet_id: str = ""
    peering_state: str = ""
    allow_forwarded_traffic: bool = False
    allow_gateway_transit: bool = False
    use_remote_gateways: bool = False
    allow_virtual_network_access: bool = True
    gateway_flags_observed: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "local_vnet_id", _lower(self.local_vnet_id))
        object.__setattr__(self, "remote_vnet_id", _lower(self.remote_vnet_id))

    @property
    def is_connected(self) -> bool:
        return self.peering_state.casefold() == "connected"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "local_vnet_id": self.local_vnet_id,
            "remote_vnet_id": self.remote_vnet_id,
            "peering_state": self.peering_state,
            "allow_forwarded_traffic": self.allow_forwarded_traffic,
            "allow_gateway_transit": self.allow_gateway_transit,
            "use_remote_gateways": self.use_remote_gateways,
            "allow_virtual_network_access": self.allow_virtual_network_access,
        }


@dataclass(frozen=True)
class FirewallRule(NetworkResource):
    entity_type: str = "FirewallRule"
    collection_id: str = ""
    rule_type: str = "NetworkRule"
    action: str = "Allow"
    protocols: tuple[str, ...] = ()
    source_addresses: tuple[str, ...] = ()
    destination_addresses: tuple[str, ...] = ()
    destination_ports: tuple[str, ...] = ()
    destination_fqdns: tuple[str, ...] = ()
    fqdn_tags: tuple[str, ...] = ()
    source_ip_groups: tuple[str, ...] = ()
    destination_ip_groups: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "collection_id", _lower(self.collection_id))
        for name in (
            "protocols",
            "source_addresses",
            "destination_addresses",
            "destination_ports",
            "destination_fqdns",
            "fqdn_tags",
            "source_ip_groups",
            "destination_ip_groups",
        ):
            object.__setattr__(self, name, _tuple(getattr(self, name)))

    @property
    def is_allow(self) -> bool:
        return self.action.casefold() == "allow"

    def source_specs(self) -> tuple[AddressSpec, ...]:
        return tuple(AddressSpec.parse(value) for value in self.source_addresses)

    def destination_specs(self) -> tuple[AddressSpec, ...]:
        return tuple(AddressSpec.parse(value) for value in self.destination_addresses)

    def port_specs(self) -> tuple[PortSpec, ...]:
        return tuple(PortSpec.parse(value) for value in self.destination_ports)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "collection_id": self.collection_id,
            "rule_type": self.rule_type,
            "action": self.action,
            "protocols": list(self.protocols),
            "source_addresses": list(self.source_addresses),
            "destination_addresses": list(self.destination_addresses),
            "destination_ports": list(self.destination_ports),
            "destination_fqdns": list(self.destination_fqdns),
            "fqdn_tags": list(self.fqdn_tags),
            "source_ip_groups": list(self.source_ip_groups),
            "destination_ip_groups": list(self.destination_ip_groups),
        }


@dataclass(frozen=True)
class FirewallRuleCollection(NetworkResource):
    entity_type: str = "FirewallRuleCollection"
    policy_id: str = ""
    firewall_id: str = ""
    group_priority: int = 0
    priority: int = 0
    action: str = "Allow"
    collection_type: str = "NetworkRuleCollection"
    rules: tuple[FirewallRule, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "policy_id", _lower(self.policy_id))
        object.__setattr__(self, "firewall_id", _lower(self.firewall_id))
        object.__setattr__(self, "rules", tuple(self.rules))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "policy_id": self.policy_id,
            "firewall_id": self.firewall_id,
            "group_priority": self.group_priority,
            "priority": self.priority,
            "action": self.action,
            "collection_type": self.collection_type,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True)
class FirewallPolicy(NetworkResource):
    entity_type: str = "FirewallPolicy"
    firewall_ids: tuple[str, ...] = ()
    collection_ids: tuple[str, ...] = ()
    base_policy_id: str = ""
    threat_intel_mode: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "base_policy_id", _lower(self.base_policy_id))
        object.__setattr__(self, "firewall_ids", tuple(_lower(x) for x in _tuple(self.firewall_ids)))
        object.__setattr__(self, "collection_ids", tuple(_lower(x) for x in _tuple(self.collection_ids)))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "firewall_ids": list(self.firewall_ids),
            "collection_ids": list(self.collection_ids),
            "base_policy_id": self.base_policy_id,
            "threat_intel_mode": self.threat_intel_mode,
        }


@dataclass(frozen=True)
class AzureFirewall(NetworkResource):
    entity_type: str = "AzureFirewall"
    vnet_id: str = ""
    subnet_id: str = ""
    policy_id: str = ""
    private_ip: str = ""
    public_ips: tuple[str, ...] = ()
    sku_tier: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "vnet_id", _lower(self.vnet_id))
        object.__setattr__(self, "subnet_id", _lower(self.subnet_id))
        object.__setattr__(self, "policy_id", _lower(self.policy_id))
        object.__setattr__(self, "public_ips", _tuple(self.public_ips))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "vnet_id": self.vnet_id,
            "subnet_id": self.subnet_id,
            "policy_id": self.policy_id,
            "private_ip": self.private_ip,
            "public_ips": list(self.public_ips),
            "sku_tier": self.sku_tier,
        }


@dataclass(frozen=True)
class PrivateEndpoint(NetworkResource):
    entity_type: str = "PrivateEndpoint"
    subnet_id: str = ""
    target_resource_id: str = ""
    group_ids: tuple[str, ...] = ()
    private_ips: tuple[str, ...] = ()
    private_dns_zone_ids: tuple[str, ...] = ()
    connection_state: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "subnet_id", _lower(self.subnet_id))
        object.__setattr__(self, "target_resource_id", _lower(self.target_resource_id))
        object.__setattr__(self, "group_ids", _tuple(self.group_ids))
        object.__setattr__(self, "private_ips", _tuple(self.private_ips))
        object.__setattr__(
            self, "private_dns_zone_ids", tuple(_lower(x) for x in _tuple(self.private_dns_zone_ids))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "subnet_id": self.subnet_id,
            "target_resource_id": self.target_resource_id,
            "group_ids": list(self.group_ids),
            "private_ips": list(self.private_ips),
            "private_dns_zone_ids": list(self.private_dns_zone_ids),
            "connection_state": self.connection_state,
        }


@dataclass(frozen=True)
class PrivateDnsZone(NetworkResource):
    entity_type: str = "PrivateDnsZone"
    linked_vnet_ids: tuple[str, ...] = ()
    record_count: int = 0
    zone_name: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self, "linked_vnet_ids", tuple(_lower(x) for x in _tuple(self.linked_vnet_ids))
        )
        object.__setattr__(self, "zone_name", _lower(self.zone_name) or _lower(self.name))

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "linked_vnet_ids": list(self.linked_vnet_ids),
            "record_count": self.record_count,
            "zone_name": self.zone_name,
        }


@dataclass(frozen=True)
class NetworkGateway(NetworkResource):
    """VPN, ExpressRoute, NAT gateway, Bastion, and DNS resolver.

    These share the same shape — a device attached to a VNet/subnet that
    creates or mediates connectivity — so one class carries all of them,
    discriminated by ``entity_type``.
    """

    entity_type: str = "VpnGateway"
    vnet_id: str = ""
    subnet_id: str = ""
    gateway_type: str = ""
    sku: str = ""
    public_ips: tuple[str, ...] = ()
    private_ips: tuple[str, ...] = ()
    connected_circuit_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "vnet_id", _lower(self.vnet_id))
        object.__setattr__(self, "subnet_id", _lower(self.subnet_id))
        object.__setattr__(self, "public_ips", _tuple(self.public_ips))
        object.__setattr__(self, "private_ips", _tuple(self.private_ips))
        object.__setattr__(
            self, "connected_circuit_ids", tuple(_lower(x) for x in _tuple(self.connected_circuit_ids))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "vnet_id": self.vnet_id,
            "subnet_id": self.subnet_id,
            "gateway_type": self.gateway_type,
            "sku": self.sku,
            "public_ips": list(self.public_ips),
            "private_ips": list(self.private_ips),
            "connected_circuit_ids": list(self.connected_circuit_ids),
        }


@dataclass(frozen=True)
class LoadBalancingResource(NetworkResource):
    """Application Gateway and Load Balancer."""

    entity_type: str = "LoadBalancer"
    vnet_id: str = ""
    subnet_id: str = ""
    sku: str = ""
    frontend_ips: tuple[str, ...] = ()
    public_ips: tuple[str, ...] = ()
    backend_resource_ids: tuple[str, ...] = ()
    backend_subnet_ids: tuple[str, ...] = ()
    waf_enabled: bool = False
    managed_resource_id: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "vnet_id", _lower(self.vnet_id))
        object.__setattr__(self, "subnet_id", _lower(self.subnet_id))
        object.__setattr__(self, "frontend_ips", _tuple(self.frontend_ips))
        object.__setattr__(self, "public_ips", _tuple(self.public_ips))
        object.__setattr__(
            self, "backend_resource_ids", tuple(_lower(x) for x in _tuple(self.backend_resource_ids))
        )
        object.__setattr__(
            self, "backend_subnet_ids", tuple(_lower(x) for x in _tuple(self.backend_subnet_ids))
        )
        object.__setattr__(self, "managed_resource_id", _lower(self.managed_resource_id))

    @property
    def is_internet_facing(self) -> bool:
        return bool(self.public_ips)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "vnet_id": self.vnet_id,
            "subnet_id": self.subnet_id,
            "sku": self.sku,
            "frontend_ips": list(self.frontend_ips),
            "public_ips": list(self.public_ips),
            "backend_resource_ids": list(self.backend_resource_ids),
            "backend_subnet_ids": list(self.backend_subnet_ids),
            "waf_enabled": self.waf_enabled,
            "managed_resource_id": self.managed_resource_id,
        }


@dataclass(frozen=True)
class SharedService(NetworkResource):
    """A hub-hosted common service that spokes are expected to consume.

    Derived, not ingested: the topology builder promotes hub firewalls,
    gateways, Bastion hosts, and DNS resolvers into shared services so
    "what depends on the hub?" has a first-class answer.
    """

    entity_type: str = "SharedService"
    service_kind: str = ""
    provider_resource_id: str = ""
    hub_vnet_id: str = ""
    consumer_vnet_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "provider_resource_id", _lower(self.provider_resource_id))
        object.__setattr__(self, "hub_vnet_id", _lower(self.hub_vnet_id))
        object.__setattr__(
            self, "consumer_vnet_ids", tuple(_lower(x) for x in _tuple(self.consumer_vnet_ids))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "service_kind": self.service_kind,
            "provider_resource_id": self.provider_resource_id,
            "hub_vnet_id": self.hub_vnet_id,
            "consumer_vnet_ids": list(self.consumer_vnet_ids),
        }


@dataclass(frozen=True)
class PrivateLinkResource(NetworkResource):
    """A PaaS resource that should normally sit behind Private Link.

    Carried on the network snapshot so private-endpoint coverage can be
    reported per *resource* rather than per service kind. Sourced from the
    same synced ARG rows as everything else -- the ontology already retains
    every resource type, so this is a projection, not a new ingestion.
    """

    entity_type: str = "PrivateLinkResource"
    service_kind: str = ""
    resource_type: str = ""
    public_network_access: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "resource_type", _lower(self.resource_type))

    @property
    def allows_public_access(self) -> bool:
        """Whether Azure reports public network access as explicitly enabled."""
        return self.public_network_access.strip().casefold() == "enabled"

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "service_kind": self.service_kind,
            "resource_type": self.resource_type,
            "public_network_access": self.public_network_access,
        }


@dataclass(frozen=True)
class NetworkSnapshot:
    """The complete network estate assembled across every connection."""

    vnets: tuple[VNet, ...] = ()
    subnets: tuple[Subnet, ...] = ()
    nics: tuple[NetworkInterface, ...] = ()
    nsgs: tuple[NetworkSecurityGroup, ...] = ()
    route_tables: tuple[RouteTable, ...] = ()
    peerings: tuple[VNetPeering, ...] = ()
    firewalls: tuple[AzureFirewall, ...] = ()
    firewall_policies: tuple[FirewallPolicy, ...] = ()
    firewall_collections: tuple[FirewallRuleCollection, ...] = ()
    private_endpoints: tuple[PrivateEndpoint, ...] = ()
    private_dns_zones: tuple[PrivateDnsZone, ...] = ()
    gateways: tuple[NetworkGateway, ...] = ()
    load_balancers: tuple[LoadBalancingResource, ...] = ()
    shared_services: tuple[SharedService, ...] = ()
    private_link_resources: tuple[PrivateLinkResource, ...] = ()
    # The most recent observation across the ingested rows. Drives API
    # freshness banding: an empty value means "unknown", never "fresh".
    observed_at: str = ""

    def counts(self) -> dict[str, int]:
        return {
            "vnets": len(self.vnets),
            "subnets": len(self.subnets),
            "nics": len(self.nics),
            "nsgs": len(self.nsgs),
            "nsg_rules": sum(len(nsg.rules) for nsg in self.nsgs),
            "route_tables": len(self.route_tables),
            "routes": sum(len(table.routes) for table in self.route_tables),
            "peerings": len(self.peerings),
            "firewalls": len(self.firewalls),
            "firewall_policies": len(self.firewall_policies),
            "firewall_collections": len(self.firewall_collections),
            "firewall_rules": sum(len(c.rules) for c in self.firewall_collections),
            "private_endpoints": len(self.private_endpoints),
            "private_dns_zones": len(self.private_dns_zones),
            "gateways": len(self.gateways),
            "load_balancers": len(self.load_balancers),
            "shared_services": len(self.shared_services),
            "private_link_resources": len(self.private_link_resources),
        }

    @property
    def is_empty(self) -> bool:
        return not any(self.counts().values())

    def all_nsg_rules(self) -> tuple[NetworkSecurityRule, ...]:
        return tuple(rule for nsg in self.nsgs for rule in nsg.rules)

    def all_firewall_rules(self) -> tuple[FirewallRule, ...]:
        return tuple(rule for c in self.firewall_collections for rule in c.rules)

    def all_routes(self) -> tuple[Route, ...]:
        return tuple(route for table in self.route_tables for route in table.routes)

    def connection_ids(self) -> tuple[str, ...]:
        seen = {
            resource.connection_id
            for group in (
                self.vnets, self.subnets, self.nics, self.nsgs, self.route_tables,
                self.peerings, self.firewalls, self.private_endpoints, self.gateways,
            )
            for resource in group
            if resource.connection_id
        }
        return tuple(sorted(seen))
