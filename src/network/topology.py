"""Hub-spoke topology stitching across independently onboarded subscriptions.

Each subscription is ingested through its own connection and knows nothing of
its peers. A peering, however, names a remote VNet by full ARM ID — which
means once two connections have both synced, their peerings can be matched
into a single cross-subscription graph.

Hub classification is evidence-based and scored, never assumed from naming.
A VNet is a hub because it hosts shared infrastructure and terminates many
peerings, not because someone called it "hub".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .models import (
    AzureFirewall,
    FirewallRule,
    FirewallRuleCollection,
    NetworkSnapshot,
    SharedService,
    VNet,
)

#: Signals that promote a VNet to hub, and what each contributes.
HUB_SIGNAL_WEIGHTS: dict[str, float] = {
    "hosts_firewall": 4.0,
    "hosts_vpn_gateway": 3.0,
    "hosts_expressroute": 3.0,
    "allows_gateway_transit": 2.5,
    "hosts_bastion": 1.5,
    "hosts_dns_resolver": 1.5,
    "many_peerings": 2.0,
    "name_suggests_hub": 0.5,
}

#: A VNet needs this much evidence before it is treated as a hub.
HUB_SCORE_THRESHOLD = 3.0

#: Peerings above this count count as "many".
MANY_PEERINGS_THRESHOLD = 2

SHARED_SERVICE_KINDS: dict[str, str] = {
    "AzureFirewall": "firewall",
    "VpnGateway": "vpn",
    "ExpressRouteGateway": "expressroute",
    "Bastion": "bastion",
    "DnsResolver": "dns",
    "NatGateway": "egress",
}


@dataclass(frozen=True)
class PeeringLink:
    """A peering relationship resolved from one or both directions.

    ``is_bidirectional`` is what distinguishes working connectivity from a
    half-configured peering, which is a common and silent outage cause.
    """

    local_vnet_id: str
    remote_vnet_id: str
    local_connection_id: str
    remote_connection_id: str
    is_bidirectional: bool
    local_state: str
    remote_state: str
    allow_forwarded_traffic: bool
    allow_gateway_transit: bool
    use_remote_gateways: bool
    remote_vnet_observed: bool

    @property
    def is_healthy(self) -> bool:
        return (
            self.is_bidirectional
            and self.local_state.casefold() == "connected"
            and self.remote_state.casefold() == "connected"
        )

    @property
    def is_cross_subscription(self) -> bool:
        return bool(
            self.local_connection_id
            and self.remote_connection_id
            and self.local_connection_id != self.remote_connection_id
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "local_vnet_id": self.local_vnet_id,
            "remote_vnet_id": self.remote_vnet_id,
            "local_connection_id": self.local_connection_id,
            "remote_connection_id": self.remote_connection_id,
            "is_bidirectional": self.is_bidirectional,
            "is_healthy": self.is_healthy,
            "is_cross_subscription": self.is_cross_subscription,
            "local_state": self.local_state,
            "remote_state": self.remote_state,
            "allow_forwarded_traffic": self.allow_forwarded_traffic,
            "allow_gateway_transit": self.allow_gateway_transit,
            "use_remote_gateways": self.use_remote_gateways,
            "remote_vnet_observed": self.remote_vnet_observed,
        }


@dataclass(frozen=True)
class HubClassification:
    vnet_id: str
    name: str
    role: str
    score: float
    signals: tuple[str, ...]
    connection_id: str
    subscription_id: str
    peer_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "vnet_id": self.vnet_id,
            "name": self.name,
            "role": self.role,
            "score": round(self.score, 2),
            "signals": list(self.signals),
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "peer_count": self.peer_count,
        }


@dataclass(frozen=True)
class NetworkTopology:
    """The stitched cross-subscription hub-spoke graph."""

    classifications: tuple[HubClassification, ...] = ()
    links: tuple[PeeringLink, ...] = ()
    shared_services: tuple[SharedService, ...] = ()
    unresolved_peer_vnet_ids: tuple[str, ...] = ()
    connection_ids: tuple[str, ...] = ()
    snapshot: NetworkSnapshot = field(default_factory=NetworkSnapshot)
    semantic_relationships: tuple[dict[str, Any], ...] = ()

    @property
    def hubs(self) -> tuple[HubClassification, ...]:
        return tuple(item for item in self.classifications if item.role == "hub")

    @property
    def spokes(self) -> tuple[HubClassification, ...]:
        return tuple(item for item in self.classifications if item.role == "spoke")

    @property
    def isolated(self) -> tuple[HubClassification, ...]:
        return tuple(item for item in self.classifications if item.role == "isolated")

    def role_of(self, vnet_id: str) -> str:
        target = str(vnet_id or "").casefold()
        for item in self.classifications:
            if item.vnet_id == target:
                return item.role
        return "unknown"

    def peers_of(self, vnet_id: str) -> tuple[str, ...]:
        target = str(vnet_id or "").casefold()
        peers = {
            link.remote_vnet_id
            for link in self.links
            if link.local_vnet_id == target
        } | {
            link.local_vnet_id
            for link in self.links
            if link.remote_vnet_id == target
        }
        return tuple(sorted(peers))

    def hub_for(self, vnet_id: str) -> str:
        """The hub a spoke peers with, or ``""`` when it peers with none."""
        hub_ids = {hub.vnet_id for hub in self.hubs}
        for peer in self.peers_of(vnet_id):
            if peer in hub_ids:
                return peer
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "hubs": [hub.to_dict() for hub in self.hubs],
            "spokes": [spoke.to_dict() for spoke in self.spokes],
            "isolated": [item.to_dict() for item in self.isolated],
            "links": [link.to_dict() for link in self.links],
            "shared_services": [service.to_dict() for service in self.shared_services],
            "resources": _topology_resources(self),
            "relationships": _topology_relationships(self),
            "unresolved_peer_vnet_ids": list(self.unresolved_peer_vnet_ids),
            "connection_ids": list(self.connection_ids),
            "counts": self.snapshot.counts(),
        }


class TopologyBuilder:
    """Stitches per-connection snapshots into one hub-spoke topology."""

    def __init__(
        self,
        *,
        hub_score_threshold: float = HUB_SCORE_THRESHOLD,
        many_peerings_threshold: int = MANY_PEERINGS_THRESHOLD,
    ) -> None:
        self.hub_score_threshold = hub_score_threshold
        self.many_peerings_threshold = many_peerings_threshold

    def build(
        self,
        snapshot: NetworkSnapshot,
        semantic_relationships: tuple[dict[str, Any], ...] = (),
    ) -> NetworkTopology:
        vnets = {vnet.resource_id: vnet for vnet in snapshot.vnets}
        links = self._stitch_peerings(snapshot, vnets)
        peer_counts = self._peer_counts(links)
        shared_services = self._shared_services(snapshot, vnets)
        classifications = self._classify(snapshot, vnets, peer_counts, links)

        unresolved = sorted(
            {
                link.remote_vnet_id
                for link in links
                if not link.remote_vnet_observed and link.remote_vnet_id
            }
        )
        shared_services = self._attach_consumers(shared_services, classifications, links)

        return NetworkTopology(
            classifications=tuple(classifications),
            links=tuple(links),
            shared_services=tuple(shared_services),
            unresolved_peer_vnet_ids=tuple(unresolved),
            connection_ids=snapshot.connection_ids(),
            snapshot=snapshot,
            semantic_relationships=semantic_relationships,
        )

    def _stitch_peerings(
        self, snapshot: NetworkSnapshot, vnets: dict[str, VNet]
    ) -> list[PeeringLink]:
        """Matches peerings by (local, remote) VNet pair across connections."""
        by_pair: dict[tuple[str, str], Any] = {}
        for peering in snapshot.peerings:
            if not peering.local_vnet_id or not peering.remote_vnet_id:
                continue
            by_pair[(peering.local_vnet_id, peering.remote_vnet_id)] = peering

        seen: set[tuple[str, str]] = set()
        links: list[PeeringLink] = []
        for (local_id, remote_id), peering in sorted(by_pair.items()):
            canonical = tuple(sorted((local_id, remote_id)))
            if canonical in seen:
                continue
            seen.add(canonical)
            reverse = by_pair.get((remote_id, local_id))
            local_vnet = vnets.get(local_id)
            remote_vnet = vnets.get(remote_id)
            links.append(
                PeeringLink(
                    local_vnet_id=local_id,
                    remote_vnet_id=remote_id,
                    local_connection_id=(local_vnet.connection_id if local_vnet else peering.connection_id),
                    remote_connection_id=(remote_vnet.connection_id if remote_vnet else ""),
                    is_bidirectional=reverse is not None,
                    local_state=peering.peering_state,
                    remote_state=(reverse.peering_state if reverse else ""),
                    allow_forwarded_traffic=peering.allow_forwarded_traffic
                    or bool(reverse and reverse.allow_forwarded_traffic),
                    allow_gateway_transit=peering.allow_gateway_transit
                    or bool(reverse and reverse.allow_gateway_transit),
                    use_remote_gateways=peering.use_remote_gateways
                    or bool(reverse and reverse.use_remote_gateways),
                    remote_vnet_observed=remote_id in vnets,
                )
            )
        return links

    def _peer_counts(self, links: list[PeeringLink]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for link in links:
            counts[link.local_vnet_id] += 1
            counts[link.remote_vnet_id] += 1
        return dict(counts)

    def _shared_services(
        self, snapshot: NetworkSnapshot, vnets: dict[str, VNet]
    ) -> list[SharedService]:
        """Promotes hub-hosted infrastructure into addressable shared services."""
        services: list[SharedService] = []

        def vnet_of(subnet_id: str, fallback: str) -> str:
            if "/subnets/" in subnet_id:
                return subnet_id.split("/subnets/", 1)[0]
            return fallback

        for firewall in snapshot.firewalls:
            host = vnet_of(firewall.subnet_id, firewall.vnet_id)
            services.append(
                SharedService(
                    resource_id=f"{firewall.resource_id}/sharedservice",
                    name=firewall.name,
                    subscription_id=firewall.subscription_id,
                    resource_group=firewall.resource_group,
                    location=firewall.location,
                    connection_id=firewall.connection_id,
                    environment=firewall.environment,
                    business_service=firewall.business_service,
                    application=firewall.application,
                    owner=firewall.owner,
                    tags=dict(firewall.tags),
                    service_kind="firewall",
                    provider_resource_id=firewall.resource_id,
                    hub_vnet_id=host,
                )
            )

        for gateway in snapshot.gateways:
            kind = SHARED_SERVICE_KINDS.get(gateway.entity_type)
            if not kind:
                continue
            host = vnet_of(gateway.subnet_id, gateway.vnet_id)
            services.append(
                SharedService(
                    resource_id=f"{gateway.resource_id}/sharedservice",
                    name=gateway.name,
                    subscription_id=gateway.subscription_id,
                    resource_group=gateway.resource_group,
                    location=gateway.location,
                    connection_id=gateway.connection_id,
                    environment=gateway.environment,
                    business_service=gateway.business_service,
                    application=gateway.application,
                    owner=gateway.owner,
                    tags=dict(gateway.tags),
                    service_kind=kind,
                    provider_resource_id=gateway.resource_id,
                    hub_vnet_id=host,
                )
            )

        for zone in snapshot.private_dns_zones:
            if not zone.linked_vnet_ids:
                continue
            services.append(
                SharedService(
                    resource_id=f"{zone.resource_id}/sharedservice",
                    name=zone.zone_name or zone.name,
                    subscription_id=zone.subscription_id,
                    resource_group=zone.resource_group,
                    location=zone.location,
                    connection_id=zone.connection_id,
                    tags=dict(zone.tags),
                    service_kind="private_dns",
                    provider_resource_id=zone.resource_id,
                    hub_vnet_id=zone.linked_vnet_ids[0],
                    consumer_vnet_ids=zone.linked_vnet_ids,
                )
            )

        return services

    def _classify(
        self,
        snapshot: NetworkSnapshot,
        vnets: dict[str, VNet],
        peer_counts: dict[str, int],
        links: list[PeeringLink],
    ) -> list[HubClassification]:
        firewall_vnets = {
            firewall.subnet_id.split("/subnets/", 1)[0] if "/subnets/" in firewall.subnet_id else firewall.vnet_id
            for firewall in snapshot.firewalls
        }
        gateway_vnets: dict[str, set[str]] = defaultdict(set)
        for gateway in snapshot.gateways:
            host = (
                gateway.subnet_id.split("/subnets/", 1)[0]
                if "/subnets/" in gateway.subnet_id
                else gateway.vnet_id
            )
            if host:
                gateway_vnets[host].add(gateway.entity_type)

        transit_vnets = {
            link.local_vnet_id if link.allow_gateway_transit else ""
            for link in links
            if link.allow_gateway_transit
        } - {""}

        results: list[HubClassification] = []
        for vnet_id, vnet in sorted(vnets.items()):
            signals: list[str] = []
            score = 0.0

            if vnet_id in firewall_vnets:
                signals.append("hosts_firewall")
            kinds = gateway_vnets.get(vnet_id, set())
            if "VpnGateway" in kinds:
                signals.append("hosts_vpn_gateway")
            if "ExpressRouteGateway" in kinds:
                signals.append("hosts_expressroute")
            if "Bastion" in kinds:
                signals.append("hosts_bastion")
            if "DnsResolver" in kinds:
                signals.append("hosts_dns_resolver")
            if vnet_id in transit_vnets:
                signals.append("allows_gateway_transit")
            peer_count = peer_counts.get(vnet_id, 0)
            if peer_count >= self.many_peerings_threshold:
                signals.append("many_peerings")
            if "hub" in vnet.name.casefold() or "shared" in vnet.name.casefold():
                signals.append("name_suggests_hub")

            for signal in signals:
                score += HUB_SIGNAL_WEIGHTS.get(signal, 0.0)

            if score >= self.hub_score_threshold:
                role = "hub"
            elif peer_count > 0:
                role = "spoke"
            else:
                role = "isolated"

            results.append(
                HubClassification(
                    vnet_id=vnet_id,
                    name=vnet.name,
                    role=role,
                    score=score,
                    signals=tuple(signals),
                    connection_id=vnet.connection_id,
                    subscription_id=vnet.subscription_id,
                    peer_count=peer_count,
                )
            )
        return results

    def _attach_consumers(
        self,
        services: list[SharedService],
        classifications: list[HubClassification],
        links: list[PeeringLink],
    ) -> list[SharedService]:
        """Records which spokes reach each hub-hosted shared service."""
        peers: dict[str, set[str]] = defaultdict(set)
        for link in links:
            peers[link.local_vnet_id].add(link.remote_vnet_id)
            peers[link.remote_vnet_id].add(link.local_vnet_id)
        spoke_ids = {item.vnet_id for item in classifications if item.role == "spoke"}

        resolved: list[SharedService] = []
        for service in services:
            if service.consumer_vnet_ids:
                resolved.append(service)
                continue
            consumers = sorted(peers.get(service.hub_vnet_id, set()) & spoke_ids)
            resolved.append(
                SharedService(
                    resource_id=service.resource_id,
                    name=service.name,
                    subscription_id=service.subscription_id,
                    resource_group=service.resource_group,
                    location=service.location,
                    connection_id=service.connection_id,
                    environment=service.environment,
                    business_service=service.business_service,
                    application=service.application,
                    owner=service.owner,
                    tags=dict(service.tags),
                    service_kind=service.service_kind,
                    provider_resource_id=service.provider_resource_id,
                    hub_vnet_id=service.hub_vnet_id,
                    consumer_vnet_ids=tuple(consumers),
                )
            )
        return resolved


def build_topology(snapshot: NetworkSnapshot) -> NetworkTopology:
    """Convenience wrapper around :class:`TopologyBuilder`."""
    return TopologyBuilder().build(snapshot)


def _resource_payload(resource: Any) -> dict[str, Any]:
    return resource.to_dict() if hasattr(resource, "to_dict") else dict(resource)


def _resource_node(resource: Any, *, role: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _resource_payload(resource)
    return {
        "id": resource.resource_id,
        "name": resource.name,
        "entity_type": resource.entity_type,
        "role": role,
        "subscription_id": resource.subscription_id,
        "resource_group": resource.resource_group,
        "location": resource.location,
        "connection_id": resource.connection_id,
        "environment": resource.environment,
        "business_service": resource.business_service,
        "application": resource.application,
        "owner": resource.owner,
        "tags": dict(resource.tags),
        "details": {**payload, **(details or {})},
    }


def _rule_summary(rule: FirewallRule) -> dict[str, Any]:
    return {
        "id": rule.resource_id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "action": rule.action,
        "protocols": list(rule.protocols),
        "source_addresses": list(rule.source_addresses),
        "destination_addresses": list(rule.destination_addresses),
        "destination_ports": list(rule.destination_ports),
        "destination_fqdns": list(rule.destination_fqdns),
        "source_ip_groups": list(rule.source_ip_groups),
    }


def _nsg_rule_summary(rule: Any) -> dict[str, Any]:
    return {
        "id": rule.resource_id,
        "name": rule.name,
        "priority": rule.priority,
        "direction": rule.direction,
        "access": rule.access,
        "protocol": rule.protocol,
        "source_address": rule.source_address,
        "destination_address": rule.destination_address,
        "source_port": rule.source_port,
        "destination_port": rule.destination_port,
        "description": rule.description,
        "is_default": rule.is_default,
    }


def _firewall_rules_for(
    firewall: AzureFirewall,
    collections_by_firewall: dict[str, tuple[FirewallRuleCollection, ...]],
    collections_by_policy: dict[str, tuple[FirewallRuleCollection, ...]],
) -> list[dict[str, Any]]:
    collections = list(collections_by_firewall.get(firewall.resource_id, ()))
    if firewall.policy_id:
        collections.extend(collections_by_policy.get(firewall.policy_id, ()))
    deduped: dict[str, FirewallRule] = {}
    for collection in collections:
        for rule in collection.rules:
            deduped[rule.resource_id] = rule
    return [_rule_summary(rule) for rule in sorted(deduped.values(), key=lambda r: (r.name, r.resource_id))]


def _topology_resources(topology: NetworkTopology) -> list[dict[str, Any]]:
    snapshot = topology.snapshot
    role_by_vnet = {item.vnet_id: item.role for item in topology.classifications}
    collections_by_firewall: dict[str, tuple[FirewallRuleCollection, ...]] = defaultdict(tuple)
    collections_by_policy: dict[str, tuple[FirewallRuleCollection, ...]] = defaultdict(tuple)
    for collection in snapshot.firewall_collections:
        if collection.firewall_id:
            collections_by_firewall[collection.firewall_id] += (collection,)
        if collection.policy_id:
            collections_by_policy[collection.policy_id] += (collection,)

    nodes: list[dict[str, Any]] = []
    nodes.extend(_resource_node(vnet, role=role_by_vnet.get(vnet.resource_id, "unknown")) for vnet in snapshot.vnets)
    nodes.extend(_resource_node(subnet) for subnet in snapshot.subnets)
    nodes.extend(_resource_node(nic) for nic in snapshot.nics)
    nodes.extend(
        _resource_node(
            nsg,
            details={
                "rules": [_nsg_rule_summary(rule) for rule in nsg.ordered_rules()],
                "custom_rule_count": len([rule for rule in nsg.rules if not rule.is_default]),
                "effective_rule_count": len(nsg.effective_rules()),
            },
        )
        for nsg in snapshot.nsgs
    )
    nodes.extend(_resource_node(rule) for nsg in snapshot.nsgs for rule in nsg.rules)
    nodes.extend(
        _resource_node(
            table,
            details={
                "routes": [route.to_dict() for route in table.routes],
                "route_count": len(table.routes),
            },
        )
        for table in snapshot.route_tables
    )
    nodes.extend(_resource_node(route) for table in snapshot.route_tables for route in table.routes)
    nodes.extend(_resource_node(peering) for peering in snapshot.peerings)
    nodes.extend(
        _resource_node(
            firewall,
            details={
                "rules": _firewall_rules_for(firewall, collections_by_firewall, collections_by_policy),
                "rule_count": len(_firewall_rules_for(firewall, collections_by_firewall, collections_by_policy)),
            },
        )
        for firewall in snapshot.firewalls
    )
    nodes.extend(
        _resource_node(
            policy,
            details={
                "rule_collections": [collection.to_dict() for collection in collections_by_policy.get(policy.resource_id, ())],
                "rule_count": sum(len(collection.rules) for collection in collections_by_policy.get(policy.resource_id, ())),
            },
        )
        for policy in snapshot.firewall_policies
    )
    nodes.extend(
        _resource_node(
            collection,
            details={
                "rules": [_rule_summary(rule) for rule in collection.rules],
                "rule_count": len(collection.rules),
            },
        )
        for collection in snapshot.firewall_collections
    )
    nodes.extend(_resource_node(rule) for collection in snapshot.firewall_collections for rule in collection.rules)
    nodes.extend(_resource_node(endpoint) for endpoint in snapshot.private_endpoints)
    nodes.extend(_resource_node(zone) for zone in snapshot.private_dns_zones)
    nodes.extend(_resource_node(gateway) for gateway in snapshot.gateways)
    nodes.extend(_resource_node(lb) for lb in snapshot.load_balancers)
    nodes.extend(_attached_workload_nodes(snapshot))
    nodes = _disambiguate_duplicate_names(nodes)
    return sorted(nodes, key=lambda node: (node["entity_type"], node["name"], node["id"]))


def _disambiguate_duplicate_names(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Appends a resource-group suffix to nodes that share an identical name.

    Azure lets unrelated resources reuse the same name across resource
    groups/subscriptions - most commonly the ``capp-svc-lb`` internal load
    balancer that every Container Apps managed environment creates. Without a
    disambiguator, the canvas renders indistinguishable nodes that the user
    can only tell apart by clicking each one.
    """
    counts: dict[str, int] = {}
    for node in nodes:
        counts[node["name"]] = counts.get(node["name"], 0) + 1
    for node in nodes:
        if counts.get(node["name"], 0) <= 1:
            continue
        suffix = node["resource_group"] or (node["subscription_id"][:8] if node["subscription_id"] else "")
        if suffix:
            node["name"] = f"{node['name']} ({suffix})"
    return nodes


