from __future__ import annotations

import io
import json
import logging
import threading
from dataclasses import dataclass

import pytest

from fabric.runtime import FabricRuntimeMode
from fabric.sync_service import FabricTableWriteProgress
from onboarding.activation import (
    ActivationFailure,
    ActivationProgressReporter,
    _shared_metadata_prefetch,
    activate_runtime,
    build_activation_progress_event,
    publish_combined_snapshot,
)
from onboarding.graph_normalize import ENTITY_TYPES, NormalizedGraph
from storage.datasets import DatasetStore
from storage.delta_writer import DeltaWriteResult
from storage.locking import RunLock
from storage.onelake_documents import OneLakeDocumentStore


@dataclass(frozen=True)
class _Connection:
    connection_id: str


class _Registry:
    def __init__(self, connection_ids: tuple[str, ...] = ()) -> None:
        self.connection_ids = connection_ids
        self.root = ""

    def get(self, connection_id: str) -> _Connection:
        return _Connection(connection_id)

    def list(self, *, include_disabled: bool):
        assert include_disabled is False
        return [_Connection(connection_id) for connection_id in self.connection_ids]


class _Coordinator:
    def __init__(self, roots):
        self.roots = roots

    def connection_output_dir(self, connection: _Connection):
        return self.roots[connection.connection_id]


class _Service:
    def __init__(self, roots):
        self.registry = _Registry(tuple(roots))
        self.sync_coordinator = _Coordinator(roots)

    def validate(self, connection_id: str):
        return {"connection_id": connection_id, "passed": True}

    def sync(self, connection_id: str, *, mode: str):
        return {"connection_id": connection_id, "status": "succeeded", "mode": mode}


def _publish(root, connection_id: str, resource_id: str) -> None:
    entities = {name: [] for name in ENTITY_TYPES}
    entities["Resource"] = [
        {
            "id": resource_id,
            "name": resource_id,
            "entityType": "Resource",
            "connection_id": connection_id,
        }
    ]
    graph = NormalizedGraph(entities=entities)
    DatasetStore(root).publish(
        {
            **{
                f"entities/{entity_type}": rows
                for entity_type, rows in graph.entities.items()
            },
            "relationships/relationships": [],
            "changes/resource_changes": [],
            "exposure/source_partition_rows": [
                {
                    "partition_key": f"partition-{connection_id}",
                    "query_name": "defender_assessments",
                    "row_key": f"row-{connection_id}",
                    "payload_json": "{}",
                    "effective_generation": f"effective-{connection_id}",
                    "connection_id": connection_id,
                }
            ],
            "exposure/workload_observations": [
                {
                    "observation_id": f"observation-{connection_id}",
                    "connection_id": connection_id,
                }
            ],
            "exposure/workload_deployments": [
                {
                    "deployment_id": f"deployment-{connection_id}",
                    "connection_id": connection_id,
                    "workspace_id": f"workspace-{connection_id}",
                }
            ],
            "exposure/workload_source_checkpoints": [
                {
                    "checkpoint_key": f"checkpoint-{connection_id}",
                    "connection_id": connection_id,
                    "workspace_id": f"workspace-{connection_id}",
                }
            ],
            "situations/source_status": [
                {
                    "partition_key": f"partition-{connection_id}",
                    "connection_id": connection_id,
                    "source_family": "defender_image",
                    "attempted_generation": f"attempt-{connection_id}",
                    "effective_generation": f"effective-{connection_id}",
                    "attempted_at": "2026-01-01T00:00:00Z",
                    "last_success_at": "2026-01-01T00:00:00Z",
                    "row_count": 1,
                    "represented_count": 1,
                    "expected_count": 1,
                    "completeness": "complete",
                    "safe_error_code": "",
                    "safe_error_summary": "",
                }
            ],
        },
        {},
        {
            "runId": f"run-{connection_id}",
            "status": "completed",
            "startedAt": "2026-01-01T00:00:00Z",
            "completedAt": "2026-01-01T00:01:00Z",
        },
        ontology={},
    )


def test_combined_snapshot_preserves_distinct_connection_entities(tmp_path):
    roots = {"hub": tmp_path / "hub", "spoke": tmp_path / "spoke"}
    _publish(roots["hub"], "hub", "/subscriptions/hub/resourceGroups/rg/providers/x/a")
    _publish(
        roots["spoke"],
        "spoke",
        "/subscriptions/spoke/resourceGroups/rg/providers/x/b",
    )

    publish_combined_snapshot(_Service(roots), ["hub", "spoke"], tmp_path / "combined")

    rows = DatasetStore(tmp_path / "combined").read_dataset("entities/Resource")
    assert {(row["id"], row["connection_id"]) for row in rows} == {
        ("/subscriptions/hub/resourceGroups/rg/providers/x/a", "hub"),
        ("/subscriptions/spoke/resourceGroups/rg/providers/x/b", "spoke"),
    }
    combined = DatasetStore(tmp_path / "combined")
    assert {
        row["deployment_id"]
        for row in combined.read_dataset("exposure/workload_deployments")
    } == {"deployment-hub", "deployment-spoke"}
    assert {
        row["row_key"]
        for row in combined.read_dataset("exposure/source_partition_rows")
    } == {"row-hub", "row-spoke"}
    assert {
        row["checkpoint_key"]
        for row in combined.read_dataset("exposure/workload_source_checkpoints")
    } == {"checkpoint-hub", "checkpoint-spoke"}
    assert {
        row["partition_key"]
        for row in combined.read_dataset("situations/source_status")
    } == {"partition-hub", "partition-spoke"}


