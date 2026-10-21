from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from urllib.parse import unquote, urlparse

import pyarrow as pa
import pyarrow.parquet as pq
from deltalake import CommitProperties, DeltaTable, write_deltalake

_T = TypeVar("_T")
_APPEND_INVOCATION_ID = "delta_writer_append_invocation_id"
_APPEND_ROWS_ADDED = "delta_writer_append_rows_added"
_APPEND_HISTORY_LIMIT = 32
_PUBLICATION_INTENT_ID = "fabric_publication_intent_id"
_PUBLICATION_OUTCOME_DIGEST = "fabric_publication_outcome_digest"
_PUBLICATION_ROWS_PROCESSED = "fabric_publication_rows_processed"
_PUBLICATION_HISTORY_LIMIT = 128
_TIMESTAMP_HISTORY_LIMIT = 1_000
_NO_EXPECTED_VERSION = object()


class DeltaVersionConflictError(RuntimeError):
    """Raised when a fenced publication no longer owns the planned Delta head."""


class DeltaHistoryTruncatedError(RuntimeError):
    """Raised when bounded Delta history cannot prove an intent's outcome."""


def _publication_commit_metadata(
    transaction_id: str,
    transaction_digest: str,
    *,
    rows_processed: int,
) -> dict[str, str]:
    if bool(transaction_id) != bool(transaction_digest):
        raise ValueError(
            "transaction_id and transaction_digest must be supplied together"
        )
    if not transaction_id:
        return {}
    for field, value in (
        ("transaction_id", transaction_id),
        ("transaction_digest", transaction_digest),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"{field} must be a SHA-256 digest")
    if rows_processed < 0:
        raise ValueError("rows_processed must be non-negative")
    return {
        _PUBLICATION_INTENT_ID: transaction_id,
        _PUBLICATION_OUTCOME_DIGEST: transaction_digest,
        _PUBLICATION_ROWS_PROCESSED: str(rows_processed),
    }


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
    APPEND_BATCH_SIZE: ClassVar[int] = 1_000
    APPEND_TARGET_STREAMING_THRESHOLD: ClassVar[int] = 10_000
    APPEND_TARGET_SCAN_BATCH_SIZE: ClassVar[int] = 1_000
    # Bounds payload-proportional materialization in both conflict preflight
    # and Arrow record-batch construction. Actual peak memory is higher than
    # this estimate because Arrow and Python representations coexist briefly.
    APPEND_PREFLIGHT_BATCH_BYTES: ClassVar[int] = 4 * 1024 * 1024
    REQUIRED_COLUMNS: ClassVar[frozenset[str]] = frozenset(
        {
            "tenant_id",
            "subscription_id",
            "resource_id",
            "timestamp",
            "change_version",
            "ingestion_run_id",
        }
    )

    def __init__(
        self,
        *,
        storage_options: Mapping[str, str] | None = None,
        storage_options_provider: Callable[[], Mapping[str, str]] | None = None,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        append_batch_size: int = APPEND_BATCH_SIZE,
        append_preflight_batch_bytes: int = APPEND_PREFLIGHT_BATCH_BYTES,
    ) -> None:
        self.storage_options = dict(storage_options or {})
        self.storage_options_provider = storage_options_provider
        self.max_attempts = max_attempts
        self.sleep = sleep
        self.append_batch_size = append_batch_size
        self.append_preflight_batch_bytes = append_preflight_batch_bytes

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
        append_scan_partition_columns: Collection[str] = (),
        transaction_id: str = "",
        transaction_digest: str = "",
        expected_version: int | None | object = _NO_EXPECTED_VERSION,
    ) -> DeltaWriteResult:
        """Write rows with optional durable publication transaction evidence."""

        _validate_expected_version(expected_version)
        commit_metadata = _publication_commit_metadata(
            transaction_id,
            transaction_digest,
            rows_processed=len(rows),
        )
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
                    for column, fields in (append_replay_json_fields or {}).items()
                },
                scan_partition_columns=tuple(append_scan_partition_columns),
                transaction_id=transaction_id,
                transaction_digest=transaction_digest,
                publication_expected_version=expected_version,
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
                commit_metadata=commit_metadata,
                expected_version=expected_version,
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
        scan_partition_columns: tuple[str, ...],
        transaction_id: str,
        transaction_digest: str,
        publication_expected_version: int | None | object,
    ) -> DeltaWriteResult:
        batch_size = self.append_batch_size
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size < 1
        ):
            raise ValueError("append_batch_size must be a positive integer")
        preflight_batch_bytes = self.append_preflight_batch_bytes
        if (
            isinstance(preflight_batch_bytes, bool)
            or not isinstance(preflight_batch_bytes, int)
            or preflight_batch_bytes < 1
        ):
            raise ValueError("append_preflight_batch_bytes must be a positive integer")

        incoming_indices: dict[tuple[str, ...], int] = {}
        for index, row in enumerate(rows):
            key = _row_key(row, key_columns)
            previous_index = incoming_indices.get(key)
            if previous_index is not None and _canonical_row(
                rows[previous_index],
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            ) != _canonical_row(
                row,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
            ):
                raise ValueError(f"Append row mutation for key {key}")
            # Preserve the previous implementation's last-row-wins behavior
            # for physically duplicated but canonically identical events.
            incoming_indices[key] = index

        unique_indices = tuple(incoming_indices.values())
        del incoming_indices
        payload_bytes = [0] * len(rows)
        for index in unique_indices:
            payload_bytes[index] = _estimate_row_payload_bytes(rows[index])
        scan_partition_values = {
            column: frozenset(str(row.get(column) or "") for row in rows)
            for column in scan_partition_columns
        }
        if rows and any(
            not values or "" in values for values in scan_partition_values.values()
        ):
            raise ValueError("APPEND scan partition columns require non-empty values")
        version, pending_indices = self._retry(
            lambda: self._append_preflight_once(
                uri,
                rows,
                incoming_indices=unique_indices,
                payload_bytes=payload_bytes,
                key_columns=key_columns,
                batch_size=batch_size,
                batch_bytes=preflight_batch_bytes,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
                scan_partition_values=scan_partition_values,
            )
        )
        if (
            publication_expected_version is not _NO_EXPECTED_VERSION
            and version != publication_expected_version
        ):
            raise DeltaVersionConflictError(
                "Delta table changed after publication planning"
            )

        if unique_indices and not pending_indices:
            return DeltaWriteResult(
                rows_processed=len(rows),
                skipped=True,
                version=version,
            )

        invocation_id = transaction_id or uuid.uuid4().hex
        attempt = 0

        def append_once() -> DeltaWriteResult:
            nonlocal attempt
            attempt += 1
            return self._write_append_once(
                uri,
                rows,
                incoming_indices=pending_indices,
                payload_bytes=payload_bytes,
                key_columns=key_columns,
                partition_by=partition_by,
                schema=schema,
                batch_size=batch_size,
                preflight_batch_bytes=preflight_batch_bytes,
                invocation_id=invocation_id,
                recover_committed=attempt > 1,
                expected_version=version,
                replay_columns=replay_columns,
                replay_json_fields=replay_json_fields,
                scan_partition_values=scan_partition_values,
                transaction_digest=transaction_digest,
                publication_expected_version=publication_expected_version,
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
        payload_bytes: Sequence[int],
        key_columns: tuple[str, ...],
        batch_size: int,
        batch_bytes: int,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
        scan_partition_values: Mapping[str, frozenset[str]],
    ) -> tuple[int | None, list[int]]:
        if not self.exists(uri):
            return None, list(incoming_indices)
        table = DeltaTable(uri, storage_options=self.storage_options)
        pending_indices: list[int] = []
        if incoming_indices and _has_active_files(table):
            # Validate every immutable conflict before the first chunk is
            # committed. Only rows matching this bounded incoming-key batch
            # are materialized from the target.
            if len(incoming_indices) > self.APPEND_TARGET_STREAMING_THRESHOLD:
                incoming = [rows[index] for index in incoming_indices]
                existing_keys = self._validate_append_target_streaming(
                    table,
                    incoming,
                    key_columns,
                    batch_size=self.APPEND_TARGET_SCAN_BATCH_SIZE,
                    batch_bytes=batch_bytes,
                    replay_columns=replay_columns,
                    replay_json_fields=replay_json_fields,
                    scan_partition_values=scan_partition_values,
                )
                pending_indices.extend(
                    index
                    for index in incoming_indices
                    if _row_key(rows[index], key_columns) not in existing_keys
                )
            else:
                for indices in _batched_payload_indices(
                    incoming_indices,
                    payload_bytes,
                    max_rows=batch_size,
                    max_bytes=batch_bytes,
                ):
                    incoming = [rows[index] for index in indices]
                    existing_keys = self._validate_append_target(
                        table,
                        incoming,
                        key_columns,
                        replay_columns=replay_columns,
                        replay_json_fields=replay_json_fields,
                        scan_partition_values=scan_partition_values,
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
        payload_bytes: Sequence[int],
        key_columns: tuple[str, ...],
        partition_by: tuple[str, ...],
        schema: pa.Schema | None,
        batch_size: int,
        preflight_batch_bytes: int,
        invocation_id: str,
        recover_committed: bool,
        expected_version: int | None,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
        scan_partition_values: Mapping[str, frozenset[str]],
        transaction_digest: str,
        publication_expected_version: int | None | object,
    ) -> DeltaWriteResult:
        if recover_committed:
            committed = self._committed_append_result(uri, invocation_id)
            if committed is not None:
                return committed

        exists = self.exists(uri)
        table = (
            DeltaTable(uri, storage_options=self.storage_options) if exists else None
        )
        if publication_expected_version is not _NO_EXPECTED_VERSION:
            current_version = table.version() if table is not None else None
            if current_version != publication_expected_version:
                raise DeltaVersionConflictError(
                    "Delta table changed after publication planning"
                )
        pending_indices = list(incoming_indices)
        if table is not None:
            if not incoming_indices:
                return DeltaWriteResult(
                    rows_processed=0,
                    skipped=True,
                    version=table.version(),
                )
            if table.version() != expected_version and _has_active_files(table):
                pending_indices = []
                if len(incoming_indices) > self.APPEND_TARGET_STREAMING_THRESHOLD:
                    incoming = [rows[index] for index in incoming_indices]
                    existing_keys = self._validate_append_target_streaming(
                        table,
                        incoming,
                        key_columns,
                        batch_size=self.APPEND_TARGET_SCAN_BATCH_SIZE,
                        batch_bytes=preflight_batch_bytes,
                        replay_columns=replay_columns,
                        replay_json_fields=replay_json_fields,
                        scan_partition_values=scan_partition_values,
                    )
                    pending_indices.extend(
                        index
                        for index in incoming_indices
                        if _row_key(rows[index], key_columns) not in existing_keys
                    )
                else:
                    for indices in _batched_payload_indices(
                        incoming_indices,
                        payload_bytes,
                        max_rows=batch_size,
                        max_bytes=preflight_batch_bytes,
                    ):
                        incoming = [rows[index] for index in indices]
                        existing_keys = self._validate_append_target(
                            table,
                            incoming,
                            key_columns,
                            replay_columns=replay_columns,
                            replay_json_fields=replay_json_fields,
                            scan_partition_values=scan_partition_values,
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
            payload_bytes,
            batch_size,
            preflight_batch_bytes,
        )
        source = pa.RecordBatchReader.from_batches(
            source_schema,
            _append_record_batches(
                rows,
                pending_indices,
                payload_bytes,
                batch_size,
                preflight_batch_bytes,
                source_schema,
            ),
        )
        rows_added = len(pending_indices)
        custom_metadata = {
            _APPEND_INVOCATION_ID: invocation_id,
            _APPEND_ROWS_ADDED: str(rows_added),
        }
        custom_metadata.update(
            _publication_commit_metadata(
                invocation_id if transaction_digest else "",
                transaction_digest,
                rows_processed=len(incoming_indices),
            )
        )
        write_deltalake(
            table if table is not None else uri,
            source,
            mode="append",
            partition_by=list(partition_by) or None,
            schema_mode="merge",
            storage_options=self.storage_options,
            commit_properties=CommitProperties(custom_metadata=custom_metadata),
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
        scan_partition_values: Mapping[str, frozenset[str]],
    ) -> set[tuple[str, ...]]:
        incoming_by_key = {_row_key(row, key_columns): row for row in incoming_rows}
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
            filters.extend(
                (partition_column, "in", sorted(values))
                for partition_column, values in scan_partition_values.items()
            )
        else:
            filters = [
                [
                    *((column, "=", row[column]) for column in key_columns),
                    *(
                        (partition_column, "in", sorted(values))
                        for partition_column, values in scan_partition_values.items()
                    ),
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

    def _validate_append_target_streaming(
        self,
        table: DeltaTable,
        incoming_rows: Sequence[Mapping[str, Any]],
        key_columns: tuple[str, ...],
        *,
        batch_size: int,
        batch_bytes: int,
        replay_columns: frozenset[str],
        replay_json_fields: Mapping[str, frozenset[str]],
        scan_partition_values: Mapping[str, frozenset[str]],
    ) -> set[tuple[str, ...]]:
        incoming_by_key = {_row_key(row, key_columns): row for row in incoming_rows}
        excluded_columns = {"ingestion_run_id", *replay_columns}
        dataset = table.to_pyarrow_dataset()
        semantic_columns = [
            name
            for name in dataset.schema.names
            if name not in excluded_columns or name in key_columns
        ]
        null_defaults = dict.fromkeys(semantic_columns)
        action_table = pa.table(table.get_add_actions(flatten=True))
        partition_columns = [
            name for name in action_table.column_names if name.startswith("partition.")
        ]
        active_files = {
            _normalized_delta_file_path(str(row["path"])): {
                name.removeprefix("partition."): row.get(name)
                for name in partition_columns
            }
            for row in action_table.select(["path", *partition_columns]).to_pylist()
        }
        existing_keys: set[tuple[str, ...]] = set()
        for file_path in dataset.files:
            partitions = active_files.get(_normalized_delta_file_path(file_path))
            if partitions is None:
                raise RuntimeError("Delta active file is missing partition metadata")
            if any(
                str(partitions.get(column) or "") not in values
                for column, values in scan_partition_values.items()
            ):
                continue
            parquet = pq.ParquetFile(
                file_path,
                filesystem=dataset.filesystem,
                pre_buffer=False,
            )
            missing_key_columns = [
                name
                for name in key_columns
                if name not in parquet.schema_arrow.names and name not in partitions
            ]
            if missing_key_columns:
                raise ValueError(
                    "Delta active file is missing key columns: "
                    + ", ".join(missing_key_columns)
                )
            file_columns = [
                name for name in semantic_columns if name in parquet.schema_arrow.names
            ]
            file_schema = pa.schema(
                [dataset.schema.field(name) for name in file_columns]
            )
            target_batch_size = _parquet_batch_size(
                parquet,
                max_rows=batch_size,
                max_bytes=batch_bytes,
            )
            for batch in parquet.iter_batches(
                batch_size=target_batch_size,
                columns=file_columns,
                use_threads=False,
            ):
                for physical_row in batch.cast(file_schema).to_pylist():
                    existing = {**null_defaults, **physical_row}
                    existing.update(partitions)
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
        columns: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read a Delta table, optionally projecting only required columns."""
        if version is not None and (
            isinstance(version, bool) or not isinstance(version, int) or version < 0
        ):
            raise ValueError("Delta read version must be a non-negative integer")
        self._refresh_storage_options()
        if not self.exists(table_uri):
            if version is not None:
                raise ValueError("Version-qualified Delta table does not exist")
            return []
        uri = str(table_uri)
        table = DeltaTable(
            uri,
            version=version,
            storage_options=self.storage_options,
        )
        projected_columns = list(columns) if columns is not None else None
        if urlparse(uri).scheme in {"", "file"}:
            actions = pa.table(table.get_add_actions(flatten=True))
            files = [
                str(Path(uri) / path) for path in actions.column("path").to_pylist()
            ]
            return (
                pq.read_table(files, columns=projected_columns).to_pylist()
                if files
                else []
            )
        return table.to_pyarrow_table(columns=projected_columns).to_pylist()

    def exists(self, table_uri: str | Path) -> bool:
        return DeltaTable.is_deltatable(
            str(table_uri), storage_options=self.storage_options
        )

    def version(self, table_uri: str | Path) -> int | None:
        self._refresh_storage_options()
        if not self.exists(table_uri):
            return None
        return DeltaTable(
            str(table_uri), storage_options=self.storage_options
        ).version()

    def latest_commit_timestamp(
        self,
        table_uri: str | Path,
        *,
        version: int | None = None,
    ) -> str | None:
        """Return recorded commit time only when bounded history proves the version."""
        if version is not None and (
            isinstance(version, bool) or not isinstance(version, int) or version < 0
        ):
            raise ValueError("Delta history version must be a non-negative integer")
        self._refresh_storage_options()
        if not self.exists(table_uri):
            if version is not None:
                raise ValueError("Version-qualified Delta table does not exist")
            return None
        table = DeltaTable(str(table_uri), storage_options=self.storage_options)
        target_version = table.version() if version is None else version
        history = table.history(limit=_TIMESTAMP_HISTORY_LIMIT)
        commit = next(
            (
                entry
                for entry in history
                if entry.get("version") == target_version
            ),
            None,
        )
        if commit is None:
            return None
        timestamp = commit.get("timestamp")
        if isinstance(timestamp, datetime):
            value = timestamp
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return None
        try:
            return (
                datetime.fromtimestamp(timestamp / 1000, tz=UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError):
            return None

    def describe(self, table_uri: str | Path, *, version: int) -> dict[str, Any]:
        """Read schema and configuration at an explicitly pinned Delta version."""
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError("Delta metadata version must be a non-negative integer")
        self._refresh_storage_options()
        table = DeltaTable(
            str(table_uri), version=version, storage_options=self.storage_options
        )
        return {
            "version": table.version(),
            "schema": json.loads(table.schema().to_json()),
            "configuration": dict(table.metadata().configuration),
        }

    def committed_transaction(
        self,
        table_uri: str | Path,
        *,
        transaction_id: str,
        transaction_digest: str,
    ) -> DeltaWriteResult | None:
        """Return exact Delta commit evidence for one publication intent."""

        _publication_commit_metadata(
            transaction_id,
            transaction_digest,
            rows_processed=0,
        )
        self._refresh_storage_options()
        if not self.exists(table_uri):
            return None
        table = DeltaTable(str(table_uri), storage_options=self.storage_options)
        history = table.history(limit=_PUBLICATION_HISTORY_LIMIT)
        for commit in history:
            if commit.get(_PUBLICATION_INTENT_ID) != transaction_id:
                continue
            if commit.get(_PUBLICATION_OUTCOME_DIGEST) != transaction_digest:
                raise RuntimeError(
                    "Delta publication transaction digest does not match"
                )
            version = int(commit["version"])
            rows_processed = int(commit.get(_PUBLICATION_ROWS_PROCESSED) or 0)
            if version < 0 or rows_processed < 0:
                raise RuntimeError("Invalid Delta publication commit metadata")
            return DeltaWriteResult(
                rows_processed=rows_processed,
                version=version,
            )
        if len(history) == _PUBLICATION_HISTORY_LIMIT:
            raise DeltaHistoryTruncatedError(
                "Delta publication history is truncated before the transaction "
                "could be reconciled; verify the table head and explicitly "
                "abandon the publication checkpoint if the intent cannot be proven"
            )
        return None

    def restore(
        self,
        table_uri: str | Path,
        version: int,
        *,
        transaction_id: str = "",
        transaction_digest: str = "",
        expected_version: int | None | object = _NO_EXPECTED_VERSION,
    ) -> int:
        """Restore a version and return the new version with optional evidence."""

        _validate_expected_version(expected_version)
        self._refresh_storage_options()
        table = DeltaTable(str(table_uri), storage_options=self.storage_options)
        self._assert_table_version(table, expected_version)
        table.restore(
            version,
            commit_properties=CommitProperties(
                custom_metadata=_publication_commit_metadata(
                    transaction_id,
                    transaction_digest,
                    rows_processed=0,
                )
            )
            if transaction_id
            else None,
        )
        table.update_incremental()
        return table.version()

    def _write_once(
        self,
        uri: str,
        rows: list[dict[str, Any]],
        *,
        mode: DeltaWriteMode,
        key_columns: tuple[str, ...],
        partition_by: tuple[str, ...],
        schema: pa.Schema | None,
        commit_metadata: Mapping[str, str],
        expected_version: int | None | object,
    ) -> DeltaWriteResult:
        if mode is DeltaWriteMode.APPEND:
            raise AssertionError("APPEND must use the bounded append path")
        processed_count = len(rows)
        exists = self.exists(uri)
        table = (
            DeltaTable(uri, storage_options=self.storage_options) if exists else None
        )
        self._assert_table_version(table, expected_version)
        supports_version_compare = bool(rows) and {
            "resource_id",
            "change_version",
        } <= set(rows[0])
        if mode is DeltaWriteMode.OVERWRITE and exists and supports_version_compare:
            assert table is not None
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
            schema_unchanged = schema is None or schema.equals(
                pa.schema(table.schema().to_arrow())
            )
            if current_versions == incoming_versions and schema_unchanged:
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
            assert table is not None
            builder = (
                table.merge(
                    source,
                    predicate=predicate,
                    source_alias="source",
                    target_alias="target",
                    merge_schema=True,
                    commit_properties=CommitProperties(
                        custom_metadata=dict(commit_metadata)
                    )
                    if commit_metadata
                    else None,
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
        if table is not None:
            previous_count = table.count()
        write_deltalake(
            table if table is not None else uri,
            source,
            mode="overwrite",
            partition_by=list(partition_by) or None,
            schema_mode="merge",
            storage_options=self.storage_options,
            commit_properties=CommitProperties(custom_metadata=dict(commit_metadata))
            if commit_metadata
            else None,
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
            raise ValueError(
                "Delta row is missing required columns: " + ", ".join(missing)
            )
        for index in range(1, len(rows)):
            row = rows[index]
            row_missing = sorted(required_columns - set(row))
            if row_missing:
                raise ValueError(
                    f"Delta row {index} is missing required columns: "
                    + ", ".join(row_missing)
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

    @staticmethod
    def _assert_table_version(
        table: DeltaTable | None,
        expected_version: int | None | object,
    ) -> None:
        if expected_version is _NO_EXPECTED_VERSION:
            return
        current_version = table.version() if table is not None else None
        if current_version != expected_version:
            raise DeltaVersionConflictError(
                "Delta table changed after publication planning"
            )

    def _refresh_storage_options(self) -> None:
        if self.storage_options_provider is not None:
            self.storage_options = dict(self.storage_options_provider())


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, DeltaVersionConflictError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    text = str(exc).lower()
    if "delta_log" in text and "file not found" in text:
        return True
    return any(
        marker in text
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "timeout",
            "temporarily",
            "conflict",
        )
    )


def _validate_expected_version(value: object) -> None:
    if value is _NO_EXPECTED_VERSION or value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_version must be a non-negative integer or None")


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
    content = {key: value for key, value in row.items() if key not in excluded_columns}
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
            key: item for key, item in parsed.items() if key not in excluded_fields
        }
    return json.dumps(
        content,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _has_active_files(table: DeltaTable) -> bool:
    return bool(table.file_uris())


def _batched_payload_indices(
    indices: Iterable[int],
    payload_bytes: Sequence[int],
    *,
    max_rows: int,
    max_bytes: int,
) -> Iterator[list[int]]:
    batch: list[int] = []
    batch_bytes = 0
    for index in indices:
        row_bytes = payload_bytes[index]
        if batch and (len(batch) >= max_rows or batch_bytes + row_bytes > max_bytes):
            yield batch
            batch = []
            batch_bytes = 0
        batch.append(index)
        batch_bytes += row_bytes
    if batch:
        yield batch


def _parquet_batch_size(
    parquet: pq.ParquetFile,
    *,
    max_rows: int,
    max_bytes: int,
) -> int:
    total_rows = max(1, parquet.metadata.num_rows)
    uncompressed_bytes = sum(
        parquet.metadata.row_group(index).total_byte_size
        for index in range(parquet.metadata.num_row_groups)
    )
    average_row_bytes = max(1, uncompressed_bytes // total_rows)
    return max(1, min(max_rows, max_bytes // average_row_bytes))


def _normalized_delta_file_path(path: str) -> str:
    normalized = path
    while (decoded := unquote(normalized)) != normalized:
        normalized = decoded
    return normalized


def _estimate_row_payload_bytes(row: Mapping[str, Any]) -> int:
    # Estimate one row at a time so sizing does not introduce another
    # aggregate allocation. Iterate the mapping directly instead of copying
    # it so sizing cannot mask failures in later Arrow materialization.
    size = 2
    first = True
    for key in row:
        if not first:
            size += 1
        first = False
        size += len(
            json.dumps(
                str(key),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        size += 1
        size += len(
            json.dumps(
                row[key],
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
    return max(1, size)


def _infer_append_schema(
    rows: Sequence[Mapping[str, Any]],
    indices: Sequence[int],
    payload_bytes: Sequence[int],
    batch_size: int,
    batch_bytes: int,
) -> pa.Schema:
    inferred: pa.Schema | None = None
    for batch in _batched_payload_indices(
        indices,
        payload_bytes,
        max_rows=batch_size,
        max_bytes=batch_bytes,
    ):
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
    payload_bytes: Sequence[int],
    batch_size: int,
    batch_bytes: int,
    schema: pa.Schema,
) -> Iterator[pa.RecordBatch]:
    emitted = False
    for batch in _batched_payload_indices(
        indices,
        payload_bytes,
        max_rows=batch_size,
        max_bytes=batch_bytes,
    ):
        emitted = True
        yield pa.RecordBatch.from_pylist(
            [dict(rows[index]) for index in batch],
            schema=schema,
        )
    if not emitted:
        yield pa.RecordBatch.from_pylist([], schema=schema)
