"""Network intelligence service.

The single entry point every caller uses — API routers, CLI, and the semantic
layer. Loads a snapshot once, stitches topology once, and serves topology,
flow validation, rule findings, and design gaps from that shared state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .design import NetworkDesignPolicy, load_design_policy
from .flow import FlowQuery, FlowResult, TrafficFlowValidator
from .gaps import NetworkGap, NetworkGapAnalyzer
from .loader import load_network_snapshot
from .models import NetworkSnapshot
from .tightening import RuleFinding, analyze_rules
from .topology import NetworkTopology, TopologyBuilder

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@dataclass(frozen=True)
class NetworkScope:
    """Filters applied to network results.

    Mirrors the platform-wide scope model so a UI selection narrows network
    results the same way it narrows every other surface.
    """

    connection_ids: tuple[str, ...] = ()
    subscription_ids: tuple[str, ...] = ()
    environments: tuple[str, ...] = ()
    business_services: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.connection_ids,
                self.subscription_ids,
                self.environments,
                self.business_services,
                self.applications,
                self.owners,
            )
        )

    def matches(self, item: Any) -> bool:
        if self.is_empty:
            return True
        return (
            self._match(self.connection_ids, getattr(item, "connection_id", ""))
            and self._match(self.subscription_ids, getattr(item, "subscription_id", ""))
            and self._match(self.environments, getattr(item, "environment", ""))
            and self._match(self.business_services, getattr(item, "business_service", ""))
            and self._match(self.applications, getattr(item, "application", ""))
            and self._match(self.owners, getattr(item, "owner", ""))
        )

    def filter_snapshot(self, snapshot: NetworkSnapshot) -> NetworkSnapshot:
        """Narrows a snapshot to the in-scope resources.

        The topology summary is derived from the snapshot, so filtering only
        the classifications would still report estate-wide counts and
        connection IDs to a scoped caller -- a disclosure across the same
        authorization boundary the scope exists to enforce.
        """
        if self.is_empty:
            return snapshot
        keep = self.matches
        return replace(
            snapshot,
            vnets=tuple(i for i in snapshot.vnets if keep(i)),
            subnets=tuple(i for i in snapshot.subnets if keep(i)),
            nics=tuple(i for i in snapshot.nics if keep(i)),
            nsgs=tuple(i for i in snapshot.nsgs if keep(i)),
            route_tables=tuple(i for i in snapshot.route_tables if keep(i)),
            peerings=tuple(i for i in snapshot.peerings if keep(i)),
            firewalls=tuple(i for i in snapshot.firewalls if keep(i)),
            firewall_policies=tuple(i for i in snapshot.firewall_policies if keep(i)),
            firewall_collections=tuple(
                i for i in snapshot.firewall_collections if keep(i)
            ),
            private_endpoints=tuple(i for i in snapshot.private_endpoints if keep(i)),
            private_dns_zones=tuple(i for i in snapshot.private_dns_zones if keep(i)),
            gateways=tuple(i for i in snapshot.gateways if keep(i)),
            load_balancers=tuple(i for i in snapshot.load_balancers if keep(i)),
            shared_services=tuple(i for i in snapshot.shared_services if keep(i)),
        )

    @staticmethod
    def _match(allowed: tuple[str, ...], value: Any) -> bool:
        if not allowed:
            return True
        folded = str(value or "").casefold()
        return folded in {str(item).casefold() for item in allowed}


@dataclass(frozen=True)
class NetworkAnalysis:
    """Everything the network surface can report for one scope."""

    topology: NetworkTopology
    gaps: tuple[NetworkGap, ...]
    rule_findings: tuple[RuleFinding, ...]
    policy: NetworkDesignPolicy

    def summary(self) -> dict[str, Any]:
        return {
            "hub_count": len(self.topology.hubs),
            "spoke_count": len(self.topology.spokes),
            "isolated_vnet_count": len(self.topology.isolated),
            "peering_count": len(self.topology.links),
            "cross_subscription_peering_count": sum(
                1 for link in self.topology.links if link.is_cross_subscription
            ),
            "unhealthy_peering_count": sum(
                1 for link in self.topology.links if not link.is_healthy
            ),
            "shared_service_count": len(self.topology.shared_services),
            "connection_count": len(self.topology.connection_ids),
            "gap_count": len(self.gaps),
            "gaps_by_severity": _count_by(self.gaps, "severity"),
            "gaps_by_category": _count_by(self.gaps, "category"),
            "rule_finding_count": len(self.rule_findings),
            "rule_findings_by_severity": _count_by(self.rule_findings, "severity"),
            "rule_findings_by_category": _count_by(self.rule_findings, "category"),
            "intended_design_declared": self.policy.is_declared,
            "resource_counts": self.topology.snapshot.counts(),
        }


def _count_by(items: Iterable[Any], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(getattr(item, attribute, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


class NetworkIntelligenceService:
    """Builds and serves the network view of the estate."""

    def __init__(
        self,
        snapshot: NetworkSnapshot,
        *,
        policy: NetworkDesignPolicy | None = None,
        semantic_relationships: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self.snapshot = snapshot
        self.policy = policy if policy is not None else NetworkDesignPolicy()
        self.semantic_relationships = tuple(dict(row) for row in semantic_relationships)
        self._topology: NetworkTopology | None = None
        self._gaps: tuple[NetworkGap, ...] | None = None
        self._findings: tuple[RuleFinding, ...] | None = None

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        policy: NetworkDesignPolicy | None = None,
        policy_path: str | None = None,
        semantic_relationships: Iterable[Mapping[str, Any]] = (),
    ) -> NetworkIntelligenceService:
        resolved = policy if policy is not None else load_design_policy(policy_path)
        return cls(
            load_network_snapshot(rows),
            policy=resolved,
            semantic_relationships=semantic_relationships,
        )

    @property
    def topology(self) -> NetworkTopology:
        if self._topology is None:
            self._topology = TopologyBuilder().build(self.snapshot, self.semantic_relationships)
        return self._topology

    @property
    def gaps(self) -> tuple[NetworkGap, ...]:
        if self._gaps is None:
            self._gaps = NetworkGapAnalyzer(self.snapshot, self.topology, self.policy).analyze()
        return self._gaps

    @property
    def rule_findings(self) -> tuple[RuleFinding, ...]:
        if self._findings is None:
            self._findings = analyze_rules(self.snapshot)
        return self._findings

    def analyze(self, scope: NetworkScope | None = None) -> NetworkAnalysis:
        active = scope or NetworkScope()
        return NetworkAnalysis(
            topology=self._scoped_topology(active),
            gaps=tuple(gap for gap in self.gaps if active.matches(gap)),
            rule_findings=tuple(item for item in self.rule_findings if active.matches(item)),
            policy=self.policy,
        )

    def scoped(self, scope: NetworkScope) -> NetworkIntelligenceService:
        """Return an isolated service whose every operation sees only ``scope``."""
        if scope.is_empty:
            return self
        return NetworkIntelligenceService(
            scope.filter_snapshot(self.snapshot),
            policy=self.policy,
        )

    def validate_flow(self, query: FlowQuery) -> FlowResult:
        return TrafficFlowValidator(self.snapshot, self.topology).validate(query)

    def validate_flows(self, queries: Iterable[FlowQuery]) -> tuple[FlowResult, ...]:
        validator = TrafficFlowValidator(self.snapshot, self.topology)
        return tuple(validator.validate(query) for query in queries)

    def hub_dependents(self, hub_vnet_id: str) -> dict[str, Any]:
        """Answers "what depends on the hub?" for one hub."""
        target = str(hub_vnet_id or "").casefold()
        peers = self.topology.peers_of(target)
        services = [
            service
            for service in self.topology.shared_services
            if service.hub_vnet_id == target
        ]
        vnets = {vnet.resource_id: vnet for vnet in self.snapshot.vnets}
        return {
            "hub_vnet_id": target,
            "hub_name": vnets[target].name if target in vnets else "",
            "dependent_vnets": [
                {
                    "vnet_id": peer,
                    "name": vnets[peer].name if peer in vnets else "",
                    "connection_id": vnets[peer].connection_id if peer in vnets else "",
                    "subscription_id": vnets[peer].subscription_id if peer in vnets else "",
                    "business_service": vnets[peer].business_service if peer in vnets else "",
                    "environment": vnets[peer].environment if peer in vnets else "",
                    "observed": peer in vnets,
                }
                for peer in peers
            ],
            "shared_services": [service.to_dict() for service in services],
            "dependent_count": len(peers),
        }

    def firewall_bypass_spokes(self) -> tuple[NetworkGap, ...]:
        """Answers "which spokes bypass the firewall?"."""
        return tuple(gap for gap in self.gaps if gap.category == "firewall_bypass")

    def _scoped_topology(self, scope: NetworkScope) -> NetworkTopology:
        if scope.is_empty:
            return self.topology
        base = self.topology
        classifications = tuple(item for item in base.classifications if scope.matches(item))
        kept = {item.vnet_id for item in classifications}
        scoped_snapshot = scope.filter_snapshot(base.snapshot)
        return NetworkTopology(
            classifications=classifications,
            links=tuple(
                link
                for link in base.links
                if link.local_vnet_id in kept and link.remote_vnet_id in kept
            ),
            shared_services=tuple(
                service for service in base.shared_services if scope.matches(service)
            ),
            unresolved_peer_vnet_ids=base.unresolved_peer_vnet_ids,
            connection_ids=scoped_snapshot.connection_ids(),
            snapshot=scoped_snapshot,
        )


def build_service(
    rows: Iterable[Mapping[str, Any]],
    *,
    policy_path: str | None = None,
) -> NetworkIntelligenceService:
    """Convenience wrapper for callers holding raw ontology rows."""
    return NetworkIntelligenceService.from_rows(rows, policy_path=policy_path)