def test_combined_activation_creates_new_generation_when_sources_are_unchanged(
    tmp_path,
) -> None:
    roots = {"hub": tmp_path / "hub"}
    _publish(
        roots["hub"],
        "hub",
        "/subscriptions/hub/resourceGroups/rg/providers/x/a",
    )
    combined_root = tmp_path / "combined"
    service = _Service(roots)

    first = publish_combined_snapshot(service, ["hub"], combined_root)
    second = publish_combined_snapshot(service, ["hub"], combined_root)

    assert second["runId"] != first["runId"]
    assert second["sourceRunIds"] == first["sourceRunIds"]


def test_combined_snapshot_can_reuse_unchanged_sources_for_patch_writer(
    tmp_path,
) -> None:
    roots = {"hub": tmp_path / "hub"}
    _publish(
        roots["hub"],
        "hub",
        "/subscriptions/hub/resourceGroups/rg/providers/x/a",
    )
    combined_root = tmp_path / "combined"
    service = _Service(roots)

    first = publish_combined_snapshot(
        service,
        ["hub"],
        combined_root,
        reuse_unchanged=True,
    )
    second = publish_combined_snapshot(
        service,
        ["hub"],
        combined_root,
        reuse_unchanged=True,
    )

    assert second == first
    assert str(DatasetStore(combined_root).current_generation()) == str(
        DatasetStore(combined_root).generation_path(str(first["runId"]))
    )


def test_combined_snapshot_rejects_cross_connection_identity_collision(tmp_path):
    roots = {"hub": tmp_path / "hub", "spoke": tmp_path / "spoke"}
    shared_id = "/subscriptions/shared/resourceGroups/rg/providers/x/a"
    _publish(roots["hub"], "hub", shared_id)
    _publish(roots["spoke"], "spoke", shared_id)

    with pytest.raises(ValueError, match="identity collision across connections"):
        publish_combined_snapshot(
            _Service(roots), ["hub", "spoke"], tmp_path / "combined"
        )


@pytest.mark.parametrize(
    ("stage", "payload"),
    [
        ("connection_validation", {"completed": 1, "total": 2}),
        ("connection_discovery", {"completed": 2, "total": 2}),
        ("combined_snapshot", {"dataset_count": 17, "failure_count": 0}),
        ("dataset_mapping", {"dataset_count": 33, "failure_count": 1}),
        (
            "workload_projection",
            {"entity_count": 80_000, "relationship_count": 233_000, "failure_count": 0},
        ),
        (
            "temporal_projection",
            {"entity_count": 0, "relationship_count": 0, "failure_count": 0},
        ),
        ("temporal_retained_load", {"row_count": 11, "failure_count": 0}),
        ("temporal_legacy_normalization", {"row_count": 12, "failure_count": 0}),
        (
            "temporal_observation_combination",
            {"row_count": 13, "failure_count": 0},
        ),
        ("temporal_current_projection", {"row_count": 14, "failure_count": 0}),
        ("temporal_immutable_checks", {"row_count": 15, "failure_count": 0}),
        (
            "checkpoint_persistence",
            {
                "dataset_count": 460,
                "failure_count": 0,
                "checkpoint_rows_written": 100_000,
                "checkpoint_bytes_written": 12_345_678,
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "persisted",
                "publication_id": "a" * 64,
                "current_phase": "checkpoint_persistence",
            },
        ),
        (
            "checkpoint_restore",
            {
                "dataset_count": 460,
                "failure_count": 0,
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "restored",
                "publication_id": "a" * 64,
                "current_phase": "checkpoint_restore",
            },
        ),
        (
            "publication_resume",
            {
                "completed": 453,
                "total": 460,
                "remaining_tables": 7,
                "resumed_tables": 453,
                "skipped_tables": 453,
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "restored",
                "publication_id": "a" * 64,
                "current_phase": "table_publication",
            },
        ),
        (
            "checkpoint_finalization",
            {
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "finalized",
                "publication_id": "a" * 64,
                "current_phase": "checkpoint_finalization",
            },
        ),
        (
            "checkpoint_activation_pending",
            {
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "activation_pending",
                "publication_id": "a" * 64,
                "current_phase": "pointer_activation",
            },
        ),
        (
            "container_projection",
            {
                "entity_count": 2_147_483_647,
                "relationship_count": 2_147_483_647,
                "failure_count": 2_147_483_647,
            },
        ),
        (
            "ontology_construction",
            {"entity_count": 5, "relationship_count": 7, "failure_count": 0},
        ),
        (
            "ontology_validation",
            {"entity_count": 5, "relationship_count": 7, "failure_count": 2},
        ),
        (
            "table_publication",
            {
                "table_name": "silver_resources",
                "row_count": 123,
                "completed": 4,
                "total": 9,
                "remaining_tables": 5,
                "resumed_tables": 3,
                "skipped_tables": 3,
                "checkpoint_id": "a" * 64,
                "checkpoint_state": "restored",
                "publication_id": "a" * 64,
                "current_phase": "table_publication",
            },
        ),
        ("fabric_asset_registration", {}),
        ("ontology_publication", {}),
        ("gold_staging", {}),
        ("shortcut_finalization", {}),
        ("pointer_activation", {}),
        ("fabric_publication", {}),
        ("activation", {}),
    ],
)
def test_activation_progress_completion_schema_is_exact(stage, payload) -> None:
    event = build_activation_progress_event(
        stage,
        "completed",
        elapsed_seconds=12.5,
        **payload,
    )

    assert event == {
        "event": "activation_progress",
        "stage": stage,
        "status": "completed",
        "elapsed_seconds": 12.5,
        **payload,
    }
    assert set(
        build_activation_progress_event(stage, "started", elapsed_seconds=0)
    ) == {
        "event",
        "stage",
        "status",
        "elapsed_seconds",
    }
    assert set(
        build_activation_progress_event(stage, "heartbeat", elapsed_seconds=60)
    ) == {
        "event",
        "stage",
        "status",
        "elapsed_seconds",
    }


