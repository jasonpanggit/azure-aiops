from __future__ import annotations

from datetime import datetime
from typing import Any


def fetch_software_inventory(
    logs_client: Any,
    subscriptions: list[str],
    started: datetime,
    *,
    discovered_workspaces: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Fetch ConfigurationData from every Log Analytics workspace in scope.

    Workspace IDs come entirely from dynamic ARG discovery
    (``discovered_workspaces``, subscription-wide
    ``microsoft.operationalinsights/workspaces``) -- there is no static or
    hardcoded connection -> workspace mapping. Any workspace visible to the
    connection's subscription scope is queried automatically.
    """

    workspaces = tuple(
        dict.fromkeys(
            str(row.get("workspaceId") or "").strip()
            for row in (discovered_workspaces or [])
            if str(row.get("workspaceId") or "").strip()
        )
    )
    requested_scope = {"subscription": sorted(subscriptions)}
    query_version = "inventory-software-v1"
    if not workspaces:
        return [], {
            "source_type": "logs",
            "state": "unavailable",
            "observed_at": started.astimezone().replace(microsecond=0).isoformat(),
            "query_version": query_version,
            "row_count": 0,
            "error": "No Log Analytics workspace was discovered in this connection's scope",
            "workspace_count": 0,
            "requested_scope": requested_scope,
        }
    if logs_client is None:
        return [], {
            "source_type": "logs",
            "state": "unavailable",
            "observed_at": started.astimezone().replace(microsecond=0).isoformat(),
            "query_version": query_version,
            "row_count": 0,
            "error": "No Azure Monitor Logs client is configured",
            "workspace_count": len(workspaces),
            "requested_scope": requested_scope,
        }

    rows: list[dict] = []
    errors: list[str] = []
    for workspace_id in workspaces:
        try:
            result = logs_client.query_configuration_data(workspace_id)
        except Exception as exc:  # noqa: BLE001 - source failures are surfaced in status
            errors.append(f"{workspace_id}: {str(exc).strip() or exc.__class__.__name__}")
        else:
            rows.extend(result)
    state = "ready" if not errors else "partial" if rows else "degraded"
    observed = max(
        (
            str(row.get("TimeGenerated") or row.get("time_generated") or "")
            for row in rows
        ),
        default=started.astimezone().replace(microsecond=0).isoformat(),
    )
    return rows, {
        "source_type": "logs",
        "state": state,
        "observed_at": observed,
        "query_version": query_version,
        "row_count": len(rows),
        "error": "; ".join(errors)[:2048],
        "workspace_count": len(workspaces),
        "requested_scope": requested_scope,
    }


__all__ = ["fetch_software_inventory"]
