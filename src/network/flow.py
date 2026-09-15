"""Traffic-flow validation across NSGs, Azure Firewall, routing, and peering.

Answers "can A reach B on port N, and which rules decide it?" by walking the
same path Azure does: source NSG egress → routing → firewall (when the route
forces it) → peering → destination NSG ingress. Every hop records the rule
that made the decision, so a result is always explainable.

Where evidence is missing — an unresolvable service tag, an unobserved remote
VNet, an IP-less endpoint — the verdict is ``indeterminate``, never a guess.
A tool that says "allowed" when it does not know is worse than one that says
"I cannot tell".
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any

from .addressing import INTERNET_TAGS, AddressSpec, PortSpec, ProtocolSpec
from .models import (
    NetworkSecurityRule,
    NetworkSnapshot,
    Route,
    Subnet,
)
from .topology import NetworkTopology

#: Flow verdicts, in increasing order of confidence that traffic passes.
VERDICT_DENIED = "denied"
VERDICT_INDETERMINATE = "indeterminate"
VERDICT_ALLOWED = "allowed"


@dataclass(frozen=True)
class FlowEndpoint:
    """One side of a flow, resolved to whatever the estate actually knows.

    A caller may supply an IP, a subnet ID, a resource ID, or a name. The
    resolver fills in what it can and leaves the rest blank, and the
    evaluator degrades to ``indeterminate`` rather than inventing detail.
    """

    raw: str
    ip_address: str = ""
    subnet_id: str = ""
    vnet_id: str = ""
    nsg_id: str = ""
    resource_id: str = ""
    environment: str = ""
    name: str = ""
    is_internet: bool = False
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "ip_address": self.ip_address,
            "subnet_id": self.subnet_id,
            "vnet_id": self.vnet_id,
            "nsg_id": self.nsg_id,
            "resource_id": self.resource_id,
            "environment": self.environment,
            "name": self.name,
            "is_internet": self.is_internet,
            "resolved": self.resolved,
        }


@dataclass(frozen=True)
class FlowHop:
    """A single enforcement decision along the path."""

    stage: str
    control: str
    control_id: str
    decision: str
    rule_id: str = ""
    rule_name: str = ""
    priority: int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "control": self.control,
            "control_id": self.control_id,
            "decision": self.decision,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "priority": self.priority,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FlowQuery:
    source: str
    destination: str
    port: int | None = None
    protocol: str = "Tcp"
    environment_scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "destination": self.destination,
            "port": self.port,
            "protocol": self.protocol,
            "environment_scope": self.environment_scope,
        }


@dataclass(frozen=True)
class FlowResult:
    query: FlowQuery
    source_endpoint: FlowEndpoint
    destination_endpoint: FlowEndpoint
    verdict: str
    hops: tuple[FlowHop, ...] = ()
    missing_enforcement_points: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    path_summary: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.verdict == VERDICT_ALLOWED

    @property
    def deciding_hop(self) -> FlowHop | None:
        for hop in self.hops:
            if hop.decision == "deny":
                return hop
        return self.hops[-1] if self.hops else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "source": self.source_endpoint.to_dict(),
            "destination": self.destination_endpoint.to_dict(),
            "verdict": self.verdict,
            "hops": [hop.to_dict() for hop in self.hops],
            "missing_enforcement_points": list(self.missing_enforcement_points),
            "unknowns": list(self.unknowns),
            "path_summary": self.path_summary,
        }


class EndpointResolver:
    """Resolves a free-form endpoint string against the observed estate."""

    def __init__(self, snapshot: NetworkSnapshot) -> None:
        self.snapshot = snapshot
        self._subnets = {subnet.resource_id: subnet for subnet in snapshot.subnets}
        self._nics = list(snapshot.nics)

    def resolve(self, value: str) -> FlowEndpoint:
        raw = str(value or "").strip()
        if not raw:
            return FlowEndpoint(raw=raw)
        token = raw.casefold()

        if token in INTERNET_TAGS:
            return FlowEndpoint(raw=raw, name="Internet", is_internet=True, resolved=True)

        if token in self._subnets:
            return self._from_subnet(raw, self._subnets[token])

        for nic in self._nics:
            if nic.resource_id == token or nic.attached_resource_id == token:
                return self._from_nic(raw, nic)
            if raw in nic.private_ips:
                return self._from_nic(raw, nic, ip_address=raw)

        if self._is_ip(raw):
            subnet = self._subnet_for_ip(raw)
            if subnet is not None:
                return self._from_subnet(raw, subnet, ip_address=raw)
            # A public address is a legitimate, fully-resolved destination —
            # "can this spoke reach the internet?" is a first-class question.
            if self._is_public(raw):
                return FlowEndpoint(
                    raw=raw,
                    ip_address=raw,
                    name=raw,
                    is_internet=True,
                    resolved=True,
                )
            return FlowEndpoint(raw=raw, ip_address=raw, resolved=False)

        for nic in self._nics:
            if nic.name.casefold() == token:
                return self._from_nic(raw, nic)
        for subnet in self._subnets.values():
            if subnet.name.casefold() == token:
                return self._from_subnet(raw, subnet)

        if self._is_public_fqdn(raw):
            return FlowEndpoint(
                raw=raw,
                name=raw,
                is_internet=True,
                resolved=True,
            )

        return FlowEndpoint(raw=raw, name=raw, resolved=False)

    def _from_subnet(self, raw: str, subnet: Subnet, *, ip_address: str = "") -> FlowEndpoint:
        return FlowEndpoint(
            raw=raw,
            ip_address=ip_address,
            subnet_id=subnet.resource_id,
            vnet_id=subnet.vnet_id,
            nsg_id=subnet.nsg_id,
            environment=subnet.environment,
            name=subnet.name,
            resolved=True,
        )

    def _from_nic(self, raw: str, nic: Any, *, ip_address: str = "") -> FlowEndpoint:
        subnet = self._subnets.get(nic.subnet_id)
        return FlowEndpoint(
            raw=raw,
            ip_address=ip_address or (nic.private_ips[0] if nic.private_ips else ""),
            subnet_id=nic.subnet_id,
            vnet_id=subnet.vnet_id if subnet else "",
            nsg_id=nic.nsg_id or (subnet.nsg_id if subnet else ""),
            resource_id=nic.attached_resource_id or nic.resource_id,
            environment=nic.environment or (subnet.environment if subnet else ""),
            name=nic.name,
            resolved=True,
        )

    def _subnet_for_ip(self, address: str) -> Subnet | None:
        try:
            candidate = ipaddress.ip_address(address)
        except ValueError:
            return None
        for subnet in self._subnets.values():
            for prefix in subnet.address_prefixes:
                try:
                    network = ipaddress.ip_network(prefix, strict=False)
                except ValueError:
                    continue
                if network.version == candidate.version and candidate in network:
                    return subnet
        return None

    @staticmethod
    def _is_ip(value: str) -> bool:
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_public(value: str) -> bool:
        try:
            return ipaddress.ip_address(value).is_global
        except ValueError:
            return False

    @staticmethod
    def _is_public_fqdn(value: str) -> bool:
        candidate = value.rstrip(".")
        if len(candidate) > 253:
            return False
        labels = candidate.split(".")
        if len(labels) < 2:
            return False
        label_pattern = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
        if not all(label_pattern.fullmatch(label) for label in labels):
            return False
        return bool(re.fullmatch(r"(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{2,59})", labels[-1]))


class TrafficFlowValidator:
    """Evaluates a flow hop by hop and reports the deciding controls."""

    def __init__(self, snapshot: NetworkSnapshot, topology: NetworkTopology | None = None) -> None:
        self.snapshot = snapshot
        self.topology = topology
        self.resolver = EndpointResolver(snapshot)
        self._nsgs = {nsg.resource_id: nsg for nsg in snapshot.nsgs}
        self._subnets = {subnet.resource_id: subnet for subnet in snapshot.subnets}
        self._route_tables = {table.resource_id: table for table in snapshot.route_tables}
        self._firewall_ips = {
            firewall.private_ip for firewall in snapshot.firewalls if firewall.private_ip
        }
        self._address_spaces: tuple[str, ...] | None = None

    def validate(self, query: FlowQuery) -> FlowResult:
        source = self.resolver.resolve(query.source)
        destination = self.resolver.resolve(query.destination)
        hops: list[FlowHop] = []
        unknowns: list[str] = []
        missing: list[str] = []

        if not source.resolved:
            unknowns.append(f"source '{query.source}' could not be resolved to an observed resource")
        if not destination.resolved:
            unknowns.append(
                f"destination '{query.destination}' could not be resolved to an observed resource"
            )

        egress = self._evaluate_nsg(
            source.nsg_id, query, source, destination, direction="Outbound", stage="source_egress"
        )
        if egress is not None:
            hops.append(egress)
        elif source.subnet_id:
            missing.append(f"no NSG applied to source subnet {source.subnet_id}")

        route_hop, forced_via_firewall = self._evaluate_routing(source, destination, query)
        if route_hop is not None:
            hops.append(route_hop)

        peering_hop = self._evaluate_peering(source, destination)
        if peering_hop is not None:
            hops.append(peering_hop)

        if forced_via_firewall:
            firewall_hop = self._evaluate_firewall(query, source, destination)
            if firewall_hop is not None:
                hops.append(firewall_hop)
            else:
                missing.append(
                    "route forces traffic to a virtual appliance but no matching firewall rule was observed"
                )
        elif self._crosses_vnet(source, destination) and self.snapshot.firewalls:
            missing.append(
                "traffic crosses VNet boundaries without a route forcing it through the firewall"
            )
        elif destination.is_internet and self.snapshot.firewalls:
            missing.append(
                "internet-bound traffic egresses directly without traversing the hub firewall"
            )

        if destination.is_internet:
            ingress = None
        else:
            ingress = self._evaluate_nsg(
                destination.nsg_id,
                query,
                source,
                destination,
                direction="Inbound",
                stage="destination_ingress",
            )
        if ingress is not None:
            hops.append(ingress)
        elif destination.subnet_id and not destination.is_internet:
            missing.append(f"no NSG applied to destination subnet {destination.subnet_id}")

        unknowns.extend(hop.reason for hop in hops if hop.decision == "unknown")
        if not hops:
            unknowns.append(
                "no ordered enforcement path could be established from the observed controls"
            )

        verdict = self._verdict(hops, unknowns)
        return FlowResult(
            query=query,
            source_endpoint=source,
            destination_endpoint=destination,
            verdict=verdict,
            hops=tuple(hops),
            missing_enforcement_points=tuple(dict.fromkeys(missing)),
            unknowns=tuple(dict.fromkeys(unknowns)),
            path_summary=self._summarize(source, destination, hops, verdict),
        )

    def validate_many(self, queries: list[FlowQuery]) -> tuple[FlowResult, ...]:
        return tuple(self.validate(query) for query in queries)

    def _evaluate_nsg(
        self,
        nsg_id: str,
        query: FlowQuery,
        source: FlowEndpoint,
        destination: FlowEndpoint,
        *,
        direction: str,
        stage: str,
    ) -> FlowHop | None:
        nsg = self._nsgs.get(str(nsg_id or "").casefold())
        if nsg is None:
            return None

        source_value = source.ip_address or self._prefix_for(source)
        dest_value = destination.ip_address or self._prefix_for(destination)
        uncertain_rule: NetworkSecurityRule | None = None

        for rule in nsg.ordered_rules(direction=direction):
            match = self._rule_matches(
                rule,
                source_value,
                dest_value,
                query,
                source,
                destination,
            )
            if match is None:
                # Azure stops at the first matching rule by priority. If a
                # higher-priority rule *might* match, no lower-priority rule
                # can be reported as the decision — the outcome is unknown.
                if uncertain_rule is None:
                    uncertain_rule = rule
                continue
            if not match:
                continue
            if uncertain_rule is not None:
                break
            return FlowHop(
                stage=stage,
                control="nsg",
                control_id=nsg.resource_id,
                decision="allow" if rule.is_allow else "deny",
                rule_id=rule.resource_id,
                rule_name=rule.name,
                priority=rule.priority,
                reason=(
                    f"{rule.direction} rule '{rule.name}' (priority {rule.priority}) "
                    f"{rule.access.lower()}s {rule.protocol} "
                    f"{rule.source_address} -> {rule.destination_address}:{rule.destination_port}"
                ),
            )

        if uncertain_rule is not None:
            return FlowHop(
                stage=stage,
                control="nsg",
                control_id=nsg.resource_id,
                decision="unknown",
                rule_id=uncertain_rule.resource_id,
                rule_name=uncertain_rule.name,
                priority=uncertain_rule.priority,
                reason=(
                    f"rule '{uncertain_rule.name}' (priority {uncertain_rule.priority}) "
                    f"may match but could not be evaluated: "
                    f"{uncertain_rule.source_address} -> {uncertain_rule.destination_address} "
                    "could not be resolved to addresses"
                ),
            )

        return FlowHop(
            stage=stage,
            control="nsg",
            control_id=nsg.resource_id,
            decision="deny",
            reason="no rule matched; Azure's implicit deny applies",
        )

    def _rule_matches(
        self,
        rule: NetworkSecurityRule,
        source_value: str,
        dest_value: str,
        query: FlowQuery,
        source: FlowEndpoint,
        destination: FlowEndpoint,
    ) -> bool | None:
        """``None`` means undecidable (unresolved service tag)."""
        if not rule.protocol_spec.matches(query.protocol):
            return False
        if not rule.destination_port_spec.contains(query.port):
            return False

        source_spec, dest_spec = rule.source_spec, rule.destination_spec

        source_match = self._address_match(source_spec, source_value, source)
        dest_match = self._address_match(dest_spec, dest_value, destination)
        if source_match is None or dest_match is None:
            return None
        return source_match and dest_match

    def _address_match(
        self,
        spec: AddressSpec,
        value: str,
        endpoint: FlowEndpoint | None = None,
    ) -> bool | None:
        if spec.is_any:
            return True
        if endpoint is not None and endpoint.is_internet:
            if spec.service_tag in INTERNET_TAGS:
                return True
            if spec.is_virtual_network or spec.networks:
                return False
        if not value:
            return None
        if spec.service_tag:
            return self._service_tag_match(spec, value)
        return spec.contains_address(value)

    def _service_tag_match(self, spec: AddressSpec, value: str) -> bool | None:
        """Resolves the tags the estate has evidence for; others stay unknown.

        ``VirtualNetwork`` and ``Internet`` are decidable from the observed VNet
        address spaces, and resolving them is what lets the synthesized default
        rules produce correct verdicts. Every other tag (``Storage``,
        ``AzureLoadBalancer``, ...) has no ingested definition, so it returns
        ``None`` and the flow is reported as indeterminate.
        """
        if spec.is_virtual_network:
            return self._within_estate(value)
        if spec.service_tag in INTERNET_TAGS:
            inside = self._within_estate(value)
            return None if inside is None else not inside
        return None

    def _within_estate(self, value: str) -> bool | None:
        """Whether an address falls inside any observed VNet address space."""
        spaces = self._estate_address_spaces()
        if not spaces:
            return None
        estate = AddressSpec(raw="VirtualNetwork", networks=spaces)
        return estate.contains_address(value)

    def _estate_address_spaces(self) -> tuple[str, ...]:
        if self._address_spaces is None:
            spaces: list[str] = []
            for vnet in self.snapshot.vnets:
                spaces.extend(vnet.address_spaces)
            self._address_spaces = tuple(dict.fromkeys(spaces))
        return self._address_spaces

    def _prefix_for(self, endpoint: FlowEndpoint) -> str:
        subnet = self._subnets.get(endpoint.subnet_id)
        if subnet is not None and subnet.address_prefixes:
            return subnet.address_prefixes[0]
        return ""

    def _evaluate_routing(
        self, source: FlowEndpoint, destination: FlowEndpoint, query: FlowQuery
    ) -> tuple[FlowHop | None, bool]:
        """Returns ``(hop, forced_through_appliance)``."""
        subnet = self._subnets.get(source.subnet_id)
        if subnet is None or not subnet.route_table_id:
            return None, False
        table = self._route_tables.get(subnet.route_table_id)
        if table is None:
            return None, False

        best = self._longest_prefix_match(table.routes, destination)
        if best is None:
            return (
                FlowHop(
                    stage="routing",
                    control="route_table",
                    control_id=table.resource_id,
                    decision="allow",
                    reason="no user-defined route matched; system routing applies",
                ),
                False,
            )

        if best.next_hop_type.casefold() == "none":
            return (
                FlowHop(
                    stage="routing",
                    control="route_table",
                    control_id=table.resource_id,
                    decision="deny",
                    rule_id=best.resource_id,
                    rule_name=best.name,
                    reason=f"route '{best.name}' blackholes {best.address_prefix} (next hop None)",
                ),
                False,
            )

        forced = best.forces_appliance
        return (
            FlowHop(
                stage="routing",
                control="route_table",
                control_id=table.resource_id,
                decision="allow",
                rule_id=best.resource_id,
                rule_name=best.name,
                reason=(
                    f"route '{best.name}' sends {best.address_prefix} to "
                    f"{best.next_hop_type}"
                    + (f" {best.next_hop_ip}" if best.next_hop_ip else "")
                ),
            ),
            forced,
        )

    def _longest_prefix_match(
        self, routes: tuple[Route, ...], destination: FlowEndpoint
    ) -> Route | None:
        target = destination.ip_address or self._prefix_for(destination)
        if not target:
            return None
        best: Route | None = None
        best_length = -1
        for route in routes:
            try:
                network = ipaddress.ip_network(route.address_prefix, strict=False)
            except ValueError:
                continue
            spec = AddressSpec(raw=route.address_prefix, networks=(str(network),))
            if spec.contains_address(target) and network.prefixlen > best_length:
                best, best_length = route, network.prefixlen
        return best

    def _evaluate_peering(
        self, source: FlowEndpoint, destination: FlowEndpoint
    ) -> FlowHop | None:
        if not self._crosses_vnet(source, destination):
            return None
        for peering in self.snapshot.peerings:
            pair = {peering.local_vnet_id, peering.remote_vnet_id}
            if pair != {source.vnet_id, destination.vnet_id}:
                continue
            if peering.is_connected and peering.allow_virtual_network_access:
                return FlowHop(
                    stage="peering",
                    control="vnet_peering",
                    control_id=peering.resource_id,
                    decision="allow",
                    rule_name=peering.name,
                    reason=f"peering '{peering.name}' is Connected and allows VNet access",
                )
            return FlowHop(
                stage="peering",
                control="vnet_peering",
                control_id=peering.resource_id,
                decision="deny",
                rule_name=peering.name,
                reason=(
                    f"peering '{peering.name}' is {peering.peering_state or 'not connected'}"
                    if not peering.is_connected
                    else f"peering '{peering.name}' disallows virtual network access"
                ),
            )

        transit = self._transit_hop(source, destination)
        if transit is not None:
            return transit

        return FlowHop(
            stage="peering",
            control="vnet_peering",
            control_id="",
            decision="deny",
            reason=(
                f"no peering observed between {source.vnet_id or 'source VNet'} and "
                f"{destination.vnet_id or 'destination VNet'}"
            ),
        )

    def _transit_hop(self, source: FlowEndpoint, destination: FlowEndpoint) -> FlowHop | None:
        """Spoke-to-spoke traffic transits the hub; report that explicitly."""
        if self.topology is None:
            return None
        source_hub = self.topology.hub_for(source.vnet_id)
        dest_hub = self.topology.hub_for(destination.vnet_id)
        if source_hub and source_hub == dest_hub:
            return FlowHop(
                stage="peering",
                control="hub_transit",
                control_id=source_hub,
                decision="unknown",
                reason=(
                    "both VNets peer with the same hub but no direct peering exists; "
                    "reachability depends on hub routing and firewall policy"
                ),
            )
        return None

    def _evaluate_firewall(
        self, query: FlowQuery, source: FlowEndpoint, destination: FlowEndpoint
    ) -> FlowHop | None:
        source_value = source.ip_address or self._prefix_for(source)
        dest_value = destination.ip_address or self._prefix_for(destination)
        collections = sorted(
            self.snapshot.firewall_collections, key=lambda item: (item.priority, item.name)
        )
        uncertain = False

        for collection in collections:
            for rule in collection.rules:
                match = self._firewall_rule_matches(
                    rule,
                    source_value,
                    dest_value,
                    query,
                    source,
                    destination,
                )
                if match is None:
                    uncertain = True
                    continue
                if not match:
                    continue
                return FlowHop(
                    stage="firewall",
                    control="azure_firewall",
                    control_id=collection.resource_id,
                    decision="allow" if rule.is_allow else "deny",
                    rule_id=rule.resource_id,
                    rule_name=rule.name,
                    priority=collection.priority,
                    reason=(
                        f"collection '{collection.name}' (priority {collection.priority}) "
                        f"rule '{rule.name}' {collection.action.lower()}s the flow"
                    ),
                )

        if not collections:
            return None
        return FlowHop(
            stage="firewall",
            control="azure_firewall",
            control_id=collections[0].policy_id or collections[0].resource_id,
            decision="unknown" if uncertain else "deny",
            reason=(
                "firewall rules reference IP groups or FQDNs that cannot be evaluated"
                if uncertain
                else "no firewall rule matched; Azure Firewall denies by default"
            ),
        )

    def _firewall_rule_matches(
        self,
        rule: Any,
        source_value: str,
        dest_value: str,
        query: FlowQuery,
        source: FlowEndpoint,
        destination: FlowEndpoint,
    ) -> bool | None:
        if rule.source_ip_groups or rule.destination_fqdns:
            return None
        if rule.protocols:
            protocol_specs = [ProtocolSpec.parse(value) for value in rule.protocols]
            if not any(spec.matches(query.protocol) for spec in protocol_specs):
                return False
        port_specs = rule.port_specs() or (PortSpec.parse("*"),)
        if not any(spec.contains(query.port) for spec in port_specs):
            return False

        source_match = self._any_address_match(rule.source_specs(), source_value, source)
        dest_match = self._any_address_match(
            rule.destination_specs(),
            dest_value,
            destination,
        )
        if source_match is None or dest_match is None:
            return None
        return source_match and dest_match

    def _any_address_match(
        self,
        specs: tuple[AddressSpec, ...],
        value: str,
        endpoint: FlowEndpoint,
    ) -> bool | None:
        if not specs:
            return True
        uncertain = False
        for spec in specs:
            result = self._address_match(spec, value, endpoint)
            if result:
                return True
            if result is None:
                uncertain = True
        return None if uncertain else False

    def _crosses_vnet(self, source: FlowEndpoint, destination: FlowEndpoint) -> bool:
        return bool(source.vnet_id and destination.vnet_id and source.vnet_id != destination.vnet_id)

    def _verdict(self, hops: list[FlowHop], unknowns: list[str]) -> str:
        # An unresolved endpoint means the evaluated path may not be the real
        # one, so no verdict can be claimed — not even a deny.
        if unknowns or any(hop.decision == "unknown" for hop in hops):
            return VERDICT_INDETERMINATE
        if any(hop.decision == "deny" for hop in hops):
            return VERDICT_DENIED
        if not hops:
            return VERDICT_INDETERMINATE
        return VERDICT_ALLOWED

    def _summarize(
        self,
        source: FlowEndpoint,
        destination: FlowEndpoint,
        hops: list[FlowHop],
        verdict: str,
    ) -> str:
        left = source.name or source.raw
        right = destination.name or destination.raw
        controls = " -> ".join(hop.control for hop in hops) or "no enforcement points observed"
        return f"{left} => {right}: {verdict} via {controls}"


def validate_flow(
    snapshot: NetworkSnapshot, query: FlowQuery, topology: NetworkTopology | None = None
) -> FlowResult:
    """Convenience wrapper around :class:`TrafficFlowValidator`."""
    return TrafficFlowValidator(snapshot, topology).validate(query)
