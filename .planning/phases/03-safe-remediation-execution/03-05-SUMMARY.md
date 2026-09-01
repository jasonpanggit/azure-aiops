---
phase: 03-safe-remediation-execution
plan: 05
subsystem: remediation-execution
tags: [fastapi, atomic-claims, arm-verification, authorization, audit-history]
requires:
  - phase: 03-04
    provides: approval-bound immutable execution snapshots and bypass removal
provides:
  - Cross-replica atomic execution and retry claims with permanent identities
  - Append-only attempt and transition audit history
  - ARM-authoritative terminal verification using the submission credential boundary
  - Scope-safe reads, truthful cancellation, and server-owned eligibility
affects: [03-06, remediation-ui, remediation-api, patching]
actuals:
  tokens: 20540
  tasks: 4
  commits: 9
tech-stack:
  added: []
  patterns:
    - Dedicated local flock or finite OneLake lease around short durable claims
    - Immutable approval snapshot copied into every bounded attempt
    - Accepted provider submission remains running until ARM terminal polling
key-files:
  created:
    - tests/test_storage_locking.py
  modified:
    - src/intelligence/remediation/execution_store.py
    - src/intelligence/remediation/execution_service.py
    - src/intelligence/remediation/execution_verifier.py
    - src/api/routers/remediation.py
    - src/api/runtime.py
    - src/storage/locking.py
key-decisions:
  - "The durable pre-submit claim is the idempotency boundary because the supported Azure patch operations expose no idempotency token."
  - "Only failed or cancelled records may append a retry attempt; execute always returns the permanent matching execution identity."
  - "Provider work is never reported cancelled without a proven provider cancellation API."
patterns-established:
  - "Claim-before-side-effect: hold the dedicated lease only for read-validate-write, then release it before ARM calls."
  - "Lifecycle projection: clients consume service-owned executable, retryable, cancellable, remaining-attempt, and reason fields."
requirements-completed: [EXEC-03, EXEC-04, EXEC-05, EXEC-06]
coverage:
  - id: D1
    description: Atomic permanent execution identities and bounded immutable attempt history
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_remediation_execution_service.py, tests/test_remediation_execution_retry.py, tests/test_storage_locking.py"
        status: pass
    human_judgment: false
  - id: D2
    description: Submission remains running until ARM verifies succeeded, failed, or cancelled
    requirement: EXEC-05
    verification:
      - kind: integration
        ref: "tests/test_api_runtime.py, tests/test_remediation_execution_verifier.py, tests/test_api_remediation_execution.py"
        status: pass
    human_judgment: false
  - id: D3
    description: Scope-safe lifecycle reads, truthful cancellation, and authoritative eligibility
    requirement: EXEC-04
    verification:
      - kind: integration
        ref: "tests/test_api_remediation_router.py, tests/test_api_remediation_execution.py"
        status: pass
    human_judgment: false
  - id: D4
    description: Bounded retry consumes only the immutable approved snapshot
    requirement: EXEC-06
    verification:
      - kind: unit
        ref: "tests/test_remediation_execution_retry.py"
        status: pass
    human_judgment: false
duration: 8min
completed: 2026-09-01
status: complete
---

# Phase 3 Plan 5: Atomic Remediation Lifecycle Summary

**Cross-replica claim serialization, immutable attempt history, ARM-authoritative outcomes, scoped lifecycle controls, and truthful cancellation now protect approved patch execution.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-09-01T14:50:37Z
- **Completed:** 2026-09-01T14:58:47Z
- **Tasks:** 4
- **Files modified:** 13
- **Tests:** 156 passed

## Accomplishments

- Permanent plan/snapshot/action identities and a dedicated local/OneLake lock prevent duplicate execute or retry submissions across independent store instances.
- Every attempt and state transition preserves actor, approved target/patch selection, provider job, verified state, failure, outcome, and timestamp history.
- Production shares one ARM credential between patch submission and `ExecutionVerifier`; accepted work stays running until upstream ARM reports a terminal outcome.
- Execution reads and mutations authorize through plan scope, queued cancellation is atomic, provider cancellation limitations are explicit, and API eligibility is server-derived.
- All plan-owned Python files pass scoped Ruff checks and the complete 156-test Phase 3 backend regression passes.

## Task Commits

