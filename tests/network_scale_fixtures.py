"""Deterministic, real-model network estates used by Phase 12 scale gates.

The presets intentionally exercise every collection currently projected by
``build_topology`` as well as ``private_link_resources``.  All resources are
constructed through the production dataclasses so their ``__post_init__``
normalisation remains part of every measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import cycle

from network.models import (
    AzureFirewall,
    FirewallPolicy,
    FirewallRule,
    FirewallRuleCollection,
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
)

DEFAULT_SUBSCRIPTIONS = ("00000000-0000-0000-0000-000000000001",)
OBSERVED_AT = "2026-01-01T00:00:00+00:00"


@dataclass(frozen=True)
class EstateShape:
    """The dimensions that dominate topology size."""

    vnets: int
    subnets_per_vnet: int
    nsgs: int
    rules_per_nsg: int
    target_full_nodes: int


SMALL = EstateShape(20, 3, 40, 25, 1_330)
MID = EstateShape(60, 6, 150, 30, 6_930)
ENTERPRISE = EstateShape(200, 8, 600, 40, 34_600)


def _arm(
    subscription_id: str,
    resource_group: str,
    provider: str,
    kind: str,
    name: str,
    *,
    mixed_case: bool,
    index: int,
) -> str:
    value = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/{provider}/{kind}/{name}"
    )
    if mixed_case and index % 11 == 0:
        return value.replace("/subscriptions/", "/SUBSCRIPTIONS/").replace(
            "/resourceGroups/", "/ResourceGroups/"
        )
    return value


def build_estate(
    shape: EstateShape,
    *,
    subscription_ids: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS,
    mixed_case_ids: bool = False,
    include_private_link_resources: bool = True,
) -> NetworkSnapshot:
    """Build a deterministic estate through production model constructors."""
    if not subscription_ids:
        raise ValueError("subscription_ids must contain at least one subscription")

    subscriptions = tuple(str(value).casefold() for value in subscription_ids)
    assignments = cycle(subscriptions)
    vnets: list[VNet] = []
    subnets: list[Subnet] = []
    nsg_subnets: list[list[str]] = [[] for _ in range(shape.nsgs)]
    route_subnets: list[list[str]] = [[] for _ in range(shape.vnets)]
    private_endpoints: list[PrivateEndpoint] = []
    private_link_resources: list[PrivateLinkResource] = []
    nics: list[NetworkInterface] = []
    dns_zones: list[PrivateDnsZone] = []

    vnet_specs: list[tuple[str, str, str, list[str]]] = []
    for vnet_index in range(shape.vnets):
        subscription_id = next(assignments)
        resource_group = f"rg-network-{vnet_index:04d}"
        vnet_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "virtualNetworks",
            f"vnet-{vnet_index:04d}",
            mixed_case=mixed_case_ids,
            index=vnet_index,
        )
        endpoint_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "privateEndpoints",
            f"pe-{vnet_index:04d}",
            mixed_case=mixed_case_ids,
            index=vnet_index,
        )
        subnet_ids: list[str] = []
        for subnet_offset in range(shape.subnets_per_vnet):
            subnet_index = vnet_index * shape.subnets_per_vnet + subnet_offset
            subnet_id = f"{vnet_id}/subnets/subnet-{subnet_offset:02d}"
            nsg_index = subnet_index % shape.nsgs
            route_index = vnet_index
            nsg_id = _arm(
                subscriptions[nsg_index % len(subscriptions)],
                f"rg-security-{nsg_index:04d}",
                "Microsoft.Network",
                "networkSecurityGroups",
                f"nsg-{nsg_index:04d}",
                mixed_case=mixed_case_ids,
                index=nsg_index,
            )
            route_id = _arm(
                subscription_id,
                resource_group,
                "Microsoft.Network",
                "routeTables",
                f"rt-{route_index:04d}",
                mixed_case=mixed_case_ids,
                index=route_index,
            )
            subnet_ids.append(subnet_id)
            nsg_subnets[nsg_index].append(subnet_id)
            route_subnets[route_index].append(subnet_id)
            subnets.append(
                Subnet(
                    resource_id=subnet_id,
                    name=f"subnet-{subnet_offset:02d}",
                    subscription_id=subscription_id,
                    resource_group=resource_group,
                    connection_id=f"conn-{subscription_id}",
                    vnet_id=vnet_id,
                    address_prefixes=(f"10.{vnet_index % 250}.{subnet_offset}.0/24",),
                    nsg_id=nsg_id,
                    route_table_id=route_id,
                    private_endpoint_ids=(endpoint_id,)
                    if mixed_case_ids and subnet_offset == 0
                    else (),
                )
            )
        vnet_specs.append((subscription_id, resource_group, vnet_id, subnet_ids))
        vnets.append(
            VNet(
                resource_id=vnet_id,
                name=f"vnet-{vnet_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                address_spaces=(f"10.{vnet_index % 250}.0.0/16",),
                subnet_ids=tuple(subnet_ids),
            )
        )

    nsgs: list[NetworkSecurityGroup] = []
    for nsg_index in range(shape.nsgs):
        subscription_id = subscriptions[nsg_index % len(subscriptions)]
        resource_group = f"rg-security-{nsg_index:04d}"
        nsg_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "networkSecurityGroups",
            f"nsg-{nsg_index:04d}",
            mixed_case=mixed_case_ids,
            index=nsg_index,
        )
        rules = tuple(
            NetworkSecurityRule(
                resource_id=f"{nsg_id}/securityRules/rule-{rule_index:04d}",
                name=f"rule-{rule_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                nsg_id=nsg_id,
                priority=100 + rule_index,
                direction="Inbound" if rule_index % 2 == 0 else "Outbound",
                access="Allow",
                protocol="Tcp",
                source_address=f"10.{nsg_index % 250}.0.0/16",
                destination_address="*",
                destination_port=str(1000 + (rule_index % 100)),
            )
            for rule_index in range(shape.rules_per_nsg)
        )
        nsgs.append(
            NetworkSecurityGroup(
                resource_id=nsg_id,
                name=f"nsg-{nsg_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                rules=rules,
                subnet_ids=tuple(nsg_subnets[nsg_index]),
            )
        )

    route_tables: list[RouteTable] = []
    for route_index, (subscription_id, resource_group, _, _) in enumerate(vnet_specs):
        route_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "routeTables",
            f"rt-{route_index:04d}",
            mixed_case=mixed_case_ids,
            index=route_index,
        )
        routes = tuple(
            Route(
                resource_id=f"{route_id}/routes/route-{item:02d}",
                name=f"route-{item:02d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                route_table_id=route_id,
                address_prefix=f"172.{item % 250}.0.0/16",
                next_hop_type="Internet",
            )
            for item in range(shape.subnets_per_vnet)
        )
        route_tables.append(
            RouteTable(
                resource_id=route_id,
                name=f"rt-{route_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                routes=routes,
                subnet_ids=tuple(route_subnets[route_index]),
            )
        )

    zone_count = max(1, shape.vnets // 5)
    for zone_index in range(zone_count):
        subscription_id, resource_group, vnet_id, _ = vnet_specs[zone_index]
        dns_zones.append(
            PrivateDnsZone(
                resource_id=_arm(
                    subscription_id,
                    resource_group,
                    "Microsoft.Network",
                    "privateDnsZones",
                    f"privatelink{zone_index:04d}.example.test",
                    mixed_case=mixed_case_ids,
                    index=zone_index,
                ),
                name=f"privatelink{zone_index:04d}.example.test",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                linked_vnet_ids=(vnet_id,),
                record_count=1,
            )
        )

    for endpoint_index, (subscription_id, resource_group, _, subnet_ids) in enumerate(vnet_specs):
        target_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Storage",
            "storageAccounts",
            f"storage{endpoint_index:04d}",
            mixed_case=mixed_case_ids,
            index=endpoint_index,
        )
        endpoint_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "privateEndpoints",
            f"pe-{endpoint_index:04d}",
            mixed_case=mixed_case_ids,
            index=endpoint_index,
        )
        zone_id = dns_zones[endpoint_index % len(dns_zones)].resource_id
        private_endpoints.append(
            PrivateEndpoint(
                resource_id=endpoint_id,
                name=f"pe-{endpoint_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                subnet_id=subnet_ids[0],
                target_resource_id=target_id,
                group_ids=("blob",),
                private_ips=(f"10.{endpoint_index % 250}.0.10",),
                private_dns_zone_ids=(zone_id,),
                connection_state="Approved",
            )
        )
        if include_private_link_resources:
            private_link_resources.append(
                PrivateLinkResource(
                    resource_id=target_id,
                    name=f"storage{endpoint_index:04d}",
                    subscription_id=subscription_id,
                    resource_group=resource_group,
                    connection_id=f"conn-{subscription_id}",
                    service_kind="Storage",
                    resource_type="Microsoft.Storage/storageAccounts",
                    public_network_access="Disabled",
                )
            )

    firewall_count = max(1, shape.vnets // 10)
    fixed_projected_nodes = (
        shape.vnets
        + shape.vnets * shape.subnets_per_vnet
        + shape.nsgs
        + shape.nsgs * shape.rules_per_nsg
        + shape.vnets
        + shape.vnets * shape.subnets_per_vnet
        + shape.vnets
        + zone_count
        + firewall_count * 3
        + shape.vnets  # one attached-workload node per private endpoint target
    )
    # Two rules per collection are sufficient to exercise policy projection.
    # Fill the remainder with NICs, whose flat payload keeps the enterprise
    # fixture practical while still creating real topology nodes and edges.
    firewall_rule_count = firewall_count * 2
    nic_count = shape.target_full_nodes - fixed_projected_nodes - firewall_rule_count
    if nic_count < 0:
        raise ValueError("target_full_nodes is too small for the requested estate shape")

    firewalls: list[AzureFirewall] = []
    firewall_policies: list[FirewallPolicy] = []
    firewall_collections: list[FirewallRuleCollection] = []
    for firewall_index in range(firewall_count):
        subscription_id, resource_group, vnet_id, subnet_ids = vnet_specs[firewall_index]
        firewall_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "azureFirewalls",
            f"fw-{firewall_index:04d}",
            mixed_case=mixed_case_ids,
            index=firewall_index,
        )
        policy_id = _arm(
            subscription_id,
            resource_group,
            "Microsoft.Network",
            "firewallPolicies",
            f"policy-{firewall_index:04d}",
            mixed_case=mixed_case_ids,
            index=firewall_index,
        )
        collection_id = f"{policy_id}/ruleCollectionGroups/default/ruleCollections/collection-{firewall_index:04d}"
        rules = tuple(
            FirewallRule(
                resource_id=f"{collection_id}/rules/rule-{rule_index:04d}",
                name=f"rule-{rule_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                collection_id=collection_id,
                protocols=("TCP",),
                source_addresses=(f"10.{firewall_index % 250}.0.0/16",),
                destination_addresses=("10.255.0.0/16",),
                destination_ports=(str(2000 + (rule_index % 100)),),
            )
            for rule_index in range(2)
        )
        firewalls.append(
            AzureFirewall(
                resource_id=firewall_id,
                name=f"fw-{firewall_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                vnet_id=vnet_id,
                subnet_id=subnet_ids[0],
                policy_id=policy_id,
                private_ip=f"10.{firewall_index % 250}.0.4",
                sku_tier="Premium",
            )
        )
        firewall_policies.append(
            FirewallPolicy(
                resource_id=policy_id,
                name=f"policy-{firewall_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                firewall_ids=(firewall_id,),
                collection_ids=(collection_id,),
                threat_intel_mode="Alert",
            )
        )
        firewall_collections.append(
            FirewallRuleCollection(
                resource_id=collection_id,
                name=f"collection-{firewall_index:04d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                policy_id=policy_id,
                firewall_id=firewall_id,
                priority=100,
                rules=rules,
            )
        )

    for nic_index in range(nic_count):
        subscription_id, resource_group, _, subnet_ids = vnet_specs[
            nic_index % len(vnet_specs)
        ]
        nics.append(
            NetworkInterface(
                resource_id=_arm(
                    subscription_id,
                    resource_group,
                    "Microsoft.Network",
                    "networkInterfaces",
                    f"nic-{nic_index:05d}",
                    mixed_case=mixed_case_ids,
                    index=nic_index,
                ),
                name=f"nic-{nic_index:05d}",
                subscription_id=subscription_id,
                resource_group=resource_group,
                connection_id=f"conn-{subscription_id}",
                subnet_id=subnet_ids[nic_index % len(subnet_ids)],
                private_ips=(f"10.{nic_index % 250}.{(nic_index // 250) % 250}.10",),
            )
        )

    return NetworkSnapshot(
        vnets=tuple(vnets),
        subnets=tuple(subnets),
        nics=tuple(nics),
        nsgs=tuple(nsgs),
        route_tables=tuple(route_tables),
        firewalls=tuple(firewalls),
        firewall_policies=tuple(firewall_policies),
        firewall_collections=tuple(firewall_collections),
        private_endpoints=tuple(private_endpoints),
        private_dns_zones=tuple(dns_zones),
        private_link_resources=tuple(private_link_resources),
        observed_at=OBSERVED_AT,
    )


def small_estate(
    *, subscription_ids: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS, mixed_case_ids: bool = False
) -> NetworkSnapshot:
    return build_estate(SMALL, subscription_ids=subscription_ids, mixed_case_ids=mixed_case_ids)


def mid_estate(
    *, subscription_ids: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS, mixed_case_ids: bool = False
) -> NetworkSnapshot:
    return build_estate(MID, subscription_ids=subscription_ids, mixed_case_ids=mixed_case_ids)


def enterprise_estate(
    *, subscription_ids: tuple[str, ...] = DEFAULT_SUBSCRIPTIONS, mixed_case_ids: bool = False
) -> NetworkSnapshot:
    return build_estate(ENTERPRISE, subscription_ids=subscription_ids, mixed_case_ids=mixed_case_ids)


def g4_baseline_estate() -> NetworkSnapshot:
    """Return the frozen private-link-free G-4 fixture; later plans must not alter it."""
    return build_estate(
        EstateShape(2, 2, 2, 3, 40),
        subscription_ids=DEFAULT_SUBSCRIPTIONS,
        include_private_link_resources=False,
    )
