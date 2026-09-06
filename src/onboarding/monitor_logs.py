"""Bounded Azure Monitor Logs Query API access for ConfigurationData."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

LOGS_QUERY_SCOPE = "https://api.loganalytics.io/.default"
CONFIGURATION_DATA_QUERY = """
ConfigurationData
| where ConfigDataType == "Software"
| summarize arg_max(TimeGenerated, *) by Computer, SourceComputerId, _ResourceId, SoftwareName
| project ConfigDataType, TimeGenerated, Computer, SourceComputerId, _ResourceId, _SubscriptionId,
          SoftwareName, CurrentVersion, Publisher, SoftwareType
| order by _ResourceId asc, SoftwareName asc, CurrentVersion asc
""".strip()

# Virtual network flow logs processed through Traffic Analytics land in
# ``NTANetAnalytics``: one row per observed flow bucket, already
# deduplicated/aggregated by Traffic Analytics's own pipeline (unlike raw
# flow log JSON, which this platform does not parse directly).
#
# Schema note: ``NTANetAnalytics`` (VNet flow logs, FASchemaVersion 3) uses
# unsuffixed column names -- ``SrcIp``/``DestIp``/``DestPort``/``L4Protocol``.
# The ``_s``/``_d`` suffixed names belong to the *retired* NSG flow log table
# ``AzureNetworkAnalytics_CL`` and do not resolve here. NSG flow logs were
# blocked for new creation in June 2025 and retire entirely September 2027,
# so only the VNet schema is supported.
#
# ``SubType == "FlowLog"`` is mandatory: other SubType values in this table
# are internal to Traffic Analytics and are not flow observations.
#
# Only the last day is queried and the result is bounded by
# ``LogsQueryLimits.max_rows`` -- flow tables are the highest-volume Log
# Analytics data this platform reads, so an unbounded query is an
# availability risk, not just a cost one.
NSG_FLOW_LOG_QUERY = """
NTANetAnalytics
| where TimeGenerated > ago(1d)
| where SubType == "FlowLog"
| where isnotempty(SrcIp) and isnotempty(DestIp)
| summarize arg_max(TimeGenerated, *) by SrcIp, DestIp, L4Protocol, DestPort, FlowStatus
| project TimeGenerated, SrcIp, DestIp, L4Protocol, DestPort, FlowStatus,
          FlowDirection, FlowType, AclGroup, AclRule
| order by TimeGenerated desc
""".strip()

# Guest performance counters written by the "classic" (logs-based) Azure
# Monitor Agent perf collection path. These cover the two signals the
# platform Metrics API cannot provide for an ordinary VM: memory utilization
# and disk free space. Windows and Linux report different counter names for
# the same concept, so both are queried and normalized to one row per
# resource with the latest sample for each metric.
GUEST_PERFORMANCE_QUERY = """
Perf
| where (ObjectName == "Memory" and CounterName in ("% Committed Bytes In Use", "% Used Memory"))
   or (ObjectName == "LogicalDisk" and CounterName == "% Free Space" and InstanceName == "_Total")
| summarize arg_max(TimeGenerated, CounterValue) by _ResourceId, CounterName
| project _ResourceId, CounterName, CounterValue
""".strip()

KUBE_POD_INVENTORY_QUERY = """
KubePodInventory
| where TimeGenerated > ago(15m)
| project TimeGenerated, ClusterId, Namespace, ControllerKind, ControllerName,
          Name, PodUid, ContainerID, ContainerName, _SubscriptionId
| order by TimeGenerated desc
| take 25000
""".strip()

CONTAINER_INVENTORY_QUERY = """
ContainerInventory
| where TimeGenerated > ago(15m)
| project TimeGenerated, ContainerID, Image, ImageID, Repository, Name, _SubscriptionId
| order by TimeGenerated desc
| take 25000
""".strip()

CONTAINER_IMAGE_INVENTORY_QUERY = """
ContainerImageInventory
| where TimeGenerated > ago(15m)
| project TimeGenerated, ImageID, Repository, Tag, _SubscriptionId
| order by TimeGenerated desc
| take 25000
""".strip()

CONTAINER_INSIGHTS_QUERIES = {
    "kube_pod_inventory": KUBE_POD_INVENTORY_QUERY,
    "container_inventory": CONTAINER_INVENTORY_QUERY,
    "container_image_inventory": CONTAINER_IMAGE_INVENTORY_QUERY,
}
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
        return self._execute(workspace_id, CONFIGURATION_DATA_QUERY, "ConfigurationData")

    query = query_configuration_data

    def query_nsg_flow_logs(self, workspace_id: str) -> list[dict[str, Any]]:
        """Latest observed NSG flow records from Traffic Analytics, one per
        distinct (source, destination, protocol, port, decision) bucket over
        the last day. Returns raw ``NTANetAnalytics`` rows -- callers are
        responsible for mapping them onto :class:`FlowLogRecord`."""
        return self._execute(workspace_id, NSG_FLOW_LOG_QUERY, "NSG flow log")

    def query_guest_performance(self, workspace_id: str) -> dict[str, dict[str, float]]:
        """Latest memory/disk-free guest performance counters, keyed by resource ID.

        Returns ``{resource_id_lower: {"memory_percent": ..., "disk_free_percent": ...}}``.
        Memory is normalized to "percent used" and disk to "percent free" so the
        caller can merge these directly into a utilization snapshot alongside the
        platform Metrics API's CPU/network/disk-IO readings.
        """
        rows = self._execute(workspace_id, GUEST_PERFORMANCE_QUERY, "guest performance")
        by_resource: dict[str, dict[str, float]] = {}
        for row in rows:
            resource_id = str(row.get("_ResourceId") or "").strip().casefold()
            counter = str(row.get("CounterName") or "")
            value = row.get("CounterValue")
            if not resource_id or not isinstance(value, (int, float)):
                continue
            bucket = by_resource.setdefault(resource_id, {})
            if counter in ("% Committed Bytes In Use", "% Used Memory"):
                bucket["memory_percent"] = float(value)
            elif counter == "% Free Space":
                bucket["disk_free_percent"] = float(value)
        return by_resource

    def query_kube_pod_inventory(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._execute(
            workspace_id,
            KUBE_POD_INVENTORY_QUERY,
            "KubePodInventory",
        )

    def query_container_inventory(self, workspace_id: str) -> list[dict[str, Any]]:
        return self._execute(
            workspace_id,
            CONTAINER_INVENTORY_QUERY,
            "ContainerInventory",
        )

    def query_container_image_inventory(
        self, workspace_id: str
    ) -> list[dict[str, Any]]:
        return self._execute(
            workspace_id,
            CONTAINER_IMAGE_INVENTORY_QUERY,
            "ContainerImageInventory",
        )

    def _execute(
        self, workspace_id: str, query: str, label: str
    ) -> list[dict[str, Any]]:
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
            json={"query": query},
            timeout=self.limits.timeout_seconds,
        )
        if response.status_code >= 400:
            detail = response.text.strip()[:512] or f"HTTP {response.status_code}"
            raise RuntimeError(f"Logs {label} query failed: {detail}")
        content = response.content
        if len(content) > self.limits.max_response_bytes:
            raise RuntimeError(f"Logs {label} response exceeded the configured byte limit")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Logs {label} response was not valid JSON") from exc
        return parse_logs_tables(payload, max_rows=self.limits.max_rows)


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


def validate_workspace_id(value: str) -> str:
    """Validate a workspace identifier at a configuration boundary."""
    return _validated_workspace_id(value)
