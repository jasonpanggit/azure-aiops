"""Durable, atomic remediation execution lifecycle storage.

Azure's patch APIs do not expose an idempotency token.  A durable claim made
before submission is therefore the side-effect safety boundary: after a claim
is persisted, a process crash leaves an observable active attempt and no
caller may automatically submit it again.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.locking import RunLock

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
EXECUTION_TERMINAL_STATUSES = frozenset(
    {EXECUTION_STATUS_SUCCEEDED, EXECUTION_STATUS_FAILED, EXECUTION_STATUS_CANCELLED}
)
RETRYABLE_STATUSES = frozenset({EXECUTION_STATUS_FAILED, EXECUTION_STATUS_CANCELLED})
EXECUTION_LOCK_DOCUMENT = "state/remediation_execution.lock"


class ExecutionClaimConflict(RuntimeError):
    """A compare-and-set lifecycle claim lost to another caller."""

    def __init__(self, reason: str, record: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.record = copy.deepcopy(record)


class RemediationExecutionStore:
    """Revisioned execution records with cross-process claim serialization."""

    _SCHEMA_VERSION = "2.0.0"

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
        self._lock_root = self._resolve_lock_root()

    def create_or_get(
        self,
        plan_id: str,
        *,
        requested_by: str,
        approved_by: str,
        execution_snapshot: dict[str, Any],
        rollback_guidance: list[str] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim the permanent identity for one approved snapshot."""
        timestamp = _timestamp(now)
        identity = _execution_identity(plan_id, execution_snapshot)
        with self._claim_lock():
            state = self._read_state()
            existing = next(
                (
                    row
                    for row in state["executions"]
                    if str(row.get("execution_identity") or "") == identity
                    or (
                        not row.get("execution_identity")
                        and str(row.get("plan_id") or "") == str(plan_id)
                    )
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing), False
            if len(state["executions"]) >= self.max_executions:
                raise ValueError("Remediation execution store is full")
            snapshot = copy.deepcopy(execution_snapshot)
            attempt = _new_attempt(
                number=1,
                actor=requested_by,
                timestamp=timestamp,
                snapshot=snapshot,
            )
            record = {
                "execution_id": "RME-" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper(),
                "execution_identity": identity,
                "plan_id": str(plan_id),
                "status": EXECUTION_STATUS_QUEUED,
                "revision": 0,
                "requested_by": requested_by,
                "approved_by": approved_by,
                "created_at": timestamp,
                "updated_at": timestamp,
                "provider_job_id": "",
                "message": "",
                "attempt_count": 1,
                "rollback_guidance": list(rollback_guidance or []),
                "verified_state": "",
                "failure_details": "",
                "ineligibility_reason": "",
                "execution_snapshot": snapshot,
                "attempts": [attempt],
                "history": copy.deepcopy(attempt["transitions"]),
            }
            state["executions"].append(record)
            self._persist_advanced(state, timestamp)
            return copy.deepcopy(record), True

    def create(
        self, plan_id: str, *, requested_by: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Backward-compatible creation for records without an approval snapshot."""
        record, _ = self.create_or_get(
            plan_id,
            requested_by=requested_by,
            approved_by="",
            execution_snapshot={
                "target_id": "",
                "patch_ids": [],
                "target_kind": "",
                "operation": "",
                "action_version": "",
                "snapshot_hash": "",
            },
            now=now,
        )
        return record

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

    def claim_retry(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        actor: str,
        max_attempts: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Claim one failed/cancelled attempt using status-and-revision CAS."""
        timestamp = _timestamp(now)
        with self._claim_lock():
            state, index, record = self._locate(execution_id)
            if (
                int(record.get("revision") or 0) != expected_revision
                or record.get("status") not in RETRYABLE_STATUSES
            ):
                raise ExecutionClaimConflict("execution_claim_conflict", record)
            if int(record.get("attempt_count") or 0) >= max_attempts:
                raise ExecutionClaimConflict("max_attempts_exceeded", record)
            snapshot = copy.deepcopy(record.get("execution_snapshot") or {})
            number = int(record.get("attempt_count") or 0) + 1
            attempt = _new_attempt(
                number=number,
                actor=actor,
                timestamp=timestamp,
                snapshot=snapshot,
                status=EXECUTION_STATUS_RETRYING,
            )
            record["attempt_count"] = number
            record["ineligibility_reason"] = ""
            record.setdefault("attempts", []).append(attempt)
            record.setdefault("history", []).extend(copy.deepcopy(attempt["transitions"]))
            self._replace_record(
                state,
                index,
                record,
                timestamp=timestamp,
                status=EXECUTION_STATUS_RETRYING,
            )
            return copy.deepcopy(record)

    def claim_cancel(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically cancel work that is still queued and unsubmitted."""
        with self._claim_lock():
            state, index, record = self._locate(execution_id)
            if (
                int(record.get("revision") or 0) != expected_revision
                or record.get("status") != EXECUTION_STATUS_QUEUED
                or bool(record.get("provider_job_id"))
            ):
                raise ExecutionClaimConflict("execution_claim_conflict", record)
            return self._transition_locked(
                state,
                index,
                record,
                status=EXECUTION_STATUS_CANCELLED,
                actor=actor,
                outcome=EXECUTION_STATUS_CANCELLED,
                failure_details="Cancelled before provider submission",
                now=now,
            )

    def transition(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        expected_status: str | set[str] | frozenset[str],
        status: str,
        actor: str,
        now: datetime | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Append an immutable transition after a status-and-revision CAS."""
        expected = (
            {expected_status} if isinstance(expected_status, str) else set(expected_status)
        )
        with self._claim_lock():
            state, index, record = self._locate(execution_id)
            if (
                int(record.get("revision") or 0) != expected_revision
                or record.get("status") not in expected
            ):
                raise ExecutionClaimConflict("execution_claim_conflict", record)
            return self._transition_locked(
                state,
                index,
                record,
                status=status,
                actor=actor,
                now=now,
                **fields,
            )

    def update(self, execution_id: str, **fields: Any) -> dict[str, Any]:
        """Compatibility update that still appends an immutable transition."""
        with self._claim_lock():
            state, index, record = self._locate(execution_id)
            status = str(fields.pop("status", record.get("status") or ""))
            return self._transition_locked(
                state,
                index,
                record,
                status=status,
                actor=str(fields.pop("actor", record.get("requested_by") or "")),
                **fields,
            )

    def _transition_locked(
        self,
        state: dict[str, Any],
        index: int,
        record: dict[str, Any],
        *,
        status: str,
        actor: str,
        now: datetime | None = None,
        outcome: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        if status not in EXECUTION_STATUSES:
            raise ValueError(f"Unknown execution status {status!r}")
        timestamp = _timestamp(now)
        previous_status = str(record.get("status") or "")
        record.update(fields)
        record["status"] = status
        if status != previous_status and "ineligibility_reason" not in fields:
            record["ineligibility_reason"] = ""
        if outcome:
            record["outcome"] = outcome
        current = _current_attempt(record)
        for name in (
            "provider_job_id",
            "verified_state",
            "failure_details",
            "message",
        ):
            if name in fields:
                current[name] = copy.deepcopy(fields[name])
        current["status"] = status
        if outcome:
            current["outcome"] = outcome
        elif status in EXECUTION_TERMINAL_STATUSES:
            current["outcome"] = status
        event = _event(
            sequence=len(record.setdefault("history", [])) + 1,
            status=status,
            actor=actor,
            timestamp=timestamp,
            provider_job_id=str(record.get("provider_job_id") or ""),
            verified_state=str(record.get("verified_state") or ""),
            failure_details=str(record.get("failure_details") or ""),
            outcome=str(current.get("outcome") or ""),
            message=str(record.get("message") or ""),
        )
        record["history"].append(event)
        current.setdefault("transitions", []).append(copy.deepcopy(event))
        self._replace_record(state, index, record, timestamp=timestamp, status=status)
        return copy.deepcopy(record)

    def _replace_record(
        self,
        state: dict[str, Any],
        index: int,
        record: dict[str, Any],
        *,
        timestamp: str,
        status: str,
    ) -> None:
        record["status"] = status
        record["revision"] = int(record.get("revision") or 0) + 1
        record["updated_at"] = timestamp
        state["executions"][index] = record
        self._persist_advanced(state, timestamp)

    def _locate(
        self, execution_id: str
    ) -> tuple[dict[str, Any], int, dict[str, Any]]:
        state = self._read_state()
        index = next(
            (
                position
                for position, row in enumerate(state["executions"])
                if row["execution_id"] == execution_id
            ),
            None,
        )
        if index is None:
            raise ValueError(f"Unknown execution id {execution_id!r}")
        return state, index, copy.deepcopy(state["executions"][index])

    def _persist_advanced(self, state: dict[str, Any], timestamp: str) -> None:
        expected_revision = state["revision"]
        state["revision"] += 1
        state["updated_at"] = timestamp
        self._write_state(state, expected_revision=expected_revision)

    @contextmanager
    def _claim_lock(self) -> Iterator[None]:
        with self._lock:
            if self._lock_root is None:
                yield
                return
            deadline = time.monotonic() + 5.0
            while True:
                lock = RunLock(
                    self._lock_root,
                    lock_document=EXECUTION_LOCK_DOCUMENT,
                )
                try:
                    lock.__enter__()
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
                    continue
                try:
                    yield
                finally:
                    lock.__exit__(None, None, None)
                return

    def _resolve_lock_root(self) -> Path | str | None:
        if self.path is not None:
            parent = self.path.parent
            return parent.parent if parent.name == "state" else parent
        root = getattr(self.document_store, "root", None)
        return str(root) if root else None

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
            "executions": [_with_defaults(item) for item in executions],
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


def _execution_identity(plan_id: str, snapshot: dict[str, Any]) -> str:
    return "|".join(
        (
            str(plan_id),
            str(snapshot.get("snapshot_hash") or ""),
            str(snapshot.get("action_version") or ""),
        )
    )


def _new_attempt(
    *,
    number: int,
    actor: str,
    timestamp: str,
    snapshot: dict[str, Any],
    status: str = EXECUTION_STATUS_QUEUED,
) -> dict[str, Any]:
    transition = _event(
        sequence=1,
        status=status,
        actor=actor,
        timestamp=timestamp,
    )
    return {
        "attempt_number": number,
        "actor": actor,
        "created_at": timestamp,
        "target_id": str(snapshot.get("target_id") or ""),
        "patch_ids": list(snapshot.get("patch_ids") or []),
        "action_version": str(snapshot.get("action_version") or ""),
        "snapshot_hash": str(snapshot.get("snapshot_hash") or ""),
        "status": status,
        "provider_job_id": "",
        "verified_state": "",
        "failure_details": "",
        "message": "",
        "outcome": "",
        "transitions": [transition],
    }


def _event(
    *,
    sequence: int,
    status: str,
    actor: str,
    timestamp: str,
    provider_job_id: str = "",
    verified_state: str = "",
    failure_details: str = "",
    outcome: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "timestamp": timestamp,
        "status": status,
        "actor": actor,
        "provider_job_id": provider_job_id,
        "verified_state": verified_state,
        "failure_details": failure_details,
        "outcome": outcome,
        "message": message,
    }


def _current_attempt(record: dict[str, Any]) -> dict[str, Any]:
    attempts = record.setdefault("attempts", [])
    if not attempts:
        attempts.append(
            _new_attempt(
                number=max(1, int(record.get("attempt_count") or 1)),
                actor=str(record.get("requested_by") or ""),
                timestamp=str(record.get("created_at") or _timestamp()),
                snapshot=record.get("execution_snapshot") or {},
                status=str(record.get("status") or EXECUTION_STATUS_QUEUED),
            )
        )
    return attempts[-1]


def _with_defaults(item: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(item)
    record.setdefault("revision", 0)
    record.setdefault("execution_identity", "")
    record.setdefault("execution_snapshot", {})
    record.setdefault("attempts", [])
    record.setdefault("history", [])
    record.setdefault("ineligibility_reason", "")
    record.setdefault("verified_state", "")
    record.setdefault("failure_details", "")
    record.setdefault("provider_job_id", "")
    record.setdefault("message", "")
    record.setdefault("rollback_guidance", [])
    record.setdefault("attempt_count", 1)
    return record


def _timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat()


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
    "ExecutionClaimConflict",
    "RemediationExecutionStore",
]
