from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import pytest
from test_container_image_exposure import REGISTRY, _granular_image_row
from test_incremental_sync import FIXTURE, _source_snapshot

import fabric.sync_service as sync_module
from fabric.config import FabricRuntimeConfig
from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import GranularExposureOntologyMapper
from fabric.publication_checkpoint import (
    CompletedTableWrite,
    PublicationCheckpointError,
    PublicationResumePlan,
)
from fabric.schema_registry import schema_for
from fabric.sync_service import (
    DedicatedOntologyPublisherAdapter,
    FabricSyncService,
    FabricTableWriteProgress,
    _commit_patch_publication,
    _exposure_gold_generation_id,
    _merge_granular_ontology_entities,
    _merge_granular_ontology_relationships,
    _observation_rows_at_or_before,
    _partition_patch_publication_items,
    _prepare_publish_items,
    _should_publish_table,
    _state_row,
    _validate_checkpoint_table_versions,
)
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_GENERATIONS_TABLE,
    EXPOSURE_GOLD_POINTER_DOCUMENT,
    EXPOSURE_GOLD_TABLES,
    EXPOSURE_OBSERVATIONS_TABLE,
    TemporalExposureMaterialization,
)
from onboarding.activation import ActivationProgressReporter
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from ontology.entity_builder import entity_change_version
from ontology.ontology_sync import OntologyGraphResult
from ontology.relationship_builder import relationship_change_version
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.delta_writer import (
    DeltaHistoryTruncatedError,
    DeltaWriteMode,
    DeltaWriter,
    DeltaWriteResult,
)
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter


def _service(tmp_path: Path) -> FabricSyncService:
    source = tmp_path / "source"
    _source_snapshot(source)
    return FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )


def _container_source_snapshot(
    root: Path,
    *,
    observed_at: datetime,
    run_id: str,
    severity: str = "Critical",
    provider_event_time: bool = True,
) -> None:
    payload = json.loads(FIXTURE.read_text())
    payload["resources"].append(
        {
            "id": REGISTRY,
            "name": "acr1",
            "type": "Microsoft.ContainerRegistry/registries",
            "location": "australiaeast",
            "subscriptionId": "sub1",
            "resourceGroup": "rg1",
            "tenantId": "tenant1",
        }
    )
    image_assessment = _granular_image_row(
        "openssl",
        [severity],
        ["CVE-2026-1001"],
    )
    if not provider_event_time:
        image_assessment["properties"].pop("timeGenerated", None)
    image_assessment["tenantId"] = "tenant1"
    payload["defender_assessments"].append(image_assessment)
    graph = Normalizer({"connection_id": "connection-1"}).normalize(
        payload,
        observed_at,
        run_id=run_id,
    )
    DatasetStore(root).publish(
        graph,
        payload,
        {
            "runId": run_id,
            "startedAt": observed_at.isoformat().replace("+00:00", "Z"),
            "status": "completed",
        },
    )


def test_explicit_replay_returns_matching_finalized_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    first = service.sync()
    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "finalized source snapshot was projected again"
        ),
    )

    second = service.sync(replay_source_run_id=first.source_run_id)

    assert second.run_id == first.run_id
    assert second.source_run_id == first.source_run_id
    assert second.tables == first.tables
    assert second.replay is True


def test_sync_deduplicates_unchanged_and_appends_changed_container_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _container_source_snapshot(
        source,
        observed_at=datetime(2026, 9, 2, tzinfo=UTC),
        run_id="source-generation-1",
        provider_event_time=False,
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace",
            "lakehouse",
            local_root=lakehouse,
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    monkeypatch.setattr(service, "_validate", lambda _datasets: [])
    write_mode_for_table = service._write_mode_for_table
    monkeypatch.setattr(
        service,
        "_write_mode_for_table",
        lambda table_name: (
            DeltaWriteMode.OVERWRITE
            if table_name == "metadata_audit_events"
            else write_mode_for_table(table_name)
        ),
    )

    first = service.sync()
    _container_source_snapshot(
        source,
        observed_at=datetime(2026, 9, 3, tzinfo=UTC),
        run_id="source-generation-2",
        provider_event_time=False,
    )
    second = service.sync()

    observations = service.delta.read(
        lakehouse / "Tables/silver_container_vulnerability_observations"
    )
    assert first.status == "completed"
    assert second.status == "completed"
    assert len(observations) == 1
    original_observation_id = observations[0]["resource_id"]

    _container_source_snapshot(
        source,
        observed_at=datetime(2026, 9, 4, tzinfo=UTC),
        run_id="source-generation-3",
        severity="Low",
        provider_event_time=False,
    )
    third = service.sync()
    observations = service.delta.read(
        lakehouse / "Tables/silver_container_vulnerability_observations"
    )

    assert third.status == "completed"
    assert len(observations) == 2
    assert {row["severity"] for row in observations} == {"Critical", "Low"}
    assert len({row["resource_id"] for row in observations}) == 2
    assert original_observation_id in {
        row["resource_id"] for row in observations
    }


def test_sync_reports_successful_table_writes_in_completion_order(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[FabricTableWriteProgress] = []
    caplog.set_level(logging.INFO, logger=sync_module.__name__)

    service = _service(tmp_path)
    result = service.sync(progress_callback=events.append)
    started = [
        record
        for record in caplog.records
        if record.message == "fabric_table_write_started"
    ]

    assert result.status == "completed"
    assert events
    assert [event.completed_tables for event in events] == list(
        range(1, len(events) + 1)
    )
    assert all(event.total_tables == len(events) for event in events)
    assert {event.table_name for event in events} == set(result.tables)
    assert all(event.result is not None for event in events)
    assert {record.table_name for record in started} == {
        event.table_name for event in events
    }
    assert all(
        isinstance(record.row_count, int)
        and not isinstance(record.row_count, bool)
        and 0 <= record.row_count <= 2_147_483_647
        for record in started
    )
    assert not (
        tmp_path / "lakehouse" / "Tables" / "bronze_container_image_exposure"
    ).exists()


def test_sync_releases_transient_memory_before_table_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequence: list[str] = []
    monkeypatch.setattr(
        sync_module,
        "_release_transient_publication_memory",
        lambda: sequence.append("release"),
    )

    result = _service(tmp_path).sync(
        progress_callback=lambda _event: sequence.append("table"),
    )

    assert result.status == "completed"
    assert sequence[0] == "release"
    assert "table" in sequence


def test_patch_publication_items_precede_manifest_barrier_and_remaining_tables() -> (
    None
):
    patch_items, barrier_item, remaining = _partition_patch_publication_items(
        [
            ("ontology_entities", []),
            ("metadata_patch_snapshot", [{"resource_id": "manifest"}]),
            ("silver_patch_snapshot_findings", [{"resource_id": "finding"}]),
            ("bronze_patchassessment", [{"resource_id": "assessment"}]),
            ("silver_exposure_observations", [{"resource_id": "observation"}]),
        ],
        patch_tables=(
            "bronze_patchassessment",
            "silver_patch_snapshot_findings",
        ),
        barrier_table="metadata_patch_snapshot",
    )

    assert [name for name, _rows in patch_items] == [
        "bronze_patchassessment",
        "silver_patch_snapshot_findings",
    ]
    assert barrier_item is not None
    assert barrier_item[0] == "metadata_patch_snapshot"
    assert [name for name, _rows in remaining] == [
        "ontology_entities",
        "silver_exposure_observations",
    ]


def test_full_sync_publishes_empty_patch_tables_when_manifest_exists() -> None:
    assert _should_publish_table(
        "silver_patch_snapshot_findings",
        [],
        patch_barrier_present=True,
        patch_tables=("silver_patch_snapshot_findings",),
        barrier_table="metadata_patch_snapshot",
    )
    assert not _should_publish_table(
        "silver_patch_snapshot_findings",
        [],
        patch_barrier_present=False,
        patch_tables=("silver_patch_snapshot_findings",),
        barrier_table="metadata_patch_snapshot",
    )


def test_forced_empty_patch_table_captures_prior_version_for_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    snapshot_uri = service.onelake.table_uri(
        "silver",
        "patch_snapshot_findings",
    )
    monkeypatch.setattr(
        service.delta,
        "version",
        lambda table_uri: 7 if str(table_uri) == str(snapshot_uri) else None,
    )

    items, known_versions = _prepare_publish_items(
        {
            "silver_patch_snapshot_findings": [],
            "metadata_patch_snapshot": [{"resource_id": "manifest"}],
        },
        onelake=service.onelake,
        delta=service.delta,
        patch_barrier_present=True,
        patch_tables=("silver_patch_snapshot_findings",),
        barrier_table="metadata_patch_snapshot",
    )

    assert [name for name, _rows in items] == [
        "silver_patch_snapshot_findings",
        "metadata_patch_snapshot",
    ]
    assert known_versions == {"silver_patch_snapshot_findings": 7}


def test_full_sync_without_patch_barrier_preserves_existing_patch_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    existing_versions = {
        str(service.onelake.table_uri("silver", "patch_snapshot_findings")): 7,
        str(service.onelake.table_uri("metadata", "patch_snapshot")): 8,
    }
    monkeypatch.setattr(
        service.delta,
        "version",
        lambda table_uri: existing_versions.get(str(table_uri)),
    )

    items, known_versions = _prepare_publish_items(
        {
            "silver_patch_snapshot_findings": [],
            "metadata_patch_snapshot": [],
            "silver_exposure_observations": [{"resource_id": "observation"}],
        },
        onelake=service.onelake,
        delta=service.delta,
        patch_barrier_present=False,
        patch_tables=("silver_patch_snapshot_findings",),
        barrier_table="metadata_patch_snapshot",
    )

    assert items == [("silver_exposure_observations", [{"resource_id": "observation"}])]
    assert known_versions == {}


def test_patch_manifest_barrier_commits_bronze_and_silver_independently() -> None:
    written_versions = {
        "bronze_patchassessment": ("bronze-uri", 1),
        "silver_patch_snapshot_findings": ("snapshot-uri", 2),
        "metadata_patch_snapshot": ("manifest-uri", 3),
        "ontology_entities": ("ontology-uri", 4),
    }

    _commit_patch_publication(
        written_versions,
        patch_tables=(
            "bronze_patchassessment",
            "silver_patch_snapshot_findings",
        ),
        barrier_table="metadata_patch_snapshot",
    )

    assert written_versions == {
        "ontology_entities": ("ontology-uri", 4),
    }


def test_patch_only_sync_writes_patch_tables_and_manifest_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    manifest_row = _patch_barrier_row("source-run-1")
    mapped = {table_name: [] for table_name in service._PATCH_PUBLICATION_TABLES}
    mapped[service._PATCH_PUBLICATION_BARRIER] = [manifest_row]
    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: mapped,
    )
    writes: list[tuple[str, DeltaWriteMode]] = []

    def write(table_uri, _rows, *, mode, **_kwargs):
        writes.append((str(table_uri), DeltaWriteMode(mode)))
        return DeltaWriteResult(rows_processed=0, version=len(writes))

    monkeypatch.setattr(service.delta, "write", write)
    events: list[FabricTableWriteProgress] = []

    result = service.sync_patch_tables(progress_callback=events.append)

    expected_names = [
        *service._PATCH_PUBLICATION_TABLES,
        service._PATCH_PUBLICATION_BARRIER,
    ]
    assert result.status == "completed"
    assert set(result.tables) == set(expected_names)
    assert [event.table_name for event in events] == expected_names
    assert [event.completed_tables for event in events] == list(
        range(1, len(expected_names) + 1)
    )
    assert all(event.total_tables == len(expected_names) for event in events)
    assert writes[-1][0].endswith("/Tables/metadata_patch_snapshot")
    assert (
        dict(writes)[
            next(
                uri
                for uri, _mode in writes
                if uri.endswith("/Tables/silver_patch_snapshot_findings")
            )
        ]
        is DeltaWriteMode.APPEND
    )


def test_patch_only_sync_publishes_due_generation_then_noops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    mapped = {table_name: [] for table_name in service._PATCH_PUBLICATION_TABLES}
    mapped[service._PATCH_PUBLICATION_BARRIER] = [
        _patch_barrier_row("source-run-1")
    ]
    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: mapped,
    )

    published = service.sync_patch_tables()
    skipped = service.sync_patch_tables()

    barrier_rows = service.delta.read(
        service.onelake.table_uri("metadata", "patch_snapshot")
    )
    assert published.status == "completed"
    assert published.source_run_id == "source-run-1"
    assert skipped.status == "skipped"
    assert skipped.source_run_id == "source-run-1"
    assert skipped.tables == ()
    assert {row["combined_source_generation"] for row in barrier_rows} == {
        "source-run-1"
    }
    assert {row["completeness"] for row in barrier_rows} == {"complete"}


