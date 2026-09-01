"""Approval-gated execution of a single controlled-patch-recovery plan.

This is the only place in Phase 3 where HOG changes Azure state. The gate
here is the security boundary: an execute call must resolve exactly one
already-approved ``controlled-patch-recovery`` plan, and every parameter
handed to :class:`operations.patching.service.PatchingService` comes
verbatim from the stored plan -- never from the caller. See the phase
threat model (T-03-04, T-03-05) for the guarantees this enforces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.models import PatchTarget
from operations.patching.service import PatchingService, PatchValidationError

# The only action_id this phase authorizes for execution. Every other
# governed catalog action remains recommendation-only (EXEC-01).
CONTROLLED_PATCH_RECOVERY = "controlled-patch-recovery"


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
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._plans = plan_repository
        self._patching = patching_service
        self._store = execution_store
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

        execution_id = None
        if self._store is not None:
            record = self._store.create(plan_id, requested_by=requested_by)
            execution_id = record["execution_id"]
            self._store.update(execution_id, status="running")

        target, patch_ids = self._resolve_target(plan)
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
                self._store.update(execution_id, status="failed", message=message)
            return {
                "execution_id": execution_id,
                "plan_id": plan_id,
                "status": "failed",
                "message": message,
            }

        if execution_id is not None:
            self._store.update(
                execution_id,
                status="succeeded",
                provider_job_id=run.provider_job_id,
                message=run.message,
            )
        return {
            "execution_id": execution_id,
            "plan_id": plan_id,
            "status": "succeeded",
            "provider_job_id": run.provider_job_id,
            "message": run.message,
            "run_id": run.run_id,
        }

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

    def _resolve_target(self, plan: dict[str, Any]) -> tuple[PatchTarget, list[str]]:
        resource = plan.get("resource") or {}
        target_id = str(
            resource.get("id")
            or plan.get("resource_key")
            or ""
        ).strip()
        target = self._patching.target(target_id)
        if target is None:
            raise RemediationExecutionError(
                "No patch target matches this plan's resource",
                reason="target_not_found",
                details={"plan_id": plan.get("plan_id"), "target_id": target_id},
            )
        patch_ids = sorted(target.available_patch_ids)
        return target, patch_ids


__all__ = [
    "CONTROLLED_PATCH_RECOVERY",
    "RemediationExecutionError",
    "RemediationExecutionService",
]
