"""Finite publisher-only worker for durable ontology dispatches."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from storage.datasets import GenerationPointerConditions
from storage.locking import MonotonicFenceAllocator

from .dispatch_store import DispatchConflict, PublisherDispatchView
from .publisher import (
    APPROVED_PUBLICATION_CHECKPOINTS,
    CONSUMER_FAMILIES,
    OntologyGenerationCandidate,
    OntologyGenerationPublisher,
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
    ) -> None:
        self._dispatches = dispatches
        self._publisher = publisher
        self._publisher_identity = _required(publisher_identity, "publisher_identity")
        self._owner_id = _required(owner_id, "owner_id")
        self._fences = fence_allocator
        self._materialize = materialize
        self._consumer_check = consumer_check
        self._now = now

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
                    self._dispatches.fail_publish(
                        claimed["dispatch_id"],
                        expected_revision=int(current["revision"]),
                        owner=self._owner_id,
                        reason_code=_closed_reason(exc),
                        retryable=True,
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
        return result

    def _process(self, claimed: Mapping[str, Any], moment: datetime) -> None:
        candidate = _candidate_from_dispatch(claimed)
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
                or datetime.fromisoformat(row["lease_expires_at"]) <= moment
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
            staged_consumer_check=lambda generation_id: self._consumer_check(
                "staged", generation_id
            ),
            post_consumer_check=lambda generation_id: self._consumer_check(
                "post", generation_id
            ),
            step_recorder=record,
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


def _candidate_from_dispatch(row: Mapping[str, Any]) -> OntologyGenerationCandidate:
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
    if any(
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
    if isinstance(exc, DispatchConflict):
        return "dispatch_conflict"
    if isinstance(exc, PublicationSafetyError):
        return "publication_safety_refusal"
    return "publisher_dependency_failure"


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["PublisherWorker"]