@pytest.mark.parametrize(
    ("stage", "payload"),
    [
        ("combined_snapshot", {"dataset_count": -1, "failure_count": 0}),
        ("combined_snapshot", {"dataset_count": True, "failure_count": 0}),
        ("combined_snapshot", {"dataset_count": 2_147_483_648, "failure_count": 0}),
        ("combined_snapshot", {"dataset_count": 1}),
        ("connection_validation", {"completed": 1, "total": 1, "failure_count": 0}),
        ("fabric_asset_registration", {"dataset_count": 1}),
        ("unknown_stage", {}),
    ],
)
def test_activation_progress_rejects_invalid_or_cross_stage_payloads(
    stage,
    payload,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_activation_progress_event(
            stage,
            "completed",
            elapsed_seconds=1,
            **payload,
        )


def test_activation_progress_failure_schema_is_sanitized() -> None:
    event = build_activation_progress_event(
        "connection_discovery",
        "failed",
        elapsed_seconds=9,
        error_code="ACTIVATION_FAILED",
    )

    assert event == {
        "event": "activation_progress",
        "stage": "connection_discovery",
        "status": "failed",
        "elapsed_seconds": 9.0,
        "error_code": "ACTIVATION_FAILED",
    }
    with pytest.raises(ValueError):
        build_activation_progress_event(
            "connection_discovery",
            "failed",
            elapsed_seconds=9,
            error_code="ACTIVATION_FAILED",
            dataset_count=1,
        )


def test_reporter_emits_bounded_heartbeat_and_joins_worker() -> None:
    now = [0.0]
    heartbeat_seen = threading.Event()
    events: list[dict[str, object]] = []

    def sink(event):
        events.append(event)
        if event["status"] == "heartbeat":
            heartbeat_seen.set()

    def wait(stop: threading.Event, interval: float) -> bool:
        if not heartbeat_seen.is_set():
            now[0] += interval
            return False
        return stop.wait()

    reporter = ActivationProgressReporter(
        sink,
        heartbeat_interval=30,
        clock=lambda: now[0],
        wait=wait,
    )
    reporter.start("combined_snapshot")
    assert heartbeat_seen.wait(timeout=1)
    reporter.complete("combined_snapshot", dataset_count=17, failure_count=0)
    reporter.close()

    assert [event["status"] for event in events] == [
        "started",
        "heartbeat",
        "completed",
    ]
    assert events[1]["elapsed_seconds"] == 30.0
    assert reporter.heartbeat_thread_alive is False


def test_reporter_translates_existing_fabric_table_progress() -> None:
    events: list[dict[str, object]] = []
    reporter = ActivationProgressReporter(events.append, heartbeat_interval=60)

    reporter.fabric_table_progress(
        FabricTableWriteProgress(
            completed_tables=3,
            total_tables=11,
            table_name="gold_exposure_facts",
            result=DeltaWriteResult(rows_processed=456),
            remaining_tables=8,
            resumed_tables=2,
            skipped_tables=2,
            checkpoint_id="a" * 64,
            checkpoint_state="restored",
            current_phase="gold_staging",
        )
    )
    reporter.close()

    assert events == [
        {
            "event": "activation_progress",
            "stage": "table_publication",
            "status": "completed",
            "elapsed_seconds": pytest.approx(events[0]["elapsed_seconds"]),
            "table_name": "gold_exposure_facts",
            "row_count": 456,
            "completed": 3,
            "total": 11,
            "remaining_tables": 8,
            "resumed_tables": 2,
            "skipped_tables": 2,
            "checkpoint_id": "a" * 64,
            "checkpoint_state": "restored",
            "publication_id": "a" * 64,
            "current_phase": "gold_staging",
        }
    ]


def test_progress_sink_failure_logs_only_fixed_safe_contract(caplog) -> None:
    secret = "credential=planted-secret"
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/x/y"

    def broken_sink(_event):
        raise RuntimeError(f"{secret} {resource_id}")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(error_code)s"))
    logger = logging.getLogger("onboarding.activation")
    logger.addHandler(handler)
    caplog.set_level(logging.WARNING, logger="onboarding.activation")
    try:
        reporter = ActivationProgressReporter(broken_sink, heartbeat_interval=60)
        reporter.start("activation")
        reporter.close()
    finally:
        logger.removeHandler(handler)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "activation_progress_callback_failed"
    assert record.error_code == "ACTIVATION_PROGRESS_CALLBACK_FAILED"
    assert record.exc_info is None
    assert stream.getvalue().strip() == (
        "activation_progress_callback_failed ACTIVATION_PROGRESS_CALLBACK_FAILED"
    )
    rendered = caplog.text + stream.getvalue()
    assert secret not in rendered
    assert resource_id not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered


def test_activate_runtime_streams_fabric_stages_through_single_reporter(
    tmp_path,
    monkeypatch,
) -> None:
    roots = {"hub": tmp_path / "hub"}
    _publish(
        roots["hub"],
        "hub",
        "/subscriptions/hub/resourceGroups/rg/providers/x/a",
    )
    service = _Service(roots)
    service.registry.root = tmp_path / "registry"
    events: list[dict[str, object]] = []
    replay_source_run_ids: list[str] = []

    class FabricService:
        def sync(self, **kwargs):
            replay_source_run_ids.append(kwargs["replay_source_run_id"])
            kwargs["stage_progress_callback"](
                {"stage": "dataset_mapping", "status": "started"}
            )
            kwargs["stage_progress_callback"](
                {
                    "stage": "dataset_mapping",
                    "status": "completed",
                    "dataset_count": 17,
                    "failure_count": 0,
                }
            )
            kwargs["progress_callback"](
                FabricTableWriteProgress(
                    completed_tables=1,
                    total_tables=1,
                    table_name="silver_resources",
                    result=DeltaWriteResult(rows_processed=123),
                )
            )
            return type(
                "Publication",
                (),
                {
                    "run_id": "run-1",
                    "source_run_id": "source-1",
                    "status": "completed",
                    "tables": ("silver_resources",),
                },
            )()

    runtime = type(
        "Runtime",
        (),
        {
            "service": FabricService(),
            "semantic_engine": lambda self: type(
                "Semantic",
                (),
                {"knowledge_version": "v1", "freshness": "current"},
            )(),
        },
    )()
    config = type("Config", (), {"source_data_root": tmp_path / "combined"})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )
    runtime_modes: list[FabricRuntimeMode] = []

    def build_publication_runtime(_config, *, mode):
        runtime_modes.append(mode)
        if mode is FabricRuntimeMode.READ:
            raise RuntimeError("metadata_patch_snapshot readiness incomplete")
        return runtime

    monkeypatch.setattr("fabric.runtime.build_runtime", build_publication_runtime)

    result = activate_runtime(
        service,
        fabric_config="fabric.test.yaml",
        progress_callback=events.append,
        heartbeat_interval=3600,
        metadata_prefetch=lambda **_kwargs: {
            "status": "succeeded",
            "requested_count": 0,
            "succeeded_count": 0,
            "failure_count": 0,
        },
    )

    assert result["status"] == "activated"
    assert [event["stage"] for event in events if event["status"] == "started"] == [
        "activation",
        "connection_validation",
        "connection_discovery",
        "combined_snapshot",
        "fabric_publication",
        "dataset_mapping",
        "metadata_prefetch",
    ]
    table_event = next(
        event for event in events if event["stage"] == "table_publication"
    )
    assert table_event["row_count"] == 123
    assert table_event["completed"] == table_event["total"] == 1
    assert "hub" not in json.dumps(events)
    assert replay_source_run_ids == [str(result["combined_snapshot"]["runId"])]
    assert runtime_modes == [FabricRuntimeMode.PUBLISH]


