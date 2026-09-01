---
phase: 03-safe-remediation-execution
verified: 2026-09-01T14:20:55Z
status: gaps_found
score: 12/19 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "The MVP operator flow allows an operator to run an approved remediation and receive a verified, auditable outcome."
    status: failed
    reason: "The existing remediation page remains a Phase 2 approval-only surface and explicitly says execution and realized outcomes are unavailable."
    artifacts:
      - path: "web/src/app/remediation/page.tsx"
        issue: "No preview, execute, execution polling, retry, or verified-outcome controls; copy explicitly says no Azure execution is available."
      - path: "web/src/lib/services.ts"
        issue: "No client methods call the new /api/v1/remediation/plans/* execution API."
    missing:
      - "Wire the operator-facing flow to preview, execute, poll verification, display failures/rollback guidance, and retry."
  - truth: "No direct action bypasses the approved plan and its business-impact evidence."
    status: failed
    reason: "POST /api/v1/patching/runs remains mounted and accepts caller-supplied target_id, patch_ids, approved_by, and reason without requiring a remediation plan, decision record, action version, or business-impact evidence."
    artifacts:
      - path: "src/api/routers/patching.py"
        issue: "create_patch_run calls PatchingService.trigger directly from PatchRunCreateRequest."
      - path: "src/api/models.py"
        issue: "PatchRunCreateRequest exposes caller-controlled target and patch selection."
      - path: "src/intelligence/remediation/execution_service.py"
        issue: "Approval gate checks action/status/version/expiry only; it does not validate business-impact evidence."
    missing:
      - "Disable or place the direct patch mutation route behind the same approved-plan gate."
      - "Require and revalidate business-impact/evidence context before execution."
  - truth: "Submission is never treated as success; production execution polls Azure and persists the verified outcome or failure."
    status: failed
    reason: "The runtime constructs RemediationExecutionService without ExecutionVerifier. The service intentionally maps accepted submission to succeeded when no verifier is configured, and GET /executions/{id} only reads the store instead of invoking poll_verification()."
    artifacts:
      - path: "src/api/runtime.py"
        issue: "execution_provider omits execution_verifier."
      - path: "src/intelligence/remediation/execution_service.py"
        issue: "Lines 174-180 preserve immediate succeeded status when verifier is absent."
      - path: "src/api/routers/remediation.py"
        issue: "GET /executions/{id} reads store.get() only; no production caller of poll_verification exists."
      - path: "tests/test_api_remediation_execution.py"
        issue: "API test asserts an accepted submission is immediately succeeded, masking the production wiring gap."
    missing:
      - "Construct and inject ExecutionVerifier in the real runtime."
      - "Wire polling/scheduling or the execution GET endpoint to poll_verification safely."
      - "Remove the no-verifier immediate-success fallback."
      - "Add API-level tests proving accepted remains running until Azure reports a terminal outcome."
  - truth: "Retries and duplicate execute requests are bounded, idempotent, and revalidate target context."
    status: failed
    reason: "execute() resubmits even when store.create() returns an existing non-terminal execution; retry() also permits running executions. Retry resolves the current target and selects all currently available patches, so a changed patch set can widen a previously approved attempt. No provider idempotency key is used."
    artifacts:
      - path: "src/intelligence/remediation/execution_service.py"
        issue: "execute() does not distinguish a newly created record from an existing non-terminal record; retry() rejects only succeeded/max-attempt cases; _resolve_target() uses sorted(target.available_patch_ids)."
      - path: "tests/test_remediation_execution_retry.py"
        issue: "Covers retries after failure but not duplicate execute or retry while running."
    missing:
      - "Return the existing non-terminal execution without another Azure submission."
      - "Reject retry unless the execution is in an explicitly retryable terminal state."
      - "Persist the approved target/patch snapshot and compare it on retry."
      - "Add duplicate/concurrent request tests and provider-side idempotency where supported."
  - truth: "The durable execution lifecycle and audit record expose all required states and bounded attempt history under caller scope."
    status: failed
    reason: "cancelled exists only as an accepted enum value with no transition or test; retry overwrites provider_job_id and failure fields instead of retaining per-attempt history; GET /executions/{id} does not scope-check the execution's plan."
    artifacts:
      - path: "src/intelligence/remediation/execution_store.py"
        issue: "No attempt-history collection; cancelled is declarative only."
      - path: "src/api/routers/remediation.py"
        issue: "Single-execution GET does not call _get_scoped_plan before returning the record."
    missing:
      - "Persist immutable per-attempt transition/provider/outcome history."
      - "Implement or explicitly record cancellation transitions."
      - "Scope-authorize execution reads through their plan."
---

# Phase 3: Safe Remediation Execution Verification Report

