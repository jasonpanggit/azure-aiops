from __future__ import annotations

import gc
import inspect
import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import pyarrow as pa

from fabric_pipelines import (
    change_pipeline,
    incident_pipeline,
    predictive_pipeline,
)
from fabric_pipelines.topology_pipeline import derive_edges, to_topology_edge_row
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_TABLES,
    ExposureGoldFabricPublisher,
    materialize_container_exposure_tables,
    materialize_temporal_exposure_tables,
)
from ontology.entity_builder import entity_change_version
from ontology.ontology_sync import OntologyGraphSynchronizer
from ontology.ontology_validator import OntologyValidator
from ontology.publication_manifest import PublicationManifestStore
from ontology.relationship_builder import relationship_change_version
from ontology_discovery.publisher import (
    OntologyGenerationCandidate,
    OntologyGenerationPublisher,
    PublicationSafetyError,
)
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.locking import LeaseLostError
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter
from storage.partitioning import PartitioningPolicy

from .data_quality import DataQualityValidator, QualityReport
from .dataset_mapper import (
    ONTOLOGY_ENTITY_TYPES,
    ONTOLOGY_RELATIONSHIP_TYPES,
    GranularExposureOntologyMapper,
    InventoryDatasetMapper,
    exposure_gold_products_from_datasets,
    filter_legacy_granular_exposure_graph,
    ontology_entity_table,
    ontology_relationship_table,
    remediation_decision_ontology_rows,
    remediation_plan_ontology_rows,
    temporal_products_from_legacy,
)
from .lakehouse_manager import LakehouseManager
from .schema_registry import schema_for
from .telemetry import FabricMetrics

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FabricSyncResult:
    run_id: str
    source_run_id: str
    status: str
    replay: bool
    rows_processed: int
    rows_added: int
    rows_changed: int
    rows_removed: int
    failed_records: int
    tables: tuple[str, ...]
    duration_seconds: float


@dataclass(frozen=True)
class FabricTableWriteProgress:
    """Best-effort notification emitted after a Fabric table write succeeds."""

    completed_tables: int
    total_tables: int
    table_name: str
    result: DeltaWriteResult


class FabricStageProgress(TypedDict, total=False):
    """Best-effort low-cardinality Fabric lifecycle stage notification.

    ``stage`` and ``status`` are always present. Completion events include
    only the aggregate fields assigned to that stage; every count is a
    non-boolean integer in the inclusive range 0..2,147,483,647.
    """

    stage: str
    status: str
    dataset_count: int
    entity_count: int
    relationship_count: int
    failure_count: int


_FABRIC_STAGE_FIELDS: dict[str, frozenset[str]] = {
    "dataset_mapping": frozenset({"dataset_count", "failure_count"}),
    "workload_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "temporal_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "container_projection": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "ontology_construction": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "ontology_validation": frozenset(
        {"entity_count", "relationship_count", "failure_count"}
    ),
    "table_publication": frozenset(),
    "fabric_asset_registration": frozenset(),
    "ontology_publication": frozenset(),
    "gold_staging": frozenset(),
    "shortcut_finalization": frozenset(),
    "pointer_activation": frozenset(),
}
_MAX_PROGRESS_COUNT = 2_147_483_647


def _bounded_progress_count(value: int) -> int:
    return min(max(int(value), 0), _MAX_PROGRESS_COUNT)


def _release_transient_publication_memory() -> None:
    gc.collect()
    pa.default_memory_pool().release_unused()


def _notify_stage_progress(
    callback: Callable[[FabricStageProgress], None] | None,
    stage: str,
    status: str,
    **payload: int,
) -> None:
    if callback is None:
        return
    expected = (
        _FABRIC_STAGE_FIELDS.get(stage)
        if status == "completed"
        else frozenset()
        if status == "started"
        else None
    )
    if expected is None or frozenset(payload) != expected:
        return
    event: FabricStageProgress = {"stage": stage, "status": status}
    event.update(
        {
            field: _bounded_progress_count(value)
            for field, value in payload.items()
        }
    )
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - observability must remain best-effort.
        _LOGGER.warning(
            "fabric_stage_progress_callback_failed",
            extra={"error_code": "FABRIC_STAGE_PROGRESS_CALLBACK_FAILED"},
        )


def _notify_table_progress(
    callback: Callable[[FabricTableWriteProgress], None] | None,
    event: FabricTableWriteProgress,
) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:  # noqa: BLE001 - observability must remain best-effort.
        _LOGGER.warning(
            "fabric_table_progress_callback_failed",
            extra={"error_code": "FABRIC_TABLE_PROGRESS_CALLBACK_FAILED"},
        )


class DedicatedOntologyPublisherAdapter:
    """Keep generation and Fabric writes behind one publisher-only boundary.

    The request factory supplies fencing and pointer preconditions but is
    forbidden from supplying either the candidate or publisher identity.
    Those values are bound by this adapter, so API/coordinator input cannot
    substitute a broader credential.
    """

    def __init__(
        self,
        *,
        generation_publisher: OntologyGenerationPublisher,
        fabric_sync_service: FabricSyncService,
        publisher_identity: str,
        request_factory: Callable[
            [Mapping[str, Any], OntologyGenerationCandidate],
            Mapping[str, Any],
        ],
        status_reader: Callable[[str], Mapping[str, Any]],
    ) -> None:
        identity = str(publisher_identity or "").strip()
        if not identity:
            raise ValueError("publisher_identity must not be empty")
        self._generation_publisher = generation_publisher
        self._fabric_sync_service = fabric_sync_service
        self._publisher_identity = identity
        self._request_factory = request_factory
        self._status_reader = status_reader

    async def publish(
        self,
        *,
        run: Mapping[str, Any],
        candidate: OntologyGenerationCandidate,
    ) -> Mapping[str, Any]:
        if not isinstance(candidate, OntologyGenerationCandidate):
            raise TypeError("candidate must be an OntologyGenerationCandidate")
        request = dict(self._request_factory(run, candidate))
        forbidden = {"candidate", "publisher_identity"} & request.keys()
        if forbidden:
            raise PermissionError(
                "publisher request cannot override candidate or publisher identity"
            )
        try:
            materialization: dict[str, Any] = {}

            def materialize(published: OntologyGenerationCandidate) -> Mapping[str, Any]:
                publication = self._fabric_sync_service.sync(
                    replay_source_run_id=published.source_generation
                )
                materialization.update(
                    run_id=publication.run_id,
                    status=publication.status,
                    tables=list(publication.tables),
                )
                return {
                    "status": publication.status,
                    "run_id": publication.run_id,
                    "tables": list(publication.tables),
                }

            promoted = self._generation_publisher.publish(
                candidate,
                publisher_identity=self._publisher_identity,
                materialize_generation=materialize,
                **request,
            )
        except PublicationSafetyError as exc:
            # If the publisher committed and the coordinator died before its
            # own success checkpoint, immutable restaging is an expected
            # retry.  Only that precise condition may be treated as complete.
            if "immutable" not in str(exc).casefold():
                raise
            durable = await self.publication_status(str(run.get("run_id") or ""))
            if (
                durable.get("run_id") != run.get("run_id")
                or durable.get("active_generation") != candidate.generation_id
            ):
                raise
            promoted = type(
                "_RecoveredPointer",
                (),
                {
                    "pointer": type(
                        "_RecoveredGeneration",
                        (),
                        {"active_generation": candidate.generation_id},
                    )(),
                    "etag": durable.get("pointer_etag"),
                },
            )()

        # Compatibility with protocol doubles that predate the ordered
        # materialization callback. Real OntologyGenerationPublisher instances
        # always invoke the callback before pointer CAS.
        if not materialization:
            materialize(candidate)
        return {
            "generation_id": candidate.generation_id,
            "active_generation": promoted.pointer.active_generation,
            "pointer_etag": promoted.etag,
            "fabric_run_id": materialization["run_id"],
            "fabric_status": materialization["status"],
            "fabric_tables": materialization["tables"],
        }

    async def publication_status(self, run_id: str) -> Mapping[str, Any]:
        status = self._status_reader(run_id)
        if inspect.isawaitable(status):
            status = await status
        if not isinstance(status, Mapping):
            raise TypeError("publisher status reader must return a mapping")
        return dict(status)


