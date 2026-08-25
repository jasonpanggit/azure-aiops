"""Bounded Azure Monitor Logs Query API access for ConfigurationData."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

LOGS_QUERY_SCOPE = "https://api.loganalytics.azure.com/.default"
CONFIGURATION_DATA_QUERY = """
ConfigurationData
| where ConfigDataType == "Software"
| summarize arg_max(TimeGenerated, *) by Computer, SourceComputerId, _ResourceId, SoftwareName
| project TimeGenerated, Computer, SourceComputerId, _ResourceId, _SubscriptionId,
          SoftwareName, CurrentVersion, Publisher, SoftwareType
| order by _ResourceId asc, SoftwareName asc, CurrentVersion asc
""".strip()
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LogsRequester(Protocol):
    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True)
class LogsQueryLimits:
    """Hard limits applied before an untrusted response is parsed."""

    timeout_seconds: float = 30.0
    max_response_bytes: int = 4 * 1024 * 1024
    max_rows: int = 25_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_response_bytes <= 0 or self.max_rows <= 0:
            raise ValueError("Logs query bounds must be positive")


class AzureMonitorLogsClient:
    """Query the fixed ConfigurationData projection through the Logs API.

    This adapter intentionally does not accept KQL from a caller.  Workspace
    selection and credentials are server-owned, while the response parser is
    strict because workspace content is an external trust boundary.
    """

    endpoint_template = "https://api.loganalytics.azure.com/v1/workspaces/{workspace_id}/query"

    def __init__(
        self,
        credential: Any,
        *,
        limits: LogsQueryLimits | None = None,
        requester: LogsRequester | None = None,
    ) -> None:
        self.credential = credential
        self.limits = limits or LogsQueryLimits()
        self.requester = requester or httpx.request

    def query_configuration_data(self, workspace_id: str) -> list[dict[str, Any]]:
        workspace = _validated_workspace_id(workspace_id)
        token = self.credential.get_token(LOGS_QUERY_SCOPE)
        access_token = getattr(token, "token", "")
        if not access_token:
            raise RuntimeError("Azure AD returned an empty access token for Azure Monitor Logs")

        response = self.requester(
            "POST",
            self.endpoint_template.format(workspace_id=workspace),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"query": CONFIGURATION_DATA_QUERY},
            timeout=self.limits.timeout_seconds,
        )
        if response.status_code >= 400:
            detail = response.text.strip()[:512] or f"HTTP {response.status_code}"
            raise RuntimeError(f"Logs ConfigurationData query failed: {detail}")
        content = response.content
        if len(content) > self.limits.max_response_bytes:
            raise RuntimeError(
                "Logs ConfigurationData response exceeded the configured byte limit"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Logs ConfigurationData response was not valid JSON") from exc
        return parse_logs_tables(payload, max_rows=self.limits.max_rows)

    query = query_configuration_data


def parse_logs_tables(payload: Any, *, max_rows: int = 25_000) -> list[dict[str, Any]]:
    """Parse one typed Logs API table, rejecting schema drift and row overflow."""

    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list):
        raise TypeError("Logs response must contain a tables array")
    tables = payload["tables"]
    if len(tables) != 1 or not isinstance(tables[0], dict):
        raise ValueError("Logs response must contain exactly one result table")
    table = tables[0]
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise TypeError("Logs result table must contain columns and rows arrays")
    if len(rows) > max_rows:
        raise ValueError("Logs result exceeded the configured row limit")

    names: list[str] = []
    for column in columns:
        if not isinstance(column, dict):
            raise TypeError("Logs result columns must be objects")
        name = str(column.get("name") or "").strip()
        if not name or name in names:
            raise ValueError("Logs result contains an invalid or duplicate column")
        names.append(name)
    if not names:
        raise ValueError("Logs result must contain at least one column")

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise ValueError("Logs result row does not match its column schema")
        parsed.append(dict(zip(names, row, strict=True)))
    return parsed


def _validated_workspace_id(value: str) -> str:
    workspace = str(value or "").strip()
    if not _WORKSPACE_ID.fullmatch(workspace):
        raise ValueError("Logs workspace ID is invalid")
    return workspace
