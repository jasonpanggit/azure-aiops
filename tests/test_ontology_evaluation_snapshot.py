"""Durable evaluation evidence contracts for ontology release decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ontology_discovery.evaluation import (
    ArtifactReference,
    EvaluationLineage,
    EvaluationSnapshot,
    EvaluationStatus,
    EvaluationThreshold,
    SliceMetric,
    SourceExpiry,
)
from ontology_discovery.evaluation_store import (
    EvaluationSnapshotStore,
    SnapshotConflictError,
)
from storage.onelake_documents import OneLakeDocumentStore

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _snapshot(
    *,
    evaluated_at: datetime = NOW,
    expires_at: datetime | None = None,
    precision: float = 0.99,
    release_eligible: bool = True,
    critical_failures: tuple[str, ...] = (),
) -> EvaluationSnapshot:
    return EvaluationSnapshot.create(
        scope_key="scope-0123456789abcdef",
        observed_at=evaluated_at - timedelta(minutes=5),
        evaluated_at=evaluated_at,
        expires_at=expires_at or evaluated_at + timedelta(hours=24),
        lineage=EvaluationLineage(
            dataset_version="wave0-v1",
            dataset_hash="1" * 64,
            prompt_version="curator-v3",
            prompt_hash="2" * 64,
            schema_version="proposal-v2",
            schema_hash="3" * 64,
            model_version="gpt-5.4-mini-2026-03-17",
            model_hash="4" * 64,
            agent_version="ontology-curator-v5",
            agent_hash="5" * 64,
            policy_version="ontology-policy-v7",
            policy_hash="6" * 64,
        ),
        source_expiries=(
            SourceExpiry(
                source="azure-resource-graph",
                observed_at=evaluated_at - timedelta(minutes=5),
                expires_at=evaluated_at + timedelta(hours=2),
            ),
            SourceExpiry(
                source="fabric-gold",
                observed_at=evaluated_at - timedelta(minutes=2),
                expires_at=evaluated_at + timedelta(hours=24),
            ),
        ),
        slice_metrics=(
            SliceMetric(
                metric="precision",
                slice_key="overall",
                numerator=round(precision * 100),
                denominator=100,
                value=precision,
                critical=True,
            ),
            SliceMetric(
                metric="recall",
                slice_key="predicate:depends_on",
                numerator=91,
                denominator=100,
                value=0.91,
                critical=True,
            ),
        ),
        thresholds=(
            EvaluationThreshold(
                metric="precision",
                slice_key="overall",
                minimum=0.98,
                critical=True,
            ),
            EvaluationThreshold(
                metric="recall",
                slice_key="predicate:depends_on",
                minimum=0.85,
                critical=True,
            ),
        ),
        critical_failures=critical_failures,
        release_eligible=release_eligible,
        artifact_references=(
            ArtifactReference(
                kind="dataset",
                reference="artifact:wave0-reference-v1",
                sha256="7" * 64,
            ),
            ArtifactReference(
                kind="report",
                reference="artifact:evaluation-report-v1",
                sha256="8" * 64,
            ),
        ),
    )


def test_contract_is_strict_frozen_bounded_and_content_addressed():
    snapshot = _snapshot()
    same = EvaluationSnapshot.model_validate_json(snapshot.model_dump_json())

    assert snapshot.contract_version == "1.0.0"
    assert snapshot.snapshot_id.startswith("EVS-")
    assert snapshot.scope_hash == "0123456789abcdef"
    assert snapshot == same
    assert snapshot.snapshot_id == same.snapshot_id
    assert snapshot.effective_expires_at == NOW + timedelta(hours=2)

    with pytest.raises(ValidationError):
        snapshot.release_eligible = False
    with pytest.raises(ValidationError):
        EvaluationSnapshot.create(
            **{
                **snapshot.creation_values(),
                "scope_key": "/subscriptions/raw-tenant-id",
            }
        )
    with pytest.raises(ValidationError):
        ArtifactReference(
            kind="report",
            reference="https://storage.example/raw/prompt.json",
            sha256="8" * 64,
        )
    with pytest.raises(ValidationError):
        EvaluationSnapshot.model_validate(
            {**snapshot.model_dump(), "snapshot_id": "EVS-" + "0" * 64}
        )


def test_write_persists_immutable_snapshot_before_advancing_latest(tmp_path):
    store = EvaluationSnapshotStore(tmp_path)
    snapshot = _snapshot()

    stored = store.write(snapshot, expected_revision=0)
    pointer = store.pointer(snapshot.scope_hash)

    assert stored == snapshot
    assert pointer is not None
    assert pointer.revision == 1
    assert pointer.snapshot_id == snapshot.snapshot_id
    assert store.read_snapshot(snapshot.scope_hash, snapshot.snapshot_id) == snapshot

    snapshot_path = (
        tmp_path
        / "ontology_evaluations"
        / "snapshots"
        / snapshot.scope_hash
        / f"{snapshot.snapshot_id}.json"
    )
    before = snapshot_path.read_bytes()
    assert store.write(snapshot, expected_revision=1) == snapshot
    assert snapshot_path.read_bytes() == before


def test_cas_conflict_preserves_current_pointer_and_both_immutable_records(tmp_path):
    first_store = EvaluationSnapshotStore(tmp_path)
    stale_store = EvaluationSnapshotStore(tmp_path)
    first = _snapshot()
    second = _snapshot(
        evaluated_at=NOW + timedelta(minutes=1),
        precision=0.97,
        release_eligible=False,
        critical_failures=("precision_below_threshold",),
    )

    first_store.write(first, expected_revision=0)
    with pytest.raises(SnapshotConflictError):
        stale_store.write(second, expected_revision=0)

    pointer = first_store.pointer(first.scope_hash)
    assert pointer.snapshot_id == first.snapshot_id
    assert pointer.revision == 1
    assert first_store.read_snapshot(first.scope_hash, first.snapshot_id) == first
    assert first_store.read_snapshot(second.scope_hash, second.snapshot_id) == second


def test_write_failure_cannot_advance_latest_or_make_evidence_eligible(tmp_path):
    class FailingSnapshotDocuments(OneLakeDocumentStore):
        def write(self, name, payload, *, expected_revision):
            if "/snapshots/" in name:
                raise OSError("simulated durable write failure")
            return super().write(name, payload, expected_revision=expected_revision)

    documents = FailingSnapshotDocuments(tmp_path)
    store = EvaluationSnapshotStore(document_store=documents)
    snapshot = _snapshot()

    with pytest.raises(OSError, match="durable write failure"):
        store.write(snapshot, expected_revision=0)

    assert store.pointer(snapshot.scope_hash) is None
    assert store.release_evidence(snapshot.scope_hash, now=NOW) is None


def test_restart_reconstructs_fresh_latest_and_bounded_immutable_history(tmp_path):
    first_store = EvaluationSnapshotStore(tmp_path)
    first = _snapshot()
    second = _snapshot(evaluated_at=NOW + timedelta(minutes=1))
    first_store.write(first, expected_revision=0)
    first_store.write(second, expected_revision=1)

    restarted = EvaluationSnapshotStore(tmp_path)
    latest = restarted.latest(first.scope_hash, now=NOW + timedelta(minutes=2))
    history = restarted.history(first.scope_hash, limit=1)

    assert latest.status is EvaluationStatus.FRESH
    assert latest.snapshot == second
    assert latest.pointer_revision == 2
    assert history == [second]
    assert restarted.history(first.scope_hash, limit=10) == [second, first]
    assert restarted.release_evidence(
        first.scope_hash,
        now=NOW + timedelta(minutes=2),
    ) == second


def test_stale_boundary_remains_auditable_but_fails_release_closed(tmp_path):
    store = EvaluationSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.write(snapshot, expected_revision=0)

    before_boundary = store.latest(
        snapshot.scope_hash,
        now=NOW + timedelta(hours=2) - timedelta(microseconds=1),
    )
    at_boundary = store.latest(
        snapshot.scope_hash,
        now=NOW + timedelta(hours=2),
    )

    assert before_boundary.status is EvaluationStatus.FRESH
    assert at_boundary.status is EvaluationStatus.STALE
    assert at_boundary.snapshot == snapshot
    assert at_boundary.reason == "evaluation_snapshot_expired"
    assert store.history(snapshot.scope_hash) == [snapshot]
    assert (
        store.release_evidence(
            snapshot.scope_hash,
            now=NOW + timedelta(hours=2),
        )
        is None
    )


def test_missing_and_invalid_latest_are_distinct_and_never_release(tmp_path):
    store = EvaluationSnapshotStore(tmp_path)
    scope_hash = "0123456789abcdef"

    missing = store.latest(scope_hash, now=NOW)
    assert missing.status is EvaluationStatus.MISSING
    assert missing.reason == "evaluation_pointer_missing"

    pointer_path = (
        tmp_path / "ontology_evaluations" / "latest" / f"{scope_hash}.json"
    )
    pointer_path.parent.mkdir(parents=True)
    pointer_path.write_text("{not-json", encoding="utf-8")

    invalid = EvaluationSnapshotStore(tmp_path).latest(scope_hash, now=NOW)
    assert invalid.status is EvaluationStatus.INVALID
    assert invalid.snapshot is None
    assert invalid.reason == "evaluation_pointer_invalid"
    assert store.release_evidence(scope_hash, now=NOW) is None


def test_corrupt_pointer_does_not_discard_prior_valid_history(tmp_path):
    store = EvaluationSnapshotStore(tmp_path)
    first = _snapshot()
    second = _snapshot(evaluated_at=NOW + timedelta(minutes=1))
    store.write(first, expected_revision=0)
    store.write(second, expected_revision=1)
    pointer_path = (
        tmp_path
        / "ontology_evaluations"
        / "latest"
        / f"{first.scope_hash}.json"
    )
    pointer_path.write_text('{"revision": 2, "snapshot_id": "EVS-MISSING"}\n')

    restarted = EvaluationSnapshotStore(tmp_path)
    latest = restarted.latest(first.scope_hash, now=NOW + timedelta(minutes=2))

    assert latest.status is EvaluationStatus.INVALID
    assert latest.reason == "evaluation_pointer_invalid"
    assert restarted.history(first.scope_hash) == [second, first]
    assert restarted.release_evidence(
        first.scope_hash,
        now=NOW + timedelta(minutes=2),
    ) is None


def test_valid_pointer_to_missing_snapshot_is_invalid_and_fail_closed(tmp_path):
    store = EvaluationSnapshotStore(tmp_path)
    snapshot = _snapshot()
    store.write(snapshot, expected_revision=0)
    pointer_path = (
        tmp_path
        / "ontology_evaluations"
        / "latest"
        / f"{snapshot.scope_hash}.json"
    )
    payload = store.pointer(snapshot.scope_hash).model_dump(mode="json")
    payload["snapshot_id"] = "EVS-" + "F" * 64
    import json

    pointer_path.write_text(json.dumps(payload), encoding="utf-8")

    latest = EvaluationSnapshotStore(tmp_path).latest(snapshot.scope_hash, now=NOW)
    assert latest.status is EvaluationStatus.INVALID
    assert latest.reason == "evaluation_snapshot_missing"
    assert store.history(snapshot.scope_hash) == [snapshot]
    assert store.release_evidence(snapshot.scope_hash, now=NOW) is None


def test_legacy_incomplete_pointer_and_snapshot_default_to_invalid(tmp_path):
    scope_hash = "0123456789abcdef"
    snapshot_id = "EVS-" + "A" * 64
    pointer_path = (
        tmp_path / "ontology_evaluations" / "latest" / f"{scope_hash}.json"
    )
    snapshot_path = (
        tmp_path
        / "ontology_evaluations"
        / "snapshots"
        / scope_hash
        / f"{snapshot_id}.json"
    )
    pointer_path.parent.mkdir(parents=True)
    snapshot_path.parent.mkdir(parents=True)
    pointer_path.write_text(
        f'{{"revision": 1, "snapshot_id": "{snapshot_id}"}}',
        encoding="utf-8",
    )
    snapshot_path.write_text(
        '{"revision": 1, "snapshot": {"schema_version": "legacy"}}',
        encoding="utf-8",
    )

    store = EvaluationSnapshotStore(tmp_path)
    latest = store.latest(scope_hash, now=NOW)

    assert latest.status is EvaluationStatus.INVALID
    assert latest.reason == "evaluation_pointer_invalid"
    assert latest.snapshot is None
    assert store.release_evidence(scope_hash, now=NOW) is None
