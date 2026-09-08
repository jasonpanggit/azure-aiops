from __future__ import annotations

from dataclasses import dataclass

import pytest

from fabric.commands import FabricCommandService
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter


@dataclass
class Result:
    run_id: str = "run-1"
    source_run_id: str = "source-1"
    status: str = "completed"
    replay: bool = False
    rows_processed: int = 10
    rows_added: int = 8
    rows_changed: int = 2
    rows_removed: int = 0
    failed_records: int = 0
    tables: tuple[str, ...] = ("bronze_resources",)
    duration_seconds: float = 1.5


class FakeSync:
    def __init__(self):
        self.sync_calls = 0

    def sync(self, **_kwargs):
        self.sync_calls += 1
        return Result()

    def status(self):
        return [
            {"status": "failed", "timestamp": "2026-08-16T00:00:00Z"},
            {"status": "completed", "timestamp": "2026-08-17T00:00:00Z", "ingestion_run_id": "run-1"},
        ]

    def validate_current(self):
        return [type("Report", (), {"to_dict": lambda self: {"passed": True}})()]


def test_sync_agent_command_runs_fabric_sync() -> None:
    sync = FakeSync()

    result = FabricCommandService(sync).execute("Sync Azure inventory to OneLake")

    assert result["status"] == "completed"
    assert sync.sync_calls == 1


def test_status_and_last_sync_commands_are_read_only() -> None:
    sync = FakeSync()
    commands = FabricCommandService(sync)

    status = commands.execute("Show ingestion status")
    last = commands.execute("Show last Fabric sync")

    assert status["runs"] == 2
    assert last["ingestion_run_id"] == "run-1"
    assert sync.sync_calls == 0


def test_validate_command_returns_quality_reports() -> None:
    result = FabricCommandService(FakeSync()).execute("Validate inventory data")

    assert result["passed"]


def test_publish_catalog_command_is_idempotent(tmp_path) -> None:
    sync = FakeSync()
    sync.onelake = OneLakeWriter(
        "workspace", "lakehouse", local_root=tmp_path / "lakehouse"
    )
    sync.delta = DeltaWriter()
    commands = FabricCommandService(sync)

    first = commands.execute("Publish governed remediation catalog")
    second = commands.execute("Publish governed remediation catalog")

    assert first["action_count"] == 6
    assert first["policy_count"] == 4
    assert first["changed"] is True
    assert second["content_digest"] == first["content_digest"]
    assert second["changed"] is False


def test_unknown_fabric_command_is_rejected() -> None:
    with pytest.raises(ValueError, match="Supported commands"):
        FabricCommandService(FakeSync()).execute("Delete the lakehouse")
