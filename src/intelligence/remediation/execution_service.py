"""Approval-gated execution of a single bounded remediation plan.

The gate here is the security boundary: execution resolves exactly one
already-approved patch action or explicit Defender configuration action, and
every provider parameter comes from the server-owned snapshot, never the
caller.
"""

from __future__ import annotations

import copy
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from api.scope import scope_attributes
from intelligence.remediation.action_catalog import EXECUTABLE_ACTION_IDS
from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.approval_gate import (
    is_self_approval,
    requirement_satisfaction,
)
from operations.defender_configuration import (
    DEFENDER_CONFIGURATION_ACTION_IDS,
    DefenderConfigurationUnavailable,
    UnconfiguredDefenderConfigurationAdapter,
    build_defender_configuration_snapshot,
)
from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.models import PatchTarget
from operations.patching.service import PatchingService, PatchValidationError
from operations.patching.sre_agent_adapter import SRE_AGENT_PROVIDER

from .execution_store import (
    ExecutionClaimConflict,
    _is_patch_evidence_candidate,
    execution_scope_attributes,
    is_submission_ambiguous,
    submitted_attempt_count,
)
from .execution_verifier import ExecutionVerificationUnavailable, ExecutionVerifier

# Patch recovery and the small code-authored Defender configuration catalog
# are the only execution families. All other recommendations remain review-only.
CONTROLLED_PATCH_RECOVERY = "controlled-patch-recovery"

# Bounded retry ceiling (T-03-11): a failing target cannot be retried
# indefinitely against Azure.
MAX_EXECUTION_ATTEMPTS = 3

