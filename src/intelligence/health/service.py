"""Live Azure Monitor Metrics + Logs utilization for compute resources.

Fetches VM/server platform metrics (CPU %, network and disk I/O) per active
connection, scoped by subscription. This deliberately mirrors the "live,
uncached" pattern used by :class:`ConnectionScopedLiveResourceProvider` --
utilization is observed at request time rather than persisted, since a stale
CPU reading is actively misleading.

Memory utilization and disk free-space are *not* exposed by the platform
Metrics API for ordinary VMs -- they require the Azure Monitor Agent's
"classic" guest performance counters, written to a Log Analytics workspace.
When a ``guest_performance_reader`` is supplied, this service auto-discovers
the Log Analytics workspaces in scope (the same ARG-based discovery already
used for software inventory) and merges the latest memory/disk-free reading
per resource into the snapshot. Without one, those two fields remain
unavailable and every response says so explicitly via ``unavailable_metrics``
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
#
# Arc-connected servers (microsoft.hybridcompute/machines) are intentionally
# excluded: they are not a supported platform metric namespace for the Azure
# Monitor Metrics REST API (confirmed by the API's own "not a supported
# platform metric namespace" error) -- Arc machine CPU/network/disk data is
# only available via the Azure Monitor Agent writing guest performance
# counters to Log Analytics, the same gap already called out for memory and
# disk-free metrics above.
SUPPORTED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "microsoft.compute/virtualmachines",
    }
)

# Guest-level signals the platform Metrics API cannot provide for an ordinary
# VM. These are only actually filled in when the service is constructed with a
# guest_performance_reader; otherwise they are surfaced as a standing warning
# so the UI never implies these are simply zero or healthy.
UNAVAILABLE_METRICS: tuple[str, ...] = (
    "memory_percent",
    "disk_free_percent",
)

# Resource type ARG discovers Log Analytics workspaces under.
_LAW_RESOURCE_TYPE = "microsoft.operationalinsights/workspaces"

_CPU_WARNING_THRESHOLD = 70.0
_CPU_CRITICAL_THRESHOLD = 90.0


class MetricsReader(Protocol):
    def query_resource_metrics(self, resource_id: str) -> dict[str, Any]: ...


class GuestPerformanceReader(Protocol):
    """Reads Log Analytics guest performance counters for one workspace."""

    def query_guest_performance(self, workspace_id: str) -> dict[str, dict[str, float]]: ...


class OtelGuestPerformanceReader(Protocol):
    """Reads Azure Monitor Workspace (OTel) guest metrics for one endpoint."""

    def query_guest_performance(self, endpoint: Any) -> dict[str, dict[str, float]]: ...


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
    memory_percent: float | None = None
    disk_free_percent: float | None = None
    status: str = "unknown"
    observed_at: str = ""
    error: str = ""
    # Ordered {timestamp, value} points across the queried lookback window,
    # for trend/sparkline charts. Populated straight from the same Monitor
    # Metrics response that already produced cpu_percent -- no extra Azure
    # Monitor calls. Empty when the metric had no data or the resource had an
    # error (see _fetch_resource_utilization).
    cpu_series: tuple[dict[str, Any], ...] = field(default_factory=tuple)

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
            "memory_percent": self.memory_percent,
            "disk_free_percent": self.disk_free_percent,
            "status": self.status,
            "observed_at": self.observed_at,
            "error": self.error,
            "cpu_series": list(self.cpu_series),
        }


@dataclass(frozen=True)
class ResourceHealthSnapshot:
    """Bounded, scoped result set of live resource utilization."""

    resources: tuple[ResourceUtilization, ...]
    observed_at: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
    # Guest metrics that no in-scope connection could supply a reader for
    # (i.e. no Log Analytics workspace / Azure Monitor Agent guest counters
    # were available). Empty once a guest_performance_reader is wired in and
    # at least one resource's counters were found.
    unavailable_metrics: tuple[str, ...] = UNAVAILABLE_METRICS

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
            "unavailable_metrics": list(self.unavailable_metrics),
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
        law_lister: Callable[[Any], list[dict[str, Any]]] | None = None,
        guest_performance_reader_factory: Callable[[Any], GuestPerformanceReader]
        | None = None,
        amw_lister: Callable[[Any], list[dict[str, Any]]] | None = None,
        otel_performance_reader_factory: Callable[[Any], OtelGuestPerformanceReader]
        | None = None,
    ) -> None:
        if max_resources < 1:
            raise ValueError("Resource health max_resources must be positive")
        self.connections = connections
        self.resource_lister = resource_lister
        self.metrics_client_factory = metrics_client_factory
        self.max_resources = max_resources
        # Both are optional and only used together: law_lister discovers the
        # Log Analytics workspaces in scope for a connection (ARG rows with a
        # workspaceId column), and guest_performance_reader_factory builds a
        # reader that queries one workspace's memory/disk guest counters.
        self.law_lister = law_lister
        self.guest_performance_reader_factory = guest_performance_reader_factory
        # Same pairing for the OpenTelemetry path: amw_lister discovers Azure
        # Monitor Workspaces in scope (ARG rows with id/region columns, and
        # optionally a prometheusQueryEndpoint), and
        # otel_performance_reader_factory builds a PromQL reader for them.
        # Both metric sources are merged per-resource (see
        # _guest_performance_for_connection) since a subscription may have
        # some VMs on classic guest counters and others on OTel.
        self.amw_lister = amw_lister
        self.otel_performance_reader_factory = otel_performance_reader_factory

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
        guest_performance_found = False
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
            guest_performance = self._guest_performance_for_connection(connection, warnings)
            if guest_performance:
                guest_performance_found = True
            for row in candidates:
                results.append(
                    _fetch_resource_utilization(
                        row, connection, metrics_client, guest_performance
                    )
                )
        if len(results) > self.max_resources:
            results = results[: self.max_resources]
            warnings.append(
                "Results are truncated; narrow the scope for a complete view."
            )
        unavailable = () if guest_performance_found else UNAVAILABLE_METRICS
        return ResourceHealthSnapshot(
            resources=tuple(results),
            observed_at=_now(),
            warnings=tuple(warnings),
            unavailable_metrics=unavailable,
        )

    def _guest_performance_for_connection(
        self, connection: Any, warnings: list[str]
    ) -> dict[str, dict[str, float]]:
        """Merge memory/disk guest counters from every classic + OTel source in scope.

        Returns an empty dict (never raises) when neither path is wired in,
        or when workspace discovery/queries fail -- CPU and network/disk-IO
        metrics must still be returned even if this fails. When both the
        classic (Log Analytics) and OTel (Azure Monitor Workspace) paths
        supply a reading for the same resource, the OTel reading wins since
        it is the more actively-maintained/higher-fidelity source per-VM;
        callers should still get full coverage by merging non-overlapping
        resources from either source.
        """
        merged = self._classic_guest_performance(connection, warnings)
        otel = self._otel_guest_performance(connection, warnings)
        for resource_id, values in otel.items():
            merged.setdefault(resource_id, {}).update(values)
        return merged

    def _classic_guest_performance(
        self, connection: Any, warnings: list[str]
    ) -> dict[str, dict[str, float]]:
        if self.law_lister is None or self.guest_performance_reader_factory is None:
            return {}
        try:
            law_rows = self.law_lister(connection)
        except (RuntimeError, ValueError) as exc:
            warnings.append(
                f"Could not list Log Analytics workspaces for connection "
                f"'{connection.connection_id}': {exc}"
            )
            return {}
        workspace_ids = {
            str(row.get("workspaceId") or "").strip()
            for row in law_rows
            if str(row.get("workspaceId") or "").strip()
        }
        if not workspace_ids:
            return {}
        try:
            reader = self.guest_performance_reader_factory(connection)
        except (RuntimeError, ValueError) as exc:
            warnings.append(
                f"Could not build a Logs client for connection "
                f"'{connection.connection_id}': {exc}"
            )
            return {}
        merged: dict[str, dict[str, float]] = {}
        for workspace_id in workspace_ids:
            try:
                merged.update(reader.query_guest_performance(workspace_id))
            except (RuntimeError, ValueError):
                # One workspace's guest counters being unreachable (e.g. no
                # Azure Monitor Agent perf collection configured) must not
                # block CPU/network/disk-IO metrics for the rest of scope.
                continue
        return merged

    def _otel_guest_performance(
        self, connection: Any, warnings: list[str]
    ) -> dict[str, dict[str, float]]:
        if self.amw_lister is None or self.otel_performance_reader_factory is None:
            return {}
        try:
            amw_rows = self.amw_lister(connection)
        except (RuntimeError, ValueError) as exc:
            warnings.append(
                f"Could not list Azure Monitor Workspaces for connection "
                f"'{connection.connection_id}': {exc}"
            )
            return {}
        if not amw_rows:
            return {}
        try:
            reader = self.otel_performance_reader_factory(connection)
        except (RuntimeError, ValueError) as exc:
            warnings.append(
                f"Could not build a Prometheus client for connection "
                f"'{connection.connection_id}': {exc}"
            )
            return {}
        merged: dict[str, dict[str, float]] = {}
        for row in amw_rows:
            endpoint = row.get("endpoint")
            if endpoint is None:
                continue
            try:
                merged.update(reader.query_guest_performance(endpoint))
            except (RuntimeError, ValueError):
                # One Azure Monitor Workspace being unreachable (e.g. no
                # OTel collector configured, or an RBAC gap) must not block
                # CPU/network/disk-IO metrics -- or the classic guest path --
                # for the rest of scope.
                continue
        return merged


def _fetch_resource_utilization(
    row: dict[str, Any],
    connection: Any,
    metrics_client: MetricsReader,
    guest_performance: dict[str, dict[str, float]] | None = None,
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
    guest = (guest_performance or {}).get(resource_id.casefold(), {})
    try:
        metrics = metrics_client.query_resource_metrics(resource_id)
    except (RuntimeError, ValueError) as exc:
        return ResourceUtilization(
            **base,
            memory_percent=guest.get("memory_percent"),
            disk_free_percent=guest.get("disk_free_percent"),
            observed_at=_now(),
            error=str(exc),
        )

    cpu = _metric_value(metrics, "Percentage CPU")
    return ResourceUtilization(
        **base,
        cpu_percent=cpu,
        network_in_bytes=_metric_value(metrics, "Network In Total"),
        network_out_bytes=_metric_value(metrics, "Network Out Total"),
        disk_read_bytes=_metric_value(metrics, "Disk Read Bytes"),
        disk_write_bytes=_metric_value(metrics, "Disk Write Bytes"),
        os_disk_queue_depth=_metric_value(metrics, "OS Disk Queue Depth"),
        memory_percent=guest.get("memory_percent"),
        disk_free_percent=guest.get("disk_free_percent"),
        status=_cpu_status(cpu),
        observed_at=_now(),
        cpu_series=_metric_series(metrics, "Percentage CPU"),
    )


def _metric_value(metrics: dict[str, Any], name: str) -> float | None:
    entry = metrics.get(name)
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _metric_series(metrics: dict[str, Any], name: str) -> tuple[dict[str, Any], ...]:
    entry = metrics.get(name)
    if not isinstance(entry, dict):
        return ()
    series = entry.get("series")
    if not isinstance(series, list):
        return ()
    return tuple(point for point in series if isinstance(point, dict))


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
