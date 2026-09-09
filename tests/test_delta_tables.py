from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from deltalake import DeltaTable
from deltalake.exceptions import DeltaError

import storage.delta_writer as delta_writer_module
from fabric.schema_registry import schema_for
from storage.delta_writer import (
    DeltaWriteMode,
    DeltaWriter,
    DeltaWriteResult,
    _is_transient,
)
from storage.partitioning import PartitioningPolicy

REQUIRED = {
    "tenant_id": "tenant-1",
    "subscription_id": "sub-1",
    "resource_id": "/subscriptions/sub-1/resources/r1",
    "timestamp": "2026-08-17T00:00:00Z",
    "change_version": "v1",
    "ingestion_run_id": "run-1",
}


def _append_rows(count: int) -> list[dict[str, Any]]:
    return [
        {
            **REQUIRED,
            "resource_id": f"resource-{index}",
            "name": f"row-{index}",
        }
        for index in range(count)
    ]


def _rows(path: Path) -> list[dict]:
    return DeltaTable(str(path)).to_pyarrow_table().to_pylist()


def _remove_add_action_statistics(path: Path) -> None:
    log_file = next((path / "_delta_log").glob("*.json"))
    actions = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]
    removed = False
    for action in actions:
        add = action.get("add")
        if add is not None and "stats" in add:
            del add["stats"]
            removed = True
    assert removed
    log_file.write_text(
        "\n".join(json.dumps(action) for action in actions) + "\n",
        encoding="utf-8",
    )


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


def test_delta_writer_reads_exact_historical_version(tmp_path: Path) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    first = writer.write(
        table,
        [{**REQUIRED, "name": "first"}],
        mode=DeltaWriteMode.OVERWRITE,
    )
    second = writer.write(
        table,
        [{**REQUIRED, "name": "second", "change_version": "v2"}],
        mode=DeltaWriteMode.OVERWRITE,
    )

    assert first.version == 0
    assert second.version == 1
    assert writer.read(table, version=first.version)[0]["name"] == "first"
    assert writer.read(table, version=second.version)[0]["name"] == "second"


@pytest.mark.parametrize("version", [-1, True, 1.5, "1"])
def test_delta_writer_rejects_invalid_historical_version(
    tmp_path: Path,
    version: object,
) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        DeltaWriter().read(tmp_path / "table", version=version)  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    ("row_count", "expected_batch_sizes", "expected_copy_counts"),
    [
        (1, [1], [1]),
        (2, [2], [2]),
        (3, [2, 1], [2, 3]),
    ],
)
def test_delta_writer_append_bounds_python_and_arrow_materialization(
    tmp_path: Path,
    monkeypatch,
    row_count: int,
    expected_batch_sizes: list[int],
    expected_copy_counts: list[int],
) -> None:
    copied_rows: list[int] = []

    class CopyObservedRow(Mapping[str, Any]):
        def __init__(self, index: int, payload: Mapping[str, Any]) -> None:
            self.index = index
            self.payload = payload

        def __getitem__(self, key: str) -> Any:
            return self.payload[key]

        def __iter__(self) -> Iterator[str]:
            return iter(self.payload)

        def __len__(self) -> int:
            return len(self.payload)

        def keys(self):
            copied_rows.append(self.index)
            return self.payload.keys()

    original_write = delta_writer_module.write_deltalake
    observed_batches: list[tuple[int, int]] = []
    write_calls = 0

    def capture_write(uri, source, **kwargs):
        nonlocal write_calls
        write_calls += 1
        if isinstance(source, pa.RecordBatchReader):
            batches = []
            for batch in source:
                observed_batches.append((len(copied_rows), batch.num_rows))
                batches.append(batch)
            source = pa.RecordBatchReader.from_batches(source.schema, batches)
        else:
            observed_batches.append((len(copied_rows), source.num_rows))
        return original_write(uri, source, **kwargs)

    monkeypatch.setattr(delta_writer_module, "write_deltalake", capture_write)
    writer = DeltaWriter()
    writer.append_batch_size = 2
    rows = [
        CopyObservedRow(index, row)
        for index, row in enumerate(_append_rows(row_count))
    ]
    schema = pa.Table.from_pylist(_append_rows(row_count)).schema

    result = writer.write(
        tmp_path / "table",
        rows,
        mode=DeltaWriteMode.APPEND,
        schema=schema,
    )

    assert write_calls == 1
    assert [batch_size for _, batch_size in observed_batches] == expected_batch_sizes
    assert [copy_count for copy_count, _ in observed_batches] == expected_copy_counts
    assert result.rows_processed == row_count
    assert result.rows_added == row_count


