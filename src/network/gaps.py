"""Network design gap detection.

Compares the observed hub-spoke topology against the customer's declared
design and reports where reality diverges. Each gap names the affected
resource, the rule it violates, and the evidence — so it can be triaged
without re-deriving the analysis by hand.

Every check states its basis. Where a conclusion depends on data the platform
does not ingest (flow logs, effective routes, DNS query telemetry), the gap
says so rather than overstating confidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .design import NetworkDesignPolicy
from .models import NetworkSnapshot
from .topology import NetworkTopology

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

#: ARM resource-type fragments that should normally sit behind Private Link.
PRIVATE_LINK_CANDIDATES: dict[str, str] = {
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
}


@dataclass(frozen=True)
class NetworkGap:
    """A divergence between the observed estate and the intended design."""

    gap_id: str
    category: str
    severity: str
    title: str
    detail: str
    resource_id: str
    resource_name: str
    resource_type: str
    evidence: dict[str, Any]
    recommendation: str
    basis: str
    connection_id: str = ""
    subscription_id: str = ""
    environment: str = ""
    vnet_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "resource_type": self.resource_type,
            "evidence": dict(self.evidence),
            "recommendation": self.recommendation,
            "basis": self.basis,
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "environment": self.environment,
            "vnet_id": self.vnet_id,
        }


def _gap_id(category: str, resource_id: str) -> str:
    digest = hashlib.sha256(f"{category}|{resource_id}".encode()).hexdigest()[:16]
    return f"netgap-{digest}"


class NetworkGapAnalyzer:
    """Runs every design-conformance check against the stitched topology."""

    def __init__(
        self,
        snapshot: NetworkSnapshot,
        topology: NetworkTopology,
        policy: NetworkDesignPolicy | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.topology = topology
        self.policy = policy or NetworkDesignPolicy()
        self._subnets = {subnet.resource_id: subnet for subnet in snapshot.subnets}
        self._vnets = {vnet.resource_id: vnet for vnet in snapshot.vnets}
        self._route_tables = {table.resource_id: table for table in snapshot.route_tables}
        self._firewall_ips = {
            firewall.private_ip.strip()
            for firewall in snapshot.firewalls
            if firewall.private_ip.strip()
        }

    def analyze(self) -> tuple[NetworkGap, ...]:
        gaps: list[NetworkGap] = []
        gaps.extend(self._firewall_bypass())
        gaps.extend(self._missing_udr())
        gaps.extend(self._missing_nsg())
        gaps.extend(self._missing_private_endpoint())
        gaps.extend(self._unapproved_peering())
        gaps.extend(self._asymmetric_peering())
        gaps.extend(self._dns_dependency())
        gaps.extend(self._orphan_firewall_rules())
        gaps.extend(self._undocumented_dependencies())
        gaps.extend(self._public_ip_on_spoke())
        gaps.extend(self._missing_hub_firewall())
        return tuple(
            sorted(
                gaps,
                key=lambda item: (SEVERITY_ORDER.get(item.severity, 9), item.category, item.resource_id),
            )
        )

    def _spoke_vnet_ids(self) -> set[str]:
        declared = {
            vnet_id
            for vnet_id, vnet in self._vnets.items()
            if self.policy.declares_hub(vnet.name)
        }
        hubs = {hub.vnet_id for hub in self.topology.hubs} | declared
        return {
            item.vnet_id
            for item in self.topology.classifications
            if item.vnet_id not in hubs and not self.policy.is_exempt_vnet(item.name)
        }

    def _firewall_bypass(self) -> list[NetworkGap]:
        """A spoke subnet with no default route to the firewall egresses directly."""
        if not self.policy.require_default_route_to_firewall:
            return []
        if not self.snapshot.firewalls:
            return []

        gaps: list[NetworkGap] = []
        spokes = self._spoke_vnet_ids()
        for subnet in self.snapshot.subnets:
            if subnet.vnet_id not in spokes or self.policy.is_exempt_subnet(subnet.name):
                continue
            table = self._route_tables.get(subnet.route_table_id)
            default_route = table.default_route if table is not None else None
            if default_route is not None and self._points_at_firewall(default_route):
                continue

            reason = (
                "no route table is associated"
                if table is None
                else "the route table has no 0.0.0.0/0 route"
                if default_route is None
                else f"the default route sends traffic to {default_route.next_hop_type}"
                + (f" {default_route.next_hop_ip}" if default_route.next_hop_ip else "")
            )
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("firewall_bypass", subnet.resource_id),
                    category="firewall_bypass",
                    severity="high",
                    title="Spoke subnet egresses without traversing the firewall",
                    detail=(
                        f"Subnet '{subnet.name}' in VNet "
                        f"'{self._vnet_name(subnet.vnet_id)}' can reach the internet directly "
                        f"because {reason}."
                    ),
                    resource_id=subnet.resource_id,
                    resource_name=subnet.name,
                    resource_type="Subnet",
                    evidence={
                        "route_table_id": subnet.route_table_id,
                        "default_route_next_hop": (
                            default_route.next_hop_type if default_route else ""
                        ),
                        "default_route_next_hop_ip": (
                            default_route.next_hop_ip if default_route else ""
                        ),
                        "firewall_private_ips": sorted(self._firewall_ips),
                    },
                    recommendation=(
                        "Associate a route table with a 0.0.0.0/0 route whose next hop is the "
                        "hub firewall's private IP."
                    ),
                    basis="route table associations and next-hop configuration",
                    connection_id=subnet.connection_id,
                    subscription_id=subnet.subscription_id,
                    environment=subnet.environment,
                    vnet_id=subnet.vnet_id,
                )
            )
        return gaps

    def _points_at_firewall(self, route: Any) -> bool:
        if not route.forces_appliance:
            return False
        if not self._firewall_ips:
            return True
        if not route.next_hop_ip:
            return route.next_hop_type.casefold() == "virtualnetworkgateway"
        return route.next_hop_ip.strip() in self._firewall_ips

    def _missing_udr(self) -> list[NetworkGap]:
        """A spoke subnet with no route table at all."""
        if not self.policy.require_default_route_to_firewall:
            return []
        gaps: list[NetworkGap] = []
        spokes = self._spoke_vnet_ids()
        for subnet in self.snapshot.subnets:
            if subnet.vnet_id not in spokes or self.policy.is_exempt_subnet(subnet.name):
                continue
            if subnet.route_table_id:
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("missing_udr", subnet.resource_id),
                    category="missing_udr",
                    severity="medium",
                    title="Spoke subnet has no user-defined route table",
                    detail=(
                        f"Subnet '{subnet.name}' relies entirely on Azure system routing, so "
                        "its egress path is not controlled by the platform team."
                    ),
                    resource_id=subnet.resource_id,
                    resource_name=subnet.name,
                    resource_type="Subnet",
                    evidence={"address_prefixes": list(subnet.address_prefixes)},
                    recommendation="Associate the standard spoke route table with this subnet.",
                    basis="subnet route table association",
                    connection_id=subnet.connection_id,
                    subscription_id=subnet.subscription_id,
                    environment=subnet.environment,
                    vnet_id=subnet.vnet_id,
                )
            )
        return gaps

    def _missing_nsg(self) -> list[NetworkGap]:
        if not self.policy.require_nsg_on_every_subnet:
            return []
        gaps: list[NetworkGap] = []
        for subnet in self.snapshot.subnets:
            if subnet.nsg_id or self.policy.is_exempt_subnet(subnet.name):
                continue
            if self.policy.is_exempt_vnet(self._vnet_name(subnet.vnet_id)):
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("missing_nsg", subnet.resource_id),
                    category="missing_nsg",
                    severity="medium",
                    title="Subnet has no network security group",
                    detail=(
                        f"Subnet '{subnet.name}' in VNet '{self._vnet_name(subnet.vnet_id)}' has "
                        "no NSG association, so no subnet-level filtering is applied."
                    ),
                    resource_id=subnet.resource_id,
                    resource_name=subnet.name,
                    resource_type="Subnet",
                    evidence={"address_prefixes": list(subnet.address_prefixes)},
                    recommendation="Associate an NSG that reflects the tier's required access.",
                    basis="subnet NSG association",
                    connection_id=subnet.connection_id,
                    subscription_id=subnet.subscription_id,
                    environment=subnet.environment,
                    vnet_id=subnet.vnet_id,
                )
            )
        return gaps

    def _missing_private_endpoint(self) -> list[NetworkGap]:
        """PaaS services the design requires behind Private Link but are not.

        Reported per *required service kind* rather than per resource, since
        the resource inventory of PaaS services lives outside the network
        snapshot — this states clearly what it can and cannot see.
        """
        required = self.policy.require_private_endpoint_for_services
        if not required:
            return []

        observed_kinds: set[str] = set()
        for endpoint in self.snapshot.private_endpoints:
            target = endpoint.target_resource_id
            for fragment, label in PRIVATE_LINK_CANDIDATES.items():
                if f"/providers/{fragment}/" in target:
                    observed_kinds.add(label.casefold())
            for group in endpoint.group_ids:
                observed_kinds.add(group.casefold())

        gaps: list[NetworkGap] = []
        for service in required:
            if service.casefold() in observed_kinds:
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("missing_private_endpoint", service.casefold()),
                    category="missing_private_endpoint",
                    severity="high",
                    title=f"No private endpoint observed for {service}",
                    detail=(
                        f"The declared design requires {service} to be reachable only through "
                        "Private Link, but no private endpoint targeting it was observed in any "
                        "connected subscription."
                    ),
                    resource_id=f"design://private-endpoint/{service.casefold()}",
                    resource_name=service,
                    resource_type="PrivateEndpoint",
                    evidence={
                        "required_service": service,
                        "observed_private_endpoints": len(self.snapshot.private_endpoints),
                        "observed_group_ids": sorted(observed_kinds),
                    },
                    recommendation=(
                        f"Create a private endpoint for {service} and disable its public "
                        "network access."
                    ),
                    basis="private endpoint target resource IDs and group IDs",
                )
            )
        return gaps

    def _unapproved_peering(self) -> list[NetworkGap]:
        gaps: list[NetworkGap] = []
        hub_ids = {hub.vnet_id for hub in self.topology.hubs}

        for link in self.topology.links:
            left = self._vnet_name(link.local_vnet_id)
            right = self._vnet_name(link.remote_vnet_id)

            if not self.policy.peering_is_approved(left, right):
                gaps.append(
                    self._peering_gap(
                        link,
                        category="unapproved_peering",
                        severity="high",
                        title="Peering is not on the approved list",
                        detail=(
                            f"A peering exists between '{left or link.local_vnet_id}' and "
                            f"'{right or link.remote_vnet_id}' but the declared design does not "
                            "list it as approved."
                        ),
                        recommendation=(
                            "Remove the peering, or add it to the approved list if it is "
                            "intentional."
                        ),
                    )
                )
                continue

            if (
                self.policy.forbid_spoke_to_spoke_peering
                and link.local_vnet_id not in hub_ids
                and link.remote_vnet_id not in hub_ids
                and link.remote_vnet_observed
            ):
                gaps.append(
                    self._peering_gap(
                        link,
                        category="unapproved_peering",
                        severity="high",
                        title="Spoke-to-spoke peering bypasses the hub",
                        detail=(
                            f"'{left}' and '{right}' peer directly. Traffic between them does "
                            "not traverse the hub firewall."
                        ),
                        recommendation=(
                            "Remove the direct peering and route the traffic through the hub."
                        ),
                    )
                )
        return gaps

    def _asymmetric_peering(self) -> list[NetworkGap]:
        if not self.policy.require_bidirectional_peering:
            return []
        gaps: list[NetworkGap] = []
        for link in self.topology.links:
            if link.is_bidirectional and link.is_healthy:
                continue
            if not link.remote_vnet_observed:
                gaps.append(
                    self._peering_gap(
                        link,
                        category="asymmetric_routing_risk",
                        severity="medium",
                        title="Peering targets a VNet in an unconnected subscription",
                        detail=(
                            f"The peering from '{self._vnet_name(link.local_vnet_id)}' targets "
                            f"{link.remote_vnet_id}, which no onboarded connection has synced. "
                            "The far side cannot be verified."
                        ),
                        recommendation=(
                            "Onboard the subscription that owns the remote VNet so the peering "
                            "can be validated end to end."
                        ),
                        basis="peering remote VNet ID matched against synced connections",
                    )
                )
                continue
            gaps.append(
                self._peering_gap(
                    link,
                    category="asymmetric_routing_risk",
                    severity="high",
                    title="Peering is configured on only one side or is not connected",
                    detail=(
                        f"The peering between '{self._vnet_name(link.local_vnet_id)}' and "
                        f"'{self._vnet_name(link.remote_vnet_id)}' is "
                        f"{'unidirectional' if not link.is_bidirectional else 'not in a Connected state'} "
                        f"(local: {link.local_state or 'unknown'}, remote: {link.remote_state or 'absent'}). "
                        "Traffic will fail or return asymmetrically."
                    ),
                    recommendation=(
                        "Create or repair the reverse peering so both sides report Connected."
                    ),
                )
            )
        return gaps

    def _peering_gap(
        self,
        link: Any,
        *,
        category: str,
        severity: str,
        title: str,
        detail: str,
        recommendation: str,
        basis: str = "VNet peering configuration observed on both sides",
    ) -> NetworkGap:
        vnet = self._vnets.get(link.local_vnet_id)
        return NetworkGap(
            gap_id=_gap_id(category, f"{link.local_vnet_id}|{link.remote_vnet_id}"),
            category=category,
            severity=severity,
            title=title,
            detail=detail,
            resource_id=link.local_vnet_id,
            resource_name=self._vnet_name(link.local_vnet_id),
            resource_type="VNetPeering",
            evidence=link.to_dict(),
            recommendation=recommendation,
            basis=basis,
            connection_id=link.local_connection_id,
            subscription_id=vnet.subscription_id if vnet else "",
            environment=vnet.environment if vnet else "",
            vnet_id=link.local_vnet_id,
        )

    def _dns_dependency(self) -> list[NetworkGap]:
        """Private endpoints whose DNS zone is not linked to the consuming VNet."""
        if not self.policy.require_private_dns_zone_link:
            return []
        zones = {zone.resource_id: zone for zone in self.snapshot.private_dns_zones}
        gaps: list[NetworkGap] = []

        for endpoint in self.snapshot.private_endpoints:
            subnet = self._subnets.get(endpoint.subnet_id)
            consuming_vnet = subnet.vnet_id if subnet else ""

            if not endpoint.private_dns_zone_ids:
                gaps.append(
                    NetworkGap(
                        gap_id=_gap_id("dns_dependency_gap", endpoint.resource_id),
                        category="dns_dependency_gap",
                        severity="high",
                        title="Private endpoint has no private DNS zone group",
                        detail=(
                            f"Private endpoint '{endpoint.name}' has no DNS zone group, so "
                            "clients will resolve the service's public IP and bypass Private Link."
                        ),
                        resource_id=endpoint.resource_id,
                        resource_name=endpoint.name,
                        resource_type="PrivateEndpoint",
                        evidence={
                            "target_resource_id": endpoint.target_resource_id,
                            "group_ids": list(endpoint.group_ids),
                        },
                        recommendation=(
                            "Attach the endpoint to the corresponding centralized private DNS zone."
                        ),
                        basis="private endpoint DNS zone group configuration",
                        connection_id=endpoint.connection_id,
                        subscription_id=endpoint.subscription_id,
                        environment=endpoint.environment,
                        vnet_id=consuming_vnet,
                    )
                )
                continue

            for zone_id in endpoint.private_dns_zone_ids:
                zone = zones.get(zone_id)
                if zone is None:
                    continue
                if consuming_vnet and consuming_vnet not in zone.linked_vnet_ids:
                    gaps.append(
                        NetworkGap(
                            gap_id=_gap_id(
                                "dns_dependency_gap", f"{endpoint.resource_id}|{zone_id}"
                            ),
                            category="dns_dependency_gap",
                            severity="high",
                            title="Private DNS zone is not linked to the consuming VNet",
                            detail=(
                                f"Endpoint '{endpoint.name}' resolves through zone "
                                f"'{zone.zone_name}', but that zone has no virtual network link "
                                f"to '{self._vnet_name(consuming_vnet)}'. Name resolution will fail "
                                "or fall back to the public endpoint."
                            ),
                            resource_id=endpoint.resource_id,
                            resource_name=endpoint.name,
                            resource_type="PrivateEndpoint",
                            evidence={
                                "zone_id": zone_id,
                                "zone_name": zone.zone_name,
                                "linked_vnet_ids": list(zone.linked_vnet_ids),
                                "consuming_vnet_id": consuming_vnet,
                            },
                            recommendation=(
                                "Add a virtual network link from the private DNS zone to the "
                                "consuming VNet."
                            ),
                            basis="private DNS zone virtual network links",
                            connection_id=endpoint.connection_id,
                            subscription_id=endpoint.subscription_id,
                            environment=endpoint.environment,
                            vnet_id=consuming_vnet,
                        )
                    )
        return gaps

    def _orphan_firewall_rules(self) -> list[NetworkGap]:
        """Rules whose source or destination no longer exists in the estate.

        Compares rule addresses against every observed subnet prefix. A rule
        naming a private range that matches nothing is very likely stale.
        """
        from .addressing import AddressSpec

        known_prefixes = [
            AddressSpec.parse(prefix)
            for subnet in self.snapshot.subnets
            for prefix in subnet.address_prefixes
        ]
        if not known_prefixes:
            return []

        gaps: list[NetworkGap] = []
        for collection in self.snapshot.firewall_collections:
            for rule in collection.rules:
                stale = self._stale_addresses(rule.destination_addresses, known_prefixes)
                if not stale:
                    continue
                gaps.append(
                    NetworkGap(
                        gap_id=_gap_id("orphan_firewall_rule", rule.resource_id),
                        category="orphan_firewall_rule",
                        severity="low",
                        title="Firewall rule targets addresses no longer present in the estate",
                        detail=(
                            f"Rule '{rule.name}' in collection '{collection.name}' allows traffic "
                            f"to {', '.join(stale)}, which does not fall inside any observed "
                            "subnet across the connected subscriptions."
                        ),
                        resource_id=rule.resource_id,
                        resource_name=rule.name,
                        resource_type="FirewallRule",
                        evidence={
                            "unmatched_destinations": stale,
                            "collection": collection.name,
                            "observed_subnet_count": len(self.snapshot.subnets),
                        },
                        recommendation=(
                            "Confirm the target still exists; remove the rule if the workload "
                            "was decommissioned."
                        ),
                        basis=(
                            "rule destinations compared against observed subnet prefixes; "
                            "targets outside connected subscriptions cannot be verified"
                        ),
                        connection_id=rule.connection_id or collection.connection_id,
                        subscription_id=rule.subscription_id or collection.subscription_id,
                        environment=rule.environment or collection.environment,
                    )
                )
        return gaps

    def _stale_addresses(self, addresses: tuple[str, ...], known: list[Any]) -> list[str]:
        from .addressing import AddressSpec

        stale: list[str] = []
        for address in addresses:
            spec = AddressSpec.parse(address)
            if spec.is_any or spec.service_tag or not spec.networks:
                continue
            if not self._is_private(spec):
                continue
            if any(prefix.overlaps(spec) is True for prefix in known):
                continue
            stale.append(address)
        return stale

    @staticmethod
    def _is_private(spec: Any) -> bool:
        import ipaddress

        for cidr in spec.networks:
            try:
                if ipaddress.ip_network(cidr, strict=False).is_private:
                    return True
            except ValueError:
                continue
        return False

    def _undocumented_dependencies(self) -> list[NetworkGap]:
        """Cross-business-service network reachability nobody declared.

        A peering between VNets attributed to different business services is
        a dependency that should appear in the service model. When it does
        not, the platform is carrying an undocumented coupling.
        """
        gaps: list[NetworkGap] = []
        for link in self.topology.links:
            local = self._vnets.get(link.local_vnet_id)
            remote = self._vnets.get(link.remote_vnet_id)
            if local is None or remote is None:
                continue
            left = local.business_service.strip()
            right = remote.business_service.strip()
            if not left or not right or left.casefold() == right.casefold():
                continue
            if self.topology.role_of(link.local_vnet_id) == "hub" or (
                self.topology.role_of(link.remote_vnet_id) == "hub"
            ):
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id(
                        "undocumented_dependency", f"{link.local_vnet_id}|{link.remote_vnet_id}"
                    ),
                    category="undocumented_dependency",
                    severity="medium",
                    title="Network path couples two business services",
                    detail=(
                        f"'{local.name}' ({left}) peers directly with '{remote.name}' ({right}). "
                        "This creates a cross-service dependency that is not mediated by the hub."
                    ),
                    resource_id=link.local_vnet_id,
                    resource_name=local.name,
                    resource_type="VNetPeering",
                    evidence={
                        "local_business_service": left,
                        "remote_business_service": right,
                        **link.to_dict(),
                    },
                    recommendation=(
                        "Document the dependency in the service model, or route the traffic "
                        "through the hub so it is governed centrally."
                    ),
                    basis="business service attribution on peered VNets",
                    connection_id=local.connection_id,
                    subscription_id=local.subscription_id,
                    environment=local.environment,
                    vnet_id=link.local_vnet_id,
                )
            )
        return gaps

    def _public_ip_on_spoke(self) -> list[NetworkGap]:
        if not self.policy.forbid_public_ip_on_spoke_nics:
            return []
        spokes = self._spoke_vnet_ids()
        gaps: list[NetworkGap] = []
        for nic in self.snapshot.nics:
            if not nic.has_public_ip:
                continue
            subnet = self._subnets.get(nic.subnet_id)
            vnet_id = subnet.vnet_id if subnet else ""
            if vnet_id and vnet_id not in spokes:
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("public_ip_on_spoke", nic.resource_id),
                    category="firewall_bypass",
                    severity="high",
                    title="Spoke workload has a directly attached public IP",
                    detail=(
                        f"Network interface '{nic.name}' has a public IP, so inbound and "
                        "outbound traffic can bypass the hub firewall entirely."
                    ),
                    resource_id=nic.resource_id,
                    resource_name=nic.name,
                    resource_type="NetworkInterface",
                    evidence={
                        "public_ip_ids": list(nic.public_ips),
                        "attached_resource_id": nic.attached_resource_id,
                        "subnet_id": nic.subnet_id,
                    },
                    recommendation=(
                        "Remove the public IP and publish the workload through the hub firewall, "
                        "Application Gateway, or Bastion."
                    ),
                    basis="NIC IP configuration",
                    connection_id=nic.connection_id,
                    subscription_id=nic.subscription_id,
                    environment=nic.environment,
                    vnet_id=vnet_id,
                )
            )
        return gaps

    def _missing_hub_firewall(self) -> list[NetworkGap]:
        if not self.policy.require_firewall_in_hub:
            return []
        hubs = self.topology.hubs
        if not hubs:
            return []
        firewall_vnets = {
            firewall.subnet_id.split("/subnets/", 1)[0]
            if "/subnets/" in firewall.subnet_id
            else firewall.vnet_id
            for firewall in self.snapshot.firewalls
        }
        gaps: list[NetworkGap] = []
        for hub in hubs:
            if hub.vnet_id in firewall_vnets:
                continue
            gaps.append(
                NetworkGap(
                    gap_id=_gap_id("missing_hub_firewall", hub.vnet_id),
                    category="missing_hub_firewall",
                    severity="critical",
                    title="Hub VNet has no Azure Firewall",
                    detail=(
                        f"'{hub.name}' is classified as a hub "
                        f"(signals: {', '.join(hub.signals) or 'none'}) but hosts no Azure "
                        "Firewall, so spoke traffic has no central inspection point."
                    ),
                    resource_id=hub.vnet_id,
                    resource_name=hub.name,
                    resource_type="VNet",
                    evidence={
                        "hub_signals": list(hub.signals),
                        "hub_score": hub.score,
                        "peer_count": hub.peer_count,
                    },
                    recommendation="Deploy Azure Firewall into the hub's AzureFirewallSubnet.",
                    basis="firewall subnet association against hub-classified VNets",
                    connection_id=hub.connection_id,
                    subscription_id=hub.subscription_id,
                    vnet_id=hub.vnet_id,
                )
            )
        return gaps

    def _vnet_name(self, vnet_id: str) -> str:
        vnet = self._vnets.get(str(vnet_id or "").casefold())
        return vnet.name if vnet else ""


def analyze_gaps(
    snapshot: NetworkSnapshot,
    topology: NetworkTopology,
    policy: NetworkDesignPolicy | None = None,
) -> tuple[NetworkGap, ...]:
    """Convenience wrapper around :class:`NetworkGapAnalyzer`."""
    return NetworkGapAnalyzer(snapshot, topology, policy).analyze()
