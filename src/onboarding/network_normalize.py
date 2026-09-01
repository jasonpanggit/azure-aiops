"""Normalizers for network topology ARG payloads.

Azure returns network sub-resources (subnets, NSG rules, routes, peerings,
firewall rule collections) nested inside their parent's ``properties``. This
module flattens them into first-class entities with derived IDs, because
topology, traffic-flow, and tightening analysis all need to address a single
rule or subnet directly.

Kept separate from ``normalize.py`` so the network surface can grow without
turning the core normalizer into a thousand-line file.
"""

from __future__ import annotations

from typing import Any

#: Entity families emitted by this module, appended to ``ENTITY_TYPES``.
NETWORK_ENTITY_TYPES: tuple[str, ...] = (
    "VNet",
    "Subnet",
    "NetworkInterface",
    "NetworkSecurityGroup",
    "NetworkSecurityRule",
    "RouteTable",
    "Route",
    "VNetPeering",
    "AzureFirewall",
    "FirewallPolicy",
    "FirewallRuleCollection",
    "FirewallRule",
    "PrivateEndpoint",
    "PrivateDnsZone",
    "NetworkGateway",
    "LoadBalancer",
)

#: Maps an ARM resource type onto the gateway ``entity_type`` it represents.
GATEWAY_KINDS: dict[str, str] = {
    "microsoft.network/virtualnetworkgateways": "VpnGateway",
    "microsoft.network/vpngateways": "VpnGateway",
    "microsoft.network/expressroutegateways": "ExpressRouteGateway",
    "microsoft.network/expressroutecircuits": "ExpressRouteGateway",
    "microsoft.network/natgateways": "NatGateway",
    "microsoft.network/bastionhosts": "Bastion",
    "microsoft.network/dnsresolvers": "DnsResolver",
}

LOAD_BALANCER_KINDS: dict[str, str] = {
    "microsoft.network/loadbalancers": "LoadBalancer",
    "microsoft.network/applicationgateways": "ApplicationGateway",
}


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return []


def _sub_id(parent_id: str, kind: str, name: str) -> str:
    """Derives a stable child ID for a nested sub-resource."""
    return f"{_lower(parent_id)}/{kind}/{_lower(name)}"


def _child_base(base: dict, entity_type: str, child_id: str, name: str) -> dict:
    """Builds a sub-resource's base fields from its parent's.

    Drops the parent's identity *and* its ``resourceType``: a subnet is not a
    ``microsoft.network/virtualnetworks``, and leaving the parent's ARM type
    on the child causes the ontology's resource-type classifier to relabel it
    as its parent. Business context (subscription, connection, tags) is
    deliberately inherited.
    """
    inherited = {
        key: value
        for key, value in base.items()
        if key not in {"id", "name", "displayName", "resourceType"}
    }
    return {
        **inherited,
        "id": child_id,
        "name": _text(name),
        "displayName": _text(name),
        "entityType": entity_type,
    }


def _address_prefixes(props: dict) -> list[str]:
    """Reads ``addressPrefix`` and ``addressPrefixes`` as one list."""
    values = _strings(props.get("addressPrefixes"))
    single = _text(props.get("addressPrefix"))
    if single and single not in values:
        values.insert(0, single)
    return values


def _ref_id(value: Any) -> str:
    """Unwraps Azure's ``{"id": "..."}`` reference shape."""
    if isinstance(value, dict):
        return _lower(value.get("id"))
    return _lower(value)


def _ref_ids(value: Any) -> list[str]:
    return [ref for ref in (_ref_id(item) for item in _list(value)) if ref]


