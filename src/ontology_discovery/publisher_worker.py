"""Finite publisher-only worker for durable ontology dispatches."""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from onboarding.registry import ConnectionNotFoundError, ConnectionRegistry
from storage.datasets import GenerationPointerConditions
from storage.locking import MonotonicFenceAllocator

from .command_intake import (
    CommandConflict,
    PublisherCommandConsumer,
    scope_receipt,
)
from .dispatch_store import DispatchConflict, PublisherDispatchView
from .drill_control import PublisherDrillControl
from .publisher import (
    APPROVED_PUBLICATION_CHECKPOINTS,
    CONSUMER_FAMILIES,
    OntologyGenerationCandidate,
    OntologyGenerationPublisher,
    PostCheckRollbackError,
    PublicationSafetyError,
)


class PublisherWorker:
    """Claim at most ``limit`` immutable dispatches and publish them in isolation."""

    def __init__(
        self,
        *,
        dispatches: PublisherDispatchView,
        publisher: OntologyGenerationPublisher,
        publisher_identity: str,
        owner_id: str,
        fence_allocator: MonotonicFenceAllocator,
        materialize: Callable[[OntologyGenerationCandidate], Mapping[str, Any]],
        consumer_check: Callable[[str, str], Mapping[str, bool]],
        now: Callable[[], datetime],
        drill_control: PublisherDrillControl | None = None,
        maintenance_authorizer: Any | None = None,
    ) -> None:
        if maintenance_authorizer is not None and not getattr(
            consumer_check, "maintenance_observer", False
        ):
            # Phase 13 callbacks are never maintenance convergence evidence.
            raise ValueError("maintenance_requires_independent_consumer_observers")
        self._maintenance = maintenance_authorizer
        self._dispatches = dispatches
        self._publisher = publisher
        self._publisher_identity = _required(publisher_identity, "publisher_identity")
        self._owner_id = _required(owner_id, "owner_id")
        self._fences = fence_allocator
        self._materialize = materialize
        self._consumer_check = consumer_check
        self._now = now
        self._drill = drill_control

    def run_once(
        self, now: datetime | None = None, *, limit: int = 1
    ) -> dict[str, int]:
        moment = _aware(now or self._now())
        due = self._dispatches.list_due_publish(now=moment, limit=limit)
        result = {"selected": len(due), "succeeded": 0, "failed": 0, "contended": 0}
        for pending in due:
            try:
                claimed = self._dispatches.claim_publish(
                    pending["dispatch_id"],
                    expected_revision=int(pending["revision"]),
                    owner=self._owner_id,
                    now=moment,
                )
            except DispatchConflict:
                result["contended"] += 1
                continue
            try:
                self._process(claimed, moment)
            except DispatchConflict:
                result["contended"] += 1
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                current = self._dispatches.get_publish(claimed["dispatch_id"])
                if current is not None and current["status"] == "claimed":
                    retryable = not isinstance(exc, PostCheckRollbackError)
                    self._dispatches.fail_publish(
                        claimed["dispatch_id"],
                        expected_revision=int(current["revision"]),
                        owner=self._owner_id,
                        reason_code=_closed_reason(exc),
                        retryable=retryable,
                        receipt={
                            "failure_class": _closed_reason(exc),
                            "command_hash": claimed["content_hash"],
                            "failed_at": moment.isoformat(),
                        },
                        now=moment,
                    )
                result["failed"] += 1
            else:
                result["succeeded"] += 1
        remaining = max(0, int(limit) - len(due))
        for pending in self._dispatches.list_due_rollback(
            now=moment, limit=remaining
        ):
            result["selected"] += 1
            try:
                claimed = self._dispatches.claim_rollback(
                    pending["dispatch_id"],
                    expected_revision=int(pending["revision"]),
                    owner=self._owner_id,
                    now=moment,
                )
                self._process_rollback(claimed, moment)
            except DispatchConflict:
                result["contended"] += 1
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                current = self._dispatches.get_rollback(pending["dispatch_id"])
                if current is not None and current["status"] == "claimed":
                    self._dispatches.fail_rollback(
                        pending["dispatch_id"],
                        expected_revision=int(current["revision"]),
                        owner=self._owner_id,
                        reason_code=_closed_reason(exc),
                        receipt={
                            "failure_class": _closed_reason(exc),
                            "command_hash": pending["content_hash"],
                            "failed_at": moment.isoformat(),
                        },
                        now=moment,
                    )
                result["failed"] += 1
            else:
                result["succeeded"] += 1
        return result

    def _process(self, claimed: Mapping[str, Any], moment: datetime) -> None:
        candidate = _candidate_from_dispatch(
            claimed, allow_model_rows=self._maintenance is not None
        )
        dispatch_id = str(claimed["dispatch_id"])
        revision = [int(claimed["revision"])]
        initial_pointer = self._publisher._storage.read_pointer()
        conditions = GenerationPointerConditions.from_snapshot(initial_pointer)
        stage_receipt = next(
            (
                receipt
                for receipt in claimed.get("receipts", [])
                if receipt.get("step") == "immutable_stage"
            ),
            None,
        )
        fence = (
            self._fences.allocate(
                scope=str(claimed["connection_id"]),
                owner_id=self._owner_id,
            )
            if stage_receipt is None
            else type(
                "_RecoveredFence",
                (),
                {"value": int(stage_receipt["fence"])},
            )()
        )

        def current() -> Mapping[str, Any]:
            row = self._dispatches.get_publish(dispatch_id)
            if row is None:
                raise DispatchConflict("dispatch_not_found")
            return row

        def lease_guard() -> None:
            row = current()
            if (
                row["status"] != "claimed"
                or row["lease_owner"] != self._owner_id
                or datetime.fromisoformat(row["lease_expires_at"]) <= (
                    _aware(self._now())
                    if getattr(self._materialize, "maintenance_candidate_bound", False)
                    else moment
                )
            ):
                raise DispatchConflict("dispatch_lease_lost")

        def record(step: str, receipt: Mapping[str, Any]) -> None:
            row = current()
            updated = self._dispatches.record_step_receipt(
                dispatch_id,
                expected_revision=int(row["revision"]),
                owner=self._owner_id,
                step=step,
                receipt={
                    **dict(receipt),
                    "command_hash": str(claimed["content_hash"]),
                    "recorded_at": moment.isoformat(),
                },
                now=moment,
            )
            revision[0] = int(updated["revision"])

        def checked(stage: str, generation_id: str) -> Mapping[str, bool]:
            values = dict(self._consumer_check(stage, generation_id))
            if self._drill is not None and stage == "post":
                for family in CONSUMER_FAMILIES:
                    if self._drill.fail_post_check(
                        command_hash=str(claimed["content_hash"]),
                        family=family,
                        now=moment,
                    ):
                        values[family] = False
                        break
            return values

        materializer = (
            self._materialize
            if getattr(self._materialize, "maintenance_candidate_bound", False)
            and callable(getattr(self._materialize, "bind", None))
            else None
        )
        if materializer is not None:
            journal = materializer.journal.read() or {}
            if (
                (journal.get("operation") or {}).get("generation_id") == candidate.generation_id
                and (journal.get("recovery_intent") or {}).get("reason") == "post_check_failed"
                and journal.get("phase") in {"restoring", "critical"}
            ):
                recovery_fence = self._fences.allocate(
                    scope=str(claimed["connection_id"]), owner_id=self._owner_id
                ).value
                materializer.bind(
                    owner_id=self._owner_id, fence=recovery_fence,
                    predecessor=(journal.get("recovery_intent") or {}).get("target_generation"),
                    pointer_etag=initial_pointer.etag,
                )
                self._publisher.resume_recovery(
                    materializer=materializer,
                    publisher_identity=self._publisher_identity, owner_id=self._owner_id,
                    rollback_fence_allocator=lambda: self._fences.allocate(
                        scope=str(claimed["connection_id"]), owner_id=self._owner_id
                    ).value,
                    post_consumer_check=lambda generation_id: checked("post", generation_id),
                )
        if materializer is not None and (
            initial_pointer.pointer is not None
            and initial_pointer.pointer.active_generation == candidate.generation_id
        ):
            # The pointer CAS survived a process death: reconcile the real
            # products against the immutable receipt, then finish post-check,
            # receipt and journal -- never a second blind promotion.
            materializer.bind(
                owner_id=self._owner_id,
                fence=fence.value,
                predecessor=initial_pointer.pointer.prior_generation,
                pointer_etag=initial_pointer.etag,
            )
            try:
                materializer.reconcile()
                promoted = self._publisher.resume_committed(
                    generation_id=candidate.generation_id,
                    source_generation=candidate.source_generation,
                    content_hash=str(claimed["content_hash"]),
                    materializer=materializer,
                    post_consumer_check=lambda generation_id: checked(
                        "post", generation_id
                    ),
                    publisher_identity=self._publisher_identity,
                    owner_id=self._owner_id,
                    rollback_fence_allocator=lambda: self._fences.allocate(
                        scope=str(claimed["connection_id"]),
                        owner_id=self._owner_id,
                    ).value,
                    cancellation_check=lambda: False,
                    lease_guard=lease_guard,
                    step_recorder=record,
                )
            finally:
                materializer.release()
            row = current()
            self._dispatches.complete_publish(
                dispatch_id,
                expected_revision=int(row["revision"]),
                owner=self._owner_id,
                receipt={
                    "generation_id": candidate.generation_id,
                    "pointer_etag": promoted.etag or "",
                    "command_hash": claimed["content_hash"],
                    "completed_at": moment.isoformat(),
                    "resumed": True,
                },
                now=moment,
            )
            return
        promoted = self._publisher.publish(
            candidate,
            publisher_identity=self._publisher_identity,
            checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
            pointer_conditions=conditions,
            owner_id=self._owner_id,
            fence=fence.value,
            consumer_compatibility={family: True for family in CONSUMER_FAMILIES},
            cancellation_check=lambda: False,
            lease_guard=lease_guard,
            materialize_generation=self._materialize,
            staged_consumer_check=lambda generation_id: checked(
                "staged", generation_id
            ),
            post_consumer_check=lambda generation_id: checked(
                "post", generation_id
            ),
            step_recorder=record,
            pre_cas_hook=(
                None
                if self._drill is None
                else lambda: self._drill.before_cas(
                    command_hash=str(claimed["content_hash"]),
                    now=moment,
                )
            ),
            rollback_fence_allocator=lambda: self._fences.allocate(
                scope=str(claimed["connection_id"]),
                owner_id=self._owner_id,
            ).value,
            maintenance_authorizer=self._maintenance,
        )
        row = current()
        self._dispatches.complete_publish(
            dispatch_id,
            expected_revision=int(row["revision"]),
            owner=self._owner_id,
            receipt={
                "generation_id": candidate.generation_id,
                "pointer_etag": promoted.etag or "",
                "command_hash": claimed["content_hash"],
                "completed_at": moment.isoformat(),
            },
            now=moment,
        )

    def _process_rollback(
        self, claimed: Mapping[str, Any], moment: datetime
    ) -> None:
        pointer = self._publisher._storage.read_pointer()
        if (
            pointer.pointer is None
            or pointer.pointer.active_generation
            != claimed["observed_active_generation"]
            or pointer.etag != claimed["observed_pointer_etag"]
        ):
            raise PublicationSafetyError("stale rollback pointer observation")
        if self._maintenance is not None:
            active = self._publisher._storage.read_generation(
                pointer.pointer.active_generation
            )
            if self._maintenance.model_rows(active["relationships"]):
                # Recovery needs its own current restore permission; revoked
                # new-edge admission is not enough and is not required.
                try:
                    self._maintenance.authorize_restore()
                except Exception:  # noqa: BLE001
                    raise PublicationSafetyError("restore_not_authorized") from None
        fence = self._fences.allocate(
            scope=str(claimed["connection_id"]),
            owner_id=self._owner_id,
        )
        materializer = (
            self._materialize
            if getattr(self._materialize, "maintenance_candidate_bound", False)
            and callable(getattr(self._materialize, "bind", None))
            else None
        )
        if materializer is not None:
            # Rollback must rematerialize the target's physical products, not
            # just move the pointer.  Pointer and consumers are separate steps.
            materializer.bind(
                owner_id=self._owner_id,
                fence=fence.value,
                predecessor=pointer.pointer.active_generation,
                pointer_etag=pointer.etag,
            )
            try:
                materializer.recover_physical(
                    reason="explicit_rollback",
                    target=str(claimed["target_generation_id"]),
                    expected_active=pointer.pointer.active_generation,
                )
            except Exception:
                materializer.release()
                raise
        try:
            rolled_back = self._publisher.rollback(
            target_generation_id=str(claimed["target_generation_id"]),
            source_generation=str(claimed["source_generation_id"]),
            publisher_identity=self._publisher_identity,
            checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
            pointer_conditions=GenerationPointerConditions.from_snapshot(pointer),
            owner_id=self._owner_id,
            fence=fence.value,
            cancellation_check=lambda: False,
            lease_guard=lambda: None,
            restore_guard=(
                materializer.assert_restore_authorized if materializer is not None else None
            ),
            )
        except Exception:
            if materializer is not None:
                with contextlib.suppress(Exception):  # critical journal durable
                    materializer.recover_physical(reason="rollback_pointer_failed")
                materializer.release()
            raise
        checks = dict(
            self._consumer_check(
                "post", str(claimed["target_generation_id"])
            )
        )
        if materializer is not None:
            materializer.mark_recovery(
                pointer=True,
                consumer=set(checks) == set(CONSUMER_FAMILIES) and all(checks.values()),
            )
            materializer.release()
        if set(checks) != set(CONSUMER_FAMILIES) or not all(checks.values()):
            raise PublicationSafetyError("rollback consumer verification failed")
        self._dispatches.complete_rollback(
            str(claimed["dispatch_id"]),
            expected_revision=int(claimed["revision"]),
            owner=self._owner_id,
            receipt={
                "target_generation_hash": hashlib.sha256(
                    str(claimed["target_generation_id"]).encode()
                ).hexdigest(),
                "pointer_etag": rolled_back.etag or "",
                "fence": fence.value,
                "consumer_hash": _hash_mapping(checks),
                "completed_at": moment.isoformat(),
            },
            now=moment,
        )


