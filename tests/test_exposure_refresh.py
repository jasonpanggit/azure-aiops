from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from api.exposure_refresh import (
    ExposurePatchRefreshCoordinator,
    ExposurePatchRefreshScope,
)


def _scope() -> ExposurePatchRefreshScope:
    return ExposurePatchRefreshScope(
        tenant_id="tenant-a",
        connection_id="connection-a",
        subscription_id="subscription-a",
    )


def test_concurrent_stale_reads_enqueue_one_scoped_persistence_callback() -> None:
    started = threading.Event()
    release = threading.Event()
    starts: list[ExposurePatchRefreshScope] = []

    def start_refresh(
        scope: ExposurePatchRefreshScope,
    ) -> dict[str, Any]:
        starts.append(scope)
        started.set()
        release.wait(timeout=2)
        return {"status": "running"}

    coordinator = ExposurePatchRefreshCoordinator(
        start_refresh=start_refresh,
        read_status=lambda _scope: {"status": "idle"},
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        first = executor.submit(coordinator.request_refresh, _scope())
        assert started.wait(timeout=1)
        concurrent = [
            executor.submit(coordinator.request_refresh, _scope())
            for _ in range(3)
        ]
        release.set()
        states = [first.result(), *(future.result() for future in concurrent)]

    assert starts == [_scope()]
    assert all(state.refreshing for state in states)
    assert all(state.state == "refreshing" for state in states)


def test_recent_failure_applies_exponential_backoff_and_preserves_lkg() -> None:
    starts: list[ExposurePatchRefreshScope] = []
    coordinator = ExposurePatchRefreshCoordinator(
        start_refresh=lambda scope: starts.append(scope) or {},
        read_status=lambda _scope: {
            "status": "failed",
            "attempts": 2,
            "last_successful_sync_at": "2026-09-14T04:00:00Z",
            "last_failed_at": "2026-09-14T04:59:30Z",
        },
        clock=lambda: datetime(2026, 9, 14, 5, 0, tzinfo=UTC),
        base_cooldown_seconds=30,
        max_cooldown_seconds=300,
    )

    state = coordinator.request_refresh(_scope())

    assert starts == []
    assert state.to_dict() == {
        "state": "failed",
        "refreshing": False,
        "last_success_at": "2026-09-14T04:00:00Z",
        "last_failure_at": "2026-09-14T04:59:30Z",
        "failure_code": "refresh_backoff",
    }


def test_completed_background_refresh_reports_persisted_success() -> None:
    status = {
        "status": "idle",
        "last_successful_sync_at": "2026-09-14T04:00:00Z",
    }

    def start_refresh(
        _scope: ExposurePatchRefreshScope,
    ) -> dict[str, Any]:
        status["status"] = "running"
        return {"sync_state": dict(status)}

    coordinator = ExposurePatchRefreshCoordinator(
        start_refresh=start_refresh,
        read_status=lambda _scope: dict(status),
    )

    assert coordinator.request_refresh(_scope()).refreshing is True
    status.update(
        {
            "status": "succeeded",
            "last_successful_sync_at": "2026-09-14T05:00:00Z",
        }
    )

    completed = coordinator.request_refresh(_scope())
    assert completed.state == "succeeded"
    assert completed.refreshing is False
    assert completed.last_success_at == "2026-09-14T05:00:00Z"
