from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import CommitProperties, DeltaTable, write_deltalake

_T = TypeVar("_T")
_APPEND_INVOCATION_ID = "delta_writer_append_invocation_id"
_APPEND_ROWS_ADDED = "delta_writer_append_rows_added"
_APPEND_HISTORY_LIMIT = 32


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
    APPEND_BATCH_SIZE: ClassVar[int] = 10_000
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
        append_batch_size: int = APPEND_BATCH_SIZE,
    ) -> None:
        self.storage_options = dict(storage_options or {})
        self.storage_options_provider = storage_options_provider
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.append_batch_size = append_batch_size

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
        append_replay_columns: Collection[str] = (),
        append_replay_json_fields: Mapping[str, Collection[str]] | None = None,
    ) -> DeltaWriteResult:
        write_mode = DeltaWriteMode(mode)
        if write_mode is DeltaWriteMode.APPEND:
            if not rows and schema is None:
                return DeltaWriteResult(rows_processed=0, skipped=True)
            if rows and required_columns:
                self._validate_columns(rows, frozenset(required_columns))
            self._refresh_storage_options()
            return self._write_append(
                str(table_uri),
                rows,
                key_columns=key_columns,
                partition_by=partition_by,
                schema=schema,
                replay_columns=frozenset(append_replay_columns),
                replay_json_fields={
                    column: frozenset(fields)
                    for column, fields in (
                        append_replay_json_fields or {}
                    ).items()
                },
            )

        normalized = [dict(row) for row in rows]
        if not normalized and schema is None:
            return DeltaWriteResult(rows_processed=0, skipped=True)
        if normalized and required_columns:
            self._validate_columns(normalized, frozenset(required_columns))
        self._refresh_storage_options()
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

    def _write_append(
        self,
        uri: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        key_columns: tuple[str, ...],
        partition_by: tuple[str, ...],
        schema: pa.Schema | None,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
    ) -> DeltaWriteResult:
        batch_size = self.append_batch_size
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("append_batch_size must be a positive integer")

        incoming_indices: dict[tuple[str, ...], int] = {}
        for index, row in enumerate(rows):
            key = _row_key(row, key_columns)
            previous_index = incoming_indices.get(key)
            if (
                previous_index is not None
                and _canonical_row(
                    rows[previous_index],
                    replay_columns=replay_columns,
                    replay_json_fields=replay_json_fields,
                )
                != _canonical_row(
                    row,
                    replay_columns=replay_columns,
                    replay_json_fields=replay_json_fields,
                )
            ):
                raise ValueError(f"Append row mutation for key {key}")
            # Preserve the previous implementation's last-row-wins behavior
            # for physically duplicated but canonically identical events.
            incoming_indices[key] = index

        unique_indices = tuple(incoming_indices.values())
        del incoming_indices
        version, pending_indices = self._retry(
            lambda: self._append_preflight_once(
                uri,
                rows,
                incoming_indices=unique_indices,
                key_columns=key_columns,
                batch_size=batch_size,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            )
        )

        if unique_indices and not pending_indices:
            return DeltaWriteResult(
                rows_processed=len(rows),
                skipped=True,
                version=version,
            )

        invocation_id = uuid.uuid4().hex
        attempt = 0

        def append_once() -> DeltaWriteResult:
            nonlocal attempt
            attempt += 1
            return self._write_append_once(
                uri,
                rows,
                incoming_indices=pending_indices,
                key_columns=key_columns,
                partition_by=partition_by,
                schema=schema,
                batch_size=batch_size,
                invocation_id=invocation_id,
                recover_committed=attempt > 1,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            )

        result = self._retry(append_once)
        return DeltaWriteResult(
            rows_processed=len(rows),
            rows_added=result.rows_added,
            skipped=result.skipped,
            version=result.version,
        )

    def _append_preflight_once(
        self,
        uri: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        incoming_indices: Sequence[int],
        key_columns: tuple[str, ...],
        batch_size: int,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
    ) -> tuple[int | None, list[int]]:
        if not self.exists(uri):
            return None, list(incoming_indices)
        table = DeltaTable(uri, storage_options=self.storage_options)
        pending_indices: list[int] = []
        if incoming_indices and _has_active_files(table):
            # Validate every immutable conflict before the first chunk is
            # committed. Only rows matching this bounded incoming-key batch
            # are materialized from the target.
            for indices in _batched_indices(incoming_indices, batch_size):
                incoming = [rows[index] for index in indices]
                existing_keys = self._validate_append_target(
                    table,
                    incoming,
                    key_columns,
                    replay_columns=replay_columns,
                    replay_json_fields=replay_json_fields,
                )
                pending_indices.extend(
                    index
                    for index in indices
                    if _row_key(rows[index], key_columns) not in existing_keys
                )
        else:
            pending_indices.extend(incoming_indices)
        return table.version(), pending_indices

    def _write_append_once(
        self,
        uri: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        incoming_indices: Sequence[int],
        key_columns: tuple[str, ...],
        partition_by: tuple[str, ...],
        schema: pa.Schema | None,
        batch_size: int,
        invocation_id: str,
        recover_committed: bool,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
    ) -> DeltaWriteResult:
        if recover_committed:
            committed = self._committed_append_result(uri, invocation_id)
            if committed is not None:
                return committed

        exists = self.exists(uri)
        table = (
            DeltaTable(uri, storage_options=self.storage_options)
            if exists
            else None
        )
        pending_indices = list(incoming_indices)
        if table is not None:
            if not incoming_indices:
                return DeltaWriteResult(
                    rows_processed=0,
                    skipped=True,
                    version=table.version(),
                )
            if _has_active_files(table):
                pending_indices = []
                for indices in _batched_indices(incoming_indices, batch_size):
                    incoming = [rows[index] for index in indices]
                    existing_keys = self._validate_append_target(
                        table,
                        incoming,
                        key_columns,
                        replay_columns=replay_columns,
                        replay_json_fields=replay_json_fields,
                    )
                    pending_indices.extend(
                        index
                        for index in indices
                        if _row_key(rows[index], key_columns) not in existing_keys
                    )
            if not pending_indices:
                return DeltaWriteResult(
                    rows_processed=len(incoming_indices),
                    skipped=True,
                    version=table.version(),
                )

        source_schema = schema or _infer_append_schema(
            rows,
            pending_indices,
            batch_size,
        )
        source = pa.RecordBatchReader.from_batches(
            source_schema,
            _append_record_batches(
                rows,
                pending_indices,
                batch_size,
                source_schema,
            ),
        )
        rows_added = len(pending_indices)
        write_deltalake(
            uri,
            source,
            mode="append",
            partition_by=list(partition_by) or None,
            schema_mode="merge",
            storage_options=self.storage_options,
            commit_properties=CommitProperties(
                custom_metadata={
                    _APPEND_INVOCATION_ID: invocation_id,
                    _APPEND_ROWS_ADDED: str(rows_added),
                }
            ),
        )
        table = DeltaTable(uri, storage_options=self.storage_options)
        return DeltaWriteResult(
            rows_processed=len(incoming_indices),
            rows_added=rows_added,
            version=table.version(),
        )

    def _committed_append_result(
        self,
        uri: str,
        invocation_id: str,
    ) -> DeltaWriteResult | None:
        if not self.exists(uri):
            return None
        table = DeltaTable(uri, storage_options=self.storage_options)
        for commit in table.history(limit=_APPEND_HISTORY_LIMIT):
            if commit.get(_APPEND_INVOCATION_ID) != invocation_id:
                continue
            rows_added = int(commit[_APPEND_ROWS_ADDED])
            version = int(commit["version"])
            if rows_added < 0 or version < 0:
                raise RuntimeError("Invalid Delta APPEND commit metadata")
            return DeltaWriteResult(
                rows_processed=rows_added,
                rows_added=rows_added,
                skipped=False,
                version=version,
            )
        return None

    def _validate_append_target(
        self,
        table: DeltaTable,
        incoming_rows: Sequence[Mapping[str, Any]],
        key_columns: tuple[str, ...],
        *,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
    ) -> set[tuple[str, ...]]:
        incoming_by_key = {
            _row_key(row, key_columns): row
            for row in incoming_rows
        }
        filters: Any
        if len(key_columns) == 1:
            column = key_columns[0]
            filters = [
                (
                    column,
                    "in",
                    [row[column] for row in incoming_rows],
                )
            ]
        else:
            filters = [
                [
                    (column, "=", row[column])
                    for column in key_columns
                ]
                for row in incoming_rows
            ]
        existing_rows = table.to_pyarrow_table(filters=filters).to_pylist()
        existing_keys: set[tuple[str, ...]] = set()
        for existing in existing_rows:
            key = _row_key(existing, key_columns)
            incoming = incoming_by_key.get(key)
            if incoming is None:
                continue
            if _canonical_row(
                existing,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            ) != _canonical_row(
                incoming,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            ):
                raise ValueError(f"Append row mutation for key {key}")
            existing_keys.add(key)
        return existing_keys

    def read(
        self,
        table_uri: str | Path,
        *,
        version: int | None = None,
    ) -> list[dict[str, Any]]:
        if (
            version is not None
            and (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version < 0
            )
        ):
            raise ValueError("Delta read version must be a non-negative integer")
        self._refresh_storage_options()
        if not self.exists(table_uri):
            if version is not None:
                raise ValueError(
                    "Version-qualified Delta table does not exist"
                )
            return []
        uri = str(table_uri)
        table = DeltaTable(
            uri,
            version=version,
            storage_options=self.storage_options,
        )
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
        if mode is DeltaWriteMode.APPEND:
            raise AssertionError("APPEND must use the bounded append path")
        processed_count = len(rows)
        exists = self.exists(uri)
        supports_version_compare = bool(rows) and {"resource_id", "change_version"} <= set(rows[0])
        if mode is DeltaWriteMode.OVERWRITE and exists and supports_version_compare:
            table = DeltaTable(uri, storage_options=self.storage_options)
            # A synchronous scan prevents Arrow workers from outliving short-lived
            # publication processes during interpreter shutdown.
            current = table.to_pyarrow_dataset().to_table(
                columns=["resource_id", "change_version"],
                use_threads=False,
            )
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

        previous_count = 0
        if exists:
            previous_count = DeltaTable(uri, storage_options=self.storage_options).count()
        write_deltalake(
            uri,
            source,
            mode="overwrite",
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

    def _validate_columns(
        self,
        rows: Sequence[Mapping[str, Any]],
        required_columns: frozenset[str],
    ) -> None:
        missing = sorted(required_columns - set(rows[0]))
        if missing:
            raise ValueError("Delta row is missing required columns: " + ", ".join(missing))
        for index in range(1, len(rows)):
            row = rows[index]
            row_missing = sorted(required_columns - set(row))
            if row_missing:
                raise ValueError(
                    f"Delta row {index} is missing required columns: " + ", ".join(row_missing)
                )

    def _retry(self, operation: Callable[[], _T]) -> _T:
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
    if "delta_log" in text and "file not found" in text:
        return True
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


def _canonical_row(
    row: Mapping[str, Any],
    *,
    replay_columns: Collection[str] = (),
    replay_json_fields: Mapping[str, Collection[str]] | None = None,
) -> str:
    # The physical ingestion run is write metadata, not event content. A
    # replay of the same stable event must remain idempotent across runs.
    excluded_columns = {"ingestion_run_id", *replay_columns}
    content = {
        key: value
        for key, value in row.items()
        if key not in excluded_columns
    }
    for column, excluded_fields in (replay_json_fields or {}).items():
        value = content.get(column)
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, Mapping):
            continue
        content[column] = {
            key: item
            for key, item in parsed.items()
            if key not in excluded_fields
        }
    return json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _has_active_files(table: DeltaTable) -> bool:
    return bool(table.file_uris())


def _batched_indices(indices: Iterable[int], size: int) -> Iterator[list[int]]:
    iterator = iter(indices)
    while batch := list(islice(iterator, size)):
        yield batch


def _infer_append_schema(
    rows: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
    batch_size: int,
) -> pa.Schema:
    inferred: pa.Schema | None = None
    for batch in _batched_indices(indices, batch_size):
        batch_schema = pa.Table.from_pylist(
            [dict(rows[index]) for index in batch]
        ).schema
        inferred = (
            batch_schema
            if inferred is None
            else pa.unify_schemas(
                [inferred, batch_schema],
                promote_options="permissive",
            )
        )
    if inferred is None:
        raise ValueError("Cannot infer an APPEND schema without rows")
    return inferred


def _append_record_batches(
    rows: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
    batch_size: int,
    schema: pa.Schema,
) -> Iterator[pa.RecordBatch]:
    emitted = False
    for batch in _batched_indices(indices, batch_size):
        emitted = True
        yield pa.RecordBatch.from_pylist(
            [dict(rows[index]) for index in batch],
            schema=schema,
        )
    if not emitted:
        yield pa.RecordBatch.from_pylist([], schema=schema)
