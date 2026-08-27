"""Desired-state (proposed) versus discovered-state (observed) comparison.

The proposed change declares what the deployment *intends*. The ontology
projection reports what the estate *currently is*. Where those disagree before
deployment, the plan was built against a stale read of reality, and applying it
will do something other than what the author reviewed.

Three findings matter, and they are kept distinct because they demand different
operator responses:

* ``missing_target``  — the change updates or deletes a resource that is not in
  discovered state. Either the inventory is stale or the target is gone.
* ``unmanaged_drift`` — discovered state already differs from the change's
  recorded "before". The plan's diff is not the diff that will actually apply.
* ``untracked_create`` — the change creates a resource that already exists.

Nothing here asserts *why* a discrepancy exists. A stale snapshot and a
genuinely deleted resource are indistinguishable from this vantage point, so
both are reported as the same observation with the ambiguity stated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .models import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_REPLACE,
    ACTION_UPDATE,
    DiscoveredResource,
    ProposedChange,
    ProposedResourceChange,
    index_by_resource_id,
)

FINDING_MISSING_TARGET = "missing_target"
FINDING_UNMANAGED_DRIFT = "unmanaged_drift"
FINDING_UNTRACKED_CREATE = "untracked_create"
FINDING_MATCHED = "matched"

# Actions that require the target to already exist for the plan to be valid.
_REQUIRES_EXISTING = frozenset({ACTION_UPDATE, ACTION_DELETE, ACTION_REPLACE})


@dataclass(frozen=True)
class StateComparison:
    """One resource change measured against discovered state."""

    address: str
    finding: str
    action: str
    resource_id: str = ""
    detail: str = ""
    drifted_properties: tuple[str, ...] = ()
    discovered_observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "finding": self.finding,
            "action": self.action,
            "resource_id": self.resource_id,
            "detail": self.detail,
            "drifted_properties": list(self.drifted_properties),
            "discovered_observed_at": self.discovered_observed_at,
        }


def _compare_one(
    change: ProposedResourceChange,
    discovered: DiscoveredResource | None,
) -> StateComparison:
    if change.action in _REQUIRES_EXISTING and discovered is None:
        return StateComparison(
            address=change.address,
            finding=FINDING_MISSING_TARGET,
            action=change.action,
            resource_id=change.resource_id,
            detail=(
                "The change targets a resource that is absent from discovered state. "
                "The inventory snapshot may be stale, the resource may already be deleted, "
                "or it may lie outside the authorized scope. This cannot be distinguished here."
            ),
        )

    if change.action == ACTION_CREATE and discovered is not None:
        return StateComparison(
            address=change.address,
            finding=FINDING_UNTRACKED_CREATE,
            action=change.action,
            resource_id=change.resource_id,
            detail=(
                "The change creates a resource that already exists in discovered state. "
                "Deployment may fail or adopt the existing resource."
            ),
            discovered_observed_at=discovered.observed_at,
        )

    if discovered is not None and change.before:
        drifted = tuple(
            name
            for name, expected in sorted(change.before.items())
            # Only compare properties the discovered projection actually
            # reports. Absence in the projection means "not observed", which is
            # not evidence of drift.
            if name in discovered.properties and discovered.properties[name] != expected
        )
        if drifted:
            return StateComparison(
                address=change.address,
                finding=FINDING_UNMANAGED_DRIFT,
                action=change.action,
                resource_id=change.resource_id,
                detail=(
                    "Discovered state differs from the state this change was planned against, "
                    "so the applied diff will not match the reviewed diff."
                ),
                drifted_properties=drifted,
                discovered_observed_at=discovered.observed_at,
            )

    return StateComparison(
        address=change.address,
        finding=FINDING_MATCHED,
        action=change.action,
        resource_id=change.resource_id,
        detail="Proposed state is consistent with discovered state.",
        discovered_observed_at=discovered.observed_at if discovered else "",
    )


def compare_states(
    change: ProposedChange,
    discovered: Sequence[DiscoveredResource],
) -> dict[str, Any]:
    """Compare every effective resource change against discovered state."""
    index = index_by_resource_id(discovered)
    comparisons = [
        _compare_one(item, index.get(item.resource_id.casefold()) if item.resource_id else None)
        for item in change.effective_changes
    ]
    by_finding: dict[str, int] = {}
    for comparison in comparisons:
        by_finding[comparison.finding] = by_finding.get(comparison.finding, 0) + 1

    unresolved = [item for item in change.effective_changes if not item.resource_id]
    unknowns: list[str] = []
    if unresolved:
        unknowns.append(
            f"{len(unresolved)} proposed change(s) carry no resolvable resource id, so they "
            "could not be compared against discovered state."
        )
    if not discovered:
        unknowns.append(
            "No discovered resources were available in scope; desired-versus-discovered "
            "comparison could not be performed."
        )

    return {
        "comparisons": [item.to_dict() for item in comparisons],
        "counts": by_finding,
        "consistent": by_finding.get(FINDING_MATCHED, 0) == len(comparisons) and bool(comparisons),
        "unknowns": unknowns,
        "compared_count": len(comparisons),
        "discovered_count": len(discovered),
    }
