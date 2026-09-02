from __future__ import annotations

from typing import Any

from fabric.auth import build_credential
from fabric.config import FabricRuntimeConfig
from fabric.fabric_client import FabricClient

AIOPS_FABRIC_CONFIG_ENV = "AIOPS_FABRIC_CONFIG"
_SUCCEEDED = {"succeeded", "completed", "success"}
_FAILED = {"failed", "cancelled", "canceled", "error"}


def _default_fabric_client() -> FabricClient:
    import os

    config_path = os.environ.get(AIOPS_FABRIC_CONFIG_ENV, "fabric.config.yaml").strip() or "fabric.config.yaml"
    config = FabricRuntimeConfig.load(config_path)
    return FabricClient(build_credential(config.auth))


def _status(raw: str) -> str:
    value = raw.casefold()
    if value in _SUCCEEDED:
        return "succeeded"
    if value in _FAILED:
        return "failed"
    return "unknown"


def _run_time(run: dict[str, Any]) -> str:
    for field in ("startTimeUtc", "startTime", "createdDateTime", "endTimeUtc"):
        value = str(run.get(field) or "")
        if value:
            return value
    return ""


def _activity_name(run: dict[str, Any]) -> str:
    for field in ("jobType", "activityName", "name"):
        value = str(run.get(field) or "")
        if value:
            return value
    return ""


def _looks_like_maintenance(run: dict[str, Any]) -> bool:
    text = " ".join(
        str(run.get(field) or "")
        for field in ("jobType", "activityName", "name", "displayName")
    ).casefold()
    return "maintenance" in text or "tablemaintenance" in text


def last_maintenance_status(
    workspace_id: str,
    lakehouse_id: str,
    *,
    client: FabricClient | None = None,
) -> dict[str, str]:
    if not workspace_id or not lakehouse_id:
        raise ValueError("workspace_id and lakehouse_id are required")

    active_client = client or _default_fabric_client()
    endpoint = f"/workspaces/{workspace_id}/items/{lakehouse_id}/jobs/instances"
    runs = [run for run in active_client.iter_items(endpoint) if _looks_like_maintenance(run)]
    if not runs:
        return {"status": "no_runs_recorded", "last_run_at": "", "activity_name": ""}
    latest = max(runs, key=_run_time)
    return {
        "status": _status(str(latest.get("status") or latest.get("state") or "")),
        "last_run_at": _run_time(latest),
        "activity_name": _activity_name(latest),
    }