def test_patch_only_sync_lock_conflict_fails_closed(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with (
        service.onelake.sync_lock(),
        pytest.raises(RuntimeError, match="already running"),
    ):
        service.sync_patch_tables()


def test_incomplete_patch_generation_preserves_prior_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    barrier_uri = service.onelake.table_uri("metadata", "patch_snapshot")
    prior = _patch_barrier_row("source-run-0")
    service.delta.write(
        barrier_uri,
        [prior],
        mode=DeltaWriteMode.OVERWRITE,
        key_columns=("resource_id",),
        schema=schema_for("metadata_patch_snapshot"),
    )
    mapped = {table_name: [] for table_name in service._PATCH_PUBLICATION_TABLES}
    mapped[service._PATCH_PUBLICATION_BARRIER] = [
        {
            **_patch_barrier_row("source-run-1"),
            "status": "partial",
            "completeness": "partial",
        }
    ]
    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: mapped,
    )

    with pytest.raises(ValueError, match="complete AUM source barrier"):
        service.sync_patch_tables()

    assert service.delta.read(barrier_uri) == [prior]


def test_patch_only_registration_failure_rolls_back_mutable_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    mapped = {table_name: [] for table_name in service._PATCH_PUBLICATION_TABLES}
    mapped[service._PATCH_PUBLICATION_BARRIER] = [
        _patch_barrier_row("source-run-1")
    ]
    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: mapped,
    )
    monkeypatch.setattr(service.delta, "version", lambda _uri: 1)
    version = 1

    def write(_table_uri, _rows, **_kwargs):
        nonlocal version
        version += 1
        return DeltaWriteResult(rows_processed=0, version=version)

    restored: list[str] = []
    monkeypatch.setattr(service.delta, "write", write)
    monkeypatch.setattr(
        service.delta,
        "restore",
        lambda table_uri, _version: restored.append(str(table_uri)),
    )
    monkeypatch.setattr(
        service,
        "_register_fabric_assets",
        lambda _tables: (_ for _ in ()).throw(RuntimeError("registration failed")),
    )

    with pytest.raises(RuntimeError, match="registration failed"):
        service.sync_patch_tables()

    assert all(
        not uri.endswith("/Tables/silver_patch_snapshot_findings") for uri in restored
    )
    assert any(uri.endswith("/Tables/metadata_patch_snapshot") for uri in restored)
    assert any(uri.endswith("/Tables/bronze_patchassessment") for uri in restored)


def _patch_barrier_row(source_generation: str) -> dict[str, Any]:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "patch-snapshot://sub-1",
        "timestamp": "2026-09-14T00:00:00Z",
        "change_version": "patch-change-1",
        "ingestion_run_id": "patch-publication-1",
        "connection_id": "connection-1",
        "combined_source_generation": source_generation,
        "source_generation": "aum-generation-1",
        "replaces_legacy_connection_id": "",
        "status": "succeeded",
        "completeness": "complete",
        "freshness": "fresh",
        "freshness_at": "2026-09-14T00:00:00Z",
        "freshness_threshold_seconds": 3600,
        "represented_count": 1,
        "expected_count": 1,
    }


def test_failed_patch_manifest_restore_preserves_snapshot_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    restored: list[str] = []

    def restore(table_uri: str, _version: int) -> None:
        restored.append(table_uri)
        if table_uri == "manifest-uri":
            raise RuntimeError("manifest restore failed")

    monkeypatch.setattr(service.delta, "restore", restore)
    service.rollback_sleep = lambda _seconds: None

    errors = service._rollback(
        {
            "silver_patch_snapshot_findings": ("snapshot-uri", 1),
            "metadata_patch_snapshot": ("manifest-uri", 2),
        }
    )

    assert restored == ["manifest-uri", "manifest-uri", "manifest-uri"]
    assert errors == ["metadata_patch_snapshot: manifest restore failed"]


def test_successful_rollback_also_preserves_immutable_snapshot_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    restored: list[str] = []
    monkeypatch.setattr(
        service.delta,
        "restore",
        lambda table_uri, _version: restored.append(table_uri),
    )

    errors = service._rollback(
        {
            "silver_patch_snapshot_findings": ("snapshot-uri", 1),
            "metadata_patch_snapshot": ("manifest-uri", 2),
        }
    )

    assert errors == []
    assert restored == ["manifest-uri"]


def test_partial_rollback_clears_only_restored_checkpoint_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    checkpoint = service.publication_checkpoints.persist(
        source_run_id="source-run-1",
        source_manifest_digest="a" * 64,
        run_id="publication-run-1",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-09-13T00:00:00Z",
        source_watermark="",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=1,
        ontology_relationship_count=1,
        datasets={
            "bronze_resources": [{"resource_id": "resource-1"}],
            "ontology_entities": [{"resource_id": "entity-1"}],
        },
        exposure_gold_observation_rows=None,
    )
    expected_versions = {
        "bronze_resources": 0,
        "ontology_entities": 0,
    }
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=expected_versions,
        expected_before_versions=expected_versions,
    )
    for table_name in expected_versions:
        intent = service.publication_checkpoints.begin_table_write(
            checkpoint,
            plan,
            table_name=table_name,
            outcome_digest=("b" if table_name == "bronze_resources" else "c") * 64,
        )
        service.publication_checkpoints.record_table_result(
            checkpoint,
            plan,
            table_name=table_name,
            expected_before_version=0,
            result=DeltaWriteResult(rows_processed=1, version=1),
            intent=intent,
        )

    def restore(table_uri: str, _version: int) -> None:
        if table_uri == "failed-uri":
            raise RuntimeError("restore unavailable")

    monkeypatch.setattr(service.delta, "restore", restore)
    service.rollback_sleep = lambda _seconds: None

    errors = service._rollback_publication(
        {
            "bronze_resources": ("restored-uri", 0),
            "ontology_entities": ("failed-uri", 0),
        },
        checkpoint=checkpoint,
        plan=plan,
    )
    resumed = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=expected_versions,
        expected_before_versions=expected_versions,
    )

    assert errors == ["ontology_entities: restore unavailable"]
    assert set(resumed.completed) == {"ontology_entities"}
    assert resumed.completed["ontology_entities"].resulting_version == 1
    assert "bronze_resources" not in resumed.completed


def test_reconciliation_reports_truncated_delta_history_actionably(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    checkpoint = service.publication_checkpoints.persist(
        source_run_id="source-run-1",
        source_manifest_digest="a" * 64,
        run_id="publication-run-1",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-09-13T00:00:00Z",
        source_watermark="",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=1,
        ontology_relationship_count=0,
        datasets={"bronze_resources": [{"resource_id": "resource-1"}]},
        exposure_gold_observation_rows=None,
    )
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=("bronze_resources",),
        expected_before_versions={"bronze_resources": 7},
    )
    service.publication_checkpoints.begin_table_write(
        checkpoint,
        plan,
        table_name="bronze_resources",
        outcome_digest="b" * 64,
    )
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=("bronze_resources",),
        expected_before_versions={"bronze_resources": 7},
    )
    monkeypatch.setattr(
        service.delta,
        "committed_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DeltaHistoryTruncatedError("history is truncated")
        ),
    )
    monkeypatch.setattr(service.delta, "version", lambda _uri: 8)

    with pytest.raises(
        PublicationCheckpointError,
        match="history is truncated.*explicitly abandon",
    ):
        service._reconcile_publication_intents(
            checkpoint,
            plan,
            table_uris={"bronze_resources": "table-uri"},
        )


def test_reconciliation_clears_uncommitted_intent_before_history_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    checkpoint = service.publication_checkpoints.persist(
        source_run_id="source-run-1",
        source_manifest_digest="a" * 64,
        run_id="publication-run-1",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-09-13T00:00:00Z",
        source_watermark="",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=1,
        ontology_relationship_count=0,
        datasets={"bronze_resources": [{"resource_id": "resource-1"}]},
        exposure_gold_observation_rows=None,
    )
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=("bronze_resources",),
        expected_before_versions={"bronze_resources": 7},
    )
    service.publication_checkpoints.begin_table_write(
        checkpoint,
        plan,
        table_name="bronze_resources",
        outcome_digest="b" * 64,
    )
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=("bronze_resources",),
        expected_before_versions={"bronze_resources": 7},
    )
    monkeypatch.setattr(service.delta, "version", lambda _uri: 7)
    monkeypatch.setattr(
        service.delta,
        "committed_transaction",
        lambda *_args, **_kwargs: pytest.fail(
            "unchanged table head must not scan transaction history"
        ),
    )

    reconciled = service._reconcile_publication_intents(
        checkpoint,
        plan,
        table_uris={"bronze_resources": "table-uri"},
    )

    assert reconciled.in_flight == {}
    assert reconciled.completed == {}


