from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fabric.config import SourceFreshnessThresholds, freshness_source_family
from intelligence.vulnerability.acquisition import (
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionSuccess,
)
from intelligence.vulnerability.workload_inventory import (
    WorkloadProjection,
    acquire_workload_inventory,
    activate_workload_partitions,
)
from operations.exposure_metrics import ExposureMetrics
from storage.datasets import DatasetStore as GenerationDatasetStore
from storage.locking import RunLock
from storage.renewing_run import renewing_run_lock

from .azure_clients import AzureCliArgClient, AzureMcpClient
from .config import ConnectorConfig
from .defender_normalize import is_container_image_assessment
from .discovery_source import AzureResourceGraphSource, CostActualsSource
from .graph_normalize import Normalizer
from .ingestion_state import StateStore
from .ingestion_storage import DatasetStore
from .inventory_read_adapter import InventoryReadAdapter
from .monitor_logs import AzureMonitorLogsClient
from .ontology_metadata import generate_ontology_metadata
from .query_catalog import QueryCatalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourcePartitionProjection:
    """Effective rows and status for independently activated source partitions."""

    rows_by_query: dict[str, list[dict[str, Any]]]
    partition_rows: tuple[dict[str, Any], ...]
    statuses: tuple[dict[str, Any], ...]


