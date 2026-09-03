"""Connection-scoped sync lifecycle.

Every run is bound to one :class:`SubscriptionConnection`, produces an
ingestion run id, and updates that connection's :class:`SyncState` only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ontology.publication_state import DEFAULT_ONTOLOGY_NAME, PublicationStateStore
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
        publication_state_store: PublicationStateStore | None = None,
        ontology_name: str = DEFAULT_ONTOLOGY_NAME,
        metrics: Any | None = None,
        publish_timeout_seconds: int = 600,
    ) -> None:
        self.output_dir = resolve_root(str(output_dir))
        self.ingestion_factory = ingestion_factory
        self.publish_factory = publish_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        # The Fabric publish step (OneLake/Delta table writes) makes network
        # calls with no caller-supplied timeout anywhere in that path (ARG
        # discovery is bounded by ``command_timeout_seconds``, but the
        # publish step is not). A hang there -- e.g. an orphaned OneLake
        # write lease, a stalled MSAL/IMDS token refresh -- previously left
        # ``sync_status`` at "running" indefinitely with no way to recover
        # short of a full container restart. Bounding it here means a stuck
        # publish surfaces as a normal "failed" sync (retryable) instead of
        # a silent, permanent stall.
        if publish_timeout_seconds < 1:
            raise ValueError("publish_timeout_seconds must be positive")
        self.publish_timeout_seconds = publish_timeout_seconds
        if stale_after_hours < 1:
            raise ValueError("stale_after_hours must be positive")
        self.stale_after_hours = stale_after_hours
        # Durable terminal-state record of ontology publish attempts (MED-01).
        # Defaults to a store backed by this coordinator's own output root, so
        # it uses the exact same storage tier (local disk in dev, OneLake in
        # prod) as everything else this coordinator persists.
        self.publication_state_store = publication_state_store or PublicationStateStore(
            self.output_dir
        )
        self.ontology_name = ontology_name
        # ``metrics`` follows the same optional-injection pattern as
        # ``fabric.sync_service.OntologySyncService`` (``metrics or
        # FabricMetrics()``). Import is local so plain ingestion-only callers
        # (this coordinator's default mode with no ``publish_factory``) never
        # require ``fabric.telemetry``/OpenTelemetry to be importable.
        if metrics is not None:
            self.metrics = metrics
        else:
            try:
                from fabric.telemetry import FabricMetrics

                self.metrics = FabricMetrics()
            except ImportError:  # pragma: no cover - fabric.telemetry is a hard dependency elsewhere
                self.metrics = None

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
                def _on_fabric_progress(event: Any) -> None:
                    total = max(int(event.total_tables), 0)
                    completed = min(max(int(event.completed_tables), 0), total)
                    pct = (
                        85
                        if total == 0
                        else min(99, 85 + ((completed * 14 + total - 1) // total))
                    )
                    _report(
                        "writing_fabric_tables",
                        (
                            f"Writing Fabric tables: {completed}/{total} tables written "
                            f"(latest: {event.table_name})"
                        ),
                        pct,
                    )

                self._run_publish_with_timeout(connection, _on_fabric_progress)
            except Exception as exc:
                logger.exception(
                    "Fabric publish failed for connection '%s' during %s sync",
                    connection.connection_id,
                    mode,
                )
                publish_message = (
                    f"{mode} sync completed but Fabric publish failed: "
                    f"{str(exc).strip() or exc.__class__.__name__}"
                )
                self._record_publication_attempt(exc)
            else:
                self._record_publication_attempt(None)

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

    def _run_publish_with_timeout(
        self,
        connection: SubscriptionConnection,
        progress_callback: Callable[[Any], None] | None = None,
    ) -> None:
        """Run ``publish_factory(connection).run()`` with a bounded timeout.

        The Fabric publish step performs OneLake/Delta network I/O with no
        internal timeout of its own (unlike ARG discovery, which is bounded
        by ``command_timeout_seconds``). A hang anywhere in that path -- an
        orphaned OneLake write lease, a stalled credential/token refresh --
        previously left the calling sync thread blocked forever, so
        ``sync_status`` stayed "running" indefinitely with no automatic
        recovery. Running it on a short-lived helper thread lets us raise a
        ``TimeoutError`` after ``publish_timeout_seconds`` and mark the sync
        "failed" (which the existing retry/backoff machinery then handles
        normally) instead of hanging the connection forever. The runaway
        thread itself is deliberately abandoned (daemon, no join) since
        Python cannot forcibly cancel a blocked call; it will terminate on
        its own once (or if) the stuck network call eventually resolves.
        """
        # Not a context manager: ``ThreadPoolExecutor.__exit__``/``shutdown``
        # default to ``wait=True``, which would block on the very same stuck
        # thread we're trying to time out on. ``shutdown(wait=False)`` lets
        # this call return promptly while the (possibly still-hung) worker
        # thread is abandoned to exit on its own whenever its blocking call
        # eventually resolves.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fabric-publish")
        try:
            future = executor.submit(self.publish_factory(connection).run)
            try:
                future.result(timeout=self.publish_timeout_seconds)
            except FutureTimeoutError as exc:
                raise TimeoutError(
                    f"Fabric publish for connection '{connection.connection_id}' "
                    f"exceeded publish_timeout_seconds={self.publish_timeout_seconds}"
                ) from exc
        finally:
            executor.shutdown(wait=False)

    def _record_publication_attempt(self, exc: Exception | None) -> None:
        """Record this publish attempt's terminal state, durably and via telemetry.

        Never allowed to raise: recording an attempt must not itself break
        the sync run it is describing (mirrors the ``noqa: BLE001, S110``
        discipline already used for ``_report`` above).

        ``exc`` is ``None`` on a successful publish. A caught ``ValueError``
        is a preflight rejection from ``OntologyPublisher.build_definition()``
        (never reaches the network, never retried). Anything else is a Fabric
        REST failure that reached ``fabric_client.py``'s bounded retry loop;
        it is only marked ``retryable`` when it carries one of that module's
        own ``TRANSIENT_STATUS`` codes (or is a transport-level failure),
        i.e. exactly the class of error that loop already gives up on.
        """
        try:
            metrics = self.metrics
            if exc is None:
                self.publication_state_store.record(
                    ontology_name=self.ontology_name,
                    outcome="succeeded",
                    retryable=False,
                    error="",
                    attempted_at=_iso(self.clock()),
                )
                return
            error = str(exc).strip() or exc.__class__.__name__
            if isinstance(exc, ValueError):
                self.publication_state_store.record(
                    ontology_name=self.ontology_name,
                    outcome="rejected",
                    retryable=False,
                    error=error,
                    attempted_at=_iso(self.clock()),
                )
                if metrics is not None:
                    metrics.record_publish_preflight_rejected()
                return
            retryable, status_code = _transient_fabric_status(exc)
            self.publication_state_store.record(
                ontology_name=self.ontology_name,
                outcome="failed",
                retryable=retryable,
                error=error,
                attempted_at=_iso(self.clock()),
            )
            if retryable and metrics is not None:
                metrics.record_publish_retry(status_code)
        except Exception:
            logger.exception("Failed to record ontology publication attempt state")


def _transient_fabric_status(exc: Exception) -> tuple[bool, int | None]:
    """Return ``(retryable, status_code)`` for an exhausted-retry Fabric failure.

    ``retryable`` mirrors ``fabric.fabric_client.FabricClient.TRANSIENT_STATUS``
    -- the same status-code set that client's own backoff loop already
    retries -- so a publish failure is only ever marked retryable when it's
    the same class of error that loop just gave up on. Import is local to
    avoid ``onboarding.sync`` depending on ``fabric`` at module load time for
    callers (e.g. plain ingestion-only tests) that never touch Fabric.
    """
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        from fabric.fabric_client import FabricClient

        if status_code in FabricClient.TRANSIENT_STATUS:
            return True, status_code
    except ImportError:  # pragma: no cover - fabric is a hard dependency elsewhere
        pass
    try:
        import httpx

        if isinstance(exc, httpx.TransportError):
            return True, status_code
    except ImportError:  # pragma: no cover - httpx is a hard dependency elsewhere
        pass
    return False, status_code


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