def test_reconciliation_batches_untouched_intent_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    checkpoint = service.publication_checkpoints.persist(
        source_run_id="source-run-1",
        source_manifest_digest="a" * 64,
        run_id="publication-run-1",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-09-13T00:00:00Z",
        source_watermark="",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=2,
        ontology_relationship_count=0,
        datasets={
            "bronze_resources": [{"resource_id": "resource-1"}],
            "silver_vm_inventory": [{"resource_id": "resource-1"}],
        },
        exposure_gold_observation_rows=None,
    )
    versions = {"bronze_resources": 7, "silver_vm_inventory": 9}
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=versions,
        expected_before_versions=versions,
    )
    service.publication_checkpoints.begin_table_writes(
        checkpoint,
        plan,
        outcome_digests={name: "b" * 64 for name in versions},
    )
    plan = service.publication_checkpoints.prepare_table_plan(
        checkpoint,
        table_names=versions,
        expected_before_versions=versions,
    )
    monkeypatch.setattr(
        service.delta,
        "version",
        lambda uri: versions[str(uri)],
    )
    monkeypatch.setattr(
        service.delta,
        "committed_transaction",
        lambda *_args, **_kwargs: pytest.fail(
            "unchanged table heads must not scan transaction history"
        ),
    )
    calls = 0
    original_clear = service.publication_checkpoints.clear_table_intents

    def record_clear(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_clear(*args, **kwargs)

    monkeypatch.setattr(
        service.publication_checkpoints,
        "clear_table_intents",
        record_clear,
    )

    reconciled = service._reconcile_publication_intents(
        checkpoint,
        plan,
        table_uris={name: name for name in versions},
    )

    assert calls == 1
    assert reconciled.in_flight == {}


def test_exposure_gold_input_view_retains_only_projection_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_keys: set[str] = set()

    def capture_generation(
        _source_run_id: str,
        datasets: Mapping[str, list[dict[str, Any]]],
    ) -> str:
        captured_keys.update(datasets)
        raise RuntimeError("stop after Gold input construction")

    monkeypatch.setattr(
        sync_module,
        "_exposure_gold_generation_id",
        capture_generation,
    )

    with pytest.raises(
        RuntimeError,
        match="stop after Gold input construction",
    ):
        _service(tmp_path).sync(
            exposure_pointer_store=OneLakeDocumentStore(str(tmp_path / "pointer"))
        )

    assert captured_keys == set(sync_module._EXPOSURE_GOLD_INPUT_TABLES)
    assert "ontology_entities" not in captured_keys
    assert "ontology_relationships" not in captured_keys


def test_deployed_publication_orders_observations_after_workload_checkpoint(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    snapshot = Path(service._resolve_snapshot(""))
    product_dir = snapshot / "exposure"
    product_dir.mkdir(parents=True, exist_ok=True)
    (product_dir / "workload_source_checkpoints.jsonl").write_text(
        json.dumps({"checkpoint_key": "checkpoint-1"}) + "\n"
    )
    datasets = {"prior_table": [{"resource_id": "prior"}]}
    datasets.update(service._load_workload_products(snapshot))
    datasets.update(
        TemporalExposureMaterialization(
            observation_rows=({"resource_id": "observation-1"},),
            current_rows=(),
            all_observation_rows=({"resource_id": "observation-1"},),
        ).write_tables()
    )
    table_names = list(datasets)
    checkpoint_index = table_names.index("metadata_workload_source_checkpoints")

    assert FabricRuntimeConfig.load("fabric.config.deploy.yaml").write_workers == 1
    assert table_names[checkpoint_index + 1] == EXPOSURE_OBSERVATIONS_TABLE


def test_sync_ignores_progress_callback_errors(tmp_path: Path) -> None:
    calls = 0

    def broken_callback(_event: FabricTableWriteProgress) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("progress sink unavailable")

    result = _service(tmp_path).sync(progress_callback=broken_callback)

    assert result.status == "completed"
    assert calls == len(result.tables)


def test_sync_emits_exact_fabric_stage_contract_and_shared_table_total(
    tmp_path: Path,
) -> None:
    stage_events: list[dict[str, object]] = []
    table_events: list[FabricTableWriteProgress] = []

    result = _service(tmp_path).sync(
        progress_callback=table_events.append,
        stage_progress_callback=stage_events.append,
        exposure_pointer_store=OneLakeDocumentStore(tmp_path / "registry"),
    )

    assert result.status == "completed"
    lifecycle_stages = [
        event["stage"] for event in stage_events if event["status"] == "started"
    ]
    assert lifecycle_stages == [
        "dataset_mapping",
        "workload_projection",
        "temporal_retained_load",
        "temporal_projection",
        "temporal_legacy_normalization",
        "temporal_observation_combination",
        "temporal_current_projection",
        "temporal_immutable_checks",
        "container_projection",
        "ontology_construction",
        "ontology_validation",
        "checkpoint_persistence",
        "table_publication",
        "fabric_asset_registration",
        "ontology_publication",
        "gold_staging",
        "fabric_asset_registration",
        "shortcut_finalization",
        "checkpoint_activation_pending",
        "pointer_activation",
        "checkpoint_finalization",
    ]
    completion_fields = {
        "dataset_mapping": {"dataset_count", "failure_count"},
        "workload_projection": {
            "entity_count",
            "relationship_count",
            "failure_count",
        },
        "temporal_projection": {
            "entity_count",
            "relationship_count",
            "failure_count",
        },
        "temporal_retained_load": {"row_count", "failure_count"},
        "temporal_legacy_normalization": {"row_count", "failure_count"},
        "temporal_observation_combination": {"row_count", "failure_count"},
        "temporal_current_projection": {"row_count", "failure_count"},
        "temporal_immutable_checks": {"row_count", "failure_count"},
        "container_projection": {
            "entity_count",
            "relationship_count",
            "failure_count",
        },
        "ontology_construction": {
            "entity_count",
            "relationship_count",
            "failure_count",
        },
        "ontology_validation": {
            "entity_count",
            "relationship_count",
            "failure_count",
        },
        "table_publication": set(),
        "fabric_asset_registration": set(),
        "ontology_publication": set(),
        "gold_staging": set(),
        "shortcut_finalization": set(),
        "pointer_activation": set(),
        "checkpoint_persistence": {
            "dataset_count",
            "failure_count",
            "checkpoint_rows_written",
            "checkpoint_bytes_written",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        },
        "checkpoint_restore": {
            "dataset_count",
            "failure_count",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        },
        "publication_resume": {
            "completed",
            "total",
            "remaining_tables",
            "resumed_tables",
            "skipped_tables",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        },
        "checkpoint_finalization": {
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        },
        "checkpoint_activation_pending": {
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        },
    }
    count_fields = {
        "dataset_count",
        "entity_count",
        "relationship_count",
        "failure_count",
        "row_count",
        "completed",
        "total",
        "remaining_tables",
        "resumed_tables",
        "skipped_tables",
        "checkpoint_rows_written",
        "checkpoint_bytes_written",
    }
    for event in stage_events:
        assert set(event) >= {"stage", "status"}
        expected_fields = {"stage", "status"}
        if event["status"] == "completed":
            expected_fields |= completion_fields[event["stage"]]
        assert set(event) == expected_fields
        if event["status"] == "completed":
            for field in completion_fields[event["stage"]] & count_fields:
                assert isinstance(event[field], int)
                assert not isinstance(event[field], bool)
                assert 0 <= event[field] <= 2_147_483_647
    assert table_events
    assert [event.completed_tables for event in table_events] == list(
        range(1, len(table_events) + 1)
    )
    assert all(event.total_tables == len(table_events) for event in table_events)
    assert all(event.result.rows_processed >= 0 for event in table_events)
    assert all(event.remaining_tables >= 0 for event in table_events)
    assert all(event.resumed_tables == 0 for event in table_events)
    assert all(event.skipped_tables == 0 for event in table_events)
    assert all(len(event.checkpoint_id) == 64 for event in table_events)
    assert all(event.checkpoint_state == "persisted" for event in table_events)


@pytest.mark.parametrize(
    ("callback_name", "message", "error_code"),
    [
        (
            "progress_callback",
            "fabric_table_progress_callback_failed",
            "FABRIC_TABLE_PROGRESS_CALLBACK_FAILED",
        ),
        (
            "stage_progress_callback",
            "fabric_stage_progress_callback_failed",
            "FABRIC_STAGE_PROGRESS_CALLBACK_FAILED",
        ),
    ],
)
def test_sync_callback_failures_log_only_fixed_safe_contract(
    tmp_path: Path,
    caplog,
    callback_name: str,
    message: str,
    error_code: str,
) -> None:
    secret = "credential=planted-secret"
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/x/y"

    def broken_callback(_event) -> None:
        raise RuntimeError(f"{secret} {resource_id}")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(error_code)s"))
    logger = logging.getLogger("fabric.sync_service")
    logger.addHandler(handler)
    caplog.set_level(logging.WARNING, logger="fabric.sync_service")
    try:
        result = _service(tmp_path).sync(**{callback_name: broken_callback})
    finally:
        logger.removeHandler(handler)

    assert result.status == "completed"
    records = [
        record for record in caplog.records if record.name == "fabric.sync_service"
    ]
    assert records
    assert {record.getMessage() for record in records} == {message}
    assert {record.error_code for record in records} == {error_code}
    assert all(record.exc_info is None for record in records)
    rendered = caplog.text + stream.getvalue()
    assert secret not in rendered
    assert resource_id not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered


def test_fabric_stage_order_keeps_pointer_activation_last(tmp_path: Path) -> None:
    events: list[dict[str, object]] = []
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    service.sync(
        stage_progress_callback=events.append,
        exposure_pointer_store=pointer_store,
    )

    completed = [event["stage"] for event in events if event["status"] == "completed"]
    assert completed.index("ontology_publication") < completed.index("gold_staging")
    assert completed.index("gold_staging") < completed.index("shortcut_finalization")
    assert completed.index("shortcut_finalization") < completed.index(
        "pointer_activation"
    )
    assert completed.index("pointer_activation") < completed.index(
        "checkpoint_finalization"
    )
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)


def test_exact_historical_replay_runs_full_finalization_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    first_payload = json.loads(FIXTURE.read_text())
    first_payload["resources"][0]["name"] = "historical-resource"
    first_graph = Normalizer().normalize(
        first_payload,
        datetime(2026, 9, 8, tzinfo=UTC),
    )
    DatasetStore(source).publish(
        first_graph,
        first_payload,
        {
            "runId": "historical-generation",
            "startedAt": "2026-09-08T00:00:00Z",
            "status": "completed",
        },
    )
    current_payload = json.loads(FIXTURE.read_text())
    current_payload["resources"][0]["name"] = "current-resource"
    current_graph = Normalizer().normalize(
        current_payload,
        datetime(2026, 9, 9, tzinfo=UTC),
    )
    DatasetStore(source).publish(
        current_graph,
        current_payload,
        {
            "runId": "current-generation",
            "startedAt": "2026-09-09T00:00:00Z",
            "status": "completed",
        },
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace",
            "lakehouse",
            local_root=tmp_path / "lakehouse",
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    events: list[dict[str, object]] = []
    shortcuts: list[str] = []
    original_shortcuts = service._create_shortcuts

    def record_shortcuts() -> None:
        shortcuts.append("finalized")
        original_shortcuts()

    monkeypatch.setattr(service, "_create_shortcuts", record_shortcuts)

    result = service.sync(
        replay_source_run_id="historical-generation",
        exposure_pointer_store=pointer_store,
        stage_progress_callback=events.append,
    )

    resources = service.delta.read(service.onelake.table_uri("bronze", "resources"))
    names = {str(row.get("name") or "") for row in resources}
    assert "historical-resource" in names
    assert "current-resource" not in names
    assert result.status == "completed"
    assert result.replay is True
    assert result.source_run_id == "historical-generation"
    assert {
        "bronze_resources",
        "ontology_entities",
        "ontology_relationships",
        *EXPOSURE_GOLD_TABLES,
        EXPOSURE_GOLD_GENERATIONS_TABLE,
    } <= set(result.tables)
    assert shortcuts == ["finalized"]
    completed = [event["stage"] for event in events if event["status"] == "completed"]
    assert completed.index("shortcut_finalization") < completed.index(
        "pointer_activation"
    )
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    marker = max(
        (row for row in service.status() if row.get("status") == "completed"),
        key=lambda row: str(row.get("timestamp") or ""),
    )
    assert marker["source_run_id"] == "historical-generation"
    assert marker["replay"] is True


@pytest.mark.parametrize(
    ("replay_source_run_id", "expected_replay"),
    [("source-run-1", True), ("", False)],
)
def test_rerun_restores_prepared_state_and_skips_completed_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_source_run_id: str,
    expected_replay: bool,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    original_publish = service._publish_ontology
    publish_attempts = 0

    def interrupt_once(datasets):
        nonlocal publish_attempts
        publish_attempts += 1
        if publish_attempts == 1:
            raise RuntimeError("simulated process interruption")
        return original_publish(datasets)

    monkeypatch.setattr(service, "_publish_ontology", interrupt_once)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        service.sync(exposure_pointer_store=pointer_store)

    source_manifest = service._read_manifest(service._resolve_snapshot("source-run-1"))
    checkpoint = service.publication_checkpoints.load(
        "source-run-1",
        source_manifest_digest=sync_module._hash_json(source_manifest),
    )
    assert checkpoint is not None
    progress_paths = list((tmp_path / "lakehouse" / "Files").rglob("progress.json"))
    progress = json.loads(progress_paths[0].read_text(encoding="utf-8"))
    completed_before_resume = set(progress["completed_tables"])
    assert completed_before_resume

    monkeypatch.setattr(
        service.mapper,
        "load",
        lambda *_args, **_kwargs: pytest.fail("dataset mapping was repeated"),
    )
    monkeypatch.setattr(
        service,
        "_load_workload_products",
        lambda *_args, **_kwargs: pytest.fail("workload projection was repeated"),
    )
    monkeypatch.setattr(
        sync_module,
        "materialize_temporal_exposure_tables",
        lambda *_args, **_kwargs: pytest.fail("temporal projection was repeated"),
    )
    monkeypatch.setattr(
        service,
        "_synchronize_ontology",
        lambda *_args, **_kwargs: pytest.fail("ontology construction was repeated"),
    )
    monkeypatch.setattr(
        service,
        "_validate",
        lambda *_args, **_kwargs: pytest.fail("ontology validation was repeated"),
    )
    original_write = service.delta.write

    def reject_completed_rewrite(uri, rows, **kwargs):
        table_name = Path(str(uri)).name
        if table_name in completed_before_resume:
            pytest.fail(f"completed table was rewritten: {table_name}")
        return original_write(uri, rows, **kwargs)

    monkeypatch.setattr(service.delta, "write", reject_completed_rewrite)
    events: list[dict[str, object]] = []
    table_events: list[FabricTableWriteProgress] = []

    result = service.sync(
        replay_source_run_id=replay_source_run_id,
        exposure_pointer_store=pointer_store,
        progress_callback=table_events.append,
        stage_progress_callback=events.append,
    )

    assert result.status == "completed"
    assert result.replay is expected_replay
    assert result.run_id == checkpoint.run_id
    assert any(event["stage"] == "checkpoint_restore" for event in events)
    resume_event = next(
        event
        for event in events
        if event["stage"] == "publication_resume"
        and event["status"] == "completed"
    )
    assert resume_event["checkpoint_id"] == checkpoint.checkpoint_id
    assert resume_event["publication_id"] == checkpoint.checkpoint_id
    assert resume_event["checkpoint_state"] == "restored"
    assert resume_event["resumed_tables"] == len(completed_before_resume)
    assert resume_event["skipped_tables"] == len(completed_before_resume)
    assert resume_event["remaining_tables"] == (
        resume_event["total"] - resume_event["completed"]
    )
    assert table_events[-1].remaining_tables == 0
    assert table_events[-1].completed_tables == table_events[-1].total_tables
    assert table_events[-1].resumed_tables == len(completed_before_resume)
    assert table_events[-1].skipped_tables == len(completed_before_resume)
    assert table_events[-1].checkpoint_id == checkpoint.checkpoint_id
    assert table_events[-1].checkpoint_state == "restored"
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)


def test_normal_nonfinalized_manifest_mismatch_fails_without_deletion(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    snapshot = Path(service._resolve_snapshot(""))
    source_manifest = service._read_manifest(snapshot)
    source_manifest_digest = sync_module._hash_json(source_manifest)
    checkpoint = service.publication_checkpoints.persist(
        source_run_id="source-run-1",
        source_manifest_digest=source_manifest_digest,
        run_id="interrupted-publication",
        started_at="2026-09-13T00:00:00Z",
        source_projected_at="2026-08-17T00:00:00Z",
        source_watermark="2026-08-17T00:00:00Z",
        failed_records=0,
        ontology_health={"status": "healthy"},
        ontology_entity_count=0,
        ontology_relationship_count=0,
        datasets={},
        exposure_gold_observation_rows=None,
    )
    source_manifest["retryNonce"] = "changed-after-checkpoint"
    (snapshot / "manifest.json").write_text(
        json.dumps(source_manifest),
        encoding="utf-8",
    )

    with pytest.raises(
        PublicationCheckpointError,
        match="source manifest does not match",
    ):
        service.sync()

    assert service.publication_checkpoints.load(
        "source-run-1",
        source_manifest_digest=source_manifest_digest,
    ) == checkpoint


def test_fresh_process_exact_replay_survives_prepare_and_high_count_deaths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedProcessDeath(BaseException):
        pass

    class LazyFuture:
        def __init__(self, operation, args) -> None:
            self._operation = operation
            self._args = args

        def result(self):
            return self._operation(*self._args)

    class SerialExecutor:
        def __init__(self, *, max_workers: int) -> None:
            assert max_workers >= 1

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def submit(self, operation, *args):
            return LazyFuture(operation, args)

    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    registry = tmp_path / "registry"
    _source_snapshot(source)

    def fresh_service() -> FabricSyncService:
        return FabricSyncService(
            source_root=source,
            onelake=OneLakeWriter(
                "workspace",
                "lakehouse",
                local_root=lakehouse,
            ),
            delta_writer=DeltaWriter(),
            validator=DataQualityValidator(),
            write_workers=1,
        )

    pointer_store = OneLakeDocumentStore(registry)
    first = fresh_service()
    original_persist = first.publication_checkpoints.persist

    def persist_then_die(**kwargs):
        original_persist(**kwargs)
        raise SimulatedProcessDeath("after durable prepared projection")

    monkeypatch.setattr(
        first.publication_checkpoints,
        "persist",
        persist_then_die,
    )
    with pytest.raises(
        SimulatedProcessDeath,
        match="after durable prepared projection",
    ):
        first.sync(exposure_pointer_store=pointer_store)
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}

    source_manifest = first._read_manifest(
        first._resolve_snapshot("source-run-1")
    )
    source_manifest_digest = sync_module._hash_json(source_manifest)
    prepared = first.publication_checkpoints.load(
        "source-run-1",
        source_manifest_digest=source_manifest_digest,
    )
    assert prepared is not None
    publish_items, _known_versions = _prepare_publish_items(
        prepared.datasets,
        onelake=first.onelake,
        delta=first.delta,
        patch_barrier_present=bool(
            prepared.datasets.get(first._PATCH_PUBLICATION_BARRIER)
        ),
        patch_tables=first._PATCH_PUBLICATION_TABLES,
        barrier_table=first._PATCH_PUBLICATION_BARRIER,
    )
    expected_total = len(publish_items) + len(EXPOSURE_GOLD_TABLES) + 1
    interruption_target = (
        453
        if expected_total > 453
        else max(1, expected_total - 2)
    )

    def forbid_expensive_projection(service: FabricSyncService) -> None:
        monkeypatch.setattr(
            service.mapper,
            "load",
            lambda *_args, **_kwargs: pytest.fail(
                "dataset mapping was repeated"
            ),
        )
        monkeypatch.setattr(
            service,
            "_load_workload_products",
            lambda *_args, **_kwargs: pytest.fail(
                "workload projection was repeated"
            ),
        )
        monkeypatch.setattr(
            service,
            "_synchronize_ontology",
            lambda *_args, **_kwargs: pytest.fail(
                "ontology construction was repeated"
            ),
        )
        monkeypatch.setattr(
            service,
            "_validate",
            lambda *_args, **_kwargs: pytest.fail(
                "ontology validation was repeated"
            ),
        )

    monkeypatch.setattr(
        sync_module,
        "materialize_temporal_exposure_tables",
        lambda *_args, **_kwargs: pytest.fail(
            "temporal projection was repeated"
        ),
    )
    monkeypatch.setattr(
        sync_module,
        "materialize_container_exposure_tables",
        lambda *_args, **_kwargs: pytest.fail(
            "container projection was repeated"
        ),
    )

    second = fresh_service()
    forbid_expensive_projection(second)
    original_record = second.publication_checkpoints.record_table_result
    durable_results = 0
    commit_gap_table = ""

    def record_then_die(*args, **kwargs):
        nonlocal commit_gap_table, durable_results
        durable_results += 1
        if durable_results == interruption_target:
            commit_gap_table = str(kwargs["table_name"])
            raise RuntimeError(
                "after Delta commit before checkpoint completion"
            )
        original_record(*args, **kwargs)

    with monkeypatch.context() as process_death:
        process_death.setattr(
            sync_module,
            "ThreadPoolExecutor",
            SerialExecutor,
        )
        process_death.setattr(
            sync_module,
            "as_completed",
            lambda futures: futures,
        )
        process_death.setattr(
            second.publication_checkpoints,
            "record_table_result",
            record_then_die,
        )
        with pytest.raises(
            RuntimeError,
            match="after Delta commit before checkpoint completion",
        ):
            second.sync(
                replay_source_run_id="source-run-1",
                exposure_pointer_store=pointer_store,
            )
    assert durable_results == interruption_target
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}

    progress_path = next(
        (lakehouse / "Files").rglob("progress.json")
    )
    interrupted_progress = json.loads(
        progress_path.read_text(encoding="utf-8")
    )
    completed_before_final_resume = set(
        interrupted_progress["completed_tables"]
    )
    planned_tables = set(interrupted_progress["table_names"])
    assert len(completed_before_final_resume) == interruption_target - 1
    assert commit_gap_table in interrupted_progress["in_flight"]
    assert set(interrupted_progress["in_flight"]) == {commit_gap_table}

    third = fresh_service()
    forbid_expensive_projection(third)
    original_write = third.delta.write
    final_writes: list[str] = []

    def write_only_remaining(uri, rows, **kwargs):
        table_name = Path(str(uri)).name
        if table_name in {
            *completed_before_final_resume,
            commit_gap_table,
        }:
            pytest.fail(f"validated completed table was rewritten: {table_name}")
        if table_name in planned_tables:
            final_writes.append(table_name)
        return original_write(uri, rows, **kwargs)

    monkeypatch.setattr(third.delta, "write", write_only_remaining)
    structured_events: list[dict[str, object]] = []
    reporter = ActivationProgressReporter(
        structured_events.append,
        heartbeat_interval=3_600,
    )
    original_activate = sync_module.ExposureGoldFabricPublisher.activate

    def die_before_pointer(_publisher, _stage):
        raise SimulatedProcessDeath(
            "after activation-pending before pointer activation"
        )

    try:
        with monkeypatch.context() as activation_death:
            activation_death.setattr(
                sync_module.ExposureGoldFabricPublisher,
                "activate",
                die_before_pointer,
            )
            with pytest.raises(
                SimulatedProcessDeath,
                match="after activation-pending before pointer activation",
            ):
                third.sync(
                    replay_source_run_id="source-run-1",
                    exposure_pointer_store=pointer_store,
                    progress_callback=reporter.fabric_table_progress,
                    stage_progress_callback=reporter.fabric_stage_progress,
                )
    finally:
        reporter.close()

    assert set(final_writes) == (
        planned_tables
        - completed_before_final_resume
        - {commit_gap_table}
    )
    activation_pending = json.loads(progress_path.read_text(encoding="utf-8"))
    assert activation_pending["status"] == "activation_pending"
    assert activation_pending["activation"]["generation_id"]
    assert set(activation_pending["completed_tables"]) == planned_tables
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}

    restore_event = next(
        event
        for event in structured_events
        if event["stage"] == "checkpoint_restore"
        and event["status"] == "completed"
    )
    resume_event = next(
        event
        for event in structured_events
        if event["stage"] == "publication_resume"
        and event["status"] == "completed"
    )
    table_event = next(
        event
        for event in reversed(structured_events)
        if event["stage"] == "table_publication"
    )
    assert restore_event["checkpoint_state"] == "restored"
    assert restore_event["publication_id"] == prepared.checkpoint_id
    assert resume_event["resumed_tables"] == interruption_target
    assert resume_event["skipped_tables"] == interruption_target
    assert resume_event["completed"] == interruption_target
    assert resume_event["total"] == expected_total
    assert resume_event["remaining_tables"] == (
        expected_total - interruption_target
    )
    assert table_event["completed"] == expected_total
    assert table_event["total"] == expected_total
    assert table_event["remaining_tables"] == 0
    assert table_event["resumed_tables"] == interruption_target
    assert table_event["skipped_tables"] == interruption_target
    assert table_event["publication_id"] == prepared.checkpoint_id
    assert table_event["current_phase"] in {
        "table_publication",
        "gold_staging",
    }

    fourth = fresh_service()
    forbid_expensive_projection(fourth)
    fourth_write = fourth.delta.write

    def reject_restage_write(uri, rows, **kwargs):
        if Path(str(uri)).name in planned_tables:
            pytest.fail("activation-pending replay rewrote a staged table")
        return fourth_write(uri, rows, **kwargs)

    monkeypatch.setattr(fourth.delta, "write", reject_restage_write)
    monkeypatch.setattr(
        sync_module.ExposureGoldFabricPublisher,
        "stage",
        lambda *_args, **_kwargs: pytest.fail(
            "activation-pending replay restaged Gold"
        ),
    )
    activation_order: list[str] = []

    def activate_once(publisher, stage):
        activation_order.append("pointer_activation")
        return original_activate(publisher, stage)

    def die_after_pointer(*_args, **_kwargs):
        raise SimulatedProcessDeath(
            "after pointer activation before checkpoint finalization"
        )

    with monkeypatch.context() as pointer_death:
        pointer_death.setattr(
            sync_module.ExposureGoldFabricPublisher,
            "activate",
            activate_once,
        )
        pointer_death.setattr(
            fourth.publication_checkpoints,
            "finalize",
            die_after_pointer,
        )
        with pytest.raises(
            SimulatedProcessDeath,
            match="after pointer activation before checkpoint finalization",
        ):
            fourth.sync(
                replay_source_run_id="source-run-1",
                exposure_pointer_store=pointer_store,
            )

    after_pointer = json.loads(progress_path.read_text(encoding="utf-8"))
    assert after_pointer["status"] == "activation_pending"
    pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    assert pointer["readable_generation_id"] == (
        activation_pending["activation"]["generation_id"]
    )

    fifth = fresh_service()
    forbid_expensive_projection(fifth)
    fifth_write = fifth.delta.write

    def reject_post_pointer_rewrite(uri, rows, **kwargs):
        if Path(str(uri)).name in planned_tables:
            pytest.fail("post-pointer replay rewrote a staged table")
        return fifth_write(uri, rows, **kwargs)

    monkeypatch.setattr(
        fifth.delta,
        "write",
        reject_post_pointer_rewrite,
    )
    monkeypatch.setattr(
        sync_module.ExposureGoldFabricPublisher,
        "stage",
        lambda *_args, **_kwargs: pytest.fail(
            "post-pointer replay restaged Gold"
        ),
    )
    final_events: list[dict[str, object]] = []
    final_reporter = ActivationProgressReporter(
        final_events.append,
        heartbeat_interval=3_600,
    )
    try:
        result = fifth.sync(
            replay_source_run_id="source-run-1",
            exposure_pointer_store=pointer_store,
            progress_callback=final_reporter.fabric_table_progress,
            stage_progress_callback=final_reporter.fabric_stage_progress,
        )
    finally:
        final_reporter.close()

    assert result.status == "completed"
    assert activation_order == ["pointer_activation"]
    finalized_progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert finalized_progress["status"] == "finalized"
    assert set(finalized_progress["completed_tables"]) == planned_tables
    pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    assert pointer["readable_generation_id"] == (
        activation_pending["activation"]["generation_id"]
    )
    completed_stages = [
        event["stage"]
        for event in final_events
        if event["status"] == "completed"
    ]
    assert completed_stages[-2:] == [
        "pointer_activation",
        "checkpoint_finalization",
    ]

    sixth = fresh_service()
    monkeypatch.setattr(
        sixth.mapper,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "finalized replay remapped datasets"
        ),
    )
    repeated = sixth.sync(
        replay_source_run_id="source-run-1",
        exposure_pointer_store=pointer_store,
    )
    assert repeated.status == "completed"
    assert repeated.replay is True
    assert repeated.run_id == result.run_id
    assert repeated.tables == result.tables


