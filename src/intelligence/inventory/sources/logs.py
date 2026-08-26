from __future__ import annotations

from datetime import datetime
from typing import Any


def fetch_software_inventory(
    config: Any,
    logs_client: Any,
    subscriptions: list[str],
    started: datetime,
) -> tuple[list[dict], dict]:
    """Fetch ConfigurationData only from server-owned workspace mappings."""

    connection_id = str(getattr(config, "connection_context", {}).get("connection_id") or "")
    workspaces = config.workspaces_for_connection(connection_id)
    requested_scope = {"subscription": sorted(subscriptions)}
    query_version = "inventory-software-v1"
    if not workspaces:
        return [], {
            "source_type": "logs",
            "state": "unavailable",
            "observed_at": "",
            "query_version": query_version,
            "row_count": 0,
            "error": "No Log Analytics workspace is configured for this connection",
            "workspace_count": 0,
            "requested_scope": requested_scope,
        }
    if logs_client is None:
        return [], {
            "source_type": "logs",
            "state": "unavailable",
            "observed_at": "",
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

