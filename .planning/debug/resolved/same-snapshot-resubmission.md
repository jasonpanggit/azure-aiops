---
status: resolved
trigger: "A fresh approval for the same still-applicable target/patch snapshot reuses the old execution instead of creating a new SRE request."
created: 2026-09-17T01:25:13+08:00
updated: 2026-09-17T02:52:00+08:00
---

## Symptoms

- expected: Repeated clicks under one approval are idempotent, while a new current approval after a terminal incomplete execution creates a new execution/thread.
- actual: Execution identity uses only plan, snapshot hash, and action version, so every future approval reuses the first execution forever.
- errors: Execute returns HTTP 202 with old execution RME-0AD1A242DAE59DE9 and creates no SRE thread.
- timeline: Observed after PR191 deployment during a second VM2/KB5007651 test.
- reproduction: Approve the unchanged VM2/KB5007651 snapshot again and execute it after the prior execution reached reconciled_incomplete.

## Current Focus

reasoning_checkpoint:
  hypothesis: "The approval-scoped store identity now permits a safe replacement after any terminal non-ambiguous execution, but the UI predicate exposes `Start a new run` only for `reconciled_incomplete`; therefore failed/cancelled non-ambiguous runs remain unnecessarily locked out in the operator workflow."
  confirming_evidence:
    - "The store's `_blocks_new_approval_execution` returns false for terminal failed/cancelled records unless the latest attempt is `submission_ambiguous`, and the existing backend test already observes a new identity for those terminal statuses."
    - "The rendered button currently requires `evidence_reconciliation.status === reconciled_incomplete`, so failed/cancelled records without that patch-success reconciliation cannot enter the fresh-approval workflow."
    - "`startNewRun` only resets local form/workflow state and navigates to Approve; it invokes neither execute nor another provider-facing API."
  falsification_test: "The correction would be wrong if a failed/cancelled record with a non-ambiguous latest attempt remained blocked by `create_or_get`, or if exposing the UI action directly invoked execute/provider mutation; it would be unsafe if any active or submission-ambiguous fixture rendered the action."
  fix_rationale: "Centralize the UI eligibility contract to mirror the store safety boundary: allow failed/cancelled non-ambiguous terminal records plus the existing succeeded/reconciled-incomplete case, reject submission ambiguity before either branch, and retain the local-only fresh-approval transition."
  blind_spots: "No cloud/live provider verification is authorized; multi-replica locking is exercised by existing local store concurrency tests rather than a deployed filesystem."
  candidate_causes:
    - "code: frontend eligibility encodes only the reconciled-incomplete success path and omits safe failed/cancelled terminal paths"
    - "data: submission ambiguity is represented by failure_class independently of terminal status/reconciliation and must dominate eligibility"
  and_gate: "Yes for safe UI eligibility: a terminal status must satisfy an allowed branch AND the latest failure class must be non-ambiguous; either condition alone is insufficient."
bug_class: Bohrbug (deterministic identity collision)
hypothesis: Confirmed correction — a terminal failed or cancelled execution is safe to route back to fresh approval only when its failure_class is not submission_ambiguous; active states and every submission_ambiguous execution must remain blocked.
test: Completed — focused behavior, static checks, scope integrity, and revert-and-reconfirm all passed.
expecting: Satisfied — failed/cancelled non-ambiguous executions expose a UI-only fresh-approval action; active and submission-ambiguous executions remain blocked.
next_action: Archive this resolved record, append the knowledge-base prevention entry, and commit only the explicit implementation and debug-documentation files.

## Evidence

- timestamp: 2026-09-17T01:21:00+08:00
  checked: Live API logs and Remediation workflow
  found: Execute returned 202 but the UI projected the historical execution ID; SRE trigger history had no new thread.
  implication: Dispatch was suppressed by durable execution identity before provider submission.
- timestamp: 2026-09-17T01:33:00+08:00
  checked: `.planning/STATE.md` scope and working-tree diff
  found: Phase 4 gates are retained and out of scope; the only partial code changes pass `decision_id` from the approved decision into `create_or_get` and add approval-scoped identity plus related active/ambiguous blocking.
  implication: The requested bug fix is isolated from Phase 4 gates, but the partial implementation is unverified and lacks required backend/API/UI regressions.
- timestamp: 2026-09-17T01:39:00+08:00
  checked: Debug knowledge base and complete execute/store/UI call path
  found: No prior KB entry matches this failure. `_check_approval_gate` returns the overall latest decision before the store claim, provider submission occurs only after a successful claim, and the baseline three-part identity permanently aliases all approvals.
  implication: The root cause is confirmed in code and the store is the correct side-effect-safety boundary.
- timestamp: 2026-09-17T01:40:00+08:00
  checked: Partial `_execution_identity` compatibility
  found: Appending an unconditional empty fourth identity segment would change legacy caller identity from `plan|snapshot|action` to `plan|snapshot|action|` and could duplicate existing records with a populated old identity.
  implication: Approval ID must be appended only when nonempty; empty-ID callers and persisted legacy identities must retain exact behavior.
