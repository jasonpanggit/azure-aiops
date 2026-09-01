"""Connection-scoped sync lifecycle.

Every run is bound to one :class:`SubscriptionConnection`, produces an
ingestion run id, and updates that connection's :class:`SyncState` only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ontology.subscription_connection import SubscriptionConnection, SyncState
from storage.fs import join_root, resolve_root

DEFAULT_STALE_AFTER_HOURS = 24

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    connection_id: str
    run_id: str
    status: str
    started_at: str
    completed_at: str
    record_count: int = 0
    message: str | None = None
    manifest: dict[str, Any] | None = None
    # Optional discovery-observability rollup (entities/relationships added,
    # dangling-relationship count, confidence distribution, ...), populated
    # opportunistically from the ingestion manifest when the ingestion
    # factory happens to surface one (see ``_discovery_metrics`` below).
    # ``None`` by default so existing callers/tests that construct
    # ``SyncResult`` without this field see no behavior change.
    discovery_metrics: dict[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "record_count": self.record_count,
            "message": self.message,
            "manifest": self.manifest,
            "discovery_metrics": self.discovery_metrics,
        }


#: Ordered stages a connection-scoped sync passes through when a
#: ``publish_factory`` is configured. Exposed so callers (e.g. the API layer)
#: can render a fixed progress sequence without guessing percentages.
SYNC_STAGES: tuple[str, ...] = (
    "queued",
    "discovering",
    "merging",
    "publishing_ontology",
    "writing_fabric_tables",
    "succeeded",
)


class ConnectionSyncCoordinator:
    """Runs connection-scoped ingestion and maintains the connection's SyncState.

    ``ingestion_factory`` receives the connection and returns an object with a
    ``run()`` method. Keeping it injectable means the connection boundary owns
    scoping rather than the ingestion service inferring it from global config.

    ``publish_factory``, if provided, is called with the connection after its
    own ingestion succeeds and must return an object with a ``run()`` method
    that rebuilds that connection's inventory/ontology publication and writes
    the result to Fabric. This is the same publication work exposed by
    ``aiops-inventory inventory-refresh``, made reachable from an interactive
    "Sync" click without refreshing unrelated connections.
    Leaving it ``None`` keeps this coordinator's existing per-connection-only
    behavior (used by tests and any caller that does not want the merge step
    to run inline).
    """

    def __init__(
        self,
        output_dir: str,
        ingestion_factory: Callable[[SubscriptionConnection], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
        publish_factory: Callable[[SubscriptionConnection], Any] | None = None,
    ) -> None:
        self.output_dir = resolve_root(str(output_dir))
        self.ingestion_factory = ingestion_factory
        self.publish_factory = publish_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        if stale_after_hours < 1:
            raise ValueError("stale_after_hours must be positive")
        self.stale_after_hours = stale_after_hours

    def connection_output_dir(self, connection: SubscriptionConnection) -> str:
        """Each connection writes to an isolated dataset root."""
        return join_root(self.output_dir, "connections", _slug(connection.connection_id))

    def run(
        self,
        connection: SubscriptionConnection,
        *,
        mode: str = "initial",
        run_id: str | None = None,
        progress_callback: Callable[[str, str, int], None] | None = None,
    ) -> tuple[SyncResult, SyncState]:
        """Run one connection's sync.

        ``progress_callback``, when given, is invoked as
        ``callback(stage, stage_message, progress_pct)`` at each transition in
        :data:`SYNC_STAGES` (or ``"failed"`` on error) *before* the final
        return. Callers use this to persist live progress (e.g. into
        ``SyncState``) while this method runs on a background thread; it is
        best-effort and any exception it raises is swallowed rather than
        allowed to corrupt the underlying ingestion/publish run.
        """
        if mode not in {"initial", "scheduled", "manual"}:
            raise ValueError("sync mode must be initial, scheduled, or manual")
        if not connection.is_active:
            raise ValueError(
                f"Connection '{connection.connection_id}' is disabled; enable it before syncing"
            )

        previous = connection.sync_state or SyncState()
        started = self.clock()
        identifier = run_id or str(uuid.uuid4())

        if self.ingestion_factory is None:
            raise RuntimeError(
                "No ingestion factory is configured; cannot run a connection-scoped sync"
            )

        def _report(stage: str, message: str, pct: int) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(stage, message, pct)
            except Exception:  # noqa: BLE001, S110 - progress reporting must never break sync
                pass

        _report("discovering", f"Running {mode} discovery for {connection.connection_id}", 10)

        try:
            manifest = self.ingestion_factory(connection).run()
        except Exception as exc:  # noqa: BLE001 - failures are recorded, not swallowed
            finished = self.clock()
            message = str(exc).strip() or exc.__class__.__name__
            _report("failed", message, 100)
            state = SyncState(
                status="failed",
                last_synced_at=_iso(finished),
                last_successful_sync_at=previous.last_successful_sync_at,
                last_failed_at=_iso(finished),
                run_id=identifier,
                source_version=previous.source_version,
                record_count=previous.record_count,
                attempts=previous.attempts + 1,
                message=message,
                stage="failed",
                stage_message=message,
                progress_pct=100,
            )
            result = SyncResult(
                connection_id=connection.connection_id,
                run_id=identifier,
                status="failed",
                started_at=_iso(started),
                completed_at=_iso(finished),
                record_count=0,
                message=message,
            )
            return result, state

        payload = manifest if isinstance(manifest, dict) else {}
        record_count = _record_count(payload)

        publish_message: str | None = None
        if self.publish_factory is not None:
            _report("merging", "Merging inventory across active connections", 45)
            try:
                _report(
                    "publishing_ontology",
                    "Rebuilding ontology from the merged snapshot",
                    65,
                )
                _report(
                    "writing_fabric_tables",
                    "Publishing ontology and inventory tables to Fabric",
                    85,
                )
                self.publish_factory(connection).run()
            except Exception as exc:  # noqa: BLE001 - publish failures are surfaced, not fatal
                logger.exception(
                    "Fabric publish failed for connection '%s' during %s sync",
                    connection.connection_id,
                    mode,
                )
                publish_message = (
                    f"{mode} sync completed but Fabric publish failed: "
                    f"{str(exc).strip() or exc.__class__.__name__}"
                )

        finished = self.clock()
        message = publish_message or f"{mode} sync completed"
        status = "failed" if publish_message else "succeeded"
        _report(status, message, 100)
        state = SyncState(
            status=status,
            last_synced_at=_iso(finished),
            last_successful_sync_at=(
                _iso(finished) if status == "succeeded" else previous.last_successful_sync_at
            ),
            last_failed_at=_iso(finished) if status == "failed" else previous.last_failed_at,
            run_id=identifier,
            source_version=str(payload.get("queryVersion") or previous.source_version or ""),
            record_count=record_count,
            attempts=previous.attempts + 1,
            message=message,
            stage=status,
            stage_message=message,
            progress_pct=100,
        )
        result = SyncResult(
            connection_id=connection.connection_id,
            run_id=identifier,
            status=status,
            started_at=_iso(started),
            completed_at=_iso(finished),
            record_count=record_count,
            message=message,
            manifest=payload or None,
            discovery_metrics=_discovery_metrics(payload),
        )
        return result, state

    def freshness(self, state: SyncState | None) -> dict[str, Any]:
        """Classify data freshness for a connection's sync state."""
        current = state or SyncState()
        last_success = _parse(current.last_successful_sync_at)
        if last_success is None:
            return {
                "status": "never_synced",
                "stale": True,
                "age_hours": None,
                "last_successful_sync_at": None,
                "stale_after_hours": self.stale_after_hours,
            }
        age = self.clock().astimezone(UTC) - last_success
        age_hours = round(age.total_seconds() / 3600, 2)
        stale = age > timedelta(hours=self.stale_after_hours)
        return {
            "status": "stale" if stale else "fresh",
            "stale": stale,
            "age_hours": age_hours,
            "last_successful_sync_at": current.last_successful_sync_at,
            "stale_after_hours": self.stale_after_hours,
        }


