"""Unit tests for :class:`ResourceHealthService`."""

from __future__ import annotations

from types import SimpleNamespace

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
