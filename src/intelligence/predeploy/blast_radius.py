"""Dependency-aware blast-radius analysis for a proposed change.

Blast radius answers "if this change goes wrong, what else is in the path?"
It is a *reachability* result, not a prediction: a resource appearing in the
radius means it depends transitively on something the change touches, which is
a structural fact about the dependency graph. Whether it would actually fail
depends on runtime behaviour this engine cannot observe, so every result is
labelled as potential impact and never as predicted failure.

Traversal is breadth-first over the inverted dependency graph and bounded by an
explicit hop limit. The bound is not an optimization — an unbounded radius in a
connected estate degenerates to "everything", which tells an approver nothing.
Truncation is always reported so a bounded answer is never mistaken for a
complete one.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

# ``api`` imports the FastAPI app, whose router package imports this one. A
# module-level import here would therefore be circular, so Scope is imported
# lazily at its single use site and only typed statically.
if TYPE_CHECKING:
    from api.scope import Scope

from .models import (
    DiscoveredResource,
    ProposedChange,
    dependents_of,
    index_by_resource_id,
    unrestricted_scope,
)

# Hops of dependency traversal. Two hops covers "what calls the thing I changed"
# and "what calls that" — the horizon an approver can still reason about.
DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_NODES = 500


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _network_exposure(resource: DiscoveredResource) -> dict[str, Any]:
    """Network-control facts attached to a resource, when the projection has them."""
    properties = resource.properties
    exposure: dict[str, Any] = {}
    for source_key, label in (
        ("nsg_rules", "nsg_rules"),
        ("firewall_rules", "firewall_rules"),
        ("route_table", "route_table"),
        ("private_endpoints", "private_endpoints"),
        ("public_network_access", "public_network_access"),
    ):
        if source_key in properties:
            exposure[label] = properties[source_key]
    return exposure


def analyze_blast_radius(
    change: ProposedChange,
    discovered: Sequence[DiscoveredResource],
    *,
    scope: Scope | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    vulnerability_index: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Traverse dependents of every directly-changed resource.

    ``scope`` is applied to every node *as it is visited*, so an unauthorized
    resource is never counted, named, or used to widen the radius. Filtering at
    traversal time rather than on the final result is what prevents scope
    leakage through aggregate counts.
    """
    effective_scope = scope or unrestricted_scope()
    index = index_by_resource_id(discovered)
    dependents = dependents_of(discovered)
    vulnerabilities = {_key(key): list(value) for key, value in (vulnerability_index or {}).items()}

    def in_scope(resource: DiscoveredResource) -> bool:
        return effective_scope.matches(resource.scope_attributes())

    # Seed: resources the change touches directly and that we can both resolve
    # and authorize. Unresolvable targets become declared unknowns.
    seeds: list[DiscoveredResource] = []
    unresolved: list[str] = []
    out_of_scope_seeds = 0
    for item in change.effective_changes:
        resource = index.get(_key(item.resource_id)) if item.resource_id else None
        if resource is None:
            unresolved.append(item.address)
            continue
        if not in_scope(resource):
            out_of_scope_seeds += 1
            continue
        seeds.append(resource)

    visited: dict[str, int] = {}
    impacted: list[dict[str, Any]] = []
    truncated = False
    queue: deque[tuple[DiscoveredResource, int]] = deque()

    for resource in seeds:
        key = _key(resource.resource_id)
        if key in visited:
            continue
        visited[key] = 0
        queue.append((resource, 0))

    while queue:
        resource, depth = queue.popleft()
        record: dict[str, Any] = {
            **resource.to_dict(),
            "depth": depth,
            "relationship": "directly_changed" if depth == 0 else "depends_on_changed_resource",
        }
        exposure = _network_exposure(resource)
        if exposure:
            record["network_exposure"] = exposure
        findings = vulnerabilities.get(_key(resource.resource_id))
        if findings:
            record["vulnerability_findings"] = list(findings)
        impacted.append(record)

        if depth >= max_depth:
            # Reaching the depth bound with dependents still unexplored means
            # the radius is genuinely incomplete, not merely finished.
            if dependents.get(_key(resource.resource_id)):
                truncated = True
            continue

        for dependent_id in dependents.get(_key(resource.resource_id), ()):
            key = _key(dependent_id)
            if key in visited:
                continue
            dependent = index.get(key)
            if dependent is None or not in_scope(dependent):
                continue
            if len(visited) >= max_nodes:
                truncated = True
                break
            visited[key] = depth + 1
            queue.append((dependent, depth + 1))

    # Roll the impacted set up along the dimensions an approver decides on.
    def distinct(field: str) -> list[str]:
        return sorted({str(row.get(field)) for row in impacted if row.get(field)})

    unknowns: list[str] = []
    if unresolved:
        unknowns.append(
            f"{len(unresolved)} changed resource(s) could not be located in discovered state, "
            "so anything depending on them is absent from this blast radius."
        )
    if out_of_scope_seeds:
        unknowns.append(
            f"{out_of_scope_seeds} changed resource(s) fall outside the authorized scope and "
            "were excluded; the true blast radius may be larger."
        )
    if truncated:
        unknowns.append(
            f"Traversal stopped at depth {max_depth} or {max_nodes} nodes; "
            "downstream dependents beyond that bound were not evaluated."
        )
    if not discovered:
        unknowns.append("No discovered resources were in scope; blast radius could not be derived.")

    return {
        "impacted_resources": impacted,
        "directly_changed_count": sum(1 for row in impacted if row["depth"] == 0),
        "total_impacted_count": len(impacted),
        "max_depth_reached": max(visited.values(), default=0),
        "applications": distinct("application"),
        "business_services": distinct("business_service"),
        "subscriptions": distinct("subscription"),
        "environments": distinct("environment"),
        "owners": distinct("owner"),
        "support_teams": distinct("support_team"),
        "regions": distinct("region"),
        "network_controls_in_path": sum(1 for row in impacted if row.get("network_exposure")),
        "vulnerable_resources_in_path": sum(1 for row in impacted if row.get("vulnerability_findings")),
        "truncated": truncated,
        "unknowns": unknowns,
        # Load-bearing: everything above describes graph reachability. Without
        # this qualifier a reader could reasonably read "impacted" as "will break".
        "interpretation": (
            "Resources listed here depend, directly or transitively, on something this change "
            "modifies. That is a structural dependency relationship, not a prediction of failure."
        ),
        "confirmed_impact": False,
    }