def test_453_completed_table_versions_resume_without_rewrite() -> None:
    names = tuple(f"silver_resume_{index:03d}" for index in range(460))
    completed = {
        name: CompletedTableWrite(
            table_name=name,
            expected_before_version=4,
            resulting_version=5,
            result=DeltaWriteResult(rows_processed=1, version=5),
        )
        for name in names[:453]
    }
    plan = PublicationResumePlan(
        plan_hash="plan",
        table_names=names,
        expected_before_versions={name: 4 for name in names},
        completed=completed,
        in_flight={},
        activation_pending=None,
    )
    versions = {name: 5 if name in completed else 4 for name in names}

    resumed = _validate_checkpoint_table_versions(
        plan,
        table_uris={name: name for name in names},
        version_reader=versions.__getitem__,
    )

    assert len(resumed) == 453
    assert resumed == frozenset(names[:453])


def test_completed_table_version_drift_refuses_resume() -> None:
    completed = CompletedTableWrite(
        table_name="silver_exposure",
        expected_before_version=4,
        resulting_version=5,
        result=DeltaWriteResult(rows_processed=1, version=5),
    )
    plan = PublicationResumePlan(
        plan_hash="plan",
        table_names=("silver_exposure",),
        expected_before_versions={"silver_exposure": 4},
        completed={"silver_exposure": completed},
        in_flight={},
        activation_pending=None,
    )

    with pytest.raises(PublicationCheckpointError, match="version drifted"):
        _validate_checkpoint_table_versions(
            plan,
            table_uris={"silver_exposure": "silver_exposure"},
            version_reader=lambda _uri: 6,
        )


