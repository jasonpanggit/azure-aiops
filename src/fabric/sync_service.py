from __future__ import annotations

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ontology.ontology_sync import OntologyGraphSynchronizer
from ontology.ontology_validator import OntologyValidator
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.onelake_writer import OneLakeWriter
from storage.partitioning import PartitioningPolicy

from .data_quality import DataQualityValidator, QualityReport
from .dataset_mapper import (
    ONTOLOGY_ENTITY_TYPES,
    ONTOLOGY_RELATIONSHIP_TYPES,
    InventoryDatasetMapper,
    ontology_entity_table,
    ontology_relationship_table,
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


class FabricSyncService:
    def __init__(
        self,
        *,
        source_root: Path,
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
        ontology_publisher=None,
        ontology_id: str = "",
        ontology_name: str = "Operational_Context_Graph",
        patch_policies: tuple[object, ...] = (),
        lifecycle_catalog: tuple[dict[str, Any], ...] = (),
        rollback_sleep=time.sleep,
        clock=time.monotonic,
        sql_reader=None,
    ) -> None:
        self.source_root = Path(source_root).resolve()
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
        self.ontology_publisher = ontology_publisher
        self.ontology_id = ontology_id
        self.ontology_name = ontology_name
        self.patch_policies = patch_policies
        self.lifecycle_catalog = tuple(dict(row) for row in lifecycle_catalog)
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
    ) -> FabricSyncResult:
        with self.onelake.sync_lock():
            return self._sync_locked(
                replay_source_run_id=replay_source_run_id,
                raise_on_quality_failure=raise_on_quality_failure,
            )

    def _sync_locked(
        self,
        *,
        replay_source_run_id: str = "",
        raise_on_quality_failure: bool = True,
    ) -> FabricSyncResult:
        started_clock = self.clock()
        run_id = str(uuid.uuid4())
        snapshot = self._resolve_snapshot(replay_source_run_id)
        manifest = _read_json(snapshot / "manifest.json")
        source_run_id = str(manifest.get("runId") or replay_source_run_id or "unknown")
        replay = bool(replay_source_run_id)
        started_at = _utc_now()
        self.onelake.ensure_standard_structure()
        self._write_state(
            _state_row(
                run_id,
                source_run_id,
                status="started",
                timestamp=started_at,
                replay=replay,
            )
        )

        table_results: dict[str, DeltaWriteResult] = {}
        written_versions: dict[str, tuple[str, int | None]] = {}
        failed_records = 0
        ontology_started = self.clock()
        ontology_health: dict[str, Any] = {}
        data_committed = False
        try:
            datasets = self.mapper.load(snapshot, run_id)
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
            datasets = self._synchronize_ontology(datasets, source_run_id, started_at)
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
            reports = self._validate(datasets)
            failed_records = sum(report.failed_records for report in reports)
            self._write_quality_report(run_id, source_run_id, reports, started_at)
            if failed_records:
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

            def write_table(
                item: tuple[str, list[dict[str, Any]]],
            ) -> tuple[str, str, int | None, DeltaWriteResult]:
                table_name, rows = item
                layer, logical_name = table_name.split("_", 1)
                mode = (
                    DeltaWriteMode.APPEND
                    if table_name == "metadata_audit_events"
                    else
                    DeltaWriteMode.MERGE
                    if table_name
                    in {
                        "bronze_resource_changes",
                        "silver_patch_history",
                        "silver_lifecycle_history",
                    }
                    else DeltaWriteMode.OVERWRITE
                )
                table_uri = self.onelake.table_uri(layer, logical_name)
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
                )
                return table_name, table_uri, before_version, result

            with ThreadPoolExecutor(max_workers=self.write_workers) as executor:
                futures = [
                    executor.submit(write_table, item) for item in datasets.items()
                ]
                write_error = None
                for future in as_completed(futures):
                    try:
                        table_name, table_uri, before_version, result = future.result()
                    except Exception as exc:  # noqa: BLE001 - collect all worker failures before rollback.
                        write_error = write_error or exc
                        continue
                    table_results[table_name] = result
                    if result.version != before_version:
                        written_versions[table_name] = (table_uri, before_version)
                    self.metrics.record_table(table_name, result)
                if write_error is not None:
                    raise write_error

            catalog = _catalog_metadata(datasets, table_results, run_id, source_run_id)
            self._register_fabric_assets(set(table_results))
            self.onelake.write_json("ontology/metadata/catalog.json", catalog)
            data_committed = True
            self._publish_ontology(datasets)
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
            )
            self._write_state(completed)
            self._create_shortcuts()
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
            rollback_errors = [] if data_committed else self._rollback(written_versions)
            if not isinstance(exc, ValueError) or "data quality validation failed" not in str(exc).lower():
                error_message = str(exc)
                if data_committed:
                    error_message += "; committed graph tables were retained for idempotent retry"
                if rollback_errors:
                    error_message += "; rollback incomplete: " + " | ".join(rollback_errors)
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

        entities = self.delta.read(self.onelake.table_uri("ontology", "entities"))
        relationships = self.delta.read(self.onelake.table_uri("ontology", "relationships"))
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

        states = [row for row in self.status() if row.get("status") == "completed"]
        latest = max(states, key=lambda row: str(row.get("timestamp") or ""), default={})
        entities = read("ontology", "entities")
        relationships = read("ontology", "relationships")
        # A published ontology can outlive its ingestion-state rows (for example
        # when the metadata table was truncated or written by an earlier run).
        # Fall back to the newest published entity timestamp so downstream
        # intelligence receives a real freshness instead of an empty string,
        # which every consumer rejects as an invalid timestamp.
        entity_watermark = max(
            (str(row.get("timestamp") or "") for row in entities), default=""
        )
        entity_index = {row["resource_id"]: row for row in entities}
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
            if str(payload.get("category") or "").casefold() == "security":
                security.append(
                    {
                        "target_resource_id": str(edge.get("object_id") or ""),
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

        states = [row for row in self.status() if row.get("status") == "completed"]
        latest = max(states, key=lambda row: str(row.get("timestamp") or ""), default={})
        entities = read("ontology", "entities")
        relationships = read("ontology", "relationships")
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
        states = [row for row in self.status() if row.get("status") == "completed"]
        latest = max(states, key=lambda row: str(row.get("timestamp") or ""), default={})
        raw_version = str(
            latest.get("source_run_id") or latest.get("change_version") or ""
        )
        if not raw_version:
            # Mirror semantic_snapshot()'s fallback so the cached engine version
            # matches the snapshot version and the engine is not rebuilt on
            # every call when ingestion state is missing.
            uri = self.onelake.table_uri("ontology", "entities")
            entities = self.delta.read(uri) if self.delta.version(uri) is not None else []
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
            "installations": read("silver", "patch_installations"),
            "history": read("silver", "patch_history"),
            "policies": policies,
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
            for row in read("silver", "remediation_action_catalog")
        ]
        policies = [
            {
                "policy_id": str(row.get("policy_id") or ""),
                "conditions": parsed(row, "conditions_json", dict),
                "roles": parsed(row, "roles_json", list),
            }
            for row in read("silver", "remediation_approval_policies")
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
        entity_uri = self.onelake.table_uri("ontology", "entities")
        relationship_uri = self.onelake.table_uri("ontology", "relationships")
        previous_entities = self.delta.read(entity_uri) if self.delta.version(entity_uri) is not None else []
        previous_relationships = (
            self.delta.read(relationship_uri)
            if self.delta.version(relationship_uri) is not None
            else []
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
        datasets = self.mapper.load(snapshot, "validation")
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

    def _resolve_snapshot(self, replay_source_run_id: str) -> Path:
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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