#: Workloads a NIC or private endpoint attaches to are not network resources, so
#: they never appear in the network snapshot. The topology still needs them as
#: endpoints, otherwise a NIC looks like it serves nothing and a private
#: endpoint hides the PaaS service it was created to reach. Naming the ARM type
#: lets the canvas draw the real service glyph instead of a generic box.
_WORKLOAD_ENTITY_TYPE_BY_PROVIDER = {
    "microsoft.compute/virtualmachines": "VirtualMachine",
    "microsoft.compute/virtualmachinescalesets": "VirtualMachineScaleSet",
    "microsoft.documentdb/databaseaccounts": "CosmosDb",
    "microsoft.dbforpostgresql/flexibleservers": "PostgreSqlServer",
    "microsoft.dbforpostgresql/servers": "PostgreSqlServer",
    "microsoft.sql/servers": "SqlServer",
    "microsoft.keyvault/vaults": "KeyVault",
    "microsoft.storage/storageaccounts": "StorageAccount",
    "microsoft.containerregistry/registries": "ContainerRegistry",
    "microsoft.app/managedenvironments": "ContainerAppEnvironment",
    "microsoft.web/sites": "AppService",
}


def _attached_workload_nodes(snapshot: NetworkSnapshot) -> list[dict[str, Any]]:
    """Builds placeholder nodes for the workloads that network resources serve."""
    known = {resource.resource_id for resource in (*snapshot.nics, *snapshot.private_endpoints)}
    known |= {vnet.resource_id for vnet in snapshot.vnets}
    targets: dict[str, str] = {}
    for nic in snapshot.nics:
        if nic.attached_resource_id:
            targets.setdefault(nic.attached_resource_id, nic.connection_id)
    for endpoint in snapshot.private_endpoints:
        if endpoint.target_resource_id:
            targets.setdefault(endpoint.target_resource_id, endpoint.connection_id)
    for lb in snapshot.load_balancers:
        if lb.managed_resource_id:
            targets.setdefault(lb.managed_resource_id, lb.connection_id)

    nodes: list[dict[str, Any]] = []
    for resource_id, connection_id in targets.items():
        if resource_id in known:
            continue
        nodes.append(_workload_node(resource_id, connection_id))
    return nodes


