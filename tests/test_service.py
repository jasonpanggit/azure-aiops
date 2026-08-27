from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hermes_arg_connector.config import ConnectorConfig
from hermes_arg_connector.queries import QueryCatalog
from hermes_arg_connector.service import IngestionService, _merge_changes
from hermes_arg_connector.source import AzureResourceGraphSource

FIXTURE = Path(__file__).parent / "fixtures" / "mock_arg_responses.json"


class FakeSource:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, ...]] = []
        self.query_batches = []

    def list_subscriptions(self) -> list[dict]:
        return [{"subscriptionId": "sub-1", "tenantId": "tenant-1"}]

    def fetch(self, specs, subscription_ids):
        self.calls.append(tuple(subscription_ids))
        self.query_batches.append(list(specs))
        # A real source returns an empty result for a resource type the
        # subscription has none of, so an absent fixture key is not an error.
        return {spec.name: list(self.payload.get(spec.name, [])) for spec in specs}


class FakeCostSource:
    """Standalone cost-actuals source, independent of ARG discovery."""

    def __init__(self, payload: list[dict] | None = None, error: Exception | None = None) -> None:
        self.cost_payload = payload or []
        self.error = error
        self.cost_calls: list[tuple[tuple[str, ...], datetime, timedelta]] = []

    def fetch(self, subscription_ids, *, end, lookback):
        self.cost_calls.append((tuple(subscription_ids), end, lookback))
        if self.error is not None:
            raise self.error
        return list(self.cost_payload)


def test_end_to_end_mock_ingestion_tracks_incremental_state(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())
    source = FakeSource(payload)
    config = ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-1",))
    clock_values = iter([
        datetime(2026, 8, 17, 1, tzinfo=UTC),
        datetime(2026, 8, 17, 2, tzinfo=UTC),
    ])
    service = IngestionService(config, source=source, clock=lambda: next(clock_values))

    first = service.run()
    second = service.run()

    state = json.loads((tmp_path / "state/state.json").read_text())
    assert first["status"] == "completed"
    assert second["changedDatasets"] == []
    assert state["lastSuccessfulRun"] == "2026-08-17T02:00:00Z"
    assert state["resourceChangesWatermark"] == "2026-08-17T00:30:00Z"
    assert state["watermarkVersion"] == 2
    assert source.calls == [("sub-1",), ("sub-1",)]
    second_change_query = next(
        spec.query for spec in source.query_batches[1] if spec.name == "resource_changes"
    )
    assert "datetime(2026-08-17T00:20:00Z)" in second_change_query

    vm = json.loads((tmp_path / "current/entities/VirtualMachine.jsonl").read_text())
    assert vm["createdTimestamp"] == "2026-08-17T01:00:00Z"
    assert vm["lastObservedTimestamp"] == "2026-08-17T02:00:00Z"


def test_ingestion_publishes_cost_management_actuals(tmp_path: Path) -> None:
    source = FakeSource(json.loads(FIXTURE.read_text()))
    cost_source = FakeCostSource(
        payload=[
            {
                "subscriptionId": "sub-1",
                "usageDate": "2026-08-17",
                "cost": 42.5,
                "currency": "AUD",
                "resourceId": "/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-prod",
                "resourceGroup": "rg-prod",
                "serviceName": "Virtual Machines",
            }
        ]
    )
    config = ConnectorConfig(
        output_dir=tmp_path,
        subscriptions=("sub-1",),
        cost_management_lookback_days=7,
    )

    IngestionService(
        config,
        source=source,
        cost_source=cost_source,
        clock=lambda: datetime(2026, 8, 17, 1, tzinfo=UTC),
    ).run()

    rows = [
        json.loads(line)
        for line in (tmp_path / "current/entities/CostActual.jsonl").read_text().splitlines()
    ]
    assert rows[0]["cost"] == 42.5
    assert rows[0]["currency"] == "AUD"
    assert rows[0]["targetResourceId"].endswith("/virtualmachines/vm-prod")
    assert cost_source.cost_calls[0][0] == ("sub-1",)
    assert cost_source.cost_calls[0][2] == timedelta(days=7)


def test_cost_management_failure_does_not_fail_discovery(tmp_path: Path) -> None:
    """A Cost Management outage/throttle must never fail the semantic graph sync."""
    source = FakeSource(json.loads(FIXTURE.read_text()))
    cost_source = FakeCostSource(error=RuntimeError("429 Too Many Requests"))
    config = ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-1",))

    manifest = IngestionService(
        config,
        source=source,
        cost_source=cost_source,
        clock=lambda: datetime(2026, 8, 17, 1, tzinfo=UTC),
    ).run()

    assert manifest["status"] == "completed"
    rows = [
        json.loads(line)
        for line in (tmp_path / "current/entities/CostActual.jsonl").read_text().splitlines()
    ]
    assert rows == []
    vm = json.loads((tmp_path / "current/entities/VirtualMachine.jsonl").read_text())
    assert vm["id"]


def test_incremental_run_preserves_prior_resource_change_history(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text())

    class DeltaSource(FakeSource):
        def fetch(self, specs, subscription_ids):
            result = super().fetch(specs, subscription_ids)
            if len(self.calls) == 2:
                result["resource_changes"] = []
            return result

    source = DeltaSource(payload)
    config = ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-1",))
    times = iter([
        datetime(2026, 8, 17, 1, tzinfo=UTC),
        datetime(2026, 8, 17, 2, tzinfo=UTC),
    ])
    service = IngestionService(config, source=source, clock=lambda: next(times))

    service.run()
    service.run()

    changes = (tmp_path / "current/changes/resource_changes.jsonl").read_text().splitlines()
    assert len(changes) == 1


def test_source_fetches_independent_arg_queries_in_parallel() -> None:
    specs = QueryCatalog().build(None)
    workers = len(specs)
    barrier = threading.Barrier(workers)

    class ParallelArg:
        def query(self, spec, subscription_ids):
            barrier.wait(timeout=5)
            return [{"query": spec.name}]

    source = AzureResourceGraphSource(mcp=None, arg=ParallelArg(), max_workers=workers)

    result = source.fetch(specs, ["sub-1"])

    assert set(result) == {spec.name for spec in specs}


def test_service_repairs_legacy_overadvanced_watermark(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps({"resourceChangesWatermark": "2026-08-17T02:00:00Z"})
    )
    source = FakeSource(json.loads(FIXTURE.read_text()))
    service = IngestionService(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-1",)),
        source=source,
        clock=lambda: datetime(2026, 8, 17, 3, tzinfo=UTC),
    )

    service.run()

    change_query = next(spec.query for spec in source.query_batches[0] if spec.name == "resource_changes")
    state = json.loads((state_dir / "state.json").read_text())
    assert "ago(7d)" in change_query
    assert state["resourceChangesWatermark"] == "2026-08-17T00:30:00Z"
    assert state["watermarkVersion"] == 2


def test_change_merge_uses_case_insensitive_azure_ids() -> None:
    previous = [
        {"id": "/SUBSCRIPTIONS/SUB-1/CHANGES/ABC", "changedAt": "2026-08-17T00:30:00Z"}
    ]
    current = [
        {"id": "/subscriptions/sub-1/changes/abc", "changedAt": "2026-08-17T00:30:00Z"}
    ]

    merged = _merge_changes(previous, current)

    assert len(merged) == 1