#: Keys under which an ingestion factory MAY surface an already-computed
#: ``OntologyValidationReport.to_dict()``-shaped (or equivalent) rollup
#: inside its returned manifest. Checked in order; the first match wins.
#: This coordinator never computes the report itself -- it only forwards
#: one if the ingestion pipeline already produced it, so this stays a
#: read-only, purely-additive surface with zero coupling to the ontology
#: validator internals.
_DISCOVERY_METRICS_MANIFEST_KEYS: tuple[str, ...] = ("discovery_metrics", "ontology_report")


def _discovery_metrics(manifest: dict[str, Any]) -> dict[str, Any] | None:
    for key in _DISCOVERY_METRICS_MANIFEST_KEYS:
        value = manifest.get(key)
        if isinstance(value, dict) and value:
            return value
    return None


def _record_count(manifest: dict[str, Any]) -> int:
    datasets = manifest.get("datasets")
    if isinstance(datasets, dict):
        total = 0
        for value in datasets.values():
            if isinstance(value, dict):
                total += int(value.get("rowCount") or value.get("row_count") or 0)
        if total:
            return total
    for key in ("recordCount", "record_count", "rowCount", "row_count"):
        if key in manifest:
            try:
                return max(int(manifest[key]), 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value)).strip("-")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["DEFAULT_STALE_AFTER_HOURS", "SYNC_STAGES", "ConnectionSyncCoordinator", "SyncResult"]