- timestamp: 2026-09-17T01:50:00+08:00
  checked: Minimal implementation and regression additions
  found: Store schema 2.4 now appends only nonempty decision IDs, blocks same-snapshot active/ambiguous records, and defaults the new field for legacy reads; service passes the selected decision ID. UI action is local navigation only and performs no provider/API mutation.
  implication: The fix is ready for focused automated verification.
- timestamp: 2026-09-17T01:54:00+08:00
  checked: Focused Ruff and Python regression run
  found: Ruff passed. 82/83 focused backend tests passed; the new service test appended both decisions at the helper's identical fixed NOW, so `_latest_decision` correctly retained the first tie and reused its execution. The HTTP regression, which uses real distinct timestamps, passed.
  implication: The implementation behavior is supported; the deterministic service fixture must model a genuinely later approval timestamp.
- timestamp: 2026-09-17T01:55:00+08:00
  checked: Initial web test command
  found: npm was invoked from repository root, where no package.json exists.
  implication: This is an invocation error, not a product failure; rerun from `web/`.
- timestamp: 2026-09-17T01:59:00+08:00
  checked: Corrected focused backend run
  found: All 83 store/service/API tests passed after giving the fresh fixture decision a later timestamp.
  implication: Backend identity, idempotency, terminal resubmission, ambiguity blocking, and API projection regressions are green.
- timestamp: 2026-09-17T01:59:30+08:00
  checked: Correctly scoped web test invocation
  found: `web/node_modules` is absent, so the locked `vitest` binary is unavailable.
  implication: Install from the existing lockfile before evaluating frontend behavior.
- timestamp: 2026-09-17T02:05:00+08:00
  checked: Frontend focused verification
  found: Remediation page Vitest passed 70/70 tests; `tsc --noEmit` and Next ESLint completed with zero errors or warnings.
  implication: UI visibility/absence, navigation, no-provider-call behavior, typing, and lint are green.
- timestamp: 2026-09-17T02:07:00+08:00
  checked: Fix diff and guardrail signals 1, 2, and 3
  found: Target backend/UI tests pass; diff adds identity/state behavior rather than deleting or short-circuiting it. No Stryker configuration exists for the Python fix site, so mutation signal is unavailable.
  implication: Target and no-op/deletion signals pass; mutation check must be recorded skipped and revert-and-reconfirm remains.
- timestamp: 2026-09-17T02:13:00+08:00
  checked: Revert-and-reconfirm guardrail
  found: With implementation files stashed to baseline, both backend driving tests failed (fresh approval reused the original ID and API omitted approval_decision_id) and the UI driving test failed because Start a new run was absent. After restoring the implementation, all three passed.
  implication: The changed implementation directly fixes both the durable resubmission and UI navigation defects.
- timestamp: 2026-09-17T02:16:00+08:00
  checked: All execution-minting paths
  found: `supersede()` also obtains a current decision before `create_superseding`, but that store method did not accept or persist the decision ID.
  implication: To satisfy the execution-identity contract consistently, superseding identities must include a nonempty decision ID too, with an empty default for legacy callers.
- timestamp: 2026-09-17T02:23:00+08:00
  checked: Final focused Ruff and adjacent Python execution suites
  found: Ruff passed and 175/175 tests passed across execution service/API, retry, supersede, submission accounting, evidence reconciliation, verification scheduling, and review-fix suites.
  implication: The completed store/service change preserves adjacent lifecycle and ambiguity behavior.
- timestamp: 2026-09-17T02:29:00+08:00
  checked: Full frontend and final repository verification
  found: Full Vitest passed 64 files/797 tests; `tsc --noEmit`, Next ESLint, focused Ruff, and `git diff --check` all passed. `.planning/STATE.md` and Phase 4 gates are unchanged.
  implication: All applicable automated and scope-integrity checks are green; only human confirmation remains before archive.
- timestamp: 2026-09-17T02:33:00+08:00
  checked: User correction against store blocker, execution projection, UI predicate, and existing regressions
  found: Backend identity safety already permits terminal failed/cancelled records unless their latest failure_class is submission_ambiguous, but the UI action is restricted to terminal reconciled-incomplete evidence; the previous frontend absence test even treats a non-ambiguous failed timeout as permanently ineligible.
  implication: Preserve the backend safety boundary, strengthen its explicit failed/cancelled ambiguity regressions, and correct the frontend eligibility predicate/tests rather than changing provider dispatch.
- timestamp: 2026-09-17T02:40:00+08:00
  checked: Corrected eligibility implementation and regression matrix
  found: The UI now rejects top-level/latest-attempt submission ambiguity first, then allows failed/cancelled terminals or the existing succeeded/reconciled-incomplete case. Backend regressions carry explicit non-ambiguous failure classes and cover ambiguous failed/cancelled records; frontend regressions cover eligible failed/cancelled, blocked queued/running/retrying, and ambiguous absence without invoking approve/execute.
  implication: The minimal correction mirrors the durable store blocker and is ready for focused verification.
