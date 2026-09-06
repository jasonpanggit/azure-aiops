"""Network intelligence service.

The single entry point every caller uses — API routers, CLI, and the semantic
layer. Loads a snapshot once, stitches topology once, and serves topology,
flow validation, rule findings, and design gaps from that shared state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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
            private_link_resources=tuple(
                i for i in snapshot.private_link_resources if keep(i)
            ),
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
            "projected_full_node_count": self.topology.projected_full_node_count(),
        }


def _count_by(items: Iterable[Any], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(getattr(item, attribute, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def _snapshot_resource_ids(snapshot: NetworkSnapshot) -> set[str]:
    """Return every addressable resource id retained by a snapshot."""
    groups = (
        snapshot.vnets,
        snapshot.subnets,
        snapshot.nics,
        snapshot.nsgs,
        snapshot.route_tables,
        snapshot.peerings,
        snapshot.firewalls,
        snapshot.firewall_policies,
        snapshot.firewall_collections,
        snapshot.private_endpoints,
        snapshot.private_dns_zones,
        snapshot.gateways,
        snapshot.load_balancers,
        snapshot.shared_services,
        snapshot.private_link_resources,
    )
    resource_ids = {
        resource.resource_id
        for group in groups
        for resource in group
        if resource.resource_id
    }
    resource_ids.update(
        rule.resource_id for nsg in snapshot.nsgs for rule in nsg.rules
    )
    resource_ids.update(
        route.resource_id for table in snapshot.route_tables for route in table.routes
    )
    resource_ids.update(
        rule.resource_id
        for collection in snapshot.firewall_collections
        for rule in collection.rules
    )
    return resource_ids


def _scope_relationships(
    relationships: Iterable[Mapping[str, Any]],
    snapshot: NetworkSnapshot,
) -> tuple[dict[str, Any], ...]:
    """Keep semantic edges only when both endpoints survived snapshot scoping."""
    resource_ids = _snapshot_resource_ids(snapshot)
    return tuple(
        dict(relationship)
        for relationship in relationships
        if str(relationship.get("subject_id") or "").casefold() in resource_ids
        and str(relationship.get("object_id") or "").casefold() in resource_ids
    )


class NetworkIntelligenceService:
    """Builds and serves the network view of the estate."""

    def __init__(
        self,
        snapshot: NetworkSnapshot,
        *,
        policy: NetworkDesignPolicy | None = None,
        semantic_relationships: Iterable[Mapping[str, Any]] = (),
        flow_observations: Iterable[Mapping[str, Any]] | None = None,
        peer_resolutions: Mapping[str, str] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.policy = policy if policy is not None else NetworkDesignPolicy()
        self.semantic_relationships = tuple(
            {
                **dict(row),
                "subject_id": str(row.get("subject_id") or "").casefold(),
                "object_id": str(row.get("object_id") or "").casefold(),
            }
            for row in semantic_relationships
        )
        self.flow_observations = (
            None
            if flow_observations is None
            else tuple(dict(row) for row in flow_observations)
        )
        self.peer_resolutions = (
            None
            if peer_resolutions is None
            else {
                str(peer_id or "").casefold(): str(resolution or "")
                for peer_id, resolution in peer_resolutions.items()
            }
        )
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
        observed_at: str | None = None,
        flow_observations: Iterable[Mapping[str, Any]] | None = None,
    ) -> NetworkIntelligenceService:
        resolved = policy if policy is not None else load_design_policy(policy_path)
        return cls(
            load_network_snapshot(rows, observed_at=observed_at),
            policy=resolved,
            semantic_relationships=semantic_relationships,
            flow_observations=flow_observations,
        )

    @classmethod
    def from_arg_rows(
        cls,
        rows: Iterable[Mapping[str, Any]],
        *,
        observed_at: str = "",
        policy: NetworkDesignPolicy | None = None,
        policy_path: str | None = None,
        flow_observations: Iterable[Mapping[str, Any]] | None = None,
    ) -> NetworkIntelligenceService:
        """Normalize raw ARG resources before loading the typed network view.

        ``from_rows`` consumes canonical ontology entities. Request-time ARG
        queries instead return parent/child ARM resources without
        ``entityType``; feeding those rows directly to the ontology loader
        produces an empty topology. Reuse the ingestion normalizer so live and
        synchronized views share the same ID and nested-resource semantics.
        """
        from onboarding.graph_normalize import Normalizer
        from onboarding.query_catalog import NETWORK_RESOURCE_TYPES

        materialized = [dict(row) for row in rows]
        payload: dict[str, list[dict]] = {"resources": materialized}
        for family, resource_types in NETWORK_RESOURCE_TYPES.items():
            accepted = {resource_type.casefold() for resource_type in resource_types}
            payload[family] = [
                row
                for row in materialized
                if str(row.get("type") or "").casefold() in accepted
            ]

        timestamp = datetime.now(UTC)
        if observed_at.strip():
            try:
                timestamp = datetime.fromisoformat(observed_at.strip())
            except ValueError:
                pass
        graph = Normalizer().normalize(payload, timestamp, run_id="live-network")
        normalized_rows = [
            entity
            for entities in graph.entities.values()
            for entity in entities
        ]
        semantic_relationships = [
            {
                **relationship,
                "subject_id": relationship.get("subjectId", ""),
                "object_id": relationship.get("objectId", ""),
            }
            for relationship in graph.relationships
        ]
        return cls.from_rows(
            normalized_rows,
            policy=policy,
            policy_path=policy_path,
            semantic_relationships=semantic_relationships,
            observed_at=observed_at,
            flow_observations=flow_observations,
        )

    @property
    def topology(self) -> NetworkTopology:
        if self._topology is None:
            self._topology = TopologyBuilder().build(
                self.snapshot,
                self.semantic_relationships,
                flow_log_provenance=self.flow_log_provenance,
                peer_resolutions=self.peer_resolutions,
            )
        return self._topology

    @property
    def flow_log_provenance(self) -> dict[str, Any]:
        evidence = tuple(
            row
            for row in self.semantic_relationships
            if str(row.get("predicate") or "").casefold() == "trafficobserved"
            and isinstance(row.get("attributes"), Mapping)
            and row["attributes"].get("dataSource") == "traffic_analytics"
        )
        if self.flow_observations is None:
            return {
                "state": "ingested_not_analyzed" if evidence else "not_ingested",
                "observed_flow_count": len(evidence),
            }
        analyzed = tuple(
            row
            for row in self.flow_observations
            if isinstance(row.get("attributes"), Mapping)
            and row["attributes"].get("dataSource") == "traffic_analytics"
        )
        return {
            "state": "analyzed",
            "observed_flow_count": len(analyzed),
        }

    @property
    def gaps(self) -> tuple[NetworkGap, ...]:
        if self._gaps is None:
            self._gaps = NetworkGapAnalyzer(self.snapshot, self.topology, self.policy).analyze()
        return self._gaps

    @property
    def rule_findings(self) -> tuple[RuleFinding, ...]:
        if self._findings is None:
            self._findings = analyze_rules(
                self.snapshot,
                self.flow_observations or (),
            )
        return self._findings

    def analyze(self) -> NetworkAnalysis:
        return NetworkAnalysis(
            topology=self.topology,
            gaps=self.gaps,
            rule_findings=self.rule_findings,
            policy=self.policy,
        )

    def scoped(self, scope: NetworkScope) -> NetworkIntelligenceService:
        """Return an isolated service whose every operation sees only ``scope``."""
        if scope.is_empty:
            return self
        snapshot = scope.filter_snapshot(self.snapshot)
        unscoped_vnet_ids = {vnet.resource_id for vnet in self.snapshot.vnets}
        scoped_vnet_ids = {vnet.resource_id for vnet in snapshot.vnets}
        peer_resolutions: dict[str, str] = {}
        for peering in snapshot.peerings:
            peer_id = peering.remote_vnet_id
            if not peer_id:
                continue
            if peer_id in scoped_vnet_ids:
                peer_resolutions[peer_id] = "observed"
            elif peer_id in unscoped_vnet_ids:
                peer_resolutions[peer_id] = "excluded_by_scope"
            else:
                peer_resolutions[peer_id] = "not_ingested"
        return NetworkIntelligenceService(
            snapshot,
            policy=self.policy,
            semantic_relationships=_scope_relationships(
                self.semantic_relationships,
                snapshot,
            ),
            flow_observations=(
                None
                if self.flow_observations is None
                else _scope_relationships(
                    self.flow_observations,
                    snapshot,
                )
            ),
            peer_resolutions=peer_resolutions,
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

def build_service(
    rows: Iterable[Mapping[str, Any]],
    *,
    policy_path: str | None = None,
) -> NetworkIntelligenceService:
    """Convenience wrapper for callers holding raw ontology rows."""
    return NetworkIntelligenceService.from_rows(rows, policy_path=policy_path)
