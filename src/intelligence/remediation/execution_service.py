"""Approval-gated execution of a single controlled-patch-recovery plan.

This is the only place in Phase 3 where HOG changes Azure state. The gate
here is the security boundary: an execute call must resolve exactly one
already-approved ``controlled-patch-recovery`` plan, and every parameter
handed to :class:`operations.patching.service.PatchingService` comes
verbatim from the stored plan -- never from the caller. See the phase
threat model (T-03-04, T-03-05) for the guarantees this enforces.
"""

from __future__ import annotations

import copy
import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.models import PatchTarget
from operations.patching.service import PatchingService, PatchValidationError

from .execution_store import ExecutionClaimConflict
from .execution_verifier import ExecutionVerificationUnavailable, ExecutionVerifier

# The only action_id this phase authorizes for execution. Every other
# governed catalog action remains recommendation-only (EXEC-01).
CONTROLLED_PATCH_RECOVERY = "controlled-patch-recovery"

# Bounded retry ceiling (T-03-11): a failing target cannot be retried
# indefinitely against Azure.
MAX_EXECUTION_ATTEMPTS = 3


class RemediationExecutionError(RuntimeError):
    """A plan is not eligible for execution right now.

    Raised before any target resolution or Azure call, matching the
    ``PatchValidationError`` convention: a stable ``reason`` code plus a
    ``details`` dict for the API layer to translate into a response.
    """

    def __init__(self, message: str, *, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details or {}


def validate_business_eligibility(plan: dict[str, Any]) -> None:
    """Reject plans whose business decision is not deterministically executable."""
    plan_id = str(plan.get("plan_id") or "")
    decision = plan.get("business_decision") or {}
    disposition = str(decision.get("disposition") or "")
    if disposition not in {"act_now", "schedule"}:
        raise RemediationExecutionError(
            "The business decision disposition is not executable",
            reason="disposition_not_executable",
            details={"plan_id": plan_id, "disposition": disposition},
        )
    impact_status = str((decision.get("business_impact") or {}).get("status") or "")
    if impact_status != "known":
        raise RemediationExecutionError(
            "Business impact must be known before execution",
            reason="business_impact_unknown",
            details={"plan_id": plan_id, "status": impact_status},
        )
    review_requirements = list(decision.get("review_requirements") or [])
    if review_requirements:
        raise RemediationExecutionError(
            "Outstanding review requirements block execution",
            reason="review_required",
            details={"plan_id": plan_id, "review_requirements": review_requirements},
        )
    unknowns = list(decision.get("unknowns") or [])
    if unknowns:
        raise RemediationExecutionError(
            "Unresolved business-decision unknowns block execution",
            reason="decision_unknowns_present",
            details={"plan_id": plan_id, "unknowns": unknowns},
        )
    decision_citations = list(
        (decision.get("urgency_rationale") or {}).get("evidence_citations") or []
    )
    if not decision_citations:
        raise RemediationExecutionError(
            "The business decision has no urgency evidence citations",
            reason="decision_evidence_missing",
            details={"plan_id": plan_id},
        )
    if not list(plan.get("evidence_citations") or []):
        raise RemediationExecutionError(
            "The remediation plan has no evidence citations",
            reason="plan_evidence_missing",
            details={"plan_id": plan_id},
        )


class RemediationExecutionService:
    """Thin, bounded adapter from an approved plan to ``PatchingService.trigger``.

    Introduces no parallel ARM-calling code: everything past the approval
    gate delegates to the existing, unmodified patching stack.
    """

    def __init__(
        self,
        *,
        plan_repository: Any,
        patching_service: PatchingService,
        execution_store: Any | None = None,
        execution_verifier: ExecutionVerifier | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._plans = plan_repository
        self._patching = patching_service
        self._store = execution_store
        self._verifier = execution_verifier
        self._now = now

    def execute(self, plan_id: str, *, requested_by: str) -> dict[str, Any]:
        """Execute ``plan_id`` if -- and only if -- it is currently approved.

        Takes no target/patch/operation parameter: everything comes from
        the stored, already-approved plan. Raises
        :class:`RemediationExecutionError` for every rejection case listed
        below, before any patching-service call or Azure request.
        """
        plan = self._plans.get(plan_id)
        if plan is None:
            raise RemediationExecutionError(
                f"Remediation plan {plan_id!r} was not found",
                reason="plan_not_found",
                details={"plan_id": plan_id},
            )

        decision = self._check_approval_gate(plan)
        snapshot = self._validated_execution_snapshot(plan, decision)

        execution_id = None
        if self._store is not None:
            rollback_guidance = list(
                (plan.get("rollback_plan") or {}).get("rollback_actions") or []
            )
            record, claimed = self._store.create_or_get(
                plan_id,
                requested_by=requested_by,
                approved_by=str(decision.get("approver") or ""),
                execution_snapshot=snapshot,
                rollback_guidance=rollback_guidance,
                now=self._now(),
            )
            execution_id = record["execution_id"]
            if not claimed:
                return self.execution_view(record)
            record = self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="queued",
                status="running",
                actor=requested_by,
                now=self._now(),
            )

        return self._submit_and_record(
            plan=plan,
            decision=decision,
            requested_by=requested_by,
            execution_id=execution_id,
        )

    def _check_approval_gate(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Run the four approval-gate checks against ``plan``'s *current* state.

        Shared verbatim by :meth:`execute` and :meth:`retry` so the two
        code paths cannot drift apart (T-03-10): action_id allowlist,
        approval status, action_version currency, and expiry.
        """
        plan_id = str(plan.get("plan_id") or "")
        action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
        if action_id != CONTROLLED_PATCH_RECOVERY:
            raise RemediationExecutionError(
                "Only a controlled-patch-recovery plan may be executed in this phase",
                reason="action_not_executable",
                details={"plan_id": plan_id, "action_id": action_id},
            )

        decision = self._latest_decision(plan_id)
        current_action_version = str(plan.get("action_version") or "")
        if decision is None or decision.get("decision") != "approved":
            raise RemediationExecutionError(
                "This plan has no approved decision on record",
                reason="not_approved",
                details={"plan_id": plan_id},
            )
        if str(decision.get("action_version") or "") != current_action_version:
            raise RemediationExecutionError(
                "The approved decision no longer matches this plan's current action_version",
                reason="stale_approval",
                details={
                    "plan_id": plan_id,
                    "approved_action_version": decision.get("action_version"),
                    "current_action_version": current_action_version,
                },
            )
        if self._is_expired(decision.get("expires_at")):
            raise RemediationExecutionError(
                "The approved decision has expired",
                reason="approval_expired",
                details={"plan_id": plan_id, "expires_at": decision.get("expires_at")},
            )
        validate_business_eligibility(plan)
        self._validated_execution_snapshot(plan, decision)
        return decision

    def _submit_and_record(
        self,
        *,
        plan: dict[str, Any],
        decision: dict[str, Any],
        requested_by: str,
        execution_id: str | None,
    ) -> dict[str, Any]:
        plan_id = str(plan.get("plan_id") or "")
        target, patch_ids = self._resolve_target(plan, decision)
        try:
            run = self._patching.trigger(
                target=target,
                patch_ids=patch_ids,
                requested_by=requested_by,
                approved_by=str(decision.get("approver") or ""),
                dry_run=False,
            )
        except (PatchValidationError, PatchExecutionUnavailable) as exc:
            message = str(exc)
            if execution_id is not None:
                current = self._store.get(execution_id)
                self._store.transition(
                    execution_id,
                    expected_revision=int(current.get("revision") or 0),
                    expected_status={"running", "retrying"},
                    status="failed",
                    actor=requested_by,
                    message=message,
                    failure_details=message,
                    outcome="failed",
                    now=self._now(),
                )
            if execution_id is not None:
                return self.execution_view(self._store.get(execution_id))
            return {
                "execution_id": execution_id,
                "plan_id": plan_id,
                "status": "failed",
                "message": message,
            }

        # Azure exposes no idempotency token for these operations.  The
        # durable pre-submit claim is therefore the safety boundary, and an
        # accepted response can only ever mean "running".  Only verifier
        # polling may persist a terminal provider outcome.
        terminal_status = "running"
        message = run.message
        if self._verifier is None:
            message = _append_note(
                message,
                "Verification unavailable: no execution verifier is configured",
            )
        if execution_id is not None:
            current = self._store.get(execution_id)
            self._store.transition(
                execution_id,
                expected_revision=int(current.get("revision") or 0),
                expected_status={"running", "retrying"},
                status=terminal_status,
                actor=requested_by,
                provider_job_id=run.provider_job_id,
                message=message,
                now=self._now(),
            )
            return self.execution_view(self._store.get(execution_id))
        return {
            "execution_id": execution_id,
            "plan_id": plan_id,
            "status": terminal_status,
            "provider_job_id": run.provider_job_id,
            "message": message,
            "run_id": run.run_id,
        }

    def retry(self, execution_id: str) -> dict[str, Any]:
        """Retry a failed/retrying execution: bounded, idempotent, revalidated.

        Rejects (never resubmits) when the execution is already
        ``"succeeded"`` (idempotency) or has reached
        :data:`MAX_EXECUTION_ATTEMPTS` (bounded), and re-runs the identical
        approval-gate checks from :meth:`execute` against the plan's
        *current* state before resubmitting (revalidation, T-03-10).
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to retry",
                reason="store_not_configured",
                details={"execution_id": execution_id},
            )
        record = self._store.get(execution_id)
        if record is None:
            raise RemediationExecutionError(
                f"Execution {execution_id!r} was not found",
                reason="execution_not_found",
                details={"execution_id": execution_id},
            )

        status = str(record.get("status") or "")
        if status not in {"failed", "cancelled"}:
            raise RemediationExecutionError(
                "This execution is not in a retryable terminal state",
                reason="execution_not_retryable",
                details={"execution_id": execution_id, "status": status},
            )

        plan_id = str(record.get("plan_id") or "")
        plan = self._plans.get(plan_id)
        if plan is None:
            raise RemediationExecutionError(
                f"Remediation plan {plan_id!r} was not found",
                reason="plan_not_found",
                details={"plan_id": plan_id},
            )

        # Revalidate the plan's *current* approval/target state -- it may
        # have changed since the original attempt even though this
        # execution was itself once approved.
        decision = self._check_approval_gate(plan)
        approved_snapshot = self._validated_execution_snapshot(plan, decision)
        immutable_snapshot = record.get("execution_snapshot") or {}
        if (
            execution_snapshot_hash(approved_snapshot)
            != execution_snapshot_hash(immutable_snapshot)
        ):
            raise RemediationExecutionError(
                "The current approval no longer matches the execution's immutable snapshot",
                reason="execution_snapshot_changed",
                details={"execution_id": execution_id, "plan_id": plan_id},
            )
        immutable_decision = dict(decision)
        immutable_decision["execution_snapshot"] = immutable_snapshot

        try:
            claimed = self._store.claim_retry(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                actor=str(record.get("requested_by") or ""),
                max_attempts=MAX_EXECUTION_ATTEMPTS,
                now=self._now(),
            )
            self._store.transition(
                execution_id,
                expected_revision=int(claimed.get("revision") or 0),
                expected_status="retrying",
                status="running",
                actor=str(record.get("requested_by") or ""),
                now=self._now(),
            )
        except ExecutionClaimConflict as exc:
            raise RemediationExecutionError(
                "Another lifecycle operation already claimed this execution",
                reason=exc.reason,
                details={
                    "execution_id": execution_id,
                    "status": exc.record.get("status"),
                    "revision": exc.record.get("revision"),
                },
            ) from exc

        return self._submit_and_record(
            plan=plan,
            decision=immutable_decision,
            requested_by=str(record.get("requested_by") or ""),
            execution_id=execution_id,
        )

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Return a server-projected execution record without polling it."""
        if self._store is None:
            return None
        record = self._store.get(execution_id)
        return self.execution_view(record) if record is not None else None

    def list_executions(self, plan_id: str) -> list[dict[str, Any]]:
        """Return all execution identities for a plan with eligibility fields."""
        if self._store is None:
            return []
        return [
            self.execution_view(record)
            for record in self._store.list_for_plan(plan_id)
        ]

    def plan_eligibility(self, plan_id: str) -> dict[str, Any]:
        """Project whether the current durable plan can be executed."""
        plan = self._plans.get(plan_id)
        if plan is None:
            return {"executable": False, "ineligibility_reason": "plan_not_found"}
        try:
            self._check_approval_gate(plan)
        except RemediationExecutionError as exc:
            return {"executable": False, "ineligibility_reason": exc.reason}
        return {"executable": True, "ineligibility_reason": ""}

    @staticmethod
    def execution_view(record: dict[str, Any]) -> dict[str, Any]:
        """Add authoritative retry/cancel eligibility to a durable record."""
        view = copy.deepcopy(record)
        attempts = int(view.get("attempt_count") or 0)
        remaining = max(0, MAX_EXECUTION_ATTEMPTS - attempts)
        status = str(view.get("status") or "")
        retryable = status in {"failed", "cancelled"} and remaining > 0
        cancellable = (
            status == "queued" and not bool(view.get("provider_job_id"))
        )
        explicit = str(view.get("ineligibility_reason") or "")
        if explicit:
            reason = explicit
        elif status == "running" and view.get("provider_job_id"):
            reason = "provider_not_cancellable"
        elif status == "succeeded":
            reason = "already_succeeded"
        elif status in {"failed", "cancelled"} and remaining == 0:
            reason = "max_attempts_exceeded"
        elif retryable or cancellable:
            reason = ""
        else:
            reason = "execution_not_retryable"
        view.update(
            {
                "retryable": retryable,
                "cancellable": cancellable,
                "remaining_attempts": remaining,
                "ineligibility_reason": reason,
            }
        )
        return view

    def cancel(self, execution_id: str, *, requested_by: str) -> dict[str, Any]:
        """Cancel queued local work or record that provider work cannot cancel."""
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to cancel",
                reason="store_not_configured",
                details={"execution_id": execution_id},
            )
        record = self._store.get(execution_id)
        if record is None:
            raise RemediationExecutionError(
                f"Execution {execution_id!r} was not found",
                reason="execution_not_found",
                details={"execution_id": execution_id},
            )
        if record.get("status") == "queued" and not record.get("provider_job_id"):
            try:
                cancelled = self._store.claim_cancel(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    actor=requested_by,
                    now=self._now(),
                )
            except ExecutionClaimConflict as exc:
                raise RemediationExecutionError(
                    "Another lifecycle operation already claimed this execution",
                    reason=exc.reason,
                    details={"execution_id": execution_id},
                ) from exc
            return self.execution_view(cancelled)
        if record.get("status") == "running" or record.get("provider_job_id"):
            message = _append_note(
                record.get("message"),
                "Provider operation cannot be safely cancelled; monitor it to completion.",
            )
            try:
                current = self._store.transition(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status=str(record.get("status") or ""),
                    status=str(record.get("status") or ""),
                    actor=requested_by,
                    outcome="provider_not_cancellable",
                    message=message,
                    ineligibility_reason="provider_not_cancellable",
                    now=self._now(),
                )
            except ExecutionClaimConflict:
                current = self._store.get(execution_id)
            return self.execution_view(current)
        view = self.execution_view(record)
        view["ineligibility_reason"] = "execution_not_cancellable"
        return view


    def poll_verification(self, execution_id: str) -> dict[str, Any]:
        """Poll the real upstream source of truth for one running execution.

        A terminal ARM outcome ("succeeded"/"failed") updates the stored
        record accordingly. A still-running outcome is a no-op -- the
        record stays "running". A not-verifiable or verification-unavailable
        result leaves ``status`` unchanged but appends a note to ``message``
        so a poller can see verification itself is degraded, without
        falsely claiming success or failure.
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to poll",
                reason="store_not_configured",
                details={"execution_id": execution_id},
            )
        record = self._store.get(execution_id)
        if record is None:
            raise RemediationExecutionError(
                f"Execution {execution_id!r} was not found",
                reason="execution_not_found",
                details={"execution_id": execution_id},
            )
        if record.get("status") != "running":
            return self.execution_view(record)
        if self._verifier is None:
            note = "Verification unavailable: no execution verifier is configured"
            message = _append_note(record.get("message"), note)
            if message == record.get("message"):
                return self.execution_view(record)
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="running",
                actor="execution-verifier",
                message=message,
                now=self._now(),
            ))

        try:
            outcome = self._verifier.verify(record)
        except ExecutionVerificationUnavailable as exc:
            note = f"Verification unavailable: {exc}"
            message = _append_note(record.get("message"), note)
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="running",
                actor="execution-verifier",
                message=message,
                now=self._now(),
            ))

        if not outcome.get("verifiable", False):
            note = f"Verification not available: {outcome.get('reason', 'unknown')}"
            message = _append_note(record.get("message"), note)
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="running",
                actor="execution-verifier",
                message=message,
                now=self._now(),
            ))

        result_outcome = outcome.get("outcome")
        if result_outcome == "succeeded":
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="succeeded",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                outcome="succeeded",
                now=self._now(),
            ))
        if result_outcome == "failed":
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="failed",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                failure_details=outcome.get("failure_details", ""),
                outcome="failed",
                now=self._now(),
            ))
        if result_outcome == "cancelled":
            return self.execution_view(self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="cancelled",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                failure_details=outcome.get("failure_details", ""),
                outcome="cancelled",
                now=self._now(),
            ))
        # Still running -- no-op, but record the latest verified_state seen.
        return self.execution_view(self._store.transition(
            execution_id,
            expected_revision=int(record.get("revision") or 0),
            expected_status="running",
            status="running",
            actor="execution-verifier",
            verified_state=outcome.get("verified_state", ""),
            now=self._now(),
        ))

    def _latest_decision(self, plan_id: str) -> dict[str, Any] | None:
        decisions = self._plans.decisions.list(plan_id) if hasattr(self._plans, "decisions") else []
        if not decisions:
            return None
        return max(decisions, key=lambda row: str(row.get("decided_at") or ""))

    def _is_expired(self, expires_at: Any) -> bool:
        text = str(expires_at or "").strip()
        if not text:
            return True
        try:
            expiry = datetime.fromisoformat(text)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return expiry <= self._now()

    def _validated_execution_snapshot(
        self, plan: dict[str, Any], decision: dict[str, Any]
    ) -> dict[str, Any]:
        plan_id = str(plan.get("plan_id") or "")
        snapshot = decision.get("execution_snapshot")
        if not isinstance(snapshot, dict):
            raise RemediationExecutionError(
                "The approved decision has no executable snapshot",
                reason="execution_snapshot_missing",
                details={"plan_id": plan_id},
            )
        patch_ids = snapshot.get("patch_ids")
        target_id = str(snapshot.get("target_id") or "").strip()
        snapshot_version = str(snapshot.get("action_version") or "")
        expected_version = str(plan.get("action_version") or "")
        supplied_hash = str(snapshot.get("snapshot_hash") or "")
        expected_hash = execution_snapshot_hash(snapshot)
        if (
            not target_id
            or not isinstance(patch_ids, list)
            or not patch_ids
            or any(not isinstance(item, str) or not item.strip() for item in patch_ids)
            or snapshot_version != expected_version
            or snapshot_version != str(decision.get("action_version") or "")
            or not hmac.compare_digest(supplied_hash, expected_hash)
        ):
            raise RemediationExecutionError(
                "The approved execution snapshot is invalid or has been altered",
                reason="execution_snapshot_invalid",
                details={"plan_id": plan_id},
            )
        return snapshot

    def _resolve_target(
        self, plan: dict[str, Any], decision: dict[str, Any]
    ) -> tuple[PatchTarget, list[str]]:
        snapshot = self._validated_execution_snapshot(plan, decision)
        target_id = str(snapshot["target_id"])
        target = self._patching.target(target_id)
        if target is None:
            raise RemediationExecutionError(
                "No patch target matches this plan's resource",
                reason="target_not_found",
                details={"plan_id": plan.get("plan_id"), "target_id": target_id},
            )
        patch_ids = list(snapshot["patch_ids"])
        unavailable = sorted(
            patch_id for patch_id in patch_ids if patch_id not in target.available_patch_ids
        )
        if (
            unavailable
            or target.inventory_kind != snapshot.get("target_kind")
            or target.operation != snapshot.get("operation")
        ):
            raise RemediationExecutionError(
                "The approved execution snapshot no longer matches the patch target",
                reason="execution_snapshot_drift",
                details={
                    "plan_id": plan.get("plan_id"),
                    "target_id": target_id,
                    "unavailable_patch_ids": unavailable,
                },
            )
        return target, patch_ids


def _append_note(existing_message: Any, note: str) -> str:
    text = str(existing_message or "").strip()
    if not text:
        return note
    if note in text:
        return text
    return f"{text} | {note}"


__all__ = [
    "CONTROLLED_PATCH_RECOVERY",
    "MAX_EXECUTION_ATTEMPTS",
    "RemediationExecutionError",
    "RemediationExecutionService",
    "validate_business_eligibility",
]