def test_activate_runtime_prefetches_after_lock_release_and_keeps_partial_success(
    tmp_path,
    monkeypatch,
) -> None:
    roots = {"hub": tmp_path / "hub"}
    _publish(
        roots["hub"],
        "hub",
        "/subscriptions/hub/resourceGroups/rg/providers/x/a",
    )
    service = _Service(roots)
    service.registry.root = tmp_path / "registry"
    config = type("Config", (), {"source_data_root": tmp_path / "combined"})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )
    ingestion_lock_root = tmp_path / "fabric"

    class FabricService:
        def sync(self, **_kwargs):
            with RunLock(
                ingestion_lock_root,
                lock_document="ingestion.lock",
            ):
                return type(
                    "Publication",
                    (),
                    {
                        "run_id": "fabric-run",
                        "source_run_id": "source-run",
                        "status": "completed",
                        "tables": ("silver_resources",),
                    },
                )()

    runtime = type(
        "Runtime",
        (),
        {
            "service": FabricService(),
            "semantic_engine": lambda self: type(
                "Semantic",
                (),
                {"knowledge_version": "v1", "freshness": "current"},
            )(),
        },
    )()
    monkeypatch.setattr(
        "fabric.runtime.build_runtime",
        lambda _config, **_kwargs: runtime,
    )
    prefetch_calls: list[dict[str, object]] = []

    def partial_prefetch(**kwargs):
        with RunLock(
            ingestion_lock_root,
            lock_document="ingestion.lock",
        ):
            prefetch_calls.append(kwargs)
        return {
            "status": "partial",
            "selected_count": 4,
            "attempted_count": 4,
            "failed_count": 1,
            "provider_error": "credential=must-not-be-exposed",
        }

    events: list[dict[str, object]] = []
    result = activate_runtime(
        service,
        fabric_config="fabric.test.yaml",
        metadata_prefetch=partial_prefetch,
        progress_callback=events.append,
        heartbeat_interval=3600,
    )

    assert result["status"] == "activated"
    assert result["fabric_publication"]["status"] == "completed"
    assert result["metadata_prefetch"] == {
        "status": "partial",
        "requested_count": 4,
        "succeeded_count": 3,
        "failure_count": 1,
    }
    assert prefetch_calls == [
        {
            "source_root": config.source_data_root,
            "generation_id": result["combined_snapshot"]["runId"],
        }
    ]
    prefetch_event = next(
        event
        for event in events
        if event["stage"] == "metadata_prefetch"
        and event["status"] == "completed"
    )
    assert prefetch_event["requested_count"] == 4
    assert prefetch_event["succeeded_count"] == 3
    assert prefetch_event["failure_count"] == 1
    assert "must-not-be-exposed" not in json.dumps(result) + json.dumps(events)