- timestamp: 2026-09-17T02:44:00+08:00
  checked: Focused corrected backend and frontend behavioral gates
  found: The focused execution store/service/API/supersede pytest selection passed, and remediation page Vitest passed 76/76 tests including failed/cancelled eligibility, active-state absence, ambiguity absence, and no approve/execute call from Start a new run.
  implication: The specified corrected behavior is green across the backend safety boundary and frontend operator workflow.
- timestamp: 2026-09-17T02:47:00+08:00
  checked: Focused static and scope-integrity gates
  found: Ruff, TypeScript no-emit, and Next ESLint passed; git diff has no whitespace errors, and `.planning/STATE.md` plus `.planning/phases` remain unchanged.
  implication: The correction is type/lint clean and has not altered the protected Phase 4 planning scope.
- timestamp: 2026-09-17T02:52:00+08:00
  checked: Correction-specific revert-and-reconfirm guardrail
  found: With only `web/src/app/remediation/page.tsx` stashed to baseline, the new failed/non-ambiguous Start-a-new-run regression failed because the action was absent; after restoring the implementation, the exact test passed.
  implication: The corrected UI eligibility implementation, rather than the fixture or an unrelated change, enables the required failed/cancelled recovery path.

## Eliminated

- hypothesis: The enabled revision did not receive the request.
  reason: API logs show the execute POST returned 202 on the enabled revision.

## Resolution

- root_cause: The durable execution identity omitted the current approval decision ID, so every approval for an unchanged plan/snapshot/action version collided with and reused the first execution forever, suppressing any later provider submission.
- fix: Added nonempty approval-decision ID to durable execution identity while preserving the legacy three-part identity, conservatively blocked related active or submission-ambiguous executions, passed the selected decision through the service, and added a UI-only `Start a new run` transition for succeeded/reconciled-incomplete or failed/cancelled non-ambiguous terminals back to fresh approval.
- verification:
    target_test:
      result: pass
      details: "The focused store/service/API/supersede pytest selection passed, and 76/76 remediation page tests passed."
    mutation_check:
      result: skipped
      reason_if_skipped: "No Stryker configuration exists for the Python execution-store fix site."
      mutant_killed: null
    no_op_deletion:
      result: pass
      deletion_justified_by_rca: false
      details: "Diff adds identity dimensions, conservative blockers, UI navigation, and assertions; it does not delete or short-circuit behavior."
    adjacent_tests:
      result: pass
      suites_run:
        - "175/175 adjacent Python execution/retry/supersede/submission/reconciliation tests"
        - "64/64 web test files, 797/797 tests"
        - "Correction-focused backend and 76-test remediation frontend suites"
        - "Ruff, TypeScript, Next ESLint, git diff --check, protected planning scope"
    revert_and_reconfirm:
      result: pass
      bug_returned_on_revert: true
      fixed_on_reapply: true
      details: "Initial backend fresh-approval and UI tests failed against stashed baseline and passed after restore; the corrected failed-terminal UI regression was separately reconfirmed failing with page.tsx stashed and passing after restoration."
    guardrail_verdict: accepted
- oracle_type: specified
- files_changed:
  - src/intelligence/remediation/execution_service.py
  - src/intelligence/remediation/execution_store.py
  - tests/test_remediation_execution_service.py
  - tests/test_api_remediation_execution.py
  - tests/test_remediation_execution_supersede.py
  - web/src/app/remediation/page.tsx
  - web/src/app/remediation/page.test.tsx
  - web/src/lib/services.ts
  - docs/REMEDIATION_PLANNING_RUNBOOK.md

## Prevention

- branching_5_whys:
    - branch: code
      chain: "Execution identity omitted approval decision ID -> unchanged snapshots permanently collided -> later approvals reused the first terminal record -> no provider dispatch occurred. The correction then exposed that the UI encoded only one safe terminal recovery reason (`reconciled_incomplete`) rather than the store's status/failure-class safety contract."
    - branch: data_contract
      chain: "Terminal status alone does not establish resubmission safety -> `failure_class=submission_ambiguous` means provider side effects may still exist -> eligibility must combine an allowed terminal state with non-ambiguous latest-attempt evidence -> the UI and store now enforce the same AND-gate."
  and_gate: "Fresh-run eligibility requires both a safe terminal branch (failed/cancelled, or succeeded with reconciled-incomplete evidence) and absence of submission ambiguity; active status or ambiguity independently blocks it."
- why_not_caught: "No end-to-end regression covered approval-scoped identity across a second approval, and the initial UI regression covered only reconciled-incomplete success rather than failed/cancelled terminals plus the failure-class negative matrix."
- recurrence_guard: "`tests/test_remediation_execution_service.py::{test_same_approval_execution_identity_is_idempotent_after_every_status,test_fresh_approval_creates_execution_after_terminal_non_ambiguous_status,test_fresh_approval_is_blocked_by_related_active_execution,test_fresh_approval_is_blocked_by_any_related_submission_ambiguity}`, `tests/test_api_remediation_execution.py::test_execute_same_approval_is_idempotent_but_fresh_terminal_approval_resubmits`, and the `Start a new run` cases in `web/src/app/remediation/page.test.tsx` lock same-approval idempotency, fresh terminal resubmission, active/ambiguity blocking, and UI-only navigation."
