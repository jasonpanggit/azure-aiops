from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake


class DeltaWriteMode(StrEnum):
    OVERWRITE = "overwrite"
    APPEND = "append"
    MERGE = "merge"
    # Upsert matched keys and delete target rows absent from this run's
    # source, i.e. a full-snapshot semantics like OVERWRITE but expressed as
    # a merge so unchanged rows are never rewritten. Use for full-state
    # tables (e.g. current resource/VM/server inventory) where OVERWRITE was
    # previously used only because plain MERGE cannot express deletions.
    SNAPSHOT_MERGE = "snapshot_merge"


@dataclass(frozen=True)
class DeltaWriteResult:
    rows_processed: int
    rows_added: int = 0
    rows_changed: int = 0
    rows_removed: int = 0
    skipped: bool = False
    version: int | None = None


class DeltaWriter:
    REQUIRED_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
    })

    def __init__(
        self,
        *,
        storage_options: Mapping[str, str] | None = None,
        storage_options_provider: Callable[[], Mapping[str, str]] | None = None,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.storage_options = dict(storage_options or {})
        self.storage_options_provider = storage_options_provider
        self.max_attempts = max_attempts
        self.sleep = sleep

    def write(
        self,
        table_uri: str | Path,
        rows: Sequence[Mapping[str, Any]],
        *,
        mode: DeltaWriteMode | str,
        key_columns: tuple[str, ...] = ("resource_id",),
        partition_by: tuple[str, ...] = (),
        schema: pa.Schema | None = None,
        required_columns: frozenset[str] | tuple[str, ...] | None = REQUIRED_COLUMNS,
    ) -> DeltaWriteResult:
        normalized = [dict(row) for row in rows]
        if not normalized and schema is None:
            return DeltaWriteResult(rows_processed=0, skipped=True)
        if normalized and required_columns:
            self._validate_columns(normalized, frozenset(required_columns))
        self._refresh_storage_options()
        write_mode = DeltaWriteMode(mode)
        uri = str(table_uri)
        return self._retry(
            lambda: self._write_once(
                uri,
                normalized,
                mode=write_mode,
                key_columns=key_columns,
                partition_by=partition_by,
                schema=schema,
            )
        )

    def read(self, table_uri: str | Path) -> list[dict[str, Any]]:
        self._refresh_storage_options()
        if not self.exists(table_uri):
            return []
        uri = str(table_uri)
        table = DeltaTable(uri, storage_options=self.storage_options)
        if urlparse(uri).scheme in {"", "file"}:
            actions = pa.table(table.get_add_actions(flatten=True))
            files = [str(Path(uri) / path) for path in actions.column("path").to_pylist()]
            return pq.read_table(files).to_pylist() if files else []
        return table.to_pyarrow_table().to_pylist()

    def exists(self, table_uri: str | Path) -> bool:
        return DeltaTable.is_deltatable(str(table_uri), storage_options=self.storage_options)

    def version(self, table_uri: str | Path) -> int | None:
        self._refresh_storage_options()
        if not self.exists(table_uri):
            return None
        return DeltaTable(str(table_uri), storage_options=self.storage_options).version()

    def restore(self, table_uri: str | Path, version: int) -> None:
        self._refresh_storage_options()
        DeltaTable(str(table_uri), storage_options=self.storage_options).restore(version)

    def _write_once(
        self,
        uri: str,
        rows: list[dict[str, Any]],
        *,
        mode: DeltaWriteMode,
        key_columns: tuple[str, ...],
        partition_by: tuple[str, ...],
        schema: pa.Schema | None,
    ) -> DeltaWriteResult:
        processed_count = len(rows)
        exists = self.exists(uri)
        supports_version_compare = bool(rows) and {"resource_id", "change_version"} <= set(rows[0])
        if mode is DeltaWriteMode.OVERWRITE and exists and supports_version_compare:
            table = DeltaTable(uri, storage_options=self.storage_options)
            current = table.to_pyarrow_table(columns=["resource_id", "change_version"])
            current_versions = sorted(
                zip(
                    current.column("resource_id").to_pylist(),
                    current.column("change_version").to_pylist(),
                    strict=True,
                )
            )
            incoming_versions = sorted(
                (str(row["resource_id"]), str(row["change_version"])) for row in rows
            )
            if current_versions == incoming_versions:
                return DeltaWriteResult(
                    rows_processed=processed_count,
                    skipped=True,
                    version=table.version(),
                )
        if mode is DeltaWriteMode.APPEND and exists:
            table = DeltaTable(uri, storage_options=self.storage_options)
            existing_rows = table.to_pyarrow_table().to_pylist()
            existing_by_key = {_row_key(row, key_columns): row for row in existing_rows}
            incoming_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
            for row in rows:
                key = _row_key(row, key_columns)
                previous = incoming_by_key.get(key)
                if previous is not None and _canonical_row(previous) != _canonical_row(row):
                    raise ValueError(f"Append row mutation for key {key}")
                incoming_by_key[key] = row
            rows = []
            for key, row in incoming_by_key.items():
                previous = existing_by_key.get(key)
                if previous is not None:
                    if _canonical_row(previous) != _canonical_row(row):
                        raise ValueError(f"Append row mutation for key {key}")
                    continue
                rows.append(row)
        if mode is DeltaWriteMode.APPEND:
            unique_rows: dict[tuple[str, ...], dict[str, Any]] = {}
            for row in rows:
                key = _row_key(row, key_columns)
                previous = unique_rows.get(key)
                if previous is not None and _canonical_row(previous) != _canonical_row(row):
                    raise ValueError(f"Append row mutation for key {key}")
                unique_rows[key] = row
            rows = list(unique_rows.values())
        if mode is DeltaWriteMode.APPEND and exists and not rows:
            return DeltaWriteResult(
                rows_processed=processed_count,
                skipped=True,
                version=table.version(),
            )
        source = pa.Table.from_pylist(rows, schema=schema)
        if mode in (DeltaWriteMode.MERGE, DeltaWriteMode.SNAPSHOT_MERGE) and exists:
            if not key_columns:
                raise ValueError("merge mode requires key_columns")
            predicate = " AND ".join(
                f"target.{column} = source.{column}" for column in key_columns
            )
            table = DeltaTable(uri, storage_options=self.storage_options)
            builder = (
                table.merge(
                    source,
                    predicate=predicate,
                    source_alias="source",
                    target_alias="target",
                    merge_schema=True,
                )
                .when_matched_update_all(
                    predicate="target.change_version <> source.change_version"
                )
                .when_not_matched_insert_all()
            )
            if mode is DeltaWriteMode.SNAPSHOT_MERGE:
                # Unlike plain MERGE (append-only history), a snapshot table
                # must not accumulate rows for resources no longer present in
                # this run's source -- delete anything the target has that
                # this write didn't touch, matching OVERWRITE's full-replace
                # semantics without rewriting rows that did not change.
                builder = builder.when_not_matched_by_source_delete()
            metrics = builder.execute()
            added = int(metrics.get("num_target_rows_inserted", 0))
            changed = int(metrics.get("num_target_rows_updated", 0))
            removed = int(metrics.get("num_target_rows_deleted", 0))
            table.update_incremental()
            return DeltaWriteResult(
                rows_processed=len(rows),
                rows_added=added,
                rows_changed=changed,
                rows_removed=removed,
                version=table.version(),
            )

        actual_mode = (
            "overwrite"
            if mode in {DeltaWriteMode.OVERWRITE, DeltaWriteMode.MERGE, DeltaWriteMode.SNAPSHOT_MERGE}
            else "append"
        )
        previous_count = 0
        if exists and actual_mode == "overwrite":
            previous_count = DeltaTable(uri, storage_options=self.storage_options).count()
        write_deltalake(
            uri,
            source,
            mode=actual_mode,
            partition_by=list(partition_by) or None,
            schema_mode="merge",
            storage_options=self.storage_options,
        )
        table = DeltaTable(uri, storage_options=self.storage_options)
        return DeltaWriteResult(
            rows_processed=processed_count,
            rows_added=len(rows),
            rows_removed=previous_count,
            version=table.version(),
        )

    def _validate_columns(self, rows: list[dict[str, Any]], required_columns: frozenset[str]) -> None:
        missing = sorted(required_columns - set(rows[0]))
        if missing:
            raise ValueError("Delta row is missing required columns: " + ", ".join(missing))
        for index, row in enumerate(rows[1:], start=1):
            row_missing = sorted(required_columns - set(row))
            if row_missing:
                raise ValueError(
                    f"Delta row {index} is missing required columns: " + ", ".join(row_missing)
                )

    def _retry(self, operation: Callable[[], DeltaWriteResult]) -> DeltaWriteResult:
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                if attempt == self.max_attempts or not _is_transient(exc):
                    raise
                self.sleep(min(2 ** (attempt - 1), 15))
        raise AssertionError("unreachable")

    def _refresh_storage_options(self) -> None:
        if self.storage_options_provider is not None:
            self.storage_options = dict(self.storage_options_provider())


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("429", "500", "502", "503", "504", "timeout", "temporarily", "conflict")
    )


def _row_key(row: Mapping[str, Any], key_columns: tuple[str, ...]) -> tuple[str, ...]:
    if not key_columns:
        raise ValueError("append mode requires key_columns")
    missing = [column for column in key_columns if column not in row]
    if missing:
        raise ValueError("Append row is missing key columns: " + ", ".join(missing))
    return tuple(str(row[column]) for column in key_columns)


def _canonical_row(row: Mapping[str, Any]) -> str:
    # The physical ingestion run is write metadata, not event content. A
    # replay of the same stable event must remain idempotent across runs.
    return json.dumps(
        {key: value for key, value in row.items() if key != "ingestion_run_id"},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