def normalize_vnet(base: dict, row: dict, observed: str) -> tuple[dict, list[dict], list[dict]]:
    """Returns ``(vnet, subnets, peerings)``.

    Subnets and peerings are emitted as separate entities so a subnet can own
    an NSG association and a peering can be evaluated as its own topology edge.
    """
    props = row.get("properties") or {}
    vnet_id = base["id"]
    address_spaces = _strings((props.get("addressSpace") or {}).get("addressPrefixes"))

    subnets: list[dict] = []
    for subnet in _list(props.get("subnets")):
        subnet_props = subnet.get("properties") or {}
        subnet_id = _lower(subnet.get("id")) or _sub_id(vnet_id, "subnets", subnet.get("name"))
        subnets.append(
            {
                **_child_base(base, "Subnet", subnet_id, subnet.get("name")),
                "vnetId": vnet_id,
                "addressPrefixes": _address_prefixes(subnet_props),
                "nsgId": _ref_id(subnet_props.get("networkSecurityGroup")),
                "routeTableId": _ref_id(subnet_props.get("routeTable")),
                "natGatewayId": _ref_id(subnet_props.get("natGateway")),
                "privateEndpointIds": _ref_ids(subnet_props.get("privateEndpoints")),
                "serviceEndpoints": [
                    _text(item.get("service"))
                    for item in _list(subnet_props.get("serviceEndpoints"))
                    if _text(item.get("service"))
                ],
                "delegations": [
                    _text((item.get("properties") or {}).get("serviceName"))
                    for item in _list(subnet_props.get("delegations"))
                    if _text((item.get("properties") or {}).get("serviceName"))
                ],
                "properties": subnet_props,
            }
        )

    peerings: list[dict] = []
    for peering in _list(props.get("virtualNetworkPeerings")):
        peer_props = peering.get("properties") or {}
        peering_id = _lower(peering.get("id")) or _sub_id(
            vnet_id, "virtualnetworkpeerings", peering.get("name")
        )
        peerings.append(
            {
                **_child_base(base, "VNetPeering", peering_id, peering.get("name")),
                "localVnetId": vnet_id,
                "remoteVnetId": _ref_id(peer_props.get("remoteVirtualNetwork")),
                "peeringState": _text(peer_props.get("peeringState")),
                "allowForwardedTraffic": bool(peer_props.get("allowForwardedTraffic")),
                "allowGatewayTransit": bool(peer_props.get("allowGatewayTransit")),
                "useRemoteGateways": bool(peer_props.get("useRemoteGateways")),
                "allowVirtualNetworkAccess": bool(peer_props.get("allowVirtualNetworkAccess", True)),
                "properties": peer_props,
            }
        )

    vnet = {
        **base,
        "entityType": "VNet",
        "addressSpaces": address_spaces,
        "subnetIds": [subnet["id"] for subnet in subnets],
        "peeringIds": [peering["id"] for peering in peerings],
        "dnsServers": _strings((props.get("dhcpOptions") or {}).get("dnsServers")),
        "ddosProtectionEnabled": bool(props.get("enableDdosProtection")),
        "properties": props,
    }
    return vnet, subnets, peerings


def normalize_nsg(base: dict, row: dict, observed: str) -> tuple[dict, list[dict]]:
    """Returns ``(nsg, rules)`` including Azure's default security rules.

    Default rules are retained and flagged, not dropped: ``DenyAllInBound``
    is what makes an explicit allow meaningful, and shadowing analysis is
    wrong without it.
    """
    props = row.get("properties") or {}
    nsg_id = base["id"]
    rules: list[dict] = []

    for collection_key, is_default in (("securityRules", False), ("defaultSecurityRules", True)):
        for rule in _list(props.get(collection_key)):
            rule_props = rule.get("properties") or {}
            rule_id = _lower(rule.get("id")) or _sub_id(nsg_id, "securityrules", rule.get("name"))
            source_addresses = _strings(rule_props.get("sourceAddressPrefixes")) or [
                _text(rule_props.get("sourceAddressPrefix")) or "*"
            ]
            dest_addresses = _strings(rule_props.get("destinationAddressPrefixes")) or [
                _text(rule_props.get("destinationAddressPrefix")) or "*"
            ]
            dest_ports = _strings(rule_props.get("destinationPortRanges")) or [
                _text(rule_props.get("destinationPortRange")) or "*"
            ]
            source_ports = _strings(rule_props.get("sourcePortRanges")) or [
                _text(rule_props.get("sourcePortRange")) or "*"
            ]
            rules.append(
                {
                    **_child_base(base, "NetworkSecurityRule", rule_id, rule.get("name")),
                    "nsgId": nsg_id,
                    "priority": int(rule_props.get("priority") or 0),
                    "direction": _text(rule_props.get("direction")) or "Inbound",
                    "access": _text(rule_props.get("access")) or "Allow",
                    "protocol": _text(rule_props.get("protocol")) or "*",
                    "sourceAddress": ",".join(source_addresses),
                    "destinationAddress": ",".join(dest_addresses),
                    "sourcePort": ",".join(source_ports),
                    "destinationPort": ",".join(dest_ports),
                    "description": _text(rule_props.get("description")),
                    "isDefault": is_default,
                    "properties": rule_props,
                }
            )

    nsg = {
        **base,
        "entityType": "NetworkSecurityGroup",
        "ruleIds": [rule["id"] for rule in rules],
        "subnetIds": _ref_ids(props.get("subnets")),
        "nicIds": _ref_ids(props.get("networkInterfaces")),
        "properties": props,
    }
    return nsg, rules


