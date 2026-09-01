from __future__ import annotations

from ontology.pending_relationships import PendingRelationshipStore


def _edge(relationship_id: str, subject_id: str, object_id: str) -> dict:
    return {
        "resource_id": relationship_id,
        "subject_id": subject_id,
        "object_id": object_id,
        "predicate": "depends_on",
    }


def test_defer_then_resolve_returns_edge_once_target_is_known():
    store = PendingRelationshipStore()
    store.defer([_edge("edge-1", "a", "b")])

    resolved, pending = store.resolve({"a"})
    assert resolved == []
    assert len(pending) == 1

    resolved, pending = store.resolve({"a", "b"})
    assert len(resolved) == 1
    assert resolved[0]["resource_id"] == "edge-1"
    assert pending == []
    assert len(store) == 0


def test_edge_stays_pending_indefinitely_without_crashing_or_growing_unbounded():
    store = PendingRelationshipStore(max_pending=5)
    store.defer([_edge("edge-1", "a", "b")])

    for _ in range(50):
        resolved, pending = store.resolve(set())
        assert resolved == []
        assert len(pending) == 1
        store.defer(pending)

    assert len(store) <= 5


def test_deferred_edges_beyond_cap_are_evicted_not_accumulated_forever():
    store = PendingRelationshipStore(max_pending=3)
    store.defer([_edge(f"edge-{i}", f"s{i}", f"o{i}") for i in range(10)])

    assert len(store) == 3


def test_resolve_with_no_pending_edges_returns_empty_lists():
    store = PendingRelationshipStore()
    resolved, pending = store.resolve({"anything"})
    assert resolved == []
    assert pending == []


def test_to_list_and_from_list_round_trip_pending_edges():
    store = PendingRelationshipStore()
    store.defer([_edge("edge-1", "a", "b")])

    serialized = store.to_list()
    rehydrated = PendingRelationshipStore.from_list(serialized)

    resolved, pending = rehydrated.resolve({"a", "b"})
    assert len(resolved) == 1
    assert resolved[0]["resource_id"] == "edge-1"