def test_partial_patch_checkpoint_restarts_entire_barrier_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    original_load = service.mapper.load

    def load_with_patch_barrier(*args, **kwargs):
        datasets = original_load(*args, **kwargs)
        content = {
            "combined_source_generation": "source-run-1",
            "source_generation": "source-run-1",
            "replaces_legacy_connection_id": "",
            "status": "succeeded",
            "completeness": "healthy-empty",
            "freshness": "fresh",
            "freshness_at": "2026-08-17T00:00:00Z",
            "freshness_threshold_seconds": 3600,
            "represented_count": 0,
            "expected_count": 0,
        }
        datasets[service._PATCH_PUBLICATION_BARRIER] = [
            {
                "tenant_id": "system",
                "subscription_id": "sub-1",
                "resource_id": "patch-snapshot://sub-1",
                "timestamp": "2026-08-17T00:00:00Z",
                "change_version": sync_module._hash_json(content),
                "ingestion_run_id": "publication-run",
                "connection_id": "connection-a",
                **content,
            }
        ]
        return datasets

    monkeypatch.setattr(service.mapper, "load", load_with_patch_barrier)
    original_record = service.publication_checkpoints.record_table_result
    crashed = False

    def interrupt_after_first_patch(*args, table_name, **kwargs):
        nonlocal crashed
        original_record(*args, table_name=table_name, **kwargs)
        if table_name in service._PATCH_PUBLICATION_TABLES and not crashed:
            crashed = True
            raise SystemExit("simulated process death")

    monkeypatch.setattr(
        service.publication_checkpoints,
        "record_table_result",
        interrupt_after_first_patch,
    )
    with pytest.raises(SystemExit, match="simulated process death"):
        service.sync()

    monkeypatch.setattr(
        service.publication_checkpoints,
        "record_table_result",
        original_record,
    )
    writes: list[str] = []
    original_write = service.delta.write

    def record_write(uri, rows, **kwargs):
        writes.append(Path(str(uri)).name)
        return original_write(uri, rows, **kwargs)

    monkeypatch.setattr(service.delta, "write", record_write)
    result = service.sync(replay_source_run_id="source-run-1")

    expected_group = [
        *service._PATCH_PUBLICATION_TABLES,
        service._PATCH_PUBLICATION_BARRIER,
    ]
    published_group = [name for name in writes if name in expected_group]
    assert result.status == "completed"
    assert published_group[-len(expected_group) :] == expected_group
    assert published_group[0] in service._PATCH_PUBLICATION_TABLES