class PublisherIntakeAdapter:
    """Reauthorize untrusted rollback intake before authoritative dispatch."""

    def __init__(
        self,
        *,
        registry: ConnectionRegistry,
        commands: PublisherCommandConsumer,
        dispatches: PublisherDispatchView,
        publication: Any,
        owner_id: str,
        now: Callable[[], datetime],
    ) -> None:
        self._registry = registry
        self._commands = commands
        self._dispatches = dispatches
        self._publication = publication
        self._owner_id = _required(owner_id, "owner_id")
        self._now = now

    def process_one(self) -> dict[str, int]:
        moment = _aware(self._now())
        due = self._commands.list_due_rollback(now=moment, limit=1)
        result = {"accepted": 0, "denied": 0, "contended": 0}
        if not due:
            return result
        pending = due[0]
        try:
            claimed = self._commands.claim_rollback(
                pending["command_id"],
                expected_revision=int(pending["revision"]),
                owner=self._owner_id,
                now=moment,
            )
        except CommandConflict:
            result["contended"] = 1
            return result
        reason = self._authorize(claimed, moment)
        audit = {
            "event": "rollback_authorization",
            "outcome": "authorized" if reason == "" else "denied",
            "command_hash": _hash_mapping(_immutable_rollback_intake(claimed)),
            "scope_hash": str(claimed["effective_scope_hash"]),
            "target_generation_hash": hashlib.sha256(
                str(claimed["target_generation_id"]).encode()
            ).hexdigest(),
            "observed_at": moment.isoformat(),
            "reason_code": reason,
        }
        if reason:
            self._commands.deny(
                claimed["command_id"],
                expected_revision=int(claimed["revision"]),
                owner=self._owner_id,
                reason_code=reason,
                authorization_audit=audit,
                now=moment,
            )
            result["denied"] = 1
            return result
        target = self._publication.read_generation(
            str(claimed["target_generation_id"])
        )
        self._dispatches.create_rollback(
            source_command_id=str(claimed["command_id"]),
            connection_id=str(claimed["connection_id"]),
            target_generation_id=str(claimed["target_generation_id"]),
            source_generation_id=str(target["manifest"]["source_generation"]),
            observed_active_generation=str(
                claimed["observed_active_generation"]
            ),
            observed_pointer_etag=str(claimed["observed_pointer_etag"]),
            reason_hash=hashlib.sha256(
                str(claimed.get("reason") or "").encode()
            ).hexdigest(),
            authorization_audit=audit,
            now=moment,
        )
        self._commands.complete(
            claimed["command_id"],
            expected_revision=int(claimed["revision"]),
            owner=self._owner_id,
            authorization_audit=audit,
            now=moment,
        )
        result["accepted"] = 1
        return result

    def _authorize(self, command: Mapping[str, Any], moment: datetime) -> str:
        if datetime.fromisoformat(str(command["expires_at"])) <= moment:
            return "command_expired"
        try:
            connection = self._registry.get(str(command["connection_id"]))
        except ConnectionNotFoundError:
            return "connection_not_found"
        if not connection.is_active:
            return "connection_inactive"
        if command["effective_scope_hash"] != scope_receipt(
            connection, "ontology.publication.rollback"
        ):
            return "scope_receipt_mismatch"
        pointer = self._publication.read_pointer()
        if (
            pointer.pointer is None
            or pointer.pointer.active_generation
            != command["observed_active_generation"]
            or pointer.etag != command["observed_pointer_etag"]
        ):
            return "stale_pointer_observation"
        try:
            target = self._publication.read_generation(
                str(command["target_generation_id"])
            )
        except (FileNotFoundError, TypeError, ValueError):
            return "rollback_target_unavailable"
        if (
            target["manifest"].get("complete") is not True
            or target["validation"].get("passed") is not True
            or target["compatibility"].get("all_consumers_compatible") is not True
            or not target.get("audit")
        ):
            return "rollback_target_ineligible"
        return ""