**Phase Goal:** As a platform operator, I want to run an approved remediation as a bounded, observable Azure job, so that I receive a verified and auditable outcome.
**Verified:** 2026-09-01T14:20:55Z
**Status:** gaps_found
**Re-verification:** No prior Phase 3 VERIFICATION.md existed; this is the first code verification after the MVP goal repair.

## User Flow Coverage

| Step | Expected | Evidence | Status |
|---|---|---|---|
| Review | Operator previews exact target, operation, preconditions, effect, and collateral impact | Backend preview exists at `remediation.py:104-140`; the web page does not call it | ✗ |
| Execute | Operator runs an approved `controlled-patch-recovery` plan | Backend endpoint exists; `page.tsx` explicitly says execution is unavailable | ✗ |
| Observe | Operator sees queued/running/retrying/terminal progress | Execution GET exists, but no UI integration and production marks submission succeeded | ✗ |
| Verify outcome | Operator receives Azure-verified actual state, failure detail, rollback guidance, and audit history | Verifier module exists but is not runtime-wired; attempt history is absent | ✗ |
| Outcome | “I receive a verified and auditable outcome” | Not achievable through the shipped operator flow | ✗ |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Only typed, allowlisted low-risk actions are executable; no arbitrary shell/CLI or bypass exists | ✗ FAILED | Remediation service allowlists one action and has no shell use, but mounted `POST /api/v1/patching/runs` bypasses plans |
| 2 | Approver can preview exact targets, operations, preconditions, effects, and collateral impact | ✓ VERIFIED | `preview_plan()` derives these fields from the stored plan; router tests pass |
| 3 | Approved execution enforces bounded targets, validation, timeout, idempotency, revalidation, and all durable states | ✗ FAILED | Duplicate/running retries can resubmit; cancelled is enum-only |
| 4 | Operator/auditor sees verified actual state, outcome/failure, rollback status, and bounded retry history | ✗ FAILED | Production verifier is disconnected and no per-attempt history is persisted |
| 5 | Plan list is live, scoped, paginated, and evidence-wrapped | ✓ VERIFIED | `remediation.py:70-91` |
| 6 | Plan detail returns a scope-safe 404 | ✓ VERIFIED | `_get_scoped_plan()` and passing router tests |
| 7 | Approval requirements and decisions are readable | ✓ VERIFIED | `plan_approvals()` delegates to decision store |
| 8 | Business-decision context is readable | ✓ VERIFIED | `plan_business_decision()` returns stored plan context |
| 9 | Existing remediation web API routes remain mounted | ✓ VERIFIED | OpenAPI regression tests pass |
| 10 | Remediation execute rejects non-allowlisted, unapproved, stale, and expired plans | ✓ VERIFIED | Shared `_check_approval_gate()` plus service/API tests |
| 11 | Remediation execute accepts no caller-supplied target or operation | ✓ VERIFIED | `execute(plan_id, requested_by=...)`; target is resolved by plan resource ID |
| 12 | Execution record can be polled through HTTP | ✓ VERIFIED | `GET /api/v1/remediation/executions/{id}` is mounted and tested |
| 13 | Execution delegates to the existing patching stack | ✓ VERIFIED | Service calls `PatchingService.trigger`; only `azure_adapter.py` performs ARM POST |
| 14 | Submission remains running until upstream verification | ✗ FAILED | Runtime omits verifier and service falls back to immediate succeeded |
| 15 | Upstream failure is persisted with actual state and details | ✗ FAILED | Unit implementation exists, but no production path calls it |
| 16 | Rollback remains guidance-only and is never automatic | ✓ VERIFIED | Guidance copied from plan; `automatic_rollback=False`; no reversal call found |
| 17 | Retries are bounded, idempotent, and revalidate approval and target context | ✗ FAILED | Max=3 and approval checks exist, but duplicate/running retries and changing patch selection are unsafe |
| 18 | Execution response exposes verification, failure, rollback, and retry history | ✗ FAILED | Current fields exist, but historical attempts are overwritten |
| 19 | Remediation router is mounted and the Phase 2 404 gap is closed | ✓ VERIFIED | `app.py:46,248`; OpenAPI/router tests pass |

**Score:** 12/19 truths verified.

### Required Artifacts

| Artifact | Status | Details |
|---|---|---|
| `src/api/routers/remediation.py` | ⚠️ PARTIAL | Substantive and mounted; execution polling does not poll Azure and single-record reads are not plan-scope checked |
| `src/intelligence/remediation/execution_service.py` | ✗ FAILED | Substantive, but immediate-success fallback and duplicate retry behavior violate core invariants |
| `src/intelligence/remediation/execution_store.py` | ⚠️ PARTIAL | Durable file/OneLake persistence; no immutable attempt history or cancellation flow |
| `src/intelligence/remediation/execution_verifier.py` | ⚠️ ORPHANED | Substantive and unit-tested, but absent from runtime wiring |
| `src/api/runtime.py` | ✗ FAILED | Execution service is wired without an `ExecutionVerifier` |
| `web/src/app/remediation/page.tsx` | ✗ FAILED | Approval-only Phase 2 UI; Phase 3 execution flow is absent |

