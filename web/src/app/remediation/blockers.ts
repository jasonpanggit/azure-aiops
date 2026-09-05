/**
 * Phase 03.6 UI-SPEC Blocker Contract -- workflow step metadata, the
 * locked Blocker Vocabulary table, and the `blockerCopy()` resolver.
 * Extracted from `page.tsx` (a Next.js page route file may only export
 * a small fixed set of named exports -- `blockerCopy` cannot be
 * exported directly from page.tsx) so Plan 03.6-05's Supersede
 * race-handling callout can import and reuse it.
 */

export type WorkflowStep = "select" | "review" | "approve" | "run" | "verify";

export const WORKFLOW_STEPS: Array<{ id: WorkflowStep; label: string }> = [
  { id: "select", label: "Select fix" },
  { id: "review", label: "Review impact" },
  { id: "approve", label: "Approve" },
  { id: "run", label: "Run" },
  { id: "verify", label: "Verify" },
];

/**
 * Phase 03.6 UI-SPEC "Blocker Vocabulary" table, reproduced verbatim.
 * `already_succeeded` is deliberately omitted -- see "Excluded from
 * Blockers"; it is handled by an explicit exclusion check, not a table
 * entry.
 */
export const BLOCKER_VOCABULARY: Record<
  string,
  { severity: "warning" | "critical"; message: string; step?: WorkflowStep; nextAction: string }