class FabricSyncService:
    _MERGE_WRITE_TABLES: frozenset[str] = frozenset({
        "bronze_resource_changes",
        "silver_patch_history",
        "silver_lifecycle_history",
        "silver_defender_secure_scores",
        "silver_change_history",
        "silver_incident_history",
        "silver_predictive_history",
        "silver_cost_actuals",
    })
    # Full-state (current-snapshot) tables keyed by resource_id: rows must
    # disappear once the underlying resource is gone, which plain MERGE can't
    # express, but a full OVERWRITE rewrites the whole table even when only a
    # handful of rows changed. SNAPSHOT_MERGE upserts changed keys and
    # deletes keys absent from this run, giving OVERWRITE's replace semantics
    # at MERGE's cost for the largest, least-churny tables.
    _SNAPSHOT_MERGE_WRITE_TABLES: frozenset[str] = frozenset({
        "bronze_resources",
        "silver_vm_inventory",
        "silver_server_inventory",
    })
    _WORKLOAD_APPEND_WRITE_TABLES: frozenset[str] = frozenset({
        "silver_exposure_observations",
        "silver_container_vulnerability_observations",
        "silver_workload_observations",
    })
    _APPEND_REPLAY_COLUMNS: Mapping[str, frozenset[str]] = {
        "silver_container_vulnerability_observations": frozenset({
            "timestamp",
            "change_version",
            "ingested_at",
        }),
    }
    _APPEND_REPLAY_JSON_FIELDS: Mapping[
        str,
        Mapping[str, frozenset[str]],
    ] = {
        "silver_container_vulnerability_observations": {
            "provenance_json": frozenset({"ingested_at"}),
        },
    }
    _WORKLOAD_MERGE_WRITE_TABLES: frozenset[str] = frozenset({
        "silver_container_image_digests",
        "silver_container_logical_images",
        "silver_container_registries",
        "silver_workload_deployments",
        "metadata_workload_source_checkpoints",
    })
    _EXPOSURE_SNAPSHOT_WRITE_TABLES: frozenset[str] = frozenset({
        "gold_exposure_current",
        "gold_container_exposure_current",
        "gold_container_exposure_coverage",
    })
    _DERIVED_EXPOSURE_TABLES: frozenset[str] = frozenset({
        "silver_exposure_observations",
        *_EXPOSURE_SNAPSHOT_WRITE_TABLES,
    })

    def __init__(
        self,
        *,
        source_root: Path | str,
        onelake: OneLakeWriter,
        delta_writer: DeltaWriter,
        validator: DataQualityValidator,
        mapper: InventoryDatasetMapper | None = None,
        partitioning: PartitioningPolicy | None = None,
        metrics: FabricMetrics | None = None,
        lakehouse_manager: LakehouseManager | None = None,
        lakehouse_id: str = "",
        shortcuts: tuple[object, ...] = (),
        registration_attempts: int = 20,
        write_workers: int = 4,
        topology_enabled: bool = False,
        ontology_publisher=None,
        ontology_id: str = "",
        ontology_name: str = "Operational_Context_Graph",
        patch_policies: tuple[object, ...] = (),
        lifecycle_catalog: tuple[dict[str, Any], ...] = (),
        remediation_decision_reader=None,
        remediation_plan_reader=None,
        rollback_sleep=time.sleep,
        clock=time.monotonic,
        sql_reader=None,
    ) -> None:
        # ``source_root`` is normally a local disk path (CLI/manual sync), but
        # the API-triggered refresh path (``inventory_orchestration.
        # run_inventory_refresh_all_connections``) passes the connection
        # registry's combined-snapshot root, which is an ``abfss://`` OneLake
        # URI whenever ``AIOPS_HOME`` points at OneLake (the production
        # default -- see ``arg.config.deploy.yaml``). ``pathlib.Path``
        # mangles that URI's ``//`` (producing paths like
        # ``/app/abfss:/workspace@onelake...``), so remote roots must use
        # ``storage.fs.resolve_root`` instead, exactly like ``DatasetStore``
        # and ``RunLock`` already do.
        from storage.fs import is_onelake_uri, resolve_fs, resolve_root

        self._source_root_is_remote = is_onelake_uri(source_root)
        if self._source_root_is_remote:
            self.source_root = resolve_root(str(source_root))
            self._source_fs, self._resolved_source_root = resolve_fs(str(self.source_root))
        else:
            self.source_root = Path(source_root).resolve()
            self._source_fs = None
            self._resolved_source_root = str(self.source_root)
        self.onelake = onelake
        self.delta = delta_writer
        self.validator = validator
        self.mapper = mapper or InventoryDatasetMapper()
        self.partitioning = partitioning or PartitioningPolicy()
        self.metrics = metrics or FabricMetrics()
        self.lakehouse_manager = lakehouse_manager
        self.lakehouse_id = lakehouse_id
        self.shortcuts = shortcuts
        self.registration_attempts = registration_attempts
        if write_workers < 1:
            raise ValueError("write_workers must be positive")
        self.write_workers = write_workers
        self.topology_enabled = topology_enabled
        self.ontology_publisher = ontology_publisher
        self.ontology_id = ontology_id
        self.ontology_name = ontology_name
        self.patch_policies = patch_policies
        self.lifecycle_catalog = tuple(dict(row) for row in lifecycle_catalog)
        self.remediation_decision_reader = remediation_decision_reader
        self.remediation_plan_reader = remediation_plan_reader
        self.rollback_sleep = rollback_sleep
        self.clock = clock
        # Optional read accelerator. When present, aggregate reads (freshness
        # watermarks) are pushed down to the Lakehouse SQL endpoint instead of
        # materializing whole Delta tables. Writes always go through Delta.
        self.sql_reader = sql_reader

    def sync(
        self,
        *,
        replay_source_run_id: str = "",
        raise_on_quality_failure: bool = True,
        requested_scope: dict[str, list[str]] | None = None,
        progress_callback: Callable[[FabricTableWriteProgress], None] | None = None,
        stage_progress_callback: Callable[[FabricStageProgress], None] | None = None,
        exposure_pointer_store: OneLakeDocumentStore | None = None,
    ) -> FabricSyncResult:
        """Publish one snapshot and optionally report best-effort progress.

        Table callbacks retain the existing post-success
        :class:`FabricTableWriteProgress` contract. Stage callbacks receive
        exact, low-cardinality lifecycle mappings with bounded aggregate
        counts; callback failures never affect publication or expose dynamic
        exception data.
        """
        with self.onelake.sync_lock() as sync_lock:
            return self._sync_locked(
                replay_source_run_id=replay_source_run_id,
                raise_on_quality_failure=raise_on_quality_failure,
                requested_scope=requested_scope,
                progress_callback=progress_callback,
                stage_progress_callback=stage_progress_callback,
                exposure_pointer_store=exposure_pointer_store,
                assert_lock_held=sync_lock.assert_held,
            )

    def _sync_locked(
        self,
        *,
        replay_source_run_id: str = "",
        raise_on_quality_failure: bool = True,
        requested_scope: dict[str, list[str]] | None = None,
        progress_callback: Callable[[FabricTableWriteProgress], None] | None = None,
        stage_progress_callback: Callable[[FabricStageProgress], None] | None = None,
        exposure_pointer_store: OneLakeDocumentStore | None = None,
        assert_lock_held: Callable[[], None],
    ) -> FabricSyncResult:
        assert_lock_held()
        started_clock = self.clock()
        run_id = str(uuid.uuid4())
        snapshot = self._resolve_snapshot(replay_source_run_id)
        manifest = self._read_manifest(snapshot)
        source_run_id = str(manifest.get("runId") or replay_source_run_id or "unknown")
        replay = bool(replay_source_run_id)
        started_at = _utc_now()
        source_projected_at = str(
            manifest.get("completedAt")
            or manifest.get("startedAt")
            or started_at
        )
        assert_lock_held()
        self.onelake.ensure_standard_structure()
        assert_lock_held()
        self._write_state(
            _state_row(
                run_id,
                source_run_id,
                status="started",
                timestamp=started_at,
                replay=replay,
            )
        )
        assert_lock_held()

        table_results: dict[str, DeltaWriteResult] = {}
        written_versions: dict[str, tuple[str, int | None]] = {}
        completed_tables = 0
        failed_records = 0
        ontology_started = self.clock()
        ontology_health: dict[str, Any] = {}
        exposure_gold_datasets: dict[str, list[dict[str, Any]]] | None = None
        exposure_gold_publisher: ExposureGoldFabricPublisher | None = None
        exposure_gold_stage = None
        data_committed = False
        try:
            _notify_stage_progress(
                stage_progress_callback,
                "dataset_mapping",
                "started",
            )
            datasets = self.mapper.load(snapshot, run_id, fs=self._source_fs)
            _notify_stage_progress(
                stage_progress_callback,
                "dataset_mapping",
                "completed",
                dataset_count=len(datasets),
                failure_count=0,
            )
            datasets["metadata_source_status"] = [
                _with_source_partition_defaults(row)
                for row in datasets.get("metadata_source_status", [])
            ]
            partition_status = self._load_source_partition_status(snapshot, run_id)
            if partition_status:
                partition_families = {
                    row["source_family"] for row in partition_status
                }
                datasets["metadata_source_status"] = [
                    row
                    for row in datasets.get("metadata_source_status", [])
                    if row.get("source_family") not in partition_families
                ]
                datasets["metadata_source_status"].extend(partition_status)
            _notify_stage_progress(
                stage_progress_callback,
                "workload_projection",
                "started",
            )
            workload_products = self._load_workload_products(snapshot)
            datasets.update(workload_products)
            self._validate_workload_products(datasets)
            _notify_stage_progress(
                stage_progress_callback,
                "workload_projection",
                "completed",
                entity_count=_bounded_progress_count(
                    sum(len(rows) for rows in workload_products.values())
                ),
                relationship_count=0,
                failure_count=0,
            )
            if exposure_pointer_store is not None:
                observation_uri = self.onelake.table_uri(
                    "silver",
                    "exposure_observations",
                )
                persisted_observations = (
                    self.delta.read(observation_uri)
                    if self.delta.version(observation_uri) is not None
                    else []
                )
                existing_observations = _observation_rows_at_or_before(
                    persisted_observations,
                    projected_at=source_projected_at,
                )
                _notify_stage_progress(
                    stage_progress_callback,
                    "temporal_projection",
                    "started",
                )
                temporal = materialize_temporal_exposure_tables(
                    temporal_products_from_legacy(
                        datasets,
                        generation_id=source_run_id,
                        ingested_at=source_projected_at,
                    ),
                    existing_rows=existing_observations,
                    known_observation_rows=persisted_observations,
                )
                del persisted_observations, existing_observations
                temporal_tables = temporal.write_tables(copy_rows=False)
                datasets.update(temporal_tables)
                _notify_stage_progress(
                    stage_progress_callback,
                    "temporal_projection",
                    "completed",
                    entity_count=_bounded_progress_count(
                        sum(len(rows) for rows in temporal_tables.values())
                    ),
                    relationship_count=0,
                    failure_count=0,
                )
                _notify_stage_progress(
                    stage_progress_callback,
                    "container_projection",
                    "started",
                )
                container_tables = materialize_container_exposure_tables(
                    datasets,
                    projected_at=source_projected_at,
                    source_generation=source_run_id,
                )
                datasets.update(container_tables)
                _notify_stage_progress(
                    stage_progress_callback,
                    "container_projection",
                    "completed",
                    entity_count=_bounded_progress_count(
                        sum(len(rows) for rows in container_tables.values())
                    ),
                    relationship_count=0,
                    failure_count=0,
                )
                granular_entities, granular_relationships = (
                    GranularExposureOntologyMapper().build_rows(
                        datasets,
                        ontology_generation_id=source_run_id,
                        allow_empty=True,
                    )
                )
                _merge_granular_ontology_entities(
                    datasets["ontology_entities"],
                    granular_entities,
                )
                _merge_granular_ontology_relationships(
                    datasets["ontology_relationships"],
                    granular_relationships,
                )
                exposure_gold_datasets = {
                    **datasets,
                    "silver_exposure_observations": list(
                        temporal.all_observation_rows
                    ),
                }
                del (
                    container_tables,
                    granular_entities,
                    granular_relationships,
                    temporal,
                    temporal_tables,
                )
            del workload_products
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_construction",
                "started",
            )
            if self.topology_enabled:
                self._extend_with_topology_tables(
                    datasets,
                    snapshot=snapshot,
                    observed_at=started_at,
                    run_id=run_id,
                )
            datasets["silver_patch_policies"] = [
                {
                    "tenant_id": "not-applicable",
                    "subscription_id": "not-applicable",
                    "resource_id": "policy://"
                    + _hash_json(
                        {
                            "name": str(getattr(policy, "name", "")),
                            "environment": str(getattr(policy, "environment", "")),
                        }
                    )[:24],
                    "timestamp": started_at,
                    "change_version": _hash_json(
                        {
                            "name": str(getattr(policy, "name", "")),
                            "environment": str(getattr(policy, "environment", "")),
                            "max_patch_age_days": int(
                                getattr(policy, "max_patch_age_days", 0)
                            ),
                            "minimum_compliance_score": int(
                                getattr(policy, "minimum_compliance_score", 0)
                            ),
                        }
                    ),
                    "ingestion_run_id": run_id,
                    "name": str(getattr(policy, "name", "")),
                    "environment": str(getattr(policy, "environment", "")),
                    "max_patch_age_days": int(
                        getattr(policy, "max_patch_age_days", 0)
                    ),
                    "minimum_compliance_score": int(
                        getattr(policy, "minimum_compliance_score", 0)
                    ),
                }
                for policy in self.patch_policies
            ]
            if self.lifecycle_catalog:
                catalog_rows, catalog_entities = self._lifecycle_catalog_rows(
                    run_id, source_run_id, started_at
                )
                datasets["metadata_lifecycle_catalog"] = catalog_rows
                datasets["ontology_entities"].extend(catalog_entities)
            decision_entities: list[dict[str, Any]] = []
            decision_relationships: list[dict[str, Any]] = []
            plan_entities: list[dict[str, Any]] = []
            plan_relationships: list[dict[str, Any]] = []
            if self.remediation_plan_reader is not None:
                plan_entities, plan_relationships = remediation_plan_ontology_rows(
                    self.remediation_plan_reader(datasets["ontology_entities"]),
                    run_id,
                    started_at,
                )
            if self.remediation_decision_reader is not None:
                decision_entities, decision_relationships = (
                    remediation_decision_ontology_rows(
                        list(self.remediation_decision_reader()),
                        run_id,
                        started_at,
                    )
                )
            _extend_unique_ontology_rows(
                datasets["ontology_entities"],
                [*plan_entities, *decision_entities],
            )
            _extend_unique_ontology_rows(
                datasets["ontology_relationships"],
                [*decision_relationships, *plan_relationships],
            )
            change_pipeline_result = change_pipeline.run(
                freshness=started_at,
                **self._change_pipeline_snapshot(),
            )
            datasets["ontology_entities"].extend(change_pipeline_result.entities)
            datasets["ontology_relationships"].extend(change_pipeline_result.relationships)
            datasets["assessment_change_findings"] = self._assessment_change_finding_rows(
                change_pipeline_result.findings, run_id, started_at
            )
            predictive_pipeline_result = predictive_pipeline.run(
                freshness=started_at,
                **self._predictive_pipeline_snapshot(),
            )
            datasets["ontology_entities"].extend(predictive_pipeline_result.entities)
            datasets["ontology_relationships"].extend(predictive_pipeline_result.relationships)
            incident_pipeline_result = incident_pipeline.run(
                freshness=started_at,
                **self._incident_pipeline_snapshot(),
            )
            datasets["ontology_entities"].extend(incident_pipeline_result.entities)
            datasets["ontology_relationships"].extend(incident_pipeline_result.relationships)
            datasets = self._synchronize_ontology(
                datasets,
                source_run_id,
                started_at,
            )
            ontology_entity_count = _bounded_progress_count(
                len(datasets.get("ontology_entities", ()))
            )
            ontology_relationship_count = _bounded_progress_count(
                len(datasets.get("ontology_relationships", ()))
            )
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_construction",
                "completed",
                entity_count=ontology_entity_count,
                relationship_count=ontology_relationship_count,
                failure_count=0,
            )
            if self.lifecycle_catalog:
                datasets["silver_lifecycle_history"] = self._lifecycle_history_rows(
                    datasets, run_id, source_run_id, started_at
                )
            ontology_health = datasets["ontology_health"][0]
            source_watermark = max(
                (
                    str(row.get("timestamp") or "")
                    for row in datasets.get("bronze_resource_changes", [])
                    if row.get("timestamp")
                ),
                default=str(manifest.get("startedAt") or ""),
            )
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_validation",
                "started",
            )
            reports = self._validate(datasets)
            failed_records = sum(report.failed_records for report in reports)
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_validation",
                "completed",
                entity_count=ontology_entity_count,
                relationship_count=ontology_relationship_count,
                failure_count=_bounded_progress_count(failed_records),
            )
            self._write_quality_report(
                run_id,
                source_run_id,
                reports,
                started_at,
            )
            assert_lock_held()
            source_status_rows = [
                *datasets.get("metadata_source_status", []),
                *_table_source_status_rows(
                    {
                        name: rows
                        for name, rows in datasets.items()
                        if name not in self._DERIVED_EXPOSURE_TABLES
                    },
                    run_id,
                    started_at,
                    requested_scope=requested_scope,
                ),
            ]
            datasets["metadata_source_status"] = source_status_rows
            if exposure_gold_datasets is not None:
                exposure_gold_datasets["metadata_source_status"] = [
                    dict(row) for row in source_status_rows
                ]
            if source_status_rows:
                assert_lock_held()
                table_uri = self.onelake.table_uri("metadata", "source_status")
                before_version = self.delta.version(table_uri)
                result = self.delta.write(
                    table_uri,
                    source_status_rows,
                    mode=DeltaWriteMode.MERGE,
                    key_columns=("resource_id",),
                    schema=schema_for("metadata_source_status"),
                )
                table_results["metadata_source_status"] = result
                if result.version != before_version:
                    written_versions["metadata_source_status"] = (table_uri, before_version)
                self.metrics.record_table("metadata_source_status", result)
                assert_lock_held()
            if failed_records:
                assert_lock_held()
                failed = _state_row(
                    run_id,
                    source_run_id,
                    status="failed",
                    timestamp=_utc_now(),
                    replay=replay,
                    failed_records=failed_records,
                    error="Data quality validation failed",
                )
                self._write_state(failed)
                duration = self.clock() - started_clock
                self.metrics.record_run(duration, failed_records, "failed")
                result = _result(
                    run_id,
                    source_run_id,
                    "failed",
                    replay,
                    table_results,
                    failed_records,
                    duration,
                )
                if raise_on_quality_failure:
                    raise ValueError(f"Fabric data quality validation failed: {failed_records} records")
                return result

            _release_transient_publication_memory()

            def write_table(
                item: tuple[str, list[dict[str, Any]]],
            ) -> tuple[str, str, int | None, DeltaWriteResult]:
                assert_lock_held()
                table_name, rows = item
                _LOGGER.info(
                    "fabric_table_write_started",
                    extra={
                        "table_name": table_name,
                        "row_count": _bounded_progress_count(len(rows)),
                    },
                )
                layer, logical_name = table_name.split("_", 1)
                mode = self._write_mode_for_table(table_name)
                table_uri = self.onelake.table_uri(layer, logical_name)
                before_version = known_versions.get(table_name)
                if before_version is None and rows:
                    before_version = self.delta.version(table_uri)
                result = self.delta.write(
                    table_uri,
                    rows,
                    mode=mode,
                    key_columns=("event_id",)
                    if table_name == "metadata_audit_events"
                    else ("resource_id",),
                    partition_by=self.partitioning.columns_for(table_name),
                    schema=schema_for(table_name),
                    append_replay_columns=self._APPEND_REPLAY_COLUMNS.get(
                        table_name,
                        (),
                    ),
                    append_replay_json_fields=(
                        self._APPEND_REPLAY_JSON_FIELDS.get(table_name)
                    ),
                )
                assert_lock_held()
                return table_name, table_uri, before_version, result

            # Empty projections do not need a Fabric transaction unless the
            # table already exists and must be cleared for this snapshot.
            known_versions: dict[str, int | None] = {}
            publish_items: list[tuple[str, list[dict[str, Any]]]] = []
            for table_name, rows in datasets.items():
                if rows or table_name in {
                    "ontology_entities",
                    "ontology_relationships",
                }:
                    publish_items.append((table_name, rows))
                    continue
                table_uri = self.onelake.table_uri(
                    table_name.split("_", 1)[0],
                    table_name.split("_", 1)[1],
                )
                version = self.delta.version(table_uri)
                if version is not None:
                    known_versions[table_name] = version
                    publish_items.append((table_name, rows))
            _LOGGER.info(
                "Preparing Fabric publish: %d datasets (%d non-empty, %d empty skipped)",
                len(publish_items),
                sum(bool(rows) for _, rows in publish_items),
                len(datasets) - len(publish_items),
            )
            gold_table_count = (
                len(EXPOSURE_GOLD_TABLES) + 1
                if exposure_gold_datasets is not None
                and exposure_pointer_store is not None
                else 0
            )
            total_publish_tables = len(publish_items) + gold_table_count
            _notify_stage_progress(
                stage_progress_callback,
                "table_publication",
                "started",
            )
            with ThreadPoolExecutor(max_workers=self.write_workers) as executor:
                futures = [
                    executor.submit(write_table, item) for item in publish_items
                ]
                write_error = None
                for future in as_completed(futures):
                    try:
                        table_name, table_uri, before_version, result = future.result()
                    except Exception as exc:  # noqa: BLE001 - collect all worker failures before rollback.
                        write_error = write_error or exc
                        continue
                    table_results[table_name] = result
                    completed_tables += 1
                    if result.version != before_version:
                        written_versions[table_name] = (table_uri, before_version)
                    self.metrics.record_table(table_name, result)
                    _notify_table_progress(
                        progress_callback,
                        FabricTableWriteProgress(
                            completed_tables=completed_tables,
                            total_tables=total_publish_tables,
                            table_name=table_name,
                            result=result,
                        ),
                    )
                if write_error is not None:
                    raise write_error

            catalog = _catalog_metadata(
                datasets,
                table_results,
                run_id,
                source_run_id,
            )
            _notify_stage_progress(
                stage_progress_callback,
                "fabric_asset_registration",
                "started",
            )
            assert_lock_held()
            self._register_fabric_assets(set(table_results))
            assert_lock_held()
            _notify_stage_progress(
                stage_progress_callback,
                "fabric_asset_registration",
                "completed",
            )
            if self.topology_enabled:
                self._write_topology_manifest(
                    run_id=run_id,
                    observed_at=started_at,
                )
            self.onelake.write_json("ontology/metadata/catalog.json", catalog)
            assert_lock_held()
            data_committed = True
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_publication",
                "started",
            )
            self._publish_ontology(datasets)
            assert_lock_held()
            _notify_stage_progress(
                stage_progress_callback,
                "ontology_publication",
                "completed",
            )
            if (
                exposure_gold_datasets is not None
                and exposure_pointer_store is not None
            ):
                sample_table_uri = self.onelake.table_uri(
                    "gold",
                    "exposure_facts",
                )
                table_root: Path | str = (
                    str(sample_table_uri).rsplit("/", 1)[0]
                    if "://" in str(sample_table_uri)
                    else Path(str(sample_table_uri)).parent
                )
                gold_generation_id = _exposure_gold_generation_id(
                    source_run_id,
                    exposure_gold_datasets,
                )
                gold_tables = exposure_gold_products_from_datasets(
                    exposure_gold_datasets,
                    generation_id=gold_generation_id,
                    projected_at=source_projected_at,
                )
                exposure_gold_publisher = ExposureGoldFabricPublisher(
                    table_root=table_root,
                    delta_writer=self.delta,
                    pointer_store=exposure_pointer_store,
                )
                _notify_stage_progress(
                    stage_progress_callback,
                    "gold_staging",
                    "started",
                )
                exposure_gold_stage = exposure_gold_publisher.stage(
                    exposure_gold_datasets,
                    generation_id=gold_generation_id,
                    projected_at=source_projected_at,
                    published_at=started_at,
                )
                assert_lock_held()
                _notify_stage_progress(
                    stage_progress_callback,
                    "gold_staging",
                    "completed",
                )
                datasets.update(gold_tables)
                for table_name, result in exposure_gold_stage.table_writes.items():
                    table_results[table_name] = result
                    completed_tables += 1
                    self.metrics.record_table(table_name, result)
                    _notify_table_progress(
                        progress_callback,
                        FabricTableWriteProgress(
                            completed_tables=completed_tables,
                            total_tables=total_publish_tables,
                            table_name=table_name,
                            result=result,
                        ),
                    )

                _notify_stage_progress(
                    stage_progress_callback,
                    "fabric_asset_registration",
                    "started",
                )
                assert_lock_held()
                self._register_fabric_assets(
                    set(exposure_gold_stage.table_writes)
                )
                assert_lock_held()
                _notify_stage_progress(
                    stage_progress_callback,
                    "fabric_asset_registration",
                    "completed",
                )
                self.onelake.write_json(
                    "ontology/metadata/catalog.json",
                    _catalog_metadata(
                        datasets,
                        table_results,
                        run_id,
                        source_run_id,
                    ),
                )
                assert_lock_held()
            assert_lock_held()
            ontology_entity_version = _required_table_version(
                table_results,
                "ontology_entities",
            )
            ontology_relationship_version = _required_table_version(
                table_results,
                "ontology_relationships",
            )
            completed = _state_row(
                run_id,
                source_run_id,
                status="completed",
                timestamp=_utc_now(),
                replay=replay,
                rows_processed=sum(value.rows_processed for value in table_results.values()),
                rows_added=sum(value.rows_added for value in table_results.values()),
                rows_changed=sum(value.rows_changed for value in table_results.values()),
                rows_removed=sum(value.rows_removed for value in table_results.values()),
                watermark=source_watermark,
                ontology_entity_version=ontology_entity_version,
                ontology_relationship_version=ontology_relationship_version,
            )
            _notify_stage_progress(
                stage_progress_callback,
                "shortcut_finalization",
                "started",
            )
            self._create_shortcuts()
            assert_lock_held()
            _notify_stage_progress(
                stage_progress_callback,
                "shortcut_finalization",
                "completed",
            )
            assert_lock_held()
            self._write_state(completed)
            assert_lock_held()
            if (
                exposure_gold_publisher is not None
                and exposure_gold_stage is not None
            ):
                _notify_stage_progress(
                    stage_progress_callback,
                    "pointer_activation",
                    "started",
                )
                assert_lock_held()
                exposure_gold_publisher.activate(exposure_gold_stage)
                assert_lock_held()
                _notify_stage_progress(
                    stage_progress_callback,
                    "pointer_activation",
                    "completed",
                )
            self.metrics.record_ontology(
                ontology_health, self.clock() - ontology_started
            )
            duration = self.clock() - started_clock
            self.metrics.record_run(duration, 0, "completed")
            return _result(
                run_id,
                source_run_id,
                "completed",
                replay,
                table_results,
                0,
                duration,
            )
        except Exception as exc:
            self.metrics.record_ontology(
                ontology_health, self.clock() - ontology_started, errors=1
            )
            lock_error: Exception | None = None
            try:
                assert_lock_held()
            except LeaseLostError as lost:
                lock_error = lost
            rollback_errors = (
                []
                if data_committed or lock_error is not None
                else self._rollback(written_versions)
            )
            if not isinstance(exc, ValueError) or "data quality validation failed" not in str(exc).lower():
                error_message = str(exc)
                if data_committed:
                    error_message += "; committed graph tables were retained for idempotent retry"
                if rollback_errors:
                    error_message += "; rollback incomplete: " + " | ".join(rollback_errors)
                if lock_error is None:
                    self._write_state(
                        _state_row(
                            run_id,
                            source_run_id,
                            status="failed",
                            timestamp=_utc_now(),
                            replay=replay,
                            failed_records=max(failed_records, 1),
                            error=error_message[:2048],
                        )
                    )
                self.metrics.record_run(self.clock() - started_clock, max(failed_records, 1), "failed")
            if lock_error is not None:
                raise lock_error from exc
            if rollback_errors:
                raise RuntimeError(
                    "Fabric sync failed and rollback was incomplete: " + " | ".join(rollback_errors)
                ) from exc
            raise

    def _rollback(self, written_versions: dict[str, tuple[str, int | None]]) -> list[str]:
        errors: list[str] = []
        for table_name, (table_uri, before_version) in reversed(written_versions.items()):
            for attempt in range(1, 4):
                try:
                    if before_version is not None:
                        self.delta.restore(table_uri, before_version)
                    else:
                        layer, logical_name = table_name.split("_", 1)
                        self.onelake.delete_table(layer, logical_name)
                    break
                except Exception as rollback_error:  # noqa: BLE001 - continue all rollback actions.
                    if attempt == 3:
                        errors.append(f"{table_name}: {rollback_error}")
                    else:
                        self.rollback_sleep(min(2 ** (attempt - 1), 5))
        return errors

    def status(self) -> list[dict[str, Any]]:
        return self.delta.read(self.onelake.table_uri("metadata", "ingestion_state"))

    def ontology_query(self, question: str, *, entity: str = "") -> dict[str, Any]:
        from ontology.graph_queries import OntologyQueryService

        entities, relationships = self._read_authoritative_ontology()
        return OntologyQueryService(entities, relationships).answer(question, entity=entity)

    def ontology_health(self) -> dict[str, Any]:
        rows = self.delta.read(self.onelake.table_uri("ontology", "health"))
        return max(rows, key=lambda row: str(row.get("timestamp") or ""), default={})

    # Governed tables (beyond ontology entities) whose timestamps can lag or
    # lead ontology publication independently, since each is written by its
    # own ingestion pipeline. Every intelligence engine validates its inputs
    # against `SemanticEngine.freshness`, so that value must be the maximum
    # watermark across *everything* being loaded -- not just ontology
    # entities -- or a perfectly valid, newer row from any of these tables
    # trips the "observation exceeds snapshot freshness" guard and the whole
    # provider is marked unavailable.
    _FRESHNESS_WATERMARK_TABLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("silver", "compliance", ("timestamp",)),
        ("silver", "cost_actuals", ("usage_date", "timestamp")),
        ("silver", "patch_findings", ("timestamp",)),
        ("silver", "patch_installations", ("timestamp",)),
        ("silver", "patch_history", ("observed_at", "timestamp")),
        ("silver", "lifecycle_history", ("observed_at", "timestamp")),
        ("silver", "incidents", ("started_at", "timestamp")),
        ("silver", "alerts", ("fired_at", "timestamp")),
        ("silver", "incident_history", ("observed_at", "timestamp")),
        ("silver", "change_history", ("observed_at", "timestamp")),
        ("silver", "predictive_history", ("observed_at", "timestamp")),
        ("bronze", "resource_changes", ("timestamp",)),
    )

    def _global_freshness_watermark(self, floor: str) -> str:
        """Return the max timestamp across `floor` and every table in
        `_FRESHNESS_WATERMARK_TABLES` that is actually present, so
        `SemanticEngine.freshness` never lags behind data intelligence
        engines will validate against it.

        When a SQL endpoint reader is configured this runs as one aggregate
        query per table (a single row each). Otherwise it falls back to
        reading each Delta table in full, which is correct but downloads
        every row purely to compute a maximum.
        """
        watermark = floor
        if self.sql_reader is not None:
            try:
                return self._sql_freshness_watermark(floor)
            except Exception:
                _LOGGER.warning(
                    "fabric_sql_watermark_failed; falling back to Delta reads",
                    exc_info=True,
                )
        for layer, name, fields in self._FRESHNESS_WATERMARK_TABLES:
            uri = self.onelake.table_uri(layer, name)
            if self.delta.version(uri) is None:
                continue
            for row in self.delta.read(uri):
                value = ""
                for field in fields:
                    value = str(row.get(field) or "")
                    if value:
                        break
                if value and value > watermark:
                    watermark = value
        return watermark

    def _sql_freshness_watermark(self, floor: str) -> str:
        """Compute the watermark with one aggregate query per present table."""
        watermark = floor
        for layer, name, fields in self._FRESHNESS_WATERMARK_TABLES:
            table = f"{layer}_{name}"
            if not self.sql_reader.table_exists(table):
                continue
            value = self.sql_reader.max_timestamp(table, fields)
            if value and value > watermark:
                watermark = value
        return watermark

    def semantic_snapshot(self) -> dict[str, Any]:
        """Legacy compatibility projection for snapshot-based consumers.

        New API and modeler flows must use :meth:`semantic_graph_snapshot` and
        request-time live providers; this method is retained for existing
        intelligence providers during the migration.
        """

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        latest = self._latest_completed_ontology_state()
        entities, relationships = self._read_authoritative_ontology(
            marker=latest,
        )
        # A published ontology can outlive its ingestion-state rows (for example
        # when the metadata table was truncated or written by an earlier run).
        # Fall back to the newest published entity timestamp so downstream
        # intelligence receives a real freshness instead of an empty string,
        # which every consumer rejects as an invalid timestamp.
        entity_watermark = max(
            (str(row.get("timestamp") or "") for row in entities), default=""
        )
        entity_index = {row["resource_id"]: row for row in entities}
        # Mirror SemanticValidator.validate_snapshot()'s entity_ids exactly:
        # only ACTIVE entities count as valid fact targets. A security/cost
        # fact referencing a retired/inactive resource_id is dangling from
        # the validator's perspective even if the resource_id still exists
        # somewhere in the (unfiltered) entities table.
        entity_keys = {
            str(row.get("resource_id") or "").casefold()
            for row in entities
            if row.get("lifecycle_status", "active") == "active"
        }
        security: list[dict[str, Any]] = []
        for edge in relationships:
            if edge.get("predicate") != "affects":
                continue
            advisor = entity_index.get(str(edge.get("subject_id") or ""), {})
            if advisor.get("entity_type") != "AdvisorRecommendation":
                continue
            try:
                parsed = json.loads(str(advisor.get("payload_json") or "{}"))
                payload = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                payload = {}
            if str(payload.get("category") or "").casefold() != "security":
                continue
            target = str(edge.get("object_id") or "")
            # Advisor recommendations can outlive the resource they target
            # (deleted/renamed since the recommendation was raised). Skip
            # those instead of emitting a dangling reference that fails
            # SemanticEngine.from_rows validation and takes down every
            # downstream provider (semantic, vulnerability, incidents,
            # remediation) on the next refresh.
            if target.casefold() not in entity_keys:
                continue
            security.append(
                {
                    "target_resource_id": target,
                    "title": str(advisor.get("name") or "Security recommendation"),
                    "severity": str(payload.get("impact") or "unknown"),
                    "source": "Azure Advisor",
                    "timestamp": str(advisor.get("timestamp") or ""),
                }
            )
        business_functions = {
            row["resource_id"]: row
            for row in entities
            if row.get("entity_type") == "BusinessFunction"
        }
        service_functions = {
            str(edge.get("subject_id") or ""): str(edge.get("object_id") or "")
            for edge in relationships
            if edge.get("predicate") == "funded_by"
            and edge.get("object_id") in business_functions
        }
        cost = [
            {
                "target_resource_id": str(edge.get("subject_id") or ""),
                "cost_center": str(
                    business_functions[service_functions[str(edge.get("object_id"))]].get(
                        "name"
                    )
                    or ""
                ),
                "period": str(latest.get("timestamp") or ""),
            }
            for edge in relationships
            if edge.get("predicate") == "belongs_to"
            and str(edge.get("object_id") or "") in service_functions
            and str(edge.get("subject_id") or "").casefold() in entity_keys
        ]
        raw_version = str(
            latest.get("source_run_id")
            or latest.get("change_version")
            or max(
                (str(row.get("ingestion_run_id") or "") for row in entities),
                default="",
            )
        )
        public_version = (
            f"semantic-{_hash_json(raw_version)[:16]}"
            if raw_version
            else "semantic-unversioned"
        )
        freshness = self._global_freshness_watermark(
            str(latest.get("watermark") or latest.get("timestamp") or entity_watermark)
        )
        return {
            "entities": entities,
            "relationships": relationships,
            "inventory": read("bronze", "resources"),
            "compliance": read("silver", "compliance"),
            "security": security,
            "cost": cost,
            "knowledge_version": public_version,
            "freshness": freshness,
            "ontology_synchronized_at": str(
                latest.get("timestamp") or entity_watermark
            ),
        }

    def semantic_graph_snapshot(self) -> dict[str, Any]:
        """Return only the durable ontology graph for semantic-model consumers.

        Mutable inventory and operational facts remain in their authoritative
        source systems and are intentionally excluded from this projection.
        """

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        latest = self._latest_completed_ontology_state()
        entities, relationships = self._read_authoritative_ontology(
            marker=latest,
        )
        entity_watermark = max(
            (str(row.get("timestamp") or "") for row in entities), default=""
        )
        raw_version = str(
            latest.get("source_run_id")
            or latest.get("change_version")
            or max(
                (str(row.get("ingestion_run_id") or "") for row in entities),
                default="",
            )
        )
        knowledge_version = (
            f"semantic-{_hash_json(raw_version)[:16]}"
            if raw_version
            else "semantic-unversioned"
        )
        freshness = self._global_freshness_watermark(
            str(latest.get("watermark") or latest.get("timestamp") or entity_watermark)
        )
        return {
            "entities": entities,
            "relationships": relationships,
            "knowledge_version": knowledge_version,
            "freshness": freshness,
            "ontology_synchronized_at": str(
                latest.get("timestamp") or entity_watermark
            ),
        }

    def semantic_version(self) -> str:
        latest = self._latest_completed_ontology_state()
        raw_version = str(
            latest.get("source_run_id") or latest.get("change_version") or ""
        )
        if not raw_version:
            # Mirror semantic_snapshot()'s fallback so the cached engine version
            # matches the snapshot version and the engine is not rebuilt on
            # every call when ingestion state is missing.
            entities, _relationships = self._read_authoritative_ontology(
                marker=latest,
            )
            raw_version = max(
                (str(row.get("ingestion_run_id") or "") for row in entities),
                default="",
            )
        return (
            f"semantic-{_hash_json(raw_version)[:16]}"
            if raw_version
            else "semantic-unversioned"
        )

    def _lifecycle_catalog_rows(
        self, run_id: str, ontology_version: str, timestamp: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        metadata: list[dict[str, Any]] = []
        entities: list[dict[str, Any]] = []
        for entry in self.lifecycle_catalog:
            entry = {
                **entry,
                "notes": str(entry.get("notes") or ""),
                "default_support_channel": str(
                    entry.get("default_support_channel") or "mainstream"
                ),
            }
            key = "ontology://lifecycle-product/" + _hash_json(
                {
                    "product": str(entry.get("product") or "").casefold(),
                    "version": str(entry.get("version") or "").casefold(),
                }
            )[:32]
            base = {
                "tenant_id": "not-applicable",
                "subscription_id": "not-applicable",
                "resource_id": key,
                "timestamp": timestamp,
                "change_version": _hash_json(entry),
                "ingestion_run_id": run_id,
            }
            metadata.append({**base, **entry})
            entities.append(
                {
                    **base,
                    "entity_type": "LifecycleProduct",
                    "name": f"{entry.get('product', '')} {entry.get('version', '')}".strip(),
                    "resource_type": "lifecycle/product",
                    "location": "global",
                    "payload_json": json.dumps(entry, sort_keys=True),
                    "lineage_json": json.dumps(
                        {"source_url": entry.get("source_url", "")},
                        sort_keys=True,
                    ),
                    "semantic_metadata_json": json.dumps(
                        {"authority": "vendor_lifecycle_catalog"}, sort_keys=True
                    ),
                    "lifecycle_status": "active",
                    "valid_from": timestamp,
                    "retired_at": "",
                    "ontology_version": ontology_version,
                }
            )
        return metadata, entities

    def _lifecycle_history_rows(
        self,
        datasets: dict[str, list[dict[str, Any]]],
        run_id: str,
        source_run_id: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        from intelligence.lifecycle import LifecycleIntelligence
        from semantic.semantic_engine import SemanticEngine

        semantic = SemanticEngine.from_rows(
            entities=datasets["ontology_entities"],
            relationships=datasets["ontology_relationships"],
            inventory=datasets.get("bronze_resources", []),
            compliance=datasets.get("silver_compliance", []),
            knowledge_version=source_run_id,
            freshness=timestamp,
            ontology_synchronized_at=timestamp,
        )
        patch_posture = {
            str(row.get("assessed_resource_id") or "").casefold(): {
                "compliance_score": score
            }
            for row in datasets.get("silver_compliance", [])
            if row.get("assessed_resource_id")
            and (score := LifecycleIntelligence.semantic_patch_score(row.get("status")))
            is not None
        }
        intelligence = LifecycleIntelligence.from_semantic_engine(
            semantic,
            inventory=datasets.get("bronze_resources", []),
            catalog=list(self.lifecycle_catalog),
            history=[],
            patch_posture=patch_posture,
        )
        subscriptions_by_resource = {
            str(row.get("resource_id") or "").casefold(): str(
                row.get("subscription_id") or "not-applicable"
            )
            for row in datasets.get("bronze_resources", [])
        }
        rows = []
        for finding in intelligence._history_findings():
            resource_key = str(finding.get("_resource_key") or "").casefold()
            if not resource_key:
                continue
            subscription_id = subscriptions_by_resource.get(
                resource_key, "not-applicable"
            )
            history_id = "lifecycle-history://" + _hash_json(
                {
                    "resource_key": resource_key,
                    "observed_at": timestamp,
                    "ingestion_run_id": run_id,
                }
            )[:32]
            rows.append(
                {
                    "tenant_id": "not-applicable",
                    "subscription_id": subscription_id,
                    "resource_id": history_id,
                    "timestamp": timestamp,
                    "change_version": _hash_json(
                        {
                            "status": finding["lifecycle_status"],
                            "risk_score": finding["risk_score"],
                        }
                    ),
                    "ingestion_run_id": run_id,
                    "resource_key": resource_key,
                    "observed_at": timestamp,
                    "lifecycle_status": finding["lifecycle_status"],
                    "risk_score": int(finding["risk_score"]),
                    "modernization_state": "not_started",
                }
            )
        return rows

    def patch_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed patch facts for correlation through the Semantic Engine."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        policies = [
            {
                "name": str(row.get("name") or ""),
                "environment": str(row.get("environment") or ""),
                "max_patch_age_days": int(row.get("max_patch_age_days") or 0),
                "minimum_compliance_score": int(
                    row.get("minimum_compliance_score") or 0
                ),
            }
            for row in read("silver", "patch_policies")
        ]
        return {
            "inventory": read("bronze", "resources"),
            "assessments": read("silver", "compliance"),
            "findings": read("silver", "patch_findings"),
            "defender_findings": read("silver", "defender_findings"),
            "installations": read("silver", "patch_installations"),
            "history": read("silver", "patch_history"),
            "policies": policies,
        }

    def defender_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed Defender threat, attack-path, and posture facts."""

        def read(name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri("silver", name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        return {
            "assessments": read("defender_assessments"),
            "alerts": read("defender_alerts"),
            "attack_paths": read("defender_attack_paths"),
            "attack_path_nodes": read("defender_attack_path_nodes"),
            "attack_path_connections": read("defender_attack_path_connections"),
            "secure_scores": read("defender_secure_scores"),
            "secure_score_controls": read("defender_secure_score_controls"),
            "source_status": [
                row
                for row in (
                    self.delta.read(
                        self.onelake.table_uri("metadata", "source_status")
                    )
                    if self.delta.version(
                        self.onelake.table_uri("metadata", "source_status")
                    )
                    is not None
                    else []
                )
                if str(row.get("source_family") or "").startswith("defender_")
            ],
        }

    def lifecycle_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed lifecycle metadata and observation history."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        catalog = [
            {
                key: row.get(key)
                for key in (
                    "product",
                    "version",
                    "release_date",
                    "mainstream_support_end",
                    "extended_support_end",
                    "last_update_date",
                    "recommended_upgrade_path",
                    "source_url",
                    "notes",
                    "default_support_channel",
                )
            }
            for row in read("metadata", "lifecycle_catalog")
        ]
        return {
            "inventory": read("bronze", "resources"),
            "catalog": catalog,
            "history": read("silver", "lifecycle_history"),
        }

    def incident_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed incident, alert, and ARG change evidence for causality analysis."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        incidents = [
            {
                "incident_id": str(row.get("incident_id") or ""),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or "Unknown"),
                "severity": str(row.get("severity") or "Unknown"),
                "started_at": str(row.get("started_at") or row.get("timestamp") or ""),
                "resource_key": str(row.get("target_resource_id") or "").casefold(),
            }
            for row in read("silver", "incidents")
        ]
        alerts = [
            {
                "alert_id": str(row.get("alert_id") or ""),
                "title": str(row.get("title") or ""),
                "severity": str(row.get("severity") or "Unknown"),
                "fired_at": str(row.get("fired_at") or row.get("timestamp") or ""),
                "resource_key": str(row.get("target_resource_id") or "").casefold(),
                "signal": str(row.get("signal") or "Unknown"),
            }
            for row in read("silver", "alerts")
        ]
        resource_changes = _dedupe_changes([
            {
                "change_id": _change_identity(row, namespace="resource_changes"),
                "change_type": str(row.get("change_type") or "Unknown"),
                "changed_at": str(row.get("timestamp") or ""),
                "resource_key": str(row.get("target_resource_id") or "").casefold(),
                "summary": f"Resource change: {row.get('change_type') or 'Unknown'}",
            }
            for row in read("bronze", "resource_changes")
        ])
        return {
            "inventory": read("bronze", "resources"),
            "incidents": incidents,
            "alerts": alerts,
            "resource_changes": resource_changes,
            "history": [
                {
                    "incident_id": str(row.get("incident_id") or ""),
                    "observed_at": str(
                        row.get("observed_at") or row.get("timestamp") or ""
                    ),
                    "status": str(row.get("status") or "Unknown"),
                    "severity": str(row.get("severity") or "Unknown"),
                    "resource_key": str(
                        row.get("target_resource_id") or ""
                    ).casefold(),
                }
                for row in read("silver", "incident_history")
            ],
        }

    def _incident_pipeline_snapshot(self) -> dict[str, Any]:
        """Translate ``incident_intelligence_snapshot()``'s governed shape
        into ``IncidentIntelligence.from_snapshot()``'s expected
        ``resources`` shape (only ``resource_key`` is strictly required per
        ``IncidentContextBuilder``). ``patch_findings``/``lifecycle_findings``
        are empty here — those come from live cross-domain semantic-engine
        posture in the on-demand query path (``runtime.py``), which this
        batch sync flow does not have; this is additive forwarding of the
        five keys ``incident_intelligence_snapshot()`` already produces, not
        an invented cross-domain computation."""
        snapshot = self.incident_intelligence_snapshot()
        resources = [
            {
                "resource_key": str(row.get("resource_id") or ""),
                "name": str(row.get("name") or ""),
                "entity_type": str(row.get("entity_type") or "Resource"),
            }
            for row in snapshot["inventory"]
        ]
        return {
            "resources": resources,
            "incidents": snapshot["incidents"],
            "alerts": snapshot["alerts"],
            "resource_changes": snapshot["resource_changes"],
            "patch_findings": [],
            "lifecycle_findings": [],
            "history": snapshot["history"],
        }

    def change_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed change, drift, policy, security, identity, and IaC evidence."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        def payload(row: dict[str, Any]) -> dict[str, Any]:
            try:
                value = json.loads(str(row.get("payload_json") or "{}"))
            except json.JSONDecodeError:
                return {}
            return value if isinstance(value, dict) else {}

        resource_changes = []
        for row in read("bronze", "resource_changes"):
            source = payload(row)
            properties = source.get("properties") or {}
            attributes = properties.get("changeAttributes") or {}
            changes = properties.get("changes") or {}
            previous_state = {
                str(key): value.get("previousValue")
                for key, value in changes.items()
                if isinstance(value, dict) and "previousValue" in value
            }
            current_state = {
                str(key): value.get("newValue")
                for key, value in changes.items()
                if isinstance(value, dict) and "newValue" in value
            }
            authorized = source.get("authorized")
            if not isinstance(authorized, bool):
                authorized = None
            resource_changes.append(
                {
                    "change_id": _change_identity(row, namespace="resource_changes"),
                    "resource_key": str(
                        row.get("target_resource_id") or ""
                    ).casefold(),
                    "changed_at": str(row.get("timestamp") or ""),
                    "change_type": str(row.get("change_type") or "Unknown"),
                    "category": "Configuration",
                    "changed_by": str(
                        source.get("changedBy")
                        or attributes.get("changedBy")
                        or "Unknown"
                    ),
                    "source": "Azure Resource Graph ResourceChanges",
                    "changed_fields": sorted(str(key) for key in changes)[:50],
                    "summary": f"Resource change: {row.get('change_type') or 'Unknown'}",
                    "previous_state": previous_state,
                    "current_state": current_state,
                    "authorized": authorized,
                    "approval_reference": str(
                        source.get("approvalReference") or "Unknown"
                    ),
                }
            )
        resource_changes = _dedupe_changes(resource_changes)

        def deviations(name: str) -> list[dict[str, Any]]:
            return [
                {
                    "deviation_id": str(row.get("deviation_id") or ""),
                    "resource_key": str(
                        row.get("target_resource_id") or ""
                    ).casefold(),
                    "observed_at": str(
                        row.get("observed_at") or row.get("timestamp") or ""
                    ),
                    "severity": str(row.get("severity") or "Unknown"),
                    "control": str(row.get("control") or "Unknown"),
                    "status": str(row.get("status") or "Unknown"),
                }
                for row in read("silver", name)
            ]

        def changes(name: str) -> list[dict[str, Any]]:
            return _dedupe_changes([
                {
                    "change_id": _change_identity(
                        row,
                        fallback=str(row.get("change_id") or ""),
                        namespace=name,
                    ),
                    "resource_key": str(
                        row.get("target_resource_id") or ""
                    ).casefold(),
                    "changed_at": str(
                        row.get("changed_at") or row.get("timestamp") or ""
                    ),
                    "severity": str(row.get("severity") or "Unknown"),
                    "changed_by": str(row.get("changed_by") or "Unknown"),
                    "source": str(row.get("source") or name),
                    "summary": str(row.get("summary") or "Change observed"),
                }
                for row in read("silver", name)
            ])

        def configurations(name: str) -> dict[str, dict[str, Any]]:
            result = {}
            for row in read("silver", name):
                try:
                    configuration = json.loads(
                        str(row.get("configuration_json") or "{}")
                    )
                except json.JSONDecodeError:
                    configuration = {}
                if isinstance(configuration, dict):
                    result[
                        str(row.get("target_resource_id") or "").casefold()
                    ] = configuration
            return result

        incident_snapshot = self.incident_intelligence_snapshot()
        return {
            "inventory": read("bronze", "resources"),
            "resource_changes": resource_changes,
            "policy_deviations": deviations("policy_deviations"),
            "security_deviations": deviations("security_deviations"),
            "network_changes": changes("network_changes"),
            "identity_changes": changes("identity_changes"),
            "iac_changes": changes("iac_changes"),
            "incidents": incident_snapshot["incidents"],
            "history": read("silver", "change_history"),
            "expected_configurations": configurations("expected_configurations"),
            "observed_configurations": configurations("observed_configurations"),
        }

    def _change_pipeline_snapshot(self) -> dict[str, Any]:
        """Translate ``change_intelligence_snapshot()``'s governed shape into
        ``ChangeIntelligence.from_snapshot()``'s expected ``resources`` shape.

        ``change_intelligence_snapshot()`` keeps ``expected_configurations``/
        ``observed_configurations`` as separate resource-key-indexed maps
        (the shape ``ChangeIntelligence.from_semantic_engine`` merges using
        live semantic-engine context). ``from_snapshot`` instead expects each
        resource's expected/observed configuration nested directly on the
        resource row. This merges the governed inventory with those maps so
        the same governed snapshot can feed both call paths.
        """
        snapshot = self.change_intelligence_snapshot()
        expected = snapshot["expected_configurations"]
        observed = snapshot["observed_configurations"]
        resources = [
            {
                "resource_key": str(row.get("resource_id") or ""),
                "name": str(row.get("name") or ""),
                "entity_type": str(row.get("entity_type") or "Resource"),
                "expected_configuration": expected.get(
                    str(row.get("resource_id") or "").casefold()
                )
                or {},
                "observed_configuration": observed.get(
                    str(row.get("resource_id") or "").casefold()
                )
                or {},
            }
            for row in snapshot["inventory"]
        ]
        return {
            "resources": resources,
            "resource_changes": snapshot["resource_changes"],
            "policy_deviations": snapshot["policy_deviations"],
            "security_deviations": snapshot["security_deviations"],
            "network_changes": snapshot["network_changes"],
            "identity_changes": snapshot["identity_changes"],
            "iac_changes": snapshot["iac_changes"],
            "incidents": snapshot["incidents"],
            "history": snapshot["history"],
        }

    def _assessment_change_finding_rows(
        self, findings: list[dict[str, Any]], run_id: str, timestamp: str
    ) -> list[dict[str, Any]]:
        """Shape ``ChangePipelineResult.findings`` rows for the
        ``assessment_change_findings`` Delta table's governed-row contract
        (``DeltaWriter.REQUIRED_COLUMNS``)."""
        rows = []
        for finding in findings:
            change_id = str(finding.get("change_id") or "")
            rows.append(
                {
                    "tenant_id": "not-applicable",
                    "subscription_id": "not-applicable",
                    "resource_id": "assessment-change-finding://" + change_id,
                    "timestamp": timestamp,
                    "change_version": _hash_json(finding),
                    "ingestion_run_id": run_id,
                    "change_id": change_id,
                    "resource_name": str(finding.get("resource_name") or ""),
                    "change_type": str(finding.get("change_type") or ""),
                    "category": str(finding.get("category") or ""),
                    "authorized": finding.get("authorized"),
                    "risk_score": int(finding.get("risk_score") or 0),
                    "risk_level": str(finding.get("risk_level") or ""),
                    "compliance_score": int(finding.get("compliance_score") or 0),
                    "configuration_drifted": finding.get("configuration_drifted"),
                    "drift_fields": list(finding.get("drift_fields") or []),
                    "incident_id": str(finding.get("incident_id") or ""),
                    "incident_contribution_score": int(
                        finding.get("incident_contribution_score") or 0
                    ),
                    "application": str(finding.get("application") or ""),
                    "business_service": str(finding.get("business_service") or ""),
                    "confirmed_cause": bool(finding.get("confirmed_cause") or False),
                    "source": str(finding.get("source") or ""),
                }
            )
        return rows

    def predictive_intelligence_snapshot(self) -> dict[str, Any]:
        """Governed inventory and historical predictive feature observations."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        history = [
            {
                "resource_key": str(
                    row.get("target_resource_id") or row.get("resource_key") or ""
                ).casefold(),
                "observed_at": str(
                    row.get("observed_at") or row.get("timestamp") or ""
                ),
                "observation_id": str(row.get("resource_id") or ""),
                "patch_debt": int(row.get("patch_debt") or 0),
                "lifecycle_risk_score": int(
                    row.get("lifecycle_risk_score") or 0
                ),
                "incident_count_30d": int(row.get("incident_count_30d") or 0),
                "configuration_drift_count": int(
                    row.get("configuration_drift_count") or 0
                ),
                "risk_score": int(row.get("risk_score") or 0),
                **(
                    {"ownership_coverage_score": int(row["ownership_coverage_score"])}
                    if row.get("ownership_coverage_score") is not None
                    else {}
                ),
                **(
                    {"security_debt_score": int(row["security_debt_score"])}
                    if row.get("security_debt_score") is not None
                    else {}
                ),
            }
            for row in read("silver", "predictive_history")
        ]
        return {"inventory": read("bronze", "resources"), "history": history}

    def _predictive_pipeline_snapshot(self) -> dict[str, Any]:
        """Translate ``predictive_intelligence_snapshot()``'s governed shape
        into ``PredictiveIntelligence.from_snapshot()``'s expected
        ``resources`` shape (only ``resource_key`` is strictly required —
        every other field defaults to "Unknown"/0 in
        ``PredictiveContextBuilder``, so the governed inventory alone is
        sufficient without needing live semantic-engine context)."""
        snapshot = self.predictive_intelligence_snapshot()
        resources = [
            {
                "resource_key": str(row.get("resource_id") or ""),
                "name": str(row.get("name") or ""),
                "entity_type": str(row.get("entity_type") or "Resource"),
            }
            for row in snapshot["inventory"]
        ]
        return {"resources": resources, "history": snapshot["history"]}

    def remediation_planning_snapshot(self) -> dict[str, Any]:
        """Governed inventory, declarative actions, and approval policies."""

        def read(layer: str, name: str) -> list[dict[str, Any]]:
            uri = self.onelake.table_uri(layer, name)
            return self.delta.read(uri) if self.delta.version(uri) is not None else []

        def parsed(row: dict[str, Any], field: str, expected_type):
            try:
                value = json.loads(str(row.get(field) or ""))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed governed remediation {field}") from exc
            if not isinstance(value, expected_type):
                raise TypeError(f"Invalid governed remediation {field}")
            return value

        action_rows = read("silver", "remediation_action_catalog")
        policy_rows = read("silver", "remediation_approval_policies")
        if bool(action_rows) != bool(policy_rows):
            raise RuntimeError(
                "Governed remediation catalog publication is incomplete: "
                "action and approval-policy tables must be published together"
            )
        if action_rows:
            action_versions = {
                str(row.get("change_version") or "") for row in action_rows
            }
            policy_versions = {
                str(row.get("change_version") or "") for row in policy_rows
            }
            if (
                len(action_versions) != 1
                or len(policy_versions) != 1
                or action_versions != policy_versions
                or "" in action_versions
            ):
                raise RuntimeError(
                    "Governed remediation catalog publication has mixed generations"
                )

        catalog = [
            {
                "action_id": str(row.get("action_id") or ""),
                "title": str(row.get("title") or ""),
                "opportunity_type": str(row.get("opportunity_type") or ""),
                "trigger": parsed(row, "trigger_json", dict),
                "execution_steps": parsed(row, "execution_steps_json", list),
                "preconditions": parsed(row, "preconditions_json", list),
                "rollback_actions": parsed(row, "rollback_actions_json", list),
                "success_criteria": parsed(row, "success_criteria_json", list),
                "failure_criteria": parsed(row, "failure_criteria_json", list),
                "deployment_stages": parsed(row, "deployment_stages_json", list),
                "effectiveness": parsed(row, "effectiveness_json", dict),
            }
            for row in action_rows
        ]
        policies = [
            {
                "policy_id": str(row.get("policy_id") or ""),
                "conditions": parsed(row, "conditions_json", dict),
                "roles": parsed(row, "roles_json", list),
                # role_ids_json is nullable (Phase 03.5 CR-05 fix -- added
                # after the original schema shipped): a governed policy row
                # written before this column existed, or one that simply
                # has not configured a distinct per-role identity yet,
                # reads back with an empty mapping rather than raising --
                # ApprovalEngine.requirements() then derives a stable,
                # deterministic, distinct id per role on its own, never
                # collapsing every unmapped role onto one shared default.
                "role_ids": (
                    parsed(row, "role_ids_json", dict) if row.get("role_ids_json") else {}
                ),
            }
            for row in policy_rows
        ]
        return {
            "inventory": read("bronze", "resources"),
            "action_catalog": catalog,
            "approval_policies": policies,
        }

    def _synchronize_ontology(
        self,
        datasets: dict[str, list[dict[str, Any]]],
        ontology_version: str,
        timestamp: str,
    ) -> dict[str, list[dict[str, Any]]]:
        previous_entities, previous_relationships = (
            self._authoritative_ontology_predecessor()
        )
        previous_entities, previous_relationships = (
            filter_legacy_granular_exposure_graph(
                previous_entities,
                previous_relationships,
            )
        )
        result = OntologyGraphSynchronizer(OntologyValidator()).synchronize(
            datasets["ontology_entities"],
            datasets["ontology_relationships"],
            previous_entities=previous_entities,
            previous_relationships=previous_relationships,
            ontology_version=ontology_version,
            timestamp=timestamp,
        )
        datasets["ontology_entities"] = result.entities
        datasets["ontology_relationships"] = result.relationships
        for table_name in list(datasets):
            if table_name.startswith("ontology_rel_") or (
                table_name.startswith("ontology_")
                and table_name.endswith("_entities")
                and table_name != "ontology_entities"
            ):
                del datasets[table_name]
        for entity_type in ONTOLOGY_ENTITY_TYPES:
            datasets[ontology_entity_table(entity_type)] = [
                row
                for row in result.entities
                if row["entity_type"] == entity_type
                and row["lifecycle_status"] == "active"
            ]
        for row in result.relationships:
            if row["lifecycle_status"] != "active":
                continue
            table_name = ontology_relationship_table(
                row["subject_type"], row["predicate"], row["object_type"]
            )
            datasets.setdefault(table_name, []).append(row)
        for relationship_type in ONTOLOGY_RELATIONSHIP_TYPES:
            datasets.setdefault(ontology_relationship_table(*relationship_type), [])
        return datasets

    def _authoritative_ontology_predecessor(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Read only the canonical versions recorded by a completed sync.

        Per-table Delta overwrites are individually atomic but a process can
        die between the entity and relationship writes. The completed
        ingestion-state row is deliberately published only after every
        finalization step, so a missing marker means there is no authoritative
        predecessor and a later partial head can never be consumed.
        """
        return self._read_authoritative_ontology()

    def _latest_completed_ontology_state(self) -> dict[str, Any]:
        completed = [
            row
            for row in self.status()
            if row.get("status") == "completed"
            and row.get("ontology_entity_version") is not None
            and row.get("ontology_relationship_version") is not None
        ]
        if not completed:
            return {}
        return max(
            completed,
            key=lambda row: str(row.get("timestamp") or ""),
        )

    def _read_authoritative_ontology(
        self,
        *,
        marker: Mapping[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        selected = (
            dict(marker)
            if marker is not None
            else self._latest_completed_ontology_state()
        )
        if not selected:
            return [], []
        entity_version = _validated_delta_version(
            selected.get("ontology_entity_version"),
            field_name="ontology_entity_version",
        )
        relationship_version = _validated_delta_version(
            selected.get("ontology_relationship_version"),
            field_name="ontology_relationship_version",
        )
        return (
            self.delta.read(
                self.onelake.table_uri("ontology", "entities"),
                version=entity_version,
            ),
            self.delta.read(
                self.onelake.table_uri("ontology", "relationships"),
                version=relationship_version,
            ),
        )

    def _publish_ontology(self, datasets: dict[str, list[dict[str, Any]]]) -> None:
        if self.ontology_publisher is None:
            return
        entity_types = {
            entity_type: ontology_entity_table(entity_type)
            for entity_type in ONTOLOGY_ENTITY_TYPES
        }
        relationships = {
            relationship_type: ontology_relationship_table(*relationship_type)
            for relationship_type in ONTOLOGY_RELATIONSHIP_TYPES
        }
        relationships.update({
            (row["subject_type"], row["predicate"], row["object_type"]): ontology_relationship_table(
                row["subject_type"], row["predicate"], row["object_type"]
            )
            for row in datasets["ontology_relationships"]
        })
        self.ontology_publisher.publish(
            ontology_id=self.ontology_id,
            ontology_name=self.ontology_name,
            entity_types=entity_types,
            relationships=relationships,
        )

    def validate_current(self) -> list[QualityReport]:
        snapshot = self._resolve_snapshot("")
        datasets = self.mapper.load(snapshot, "validation", fs=self._source_fs)
        return self._validate(datasets)

    def _validate(self, datasets: dict[str, list[dict]]) -> list[QualityReport]:
        entity_ids = {row["resource_id"] for row in datasets.get("ontology_entities", [])}
        reports = []
        for table_name, rows in datasets.items():
            if table_name in {"silver_resource_relationships", "ontology_relationships"} or table_name.startswith(
                "ontology_rel_"
            ):
                reports.append(
                    self.validator.validate_relationships(
                        rows,
                        entity_ids=entity_ids,
                        table_name=table_name,
                    )
                )
            else:
                reports.append(self.validator.validate_table(table_name, rows))
        return reports

    def _write_state(self, row: dict[str, Any]) -> None:
        self.delta.write(
            self.onelake.table_uri("metadata", "ingestion_state"),
            [row],
            mode=DeltaWriteMode.MERGE,
            key_columns=("resource_id",),
            schema=schema_for("metadata_ingestion_state"),
        )

    def _write_quality_report(
        self,
        run_id: str,
        source_run_id: str,
        reports: list[QualityReport],
        timestamp: str,
    ) -> None:
        failed = sum(report.failed_records for report in reports)
        row = {
            "tenant_id": "system",
            "subscription_id": "system",
            "resource_id": f"quality://{run_id}",
            "timestamp": timestamp,
            "change_version": _hash_json([report.to_dict() for report in reports]),
            "ingestion_run_id": run_id,
            "source_run_id": source_run_id,
            "passed": failed == 0,
            "failed_records": failed,
            "report_json": json.dumps([report.to_dict() for report in reports], sort_keys=True),
        }
        self.delta.write(
            self.onelake.table_uri("metadata", "quality_reports"),
            [row],
            mode=DeltaWriteMode.MERGE,
            key_columns=("resource_id",),
            schema=schema_for("metadata_quality_reports"),
        )

    def _resolve_snapshot(self, replay_source_run_id: str) -> Path | str:
        if self._source_root_is_remote:
            return self._resolve_snapshot_remote(replay_source_run_id)
        candidate = (
            self.source_root / "generations" / replay_source_run_id
            if replay_source_run_id
            else self.source_root / "current"
        )
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(self.source_root)
        except ValueError as exc:
            raise ValueError(f"Source snapshot escapes configured root: {candidate}") from exc
        if not (resolved / "manifest.json").is_file():
            raise ValueError(f"Source snapshot has no manifest: {candidate}")
        return resolved

    def _resolve_snapshot_remote(self, replay_source_run_id: str) -> str:
        """Resolve a snapshot under an ``abfss://`` OneLake ``source_root``.

        Mirrors ``DatasetStore.current_generation``'s pointer-file protocol
        (no symlinks on OneLake): ``current.json`` at the root names the
        active generation directory under ``generations/``.
        """
        fs = self._source_fs
        root = str(self._resolved_source_root)
        if replay_source_run_id:
            candidate = f"{root}/generations/{replay_source_run_id}"
        elif fs.exists(f"{root}/manifest.json"):
            candidate = root
        else:
            pointer_path = f"{root}/current.json"
            if not fs.exists(pointer_path):
                raise ValueError(f"Source snapshot has no manifest: {root}/current")
            with fs.open(pointer_path, "rt") as handle:
                pointer = json.loads(handle.read())
            name = str(pointer.get("generation") or "").strip()
            if not name:
                raise ValueError(f"Source snapshot has no manifest: {root}/current")
            candidate = f"{root}/generations/{name}"
        if not fs.exists(candidate):
            raise ValueError(f"Source snapshot escapes configured root: {candidate}")
        if not fs.exists(f"{candidate}/manifest.json"):
            raise ValueError(f"Source snapshot has no manifest: {candidate}")
        return candidate

    def _read_manifest(self, snapshot: Path | str) -> dict[str, Any]:
        if self._source_root_is_remote:
            fs = self._source_fs
            with fs.open(f"{snapshot}/manifest.json", "rt") as handle:
                payload = json.loads(handle.read())
            if not isinstance(payload, dict):
                raise TypeError(f"Expected object JSON: {snapshot}/manifest.json")
            return payload
        return _read_json(Path(snapshot) / "manifest.json")

    def _register_fabric_assets(self, tables: set[str]) -> None:
        if self.lakehouse_manager is None:
            return
        expected = set(tables) | {"metadata_ingestion_state", "metadata_quality_reports"}
        self.lakehouse_manager.ensure_tables_registered(
            self.lakehouse_id,
            expected,
            attempts=self.registration_attempts,
        )

    def _create_shortcuts(self) -> None:
        if self.lakehouse_manager is None:
            return
        for shortcut in self.shortcuts:
            self.lakehouse_manager.create_shortcut(
                self.lakehouse_id,
                path=shortcut.path,
                name=shortcut.name,
                target=shortcut.target,
                conflict_policy=shortcut.conflict_policy,
            )

    def _write_mode_for_table(self, table_name: str) -> DeltaWriteMode:
        if (
            table_name == "metadata_audit_events"
            or table_name in self._WORKLOAD_APPEND_WRITE_TABLES
        ):
            return DeltaWriteMode.APPEND
        if (
            table_name in self._MERGE_WRITE_TABLES
            or table_name in self._WORKLOAD_MERGE_WRITE_TABLES
        ):
            return DeltaWriteMode.MERGE
        if table_name in self._SNAPSHOT_MERGE_WRITE_TABLES:
            return DeltaWriteMode.SNAPSHOT_MERGE
        if table_name in self._EXPOSURE_SNAPSHOT_WRITE_TABLES:
            return DeltaWriteMode.SNAPSHOT_MERGE
        return DeltaWriteMode.OVERWRITE

    def _load_workload_products(
        self,
        snapshot: Path | str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read additive v1 products with a legacy path compatibility window."""

        products = {
            "silver_workload_observations": (
                "exposure/workload_observations",
                "workload/workload_observations",
            ),
            "silver_workload_deployments": (
                "exposure/workload_deployments",
                "workload/workload_deployments",
            ),
            "metadata_workload_source_checkpoints": (
                "exposure/workload_source_checkpoints",
                "workload/workload_source_checkpoints",
            ),
        }
        loaded: dict[str, list[dict[str, Any]]] = {}
        for table_name, paths in products.items():
            rows: list[dict[str, Any]] = []
            for relative in paths:
                exists, candidate = self._read_snapshot_jsonl(snapshot, relative)
                if exists:
                    rows = candidate
                    break
            if rows:
                loaded[table_name] = rows
        return loaded

    def _load_source_partition_status(
        self,
        snapshot: Path | str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        exists, rows = self._read_snapshot_jsonl(
            snapshot,
            "situations/source_status",
        )
        if not exists:
            return []
        return [
            _source_partition_status_row(row, run_id)
            for row in rows
            if row.get("partition_key")
        ]

    def _read_snapshot_jsonl(
        self,
        snapshot: Path | str,
        relative: str,
    ) -> tuple[bool, list[dict[str, Any]]]:
        path = (
            f"{str(snapshot).rstrip('/')}/{relative}.jsonl"
            if self._source_root_is_remote
            else Path(snapshot) / f"{relative}.jsonl"
        )
        if self._source_fs is not None:
            if not self._source_fs.exists(path):
                return False, []
            with self._source_fs.open(path, "rt") as handle:
                lines = handle.read().splitlines()
        else:
            local_path = Path(path)
            if not local_path.exists():
                return False, []
            lines = local_path.read_text().splitlines()
        rows: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise TypeError("Workload product rows must be JSON objects")
            rows.append(parsed)
        return True, rows

    def _validate_workload_products(
        self,
        datasets: dict[str, list[dict[str, Any]]],
    ) -> None:
        from intelligence.vulnerability.workload_inventory import (
            WORKLOAD_QUERY_FAMILIES,
            normalize_digest,
            workload_checkpoint_key,
        )

        checkpoints = datasets.get("metadata_workload_source_checkpoints", [])
        observations = datasets.get("silver_workload_observations", [])
        deployments = datasets.get("silver_workload_deployments", [])
        if not checkpoints and not observations and not deployments:
            return
        checkpoint_ids = {
            str(row.get("checkpoint_key") or "") for row in checkpoints
        }
        workspace_families: dict[tuple[str, str], set[str]] = {}
        for row in checkpoints:
            connection_id = str(row.get("connection_id") or "")
            workspace_id = str(row.get("workspace_id") or "")
            source_family = str(row.get("source_family") or "")
            expected_key = workload_checkpoint_key(
                connection_id,
                workspace_id,
                source_family,
            )
            if row.get("checkpoint_key") != expected_key:
                raise ValueError("Workload checkpoint identity is invalid")
            workspace_families.setdefault(
                (connection_id, workspace_id),
                set(),
            ).add(source_family)
            status = str(row.get("status") or "")
            effective = str(row.get("effective_generation") or "")
            if status == "unavailable" and effective:
                raise ValueError("Unavailable workload checkpoint has an effective generation")
            if status in {"complete", "healthy-empty", "stale"} and not effective:
                raise ValueError("Usable workload checkpoint lacks an effective generation")
        required_families = set(WORKLOAD_QUERY_FAMILIES)
        if any(families != required_families for families in workspace_families.values()):
            raise ValueError("Workload checkpoint family set is incomplete")
        for row in [*observations, *deployments]:
            if str(row.get("checkpoint_key") or "") not in checkpoint_ids:
                raise ValueError("Workload row references an unknown checkpoint")
        for row in deployments:
            digest = str(row.get("image_digest") or "")
            if normalize_digest(digest) != digest:
                raise ValueError("Workload deployment image digest is invalid")
            if row.get("unknown_reason"):
                raise ValueError("Unknown workload evidence cannot be a deployment row")
            if not row.get("effective_generation"):
                raise ValueError("Workload deployment lacks an effective generation")

    def _extend_with_topology_tables(
        self,
        datasets: dict[str, list[dict[str, Any]]],
        *,
        snapshot: Path | str,
        observed_at: str,
        run_id: str,
    ) -> None:
        topology_rows = self._load_topology_rows(snapshot)
        entities, edges = derive_edges(topology_rows, observed=observed_at)
        governed_entities = [
            self._as_governed_topology_entity(
                row,
                run_id=run_id,
                observed_at=observed_at,
            )
            for row in entities
        ]
        entity_by_id = {
            str(row.get("entity_id") or "").casefold(): row for row in governed_entities
        }
        governed_edges = [
            self._as_governed_topology_edge(
                to_topology_edge_row(edge),
                entity_by_id=entity_by_id,
                run_id=run_id,
                observed_at=observed_at,
            )
            for edge in edges
        ]
        datasets["topology_entities"] = governed_entities
        datasets["topology_edges"] = governed_edges

    def _as_governed_topology_entity(
        self,
        row: dict[str, Any],
        *,
        run_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        entity_id = str(row.get("entity_id") or "")
        if not entity_id:
            entity_id = "topology-entity://" + _hash_json(row)[:24]
        tenant_id = str(row.get("tenant_id") or "unknown")
        subscription_id = str(
            row.get("subscription_id") or _subscription_from_id(entity_id) or "unknown"
        )
        timestamp = str(
            row.get("last_observed_timestamp")
            or row.get("created_timestamp")
            or observed_at
        )
        payload = {
            "entity_id": entity_id,
            "entity_type": str(row.get("entity_type") or ""),
            "name": str(row.get("name") or ""),
            "display_name": str(row.get("display_name") or ""),
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "source_system": str(row.get("source_system") or ""),
            "source_id": str(row.get("source_id") or ""),
            "created_timestamp": str(row.get("created_timestamp") or timestamp),
            "last_observed_timestamp": str(row.get("last_observed_timestamp") or timestamp),
            "schema_version": str(row.get("schema_version") or "1.0.0"),
            "attributes_json": str(row.get("attributes_json") or "{}"),
        }
        return {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "resource_id": entity_id,
            "timestamp": timestamp,
            "change_version": _hash_json(payload),
            "ingestion_run_id": run_id,
            **payload,
        }

    def _as_governed_topology_edge(
        self,
        row: dict[str, Any],
        *,
        entity_by_id: dict[str, dict[str, Any]],
        run_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        relationship_id = str(row.get("relationship_id") or "")
        if not relationship_id:
            relationship_id = _hash_json(row)[:24]
        subject_id = str(row.get("subject_id") or "")
        object_id = str(row.get("object_id") or "")
        subject = entity_by_id.get(subject_id.casefold(), {})
        obj = entity_by_id.get(object_id.casefold(), {})
        tenant_id = str(
            subject.get("tenant_id") or obj.get("tenant_id") or "unknown"
        )
        subscription_id = str(
            subject.get("subscription_id")
            or obj.get("subscription_id")
            or _subscription_from_id(subject_id)
            or _subscription_from_id(object_id)
            or "unknown"
        )
        timestamp = str(
            row.get("last_observed_timestamp")
            or row.get("created_timestamp")
            or observed_at
        )
        payload = {
            "relationship_id": relationship_id,
            "subject_id": subject_id,
            "predicate": str(row.get("predicate") or ""),
            "object_id": object_id,
            "confidence": float(row.get("confidence") or 0.0),
            "source": str(row.get("source") or ""),
            "created_timestamp": str(row.get("created_timestamp") or timestamp),
            "last_observed_timestamp": str(row.get("last_observed_timestamp") or timestamp),
            "assertion_state": str(row.get("assertion_state") or "accepted"),
            "schema_version": str(row.get("schema_version") or "1.0.0"),
        }
        return {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "resource_id": relationship_id,
            "timestamp": timestamp,
            "change_version": _hash_json(payload),
            "ingestion_run_id": run_id,
            **payload,
        }

    def _load_topology_rows(self, snapshot: Path | str) -> dict[str, list[dict[str, Any]]]:
        file_by_key = {
            "network_vnets": "VNet.jsonl",
            "network_security_groups": "NetworkSecurityGroup.jsonl",
            "network_interfaces": "NetworkInterface.jsonl",
            "network_route_tables": "RouteTable.jsonl",
            "network_firewalls": "AzureFirewall.jsonl",
            "network_firewall_policies": "FirewallPolicy.jsonl",
            "network_private_endpoints": "PrivateEndpoint.jsonl",
            "network_private_dns_zones": "PrivateDnsZone.jsonl",
            "network_gateways": "NetworkGateway.jsonl",
            "network_load_balancers": "LoadBalancer.jsonl",
        }

        def normalize(row: dict[str, Any]) -> dict[str, Any]:
            row_id = str(row.get("id") or row.get("sourceId") or "").casefold()
            if not row.get("type") and row.get("resourceType"):
                row["type"] = str(row.get("resourceType"))
            return {
                **row,
                "id": row_id,
                "tenantId": str(row.get("tenantId") or row.get("tenant_id") or ""),
                "subscriptionId": str(
                    row.get("subscriptionId")
                    or row.get("subscription_id")
                    or _subscription_from_id(row_id)
                ),
            }

        if self._source_root_is_remote:
            fs = self._source_fs
            root = str(snapshot)

            def read_rows(filename: str) -> list[dict[str, Any]]:
                path = f"{root}/entities/{filename}"
                if not fs.exists(path):
                    return []
                with fs.open(path, "rt") as handle:
                    return [
                        normalize(json.loads(line))
                        for line in handle.read().splitlines()
                        if line.strip()
                    ]

        else:
            root = Path(snapshot)

            def read_rows(filename: str) -> list[dict[str, Any]]:
                path = root / "entities" / filename
                if not path.is_file():
                    return []
                return [
                    normalize(json.loads(line))
                    for line in path.read_text().splitlines()
                    if line.strip()
                ]

        return {key: read_rows(filename) for key, filename in file_by_key.items()}

    def _write_topology_manifest(self, *, run_id: str, observed_at: str) -> None:
        table_uri = self.onelake.table_uri("metadata", "publication_manifest")
        current_rows = self.delta.read(table_uri) if self.delta.version(table_uri) is not None else []
        store = PublicationManifestStore.from_list([
            {
                "projection_name": str(row.get("projection_name") or ""),
                "disposition": str(row.get("disposition") or "active"),
                "compatibility_version": (
                    str(row.get("compatibility_version"))
                    if row.get("compatibility_version")
                    else None
                ),
                "retired_reason": (
                    str(row.get("retired_reason")) if row.get("retired_reason") else None
                ),
                "registered_at": str(row.get("registered_at") or ""),
                "updated_at": str(row.get("updated_at") or ""),
            }
            for row in current_rows
            if str(row.get("projection_name") or "")
        ])
        for table_name in ("topology_entities", "topology_edges"):
            entry = store.get(table_name)
            if entry.disposition == "unknown":
                store.register(table_name, disposition="active")
            else:
                store.set_disposition(table_name, "active")
        rows = []
        for entry in store.to_list():
            content = {
                "projection_name": str(entry.get("projection_name") or ""),
                "disposition": str(entry.get("disposition") or "active"),
                "compatibility_version": (
                    str(entry.get("compatibility_version"))
                    if entry.get("compatibility_version")
                    else None
                ),
                "retired_reason": (
                    str(entry.get("retired_reason")) if entry.get("retired_reason") else None
                ),
                "registered_at": str(entry.get("registered_at") or observed_at),
                "updated_at": str(entry.get("updated_at") or observed_at),
            }
            rows.append(
                {
                    "tenant_id": "system",
                    "subscription_id": "system",
                    "resource_id": (
                        "publication-manifest://"
                        + str(content["projection_name"]).casefold()
                    ),
                    "timestamp": observed_at,
                    "change_version": _hash_json(content),
                    "ingestion_run_id": run_id,
                    **content,
                }
            )
        self.delta.write(
            table_uri,
            rows,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=("resource_id",),
            schema=schema_for("metadata_publication_manifest"),
        )


def _state_row(
    run_id: str,
    source_run_id: str,
    *,
    status: str,
    timestamp: str,
    replay: bool,
    failed_records: int = 0,
    rows_processed: int = 0,
    rows_added: int = 0,
    rows_changed: int = 0,
    rows_removed: int = 0,
    watermark: str = "",
    error: str = "",
    ontology_entity_version: int | None = None,
    ontology_relationship_version: int | None = None,
) -> dict[str, Any]:
    content = {
        "status": status,
        "source_run_id": source_run_id,
        "failed_records": failed_records,
        "rows_processed": rows_processed,
        "rows_added": rows_added,
        "rows_changed": rows_changed,
        "rows_removed": rows_removed,
        "watermark": watermark,
        "error": error,
        "replay": replay,
        "ontology_entity_version": ontology_entity_version,
        "ontology_relationship_version": ontology_relationship_version,
    }
    return {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": f"ingestion-run://{run_id}",
        "timestamp": timestamp,
        "change_version": _hash_json(content),
        "ingestion_run_id": run_id,
        **content,
    }


def _required_table_version(
    results: Mapping[str, DeltaWriteResult],
    table_name: str,
) -> int:
    result = results.get(table_name)
    if result is None or result.version is None:
        raise RuntimeError(
            f"Completed Fabric publication is missing {table_name} Delta version"
        )
    return _validated_delta_version(
        result.version,
        field_name=f"{table_name} version",
    )


def _validated_delta_version(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _catalog_metadata(
    datasets: dict[str, list[dict]],
    results: dict[str, DeltaWriteResult],
    run_id: str,
    source_run_id: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0.0",
        "ingestionRunId": run_id,
        "sourceRunId": source_run_id,
        "generatedAt": _utc_now(),
        "tables": [
            {
                "name": table,
                "rowCount": len(rows),
                "deltaVersion": results.get(table).version if table in results else None,
                "columns": sorted(rows[0]) if rows else [],
            }
            for table, rows in sorted(datasets.items())
        ],
    }


def _observation_rows_at_or_before(
    rows: list[dict[str, Any]],
    *,
    projected_at: str,
) -> list[dict[str, Any]]:
    """Return only history visible to the immutable source generation."""
    return [
        dict(row)
        for row in rows
        if str(row.get("ingested_at") or "") <= projected_at
    ]


def _exposure_gold_generation_id(
    source_run_id: str,
    datasets: Mapping[str, list[dict[str, Any]]],
) -> str:
    """Bind Gold identity to every deterministic projection input."""
    source_coordinates = {
        (
            str(row.get("connection_id") or "").casefold(),
            str(row.get("source_family") or "").casefold(),
        )
        for table_name in (
            "silver_exposure_observations",
            "silver_container_vulnerability_observations",
        )
        for row in datasets.get(table_name, ())
        if str(row.get("source_family") or "").strip()
    }
    input_tables = (
        "gold_exposure_current",
        "silver_exposure_observations",
        "gold_container_exposure_current",
        "silver_container_vulnerability_observations",
        "metadata_source_status",
        "silver_exposure_enrichment",
        "silver_defender_secure_scores",
    )
    snapshot = {
        table_name: sorted(
            (
                _stable_exposure_input_row(
                    row,
                    table_name=table_name,
                )
                for row in datasets.get(table_name, ())
                if table_name != "metadata_source_status"
                or (
                    (
                        str(row.get("connection_id") or "").casefold(),
                        str(row.get("source_family") or "").casefold(),
                    )
                    in source_coordinates
                )
            ),
            key=_hash_json,
        )
        for table_name in input_tables
    }
    return "exposure-gold-" + _hash_json(
        {
            "source_run_id": source_run_id,
            "projection_inputs": snapshot,
        }
    )[:24]


def _stable_exposure_input_row(
    row: Mapping[str, Any],
    *,
    table_name: str = "",
) -> dict[str, Any]:
    volatile = {
        "change_version",
        "ingestion_run_id",
        "projection_generation_id",
        "published_at",
        "run_id",
        "run_at",
    }
    if table_name == "metadata_source_status":
        volatile.update(
            {
                "ingested_at",
                "observed_at",
                "timestamp",
                "watermark",
            }
        )
    return {
        key: value
        for key, value in row.items()
        if key not in volatile
    }


def _table_source_status_rows(
    datasets: dict[str, list[dict]],
    run_id: str,
    observed_at: str,
    *,
    requested_scope: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Build current status rows without dropping the source subscription scope.

    A combined snapshot can contain empty tables, so their scope cannot be
    inferred from table rows.  The orchestration layer supplies the requested
    subscription set for those snapshots; direct syncs continue to infer scope
    from populated rows and retain the system scope fallback for truly global
    tables.
    """
    requested_subscriptions = _scope_subscriptions(requested_scope)
    rows: list[dict[str, Any]] = []
    for table_name, table_rows in sorted(datasets.items()):
        if table_name == "metadata_source_status":
            continue
        if "_" not in table_name:
            continue
        row_subscriptions = _row_subscriptions(table_rows)
        subscriptions = requested_subscriptions or row_subscriptions or ("system",)
        for index, subscription_id in enumerate(subscriptions):
            scoped = subscription_id != "system"
            if scoped and requested_subscriptions and not row_subscriptions:
                row_count = len(table_rows)
            elif scoped:
                row_count = sum(
                    1
                    for row in table_rows
                    if str(row.get("subscription_id") or "") == subscription_id
                )
            else:
                row_count = len(table_rows)
            scope = {"subscription": [subscription_id]} if scoped else {}
            content = {
                "source_family": table_name,
                "run_id": run_id,
                "status": "succeeded",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "watermark": observed_at,
                "query_version": "1.0.0",
                "requested_scope_json": json.dumps(scope, sort_keys=True),
                "provider_status": "ok",
                "freshness": "fresh",
                "availability": "available",
                "quality": "complete",
                "error": "",
                "row_count": row_count,
                "lineage_ref": f"{table_name}-table",
            }
            content = _with_source_partition_defaults(content)
            resource_id = f"source-status://{table_name}"
            # Reuse the legacy key for the first scoped row so the first
            # corrected refresh replaces the pre-scope system row instead of
            # leaving a duplicate that would inflate unrestricted totals.
            if scoped and index:
                resource_id += f"/{subscription_id}"
            rows.append(
                {
                    "tenant_id": "system",
                    "subscription_id": subscription_id,
                    "resource_id": resource_id,
                    "timestamp": observed_at,
                    "change_version": _hash_json(content),
                    "ingestion_run_id": run_id,
                    **content,
                }
            )
    return rows


def _with_source_partition_defaults(
    row: dict[str, Any],
) -> dict[str, Any]:
    result = dict(row)
    for field in (
        "partition_key",
        "connection_id",
        "attempted_generation",
        "effective_generation",
        "attempted_at",
        "last_success_at",
        "carried_forward_age_seconds",
        "represented_count",
        "expected_count",
        "completeness",
        "safe_error_code",
        "safe_error_summary",
        "freshness_threshold_seconds",
        "freshness_source_family",
    ):
        result.setdefault(field, None)
    return result


def _source_partition_status_row(
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Map an activated source partition without discarding its LKG evidence."""

    requested_scope = row.get("requested_scope")
    if not isinstance(requested_scope, dict):
        requested_scope = {}
    subscriptions = _scope_subscriptions(requested_scope)
    partition_key = str(row.get("partition_key") or "")
    timestamp = str(
        row.get("ingested_at")
        or row.get("attempted_at")
        or row.get("observed_at")
        or "unknown"
    )
    content = {
        "source_family": str(row.get("source_family") or "unknown"),
        "status": str(row.get("status") or "unknown"),
        "observed_at": str(row.get("observed_at") or ""),
        "ingested_at": str(row.get("ingested_at") or ""),
        "watermark": str(row.get("watermark") or ""),
        "query_version": str(row.get("query_version") or ""),
        "requested_scope_json": json.dumps(requested_scope, sort_keys=True),
        "provider_status": str(row.get("provider_status") or ""),
        "freshness": str(row.get("freshness") or "unknown"),
        "availability": str(row.get("availability") or "unknown"),
        "quality": str(row.get("quality") or "unknown"),
        "error": str(row.get("error") or ""),
        "row_count": int(row.get("row_count") or 0),
        "lineage_ref": partition_key,
        "partition_key": partition_key,
        "connection_id": str(row.get("connection_id") or ""),
        "attempted_generation": str(row.get("attempted_generation") or ""),
        "effective_generation": str(row.get("effective_generation") or ""),
        "attempted_at": str(row.get("attempted_at") or ""),
        "last_success_at": str(row.get("last_success_at") or ""),
        "carried_forward_age_seconds": int(
            row.get("carried_forward_age_seconds") or 0
        ),
        "represented_count": int(row.get("represented_count") or 0),
        "expected_count": int(row.get("expected_count") or 0),
        "completeness": str(row.get("completeness") or "unavailable"),
        "safe_error_code": str(row.get("safe_error_code") or ""),
        "safe_error_summary": str(row.get("safe_error_summary") or ""),
        "freshness_threshold_seconds": int(
            row.get("freshness_threshold_seconds") or 0
        ),
        "freshness_source_family": str(
            row.get("freshness_source_family") or ""
        ),
    }
    return {
        "tenant_id": "system",
        "subscription_id": subscriptions[0] if subscriptions else "system",
        "resource_id": f"source-status://{partition_key}".casefold(),
        "timestamp": timestamp,
        "change_version": _hash_json(content),
        "ingestion_run_id": run_id,
        **content,
    }


def _scope_subscriptions(
    requested_scope: dict[str, list[str]] | None,
) -> tuple[str, ...]:
    if not requested_scope:
        return ()
    values = requested_scope.get("subscription", [])
    if isinstance(values, str):
        values = [values]
    return tuple(sorted({str(value) for value in values if str(value)}))


def _row_subscriptions(table_rows: list[dict]) -> tuple[str, ...]:
    ignored = {"", "system", "unknown", "not-applicable"}
    return tuple(
        sorted(
            {
                str(row.get("subscription_id") or "")
                for row in table_rows
                if str(row.get("subscription_id") or "") not in ignored
            }
        )
    )


def _result(
    run_id: str,
    source_run_id: str,
    status: str,
    replay: bool,
    results: dict[str, DeltaWriteResult],
    failed_records: int,
    duration: float,
) -> FabricSyncResult:
    return FabricSyncResult(
        run_id=run_id,
        source_run_id=source_run_id,
        status=status,
        replay=replay,
        rows_processed=sum(item.rows_processed for item in results.values()),
        rows_added=sum(item.rows_added for item in results.values()),
        rows_changed=sum(item.rows_changed for item in results.values()),
        rows_removed=sum(item.rows_removed for item in results.values()),
        failed_records=failed_records,
        tables=tuple(sorted(results)),
        duration_seconds=duration,
    )


def _hash_json(value: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _extend_unique_ontology_rows(
    target: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> None:
    known_ids = {
        str(row.get("resource_id") or "").strip().casefold()
        for row in target
    }
    for row in additions:
        resource_id = str(row.get("resource_id") or "").strip().casefold()
        if not resource_id:
            target.append(row)
            continue
        if resource_id in known_ids:
            continue
        target.append(row)
        known_ids.add(resource_id)


def _merge_granular_ontology_entities(
    target: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> None:
    index = {
        str(row.get("resource_id") or "").strip().casefold(): position
        for position, row in enumerate(target)
        if str(row.get("resource_id") or "").strip()
    }
    for addition in additions:
        resource_id = str(addition.get("resource_id") or "").strip().casefold()
        if not resource_id or resource_id not in index:
            target.append(addition)
            if resource_id:
                index[resource_id] = len(target) - 1
            continue

        position = index[resource_id]
        existing = target[position]
        for field in (
            "tenant_id",
            "subscription_id",
            "entity_type",
            "lifecycle_status",
        ):
            if str(existing.get(field) or "").casefold() != str(
                addition.get(field) or ""
            ).casefold():
                raise ValueError(
                    "Conflicting granular ontology entity "
                    f"{resource_id}: {field}"
                )

        payload = _merge_ontology_json_objects(
            existing.get("payload_json"),
            addition.get("payload_json"),
            field_name="payload_json",
        )
        lineage = _merge_ontology_json_objects(
            existing.get("lineage_json"),
            addition.get("lineage_json"),
            field_name="lineage_json",
            merge_list_keys=frozenset({"source_resource_ids"}),
        )
        merged = {
            **existing,
            "payload_json": json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "lineage_json": json.dumps(
                lineage,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        merged["change_version"] = entity_change_version(merged)
        target[position] = merged


def _merge_granular_ontology_relationships(
    target: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> None:
    index = {
        str(row.get("resource_id") or "").strip().casefold(): position
        for position, row in enumerate(target)
        if str(row.get("resource_id") or "").strip()
    }
    for addition in additions:
        resource_id = str(addition.get("resource_id") or "").strip().casefold()
        if not resource_id or resource_id not in index:
            target.append(addition)
            if resource_id:
                index[resource_id] = len(target) - 1
            continue

        position = index[resource_id]
        existing = target[position]
        for field in (
            "tenant_id",
            "subscription_id",
            "subject_id",
            "subject_type",
            "predicate",
            "object_id",
            "object_type",
            "source",
            "scope",
            "lifecycle_status",
        ):
            if str(existing.get(field) or "").casefold() != str(
                addition.get(field) or ""
            ).casefold():
                raise ValueError(
                    "Conflicting granular ontology relationship "
                    f"{resource_id}: {field}"
                )
        if existing.get("confidence") != addition.get("confidence"):
            raise ValueError(
                "Conflicting granular ontology relationship "
                f"{resource_id}: confidence"
            )

        payload = _merge_ontology_json_objects(
            existing.get("payload_json"),
            addition.get("payload_json"),
            field_name="payload_json",
        )
        lineage = _merge_ontology_json_objects(
            existing.get("lineage_json"),
            addition.get("lineage_json"),
            field_name="lineage_json",
            merge_list_keys=frozenset({"source_entity_ids"}),
        )
        merged = {
            **existing,
            "payload_json": json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "lineage_json": json.dumps(
                lineage,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        merged["change_version"] = relationship_change_version(merged)
        target[position] = merged


def _merge_ontology_json_objects(
    primary: Any,
    supplement: Any,
    *,
    field_name: str,
    merge_list_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    values: list[dict[str, Any]] = []
    for value in (primary, supplement):
        try:
            parsed = json.loads(str(value))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(
                f"Granular ontology entity {field_name} must be a JSON object"
            ) from exc
        if not isinstance(parsed, dict):
            raise TypeError(
                f"Granular ontology entity {field_name} must be a JSON object"
            )
        values.append(parsed)

    merged = dict(values[0])
    for key, value in values[1].items():
        if key in merge_list_keys:
            current = merged.get(key, [])
            if not isinstance(current, list) or not isinstance(value, list):
                raise ValueError(
                    f"Granular ontology entity {field_name}.{key} must be a list"
                )
            merged[key] = sorted(
                {
                    str(item)
                    for item in [*current, *value]
                    if str(item)
                }
            )
        elif key not in merged:
            merged[key] = value
        elif merged[key] == value or (
            key.casefold() in {"id", "resourcetype"}
            and isinstance(merged[key], str)
            and isinstance(value, str)
            and merged[key].casefold() == value.casefold()
        ):
            continue
        else:
            raise ValueError(
                f"Conflicting granular ontology entity {field_name}.{key}"
            )
    return merged


def _dedupe_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Guarantee a unique identity for every retained change event.

    Delta tables can retain byte-identical change rows across refreshes, and
    distinct events can share a resource, timestamp and change type. Consumers
    reject the whole batch on a duplicate identity, so identical rows are
    collapsed and remaining collisions are disambiguated with a deterministic
    ordinal suffix.
    """
    seen: set[str] = set()
    fingerprints: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("change_id") or "").strip()
        if not identity:
            continue
        fingerprint = _hash_json(
            {key: str(value) for key, value in sorted(row.items())}
        )
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        candidate = identity
        ordinal = 1
        while candidate.casefold() in seen:
            candidate = f"{identity}~{ordinal}"
            ordinal += 1
        seen.add(candidate.casefold())
        unique.append({**row, "change_id": candidate})
    return unique


def _change_identity(
    row: dict[str, Any], fallback: str = "", *, namespace: str = ""
) -> str:
    """Build a stable, unique identity for one change event.

    A single resource can legitimately record many change events, so the bare
    ``resource_id`` is not unique and every consumer rejects the batch with
    "Duplicate change identity". The identity is emitted as an opaque hash
    rather than the raw resource path because consumers redact
    ``/subscriptions/...`` text, which would otherwise collapse every
    resource-scoped identity onto the same redacted string. ``namespace``
    separates the change categories, which the consumer concatenates into a
    single identity space.
    """
    base = str(row.get("resource_id") or fallback or "").strip()
    if not base:
        return ""
    digest = _hash_json(
        [
            namespace,
            base,
            str(row.get("timestamp") or row.get("changed_at") or ""),
            str(row.get("change_version") or ""),
            str(row.get("change_type") or ""),
        ]
    )[:32]
    return f"{namespace or 'change'}-{digest}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise TypeError(f"Expected object JSON: {path}")
    return payload


def _subscription_from_id(value: str) -> str:
    match = re.search(r"/subscriptions/([^/]+)", str(value), flags=re.IGNORECASE)
    return str(match.group(1)) if match else ""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
