"""Cross-subscription scope model.

Every API read is evaluated against a scope: the set of business dimensions a
request targets and a principal is permitted to see. Scope is the single place
where "which slice of the estate is this?" is expressed, so filtering and RBAC
share one vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

# The dimensions a caller may scope a query by. Ordered most- to least-specific
# for deterministic serialization and predictable OpenAPI parameter ordering.
SCOPE_DIMENSIONS: tuple[str, ...] = (
    "business_service",
    "application",
    "environment",
    "subscription",
    "subscription_connection",
    "owner",
    "support_team",
    "region",
    "criticality",
)

# Dimensions that RBAC grants can be written against. Subscription scope and
# business-service scope are the two enforcement axes required by the platform.
GRANTABLE_DIMENSIONS: tuple[str, ...] = ("subscription", "business_service")

WILDCARD = "*"


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_many(values: Any) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable):
        raise TypeError("Scope dimension values must be a string or iterable")
    return frozenset(filter(None, (_normalize(item) for item in values)))


@dataclass(frozen=True)
class Scope:
    """An immutable, multi-dimensional selector over the estate.

    An empty dimension means "unconstrained on this axis". A dimension with
    values matches an entity whose corresponding attribute is any of them.
    """

    dimensions: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        cleaned: dict[str, frozenset[str]] = {}
        for name, values in dict(self.dimensions).items():
            key = _normalize(name)
            if key not in SCOPE_DIMENSIONS:
                raise ValueError(f"Unknown scope dimension {name!r}")
            normalized = _normalize_many(values)
            if normalized:
                cleaned[key] = normalized
        object.__setattr__(self, "dimensions", dict(sorted(cleaned.items())))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> Scope:
        return cls(dict(payload or {}))

    @classmethod
    def unrestricted(cls) -> Scope:
        return cls({})

    def is_unrestricted(self) -> bool:
        return not self.dimensions

    def values(self, dimension: str) -> frozenset[str]:
        return self.dimensions.get(_normalize(dimension), frozenset())

    def with_dimension(self, dimension: str, values: Any) -> Scope:
        merged = dict(self.dimensions)
        normalized = _normalize_many(values)
        if normalized:
            merged[_normalize(dimension)] = normalized
        else:
            merged.pop(_normalize(dimension), None)
        return Scope(merged)

    def intersect(self, other: Scope) -> Scope:
        """Narrow this scope by another.

        Used to fold a principal's granted scope into a requested scope so the
        effective scope can never be broader than what the principal may see.
        """
        merged: dict[str, frozenset[str]] = {}
        for dimension in set(self.dimensions) | set(other.dimensions):
            mine = self.values(dimension)
            theirs = other.values(dimension)
            if mine and theirs:
                overlap = mine & theirs
                # An empty overlap on a constrained axis means the scopes are
                # disjoint. Encode that as an unsatisfiable sentinel rather
                # than silently widening to "unconstrained".
                merged[dimension] = overlap or frozenset({_EMPTY_SENTINEL})
            else:
                chosen = mine or theirs
                if chosen:
                    merged[dimension] = chosen
        return Scope(merged)

    def is_satisfiable(self) -> bool:
        return all(
            values != frozenset({_EMPTY_SENTINEL})
            for values in self.dimensions.values()
        )

    def matches(self, attributes: Mapping[str, Any]) -> bool:
        """True when an entity's attributes fall inside this scope."""
        if not self.is_satisfiable():
            return False
        for dimension, allowed in self.dimensions.items():
            value = _normalize(attributes.get(dimension))
            if not value or value not in allowed:
                return False
        return True

    def to_dict(self) -> dict[str, list[str]]:
        return {
            dimension: sorted(values)
            for dimension, values in self.dimensions.items()
        }


_EMPTY_SENTINEL = "\x00disjoint\x00"


def scope_attributes(payload: Mapping[str, Any]) -> dict[str, str]:
    """Project an entity/context payload onto the scope dimensions.

    Accepts the several spellings the ontology layer emits (``environment_name``
    from connection metadata, ``environment`` from tags, and so on) so scope
    filtering works against any of them.
    """
    aliases: dict[str, tuple[str, ...]] = {
        "business_service": ("business_service", "business_service_name", "businessService"),
        "application": ("application", "application_name", "applicationName", "appName"),
        "environment": ("environment", "environment_name", "environmentName"),
        "subscription": ("subscription", "subscription_id", "subscriptionId"),
        "subscription_connection": ("subscription_connection", "connection_id", "connectionId"),
        "owner": ("owner", "owner_name", "project_owner"),
        "support_team": ("support_team", "support_team_name", "supportTeam"),
        "region": ("region", "location"),
        "criticality": ("criticality", "severity_tier"),
    }
    attributes: dict[str, str] = {}
    for dimension, keys in aliases.items():
        for key in keys:
            if payload.get(key):
                attributes[dimension] = _normalize(payload[key])
                break
    return attributes


def subscription_ids_for_scope(
    scope: Scope,
    connections: Iterable[Any],
    *,
    default_all: bool = False,
) -> list[str]:
    """Resolve live Azure subscription scope through active connection records."""
    selected_subscriptions = scope.values("subscription")
    selected_connections = scope.values("subscription_connection")
    if not default_all and not selected_subscriptions and not selected_connections:
        return []
    if selected_subscriptions and not selected_connections:
        return sorted(selected_subscriptions)
    matched: dict[str, None] = {}
    for connection in connections:
        if not getattr(connection, "is_active", True):
            continue
        subscription_id = str(
            getattr(connection, "subscription_id", "") or ""
        ).strip()
        connection_id = str(
            getattr(connection, "connection_id", "") or ""
        ).strip()
        if not subscription_id or (selected_connections and not connection_id):
            continue
        if (
            selected_subscriptions
            and subscription_id.casefold() not in selected_subscriptions
        ):
            continue
        if (
            selected_connections
            and connection_id.casefold() not in selected_connections
        ):
            continue
        matched.setdefault(subscription_id, None)
    return list(matched)
