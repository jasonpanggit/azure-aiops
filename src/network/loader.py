"""Builds a typed :class:`NetworkSnapshot` from ontology entity rows.

The analyzers never read ontology dicts directly. This loader is the single
place that understands the row shape, so a schema change lands here rather
than across six analysis engines.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from .models import (
    PRIVATE_LINK_RESOURCE_TYPES,
    AzureFirewall,
    FirewallPolicy,
    FirewallRule,
    FirewallRuleCollection,
    LoadBalancingResource,
    NetworkGateway,
    NetworkInterface,
    NetworkSecurityGroup,
    NetworkSecurityRule,
    NetworkSnapshot,
    PrivateDnsZone,
    PrivateEndpoint,
    PrivateLinkResource,
    Route,
    RouteTable,
    Subnet,
    VNet,
    VNetPeering,
)

GATEWAY_ENTITY_TYPES = frozenset(
    {"VpnGateway", "ExpressRouteGateway", "NatGateway", "Bastion", "DnsResolver", "NetworkGateway"}
)
LOAD_BALANCER_ENTITY_TYPES = frozenset({"LoadBalancer", "ApplicationGateway"})

#: The ontology collapses every gateway-shaped resource into one
#: ``NetworkGateway`` entity type. The specific kind is what the topology
#: canvas draws an icon for, so it is recovered from the ARM resource type.
GATEWAY_KIND_BY_RESOURCE_TYPE = {
    "microsoft.network/virtualnetworkgateways": "VpnGateway",
    "microsoft.network/vpngateways": "VpnGateway",
    "microsoft.network/expressroutegateways": "ExpressRouteGateway",
    "microsoft.network/expressroutecircuits": "ExpressRouteGateway",
    "microsoft.network/natgateways": "NatGateway",
    "microsoft.network/bastionhosts": "Bastion",
    "microsoft.network/dnsresolvers": "DnsResolver",
}

LOAD_BALANCER_KIND_BY_RESOURCE_TYPE = {
    "microsoft.network/loadbalancers": "LoadBalancer",
    "microsoft.network/applicationgateways": "ApplicationGateway",
}


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """Reads a row's payload whether it is nested JSON or already flat."""
    raw = row.get("payload_json") or row.get("payloadJson")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = {}
        if isinstance(parsed, dict):
            return parsed
    if isinstance(raw, dict):
        return raw
    return dict(row)


def _get(row: Mapping[str, Any], payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        for source in (payload, row):
            if key in source and source[key] not in (None, ""):
                return source[key]
    return default


def _tags(row: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, str]:
    raw = _get(row, payload, "tags", default={})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _tag_lookup(tags: Mapping[str, str], *names: str) -> str:
    folded = {str(key).casefold(): str(value) for key, value in tags.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value:
            return value
    return ""


def _load_balancer_backend_subnets(payload: Mapping[str, Any]) -> tuple[str, ...]:
    properties = payload.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    subnet_ids: list[str] = []
    pools = properties.get("backendAddressPools")
    if not isinstance(pools, list):
        return ()
    for pool in pools:
        if not isinstance(pool, Mapping):
            continue
        pool_properties = pool.get("properties")
        if not isinstance(pool_properties, Mapping):
            continue
        addresses = pool_properties.get("loadBalancerBackendAddresses")
        if not isinstance(addresses, list):
            continue
        for address in addresses:
            if not isinstance(address, Mapping):
                continue
            address_properties = address.get("properties")
            if not isinstance(address_properties, Mapping):
                address_properties = address
            subnet = address_properties.get("subnet")
            if isinstance(subnet, Mapping):
                subnet_id = subnet.get("id")
                if subnet_id:
                    subnet_ids.append(str(subnet_id))
    return tuple(dict.fromkeys(subnet_ids))


def _common(row: Mapping[str, Any]) -> dict[str, Any]:
    """Extracts the fields every :class:`NetworkResource` carries."""
    payload = _payload(row)
    tags = _tags(row, payload)
    return {
        "resource_id": _get(row, payload, "resource_id", "resourceId", "id", default=""),
        "name": _get(row, payload, "name", "displayName", default=""),
        "subscription_id": _get(row, payload, "subscription_id", "subscriptionId", default=""),
        "resource_group": _get(row, payload, "resource_group", "resourceGroup", default=""),
        "location": _get(row, payload, "location", default=""),
        "connection_id": _get(row, payload, "connection_id", "connectionId", default=""),
        "environment": _get(row, payload, "environment_name", "environmentName", default="")
        or _tag_lookup(tags, "environment", "env"),
        "business_service": _get(row, payload, "business_service_name", "businessServiceName", default="")
        or _tag_lookup(tags, "businessService", "business_service", "service"),
        "application": _get(row, payload, "application_name", "applicationName", default="")
        or _tag_lookup(tags, "application", "app"),
        "owner": _get(row, payload, "owner_name", "ownerName", default="")
        or _tag_lookup(tags, "owner", "ownedBy"),
        "support_team": _get(
            row, payload, "support_team", "support_team_name", "supportTeam", "supportTeamName", default=""
        ) or _tag_lookup(tags, "support_team", "supportTeam", "support-team", "support team"),
        "region": _get(row, payload, "region", "location", default=""),
        "criticality": _get(row, payload, "criticality", "severity_tier", default="")
        or _tag_lookup(tags, "criticality", "severity_tier"),
        "tags": tags,
        "properties": payload.get("properties") if isinstance(payload.get("properties"), dict) else {},
    }


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return (value,) if value.strip() else ()
        return _strings(parsed)
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item or "").strip())
    return ()


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _entity_type(row: Mapping[str, Any]) -> str:
    payload = _payload(row)
    return str(_get(row, payload, "entity_type", "entityType", default="") or "")


