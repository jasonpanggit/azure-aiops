---
phase: 03-safe-remediation-execution
plan: 04
subsystem: remediation-execution
tags: [fastapi, approval-snapshot, patching, authorization, tdd]
requires:
  - phase: 03-03
    provides: approval-gated remediation execution and bounded retry lifecycle
provides:
  - Canonical server-derived patch snapshots bound atomically to approvals
  - Deterministic business-impact eligibility before target or Azure access
  - Snapshot-only patch execution with drift and tamper rejection
  - Read-only public patching API with no direct mutation bypass
affects: [03-05, 03-06, remediation-api, patching]
actuals:
  tokens: 15508
  tasks: 4
  commits: 8
tech-stack:
  added: []
  patterns:
    - Canonical SHA-256 approval snapshot with constant-time preview comparison
    - Pure fail-closed business eligibility gate before operational lookups
    - Public read API delegating mutations only through approved remediation
key-files:
  created:
    - tests/test_remediation_approval_decisions.py
  modified:
    - src/intelligence/remediation/approval_decisions.py
    - src/intelligence/remediation/execution_service.py
    - src/api/models.py
    - src/api/routers/operations.py
    - src/api/routers/remediation.py
    - src/api/routers/patching.py
    - tests/test_remediation_execution_service.py
    - tests/test_api_remediation_approvals.py
    - tests/test_api_remediation_execution.py
    - tests/test_api_remediation_router.py
    - tests/test_api_patching_router.py
key-decisions:
  - "Only approved controlled-patch-recovery decisions carry an execution snapshot; rejected, expired, and recommendation-only decisions carry none."
  - "Execution revalidates canonical snapshot integrity and availability but never derives or widens the approved patch selection."
  - "The public patching router remains read-only; PatchingService.trigger is reachable only through remediation execution."
patterns-established:
  - "Approval-time binding: preview and approval call one scoped candidate-snapshot builder."
  - "Eligibility-before-I/O: all business-impact predicates fail before target lookup or Azure submission."
requirements-completed: [EXEC-01, EXEC-02, EXEC-03]
coverage:
  - id: D1
    description: Exact server-derived patch action is previewed and atomically persisted with approval
    requirement: EXEC-02
    verification:
      - kind: integration
        ref: "tests/test_api_remediation_approvals.py and tests/test_api_remediation_router.py"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_approval_decisions.py"
        status: pass
    human_judgment: false
  - id: D2
    description: Execution accepts only eligible business decisions and consumes the immutable approved snapshot
    requirement: EXEC-03
    verification:
      - kind: unit
        ref: "tests/test_remediation_execution_service.py"
        status: pass
      - kind: integration
        ref: "tests/test_api_remediation_execution.py"
        status: pass
    human_judgment: false
  - id: D3
    description: Direct public patch mutation is unavailable while patch reads remain exposed
    requirement: EXEC-01
    verification:
      - kind: integration
        ref: "tests/test_api_patching_router.py"
        status: pass
    human_judgment: false
  - id: D4
    description: Approval-boundary source and regression files satisfy scoped Ruff checks
    verification:
      - kind: other
        ref: "uv run ruff check <03-04 plan files>"
        status: pass
    human_judgment: false
duration: 7min
completed: 2026-09-01
status: complete
---

# Phase 3 Plan 4: Approval-Bound Execution Safety Summary

**Canonical approval snapshots now bind one exact target and patch set to an evidence-eligible decision, with no public direct patch mutation route.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-01T14:40:39Z
- **Completed:** 2026-09-01T14:48:16Z
- **Tasks:** 4
- **Files modified:** 12
- **Tests:** 93 passed

## Accomplishments

- Preview derives a scoped target, sorted patch IDs, target kind, operation, action version, and canonical SHA-256 hash; approval recomputes and constant-time compares that hash before atomically persisting the snapshot.
- Execution enforces the six deterministic business-impact predicates, validates snapshot version/hash, rejects target drift, and submits only the approved patch IDs without widening.
- `POST /api/v1/patching/runs` and its router request dependency were removed while patch target and run-history reads remain available.
- All scoped approval-boundary files pass Ruff and the combined regression suite passes 93 tests.

## Task Commits

1. **Task 1 RED:** `37ca3bb3` — failing approval snapshot tests
2. **Task 1 GREEN:** `03923555` — exact server-derived approval snapshots
3. **Task 2 RED:** `e1b082a8` — failing business eligibility and snapshot-consumption tests
4. **Task 2 GREEN:** `e7b938d4` — deterministic eligibility and snapshot-only execution
5. **Task 3 RED:** `d24933d1` — failing direct patch bypass tests
6. **Task 3 GREEN:** `74e46bb3` — public direct patch mutation removal
7. **Task 4:** `1bc8745e` — scoped Ruff quality fixes

## Files Created/Modified

- `src/intelligence/remediation/approval_decisions.py` — canonical snapshot builder/hash and atomic decision persistence.
- `src/intelligence/remediation/execution_service.py` — pure eligibility validation and approved-snapshot execution.
- `src/api/models.py` — bounded `preview_snapshot_hash` approval input.
- `src/api/routers/operations.py` — scoped snapshot recomputation and stale-preview rejection at approval.
- `src/api/routers/remediation.py` — exact execution snapshot in preview responses.
- `src/api/routers/patching.py` — read-only public patch API.
- `tests/test_remediation_approval_decisions.py` — snapshot derivation, failure, and immutability tests.
- `tests/test_remediation_execution_service.py` — predicate, tamper, drift, and no-widening tests.
- `tests/test_api_remediation_approvals.py` — approval hash and strict-input integration coverage.
- `tests/test_api_remediation_execution.py` — eligible approval snapshot execution fixture.
- `tests/test_api_remediation_router.py` — exact preview snapshot coverage.
- `tests/test_api_patching_router.py` — route absence and read-only OpenAPI coverage.

## Decisions Made

- Snapshot hashes cover only executable canonical fields; extra audit metadata cannot alter execution because execution reads only those validated fields.
- Missing and mismatched preview hashes share the stable `stale_execution_preview` reason and persist no decision.
- Current availability may invalidate an approved snapshot, but newly discovered patches never enter it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated the API execution fixture for the new mandatory safety gate**
- **Found during:** Task 2 verification
- **Issue:** The pre-existing API execution fixture directly appended an ineligible approval without an execution snapshot, so it no longer represented a valid executable decision.
- **Fix:** Made the fixture produce an evidence-eligible controlled-patch plan and append a canonical approval snapshot.
- **Files modified:** `tests/test_api_remediation_execution.py`
- **Verification:** Task 2 and combined regression commands pass.
- **Committed in:** `e7b938d4`, with scoped Ruff cleanup in `1bc8745e`

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** Required only to keep the plan-specified API regression proof aligned with the new approval contract; no production scope was added.

## Issues Encountered

- Ruff identified legacy unused locals and import-order findings in the plan-listed approval tests. Scoped fixes were inspected and committed; no unrelated files were touched.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Approval-bound target/patch parameters are ready for execution lifecycle hardening in 03-05.
- The only remaining working-tree modification is the user's unrelated Fabric debug artifact, which this plan did not modify, stage, commit, revert, or depend on.

## Self-Check: PASSED

All 12 changed implementation/test files and all 7 task commits were verified on disk.

---
*Phase: 03-safe-remediation-execution*
*Completed: 2026-09-01*
