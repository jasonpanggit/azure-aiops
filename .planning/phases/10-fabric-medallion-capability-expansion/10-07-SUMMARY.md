---
phase: 10-fabric-medallion-capability-expansion
plan: 07
subsystem: fabric-security-observability
tags: [fabric, onelake, capacity-health, lineage, maintenance, arm]

requires:
  - phase: 10-fabric-medallion-capability-expansion (10-02)
    provides: Referential-integrity and quality-gate baseline for medallion modules
  - phase: 10-fabric-medallion-capability-expansion (10-03)
    provides: Durable publication-state and telemetry patterns for operational visibility
provides:
  - ARM-based Fabric capacity paused/active health classifier with explicit unknown state
  - Read-only OneLake Data Access Role listing and role lookup wrapper
  - Read-only Delta maintenance last-run status reader from Fabric jobs history
  - Internal lineage_json surfacing helper and native Fabric workspace lineage deep-link helper
affects: [10-13, 10-14, medallion-health-api, connections-web-tab]

actuals:
  tokens: 4198
  tasks: 4
  commits: 9

tech-stack:
  added: []
  patterns:
    - "Read-only Fabric wrappers: GET-only helpers with explicit no-mutation public surface"
    - "Capacity health classification separates unavailable (Paused) from unknown (errors)"
    - "Lineage deep-link helper uses verified /groups/{workspaceId}/lineage portal route"

key-files:
  created:
    - src/fabric/capacity_health.py
    - src/fabric/data_access_roles.py
    - src/fabric/table_maintenance.py
    - src/fabric/lineage.py
    - tests/test_capacity_health.py
    - tests/test_data_access_roles.py
    - tests/test_table_maintenance_status.py
    - tests/test_lineage.py
  modified:
    - src/fabric/data_access_roles.py

key-decisions:
  - "Reuse existing azure-identity credential flow with ARM scope for capacity checks; no new SDK/client path."
  - "Keep data-access-role and maintenance modules strictly read-only with no role mutation or maintenance trigger functions."
  - "Use native Fabric workspace lineage deep-link route `/groups/{workspaceId}/lineage`, verified via Microsoft Learn lineage docs plus live Power BI/Fabric client bundle navigation logic."
  - "Preserve existing Phase 2 STATE narrative and avoid destructive state-advance tooling in this mixed-phase repository state."

patterns-established:
  - "MED-10 wrappers expose deterministic dict contracts with explicit status enums and safe fallbacks."

requirements-completed: [MED-10]

coverage:
  - id: D1
    description: "Capacity health read path distinguishes Active/Paused/error into healthy/unavailable/unknown."
    requirement: "MED-10"
    verification:
      - kind: unit
        ref: "tests/test_capacity_health.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "OneLake role visibility uses paginated read-only list/get wrappers and rejects unsupported item types."
    requirement: "MED-10"
    verification:
      - kind: unit
        ref: "tests/test_data_access_roles.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Delta maintenance observability returns latest run status without triggering maintenance."
    requirement: "MED-10"
    verification:
      - kind: unit
        ref: "tests/test_table_maintenance_status.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Internal lineage_json is surfaced safely and native workspace lineage URL helper is pure and validated."
    requirement: "MED-10"
    verification:
      - kind: unit
        ref: "tests/test_lineage.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "Known unrelated baseline failures remain unrelated and reproducible after plan verification."
    verification:
      - kind: unit
        ref: "pytest tests/test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state tests/test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark -q"
        status: fail
    human_judgment: true
    rationale: "These are pre-existing baseline failures outside 10-07 scope and intentionally not modified."

duration: 17min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 07: OneLake roles, capacity, maintenance, and lineage summary

**Implemented four MED-10 read-only capability modules (capacity state, OneLake role visibility, maintenance run status, lineage surfacing/deep-linking) with deterministic tests and no runtime mutation surface.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-09-01T18:12:12+08:00
- **Completed:** 2026-09-01T18:29:43+08:00
- **Tasks:** 4/4 completed
- **Files modified:** 8 (8 created, 1 subsequently adjusted)

