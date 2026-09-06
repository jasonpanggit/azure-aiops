"""Atomic durable run ledger for autonomous ontology discovery."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from storage.locking import RunLock

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_RETRYING = "retrying"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({RUN_SUCCEEDED, RUN_FAILED, RUN_CANCELLED})
CLAIMABLE_STATUSES = frozenset({RUN_QUEUED, RUN_RETRYING})
TRIGGERS = frozenset({"initial", "manual", "scheduled"})
RUN_LOCK_DOCUMENT = "ontology_discovery_runs.lock"


class RunClaimConflict(RuntimeError):
    """A status/revision compare-and-set did not match durable state."""

    def __init__(self, reason: str, record: Mapping[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.record = copy.deepcopy(dict(record))


class RunLeaseLost(RuntimeError):
    """A stale or cancelled worker attempted a consequential transition."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("ontology_discovery_lease_lost")
        self.record = copy.deepcopy(dict(record))


class RunDeadlineExceeded(RuntimeError):
    """A claimed run crossed its durable deadline."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("ontology_discovery_deadline_exceeded")
        self.record = copy.deepcopy(dict(record))


class OntologyRunStore:
    """Versioned run records with deterministic identity and fenced ownership."""

    SCHEMA_VERSION = "1.0.0"

    def __init__(
        self,
        path: str | Path,
        *,
        max_runs: int = 5000,
        max_attempts: int = 3,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 300,
        default_deadline_seconds: int = 1800,
    ) -> None:
        for name, value in {
            "max_runs": max_runs,
            "max_attempts": max_attempts,
            "retry_base_seconds": retry_base_seconds,
            "retry_max_seconds": retry_max_seconds,
            "default_deadline_seconds": default_deadline_seconds,
        }.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.path = Path(path)
        self.max_runs = max_runs
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.default_deadline_seconds = default_deadline_seconds
        self._lock = threading.RLock()

    def get_or_create_run(
        self,
        *,
        connection_id: str,
        source_generation_id: str,
        trigger: str,
        requested_by: str,
        deadline_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Converge all triggers for one connection/source generation."""
        moment = _aware(now)
        connection = _required(connection_id, "connection_id").casefold()
        generation = _required(source_generation_id, "source_generation_id")
        requested = _required(requested_by, "requested_by")
        normalized_trigger = _required(trigger, "trigger").casefold()
        if normalized_trigger not in TRIGGERS:
            raise ValueError("trigger must be initial, manual, or scheduled")
        identity = f"{connection}|{generation}"
        run_id = "ODR-" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper()
        deadline = deadline_at or moment + timedelta(seconds=self.default_deadline_seconds)
        deadline = _aware(deadline)
        if deadline <= moment:
            raise ValueError("deadline_at must be in the future")

        with self._claim_lock():
            state = self._read_state()
            existing = next(
                (
                    row
                    for row in state["runs"]
                    if str(row.get("run_identity") or "") == identity
                    or str(row.get("run_id") or "") == run_id
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing), False
            if len(state["runs"]) >= self.max_runs:
                raise ValueError("Ontology discovery run store is full")
            timestamp = moment.isoformat()
            record = {
                "run_id": run_id,
                "run_identity": identity,
                "connection_id": connection,
                "source_generation_id": generation,
                "trigger": normalized_trigger,
                "requested_by": requested,
                "status": RUN_QUEUED,
                "revision": 0,
                "attempt_count": 0,
                "max_attempts": self.max_attempts,
                "created_at": timestamp,
                "updated_at": timestamp,
                "deadline_at": deadline.isoformat(),
                "next_attempt_at": timestamp,
                "lease_owner": "",
                "lease_expires_at": "",
                "fencing_token": 0,
                "cancel_requested": False,
                "checkpoint": {"name": RUN_QUEUED, "payload": {}},
                "failure_class": "",
                "message": "",
                "metadata": copy.deepcopy(dict(metadata or {})),
                "history": [
                    _event(
                        run_id=run_id,
                        sequence=1,
                        status=RUN_QUEUED,
                        actor=requested,
                        timestamp=timestamp,
                        checkpoint=RUN_QUEUED,
                    )
                ],
            }
            state["runs"].append(record)
            self._persist_advanced(state, moment)
            return copy.deepcopy(record), True

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read_state()["runs"]
        return next(
            (copy.deepcopy(row) for row in rows if row["run_id"] == run_id),
            None,
        )

    def list_due(
        self, *, now: datetime | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        moment = _aware(now)
        with self._lock:
            rows = self._read_state()["runs"]
        due = [row for row in rows if _is_due(row, moment)]
        due.sort(
            key=lambda row: (
                str(row.get("next_attempt_at") or ""),
                str(row.get("created_at") or ""),
            )
        )
        return copy.deepcopy(due[:limit])

    def claim(
        self,
        run_id: str,
        *,
        expected_revision: int,
        owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise TypeError("lease_seconds must be an integer")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        worker = _required(owner, "owner")
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            expired_running = record["status"] == RUN_RUNNING and _lease_expired(
                record, moment
            )
            if (
                record["revision"] != expected_revision
                or (record["status"] not in CLAIMABLE_STATUSES and not expired_running)
                or record["cancel_requested"]
                or record["attempt_count"] >= record["max_attempts"]
            ):
                raise RunClaimConflict("run_claim_conflict", record)
            state["next_fencing_token"] += 1
            record["attempt_count"] += 1
            record["lease_owner"] = worker
            record["lease_expires_at"] = (
                moment + timedelta(seconds=lease_seconds)
            ).isoformat()
            record["fencing_token"] = state["next_fencing_token"]
            record["next_attempt_at"] = ""
            record["failure_class"] = ""
            record["message"] = ""
            self._replace_record(
                state,
                index,
                record,
                status=RUN_RUNNING,
                actor=worker,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                message="Run claimed",
            )
            return copy.deepcopy(record)

    def checkpoint(
        self,
        run_id: str,
        *,
        expected_revision: int,
        owner: str,
        fencing_token: int,
        name: str,
        payload: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        checkpoint_name = _required(name, "name")
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            self._assert_owned(
                state,
                index,
                record,
                owner=owner,
                fencing_token=fencing_token,
                moment=moment,
            )
            if record["revision"] != expected_revision:
                raise RunClaimConflict("run_revision_conflict", record)
            record["checkpoint"] = {
                "name": checkpoint_name,
                "payload": copy.deepcopy(dict(payload or {})),
            }
            self._replace_record(
                state,
                index,
                record,
                status=RUN_RUNNING,
                actor=owner,
                moment=moment,
                checkpoint=checkpoint_name,
                message="Checkpoint persisted",
            )
            return copy.deepcopy(record)

    def succeed(
        self,
        run_id: str,
        *,
        expected_revision: int,
        owner: str,
        fencing_token: int,
        checkpoint: str,
        payload: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            self._assert_owned(
                state,
                index,
                record,
                owner=owner,
                fencing_token=fencing_token,
                moment=moment,
            )
            if record["revision"] != expected_revision:
                raise RunClaimConflict("run_revision_conflict", record)
            record["checkpoint"] = {
                "name": _required(checkpoint, "checkpoint"),
                "payload": copy.deepcopy(dict(payload or {})),
            }
            _clear_lease(record)
            self._replace_record(
                state,
                index,
                record,
                status=RUN_SUCCEEDED,
                actor=owner,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                message="Run completed",
            )
            return copy.deepcopy(record)

    def fail(
        self,
        run_id: str,
        *,
        expected_revision: int,
        owner: str,
        fencing_token: int,
        failure_class: str,
        message: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            self._assert_owned(
                state,
                index,
                record,
                owner=owner,
                fencing_token=fencing_token,
                moment=moment,
            )
            if record["revision"] != expected_revision:
                raise RunClaimConflict("run_revision_conflict", record)
            can_retry = (
                record["attempt_count"] < record["max_attempts"]
                and moment < _parse_timestamp(record["deadline_at"])
            )
            status = RUN_RETRYING if can_retry else RUN_FAILED
            if can_retry:
                delay = min(
                    self.retry_base_seconds * (2 ** (record["attempt_count"] - 1)),
                    self.retry_max_seconds,
                )
                record["next_attempt_at"] = (moment + timedelta(seconds=delay)).isoformat()
            else:
                record["next_attempt_at"] = ""
            record["failure_class"] = (
                _bounded(failure_class, 128) if can_retry else "attempts_exhausted"
            )
            record["message"] = _bounded(message, 1024)
            _clear_lease(record)
            self._replace_record(
                state,
                index,
                record,
                status=status,
                actor=owner,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                failure_class=record["failure_class"],
                message=record["message"],
            )
            return copy.deepcopy(record)

    def expire(
        self,
        run_id: str,
        *,
        expected_revision: int,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            if record["revision"] != expected_revision or record["status"] in TERMINAL_STATUSES:
                raise RunClaimConflict("run_revision_conflict", record)
            if moment < _parse_timestamp(record["deadline_at"]):
                raise RunClaimConflict("run_deadline_not_reached", record)
            record["failure_class"] = "deadline_exceeded"
            record["message"] = "Run deadline exceeded before completion"
            record["next_attempt_at"] = ""
            _clear_lease(record)
            self._replace_record(
                state,
                index,
                record,
                status=RUN_FAILED,
                actor=actor,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                failure_class="deadline_exceeded",
                message=record["message"],
            )
            return copy.deepcopy(record)

    def request_cancel(
        self,
        run_id: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            if record["revision"] != expected_revision or record["status"] in TERMINAL_STATUSES:
                raise RunClaimConflict("run_cancel_conflict", record)
            state["next_fencing_token"] += 1
            record["fencing_token"] = state["next_fencing_token"]
            record["cancel_requested"] = True
            record["failure_class"] = "cancelled"
            record["message"] = _bounded(reason or "Run cancelled", 1024)
            record["next_attempt_at"] = ""
            _clear_lease(record)
            self._replace_record(
                state,
                index,
                record,
                status=RUN_CANCELLED,
                actor=actor,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                failure_class="cancelled",
                message=record["message"],
            )
            return copy.deepcopy(record)

    def _assert_owned(
        self,
        state: dict[str, Any],
        index: int,
        record: dict[str, Any],
        *,
        owner: str,
        fencing_token: int,
        moment: datetime,
    ) -> None:
        owned = (
            record["status"] == RUN_RUNNING
            and record["lease_owner"] == owner
            and record["fencing_token"] == fencing_token
            and not _lease_expired(record, moment)
            and not record["cancel_requested"]
        )
        if not owned:
            self._append_event(
                state,
                index,
                record,
                actor=owner,
                moment=moment,
                failure_class="lease_lost",
                message="Stale worker transition rejected",
                consequential=False,
            )
            raise RunLeaseLost(record)
        if moment >= _parse_timestamp(record["deadline_at"]):
            record["failure_class"] = "deadline_exceeded"
            record["message"] = "Run deadline exceeded before completion"
            _clear_lease(record)
            self._replace_record(
                state,
                index,
                record,
                status=RUN_FAILED,
                actor=owner,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                failure_class="deadline_exceeded",
                message=record["message"],
            )
            raise RunDeadlineExceeded(record)

    def _append_event(
        self,
        state: dict[str, Any],
        index: int,
        record: dict[str, Any],
        *,
        actor: str,
        moment: datetime,
        failure_class: str = "",
        message: str = "",
        consequential: bool = True,
    ) -> None:
        timestamp = moment.isoformat()
        record["history"].append(
            _event(
                run_id=record["run_id"],
                sequence=len(record["history"]) + 1,
                status=record["status"],
                actor=actor,
                timestamp=timestamp,
                checkpoint=record["checkpoint"]["name"],
                failure_class=failure_class,
                message=message,
                consequential=consequential,
            )
        )
        record["revision"] += 1
        record["updated_at"] = timestamp
        state["runs"][index] = record
        self._persist_advanced(state, moment)

    def _replace_record(
        self,
        state: dict[str, Any],
        index: int,
        record: dict[str, Any],
        *,
        status: str,
        actor: str,
        moment: datetime,
        checkpoint: str,
        failure_class: str = "",
        message: str = "",
    ) -> None:
        record["status"] = status
        self._append_event(
            state,
            index,
            record,
            actor=actor,
            moment=moment,
            failure_class=failure_class,
            message=message,
        )

    def _locate(
        self, run_id: str
    ) -> tuple[dict[str, Any], int, dict[str, Any]]:
        state = self._read_state()
        index = next(
            (
                position
                for position, row in enumerate(state["runs"])
                if row["run_id"] == run_id
            ),
            None,
        )
        if index is None:
            raise ValueError(f"Unknown ontology discovery run {run_id!r}")
        return state, index, copy.deepcopy(state["runs"][index])

    @contextmanager
    def _claim_lock(self) -> Iterator[None]:
        with self._lock:
            deadline = time.monotonic() + 5.0
            while True:
                lock = RunLock(
                    self.path.parent,
                    lock_document=f".{self.path.name}.lock",
                )
                try:
                    lock.__enter__()
                except RuntimeError as exc:
                    if time.monotonic() >= deadline:
                        raise RunClaimConflict("run_store_lock_contended", {}) from exc
                    time.sleep(0.01)
                    continue
                try:
                    yield
                finally:
                    lock.__exit__(None, None, None)
                return

    def _read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return _initial_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Ontology discovery run state is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TypeError("Ontology discovery run state must be an object")
        rows = payload.get("runs", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TypeError("Ontology discovery runs must be a list of objects")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0)),
            "next_fencing_token": _nonnegative_int(
                payload.get("next_fencing_token", 0)
            ),
            "runs": [_with_defaults(row, self.max_attempts) for row in rows],
            "updated_at": str(payload.get("updated_at") or ""),
        }

    def _persist_advanced(self, state: dict[str, Any], moment: datetime) -> None:
        expected_revision = state["revision"]
        state["revision"] += 1
        state["updated_at"] = moment.isoformat()
        self._write_state(state, expected_revision=expected_revision)

    def _write_state(self, state: dict[str, Any], *, expected_revision: int) -> None:
        if self.path.exists():
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Ontology discovery run state is not valid JSON") from exc
            observed_revision = _nonnegative_int(current.get("revision", 0))
            if observed_revision != expected_revision:
                raise RunClaimConflict("run_store_revision_conflict", {})
        elif expected_revision != 0:
            raise RunClaimConflict("run_store_revision_conflict", {})
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "revision": state["revision"],
            "next_fencing_token": state["next_fencing_token"],
            "runs": state["runs"],
            "updated_at": state["updated_at"],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _initial_state() -> dict[str, Any]:
    return {
        "revision": 0,
        "next_fencing_token": 0,
        "runs": [],
        "updated_at": "",
    }


def _with_defaults(row: Mapping[str, Any], default_max_attempts: int) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    connection = str(record.get("connection_id") or "").strip().casefold()
    generation = str(record.get("source_generation_id") or "").strip()
    record.setdefault("run_id", "")
    record.setdefault("run_identity", f"{connection}|{generation}")
    record["connection_id"] = connection
    record["source_generation_id"] = generation
    record.setdefault("trigger", "scheduled")
    record.setdefault("requested_by", "")
    record.setdefault("status", RUN_QUEUED)
    record["revision"] = _nonnegative_int(record.get("revision", 0))
    record["attempt_count"] = _nonnegative_int(record.get("attempt_count", 0))
    record["max_attempts"] = max(
        1, _nonnegative_int(record.get("max_attempts", default_max_attempts))
    )
    record.setdefault("created_at", "")
    record.setdefault("updated_at", "")
    record.setdefault("deadline_at", "9999-12-31T23:59:59+00:00")
    record.setdefault("next_attempt_at", "")
    record.setdefault("lease_owner", "")
    record.setdefault("lease_expires_at", "")
    record["fencing_token"] = _nonnegative_int(record.get("fencing_token", 0))
    record.setdefault("cancel_requested", False)
    checkpoint = record.get("checkpoint")
    if not isinstance(checkpoint, dict):
        checkpoint = {}
    payload = checkpoint.get("payload")
    record["checkpoint"] = {
        "name": str(checkpoint.get("name") or RUN_QUEUED),
        "payload": copy.deepcopy(payload) if isinstance(payload, dict) else {},
    }
    record.setdefault("failure_class", "")
    record.setdefault("message", "")
    metadata = record.get("metadata")
    record["metadata"] = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    history = record.get("history")
    record["history"] = copy.deepcopy(history) if isinstance(history, list) else []
    return record


def _is_due(record: Mapping[str, Any], moment: datetime) -> bool:
    status = str(record.get("status") or "")
    if status in TERMINAL_STATUSES or bool(record.get("cancel_requested")):
        return False
    if status == RUN_RUNNING:
        return _lease_expired(record, moment)
    if status not in CLAIMABLE_STATUSES:
        return False
    next_attempt = str(record.get("next_attempt_at") or "")
    return not next_attempt or _parse_timestamp(next_attempt) <= moment


def _lease_expired(record: Mapping[str, Any], moment: datetime) -> bool:
    expires = str(record.get("lease_expires_at") or "")
    return not expires or _parse_timestamp(expires) <= moment


def _clear_lease(record: dict[str, Any]) -> None:
    record["lease_owner"] = ""
    record["lease_expires_at"] = ""


def _event(
    *,
    run_id: str,
    sequence: int,
    status: str,
    actor: str,
    timestamp: str,
    checkpoint: str,
    failure_class: str = "",
    message: str = "",
    consequential: bool = True,
) -> dict[str, Any]:
    return {
        "event_id": f"{run_id}:{sequence}",
        "sequence": sequence,
        "status": status,
        "actor": actor,
        "timestamp": timestamp,
        "checkpoint": checkpoint,
        "failure_class": failure_class,
        "message": message,
        "consequential": consequential,
    }


def _required(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _bounded(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _aware(value: datetime | None) -> datetime:
    moment = value or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Ontology discovery timestamp is invalid") from exc
    return _aware(parsed)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CLAIMABLE_STATUSES",
    "RUN_CANCELLED",
    "RUN_FAILED",
    "RUN_QUEUED",
    "RUN_RETRYING",
    "RUN_RUNNING",
    "RUN_SUCCEEDED",
    "TERMINAL_STATUSES",
    "OntologyRunStore",
    "RunClaimConflict",
    "RunDeadlineExceeded",
    "RunLeaseLost",
]