def _workload_node(resource_id: str, connection_id: str) -> dict[str, Any]:
    segments = resource_id.strip("/").split("/")
    name = segments[-1] if segments else resource_id
    provider = "/".join(segments[-3:-1]).casefold() if len(segments) >= 3 else ""
    entity_type = _WORKLOAD_ENTITY_TYPE_BY_PROVIDER.get(provider) or "AttachedWorkload"
    subscription_id = segments[1] if len(segments) > 1 and segments[0].casefold() == "subscriptions" else ""
    resource_group = segments[3] if len(segments) > 3 and segments[2].casefold() == "resourcegroups" else ""
    return {
        "id": resource_id,
        "name": name,
        "entity_type": entity_type,
        "role": "",
        "subscription_id": subscription_id,
        "resource_group": resource_group,
        "location": "",
        "connection_id": connection_id,
        "environment": "",
        "business_service": "",
        "application": "",
        "owner": "",
        "tags": {},
        "details": {"resource_id": resource_id, "name": name, "resource_type": provider},
    }


def _relationship(
    source: str,
    target: str,
    relationship_type: str,
    *,
    label: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{relationship_type}:{source}::{target}",
        "source": source,
        "target": target,
        "relationship_type": relationship_type,
        "label": label or relationship_type.replace("_", " "),
        "details": details or {},
    }