def activate_source_partitions(
    *,
    outcomes: dict[str, AcquisitionOutcome],
    attempted_generation: str,
    completed_at: str,
    previous_partition_rows: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    previous_statuses: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    metrics: ExposureMetrics | None = None,
) -> SourcePartitionProjection:
    """Select each connection/family/scope partition without false clears.

    A partition advances only when every query belonging to that source family
    completed with proven paging. A failed attempt carries its own prior
    effective rows (including a proven healthy-empty partition) or becomes
    unavailable when no last-known-good generation exists.
    """

    grouped: dict[str, list[AcquisitionOutcome]] = {}
    for outcome in outcomes.values():
        key = _source_partition_key(
            outcome.connection_id,
            outcome.source_family,
            outcome.scope,
        )
        grouped.setdefault(key, []).append(outcome)

    previous_status_by_key = {
        str(row.get("partition_key") or ""): dict(row)
        for row in previous_statuses
        if row.get("partition_key")
    }
    previous_rows_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in previous_partition_rows:
        key = str(row.get("partition_key") or "")
        if key:
            previous_rows_by_key.setdefault(key, []).append(dict(row))

    effective_rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    rows_by_query = {name: [] for name in outcomes}
    for partition_key, partition_outcomes in sorted(grouped.items()):
        partition_outcomes.sort(key=lambda item: item.query_name)
        failures = [
            outcome
            for outcome in partition_outcomes
            if isinstance(outcome, AcquisitionFailure)
        ]
        prior_status = previous_status_by_key.get(partition_key)
        prior_rows = previous_rows_by_key.get(partition_key, [])
        has_lkg = bool(
            prior_status
            and prior_status.get("effective_generation")
            and prior_status.get("completeness")
            in {"complete", "healthy-empty", "stale"}
        )

        if not failures:
            successes = [
                outcome
                for outcome in partition_outcomes
                if isinstance(outcome, AcquisitionSuccess)
            ]
            partition_rows: list[dict[str, Any]] = []
            seen_partition_rows: set[tuple[str, str]] = set()
            for outcome in successes:
                for row in outcome.rows:
                    partition_row = _source_partition_row(
                        partition_key=partition_key,
                        outcome=outcome,
                        row=row,
                        effective_generation=attempted_generation,
                    )
                    identity = (
                        str(partition_row["query_name"]),
                        str(partition_row["row_key"]),
                    )
                    if identity in seen_partition_rows:
                        continue
                    seen_partition_rows.add(identity)
                    partition_rows.append(partition_row)
            effective_rows.extend(partition_rows)
            for row in partition_rows:
                rows_by_query.setdefault(str(row["query_name"]), []).append(
                    json.loads(str(row["payload_json"]))
                )
            last_success_at = max(
                _iso(outcome.completed_at) for outcome in successes
            )
            watermark = max(
                (
                    str(outcome.watermark)
                    for outcome in successes
                    if outcome.watermark
                ),
                default="",
            )
            row_count = len(partition_rows)
            statuses.append(
                _source_partition_status(
                    partition_key=partition_key,
                    outcomes=partition_outcomes,
                    attempted_generation=attempted_generation,
                    effective_generation=attempted_generation,
                    completed_at=completed_at,
                    last_success_at=last_success_at,
                    watermark=watermark,
                    row_count=row_count,
                    completeness="healthy-empty" if row_count == 0 else "complete",
                )
            )
            _record_source_partition_metrics(
                metrics,
                source_family=partition_outcomes[0].source_family,
                attempted_rows=row_count,
                effective_rows=row_count,
                previous_effective_rows=int(
                    (prior_status or {}).get("row_count") or len(prior_rows)
                ),
                source_age_seconds=0,
                outcome="succeeded",
                completeness="healthy-empty" if row_count == 0 else "complete",
            )
            continue

        failure = failures[0]
        if has_lkg:
            effective_rows.extend(prior_rows)
            for row in prior_rows:
                rows_by_query.setdefault(str(row["query_name"]), []).append(
                    json.loads(str(row["payload_json"]))
                )
            last_success_at = str(prior_status.get("last_success_at") or "")
            statuses.append(
                _source_partition_status(
                    partition_key=partition_key,
                    outcomes=partition_outcomes,
                    attempted_generation=attempted_generation,
                    effective_generation=str(
                        prior_status.get("effective_generation") or ""
                    ),
                    completed_at=completed_at,
                    last_success_at=last_success_at,
                    watermark=str(prior_status.get("watermark") or ""),
                    row_count=len(prior_rows),
                    completeness="stale",
                    failure=failure,
                    carried_forward_age_seconds=_age_seconds(
                        last_success_at,
                        completed_at,
                    ),
                )
            )
            _record_source_partition_metrics(
                metrics,
                source_family=partition_outcomes[0].source_family,
                attempted_rows=0,
                effective_rows=len(prior_rows),
                previous_effective_rows=int(
                    (prior_status or {}).get("row_count") or len(prior_rows)
                ),
                source_age_seconds=_age_seconds(
                    last_success_at,
                    completed_at,
                ),
                outcome="partial",
                completeness="stale",
            )
            continue

        statuses.append(
            _source_partition_status(
                partition_key=partition_key,
                outcomes=partition_outcomes,
                attempted_generation=attempted_generation,
                effective_generation="",
                completed_at=completed_at,
                last_success_at="",
                watermark="",
                row_count=0,
                completeness="unavailable",
                failure=failure,
            )
        )
        _record_source_partition_metrics(
            metrics,
            source_family=partition_outcomes[0].source_family,
            attempted_rows=0,
            effective_rows=0,
            previous_effective_rows=0,
            source_age_seconds=0,
            outcome="unavailable",
            completeness="unavailable",
        )

    return SourcePartitionProjection(
        rows_by_query=rows_by_query,
        partition_rows=tuple(effective_rows),
        statuses=tuple(statuses),
    )


def _record_source_partition_metrics(
    metrics: ExposureMetrics | None,
    *,
    source_family: str,
    attempted_rows: int,
    effective_rows: int,
    previous_effective_rows: int,
    source_age_seconds: int,
    outcome: str,
    completeness: str,
) -> None:
    if metrics is None or source_family not in {
        "azure_update_manager_missing",
        "defender_subassessment",
        "defender_image",
        "workloads",
        "enrichment",
    }:
        return
    metrics.record_ingestion_cycle(
        source_family=source_family,
        target_kind=(
            "container_image"
            if source_family in {"defender_image", "workloads"}
            else "server"
        ),
        attempted_rows=attempted_rows,
        effective_rows=effective_rows,
        previous_effective_rows=previous_effective_rows,
        source_age_seconds=source_age_seconds,
        outcome=outcome,
        completeness=completeness,
    )