1. **Task 1 RED:** `131ed2dc` — failing atomic identity, concurrency, history, and lock tests.
2. **Task 1 GREEN:** `03477404` — atomic claims and immutable lifecycle history.
3. **Task 2 RED:** `f5dab7c5` — failing authoritative verification and runtime wiring tests.
4. **Task 2 GREEN:** `39460082` — shared ARM credential and terminal verification truth.
5. **Task 3 RED:** `522e0112` — failing scope, cancellation, and eligibility contract tests.
6. **Task 3 GREEN:** `bd4f8fdd` — scoped lifecycle controls and server-owned eligibility.
7. **Task 4:** `f4f780dc` — scoped Ruff fixes and assertion alignment.
8. **Post-task correctness fix:** `80d9d82b` — legacy identity safety and stale-reason cleanup.

## Files Created/Modified

- `src/intelligence/remediation/execution_store.py` — atomic CAS claims, dedicated lease use, permanent identity, attempts, and append-only transitions.
- `src/intelligence/remediation/execution_service.py` — idempotent submission, bounded retry, polling, cancellation, and eligibility projection.
- `src/intelligence/remediation/execution_verifier.py` — authenticated ARM polling and distinct cancelled outcome mapping.
- `src/api/routers/remediation.py` — scoped execution reads/mutations, polling, cancel route, and eligibility fields.
- `src/api/runtime.py` — shared Azure execution credential and production verifier injection.
- `src/storage/locking.py` — safe explicit lock-document names while preserving the ingestion default.
- `tests/test_storage_locking.py` — dedicated lock validation and ingestion-lock isolation.
- Six existing execution/runtime/router test modules — concurrency, lifecycle, verification, scope, cancellation, and eligibility coverage.

## Decisions Made

- Azure network calls occur only after the durable claim lock is released; no lease is held across provider latency.
- A legacy execution record without the new identity fields blocks automatic resubmission for its plan, favoring safety over duplicate side effects.
- Verification-unavailable remains running and visible; it never becomes success-shaped.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated stale retry and verifier fixtures for the 03-04 approval contract**
- **Found during:** Tasks 1 and 2 RED baselines.
- **Issue:** Existing fixtures omitted mandatory business evidence and immutable execution snapshots, so they failed before reaching the new lifecycle behavior.
- **Fix:** Added eligible business decisions, evidence citations, and canonical approved snapshots.
- **Files modified:** `tests/test_remediation_execution_retry.py`, `tests/test_remediation_execution_verifier.py`
- **Verification:** All Task 1/2 commands and the complete regression pass.
- **Committed in:** `131ed2dc`, `f5dab7c5`

**2. [Rule 1 - Bug] Prevented claim-lock retry logic from catching lifecycle conflicts raised inside the lock**
- **Found during:** Task 1 GREEN verification.
- **Issue:** The context manager caught `ExecutionClaimConflict` as a lock-acquisition `RuntimeError`, causing an invalid second yield.
- **Fix:** Isolated lock acquisition retries from exceptions raised by the protected claim body.
- **Files modified:** `src/intelligence/remediation/execution_store.py`
- **Verification:** Concurrent retry tests pass.
- **Committed in:** `03477404`

**3. [Rule 1 - Bug] Cleared stale operation reasons after state changes and fail-closed legacy identities**
- **Found during:** Final lifecycle review after Task 4.
- **Issue:** A provider-not-cancellable reason could survive a later terminal transition, and legacy records lacked enough identity data for safe duplicate matching.
- **Fix:** Clear operation-specific reasons when status advances and return legacy plan records rather than risk resubmission.
- **Files modified:** `src/intelligence/remediation/execution_store.py`
- **Verification:** Scoped Ruff, 50 lifecycle/API tests, and the complete regression pass.
- **Committed in:** `80d9d82b`

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking fixture update).
**Impact on plan:** All fixes were required for correctness or to exercise the planned safety behavior; no unrelated scope was added.

## Issues Encountered

- Existing unrelated Fabric edits appeared during execution. They were not read for implementation, modified, staged, committed, reverted, or included in validation.
- The final suite reports existing FastAPI/Starlette deprecation warnings; no tests are skipped or failing.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no new external service configuration is required.

## Next Phase Readiness

- The backend now publishes the stable lifecycle and eligibility contract required by the 03-06 operator UI.
- Real Azure UAT can safely validate one approved operation from running through an ARM-authoritative terminal outcome.

## Self-Check: PASSED

All 13 changed implementation/test files, the summary, and all 8 task commits were verified on disk.

---
*Phase: 03-safe-remediation-execution*
*Completed: 2026-09-01*
