"""Durable immutable evaluation snapshots with a CAS-protected latest pointer."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .evaluation import EvaluationSnapshot

_ROOT = "ontology_evaluations"


class SnapshotConflictError(RuntimeError):
    """A stale writer attempted to advance a scope's latest pointer."""


class SnapshotIntegrityError(RuntimeError):
    """Persisted evaluation state is malformed or content-inconsistent."""


class LatestEvaluationPointer(BaseModel):
    """Small mutable pointer; snapshots remain separate and immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    revision: int = Field(ge=1)
    scope_key: str
    scope_hash: str
    snapshot_id: str
    evaluated_at: datetime


class _HistoryIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    revision: int = Field(ge=1)
    scope_key: str
    scope_hash: str
    snapshot_ids: tuple[str, ...]


class EvaluationSnapshotStore:
    """Persist evaluation evidence before exposing it to release policy."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        document_store: OneLakeDocumentStore | None = None,
        max_snapshots_per_scope: int = 5000,
    ) -> None:
        if (root is None) == (document_store is None):
            raise ValueError("Use exactly one of root or document_store")
        if (
            isinstance(max_snapshots_per_scope, bool)
            or not isinstance(max_snapshots_per_scope, int)
            or max_snapshots_per_scope < 1
        ):
            raise ValueError("max_snapshots_per_scope must be a positive integer")
        self.documents = document_store or OneLakeDocumentStore(root)
        self.max_snapshots_per_scope = max_snapshots_per_scope
        self._lock = threading.RLock()

    def write(
        self,
        snapshot: EvaluationSnapshot,
        *,
        expected_revision: int,
    ) -> EvaluationSnapshot:
        """Persist immutable evidence, index it, then CAS-advance latest."""
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        with self._lock:
            self._ensure_immutable_snapshot(snapshot)
            self._append_history(snapshot)
            current = self.pointer(snapshot.scope_hash)
            current_revision = current.revision if current is not None else 0
            if current_revision != expected_revision:
                raise SnapshotConflictError(
                    "evaluation latest pointer changed; reload and retry"
                )
            if current is not None and current.snapshot_id == snapshot.snapshot_id:
                return snapshot
            pointer = LatestEvaluationPointer(
                revision=expected_revision + 1,
                scope_key=snapshot.scope_key,
                scope_hash=snapshot.scope_hash,
                snapshot_id=snapshot.snapshot_id,
                evaluated_at=snapshot.evaluated_at,
            )
            try:
                self.documents.write(
                    self._pointer_name(snapshot.scope_hash),
                    pointer.model_dump(mode="json"),
                    expected_revision=expected_revision,
                )
            except DocumentConflictError as exc:
                raise SnapshotConflictError(
                    "evaluation latest pointer changed; reload and retry"
                ) from exc
            return snapshot

    def pointer(self, scope_hash: str) -> LatestEvaluationPointer | None:
        payload = self.documents.read_or_raise(self._pointer_name(scope_hash))
        if not payload:
            return None
        try:
            return _validate_json(LatestEvaluationPointer, payload)
        except ValidationError as exc:
            raise SnapshotIntegrityError("evaluation latest pointer is invalid") from exc

    def read_snapshot(
        self,
        scope_hash: str,
        snapshot_id: str,
    ) -> EvaluationSnapshot | None:
        payload = self.documents.read_or_raise(
            self._snapshot_name(scope_hash, snapshot_id)
        )
        if not payload:
            return None
        snapshot_payload = payload.get("snapshot")
        if not isinstance(snapshot_payload, dict) or int(payload.get("revision") or 0) != 1:
            raise SnapshotIntegrityError("evaluation snapshot envelope is invalid")
        try:
            snapshot = _validate_json(EvaluationSnapshot, snapshot_payload)
        except ValidationError as exc:
            raise SnapshotIntegrityError("evaluation snapshot is invalid") from exc
        if snapshot.scope_hash != scope_hash or snapshot.snapshot_id != snapshot_id:
            raise SnapshotIntegrityError("evaluation snapshot path does not match content")
        return snapshot

    def release_evidence(
        self,
        scope_hash: str,
        *,
        now: datetime,
    ) -> EvaluationSnapshot | None:
        """Return only fresh, explicitly eligible durable evidence."""
        pointer = self.pointer(scope_hash)
        if pointer is None:
            return None
        snapshot = self.read_snapshot(scope_hash, pointer.snapshot_id)
        if (
            snapshot is None
            or not snapshot.release_eligible
            or now >= snapshot.effective_expires_at
        ):
            return None
        return snapshot

    def _ensure_immutable_snapshot(self, snapshot: EvaluationSnapshot) -> None:
        name = self._snapshot_name(snapshot.scope_hash, snapshot.snapshot_id)
        envelope = {
            "revision": 1,
            "snapshot": snapshot.model_dump(mode="json"),
        }
        existing = self.documents.read_or_raise(name)
        if existing:
            self._assert_same_snapshot(existing, snapshot)
            return
        try:
            self.documents.write(name, envelope, expected_revision=0)
        except DocumentConflictError:
            existing = self.documents.read_or_raise(name)
            self._assert_same_snapshot(existing, snapshot)

    def _assert_same_snapshot(
        self,
        envelope: dict[str, object],
        snapshot: EvaluationSnapshot,
    ) -> None:
        stored = envelope.get("snapshot")
        if not isinstance(stored, dict):
            raise SnapshotIntegrityError("evaluation snapshot envelope is invalid")
        try:
            parsed = _validate_json(EvaluationSnapshot, stored)
        except ValidationError as exc:
            raise SnapshotIntegrityError("evaluation snapshot is invalid") from exc
        if parsed != snapshot:
            raise SnapshotIntegrityError("immutable evaluation snapshot collision")

    def _append_history(self, snapshot: EvaluationSnapshot) -> None:
        name = self._history_name(snapshot.scope_hash)
        for _attempt in range(3):
            payload = self.documents.read_or_raise(name)
            if payload:
                try:
                    current = _validate_json(_HistoryIndex, payload)
                except ValidationError as exc:
                    raise SnapshotIntegrityError(
                        "evaluation history index is invalid"
                    ) from exc
                if (
                    current.scope_key != snapshot.scope_key
                    or current.scope_hash != snapshot.scope_hash
                ):
                    raise SnapshotIntegrityError(
                        "evaluation history scope does not match snapshot"
                    )
                if snapshot.snapshot_id in current.snapshot_ids:
                    return
                ids = (*current.snapshot_ids, snapshot.snapshot_id)
                expected_revision = current.revision
            else:
                ids = (snapshot.snapshot_id,)
                expected_revision = 0
            if len(ids) > self.max_snapshots_per_scope:
                raise ValueError("evaluation snapshot history is full")
            history = _HistoryIndex(
                revision=expected_revision + 1,
                scope_key=snapshot.scope_key,
                scope_hash=snapshot.scope_hash,
                snapshot_ids=ids,
            )
            try:
                self.documents.write(
                    name,
                    history.model_dump(mode="json"),
                    expected_revision=expected_revision,
                )
                return
            except DocumentConflictError:
                continue
        raise SnapshotConflictError("evaluation history changed; reload and retry")

    @staticmethod
    def _snapshot_name(scope_hash: str, snapshot_id: str) -> str:
        return f"{_ROOT}/snapshots/{scope_hash}/{snapshot_id}.json"

    @staticmethod
    def _pointer_name(scope_hash: str) -> str:
        return f"{_ROOT}/latest/{scope_hash}.json"

    @staticmethod
    def _history_name(scope_hash: str) -> str:
        return f"{_ROOT}/history/{scope_hash}.json"


def _validate_json(model: type[BaseModel], payload: dict[str, object]) -> Self:
    return model.model_validate_json(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )


__all__ = [
    "EvaluationSnapshotStore",
    "LatestEvaluationPointer",
    "SnapshotConflictError",
    "SnapshotIntegrityError",
]
