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


class PendingRelationshipConflict(RuntimeError):
    """A pending relationship revision no longer matches durable state."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("pending_relationship_revision_conflict")
        self.record = copy.deepcopy(dict(record))


class EvidenceBatchConflict(RuntimeError):
    """A deterministic batch identity was reused for different content."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("evidence_batch_identity_conflict")
        self.record = copy.deepcopy(dict(record))


class ProposalReviewConflict(RuntimeError):
    """A proposal review compare-and-set revision was stale."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("proposal_review_revision_conflict")
        self.record = copy.deepcopy(dict(record))


class ReviewerUnauthorized(PermissionError):
    """A caller without ontology-steward authority attempted review."""


class PairReleaseDisabled(PermissionError):
    """Production Phase 13 cannot activate model-derived pair admission."""


class PairReleaseConflict(RuntimeError):
    """A pair-release compare-and-set revision was stale."""

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__("pair_release_revision_conflict")
        self.record = copy.deepcopy(dict(record))


class OntologyRunStore:
    """Versioned run records with deterministic identity and fenced ownership."""

    SCHEMA_VERSION = "1.2.0"

    def __init__(
        self,
        path: str | Path,
        *,
        max_runs: int = 5000,
        max_attempts: int = 3,
        retry_base_seconds: int = 5,
        retry_max_seconds: int = 300,
        default_deadline_seconds: int = 1800,
        allow_pair_release_testing: bool = False,
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
        self._allow_pair_release_testing = bool(allow_pair_release_testing)
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

    def save_proposal(
        self,
        *,
        proposal: Mapping[str, Any],
        scope: str,
        source_generation_id: str,
        schema_version: str,
        policy_version: str,
        supersedes_proposal_id: str = "",
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Persist one immutable, content-addressed proposal."""

        from .contracts import proposal_content_id

        moment = _aware(now)
        proposal_copy = copy.deepcopy(dict(proposal))
        proposal_id = proposal_content_id(
            proposal=proposal_copy,
            scope=scope,
            source_generation_id=source_generation_id,
            schema_version=schema_version,
            policy_version=policy_version,
        )
        supersedes = str(supersedes_proposal_id or "").strip()
        with self._claim_lock():
            state = self._read_state()
            existing = next(
                (
                    row
                    for row in state["proposals"]
                    if row["proposal_id"] == proposal_id
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing), False
            if supersedes and not any(
                row["proposal_id"] == supersedes for row in state["proposals"]
            ):
                raise ValueError("superseded proposal does not exist")
            record = {
                "proposal_id": proposal_id,
                "proposal": proposal_copy,
                "scope": _required(scope, "scope").casefold(),
                "source_generation_id": _required(
                    source_generation_id, "source_generation_id"
                ),
                "schema_version": _required(schema_version, "schema_version"),
                "policy_version": _required(policy_version, "policy_version"),
                "supersedes_proposal_id": supersedes,
                "created_at": moment.isoformat(),
            }
            state["proposals"].append(record)
            state["proposals"].sort(key=lambda row: row["proposal_id"])
            self._persist_advanced(state, moment)
            return copy.deepcopy(record), True

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._read_state()["proposals"]
        return next(
            (
                copy.deepcopy(row)
                for row in rows
                if row["proposal_id"] == proposal_id
            ),
            None,
        )

    def get_review(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
        if not any(
            row["proposal_id"] == proposal_id for row in state["proposals"]
        ):
            raise ValueError(f"Unknown ontology proposal {proposal_id!r}")
        existing = next(
            (
                row
                for row in state["proposal_reviews"]
                if row["proposal_id"] == proposal_id
            ),
            None,
        )
        return copy.deepcopy(
            existing
            or {
                "proposal_id": proposal_id,
                "status": "pending",
                "revision": 0,
                "events": [],
            }
        )

    def review_proposal(
        self,
        proposal_id: str,
        *,
        action: str,
        expected_revision: int,
        actor: str,
        actor_roles: set[str] | frozenset[str],
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Append an authorized immutable accept/reject/reverse event."""

        roles = sorted(
            {
                str(value).strip().casefold()
                for value in actor_roles
                if str(value).strip()
            }
        )
        if "ontology_steward" not in roles:
            raise ReviewerUnauthorized("ontology_steward role is required")
        normalized_action = str(action or "").strip().casefold()
        statuses = {
            "accept": "accepted",
            "reject": "rejected",
            "reverse": "pending",
        }
        if normalized_action not in statuses:
            raise ValueError("review action must be accept, reject, or reverse")
        reviewer = _required(actor, "actor")
        explanation = _required(reason, "reason")
        moment = _aware(now)
        with self._claim_lock():
            state = self._read_state()
            if not any(
                row["proposal_id"] == proposal_id for row in state["proposals"]
            ):
                raise ValueError(f"Unknown ontology proposal {proposal_id!r}")
            index = next(
                (
                    position
                    for position, row in enumerate(state["proposal_reviews"])
                    if row["proposal_id"] == proposal_id
                ),
                None,
            )
            record = (
                copy.deepcopy(state["proposal_reviews"][index])
                if index is not None
                else {
                    "proposal_id": proposal_id,
                    "status": "pending",
                    "revision": 0,
                    "events": [],
                }
            )
            if record["revision"] != expected_revision:
                raise ProposalReviewConflict(record)
            revision = expected_revision + 1
            status = statuses[normalized_action]
            record["status"] = status
            record["revision"] = revision
            record["events"].append(
                {
                    "revision": revision,
                    "action": normalized_action,
                    "status": status,
                    "actor": reviewer,
                    "actor_roles": roles,
                    "reason": explanation,
                    "recorded_at": moment.isoformat(),
                }
            )
            if index is None:
                state["proposal_reviews"].append(record)
            else:
                state["proposal_reviews"][index] = record
            state["proposal_reviews"].sort(key=lambda row: row["proposal_id"])
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def evaluate_admission_release(
        self,
        snapshot: Any,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist eligibility evidence without enabling the pair."""

        from .contracts import AdmissionEvaluationSnapshot
        from .policy import evaluate_release_eligibility

        if not isinstance(snapshot, AdmissionEvaluationSnapshot):
            snapshot = AdmissionEvaluationSnapshot.model_validate(snapshot)
        result = evaluate_release_eligibility(snapshot)
        moment = _aware(now)
        evaluator = _required(actor, "actor")
        with self._claim_lock():
            state = self._read_state()
            existing = next(
                (
                    row
                    for row in state["admission_releases"]
                    if row["snapshot_id"] == snapshot.snapshot_id
                ),
                None,
            )
            if existing is not None:
                return copy.deepcopy(existing)
            record = {
                "pair_key": snapshot.pair_key,
                "subject_type": snapshot.subject_type,
                "predicate": snapshot.predicate,
                "object_type": snapshot.object_type,
                "snapshot_id": snapshot.snapshot_id,
                "snapshot": snapshot.model_dump(mode="json"),
                "eligible": result.status == "ELIGIBLE",
                "eligibility_reasons": list(result.reasons),
                "wilson_precision_lower_bound": (
                    result.wilson_precision_lower_bound
                ),
                # Phase 13 always records the evaluated initial state as
                # blocked/pending. Activation is a separate audited CAS.
                "status": "BLOCKED/PENDING",
                "revision": 0,
                "evaluated_by": evaluator,
                "evaluated_at": moment.isoformat(),
                "activated_by": "",
                "activated_at": "",
                "revoked_by": "",
                "revoked_at": "",
                "revocation_reason": "",
            }
            state["admission_releases"].append(record)
            state["admission_releases"].sort(
                key=lambda row: (row["pair_key"], row["snapshot_id"])
            )
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def activate_admission_release(
        self,
        snapshot_id: str,
        *,
        expected_revision: int,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Exercise the future activation CAS only in explicit synthetic tests."""

        if not self._allow_pair_release_testing:
            raise PairReleaseDisabled(
                "pair release activation is disabled for Phase 13"
            )
        moment = _aware(now)
        owner = _required(actor, "actor")
        with self._claim_lock():
            state = self._read_state()
            index = next(
                (
                    position
                    for position, row in enumerate(state["admission_releases"])
                    if row["snapshot_id"] == snapshot_id
                ),
                None,
            )
            if index is None:
                raise ValueError(f"Unknown admission snapshot {snapshot_id!r}")
            record = copy.deepcopy(state["admission_releases"][index])
            if (
                record["revision"] != expected_revision
                or record["status"] != "BLOCKED/PENDING"
            ):
                raise PairReleaseConflict(record)
            if not record["eligible"]:
                raise PairReleaseDisabled("pair release evidence is not eligible")
            record["status"] = "ENABLED"
            record["revision"] += 1
            record["activated_by"] = owner
            record["activated_at"] = moment.isoformat()
            state["admission_releases"][index] = record
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def revoke_admission_release(
        self,
        pair_key: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Revoke only the affected enabled pair and restore shadow admission."""

        normalized_reason = str(reason or "").strip().casefold()
        if normalized_reason not in {"critical_event", "threshold_breach"}:
            raise ValueError(
                "release revocation reason must be critical_event or threshold_breach"
            )
        moment = _aware(now)
        owner = _required(actor, "actor")
        with self._claim_lock():
            state = self._read_state()
            matches = [
                (position, row)
                for position, row in enumerate(state["admission_releases"])
                if row["pair_key"] == pair_key and row["status"] == "ENABLED"
            ]
            if len(matches) != 1:
                raise ValueError(f"Enabled admission pair {pair_key!r} not found")
            index, value = matches[0]
            record = copy.deepcopy(value)
            if record["revision"] != expected_revision:
                raise PairReleaseConflict(record)
            record["status"] = "REVOKED"
            record["revision"] += 1
            record["revoked_by"] = owner
            record["revoked_at"] = moment.isoformat()
            record["revocation_reason"] = normalized_reason
            state["admission_releases"][index] = record
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def list_admission_releases(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._read_state()["admission_releases"]
        return copy.deepcopy(
            sorted(rows, key=lambda row: (row["pair_key"], row["snapshot_id"]))
        )

    def admission_release_for(
        self,
        subject_type: str,
        predicate: str,
        object_type: str,
    ) -> dict[str, Any] | None:
        pair_key = f"{subject_type}|{predicate}|{object_type}"
        return next(
            (
                row
                for row in self.list_admission_releases()
                if row["pair_key"] == pair_key and row["status"] == "ENABLED"
            ),
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

    def list_pending_relationships(
        self, *, include_terminal: bool = False
    ) -> list[dict[str, Any]]:
        """Return deterministic durable pending-edge records."""
        with self._lock:
            rows = self._read_state()["pending_relationships"]
        selected = (
            rows
            if include_terminal
            else [row for row in rows if row["terminal_state"] == "pending"]
        )
        return copy.deepcopy(sorted(selected, key=lambda row: row["pending_id"]))

    def defer_pending_relationship(
        self,
        relationship: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create or merge one deterministic pending relationship."""
        moment = _aware(now)
        candidate = copy.deepcopy(dict(relationship))
        subject_id = _required(
            str(candidate.get("subject_id") or ""), "subject_id"
        ).casefold()
        object_id = _required(
            str(candidate.get("object_id") or ""), "object_id"
        ).casefold()
        predicate = _required(str(candidate.get("predicate") or ""), "predicate")
        scope = _required(str(candidate.get("scope") or ""), "scope")
        generation = _required(
            str(candidate.get("source_generation_id") or ""),
            "source_generation_id",
        )
        relationship_id = str(
            candidate.get("resource_id")
            or candidate.get("relationship_id")
            or ""
        ).strip()
        identity = (
            f"{scope.casefold()}|{subject_id}|{predicate.casefold()}|{object_id}"
        )
        pending_id = "OPR-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
        missing = sorted(
            {
                str(value).strip().casefold()
                for value in candidate.get("missing_endpoint_ids", ())
                if str(value).strip()
            }
        )
        observations = _observations(candidate.get("observations"))
        timestamp = moment.isoformat()

        with self._claim_lock():
            state = self._read_state()
            index = next(
                (
                    position
                    for position, row in enumerate(state["pending_relationships"])
                    if row["pending_id"] == pending_id
                ),
                None,
            )
            if index is None:
                record = {
                    **candidate,
                    "pending_id": pending_id,
                    "relationship_id": relationship_id,
                    "resource_id": relationship_id,
                    "subject_id": subject_id,
                    "object_id": object_id,
                    "predicate": predicate,
                    "scope": scope,
                    "source_generation_id": generation,
                    "missing_endpoint_ids": missing,
                    "observations": observations,
                    "attempts": _nonnegative_int(candidate.get("attempts", 0)),
                    "freshness": str(candidate.get("freshness") or "unknown"),
                    "terminal_state": "pending",
                    "revision": 0,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                state["pending_relationships"].append(record)
            else:
                record = copy.deepcopy(state["pending_relationships"][index])
                record["observations"] = _merge_observations(
                    record.get("observations"), observations
                )
                record["missing_endpoint_ids"] = missing or record[
                    "missing_endpoint_ids"
                ]
                record["attempts"] = max(
                    _nonnegative_int(record.get("attempts")),
                    _nonnegative_int(candidate.get("attempts")),
                )
                record["freshness"] = str(
                    candidate.get("freshness") or record["freshness"]
                )
                record["source_generation_id"] = generation
                record["revision"] += 1
                record["updated_at"] = timestamp
                state["pending_relationships"][index] = record
            state["pending_relationships"].sort(key=lambda row: row["pending_id"])
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def transition_pending_relationship(
        self,
        pending_id: str,
        *,
        expected_revision: int,
        terminal_state: str,
        missing_endpoint_ids: list[str] | tuple[str, ...] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """CAS a pending edge to a durable terminal or updated pending state."""
        normalized_state = str(terminal_state or "").strip().casefold()
        if normalized_state not in {
            "pending",
            "resolved",
            "expired",
            "rejected",
            "cancelled",
        }:
            raise ValueError("terminal_state is invalid")
        moment = _aware(now)
        with self._claim_lock():
            state = self._read_state()
            index = next(
                (
                    position
                    for position, row in enumerate(state["pending_relationships"])
                    if row["pending_id"] == pending_id
                ),
                None,
            )
            if index is None:
                raise ValueError(f"Unknown pending relationship {pending_id!r}")
            record = copy.deepcopy(state["pending_relationships"][index])
            if record["revision"] != expected_revision:
                raise PendingRelationshipConflict(record)
            if missing_endpoint_ids is not None:
                record["missing_endpoint_ids"] = sorted(
                    {
                        str(value).strip().casefold()
                        for value in missing_endpoint_ids
                        if str(value).strip()
                    }
                )
            record["terminal_state"] = normalized_state
            record["revision"] += 1
            record["updated_at"] = moment.isoformat()
            state["pending_relationships"][index] = record
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def list_evidence_batches(
        self, *, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return persisted batches in deterministic identity order."""
        with self._lock:
            rows = self._read_state()["evidence_batches"]
        selected = rows if run_id is None else [
            row for row in rows if row["run_id"] == run_id
        ]
        return copy.deepcopy(sorted(selected, key=lambda row: row["batch_id"]))

    def save_evidence_batch(
        self,
        *,
        run_id: str,
        batch: Mapping[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist a validated batch before any curator call."""
        from .contracts import EvidenceBatch

        moment = _aware(now)
        validated = EvidenceBatch.from_dict(batch).to_dict()
        batch_id = validated["batch_id"]
        with self._claim_lock():
            state, _run_index, run = self._locate(run_id)
            if validated["source_generation_id"] != run["source_generation_id"]:
                raise ValueError("batch source generation does not match run")
            existing = next(
                (
                    row
                    for row in state["evidence_batches"]
                    if row["batch_id"] == batch_id
                ),
                None,
            )
            if existing is not None:
                if existing["run_id"] != run_id or existing["batch"] != validated:
                    raise EvidenceBatchConflict(existing)
                return copy.deepcopy(existing)
            record = {
                "batch_id": batch_id,
                "run_id": run_id,
                "source_generation_id": validated["source_generation_id"],
                "scope": validated["scope"],
                "status": "persisted",
                "revision": 0,
                "persisted_at": moment.isoformat(),
                "dispatched_at": "",
                "batch": validated,
                "result": {},
            }
            state["evidence_batches"].append(record)
            state["evidence_batches"].sort(key=lambda row: row["batch_id"])
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

    def mark_evidence_batch_dispatched(
        self,
        batch_id: str,
        *,
        expected_revision: int,
        result: Mapping[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """CAS a persisted batch after the curator returns."""
        moment = _aware(now)
        with self._claim_lock():
            state = self._read_state()
            index = next(
                (
                    position
                    for position, row in enumerate(state["evidence_batches"])
                    if row["batch_id"] == batch_id
                ),
                None,
            )
            if index is None:
                raise ValueError(f"Unknown evidence batch {batch_id!r}")
            record = copy.deepcopy(state["evidence_batches"][index])
            if record["revision"] != expected_revision:
                raise EvidenceBatchConflict(record)
            if record["status"] == "dispatched":
                return record
            record["status"] = "dispatched"
            record["revision"] += 1
            record["dispatched_at"] = moment.isoformat()
            record["result"] = copy.deepcopy(dict(result))
            state["evidence_batches"][index] = record
            self._persist_advanced(state, moment)
            return copy.deepcopy(record)

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

    def renew_lease(
        self,
        run_id: str,
        *,
        expected_revision: int,
        owner: str,
        fencing_token: int,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Renew a live lease without changing its monotonic fencing token."""
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise TypeError("lease_seconds must be an integer")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
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
            record["lease_expires_at"] = (
                moment + timedelta(seconds=lease_seconds)
            ).isoformat()
            self._replace_record(
                state,
                index,
                record,
                status=RUN_RUNNING,
                actor=owner,
                moment=moment,
                checkpoint=record["checkpoint"]["name"],
                message="Lease renewed",
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

    def exhaust(
        self,
        run_id: str,
        *,
        expected_revision: int,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Fail an abandoned due run after its final claim was consumed."""
        moment = _aware(now)
        with self._claim_lock():
            state, index, record = self._locate(run_id)
            if (
                record["revision"] != expected_revision
                or record["status"] in TERMINAL_STATUSES
                or record["attempt_count"] < record["max_attempts"]
                or not _is_due(record, moment)
            ):
                raise RunClaimConflict("run_attempts_not_exhausted", record)
            record["failure_class"] = "attempts_exhausted"
            record["message"] = "Maximum run attempts exhausted"
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
                failure_class="attempts_exhausted",
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
        pending = payload.get("pending_relationships", [])
        if not isinstance(pending, list) or any(
            not isinstance(row, dict) for row in pending
        ):
            raise TypeError("Pending relationships must be a list of objects")
        batches = payload.get("evidence_batches", [])
        if not isinstance(batches, list) or any(
            not isinstance(row, dict) for row in batches
        ):
            raise TypeError("Evidence batches must be a list of objects")
        proposals = payload.get("proposals", [])
        if not isinstance(proposals, list) or any(
            not isinstance(row, dict) for row in proposals
        ):
            raise TypeError("Ontology proposals must be a list of objects")
        reviews = payload.get("proposal_reviews", [])
        if not isinstance(reviews, list) or any(
            not isinstance(row, dict) for row in reviews
        ):
            raise TypeError("Proposal reviews must be a list of objects")
        releases = payload.get("admission_releases", [])
        if not isinstance(releases, list) or any(
            not isinstance(row, dict) for row in releases
        ):
            raise TypeError("Admission releases must be a list of objects")
        return {
            "revision": _nonnegative_int(payload.get("revision", 0)),
            "next_fencing_token": _nonnegative_int(
                payload.get("next_fencing_token", 0)
            ),
            "runs": [_with_defaults(row, self.max_attempts) for row in rows],
            "pending_relationships": [
                _pending_with_defaults(row) for row in pending
            ],
            "evidence_batches": [
                _batch_with_defaults(row) for row in batches
            ],
            "proposals": [_proposal_with_defaults(row) for row in proposals],
            "proposal_reviews": [
                _review_with_defaults(row) for row in reviews
            ],
            "admission_releases": [
                _release_with_defaults(row) for row in releases
            ],
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
            "pending_relationships": state["pending_relationships"],
            "evidence_batches": state["evidence_batches"],
            "proposals": state["proposals"],
            "proposal_reviews": state["proposal_reviews"],
            "admission_releases": state["admission_releases"],
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
        "pending_relationships": [],
        "evidence_batches": [],
        "proposals": [],
        "proposal_reviews": [],
        "admission_releases": [],
        "updated_at": "",
    }


def _pending_with_defaults(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    record.setdefault("pending_id", "")
    record.setdefault("relationship_id", str(record.get("resource_id") or ""))
    record.setdefault("resource_id", record["relationship_id"])
    record["subject_id"] = str(record.get("subject_id") or "").casefold()
    record["object_id"] = str(record.get("object_id") or "").casefold()
    record.setdefault("predicate", "")
    record.setdefault("scope", "")
    record.setdefault("source_generation_id", "")
    record["missing_endpoint_ids"] = sorted(
        {
            str(value).casefold()
            for value in record.get("missing_endpoint_ids", ())
            if str(value).strip()
        }
    )
    record["observations"] = _observations(record.get("observations"))
    record["attempts"] = _nonnegative_int(record.get("attempts"))
    record.setdefault("freshness", "unknown")
    record.setdefault("terminal_state", "pending")
    record["revision"] = _nonnegative_int(record.get("revision"))
    record.setdefault("created_at", "")
    record.setdefault("updated_at", "")
    return record


def _batch_with_defaults(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    record.setdefault("batch_id", "")
    record.setdefault("run_id", "")
    record.setdefault("source_generation_id", "")
    record.setdefault("scope", "")
    record.setdefault("status", "persisted")
    record["revision"] = _nonnegative_int(record.get("revision"))
    record.setdefault("persisted_at", "")
    record.setdefault("dispatched_at", "")
    record["batch"] = (
        copy.deepcopy(record["batch"])
        if isinstance(record.get("batch"), dict)
        else {}
    )
    record["result"] = (
        copy.deepcopy(record["result"])
        if isinstance(record.get("result"), dict)
        else {}
    )
    return record


def _proposal_with_defaults(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    record.setdefault("proposal_id", "")
    record["proposal"] = (
        copy.deepcopy(record["proposal"])
        if isinstance(record.get("proposal"), dict)
        else {}
    )
    record.setdefault("scope", "")
    record.setdefault("source_generation_id", "")
    record.setdefault("schema_version", "legacy")
    record.setdefault("policy_version", "legacy")
    record.setdefault("supersedes_proposal_id", "")
    record.setdefault("created_at", "")
    return record


def _review_with_defaults(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    record.setdefault("proposal_id", "")
    record.setdefault("status", "pending")
    record["revision"] = _nonnegative_int(record.get("revision"))
    record["events"] = (
        copy.deepcopy(record["events"])
        if isinstance(record.get("events"), list)
        else []
    )
    return record


def _release_with_defaults(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    for field_name in (
        "pair_key",
        "subject_type",
        "predicate",
        "object_type",
        "snapshot_id",
        "evaluated_by",
        "evaluated_at",
        "activated_by",
        "activated_at",
        "revoked_by",
        "revoked_at",
        "revocation_reason",
    ):
        record.setdefault(field_name, "")
    record["snapshot"] = (
        copy.deepcopy(record["snapshot"])
        if isinstance(record.get("snapshot"), dict)
        else {}
    )
    record.setdefault("eligible", False)
    record["eligibility_reasons"] = list(
        record.get("eligibility_reasons")
        if isinstance(record.get("eligibility_reasons"), list)
        else []
    )
    record.setdefault("wilson_precision_lower_bound", 0.0)
    record.setdefault("status", "BLOCKED/PENDING")
    record["revision"] = _nonnegative_int(record.get("revision"))
    return record


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


def _observations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    observations = [
        copy.deepcopy(dict(item))
        for item in value
        if isinstance(item, Mapping)
    ]
    return sorted(
        observations,
        key=lambda item: json.dumps(item, sort_keys=True, default=str),
    )


def _merge_observations(left: Any, right: Any) -> list[dict[str, Any]]:
    unique = {
        json.dumps(item, sort_keys=True, default=str): item
        for item in [*_observations(left), *_observations(right)]
    }
    return [unique[key] for key in sorted(unique)]


__all__ = [
    "CLAIMABLE_STATUSES",
    "RUN_CANCELLED",
    "RUN_FAILED",
    "RUN_QUEUED",
    "RUN_RETRYING",
    "RUN_RUNNING",
    "RUN_SUCCEEDED",
    "TERMINAL_STATUSES",
    "EvidenceBatchConflict",
    "OntologyRunStore",
    "PairReleaseConflict",
    "PairReleaseDisabled",
    "PendingRelationshipConflict",
    "ProposalReviewConflict",
    "ReviewerUnauthorized",
    "RunClaimConflict",
    "RunDeadlineExceeded",
    "RunLeaseLost",
]
