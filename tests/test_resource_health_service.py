"""Unit tests for :class:`ResourceHealthService`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from intelligence.health.service import ResourceHealthService, _cpu_status


def _connection(connection_id="conn-1", subscription_id="sub-1", is_active=True):
    return SimpleNamespace(
        connection_id=connection_id, subscription_id=subscription_id, is_active=is_active
    )


class _FakeMetricsClient:
    def __init__(self, readings: dict[str, dict[str, float]] | None = None, error=None):
        self.readings = readings or {}
        self.error = error

    def query_resource_metrics(self, resource_id: str) -> dict:
        if self.error is not None:
            raise self.error
        return self.readings


def _vm_row(name="vm-1", resource_type="microsoft.compute/virtualmachines"):
    return {
        "id": f"/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/{name}",
        "name": name,
        "type": resource_type,
        "subscriptionId": "sub-1",
        "resourceGroup": "rg",
    }


def test_cpu_status_thresholds():
    assert _cpu_status(None) == "unknown"
    assert _cpu_status(10.0) == "healthy"
    assert _cpu_status(75.0) == "warning"
    assert _cpu_status(95.0) == "critical"


def test_snapshot_returns_utilization_for_supported_resources():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 42.0, "unit": "Percent", "timestamp": "t"}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [_vm_row(), {**_vm_row("net-1"), "type": "microsoft.network/virtualnetworks"}],
        metrics_client_factory=lambda _conn: metrics_client,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert len(snapshot.resources) == 1
    resource = snapshot.resources[0]
    assert resource.resource_name == "vm-1"
    assert resource.cpu_percent == 42.0
    assert resource.status == "healthy"
    assert snapshot.summary()["healthy"] == 1
    assert snapshot.to_dict()["unavailable_metrics"] == [
        "memory_percent",
        "disk_free_percent",
    ]


def test_snapshot_flags_no_matching_connection():
    service = ResourceHealthService(
        connections=lambda: [_connection(subscription_id="other-sub")],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: _FakeMetricsClient(),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert snapshot.resources == ()
    assert snapshot.warnings


def test_snapshot_records_warning_when_resource_listing_fails():
    def _boom(_conn):
        raise RuntimeError("ARG query failed")

    service = ResourceHealthService(
        connections=lambda: [_connection()],
        resource_lister=_boom,
        metrics_client_factory=lambda _conn: _FakeMetricsClient(),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert snapshot.resources == ()
    assert any("ARG query failed" in warning for warning in snapshot.warnings)


def test_snapshot_records_per_resource_error_without_aborting():
    metrics_client = _FakeMetricsClient(error=RuntimeError("Monitor Metrics 429"))
    service = ResourceHealthService(
        connections=lambda: [_connection()],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: metrics_client,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert len(snapshot.resources) == 1
    assert snapshot.resources[0].status == "unknown"
    assert "Monitor Metrics 429" in snapshot.resources[0].error


def test_snapshot_truncates_at_max_resources():
    rows = [_vm_row(name=f"vm-{i}") for i in range(5)]
    metrics_client = _FakeMetricsClient({"Percentage CPU": {"value": 1.0}})
    service = ResourceHealthService(
        connections=lambda: [_connection()],
        resource_lister=lambda _conn: rows,
        metrics_client_factory=lambda _conn: metrics_client,
        max_resources=2,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    # Per-connection candidates are already capped at max_resources before the
    # global truncation check, so a single over-limit connection is silently
    # capped rather than warned; the warning only fires when multiple
    # connections' results *combined* exceed the cap.
    assert len(snapshot.resources) == 2


class _FakeGuestPerformanceReader:
    def __init__(self, by_workspace: dict[str, dict[str, dict[str, float]]] | None = None, error=None):
        self.by_workspace = by_workspace or {}
        self.error = error
        self.queried: list[str] = []

    def query_guest_performance(self, workspace_id: str) -> dict:
        self.queried.append(workspace_id)
        if self.error is not None:
            raise self.error
        return self.by_workspace.get(workspace_id, {})


def test_snapshot_merges_guest_performance_when_workspace_discovered():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 10.0, "unit": "Percent", "timestamp": "t"}}
    )
    vm_row = _vm_row()
    reader = _FakeGuestPerformanceReader(
        {"law-1": {vm_row["id"].casefold(): {"memory_percent": 55.5, "disk_free_percent": 20.0}}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [vm_row],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [{"workspaceId": "law-1"}],
        guest_performance_reader_factory=lambda _conn: reader,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.memory_percent == 55.5
    assert resource.disk_free_percent == 20.0
    assert reader.queried == ["law-1"]
    assert snapshot.to_dict()["unavailable_metrics"] == []


def test_snapshot_reports_metrics_unavailable_when_no_workspace_discovered():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 10.0, "unit": "Percent", "timestamp": "t"}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [],
        guest_performance_reader_factory=lambda _conn: _FakeGuestPerformanceReader(),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.memory_percent is None
    assert resource.disk_free_percent is None
    assert snapshot.to_dict()["unavailable_metrics"] == [
        "memory_percent",
        "disk_free_percent",
    ]


def test_snapshot_guest_performance_failure_does_not_block_cpu_metrics():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 33.0, "unit": "Percent", "timestamp": "t"}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [{"workspaceId": "law-1"}],
        guest_performance_reader_factory=lambda _conn: _FakeGuestPerformanceReader(
            error=RuntimeError("workspace unreachable")
        ),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.cpu_percent == 33.0
    assert resource.memory_percent is None
    assert snapshot.warnings == ()


def test_snapshot_law_lister_failure_adds_warning_but_keeps_metrics():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 33.0, "unit": "Percent", "timestamp": "t"}}
    )

    def failing_law_lister(_conn):
        raise RuntimeError("ARG query failed")

    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=failing_law_lister,
        guest_performance_reader_factory=lambda _conn: _FakeGuestPerformanceReader(),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert snapshot.resources[0].cpu_percent == 33.0
    assert len(snapshot.warnings) == 1
    assert "Log Analytics workspaces" in snapshot.warnings[0]


class _FakeOtelPerformanceReader:
    def __init__(self, by_endpoint: dict[Any, dict[str, dict[str, float]]] | None = None, error=None):
        self.by_endpoint = by_endpoint or {}
        self.error = error
        self.queried: list[Any] = []

    def query_guest_performance(self, endpoint: Any) -> dict:
        self.queried.append(endpoint)
        if self.error is not None:
            raise self.error
        return self.by_endpoint.get(endpoint, {})


def test_snapshot_merges_otel_guest_performance_when_amw_discovered():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 10.0, "unit": "Percent", "timestamp": "t"}}
    )
    vm_row = _vm_row()
    reader = _FakeOtelPerformanceReader(
        {"endpoint-1": {vm_row["id"].casefold(): {"memory_percent": 61.0, "disk_free_percent": 15.0}}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [vm_row],
        metrics_client_factory=lambda _conn: metrics_client,
        amw_lister=lambda _conn: [{"endpoint": "endpoint-1"}],
        otel_performance_reader_factory=lambda _conn: reader,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.memory_percent == 61.0
    assert resource.disk_free_percent == 15.0
    assert reader.queried == ["endpoint-1"]
    assert snapshot.to_dict()["unavailable_metrics"] == []


def test_snapshot_prefers_otel_over_classic_for_same_resource():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 10.0, "unit": "Percent", "timestamp": "t"}}
    )
    vm_row = _vm_row()
    classic_reader = _FakeGuestPerformanceReader(
        {"law-1": {vm_row["id"].casefold(): {"memory_percent": 30.0, "disk_free_percent": 40.0}}}
    )
    otel_reader = _FakeOtelPerformanceReader(
        {"endpoint-1": {vm_row["id"].casefold(): {"memory_percent": 61.0, "disk_free_percent": 15.0}}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [vm_row],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [{"workspaceId": "law-1"}],
        guest_performance_reader_factory=lambda _conn: classic_reader,
        amw_lister=lambda _conn: [{"endpoint": "endpoint-1"}],
        otel_performance_reader_factory=lambda _conn: otel_reader,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.memory_percent == 61.0
    assert resource.disk_free_percent == 15.0


def test_snapshot_merges_classic_and_otel_for_different_resources():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 10.0, "unit": "Percent", "timestamp": "t"}}
    )
    classic_vm = _vm_row("vm-classic")
    otel_vm = _vm_row("vm-otel")
    classic_reader = _FakeGuestPerformanceReader(
        {"law-1": {classic_vm["id"].casefold(): {"memory_percent": 30.0, "disk_free_percent": 40.0}}}
    )
    otel_reader = _FakeOtelPerformanceReader(
        {"endpoint-1": {otel_vm["id"].casefold(): {"memory_percent": 61.0, "disk_free_percent": 15.0}}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [classic_vm, otel_vm],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [{"workspaceId": "law-1"}],
        guest_performance_reader_factory=lambda _conn: classic_reader,
        amw_lister=lambda _conn: [{"endpoint": "endpoint-1"}],
        otel_performance_reader_factory=lambda _conn: otel_reader,
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    by_name = {r.resource_name: r for r in snapshot.resources}
    assert by_name["vm-classic"].memory_percent == 30.0
    assert by_name["vm-otel"].memory_percent == 61.0
    assert snapshot.to_dict()["unavailable_metrics"] == []


def test_snapshot_otel_failure_does_not_block_classic_or_cpu_metrics():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 33.0, "unit": "Percent", "timestamp": "t"}}
    )
    vm_row = _vm_row()
    classic_reader = _FakeGuestPerformanceReader(
        {"law-1": {vm_row["id"].casefold(): {"memory_percent": 30.0, "disk_free_percent": 40.0}}}
    )
    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [vm_row],
        metrics_client_factory=lambda _conn: metrics_client,
        law_lister=lambda _conn: [{"workspaceId": "law-1"}],
        guest_performance_reader_factory=lambda _conn: classic_reader,
        amw_lister=lambda _conn: [{"endpoint": "endpoint-1"}],
        otel_performance_reader_factory=lambda _conn: _FakeOtelPerformanceReader(
            error=RuntimeError("AMW unreachable")
        ),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    resource = snapshot.resources[0]
    assert resource.cpu_percent == 33.0
    assert resource.memory_percent == 30.0
    assert snapshot.warnings == ()


def test_snapshot_amw_lister_failure_adds_warning_but_keeps_metrics():
    connection = _connection()
    metrics_client = _FakeMetricsClient(
        {"Percentage CPU": {"value": 33.0, "unit": "Percent", "timestamp": "t"}}
    )

    def failing_amw_lister(_conn):
        raise RuntimeError("ARG query failed")

    service = ResourceHealthService(
        connections=lambda: [connection],
        resource_lister=lambda _conn: [_vm_row()],
        metrics_client_factory=lambda _conn: metrics_client,
        amw_lister=failing_amw_lister,
        otel_performance_reader_factory=lambda _conn: _FakeOtelPerformanceReader(),
    )

    snapshot = service.snapshot(subscription_ids=["sub-1"])

    assert snapshot.resources[0].cpu_percent == 33.0
    assert len(snapshot.warnings) == 1
    assert "Azure Monitor Workspaces" in snapshot.warnings[0]