# Recommendation 3 (Deadline and Recovery): every provider-submitted
# execution reaches a terminal outcome by this deadline, never staying
# "running"/"submission_ambiguous" indefinitely. 30 minutes.
VERIFICATION_DEADLINE_SECONDS = 1800.0


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
    """Dispatch an approved snapshot to one typed, bounded provider adapter."""

    def __init__(
        self,
        *,
        plan_repository: Any,
        patching_service: PatchingService | None,
        defender_configuration_adapter: Any | None = None,
        execution_store: Any | None = None,
        execution_verifier: ExecutionVerifier | None = None,
        verification_deadline_seconds: float = VERIFICATION_DEADLINE_SECONDS,
        target_evidence_refresher: Callable[[str, str], dict[str, Any] | None] | None = None,
        allow_self_approval: Callable[[], bool] | bool = False,
        policy_version_resolver: Callable[[], str] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._plans = plan_repository
        self._patching = patching_service
        self._defender_configuration = (
            defender_configuration_adapter
            or UnconfiguredDefenderConfigurationAdapter()
        )
        self._store = execution_store
        self._verifier = execution_verifier
        self._verification_deadline_seconds = verification_deadline_seconds
        self._evidence_refresher = target_evidence_refresher
        # Cross-family self-approval exception (Phase 03.5, D-02): resolved
        # per call, not captured at construction, mirroring
        # PatchingService's identical pattern. Defaults closed so a
        # service built without the policy fails closed. This is the
        # shared gate's OWN policy -- independent of
        # PatchingService._allow_self_approval, which remains as defense
        # in depth for the patch family specifically (its own
        # pre-existing, non-raising, budget-neutral refusal path inside
        # PatchingService.trigger is untouched).
        self._allow_self_approval: Callable[[], bool] = (
            allow_self_approval
            if callable(allow_self_approval)
            else (lambda value=allow_self_approval: bool(value))
        )
        # WR-02 fix: resolved per call so the gate compares each decision
        # against the plan's *live* ApprovalEngine.policy_version -- the
        # same value ``approval_gate.policy_version_for(planner)`` projects
        # at the read-side routes -- rather than reusing the very decision
        # being evaluated's own recorded value (a self-referential
        # comparison that could never detect an actual policy change).
        # Defaults to a constant "" resolver when not wired, matching the
        # documented interim behavior for callers (e.g. the verification
        # coordinator) that have no live planner to consult at all.
        self._policy_version_resolver: Callable[[], str] = policy_version_resolver or (
            lambda: ""
        )
        self._now = now

    def _claim_schedule_fields(self) -> dict[str, Any]:
        """Scheduling fields seeded at every ``running``/``retrying`` claim.

        CR-01: computed once and passed into the *same* CAS write that
        claims ``"running"``/``"retrying"``, never only into a later,
        separate write -- so no crash window exists between a claim and the
        record becoming durably deadline-bound and due-for-recovery.
        ``_submit_and_record``'s own scheduling writes then simply
        re-confirm the identical values (idempotent), rather than being the
        only place they are ever established.
        """
        return {
            "verification_deadline_at": (
                self._now() + timedelta(seconds=self._verification_deadline_seconds)
            ).isoformat(),
            "next_verification_at": self._now().isoformat(),
            "verification_attempts": 0,
        }

    def execute(self, plan_id: str, *, requested_by: str) -> dict[str, Any]:
        """Execute ``plan_id`` if -- and only if -- it is currently approved.

        Takes no target/patch/operation parameter: everything comes from
        the stored, already-approved plan. Raises
        :class:`RemediationExecutionError` for every rejection case listed
        below, before any patching-service call or Azure request.
        """
        if self._plans is None:
            raise RemediationExecutionError(
                f"No remediation plan repository is configured; cannot execute {plan_id!r}",
                reason="plan_repository_unavailable",
                details={"plan_id": plan_id},
            )
        plan = self._plans.get(plan_id)
        if plan is None:
            raise RemediationExecutionError(
                f"Remediation plan {plan_id!r} was not found",
                reason="plan_not_found",
                details={"plan_id": plan_id},
            )

        decision, self_approved_decision_ids = self._check_approval_gate(
            plan, requested_by=requested_by
        )
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
                approval_decision_id=str(decision.get("decision_id") or ""),
                approval_decided_at=str(decision.get("decided_at") or ""),
                execution_snapshot=snapshot,
                rollback_guidance=rollback_guidance,
                scope_attributes={
                    **scope_attributes(plan.get("resource") or {}),
                    **scope_attributes(plan),
                },
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
                **self._claim_schedule_fields(),
            )

        # WR-03 fix: only now, with the execution durably claimed (or, when
        # no store is configured, immediately before dispatch) is
        # self-approval consumption recorded -- never earlier, when a later
        # step (the snapshot validation above, the store claim itself)
        # could still have raised and left a "self-approval was used"
        # audit fact for an execution that never actually proceeded.
        self._finalize_self_approvals(self_approved_decision_ids)
        return self._submit_and_record(
            plan=plan,
            decision=decision,
            requested_by=requested_by,
            execution_id=execution_id,
        )

    def _check_approval_gate(
        self, plan: dict[str, Any], *, requested_by: str = ""
    ) -> tuple[dict[str, Any], frozenset[str]]:
        """Run the approval-gate checks against ``plan``'s *current* state.

        Shared verbatim by :meth:`execute` and :meth:`retry` so the two
        code paths cannot drift apart (T-03-10): action_id allowlist,
        approval status, action_version currency, expiry, per-role
        ``approval_requirements`` satisfaction (Phase 03.5, D-01), and
        cross-family requester-vs-approver separation of duties (D-02).

        ``requested_by`` is optional and empty for :meth:`plan_eligibility`
        (a pure "can this plan run at all" projection, identity-blind by
        design per 03.5-UI-SPEC.md's Authorization Contract) -- an empty
        string can never equal a real approver identity
        (:func:`is_self_approval` treats empty as never-equal), so passing
        it is a safe no-op for that caller.

        Returns ``(decision, self_approved_decision_ids)``: ``decision`` is
        the plan's overall-latest decision (used for the not_approved/
        stale_approval/approval_expired checks above, and by callers for
        ``approved_by``/snapshot validation); ``self_approved_decision_ids``
        is the set of decision ids that were found to be a self-approval of
        a *satisfied requirement row* during this call and are pending a
        durable ``record_self_approval`` write (CR-02/WR-03 fix) -- deferred
        to :meth:`_finalize_self_approvals`, called only once the caller
        has confirmed execution is actually going to proceed, never here.
        """
        plan_id = str(plan.get("plan_id") or "")
        action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
        if action_id not in EXECUTABLE_ACTION_IDS:
            raise RemediationExecutionError(
                "This recommendation has no supported direct execution action",
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

        # Per-role approval_requirements satisfaction (Phase 03.5, D-01):
        # the single "some decision exists" check above is not sufficient
        # for a plan requiring multiple distinct roles -- every row must be
        # independently satisfied (CR-04, REVIEW recommendation 4).
        decisions_for_plan = (
            self._plans.decisions.list(plan_id) if hasattr(self._plans, "decisions") else []
        )
        requirements = plan.get("approval_requirements") or []
        # NOTE (documented interim simplification, Plan 03.5-05): a freshly
        # rebuilt preview snapshot_hash is not directly reachable from
        # RemediationExecutionService without new plumbing beyond this
        # plan's budget. current_snapshot_hash is left empty (never
        # triggers stale_evidence_snapshot here -- that comparison is
        # covered by _validated_execution_snapshot's own hmac check above).
        # policy_version, however, IS independently sourced (WR-02 fix) via
        # self._policy_version_resolver(), the same live
        # ApprovalEngine.policy_version the read-side routes project --
        # never the decision's own recorded value, which would make the
        # comparison self-referentially always-true for the very decision
        # matching each row.
        satisfaction = requirement_satisfaction(
            requirements,
            decisions_for_plan,
            current_action_version=current_action_version,
            current_snapshot_hash="",
            policy_version=self._policy_version_resolver(),
            now=self._now(),
        )
        unmet = [row for row in satisfaction if not row.get("satisfied")]
        if unmet:
            raise RemediationExecutionError(
                "This plan's approval requirements are not fully satisfied",
                reason="approval_requirements_unmet",
                details={
                    "plan_id": plan_id,
                    "unmet": [
                        {
                            "policy_id": row.get("policy_id"),
                            "role": row.get("role"),
                            "stage": row.get("stage"),
                            "unmet_reason": row.get("unmet_reason"),
                        }
                        for row in unmet
                    ],
                },
            )

        # Cross-family requester-vs-approver separation of duties (Phase
        # 03.5, D-02): previously enforced only against the plan's single
        # overall-latest decision, which missed a requester who
        # self-approved one *earlier* required row while a different,
        # legitimate approver later signed another row (CR-02). Checked
        # here against EVERY candidate decision that matters: the plan's
        # overall-latest ``decision`` (the baseline the pre-03.5-05 gate
        # always checked, and still the only candidate for a plan with zero
        # distinct ``approval_requirements`` rows, e.g. a family whose
        # default policy carries no rows at all) *and* every required
        # row's own satisfying decision (closing CR-02's per-row gap for
        # plans that DO carry rows). Deduplicated by decision_id so a
        # decision satisfying several rows -- or matching both the overall
        # latest and a row -- is only ever flagged/finalized once. Runs
        # identically for both families, before either adapter is ever
        # reached.
        self_approved_decision_ids: set[str] = set()
        if requested_by:
            candidates: list[tuple[Any, Any]] = [
                (decision.get("decision_id"), decision.get("approver"))
            ]
            candidates.extend(
                (row.get("decision_id"), row.get("approver"))
                for row in satisfaction
                if row.get("satisfied")
            )
            seen_decision_ids: set[str] = set()
            for decision_id, approver in candidates:
                key = str(decision_id) if decision_id else None
                if key is not None:
                    if key in seen_decision_ids:
                        continue
                    seen_decision_ids.add(key)
                if approver is None:
                    continue
                if is_self_approval(requested_by, approver):
                    if not self._allow_self_approval():
                        raise RemediationExecutionError(
                            "The approver must be someone other than the requester",
                            reason="self_approval_not_permitted",
                            details={"plan_id": plan_id},
                        )
                    if decision_id:
                        self_approved_decision_ids.add(str(decision_id))
        return decision, frozenset(self_approved_decision_ids)

    def _finalize_self_approvals(self, decision_ids: frozenset[str]) -> None:
        """Durably record self-approval only once execution is guaranteed to proceed.

        Deferred from :meth:`_check_approval_gate` itself (WR-03 fix): that
        method previously called ``record_self_approval`` immediately, which
        could durably, irreversibly mark a decision ``self_approved: true``
        even when a later step in the same request (execution snapshot
        mismatch, target no longer found, store conflict) meant the
        execution never actually proceeded. Callers invoke this only after
        their own store claim (or, when no store is configured, immediately
        before dispatch) succeeds -- ``record_self_approval`` is itself
        idempotent, so calling it once per decision id per successful claim
        is always safe.
        """
        if not decision_ids or not hasattr(self._plans, "decisions"):
            return
        for decision_id in decision_ids:
            self._plans.decisions.record_self_approval(
                decision_id, policy_id="demo-self-approval"
            )

    def build_execution_snapshot(
        self, plan: dict[str, Any], *, scope: Any = None
    ) -> dict[str, Any]:
        """Build the exact current action for preview and approval."""
        from intelligence.remediation.approval_decisions import build_execution_snapshot

        return build_execution_snapshot(
            plan,
            self._patching,
            configuration_adapter=self._defender_configuration,
            scope=scope,
        )

    def allow_self_approval(self) -> bool:
        """Public read of the gate's current self-approval policy.

        Resolved per call, matching ``_allow_self_approval``'s own
        callable-vs-bool normalization -- used by the read-side workflow
        route (Phase 03.5, D-05) to render the demo self-approval
        disclosure banner only when this policy is actually enabled,
        never a client-side guess.
        """
        return bool(self._allow_self_approval())

    def _submit_and_record(
        self,
        *,
        plan: dict[str, Any],
        decision: dict[str, Any],
        requested_by: str,
        execution_id: str | None,
    ) -> dict[str, Any]:
        plan_id = str(plan.get("plan_id") or "")
        action_id = str(plan.get("action_id") or plan.get("opportunity_type") or "")
        intended_provider = self._intended_provider(action_id)
        try:
            target, patch_ids = self._resolve_target(plan, decision)
        except RemediationExecutionError as exc:
            # Target and allowlist revalidation happens after the durable
            # attempt claim. Persist that refusal as a terminal attempt rather
            # than leaving an execution permanently "running" when inventory
            # changes between approval and submission. Proven pre-submission
            # by construction: this fires before any adapter is ever called,
            # so it must never consume the Azure submission budget
            # (Recommendation 2, Submission Accounting decision).
            if execution_id is None:
                raise
            current = self._store.get(execution_id)
            if current is None:
                raise
            self._store.transition(
                execution_id,
                expected_revision=int(current.get("revision") or 0),
                expected_status={"running", "retrying"},
                status="failed",
                actor=requested_by,
                provider=intended_provider,
                message=str(exc),
                failure_details=str(exc),
                outcome="failed",
                provider_submitted=False,
                failure_class="target_precondition",
                now=self._now(),
            )
            return self.execution_view(self._store.get(execution_id))
        try:
            if action_id in DEFENDER_CONFIGURATION_ACTION_IDS:
                run = self._defender_configuration.submit(
                    self._validated_execution_snapshot(plan, decision)
                )
            else:
                if self._patching is None:
                    raise PatchExecutionUnavailable(
                        "Patch execution is not configured for this deployment."
                    )
                run = self._patching.trigger(
                    target=target,
                    patch_ids=patch_ids,
                    requested_by=requested_by,
                    approved_by=str(decision.get("approver") or ""),
                    dry_run=False,
                    approval_context={
                        "decision_id": str(decision.get("decision_id") or ""),
                        "decision": str(decision.get("decision") or ""),
                        "decided_at": str(decision.get("decided_at") or ""),
                        "expires_at": str(decision.get("expires_at") or ""),
                        "approved_by": str(decision.get("approver") or ""),
                        "execution_snapshot": {
                            field: copy.deepcopy(
                                (decision.get("execution_snapshot") or {}).get(field)
                            )
                            for field in (
                                "target_id",
                                "patch_ids",
                                "target_kind",
                                "operation",
                                "action_version",
                                "snapshot_hash",
                            )
                        },
                    },
                )
        except (
            DefenderConfigurationUnavailable,
            PatchValidationError,
            PatchExecutionUnavailable,
        ) as exc:
            message = str(exc)
            # PatchValidationError only ever fires inside
            # PatchingService.trigger before self._adapter.submit() is
            # reached (per its own docstring) -- always pre-submission.
            # DefenderConfigurationUnavailable/PatchExecutionUnavailable
            # carry their own classification from Plan 03.3-01's adapter
            # boundary; read it directly off the caught exception, falling
            # back to the same fail-closed default the adapters themselves
            # use if a future adapter forgets to classify.
            if isinstance(exc, PatchValidationError):
                provider_submitted = False
                failure_class = "internal_validation"
            else:
                provider_submitted = bool(getattr(exc, "provider_submitted", True))
                failure_class = str(
                    getattr(exc, "failure_class", "") or "submission_ambiguous"
                )
            if execution_id is not None:
                current = self._store.get(execution_id)
                schedule_fields: dict[str, Any] = {}
                if failure_class == "submission_ambiguous":
                    # Only an ambiguous submission needs reconciliation
                    # scheduling -- a plain provider_rejected/
                    # provider_authorization/target_precondition/
                    # internal_validation failure has nothing left to
                    # reconcile, so it leaves the store's own defaults.
                    schedule_fields = {
                        "verification_deadline_at": (
                            self._now()
                            + timedelta(seconds=self._verification_deadline_seconds)
                        ).isoformat(),
                        "next_verification_at": self._now().isoformat(),
                        "verification_attempts": 0,
                    }
                self._store.transition(
                    execution_id,
                    expected_revision=int(current.get("revision") or 0),
                    expected_status={"running", "retrying"},
                    status="failed",
                    actor=requested_by,
                    provider=intended_provider,
                    message=message,
                    failure_details=message,
                    outcome="failed",
                    provider_submitted=provider_submitted,
                    failure_class=failure_class,
                    now=self._now(),
                    **schedule_fields,
                )
            if execution_id is not None:
                return self.execution_view(self._store.get(execution_id))
            return {
                "execution_id": execution_id,
                "plan_id": plan_id,
                "status": "failed",
                "provider": intended_provider,
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
                provider=run.provider,
                provider_job_id=run.provider_job_id,
                message=message,
                # A successful submission unambiguously reached the
                # provider.
                provider_submitted=True,
                failure_class="",
                verification_deadline_at=(
                    self._now() + timedelta(seconds=self._verification_deadline_seconds)
                ).isoformat(),
                next_verification_at=self._now().isoformat(),
                verification_attempts=0,
                now=self._now(),
            )
            return self.execution_view(self._store.get(execution_id))
        return {
            "execution_id": execution_id,
            "plan_id": plan_id,
            "status": terminal_status,
            "provider": run.provider,
            "provider_job_id": run.provider_job_id,
            "message": message,
            "run_id": getattr(run, "run_id", ""),
        }

    def _intended_provider(self, action_id: str) -> str:
        """Return the provider selected before any submission is attempted."""
        if action_id in DEFENDER_CONFIGURATION_ACTION_IDS:
            return str(
                getattr(
                    self._defender_configuration,
                    "name",
                    "defender-configuration",
                )
            )
        if self._patching is None:
            return "unconfigured"
        return self._patching.adapter_name

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
        if is_submission_ambiguous(record):
            # The last attempt's transport failed after the mutating call may
            # already have crossed the provider boundary -- it may still be
            # running against Azure. Firing a second concurrent submission
            # would risk a genuine double-mutation (e.g. two concurrent patch
            # installs/reboots). Until the ambiguity is reconciled (Phase
            # 03.4's verification worker) or the operator explicitly
            # supersedes this execution (which refuses the same condition,
            # forcing a deliberate decision), retry must fail closed. This
            # mirrors `_supersede_eligibility`'s identical guard so the two
            # write paths can never disagree (CR-01).
            raise RemediationExecutionError(
                "This execution's last attempt may still be running against the "
                "provider; retry is refused until it is reconciled or superseded",
                reason="submission_ambiguous",
                details={"execution_id": execution_id},
            )

        plan_id = str(record.get("plan_id") or "")
        if self._plans is None:
            raise RemediationExecutionError(
                f"No remediation plan repository is configured; cannot retry {plan_id!r}",
                reason="plan_repository_unavailable",
                details={"plan_id": plan_id},
            )
        plan = self._plans.get(plan_id)
        if plan is None:
            raise RemediationExecutionError(
                f"Remediation plan {plan_id!r} was not found",
                reason="plan_not_found",
                details={"plan_id": plan_id},
            )
        persisted_provider = str(record.get("provider") or "")
        intended_provider = self._intended_provider(
            str(plan.get("action_id") or plan.get("opportunity_type") or "")
        )
        if not persisted_provider and submitted_attempt_count(record) > 0:
            raise RemediationExecutionError(
                "The submitted execution has no durable provider lineage; create "
                "a superseding execution instead of guessing a retry provider.",
                reason="execution_provider_unknown",
                details={"execution_id": execution_id},
            )
        if persisted_provider and persisted_provider != intended_provider:
            raise RemediationExecutionError(
                "The configured execution provider changed; create a superseding "
                "execution instead of retrying through a different provider.",
                reason="execution_provider_changed",
                details={
                    "execution_id": execution_id,
                    "persisted_provider": persisted_provider,
                    "configured_provider": intended_provider,
                },
            )

        # Revalidate the plan's *current* approval/target state -- it may
        # have changed since the original attempt even though this
        # execution was itself once approved.
        decision, self_approved_decision_ids = self._check_approval_gate(
            plan, requested_by=str(record.get("requested_by") or "")
        )
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
            schedule_fields = self._claim_schedule_fields()
            claimed = self._store.claim_retry(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                actor=str(record.get("requested_by") or ""),
                max_attempts=MAX_EXECUTION_ATTEMPTS,
                now=self._now(),
                **schedule_fields,
            )
            self._store.transition(
                execution_id,
                expected_revision=int(claimed.get("revision") or 0),
                expected_status="retrying",
                status="running",
                actor=str(record.get("requested_by") or ""),
                now=self._now(),
                **schedule_fields,
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

        # WR-03 fix: see execute()'s identical placement -- only once the
        # retry claim has durably succeeded is self-approval consumption
        # recorded.
        self._finalize_self_approvals(self_approved_decision_ids)
        return self._submit_and_record(
            plan=plan,
            decision=immutable_decision,
            requested_by=str(record.get("requested_by") or ""),
            execution_id=execution_id,
        )

    def supersede(
        self, execution_id: str, *, requested_by: str, reason: str
    ) -> dict[str, Any]:
        """Close out an exhausted (but non-ambiguous) execution with a new one.

        Never mutates or deletes the old execution's audit trail (only its
        ``superseded_by``/``superseded_reason`` fields). Re-runs the approval
        gate fresh against the *current* plan state -- never reusing the old
        execution's already-approved snapshot -- so a plan whose approval was
        revoked cannot be superseded at all. Target/allowlist eligibility is
        revalidated fresh too, at the same single resolution point
        ``execute()``/``retry()`` use (inside ``_submit_and_record``): if the
        target has since drifted, the new execution is still minted and
        linked (``supersedes``), but its first attempt is recorded as a
        pre-submission ``target_precondition`` failure rather than ever
        reaching the adapter -- consistent with how ``execute()``/``retry()``
        themselves handle the identical drift (T-03.3-05).
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to supersede",
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
        if not str(reason or "").strip():
            raise RemediationExecutionError(
                "A non-empty reason is required to supersede an execution",
                reason="supersede_reason_required",
                details={"execution_id": execution_id},
            )
        ineligibility = _supersede_eligibility(record)
        if ineligibility:
            raise RemediationExecutionError(
                "This execution is not eligible for supersession",
                reason=ineligibility,
                details={"execution_id": execution_id, "status": record.get("status")},
            )

        plan_id = str(record.get("plan_id") or "")
        if self._plans is None:
            raise RemediationExecutionError(
                f"No remediation plan repository is configured; cannot supersede {plan_id!r}",
                reason="plan_repository_unavailable",
                details={"plan_id": plan_id},
            )
        plan = self._plans.get(plan_id)
        if plan is None:
            raise RemediationExecutionError(
                f"Remediation plan {plan_id!r} was not found",
                reason="plan_not_found",
                details={"plan_id": plan_id},
            )

        # Fresh revalidation -- the same checks execute()/retry() use, never
        # the old execution's already-approved snapshot forwarded as-is.
        # Target/allowlist resolution itself is intentionally left to
        # `_submit_and_record`'s own `_resolve_target` call below (the same
        # single resolution point `execute()`/`retry()` use) rather than
        # duplicated here: a second, earlier call read the identical
        # `(plan, decision)` pair with no intervening store mutation, so it
        # could never disagree with the later one, but it was also pure
        # wasted work with a latent trap if `_resolve_target` ever gains a
        # side effect (WR-02). If resolution now fails, `_submit_and_record`
        # already handles it the same way execute()/retry() do: it persists
        # a pre-submission `target_precondition` failure on the newly minted
        # execution without consuming submission budget -- it does not
        # silently widen what was approved.
        decision, self_approved_decision_ids = self._check_approval_gate(
            plan, requested_by=requested_by
        )
        approved_snapshot = self._validated_execution_snapshot(plan, decision)

        rollback_guidance = list(
            (plan.get("rollback_plan") or {}).get("rollback_actions") or []
        )
        try:
            new_record, _old_record = self._store.create_superseding(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                plan_id=plan_id,
                requested_by=requested_by,
                approved_by=str(decision.get("approver") or ""),
                approval_decision_id=str(decision.get("decision_id") or ""),
                approval_decided_at=str(decision.get("decided_at") or ""),
                execution_snapshot=approved_snapshot,
                rollback_guidance=rollback_guidance,
                scope_attributes={
                    **scope_attributes(plan.get("resource") or {}),
                    **scope_attributes(plan),
                },
                reason=reason,
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

        new_execution_id = new_record["execution_id"]
        self._store.transition(
            new_execution_id,
            expected_revision=int(new_record.get("revision") or 0),
            expected_status="queued",
            status="running",
            actor=requested_by,
            now=self._now(),
            **self._claim_schedule_fields(),
        )

        # WR-03 fix: see execute()'s identical placement -- only once the
        # superseding execution has durably claimed "running" is
        # self-approval consumption recorded.
        self._finalize_self_approvals(self_approved_decision_ids)
        return self._submit_and_record(
            plan=plan,
            decision=decision,
            requested_by=requested_by,
            execution_id=new_execution_id,
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

    def orphaned_executions(self) -> list[dict[str, Any]]:
        """Diagnostics: executions with no remaining way to reauthorize them.

        A record is orphaned only when *both* its originating plan is
        unresolvable (no plan repository at all, or the plan_id no longer
        resolves against the current one) *and* it has no derivable scope
        attributes of its own (D-02/D-04) -- i.e. there is no remaining way
        to reauthorize or reconcile the record against a live plan. This is
        read-only: it performs no migration and rewrites nothing (D-04).
        """
        if self._store is None:
            return []
        orphans: list[dict[str, Any]] = []
        for record in self._store.list_all():
            plan_unresolvable = self._plans is None or self._plans.get(
                str(record.get("plan_id") or "")
            ) is None
            if not plan_unresolvable:
                continue
            if execution_scope_attributes(record):
                continue
            orphans.append(
                {
                    "execution_id": record.get("execution_id"),
                    "plan_id": record.get("plan_id"),
                    "status": record.get("status"),
                    "reason": (
                        "plan_repository_unavailable"
                        if self._plans is None
                        else "legacy_scope_unresolvable"
                    ),
                }
            )
        return orphans

    def plan_eligibility(self, plan_id: str) -> dict[str, Any]:
        """Project whether the current durable plan can be executed."""
        if self._plans is None:
            return {"executable": False, "ineligibility_reason": "plan_repository_unavailable"}
        plan = self._plans.get(plan_id)
        if plan is None:
            return {"executable": False, "ineligibility_reason": "plan_not_found"}
        try:
            decision, _self_approved_decision_ids = self._check_approval_gate(
                plan, requested_by=""
            )
            # Eligibility is a server projection, not a cached approval
            # assertion. Re-resolve the approved target and allowlist so the
            # UI cannot offer execution after inventory has drifted. Never
            # finalizes any self-approval (requested_by="" guarantees the
            # set is always empty) -- this is a pure, non-mutating read.
            self._resolve_target(plan, decision)
        except RemediationExecutionError as exc:
            return {"executable": False, "ineligibility_reason": exc.reason}
        return {"executable": True, "ineligibility_reason": ""}

    @staticmethod
    def execution_view(record: dict[str, Any]) -> dict[str, Any]:
        """Add authoritative retry/cancel/supersede eligibility to a record."""
        view = copy.deepcopy(record)
        attempts = view.get("attempts") or []
        if attempts:
            current_attempt = attempts[-1]
            for field in (
                "provider_job_id",
                "verified_state",
                "failure_details",
                "message",
                "provider_submitted",
                "failure_class",
                "verification_evidence",
                "outcome",
            ):
                if field in current_attempt:
                    view[field] = copy.deepcopy(current_attempt[field])
        submitted = submitted_attempt_count(view)
        remaining = max(0, MAX_EXECUTION_ATTEMPTS - submitted)
        status = str(view.get("status") or "")
        # A submission-ambiguous last attempt is never retryable -- it may
        # still be running against the provider -- regardless of remaining
        # budget. This must agree with `retry()`'s own guard (CR-01) so the
        # API/web contract can never advertise `retryable: true` for a
        # record `retry()` would actually refuse.
        ambiguous = is_submission_ambiguous(view)
        retryable = status in {"failed", "cancelled"} and remaining > 0 and not ambiguous
        cancellable = (
            status == "queued" and not bool(view.get("provider_job_id"))
        ) or (
            status == "running"
            and str(view.get("provider") or "") == "sre-agent"
            and bool(view.get("provider_job_id"))
            and (view.get("verification_evidence") or {}).get("approval_pending")
            is True
            and not bool((view.get("verification_evidence") or {}).get("provider_operation"))
        )
        explicit = str(view.get("ineligibility_reason") or "")
        if explicit:
            reason = explicit
        elif status == "running" and view.get("provider_job_id") and not cancellable:
            reason = "provider_not_cancellable"
        elif status == "succeeded":
            reason = "already_succeeded"
        elif status in {"failed", "cancelled"} and ambiguous:
            reason = "submission_ambiguous"
        elif status in {"failed", "cancelled"} and remaining == 0:
            reason = "max_attempts_exceeded"
        elif retryable or cancellable:
            reason = ""
        else:
            reason = "execution_not_retryable"
        supersede_ineligibility_reason = _supersede_eligibility(view)
        abandon_ineligibility_reason = _abandon_eligibility(view)
        view.update(
            {
                "retryable": retryable,
                "cancellable": cancellable,
                "remaining_attempts": remaining,
                "submitted_attempt_count": submitted,
                "ineligibility_reason": reason,
                "supersedable": supersede_ineligibility_reason == "",
                "supersede_ineligibility_reason": supersede_ineligibility_reason,
                "can_abandon": abandon_ineligibility_reason == "",
                "abandon_ineligibility_reason": abandon_ineligibility_reason,
            }
        )
        return view

    def cancel(self, execution_id: str, *, requested_by: str) -> dict[str, Any]:
        """Cancel queued work or a typed pending Azure SRE Agent approval."""
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
        view = self.execution_view(record)
        if (
            view.get("cancellable")
            and str(record.get("provider") or "") == "sre-agent"
            and self._verifier is not None
            and callable(getattr(self._verifier, "cancel", None))
        ):
            try:
                cancellation = self._verifier.cancel(record)
            except ExecutionVerificationUnavailable as exc:
                raise RemediationExecutionError(
                    "Azure SRE Agent did not confirm cancellation; the request "
                    "remains active.",
                    reason="provider_cancellation_unconfirmed",
                    details={
                        "execution_id": execution_id,
                        "capability": exc.capability,
                    },
                ) from exc
            try:
                cancelled = self._store.transition(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status="running",
                    status="cancelled",
                    actor=requested_by,
                    outcome="cancelled",
                    verified_state="Cancelled",
                    failure_class="provider_rejected",
                    failure_details=(
                        "The operator rejected the pending Azure SRE Agent "
                        "approval before patch submission."
                    ),
                    message="Azure SRE Agent request cancelled by the operator.",
                    verification_evidence={
                        "provider_cancellation": cancellation,
                    },
                    ineligibility_reason="",
                    now=self._now(),
                )
            except ExecutionClaimConflict as exc:
                raise RemediationExecutionError(
                    "Another lifecycle operation changed the execution while "
                    "cancellation was being confirmed.",
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
        view["ineligibility_reason"] = "execution_not_cancellable"
        return view

    def abandon(self, execution_id: str, *, requested_by: str) -> dict[str, Any]:
        """Operator self-service recovery for a safe, quiescent SRE request.

        Distinct from :meth:`cancel`: this never contacts Azure SRE Agent
        and never claims to reject or cancel anything server-side. It only
        ends *this repo's own local tracking* of a running thread once a
        FRESH verification proves the thread has no pending approval, no
        approval record of any status, no submitted provider operation, no
        typed active incident/action, and no success evidence -- i.e.
        nothing an operator could still be waiting on. Every ambiguous or
        unconfirmable case fails closed and leaves the execution
        unchanged; a stale/cached ``verification_evidence`` on the record
        is never trusted for this decision.
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to abandon",
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
        if (
            str(record.get("status") or "") != "running"
            or str(record.get("provider") or "") != SRE_AGENT_PROVIDER
            or not str(record.get("provider_job_id") or "").strip()
        ):
            raise RemediationExecutionError(
                "Only a running Azure SRE Agent request can be abandoned",
                reason="execution_not_abandonable",
                details={"execution_id": execution_id},
            )
        if self._verifier is None or not callable(
            getattr(self._verifier, "verify", None)
        ):
            raise RemediationExecutionError(
                "No execution verifier is configured; cannot confirm this "
                "request is safe to abandon",
                reason="verification_unavailable",
                details={"execution_id": execution_id},
            )
        try:
            outcome = self._verifier.verify(record)
        except ExecutionVerificationUnavailable as exc:
            raise RemediationExecutionError(
                "Azure SRE Agent did not confirm this thread's current "
                "state; abandon refused.",
                reason="verification_unavailable",
                details={"execution_id": execution_id, "capability": exc.capability},
            ) from exc
        if not outcome.get("verifiable", False):
            raise RemediationExecutionError(
                "Azure SRE Agent verification is unavailable; abandon refused.",
                reason="verification_unavailable",
                details={"execution_id": execution_id},
            )
        if outcome.get("outcome") in {"succeeded", "failed", "cancelled"}:
            raise RemediationExecutionError(
                "This request already reached a terminal provider outcome; "
                "poll instead of abandoning.",
                reason="execution_already_terminal",
                details={"execution_id": execution_id},
            )
        evidence = outcome.get("verification_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if evidence.get("approval_pending") is True:
            raise RemediationExecutionError(
                "A pending Azure SRE Agent approval exists; abandon refused.",
                reason="approval_pending",
                details={"execution_id": execution_id},
            )
        if isinstance(evidence.get("provider_operation"), dict):
            raise RemediationExecutionError(
                "Azure SRE Agent already has a submitted provider operation; "
                "abandon refused.",
                reason="provider_operation_exists",
                details={"execution_id": execution_id},
            )
        if _sre_evidence_has_typed_activity(evidence):
            raise RemediationExecutionError(
                "Azure SRE Agent reports a typed active incident or action; "
                "abandon refused.",
                reason="typed_active_action_exists",
                details={"execution_id": execution_id},
            )
        # WR-abandon: even a quiescent, no-flags composite must not be
        # trusted alone -- a decided/rejected/expired approval the
        # composite summary never surfaces still proves an operator was
        # actively engaged with this thread. Read-only; never posts a
        # decision (that is exclusively `cancel()`'s job).
        read_approvals = getattr(self._verifier, "read_approvals", None)
        if not callable(read_approvals):
            raise RemediationExecutionError(
                "Azure SRE Agent approval history cannot be confirmed for "
                "this thread; abandon refused.",
                reason="verification_unavailable",
                details={"execution_id": execution_id},
            )
        try:
            approvals = read_approvals(record)
        except ExecutionVerificationUnavailable as exc:
            raise RemediationExecutionError(
                "Azure SRE Agent approval history could not be confirmed; "
                "abandon refused.",
                reason="verification_unavailable",
                details={"execution_id": execution_id, "capability": exc.capability},
            ) from exc
        if approvals:
            raise RemediationExecutionError(
                "An Azure SRE Agent approval record exists for this thread; "
                "abandon refused.",
                reason="approval_exists",
                details={"execution_id": execution_id},
            )
        try:
            abandoned = self._store.transition(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="failed",
                actor=requested_by,
                outcome="unknown",
                failure_class="operator_abandoned_without_provider_cancellation",
                verified_state="operator_abandoned",
                message=_append_note(
                    record.get("message"),
                    "The operator abandoned local tracking of this request. "
                    "Azure SRE Agent was not contacted and no provider "
                    "cancellation occurred.",
                ),
                failure_details=(
                    "The operator abandoned tracking of this quiescent Azure "
                    "SRE Agent request through the self-service recovery "
                    "control. Azure SRE Agent was not contacted and no "
                    "provider cancellation occurred; verify the thread "
                    "directly before assuming no action was taken."
                ),
                verification_evidence=evidence,
                ineligibility_reason="",
                now=self._now(),
            )
        except ExecutionClaimConflict as exc:
            raise RemediationExecutionError(
                "Another lifecycle operation changed the execution while "
                "abandonment was being confirmed.",
                reason=exc.reason,
                details={"execution_id": execution_id},
            ) from exc
        view = self.execution_view(abandoned)
        view["abandoned"] = True
        view["provider_cancelled"] = False
        return view

    def poll_verification(self, execution_id: str) -> dict[str, Any]:
        """Poll the real upstream source of truth for one running execution.

        Deadline-first (Recommendation 3, Deadline and Recovery): a running
        execution whose ``verification_deadline_at`` has already passed is
        transitioned straight to a terminal ``unknown``/
        ``verification_timed_out`` outcome *before* the verifier is ever
        touched -- an execution can never stay "running" indefinitely.
        Otherwise, a terminal ARM outcome ("succeeded"/"failed"/"cancelled")
        updates the stored record accordingly. A still-running or degraded
        (verifier unavailable/not verifiable) outcome bumps
        ``verification_attempts`` and reschedules ``next_verification_at``
        via a capped exponential backoff, so a poller (browser or the
        background coordinator) knows when to look again without polling in
        a tight loop.
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
        status = str(record.get("status") or "")
        if status not in {"running", "retrying"}:
            return self.execution_view(record)

        if status == "retrying":
            # CR-01: a crash between claim_retry() and the following
            # retrying -> running transition leaves this record here with
            # no provider submission for the *current* attempt at all --
            # any provider_job_id on the record still belongs to a prior,
            # already-terminal attempt and must never be polled as if it
            # were this one. Bounded exclusively by the deadline seeded at
            # claim time: recoverable via deadline expiry into an ordinary
            # terminal failure, never resubmitted or ARM-verified here.
            if self._is_verification_deadline_exceeded(record):
                return self._transition_or_current(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status="retrying",
                    status="failed",
                    actor="execution-verifier",
                    outcome="unknown",
                    failure_class="verification_timed_out",
                    verified_state="verification_deadline_exceeded",
                    message=_append_note(
                        record.get("message"),
                        "A retry claim did not resume to a submitted attempt "
                        "within the configured deadline; confirm actual target "
                        "state before retrying or superseding again.",
                    ),
                    failure_details=(
                        "A retry claim did not resume to a submitted attempt "
                        "within the configured deadline; confirm actual target "
                        "state before retrying or superseding again."
                    ),
                )
            current_attempts = int(record.get("verification_attempts") or 0)
            next_attempts = current_attempts + 1
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="retrying",
                status="retrying",
                actor="execution-verifier",
                verification_attempts=next_attempts,
                next_verification_at=(
                    self._now() + timedelta(seconds=_next_backoff_seconds(next_attempts))
                ).isoformat(),
            )

        deadline_exceeded = self._is_verification_deadline_exceeded(record)
        provider_review_thread = (
            str(record.get("provider") or "") == SRE_AGENT_PROVIDER
            and bool(record.get("provider_job_id"))
        )
        if deadline_exceeded and not provider_review_thread:
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="failed",
                actor="execution-verifier",
                outcome="unknown",
                failure_class="verification_timed_out",
                verified_state="verification_deadline_exceeded",
                message=_append_note(
                    record.get("message"),
                    "Verification did not reach a terminal Azure status within the "
                    "configured deadline; confirm actual target state before "
                    "retrying or superseding.",
                ),
                failure_details=(
                    "Verification did not reach a terminal Azure status within the "
                    "configured deadline; confirm actual target state before "
                    "retrying or superseding."
                ),
            )

        current_attempts = int(record.get("verification_attempts") or 0)
        next_attempts = current_attempts + 1
        backoff_at = (
            self._now() + timedelta(seconds=_next_backoff_seconds(next_attempts))
        ).isoformat()

        if self._verifier is None:
            outcome = {
                "verifiable": False,
                "reason": "no execution verifier is configured",
                "verification_evidence": {},
            }
        else:
            try:
                outcome = self._verifier.verify(record)
            except ExecutionVerificationUnavailable as exc:
                outcome = {
                    "verifiable": False,
                    "reason": str(exc),
                    "verification_evidence": {},
                }

        if not outcome.get("verifiable", False):
            message = _append_note(
                record.get("message"),
                f"Verification not available: {outcome.get('reason', 'unknown')}",
            )
            if deadline_exceeded:
                return self._transition_or_current(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status="running",
                    status="failed",
                    actor="execution-verifier",
                    outcome="unknown",
                    failure_class="verification_timed_out",
                    verified_state="verification_deadline_exceeded",
                    message=_append_note(
                        message,
                        "The Azure SRE Agent Review thread could not be proven "
                        "active after the verification deadline; confirm target "
                        "state before recovery.",
                    ),
                    failure_details=(
                        "The Azure SRE Agent Review thread could not be proven "
                        "active after the verification deadline; confirm target "
                        "state before recovery."
                    ),
                    verification_evidence=outcome.get("verification_evidence") or {},
                    verification_attempts=next_attempts,
                )
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="running",
                actor="execution-verifier",
                message=message,
                verification_evidence=outcome.get("verification_evidence") or {},
                verification_attempts=next_attempts,
                next_verification_at=backoff_at,
            )

        result_outcome = outcome.get("outcome")
        if result_outcome == "succeeded":
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="succeeded",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                outcome="succeeded",
                verification_evidence=outcome.get("verification_evidence") or {},
                verification_attempts=next_attempts,
                # Restart the deadline window for the reconciliation phase:
                # a freshly-succeeded patch record is immediately due for
                # evidence reconciliation (Plan 03.4-01's
                # list_due_for_verification rule).
                verification_deadline_at=(
                    self._now() + timedelta(seconds=self._verification_deadline_seconds)
                ).isoformat(),
                next_verification_at=self._now().isoformat(),
            )
        if result_outcome == "failed":
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="failed",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                failure_details=(
                    outcome.get("failure_details")
                    or "Provider reported a terminal outcome with no additional detail."
                ),
                outcome="failed",
                failure_class=outcome.get("failure_class") or "provider_rejected",
                verification_evidence=outcome.get("verification_evidence") or {},
                verification_attempts=next_attempts,
            )
        if result_outcome == "cancelled":
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="cancelled",
                actor="execution-verifier",
                verified_state=outcome.get("verified_state", ""),
                failure_details=(
                    outcome.get("failure_details")
                    or "Provider reported a terminal outcome with no additional detail."
                ),
                outcome="cancelled",
                verification_evidence=outcome.get("verification_evidence") or {},
                verification_attempts=next_attempts,
            )
        if deadline_exceeded and not _sre_outcome_has_deadline_extending_activity(
            record,
            outcome,
        ):
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="running",
                status="failed",
                actor="execution-verifier",
                outcome="unknown",
                failure_class="verification_timed_out",
                verified_state="verification_deadline_exceeded",
                message=_append_note(
                    record.get("message"),
                    "Verification did not prove that the Azure SRE Agent Review "
                    "thread remains active; confirm target state before recovery.",
                ),
                failure_details=(
                    "Verification did not prove that the Azure SRE Agent Review "
                    "thread remains active; confirm target state before recovery."
                ),
                verification_evidence=outcome.get("verification_evidence") or {},
                verification_attempts=next_attempts,
            )
        # Still running -- no-op except the latest verified_state/evidence
        # and the next bounded-backoff scheduling.
        return self._transition_or_current(
            execution_id,
            expected_revision=int(record.get("revision") or 0),
            expected_status="running",
            status="running",
            actor="execution-verifier",
            verified_state=outcome.get("verified_state", ""),
            verification_evidence=outcome.get("verification_evidence") or {},
            verification_attempts=next_attempts,
            next_verification_at=backoff_at,
        )

    def reconcile_evidence(self, execution_id: str) -> dict[str, Any]:
        """Compare a verified-succeeded patch execution's selected KBs against
        freshly refreshed target evidence.

        Never widens or reinterprets Azure's own reported outcome: ``status``
        stays "succeeded" regardless of the comparison result (CONTEXT.md's
        Evidence Reconciliation decision to "preserve provider success
        separately"); only ``evidence_reconciliation`` records whether the
        selected KBs actually cleared. A no-op (returns the current view
        unchanged) for a non-patch/defender-configuration record, or once
        reconciliation has already reached a terminal outcome.
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to reconcile",
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
        if record.get("status") != "succeeded" or not _is_patch_evidence_candidate(record):
            return self.execution_view(record)
        reconciliation = record.get("evidence_reconciliation") or {}
        if str(reconciliation.get("status") or "") in _RECONCILIATION_TERMINAL_STATUSES:
            return self.execution_view(record)

        selected = set(record["execution_snapshot"].get("patch_ids") or [])
        result = self._refresh_target_evidence(record)
        if (
            result is not None
            and _target_evidence_usable(result, record)
            and _submission_proof_allows_ambiguity_resolution(record)
        ):
            missing_now = set(result.get("missing_kbs") or [])
            kbs_remaining = sorted(selected & missing_now)
            kbs_cleared = sorted(selected - missing_now)
            new_status = "reconciled_clean" if not kbs_remaining else "reconciled_incomplete"
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="succeeded",
                status="succeeded",
                actor="execution-verifier",
                evidence_reconciliation={
                    "status": new_status,
                    "kbs_cleared": kbs_cleared,
                    "kbs_remaining": kbs_remaining,
                    "assessed_at": str(result.get("assessed_at") or ""),
                },
            )

        # Refresher unavailable/raised/returned nothing, or returned an
        # unconfirmed (target-not-observed) result: retry within the
        # deadline window, then reach a terminal "unreconciled" outcome.
        # WR-06: a target the refresher could not confirm it actually
        # observed must never be treated as "nothing missing" -- it is
        # unreconciled, exactly like an unavailable refresher, not clean.
        if self._is_verification_deadline_exceeded(record):
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="succeeded",
                status="succeeded",
                actor="execution-verifier",
                evidence_reconciliation={
                    "status": "unreconciled",
                    "kbs_cleared": [],
                    "kbs_remaining": sorted(selected),
                    "assessed_at": "",
                },
                message=_append_note(
                    record.get("message"),
                    "Evidence reconciliation could not be completed within the "
                    "configured deadline; provider success is preserved but the "
                    "selected KBs' actual state is unconfirmed.",
                ),
            )
        current_attempts = int(record.get("verification_attempts") or 0)
        next_attempts = current_attempts + 1
        return self._transition_or_current(
            execution_id,
            expected_revision=int(record.get("revision") or 0),
            expected_status="succeeded",
            status="succeeded",
            actor="execution-verifier",
            evidence_reconciliation={
                "status": "pending",
                "kbs_cleared": [],
                "kbs_remaining": sorted(selected),
                "assessed_at": "",
            },
            verification_attempts=next_attempts,
            next_verification_at=(
                self._now() + timedelta(seconds=_next_backoff_seconds(next_attempts))
            ).isoformat(),
        )

    def reconcile_ambiguous_submission(self, execution_id: str) -> dict[str, Any]:
        """Resolve a submission-ambiguous failed execution using target evidence.

        Direct ARM ambiguity becomes ordinary ``submission_unconfirmed`` after
        its deadline, preserving the existing bounded retry behavior. SRE
        Agent HTTP triggers have no documented idempotency guarantee, so their
        ambiguity stays non-retryable after the deadline; it becomes eligible
        only for explicit supersession/manual resolution.
        """
        if self._store is None:
            raise RemediationExecutionError(
                "No execution store is configured; nothing to reconcile",
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
        if record.get("status") != "failed" or not is_submission_ambiguous(record):
            return self.execution_view(record)

        selected = set(record["execution_snapshot"].get("patch_ids") or [])
        result = (
            self._refresh_target_evidence(record)
            if _is_patch_evidence_candidate(record)
            else None
        )
        if (
            result is not None
            and _target_evidence_usable(result, record)
            and _submission_proof_allows_ambiguity_resolution(record)
        ):
            missing_now = set(result.get("missing_kbs") or [])
            kbs_remaining = sorted(selected & missing_now)
            if selected and not kbs_remaining:
                return self._transition_or_current(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status="failed",
                    status="succeeded",
                    actor="execution-verifier",
                    outcome="succeeded",
                    failure_class="",
                    verified_state="reconciled_from_target_evidence",
                    evidence_reconciliation={
                        "status": "reconciled_clean",
                        "kbs_cleared": sorted(selected),
                        "kbs_remaining": [],
                        "assessed_at": str(result.get("assessed_at") or ""),
                    },
                )

        # WR-06: an unconfirmed (target-not-observed) result must never
        # promote a submission-ambiguous failure to "succeeded" -- fall
        # through exactly like an unavailable refresher, into the bounded
        # retry/timeout path below.
        if self._is_verification_deadline_exceeded(record):
            if str(record.get("provider") or "") == "sre-agent":
                return self._transition_or_current(
                    execution_id,
                    expected_revision=int(record.get("revision") or 0),
                    expected_status="failed",
                    status="failed",
                    actor="execution-verifier",
                    failure_class="submission_ambiguous",
                    verified_state="sre_agent_manual_resolution_required",
                    evidence_reconciliation={
                        "status": "unreconciled_manual_resolution",
                        "kbs_cleared": [],
                        "kbs_remaining": sorted(selected),
                        "assessed_at": "",
                    },
                    next_verification_at="",
                    message=_append_note(
                        record.get("message"),
                        "The SRE Agent trigger outcome remains ambiguous after the "
                        "reconciliation deadline. Retry is prohibited; recover the "
                        "thread handle or explicitly supersede after confirming "
                        "target state.",
                    ),
                    failure_details=(
                        "The SRE Agent trigger outcome remains ambiguous after the "
                        "reconciliation deadline. Retry is prohibited; recover the "
                        "thread handle or explicitly supersede after confirming "
                        "target state."
                    ),
                )
            return self._transition_or_current(
                execution_id,
                expected_revision=int(record.get("revision") or 0),
                expected_status="failed",
                status="failed",
                actor="execution-verifier",
                failure_class="submission_unconfirmed",
                verified_state="reconciliation_timed_out",
                evidence_reconciliation={
                    "status": "unreconciled_timed_out",
                    "kbs_cleared": [],
                    "kbs_remaining": sorted(selected),
                    "assessed_at": "",
                },
                message=_append_note(
                    record.get("message"),
                    "The submission's provider outcome could not be confirmed within "
                    "the reconciliation deadline; it is now an ordinary bounded "
                    "failure, retryable or supersedable like any other.",
                ),
                failure_details=(
                    "The submission's provider outcome could not be confirmed within "
                    "the reconciliation deadline; it is now an ordinary bounded "
                    "failure, retryable or supersedable like any other."
                ),
            )
        current_attempts = int(record.get("verification_attempts") or 0)
        next_attempts = current_attempts + 1
        return self._transition_or_current(
            execution_id,
            expected_revision=int(record.get("revision") or 0),
            expected_status="failed",
            status="failed",
            actor="execution-verifier",
            verification_attempts=next_attempts,
            next_verification_at=(
                self._now() + timedelta(seconds=_next_backoff_seconds(next_attempts))
            ).isoformat(),
        )

    def _is_verification_deadline_exceeded(self, record: dict[str, Any]) -> bool:
        """Whether ``record``'s deadline has passed, fail-safe on absence.

        A legacy record (or one never given a deadline for any reason) is
        never treated as already-expired -- absence of a deadline is not
        the same as an expired one (matching the store's own conservative
        legacy-default philosophy).
        """
        deadline_text = str(record.get("verification_deadline_at") or "").strip()
        if not deadline_text:
            return False
        try:
            deadline = datetime.fromisoformat(deadline_text)
        except ValueError:
            return False
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return self._now() > deadline

    def _refresh_target_evidence(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Call the injected refresher, treating any failure as unavailable.

        A refresher failure (None configured, raises, returns nothing) must
        never propagate and must never block a terminal deadline outcome --
        it is retried within the window, not treated as an error.
        """
        if self._evidence_refresher is None:
            return None
        subscription_id = execution_scope_attributes(record).get("subscription", "")
        target_id = str((record.get("execution_snapshot") or {}).get("target_id") or "")
        try:
            return self._evidence_refresher(subscription_id, target_id)
        except Exception:  # noqa: BLE001 - unavailable, not an error to propagate
            return None

    def _transition_or_current(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        expected_status: str | set[str] | frozenset[str],
        status: str,
        actor: str,
        **fields: Any,
    ) -> dict[str, Any]:
        """Transition, or -- on a lost concurrent race -- return the winner's view.

        Shared by :meth:`poll_verification`, :meth:`reconcile_evidence`, and
        :meth:`reconcile_ambiguous_submission` so two concurrent callers
        (e.g. a browser GET and the background coordinator) never see an
        unhandled :class:`ExecutionClaimConflict`: the loser simply reads
        back the winner's already-persisted, equally valid outcome.
        """
        try:
            record = self._store.transition(
                execution_id,
                expected_revision=expected_revision,
                expected_status=expected_status,
                status=status,
                actor=actor,
                now=self._now(),
                **fields,
            )
        except ExecutionClaimConflict:
            record = self._store.get(execution_id)
        return self.execution_view(record)

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
        target_id = str(snapshot.get("target_id") or "").strip()
        snapshot_version = str(snapshot.get("action_version") or "")
        expected_version = str(plan.get("action_version") or "")
        supplied_hash = str(snapshot.get("snapshot_hash") or "")
        expected_hash = execution_snapshot_hash(snapshot)
        base_invalid = (
            not target_id
            or snapshot_version != expected_version
            or snapshot_version != str(decision.get("action_version") or "")
            or not hmac.compare_digest(supplied_hash, expected_hash)
        )
        if snapshot.get("snapshot_kind") == "defender_configuration":
            invalid = (
                base_invalid
                or str(snapshot.get("action_id") or "")
                != str(plan.get("action_id") or "")
                or snapshot.get("action_id") not in DEFENDER_CONFIGURATION_ACTION_IDS
                or snapshot.get("patch_ids") != []
                or not isinstance(snapshot.get("request"), dict)
                or not isinstance(snapshot.get("precondition"), dict)
                or not isinstance(snapshot.get("prior_properties"), dict)
            )
        else:
            patch_ids = snapshot.get("patch_ids")
            invalid = (
                base_invalid
                or not isinstance(patch_ids, list)
                or not patch_ids
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in patch_ids
                )
            )
        if invalid:
            raise RemediationExecutionError(
                "The approved execution snapshot is invalid or has been altered",
                reason="execution_snapshot_invalid",
                details={"plan_id": plan_id},
            )
        return snapshot

    def _resolve_target(
        self, plan: dict[str, Any], decision: dict[str, Any]
    ) -> tuple[PatchTarget | None, list[str]]:
        snapshot = self._validated_execution_snapshot(plan, decision)
        if snapshot.get("snapshot_kind") == "defender_configuration":
            try:
                current = build_defender_configuration_snapshot(
                    plan, self._defender_configuration
                )
            except DefenderConfigurationUnavailable as exc:
                raise RemediationExecutionError(
                    str(exc),
                    reason=exc.reason,
                    details={"plan_id": plan.get("plan_id")},
                ) from exc
            current["snapshot_hash"] = execution_snapshot_hash(current)
            if not hmac.compare_digest(
                str(current["snapshot_hash"]), str(snapshot.get("snapshot_hash") or "")
            ):
                raise RemediationExecutionError(
                    "The approved Defender configuration snapshot no longer matches current state",
                    reason="execution_snapshot_drift",
                    details={"plan_id": plan.get("plan_id")},
                )
            return None, []
        if self._patching is None:
            raise RemediationExecutionError(
                "Patch execution is not configured for this deployment",
                reason="patch_execution_unavailable",
                details={"plan_id": plan.get("plan_id")},
            )
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


def _target_evidence_confirmed(result: dict[str, Any]) -> bool:
    """Whether a non-``None`` refresher ``result`` confirms the target was
    actually observed (WR-06).

    A refresher may return an empty ``missing_kbs`` list either because the
    target genuinely has zero remaining exposures, or because the target
    was never observed at all (wrong/unresolvable subscription, migrated
    resource, or a target that does not exist) -- both produce the
    identical empty result otherwise. The optional ``target_observed`` key
    makes this explicit: only a confirmed ``True`` observation may be
    trusted for a ``reconciled_clean`` outcome or an ambiguity promotion.
    Absent entirely (a legacy refresher predating this key), default to
    ``True`` so every existing caller's prior behavior is preserved
    unchanged.
    """
    return bool(result.get("target_observed", True))


def _reconciliation_boundary_at(record: dict[str, Any]) -> str:
    """Return the latest valid submission/first-terminal timestamp."""
    attempts = record.get("attempts") or []
    current = attempts[-1] if attempts and isinstance(attempts[-1], dict) else {}
    transitions = current.get("transitions") or []
    candidates: list[tuple[str, datetime]] = []
    terminal_recorded = False
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        status = str(transition.get("status") or "")
        is_submission = bool(str(transition.get("provider_job_id") or "").strip())
        is_first_terminal = (
            not terminal_recorded and status in {"succeeded", "failed", "cancelled"}
        )
        if is_first_terminal:
            terminal_recorded = True
        if not is_submission and not is_first_terminal:
            continue
        timestamp = str(transition.get("timestamp") or "").strip()
        parsed = _parse_timestamp_for_ordering(timestamp)
        if parsed is None:
            return ""
        candidates.append((timestamp, parsed))
    if not candidates:
        return ""
    return max(candidates, key=lambda candidate: candidate[1])[0]


def _parse_timestamp_for_ordering(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _target_evidence_usable(
    result: dict[str, Any],
    record: dict[str, Any],
) -> bool:
    if not _target_evidence_confirmed(result):
        return False
    if str(record.get("provider") or "") != SRE_AGENT_PROVIDER:
        return True
    assessed_at = str(result.get("assessed_at") or "").strip()
    boundary_at = _reconciliation_boundary_at(record)
    if not assessed_at or not boundary_at:
        return False
    assessed = _parse_timestamp_for_ordering(assessed_at)
    boundary = _parse_timestamp_for_ordering(boundary_at)
    if assessed is None or boundary is None:
        return False
    return assessed > boundary


def _sre_evidence_has_typed_activity(evidence: Any) -> bool:
    """Whether SRE verification evidence proves a typed active action.

    Shared by :func:`_sre_outcome_has_deadline_extending_activity` (a fresh
    verifier outcome) and :func:`_record_has_typed_active_sre_evidence` (a
    durable record's last-stored evidence), so a live poll and a read-side
    projection can never disagree about what counts as "still active":
    a submitted provider operation, a pending approval, a nonblank typed
    incident status, or a typed critical/warning action flag.
    """
    if not isinstance(evidence, dict):
        return False
    if isinstance(evidence.get("provider_operation"), dict):
        return True
    if evidence.get("approval_pending") is True:
        return True
    thread_status = evidence.get("thread_status")
    if not isinstance(thread_status, dict):
        return False
    incident_status = str(thread_status.get("incident_status") or "").strip()
    if incident_status:
        return True
    return bool(
        thread_status.get("has_critical_actions") is True
        or thread_status.get("has_warning_actions") is True
    )


def _sre_outcome_has_deadline_extending_activity(
    record: dict[str, Any],
    outcome: dict[str, Any],
) -> bool:
    if str(record.get("provider") or "") != SRE_AGENT_PROVIDER:
        return bool(outcome.get("provider_active", False))
    if outcome.get("provider_active") is not True:
        return False
    return _sre_evidence_has_typed_activity(outcome.get("verification_evidence"))


def _record_has_typed_active_sre_evidence(record: dict[str, Any]) -> bool:
    """Whether a durable record's own stored evidence still looks active.

    Read-side counterpart used only by :meth:`RemediationExecutionService
    .execution_view`'s ``can_abandon`` projection -- never by the write-side
    :meth:`RemediationExecutionService.abandon`, which always re-verifies
    fresh before ever committing a terminal transition.
    """
    if str(record.get("provider") or "") != SRE_AGENT_PROVIDER:
        return False
    return _sre_evidence_has_typed_activity(record.get("verification_evidence"))


def _submission_proof_allows_ambiguity_resolution(
    record: dict[str, Any],
) -> bool:
    if str(record.get("provider") or "") != SRE_AGENT_PROVIDER:
        return True
    evidence = record.get("verification_evidence")
    return isinstance(evidence, dict) and isinstance(
        evidence.get("provider_operation"), dict
    )


# Evidence-reconciliation status values that mean "nothing left to do" --
# mirrors execution_store's own private terminal-status set so store and
# service can never disagree on when reconciliation has finished.
_RECONCILIATION_TERMINAL_STATUSES = frozenset(
    {"reconciled_clean", "reconciled_incomplete", "unreconciled"}
)


def _next_backoff_seconds(verification_attempts: int) -> float:
    """Bounded exponential backoff for the next verification pass.

    5 seconds on the first attempt, doubling each subsequent attempt,
    capped at 60 seconds: 5, 10, 20, 40, 60, 60, 60... A transient poll
    failure backs off within the deadline rather than polling in a tight
    loop (CONTEXT.md's Deadline and Recovery decision).

    The exponent is capped before computing 2 ** exponent: for a record
    with a very large (e.g. stuck/long-running) attempt count, an
    unbounded Python int power can grow far beyond float range, and
    ``5.0 * huge_int`` then raises OverflowError converting int to float
    -- before ``min(60.0, ...)`` ever gets a chance to cap it. Six
    doublings (5 * 2**6 = 320) already exceeds the 60s cap, so capping
    the exponent there preserves identical behavior for every attempt
    count while eliminating the overflow.
    """
    attempt = max(1, int(verification_attempts))
    capped_exponent = min(attempt - 1, 6)
    return min(60.0, 5.0 * (2**capped_exponent))


def _abandon_eligibility(record: dict[str, Any]) -> str:
    """Shared read-side static abandon-eligibility check.

    Only the structural preconditions that never require a live provider
    call: the record must be a running Azure SRE Agent request with a
    thread handle, and its last-stored evidence must not already show a
    typed active action (used by :meth:`RemediationExecutionService
    .execution_view`'s ``can_abandon`` projection). :meth:`
    RemediationExecutionService.abandon` always re-verifies fresh on top
    of this before ever committing a terminal transition -- this
    projection only decides whether to offer the control.
    """
    status = str(record.get("status") or "")
    if (
        status != "running"
        or str(record.get("provider") or "") != SRE_AGENT_PROVIDER
        or not str(record.get("provider_job_id") or "").strip()
    ):
        return "execution_not_abandonable"
    evidence = record.get("verification_evidence")
    if isinstance(evidence, dict) and evidence.get("approval_pending") is True:
        return "approval_pending"
    if isinstance(evidence, dict) and isinstance(
        evidence.get("provider_operation"), dict
    ):
        return "provider_operation_exists"
    if _record_has_typed_active_sre_evidence(record):
        return "typed_active_action_exists"
    return ""


def _supersede_eligibility(record: dict[str, Any]) -> str:
    """Shared write/read supersede-eligibility check.

    A single function used by both :meth:`RemediationExecutionService
    .supersede` (the write-side guard) and :meth:`execution_view` (the
    read-side projection) so the two can never disagree (CONTEXT.md's
    Supersession decision): refused for anything still active, anything
    already superseded, or any submission-ambiguous latest attempt that may
    still be running against the provider. Returns ``""`` when eligible,
    else the specific ineligibility reason.
    """
    status = str(record.get("status") or "")
    if status not in {"failed", "cancelled"}:
        return "execution_active"
    if record.get("superseded_by"):
        return "already_superseded"
    if is_submission_ambiguous(record):
        return "submission_ambiguous"
    return ""


__all__ = [
    "CONTROLLED_PATCH_RECOVERY",
    "EXECUTABLE_ACTION_IDS",
    "MAX_EXECUTION_ATTEMPTS",
    "VERIFICATION_DEADLINE_SECONDS",
    "RemediationExecutionError",
    "RemediationExecutionService",
    "validate_business_eligibility",
]