def test_shared_prefetch_writes_enrichment_to_api_visible_root(
    tmp_path,
    monkeypatch,
) -> None:
    from intelligence.vulnerability import enrichment_worker as worker_module
    from intelligence.vulnerability import exposure_prefetch as prefetch_module
    from intelligence.vulnerability.enrichment_cache import (
        EXPOSURE_ENRICHMENT_DOCUMENT,
    )

    pointer_store = OneLakeDocumentStore(tmp_path / "connections")
    enrichment_store = OneLakeDocumentStore(tmp_path / "aiops")
    captured: dict[str, object] = {}

    class FakeWorker:
        def __init__(self, cache, *, max_items):
            captured["cache_store"] = cache.store
            captured["worker_max_items"] = max_items

    class FakeDiscovery:
        def __init__(self, *, pointer_store, table_reader):
            captured["pointer_store"] = pointer_store
            captured["table_reader"] = table_reader

    class FakeReport:
        def to_dict(self):
            return {"status": "succeeded", "selected_count": 0}

    class FakePrefetchService:
        def __init__(self, *, discovery, worker, checkpoint_store, max_items):
            captured["checkpoint_store"] = checkpoint_store
            captured["service_max_items"] = max_items

        def run(self):
            enrichment_store.write(
                EXPOSURE_ENRICHMENT_DOCUMENT,
                {"schema_version": "2.0.0", "revision": 1},
                expected_revision=0,
            )
            return FakeReport()

    monkeypatch.setattr(worker_module, "EnrichmentWorker", FakeWorker)
    monkeypatch.setattr(
        prefetch_module,
        "ExposureGenerationDiscovery",
        FakeDiscovery,
    )
    monkeypatch.setattr(
        prefetch_module,
        "ExposurePrefetchService",
        FakePrefetchService,
    )

    result = _shared_metadata_prefetch(
        runtime=object(),
        pointer_store=pointer_store,
        enrichment_store=enrichment_store,
    )

    assert result == {"status": "succeeded", "selected_count": 0}
    assert captured["pointer_store"] is pointer_store
    assert captured["cache_store"] is enrichment_store
    assert captured["checkpoint_store"] is enrichment_store
    assert enrichment_store.read(EXPOSURE_ENRICHMENT_DOCUMENT)["revision"] == 1
    assert pointer_store.read(EXPOSURE_ENRICHMENT_DOCUMENT) == {}


