"""Deferred/retry store for relationships whose endpoints aren't discovered yet.

``OntologyValidator`` flags a relationship as *dangling* when its subject or
object id isn't present in the current entity snapshot. Historically those
edges were silently dropped by ``OntologyGraphSynchronizer.synchronize()`` --
correct from a validation standpoint (a dangling edge can never pass
:class:`~ontology.ontology_validator.OntologyValidator`), but wasteful: many
dangling edges exist only because discovery hasn't ingested the missing
resource *yet* (e.g. a lineage or dependency edge discovered before its
target's inventory row lands in the same sync).

:class:`PendingRelationshipStore` holds those edges keyed by the missing
entity id(s) they're waiting on, so a caller can retry them on a later sync
once the referenced entity appears -- without having to re-derive the edge
from scratch. The store is a plain in-memory/dict structure (mirroring the
lightweight, caller-persisted pattern already used by other onboarding
registries): callers that want durability serialize ``to_list()``/reload via
``from_list()`` themselves (e.g. alongside the rest of their sync state),
the same way :class:`~onboarding.registry.ConnectionRegistry` persists a
JSON document.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ontology_discovery.store import OntologyRunStore

#: Hard cap on how many edges may sit pending at once. Prevents unbounded
#: growth if an edge's target is never discovered (e.g. a stale/bad reference
#: from a misconfigured tag) -- the oldest pending edges are dropped once the
#: cap is exceeded rather than silently growing the store forever.
DEFAULT_MAX_PENDING = 10_000


def _missing_ids(edge: dict[str, Any], known_entity_ids: set[str]) -> set[str]:
    subject_id = str(edge.get("subject_id") or "").casefold()
    object_id = str(edge.get("object_id") or "").casefold()
    return {
        entity_id
        for entity_id in (subject_id, object_id)
        if entity_id and entity_id not in known_entity_ids
    }


class PendingRelationshipStore:
    """Holds dangling relationships until their missing endpoint appears."""

    def __init__(
        self,
        *,
        max_pending: int = DEFAULT_MAX_PENDING,
        durable_store: OntologyRunStore | None = None,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("PendingRelationshipStore max_pending must be a positive integer")
        self.max_pending = max_pending
        self._durable_store = durable_store
        self._pending: dict[str, dict[str, Any]] = {}

    def __len__(self) -> int:
        if self._durable_store is not None:
            return len(self._durable_store.list_pending_relationships())
        return len(self._pending)

    def defer(self, edges: list[dict[str, Any]]) -> None:
        """Persists ``edges`` (relationship rows) to be retried on a later sync."""
        if self._durable_store is not None:
            for edge in edges:
                self._durable_store.defer_pending_relationship(edge)
            active = self._durable_store.list_pending_relationships()
            for stale in active[: max(0, len(active) - self.max_pending)]:
                self._durable_store.transition_pending_relationship(
                    stale["pending_id"],
                    expected_revision=stale["revision"],
                    terminal_state="expired",
                )
            return
        for edge in edges:
            relationship_id = str(edge.get("resource_id") or "").casefold()
            if not relationship_id:
                continue
            self._pending[relationship_id] = dict(edge)
        if len(self._pending) > self.max_pending:
            # Oldest-inserted-first eviction: dict preserves insertion order,
            # so this keeps the most recently deferred edges.
            overflow = len(self._pending) - self.max_pending
            for stale_id in list(self._pending.keys())[:overflow]:
                del self._pending[stale_id]

    def resolve(
        self, known_entity_ids: set[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Splits stored edges into (resolved-now, still-pending) against ``known_entity_ids``.

        Resolved edges are removed from the store; still-pending edges remain
        for the next call. ``known_entity_ids`` should already be casefolded
        the same way entity ids are canonicalized elsewhere in the ontology
        pipeline (see ``ontology_sync._canonical_id``).
        """
        if self._durable_store is not None:
            resolved: list[dict[str, Any]] = []
            still_pending: list[dict[str, Any]] = []
            for edge in self._durable_store.list_pending_relationships():
                missing = _missing_ids(edge, known_entity_ids)
                if missing:
                    if sorted(missing) != edge["missing_endpoint_ids"]:
                        edge = self._durable_store.transition_pending_relationship(
                            edge["pending_id"],
                            expected_revision=edge["revision"],
                            terminal_state="pending",
                            missing_endpoint_ids=sorted(missing),
                        )
                    still_pending.append(edge)
                else:
                    edge = self._durable_store.transition_pending_relationship(
                        edge["pending_id"],
                        expected_revision=edge["revision"],
                        terminal_state="resolved",
                        missing_endpoint_ids=[],
                    )
                    resolved.append(edge)
            return resolved, still_pending
        resolved: list[dict[str, Any]] = []
        still_pending: list[dict[str, Any]] = []
        for edge in self._pending.values():
            if _missing_ids(edge, known_entity_ids):
                still_pending.append(edge)
            else:
                resolved.append(edge)
        self._pending = {
            str(edge.get("resource_id") or "").casefold(): edge for edge in still_pending
        }
        return resolved, still_pending

    def to_list(self) -> list[dict[str, Any]]:
        """Returns pending edges as a plain list a caller can serialize (e.g. to JSON)."""
        if self._durable_store is not None:
            return self._durable_store.list_pending_relationships()
        return list(self._pending.values())

    @classmethod
    def from_list(
        cls,
        edges: list[dict[str, Any]],
        *,
        max_pending: int = DEFAULT_MAX_PENDING,
        durable_store: OntologyRunStore | None = None,
    ) -> PendingRelationshipStore:
        """Rehydrates a store previously flattened with :meth:`to_list`."""
        store = cls(max_pending=max_pending, durable_store=durable_store)
        store.defer(list(edges))
        return store