def normalize_route_table(base: dict, row: dict, observed: str) -> tuple[dict, list[dict]]:
    """Returns ``(route_table, routes)``."""
    props = row.get("properties") or {}
    table_id = base["id"]
    routes: list[dict] = []
    for route in _list(props.get("routes")):
        route_props = route.get("properties") or {}
        route_id = _lower(route.get("id")) or _sub_id(table_id, "routes", route.get("name"))
        routes.append(
            {
                **_child_base(base, "Route", route_id, route.get("name")),
                "routeTableId": table_id,
                "addressPrefix": _text(route_props.get("addressPrefix")),
                "nextHopType": _text(route_props.get("nextHopType")),
                "nextHopIp": _text(route_props.get("nextHopIpAddress")),
                "properties": route_props,
            }
        )
    table = {
        **base,
        "entityType": "RouteTable",
        "routeIds": [route["id"] for route in routes],
        "subnetIds": _ref_ids(props.get("subnets")),
        "disableBgpRoutePropagation": bool(props.get("disableBgpRoutePropagation")),
        "properties": props,
    }
    return table, routes


def normalize_nic(base: dict, row: dict, observed: str) -> dict:
    props = row.get("properties") or {}
    configs = _list(props.get("ipConfigurations"))
    private_ips: list[str] = []
    public_ips: list[str] = []
    subnet_id = ""
    for config in configs:
        config_props = config.get("properties") or {}
        private = _text(config_props.get("privateIPAddress"))
        if private:
            private_ips.append(private)
        public = config_props.get("publicIPAddress")
        public_ref = _ref_id(public)
        if public_ref:
            public_ips.append(public_ref)
        if not subnet_id:
            subnet_id = _ref_id(config_props.get("subnet"))
    return {
        **base,
        "entityType": "NetworkInterface",
        "subnetId": subnet_id,
        "privateIps": private_ips,
        "publicIps": public_ips,
        "nsgId": _ref_id(props.get("networkSecurityGroup")),
        # A NIC belongs to a VM, or - for a private endpoint - to the endpoint
        # that owns it. Without the fallback a private endpoint NIC looks
        # unattached and its edge to the endpoint is never drawn.
        "attachedResourceId": _ref_id(props.get("virtualMachine")) or _ref_id(props.get("privateEndpoint")),
        "properties": props,
    }


