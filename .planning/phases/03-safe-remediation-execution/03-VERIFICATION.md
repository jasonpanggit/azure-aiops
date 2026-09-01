---
phase: 03-safe-remediation-execution
verified: 2026-09-01T15:48:57Z
status: human_needed
score: 19/19 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 18/19
  gaps_closed:
    - "The backend/frontend attempt-history contract is now aligned on attempts[].attempt_number, and the remediation page renders Attempt 1 from the backend-shaped fixture."
    - "The production runtime now generates the fresh scoped planner repository used by execution_provider(scope), so the runtime-like scoped list/preview/approval/execute regression no longer fails with plan_not_found."
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "With a real least-privileged Azure operator identity, select a subscription-scoped controlled-patch-recovery plan, preview it, approve the exact server preview, execute it once, and poll until terminal."
    expected: "The request is accepted as running, terminal outcome is supplied only by ARM/provider polling, and the audit history includes the approved snapshot, attempts, verification result, failure/rollback details when applicable, and retry/cancel eligibility."
    why_human: "This final deployed Azure provider/identity flow depends on live Azure credentials, RBAC, and ARM operation polling that the focused TestClient regression cannot exercise."
---

# Phase 3: Safe Remediation Execution Verification Report

**Phase Goal:** As a platform operator, I want to run an approved remediation as a bounded, observable Azure job, so that I receive a verified and auditable outcome.
**Verified:** 2026-09-01T15:48:57Z
**Status:** human_needed
**Re-verification:** Yes — after the scoped execution-provider lifetime fix.

## User Flow Coverage

