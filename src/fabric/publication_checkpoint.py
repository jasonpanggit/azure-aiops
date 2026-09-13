"""Durable prepared-state and table-progress checkpoints for Fabric sync."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from storage.delta_writer import DeltaWriteResult
from storage.onelake_documents import (
    DocumentConflictError,
    OneLakeDocumentStore,
)

PUBLICATION_CHECKPOINT_CONTRACT = "fabric-prepared-publication/1.1.0"
_CHECKPOINT_ROOT = "fabric/publication-checkpoints"
_TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_ARTIFACT_CHUNK_BYTES = 4 * 1024 * 1024
_PLAN_DIAGNOSTIC_NAME_LIMIT = 10


class PublicationCheckpointError(RuntimeError):
    """Raised when durable publication checkpoint state is unsafe to use."""


def _table_plan_difference(
    stored_names: Iterable[object],
    requested_names: Iterable[str],
) -> str:
    """Describe a bounded, deterministic table-name-only plan difference."""

    stored = {str(name) for name in stored_names}
    requested = set(requested_names)

    def describe(label: str, names: set[str]) -> str:
        ordered = sorted(names)
        visible = ordered[:_PLAN_DIAGNOSTIC_NAME_LIMIT]
        suffix = (
            f" (showing {_PLAN_DIAGNOSTIC_NAME_LIMIT} of {len(ordered)})"
            if len(ordered) > _PLAN_DIAGNOSTIC_NAME_LIMIT
            else ""
        )
        return f"{label}={len(ordered)} [{', '.join(visible)}]{suffix}"

    return "; ".join(
        (
            describe("added", requested - stored),
            describe("removed", stored - requested),
        )
    )


@dataclass(frozen=True)
class PreparedPublicationCheckpoint:
    """Integrity-checked state restored before Fabric table publication.

    ``persisted_utf8_bytes`` counts canonical serialized artifact bytes,
    including the one newline byte written after every JSON row.
    """

    source_run_id: str
    checkpoint_id: str
    source_manifest_digest: str
    run_id: str
    started_at: str
    source_projected_at: str
    source_watermark: str
    failed_records: int
    ontology_health: dict[str, Any]
    ontology_entity_count: int
    ontology_relationship_count: int
    datasets: dict[str, list[dict[str, Any]]]
    exposure_gold_observation_rows: list[dict[str, Any]] | None
    manifest_digest: str
    persisted_row_count: int
    persisted_utf8_bytes: int


@dataclass(frozen=True)
class CompletedTableWrite:
    """One durable, version-fenced successful Delta table result."""

    table_name: str
    expected_before_version: int | None
    resulting_version: int
    result: DeltaWriteResult


@dataclass(frozen=True)
class TableWriteIntent:
    """Durable transaction intent written before a Delta mutation."""

    table_name: str
    operation: str
    intent_id: str
    outcome_digest: str
    expected_before_version: int | None
    restore_target_version: int | None = None
    restore_from_version: int | None = None


@dataclass(frozen=True)
class PublicationResumePlan:
    """Validated table plan and any previously completed table writes."""

    plan_hash: str
    table_names: tuple[str, ...]
    expected_before_versions: dict[str, int | None]
    completed: dict[str, CompletedTableWrite]
    in_flight: dict[str, TableWriteIntent]
    activation_pending: dict[str, Any] | None


class PublicationCheckpointStore:
    """Persist immutable prepared rows and CAS-guarded publication progress."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self._documents = documents
        self._mutation_lock = threading.Lock()

    def load(
        self,
        source_run_id: str,
        *,
        source_manifest_digest: str,
    ) -> PreparedPublicationCheckpoint | None:
        """Load one exact source checkpoint, or return ``None`` when absent/finalized."""

        prefix = self._prefix(source_run_id)
        manifest_name = f"{prefix}/manifest.json"
        try:
            manifest = self._documents.read_or_raise(manifest_name)
        except FileNotFoundError:
            return None
        if not manifest:
            return None
        self._validate_manifest(manifest, source_run_id=source_run_id)
        if manifest.get("source_manifest_digest") != source_manifest_digest:
            raise PublicationCheckpointError(
                "Publication checkpoint source manifest does not match"
            )
        progress = self._read_progress(source_run_id)
        if progress.get("status") == "finalized":
            return None
        if progress.get("manifest_digest") != manifest["manifest_digest"]:
            raise PublicationCheckpointError(
                "Publication checkpoint progress does not match its manifest"
            )

        datasets: dict[str, list[dict[str, Any]]] = {}
        exposure_rows: list[dict[str, Any]] | None = None
        persisted_row_count = 0
        persisted_utf8_bytes = 0
        for artifact in manifest["artifacts"]:
            rows, artifact_bytes = self._read_artifact(artifact, prefix=prefix)
            persisted_row_count += len(rows)
            persisted_utf8_bytes += artifact_bytes
            if artifact["kind"] == "dataset":
                table_name = _validated_table_name(
                    str(artifact.get("table_name") or "")
                )
                if table_name in datasets:
                    raise PublicationCheckpointError(
                        "Publication checkpoint contains duplicate datasets"
                    )
                datasets[table_name] = rows
            elif artifact["kind"] == "exposure_gold_observations":
                exposure_rows = rows
            else:
                raise PublicationCheckpointError(
                    "Publication checkpoint contains an unknown artifact kind"
                )
        expected_datasets = {
            _validated_table_name(str(item))
            for item in manifest.get("dataset_names", ())
        }
        if set(datasets) != expected_datasets:
            raise PublicationCheckpointError(
                "Publication checkpoint dataset set is incomplete"
            )
        if bool(manifest.get("has_exposure_gold_observations")) != (
            exposure_rows is not None
        ):
            raise PublicationCheckpointError(
                "Publication checkpoint Exposure history is incomplete"
            )
        for field, observed in (
            ("persisted_row_count", persisted_row_count),
            ("persisted_utf8_bytes", persisted_utf8_bytes),
        ):
            declared = manifest.get(field)
            if declared is not None and _non_negative_int(
                declared,
                field=field,
            ) != observed:
                raise PublicationCheckpointError(
                    f"Publication checkpoint {field} failed integrity validation"
                )
        return PreparedPublicationCheckpoint(
            source_run_id=source_run_id,
            checkpoint_id=_checkpoint_id(source_run_id),
            source_manifest_digest=source_manifest_digest,
            run_id=str(manifest["run_id"]),
            started_at=str(manifest["started_at"]),
            source_projected_at=str(manifest["source_projected_at"]),
            source_watermark=str(manifest["source_watermark"]),
            failed_records=_non_negative_int(
                manifest["failed_records"],
                field="failed_records",
            ),
            ontology_health=dict(manifest["ontology_health"]),
            ontology_entity_count=_non_negative_int(
                manifest["ontology_entity_count"],
                field="ontology_entity_count",
            ),
            ontology_relationship_count=_non_negative_int(
                manifest["ontology_relationship_count"],
                field="ontology_relationship_count",
            ),
            datasets=datasets,
            exposure_gold_observation_rows=exposure_rows,
            manifest_digest=str(manifest["manifest_digest"]),
            persisted_row_count=persisted_row_count,
            persisted_utf8_bytes=persisted_utf8_bytes,
        )

    def persist(
        self,
        *,
        source_run_id: str,
        source_manifest_digest: str,
        run_id: str,
        started_at: str,
        source_projected_at: str,
        source_watermark: str,
        failed_records: int,
        ontology_health: Mapping[str, Any],
        ontology_entity_count: int,
        ontology_relationship_count: int,
        datasets: Mapping[str, list[dict[str, Any]]],
        exposure_gold_observation_rows: list[dict[str, Any]] | None,
    ) -> PreparedPublicationCheckpoint:
        """Stream prepared tables to immutable artifacts, writing the manifest last."""

        _required_text(source_run_id, field="source_run_id")
        _required_text(run_id, field="run_id")
        prefix = self._prefix(source_run_id)
        try:
            existing_manifest = self._documents.read_or_raise(
                f"{prefix}/manifest.json"
            )
        except FileNotFoundError:
            existing_manifest = {}
        if not existing_manifest:
            # A process may have died after creating artifacts/progress but
            # before publishing the manifest. Such state is not resumable.
            self.abandon(source_run_id)
        else:
            self._validate_manifest(
                existing_manifest,
                source_run_id=source_run_id,
            )
            if (
                existing_manifest.get("source_manifest_digest")
                != source_manifest_digest
            ):
                raise PublicationCheckpointError(
                    "Publication checkpoint source manifest does not match; "
                    "refusing to replace durable state for this source run"
                )
            progress = self._read_progress(source_run_id)
            status = str(progress.get("status") or "unknown")
            raise PublicationCheckpointError(
                "Publication checkpoint already exists with status "
                f"{status!r}; resume or explicitly abandon it before persisting "
                "replacement state"
            )
        self._documents.ensure_directory(f"{prefix}/artifacts")
        artifacts: list[dict[str, Any]] = []
        for table_name in sorted(datasets):
            _validated_table_name(table_name)
            artifacts.append(
                self._write_artifact(
                    prefix=prefix,
                    key=f"dataset:{table_name}",
                    kind="dataset",
                    table_name=table_name,
                    rows=datasets[table_name],
                )
            )
        if exposure_gold_observation_rows is not None:
            artifacts.append(
                self._write_artifact(
                    prefix=prefix,
                    key="exposure_gold_observations",
                    kind="exposure_gold_observations",
                    table_name=None,
                    rows=exposure_gold_observation_rows,
                )
            )
        persisted_row_count = sum(int(item["row_count"]) for item in artifacts)
        persisted_utf8_bytes = sum(int(item["utf8_bytes"]) for item in artifacts)
        manifest: dict[str, Any] = {
            "contract_version": PUBLICATION_CHECKPOINT_CONTRACT,
            "source_run_id": source_run_id,
            "checkpoint_id": _checkpoint_id(source_run_id),
            "source_manifest_digest": _required_digest(
                source_manifest_digest,
                field="source_manifest_digest",
            ),
            "run_id": run_id,
            "started_at": _required_text(started_at, field="started_at"),
            "source_projected_at": _required_text(
                source_projected_at,
                field="source_projected_at",
            ),
            "source_watermark": str(source_watermark),
            "failed_records": _non_negative_int(
                failed_records,
                field="failed_records",
            ),
            "ontology_health": dict(ontology_health),
            "ontology_entity_count": _non_negative_int(
                ontology_entity_count,
                field="ontology_entity_count",
            ),
            "ontology_relationship_count": _non_negative_int(
                ontology_relationship_count,
                field="ontology_relationship_count",
            ),
            "dataset_names": sorted(datasets),
            "has_exposure_gold_observations": (
                exposure_gold_observation_rows is not None
            ),
            # Bytes include each canonical JSON row's terminating newline.
            "persisted_row_count": persisted_row_count,
            "persisted_utf8_bytes": persisted_utf8_bytes,
            "artifacts": artifacts,
        }
        manifest["manifest_digest"] = _digest_json(manifest)
        progress = {
            "revision": 1,
            "contract_version": PUBLICATION_CHECKPOINT_CONTRACT,
            "source_run_id": source_run_id,
            "manifest_digest": manifest["manifest_digest"],
            "status": "prepared",
            "plan_hash": "",
            "total_tables": 0,
            "table_names": [],
            "expected_before_versions": {},
            "completed_tables": {},
            "in_flight": {},
            "activation": None,
            "final_outcome": None,
        }
        try:
            self._documents.create_only(f"{prefix}/progress.json", progress)
            self._documents.create_only(f"{prefix}/manifest.json", manifest)
        except Exception:
            self.abandon(source_run_id)
            raise
        return PreparedPublicationCheckpoint(
            source_run_id=source_run_id,
            checkpoint_id=_checkpoint_id(source_run_id),
            source_manifest_digest=source_manifest_digest,
            run_id=run_id,
            started_at=started_at,
            source_projected_at=source_projected_at,
            source_watermark=source_watermark,
            failed_records=failed_records,
            ontology_health=dict(ontology_health),
            ontology_entity_count=ontology_entity_count,
            ontology_relationship_count=ontology_relationship_count,
            datasets=dict(datasets),
            exposure_gold_observation_rows=exposure_gold_observation_rows,
            manifest_digest=str(manifest["manifest_digest"]),
            persisted_row_count=persisted_row_count,
            persisted_utf8_bytes=persisted_utf8_bytes,
        )

    def prepare_table_plan(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        *,
        table_names: Iterable[str],
        expected_before_versions: Mapping[str, int | None],
    ) -> PublicationResumePlan:
        """Create or verify the immutable table plan for a prepared checkpoint."""

        names = tuple(sorted(set(table_names)))
        if not names:
            raise PublicationCheckpointError(
                "Publication checkpoint table plan must not be empty"
            )
        if any(not _TABLE_NAME.fullmatch(name) for name in names):
            raise PublicationCheckpointError(
                "Publication checkpoint table plan contains an invalid table name"
            )
        if set(expected_before_versions) != set(names):
            raise PublicationCheckpointError(
                "Publication checkpoint table plan versions are incomplete: "
                + _table_plan_difference(expected_before_versions, names)
            )
        normalized_versions = {
            name: _optional_version(expected_before_versions[name]) for name in names
        }
        plan_hash = _digest_json(
            {
                "contract_version": PUBLICATION_CHECKPOINT_CONTRACT,
                "manifest_digest": checkpoint.manifest_digest,
                "table_names": names,
            }
        )

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            if progress.get("manifest_digest") != checkpoint.manifest_digest:
                raise PublicationCheckpointError(
                    "Publication checkpoint progress does not match prepared state"
                )
            current_hash = str(progress.get("plan_hash") or "")
            if current_hash:
                current_names = tuple(progress.get("table_names") or ())
                if (
                    current_hash != plan_hash
                    or current_names != names
                    or int(progress.get("total_tables") or 0) != len(names)
                ):
                    raise PublicationCheckpointError(
                        "Publication checkpoint table plan does not match prepared "
                        f"state: {_table_plan_difference(current_names, names)}"
                    )
                return progress
            progress.update(
                status="publishing",
                plan_hash=plan_hash,
                total_tables=len(names),
                table_names=list(names),
                expected_before_versions=normalized_versions,
            )
            return progress

        progress = self._mutate(checkpoint.source_run_id, update)
        stored_versions = {
            str(name): _optional_version(version)
            for name, version in dict(
                progress.get("expected_before_versions") or {}
            ).items()
        }
        if stored_versions.keys() != normalized_versions.keys():
            raise PublicationCheckpointError(
                "Publication checkpoint expected-version set is incomplete: "
                + _table_plan_difference(stored_versions, normalized_versions)
            )
        return PublicationResumePlan(
            plan_hash=plan_hash,
            table_names=names,
            expected_before_versions=stored_versions,
            completed=self._completed_writes(progress, names=names),
            in_flight=self._in_flight_intents(progress, names=names),
            activation_pending=self._activation_pending(progress),
        )

    def begin_table_write(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        table_name: str,
        outcome_digest: str,
    ) -> TableWriteIntent:
        """Persist an exact Delta write intent before the table mutation."""

        return self.begin_table_writes(
            checkpoint,
            plan,
            outcome_digests={table_name: outcome_digest},
        )[table_name]

    def begin_table_writes(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        outcome_digests: Mapping[str, str],
    ) -> dict[str, TableWriteIntent]:
        """CAS-persist a batch of independent table intents before execution."""

        intents = {
            table_name: self._table_intent(
                checkpoint,
                plan,
                table_name=table_name,
                operation="write",
                outcome_digest=outcome_digest,
                restore_target_version=None,
                restore_from_version=None,
            )
            for table_name, outcome_digest in outcome_digests.items()
        }
        if not intents:
            return {}
        encoded = {
            table_name: _intent_document(intent)
            for table_name, intent in intents.items()
        }

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            in_flight = dict(progress.get("in_flight") or {})
            for table_name, document in encoded.items():
                existing = in_flight.get(table_name)
                if existing is not None and existing != document:
                    raise PublicationCheckpointError(
                        f"Table {table_name} has a conflicting in-flight intent"
                    )
                in_flight[table_name] = document
            progress["in_flight"] = in_flight
            return progress

        self._mutate(checkpoint.source_run_id, update)
        return intents

    def begin_table_restore(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        table_name: str,
        restore_target_version: int | None,
        outcome_digest: str,
    ) -> TableWriteIntent:
        """Persist a patch-reset intent before restoring or deleting a table."""

        completed = plan.completed.get(table_name)
        if completed is None:
            raise PublicationCheckpointError(
                f"Table {table_name} has no completed result to reset"
            )
        intent = self._table_intent(
            checkpoint,
            plan,
            table_name=table_name,
            operation="restore",
            outcome_digest=outcome_digest,
            restore_target_version=restore_target_version,
            restore_from_version=completed.resulting_version,
        )
        encoded = _intent_document(intent)

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            in_flight = dict(progress.get("in_flight") or {})
            existing = in_flight.get(table_name)
            if existing is not None and existing != encoded:
                raise PublicationCheckpointError(
                    f"Table {table_name} has a conflicting in-flight intent"
                )
            in_flight[table_name] = encoded
            progress["in_flight"] = in_flight
            return progress

        self._mutate(checkpoint.source_run_id, update)
        return intent

    @staticmethod
    def _table_intent(
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        table_name: str,
        operation: str,
        outcome_digest: str,
        restore_target_version: int | None,
        restore_from_version: int | None,
    ) -> TableWriteIntent:
        if table_name not in plan.table_names:
            raise PublicationCheckpointError(
                f"Table {table_name} is not in the checkpoint publication plan"
            )
        if operation == "write" and table_name in plan.completed:
            raise PublicationCheckpointError(
                f"Table {table_name} is already completed"
            )
        _required_digest(outcome_digest, field="outcome_digest")
        expected = plan.expected_before_versions[table_name]
        intent_id = _digest_json(
            {
                "checkpoint_id": checkpoint.checkpoint_id,
                "plan_hash": plan.plan_hash,
                "table_name": table_name,
                "operation": operation,
                "expected_before_version": expected,
                "restore_target_version": restore_target_version,
                "restore_from_version": restore_from_version,
                "outcome_digest": outcome_digest,
            }
        )
        intent = TableWriteIntent(
            table_name=table_name,
            operation=operation,
            intent_id=intent_id,
            outcome_digest=outcome_digest,
            expected_before_version=expected,
            restore_target_version=restore_target_version,
            restore_from_version=restore_from_version,
        )
        return intent

    def record_table_result(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        table_name: str,
        expected_before_version: int | None,
        result: DeltaWriteResult,
        intent: TableWriteIntent,
    ) -> None:
        """CAS-record one successful table result from the publication thread."""

        if table_name not in plan.table_names:
            raise PublicationCheckpointError(
                f"Table {table_name} is not in the checkpoint publication plan"
            )
        resulting_version = _required_version(
            result.version,
            field=f"{table_name} resulting version",
        )
        expected = _optional_version(expected_before_version)
        if expected != plan.expected_before_versions[table_name]:
            raise PublicationCheckpointError(
                f"Table {table_name} before-version does not match its plan"
            )
        if (
            intent.table_name != table_name
            or intent.operation != "write"
            or intent.expected_before_version != expected
        ):
            raise PublicationCheckpointError(
                f"Table {table_name} completion does not match its intent"
            )
        record = {
            "expected_before_version": expected,
            "resulting_version": resulting_version,
            "rows_processed": _non_negative_int(
                result.rows_processed,
                field="rows_processed",
            ),
            "rows_added": _non_negative_int(result.rows_added, field="rows_added"),
            "rows_changed": _non_negative_int(
                result.rows_changed,
                field="rows_changed",
            ),
            "rows_removed": _non_negative_int(
                result.rows_removed,
                field="rows_removed",
            ),
            "skipped": bool(result.skipped),
        }

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            completed = dict(progress.get("completed_tables") or {})
            in_flight = dict(progress.get("in_flight") or {})
            if in_flight.get(table_name) != _intent_document(intent):
                raise PublicationCheckpointError(
                    f"Table {table_name} in-flight intent changed unexpectedly"
                )
            existing = completed.get(table_name)
            if existing is not None:
                if (
                    existing.get("expected_before_version") != expected
                    or existing.get("resulting_version") != resulting_version
                ):
                    raise PublicationCheckpointError(
                        f"Table {table_name} checkpoint result changed unexpectedly"
                    )
                return progress
            completed[table_name] = record
            progress["completed_tables"] = completed
            in_flight.pop(table_name, None)
            progress["in_flight"] = in_flight
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def clear_table_intent(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        intent: TableWriteIntent,
    ) -> None:
        """Clear an uncommitted intent only after its baseline is verified."""

        self.clear_table_intents(checkpoint, plan, (intent,))

    def clear_table_intents(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        intents: Iterable[TableWriteIntent],
    ) -> None:
        """Clear verified-uncommitted intents in one checkpoint CAS update."""

        selected = tuple(intents)
        if not selected:
            return
        if len({intent.table_name for intent in selected}) != len(selected):
            raise PublicationCheckpointError(
                "Publication checkpoint intent batch contains duplicate tables"
            )

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            in_flight = dict(progress.get("in_flight") or {})
            for intent in selected:
                if in_flight.get(intent.table_name) != _intent_document(intent):
                    raise PublicationCheckpointError(
                        f"Table {intent.table_name} in-flight intent changed unexpectedly"
                    )
            for intent in selected:
                in_flight.pop(intent.table_name)
            progress["in_flight"] = in_flight
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def complete_table_restore(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        intent: TableWriteIntent,
        *,
        restored_version: int | None,
    ) -> None:
        """CAS-persist a new post-restore version fence before table reuse."""

        if intent.operation != "restore":
            raise PublicationCheckpointError("Table reset requires a restore intent")
        normalized = _optional_version(restored_version)

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            in_flight = dict(progress.get("in_flight") or {})
            if in_flight.get(intent.table_name) != _intent_document(intent):
                raise PublicationCheckpointError(
                    f"Table {intent.table_name} restore intent changed unexpectedly"
                )
            completed = dict(progress.get("completed_tables") or {})
            completed.pop(intent.table_name, None)
            expected = dict(progress.get("expected_before_versions") or {})
            expected[intent.table_name] = normalized
            in_flight.pop(intent.table_name)
            progress["completed_tables"] = completed
            progress["expected_before_versions"] = expected
            progress["in_flight"] = in_flight
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def mark_activation_pending(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        activation: Mapping[str, Any],
    ) -> None:
        """Persist staged Gold pointer preconditions before pointer activation."""

        document = _validated_activation_document(activation)

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            if progress.get("in_flight"):
                raise PublicationCheckpointError(
                    "Cannot activate with in-flight table mutations"
                )
            missing = set(plan.table_names) - set(
                progress.get("completed_tables") or {}
            )
            if missing:
                raise PublicationCheckpointError(
                    "Cannot activate an incomplete publication checkpoint"
                )
            existing = progress.get("activation")
            if existing not in (None, document):
                raise PublicationCheckpointError(
                    "Publication checkpoint activation state changed"
                )
            progress["activation"] = document
            progress["status"] = "activation_pending"
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def clear_table_results(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        table_names: Iterable[str],
    ) -> None:
        """Remove rolled-back table results so a later retry cannot skip them."""

        names = set(table_names)
        if not names:
            return

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            completed = dict(progress.get("completed_tables") or {})
            for name in names:
                completed.pop(name, None)
            progress["completed_tables"] = completed
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def finalize(
        self,
        checkpoint: PreparedPublicationCheckpoint,
        plan: PublicationResumePlan,
        *,
        outcome: Mapping[str, Any],
    ) -> None:
        """Durably prevent reuse after all publication finalization succeeds."""

        final_outcome = _validated_final_outcome(outcome)

        def update(progress: dict[str, Any]) -> dict[str, Any]:
            self._validate_plan_progress(progress, plan)
            missing = set(plan.table_names) - set(
                progress.get("completed_tables") or {}
            )
            if missing:
                raise PublicationCheckpointError(
                    "Cannot finalize an incomplete publication checkpoint"
                )
            if progress.get("activation") is not None and progress.get(
                "status"
            ) != "activation_pending":
                raise PublicationCheckpointError(
                    "Publication checkpoint activation state is invalid"
                )
            progress["final_outcome"] = final_outcome
            progress["status"] = "finalized"
            return progress

        self._mutate(checkpoint.source_run_id, update)

    def finalized_outcome(
        self,
        source_run_id: str,
        *,
        source_manifest_digest: str,
    ) -> dict[str, Any] | None:
        """Return the exact terminal result for an already-finalized source."""

        prefix = self._prefix(source_run_id)
        try:
            manifest = self._documents.read_or_raise(f"{prefix}/manifest.json")
        except FileNotFoundError:
            return None
        if not manifest:
            return None
        self._validate_manifest(manifest, source_run_id=source_run_id)
        if manifest.get("source_manifest_digest") != source_manifest_digest:
            raise PublicationCheckpointError(
                "Publication checkpoint source manifest does not match"
            )
        progress = self._read_progress(source_run_id)
        if progress.get("manifest_digest") != manifest["manifest_digest"]:
            raise PublicationCheckpointError(
                "Publication checkpoint progress does not match its manifest"
            )
        if progress.get("status") != "finalized":
            return None
        outcome = progress.get("final_outcome")
        if not isinstance(outcome, Mapping):
            raise PublicationCheckpointError(
                "Finalized publication checkpoint has no terminal outcome"
            )
        return _validated_final_outcome(outcome)

    def supersede_finalized(self, source_run_id: str) -> bool:
        """Discard a terminal checkpoint so a normal sync can publish again.

        Finalized state is no longer needed for crash recovery because its
        publication result is already durable. Non-finalized state is never
        removed here: it may contain the only resumable record of partial
        table writes and must instead be loaded with an exact manifest match.
        """

        prefix = self._prefix(source_run_id)
        try:
            manifest = self._documents.read_or_raise(f"{prefix}/manifest.json")
        except FileNotFoundError:
            return False
        if not manifest:
            return False
        self._validate_manifest(manifest, source_run_id=source_run_id)
        progress = self._read_progress(source_run_id)
        if progress.get("manifest_digest") != manifest["manifest_digest"]:
            raise PublicationCheckpointError(
                "Publication checkpoint progress does not match its manifest"
            )
        if progress.get("status") != "finalized":
            return False
        outcome = progress.get("final_outcome")
        if not isinstance(outcome, Mapping):
            raise PublicationCheckpointError(
                "Finalized publication checkpoint has no terminal outcome"
            )
        _validated_final_outcome(outcome)
        self.abandon(source_run_id)
        return True

    def has_in_flight(self, source_run_id: str) -> bool:
        """Return whether a checkpoint has an unresolved storage mutation."""

        return bool(self._read_progress(source_run_id).get("in_flight"))

    def abandon(self, source_run_id: str) -> None:
        """Delete every artifact for an unusable or rolled-back checkpoint."""

        prefix = self._prefix(source_run_id)
        while True:
            names, _continuation = self._documents.list_names(
                prefix,
                limit=1_000,
            )
            if not names:
                return
            for name in names:
                self._documents.delete(name)

    def _write_artifact(
        self,
        *,
        prefix: str,
        key: str,
        kind: str,
        table_name: str | None,
        rows: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        artifact_name = (
            f"{prefix}/artifacts/{hashlib.sha256(key.encode()).hexdigest()}.jsonl"
        )
        digest = hashlib.sha256()
        row_count = 0
        utf8_bytes = 0

        def chunks() -> Iterable[str]:
            nonlocal row_count, utf8_bytes
            buffered: list[str] = []
            buffered_bytes = 0
            for row in rows:
                if not isinstance(row, Mapping):
                    raise PublicationCheckpointError(
                        "Publication checkpoint rows must be mappings"
                    )
                line = _canonical_json(dict(row)) + "\n"
                encoded = line.encode("utf-8")
                if buffered and (
                    buffered_bytes + len(encoded) > _ARTIFACT_CHUNK_BYTES
                ):
                    yield "".join(buffered)
                    buffered = []
                    buffered_bytes = 0
                digest.update(encoded)
                row_count += 1
                utf8_bytes += len(encoded)
                buffered.append(line)
                buffered_bytes += len(encoded)
            if buffered:
                yield "".join(buffered)

        self._documents.create_text_chunks_only(artifact_name, chunks())
        artifact: dict[str, Any] = {
            "kind": kind,
            "name": artifact_name,
            "row_count": row_count,
            "utf8_bytes": utf8_bytes,
            "sha256": digest.hexdigest(),
        }
        if table_name is not None:
            artifact["table_name"] = table_name
        return artifact

    def _read_artifact(
        self,
        artifact: Mapping[str, Any],
        *,
        prefix: str,
    ) -> tuple[list[dict[str, Any]], int]:
        name = str(artifact.get("name") or "")
        if not name.startswith(f"{prefix}/artifacts/"):
            raise PublicationCheckpointError(
                "Publication checkpoint artifact escaped its source directory"
            )
        expected_count = _non_negative_int(
            artifact.get("row_count"),
            field="artifact row_count",
        )
        expected_digest = str(artifact.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise PublicationCheckpointError(
                "Publication checkpoint artifact digest is invalid"
            )
        rows: list[dict[str, Any]] = []
        digest = hashlib.sha256()
        utf8_bytes = 0
        try:
            with closing(self._documents.iter_text_lines_or_raise(name)) as lines:
                for line in lines:
                    encoded = line.encode("utf-8")
                    digest.update(encoded)
                    utf8_bytes += len(encoded)
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise PublicationCheckpointError(
                            "Publication checkpoint artifact contains invalid JSON"
                        ) from exc
                    if not isinstance(row, dict):
                        raise PublicationCheckpointError(
                            "Publication checkpoint artifact row is not an object"
                        )
                    rows.append(row)
        except (FileNotFoundError, UnicodeError) as exc:
            raise PublicationCheckpointError(
                "Publication checkpoint artifact is missing or unreadable"
            ) from exc
        if len(rows) != expected_count or digest.hexdigest() != expected_digest:
            raise PublicationCheckpointError(
                "Publication checkpoint artifact failed integrity validation"
            )
        declared_bytes = artifact.get("utf8_bytes")
        if declared_bytes is not None and _non_negative_int(
            declared_bytes,
            field="artifact utf8_bytes",
        ) != utf8_bytes:
            raise PublicationCheckpointError(
                "Publication checkpoint artifact byte count failed integrity validation"
            )
        return rows, utf8_bytes

    def _validate_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        source_run_id: str,
    ) -> None:
        if manifest.get("contract_version") != PUBLICATION_CHECKPOINT_CONTRACT:
            raise PublicationCheckpointError(
                "Publication checkpoint contract is incompatible"
            )
        if manifest.get("source_run_id") != source_run_id:
            raise PublicationCheckpointError(
                "Publication checkpoint source generation does not match"
            )
        if manifest.get("checkpoint_id") != _checkpoint_id(source_run_id):
            raise PublicationCheckpointError(
                "Publication checkpoint identity does not match"
            )
        supplied_digest = str(manifest.get("manifest_digest") or "")
        content = dict(manifest)
        content.pop("manifest_digest", None)
        if supplied_digest != _digest_json(content):
            raise PublicationCheckpointError(
                "Publication checkpoint manifest failed integrity validation"
            )
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise PublicationCheckpointError(
                "Publication checkpoint artifact manifest is invalid"
            )
        names = [
            str(item.get("name") or "") for item in artifacts if isinstance(item, dict)
        ]
        if len(names) != len(artifacts) or len(names) != len(set(names)):
            raise PublicationCheckpointError(
                "Publication checkpoint artifact manifest contains duplicates"
            )
        if not isinstance(manifest.get("ontology_health"), dict):
            raise PublicationCheckpointError(
                "Publication checkpoint ontology health is invalid"
            )
        _required_text(str(manifest.get("run_id") or ""), field="run_id")
        _required_text(str(manifest.get("started_at") or ""), field="started_at")
        _required_text(
            str(manifest.get("source_projected_at") or ""),
            field="source_projected_at",
        )

    def _read_progress(self, source_run_id: str) -> dict[str, Any]:
        name = f"{self._prefix(source_run_id)}/progress.json"
        try:
            progress = self._documents.read_or_raise(name)
        except FileNotFoundError as exc:
            raise PublicationCheckpointError(
                "Publication checkpoint progress document is missing"
            ) from exc
        if not progress:
            raise PublicationCheckpointError(
                "Publication checkpoint progress document is missing"
            )
        if progress.get("contract_version") != PUBLICATION_CHECKPOINT_CONTRACT:
            raise PublicationCheckpointError(
                "Publication checkpoint progress contract is incompatible"
            )
        if progress.get("source_run_id") != source_run_id:
            raise PublicationCheckpointError(
                "Publication checkpoint progress source generation does not match"
            )
        _non_negative_int(progress.get("revision"), field="progress revision")
        if progress.get("status") not in {
            "prepared",
            "publishing",
            "activation_pending",
            "finalized",
        }:
            raise PublicationCheckpointError(
                "Publication checkpoint progress status is invalid"
            )
        return progress

    def _mutate(
        self,
        source_run_id: str,
        operation: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        name = f"{self._prefix(source_run_id)}/progress.json"
        with self._mutation_lock:
            for _attempt in range(3):
                progress = self._read_progress(source_run_id)
                revision = _non_negative_int(
                    progress.get("revision"),
                    field="progress revision",
                )
                updated = operation(dict(progress))
                updated["revision"] = revision + 1
                try:
                    self._documents.write(
                        name,
                        updated,
                        expected_revision=revision,
                    )
                    return updated
                except DocumentConflictError:
                    continue
        raise PublicationCheckpointError(
            "Publication checkpoint progress changed concurrently"
        )

    def _completed_writes(
        self,
        progress: Mapping[str, Any],
        *,
        names: tuple[str, ...],
    ) -> dict[str, CompletedTableWrite]:
        raw = progress.get("completed_tables") or {}
        if not isinstance(raw, dict) or not set(raw).issubset(names):
            raise PublicationCheckpointError(
                "Publication checkpoint completed-table set is invalid"
            )
        completed: dict[str, CompletedTableWrite] = {}
        for table_name, value in raw.items():
            if not isinstance(value, dict):
                raise PublicationCheckpointError(
                    "Publication checkpoint table result is invalid"
                )
            expected = _optional_version(value.get("expected_before_version"))
            resulting = _required_version(
                value.get("resulting_version"),
                field=f"{table_name} resulting version",
            )
            completed[table_name] = CompletedTableWrite(
                table_name=table_name,
                expected_before_version=expected,
                resulting_version=resulting,
                result=DeltaWriteResult(
                    rows_processed=_non_negative_int(
                        value.get("rows_processed"),
                        field="rows_processed",
                    ),
                    rows_added=_non_negative_int(
                        value.get("rows_added"),
                        field="rows_added",
                    ),
                    rows_changed=_non_negative_int(
                        value.get("rows_changed"),
                        field="rows_changed",
                    ),
                    rows_removed=_non_negative_int(
                        value.get("rows_removed"),
                        field="rows_removed",
                    ),
                    skipped=bool(value.get("skipped")),
                    version=resulting,
                ),
            )
        return completed

    def _in_flight_intents(
        self,
        progress: Mapping[str, Any],
        *,
        names: tuple[str, ...],
    ) -> dict[str, TableWriteIntent]:
        raw = progress.get("in_flight") or {}
        if not isinstance(raw, dict) or not set(raw).issubset(names):
            raise PublicationCheckpointError(
                "Publication checkpoint in-flight intent set is invalid"
            )
        return {
            str(table_name): _parse_intent(str(table_name), value)
            for table_name, value in raw.items()
        }

    @staticmethod
    def _activation_pending(
        progress: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        raw = progress.get("activation")
        if raw is None:
            if progress.get("status") == "activation_pending":
                raise PublicationCheckpointError(
                    "Publication checkpoint activation payload is missing"
                )
            return None
        if progress.get("status") != "activation_pending":
            raise PublicationCheckpointError(
                "Publication checkpoint activation payload is unexpected"
            )
        if not isinstance(raw, Mapping):
            raise PublicationCheckpointError(
                "Publication checkpoint activation payload is invalid"
            )
        return _validated_activation_document(raw)

    @staticmethod
    def _validate_plan_progress(
        progress: Mapping[str, Any],
        plan: PublicationResumePlan,
    ) -> None:
        if (
            progress.get("plan_hash") != plan.plan_hash
            or int(progress.get("total_tables") or 0) != len(plan.table_names)
            or tuple(progress.get("table_names") or ()) != plan.table_names
            or progress.get("status") == "finalized"
        ):
            raise PublicationCheckpointError(
                "Publication checkpoint table plan changed unexpectedly"
            )

    @staticmethod
    def _prefix(source_run_id: str) -> str:
        _required_text(source_run_id, field="source_run_id")
        digest = hashlib.sha256(source_run_id.encode("utf-8")).hexdigest()
        return f"{_CHECKPOINT_ROOT}/{digest}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _validated_table_name(value: str) -> str:
    if not _TABLE_NAME.fullmatch(value):
        raise PublicationCheckpointError(f"Invalid checkpoint table name: {value!r}")
    return value


def _required_text(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicationCheckpointError(f"{field} must not be empty")
    return value


def _non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicationCheckpointError(f"{field} must be a non-negative integer")
    return value


def _optional_version(value: Any) -> int | None:
    if value is None:
        return None
    return _required_version(value, field="Delta version")


def _required_version(value: Any, *, field: str) -> int:
    return _non_negative_int(value, field=field)


def _required_digest(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PublicationCheckpointError(f"{field} must be a SHA-256 digest")
    return value


def _checkpoint_id(source_run_id: str) -> str:
    return hashlib.sha256(source_run_id.encode("utf-8")).hexdigest()


def _intent_document(intent: TableWriteIntent) -> dict[str, Any]:
    return {
        "table_name": intent.table_name,
        "operation": intent.operation,
        "intent_id": intent.intent_id,
        "outcome_digest": intent.outcome_digest,
        "expected_before_version": intent.expected_before_version,
        "restore_target_version": intent.restore_target_version,
        "restore_from_version": intent.restore_from_version,
    }


def _parse_intent(table_name: str, value: Any) -> TableWriteIntent:
    if not isinstance(value, Mapping):
        raise PublicationCheckpointError(
            f"Table {table_name} in-flight intent is invalid"
        )
    if value.get("table_name") != table_name:
        raise PublicationCheckpointError(
            f"Table {table_name} in-flight intent identity changed"
        )
    operation = str(value.get("operation") or "")
    if operation not in {"write", "restore"}:
        raise PublicationCheckpointError(
            f"Table {table_name} in-flight operation is invalid"
        )
    return TableWriteIntent(
        table_name=table_name,
        operation=operation,
        intent_id=_required_digest(
            value.get("intent_id"),
            field="intent_id",
        ),
        outcome_digest=_required_digest(
            value.get("outcome_digest"),
            field="outcome_digest",
        ),
        expected_before_version=_optional_version(
            value.get("expected_before_version")
        ),
        restore_target_version=_optional_version(
            value.get("restore_target_version")
        ),
        restore_from_version=_optional_version(
            value.get("restore_from_version")
        ),
    )


def _validated_activation_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "generation_id",
        "previous_generation_id",
        "published_at",
        "retain_until",
        "expected_pointer_revision",
        "expected_readable_generation",
        "merge_counts",
        "reconciliation",
        "shadow_reconciliation",
    }
    if set(value) != required:
        raise PublicationCheckpointError(
            "Publication checkpoint activation payload fields are invalid"
        )
    generation_id = _required_text(
        str(value.get("generation_id") or ""),
        field="generation_id",
    )
    if len(generation_id) > 256:
        raise PublicationCheckpointError("generation_id is too long")
    previous = value.get("previous_generation_id")
    if previous is not None and (
        not isinstance(previous, str) or len(previous) > 256
    ):
        raise PublicationCheckpointError("previous_generation_id is invalid")
    expected_readable = str(value.get("expected_readable_generation") or "")
    if len(expected_readable) > 256:
        raise PublicationCheckpointError(
            "expected_readable_generation is too long"
        )
    merge_counts = value.get("merge_counts")
    reconciliation = value.get("reconciliation")
    shadow = value.get("shadow_reconciliation")
    if not isinstance(merge_counts, Mapping) or not all(
        isinstance(key, str)
        and not isinstance(count, bool)
        and isinstance(count, int)
        and count >= 0
        for key, count in merge_counts.items()
    ):
        raise PublicationCheckpointError("activation merge_counts are invalid")
    if not isinstance(reconciliation, Mapping):
        raise PublicationCheckpointError("activation reconciliation is invalid")
    if shadow is not None and not isinstance(shadow, Mapping):
        raise PublicationCheckpointError(
            "activation shadow reconciliation is invalid"
        )
    return {
        "generation_id": generation_id,
        "previous_generation_id": previous,
        "published_at": _required_text(
            str(value.get("published_at") or ""),
            field="published_at",
        ),
        "retain_until": _required_text(
            str(value.get("retain_until") or ""),
            field="retain_until",
        ),
        "expected_pointer_revision": _non_negative_int(
            value.get("expected_pointer_revision"),
            field="expected_pointer_revision",
        ),
        "expected_readable_generation": expected_readable,
        "merge_counts": dict(merge_counts),
        "reconciliation": dict(reconciliation),
        "shadow_reconciliation": dict(shadow) if shadow is not None else None,
    }


def _validated_final_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "run_id",
        "source_run_id",
        "status",
        "replay",
        "rows_processed",
        "rows_added",
        "rows_changed",
        "rows_removed",
        "failed_records",
        "tables",
        "duration_seconds",
    }
    if set(value) != required:
        raise PublicationCheckpointError(
            "Publication checkpoint terminal outcome fields are invalid"
        )
    if value.get("status") != "completed":
        raise PublicationCheckpointError(
            "Publication checkpoint terminal outcome is not completed"
        )
    tables = value.get("tables")
    if not isinstance(tables, (list, tuple)) or any(
        not isinstance(table, str) or not _TABLE_NAME.fullmatch(table)
        for table in tables
    ):
        raise PublicationCheckpointError(
            "Publication checkpoint terminal table set is invalid"
        )
    duration = value.get("duration_seconds")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or duration < 0
    ):
        raise PublicationCheckpointError(
            "Publication checkpoint terminal duration is invalid"
        )
    if not isinstance(value.get("replay"), bool):
        raise PublicationCheckpointError(
            "Publication checkpoint terminal replay flag is invalid"
        )
    return {
        "run_id": _required_text(str(value.get("run_id") or ""), field="run_id"),
        "source_run_id": _required_text(
            str(value.get("source_run_id") or ""),
            field="source_run_id",
        ),
        "status": "completed",
        "replay": value["replay"],
        "rows_processed": _non_negative_int(
            value.get("rows_processed"),
            field="rows_processed",
        ),
        "rows_added": _non_negative_int(
            value.get("rows_added"),
            field="rows_added",
        ),
        "rows_changed": _non_negative_int(
            value.get("rows_changed"),
            field="rows_changed",
        ),
        "rows_removed": _non_negative_int(
            value.get("rows_removed"),
            field="rows_removed",
        ),
        "failed_records": _non_negative_int(
            value.get("failed_records"),
            field="failed_records",
        ),
        "tables": list(tables),
        "duration_seconds": float(duration),
    }


__all__ = [
    "PUBLICATION_CHECKPOINT_CONTRACT",
    "CompletedTableWrite",
    "PreparedPublicationCheckpoint",
    "PublicationCheckpointError",
    "PublicationCheckpointStore",
    "PublicationResumePlan",
    "TableWriteIntent",
]
