"""Connection-scoped sync lifecycle.

Every run is bound to one :class:`SubscriptionConnection`, produces an
ingestion run id, and updates that connection's :class:`SyncState` only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from storage.fs import join_root, resolve_root
from ontology.subscription_connection import SubscriptionConnection, SyncState

DEFAULT_STALE_AFTER_HOURS = 24


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
        }


class ConnectionSyncCoordinator:
    """Runs connection-scoped ingestion and maintains the connection's SyncState.

    ``ingestion_factory`` receives the connection and returns an object with a
    ``run()`` method. Keeping it injectable means the connection boundary owns
    scoping rather than the ingestion service inferring it from global config.
    """

    def __init__(
        self,
        output_dir: str,
        ingestion_factory: Callable[[SubscriptionConnection], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
    ) -> None:
        self.output_dir = resolve_root(str(output_dir))
        self.ingestion_factory = ingestion_factory
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
    ) -> tuple[SyncResult, SyncState]:
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

        try:
            manifest = self.ingestion_factory(connection).run()
        except Exception as exc:  # noqa: BLE001 - failures are recorded, not swallowed
            finished = self.clock()
            message = str(exc).strip() or exc.__class__.__name__
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

        finished = self.clock()
        payload = manifest if isinstance(manifest, dict) else {}
        record_count = _record_count(payload)
        state = SyncState(
            status="succeeded",
            last_synced_at=_iso(finished),
            last_successful_sync_at=_iso(finished),
            last_failed_at=previous.last_failed_at,
            run_id=identifier,
            source_version=str(payload.get("queryVersion") or previous.source_version or ""),
            record_count=record_count,
            attempts=previous.attempts + 1,
            message=f"{mode} sync completed",
        )
        result = SyncResult(
            connection_id=connection.connection_id,
            run_id=identifier,
            status="succeeded",
            started_at=_iso(started),
            completed_at=_iso(finished),
            record_count=record_count,
            message=f"{mode} sync completed",
            manifest=payload or None,
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


__all__ = ["DEFAULT_STALE_AFTER_HOURS", "ConnectionSyncCoordinator", "SyncResult"]