def test_delta_writer_append_bounds_arrow_batches_by_payload_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rows = [
        {
            **row,
            "source_event_payload_json": "x" * 1_024,
        }
        for row in _append_rows(2)
    ]
    schema = pa.Table.from_pylist(rows).schema
    original_write = delta_writer_module.write_deltalake
    observed_batch_sizes: list[int] = []

    def capture_write(uri, source, **kwargs):
        batches = list(source)
        observed_batch_sizes.extend(batch.num_rows for batch in batches)
        replacement = pa.RecordBatchReader.from_batches(source.schema, batches)
        return original_write(uri, replacement, **kwargs)

    monkeypatch.setattr(delta_writer_module, "write_deltalake", capture_write)

    result = DeltaWriter(
        append_batch_size=10,
        append_preflight_batch_bytes=1,
    ).write(
        tmp_path / "table",
        rows,
        mode=DeltaWriteMode.APPEND,
        schema=schema,
    )

    assert observed_batch_sizes == [1, 1]
    assert result.rows_added == 2


def test_delta_writer_append_bounds_schema_inference_by_payload_bytes(
    monkeypatch,
) -> None:
    rows = [
        {
            **row,
            "optional": None if index == 0 else "later",
            "source_event_payload_json": "x" * 1_024,
        }
        for index, row in enumerate(_append_rows(2))
    ]
    payload_bytes = [
        delta_writer_module._estimate_row_payload_bytes(row)
        for row in rows
    ]
    original_table = pa.Table
    observed_batch_sizes: list[int] = []

    class TableProxy:
        @staticmethod
        def from_pylist(batch, *args, **kwargs):
            observed_batch_sizes.append(len(batch))
            return original_table.from_pylist(batch, *args, **kwargs)

    monkeypatch.setattr(delta_writer_module.pa, "Table", TableProxy)

    schema = delta_writer_module._infer_append_schema(
        rows,
        [0, 1],
        payload_bytes,
        10,
        1,
    )

    assert observed_batch_sizes == [1, 1]
    assert schema.field("optional").type == pa.string()


def test_delta_writer_append_estimates_each_unique_row_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    existing = {
        **_append_rows(1)[0],
        "source_event_payload_json": "x" * 1_024,
    }
    new = {
        **_append_rows(2)[1],
        "source_event_payload_json": "y" * 1_024,
    }
    writer = DeltaWriter(append_preflight_batch_bytes=1)
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    original_estimate = delta_writer_module._estimate_row_payload_bytes
    estimated_keys: list[str] = []

    def capture_estimate(row):
        estimated_keys.append(str(row["resource_id"]))
        return original_estimate(row)

    monkeypatch.setattr(
        delta_writer_module,
        "_estimate_row_payload_bytes",
        capture_estimate,
    )

    result = writer.write(
        table,
        [existing, new],
        mode=DeltaWriteMode.APPEND,
    )

    assert estimated_keys == ["resource-0", "resource-1"]
    assert result.rows_added == 1


