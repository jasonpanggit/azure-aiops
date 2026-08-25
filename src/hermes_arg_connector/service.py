from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from .azure import AzureCliArgClient, AzureMcpClient
from .config import ConnectorConfig
from .locking import RunLock
from .normalize import Normalizer
from .queries import QueryCatalog
from .source import AzureResourceGraphSource
from .state import StateStore
from .storage import DatasetStore


class IngestionService:
    def __init__(self, config: ConnectorConfig, source=None, clock: Callable[[], datetime] | None = None) -> None:
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

    def run(self) -> dict:
        with RunLock(self.config.output_dir):
            return self._run_locked()

    def _run_locked(self) -> dict:
        started = self.clock().astimezone(UTC).replace(microsecond=0)
        previous = self.state.load()
        watermark_is_current = previous.get("watermarkVersion") == 2
        previous_watermark = previous.get("resourceChangesWatermark") if watermark_is_current else None
        since = _parse_time(previous_watermark)

        subscriptions = list(self.config.subscriptions)
        discovered = self.source.list_subscriptions()
        if not subscriptions:
            subscriptions = [
                str(item.get("subscriptionId") or item.get("id") or "")
                for item in discovered
                if item.get("subscriptionId") or item.get("id")
            ]
        if not subscriptions:
            raise RuntimeError("No Azure subscriptions were returned by Azure MCP")

        specs = QueryCatalog(self.config.change_overlap_minutes).build(
            since, include_management_groups=bool(self.config.management_groups)
        )
        query_results = self.source.fetch(specs, subscriptions)
        for spec in specs:
            for row in query_results.get(spec.name, []):
                row.setdefault("query_version", "1.0.0")
                row.setdefault("requested_scope", {"subscription": sorted(subscriptions)})
                row.setdefault("provider_status", "ok")
        previous_changes = self.store.read_dataset("changes/resource_changes")
        normalization_payload = dict(query_results)
        normalization_payload["resource_changes"] = _merge_changes(
            previous_changes,
            query_results.get("resource_changes", []),
        )
        run_id = str(uuid.uuid4())
        graph = Normalizer(self.config.connection_context).normalize(normalization_payload, started, run_id=run_id, requested_scope={"subscription": sorted(subscriptions)})
        _preserve_created_timestamps(graph, self.store)
        _preserve_source_watermarks(graph, self.store)
        change_watermark = _max_change_watermark(previous_watermark, graph.changes)
        manifest = self.store.publish(
            graph,
            query_results,
            {
                "runId": run_id,
                "startedAt": _iso(started),
                "subscriptions": sorted(subscriptions),
                "queryVersion": "1.0.0",
                "status": "completed",
            },
        )
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
    prior_evidence = {row.get("evidence_id"): row for row in store.read_dataset("situations/evidence")}
    for evidence in graph.evidence:
        previous = prior_evidence.get(evidence.get("evidence_id"))
        if previous and previous.get("ingested_at"):
            evidence["ingested_at"] = previous["ingested_at"]
    evidence_times = {row.get("evidence_id"): row.get("ingested_at") for row in graph.evidence if row.get("evidence_id")}
    for event in graph.audit_events:
        if event.get("action") == "evidence.ingested" and event.get("evidence_ids"):
            event["timestamp"] = evidence_times.get(event["evidence_ids"][0], event.get("timestamp"))
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
    previous = {row.get("source_family"): row for row in store.read_dataset("situations/source_status")}
    for status in graph.source_status:
        if status.get("status") != "succeeded":
            status["watermark"] = ""
            continue
        old = str(previous.get(status.get("source_family"), {}).get("watermark") or "")
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