> = {
  plan_repository_unavailable: {
    severity: "critical",
    message: "The plan repository is temporarily unavailable, so this fix cannot be resolved right now.",
    step: "review",
    nextAction: "Wait a moment and reopen this fix; if this persists, contact the platform team.",
  },
  execution_unavailable: {
    severity: "critical",
    message: "Remediation execution is not configured for this deployment.",
    step: "review",
    nextAction: "Contact the platform team; this fix cannot be scheduled for execution here.",
  },
  plan_not_found: {
    severity: "warning",
    message: "This plan no longer exists in the current generation.",
    step: "select",
    nextAction: "Return to Select fix and choose a currently listed plan.",
  },
  disposition_not_executable: {
    severity: "warning",
    message: "This fix's business disposition does not permit automated execution.",
    step: "review",
    nextAction: "Route it to the owning platform team for manual handling.",
  },
  unsupported_configuration_action: {
    severity: "warning",
    message: "This Defender recommendation has no supported direct configuration action.",
    step: "review",
    nextAction: "Route it to the owning platform team for manual handling in the Azure portal.",
  },
  configuration_target_not_supported: {
    severity: "warning",
    message: "The target resource type is not supported for direct Defender configuration changes.",
    step: "review",
    nextAction: "Route it to the owning platform team for manual handling.",
  },
  business_impact_unknown: {
    severity: "warning",
    message: "Business impact has not been established for this fix.",
    step: "review",
    nextAction: "Complete the business-impact assessment before requesting approval.",
  },
  review_required: {
    severity: "warning",
    message: "This fix requires a manual review before it can proceed.",
    step: "review",
    nextAction: "Complete the outstanding review requirement(s) shown above.",
  },
  decision_unknowns_present: {
    severity: "warning",
    message: "Open unknowns remain on this fix's business decision.",
    step: "review",
    nextAction: "Resolve the listed unknowns before requesting approval.",
  },
  decision_evidence_missing: {
    severity: "warning",
    message: "Business-decision evidence citations are missing.",
    step: "review",
    nextAction: "Add the required evidence citations before requesting approval.",
  },
  plan_evidence_missing: {
    severity: "warning",
    message: "This plan has no supporting evidence citations.",
    step: "review",
    nextAction: "Do not approve without evidence; request evidence collection first.",
  },
  no_patches_available: {
    severity: "warning",
    message: "No patches are currently available for this remediation target.",
    step: "review",
    nextAction: "Wait for the next patch-evidence refresh and reopen this fix; if the target no longer needs this action, route it back for reassessment instead of approving it.",
  },
  patch_ids_not_available: {
    severity: "warning",
    message: "One or more previously selected patches are no longer in this target's observed available list.",
    step: "review",
    nextAction: "Return to Select fix, refresh evidence, and choose only from the currently available patches.",
  },
  no_patches_selected: {
    severity: "warning",
    message: "At least one patch must be selected before this plan can be previewed or approved.",
    step: "review",
    nextAction: "Return to Select fix and choose at least one available patch.",
  },
  action_not_executable: {
    severity: "warning",
    message: "This action is not currently executable (manual review only).",
    step: "approve",
    nextAction: "See the manual review reason above.",
  },
  not_approved: {
    severity: "warning",
    message: "No decision has been recorded yet.",
    step: "approve",
    nextAction: "Record an approval decision for every required role.",
  },
  stale_approval: {
    severity: "warning",
    message: "The recorded approval no longer matches the current version, evidence, or policy.",
    step: "approve",
    nextAction: "Record a new decision against the current snapshot.",
  },
  approval_expired: {
    severity: "warning",
    message: "The recorded approval has expired.",
    step: "approve",
    nextAction: "Record a new decision with a future expiry.",
  },
  approval_requirements_unmet: {
    severity: "warning",
    message: "One or more required approval roles have not signed off.",
    step: "approve",
    nextAction: "Record a decision for each unmet role shown above.",
  },
  self_approval_not_permitted: {
    severity: "warning",
    message: "This decision would be a self-approval, which is not permitted under the current policy.",
    step: "approve",
    nextAction: "Ask a different approver to record this decision.",
  },
  execution_snapshot_missing: {
    severity: "warning",
    message: "No valid executable snapshot is attached to this approval.",
    step: "approve",
    nextAction: "Return to Review impact to regenerate a current preview.",
  },
  execution_snapshot_invalid: {
    severity: "warning",
    message: "No valid executable snapshot is attached to this approval.",
    step: "approve",
    nextAction: "Return to Review impact to regenerate a current preview.",
  },
  execution_snapshot_changed: {
    severity: "warning",
    message: "The approved snapshot no longer matches the plan's current executable preview.",
    step: "run",
    nextAction: "Return to Review impact, confirm the refreshed preview, and record a new approval.",
  },
  execution_snapshot_drift: {
    severity: "warning",
    message: "The approved snapshot no longer matches the plan's current executable preview.",
    step: "run",
    nextAction: "Return to Review impact, confirm the refreshed preview, and record a new approval.",
  },
  store_not_configured: {
    severity: "critical",
    message: "The execution store is not configured in this environment.",
    step: "run",
    nextAction: "Contact the platform team; execution cannot be recorded here.",
  },
  patch_execution_unavailable: {
    severity: "critical",
    message: "The patch provider could not accept this submission.",
    step: "run",
    nextAction: "Review the failure detail below; retry once the underlying cause is resolved.",
  },
  defender_configuration_unavailable: {
    severity: "critical",
    message: "The Defender configuration provider returned an unreachable or invalid response.",
    step: "run",
    nextAction: "Review the failure detail below; retry once Azure Resource Manager is reachable again.",
  },
  configuration_execution_unavailable: {
    severity: "critical",
    message: "No Defender configuration execution adapter is configured in this environment.",
    step: "run",
    nextAction: "Contact the platform team; this configuration change cannot be submitted here.",
  },
  azure_arm_token_unavailable: {
    severity: "critical",
    message: "An Azure management token could not be acquired for this Defender configuration change.",
    step: "run",
    nextAction: "Confirm the platform's Azure credential is valid, then retry once resolved.",
  },
  scope_not_authorized: {
    severity: "critical",
    message: "This target falls outside the caller's authorized scope for Defender configuration changes.",
    step: "run",
    nextAction: "Confirm the requested scope is correct; contact the platform team if this is unexpected.",
  },
  target_not_found: {
    severity: "critical",
    message: "The target resource could not be located by the provider.",
    step: "run",
    nextAction: "Confirm the resource still exists and is in scope, then retry.",
  },
  execution_not_found: {
    severity: "critical",
    message: "This execution record could not be found.",
    step: "verify",
    nextAction: "Return to Run and re-check the plan's execution history.",
  },
  execution_not_retryable: {
    severity: "warning",
    message: "This execution cannot be retried in its current state.",
    step: "verify",
    nextAction: "Check remaining attempts and lineage below for the available recovery action.",
  },
  submission_ambiguous: {
    severity: "critical",
    message: "The last attempt's outcome could not be confirmed with the provider.",
    step: "verify",
    nextAction: "Wait for automatic reconciliation; retry and supersede remain refused until it resolves.",
  },
  verification_timed_out: {
    severity: "critical",
    message: "The provider outcome could not be verified within the deadline.",
    step: "verify",
    nextAction: "Treat this execution's outcome as unknown; use Retry or Supersede once eligible.",
  },
  provider_not_cancellable: {
    severity: "warning",
    message: "This execution has already reached the provider and can no longer be cancelled.",
    step: "verify",
    nextAction: "Wait for verification, or use Retry/Supersede once eligible.",
  },
  max_attempts_exceeded: {
    severity: "critical",
    message: "All submitted attempts have been used.",
    step: "verify",
    nextAction: "Use Supersede with a new approval to continue, once the blocking cause is resolved.",
  },
  execution_not_cancellable: {
    severity: "warning",
    message: "This execution is not in a cancellable state.",
    step: "verify",
    nextAction: "Check whether Retry or Supersede is available instead.",
  },
  supersede_reason_required: {
    severity: "warning",
    message: "A reason is required to supersede this execution.",
    step: "verify",
    nextAction: "Enter a reason and submit again.",
  },
  execution_active: {
    severity: "warning",
    message: "This execution is still active and cannot be superseded until it reaches a terminal failed or cancelled state.",
    step: "verify",
    nextAction: "Wait for it to finish, or use Cancel if it is still queued.",
  },
  already_superseded: {
    severity: "warning",
    message: "This execution has already been superseded by another execution.",
    step: "verify",
    nextAction: "See the lineage below for the current, active execution.",
  },
};