def _has_resource(resource_ids: set[str], resource_id: str) -> bool:
    return bool(resource_id and resource_id in resource_ids)


def _topology_relationships(topology: NetworkTopology) -> list[dict[str, Any]]:
    snapshot = topology.snapshot
    resource_ids = {node["id"] for node in _topology_resources(topology)}
    relationships: dict[str, dict[str, Any]] = {}

    def add(source: str, target: str, relationship_type: str, *, label: str = "", details: dict[str, Any] | None = None) -> None:
        if not (_has_resource(resource_ids, source) and _has_resource(resource_ids, target)):
            return
        relationship = _relationship(source, target, relationship_type, label=label, details=details)
        relationships[relationship["id"]] = relationship

    def add_hosted(resource: Any, label: str) -> None:
        """Links a subnet-deployed service to its most specific container.

        A firewall, gateway or load balancer sits in a subnet, which the VNet
        already contains. Drawing the VNet edge as well duplicates a path that
        the graph expresses more precisely, so the VNet is only used when the
        subnet is unknown or absent from the graph.
        """
        if _has_resource(resource_ids, resource.subnet_id):
            add(resource.subnet_id, resource.resource_id, "hosts", label=label)
            return
        add(resource.vnet_id, resource.resource_id, "hosts", label=label)

    predicate_map = {
        "attachedto": "attached_to",
        "loadbalances": "load_balances",
        "hosts": "hosts",
    }
    for semantic in topology.semantic_relationships:
        predicate = str(semantic.get("predicate") or "").casefold()
        relationship_type = predicate_map.get(predicate)
        if relationship_type:
            add(
                str(semantic.get("subject_id") or ""),
                str(semantic.get("object_id") or ""),
                relationship_type,
                label=relationship_type.replace("_", " "),
                details={"source": "aiops_semantic_graph", "confidence": semantic.get("confidence")},
            )

    for vnet in snapshot.vnets:
        for subnet_id in vnet.subnet_ids:
            add(vnet.resource_id, subnet_id, "contains", label="contains subnet")
        for peering_id in vnet.peering_ids:
            add(vnet.resource_id, peering_id, "has_peering", label="has peering")

    for peering in snapshot.peerings:
        add(peering.local_vnet_id, peering.resource_id, "has_peering", label="has peering", details=peering.to_dict())
        add(peering.resource_id, peering.remote_vnet_id, "peers_with", label="peers with VNet", details=peering.to_dict())

    for subnet in snapshot.subnets:
        add(subnet.vnet_id, subnet.resource_id, "contains", label="contains subnet")
        add(subnet.resource_id, subnet.nsg_id, "protected_by", label="protected by NSG")
        add(subnet.resource_id, subnet.route_table_id, "routed_by", label="routed by route table")
        add(subnet.resource_id, subnet.nat_gateway_id, "egresses_via", label="egresses via NAT")
        for endpoint_id in subnet.private_endpoint_ids:
            add(subnet.resource_id, endpoint_id, "hosts", label="hosts private endpoint")

    for nic in snapshot.nics:
        add(nic.subnet_id, nic.resource_id, "hosts", label="hosts NIC")
        add(nic.resource_id, nic.nsg_id, "protected_by", label="protected by NSG")
        add(nic.resource_id, nic.attached_resource_id, "attached_to", label="attached to workload")

    for nsg in snapshot.nsgs:
        for rule in nsg.rules:
            add(nsg.resource_id, rule.resource_id, "has_rule", label="has NSG rule", details=_nsg_rule_summary(rule))
        for subnet_id in nsg.subnet_ids:
            add(subnet_id, nsg.resource_id, "protected_by", label="protected by NSG")
        for nic_id in nsg.nic_ids:
            add(nic_id, nsg.resource_id, "protected_by", label="protected by NSG")

    # A virtual-appliance route points at an IP, not a resource id. Resolving it
    # against the firewalls in the estate turns "next hop 10.0.2.4" into a real
    # edge to the appliance that actually receives the traffic.
    firewall_by_private_ip = {
        firewall.private_ip: firewall.resource_id for firewall in snapshot.firewalls if firewall.private_ip
    }

    for table in snapshot.route_tables:
        for route in table.routes:
            add(table.resource_id, route.resource_id, "has_route", label="has route", details=route.to_dict())
            next_hop_id = firewall_by_private_ip.get(route.next_hop_ip, "")
            add(
                route.resource_id,
                next_hop_id,
                "next_hop",
                label=f"next hop {route.next_hop_ip}",
                details=route.to_dict(),
            )
        for subnet_id in table.subnet_ids:
            add(subnet_id, table.resource_id, "routed_by", label="routed by route table")

    for firewall in snapshot.firewalls:
        add_hosted(firewall, "hosts firewall")
        add(firewall.resource_id, firewall.subnet_id, "attached_to", label="attached to subnet")
        add(firewall.resource_id, firewall.policy_id, "enforces_policy", label="enforces policy")

    for policy in snapshot.firewall_policies:
        for firewall_id in policy.firewall_ids:
            add(firewall_id, policy.resource_id, "enforces_policy", label="enforces policy")
        for collection_id in policy.collection_ids:
            add(policy.resource_id, collection_id, "has_rule_collection", label="has rule collection")

    for collection in snapshot.firewall_collections:
        add(collection.firewall_id, collection.resource_id, "has_rule_collection", label="has rule collection")
        add(collection.policy_id, collection.resource_id, "has_rule_collection", label="has rule collection")
        for rule in collection.rules:
            add(collection.resource_id, rule.resource_id, "has_rule", label="has firewall rule", details=_rule_summary(rule))

    for endpoint in snapshot.private_endpoints:
        add(endpoint.subnet_id, endpoint.resource_id, "hosts", label="hosts private endpoint")
        add(endpoint.resource_id, endpoint.subnet_id, "attached_to", label="attached to subnet")
        add(endpoint.resource_id, endpoint.target_resource_id, "connects_to", label="connects to service")
        for zone_id in endpoint.private_dns_zone_ids:
            add(endpoint.resource_id, zone_id, "uses_dns_zone", label="uses DNS zone")

    for zone in snapshot.private_dns_zones:
        for vnet_id in zone.linked_vnet_ids:
            add(zone.resource_id, vnet_id, "linked_to", label="linked to VNet")

    for gateway in snapshot.gateways:
        add_hosted(gateway, "hosts gateway")
        add(gateway.resource_id, gateway.subnet_id, "attached_to", label="attached to subnet")
        for circuit_id in gateway.connected_circuit_ids:
            add(gateway.resource_id, circuit_id, "connects_to", label="connects to circuit")

    if not topology.semantic_relationships:
        for lb in snapshot.load_balancers:
            add_hosted(lb, "hosts load balancer")
            add(lb.resource_id, lb.subnet_id, "attached_to", label="attached to subnet")
            for backend_id in lb.backend_resource_ids:
                add(lb.resource_id, backend_id, "load_balances", label="load balances")
            for backend_subnet_id in lb.backend_subnet_ids:
                add(lb.resource_id, backend_subnet_id, "load_balances", label="load balances subnet")
            if lb.managed_resource_id:
                add(lb.managed_resource_id, lb.resource_id, "hosts", label="uses internal load balancer")

    for service in topology.shared_services:
        for consumer_id in service.consumer_vnet_ids:
            add(
                service.provider_resource_id,
                consumer_id,
                "serves",
                label=f"serves VNet as {service.service_kind}",
                details=service.to_dict(),
            )

    # A private DNS zone linked to a VNet is also a shared service serving that
    # VNet, which emits the same pair of endpoints twice. The "serves" edge
    # carries the service detail, so the plainer link is dropped where both
    # describe the same connection.
    served_pairs = {
        (item["source"], item["target"]) for item in relationships.values() if item["relationship_type"] == "serves"
    }
    for key, item in list(relationships.items()):
        if item["relationship_type"] == "linked_to" and (item["source"], item["target"]) in served_pairs:
            del relationships[key]

    return sorted(relationships.values(), key=lambda item: (item["relationship_type"], item["source"], item["target"]))