def test_activate_runtime_replays_exact_generation_without_upstream_work(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "combined"
    manifest = DatasetStore(source_root).publish(
        {"entities/Resource": [{"id": "historical-resource"}]},
        {},
        {
            "runId": "exact-generation",
            "status": "completed",
            "sourceConnectionIds": ["spoke", "hub"],
            "sourceRunIds": ["run-spoke", "run-hub"],
            "queryVersion": "combined-subscription-connections-v1",
        },
        ontology={},
    )
    service = _Service({})
    service.registry.root = tmp_path / "registry"

    def unexpected_upstream_call(*_args, **_kwargs):
        pytest.fail("exact replay must not invoke upstream discovery")

    service.registry.list = unexpected_upstream_call
    service.validate = unexpected_upstream_call
    service.sync = unexpected_upstream_call
    monkeypatch.setattr(DatasetStore, "current_generation", unexpected_upstream_call)

    sync_kwargs: dict[str, object] = {}

    class FabricService:
        def sync(self, **kwargs):
            sync_kwargs.update(kwargs)
            return type(
                "Publication",
                (),
                {
                    "run_id": "fabric-run",
                    "source_run_id": "exact-generation",
                    "status": "completed",
                    "tables": ("silver_resources",),
                },
            )()

    runtime = type(
        "Runtime",
        (),
        {
            "service": FabricService(),
            "semantic_engine": lambda self: type(
                "Semantic",
                (),
                {"knowledge_version": "v1", "freshness": "current"},
            )(),
        },
    )()
    config = type("Config", (), {"source_data_root": source_root})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )
    monkeypatch.setattr(
        "fabric.runtime.build_runtime",
        lambda _config, **_kwargs: runtime,
    )
    events: list[dict[str, object]] = []

    result = activate_runtime(
        service,
        fabric_config="fabric.test.yaml",
        replay_source_run_id="exact-generation",
        progress_callback=events.append,
        heartbeat_interval=3600,
        metadata_prefetch=lambda **_kwargs: {
            "status": "succeeded",
            "requested_count": 0,
            "succeeded_count": 0,
            "failure_count": 0,
        },
    )

    assert result == {
        "status": "activated",
        "connections": ["hub", "spoke"],
        "validations": {},
        "discovery_syncs": {},
        "combined_snapshot": manifest,
        "fabric_publication": {
            "run_id": "fabric-run",
            "source_run_id": "exact-generation",
            "status": "completed",
            "tables": ["silver_resources"],
        },
        "metadata_prefetch": {
            "status": "succeeded",
            "requested_count": 0,
            "succeeded_count": 0,
            "failure_count": 0,
        },
        "ontology_version": "v1",
        "freshness": "current",
    }
    assert sync_kwargs["replay_source_run_id"] == "exact-generation"
    pointer_store = sync_kwargs["exposure_pointer_store"]
    assert isinstance(pointer_store, OneLakeDocumentStore)
    assert pointer_store.root == str(service.registry.root)
    started = [event["stage"] for event in events if event["status"] == "started"]
    assert started == ["activation", "fabric_publication", "metadata_prefetch"]
    assert not {
        "connection_validation",
        "connection_discovery",
        "combined_snapshot",
    } & set(started)


def test_activate_runtime_reverifies_exact_generation_before_sync(
    tmp_path,
    monkeypatch,
) -> None:
    source_root = tmp_path / "combined"
    store = DatasetStore(source_root)
    store.publish(
        {
            "entities/Resource": [
                {
                    "id": "historical-resource",
                    "observed_at": "2026-09-10T00:00:00Z",
                }
            ]
        },
        {},
        {
            "runId": "exact-generation",
            "status": "completed",
            "sourceConnectionIds": ["hub"],
            "sourceRunIds": ["run-hub"],
            "queryVersion": "combined-subscription-connections-v1",
        },
        ontology={},
    )
    service = _Service({})
    service.registry.root = tmp_path / "registry"
    config = type("Config", (), {"source_data_root": source_root})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )

    generation = store.generation_path("exact-generation")
    assert isinstance(generation, type(tmp_path))
    dataset_path = generation / "entities" / "Resource.jsonl"

    class FabricService:
        def sync(self, **_kwargs):
            pytest.fail("second verification must fail before Fabric sync")

    runtime = type(
        "Runtime",
        (),
        {
            "service": FabricService(),
            "semantic_engine": lambda self: None,
        },
    )()

    def build_runtime_and_tamper(_config, **_kwargs):
        row = json.loads(dataset_path.read_text())
        row["observed_at"] = "2026-09-10T00:01:00Z"
        dataset_path.write_text(json.dumps(row) + "\n")
        return runtime

    monkeypatch.setattr("fabric.runtime.build_runtime", build_runtime_and_tamper)

    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="fabric.test.yaml",
            replay_source_run_id="exact-generation",
            heartbeat_interval=3600,
        )

    assert captured.value.stage == "fabric_publication"
    assert not (tmp_path / "registry").exists()


def test_activate_runtime_config_load_failure_is_combined_snapshot_failure(
    tmp_path,
    monkeypatch,
) -> None:
    service = _Service({"hub": tmp_path / "hub"})
    events: list[dict[str, object]] = []
    secret = "credential=planted-secret"

    def fail_config_load(_path):
        raise RuntimeError(secret)

    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(fail_config_load),
    )

    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="missing-fabric.yaml",
            progress_callback=events.append,
            heartbeat_interval=3600,
        )

    failure = captured.value
    assert failure.stage == "combined_snapshot"
    assert (events[-2]["stage"], events[-2]["status"]) == (
        "combined_snapshot",
        "started",
    )
    assert events[-1] == {
        "event": "activation_progress",
        "stage": "combined_snapshot",
        "status": "failed",
        "elapsed_seconds": failure.elapsed_seconds,
        "error_code": "ACTIVATION_FAILED",
    }
    assert secret not in json.dumps(events) + str(failure)


