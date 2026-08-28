"""Live Azure Monitor Metrics utilization for compute resources.

Fetches VM/server platform metrics (CPU %, network and disk I/O) per active
connection, scoped by subscription. This deliberately mirrors the "live,
uncached" pattern used by :class:`ConnectionScopedLiveResourceProvider` --
utilization is observed at request time rather than persisted, since a stale
CPU reading is actively misleading.

Memory utilization and disk free-space are *not* exposed by the platform
Metrics API for ordinary VMs -- they require the Azure Monitor Agent and
Log Analytics guest performance counters, which are not wired into this
service. Every response says so explicitly via ``unavailable_metrics``
rather than silently omitting the fields.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

# Azure resource types this service will fetch platform metrics for. Limited to
# compute types with well-known Monitor metric namespaces; unsupported types
# are silently skipped rather than producing noisy per-resource errors.
SUPPORTED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "microsoft.compute/virtualmachines",
        "microsoft.hybridcompute/machines",
    }
)

# Guest-level signals the platform Metrics API cannot provide for an ordinary
# VM. Surfaced as a standing warning so the UI never implies these are simply
# zero or healthy.
UNAVAILABLE_METRICS: tuple[str, ...] = (
    "memory_percent",
    "disk_free_percent",
)

_CPU_WARNING_THRESHOLD = 70.0
_CPU_CRITICAL_THRESHOLD = 90.0


class MetricsReader(Protocol):
    def query_resource_metrics(self, resource_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ResourceUtilization:
    """A single resource's most recent platform-metric readings."""

    resource_id: str
    resource_name: str
    resource_type: str
    subscription_id: str
    resource_group: str
    connection_id: str
    cpu_percent: float | None = None
    network_in_bytes: float | None = None
    network_out_bytes: float | None = None
    disk_read_bytes: float | None = None
    disk_write_bytes: float | None = None
    os_disk_queue_depth: float | None = None
    status: str = "unknown"
    observed_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "resource_type": self.resource_type,
            "subscription_id": self.subscription_id,
            "resource_group": self.resource_group,
            "connection_id": self.connection_id,
            "cpu_percent": self.cpu_percent,
            "network_in_bytes": self.network_in_bytes,
            "network_out_bytes": self.network_out_bytes,
            "disk_read_bytes": self.disk_read_bytes,
            "disk_write_bytes": self.disk_write_bytes,
            "os_disk_queue_depth": self.os_disk_queue_depth,
            "status": self.status,
            "observed_at": self.observed_at,
            "error": self.error,
            "unavailable_metrics": list(UNAVAILABLE_METRICS),
        }