/**
 * Resolves a `workflow.blockers[]` row's rendered copy: the server's own
 * `message`/`next_action`/`severity` when present, otherwise the locked
 * vocabulary table's fallback -- or, for a code the table does not
 * recognize, the safe unrecognized-code fallback. `step` is ALWAYS taken
 * from the server-provided value, never re-derived client-side, per the
 * synthesis rule. Exported for reuse by Plan 03.6-05's Supersede
 * race-handling callout.
 */
export function blockerCopy(
  code: string,
  serverStep: WorkflowStep,
  serverMessage?: string,
  serverNextAction?: string,
  serverSeverity?: "warning" | "critical",
): { severity: "warning" | "critical"; message: string; step: WorkflowStep; nextAction: string } {
  const vocabulary = BLOCKER_VOCABULARY[code];
  return {
    severity: serverSeverity ?? vocabulary?.severity ?? "warning",
    message: serverMessage ?? vocabulary?.message ?? `An unrecognized workflow condition (${code}) is blocking this step.`,
    step: serverStep,
    nextAction: serverNextAction ?? vocabulary?.nextAction ?? "Contact the platform team with this code; do not assume the step is safe to skip.",
  };
}

/**
 * WR-02 fix: codes this page has already telemetered as unrecognized, for
 * the lifetime of this module (i.e., of the page). A module-level
 * singleton -- rather than a per-component `useRef` -- is deliberate: it
 * is shared by every `blockerCopy()` call site (the cross-step
 * `WorkflowBlockers` panel, the per-step inline `stepBlockerEcho`, and
 * `RecoveryControls`'s Supersede-ineligibility-reason callout) so
 * telemetry coverage does not depend on which component happens to render
 * a given unrecognized code first, and survives any one of those
 * components remounting.
 */
const seenUnknownBlockerCodes = new Set<string>();

/**
 * Same resolution as `blockerCopy`, plus fires
 * `console.warn("remediation.blocker.unknown_code", { code })` exactly
 * once per distinct unrecognized code for the lifetime of this module.
 * "Unrecognized" mirrors `blockerCopy`'s own fallback condition: absent
 * from `BLOCKER_VOCABULARY` and without a server-supplied `message`
 * (a server-supplied message for a code the local table doesn't know is
 * not a silent fallback -- the server told us what it means).
 *
 * Every render-path call site (`WorkflowBlockers`, `stepBlockerEcho`, and
 * `RecoveryControls`'s supersede-ineligibility-reason callout) must call
 * this instead of `blockerCopy` directly so unknown-code observability is
 * uniform regardless of which component renders a given code first.
 */
export function blockerCopyWithTelemetry(
  code: string,
  serverStep: WorkflowStep,
  serverMessage?: string,
  serverNextAction?: string,
  serverSeverity?: "warning" | "critical",
): { severity: "warning" | "critical"; message: string; step: WorkflowStep; nextAction: string } {
  const isUnrecognized = !BLOCKER_VOCABULARY[code] && !serverMessage;
  if (isUnrecognized && !seenUnknownBlockerCodes.has(code)) {
    seenUnknownBlockerCodes.add(code);
    // eslint-disable-next-line no-console
    console.warn("remediation.blocker.unknown_code", { code });
  }
  return blockerCopy(code, serverStep, serverMessage, serverNextAction, serverSeverity);
}
