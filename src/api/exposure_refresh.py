"""Bounded background refresh orchestration for stale patch priorities."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class ExposurePatchRefreshScope:
    """One server-derived connection and subscription refresh boundary."""

    tenant_id: str
    connection_id: str
    subscription_id: str


@dataclass(frozen=True, slots=True)
class ExposurePatchRefreshState:
    """Sanitized refresh metadata safe to attach to an Exposure response."""

    state: str
    refreshing: bool
    last_success_at: str = ""
    last_failure_at: str = ""
    failure_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the public refresh metadata contract."""
        return {
            "state": self.state,
            "refreshing": self.refreshing,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "failure_code": self.failure_code,
        }


class ExposurePatchRefreshCoordinator:
    """Deduplicate stale reads before queuing governed connection syncs."""

    def __init__(
        self,
        *,
        start_refresh: Callable[
            [ExposurePatchRefreshScope],
            Mapping[str, Any],
        ],
        read_status: Callable[
            [ExposurePatchRefreshScope],
            Mapping[str, Any],
        ],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        base_cooldown_seconds: int = 30,
        max_cooldown_seconds: int = 300,
    ) -> None:
        if base_cooldown_seconds < 1:
            raise ValueError("Exposure refresh cooldown must be positive")
        if max_cooldown_seconds < base_cooldown_seconds:
            raise ValueError(
                "Exposure refresh maximum cooldown must cover the base cooldown"
            )
        self._start_refresh = start_refresh
        self._read_status = read_status
        self._clock = clock
        self._base_cooldown_seconds = base_cooldown_seconds
        self._max_cooldown_seconds = max_cooldown_seconds
        self._scheduled: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    def request_refresh(
        self,
        scope: ExposurePatchRefreshScope,
    ) -> ExposurePatchRefreshState:
        """Queue at most one refresh for the exact authorized connection."""
        key = (
            scope.tenant_id.casefold(),
            scope.subscription_id.casefold(),
            scope.connection_id.casefold(),
        )
        with self._lock:
            try:
                status = dict(self._read_status(scope))
            except (LookupError, OSError, RuntimeError, ValueError):
                return ExposurePatchRefreshState(
                    state="failed",
                    refreshing=False,
                    last_failure_at=self._clock().astimezone(UTC).isoformat(),
                    failure_code="refresh_status_unavailable",
                )
            lifecycle = str(status.get("status") or "").strip().casefold()
            if lifecycle in {"processing", "running", "starting"}:
                self._scheduled.add(key)
                return _state_from_status(status, state="refreshing", refreshing=True)

            if key in self._scheduled and lifecycle == "succeeded":
                self._scheduled.discard(key)
                return _state_from_status(
                    status,
                    state="succeeded",
                    refreshing=False,
                )
            if key in self._scheduled and lifecycle not in {
                "cancelled",
                "failed",
                "stopped",
            }:
                return _state_from_status(
                    status,
                    state="refreshing",
                    refreshing=True,
                )
            self._scheduled.discard(key)
            if lifecycle == "failed" and self._in_failure_backoff(status):
                return _state_from_status(
                    status,
                    state="failed",
                    refreshing=False,
                    failure_code="refresh_backoff",
                )

            if key in self._scheduled:
                return _state_from_status(status, state="refreshing", refreshing=True)

            try:
                queued = dict(self._start_refresh(scope))
            except (OSError, RuntimeError, ValueError):
                return ExposurePatchRefreshState(
                    state="failed",
                    refreshing=False,
                    last_success_at=str(
                        status.get("last_successful_sync_at") or ""
                    ),
                    last_failure_at=(
                        self._clock().astimezone(UTC).isoformat()
                    ),
                    failure_code="refresh_failed",
                )
            self._scheduled.add(key)
            queued_status = queued.get("sync_state")
            return _state_from_status(
                queued_status if isinstance(queued_status, Mapping) else status,
                state="refreshing",
                refreshing=True,
            )

    def _in_failure_backoff(self, status: Mapping[str, Any]) -> bool:
        failed_at = _parse_timestamp(status.get("last_failed_at"))
        if failed_at is None:
            return False
        attempts = max(0, int(status.get("attempts") or 0))
        delay = min(
            self._base_cooldown_seconds * (2 ** min(attempts, 8)),
            self._max_cooldown_seconds,
        )
        return self._clock().astimezone(UTC) < failed_at + timedelta(seconds=delay)


def _state_from_status(
    status: Mapping[str, Any],
    *,
    state: str,
    refreshing: bool,
    failure_code: str = "",
) -> ExposurePatchRefreshState:
    return ExposurePatchRefreshState(
        state=state,
        refreshing=refreshing,
        last_success_at=str(status.get("last_successful_sync_at") or ""),
        last_failure_at=str(status.get("last_failed_at") or ""),
        failure_code=failure_code,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)