def normalize_firewall(base: dict, row: dict, observed: str) -> tuple[dict, list[dict], list[dict]]:
    """Returns ``(firewall, collections, rules)``.

    A classic (non-policy) Azure Firewall carries its rule collections
    inline on the firewall resource itself -- ``applicationRuleCollections``,
    ``networkRuleCollections``, ``natRuleCollections`` -- rather than in a
    separate ``FirewallPolicy``/``ruleCollectionGroups`` child resource (see
    ``normalize_firewall_policy`` below for the policy-based shape). Both
    shapes are flattened into the same ``FirewallRuleCollection``/
    ``FirewallRule`` entities so topology/gaps analysis doesn't need to care
    which style a given firewall uses.
    """
    props = row.get("properties") or {}
    configs = _list(props.get("ipConfigurations"))
    subnet_id = ""
    private_ip = ""
    public_ips: list[str] = []
    for config in configs:
        config_props = config.get("properties") or {}
        if not subnet_id:
            subnet_id = _ref_id(config_props.get("subnet"))
        if not private_ip:
            private_ip = _text(config_props.get("privateIPAddress"))
        public = _ref_id(config_props.get("publicIPAddress"))
        if public:
            public_ips.append(public)
    vnet_id = subnet_id.split("/subnets/", 1)[0] if "/subnets/" in subnet_id else ""
    firewall = {
        **base,
        "entityType": "AzureFirewall",
        "vnetId": vnet_id,
        "subnetId": subnet_id,
        "policyId": _ref_id(props.get("firewallPolicy")),
        "privateIp": private_ip,
        "publicIps": public_ips,
        "skuTier": _text((props.get("sku") or {}).get("tier")),
        "properties": props,
    }
    collections, rules = _classic_firewall_rule_collections(base, firewall["id"], props)
    return firewall, collections, rules


#: Maps each classic inline rule-collection property name onto the rule type
#: its rules should be tagged with, so application/network/NAT rules stay
#: distinguishable once flattened into the shared ``FirewallRule`` entity.
_CLASSIC_RULE_COLLECTION_KINDS: tuple[tuple[str, str], ...] = (
    ("applicationRuleCollections", "ApplicationRule"),
    ("networkRuleCollections", "NetworkRule"),
    ("natRuleCollections", "NatRule"),
)


def _classic_firewall_rule_collections(
    base: dict, firewall_id: str, props: dict
) -> tuple[list[dict], list[dict]]:
    """Flattens a classic firewall's inline rule collections/rules.

    Mirrors ``normalize_firewall_policy``'s collection/rule shape but reads
    from the firewall's own ``properties`` (``applicationRuleCollections``,
    ``networkRuleCollections``, ``natRuleCollections``) instead of a
    ``FirewallPolicy``'s ``ruleCollections``, and sets ``firewall_id`` rather
    than ``policy_id`` so the collection links back to the firewall directly.
    """
    collections: list[dict] = []
    rules: list[dict] = []
    for prop_name, rule_type in _CLASSIC_RULE_COLLECTION_KINDS:
        for collection in _list(props.get(prop_name)):
            collection_props = collection.get("properties") or collection
            collection_name = _text(collection.get("name"))
            collection_id = _sub_id(firewall_id, "rulecollections", collection_name)
            collection_action = _text((collection_props.get("action") or {}).get("type")) or "Allow"
            collections.append(
                {
                    **_child_base(base, "FirewallRuleCollection", collection_id, collection_name),
                    "policyId": "",
                    "firewallId": firewall_id,
                    "priority": int(collection_props.get("priority") or 0),
                    "action": collection_action,
                    "collectionType": rule_type + "Collection",
                    "properties": collection_props,
                }
            )
            for rule in _list(collection_props.get("rules")):
                rule_name = _text(rule.get("name"))
                # Application rules express their target as FQDNs (or FQDN
                # tags like "WindowsUpdate"); network/NAT rules use IP-style
                # destination addresses. Both land in destination_fqdns /
                # destination_addresses respectively so downstream gap
                # analysis can read either without knowing the rule type.
                destination_fqdns = _strings(rule.get("targetFqdns")) or _strings(rule.get("fqdnTags"))
                destination_fqdns = destination_fqdns or _strings(rule.get("destinationFqdns"))
                rules.append(
                    {
                        **_child_base(
                            base, "FirewallRule", _sub_id(collection_id, "rules", rule_name), rule_name
                        ),
                        "collectionId": collection_id,
                        "ruleType": rule_type,
                        "action": collection_action,
                        "protocols": _rule_protocols(rule),
                        "sourceAddresses": _strings(rule.get("sourceAddresses")),
                        "destinationAddresses": _strings(rule.get("destinationAddresses")),
                        "destinationPorts": _strings(rule.get("destinationPorts")),
                        "destinationFqdns": destination_fqdns,
                        "sourceIpGroups": _strings(rule.get("sourceIpGroups")),
                        "properties": rule,
                    }
                )
    return collections, rules