def test_patch_reset_restore_commit_gap_reconciles_new_version_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SimulatedProcessDeath(BaseException):
        pass

    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _source_snapshot(source)

    def fresh_service() -> FabricSyncService:
        return FabricSyncService(
            source_root=source,
            onelake=OneLakeWriter(
                "workspace",
                "lakehouse",
                local_root=lakehouse,
            ),
            delta_writer=DeltaWriter(),
            validator=DataQualityValidator(),
            write_workers=1,
        )

    first = fresh_service()
    original_load = first.mapper.load

    def load_with_patch_barrier(*args, **kwargs):
        datasets = original_load(*args, **kwargs)
        content = {
            "combined_source_generation": "source-run-1",
            "source_generation": "source-run-1",
            "replaces_legacy_connection_id": "",
            "status": "succeeded",
            "completeness": "healthy-empty",
            "freshness": "fresh",
            "freshness_at": "2026-08-17T00:00:00Z",
            "freshness_threshold_seconds": 3600,
            "represented_count": 0,
            "expected_count": 0,
        }
        datasets[first._PATCH_PUBLICATION_BARRIER] = [
            {
                "tenant_id": "system",
                "subscription_id": "sub-1",
                "resource_id": "patch-snapshot://sub-1",
                "timestamp": "2026-08-17T00:00:00Z",
                "change_version": sync_module._hash_json(content),
                "ingestion_run_id": "publication-run",
                "connection_id": "connection-a",
                **content,
            }
        ]
        return datasets

    monkeypatch.setattr(first.mapper, "load", load_with_patch_barrier)
    reset_table = first._PATCH_PUBLICATION_TABLES[0]
    layer, logical_name = reset_table.split("_", 1)
    table_uri = first.onelake.table_uri(layer, logical_name)
    baseline = first.delta.write(
        table_uri,
        [],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for(reset_table),
        partition_by=first.partitioning.columns_for(reset_table),
    ).version
    assert baseline == 0
    original_record = first.publication_checkpoints.record_table_result

    def die_after_first_patch(*args, table_name, **kwargs):
        original_record(*args, table_name=table_name, **kwargs)
        if table_name == reset_table:
            raise SimulatedProcessDeath("after first patch completion")

    monkeypatch.setattr(
        first.publication_checkpoints,
        "record_table_result",
        die_after_first_patch,
    )
    with pytest.raises(SimulatedProcessDeath, match="first patch completion"):
        first.sync()

    second = fresh_service()
    restore_completed = False

    def die_after_restore(*args, **kwargs):
        nonlocal restore_completed
        restore_completed = True
        raise SimulatedProcessDeath(
            "after Delta restore before checkpoint fence"
        )

    monkeypatch.setattr(
        second.publication_checkpoints,
        "complete_table_restore",
        die_after_restore,
    )
    with pytest.raises(
        SimulatedProcessDeath,
        match="after Delta restore before checkpoint fence",
    ):
        second.sync(replay_source_run_id="source-run-1")
    assert restore_completed is True
    restored_delta_version = second.delta.version(table_uri)
    assert restored_delta_version is not None
    assert restored_delta_version > baseline

    progress_path = next(
        (lakehouse / "Files").rglob("progress.json")
    )
    restore_gap = json.loads(progress_path.read_text(encoding="utf-8"))
    assert restore_gap["in_flight"][reset_table]["operation"] == "restore"

    third = fresh_service()
    monkeypatch.setattr(
        third.mapper,
        "load",
        lambda *_args, **_kwargs: pytest.fail(
            "patch reset replay remapped datasets"
        ),
    )
    monkeypatch.setattr(
        third.delta,
        "restore",
        lambda *_args, **_kwargs: pytest.fail(
            "committed patch restore was repeated"
        ),
    )
    result = third.sync(replay_source_run_id="source-run-1")

    assert result.status == "completed"
    finalized = json.loads(progress_path.read_text(encoding="utf-8"))
    assert finalized["status"] == "finalized"
    assert finalized["in_flight"] == {}
    assert (
        finalized["expected_before_versions"][reset_table]
        == restored_delta_version
    )


def test_missing_exact_replay_does_not_fallback_or_activate_pointer(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    with pytest.raises(FileNotFoundError):
        service.sync(
            replay_source_run_id="missing-generation",
            exposure_pointer_store=pointer_store,
        )

    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    assert not any(row.get("status") == "completed" for row in service.status())


def test_successful_publication_hooks_follow_exact_side_effect_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    normal_table_writes: list[str] = []
    gold_table_writes: list[str] = []
    trace_lock = Lock()
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    original_delta_write = service.delta.write
    original_register = service._register_fabric_assets
    original_catalog_write = service.onelake.write_json
    original_publish = service._publish_ontology
    original_stage = sync_module.ExposureGoldFabricPublisher.stage
    original_state = service._write_state
    original_shortcuts = service._create_shortcuts
    original_activate = sync_module.ExposureGoldFabricPublisher.activate
    original_finalize = service.publication_checkpoints.finalize
    registrations = 0
    catalogs = 0
    gold_tables = {
        *EXPOSURE_GOLD_TABLES,
        EXPOSURE_GOLD_GENERATIONS_TABLE,
    }
    non_publication_tables = {
        "metadata_ingestion_state",
        "metadata_quality_reports",
    }

    def record(entry: str) -> None:
        with trace_lock:
            trace.append(entry)

    def record_write(category: str, table_name: str) -> None:
        with trace_lock:
            trace.append(category)
            if category == "gold_write":
                gold_table_writes.append(table_name)
            else:
                normal_table_writes.append(table_name)

    def delta_write(uri, rows, **kwargs):
        table_name = Path(str(uri)).name
        if table_name in gold_tables:
            record_write("gold_write", table_name)
        elif table_name not in non_publication_tables:
            record_write("normal_write", table_name)
        return original_delta_write(uri, rows, **kwargs)

    def register(tables):
        nonlocal registrations
        registrations += 1
        record("first_registration" if registrations == 1 else "second_registration")
        return original_register(tables)

    def write_json(path, payload):
        nonlocal catalogs
        if path == "ontology/metadata/catalog.json":
            catalogs += 1
            record("normal_catalog" if catalogs == 1 else "gold_catalog")
        return original_catalog_write(path, payload)

    def publish(datasets):
        record("ontology_publication")
        return original_publish(datasets)

    def stage(publisher, *args, **kwargs):
        record("gold_stage")
        return original_stage(publisher, *args, **kwargs)

    def write_state(row):
        if row.get("status") == "completed":
            record("completed_state")
        return original_state(row)

    def shortcuts():
        record("shortcut_finalization")
        return original_shortcuts()

    def activate(publisher, stage_result):
        record("pointer_activation")
        return original_activate(publisher, stage_result)

    def finalize(*args, **kwargs):
        record("checkpoint_finalization")
        return original_finalize(*args, **kwargs)

    monkeypatch.setattr(service.delta, "write", delta_write)
    monkeypatch.setattr(service, "_register_fabric_assets", register)
    monkeypatch.setattr(service.onelake, "write_json", write_json)
    monkeypatch.setattr(service, "_publish_ontology", publish)
    monkeypatch.setattr(sync_module.ExposureGoldFabricPublisher, "stage", stage)
    monkeypatch.setattr(service, "_write_state", write_state)
    monkeypatch.setattr(service, "_create_shortcuts", shortcuts)
    monkeypatch.setattr(
        sync_module.ExposureGoldFabricPublisher,
        "activate",
        activate,
    )
    monkeypatch.setattr(
        service.publication_checkpoints,
        "finalize",
        finalize,
    )

    result = service.sync(exposure_pointer_store=pointer_store)

    assert set(normal_table_writes) == set(result.tables) - gold_tables
    assert gold_table_writes == [
        *EXPOSURE_GOLD_TABLES,
        EXPOSURE_GOLD_GENERATIONS_TABLE,
    ]
    assert trace == [
        *(["normal_write"] * len(normal_table_writes)),
        "first_registration",
        "normal_catalog",
        "ontology_publication",
        "gold_stage",
        *(["gold_write"] * len(gold_tables)),
        "second_registration",
        "gold_catalog",
        "shortcut_finalization",
        "completed_state",
        "pointer_activation",
        "checkpoint_finalization",
    ]
    assert trace.count("pointer_activation") == 1
    assert trace[-2:] == ["pointer_activation", "checkpoint_finalization"]
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)


@pytest.mark.parametrize(
    "failpoint",
    [
        "normal_write",
        "first_registration",
        "normal_catalog",
        "ontology_publication",
        "gold_stage",
        "gold_write",
        "second_registration",
        "gold_catalog",
        "shortcut_finalization",
        "completed_state",
    ],
)
def test_every_pre_activation_failpoint_leaves_gold_pointer_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failpoint: str,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    original_delta_write = service.delta.write
    original_register = service._register_fabric_assets
    original_catalog_write = service.onelake.write_json
    original_publish = service._publish_ontology
    original_stage = sync_module.ExposureGoldFabricPublisher.stage
    original_state = service._write_state
    original_shortcuts = service._create_shortcuts
    registrations = 0
    catalogs = 0
    failed_once = False

    def should_fail(category: str) -> bool:
        nonlocal failed_once
        if failpoint == category and not failed_once:
            failed_once = True
            return True
        return False

    def delta_write(uri, rows, **kwargs):
        text = str(uri)
        if "bronze_resources" in text and should_fail("normal_write"):
            raise RuntimeError("injected safe failpoint")
        if "gold_exposure_facts" in text and should_fail("gold_write"):
            raise RuntimeError("injected safe failpoint")
        return original_delta_write(uri, rows, **kwargs)

    def register(tables):
        nonlocal registrations
        registrations += 1
        category = "first_registration" if registrations == 1 else "second_registration"
        if should_fail(category):
            raise RuntimeError("injected safe failpoint")
        return original_register(tables)

    def write_json(path, payload):
        nonlocal catalogs
        if path == "ontology/metadata/catalog.json":
            catalogs += 1
            category = "normal_catalog" if catalogs == 1 else "gold_catalog"
            if should_fail(category):
                raise RuntimeError("injected safe failpoint")
        return original_catalog_write(path, payload)

    def publish(datasets):
        if should_fail("ontology_publication"):
            raise RuntimeError("injected safe failpoint")
        return original_publish(datasets)

    def stage(publisher, *args, **kwargs):
        if should_fail("gold_stage"):
            raise RuntimeError("injected safe failpoint")
        return original_stage(publisher, *args, **kwargs)

    def write_state(row):
        if row.get("status") == "completed" and should_fail("completed_state"):
            raise RuntimeError("injected safe failpoint")
        return original_state(row)

    def shortcuts():
        if should_fail("shortcut_finalization"):
            raise RuntimeError("injected safe failpoint")
        return original_shortcuts()

    monkeypatch.setattr(service.delta, "write", delta_write)
    monkeypatch.setattr(service, "_register_fabric_assets", register)
    monkeypatch.setattr(service.onelake, "write_json", write_json)
    monkeypatch.setattr(service, "_publish_ontology", publish)
    monkeypatch.setattr(sync_module.ExposureGoldFabricPublisher, "stage", stage)
    monkeypatch.setattr(service, "_write_state", write_state)
    monkeypatch.setattr(service, "_create_shortcuts", shortcuts)

    with pytest.raises(RuntimeError, match="injected safe failpoint"):
        service.sync(exposure_pointer_store=pointer_store)

    assert failed_once is True
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}


