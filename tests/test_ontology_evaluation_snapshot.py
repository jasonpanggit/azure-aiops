"""Durable evaluation evidence contracts for ontology release decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ontology_discovery.evaluation import (
    ArtifactReference,
    EvaluationLineage,
    EvaluationSnapshot,
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
