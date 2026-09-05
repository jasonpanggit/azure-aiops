from __future__ import annotations

from pathlib import Path

import pytest
from deltalake import DeltaTable

from fabric.schema_registry import schema_for
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.partitioning import PartitioningPolicy

REQUIRED = {
    "tenant_id": "tenant-1",
    "subscription_id": "sub-1",
    "resource_id": "/subscriptions/sub-1/resources/r1",
    "timestamp": "2026-08-17T00:00:00Z",
    "change_version": "v1",
    "ingestion_run_id": "run-1",
}


def _rows(path: Path) -> list[dict]:
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def test_delta_writer_overwrite_and_append_are_idempotent_by_run(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(table, [{**REQUIRED, "name": "first"}], mode=DeltaWriteMode.OVERWRITE)
    writer.write(
        table,
        [{**REQUIRED, "resource_id": "r2", "name": "second"}],
        mode=DeltaWriteMode.APPEND,
    )
    writer.write(
        table,
        [{**REQUIRED, "resource_id": "r2", "name": "second"}],
        mode=DeltaWriteMode.APPEND,
    )

    assert {row["name"] for row in _rows(table)} == {"first", "second"}


def test_delta_writer_append_deduplicates_keys_within_incoming_batch(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(table, [{**REQUIRED, "name": "first"}], mode=DeltaWriteMode.OVERWRITE)
    duplicate = {**REQUIRED, "resource_id": "r2", "name": "second"}

    writer.write(
        table,
        [duplicate, dict(duplicate)],
        mode=DeltaWriteMode.APPEND,
    )

    rows = _rows(table)
    assert len(rows) == 2
    assert len({(row["ingestion_run_id"], row["resource_id"]) for row in rows}) == 2


def test_delta_writer_merge_upserts_by_resource_id(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(table, [{**REQUIRED, "name": "before"}], mode=DeltaWriteMode.OVERWRITE)

    result = writer.write(
        table,
        [{**REQUIRED, "name": "after", "change_version": "v2", "ingestion_run_id": "run-2"}],
        mode=DeltaWriteMode.MERGE,
        key_columns=("resource_id",),
    )

    assert _rows(table)[0]["name"] == "after"
    assert result.rows_changed == 1


def test_delta_writer_merge_skips_unchanged_change_version(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(table, [{**REQUIRED, "name": "stable"}], mode=DeltaWriteMode.OVERWRITE)

    result = writer.write(
        table,
        [{**REQUIRED, "name": "stable", "ingestion_run_id": "run-2"}],
        mode=DeltaWriteMode.MERGE,
        key_columns=("resource_id",),
    )

    assert result.rows_changed == 0
    assert _rows(table)[0]["ingestion_run_id"] == "run-1"


def test_delta_writer_snapshot_merge_upserts_and_deletes_stale_keys(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(
        table,
        [
            {**REQUIRED, "resource_id": "r1", "name": "keep-unchanged"},
            {**REQUIRED, "resource_id": "r2", "name": "will-update"},
            {**REQUIRED, "resource_id": "r3", "name": "will-be-deleted"},
        ],
        mode=DeltaWriteMode.OVERWRITE,
    )

    result = writer.write(
        table,
        [
            {**REQUIRED, "resource_id": "r1", "name": "keep-unchanged"},
            {
                **REQUIRED,
                "resource_id": "r2",
                "name": "updated",
                "change_version": "v2",
                "ingestion_run_id": "run-2",
            },
        ],
        mode=DeltaWriteMode.SNAPSHOT_MERGE,
        key_columns=("resource_id",),
    )

    rows_by_id = {row["resource_id"]: row for row in _rows(table)}
    assert set(rows_by_id) == {"r1", "r2"}
    assert rows_by_id["r2"]["name"] == "updated"
    # r1 was untouched by the merge predicate (same change_version), so its
    # original run_id is preserved -- proof this rewrote only changed rows.
    assert rows_by_id["r1"]["ingestion_run_id"] == "run-1"
    assert result.rows_removed == 1
    assert result.rows_changed == 1


def test_delta_writer_snapshot_merge_on_empty_source_deletes_all_rows(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.write(
        table,
        [{**REQUIRED, "resource_id": "r1", "name": "only"}],
        mode=DeltaWriteMode.OVERWRITE,
    )

    result = writer.write(
        table,
        [],
        mode=DeltaWriteMode.SNAPSHOT_MERGE,
        key_columns=("resource_id",),
        schema=schema_for("bronze_resources"),
    )

    assert result.rows_removed == 1
    assert _rows(table) == []


def test_delta_writer_rejects_missing_operational_columns(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ingestion_run_id"):
        DeltaWriter().write(
            tmp_path / "table",
            [{key: value for key, value in REQUIRED.items() if key != "ingestion_run_id"}],
            mode=DeltaWriteMode.OVERWRITE,
        )


def test_partition_policy_uses_tenant_and_subscription_for_inventory() -> None:
    assert PartitioningPolicy().columns_for("bronze_resources") == (
        "tenant_id",
        "subscription_id",
    )
    assert PartitioningPolicy().columns_for("metadata_ingestion_state") == ()


def test_delta_writer_retries_transient_failures(tmp_path: Path, monkeypatch) -> None:
    attempts = 0
    delays = []
    writer = DeltaWriter(max_attempts=3, sleep=delays.append)

    def flaky(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporarily unavailable")
        return DeltaWriteResult(rows_processed=1, rows_added=1)

    monkeypatch.setattr(writer, "_write_once", flaky)

    result = writer.write(
        tmp_path / "table",
        [REQUIRED],
        mode=DeltaWriteMode.OVERWRITE,
    )

    assert result.rows_added == 1
    assert attempts == 2
    assert delays == [1]


def test_delta_writer_refreshes_cloud_token_before_operation(tmp_path: Path, monkeypatch) -> None:
    issued = []
    writer = DeltaWriter(
        storage_options_provider=lambda: {
            "azure_storage_token": f"token-{len(issued) + 1}",
            "azure_use_fabric_endpoint": "true",
        }
    )

    def capture(*_args, **_kwargs):
        issued.append(writer.storage_options["azure_storage_token"])
        return DeltaWriteResult(rows_processed=1, rows_added=1)

    monkeypatch.setattr(writer, "_write_once", capture)
    writer.write(tmp_path / "table", [REQUIRED], mode=DeltaWriteMode.OVERWRITE)

    assert issued == ["token-1"]


def test_delta_writer_overwrite_empty_removes_snapshot_rows(tmp_path: Path) -> None:
    table = tmp_path / "table"
    row = {
        **REQUIRED,
        "entity_type": "Resource",
        "name": "resource",
        "resource_type": "microsoft.test/resources",
        "location": "eastus",
        "payload_json": "{}",
        "resource_group": "rg",
        "status": "",
        "os_name": "",
        "os_version": "",
        "vm_size": "",
    }
    writer = DeltaWriter()
    writer.write(
        table,
        [row],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("bronze_resources"),
    )

    result = writer.write(
        table,
        [],
        mode=DeltaWriteMode.OVERWRITE,
        schema=schema_for("bronze_resources"),
    )

    assert _rows(table) == []
    assert result.rows_removed == 1