def test_completed_version_marker_is_written_before_pointer_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    original_state = service._write_state
    pointer_at_completed_state: list[dict] = []

    def write_state(row):
        if row.get("status") == "completed":
            pointer_at_completed_state.append(
                pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
            )
        return original_state(row)

    monkeypatch.setattr(service, "_write_state", write_state)

    service.sync(exposure_pointer_store=pointer_store)

    assert len(pointer_at_completed_state) == 1
    assert pointer_at_completed_state == [{}]
    marker = max(
        (row for row in service.status() if row.get("status") == "completed"),
        key=lambda row: str(row.get("timestamp") or ""),
    )
    assert marker["ontology_entity_version"] == service.delta.version(
        service.onelake.table_uri("ontology", "entities")
    )
    assert marker["ontology_relationship_version"] == service.delta.version(
        service.onelake.table_uri("ontology", "relationships")
    )


def test_pointer_activation_failure_publishes_no_completed_version_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    def fail_activation(_publisher, _stage):
        raise RuntimeError("injected pointer activation failure")

    monkeypatch.setattr(
        sync_module.ExposureGoldFabricPublisher,
        "activate",
        fail_activation,
    )

    with pytest.raises(
        RuntimeError,
        match="injected pointer activation failure",
    ):
        service.sync(exposure_pointer_store=pointer_store)

    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    assert not any(row.get("status") == "completed" for row in service.status())


def test_sync_publishes_repeatable_exposure_generation_and_pointer(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    first = service.sync(exposure_pointer_store=pointer_store)
    first_pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    first_facts = service.delta.read(
        service.onelake.table_uri("gold", "exposure_facts")
    )
    second = service.sync(exposure_pointer_store=pointer_store)

    pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    second_facts = service.delta.read(
        service.onelake.table_uri("gold", "exposure_facts")
    )
    expected_generation = str(pointer["readable_generation_id"])
    assert first.status == "completed"
    assert second.status == "completed"
    assert second.run_id != first.run_id
    assert expected_generation.startswith("exposure-gold-")
    assert set(EXPOSURE_GOLD_TABLES) <= set(second.tables)
    assert "metadata_exposure_gold_generations" in second.tables
    assert pointer["retained_generations"][expected_generation]
    assert pointer["revision"] > first_pointer["revision"]
    assert pointer["activated_at"] == first_pointer["activated_at"]
    assert (
        pointer["retained_generations"][expected_generation]
        == (first_pointer["retained_generations"][expected_generation])
    )
    assert second_facts == first_facts
    generation_rows = service.delta.read(
        service.onelake.table_uri(
            "metadata",
            "exposure_gold_generations",
        )
    )
    assert {row["read_model_generation_id"] for row in generation_rows} == {
        expected_generation
    }
    assert generation_rows[0]["published_at"] == pointer["activated_at"]
    assert (
        generation_rows[0]["retain_until"]
        == (pointer["retained_generations"][expected_generation]["retain_until"])
    )
    observations = service.delta.read(
        service.onelake.table_uri(
            "silver",
            "exposure_observations",
        )
    )
    assert len(observations) == len({row["observation_id"] for row in observations})
    assert (
        service.delta.read(
            service.onelake.table_uri(
                "gold",
                "container_exposure_coverage",
            )
        )[0]["timestamp"]
        != "1970-01-01T00:00:00Z"
    )


def test_identical_source_produces_identical_gold_in_clean_lakehouses(
    tmp_path: Path,
) -> None:
    first_service = _service(tmp_path / "first")
    second_service = _service(tmp_path / "second")
    first_pointer = OneLakeDocumentStore(tmp_path / "first-registry")
    second_pointer = OneLakeDocumentStore(tmp_path / "second-registry")

    first_service.sync(exposure_pointer_store=first_pointer)
    second_service.sync(exposure_pointer_store=second_pointer)

    assert (
        first_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)["readable_generation_id"]
        == second_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)["readable_generation_id"]
    )
    assert first_service.delta.read(
        first_service.onelake.table_uri("gold", "exposure_facts")
    ) == second_service.delta.read(
        second_service.onelake.table_uri("gold", "exposure_facts")
    )


def test_sync_deduplicates_granular_ontology_scope_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_rows = GranularExposureOntologyMapper.build_rows

    def build_overlapping_rows(self, datasets, **kwargs):
        entities, relationships = original_build_rows(
            self,
            datasets,
            **kwargs,
        )
        overlapping_entity = dict(datasets["ontology_entities"][0])
        base_payload = json.loads(overlapping_entity["payload_json"])
        overlapping_entity["payload_json"] = json.dumps(
            {
                "fabric_key": "container-registry:v1:overlap",
                "fabric_row": {"registry_id": "registry-overlap"},
                "fabric_table": "silver_container_registries",
                **{
                    key: value
                    for key, value in base_payload.items()
                    if key not in {"fabric_key", "fabric_row", "fabric_table"}
                },
            },
            sort_keys=True,
        )
        return (
            [overlapping_entity, *entities],
            [dict(datasets["ontology_relationships"][0]), *relationships],
        )

    monkeypatch.setattr(
        GranularExposureOntologyMapper,
        "build_rows",
        build_overlapping_rows,
    )
    service = _service(tmp_path)

    result = service.sync(
        exposure_pointer_store=OneLakeDocumentStore(tmp_path / "registry")
    )

    assert result.status == "completed"
    entity_rows = service.delta.read(service.onelake.table_uri("ontology", "entities"))
    relationship_rows = service.delta.read(
        service.onelake.table_uri("ontology", "relationships")
    )
    assert len(entity_rows) == len(
        {str(row["resource_id"]).strip().casefold() for row in entity_rows}
    )
    assert len(relationship_rows) == len(
        {str(row["resource_id"]).strip().casefold() for row in relationship_rows}
    )
    restored = GranularExposureOntologyMapper().to_fabric(
        OntologyGraphResult(
            entities=entity_rows,
            relationships=relationship_rows,
            views={},
            health={},
            quality_report={},
        )
    )
    assert restored["silver_container_registries"] == [
        {"registry_id": "registry-overlap"}
    ]


def test_granular_entity_merge_is_lossless_and_preserves_primary_casing() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "/Subscriptions/Sub-A/registry",
        "entity_type": "ContainerRegistry",
        "lifecycle_status": "active",
        "payload_json": json.dumps(
            {
                "id": "/Subscriptions/Sub-A/registry",
                "resourceType": "Microsoft.ContainerRegistry/registries",
                "sourceSystem": "AzureResourceGraph",
            }
        ),
        "lineage_json": json.dumps({"source_resource_ids": ["inventory"]}),
        "semantic_metadata_json": json.dumps({"discovery": "inventory"}),
        "change_version": "old",
    }
    granular = {
        **primary,
        "resource_id": "/subscriptions/sub-a/registry",
        "payload_json": json.dumps(
            {
                "id": "/subscriptions/sub-a/registry",
                "resourceType": "microsoft.containerregistry/registries",
                "fabric_table": "silver_container_registries",
                "fabric_row": {"registry_id": "registry-a"},
            }
        ),
        "lineage_json": json.dumps({"source_resource_ids": ["granular"]}),
    }
    rows = [primary]

    _merge_granular_ontology_entities(rows, [granular])

    payload = json.loads(rows[0]["payload_json"])
    assert payload["id"] == "/Subscriptions/Sub-A/registry"
    assert payload["resourceType"] == "Microsoft.ContainerRegistry/registries"
    assert payload["sourceSystem"] == "AzureResourceGraph"
    assert payload["fabric_row"] == {"registry_id": "registry-a"}
    assert json.loads(rows[0]["lineage_json"])["source_resource_ids"] == [
        "granular",
        "inventory",
    ]
    assert rows[0]["semantic_metadata_json"] == primary["semantic_metadata_json"]
    assert rows[0]["change_version"] == entity_change_version(rows[0])


def test_granular_relationship_merge_rejects_conflicting_identity() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/subscriptions/sub-a",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/subscriptions/sub-a/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": "{}",
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription", "group-one"]}
        ),
        "change_version": "",
    }
    primary["change_version"] = relationship_change_version(primary)
    conflict = {
        **primary,
        "object_id": "/subscriptions/sub-a/resourceGroups/two",
    }

    with pytest.raises(
        ValueError,
        match="Conflicting granular ontology relationship .*: object_id",
    ):
        _merge_granular_ontology_relationships([primary], [conflict])


def test_granular_relationship_merge_rejects_conflicting_payload() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/subscriptions/sub-a",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/subscriptions/sub-a/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": json.dumps({"evidence": "inventory"}),
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription", "group-one"]}
        ),
        "change_version": "",
    }
    primary["change_version"] = relationship_change_version(primary)
    conflict = {
        **primary,
        "payload_json": json.dumps({"evidence": "granular"}),
    }

    with pytest.raises(
        ValueError,
        match="Conflicting granular ontology entity payload_json.evidence",
    ):
        _merge_granular_ontology_relationships([primary], [conflict])


def test_granular_relationship_merge_unions_lineage_and_versions_row() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/Subscriptions/Sub-A",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/Subscriptions/Sub-A/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": "{}",
        "lineage_json": json.dumps({"source_entity_ids": ["subscription"]}),
        "change_version": "old",
    }
    granular = {
        **primary,
        "subject_id": "/subscriptions/sub-a",
        "object_id": "/subscriptions/sub-a/resourcegroups/one",
        "lineage_json": json.dumps({"source_entity_ids": ["group-one"]}),
    }
    rows = [primary]

    _merge_granular_ontology_relationships(rows, [granular])

    assert rows[0]["subject_id"] == "/Subscriptions/Sub-A"
    assert rows[0]["object_id"] == ("/Subscriptions/Sub-A/resourceGroups/one")
    assert json.loads(rows[0]["lineage_json"])["source_entity_ids"] == [
        "group-one",
        "subscription",
    ]
    assert rows[0]["change_version"] == relationship_change_version(rows[0])


def test_sync_does_not_activate_gold_pointer_before_finalization(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    def fail_shortcuts() -> None:
        raise RuntimeError("shortcut finalization failed")

    service._create_shortcuts = fail_shortcuts  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="shortcut finalization failed"):
        service.sync(exposure_pointer_store=pointer_store)

    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    assert not any(row.get("status") == "completed" for row in service.status())
    assert (
        max(
            service.status(),
            key=lambda row: str(row.get("timestamp") or ""),
        )["status"]
        == "failed"
    )


def _persist_uncommitted_canonical_head(
    service: FabricSyncService,
    *,
    entities: list[dict],
    relationships: list[dict],
) -> None:
    """Model writes that survived SIGKILL without running exception rollback."""
    service.onelake.ensure_standard_structure()
    service._write_state(
        _state_row(
            "dead-fabric-run",
            "dead-source-run",
            status="started",
            timestamp="2026-09-09T00:00:00Z",
            replay=False,
        )
    )
    service.delta.write(
        service.onelake.table_uri("ontology", "entities"),
        entities,
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("ontology_entities"),
    )
    service.delta.write(
        service.onelake.table_uri("ontology", "relationships"),
        relationships,
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("ontology_relationships"),
    )


