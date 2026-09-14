"""Production discovery aggregation and Fabric activation workflow."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from onboarding.ontology_metadata import generate_ontology_metadata
from onboarding.service import SubscriptionOnboardingService
from storage.datasets import COMBINED_ACTIVATION_QUERY_VERSION, DatasetStore
from storage.onelake_documents import OneLakeDocumentStore

from .graph_normalize import ENTITY_TYPES, NormalizedGraph

if TYPE_CHECKING:
    from fabric.sync_service import FabricTableWriteProgress

_LOGGER = logging.getLogger(__name__)
_MAX_PROGRESS_COUNT = 2_147_483_647
_PROGRESS_STATUSES = frozenset({"started", "heartbeat", "completed", "failed"})
_COMPLETION_FIELDS: dict[str, frozenset[str]] = {
    "connection_validation": frozenset({"completed", "total"}),
    "connection_discovery": frozenset({"completed", "total"}),
    "combined_snapshot": frozenset({"dataset_count", "failure_count"}),
    "dataset_mapping": frozenset({"dataset_count", "failure_count"}),
    "workload_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "temporal_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "temporal_retained_load": frozenset({"row_count", "failure_count"}),
    "temporal_legacy_normalization": frozenset({"row_count", "failure_count"}),
    "temporal_observation_combination": frozenset({"row_count", "failure_count"}),
    "temporal_current_projection": frozenset({"row_count", "failure_count"}),
    "temporal_immutable_checks": frozenset({"row_count", "failure_count"}),
    "container_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "ontology_construction": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "ontology_validation": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "table_publication": frozenset(    {
        "table_name",
        "row_count",
        "completed",
        "total",
        "remaining_tables",
        "resumed_tables",
        "skipped_tables",
        "checkpoint_id",
        "checkpoint_state",
        "publication_id",
        "current_phase",
    }),
    "fabric_asset_registration": frozenset(),
    "ontology_publication": frozenset(),
    "gold_staging": frozenset(),
    "shortcut_finalization": frozenset(),
    "pointer_activation": frozenset(),
    "checkpoint_persistence": frozenset(
        {
            "dataset_count",
            "failure_count",
            "checkpoint_rows_written",
            "checkpoint_bytes_written",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        }
    ),
    "checkpoint_restore": frozenset(
        {
            "dataset_count",
            "failure_count",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        }
    ),
    "publication_resume": frozenset(
        {
            "completed",
            "total",
            "remaining_tables",
            "resumed_tables",
            "skipped_tables",
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        }
    ),
    "checkpoint_finalization": frozenset(
        {
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        }
    ),
    "checkpoint_activation_pending": frozenset(
        {
            "checkpoint_id",
            "checkpoint_state",
            "publication_id",
            "current_phase",
        }
    ),
    "fabric_publication": frozenset(),
    "metadata_prefetch": frozenset(
        {"requested_count", "succeeded_count", "failure_count"}
    ),
    "activation": frozenset(),
}
_COUNT_FIELDS = frozenset(
    {
        "completed",
        "total",
        "row_count",
        "dataset_count",
        "entity_count",
        "relationship_count",
        "failure_count",
        "remaining_tables",
        "resumed_tables",
        "skipped_tables",
        "checkpoint_rows_written",
        "checkpoint_bytes_written",
        "requested_count",
        "succeeded_count",
    }
)
_SAFE_ERROR_CODES = frozenset({"ACTIVATION_FAILED"})
_TABLE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_EXPOSURE_PASSTHROUGH_KEYS = {
    "exposure/source_partition_rows": "row_key",
    "exposure/workload_observations": "observation_id",
    "exposure/workload_deployments": "deployment_id",
    "exposure/workload_source_checkpoints": "checkpoint_key",
    "situations/source_status": "partition_key",
}


class _CombinedSnapshotSource(Protocol):
    registry: Any
    sync_coordinator: Any


class ActivationFailure(RuntimeError):
    """Expose only a safe activation stage, code, and elapsed duration.

    The originating exception remains available through normal exception
    chaining for in-process diagnosis. Its text is deliberately excluded from
    this exception so CLI and progress output cannot disclose provider data.
    """

    def __init__(
        self,
        *,
        stage: str,
        error_code: str,
        elapsed_seconds: float,
    ) -> None:
        """Initialize a sanitized failure using elapsed seconds."""
        super().__init__("Activation failed")
        self.stage = stage
        self.error_code = error_code
        self.elapsed_seconds = elapsed_seconds


def build_activation_progress_event(
    stage: str,
    status: str,
    *,
    elapsed_seconds: float,
    **payload: object,
) -> dict[str, object]:
    """Build one exact-schema, low-cardinality activation progress event.

    Completion payloads are fixed per stage. Counts are non-boolean integers
    in the inclusive range 0..2,147,483,647, table names are bounded logical
    names, checkpoint/publication IDs are opaque SHA-256 values, and failed
    events contain only ``error_code``. Elapsed time is in monotonic seconds.
    """
    if stage not in _COMPLETION_FIELDS:
        raise ValueError("Unknown activation progress stage")
    if status not in _PROGRESS_STATUSES:
        raise ValueError("Unknown activation progress status")
    if (
        isinstance(elapsed_seconds, bool)
        or not isinstance(elapsed_seconds, (int, float))
        or not math.isfinite(float(elapsed_seconds))
        or float(elapsed_seconds) < 0
    ):
        raise ValueError("elapsed_seconds must be finite and non-negative")

    expected_fields = (
        _COMPLETION_FIELDS[stage]
        if status == "completed"
        else frozenset({"error_code"})
        if status == "failed"
        else frozenset()
    )
    if frozenset(payload) != expected_fields:
        raise ValueError("Progress payload does not match stage and status")
    for field in _COUNT_FIELDS & payload.keys():
        value = payload[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= _MAX_PROGRESS_COUNT
        ):
            raise ValueError(f"{field} must be a bounded non-negative integer")
    if "table_name" in payload:
        table_name = payload["table_name"]
        if not isinstance(table_name, str) or not _TABLE_NAME_PATTERN.fullmatch(
            table_name
        ):
            raise ValueError("table_name must be a bounded logical table name")
    for field in ("checkpoint_id", "publication_id"):
        value = payload.get(field)
        if value not in (None, "") and (
            not isinstance(value, str)
            or not re.fullmatch(r"[0-9a-f]{64}", value)
        ):
            raise ValueError(f"{field} must be an opaque SHA-256 identifier")
    if "checkpoint_state" in payload and payload["checkpoint_state"] not in {
        "",
        "persisted",
        "restored",
        "activation_pending",
        "finalized",
    }:
        raise ValueError("checkpoint_state is invalid")
    if "current_phase" in payload and payload["current_phase"] not in {
        "checkpoint_persistence",
        "checkpoint_restore",
        "checkpoint_finalization",
        "table_publication",
        "gold_staging",
        "pointer_activation",
    }:
        raise ValueError("current_phase is invalid")
    if "error_code" in payload and payload["error_code"] not in _SAFE_ERROR_CODES:
        raise ValueError("error_code is not allowlisted")
    return {
        "event": "activation_progress",
        "stage": stage,
        "status": status,
        "elapsed_seconds": float(elapsed_seconds),
        **payload,
    }


class ActivationProgressReporter:
    """Emit exact activation progress with one bounded heartbeat worker.

    The sink is best-effort: callback exceptions are replaced by a fixed safe
    log record and never change activation outcomes. Stage completion payloads
    follow :func:`build_activation_progress_event`; elapsed values and the
    positive heartbeat interval are expressed in monotonic seconds.
    """

    def __init__(
        self,
        sink: Callable[[Mapping[str, object]], None] | None,
        *,
        heartbeat_interval: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[threading.Event, float], bool] | None = None,
    ) -> None:
        """Initialize the reporter with injectable monotonic clock and wait."""
        if (
            isinstance(heartbeat_interval, bool)
            or not isinstance(heartbeat_interval, (int, float))
            or not math.isfinite(float(heartbeat_interval))
            or heartbeat_interval <= 0
        ):
            raise ValueError("heartbeat_interval must be finite and positive")
        self._sink = sink
        self._heartbeat_interval = float(heartbeat_interval)
        self._clock = clock
        self._wait = wait or (lambda stop, interval: stop.wait(interval))
        self._lock = threading.RLock()
        self._reporter_started = self._clock()
        self._stage_started: dict[str, float] = {}
        self._current_stage: str | None = None
        self._heartbeat_stop: threading.Event | None = None
        self._heartbeat_worker: threading.Thread | None = None
        self._closed = False

    @property
    def current_stage(self) -> str:
        """Return the active safe stage name, falling back to activation."""
        with self._lock:
            return self._current_stage or "activation"

    @property
    def heartbeat_thread_alive(self) -> bool:
        """Return whether the current daemon heartbeat worker is alive."""
        with self._lock:
            worker = self._heartbeat_worker
        return bool(worker and worker.is_alive())

    def elapsed(self, stage: str | None = None) -> float:
        """Return non-negative monotonic seconds for a stage or whole run."""
        with self._lock:
            started = self._stage_started.get(stage or "", self._reporter_started)
        return max(0.0, float(self._clock() - started))

    def start(self, stage: str) -> None:
        """Start an allowlisted stage and its bounded heartbeat lifecycle."""
        if stage not in _COMPLETION_FIELDS:
            raise ValueError("Unknown activation progress stage")
        self._stop_heartbeat()
        with self._lock:
            if self._closed:
                return
            started = self._clock()
            self._stage_started[stage] = started
            self._current_stage = stage
            stop = threading.Event()
            worker = threading.Thread(
                target=self._heartbeat_loop,
                args=(stage, started, stop),
                name=f"activation-progress-{stage}",
                daemon=True,
            )
            self._heartbeat_stop = stop
            self._heartbeat_worker = worker
        self._emit(stage, "started", elapsed_seconds=0.0)
        worker.start()

    def complete(self, stage: str, **payload: object) -> None:
        """Complete a stage using its exact allowlisted aggregate payload."""
        self._stop_heartbeat(stage)
        self._emit(stage, "completed", elapsed_seconds=self.elapsed(stage), **payload)
        with self._lock:
            self._stage_started.pop(stage, None)
            if self._current_stage == stage:
                self._current_stage = None

    def fail(
        self,
        stage: str,
        *,
        error_code: str = "ACTIVATION_FAILED",
    ) -> float:
        """Fail a stage and return its sanitized monotonic elapsed seconds."""
        self._stop_heartbeat()
        elapsed_seconds = self.elapsed(stage)
        self._emit(
            stage,
            "failed",
            elapsed_seconds=elapsed_seconds,
            error_code=error_code,
        )
        return elapsed_seconds

    def fabric_table_progress(self, progress: FabricTableWriteProgress) -> None:
        """Translate an existing FabricTableWriteProgress after a successful write."""
        self._emit(
            "table_publication",
            "completed",
            elapsed_seconds=self.elapsed("table_publication"),
            table_name=progress.table_name,
            row_count=progress.result.rows_processed,
            completed=progress.completed_tables,
            total=progress.total_tables,
            remaining_tables=progress.remaining_tables,
            resumed_tables=progress.resumed_tables,
            skipped_tables=progress.skipped_tables,
            checkpoint_id=progress.checkpoint_id,
            checkpoint_state=progress.checkpoint_state,
            publication_id=progress.checkpoint_id,
            current_phase=progress.current_phase,
        )

    def fabric_stage_progress(self, progress: Mapping[str, object]) -> None:
        """Consume a typed Fabric stage mapping through the shared event schema."""
        stage = progress.get("stage")
        status = progress.get("status")
        if not isinstance(stage, str) or not isinstance(status, str):
            return
        payload = {
            key: value
            for key, value in progress.items()
            if key not in {"stage", "status"}
        }
        try:
            if status == "started":
                self.start(stage)
            elif status == "completed":
                self.complete(stage, **payload)
            elif status == "failed":
                self.fail(stage, error_code=str(payload.get("error_code") or ""))
        except (TypeError, ValueError):
            # Invalid producer telemetry is ignored so observability cannot
            # alter a successful publication.
            return

    def close(self) -> None:
        """Stop and join the heartbeat worker without emitting another event."""
        with self._lock:
            self._closed = True
        self._stop_heartbeat()

    def _emit(
        self,
        stage: str,
        status: str,
        *,
        elapsed_seconds: float,
        **payload: object,
    ) -> None:
        try:
            event = build_activation_progress_event(
                stage,
                status,
                elapsed_seconds=elapsed_seconds,
                **payload,
            )
        except (TypeError, ValueError):
            return
        if self._sink is None:
            return
        try:
            self._sink(event)
        except Exception:  # noqa: BLE001 - observability must remain best-effort.
            _LOGGER.warning(
                "activation_progress_callback_failed",
                extra={"error_code": "ACTIVATION_PROGRESS_CALLBACK_FAILED"},
            )

    def _heartbeat_loop(
        self,
        stage: str,
        started: float,
        stop: threading.Event,
    ) -> None:
        while not self._wait(stop, self._heartbeat_interval):
            with self._lock:
                if self._closed or self._current_stage != stage or stop.is_set():
                    return
            self._emit(
                stage,
                "heartbeat",
                elapsed_seconds=max(0.0, self._clock() - started),
            )

    def _stop_heartbeat(self, stage: str | None = None) -> None:
        with self._lock:
            if stage is not None and self._current_stage != stage:
                return
            stop = self._heartbeat_stop
            worker = self._heartbeat_worker
            self._heartbeat_stop = None
            self._heartbeat_worker = None
        if stop is not None:
            stop.set()
        if worker is not None and worker is not threading.current_thread():
            worker.join()


def publish_combined_snapshot(
    service: _CombinedSnapshotSource,
    connection_ids: list[str],
    target_root: str | Path,
    *,
    reuse_unchanged: bool = False,
) -> dict[str, Any]:
    """Publish one isolated, deduplicated snapshot from synced connections.

    Full activation intentionally creates a new combined generation by
    default so code-only mapper and projection changes are republished.
    Dedicated readers may opt into source-run reuse when downstream work is
    independently generation-aware.
    """
    if not connection_ids:
        raise ValueError("At least one subscription connection is required")
    entities: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in ENTITY_TYPES}
    relationships: dict[str, dict[str, Any]] = {}
    changes: dict[str, dict[str, Any]] = {}
    exposure_rows: dict[str, dict[str, dict[str, Any]]] = {
        name: {} for name in _EXPOSURE_PASSTHROUGH_KEYS
    }
    source_runs: list[str] = []
    latest_started_at = ""

    for connection_id in connection_ids:
        connection = service.registry.get(connection_id)
        root = service.sync_coordinator.connection_output_dir(connection)
        store = DatasetStore(root)
        generation = store.current_generation()
        if generation is None:
            raise ValueError(
                f"Connection '{connection_id}' has no successful discovery snapshot"
            )
        manifest = _read_manifest(store, generation)
        source_runs.append(str(manifest.get("runId") or connection_id))
        latest_started_at = max(latest_started_at, str(manifest.get("startedAt") or ""))
        datasets = manifest.get("datasets") or {}
        for dataset_name in datasets:
            if dataset_name.startswith("entities/"):
                entity_type = dataset_name.split("/", 1)[1]
                if entity_type not in entities:
                    continue
                for row in store.read_dataset(dataset_name):
                    identifier = str(row.get("id") or "")
                    if identifier:
                        existing = entities[entity_type].get(identifier)
                        existing_connection = str(
                            (existing or {}).get("connection_id") or ""
                        )
                        incoming_connection = str(row.get("connection_id") or "")
                        if (
                            existing is not None
                            and existing_connection
                            and incoming_connection
                            and existing_connection != incoming_connection
                        ):
                            raise ValueError(
                                "Discovery entity identity collision across "
                                f"connections: {entity_type} '{identifier}' is "
                                f"present in both '{existing_connection}' and "
                                f"'{incoming_connection}'"
                            )
                        entities[entity_type][identifier] = row
            elif dataset_name == "relationships/relationships":
                for row in store.read_dataset(dataset_name):
                    identifier = str(row.get("relationshipId") or "")
                    if identifier:
                        relationships[identifier] = row
            elif dataset_name == "changes/resource_changes":
                for row in store.read_dataset(dataset_name):
                    identifier = "|".join(
                        str(row.get(key) or "")
                        for key in ("id", "changeId", "timestamp", "connection_id")
                    )
                    changes[identifier] = row
            elif dataset_name in exposure_rows:
                key_field = _EXPOSURE_PASSTHROUGH_KEYS[dataset_name]
                for row in store.read_dataset(dataset_name):
                    identifier = "|".join(
                        (
                            str(row.get("connection_id") or connection_id),
                            str(row.get("workspace_id") or ""),
                            str(row.get("partition_key") or ""),
                            str(row.get("query_name") or ""),
                            str(row.get(key_field) or ""),
                        )
                    )
                    if not str(row.get(key_field) or ""):
                        identifier = hashlib.sha256(
                            json.dumps(
                                row,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()
                    exposure_rows[dataset_name][identifier] = row

    graph = NormalizedGraph(
        entities={
            name: sorted(rows.values(), key=lambda row: str(row.get("id") or ""))
            for name, rows in entities.items()
        },
        relationships=sorted(
            relationships.values(),
            key=lambda row: str(row.get("relationshipId") or ""),
        ),
        changes=sorted(
            changes.values(),
            key=lambda row: (
                str(row.get("timestamp") or ""),
                str(row.get("id") or ""),
            ),
        ),
    )
    target_store = DatasetStore(target_root)
    current_generation = target_store.current_generation()
    if reuse_unchanged and current_generation is not None:
        current_manifest = _read_manifest(target_store, current_generation)
        if (
            str(current_manifest.get("status") or "").casefold()
            == "completed"
            and current_manifest.get("sourceConnectionIds")
            == sorted(connection_ids)
            and current_manifest.get("sourceRunIds")
            == sorted(source_runs)
        ):
            return current_manifest
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = f"activation-{uuid.uuid4()}"
    datasets = {
        **{
            f"entities/{entity_type}": rows
            for entity_type, rows in graph.entities.items()
        },
        "relationships/relationships": graph.relationships,
        "changes/resource_changes": graph.changes,
        **{
            name: [rows[key] for key in sorted(rows)]
            for name, rows in exposure_rows.items()
        },
    }
    return target_store.publish(
        datasets,
        {},
        {
            "runId": run_id,
            "status": "completed",
            "startedAt": latest_started_at or now,
            "completedAt": now,
            "queryVersion": COMBINED_ACTIVATION_QUERY_VERSION,
            "sourceConnectionIds": sorted(connection_ids),
            "sourceRunIds": sorted(source_runs),
        },
        ontology=generate_ontology_metadata(graph.entities),
    )


def activate_runtime(
    service: SubscriptionOnboardingService,
    *,
    fabric_config: str | Path,
    connection_ids: list[str] | None = None,
    replay_source_run_id: str = "",
    progress_callback: Callable[[Mapping[str, object]], None] | None = None,
    heartbeat_interval: float = 60.0,
    progress_clock: Callable[[], float] = time.monotonic,
    progress_wait: Callable[[threading.Event, float], bool] | None = None,
    metadata_prefetch: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Validate, discover, publish, and verify a production Fabric snapshot.

    Progress callbacks are best-effort and receive exact-schema mappings.
    Heartbeat and elapsed values use monotonic seconds; injectable clock/wait
    seams support deterministic local tests. Metadata prefetch begins only
    after Fabric publication releases its ingestion lock; its sanitized
    partial or failed result never rolls back a successful publication.
    """
    reporter = ActivationProgressReporter(
        progress_callback,
        heartbeat_interval=heartbeat_interval,
        clock=progress_clock,
        wait=progress_wait,
    )
    reporter.start("activation")
    try:
        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import FabricRuntimeMode, build_runtime

        exact_generation = str(replay_source_run_id)
        source_store: DatasetStore | None = None
        if exact_generation:
            config = FabricRuntimeConfig.load(fabric_config)
            source_store = DatasetStore(config.source_data_root)
            combined = source_store.verify_combined_activation_generation(
                exact_generation
            )
            selected = sorted(combined["sourceConnectionIds"])
            validations: dict[str, Any] = {}
            syncs: dict[str, Any] = {}
        else:
            selected = connection_ids or [
                connection.connection_id
                for connection in service.registry.list(include_disabled=False)
            ]
            if not selected:
                raise ValueError("No active subscription connections are registered")

            validations = {}
            syncs = {}
            total_connections = len(selected)
            for position, connection_id in enumerate(selected, start=1):
                reporter.start("connection_validation")
                validation = service.validate(connection_id)
                validations[connection_id] = validation
                if not validation.get("passed"):
                    raise ValueError("Connection failed SPN access validation")
                reporter.complete(
                    "connection_validation",
                    completed=position,
                    total=total_connections,
                )

                reporter.start("connection_discovery")
                sync = service.sync(connection_id, mode="manual")
                syncs[connection_id] = sync
                if sync.get("status") != "succeeded":
                    raise RuntimeError("Connection discovery failed")
                reporter.complete(
                    "connection_discovery",
                    completed=position,
                    total=total_connections,
                )

            reporter.start("combined_snapshot")
            config = FabricRuntimeConfig.load(fabric_config)
            combined = publish_combined_snapshot(
                service,
                selected,
                config.source_data_root,
            )
            reporter.complete(
                "combined_snapshot",
                dataset_count=len(combined.get("datasets") or {}),
                failure_count=0,
            )

        reporter.start("fabric_publication")
        runtime = build_runtime(config, mode=FabricRuntimeMode.PUBLISH)
        if source_store is not None:
            # Recheck the exact immutable input after runtime construction and
            # immediately before Fabric mapping. Remote DatasetStore publish
            # never deletes generations, so normal publication cannot
            # invalidate this verified path while the replay transaction runs.
            combined = source_store.verify_combined_activation_generation(
                exact_generation
            )
        exposure_pointer_store = OneLakeDocumentStore(service.registry.root)
        publication = runtime.service.sync(
            replay_source_run_id=exact_generation or str(combined["runId"]),
            progress_callback=reporter.fabric_table_progress,
            stage_progress_callback=reporter.fabric_stage_progress,
            exposure_pointer_store=exposure_pointer_store,
        )
        reporter.complete("fabric_publication")

        reporter.start("metadata_prefetch")
        prefetch_result = _run_metadata_prefetch(
            metadata_prefetch,
            source_root=config.source_data_root,
            generation_id=exact_generation or str(combined["runId"]),
            runtime=runtime,
            pointer_store=exposure_pointer_store,
        )
        reporter.complete(
            "metadata_prefetch",
            requested_count=prefetch_result["requested_count"],
            succeeded_count=prefetch_result["succeeded_count"],
            failure_count=prefetch_result["failure_count"],
        )

        semantic = runtime.semantic_engine()
        result = {
            "status": "activated",
            "connections": sorted(selected),
            "validations": validations,
            "discovery_syncs": syncs,
            "combined_snapshot": combined,
            "fabric_publication": {
                "run_id": publication.run_id,
                "source_run_id": publication.source_run_id,
                "status": publication.status,
                "tables": list(publication.tables),
            },
            "metadata_prefetch": prefetch_result,
            "ontology_version": semantic.knowledge_version,
            "freshness": semantic.freshness,
        }
        reporter.complete("activation")
        return result
    except Exception as exc:
        stage = reporter.current_stage
        elapsed_seconds = reporter.fail(stage)
        raise ActivationFailure(
            stage=stage,
            error_code="ACTIVATION_FAILED",
            elapsed_seconds=elapsed_seconds,
        ) from exc
    finally:
        reporter.close()


