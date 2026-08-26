from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hermes_arg_connector.config import ConnectorConfig
from intelligence.inventory.pipeline import InventoryPipeline


class _InventorySource:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture

    def list_subscriptions(self) -> list[dict[str, str]]:
        return [{"subscriptionId": "sub-a"}, {"subscriptionId": "sub-b"}]

    def fetch(self, specs, subscription_ids: list[str]) -> dict[str, list[dict]]:
        return {
            spec.name: list(self.fixture.get(spec.name, []))
            for spec in specs
            if spec.name in self.fixture
        }


class _LogsSource:
    def __init__(
        self,
        rows: list[dict] | None,
        *,
        failures: set[str] | None = None,
    ) -> None:
        self.rows = rows
        self.failures = failures or set()

    def query_configuration_data(self, workspace_id: str) -> list[dict]:
        if workspace_id in self.failures:
            raise RuntimeError("workspace access denied")
        return list(self.rows or [])


def refresh_inventory(
    store_root: Path,
    *,
    fixture_path: Path | None = None,
    software_fixture_path: Path | None = None,
    software_rows: list[dict] | None = None,
    failed_workspaces: set[str] | None = None,
    workspaces: dict[str, str | tuple[str, ...]] | None = None,
    clock: datetime | None = None,
) -> dict[str, Any]:
    fixture_path = fixture_path or Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
    software_fixture_path = (
        software_fixture_path
        or Path(__file__).parent / "fixtures" / "mock_configurationdata.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if software_rows is None:
        software_rows = json.loads(software_fixture_path.read_text(encoding="utf-8"))
    if workspaces is None:
        workspaces = {"connection-1": "workspace-1"}
    config = ConnectorConfig(
        output_dir=store_root,
        subscriptions=("sub-a", "sub-b"),
        connection_context={"connection_id": "connection-1"},
        logs_workspaces=workspaces,
        cost_management_enabled=False,
    )
    service = InventoryPipeline(
        config,
        source=_InventorySource(fixture),
        logs_client=_LogsSource(software_rows, failures=failed_workspaces),
        clock=lambda: clock or datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    return service.refresh().manifest
