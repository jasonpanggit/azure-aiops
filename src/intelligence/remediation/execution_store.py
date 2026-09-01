"""Durable execution record store for remediation plan execution.

Mirrors :class:`intelligence.remediation.approval_decisions.RemediationDecisionStore`'s
persistence shape (OneLake-or-file, revisioned write-with-retry) so an
execution record survives a process restart just like an approval decision
does. The one additional invariant this store enforces: a plan may never
carry two concurrently non-terminal executions (EXEC-03 idempotency/
no-concurrent-execution guard).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.onelake_documents import DocumentConflictError

from .approval_decisions import RevisionedDocumentStore

EXECUTION_STATUS_QUEUED = "queued"
EXECUTION_STATUS_RUNNING = "running"
EXECUTION_STATUS_SUCCEEDED = "succeeded"
EXECUTION_STATUS_FAILED = "failed"
EXECUTION_STATUS_RETRYING = "retrying"
EXECUTION_STATUS_CANCELLED = "cancelled"

EXECUTION_STATUSES: tuple[str, ...] = (
    EXECUTION_STATUS_QUEUED,
    EXECUTION_STATUS_RUNNING,
    EXECUTION_STATUS_SUCCEEDED,
    EXECUTION_STATUS_FAILED,
    EXECUTION_STATUS_RETRYING,
    EXECUTION_STATUS_CANCELLED,
)

EXECUTION_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {EXECUTION_STATUS_SUCCEEDED, EXECUTION_STATUS_FAILED, EXECUTION_STATUS_CANCELLED}
)


class RemediationExecutionStore:
    """Append/update durable store for remediation execution job records."""

    _SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        document_store: RevisionedDocumentStore | None = None,
        document_name: str = "state/remediation_executions.json",
        max_executions: int = 5000,
    ) -> None:
        if path is not None and document_store is not None:
            raise ValueError("Use either path or document_store, not both")
        if isinstance(max_executions, bool) or not isinstance(max_executions, int):
            raise TypeError("max_executions must be an integer")
        if max_executions < 1:
            raise ValueError("max_executions must be positive")
        self.path = Path(path) if path is not None else None
        self.document_store = document_store
        self.document_name = document_name
        self.max_executions = max_executions
        self._memory: dict[str, Any] | None = None
        self._lock = threading.RLock()

    def create(self, plan_id: str, *, requested_by: str, now: datetime | None = None) -> dict[str, Any]:
        """Create a new execution record in ``queued``.

        If a non-terminal (queued/running/retrying) execution already
        exists for this ``plan_id``, that existing record is returned
        instead of starting a second one -- the concurrent-execution guard.
        """
        timestamp = (now or datetime.now(UTC)).isoformat()
        with self._lock:
            for _ in range(3):
                state = self._read_state()
                executions = state["executions"]
                existing = next(
                    (
                        row
                        for row in executions
                        if row["plan_id"] == plan_id
                        and row["status"] not in EXECUTION_TERMINAL_STATUSES
                    ),
                    None,
                )
                if existing is not None:
                    return copy.deepcopy(existing)
                if len(executions) >= self.max_executions:
                    raise ValueError("Remediation execution store is full")
                sequence = len(executions) + 1
                execution_id = "RME-" + hashlib.sha256(
                    f"{plan_id}|{requested_by}|{timestamp}|{sequence}".encode()
                ).hexdigest()[:16].upper()
                record = {
                    "execution_id": execution_id,
                    "plan_id": str(plan_id),
                    "status": EXECUTION_STATUS_QUEUED,
                    "requested_by": requested_by,
                    "approved_by": "",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "provider_job_id": "",
                    "message": "",
                    "attempt_count": 1,
                    "rollback_guidance": "",
                    "verified_state": "",
                    "failure_details": "",
                }
                executions.append(copy.deepcopy(record))
                state["revision"] += 1
                state["updated_at"] = timestamp
                try:
                    self._write_state(state, expected_revision=state["revision"] - 1)
                except DocumentConflictError:
                    continue
                return copy.deepcopy(record)
        raise DocumentConflictError("Remediation execution store changed during create")

    def get(self, execution_id: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read_state()["executions"]
        return next(
            (copy.deepcopy(row) for row in rows if row["execution_id"] == execution_id),
            None,
        )

    def list_for_plan(self, plan_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._read_state()["executions"]
        return copy.deepcopy([row for row in rows if row["plan_id"] == plan_id])

    def update(self, execution_id: str, **fields: Any) -> dict[str, Any]:
        status = fields.get("status")
        if status is not None and status not in EXECUTION_STATUSES:
            raise ValueError(f"Unknown execution status {status!r}")
        timestamp = datetime.now(UTC).isoformat()
        with self._lock:
            for _ in range(3):
                state = self._read_state()
                executions = state["executions"]
                index = next(
                    (i for i, row in enumerate(executions) if row["execution_id"] == execution_id),
                    None,
                )
                if index is None:
                    raise ValueError(f"Unknown execution id {execution_id!r}")
                record = dict(executions[index])
                record.update(fields)
                record["updated_at"] = timestamp
                executions[index] = record
                state["revision"] += 1
                state["updated_at"] = timestamp
                try:
                    self._write_state(state, expected_revision=state["revision"] - 1)
                except DocumentConflictError:
                    continue
                return copy.deepcopy(record)
        raise DocumentConflictError("Remediation execution store changed during update")

    def _read_state(self) -> dict[str, Any]:
        if self._memory is not None:
            payload = self._memory
        elif self.document_store is not None:
            payload = self.document_store.read(self.document_name)
            if not payload:
                return _initial_state()
        elif self.path is not None:
            if not self.path.exists():
                return _initial_state()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Remediation execution state is not valid JSON") from exc
        else:
            return _initial_state()
        if not isinstance(payload, dict):
            raise TypeError("Remediation execution state must be an object")
        executions = payload.get("executions", [])
        if not isinstance(executions, list) or any(
            not isinstance(item, dict) for item in executions
        ):
            raise TypeError("Remediation execution executions must be a list of objects")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0)),
            "executions": [dict(item) for item in executions],
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _write_state(self, state: dict[str, Any], *, expected_revision: int) -> None:
        payload = {
            "schema_version": self._SCHEMA_VERSION,
            "revision": state["revision"],
            "executions": state["executions"],
            "updated_at": state["updated_at"],
        }
        if self.document_store is not None:
            self.document_store.write(
                self.document_name, payload, expected_revision=expected_revision
            )
            return
        if self.path is None:
            self._memory = payload
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _initial_state() -> dict[str, Any]:
    return {"revision": 0, "executions": [], "updated_at": ""}


def _nonnegative_int(value: Any) -> int:
    number = int(value or 0)
    if number < 0:
        raise ValueError("Remediation execution revision must be non-negative")
    return number


__all__ = [
    "EXECUTION_STATUSES",
    "EXECUTION_STATUS_CANCELLED",
    "EXECUTION_STATUS_FAILED",
    "EXECUTION_STATUS_QUEUED",
    "EXECUTION_STATUS_RETRYING",
    "EXECUTION_STATUS_RUNNING",
    "EXECUTION_STATUS_SUCCEEDED",
    "EXECUTION_TERMINAL_STATUSES",
    "RemediationExecutionStore",
]