def normalize_firewall_policy(
    base: dict, row: dict, observed: str
) -> tuple[dict | None, list[dict], list[dict]]:
    """Returns ``(policy, collections, rules)``.

    Handles both the policy resource and its ``ruleCollectionGroups`` child
    resource; the child carries the actual rule collections, so a
    rule-collection-group row emits collections/rules but no policy.
    """
    props = row.get("properties") or {}
    resource_type = _lower(row.get("type"))
    is_group = resource_type.endswith("/rulecollectiongroups")

    if is_group:
        policy_id = base["id"].split("/rulecollectiongroups/", 1)[0]
        policy = None
    else:
        policy_id = base["id"]
        policy = {
            **base,
            "entityType": "FirewallPolicy",
            "firewallIds": _ref_ids(props.get("firewalls")),
            "basePolicyId": _ref_id(props.get("basePolicy")),
            "threatIntelMode": _text(props.get("threatIntelMode")),
            "properties": props,
        }

    collections: list[dict] = []
    rules: list[dict] = []
    for collection in _list(props.get("ruleCollections")):
        collection_name = _text(collection.get("name"))
        collection_id = _sub_id(base["id"], "rulecollections", collection_name)
        collection_action = _text((collection.get("action") or {}).get("type")) or "Allow"
        collections.append(
            {
                **_child_base(base, "FirewallRuleCollection", collection_id, collection_name),
                "policyId": policy_id,
                "priority": int(collection.get("priority") or 0),
                "action": collection_action,
                "collectionType": _text(collection.get("ruleCollectionType")) or "FirewallPolicyFilterRuleCollection",
                "properties": collection,
            }
        )
        for rule in _list(collection.get("rules")):
            rule_name = _text(rule.get("name"))
            rules.append(
                {
                    **_child_base(
                        base, "FirewallRule", _sub_id(collection_id, "rules", rule_name), rule_name
                    ),
                    "collectionId": collection_id,
                    "ruleType": _text(rule.get("ruleType")) or "NetworkRule",
                    "action": collection_action,
                    "protocols": _rule_protocols(rule),
                    "sourceAddresses": _strings(rule.get("sourceAddresses")),
                    "destinationAddresses": _strings(rule.get("destinationAddresses")),
                    "destinationPorts": _strings(rule.get("destinationPorts")),
                    "destinationFqdns": _strings(rule.get("destinationFqdns")),
                    "sourceIpGroups": _strings(rule.get("sourceIpGroups")),
                    "properties": rule,
                }
            )
    return policy, collections, rules


def _rule_protocols(rule: dict) -> list[str]:
    """Firewall rules express protocols as strings or ``{protocolType, port}``."""
    protocols = rule.get("ipProtocols") or rule.get("protocols")
    values: list[str] = []
    for item in _list(protocols) if isinstance(protocols, list) else []:
        if isinstance(item, dict):
            value = _text(item.get("protocolType"))
        else:
            value = _text(item)
        if value:
            values.append(value)
    if not values and isinstance(protocols, str):
        values = _strings(protocols)
    return values


