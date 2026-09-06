from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology.pending_relationships import PendingRelationshipStore
from ontology_discovery.store import (
    OntologyRunStore,
    PendingRelationshipConflict,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


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

    resolved, _pending = rehydrated.resolve({"a", "b"})
    assert len(resolved) == 1
    assert resolved[0]["resource_id"] == "edge-1"


def _durable_edge() -> dict:
    return {
        **_edge("edge-durable", "a", "b"),
        "scope": "tenant-a/sub-a",
        "source_generation_id": "generation-7",
        "missing_endpoint_ids": ["b"],
        "observations": [
            {
                "evidence_id": "evidence-1",
                "observed_at": NOW.isoformat(),
            }
        ],
        "attempts": 2,
        "freshness": "fresh",
        "terminal_state": "pending",
    }


def test_durable_pending_edge_retains_replay_state_across_restart(tmp_path):
    path = tmp_path / "ontology-runs.json"
    store = OntologyRunStore(path)
    pending = PendingRelationshipStore(durable_store=store)

    pending.defer([_durable_edge()])
    first = pending.to_list()[0]
    assert first["pending_id"].startswith("OPR-")
    assert first["missing_endpoint_ids"] == ["b"]
    assert first["observations"][0]["evidence_id"] == "evidence-1"
    assert first["attempts"] == 2
    assert first["freshness"] == "fresh"
    assert first["scope"] == "tenant-a/sub-a"
    assert first["source_generation_id"] == "generation-7"
    assert first["terminal_state"] == "pending"

    restarted = PendingRelationshipStore(durable_store=OntologyRunStore(path))
    assert restarted.to_list() == [first]
    restarted.defer([_durable_edge()])
    assert len(
        OntologyRunStore(path).list_pending_relationships(include_terminal=True)
    ) == 1

    resolved, still_pending = restarted.resolve({"a", "b"})
    assert [row["resource_id"] for row in resolved] == ["edge-durable"]
    assert still_pending == []
    terminal = OntologyRunStore(path).list_pending_relationships(
        include_terminal=True
    )
    assert len(terminal) == 1
    assert terminal[0]["pending_id"] == first["pending_id"]
    assert terminal[0]["terminal_state"] == "resolved"
    assert terminal[0]["revision"] > first["revision"]


def test_pending_transition_uses_record_revision_cas(tmp_path):
    store = OntologyRunStore(tmp_path / "ontology-runs.json")
    record = store.defer_pending_relationship(_durable_edge(), now=NOW)

    with pytest.raises(PendingRelationshipConflict):
        store.transition_pending_relationship(
            record["pending_id"],
            expected_revision=record["revision"] + 1,
            terminal_state="resolved",
            now=NOW,
        )

    unchanged = store.list_pending_relationships(include_terminal=True)[0]
    assert unchanged["revision"] == record["revision"]
    assert unchanged["terminal_state"] == "pending"