@dataclass(frozen=True)
class ResourceHealthSnapshot:
    """Bounded, scoped result set of live resource utilization."""

    resources: tuple[ResourceUtilization, ...]
    observed_at: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        counted = [r for r in self.resources if r.status != "unknown"]
        return {
            "total": len(self.resources),
            "critical": sum(1 for r in counted if r.status == "critical"),
            "warning": sum(1 for r in counted if r.status == "warning"),
            "healthy": sum(1 for r in counted if r.status == "healthy"),
            "unknown": sum(1 for r in self.resources if r.status == "unknown"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "resources": [r.to_dict() for r in self.resources],
            "summary": self.summary(),
            "observed_at": self.observed_at,
            "warnings": list(self.warnings),
            "unavailable_metrics": list(UNAVAILABLE_METRICS),
        }


def _cpu_status(cpu_percent: float | None) -> str:
    if cpu_percent is None:
        return "unknown"
    if cpu_percent >= _CPU_CRITICAL_THRESHOLD:
        return "critical"
    if cpu_percent >= _CPU_WARNING_THRESHOLD:
        return "warning"
    return "healthy"


class ResourceHealthService:
    """Resolve in-scope compute resources per connection and fetch live metrics.

    ``connections`` lists the active :class:`SubscriptionConnection` objects to
    consider. ``resource_lister`` returns the raw ARG rows (id/name/type/
    subscriptionId/resourceGroup) for one connection's subscription -- callers
    typically bind this to :meth:`ConnectionScopedLiveResourceProvider.query`
    for a single connection. ``metrics_client_factory`` builds a
    :class:`AzureMonitorMetricsClient`-shaped reader for one connection.
    """

    def __init__(
        self,
        connections: Callable[[], list[Any]],
        resource_lister: Callable[[Any], list[dict[str, Any]]],
        metrics_client_factory: Callable[[Any], MetricsReader],
        *,
        max_resources: int = 200,
    ) -> None:
        if max_resources < 1:
            raise ValueError("Resource health max_resources must be positive")
        self.connections = connections
        self.resource_lister = resource_lister
        self.metrics_client_factory = metrics_client_factory
        self.max_resources = max_resources

    def snapshot(self, *, subscription_ids: list[str]) -> ResourceHealthSnapshot:
        matches = [
            connection
            for connection in self.connections()
            if getattr(connection, "is_active", True)
            and (
                not subscription_ids
                or str(getattr(connection, "subscription_id", "")) in subscription_ids
            )
        ]
        if not matches:
            return ResourceHealthSnapshot(
                resources=(),
                observed_at=_now(),
                warnings=("No active connection matches the requested subscription scope.",),
            )

        results: list[ResourceUtilization] = []
        warnings: list[str] = []
        for connection in matches:
            try:
                rows = self.resource_lister(connection)
            except (RuntimeError, ValueError) as exc:
                warnings.append(
                    f"Could not list resources for connection '{connection.connection_id}': {exc}"
                )
                continue
            candidates = [
                row
                for row in rows
                if str(row.get("type", "")).casefold() in SUPPORTED_RESOURCE_TYPES
            ][: self.max_resources]
            if not candidates:
                continue
            try:
                metrics_client = self.metrics_client_factory(connection)
            except (RuntimeError, ValueError) as exc:
                warnings.append(
                    f"Could not build a Monitor Metrics client for connection "
                    f"'{connection.connection_id}': {exc}"
                )
                continue
            for row in candidates:
                results.append(
                    _fetch_resource_utilization(row, connection, metrics_client)
                )
        if len(results) > self.max_resources:
            results = results[: self.max_resources]
            warnings.append(
                "Results are truncated; narrow the scope for a complete view."
            )
        return ResourceHealthSnapshot(
            resources=tuple(results), observed_at=_now(), warnings=tuple(warnings)
        )


def _fetch_resource_utilization(
    row: dict[str, Any], connection: Any, metrics_client: MetricsReader
) -> ResourceUtilization:
    resource_id = str(row.get("id") or "")
    base = {
        "resource_id": resource_id,
        "resource_name": str(row.get("name") or ""),
        "resource_type": str(row.get("type") or ""),
        "subscription_id": str(row.get("subscriptionId") or ""),
        "resource_group": str(row.get("resourceGroup") or ""),
        "connection_id": str(getattr(connection, "connection_id", "")),
    }
    try:
        metrics = metrics_client.query_resource_metrics(resource_id)
    except (RuntimeError, ValueError) as exc:
        return ResourceUtilization(**base, observed_at=_now(), error=str(exc))

    cpu = _metric_value(metrics, "Percentage CPU")
    return ResourceUtilization(
        **base,
        cpu_percent=cpu,
        network_in_bytes=_metric_value(metrics, "Network In Total"),
        network_out_bytes=_metric_value(metrics, "Network Out Total"),
        disk_read_bytes=_metric_value(metrics, "Disk Read Bytes"),
        disk_write_bytes=_metric_value(metrics, "Disk Write Bytes"),
        os_disk_queue_depth=_metric_value(metrics, "OS Disk Queue Depth"),
        status=_cpu_status(cpu),
        observed_at=_now(),
    )


def _metric_value(metrics: dict[str, Any], name: str) -> float | None:
    entry = metrics.get(name)
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
