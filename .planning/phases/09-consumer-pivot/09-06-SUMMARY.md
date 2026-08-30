---
phase: 09-consumer-pivot
plan: 06
subsystem: testing
tags: [pytest, regression, provenance, baseline]

requires:
  - phase: 09-consumer-pivot
    provides: completed consumer-pivot implementation and focused backend suites
provides:
  - Evidence-backed ownership record for all three full-suite failures
  - Separate Phase 9 focused gate and cross-domain baseline regression policy
affects: [consumer-pivot, governance, situations, ontology, storage]

tech-stack:
  added: []
  patterns: [detached-baseline reproduction, focused-vs-full-suite regression gates]

key-files:
  created:
    - .planning/phases/09-consumer-pivot/09-REGRESSION-OWNERSHIP.md
  modified:
    - .planning/phases/09-consumer-pivot/09-VERIFICATION.md

key-decisions:
  - "Treat failures reproduced at the 1b730f77 pre-Phase-9 boundary as baseline failures, not Phase 9 regressions."
  - "Keep all three failing tests active and use the focused Phase 9 suite independently from the full-suite baseline gate."

actuals:
  tokens: 9500
  tasks: 2
  commits: 3

requirements-completed: [INV-09, INV-10]

coverage:
  - id: D1
    description: "Three full-suite failures have reproducible evidence, commit/file ownership, causal classification, and follow-up regression policy."
    verification:
      - kind: integration
        ref: "uv run python -m pytest tests/test_governance_pipeline.py::TestGovernancePipelineComparison::test_spn_governance_matches_aiops tests/test_situations_ontology.py::test_situations_are_registered_as_ontology_entities_with_typed_links tests/test_storage.py::test_partial_publish_preserves_hash_baseline_for_next_full_publish -q"
        status: pass
      - kind: other
        ref: "Detached pre-Phase-9 baseline 1b730f77 reproduced the same three failures"
        status: pass
    human_judgment: false
  - id: D2
    description: "Phase 9 focused backend verification remains green while the full suite transparently reports only the three assigned baseline failures."
    verification:
      - kind: integration
        ref: "uv run python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py tests/test_api_copilot_investigation.py tests/test_network_analysis.py tests/test_agent_queries.py tests/test_inventory_read_port.py tests/test_api_runtime.py tests/test_foundry_agent.py tests/test_fabric_client.py tests/test_inventory_consumer_guards.py -q"
        status: pass
      - kind: integration
        ref: "uv run python -m pytest -q"
        status: fail
    human_judgment: true
    rationale: "The full suite intentionally retains three pre-existing failures; the verifier must confirm the residual set matches the ownership record."

duration: 20min
completed: 2026-08-28
status: complete
---

# Phase 09 Plan 06: Full-Suite Regression Ownership Summary

**The three backend failures reproduce before Phase 9, while all 134 Phase 9 focused backend tests pass and the residual baseline is explicitly owned rather than hidden.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-28T15:52:38+08:00
- **Completed:** 2026-08-28T16:12:38+08:00
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Ran each failing test in isolation and reproduced all three at detached commit `1b730f77`, the pre-Phase-9 boundary.
- Recorded precise test/source ownership: governance expiry fixture/classification, situation ontology link projection, and storage hash-baseline handling.
- Updated the phase verification report so the full-suite baseline result and resolved Phase 9 blockers are not misreported.
- Preserved focused Phase 9 coverage at `134 passed`; the full suite reports `3 failed, 1532 passed, 2 warnings` with no skips, xfails, or weakened assertions.

## Task Commits

1. **Task 1: Trace each full-suite failure across the Phase 9 commit boundary** - `44a9543e` (`test`)
2. **Task 2: Fix Phase 9-caused failures or formalize unrelated regression handling** - `77690de6` (`docs`)
3. **Verification report alignment** - `2bea3fba` (`docs`)

**Plan metadata:** pending final metadata commit.

## Files Created/Modified

- `.planning/phases/09-consumer-pivot/09-REGRESSION-OWNERSHIP.md` - Evidence, provenance, causal classification, and regression handling for the three residual failures.
- `.planning/phases/09-consumer-pivot/09-VERIFICATION.md` - Updated full-suite baseline result and Phase 9 verification narrative.

## Decisions Made

- No Phase 9 source fix was justified: none of the failing paths were modified by Phase 9, and all failures reproduced at the boundary.
- The full-suite failures remain visible as baseline defects owned by their originating domains; the Phase 9 focused suite is the actionable phase gate.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Used `uv run python` instead of `python`**
- **Found during:** Task 1 verification
- **Issue:** The repository's supported runner is required to expose the Python 3.11 environment.
- **Fix:** Used the existing `uv` project runner for all isolated, focused, and full-suite commands.
- **Files modified:** None.
- **Verification:** Focused suite passed; full suite reproduced the documented three failures.
- **Committed in:** No source change.

### Scope Clarification

The ownership record is the only implementation artifact needed. Governance, situation/ontology,
and storage repairs are deliberately deferred to their owning domains; changing them here would
misattribute unrelated behavior to INV-09/INV-10.

**Total deviations:** 1 execution adjustment; no behavior deviations.

## Issues Encountered

The full backend suite remains red for the three pre-existing failures documented in
`09-REGRESSION-OWNERSHIP.md`. This is an explicit residual baseline, not a hidden or suppressed
Phase 9 regression.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 9 regression ownership is complete. The next phase can use the focused suite as the
consumer-pivot gate and the ownership record as the expected full-suite baseline until the
three domain owners repair their tests/implementations.

## Self-Check: PASSED

- `.planning/phases/09-consumer-pivot/09-REGRESSION-OWNERSHIP.md` exists.
- `.planning/phases/09-consumer-pivot/09-06-SUMMARY.md` exists.
- Task commits `44a9543e` and `77690de6` exist.
- The Phase 9 focused suite passed with 134 tests.
- The full suite residual set matches the three ownership rows.