| Step | Expected | Codebase evidence | Status |
|---|---|---|---|
| Review | Operator sees business evidence plus exact server-derived target, patches, operation, preconditions, expected effect, and collateral impact | `web/src/app/remediation/page.tsx:1011-1047`; `src/api/routers/remediation.py:108-156`; focused UI/API tests pass | ✓ |
| Approve | Approval records the current server preview hash and rejects stale target/patch snapshots | `web/src/app/remediation/page.tsx:601-624`; `src/api/routers/operations.py:366-405`; approval tests pass | ✓ |
| Execute | The approved scoped plan can be executed by a least-privileged subscription operator | `remediation.py:241-253` narrows operate scope before execute; `runtime.py:2509-2513` now generates the fresh scope-selected planner before constructing `RemediationExecutionService`; focused runtime-like regression passes | ✓ |
| Observe | Durable execution can be polled until only ARM/provider verification supplies the terminal outcome | Scoped execute now creates the running execution in the focused regression; store/verifier tests cover pollable running and terminal ARM/provider outcomes | ✓ |
| Audit | Operator/auditor sees verified state, failure details, rollback guidance, immutable attempts, and retry/cancel eligibility | Backend emits `attempt_number`; TypeScript/page/tests now consume `attempt_number`; focused UI test passes | ✓ |
| Outcome | “I receive a verified and auditable outcome” | Automated code/test evidence now covers the scoped preview → approval → execute path and audit rendering; live Azure/RBAC/provider polling still needs human UAT | ⚠️ human |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Only typed, allowlisted low-risk actions are executable; arbitrary shell/CLI and direct patch mutation are unavailable | ✓ VERIFIED | `CONTROLLED_PATCH_RECOVERY` allowlist in `execution_service.py`; `patching.py` exposes only GET routes; `test_public_direct_patch_run_post_is_unavailable`/OpenAPI tests pass |
| 2 | Approver can preview exact targets, API operations, preconditions, expected effect, and collateral impact before approval | ✓ VERIFIED | `preview_plan` builds snapshot via `build_execution_snapshot(plan, _patching_service(context, scope), scope=scope)`; approval snapshot hash check exists; tests pass |
| 3 | Approved execution enforces least privilege, bounded and validated targets, preconditions, timeouts, idempotency, revalidation, and visible lifecycle states | ✓ VERIFIED | `execute_plan` computes operate scope before lookup; `execution_provider(scope)` receives that scope; runtime now calls `planner.generate_plans()` before wiring the fresh scoped repository into `RemediationExecutionService`; focused regression passes |
| 4 | Operator/auditor sees post-action actual state, outcome/failure, verification results, rollback/compensation status, and bounded retry history | ✓ VERIFIED | `execution_store.py:489-518` emits `attempt_number`; `services.ts:598-610` and `page.tsx:1113-1119` consume it; focused UI attempt-history test passes |
| 5 | Plan list is live, scoped, paginated, and evidence-wrapped | ✓ VERIFIED | `remediation.py:73-95`; router regression group passes |
| 6 | Plan detail returns a scope-safe 404 | ✓ VERIFIED | `_get_scoped_plan` scope-filters and hides out-of-scope plans; API tests pass |
| 7 | Approval requirements and decisions are readable | ✓ VERIFIED | `remediation.py:159-172`; operations decision route remains mounted |
| 8 | Business-decision context is readable | ✓ VERIFIED | `remediation.py:175-184` |
| 9 | Existing remediation web API routes remain mounted | ✓ VERIFIED | `app.py:235-248` includes operations, patching, and remediation routers; OpenAPI route tests pass |
| 10 | Execute rejects non-allowlisted, unapproved, stale, expired, and business-ineligible plans | ✓ VERIFIED | Shared `_check_approval_gate` and `validate_business_eligibility`; focused backend tests pass |
| 11 | Execute accepts no caller-supplied target, patch selection, or operation | ✓ VERIFIED | Public `execute(plan_id, requested_by=...)` resolves target/patch IDs only from approved snapshot |
| 12 | Execution records are pollable through scoped HTTP | ✓ VERIFIED | `get_execution` scope-checks associated plan and polls only running records; scoped out-of-scope test passes |
| 13 | Execution delegates to the existing patching/ARM stack | ✓ VERIFIED | Sole state-changing provider call is `self._patching.trigger(...)` in `execution_service.py:224-233`; patch router has no POST |
| 14 | Submission remains running until authoritative upstream verification | ✓ VERIFIED | `_submit_and_record` forces accepted provider response to `running`; terminal updates occur in `poll_verification` |
| 15 | ARM success, failure, cancellation, and non-terminal states map to durable truthful outcomes | ✓ VERIFIED | `poll_verification` maps succeeded/failed/cancelled/running; verifier/retry regression group passes |
| 16 | Rollback remains guidance-only and is never automatic | ✓ VERIFIED | Store copies rollback guidance; no automatic rollback submission path found |
| 17 | Retries are bounded, side-effect idempotent, approval/snapshot revalidated, and concurrency-safe | ✓ VERIFIED | `MAX_EXECUTION_ATTEMPTS=3`, immutable snapshot comparison, CAS claim tests pass |
| 18 | API responses expose verification, failure, rollback, eligibility, and immutable attempt data | ✓ VERIFIED | `execution_view` projects retry/cancel eligibility; API response tests cover history fields |
| 19 | Remediation router and execution lifecycle routes are mounted | ✓ VERIFIED | OpenAPI tests find execute, get execution, retry, cancel, and list-plan-executions routes |

