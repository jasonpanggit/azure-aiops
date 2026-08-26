from __future__ import annotations

import json
from pathlib import Path

from hermes_arg_connector.storage import DatasetStore
from intelligence.inventory.service import InventoryService

from inventory_harness import refresh_inventory


def test_failed_software_refresh_retains_rows_with_non_ready_state(tmp_path: Path) -> None:
    refresh_inventory(tmp_path)
    before = InventoryService.from_store(DatasetStore(tmp_path))
    assert before is not None
    before_rows = [row.to_dict() for row in before.snapshot.software_observations]

    refresh_inventory(tmp_path, failed_workspaces={"workspace-1"})
    after = InventoryService.from_store(DatasetStore(tmp_path))

    assert after is not None
    status = after.software_source_status()["logs"]
    assert ([row.to_dict() for row in after.snapshot.software_observations], status["state"]) == (
        before_rows,
        "degraded",
    )
    assert status["error"]


def test_successful_empty_software_refresh_replaces_rows_as_ready_empty(
    tmp_path: Path,
) -> None:
    refresh_inventory(tmp_path)
    refresh_inventory(tmp_path, software_rows=[])
    loaded = InventoryService.from_store(DatasetStore(tmp_path))

    assert loaded is not None
    assert (
        list(loaded.snapshot.software_observations),
        loaded.software_source_status()["logs"]["state"],
        loaded.software_source_status()["logs"]["row_count"],
    ) == ([], "ready", 0)


def test_read_model_reports_no_snapshot_before_generation_is_active(tmp_path: Path) -> None:
    assert InventoryService.from_store(DatasetStore(tmp_path)) is None


def test_inventory_timestamp_and_watermark_preservation_is_empirically_absent(
    tmp_path: Path,
) -> None:
    refresh_inventory(tmp_path)
    first = DatasetStore(tmp_path).read_dataset("inventory/software_source_status")[0]
    refresh_inventory(tmp_path)
    second = DatasetStore(tmp_path).read_dataset("inventory/software_source_status")[0]

    assert "watermark" not in first
    assert "watermark" not in second
    assert first["observed_at"] == second["observed_at"]


def test_mock_inventory_fixture_remains_valid_json() -> None:
    fixture = Path(__file__).parent / "fixtures" / "mock_inventory_arg.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert "inventory_native_vm_os" in payload
    assert "inventory_arc_os" in payload
