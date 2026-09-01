---
phase: 10-fabric-medallion-capability-expansion
plan: 08
subsystem: fabric-retention
tags: [fabric, delta, retention, medallion, history]

requires:
  - phase: 10-fabric-medallion-capability-expansion (10-06)
    provides: Change/incident/predictive pipeline outputs and lifecycle retention baseline
provides:
  - Explicit MERGE retention contract for MED-07 history/trend tables
  - Regression test that enumerates protected history-preserving tables
affects: [10-09, 10-13, medallion-health, governance]

actuals:
  tokens: 988
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Centralized table write-mode selector (`_write_mode_for_table`) backed by explicit allow-list contract"

key-files:
  created:
    - .planning/phases/10-fabric-medallion-capability-expansion/10-08-SUMMARY.md
  modified:
    - src/fabric/sync_service.py
    - tests/test_incremental_sync.py
    - .planning/ROADMAP.md
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Treat `silver_cost_actuals` as historical facts and retain with MERGE because CostActual IDs are usage-date-scoped and represent time-series observations."
  - "Keep `silver_compliance` on OVERWRITE because it models current patch posture snapshots, not append-only trend records."
  - "Preserve existing Phase 2 STATE.md narrative; skip destructive state-advance tooling for this explicitly requested Phase 10 execution."

patterns-established:
  - "MED-07 retention behavior is pinned by a single expected-table set assertion plus per-table mode checks."

requirements-completed: [MED-07]

coverage:
  - id: D1
    description: "Fabric sync write-mode contract preserves change/incident/predictive/cost/lifecycle/patch history tables with MERGE while keeping audit events APPEND."
    requirement: "MED-07"
    verification:
      - kind: unit
        ref: "pytest tests/ -k \"sync_service and history\""
        status: pass
    human_judgment: false
  - id: D2
    description: "Regression test enumerates all required MED-07 history tables and fails if any regress to OVERWRITE."
    requirement: "MED-07"
    verification:
      - kind: unit
        ref: "pytest tests/test_incremental_sync.py -q"
        status: pass
    human_judgment: false

duration: 21min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 08: Historical retention extension summary

**Extended MED-07’s history-retention contract by adding change, incident, predictive, and cost trend tables to MERGE mode and locking the full allow-list with regression tests.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-09-01T10:35:54Z
- **Completed:** 2026-09-01T10:57:08Z
- **Tasks:** 2/2 completed
- **Files modified:** 4

## Accomplishments

- Added explicit retained-table allow-list coverage for `silver_change_history`, `silver_incident_history`, `silver_predictive_history`, and `silver_cost_actuals`.
- Refactored write-mode decision into `_write_mode_for_table()` for a single retention contract point.
- Added/updated regression tests in `tests/test_incremental_sync.py` to enumerate all retained tables and verify non-history table behavior remains unchanged.

## Task Commits

1. **Task 1 (TDD RED): add failing write-mode contract test** — `172bc97a` (test)
2. **Task 1 (TDD GREEN): extend write-mode MERGE allow-list** — `413d80bb` (feat)
3. **Task 2: enumerate retained-table contract regression test** — `b73de9f9` (test)

## Files Created/Modified

- `src/fabric/sync_service.py` — Added `_MERGE_WRITE_TABLES`, centralized mode resolver, and expanded MED-07 retention list.
- `tests/test_incremental_sync.py` — Added retained-table contract checks and explicit OVERWRITE guard for current-state compliance.
- `.planning/ROADMAP.md` — Marked 10-08 as complete and updated Phase 10 plan counter to 8/15.
- `.planning/REQUIREMENTS.md` — Marked MED-07 complete in checklist and traceability table.

## Decisions Made

- `silver_cost_actuals` is retained with MERGE (time-series usage/cost observations keyed by usage date–scoped identity).
- `silver_compliance` remains OVERWRITE (current-state posture snapshot).
- STATE automation that would rewrite active Phase 2 narrative was intentionally skipped per user direction; only roadmap/requirements were safely updated.

## Deviations from Plan

None - plan executed as specified.

## Auth Gates

None.

## Known Stubs

None found in modified implementation files.

## Threat Flags

None. No new trust-boundary surface was introduced (write-mode contract update only).

## Issues Encountered

- Local environment lacked `python` executable alias (only `python3` available); switched verification helper commands to `python3` where needed.

## Next Phase Readiness

- MED-07 is now contractually enforced for this plan’s identified trend/history tables.
- Ready for downstream MED-02/MED-05/MED-08 work without risking silent write-mode regressions on retained tables.

## Self-Check: PASSED

- Verified summary file exists and all task commit hashes are present in git history.
