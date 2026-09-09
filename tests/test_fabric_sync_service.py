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
from fabric.schema_registry import schema_for
from fabric.sync_service import (
    DedicatedOntologyPublisherAdapter,
    FabricSyncService,
    FabricTableWriteProgress,
    _exposure_gold_generation_id,
    _merge_granular_ontology_entities,
    _merge_granular_ontology_relationships,
    _observation_rows_at_or_before,
    _state_row,
)
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_GENERATIONS_TABLE,
    EXPOSURE_GOLD_POINTER_DOCUMENT,
    EXPOSURE_GOLD_TABLES,
    EXPOSURE_OBSERVATIONS_TABLE,
    TemporalExposureMaterialization,
)
from onboarding.graph_normalize import Normalizer
from onboarding.ingestion_storage import DatasetStore
from ontology.entity_builder import entity_change_version
from ontology.ontology_sync import OntologyGraphResult
from ontology.relationship_builder import relationship_change_version
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.delta_writer import DeltaWriteMode, DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter


def _service(tmp_path: Path) -> FabricSyncService:
    source = tmp_path / "source"
    _source_snapshot(source)
    return FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lakehouse"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )


def _container_source_snapshot(
    root: Path,
    *,
    observed_at: datetime,
    run_id: str,
    severity: str = "Critical",
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
    image_assessment["tenantId"] = "tenant1"
    payload["defender_assessments"].append(image_assessment)
    graph = Normalizer(
        {"connection_id": "connection-1"}
    ).normalize(
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


def test_sync_deduplicates_unchanged_container_observation_across_source_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    _container_source_snapshot(
        source,
        observed_at=datetime(2026, 9, 2, tzinfo=UTC),
        run_id="source-generation-1",
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
    )
    second = service.sync()

    observations = service.delta.read(
        lakehouse / "Tables/silver_container_vulnerability_observations"
    )
    assert first.status == "completed"
    assert second.status == "completed"
    assert len(observations) == 1
    observation_key = (observations[0]["resource_id"],)

    _container_source_snapshot(
        source,
        observed_at=datetime(2026, 9, 4, tzinfo=UTC),
        run_id="source-generation-3",
        severity="Low",
    )
    with pytest.raises(ValueError) as error:
        service.sync()
    assert str(error.value) == f"Append row mutation for key {observation_key}"


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
    assert [event.completed_tables for event in events] == list(range(1, len(events) + 1))
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
            exposure_pointer_store=OneLakeDocumentStore(
                str(tmp_path / "pointer")
            )
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
    checkpoint_index = table_names.index(
        "metadata_workload_source_checkpoints"
    )

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
        event["stage"]
        for event in stage_events
        if event["status"] == "started"
    ]
    assert lifecycle_stages == [
        "dataset_mapping",
        "workload_projection",
        "temporal_projection",
        "container_projection",
        "ontology_construction",
        "ontology_validation",
        "table_publication",
        "fabric_asset_registration",
        "ontology_publication",
        "gold_staging",
        "fabric_asset_registration",
        "shortcut_finalization",
        "pointer_activation",
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
    }
    for event in stage_events:
        assert set(event) >= {"stage", "status"}
        expected_fields = {"stage", "status"}
        if event["status"] == "completed":
            expected_fields |= completion_fields[event["stage"]]
        assert set(event) == expected_fields
        if event["status"] == "completed":
            for field in completion_fields[event["stage"]]:
                assert isinstance(event[field], int)
                assert not isinstance(event[field], bool)
                assert 0 <= event[field] <= 2_147_483_647
    assert table_events
    assert [event.completed_tables for event in table_events] == list(
        range(1, len(table_events) + 1)
    )
    assert all(event.total_tables == len(table_events) for event in table_events)
    assert all(event.result.rows_processed >= 0 for event in table_events)


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

    completed = [
        event["stage"]
        for event in events
        if event["status"] == "completed"
    ]
    assert completed.index("ontology_publication") < completed.index("gold_staging")
    assert completed.index("gold_staging") < completed.index("shortcut_finalization")
    assert completed.index("shortcut_finalization") < completed.index(
        "pointer_activation"
    )
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)


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
        record(
            "first_registration"
            if registrations == 1
            else "second_registration"
        )
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
    ]
    assert trace.count("pointer_activation") == 1
    assert trace[-1] == "pointer_activation"
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
        (
            row
            for row in service.status()
            if row.get("status") == "completed"
        ),
        key=lambda row: str(row.get("timestamp") or ""),
    )
    assert marker["ontology_entity_version"] == service.delta.version(
        service.onelake.table_uri("ontology", "entities")
    )
    assert marker[
        "ontology_relationship_version"
    ] == service.delta.version(
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
    assert not any(
        row.get("status") == "completed" for row in service.status()
    )


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
    assert expected_generation.startswith("exposure-gold-")
    assert set(EXPOSURE_GOLD_TABLES) <= set(second.tables)
    assert "metadata_exposure_gold_generations" in second.tables
    assert pointer["retained_generations"][expected_generation]
    assert pointer["revision"] > first_pointer["revision"]
    assert pointer["activated_at"] == first_pointer["activated_at"]
    assert pointer["retained_generations"][expected_generation] == (
        first_pointer["retained_generations"][expected_generation]
    )
    assert second_facts == first_facts
    generation_rows = service.delta.read(
        service.onelake.table_uri(
            "metadata",
            "exposure_gold_generations",
        )
    )
    assert {
        row["read_model_generation_id"] for row in generation_rows
    } == {expected_generation}
    assert generation_rows[0]["published_at"] == pointer["activated_at"]
    assert generation_rows[0]["retain_until"] == (
        pointer["retained_generations"][expected_generation]["retain_until"]
    )
    observations = service.delta.read(
        service.onelake.table_uri(
            "silver",
            "exposure_observations",
        )
    )
    assert len(observations) == len(
        {row["observation_id"] for row in observations}
    )
    assert service.delta.read(
        service.onelake.table_uri(
            "gold",
            "container_exposure_coverage",
        )
    )[0]["timestamp"] != "1970-01-01T00:00:00Z"


def test_identical_source_produces_identical_gold_in_clean_lakehouses(
    tmp_path: Path,
) -> None:
    first_service = _service(tmp_path / "first")
    second_service = _service(tmp_path / "second")
    first_pointer = OneLakeDocumentStore(tmp_path / "first-registry")
    second_pointer = OneLakeDocumentStore(tmp_path / "second-registry")

    first_service.sync(exposure_pointer_store=first_pointer)
    second_service.sync(exposure_pointer_store=second_pointer)

    assert first_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)[
        "readable_generation_id"
    ] == second_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)[
        "readable_generation_id"
    ]
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
    entity_rows = service.delta.read(
        service.onelake.table_uri("ontology", "entities")
    )
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
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription"]}
        ),
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
    assert rows[0]["object_id"] == (
        "/Subscriptions/Sub-A/resourceGroups/one"
    )
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
    assert not any(
        row.get("status") == "completed" for row in service.status()
    )
    assert max(
        service.status(),
        key=lambda row: str(row.get("timestamp") or ""),
    )["status"] == "failed"


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
    partial_entities = seed.delta.read(
        seed.onelake.table_uri("ontology", "entities")
    )
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
            previous_relationships = list(
                kwargs.get("previous_relationships", ())
            )
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

    result = _service(tmp_path / "target").sync(
        exposure_pointer_store=pointer_store
    )

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
    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == (
        pointer_before_death
    )

    expected_entity_ids = {
        row["resource_id"] for row in completed_entities
    }
    expected_relationship_ids = {
        row["resource_id"] for row in completed_relationships
    }
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
            previous_relationships = list(
                kwargs.get("previous_relationships", ())
            )
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


def test_gold_generation_identity_changes_with_late_observation() -> None:
    datasets = {
        "silver_exposure_observations": [
            {"observation_id": "observation-a"}
        ]
    }
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
                {"run_id": "fabric-run", "status": "completed", "tables": ("ontology_entities",)},
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