def _candidate_from_dispatch(
    row: Mapping[str, Any], *, allow_model_rows: bool = False
) -> OntologyGenerationCandidate:
    raw = row.get("candidate")
    if not isinstance(raw, Mapping):
        raise PublicationSafetyError("dispatch candidate is malformed")
    required = {
        "generation_id",
        "entities",
        "relationships",
        "proposal_lineage",
        "decision_lineage",
        "policy_version",
        "schema_version",
    }
    if not required.issubset(raw):
        raise PublicationSafetyError("dispatch candidate is incomplete")
    if not allow_model_rows and any(
        relationship.get("model_derived") is True
        or str(relationship.get("source") or "").casefold() == "model"
        for relationship in raw["relationships"]
    ):
        raise PublicationSafetyError("model_derived_relationship")
    canonical = json.dumps(
        {
            "type": "publish",
            "run_id": row.get("run_id"),
            "connection_id": row.get("connection_id"),
            "source_generation_id": row.get("source_generation_id"),
            "candidate": raw,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if hashlib.sha256(canonical.encode()).hexdigest() != row.get("content_hash"):
        raise PublicationSafetyError("dispatch_content_hash_mismatch")
    return OntologyGenerationCandidate(
        generation_id=str(raw["generation_id"]),
        source_generation=str(row["source_generation_id"]),
        entities=tuple(dict(item) for item in raw["entities"]),
        relationships=tuple(dict(item) for item in raw["relationships"]),
        proposal_lineage=tuple(str(item) for item in raw["proposal_lineage"]),
        decision_lineage=tuple(str(item) for item in raw["decision_lineage"]),
        policy_version=str(raw["policy_version"]),
        schema_version=str(raw["schema_version"]),
    )


def _closed_reason(exc: Exception) -> str:
    if isinstance(exc, PostCheckRollbackError):
        return str(exc)
    if isinstance(exc, DispatchConflict):
        return "dispatch_conflict"
    if isinstance(exc, PublicationSafetyError):
        return "publication_safety_refusal"
    return "publisher_dependency_failure"


def _immutable_rollback_intake(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "command_id",
            "connection_id",
            "effective_scope_hash",
            "target_generation_id",
            "observed_active_generation",
            "observed_pointer_etag",
            "idempotency_key",
        )
    }


def _hash_mapping(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["PublisherIntakeAdapter", "PublisherWorker"]
