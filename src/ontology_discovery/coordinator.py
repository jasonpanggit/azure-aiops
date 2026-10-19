"""Finite, browser-independent ontology discovery coordinator."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .contracts import (
    CheckpointResult,
    Curator,
    EvidenceBatch,
    EvidenceProvider,
    RunProcessingFailure,
    RunProcessor,
)
from .curator import (
    HARD_MAX_OUTPUT_TOKENS,
    CuratorInvalidOutput,
    estimate_input_tokens,
    parse_proposal_batch,
)
from .incremental import EvidenceBatchRejected, split_evidence_batches
from .planner_capabilities import PlannerSelection, provider_receipt, select_planner
from .policy import ProposalPolicy
from .publisher import OntologyGenerationCandidate
from .store import (
    RUN_RETRYING,
    OntologyRunStore,
    RunClaimConflict,
    RunDeadlineExceeded,
    RunLeaseLost,
)

_LOGGER = logging.getLogger("aiops.ontology_discovery.coordinator")


class ValidatedCandidateProvider(Protocol):
    """Build a complete candidate without receiving publication authority."""

    async def validated_candidate(
        self, run: Mapping[str, Any]
    ) -> OntologyGenerationCandidate: ...


class DedicatedPublisher(Protocol):
    """Narrow dispatch seam implemented by the separately authorized worker."""

    async def publish(
        self,
        *,
        run: Mapping[str, Any],
        candidate: OntologyGenerationCandidate,
    ) -> Mapping[str, Any]: ...

    async def publication_status(self, run_id: str) -> Mapping[str, Any]: ...


class PublisherDispatchProcessor:
    """Submit a validated candidate without exposing writer identity or storage.

    The coordinator owns leases and durable run transitions.  This processor
    can only ask the dedicated publisher to publish and read its resulting
    status; it cannot stage generations, mutate pointers, or choose the
    publisher identity.
    """

    def __init__(
        self,
        *,
        candidate_provider: ValidatedCandidateProvider,
        publisher: DedicatedPublisher,
    ) -> None:
        self._candidate_provider = candidate_provider
        self._publisher = publisher

    async def advance(self, run: Mapping[str, Any]) -> CheckpointResult:
        candidate = await self._candidate_provider.validated_candidate(run)
        if not isinstance(candidate, OntologyGenerationCandidate):
            raise RunProcessingFailure(
                failure_class="candidate_invalid",
                checkpoint="candidate_rejected",
                message="validated candidate provider returned an invalid candidate",
            )
        try:
            publication = await self._publisher.publish(
                run=run,
                candidate=candidate,
            )
        except Exception as exc:
            try:
                status = await self._publisher.publication_status(
                    str(run.get("run_id") or "")
                )
            except Exception:  # noqa: BLE001 - denial must survive status-reader failure
                status = {}
            safe_status = {
                key: status[key]
                for key in (
                    "run_id",
                    "generation_id",
                    "active_generation",
                    "pointer_etag",
                    "status",
                )
                if key in status
            }
            raise RunProcessingFailure(
                failure_class="publisher_denied",
                checkpoint="publication_denied",
                payload=safe_status,
                message=str(exc) or exc.__class__.__name__,
            ) from exc
        return CheckpointResult(
            checkpoint="publication_succeeded",
            payload=dict(publication),
            complete=True,
        )


class ProposalPolicyCoordinator:
    """Join durable reviews to policy without granting publication authority."""

    def __init__(
        self,
        *,
        store: OntologyRunStore,
        policy: ProposalPolicy,
    ) -> None:
        self._store = store
        self._policy = policy

    def build_candidate(
        self,
        *,
        proposals: list[Mapping[str, Any]],
        deterministic_edges: list[Mapping[str, Any]],
        entities: Mapping[str, Mapping[str, Any]],
        evidence_records: Mapping[str, Mapping[str, Any]],
        scope: str,
        source_generation_id: str,
    ) -> dict[str, Any]:
        """Evaluate durable proposals and assemble a shadow-safe candidate."""

        decisions = []
        for record in proposals:
            proposal = record.get("proposal")
            if not isinstance(proposal, Mapping):
                raise TypeError("persisted proposal payload must be a mapping")
            proposal_id = str(record.get("proposal_id") or "")
            review = self._store.get_review(proposal_id)
            triple = (
                str(proposal.get("subject_type") or ""),
                str(proposal.get("predicate") or ""),
                str(proposal.get("object_type") or ""),
            )
            release = self._store.admission_release_for(*triple)
            decisions.append(
                self._policy.evaluate(
                    proposal,
                    entities=entities,
                    evidence_records=evidence_records,
                    scope=scope,
                    source_generation_id=source_generation_id,
                    review_status=str(review["status"]),
                    admission_release=release,
                    schema_version=str(
                        record.get("schema_version") or "proposal-schema-v1"
                    ),
                    policy_version=str(
                        record.get("policy_version") or "proposal-policy-v1"
                    ),
                )
            )
        return {
            "candidate": self._policy.assemble_candidate(
                deterministic_edges=deterministic_edges,
                proposal_decisions=decisions,
            ),
            "decisions": decisions,
        }


class BoundedEvidenceProcessor:
    """Collect, persist, and dispatch only contract-bounded evidence batches."""

    def __init__(
        self,
        *,
        store: OntologyRunStore,
        evidence_provider: EvidenceProvider,
        curator: Curator,
        planner_selection: PlannerSelection | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._evidence_provider = evidence_provider
        self._curator = curator
        self._planner_selection = planner_selection or select_planner()
        self._now = now or (lambda: datetime.now(UTC))

    async def advance(self, run: Mapping[str, Any]) -> CheckpointResult:
        self._planner_selection.require_supported()
        evidence = await self._evidence_provider.collect(run)
        try:
            batches = split_evidence_batches(
                changed_entities=_records(evidence, "changed_entities"),
                candidate_pairs=_records(evidence, "candidate_pairs"),
                evidence_records=_records(evidence, "evidence_records"),
                source_generation_id=str(
                    evidence.get("source_generation_id")
                    or run.get("source_generation_id")
                    or ""
                ),
                observed_at=_observed_at(evidence.get("observed_at")),
                freshness=str(evidence.get("freshness") or "unknown"),
                coverage=str(evidence.get("coverage") or "partial"),
            )
        except EvidenceBatchRejected as exc:
            raise RunProcessingFailure(
                failure_class=f"evidence_batch_{exc.reason.value}",
                checkpoint="evidence_batch_rejected",
                payload={
                    "reason": exc.reason.value,
                    "record_id": exc.record_id,
                },
                message=str(exc),
            ) from exc
        except (TypeError, ValueError) as exc:
            raise RunProcessingFailure(
                failure_class="evidence_batch_invalid",
                checkpoint="evidence_batch_rejected",
                payload={"reason": "invalid_contract"},
                message=str(exc),
            ) from exc

        dispatched_ids: list[str] = []
        for batch in batches:
            current = self._require_current(run, batch)
            persisted = self._store.save_evidence_batch(
                run_id=current["run_id"],
                batch=batch.to_dict(),
                now=self._now(),
            )
            if persisted["status"] != "dispatched":
                self._planner_selection.require_supported()
                try:
                    # Providers receive only scoped advisory context, not lease,
                    # review, checkpoint, cancellation or publication authority.
                    document = await self._curator.propose(
                        {
                            "source_generation_id": batch.source_generation_id,
                            "scope": batch.scope,
                        },
                        batch.to_dict(),
                    )
                    serialized = json.dumps(
                        document, separators=(",", ":"), allow_nan=False
                    )
                    if estimate_input_tokens(serialized) > HARD_MAX_OUTPUT_TOKENS:
                        raise CuratorInvalidOutput("curator_output_budget_exceeded")
                    result = parse_proposal_batch(serialized, batch=batch).model_dump(
                        mode="json"
                    )
                except (CuratorInvalidOutput, TypeError, ValueError):
                    raise RunProcessingFailure(
                        failure_class="curator_output_invalid",
                        checkpoint="evidence_dispatch_stopped",
                        payload={"reason": "curator_output_invalid"},
                        message="curator_output_invalid",
                    ) from None
                except Exception:  # noqa: BLE001 - sanitize arbitrary injected providers
                    raise RunProcessingFailure(
                        failure_class="curator_provider_failed",
                        checkpoint="evidence_dispatch_stopped",
                        payload={"reason": "curator_provider_failed"},
                        message="curator_provider_failed",
                    ) from None
                # Metadata is appended only AFTER strict document validation.
                # Store's existing result metadata preserves result.proposals.
                try:
                    result["provider_receipt"] = provider_receipt(
                        selection=self._planner_selection,
                        curator=self._curator,
                        result=result,
                    )
                except Exception:  # noqa: BLE001 - metadata access is a provider boundary
                    raise RunProcessingFailure(
                        failure_class="curator_provider_failed",
                        checkpoint="evidence_dispatch_stopped",
                        payload={"reason": "curator_provider_failed"},
                        message="curator_provider_failed",
                    ) from None
                self._require_current(run, batch)
                self._store.mark_evidence_batch_dispatched(
                    batch.batch_id,
                    expected_revision=persisted["revision"],
                    result=result,
                    now=self._now(),
                )

            dispatched_ids.append(batch.batch_id)
        return CheckpointResult(
            checkpoint="evidence_dispatched",
            payload={
                "batch_ids": dispatched_ids,
                "batch_count": len(dispatched_ids),
            },
            complete=True,
        )

    def _require_current(
        self, run: Mapping[str, Any], batch: EvidenceBatch
    ) -> dict[str, Any]:
        """Reject late/stale responses before making a result durable."""
        current = self._store.get(str(run.get("run_id") or ""))
        reason = ""
        if current is None:
            reason = "run_missing"
        elif current.get("cancel_requested"):
            reason = "run_cancelled"
        elif current["source_generation_id"] != batch.source_generation_id:
            reason = "source_generation_changed"
        elif self._now() >= datetime.fromisoformat(current["deadline_at"]):
            reason = "run_deadline_exceeded"
        elif run.get("fencing_token") and (
            current.get("fencing_token") != run["fencing_token"]
            or current.get("lease_owner") != run.get("lease_owner")
            or current.get("status") != run.get("status")
            or (
                current.get("lease_expires_at")
                and self._now() >= datetime.fromisoformat(current["lease_expires_at"])
            )
        ):
            reason = "run_lease_lost"
        if reason:
            raise RunProcessingFailure(
                failure_class=reason,
                checkpoint="evidence_dispatch_stopped",
                payload={"reason": reason, "unresolved_batch_ids": [batch.batch_id]},
                message=reason,
            )
        assert current is not None
        return current


class OntologyDiscoveryCoordinator:
    """Claim and advance a bounded set of runs from durable state alone."""

    def __init__(
        self,
        *,
        store: OntologyRunStore,
        processor: RunProcessor,
        owner: str,
        lease_seconds: int = 60,
        now=None,
    ) -> None:
        if not owner.strip():
            raise ValueError("owner must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._store = store
        self._processor = processor
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._now = now or (lambda: datetime.now(UTC))

    async def run_once(
        self, *, now: datetime | None = None, limit: int = 10
    ) -> dict[str, int]:
        """Advance at most ``limit`` due runs, isolating each failure."""
        moment = now or self._now()
        due = self._store.list_due(now=moment, limit=limit)
        counts = {
            "selected": len(due),
            "processed": 0,
            "retrying": 0,
            "failed": 0,
            "timed_out": 0,
            "cancelled": 0,
            "skipped_contended": 0,
            "lease_lost": 0,
            "errored": 0,
        }
        for record in due:
            run_id = record["run_id"]
            try:
                if moment >= datetime.fromisoformat(record["deadline_at"]):
                    self._store.expire(
                        run_id,
                        expected_revision=record["revision"],
                        actor=self._owner,
                        now=moment,
                    )
                    counts["timed_out"] += 1
                    continue
                if record["attempt_count"] >= record["max_attempts"]:
                    self._store.exhaust(
                        run_id,
                        expected_revision=record["revision"],
                        actor=self._owner,
                        now=moment,
                    )
                    counts["failed"] += 1
                    continue
                claimed = self._store.claim(
                    run_id,
                    expected_revision=record["revision"],
                    owner=self._owner,
                    lease_seconds=self._lease_seconds,
                    now=moment,
                )
                try:
                    result = await self._processor.advance(claimed)
                except RunProcessingFailure as exc:
                    checkpointed = self._store.checkpoint(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        name=exc.checkpoint,
                        payload=exc.payload,
                        now=moment,
                    )
                    failed = self._store.fail(
                        run_id,
                        expected_revision=checkpointed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        failure_class=exc.failure_class,
                        message=str(exc),
                        now=moment,
                    )
                    counts[
                        "retrying" if failed["status"] == RUN_RETRYING else "failed"
                    ] += 1
                    continue
                except Exception as exc:
                    failed = self._store.fail(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        failure_class="processor_error",
                        message=str(exc) or exc.__class__.__name__,
                        now=moment,
                    )
                    counts["retrying" if failed["status"] == RUN_RETRYING else "failed"] += 1
                    _LOGGER.exception(
                        "ontology_discovery_run_failed",
                        extra={"run_id": run_id},
                    )
                    continue
                if result.complete:
                    self._store.succeed(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        checkpoint=result.checkpoint,
                        payload=result.payload,
                        now=moment,
                    )
                    counts["processed"] += 1
                else:
                    self._store.checkpoint(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        name=result.checkpoint,
                        payload=result.payload,
                        now=moment,
                    )
                    counts["processed"] += 1
            except RunClaimConflict:
                counts["skipped_contended"] += 1
            except RunDeadlineExceeded:
                counts["timed_out"] += 1
            except RunLeaseLost:
                counts["lease_lost"] += 1
            except Exception:
                counts["errored"] += 1
                _LOGGER.exception(
                    "ontology_discovery_run_dispatch_failed",
                    extra={"run_id": run_id},
                )
        return counts


def _records(
    evidence: Mapping[str, Any], name: str
) -> list[Mapping[str, Any]]:
    value = evidence.get(name, ())
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a list of records")
    if any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"{name} must contain only records")
    return list(value)


def _observed_at(value: object) -> datetime:
    if isinstance(value, datetime):
        observed = value
    else:
        try:
            observed = datetime.fromisoformat(str(value or ""))
        except ValueError as exc:
            raise ValueError("observed_at must be an ISO timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return observed


__all__ = [
    "BoundedEvidenceProcessor",
    "DedicatedPublisher",
    "OntologyDiscoveryCoordinator",
    "ProposalPolicyCoordinator",
    "PublisherDispatchProcessor",
    "ValidatedCandidateProvider",
]