def _run_metadata_prefetch(
    prefetch: Callable[..., Mapping[str, object]] | None,
    *,
    source_root: str | Path,
    generation_id: str,
    runtime: Any,
    pointer_store: OneLakeDocumentStore,
) -> dict[str, object]:
    """Invoke the shared prefetch seam and return only bounded safe fields."""

    try:
        raw = (
            prefetch(source_root=source_root, generation_id=generation_id)
            if prefetch is not None
            else _shared_metadata_prefetch(
                runtime=runtime,
                pointer_store=pointer_store,
            )
        )
        return _sanitize_prefetch_result(raw)
    except Exception:  # noqa: BLE001 - provider failures cannot roll back publication.
        _LOGGER.warning(
            "activation_metadata_prefetch_failed",
            extra={"error_code": "METADATA_PREFETCH_FAILED"},
        )
        return {
            "status": "failed",
            "requested_count": 0,
            "succeeded_count": 0,
            "failure_count": 1,
        }


def _shared_metadata_prefetch(
    *,
    runtime: Any,
    pointer_store: OneLakeDocumentStore,
) -> Mapping[str, object]:
    """Adapt activation to the separately owned shared prefetch module."""

    from intelligence.vulnerability.enrichment_cache import (
        EXPOSURE_ENRICHMENT_DOCUMENT,
        EnrichmentCache,
    )
    from intelligence.vulnerability.enrichment_worker import EnrichmentWorker
    from intelligence.vulnerability.exposure_prefetch import (
        ExposureGenerationDiscovery,
        ExposurePrefetchService,
    )

    def read_table(
        table_name: str,
        columns: tuple[str, ...],
    ) -> tuple[Mapping[str, Any], ...]:
        layer, logical_name = table_name.split("_", 1)
        uri = runtime.service.onelake.table_uri(layer, logical_name)
        if runtime.service.delta.version(uri) is None:
            return ()
        return tuple(runtime.service.delta.read(uri, columns=columns))

    worker = EnrichmentWorker(
        EnrichmentCache(
            EXPOSURE_ENRICHMENT_DOCUMENT,
            store=pointer_store,
        ),
        max_items=100,
    )
    return ExposurePrefetchService(
        discovery=ExposureGenerationDiscovery(
            pointer_store=pointer_store,
            table_reader=read_table,
        ),
        worker=worker,
        checkpoint_store=pointer_store,
        max_items=100,
    ).run().to_dict()