def private_endpoint_dns_zone_ids(row: dict) -> list[str]:
    """Reads zone IDs from canonical endpoints and Azure zone-group children."""
    props = row.get("properties") or {}
    values = [
        *_list(row.get("privateDnsZoneIds")),
        *_list(props.get("privateDnsZoneIds")),
    ]
    configs = [
        *_list(props.get("privateDnsZoneConfigs")),
        *_list(
            (props.get("privateDnsZoneGroup") or {}).get(
                "privateDnsZoneConfigs"
            )
        ),
    ]
    for config in configs:
        config_props = config.get("properties") or {}
        values.append(
            config_props.get("privateDnsZoneId")
            or config.get("privateDnsZoneId")
        )
    return sorted({zone_id for value in values if (zone_id := _ref_id(value))})


def normalize_private_endpoint(base: dict, row: dict, observed: str) -> dict:
    props = row.get("properties") or {}
    connections = _list(props.get("privateLinkServiceConnections")) + _list(
        props.get("manualPrivateLinkServiceConnections")
    )
    target = ""
    group_ids: list[str] = []
    state = ""
    for connection in connections:
        connection_props = connection.get("properties") or {}
        if not target:
            target = _lower(connection_props.get("privateLinkServiceId"))
        group_ids.extend(_strings(connection_props.get("groupIds")))
        if not state:
            state = _text((connection_props.get("privateLinkServiceConnectionState") or {}).get("status"))
    private_ips = [
        _text((config.get("properties") or {}).get("privateIPAddress"))
        for config in _list(props.get("customDnsConfigs")) + _list(props.get("ipConfigurations"))
        if _text((config.get("properties") or {}).get("privateIPAddress"))
    ]
    return {
        **base,
        "entityType": "PrivateEndpoint",
        "subnetId": _ref_id(props.get("subnet")),
        "targetResourceId": target,
        "groupIds": sorted(set(group_ids)),
        "privateIps": private_ips,
        "privateDnsZoneIds": private_endpoint_dns_zone_ids(row),
        "connectionState": state,
        "properties": props,
    }


def normalize_private_dns_zone(base: dict, row: dict, observed: str) -> dict | None:
    """Zone rows become entities; virtual-network-link rows enrich them.

    A link row returns ``None`` with its parent zone recorded in
    ``linkedVnetIds`` by the caller, so links never become orphan entities.
    """
    resource_type = _lower(row.get("type"))
    if resource_type.endswith("/virtualnetworklinks"):
        return None
    props = row.get("properties") or {}
    return {
        **base,
        "entityType": "PrivateDnsZone",
        "zoneName": _lower(row.get("name")),
        "linkedVnetIds": [],
        "recordCount": int(props.get("numberOfRecordSets") or 0),
        "properties": props,
    }


def private_dns_link_target(row: dict) -> tuple[str, str]:
    """Returns ``(zone_id, linked_vnet_id)`` for a virtual-network-link row."""
    source_id = _lower(row.get("id"))
    if "/virtualnetworklinks/" not in source_id:
        return "", ""
    zone_id = source_id.split("/virtualnetworklinks/", 1)[0]
    props = row.get("properties") or {}
    return zone_id, _ref_id(props.get("virtualNetwork"))


def normalize_gateway(base: dict, row: dict, observed: str) -> dict:
    props = row.get("properties") or {}
    resource_type = _lower(row.get("type"))
    entity_type = GATEWAY_KINDS.get(resource_type, "VpnGateway")

    subnet_id = ""
    public_ips: list[str] = []
    private_ips: list[str] = []
    for config in _list(props.get("ipConfigurations")):
        config_props = config.get("properties") or {}
        if not subnet_id:
            subnet_id = _ref_id(config_props.get("subnet"))
        public = _ref_id(config_props.get("publicIPAddress"))
        if public:
            public_ips.append(public)
        private = _text(config_props.get("privateIPAddress"))
        if private:
            private_ips.append(private)
    for address in _list(props.get("publicIpAddresses")):
        ref = _ref_id(address)
        if ref:
            public_ips.append(ref)
    if not subnet_id:
        subnet_id = _ref_id(props.get("subnet"))

    vnet_id = subnet_id.split("/subnets/", 1)[0] if "/subnets/" in subnet_id else ""
    if not vnet_id:
        vnet_id = _ref_id(props.get("virtualNetwork") or {})

    return {
        **base,
        "entityType": entity_type,
        "vnetId": vnet_id,
        "subnetId": subnet_id,
        "gatewayType": _text(props.get("gatewayType")) or _text(props.get("vpnType")),
        "sku": _text((props.get("sku") or {}).get("name")) or _text((props.get("sku") or {}).get("tier")),
        "publicIps": sorted(set(public_ips)),
        "privateIps": private_ips,
        "connectedCircuitIds": _ref_ids(props.get("expressRouteCircuits") or props.get("connections")),
        "properties": props,
    }