def _record_workload_projection_metrics(
    metrics: ExposureMetrics,
    workload: WorkloadProjection,
    *,
    completed_at: str,
    previous_checkpoints: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> None:
    """Emit one aggregate workload cycle without workspace/connection labels."""

    checkpoints = tuple(workload.checkpoints)
    states = {
        str(row.get("completeness") or row.get("status") or "unknown")
        .strip()
        .casefold()
        for row in checkpoints
    }
    if not checkpoints or states == {"unavailable"}:
        outcome = "unavailable"
        completeness = "unavailable"
    elif "unavailable" in states or "stale" in states:
        outcome = "partial"
        completeness = "stale" if states <= {"stale"} else "partial"
    else:
        outcome = "succeeded"
        completeness = (
            "healthy-empty"
            if states == {"healthy-empty"}
            else "complete"
        )
    attempted_rows = sum(
        int(row.get("row_count") or 0)
        for row in checkpoints
        if str(row.get("completeness") or row.get("status") or "")
        in {"complete", "healthy-empty"}
    )
    effective_rows = sum(
        int(row.get("row_count") or 0) for row in checkpoints
    )
    previous_by_key = {
        str(row.get("checkpoint_key") or ""): int(
            row.get("row_count") or 0
        )
        for row in previous_checkpoints
        if row.get("checkpoint_key")
    }
    previous_effective_rows = sum(
        previous_by_key.get(
            str(row.get("checkpoint_key") or ""),
            int(row.get("row_count") or 0),
        )
        for row in checkpoints
    )
    source_age_seconds = max(
        (
            _age_seconds(
                str(row.get("last_success_at") or ""),
                completed_at,
            )
            for row in checkpoints
        ),
        default=0,
    )
    metrics.record_ingestion_cycle(
        source_family="workloads",
        target_kind="container_image",
        attempted_rows=attempted_rows,
        effective_rows=effective_rows,
        previous_effective_rows=previous_effective_rows,
        source_age_seconds=source_age_seconds,
        outcome=outcome,
        completeness=completeness,
    )
    represented = len(workload.deployments)
    unknown = len(workload.unknown_reasons)
    metrics.record_coverage(
        represented=represented,
        total=represented + unknown,
        unknown=unknown,
        target_kind="container_image",
        completeness=completeness,
    )


def _source_partition_key(
    connection_id: str,
    source_family: str,
    scope: tuple[str, ...],
) -> str:
    identity = json.dumps(
        [
            str(connection_id or "default").strip().casefold(),
            str(source_family).strip().casefold(),
            sorted(str(value).strip().casefold() for value in scope if str(value).strip()),
        ],
        separators=(",", ":"),
    )
    return f"exposure-source-v1:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


def _source_partition_row(
    *,
    partition_key: str,
    outcome: AcquisitionSuccess,
    row: Any,
    effective_generation: str,
) -> dict[str, Any]:
    payload_json = json.dumps(
        dict(row),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    source_id = str(
        row.get("id")
        or row.get("resource_id")
        or row.get("resourceId")
        or hashlib.sha256(payload_json.encode()).hexdigest()
    ).strip().casefold()
    # Some ARG tables (e.g. resourcechanges, subassessments) legitimately
    # return multiple distinct rows sharing the same `id` -- one row per
    # event/finding for that resource, not one row per resource. Folding the
    # full payload hash into the key lets those coexist while still catching
    # genuine duplicates (identical id + identical payload), which is what
    # an unstable ARG page ordering (missing `order by`) can produce.
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    row_key = hashlib.sha256(
        json.dumps(
            [outcome.query_name, source_id, payload_hash],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "partition_key": partition_key,
        "query_name": outcome.query_name,
        "row_key": row_key,
        "payload_json": payload_json,
        "effective_generation": effective_generation,
    }


def _source_partition_status(
    *,
    partition_key: str,
    outcomes: list[AcquisitionOutcome],
    attempted_generation: str,
    effective_generation: str,
    completed_at: str,
    last_success_at: str,
    watermark: str,
    row_count: int,
    completeness: str,
    failure: AcquisitionFailure | None = None,
    carried_forward_age_seconds: int = 0,
) -> dict[str, Any]:
    first = outcomes[0]
    scope = sorted({value for outcome in outcomes for value in outcome.scope})
    versions = sorted(
        {
            str(outcome.sequence).split(":", 1)[0]
            for outcome in outcomes
            if isinstance(outcome, AcquisitionSuccess)
        }
    )
    available = completeness != "unavailable"
    freshness_family = freshness_source_family(first.source_family)
    freshness_threshold = SourceFreshnessThresholds().threshold_for(
        freshness_family
    )
    freshness = _source_freshness(
        last_success_at or watermark,
        completed_at,
        freshness_threshold,
    )
    return {
        "partition_key": partition_key,
        "connection_id": first.connection_id or "default",
        "source_family": first.source_family,
        "run_id": attempted_generation,
        "status": (
            "succeeded"
            if completeness in {"complete", "healthy-empty"}
            else "partial"
            if completeness == "stale"
            else "unavailable"
        ),
        "observed_at": last_success_at,
        "ingested_at": completed_at,
        "watermark": watermark,
        "query_version": ",".join(versions),
        "requested_scope": {"subscription": scope},
        "provider_status": "failed" if failure is not None else "ok",
        "freshness": freshness,
        "availability": "degraded" if completeness == "stale" else "available" if available else "unavailable",
        "quality": "incomplete" if failure is not None else "complete",
        "error": failure.error_summary if failure is not None else "",
        "attempted_generation": attempted_generation,
        "effective_generation": effective_generation,
        "attempted_at": min(_iso(outcome.attempted_at) for outcome in outcomes),
        "last_success_at": last_success_at,
        "row_count": row_count,
        "carried_forward_age_seconds": carried_forward_age_seconds,
        "represented_count": 1 if available else 0,
        "expected_count": 1,
        "completeness": completeness,
        "safe_error_code": failure.error_code.value if failure is not None else "",
        "safe_error_summary": failure.error_summary if failure is not None else "",
        "freshness_threshold_seconds": freshness_threshold,
        "freshness_source_family": freshness_family,
    }


def _age_seconds(earlier: str, later: str) -> int:
    previous = _parse_time(earlier)
    current = _parse_time(later)
    if previous is None or current is None:
        return 0
    return max(0, int((current - previous).total_seconds()))


def _source_freshness(
    observed_at: str,
    reference_at: str,
    threshold_seconds: int,
) -> str:
    observed = _parse_time(observed_at)
    reference = _parse_time(reference_at)
    if observed is None or reference is None:
        return "unknown"
    age_seconds = (reference - observed).total_seconds()
    if age_seconds < 0:
        return "unknown"
    return "fresh" if age_seconds <= threshold_seconds else "stale"


def _workload_defender_rows(
    query_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Return only Defender row families supported by workload matching.

    Assessment acquisition includes recommendation rows for many resource
    types, so reuse the canonical container-image classifier before adding
    those rows. Subassessments remain accepted for providers that expose the
    established ``additionalData.imageDigest`` contract.
    """

    assessments = [
        dict(row)
        for row in query_results.get("defender_assessments", ())
        if is_container_image_assessment(row)
    ]
    subassessments = [
        dict(row)
        for row in query_results.get("defender_subassessments", ())
    ]
    return [*assessments, *subassessments]


class IngestionService:
    def __init__(
        self,
        config: ConnectorConfig,
        source=None,
        clock: Callable[[], datetime] | None = None,
        cost_source: CostActualsSource | None = None,
        logs_client: AzureMonitorLogsClient | None = None,
        inventory_read_port: Any = None,
        metrics: ExposureMetrics | None = None,
    ) -> None:
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self.state = StateStore(config.output_dir)
        self.store = DatasetStore(config.output_dir, retain_raw_queries=config.retain_raw_queries)
        self.source = source or AzureResourceGraphSource(
            mcp=AzureMcpClient(
                command_prefix=config.azure_mcp_command,
                timeout=config.command_timeout_seconds,
            ),
            arg=AzureCliArgClient(
                page_size=config.page_size,
                max_pages=config.max_pages,
                timeout=config.command_timeout_seconds,
            ),
            tenant_id=config.tenant_id,
            max_workers=config.max_query_workers,
            management_group_ids=config.management_groups,
        )
        self.cost_source = cost_source
        self.logs_client = logs_client
        # Only required when config.identity_source == "inventory" (Task 3).
        # Left None otherwise -- no runtime behavior changes for the default
        # "arg" source until 08-03's operator-gated cutover explicitly flips it.
        self.inventory_read_port = inventory_read_port
        self.metrics = metrics or ExposureMetrics()

    def run(self) -> dict:
        with renewing_run_lock(RunLock(self.config.output_dir)) as lock:
            return self._run_locked(assert_lock_held=lock.assert_held)

    def _run_locked(self, *, assert_lock_held: Callable[[], None]) -> dict:
        started = self.clock().astimezone(UTC).replace(microsecond=0)
        previous = self.state.load()
        watermark_is_current = previous.get("watermarkVersion") == 2
        previous_watermark = previous.get("resourceChangesWatermark") if watermark_is_current else None
        since = _parse_time(previous_watermark)

        subscriptions = list(self.config.subscriptions)
        if not subscriptions:
            # Only fall back to Azure MCP subscription discovery when no
            # subscriptions are pinned in config -- a deployment that pins an
            # explicit subscription list must not have a hard runtime
            # dependency on the azmcp CLI, which is a heavy, fragile native
            # binary (ICU/dbus/msalruntime shared-library requirements) that
            # a scheduled Fabric-triggered run should not need at all.
            discovered = self.source.list_subscriptions()
            subscriptions = [
                str(item.get("subscriptionId") or item.get("id") or "")
                for item in discovered
                if item.get("subscriptionId") or item.get("id")
            ]
        if not subscriptions:
            raise RuntimeError("No Azure subscriptions were returned by Azure MCP")

        from onboarding.query_contract import QuerySpec

        workspace_spec = QuerySpec(
            "inventory_log_analytics_workspaces",
            "Resources",
            (
                "Resources "
                "| where type =~ 'microsoft.operationalinsights/workspaces' "
                "| project id, name, subscriptionId, resourceGroup, "
                "workspaceId=tostring(properties.customerId) "
                "| order by id asc"
            ),
            False,
            source_family="log_analytics_workspace_discovery",
            version="inventory-law-workspaces-v1",
        )
        specs = [
            *QueryCatalog(self.config.change_overlap_minutes).build(
                since, include_management_groups=bool(self.config.management_groups)
            ),
            workspace_spec,
        ]
        # Cost Management is independent of ARG discovery. Overlap both
        # bounded acquisition paths; normalization and publication stay
        # serialized below.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingestion") as executor:
            query_future = executor.submit(self.source.fetch, specs, subscriptions)
            cost_future = executor.submit(self._fetch_cost_actuals, subscriptions, started)
            query_results = query_future.result()
            cost_rows = cost_future.result()
        completed_at = _iso(self.clock())
        run_id = str(uuid.uuid4())
        source_projection: SourcePartitionProjection | None = None
        if query_results and all(
            isinstance(value, (AcquisitionSuccess, AcquisitionFailure))
            for value in query_results.values()
        ):
            source_projection = activate_source_partitions(
                outcomes=query_results,
                attempted_generation=run_id,
                completed_at=completed_at,
                previous_partition_rows=self.store.read_dataset(
                    "exposure/source_partition_rows"
                ),
                previous_statuses=self.store.read_dataset(
                    "situations/source_status"
                ),
                metrics=self.metrics,
            )
            query_results = source_projection.rows_by_query
        for spec in specs:
            for row in query_results.get(spec.name, []):
                row.setdefault("query_version", spec.version)
                row.setdefault("requested_scope", {"subscription": sorted(subscriptions)})
                row.setdefault("provider_status", "ok")
        previous_changes = self.store.read_dataset("changes/resource_changes")
        normalization_payload = dict(query_results)
        if self.config.identity_source == "inventory":
            normalization_payload.update(self._identity_rows_from_inventory(subscriptions))
        normalization_payload["resource_changes"] = _merge_changes(
            previous_changes,
            query_results.get("resource_changes", []),
        )
        normalization_payload["cost_actuals"] = cost_rows
        previous_workload_checkpoints = self.store.read_dataset(
            "exposure/workload_source_checkpoints"
        )
        workload_outcomes = acquire_workload_inventory(
            logs_client=self.logs_client,
            connection_id=str(
                self.config.connection_context.get("connection_id") or "default"
            ),
            discovered_workspaces=query_results.get(
                "inventory_log_analytics_workspaces", []
            ),
            clock=self.clock,
        )
        workload = (
            activate_workload_partitions(
                outcomes=workload_outcomes,
                defender_rows=_workload_defender_rows(query_results),
                attempted_generation=run_id,
                completed_at=completed_at,
                previous_observations=self.store.read_dataset(
                    "exposure/workload_observations"
                ),
                previous_deployments=self.store.read_dataset(
                    "exposure/workload_deployments"
                ),
                previous_checkpoints=previous_workload_checkpoints,
            )
            if workload_outcomes
            else WorkloadProjection(
                observations=tuple(
                    self.store.read_dataset("exposure/workload_observations")
                ),
                deployments=tuple(
                    self.store.read_dataset("exposure/workload_deployments")
                ),
                checkpoints=tuple(
                    self.store.read_dataset("exposure/workload_source_checkpoints")
                ),
                unknown_reasons=("workspace_discovery_unavailable",),
            )
        )
        _record_workload_projection_metrics(
            self.metrics,
            workload,
            completed_at=completed_at,
            previous_checkpoints=previous_workload_checkpoints,
        )
        graph = Normalizer(self.config.connection_context).normalize(
            normalization_payload,
            started,
            run_id=run_id,
            requested_scope={"subscription": sorted(subscriptions)},
        )
        if source_projection is not None:
            partition_families = {
                str(row["source_family"]) for row in source_projection.statuses
            }
            partition_queries = set(source_projection.rows_by_query)
            graph.source_status = [
                row
                for row in graph.source_status
                if str(row.get("source_family") or "")
                not in partition_families | partition_queries
            ]
            graph.source_status.extend(
                dict(row) for row in source_projection.statuses
            )
        _preserve_created_timestamps(graph, self.store)
        _preserve_source_watermarks(graph, self.store)
        change_watermark = _max_change_watermark(previous_watermark, graph.changes)
        assert_lock_held()
        manifest = self._publish_generation(
            graph,
            query_results,
            {
                "runId": run_id,
                "startedAt": _iso(started),
                "completedAt": completed_at,
                "subscriptions": sorted(subscriptions),
                "queryVersion": "1.0.0",
                "status": "completed",
            },
            workload=workload,
            source_partition_rows=(
                source_projection.partition_rows
                if source_projection is not None
                else tuple(
                    self.store.read_dataset("exposure/source_partition_rows")
                )
            ),
            assert_lock_held=assert_lock_held,
        )
        assert_lock_held()
        self.state.save(
            {
                "lastSuccessfulRun": _iso(started),
                "resourceChangesWatermark": change_watermark,
                "watermarkVersion": 2,
                "lastRunId": run_id,
                "contentHash": manifest["contentHash"],
                "subscriptions": sorted(subscriptions),
            }
        )
        return manifest

    def _publish_generation(
        self,
        graph: Any,
        query_results: dict[str, list[dict]],
        run_metadata: dict[str, Any],
        *,
        workload: WorkloadProjection,
        source_partition_rows: tuple[dict[str, Any], ...] = (),
        assert_lock_held: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Publish graph and workload products behind one generation pointer."""

        datasets: dict[str, list[dict]] = {
            **{
                f"entities/{entity_type}": rows
                for entity_type, rows in graph.entities.items()
            },
            "relationships/relationships": graph.relationships,
            "changes/resource_changes": graph.changes,
            "exposure/workload_observations": list(workload.observations),
            "exposure/workload_deployments": list(workload.deployments),
            "exposure/workload_source_checkpoints": list(workload.checkpoints),
            "exposure/source_partition_rows": list(source_partition_rows),
        }
        for collection in (
            "situations",
            "evidence",
            "links",
            "audit_events",
            "source_status",
        ):
            rows = getattr(graph, collection, None)
            if rows is not None:
                datasets[f"situations/{collection}"] = list(rows)
        return GenerationDatasetStore.publish(
            self.store,
            datasets,
            query_results,
            run_metadata,
            ontology=generate_ontology_metadata(graph.entities),
            assert_lock_held=assert_lock_held,
        )

    def _identity_rows_from_inventory(self, subscriptions: list[str]) -> dict[str, list[dict]]:
        """Sources `resources`/`resource_containers` rows via the inventory
        read port instead of `self.source.fetch()`, for those two specs only
        (Task 3). All other specs (network_*, patch, advisor, cost, role,
        changes) are untouched -- they are not yet inventory-owned."""
        if self.inventory_read_port is None:
            raise RuntimeError(
                "identity_source='inventory' requires an inventory_read_port to be configured"
            )
        from api.scope import Scope

        scope = Scope.from_mapping({"subscription": sorted(subscriptions)})
        resource_rows = InventoryReadAdapter(self.inventory_read_port).resources(scope)
        containment_rows = self.inventory_read_port.list_containment(scope)
        return InventoryReadAdapter.to_arg_rows(containment_rows, resource_rows)

    def _fetch_cost_actuals(self, subscriptions: list[str], started: datetime) -> list[dict]:
        """Fetch Cost Management actuals as a best-effort side channel.

        Cost Management is a distinct Azure API with its own throughput limits
        and failure modes; it is not part of Azure Resource Graph discovery.
        A Cost Management outage or throttling must never fail or block the
        semantic graph sync, so this step is isolated and always degrades to
        an empty result rather than raising.
        """
        if not self.config.cost_management_enabled or self.cost_source is None:
            return []
        try:
            return self.cost_source.fetch(
                subscriptions,
                end=started,
                lookback=self.config.cost_management_lookback,
            )
        except Exception:
            logger.warning(
                "Cost Management fetch failed; continuing discovery without cost actuals",
                exc_info=True,
            )
            return []


def _merge_changes(previous: list[dict], current: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for index, row in enumerate([*previous, *current]):
        row_id = str(row.get("id") or "").strip().lower()
        if not row_id and str(row.get("status") or "").casefold() in {"failed", "unavailable"}:
            row_id = f"__provider_failure__{index}"
        if row_id:
            merged[row_id] = row
    return list(merged.values())


def _preserve_created_timestamps(graph, store: DatasetStore) -> None:
    prior_evidence = {
        row.get("evidence_id"): row for row in store.read_dataset("situations/evidence")
    }
    for evidence in graph.evidence:
        previous = prior_evidence.get(evidence.get("evidence_id"))
        if previous and previous.get("ingested_at"):
            evidence["ingested_at"] = previous["ingested_at"]
    evidence_times = {
        row.get("evidence_id"): row.get("ingested_at")
        for row in graph.evidence
        if row.get("evidence_id")
    }
    for event in graph.audit_events:
        if event.get("action") == "evidence.ingested":
            evidence_ids = event.get("evidence_ids") or []
            if evidence_ids and evidence_ids[0] in evidence_times:
                event["timestamp"] = evidence_times[evidence_ids[0]]
    for entity_type, entities in graph.entities.items():
        prior = {row.get("id"): row for row in store.read_dataset(f"entities/{entity_type}")}
        for entity in entities:
            previous = prior.get(entity.get("id"))
            if previous and previous.get("createdTimestamp"):
                entity["createdTimestamp"] = previous["createdTimestamp"]
    prior_edges = {
        row.get("relationshipId"): row
        for row in store.read_dataset("relationships/relationships")
    }
    for edge in graph.relationships:
        previous = prior_edges.get(edge.get("relationshipId"))
        if previous and previous.get("createdTimestamp"):
            edge["createdTimestamp"] = previous["createdTimestamp"]


def _preserve_source_watermarks(graph, store: DatasetStore) -> None:
    previous = {
        row.get("partition_key") or row.get("source_family"): row
        for row in store.read_dataset("situations/source_status")
    }
    for status in graph.source_status:
        if status.get("completeness") in {"stale", "unavailable"}:
            continue
        if status.get("status") != "succeeded":
            status["watermark"] = ""
            continue
        key = status.get("partition_key") or status.get("source_family")
        old = str(previous.get(key, {}).get("watermark") or "")
        current = str(status.get("watermark") or "")
        if old and (not current or old > current):
            status["watermark"] = old


def _max_change_watermark(previous: str | None, changes: list[dict]) -> str | None:
    candidates = [value for value in [previous, *(row.get("changedAt") for row in changes)] if value]
    if not candidates:
        return None
    parsed = [(_parse_time(str(value)), str(value)) for value in candidates]
    valid = [(stamp, value) for stamp, value in parsed if stamp is not None]
    if not valid:
        return previous
    return _iso(max(stamp for stamp, _ in valid))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