def _resource_type(row: Mapping[str, Any]) -> str:
    payload = _payload(row)
    # ARG rows carry the ARM type as `type`; ontology rows normalise it to
    # `resource_type`. Both are accepted so PaaS rows match either way.
    return str(
        _get(row, payload, "resource_type", "resourceType", "type", default="") or ""
    ).strip().casefold()


class NetworkSnapshotLoader:
    """Groups ontology rows by entity type and reassembles typed objects.

    Sub-resources are re-nested under their parents (rules into NSGs, routes
    into route tables, firewall rules into collections) so evaluation order
    and ownership are explicit rather than rediscovered by every analyzer.
    """

    def load(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        observed_at: str | None = None,
    ) -> NetworkSnapshot:
        buckets: dict[str, list[Mapping[str, Any]]] = {}
        # PaaS resources are collected by ARM type rather than entity type: the
        # ontology normalises them to a generic "Resource" and live ARG rows
        # carry no entity type at all. Without this the estate's Private Link
        # candidates would be invisible to gap analysis.
        private_link_rows: list[Mapping[str, Any]] = []
        observed = _parse_observed_at(observed_at)
        for row in rows:
            entity_type = _entity_type(row)
            if entity_type:
                buckets.setdefault(entity_type, []).append(row)
            if _resource_type(row) in PRIVATE_LINK_RESOURCE_TYPES:
                private_link_rows.append(row)
            seen = _parse_observed_at(_observed_at(row))
            if seen is not None and (observed is None or seen > observed):
                observed = seen

        nsg_rules = [self._nsg_rule(row) for row in buckets.get("NetworkSecurityRule", [])]
        rules_by_nsg: dict[str, list[NetworkSecurityRule]] = {}
        for rule in nsg_rules:
            rules_by_nsg.setdefault(rule.nsg_id, []).append(rule)

        routes = [self._route(row) for row in buckets.get("Route", [])]
        routes_by_table: dict[str, list[Route]] = {}
        for route in routes:
            routes_by_table.setdefault(route.route_table_id, []).append(route)

        firewall_rules = [self._firewall_rule(row) for row in buckets.get("FirewallRule", [])]
        rules_by_collection: dict[str, list[FirewallRule]] = {}
        for rule in firewall_rules:
            rules_by_collection.setdefault(rule.collection_id, []).append(rule)

        gateway_rows = [
            row
            for entity_type in GATEWAY_ENTITY_TYPES
            for row in buckets.get(entity_type, [])
        ]
        balancer_rows = [
            row
            for entity_type in LOAD_BALANCER_ENTITY_TYPES
            for row in buckets.get(entity_type, [])
        ]

        return NetworkSnapshot(
            vnets=tuple(self._vnet(row) for row in buckets.get("VNet", [])),
            subnets=tuple(self._subnet(row) for row in buckets.get("Subnet", [])),
            nics=tuple(self._nic(row) for row in buckets.get("NetworkInterface", [])),
            nsgs=tuple(
                self._nsg(row, rules_by_nsg) for row in buckets.get("NetworkSecurityGroup", [])
            ),
            route_tables=tuple(
                self._route_table(row, routes_by_table) for row in buckets.get("RouteTable", [])
            ),
            peerings=tuple(self._peering(row) for row in buckets.get("VNetPeering", [])),
            firewalls=tuple(self._firewall(row) for row in buckets.get("AzureFirewall", [])),
            firewall_policies=tuple(
                self._firewall_policy(row) for row in buckets.get("FirewallPolicy", [])
            ),
            firewall_collections=tuple(
                self._firewall_collection(row, rules_by_collection)
                for row in buckets.get("FirewallRuleCollection", [])
            ),
            private_endpoints=tuple(
                self._private_endpoint(row) for row in buckets.get("PrivateEndpoint", [])
            ),
            private_dns_zones=tuple(
                self._private_dns_zone(row) for row in buckets.get("PrivateDnsZone", [])
            ),
            gateways=tuple(self._gateway(row) for row in gateway_rows),
            load_balancers=tuple(self._load_balancer(row) for row in balancer_rows),
            private_link_resources=tuple(
                self._private_link_resource(row) for row in private_link_rows
            ),
            observed_at=_format_observed_at(observed),
        )

    def _vnet(self, row: Mapping[str, Any]) -> VNet:
        payload = _payload(row)
        return VNet(
            **_common(row),
            address_spaces=_strings(_get(row, payload, "addressSpaces", "address_spaces")),
            subnet_ids=_strings(_get(row, payload, "subnetIds", "subnet_ids")),
            peering_ids=_strings(_get(row, payload, "peeringIds", "peering_ids")),
            dns_servers=_strings(_get(row, payload, "dnsServers", "dns_servers")),
            ddos_protection_enabled=_bool(
                _get(row, payload, "ddosProtectionEnabled", "ddos_protection_enabled")
            ),
        )

    def _subnet(self, row: Mapping[str, Any]) -> Subnet:
        payload = _payload(row)
        return Subnet(
            **_common(row),
            vnet_id=_get(row, payload, "vnetId", "vnet_id", default=""),
            address_prefixes=_strings(_get(row, payload, "addressPrefixes", "address_prefixes")),
            nsg_id=_get(row, payload, "nsgId", "nsg_id", default=""),
            route_table_id=_get(row, payload, "routeTableId", "route_table_id", default=""),
            nat_gateway_id=_get(row, payload, "natGatewayId", "nat_gateway_id", default=""),
            private_endpoint_ids=_strings(
                _get(row, payload, "privateEndpointIds", "private_endpoint_ids")
            ),
            service_endpoints=_strings(_get(row, payload, "serviceEndpoints", "service_endpoints")),
            delegations=_strings(_get(row, payload, "delegations")),
        )

    def _nic(self, row: Mapping[str, Any]) -> NetworkInterface:
        payload = _payload(row)
        return NetworkInterface(
            **_common(row),
            subnet_id=_get(row, payload, "subnetId", "subnet_id", default=""),
            private_ips=_strings(_get(row, payload, "privateIps", "private_ips")),
            public_ips=_strings(_get(row, payload, "publicIps", "public_ips")),
            nsg_id=_get(row, payload, "nsgId", "nsg_id", default=""),
            attached_resource_id=_get(
                row, payload, "attachedResourceId", "attached_resource_id", default=""
            ),
        )

    def _nsg_rule(self, row: Mapping[str, Any]) -> NetworkSecurityRule:
        payload = _payload(row)
        # Legacy property-bearing rows may contain normalized defaults, not observations.
        return NetworkSecurityRule(
            **_common(row),
            configuration_observed=_bool(_get(
                row, payload, "configurationObserved", "configuration_observed",
                default=not isinstance(payload.get("properties"), dict) and all(
                    _get(row, payload, *keys) is not None for keys in (
                        ("priority",), ("direction",), ("access",), ("protocol",),
                        ("sourceAddress", "source_address"),
                        ("destinationAddress", "destination_address"),
                        ("sourcePort", "source_port"), ("destinationPort", "destination_port"),
                    )
                ),
            )),
            nsg_id=_get(row, payload, "nsgId", "nsg_id", default=""),
            priority=_int(_get(row, payload, "priority", default=0)),
            direction=_get(row, payload, "direction", default="Inbound"),
            access=_get(row, payload, "access", default="Allow"),
            protocol=_get(row, payload, "protocol", default="*"),
            source_address=_get(row, payload, "sourceAddress", "source_address", default="*"),
            destination_address=_get(
                row, payload, "destinationAddress", "destination_address", default="*"
            ),
            source_port=_get(row, payload, "sourcePort", "source_port", default="*"),
            destination_port=_get(
                row, payload, "destinationPort", "destination_port", default="*"
            ),
            description=_get(row, payload, "description", default=""),
            is_default=_bool(_get(row, payload, "isDefault", "is_default")),
        )

    def _nsg(
        self, row: Mapping[str, Any], rules_by_nsg: Mapping[str, list[NetworkSecurityRule]]
    ) -> NetworkSecurityGroup:
        payload = _payload(row)
        common = _common(row)
        nsg_id = str(common["resource_id"]).casefold()
        return NetworkSecurityGroup(
            **common,
            rules=tuple(rules_by_nsg.get(nsg_id, ())),
            subnet_ids=_strings(_get(row, payload, "subnetIds", "subnet_ids")),
            nic_ids=_strings(_get(row, payload, "nicIds", "nic_ids")),
        )

    def _route(self, row: Mapping[str, Any]) -> Route:
        payload = _payload(row)
        return Route(
            **_common(row),
            route_table_id=_get(row, payload, "routeTableId", "route_table_id", default=""),
            address_prefix=_get(row, payload, "addressPrefix", "address_prefix", default=""),
            next_hop_type=_get(row, payload, "nextHopType", "next_hop_type", default=""),
            next_hop_ip=_get(row, payload, "nextHopIp", "next_hop_ip", default=""),
        )

    def _route_table(
        self, row: Mapping[str, Any], routes_by_table: Mapping[str, list[Route]]
    ) -> RouteTable:
        payload = _payload(row)
        common = _common(row)
        table_id = str(common["resource_id"]).casefold()
        return RouteTable(
            **common,
            routes=tuple(routes_by_table.get(table_id, ())),
            subnet_ids=_strings(_get(row, payload, "subnetIds", "subnet_ids")),
            disable_bgp_route_propagation=_bool(
                _get(row, payload, "disableBgpRoutePropagation", "disable_bgp_route_propagation")
            ),
        )

    def _peering(self, row: Mapping[str, Any]) -> VNetPeering:
        payload = _payload(row)
        return VNetPeering(
            **_common(row),
            local_vnet_id=_get(row, payload, "localVnetId", "local_vnet_id", default=""),
            remote_vnet_id=_get(row, payload, "remoteVnetId", "remote_vnet_id", default=""),
            peering_state=_get(row, payload, "peeringState", "peering_state", default=""),
            gateway_flags_observed=_bool(_get(
                row, payload, "gatewayFlagsObserved", "gateway_flags_observed",
                default=not isinstance(payload.get("properties"), dict) and all(
                    isinstance(_get(row, payload, *keys), bool) for keys in (
                        ("allowGatewayTransit", "allow_gateway_transit"),
                        ("useRemoteGateways", "use_remote_gateways"),
                    )
                ),
            )),
            allow_forwarded_traffic=_bool(
                _get(row, payload, "allowForwardedTraffic", "allow_forwarded_traffic")
            ),
            allow_gateway_transit=_bool(
                _get(row, payload, "allowGatewayTransit", "allow_gateway_transit")
            ),
            use_remote_gateways=_bool(
                _get(row, payload, "useRemoteGateways", "use_remote_gateways")
            ),
            allow_virtual_network_access=_bool(
                _get(row, payload, "allowVirtualNetworkAccess", "allow_virtual_network_access", default=True)
            ),
        )

    def _firewall(self, row: Mapping[str, Any]) -> AzureFirewall:
        payload = _payload(row)
        return AzureFirewall(
            **_common(row),
            vnet_id=_get(row, payload, "vnetId", "vnet_id", default=""),
            subnet_id=_get(row, payload, "subnetId", "subnet_id", default=""),
            policy_id=_get(row, payload, "policyId", "policy_id", default=""),
            private_ip=_get(row, payload, "privateIp", "private_ip", default=""),
            public_ips=_strings(_get(row, payload, "publicIps", "public_ips")),
            sku_tier=_get(row, payload, "skuTier", "sku_tier", default=""),
        )

    def _firewall_policy(self, row: Mapping[str, Any]) -> FirewallPolicy:
        payload = _payload(row)
        return FirewallPolicy(
            **_common(row),
            firewall_ids=_strings(_get(row, payload, "firewallIds", "firewall_ids")),
            collection_ids=_strings(_get(row, payload, "collectionIds", "collection_ids")),
            base_policy_id=_get(row, payload, "basePolicyId", "base_policy_id", default=""),
            threat_intel_mode=_get(row, payload, "threatIntelMode", "threat_intel_mode", default=""),
        )

    def _firewall_rule(self, row: Mapping[str, Any]) -> FirewallRule:
        payload = _payload(row)
        return FirewallRule(
            **_common(row),
            collection_id=_get(row, payload, "collectionId", "collection_id", default=""),
            rule_type=_get(row, payload, "ruleType", "rule_type", default="NetworkRule"),
            action=_get(row, payload, "action", default="Allow"),
            protocols=_strings(_get(row, payload, "protocols")),
            source_addresses=_strings(_get(row, payload, "sourceAddresses", "source_addresses")),
            destination_addresses=_strings(
                _get(row, payload, "destinationAddresses", "destination_addresses")
            ),
            destination_ports=_strings(_get(row, payload, "destinationPorts", "destination_ports")),
            destination_fqdns=_strings(_get(row, payload, "destinationFqdns", "destination_fqdns")),
            fqdn_tags=_strings(_get(row, payload, "fqdnTags", "fqdn_tags")),
            source_ip_groups=_strings(_get(row, payload, "sourceIpGroups", "source_ip_groups")),
            destination_ip_groups=_strings(
                _get(row, payload, "destinationIpGroups", "destination_ip_groups")
            ),
        )

    def _firewall_collection(
        self, row: Mapping[str, Any], rules_by_collection: Mapping[str, list[FirewallRule]]
    ) -> FirewallRuleCollection:
        payload = _payload(row)
        common = _common(row)
        collection_id = str(common["resource_id"]).casefold()
        return FirewallRuleCollection(
            **common,
            policy_id=_get(row, payload, "policyId", "policy_id", default=""),
            firewall_id=_get(row, payload, "firewallId", "firewall_id", default=""),
            group_priority=_int(_get(row, payload, "groupPriority", "group_priority", default=0)),
            priority=_int(_get(row, payload, "priority", default=0)),
            action=_get(row, payload, "action", default="Allow"),
            collection_type=_get(
                row, payload, "collectionType", "collection_type", default="NetworkRuleCollection"
            ),
            rules=tuple(rules_by_collection.get(collection_id, ())),
        )

    def _private_endpoint(self, row: Mapping[str, Any]) -> PrivateEndpoint:
        payload = _payload(row)
        return PrivateEndpoint(
            **_common(row),
            subnet_id=_get(row, payload, "subnetId", "subnet_id", default=""),
            target_resource_id=_get(
                row, payload, "targetResourceId", "target_resource_id", default=""
            ),
            group_ids=_strings(_get(row, payload, "groupIds", "group_ids")),
            private_ips=_strings(_get(row, payload, "privateIps", "private_ips")),
            private_dns_zone_ids=_strings(
                _get(row, payload, "privateDnsZoneIds", "private_dns_zone_ids")
            ),
            connection_state=_get(row, payload, "connectionState", "connection_state", default=""),
        )

    def _private_dns_zone(self, row: Mapping[str, Any]) -> PrivateDnsZone:
        payload = _payload(row)
        return PrivateDnsZone(
            **_common(row),
            linked_vnet_ids=_strings(_get(row, payload, "linkedVnetIds", "linked_vnet_ids")),
            record_count=_int(_get(row, payload, "recordCount", "record_count", default=0)),
            zone_name=_get(row, payload, "zoneName", "zone_name", default=""),
        )

    def _gateway(self, row: Mapping[str, Any]) -> NetworkGateway:
        payload = _payload(row)
        common = _common(row)
        entity_type = _entity_type(row)
        if entity_type in ("", "NetworkGateway", "Resource"):
            # The ontology's generic bucket; recover the real kind from ARM so
            # the canvas does not draw every gateway as a VPN gateway.
            entity_type = GATEWAY_KIND_BY_RESOURCE_TYPE.get(_resource_type(row), "VpnGateway")
        return NetworkGateway(
            **common,
            entity_type=entity_type,
            vnet_id=_get(row, payload, "vnetId", "vnet_id", default=""),
            subnet_id=_get(row, payload, "subnetId", "subnet_id", default=""),
            gateway_type=_get(row, payload, "gatewayType", "gateway_type", default=""),
            sku=_get(row, payload, "sku", default=""),
            public_ips=_strings(_get(row, payload, "publicIps", "public_ips")),
            private_ips=_strings(_get(row, payload, "privateIps", "private_ips")),
            connected_circuit_ids=_strings(
                _get(row, payload, "connectedCircuitIds", "connected_circuit_ids")
            ),
        )

    def _load_balancer(self, row: Mapping[str, Any]) -> LoadBalancingResource:
        payload = _payload(row)
        common = _common(row)
        entity_type = _entity_type(row)
        if entity_type in ("", "LoadBalancer", "Resource"):
            entity_type = LOAD_BALANCER_KIND_BY_RESOURCE_TYPE.get(_resource_type(row), "LoadBalancer")
        backend_subnet_ids = _strings(_get(row, payload, "backendSubnetIds", "backend_subnet_ids"))
        if not backend_subnet_ids:
            backend_subnet_ids = _load_balancer_backend_subnets(payload)
        managed_resource_id = _get(row, payload, "managedResourceId", "managed_resource_id", default="")
        if not managed_resource_id:
            managed_resource_id = _tag_lookup(_tags(row, payload), "aca-managed-env-id", "managed-by-resource-id")
        return LoadBalancingResource(
            **common,
            entity_type=entity_type,
            vnet_id=_get(row, payload, "vnetId", "vnet_id", default=""),
            subnet_id=_get(row, payload, "subnetId", "subnet_id", default=""),
            sku=_get(row, payload, "sku", default=""),
            frontend_ips=_strings(_get(row, payload, "frontendIps", "frontend_ips")),
            public_ips=_strings(_get(row, payload, "publicIps", "public_ips")),
            backend_resource_ids=_strings(
                _get(row, payload, "backendResourceIds", "backend_resource_ids")
            ),
            backend_subnet_ids=backend_subnet_ids,
            waf_enabled=_bool(_get(row, payload, "wafEnabled", "waf_enabled")),
            managed_resource_id=managed_resource_id,
        )

    def _private_link_resource(self, row: Mapping[str, Any]) -> PrivateLinkResource:
        payload = _payload(row)
        common = _common(row)
        resource_type = _resource_type(row)
        return PrivateLinkResource(
            **common,
            service_kind=PRIVATE_LINK_RESOURCE_TYPES.get(resource_type, ""),
            resource_type=resource_type,
            public_network_access=str(
                _get(
                    row,
                    payload,
                    "publicNetworkAccess",
                    "public_network_access",
                    default=common["properties"].get("publicNetworkAccess", ""),
                )
                or ""
            ),
        )


def _observed_at(row: Mapping[str, Any]) -> str:
    """Reads whichever observation stamp the ontology row carries."""
    payload = _payload(row)
    return str(
        _get(
            row,
            payload,
            "last_observed_timestamp",
            "lastObservedTimestamp",
            "observed_at",
            "timestamp",
            default="",
        )
        or ""
    )


def _parse_observed_at(value: Any) -> datetime | None:
    """Parse an external observation stamp into an aware UTC instant."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _format_observed_at(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat().replace("+00:00", "Z")


def load_network_snapshot(
    rows: Iterable[Mapping[str, Any]],
    *,
    observed_at: str | None = None,
) -> NetworkSnapshot:
    """Convenience wrapper around :class:`NetworkSnapshotLoader`."""
    return NetworkSnapshotLoader().load(rows, observed_at=observed_at)
