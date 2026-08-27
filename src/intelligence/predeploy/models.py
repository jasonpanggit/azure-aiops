"""Normalized model for a *proposed* change, before it is deployed.

The distinction from ``intelligence.change`` matters: that package explains
changes that have already happened (Activity Log, drift, incident correlation).
Everything here describes an intent that does not yet exist in Azure, so no
statement in this package may be presented as an observation of the estate.

A proposed change is deliberately source-agnostic. Terraform plans, Bicep
what-if results, ARM diffs, GitHub pull requests, and Azure DevOps changes all
normalize into the same shape so downstream blast-radius, simulation, risk, and
CAB stages never branch on where the change came from.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Source systems a proposed change can be ingested from.
SOURCE_TERRAFORM = "terraform_plan"
SOURCE_BICEP = "bicep_what_if"
SOURCE_ARM = "arm_diff"
SOURCE_GITHUB = "github_pull_request"
SOURCE_AZURE_DEVOPS = "azure_devops"

CHANGE_SOURCES: tuple[str, ...] = (
    SOURCE_TERRAFORM,
    SOURCE_BICEP,
    SOURCE_ARM,
    SOURCE_GITHUB,
    SOURCE_AZURE_DEVOPS,
)

# What the change intends to do to a resource. ``replace`` is kept distinct from
# ``update`` because a replace is a destroy plus a create: it carries downtime
# and identity-rotation risk an in-place update does not.
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_REPLACE = "replace"
ACTION_DELETE = "delete"
ACTION_NOOP = "no-op"
ACTION_UNKNOWN = "unknown"

CHANGE_ACTIONS: tuple[str, ...] = (
    ACTION_CREATE,
    ACTION_UPDATE,
    ACTION_REPLACE,
    ACTION_DELETE,
    ACTION_NOOP,
    ACTION_UNKNOWN,
)

# Actions that remove or recreate capacity. Grouped once here so risk,
# simulation, and CAB all agree on what "destructive" means.
DESTRUCTIVE_ACTIONS: frozenset[str] = frozenset({ACTION_DELETE, ACTION_REPLACE})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _key(value: Any) -> str:
    return _text(value).casefold()


@dataclass(frozen=True)
class ProposedResourceChange:
    """One resource-level intent inside a proposed change set."""

    address: str
    action: str = ACTION_UNKNOWN
    resource_type: str = ""
    resource_id: str = ""
    name: str = ""
    provider: str = ""
    changed_properties: tuple[str, ...] = ()
    before: Mapping[str, Any] = field(default_factory=dict)
    after: Mapping[str, Any] = field(default_factory=dict)
    # Free-form attribution back to the source system (plan index, PR file,
    # what-if change id) so a finding can always be traced to its origin.
    source_ref: str = ""

    def __post_init__(self) -> None:
        address = _text(self.address)
        if not address:
            raise ValueError("ProposedResourceChange address is required")
        object.__setattr__(self, "address", address)
        action = _key(self.action) or ACTION_UNKNOWN
        if action not in CHANGE_ACTIONS:
            action = ACTION_UNKNOWN
        object.__setattr__(self, "action", action)
        for name in ("resource_type", "resource_id", "name", "provider", "source_ref"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(
            self,
            "changed_properties",
            tuple(dict.fromkeys(_text(item) for item in self.changed_properties if _text(item))),
        )
        object.__setattr__(self, "before", dict(self.before or {}))
        object.__setattr__(self, "after", dict(self.after or {}))

    @property
    def is_destructive(self) -> bool:
        return self.action in DESTRUCTIVE_ACTIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "name": self.name,
            "provider": self.provider,
            "changed_properties": list(self.changed_properties),
            "is_destructive": self.is_destructive,
            "source_ref": self.source_ref,
        }


@dataclass(frozen=True)
class ProposedChange:
    """A complete, normalized change set awaiting deployment."""

    change_id: str
    source: str
    resource_changes: tuple[ProposedResourceChange, ...] = ()
    title: str = ""
    author: str = ""
    submitted_at: str = ""
    target_subscriptions: tuple[str, ...] = ()
    target_environment: str = ""
    repository: str = ""
    # Parse problems that prevented full normalization. These become declared
    # unknowns downstream rather than being silently dropped, so a partially
    # readable plan can never masquerade as a fully understood one.
    ingestion_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        change_id = _text(self.change_id)
        if not change_id:
            raise ValueError("ProposedChange change_id is required")
        object.__setattr__(self, "change_id", change_id)
        source = _key(self.source)
        if source not in CHANGE_SOURCES:
            raise ValueError(f"Unknown proposed-change source {self.source!r}")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "resource_changes", tuple(self.resource_changes))
        for name in ("title", "author", "submitted_at", "target_environment", "repository"):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(
            self,
            "target_subscriptions",
            tuple(dict.fromkeys(_key(item) for item in self.target_subscriptions if _key(item))),
        )
        object.__setattr__(
            self,
            "ingestion_warnings",
            tuple(dict.fromkeys(_text(item) for item in self.ingestion_warnings if _text(item))),
        )

    @property
    def effective_changes(self) -> tuple[ProposedResourceChange, ...]:
        """Resource changes that actually alter state (no-ops excluded)."""
        return tuple(item for item in self.resource_changes if item.action != ACTION_NOOP)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "source": self.source,
            "title": self.title,
            "author": self.author,
            "submitted_at": self.submitted_at,
            "repository": self.repository,
            "target_environment": self.target_environment,
            "target_subscriptions": list(self.target_subscriptions),
            "resource_changes": [item.to_dict() for item in self.resource_changes],
            "effective_change_count": len(self.effective_changes),
            "ingestion_warnings": list(self.ingestion_warnings),
        }


@dataclass(frozen=True)
class DiscoveredResource:
    """Current, observed state of a resource in the estate.

    Supplied by the ontology/inventory projection. Used as the discovered side
    of the desired-versus-discovered comparison and as the graph node blast
    radius traverses.
    """

    resource_id: str
    resource_type: str = ""
    name: str = ""
    application: str = ""
    business_service: str = ""
    environment: str = ""
    subscription: str = ""
    owner: str = ""
    support_team: str = ""
    region: str = ""
    criticality: str = ""
    depends_on: tuple[str, ...] = ()
    properties: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str = ""

    def __post_init__(self) -> None:
        resource_id = _text(self.resource_id)
        if not resource_id:
            raise ValueError("DiscoveredResource resource_id is required")
        object.__setattr__(self, "resource_id", resource_id)
        for name in (
            "resource_type",
            "name",
            "application",
            "business_service",
            "environment",
            "subscription",
            "owner",
            "support_team",
            "region",
            "criticality",
            "observed_at",
        ):
            object.__setattr__(self, name, _text(getattr(self, name)))
        object.__setattr__(
            self,
            "depends_on",
            tuple(dict.fromkeys(_text(item) for item in self.depends_on if _text(item))),
        )
        object.__setattr__(self, "properties", dict(self.properties or {}))

    def scope_attributes(self) -> dict[str, str]:
        """Project onto scope dimensions for authorization filtering."""
        return {
            "business_service": _key(self.business_service),
            "application": _key(self.application),
            "environment": _key(self.environment),
            "subscription": _key(self.subscription),
            "owner": _key(self.owner),
            "support_team": _key(self.support_team),
            "region": _key(self.region),
            "criticality": _key(self.criticality),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_type": self.resource_type,
            "name": self.name,
            "application": self.application,
            "business_service": self.business_service,
            "environment": self.environment,
            "subscription": self.subscription,
            "owner": self.owner,
            "support_team": self.support_team,
            "region": self.region,
            "criticality": self.criticality,
            "depends_on": list(self.depends_on),
            "observed_at": self.observed_at,
        }


def index_by_resource_id(
    resources: Iterable[DiscoveredResource],
) -> dict[str, DiscoveredResource]:
    """Case-insensitive index, since ARM ids vary in casing between sources."""
    return {_key(item.resource_id): item for item in resources}


def dependents_of(
    resources: Sequence[DiscoveredResource],
) -> dict[str, tuple[str, ...]]:
    """Invert ``depends_on`` into a dependents ("who breaks if this breaks") map."""
    inverted: dict[str, list[str]] = {}
    for resource in resources:
        for dependency in resource.depends_on:
            inverted.setdefault(_key(dependency), []).append(resource.resource_id)
    return {key: tuple(dict.fromkeys(values)) for key, values in inverted.items()}


def unrestricted_scope() -> Any:
    """Return an unrestricted :class:`api.scope.Scope`.

    Imported lazily because ``api`` loads the FastAPI app, whose router package
    imports this one; a module-level import would be circular.
    """
    from api.scope import Scope

    return Scope.unrestricted()
