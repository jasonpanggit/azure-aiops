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


class ExecutionLockContended(RuntimeError):
    """The cross-replica claim lock stayed busy for the full retry window.

    WR-04: distinct from a genuine defect in verification logic -- under
    legitimate multi-replica load, another worker's own claim can hold the
    lock long enough that this caller's bounded retry window (5s) elapses
    first. This is expected, transient, and will resolve on its own on the
    coordinator's next pass; a caller (e.g.
    :class:`~intelligence.remediation.verification_coordinator
    .RemediationVerificationCoordinator`) should count it separately from an
    unexpected error rather than logging/counting it identically to one.
    """


class RemediationExecutionStore:
    """Revisioned execution records with cross-process claim serialization."""

    _SCHEMA_VERSION = "2.4.0"

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
        approval_decision_id: str = "",
        rollback_guidance: list[str] | None = None,
        scope_attributes: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim one approval-scoped execution identity."""
        timestamp = _timestamp(now)
        decision_id = str(approval_decision_id or "").strip()
        identity = _execution_identity(
            plan_id,
            execution_snapshot,
            approval_decision_id=decision_id,
        )
        with self._claim_lock():
            state = self._read_state()
            existing = next(
                (
                    row
                    for row in state["executions"]
                    if str(row.get("execution_identity") or "") == identity
                    or (
                        not decision_id
                        and not row.get("execution_identity")
                        and str(row.get("plan_id") or "") == str(plan_id)
                    )
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing), False
            related = next(
                (
                    row
                    for row in state["executions"]
                    if _same_approved_snapshot(row, plan_id, execution_snapshot)
                    and _blocks_new_approval_execution(row)
                ),
                None,
            )
            if related is not None:
                return copy.deepcopy(related), False
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
                "approval_decision_id": decision_id,
                "plan_id": str(plan_id),
                "status": EXECUTION_STATUS_QUEUED,
                "revision": 0,
                "requested_by": requested_by,
                "approved_by": approved_by,
                "created_at": timestamp,
                "updated_at": timestamp,
                "provider": "",
                "provider_job_id": "",
                "message": "",
                "attempt_count": 1,
                "rollback_guidance": list(rollback_guidance or []),
                "verified_state": "",
                "failure_details": "",
                "ineligibility_reason": "",
                "provider_submitted": False,
                "failure_class": "",
                "supersedes": "",
                "superseded_by": "",
                "superseded_reason": "",
                "verification_deadline_at": "",
                "next_verification_at": "",
                "verification_attempts": 0,
                "verification_evidence": {},
                "evidence_reconciliation": _empty_evidence_reconciliation(),
                "execution_snapshot": snapshot,
                "scope_attributes": dict(scope_attributes or {}),
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

    def create_superseding(
        self,
        old_execution_id: str,
        *,
        expected_revision: int,
        plan_id: str,
        requested_by: str,
        approved_by: str,
        execution_snapshot: dict[str, Any],
        approval_decision_id: str = "",
        rollback_guidance: list[str] | None = None,
        scope_attributes: dict[str, str] | None = None,
        reason: str,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically mint a replacement execution and close out the old one.

        Under one lock, in one write: (1) CAS-validates ``old_execution_id``
        is still supersede-eligible (terminal ``failed``/``cancelled`` and
        not already superseded) at ``expected_revision``; (2) creates a
        brand-new execution record with its own fresh identity (never
        colliding with the old one, even for a byte-identical snapshot,
        because the identity is salted with ``old_execution_id``) carrying
        ``supersedes=old_execution_id``; (3) sets ``superseded_by``/
        ``superseded_reason`` on the OLD record in place, without touching
        its ``attempts``/``history``. Never mutates or deletes the old
        execution's audit trail (Supersession decision).
        """
        timestamp = _timestamp(now)
        with self._claim_lock():
            state, old_index, old_record = self._locate(old_execution_id)
            if (
                int(old_record.get("revision") or 0) != expected_revision
                or old_record.get("status") not in RETRYABLE_STATUSES
                or old_record.get("superseded_by")
            ):
                raise ExecutionClaimConflict("execution_claim_conflict", old_record)
            if len(state["executions"]) >= self.max_executions:
                # Same store-growth cap `create_or_get` already enforces
                # (WR-01): a supersede always appends a brand-new record, so
                # without this guard the cap could be defeated by repeatedly
                # exhausting and superseding distinct executions.
                raise ExecutionClaimConflict("execution_store_full", old_record)

            snapshot = copy.deepcopy(execution_snapshot)
            decision_id = str(approval_decision_id or "").strip()
            identity = (
                _execution_identity(
                    plan_id,
                    snapshot,
                    approval_decision_id=decision_id,
                )
                + f"|supersedes:{old_execution_id}"
            )
            if any(
                str(row.get("execution_identity") or "") == identity
                for row in state["executions"]
            ):
                # An identity collision here would mean this exact
                # supersession was already minted -- refuse rather than
                # silently returning (or worse, overwriting) a different
                # caller's record.
                raise ExecutionClaimConflict("execution_claim_conflict", old_record)

            attempt = _new_attempt(
                number=1,
                actor=requested_by,
                timestamp=timestamp,
                snapshot=snapshot,
            )
            new_record = {
                "execution_id": "RME-" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper(),
                "execution_identity": identity,
                "approval_decision_id": decision_id,
                "plan_id": str(plan_id),
                "status": EXECUTION_STATUS_QUEUED,
                "revision": 0,
                "requested_by": requested_by,
                "approved_by": approved_by,
                "created_at": timestamp,
                "updated_at": timestamp,
                "provider": "",
                "provider_job_id": "",
                "message": "",
                "attempt_count": 1,
                "rollback_guidance": list(
                    rollback_guidance
                    if rollback_guidance is not None
                    else old_record.get("rollback_guidance") or []
                ),
                "verified_state": "",
                "failure_details": "",
                "ineligibility_reason": "",
                "provider_submitted": False,
                "failure_class": "",
                "execution_snapshot": snapshot,
                "scope_attributes": dict(scope_attributes or {}),
                "attempts": [attempt],
                "history": copy.deepcopy(attempt["transitions"]),
                "supersedes": old_execution_id,
                "superseded_by": "",
                "superseded_reason": "",
                "verification_deadline_at": "",
                "next_verification_at": "",
                "verification_attempts": 0,
                "verification_evidence": {},
                "evidence_reconciliation": _empty_evidence_reconciliation(),
            }
            state["executions"].append(new_record)

            old_record["superseded_by"] = new_record["execution_id"]
            old_record["superseded_reason"] = str(reason)
            old_record["revision"] = int(old_record.get("revision") or 0) + 1
            old_record["updated_at"] = timestamp
            state["executions"][old_index] = old_record

            self._persist_advanced(state, timestamp)
            return copy.deepcopy(new_record), copy.deepcopy(old_record)

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

    def list_all(self) -> list[dict[str, Any]]:
        """Every stored execution record, for read-only diagnostics."""
        with self._lock:
            rows = self._read_state()["executions"]
        return copy.deepcopy(rows)

    def list_due_for_verification(
        self, *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Every record needing a verification/reconciliation pass right now.

        Read-only: durable state alone answers "what is due" (Recommendation
        3's Verification Lifecycle decision), so a fresh process after a
        restart needs no in-memory scheduling state to resume this query.
        Uses the same lock as :meth:`get`/:meth:`list_all` -- no CAS claim is
        taken here since nothing is mutated.
        """
        moment = now or datetime.now(UTC)
        with self._lock:
            rows = self._read_state()["executions"]
        return copy.deepcopy([row for row in rows if _needs_verification_pass(row, now=moment)])

    def claim_retry(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        actor: str,
        max_attempts: int,
        now: datetime | None = None,
        verification_deadline_at: str = "",
        next_verification_at: str = "",
        verification_attempts: int = 0,
    ) -> dict[str, Any]:
        """Claim one failed/cancelled attempt using status-and-revision CAS.

        CR-01: the scheduling fields (when supplied by the caller) are
        seeded in this *same* CAS write that claims ``"retrying"`` -- not
        only in a later write -- so a crash between this claim and the
        following ``retrying -> running`` transition still leaves a
        durably-scheduled, due-for-recovery record rather than an
        undeadlined one invisible to :func:`_needs_verification_pass`.
        """
        timestamp = _timestamp(now)
        with self._claim_lock():
            state, index, record = self._locate(execution_id)
            if (
                int(record.get("revision") or 0) != expected_revision
                or record.get("status") not in RETRYABLE_STATUSES
            ):
                raise ExecutionClaimConflict("execution_claim_conflict", record)
            if submitted_attempt_count(record) >= max_attempts:
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
            record["outcome"] = ""
            record["provider"] = ""
            record["provider_job_id"] = ""
            record["verified_state"] = ""
            record["failure_details"] = ""
            record["message"] = ""
            record["provider_submitted"] = False
            record["failure_class"] = ""
            record["verification_evidence"] = {}
            record["verification_deadline_at"] = verification_deadline_at
            record["next_verification_at"] = next_verification_at
            record["verification_attempts"] = verification_attempts
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
            "provider",
            "provider_job_id",
            "verified_state",
            "failure_details",
            "message",
            "provider_submitted",
            "failure_class",
            "verification_evidence",
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
                except RuntimeError as exc:
                    if time.monotonic() >= deadline:
                        raise ExecutionLockContended(
                            "Timed out waiting for the remediation execution "
                            "claim lock; another replica is holding it."
                        ) from exc
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


def _execution_identity(
    plan_id: str,
    snapshot: dict[str, Any],
    *,
    approval_decision_id: str = "",
) -> str:
    identity = "|".join(
        (
            str(plan_id),
            str(snapshot.get("snapshot_hash") or ""),
            str(snapshot.get("action_version") or ""),
        )
    )
    decision_id = str(approval_decision_id or "")
    return f"{identity}|{decision_id}" if decision_id else identity


def _same_approved_snapshot(
    record: dict[str, Any],
    plan_id: str,
    snapshot: dict[str, Any],
) -> bool:
    current = record.get("execution_snapshot")
    return (
        isinstance(current, dict)
        and str(record.get("plan_id") or "") == str(plan_id)
        and str(current.get("snapshot_hash") or "")
        == str(snapshot.get("snapshot_hash") or "")
        and str(current.get("action_version") or "")
        == str(snapshot.get("action_version") or "")
    )


def _blocks_new_approval_execution(record: dict[str, Any]) -> bool:
    """Keep unsafe same-snapshot work from being replaced by a fresh approval."""
    if str(record.get("status") or "") in {"queued", "running", "retrying"}:
        return True
    return is_submission_ambiguous(record)


def _subscription_id_from_target_id(target_id: str) -> str:
    """Extract the subscription segment from a canonical ARM resource id.

    Duplicates ``semantic.live_operations._subscription_id_from_resource_id``
    rather than importing it: ``semantic`` already imports from
    ``intelligence.remediation``, so importing the reverse direction would be
    circular.
    """
    parts = [part for part in str(target_id or "").strip("/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "subscriptions":
            return parts[index + 1]
    return ""


def execution_scope_attributes(record: dict[str, Any]) -> dict[str, str]:
    """Project an execution record's own durable scope, independent of its plan.

    Authorization for a single execution read/retry/cancel must not depend on
    the originating plan's continued existence (D-02): a plan's identity can
    still change/disappear across evidence refresh for legacy records created
    before this field existed. Returns the stored ``scope_attributes`` when
    present; otherwise derives a subscription-only scope from the immutable
    execution snapshot's ``target_id``; otherwise returns an empty mapping,
    which fails closed for any restricted caller scope (D-02/D-04).
    """
    stored = record.get("scope_attributes")
    if isinstance(stored, dict) and stored:
        return {str(key): str(value) for key, value in stored.items()}
    snapshot = record.get("execution_snapshot")
    target_id = str((snapshot or {}).get("target_id") or "") if isinstance(snapshot, dict) else ""
    subscription_id = _subscription_id_from_target_id(target_id)
    if subscription_id:
        return {"subscription": subscription_id}
    return {}


def submitted_attempt_count(record: dict[str, Any]) -> int:
    """Count only attempts proven-or-ambiguous to have reached the provider.

    This is Phase 03.3's Recommendation 2 counter: a plain refusal that
    never touches Azure (validation, authorization, approval,
    target-precondition) must not consume the bounded retry budget, while a
    genuine submission -- even one that failed ambiguously in transport --
    must. Both :meth:`execution_view`'s ``remaining_attempts``/``retryable``
    projection and :meth:`claim_retry`'s own CAS gate call this single
    function so a caller cannot bypass the ceiling by reading a stale view.
    """
    return sum(
        1
        for attempt in record.get("attempts", [])
        if bool(attempt.get("provider_submitted"))
    )


def is_submission_ambiguous(record: dict[str, Any]) -> bool:
    """Whether the record's last attempt is a submission-ambiguous failure.

    A submission-ambiguous attempt may still be running against the
    provider (the transport failed after the mutating call may already have
    crossed the boundary), so it must never be treated as safely
    supersedable (Plan 03.3-03's supersede eligibility guard).
    """
    attempts = record.get("attempts") or []
    if not attempts:
        return False
    return str(attempts[-1].get("failure_class") or "") == "submission_ambiguous"


def is_manual_resolution_required(record: dict[str, Any]) -> bool:
    """Whether an SRE ambiguity exhausted automation and permits supersession."""
    return (
        str(record.get("provider") or "") == "sre-agent"
        and is_submission_ambiguous(record)
        and str(record.get("verified_state") or "")
        == "sre_agent_manual_resolution_required"
    )


_RECONCILED_TERMINAL_STATUSES = frozenset(
    {"reconciled_clean", "reconciled_incomplete", "unreconciled"}
)


def _is_patch_evidence_candidate(record: dict[str, Any]) -> bool:
    """Whether ``record`` has a KB-comparable patch selection to reconcile.

    Defender configuration executions and any record with an empty
    ``patch_ids`` selection have no comparable "did the KB disappear"
    evidence, so they are never eligible for KB-based evidence
    reconciliation. Shared by :meth:`RemediationExecutionStore
    .list_due_for_verification` and (Plan 03.4-02) the service layer's
    ``reconcile_evidence`` eligibility check so the two can never disagree.
    """
    snapshot = record.get("execution_snapshot")
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("snapshot_kind") == "defender_configuration":
        return False
    return bool(snapshot.get("patch_ids"))


def _needs_verification_pass(record: dict[str, Any], *, now: datetime) -> bool:
    """Whether ``record`` needs a verification/reconciliation pass right now.

    Durable-state-only decision (no in-memory scheduling carryover): a
    "running" or "retrying" record is due immediately if never scheduled,
    or once its ``next_verification_at`` has elapsed (CR-01: a "retrying"
    record is treated identically to "running" so a crash between
    ``claim_retry()`` and the following ``retrying -> running`` transition
    is still recoverable rather than permanently invisible); a "failed"
    record is due only while its last attempt is submission-ambiguous; a
    "succeeded" patch record is due until its evidence reconciliation
    reaches a terminal outcome.
    """
    status = str(record.get("status") or "")
    if status in (EXECUTION_STATUS_RUNNING, EXECUTION_STATUS_RETRYING):
        next_at = str(record.get("next_verification_at") or "").strip()
        if not next_at:
            return True
        try:
            parsed = datetime.fromisoformat(next_at)
        except ValueError:
            return True
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed <= now
    if status == EXECUTION_STATUS_FAILED:
        return is_submission_ambiguous(record) and not is_manual_resolution_required(
            record
        )
    if status == EXECUTION_STATUS_SUCCEEDED:
        if not _is_patch_evidence_candidate(record):
            return False
        reconciliation = record.get("evidence_reconciliation")
        recon_status = (
            str(reconciliation.get("status") or "")
            if isinstance(reconciliation, dict)
            else ""
        )
        return recon_status not in _RECONCILED_TERMINAL_STATUSES
    return False


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
        "provider": "",
        "provider_job_id": "",
        "verified_state": "",
        "failure_details": "",
        "message": "",
        "outcome": "",
        "provider_submitted": False,
        "failure_class": "",
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


_AMBIGUITY_MARKERS = ("unreachable", "timed out", "timeout", "connection", "ambiguous")


def _legacy_provider_submitted(attempt: dict[str, Any]) -> bool:
    """Conservative fail-closed default for a pre-migration attempt.

    Per CONTEXT.md's Compatibility and Safety decision: a recorded provider
    job ID proves submission; otherwise the attempt is treated as
    pre-submission unless its stored failure text carries an ambiguity
    marker, in which case it fails closed as submitted (never silently
    exempt, and never silently fully-submitted-only).
    """
    if "provider_submitted" in attempt:
        return bool(attempt["provider_submitted"])
    if str(attempt.get("provider_job_id") or "").strip():
        return True
    haystack = " ".join(
        str(attempt.get(field) or "").casefold()
        for field in ("failure_details", "message")
    )
    return any(marker in haystack for marker in _AMBIGUITY_MARKERS)


def _empty_evidence_reconciliation() -> dict[str, Any]:
    return {"status": "", "kbs_cleared": [], "kbs_remaining": [], "assessed_at": ""}


def _with_defaults(item: dict[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(item)
    record.setdefault("revision", 0)
    record.setdefault("execution_identity", "")
    record.setdefault("approval_decision_id", "")
    record.setdefault("execution_snapshot", {})
    record.setdefault("attempts", [])
    record.setdefault("history", [])
    record.setdefault("ineligibility_reason", "")
    record.setdefault("verified_state", "")
    record.setdefault("failure_details", "")
    record.setdefault("provider", "")
    record.setdefault("provider_job_id", "")
    record.setdefault("message", "")
    record.setdefault("rollback_guidance", [])
    record.setdefault("supersedes", "")
    record.setdefault("superseded_by", "")
    record.setdefault("superseded_reason", "")
    record.setdefault("attempt_count", 1)
    record.setdefault("verification_deadline_at", "")
    record.setdefault("next_verification_at", "")
    record.setdefault("verification_attempts", 0)
    record.setdefault("verification_evidence", {})
    record.setdefault("evidence_reconciliation", _empty_evidence_reconciliation())
    attempts = record["attempts"]
    for attempt in attempts:
        attempt.setdefault("provider", record["provider"])
        attempt["provider_submitted"] = _legacy_provider_submitted(attempt)
        attempt.setdefault("failure_class", "")
    record.setdefault(
        "provider_submitted",
        bool(attempts[-1].get("provider_submitted")) if attempts else False,
    )
    record.setdefault(
        "failure_class",
        str(attempts[-1].get("failure_class") or "") if attempts else "",
    )
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
    "ExecutionLockContended",
    "RemediationExecutionStore",
    "_is_patch_evidence_candidate",
    "execution_scope_attributes",
    "is_manual_resolution_required",
    "is_submission_ambiguous",
    "submitted_attempt_count",
]