def test_initial_gold_retry_ignores_partial_canonical_head_from_dead_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _service(tmp_path / "seed")
    seed.sync()
    partial_entities = seed.delta.read(seed.onelake.table_uri("ontology", "entities"))
    partial_relationships = seed.delta.read(
        seed.onelake.table_uri("ontology", "relationships")
    )[:-1]

    crashed = _service(tmp_path / "target")
    _persist_uncommitted_canonical_head(
        crashed,
        entities=partial_entities,
        relationships=partial_relationships,
    )
    pointer_store = OneLakeDocumentStore(tmp_path / "target" / "registry")
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    assert _service(tmp_path / "target").semantic_graph_snapshot() == {
        "entities": [],
        "relationships": [],
        "knowledge_version": "semantic-unversioned",
        "freshness": "",
        "ontology_synchronized_at": "",
    }

    synchronizer_type = sync_module.OntologyGraphSynchronizer

    class NoUncommittedPredecessor(synchronizer_type):
        def synchronize(self, *args, **kwargs):
            previous_entities = list(kwargs.get("previous_entities", ()))
            previous_relationships = list(kwargs.get("previous_relationships", ()))
            assert previous_entities == [], (
                "process-death partial canonical entities became predecessor"
            )
            assert previous_relationships == [], (
                "process-death partial canonical relationships became predecessor"
            )
            kwargs["previous_entities"] = previous_entities
            kwargs["previous_relationships"] = previous_relationships
            return super().synchronize(*args, **kwargs)

    monkeypatch.setattr(
        sync_module,
        "OntologyGraphSynchronizer",
        NoUncommittedPredecessor,
    )

    result = _service(tmp_path / "target").sync(exposure_pointer_store=pointer_store)

    assert result.status == "completed"
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)


def test_fresh_service_reads_finalized_canonical_versions_before_first_pointer(
    tmp_path: Path,
) -> None:
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    completed = _service(tmp_path)
    completed.sync()
    expected_entities = {
        row["resource_id"]
        for row in completed.delta.read(
            completed.onelake.table_uri("ontology", "entities")
        )
    }
    expected_relationships = {
        row["resource_id"]
        for row in completed.delta.read(
            completed.onelake.table_uri("ontology", "relationships")
        )
    }

    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    authoritative = _service(tmp_path).semantic_graph_snapshot()
    assert {
        row["resource_id"] for row in authoritative["entities"]
    } == expected_entities
    assert {
        row["resource_id"] for row in authoritative["relationships"]
    } == expected_relationships


def test_post_pointer_retry_reads_last_completed_versions_after_partial_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")
    completed = _service(tmp_path)
    completed.sync(exposure_pointer_store=pointer_store)
    completed_entities = completed.delta.read(
        completed.onelake.table_uri("ontology", "entities")
    )
    completed_relationships = completed.delta.read(
        completed.onelake.table_uri("ontology", "relationships")
    )
    pointer_before_death = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)

    # A later process replaces only one canonical table and dies before any
    # finalization marker or Gold pointer activation.
    crashed = _service(tmp_path)
    crashed._write_state(
        _state_row(
            "later-dead-fabric-run",
            "later-dead-source-run",
            status="started",
            timestamp="2026-09-09T00:01:00Z",
            replay=False,
        )
    )
    crashed.delta.write(
        crashed.onelake.table_uri("ontology", "relationships"),
        completed_relationships[:-1],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("ontology_relationships"),
    )
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == (pointer_before_death)

    expected_entity_ids = {row["resource_id"] for row in completed_entities}
    expected_relationship_ids = {row["resource_id"] for row in completed_relationships}
    authoritative = _service(tmp_path).semantic_graph_snapshot()
    assert {
        row["resource_id"] for row in authoritative["entities"]
    } == expected_entity_ids
    assert {
        row["resource_id"] for row in authoritative["relationships"]
    } == expected_relationship_ids
    compatibility = _service(tmp_path).semantic_snapshot()
    assert {
        row["resource_id"] for row in compatibility["entities"]
    } == expected_entity_ids
    assert {
        row["resource_id"] for row in compatibility["relationships"]
    } == expected_relationship_ids
    synchronizer_type = sync_module.OntologyGraphSynchronizer

    class ExactCompletedPredecessor(synchronizer_type):
        def synchronize(self, *args, **kwargs):
            previous_entities = list(kwargs.get("previous_entities", ()))
            previous_relationships = list(kwargs.get("previous_relationships", ()))
            assert {
                row["resource_id"] for row in previous_entities
            } == expected_entity_ids
            assert {
                row["resource_id"] for row in previous_relationships
            } == expected_relationship_ids
            kwargs["previous_entities"] = previous_entities
            kwargs["previous_relationships"] = previous_relationships
            return super().synchronize(*args, **kwargs)

    monkeypatch.setattr(
        sync_module,
        "OntologyGraphSynchronizer",
        ExactCompletedPredecessor,
    )

    result = _service(tmp_path).sync(exposure_pointer_store=pointer_store)

    assert result.status == "completed"


def test_replayed_generation_excludes_later_observation_history() -> None:
    rows = [
        {"observation_id": "before", "ingested_at": "2026-09-08T00:00:00Z"},
        {"observation_id": "same", "ingested_at": "2026-09-08T01:00:00Z"},
        {"observation_id": "after", "ingested_at": "2026-09-08T02:00:00Z"},
    ]

    visible = _observation_rows_at_or_before(
        rows,
        projected_at="2026-09-08T01:00:00Z",
    )

    assert [row["observation_id"] for row in visible] == [
        "before",
        "same",
    ]


def test_semantic_snapshot_drops_facts_for_retired_entities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    entity = {
        "resource_id": "resource-active",
        "entity_type": "VirtualMachine",
        "name": "active",
        "timestamp": "2026-09-14T00:00:00Z",
        "lifecycle_status": "active",
    }
    monkeypatch.setattr(
        service,
        "_latest_completed_ontology_state",
        lambda: {"source_run_id": "run-1", "timestamp": entity["timestamp"]},
    )
    monkeypatch.setattr(
        service,
        "_read_authoritative_ontology",
        lambda marker: ([entity], []),
    )
    monkeypatch.setattr(
        service,
        "_global_freshness_watermark",
        lambda watermark: watermark,
    )
    monkeypatch.setattr(
        service.onelake,
        "table_uri",
        lambda layer, name: f"{layer}/{name}",
    )
    monkeypatch.setattr(service.delta, "version", lambda _uri: 1)
    def fake_read(uri: str) -> list[dict[str, Any]]:
        if "compliance" in str(uri):
                return [
                    {
                        "assessed_resource_id": "resource-retired",
                        "status": "failed",
                        "failed_patch_count": 2,
                    },
                    {
                        "assessed_resource_id": "resource-active",
                        "status": "compliant",
                        "failed_patch_count": 0,
                    },
                ]
        if "resources" in str(uri):
                return [
                    {"resource_id": "resource-retired"},
                    {"resource_id": "resource-active"},
                ]
        return []

    monkeypatch.setattr(service.delta, "read", fake_read)

    snapshot = service.semantic_snapshot()

    assert snapshot["compliance"] == [
        {
            "assessed_resource_id": "resource-active",
            "status": "compliant",
            "failed_patch_count": 0,
        }
    ]
    assert snapshot["inventory"] == [{"resource_id": "resource-active"}]


def test_gold_generation_identity_changes_with_late_observation() -> None:
    datasets = {"silver_exposure_observations": [{"observation_id": "observation-a"}]}
    first = _exposure_gold_generation_id("source-a", datasets)
    datasets["silver_exposure_observations"].append(
        {"observation_id": "observation-late"}
    )

    assert _exposure_gold_generation_id("source-a", datasets) != first


def test_dedicated_publisher_promotes_before_fabric_materialization() -> None:
    calls: list[tuple[str, object]] = []

    class GenerationPublisher:
        def publish(self, candidate, **kwargs):
            calls.append(("generation", kwargs["publisher_identity"]))
            assert kwargs["publisher_identity"] == "ontology-publisher"
            return type(
                "Snapshot",
                (),
                {
                    "pointer": type(
                        "Pointer",
                        (),
                        {"active_generation": candidate.generation_id},
                    )(),
                    "etag": "etag-new",
                },
            )()

    class FabricMaterializer:
        def sync(self, **kwargs):
            calls.append(("fabric", kwargs["replay_source_run_id"]))
            return type(
                "Result",
                (),
                {
                    "run_id": "fabric-run",
                    "status": "completed",
                    "tables": ("ontology_entities",),
                },
            )()

    candidate = OntologyGenerationCandidate(
        generation_id="ontology-generation-7",
        source_generation="inventory-generation-7",
        entities=(),
        relationships=(),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="policy-v1",
        schema_version="schema-v1",
    )
    adapter = DedicatedOntologyPublisherAdapter(
        generation_publisher=GenerationPublisher(),
        fabric_sync_service=FabricMaterializer(),
        publisher_identity="ontology-publisher",
        request_factory=lambda run, published: {
            "checkpoint_ids": ("approve-pointer-cutover", "approve-publisher-rbac"),
            "pointer_conditions": object(),
            "owner_id": "publisher-worker",
            "fence": 7,
            "consumer_compatibility": {"api": True},
            "cancellation_check": lambda: False,
            "lease_guard": lambda: None,
        },
        status_reader=lambda run_id: {
            "run_id": run_id,
            "active_generation": "ontology-generation-7",
            "pointer_etag": "etag-new",
        },
    )

    result = asyncio.run(
        adapter.publish(
            run={
                "run_id": "ODR-7",
                # Caller-controlled identity data must be ignored.
                "publisher_identity": "api-identity",
            },
            candidate=candidate,
        )
    )

    assert calls == [
        ("generation", "ontology-publisher"),
        ("fabric", "inventory-generation-7"),
    ]
    assert result == {
        "generation_id": "ontology-generation-7",
        "active_generation": "ontology-generation-7",
        "pointer_etag": "etag-new",
        "fabric_run_id": "fabric-run",
        "fabric_status": "completed",
        "fabric_tables": ["ontology_entities"],
    }


def test_dedicated_publisher_rejects_identity_override_from_request_factory() -> None:
    adapter = DedicatedOntologyPublisherAdapter(
        generation_publisher=object(),
        fabric_sync_service=object(),
        publisher_identity="ontology-publisher",
        request_factory=lambda run, candidate: {
            "publisher_identity": "coordinator-identity"
        },
        status_reader=lambda run_id: {},
    )
    candidate = OntologyGenerationCandidate(
        generation_id="generation-1",
        source_generation="source-1",
        entities=(),
        relationships=(),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="policy-v1",
        schema_version="schema-v1",
    )

    try:
        asyncio.run(adapter.publish(run={"run_id": "ODR-1"}, candidate=candidate))
    except PermissionError as exc:
        assert "identity" in str(exc).lower()
    else:
        raise AssertionError("coordinator identity substitution must be denied")