@pytest.mark.parametrize(
    "manifest_body",
    [
        None,
        "{not-json",
        '["not", "an", "object"]',
        '{"runId":"exact-generation","sourceConnectionIds":"hub"}',
    ],
)
def test_activate_runtime_replay_refuses_unreadable_or_malformed_manifest(
    tmp_path,
    monkeypatch,
    manifest_body: str | None,
) -> None:
    source_root = tmp_path / "combined"
    DatasetStore(source_root).publish(
        {"entities/Resource": [{"id": "historical-resource"}]},
        {},
        {
            "runId": "exact-generation",
            "status": "completed",
            "sourceConnectionIds": ["hub"],
            "sourceRunIds": ["run-hub"],
            "queryVersion": "combined-subscription-connections-v1",
        },
        ontology={},
    )
    generation = DatasetStore(source_root).generation_path("exact-generation")
    assert generation is not None
    manifest_path = generation / "manifest.json"
    if manifest_body is None:
        manifest_path.unlink()
    else:
        manifest_path.write_text(manifest_body)
    service = _Service({})
    service.registry.root = tmp_path / "registry"
    config = type("Config", (), {"source_data_root": source_root})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )

    def unexpected_publication(*_args, **_kwargs):
        pytest.fail("invalid replay input must fail before Fabric publication")

    monkeypatch.setattr("fabric.runtime.build_runtime", unexpected_publication)

    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="fabric.test.yaml",
            replay_source_run_id="exact-generation",
            heartbeat_interval=3600,
        )

    assert captured.value.stage == "activation"
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_dataset",
        "malformed_dataset",
        "altered_dataset_row",
        "missing_ontology",
        "invalid_ontology",
        "wrong_row_count",
        "wrong_content_hash",
        "wrong_ontology_row_count",
        "wrong_ontology_content_hash",
        "wrong_overall_hash",
        "incomplete_status",
        "wrong_run_id",
        "missing_query_version",
        "wrong_query_version",
        "wrong_type_query_version",
        "missing_source_connection_ids",
        "wrong_type_source_connection_ids",
        "empty_source_connection_ids",
        "invalid_source_connection_ids",
        "non_string_source_connection_id",
        "duplicate_source_connection_ids",
        "missing_source_run_ids",
        "wrong_type_source_run_ids",
        "empty_source_run_ids",
        "blank_source_run_id",
        "non_string_source_run_id",
        "duplicate_source_run_ids",
        "mismatched_source_provenance_cardinality",
        "altered_source_connection_ids",
        "altered_source_run_ids",
        "altered_started_at",
        "altered_completed_at",
        "altered_subscription_scope",
        "altered_observed_at",
        "altered_ingested_at",
        "altered_row_run_id",
        "altered_last_observed_timestamp",
        "legacy_no_integrity_contract",
        "invalid_dataset_name",
    ],
)
def test_activate_runtime_replay_refuses_corrupt_generation_before_runtime(
    tmp_path,
    monkeypatch,
    corruption: str,
) -> None:
    source_root = tmp_path / "combined"
    store = DatasetStore(source_root)
    store.publish(
        {
            "entities/Resource": [
                {
                    "id": "historical-resource",
                    "observed_at": "2026-09-09T00:00:00Z",
                    "ingested_at": "2026-09-09T00:01:00Z",
                    "run_id": "source-run-original",
                    "lastObservedTimestamp": "2026-09-09T00:02:00Z",
                }
            ]
        },
        {},
        {
            "runId": "exact-generation",
            "status": "completed",
            "startedAt": "2026-09-09T00:00:00Z",
            "completedAt": "2026-09-09T00:05:00Z",
            "sourceConnectionIds": ["hub", "spoke"],
            "sourceRunIds": ["run-hub", "run-spoke"],
            "subscriptionScope": {
                "subscriptionIds": ["subscription-hub", "subscription-spoke"]
            },
            "queryVersion": "combined-subscription-connections-v1",
        },
        ontology={"version": "v1"},
    )
    generation = store.generation_path("exact-generation")
    assert isinstance(generation, type(tmp_path))
    manifest_path = generation / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    dataset_path = generation / "entities" / "Resource.jsonl"
    ontology_path = generation / "ontology" / "ontology.json"

    if corruption == "missing_dataset":
        dataset_path.unlink()
    elif corruption == "malformed_dataset":
        dataset_path.write_text("{not-json\n")
    elif corruption == "altered_dataset_row":
        dataset_path.write_text('{"id":"tampered-resource"}\n')
    elif corruption == "missing_ontology":
        ontology_path.unlink()
    elif corruption == "invalid_ontology":
        ontology_path.write_text("[]\n")
    elif corruption == "wrong_row_count":
        manifest["datasets"]["entities/Resource"]["rowCount"] = 2
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_content_hash":
        manifest["datasets"]["entities/Resource"]["contentHash"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_ontology_row_count":
        manifest["datasets"]["ontology/ontology"]["rowCount"] = 0
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_ontology_content_hash":
        manifest["datasets"]["ontology/ontology"]["contentHash"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_overall_hash":
        manifest["contentHash"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "incomplete_status":
        manifest["status"] = "started"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_run_id":
        manifest["runId"] = "different-generation"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "missing_query_version":
        del manifest["queryVersion"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_query_version":
        manifest["queryVersion"] = "per-connection-discovery-v1"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_type_query_version":
        manifest["queryVersion"] = ["combined-subscription-connections-v1"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "missing_source_connection_ids":
        del manifest["sourceConnectionIds"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_type_source_connection_ids":
        manifest["sourceConnectionIds"] = "hub"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "empty_source_connection_ids":
        manifest["sourceConnectionIds"] = []
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "invalid_source_connection_ids":
        manifest["sourceConnectionIds"] = [" "]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "non_string_source_connection_id":
        manifest["sourceConnectionIds"] = ["hub", 7]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "duplicate_source_connection_ids":
        manifest["sourceConnectionIds"] = ["hub", "hub"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "missing_source_run_ids":
        del manifest["sourceRunIds"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "wrong_type_source_run_ids":
        manifest["sourceRunIds"] = "run-hub"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "empty_source_run_ids":
        manifest["sourceRunIds"] = []
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "blank_source_run_id":
        manifest["sourceRunIds"] = ["run-hub", " "]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "non_string_source_run_id":
        manifest["sourceRunIds"] = ["run-hub", 7]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "duplicate_source_run_ids":
        manifest["sourceRunIds"] = ["run-hub", "run-hub"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "mismatched_source_provenance_cardinality":
        manifest["sourceRunIds"] = ["run-hub"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "altered_source_connection_ids":
        manifest["sourceConnectionIds"] = ["hub", "other-spoke"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "altered_source_run_ids":
        manifest["sourceRunIds"] = ["run-hub", "run-other-spoke"]
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "altered_started_at":
        manifest["startedAt"] = "2026-09-09T00:00:01Z"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "altered_completed_at":
        manifest["completedAt"] = "2026-09-09T00:05:01Z"
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "altered_subscription_scope":
        manifest["subscriptionScope"] = {
            "subscriptionIds": ["subscription-hub", "subscription-other-spoke"]
        }
        manifest_path.write_text(json.dumps(manifest))
    elif corruption in {
        "altered_observed_at",
        "altered_ingested_at",
        "altered_row_run_id",
        "altered_last_observed_timestamp",
    }:
        row = json.loads(dataset_path.read_text())
        field = {
            "altered_observed_at": "observed_at",
            "altered_ingested_at": "ingested_at",
            "altered_row_run_id": "run_id",
            "altered_last_observed_timestamp": "lastObservedTimestamp",
        }[corruption]
        row[field] = f"tampered-{field}"
        dataset_path.write_text(json.dumps(row) + "\n")
    elif corruption == "legacy_no_integrity_contract":
        manifest.pop("integrityHash", None)
        for details in manifest["datasets"].values():
            details.pop("integrityHash", None)
        manifest_path.write_text(json.dumps(manifest))
    elif corruption == "invalid_dataset_name":
        manifest["datasets"]["../escape"] = {
            "rowCount": 0,
            "contentHash": "0" * 64,
            "integrityHash": "0" * 64,
        }
        manifest_path.write_text(json.dumps(manifest))
    else:
        raise AssertionError(f"Unhandled corruption case: {corruption}")

    service = _Service({})
    service.registry.root = tmp_path / "registry"
    config = type("Config", (), {"source_data_root": source_root})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )

    def unexpected_runtime_or_pointer(*_args, **_kwargs):
        pytest.fail(
            "corrupt replay input must fail before runtime or pointer construction"
        )

    monkeypatch.setattr(
        "fabric.runtime.build_runtime",
        unexpected_runtime_or_pointer,
    )
    monkeypatch.setattr(
        "onboarding.activation.OneLakeDocumentStore",
        unexpected_runtime_or_pointer,
    )

    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="fabric.test.yaml",
            replay_source_run_id="exact-generation",
            heartbeat_interval=3600,
        )

    assert captured.value.stage == "activation"
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize(
    "replay_source_run_id",
    ["missing-generation", "../current"],
)
def test_activate_runtime_replay_refuses_missing_or_unsafe_exact_generation(
    tmp_path,
    monkeypatch,
    replay_source_run_id: str,
) -> None:
    source_root = tmp_path / "combined"
    DatasetStore(source_root)
    service = _Service({})
    service.registry.root = tmp_path / "registry"
    config = type("Config", (), {"source_data_root": source_root})()
    monkeypatch.setattr(
        "fabric.config.FabricRuntimeConfig.load",
        staticmethod(lambda _path: config),
    )

    def unexpected_publication(*_args, **_kwargs):
        pytest.fail("missing replay input must fail before Fabric publication")

    monkeypatch.setattr("fabric.runtime.build_runtime", unexpected_publication)

    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="fabric.test.yaml",
            replay_source_run_id=replay_source_run_id,
            heartbeat_interval=3600,
        )

    assert captured.value.stage == "activation"
    assert not (tmp_path / "registry").exists()


def test_activate_runtime_failure_uses_same_sanitized_elapsed_value(
    tmp_path,
) -> None:
    service = _Service({"hub": tmp_path / "hub"})
    secret = "credential=planted-secret"
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/x/y"
    events: list[dict[str, object]] = []
    ticks = iter(range(20))

    def fail_validation(_connection_id: str):
        raise RuntimeError(f"{secret} {resource_id}")

    service.validate = fail_validation
    with pytest.raises(ActivationFailure) as captured:
        activate_runtime(
            service,
            fabric_config="unused.yaml",
            progress_callback=events.append,
            heartbeat_interval=3600,
            progress_clock=lambda: float(next(ticks)),
        )

    failure = captured.value
    terminal_event = events[-1]
    assert terminal_event == {
        "event": "activation_progress",
        "stage": "connection_validation",
        "status": "failed",
        "elapsed_seconds": failure.elapsed_seconds,
        "error_code": "ACTIVATION_FAILED",
    }
    rendered = json.dumps(events) + str(failure)
    assert secret not in rendered
    assert resource_id not in rendered
