"""Projection of the ontology snapshot into pre-deployment discovered state.

The engine needs a flat, dependency-bearing view of the estate. The semantic
indexes hold that information, but spread across entity rows, inventory facts,
and typed edges. This module is the single translation point between the two.

Dependency edges are read in the ``in`` direction: an entity that something
else *connects to* or is *hosted on* is a dependency of that other entity. The
blast radius then inverts this again to walk outward to dependents. Doing the
inversion once, explicitly, in :func:`models.dependents_of` keeps the direction
convention in one place instead of scattered across traversal code.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from .models import DiscoveredResource, unrestricted_scope

# ``api`` imports the FastAPI app, whose router package imports this one, so
# Scope is typed statically and constructed lazily.
if TYPE_CHECKING:
    from api.scope import Scope

# Edges where the subject depends on the object. Read in the ``out`` direction
# from a resource these give "what I need"; the blast radius inverts them.
_DEPENDENCY_PREDICATES: tuple[str, ...] = (
    "depends_on",
    "connects_to",
    "hosted_on",
    "runs_on",
    "attached_to",
    "member_of",
)

# Inventory facts worth carrying into simulation and network-exposure roll-ups.
_PROPERTY_FIELDS: tuple[str, ...] = (
    "public_network_access",
    "nsg_rules",
    "firewall_rules",
    "route_table",
    "private_endpoints",
    "sku",
    "status",
    "min_tls_version",
    "retention_days",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(values: Sequence[str]) -> str:
    return _text(values[0]) if values else ""


def project_discovered_resources(
    engine: Any,
    *,
    scope: Scope | None = None,
    limit: int = 5000,
) -> list[DiscoveredResource]:
    """Build discovered state from a semantic engine's indexes.

    ``scope`` is applied during projection so out-of-scope entities never enter
    the pipeline at all. Returns an empty list when the engine does not expose
    indexes, which keeps the caller free of ``hasattr`` checks.
    """
    indexes = getattr(engine, "indexes", None)
    if indexes is None:
        return []
    effective_scope = scope or unrestricted_scope()
    if not effective_scope.is_satisfiable():
        return []

    entities: dict[str, dict[str, Any]] = getattr(indexes, "entities", {}) or {}
    inventory: dict[str, dict[str, Any]] = getattr(indexes, "inventory", {}) or {}
    freshness = _text(getattr(engine, "ontology_synchronized_at", "")) or _text(
        getattr(engine, "freshness", "")
    )

    asset_types = {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"}
    resources: list[DiscoveredResource] = []

    for entity_id, row in entities.items():
        if _text(row.get("entity_type")) not in asset_types:
            continue
        if len(resources) >= limit:
            break

        facts = inventory.get(entity_id.casefold(), {}) or {}
        applications = _safe(indexes, "applications_for_resource", entity_id)
        application = _first(applications)
        business_services: list[str] = []
        support_teams: list[str] = []
        for app in applications:
            business_services.extend(_safe(indexes, "business_services_for_application", app))
            support_teams.extend(_safe(indexes, "support_teams_for_application", app))

        candidate = DiscoveredResource(
            resource_id=_text(row.get("resource_id")) or entity_id,
            resource_type=_text(row.get("resource_type")) or _text(row.get("entity_type")),
            name=_text(row.get("name")) or _text(facts.get("name")),
            application=application,
            business_service=_first(business_services),
            environment=_text(row.get("environment")) or _text(facts.get("environment")),
            subscription=_text(row.get("subscription_id")) or _text(facts.get("subscription_id")),
            owner=_first(_safe(indexes, "owners_for_resource", entity_id)),
            support_team=_first(support_teams),
            region=_text(row.get("region")) or _text(facts.get("location")),
            criticality=_text(row.get("criticality")) or _text(facts.get("criticality")),
            depends_on=_dependencies(indexes, entity_id, entities),
            properties={
                field: facts[field] for field in _PROPERTY_FIELDS if field in facts
            },
            observed_at=freshness,
        )
        if effective_scope.matches(candidate.scope_attributes()):
            resources.append(candidate)

    return resources


def _dependencies(
    indexes: Any,
    entity_id: str,
    entities: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Resource ids this entity depends on, de-duplicated and ordered."""
    found: list[str] = []
    seen: set[str] = set()
    for predicate in _DEPENDENCY_PREDICATES:
        for target in _safe(indexes, "related", entity_id, predicate):
            row = entities.get(target) or {}
            resource_id = _text(row.get("resource_id")) or target
            key = resource_id.casefold()
            if key not in seen:
                seen.add(key)
                found.append(resource_id)
    return tuple(found)


def _safe(target: Any, method: str, *args: Any) -> list[str]:
    """Call an index helper, treating any lookup failure as "no relationship".

    The indexes raise on unknown ids and on entity types that do not
    participate in a given edge, which is normal while walking a heterogeneous
    entity set. Those are absences, not errors.
    """
    func = getattr(target, method, None)
    if not callable(func):
        return []
    try:
        return [str(value) for value in func(*args) or ()]
    except (KeyError, ValueError, TypeError):
        return []