**Score:** 19/19 truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/intelligence/remediation/approval_decisions.py` | Canonical snapshot/hash and durable approval binding | ✓ VERIFIED | Snapshot hash covers target, patches, operation, action version; approval route persists snapshot |
| `src/intelligence/remediation/execution_service.py` | Approval-gated, idempotent execution/retry/cancel lifecycle | ✓ VERIFIED | Substantive implementation; backend regression group passes |
| `src/intelligence/remediation/execution_store.py` | Durable CAS claims and append-only attempts/transitions | ✓ VERIFIED | `attempt_number`, transitions, revisioned writes, and lock-backed claims present |
| `src/intelligence/remediation/execution_verifier.py` | Authenticated read-only ARM operation polling | ✓ VERIFIED | Covered by verifier tests in focused backend group |
| `src/api/routers/remediation.py` | Scoped remediation execution API | ✓ VERIFIED | Execute/retry narrow to the principal's operate scope before lookup and resolve `execution_provider(scope)` for the same scoped path |
| `src/api/runtime.py` | Production provider wiring | ✓ VERIFIED | `_execution_service_for_scope(scope)` builds a scope-selected planner, calls `generate_plans()`, and passes that populated repository plus scope-selected patching service into `RemediationExecutionService` |
| `web/src/lib/services.ts` | Frontend execution contract | ✓ VERIFIED | Attempt contract now uses `attempt_number` |
| `web/src/app/remediation/page.tsx` | Governed execution UI and audit history | ✓ VERIFIED | Renders preview/approval/execution/audit state and `Attempt {attempt.attempt_number}` |
| `web/src/app/remediation/page.test.tsx` | UI regression coverage | ✓ VERIFIED | Backend-shaped `attempt_number` fixture and focused attempt-history assertion pass |
| `web/src/components/exposure/PatchInventory.tsx` | Read-only inventory handoff | ✓ VERIFIED | Direct mutation removed; service layer exposes only patch read methods |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Remediation UI | Phase 3 API | `remediationApi` preview/approve/execute/poll/retry/cancel | ✓ WIRED | Calls pass selected scope and response state is rendered |
| Preview/approval | Approved snapshot | Server recomputation and hash match | ✓ WIRED | Caller cannot supply target/patch/operation |
| Execute/retry | Patching service | Immutable snapshot to `_patching.trigger()` | ✓ WIRED | No caller widening path found |
| Runtime | ARM verifier | Shared credential to `ExecutionVerifier` | ✓ WIRED | `_execution_verifier()` injected in runtime execution service |
| Scoped preview/approval | Scoped execute | `execution_provider(scope)` | ✓ WIRED | Fresh provider lifetime is handled by regenerating plans inside runtime execution-service construction; approval decisions share the same decision store; focused scoped regression returns 202 running |
| Store attempt history | UI audit history | JSON/TypeScript field contract | ✓ WIRED | Backend `attempt_number` now matches `services.ts`, `page.tsx`, and tests |
| Patch inventory | Governed remediation | Read-only patching API plus remediation link | ✓ WIRED | Public `POST /api/v1/patching/runs` remains unavailable |

### Data-Flow Trace (Level 4)

| Artifact/Value | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Preview target/patches/hash | `execution_snapshot` | Scope-selected patch provider and plan | Yes | ✓ FLOWING |
| Approval snapshot | `decision.execution_snapshot` | Recomputed server snapshot with hash comparison | Yes | ✓ FLOWING |
| Execute target/patches | immutable snapshot | Durable approved decision snapshot | Yes for unscoped/persistent-planner flows | ✓ FLOWING |
| Scoped execution plan lookup | `plan_repository.get(plan_id)` | Fresh runtime `LiveRemediationPlanner.repository` populated by `generate_plans()` | Yes for runtime-like subscription scope | ✓ FLOWING |
| Provider outcome | `verified_state/outcome/failure_details` | ARM operation URL verifier | Yes | ✓ FLOWING |
| Execution status/history | `attempts/history` | Durable execution store | Yes | ✓ FLOWING |
| Attempt number in UI | `attempt.attempt_number` | Backend execution store → service contract → page render | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| New scoped regression claimed by fix | `pytest -q tests/test_api_remediation_execution.py::test_scoped_execute_uses_the_same_hybrid_providers_as_preview_and_approval` | 1 passed; Starlette deprecation warning only | ✓ PASS |
| Full remediation execution API file | `PYTHONPATH=src:tests python3 -m pytest tests/test_api_remediation_execution.py -q` | 14 passed; Starlette deprecation warning only | ✓ PASS |
| Focused Phase 3 backend regression group | `PYTHONPATH=src:tests python3 -m pytest tests/test_api_remediation_router.py tests/test_api_remediation_approvals.py tests/test_api_patching_router.py tests/test_remediation_execution_service.py tests/test_remediation_execution_retry.py tests/test_remediation_execution_verifier.py -q` | 102 passed; Starlette deprecation warning only | ✓ PASS |
| Scoped Ruff check | `PYTHONPATH=src ruff check src/api/dependencies.py src/api/routers/remediation.py src/api/runtime.py tests/test_api_remediation_execution.py` | All checks passed | ✓ PASS |
| Focused UI attempt-history regression | `cd web && npx vitest run src/app/remediation/page.test.tsx -t "renders verified failure details" --reporter=dot` | 1 passed, 27 skipped | ✓ PASS |
| Remediation UI suite | `cd web && npx vitest run src/app/remediation/page.test.tsx --reporter=dot` | 28 passed; React `act(...)` warnings | ✓ PASS |
| Scoped frontend lint | `cd web && npm run lint -- --file src/app/remediation/page.tsx --file src/lib/services.ts` | No ESLint warnings or errors | ✓ PASS |
| Runtime-like scoped provider lifetime regression | `pytest -q tests/test_api_remediation_execution.py::test_scoped_execute_uses_the_same_hybrid_providers_as_preview_and_approval` | Passed: scoped list/preview/approval/execute returns 202 running instead of `plan_not_found` | ✓ PASS |

### Probe Execution

No Phase 3 probe scripts were declared or discovered.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| EXEC-01 | 03-02, 03-04 | Typed allowlisted action catalog; no arbitrary shell/CLI | ✓ SATISFIED | Controlled patch recovery is the only executable action; public patch run POST unavailable |
| EXEC-02 | 03-01, 03-04, 03-06 | Preview target set, API operations, preconditions, expected effect, collateral impact | ✓ SATISFIED | Preview and approval snapshot routes/tests pass |
| EXEC-03 | 03-02, 03-04, 03-05 | Least privilege, bounded/validated targets, preconditions, timeouts, idempotency, revalidation | ✓ SATISFIED | Scoped execute receives operate scope, fresh runtime execution provider populates its scoped repository, and the focused regression no longer returns `plan_not_found` |
| EXEC-04 | 03-02, 03-05, 03-06 | Durable queued/running/succeeded/failed/retrying/cancelled states | ✓ SATISFIED | Store/service lifecycle and UI state tests pass |
| EXEC-05 | 03-03, 03-05, 03-06 | Post-action verification, actual state, outcome, failure details, rollback/compensation status | ✓ SATISFIED | Verifier mapping, store fields, and UI rendering verified |
| EXEC-06 | 03-03, 03-05, 03-06 | Bounded, visible, idempotent, revalidated retries | ✓ SATISFIED | Retry service/CAS tests pass; UI exposes retry only when server says retryable |

No Phase 3 requirement is orphaned.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `src/api/runtime.py:2497-2516,2638-2645` | Fresh scoped planner repository used for execution provider | ℹ️ RESOLVED | Runtime now generates the scoped plan repository before execution service lookup, closing the prior `plan_not_found` blocker |
| `tests/test_api_remediation_execution.py:247-360` | Runtime-like fresh scoped provider regression | ℹ️ RESOLVED | Test uses fresh scoped planners and passes list/preview/approval/execute through a scoped operator token |
| `web/src/app/remediation/page.tsx:588` | Stale evidence-pack text says Azure execution/rollback/outcome capture remain unavailable | ⚠️ WARNING | User-visible explanatory copy lags Phase 3 capability, but does not block execution safety; update with the next UI touch |
| Phase 3 fix files | No unreferenced TBD/FIXME/XXX markers | ℹ️ INFO | Debt-marker gate not triggered |

### Human Verification Required

Use a real least-privileged Azure operator identity to select a subscription-scoped controlled-patch-recovery plan, preview and approve it, execute once, observe running state, and confirm only ARM polling supplies terminal outcome and complete audit history.

### Gaps Summary

The previous scoped execution-provider lifetime blocker is closed. `runtime.py` now populates the fresh scope-selected planner repository before constructing `RemediationExecutionService`, and the focused runtime-like regression proves a subscription-scoped operator can list, preview, approve, and execute without `plan_not_found`. Automated must-haves are verified; final status remains `human_needed` for live Azure/RBAC/provider-polling UAT.

---

_Verified: 2026-09-01T15:48:57Z_
_Verifier: the agent (gsd-verifier)_