def test_delta_writer_append_unifies_schema_across_bounded_batches(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    rows = [
        {**row, "optional": None if index < 2 else "later"}
        for index, row in enumerate(_append_rows(3))
    ]

    result = DeltaWriter(append_batch_size=2).write(
        table,
        rows,
        mode=DeltaWriteMode.APPEND,
    )

    assert result.rows_added == 3
    assert {
        row["resource_id"]: row["optional"]
        for row in _rows(table)
    } == {
        "resource-0": None,
        "resource-1": None,
        "resource-2": "later",
    }
    assert DeltaTable(str(table)).version() == 0


def test_delta_writer_append_empty_with_schema_creates_valid_table(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    schema = pa.Table.from_pylist(_append_rows(1)).schema

    result = DeltaWriter().write(
        table,
        [],
        mode=DeltaWriteMode.APPEND,
        schema=schema,
    )

    assert result.rows_processed == 0
    assert result.rows_added == 0
    assert result.skipped is False
    assert result.version == 0
    assert DeltaTable(str(table)).version() == 0
    assert _rows(table) == []


def test_delta_writer_append_does_not_scan_valid_empty_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    incoming = _append_rows(1)[0]
    empty = pa.Table.from_pylist([incoming]).slice(0, 0)
    delta_writer_module.write_deltalake(str(table), empty, mode="overwrite")

    def reject_full_scan(*_args, **_kwargs):
        raise AssertionError("valid empty APPEND must not scan target rows")

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", reject_full_scan)

    result = DeltaWriter().write(
        table,
        [incoming],
        mode=DeltaWriteMode.APPEND,
    )

    assert DeltaTable(str(table)).count() == 1
    assert result.rows_added == 1
    assert result.skipped is False


def test_delta_writer_append_filters_target_reads_to_incoming_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    existing = _append_rows(1)[0]
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    original_read = DeltaTable.to_pyarrow_table
    observed_filters: list[object] = []

    def capture_read(self, *args, **kwargs):
        observed_filters.append(kwargs.get("filters"))
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", capture_read)
    result = writer.write(
        table,
        [dict(existing), _append_rows(2)[1]],
        mode=DeltaWriteMode.APPEND,
    )

    assert observed_filters
    assert all(filters is not None for filters in observed_filters)
    assert DeltaTable(str(table)).count() == 2
    assert result.rows_added == 1


def test_delta_writer_append_bounds_replay_preflight_by_payload_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    payload = "x" * 1_024
    existing = [
        {
            **row,
            "source_event_payload_json": payload,
        }
        for row in _append_rows(2)
    ]
    writer = DeltaWriter(append_batch_size=10)
    writer.write(table, existing, mode=DeltaWriteMode.OVERWRITE)
    writer.append_preflight_batch_bytes = 1
    original_read = DeltaTable.to_pyarrow_table
    compared_key_counts: list[int] = []

    def capture_read(self, *args, **kwargs):
        filters = kwargs.get("filters")
        assert filters is not None
        compared_key_counts.append(len(filters[0][2]))
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", capture_read)
    replay = [
        {
            **row,
            "timestamp": "2026-09-10T00:00:00Z",
            "ingestion_run_id": "run-2",
        }
        for row in existing
    ]

    result = writer.write(
        table,
        replay,
        mode=DeltaWriteMode.APPEND,
        append_replay_columns=("timestamp",),
    )

    assert compared_key_counts == [1, 1]
    assert result.rows_added == 0
    assert result.skipped is True


@pytest.mark.parametrize(
    ("budget_adjustment", "expected_key_counts"),
    [
        (-1, [1, 1]),
        (0, [2]),
        (1, [2]),
    ],
)
def test_delta_writer_append_preflight_payload_byte_boundary(
    tmp_path: Path,
    monkeypatch,
    budget_adjustment: int,
    expected_key_counts: list[int],
) -> None:
    table = tmp_path / "table"
    existing = [
        {
            **row,
            "source_event_payload_json": "x" * 1_024,
        }
        for row in _append_rows(2)
    ]
    replay = [
        {
            **row,
            "timestamp": "2026-09-10T00:00:00Z",
            "ingestion_run_id": "run-2",
        }
        for row in existing
    ]
    exact_pair_bytes = sum(
        delta_writer_module._estimate_row_payload_bytes(row)
        for row in replay
    )
    writer = DeltaWriter(
        append_batch_size=10,
        append_preflight_batch_bytes=exact_pair_bytes + budget_adjustment,
    )
    writer.write(table, existing, mode=DeltaWriteMode.OVERWRITE)
    original_read = DeltaTable.to_pyarrow_table
    compared_key_counts: list[int] = []

    def capture_read(self, *args, **kwargs):
        filters = kwargs.get("filters")
        assert filters is not None
        compared_key_counts.append(len(filters[0][2]))
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", capture_read)

    result = writer.write(
        table,
        replay,
        mode=DeltaWriteMode.APPEND,
        append_replay_columns=("timestamp",),
    )

    assert compared_key_counts == expected_key_counts
    assert result.rows_added == 0
    assert result.skipped is True


def test_delta_writer_append_bounds_retry_preflight_by_payload_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    existing = {
        **_append_rows(1)[0],
        "source_event_payload_json": "x" * 1_024,
    }
    new = {
        **_append_rows(2)[1],
        "source_event_payload_json": "y" * 1_024,
    }
    writer = DeltaWriter(
        append_batch_size=10,
        append_preflight_batch_bytes=1,
    )
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    original_read = DeltaTable.to_pyarrow_table
    compared_key_counts: list[int] = []

    def capture_read(self, *args, **kwargs):
        filters = kwargs.get("filters")
        assert filters is not None
        compared_key_counts.append(len(filters[0][2]))
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", capture_read)

    result = writer.write(
        table,
        [existing, new],
        mode=DeltaWriteMode.APPEND,
    )

    assert compared_key_counts == [1, 1, 1]
    assert result.rows_added == 1
    assert result.skipped is False


def test_delta_writer_append_rejects_conflict_when_active_file_lacks_statistics(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    existing = _append_rows(1)[0]
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    _remove_add_action_statistics(table)
    target = DeltaTable(str(table))
    assert target.count() == 0
    assert len(target.file_uris()) == 1

    with pytest.raises(ValueError, match="Append row mutation"):
        writer.write(
            table,
            [{**existing, "name": "mutated"}],
            mode=DeltaWriteMode.APPEND,
        )

    assert _rows(table) == [existing]


def test_delta_writer_append_deduplicates_active_file_without_statistics(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    existing = _append_rows(1)[0]
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    _remove_add_action_statistics(table)
    target = DeltaTable(str(table))
    assert target.count() == 0
    assert len(target.file_uris()) == 1

    result = writer.write(
        table,
        [dict(existing)],
        mode=DeltaWriteMode.APPEND,
    )

    assert _rows(table) == [existing]
    assert result.rows_added == 0
    assert result.skipped is True


def test_delta_writer_append_refuses_conflict_before_any_chunk_is_written(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter()
    writer.append_batch_size = 1
    existing = _append_rows(1)[0]
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    conflicting = {**existing, "name": "mutated"}

    with pytest.raises(ValueError, match="Append row mutation"):
        writer.write(
            table,
            [_append_rows(2)[1], conflicting],
            mode=DeltaWriteMode.APPEND,
        )

    assert _rows(table) == [existing]


def test_delta_writer_append_retries_transient_failure_during_bounded_stream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    original_write = delta_writer_module.write_deltalake
    batch_sizes: list[int] = []
    write_attempts = 0

    def fail_after_first_batch_once(uri, source, **kwargs):
        nonlocal write_attempts
        write_attempts += 1

        def observed_batches():
            for batch in source:
                batch_sizes.append(batch.num_rows)
                yield batch
                if write_attempts == 1:
                    raise OSError("temporarily unavailable")

        replacement = pa.RecordBatchReader.from_batches(
            source.schema,
            observed_batches(),
        )
        return original_write(uri, replacement, **kwargs)

    monkeypatch.setattr(
        delta_writer_module,
        "write_deltalake",
        fail_after_first_batch_once,
    )
    delays: list[float] = []
    writer = DeltaWriter(
        max_attempts=3,
        sleep=delays.append,
        append_batch_size=2,
    )

    result = writer.write(
        table,
        _append_rows(5),
        mode=DeltaWriteMode.APPEND,
        schema=pa.Table.from_pylist(_append_rows(5)).schema,
    )

    rows = _rows(table)
    assert write_attempts == 2
    assert batch_sizes == [2, 2, 2, 1]
    assert delays == [1]
    assert len(rows) == 5
    assert len({row["resource_id"] for row in rows}) == 5
    assert result.rows_processed == 5
    assert result.rows_added == 5
    assert result.skipped is False


@pytest.mark.parametrize("target_exists", [False, True])
def test_delta_writer_append_is_atomic_when_later_batch_materialization_fails(
    tmp_path: Path,
    target_exists: bool,
) -> None:
    table = tmp_path / "table"
    writer = DeltaWriter(append_batch_size=2)
    existing = _append_rows(1)[0]
    incoming = _append_rows(4)[1:]
    schema = pa.Table.from_pylist([existing, *incoming]).schema
    if target_exists:
        writer.write(
            table,
            [existing],
            mode=DeltaWriteMode.OVERWRITE,
            schema=schema,
        )
    before_version = (
        DeltaTable(str(table)).version()
        if target_exists
        else None
    )

    class CopyFailureRow(Mapping[str, Any]):
        def __init__(self, payload: Mapping[str, Any]) -> None:
            self.payload = payload

        def __getitem__(self, key: str) -> Any:
            return self.payload[key]

        def __iter__(self) -> Iterator[str]:
            return iter(self.payload)

        def __len__(self) -> int:
            return len(self.payload)

        def keys(self):
            raise RuntimeError("injected later batch materialization failure")

    with pytest.raises(
        (RuntimeError, DeltaError),
        match="injected later batch materialization failure",
    ):
        writer.write(
            table,
            [incoming[0], incoming[1], CopyFailureRow(incoming[2])],
            mode=DeltaWriteMode.APPEND,
            schema=schema,
        )

    if target_exists:
        assert DeltaTable(str(table)).version() == before_version
        assert _rows(table) == [existing]
    else:
        assert DeltaTable.is_deltatable(str(table)) is False


def test_delta_writer_append_reports_commit_that_raised_transient_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    original_write = delta_writer_module.write_deltalake
    write_calls = 0

    def commit_then_raise(uri, source, **kwargs):
        nonlocal write_calls
        write_calls += 1
        original_write(uri, source, **kwargs)
        if write_calls == 1:
            raise OSError("transient response lost after commit")

    monkeypatch.setattr(delta_writer_module, "write_deltalake", commit_then_raise)
    delays: list[float] = []
    result = DeltaWriter(max_attempts=3, sleep=delays.append).write(
        table,
        _append_rows(1),
        mode=DeltaWriteMode.APPEND,
    )

    assert write_calls == 1
    assert delays == [1]
    assert _rows(table) == _append_rows(1)
    assert result.rows_processed == 1
    assert result.rows_added == 1
    assert result.skipped is False
    assert result.version == 0


def test_delta_writer_append_retries_transient_preflight_existence_lookup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0
    delays: list[float] = []
    writer = DeltaWriter(max_attempts=3, sleep=delays.append)
    original_exists = writer.exists

    def fail_once(table_uri: str | Path) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("temporarily unavailable")
        return original_exists(table_uri)

    monkeypatch.setattr(writer, "exists", fail_once)

    result = writer.write(
        tmp_path / "table",
        _append_rows(1),
        mode=DeltaWriteMode.APPEND,
    )

    assert calls >= 2
    assert delays == [1]
    assert result.rows_added == 1


def test_delta_writer_append_retries_transient_preflight_filtered_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    table = tmp_path / "table"
    existing = _append_rows(1)[0]
    writer = DeltaWriter(max_attempts=3, sleep=lambda _delay: None)
    writer.write(table, [existing], mode=DeltaWriteMode.OVERWRITE)
    original_read = DeltaTable.to_pyarrow_table
    filtered_attempts = 0
    delays: list[float] = []
    writer.sleep = delays.append

    def fail_once(self, *args, **kwargs):
        nonlocal filtered_attempts
        if kwargs.get("filters") is not None:
            filtered_attempts += 1
            if filtered_attempts == 1:
                raise OSError("temporarily unavailable")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(DeltaTable, "to_pyarrow_table", fail_once)

    result = writer.write(
        table,
        [_append_rows(2)[1]],
        mode=DeltaWriteMode.APPEND,
    )

    assert filtered_attempts >= 2
    assert delays == [1]
    assert result.rows_added == 1
    assert len(_rows(table)) == 2


def test_delta_writer_append_fails_closed_for_malformed_delta_log(
    tmp_path: Path,
) -> None:
    table = tmp_path / "table"
    log = table / "_delta_log"
    log.mkdir(parents=True)
    (log / "00000000000000000000.json").write_text("")

    with pytest.raises(DeltaError, match="metadata or protocol"):
        DeltaWriter().write(
            table,
            _append_rows(1),
            mode=DeltaWriteMode.APPEND,
        )

    assert not list(table.glob("*.parquet"))


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


def test_delta_writer_retries_temporarily_missing_delta_log() -> None:
    error = RuntimeError(
        "Kernel error: File not found: Tables/metadata_ingestion_state/"
        "_delta_log/00000000000000000130.json"
    )

    assert _is_transient(error)


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
