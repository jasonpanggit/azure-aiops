"""Background execution and status tracking for inventory refresh runs.

A full inventory refresh acquires every subscription, republishes the combined
snapshot and syncs ~60 Fabric tables; it routinely runs far longer than any
HTTP client will wait. Azure Container Apps additionally terminates an ingress
request at 240 seconds, which is not configurable, so a synchronous trigger can
never report success and the Fabric Data Pipeline Web activity that calls it
fails every hour with a stream timeout even when the underlying work is healthy.

Refreshes therefore execute on a worker thread while the trigger returns
immediately with a run identifier the caller can poll. Runs are single-flight:
the hourly schedule must never stack a second acquisition on top of one still
publishing, so a trigger arriving during an active run adopts that run instead
of starting another.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

_MAX_TRACKED_RUNS = 20

_lock = threading.Lock()
_runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
_active_run_id: str | None = None


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _public_view(run: dict[str, Any]) -> dict[str, Any]:
    view = {
        "run_id": run["run_id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "duration_seconds": run["duration_seconds"],
    }
    if run["status"] == "succeeded":
        view["result"] = run["result"]
    elif run["status"] == "failed":
        view["error"] = run["error"]
    return view


def _record(run_id: str) -> dict[str, Any] | None:
    return _runs.get(run_id)


def _finish(run_id: str, *, status: str, result: Any, error: str | None) -> None:
    global _active_run_id
    with _lock:
        run = _runs.get(run_id)
        if run is not None:
            run["status"] = status
            run["result"] = result
            run["error"] = error
            run["finished_at"] = _utc_now()
            run["duration_seconds"] = round(time.monotonic() - run["_started_at"], 3)
        if _active_run_id == run_id:
            _active_run_id = None


def _worker(run_id: str, refresh: Callable[[], Any]) -> None:
    try:
        result = refresh()
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the poller
        _finish(run_id, status="failed", result=None, error=f"{type(exc).__name__}: {exc}")
        return
    _finish(run_id, status="succeeded", result=result, error=None)


def start_refresh(refresh: Callable[[], Any]) -> tuple[dict[str, Any], bool]:
    """Start ``refresh`` on a worker thread, or adopt the in-flight run.

    Returns the run's public view and whether an existing run was adopted.
    """

    global _active_run_id
    with _lock:
        if _active_run_id is not None:
            active = _runs.get(_active_run_id)
            if active is not None and active["status"] == "running":
                return _public_view(active), True
            _active_run_id = None

        run_id = f"refresh-{uuid.uuid4()}"
        run = {
            "run_id": run_id,
            "status": "running",
            "started_at": _utc_now(),
            "finished_at": None,
            "duration_seconds": None,
            "result": None,
            "error": None,
            "_started_at": time.monotonic(),
        }
        _runs[run_id] = run
        while len(_runs) > _MAX_TRACKED_RUNS:
            oldest, _ = _runs.popitem(last=False)
            if oldest == _active_run_id:  # pragma: no cover - defensive
                _active_run_id = None
        _active_run_id = run_id
        view = _public_view(run)

    thread = threading.Thread(
        target=_worker,
        args=(run_id, refresh),
        name=f"inventory-{run_id}",
        daemon=False,
    )
    thread.start()
    return view, False


def get_run(run_id: str) -> dict[str, Any] | None:
    with _lock:
        run = _record(run_id)
        return _public_view(run) if run is not None else None


def latest_run() -> dict[str, Any] | None:
    with _lock:
        if not _runs:
            return None
        return _public_view(next(reversed(_runs.values())))


def active_run() -> dict[str, Any] | None:
    with _lock:
        if _active_run_id is None:
            return None
        run = _runs.get(_active_run_id)
        return _public_view(run) if run is not None else None


def reset_for_tests() -> None:
    global _active_run_id
    with _lock:
        _runs.clear()
        _active_run_id = None


__all__ = [
    "active_run",
    "get_run",
    "latest_run",
    "reset_for_tests",
    "start_refresh",
]
