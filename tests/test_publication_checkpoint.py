from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fabric.publication_checkpoint import (
    PreparedPublicationCheckpoint,
    PublicationCheckpointError,
    PublicationCheckpointStore,
)
from storage.delta_writer import (
    DeltaVersionConflictError,
    DeltaWriteMode,
    DeltaWriter,
    DeltaWriteResult,
)
from storage.onelake_documents import OneLakeDocumentStore

_SOURCE_DIGEST = "a" * 64
_FINAL_OUTCOME = {
    "run_id": "publication-run-1",
    "source_run_id": "source-generation-1",
    "status": "completed",
    "replay": False,
    "rows_processed": 2,
    "rows_added": 2,
    "rows_changed": 0,
    "rows_removed": 0,
    "failed_records": 0,
    "tables": ["bronze_resources"],
    "duration_seconds": 12.5,
}


def _persist(
    root: Path,
    *,
    source_run_id: str = "source-generation-1",
) -> tuple[PublicationCheckpointStore, PreparedPublicationCheckpoint]:
    store = PublicationCheckpointStore(OneLakeDocumentStore(root))
    checkpoint = store.persist(
        source_run_id=source_run_id,
        source_manifest_digest=_SOURCE_DIGEST,
        run_id="publication-run-1",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-09-12T00:00:00Z",
        source_watermark="2026-09-11T00:00:00Z",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=2,
        ontology_relationship_count=1,
        datasets={
            "bronze_resources": [
                {"resource_id": "resource-1", "value": 1},
                {"resource_id": "resource-2", "value": 2},
            ],
            "ontology_entities": [{"resource_id": "entity-1"}],
        },
        exposure_gold_observation_rows=[
            {"resource_id": "observation-1"},
            {"resource_id": "observation-2"},
        ],
    )
    return store, checkpoint


def test_prepared_checkpoint_roundtrips_streamed_rows_with_integrity(
    tmp_path: Path,
) -> None:
    store, checkpoint = _persist(tmp_path)

    loaded = store.load(
        "source-generation-1",
        source_manifest_digest=_SOURCE_DIGEST,
    )

    assert loaded == checkpoint
    assert loaded is not None
    assert loaded.checkpoint_id != loaded.source_run_id
    assert len(loaded.checkpoint_id) == 64
    assert len(loaded.datasets["bronze_resources"]) == 2
    assert len(loaded.exposure_gold_observation_rows or []) == 2
    paths = [path.as_posix() for path in tmp_path.rglob("*") if path.is_file()]
    assert any(name.endswith("/manifest.json") for name in paths)
    assert any("/artifacts/" in name for name in paths)


def test_checkpoint_isolated_by_exact_source_and_source_manifest(
    tmp_path: Path,
) -> None:
    store, _checkpoint = _persist(tmp_path)

    assert (
        store.load(
            "source-generation-2",
            source_manifest_digest=_SOURCE_DIGEST,
        )
        is None
    )
    with pytest.raises(
        PublicationCheckpointError,
        match="source manifest does not match",
    ):
        store.load(
            "source-generation-1",
            source_manifest_digest="b" * 64,
        )


@pytest.mark.parametrize("target", ["artifact", "manifest"])
def test_checkpoint_tampering_fails_closed(
    tmp_path: Path,
    target: str,
) -> None:
    store, _checkpoint = _persist(tmp_path)
    paths = [path for path in tmp_path.rglob("*") if path.is_file()]
    path = next(
        candidate
        for candidate in paths
        if (
            "/artifacts/" in candidate.as_posix()
            if target == "artifact"
            else candidate.name == "manifest.json"
        )
    )
    if target == "artifact":
        path.write_text('{"resource_id":"tampered"}\n', encoding="utf-8")
    else:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["run_id"] = "tampered"
        path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PublicationCheckpointError, match="integrity"):
        store.load(
            "source-generation-1",
            source_manifest_digest=_SOURCE_DIGEST,
        )


def test_missing_checkpoint_artifact_fails_closed(tmp_path: Path) -> None:
    store, _checkpoint = _persist(tmp_path)
    artifact = next(
        path
        for path in tmp_path.rglob("*")
        if path.is_file() and "/artifacts/" in path.as_posix()
    )
    artifact.unlink()

    with pytest.raises(PublicationCheckpointError, match="missing or unreadable"):
        store.load(
            "source-generation-1",
            source_manifest_digest=_SOURCE_DIGEST,
        )


def test_incompatible_checkpoint_contract_fails_closed(tmp_path: Path) -> None:
    store, _checkpoint = _persist(tmp_path)
    manifest_path = next(tmp_path.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract_version"] = "fabric-prepared-publication/0.9.0"
    content = dict(manifest)
    content.pop("manifest_digest")
    manifest["manifest_digest"] = hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PublicationCheckpointError, match="incompatible"):
        store.load(
            "source-generation-1",
            source_manifest_digest=_SOURCE_DIGEST,
        )


def test_finalized_checkpoint_is_never_loaded_for_resume(
    tmp_path: Path,
) -> None:
    store, checkpoint = _persist(tmp_path)
    plan = store.prepare_table_plan(
        checkpoint,
        table_names=("bronze_resources",),
        expected_before_versions={"bronze_resources": None},
    )
    intent = store.begin_table_write(
        checkpoint,
        plan,
        table_name="bronze_resources",
        outcome_digest="b" * 64,
    )
    store.record_table_result(
        checkpoint,
        plan,
        table_name="bronze_resources",
        expected_before_version=None,
        result=DeltaWriteResult(rows_processed=2, version=0),
        intent=intent,
    )
    store.finalize(checkpoint, plan, outcome=_FINAL_OUTCOME)

    assert (
        store.load(
            "source-generation-1",
            source_manifest_digest=_SOURCE_DIGEST,
        )
        is None
    )
    assert store.finalized_outcome(
        "source-generation-1",
        source_manifest_digest=_SOURCE_DIGEST,
    ) == _FINAL_OUTCOME


def test_delta_write_rejects_stale_publication_version(tmp_path: Path) -> None:
    writer = DeltaWriter()
    table = tmp_path / "table"
    first = writer.write(
        table,
        [{"resource_id": "resource-1", "change_version": "1"}],
        mode=DeltaWriteMode.OVERWRITE,
        required_columns=None,
    )
    assert first.version == 0
    second = writer.write(
        table,
        [{"resource_id": "resource-1", "change_version": "2"}],
        mode=DeltaWriteMode.OVERWRITE,
        required_columns=None,
        expected_version=first.version,
    )
    assert second.version == 1

    with pytest.raises(
        DeltaVersionConflictError,
        match="changed after publication planning",
    ):
        writer.write(
            table,
            [{"resource_id": "resource-1", "change_version": "3"}],
            mode=DeltaWriteMode.OVERWRITE,
            required_columns=None,
            expected_version=first.version,
        )