def normalize_load_balancer(base: dict, row: dict, observed: str) -> dict:
    props = row.get("properties") or {}
    resource_type = _lower(row.get("type"))
    entity_type = LOAD_BALANCER_KINDS.get(resource_type, "LoadBalancer")

    frontend_key = "frontendIPConfigurations"
    subnet_id = ""
    public_ips: list[str] = []
    frontend_ips: list[str] = []
    for config in _list(props.get(frontend_key)):
        config_props = config.get("properties") or {}
        if not subnet_id:
            subnet_id = _ref_id(config_props.get("subnet"))
        public = _ref_id(config_props.get("publicIPAddress"))
        if public:
            public_ips.append(public)
        private = _text(config_props.get("privateIPAddress"))
        if private:
            frontend_ips.append(private)

    backends: list[str] = []
    backend_subnets: list[str] = []
    for pool in _list(props.get("backendAddressPools")):
        pool_props = pool.get("properties") or {}
        backends.extend(_ref_ids(pool_props.get("backendIPConfigurations")))
        for address in _list(pool_props.get("loadBalancerBackendAddresses")):
            address_props = address.get("properties") or address
            ref = _ref_id(address_props.get("networkInterfaceIPConfiguration"))
            if ref:
                backends.append(ref)
            # Managed backends (e.g. AKS/ACA node pools behind an internal LB)
            # are addressed by IP + subnet rather than a NIC IP-config ID, so
            # there is no per-member resource to link to. Falling back to the
            # subnet at least anchors the LB inside the topology instead of
            # leaving it with no backend edge at all.
            backend_subnet_ref = _ref_id(address_props.get("subnet"))
            if backend_subnet_ref:
                backend_subnets.append(backend_subnet_ref)

    waf_config = props.get("webApplicationFirewallConfiguration") or {}
    waf_enabled = bool(waf_config.get("enabled")) or bool(props.get("firewallPolicy"))

    vnet_id = subnet_id.split("/subnets/", 1)[0] if "/subnets/" in subnet_id else ""
    if not vnet_id and backend_subnets:
        # A public-only frontend (no subnet) leaves the LB with no VNet
        # anchor at all; anchor it to whichever VNet its backends live in.
        first_backend_subnet = backend_subnets[0]
        vnet_id = (
            first_backend_subnet.split("/subnets/", 1)[0]
            if "/subnets/" in first_backend_subnet
            else vnet_id
        )
    if not subnet_id and backend_subnets:
        subnet_id = backend_subnets[0]

    # Azure Container Apps (and similarly PaaS-managed LBs) stamp the owning
    # resource onto the LB via a tag rather than a first-class ARM reference,
    # so the only way to attach this LB to its managed environment/app is to
    # read the tag back out.
    tags = row.get("tags") or {}
    managed_resource_id = _text(
        tags.get("aca-managed-env-id") or tags.get("managed-by-resource-id") or ""
    )

    return {
        **base,
        "entityType": entity_type,
        "vnetId": vnet_id,
        "subnetId": subnet_id,
        "sku": _text((props.get("sku") or {}).get("name")),
        "frontendIps": frontend_ips,
        "publicIps": sorted(set(public_ips)),
        "backendResourceIds": sorted(set(backends)),
        "backendSubnetIds": sorted(set(backend_subnets)),
        "wafEnabled": waf_enabled,
        "managedResourceId": managed_resource_id,
        "properties": props,
    }
