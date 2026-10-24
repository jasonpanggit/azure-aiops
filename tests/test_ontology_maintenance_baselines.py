"""Restart, replay, parity and atomicity tests for committed graph baselines."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from ontology_discovery.incremental import (
    apply_incremental_graph,
    classify_incremental,
    compare_graph_parity,
    graph_row_hashes,
    normalize_graph_state,
)
from ontology_discovery.store import OntologyRunStore, RunClaimConflict

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SCOPE = "tenant-1/sub-1"
LINEAGE = "inventory+appdependencies:v1"


def _graph(
    *,
    entities: tuple[str, ...] = ("a", "b"),
    relationships: tuple[tuple[str, str], ...] = (("a", "b"),),
    pending: tuple[str, ...] = (),
) -> dict[str, list[dict[str, str]]]:
    return normalize_graph_state(
        entities=[{"resource_id": value, "name": value} for value in entities],
        relationships=[
            {
                "resource_id": f"rel:{subject}:{target}",
                "subject_id": subject,
                "predicate": "depends_on",
                "object_id": target,
            }
            for subject, target in relationships
        ],
        pending_relationships=[
            {"pending_id": value, "resource_id": value} for value in pending
        ],
    )


@pytest.mark.parametrize("protection", ["stale_ids", "unresolved_ids"])
@pytest.mark.parametrize("coverage", ["complete", "partial"])
@pytest.mark.parametrize("observation", ["missing", "changed", "new"])
def test_protected_rows_preserve_graph_and_hash_baseline(
    protection, coverage, observation,
) -> None:
    previous = _graph(entities=("a", "b"), relationships=())
    current = _graph(
        entities=("a",) if observation == "missing" else ("a", "b", "c"),
        relationships=(),
    )
    key = "entities/c" if observation == "new" else "entities/b"
    for row in current["entities"]:
        if row["resource_id"] == "b":
            row["name"] = "untrusted-change"
    delta = classify_incremental(
        previous_row_hashes=graph_row_hashes(previous),
        current_row_hashes=graph_row_hashes(current),
        source_generation_id="generation-2",
        observed_at=NOW,
        freshness="current",
        coverage=coverage,
        **{protection: (key,)},
    )
    assert key not in delta.retired
    replay = apply_incremental_graph(
        previous_graph=previous, current_graph=current, delta=delta,
    )
    assert delta.apply_to(graph_row_hashes(previous)) == graph_row_hashes(replay)
    prior = next((row for row in previous["entities"] if "entities/" + row["resource_id"] == key), None)
    actual = next((row for row in replay["entities"] if "entities/" + row["resource_id"] == key), None)
    assert actual == prior

    recovered = classify_incremental(
        previous_row_hashes=graph_row_hashes(replay),
        current_row_hashes=graph_row_hashes(current),
        source_generation_id="generation-3",
        observed_at=NOW,
        freshness="current",
        coverage="complete",
    )
    trusted = apply_incremental_graph(
        previous_graph=replay, current_graph=current, delta=recovered,
    )
    assert trusted == current
    assert recovered.apply_to(graph_row_hashes(replay)) == graph_row_hashes(current)


def test_protected_baseline_survives_restart_until_trusted_retirement(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = OntologyRunStore(path)
    original = _graph()
    store.select_reconciliation_mode(
        connection_id="connection-1", now=NOW, baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    _commit(
        store, predecessor="", watermark="generation-1", full_graph=original,
    )
    missing = _graph(entities=("a",), relationships=())
    protected = ("entities/b", "relationships/rel:a:b")
    delta = classify_incremental(
        previous_row_hashes=graph_row_hashes(original),
        current_row_hashes=graph_row_hashes(missing),
        source_generation_id="generation-2", observed_at=NOW,
        freshness="current", coverage="complete", stale_ids=protected,
    )
    replay = apply_incremental_graph(
        previous_graph=original, current_graph=missing, delta=delta,
    )
    assert replay == original
    assert delta.apply_to(graph_row_hashes(original)) == graph_row_hashes(original)
    _commit(
        store, predecessor="generation-1", watermark="generation-2",
        full_graph=replay, incremental_graph=replay, baseline_graph=replay,
        expected_baseline_revision=1, dispatch_id="dispatch-2",
    )
    restarted = OntologyRunStore(path)
    baseline = restarted.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE,
    )
    assert baseline["graph"] == original
    assert baseline["row_hashes"] == graph_row_hashes(original)
    trusted = classify_incremental(
        previous_row_hashes=baseline["row_hashes"],
        current_row_hashes=graph_row_hashes(missing),
        source_generation_id="generation-3", observed_at=NOW,
        freshness="current", coverage="complete",
    )
    assert set(trusted.retired) == set(protected)
    assert apply_incremental_graph(
        previous_graph=baseline["graph"], current_graph=missing, delta=trusted,
    ) == missing


def _commit(
    store: OntologyRunStore,
    *,
    predecessor: str,
    watermark: str,
    full_graph: dict,
    incremental_graph: dict | None = None,
    baseline_graph: dict | None = None,
    expected_baseline_revision: int | None = None,
    baseline_coverage: str = "complete",
    dispatch_id: str = "dispatch-1",
) -> dict:
    full = copy.deepcopy(full_graph)
    replayed = copy.deepcopy(incremental_graph or full_graph)
    baseline_state = copy.deepcopy(baseline_graph or full_graph)
    return store.commit_reconciliation(
        connection_id="connection-1",
        predecessor_watermark=predecessor,
        committed_watermark=watermark,
        full_graph=full,
        incremental_graph=replayed,
        dispatch_id=dispatch_id,
        baseline={
            "scope": SCOPE,
            "lineage_key": LINEAGE,
            "schema_version": "ontology-graph-v1",
            "coverage": baseline_coverage,
            "row_hashes": graph_row_hashes(baseline_state),
            "graph": baseline_state,
            "source_fingerprint": f"manifest-{watermark}",
        },
        baseline_expected_revision=expected_baseline_revision,
        now=NOW,
    )


def test_committed_baseline_survives_restart_and_replays_real_delta(tmp_path) -> None:
    path = tmp_path / "state.json"
    store = OntologyRunStore(path)
    first = _graph()
    selected = store.select_reconciliation_mode(
        connection_id="connection-1",
        now=NOW,
        baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    assert (selected["selected_mode"], selected["selection_reason"]) == (
        "full",
        "first_run",
    )
    committed = _commit(
        store,
        predecessor="",
        watermark="generation-1",
        full_graph=first,
        expected_baseline_revision=None,
    )
    assert committed["result"]["drift_status"] == "in_sync"

    restarted = OntologyRunStore(path)
    baseline = restarted.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )
    assert baseline["revision"] == 1
    assert baseline["graph"] == first
    selected = restarted.select_reconciliation_mode(
        connection_id="connection-1",
        now=NOW,
        baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    assert (selected["selected_mode"], selected["selection_reason"]) == (
        "incremental",
        "watermark_current",
    )

    current = _graph(
        entities=("a", "b", "c"),
        relationships=(("a", "c"),),
        pending=("waiting",),
    )
    next(
        row for row in current["entities"] if row["resource_id"] == "b"
    )["name"] = "b-revised"
    previous_hashes = baseline["row_hashes"]
    current_hashes = graph_row_hashes(current)
    delta = classify_incremental(
        previous_row_hashes=previous_hashes,
        current_row_hashes=current_hashes,
        source_generation_id="generation-2",
        observed_at=NOW,
        freshness="current",
        coverage="complete",
    )
    assert set(delta.added) == {"entities/c", "pending/waiting", "relationships/rel:a:c"}
    assert delta.changed == ("entities/b",)
    assert set(delta.retired) == {"relationships/rel:a:b"}
    replay = apply_incremental_graph(
        previous_graph=baseline["graph"], current_graph=current, delta=delta
    )
    assert replay == current
    assert compare_graph_parity(current, replay)["status"] == "in_sync"
    _commit(
        restarted,
        predecessor="generation-1",
        watermark="generation-2",
        full_graph=current,
        incremental_graph=replay,
        expected_baseline_revision=baseline["revision"],
        dispatch_id="dispatch-2",
    )
    final_store = OntologyRunStore(path)
    final_baseline = final_store.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )
    assert final_baseline["revision"] == 2
    assert final_baseline["graph"] == current
    assert final_store.get_reconciliation_control("connection-1")[
        "committed_watermark"
    ] == "generation-2"


def test_partial_coverage_and_dispatch_failure_cannot_advance_baseline(tmp_path) -> None:
    store = OntologyRunStore(tmp_path / "state.json")
    original = _graph()
    store.select_reconciliation_mode(
        connection_id="connection-1", now=NOW, baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    _commit(
        store,
        predecessor="",
        watermark="generation-1",
        full_graph=original,
        expected_baseline_revision=None,
    )
    previous = store.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )
    partial = _graph(entities=("a",), relationships=())
    delta = classify_incremental(
        previous_row_hashes=previous["row_hashes"],
        current_row_hashes=graph_row_hashes(partial),
        source_generation_id="generation-2",
        observed_at=NOW,
        freshness="unknown",
        coverage="partial",
        stale_ids=("entities/a",),
    )
    assert "entities/b" in delta.unresolved
    assert delta.stale == ("entities/a",)
    replay = apply_incremental_graph(
        previous_graph=previous["graph"], current_graph=partial, delta=delta
    )
    assert delta.retired == ()
    assert replay == original

    with pytest.raises(ValueError, match="dispatch"):
        _commit(
            store,
            predecessor="generation-1",
            watermark="generation-2",
            full_graph=partial,
            incremental_graph=replay,
            baseline_graph=replay,
            expected_baseline_revision=previous["revision"],
            dispatch_id="",
        )
    assert store.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    ) == previous
    assert store.get_reconciliation_control("connection-1")[
        "committed_watermark"
    ] == "generation-1"
    _commit(
        store,
        predecessor="generation-1",
        watermark="generation-2",
        full_graph=replay,
        baseline_graph=replay,
        expected_baseline_revision=previous["revision"],
        baseline_coverage="partial",
        dispatch_id="dispatch-2",
    )
    partial_baseline = store.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )
    assert partial_baseline["coverage"] == "partial"
    next_mode = store.select_reconciliation_mode(
        connection_id="connection-1",
        now=NOW,
        baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    assert next_mode["selected_mode"] == "full"
    assert next_mode["selection_reason"] == "baseline_incompatible_or_incomplete"


def test_baseline_commit_is_atomic_idempotent_and_cas_protected(tmp_path) -> None:
    path = tmp_path / "state.json"
    first_store = OntologyRunStore(path)
    graph = _graph()
    first_store.select_reconciliation_mode(
        connection_id="connection-1", now=NOW, baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    committed = _commit(
        first_store,
        predecessor="",
        watermark="generation-1",
        full_graph=graph,
        expected_baseline_revision=None,
    )
    replayed = _commit(
        OntologyRunStore(path),
        predecessor="",
        watermark="generation-1",
        full_graph=graph,
        expected_baseline_revision=None,
    )
    assert replayed == committed

    competing = OntologyRunStore(path)
    competing.select_reconciliation_mode(
        connection_id="connection-1", now=NOW, baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    with pytest.raises(RunClaimConflict, match="watermark_conflict"):
        _commit(
            competing,
            predecessor="",
            watermark="generation-2",
            full_graph=_graph(entities=("changed",)),
            expected_baseline_revision=1,
            dispatch_id="dispatch-2",
        )
    baseline = OntologyRunStore(path).get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )
    assert baseline["revision"] == 1
    assert baseline["graph"] == graph


def test_corrupt_replay_records_drift_with_full_graph_as_repair_authority(tmp_path) -> None:
    store = OntologyRunStore(tmp_path / "state.json")
    expected = _graph()
    store.select_reconciliation_mode(
        connection_id="connection-1", now=NOW, baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    outcome = _commit(
        store,
        predecessor="",
        watermark="generation-1",
        full_graph=expected,
        incremental_graph=_graph(entities=("wrong",)),
        baseline_graph=_graph(entities=("wrong",)),
        expected_baseline_revision=None,
    )
    assert outcome["result"]["drift_status"] == "drift_detected"
    assert outcome["result"]["repair_authority"] == "full"
    assert outcome["result"]["drift_hash"]
    assert outcome["control"]["force_full"] is True
    assert outcome["control"]["force_full_reason"] == "drift_detected"
    assert store.get_committed_baseline(
        connection_id="connection-1", scope=SCOPE, lineage_key=LINEAGE
    )["graph"] == expected


def test_legacy_watermark_without_a_baseline_forces_explicit_full_reconcile(
    tmp_path,
) -> None:
    store = OntologyRunStore(tmp_path / "state.json")
    store.select_reconciliation_mode(connection_id="connection-1", now=NOW)
    graph = _graph()
    store.commit_reconciliation(
        connection_id="connection-1",
        predecessor_watermark="",
        committed_watermark="legacy-generation",
        full_graph=graph,
        incremental_graph=graph,
        dispatch_id="legacy-dispatch",
        now=NOW,
    )

    selected = OntologyRunStore(tmp_path / "state.json").select_reconciliation_mode(
        connection_id="connection-1",
        now=NOW,
        baseline_scope=SCOPE,
        baseline_lineage_key=LINEAGE,
    )
    assert selected["selected_mode"] == "full"
    assert selected["selection_reason"] == "baseline_missing"