def _sanitize_prefetch_result(
    result: Mapping[str, object],
) -> dict[str, object]:
    """Reduce a prefetch result to fixed-status bounded aggregate counts."""

    if not isinstance(result, Mapping):
        raise TypeError("Metadata prefetch result must be a mapping")

    def bounded_count(*names: str) -> int:
        for name in names:
            value = result.get(name)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= _MAX_PROGRESS_COUNT
            ):
                return value
        return 0

    failed = bounded_count("failure_count", "failed_count", "failed")
    attempted = bounded_count("attempted_count")
    succeeded = bounded_count("succeeded_count", "refreshed_count", "succeeded")
    if "succeeded_count" not in result and "refreshed_count" not in result:
        succeeded = max(0, attempted - failed)
    requested = max(
        bounded_count(
            "requested_count",
            "selected_count",
            "target_count",
            "requested",
        ),
        succeeded + failed,
    )
    requested = min(requested, _MAX_PROGRESS_COUNT)
    normalized_status = str(result.get("status") or "").strip().casefold()
    status = {
        "complete": "succeeded",
        "completed": "succeeded",
        "success": "succeeded",
        "succeeded": "succeeded",
        "partial": "partial",
        "failed": "failed",
        "unavailable": "unavailable",
    }.get(normalized_status)
    if status is None:
        status = "partial" if failed else "succeeded"
    if failed and succeeded:
        status = "partial"
    elif failed and not succeeded:
        status = "failed"
    return {
        "status": status,
        "requested_count": requested,
        "succeeded_count": succeeded,
        "failure_count": failed,
    }


def _read_manifest(store: DatasetStore, generation: str) -> dict[str, Any]:
    path = f"{generation}/manifest.json"
    try:
        if store.is_remote:
            with store.fs.open(path, "rt") as handle:
                payload = json.loads(handle.read())
        else:
            payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Discovery manifest is unreadable for {generation}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Discovery manifest is invalid for {generation}")
    return payload


__all__ = [
    "ActivationFailure",
    "ActivationProgressReporter",
    "activate_runtime",
    "build_activation_progress_event",
    "publish_combined_snapshot",
]