### Key Link Verification

| From | To | Status | Details |
|---|---|---|---|
| `app.py` | remediation router | ✓ WIRED | Router imported and included |
| remediation execute endpoint | approval gate | ✓ WIRED | `_get_scoped_plan` then `service.execute` |
| execution service | patching service/ARM adapter | ✓ WIRED | One-target `PatchingService.trigger` path |
| runtime | execution store | ✓ WIRED | Durable store singleton injected |
| runtime | execution verifier | ✗ NOT WIRED | No verifier injected |
| execution GET | upstream verification poll | ✗ NOT WIRED | Store read only |
| remediation UI | Phase 3 API | ✗ NOT WIRED | No service methods or controls |

### Data-Flow Trace

| Value | Source | Status |
|---|---|---|
| Preview fields | Generated stored remediation plan | ✓ FLOWING |
| Execute target ID | Stored plan resource/resource_key | ✓ FLOWING |
| Patch selection | Current target `available_patch_ids`, not approved snapshot | ⚠️ WIDENABLE |
| Verified state/failure | ARM operation URL via verifier | ✗ DISCONNECTED in runtime |
| Rollback guidance | `plan.rollback_plan.rollback_actions` | ✓ FLOWING |
| Retry history | Overwritten current execution fields | ✗ MISSING |

### Behavioral Spot-Checks

| Check | Result | Status |
|---|---|---|
| Targeted backend suite | 93 collected and passed; 1 Starlette/httpx deprecation warning | ✓ PASS |
| Ruff targeted lint | Exit 1, 15 findings | ✗ FAIL |
| Phase probes | No probe declared or discovered | SKIPPED |

Exact test command:

```text
uv run pytest tests/test_api_remediation_router.py tests/test_api_remediation_approvals.py tests/test_api_remediation_execution.py tests/test_remediation_execution_service.py tests/test_remediation_execution_retry.py tests/test_remediation_execution_verifier.py tests/test_patching_azure_adapter.py tests/test_api_patching_router.py -q
```

Result: **93 passed**, exit 0; one `StarletteDeprecationWarning`.

Exact lint command used `uv run ruff check` over the Phase 3 implementation and tests. Result: **15 errors**, exit 1: 5 import-order findings, 5 unused unpacked variables, 3 unused imports, one `Callable` modernization, and one redundant f-string.

### Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| EXEC-01 | ✗ BLOCKED | One action is allowlisted in remediation service, but direct patch mutation bypass remains |
| EXEC-02 | ✓ SATISFIED | Preview endpoint returns required plan-derived fields |
| EXEC-03 | ✗ BLOCKED | Duplicate execution/retry is not idempotent; approved target snapshot is not retained |
| EXEC-04 | ✗ BLOCKED | Store has six status strings, but submitted becomes succeeded in production and cancellation is not wired |
| EXEC-05 | ✗ BLOCKED | Verifier is not connected to runtime/API; actual outcomes are not persisted in the deployed path |
| EXEC-06 | ✗ BLOCKED | Retry ceiling and approval checks exist, but retry safety/idempotency/target-context validation are incomplete |

No Phase 3 requirements are orphaned from the plans.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|---|---|---|---|
| `execution_service.py:174-180` | Compatibility fallback claims succeeded without verification | 🛑 BLOCKER | Violates the phase's central safety invariant |
| `patching.py:83-133` | Parallel direct mutation API bypasses plan evidence | 🛑 BLOCKER | Approval/business-impact controls can be bypassed |
| `execution_service.py:85-101` | Existing non-terminal record still resubmitted | 🛑 BLOCKER | Duplicate Azure side effects |
| `execution_service.py:219-260` | Running execution may be retried | 🛑 BLOCKER | Concurrent duplicate submission |
| `remediation.py:231-246` | Execution read omits plan scope check | 🛑 BLOCKER | Cross-scope execution metadata disclosure |
| Phase files | No TBD/FIXME/XXX debt markers found | ℹ️ INFO | No debt-marker gate triggered |

### Human Verification Required

None at this stage. The blocking gaps are directly observable in code. After they are fixed, real Azure UAT must confirm one approved patch job stays running after submission, reaches a terminal state only from the upstream ARM operation, and exposes the resulting audit record to an authorized operator.

### Gaps Summary

The router mount and read/preview surfaces are real, and the isolated verifier/retry unit tests pass. The phase goal is nevertheless not achieved: the operator UI has no execution flow, a direct patch API bypasses approved remediation plans, production never injects or calls the verifier, accepted submissions are marked succeeded, retries can duplicate or widen side effects, and the audit lifecycle lacks scoped immutable attempt history.

---

_Verified: 2026-09-01T14:20:55Z_
_Verifier: the agent (gsd-verifier)_