## Accomplishments

- Added `check_capacity_state()` ARM GET wrapper with healthy/unavailable/unknown classification and explicit paused handling.
- Added read-only `list_roles()`/`get_role()` Data Access Roles wrapper using `FabricClient.iter_items` pagination and unsupported-type guardrails.
- Added read-only `last_maintenance_status()` for Monitoring-hub/job-history style status retrieval with `no_runs_recorded` handling.
- Added `entity_lineage_summary()` and `native_lineage_url()` to surface internal provenance and native Fabric lineage navigation without rebuilding lineage graphs.
- Verified native lineage URL pattern against live Microsoft Learn lineage docs plus live Power BI/Fabric bundle route behavior showing `/groups/{workspaceId}/lineage` navigation.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fabric capacity paused/throttled detection** - `45417181` (test), `060b0b3b` (feat)
2. **Task 2: OneLake Data Access Roles read-only wrapper** - `8d2d8d5b` (test), `b599508d` (feat)
3. **Task 3: Delta table maintenance status observability** - `a425c9d8` (test), `09f10de1` (feat)
4. **Task 4: Internal ontology lineage read path + native lineage deep-link** - `574d2a59` (test), `59d77439` (feat)
5. **Post-task correctness alignment (MED-10 scope guardrail)** - `6f022181` (fix)

## Files Created/Modified

- `src/fabric/capacity_health.py` - ARM-based capacity health read wrapper
- `src/fabric/data_access_roles.py` - read-only OneLake roles list/get wrapper
- `src/fabric/table_maintenance.py` - read-only maintenance last-run status helper
- `src/fabric/lineage.py` - internal lineage projection + native workspace lineage URL helper
- `tests/test_capacity_health.py` - capacity classification and credential-path coverage
- `tests/test_data_access_roles.py` - pagination/read-only/unsupported-type coverage
- `tests/test_table_maintenance_status.py` - last-run/no-runs/read-only-surface coverage
- `tests/test_lineage.py` - lineage lookup/non-leakage/url/pure-function coverage

## Decisions Made

- Reused existing `azure-identity` mechanism (`DefaultAzureCredential` and ARM scope) for capacity checks to avoid introducing parallel credential paths.
- Kept role and maintenance modules intentionally non-mutating to satisfy least-privilege and no-implicit-operations constraints.
- Used native lineage deep link route based on live-verified workspace switcher navigation logic (`/groups/{workspaceId}/lineage`) rather than inventing a custom visualization.
- Because `.planning/STATE.md` currently tracks finalized Phase 2 session state, skipped destructive phase-advance state tooling and made only non-destructive state annotation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Support mirrored item variants for Data Access Roles**
- **Found during:** Final MED-10 conformance review after Task 2
- **Issue:** Initial guard allowed only `Lakehouse`, which was too narrow versus research-confirmed mirrored item support.
- **Fix:** Expanded support check to accept `Lakehouse` plus `Mirrored*` item variants while still rejecting unsupported item types such as `Warehouse`/`SemanticModel`.
- **Files modified:** `src/fabric/data_access_roles.py`
- **Verification:** `pytest tests/test_data_access_roles.py -q` pass
- **Committed in:** `6f022181`

---

**Total deviations:** 1 auto-fixed (Rule 2)
**Impact on plan:** Required for MED-10 correctness; no scope creep.

## Auth Gates

None.

## Issues Encountered

- The repository has active Phase 2 state metadata; running full `state.advance-plan` style automation would risk overwriting that narrative. Used non-destructive updates only and documented this explicitly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MED-10 backend capability modules for capacity, role visibility, maintenance observability, and lineage surfacing are now implemented and unit-verified.
- Ready for downstream API composition work (`10-13`) and web surface wiring (`10-14`).

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

- Verified expected 10-07 implementation files exist on disk.
- Verified all 10-07 task commit hashes are present in git history.
