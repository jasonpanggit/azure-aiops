---
phase: 06-software-and-os-inventory-visibility
plan: 01
subsystem: inventory
tags: [fastapi, pytest, nextjs, vitest, azure-resource-graph, os-inventory]

# Dependency graph
requires:
  - phase: 05-controlled-pilot-readiness
    provides: authenticated API, effective ReadScope, evidence envelopes, and immutable generation boundary
provides:
  - scope-first grouped OS inventory provider for Azure VM and Arc observations
  - versioned collection and server-validated group-detail API routes
  - typed Software Inventory OS tab with evidence, source states, lifecycle review, and drill-down
affects: [06-02, 06-03, 06-04, 06-09, inventory, software-inventory]

# Actuals (#2632)
actuals:
  tokens: 13809
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - immutable frozen inventory DTOs with raw payloads excluded from API responses
    - effective ReadScope filtering before classification, grouping, counts, evidence, and pagination
    - per-source lifecycle states preserved independently from successful empty results

key-files:
  created:
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - src/api/routers/inventory.py
    - tests/fixtures/mock_inventory_arg.json
    - tests/test_inventory_provider.py
    - tests/test_api_inventory_router.py
    - web/src/app/software-inventory/page.tsx
    - web/src/app/software-inventory/page.test.tsx
  modified:
    - src/api/app.py
    - src/api/dependencies.py
    - src/api/runtime.py
    - web/src/lib/services.ts
    - web/src/lib/types.ts

key-decisions:
  - "D-01: Group OS observations by canonical OS name/version and use server-owned keys for drill-down."
  - "D-02: Keep Azure VM and Arc source labels in one grouped view without collapsing source identity."
  - "D-09: Unknown lifecycle matches remain visible with an explicit EOL date review flag."
  - "Read source status from the active immutable generation and scope row counts before projection."

patterns-established:
  - "InventorySnapshot: immutable observations, generation metadata, query version, and independent source status."
  - "InventoryService: scope first, then lifecycle classification and deterministic resource-id ordering."

requirements-completed: [INV-01, INV-02, INV-05, INV-06]

coverage:
  - id: D1
    description: "Authorized collection returns grouped OS rows with effective scope and per-source status."
    requirement: INV-01
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_os_collection_is_scoped_before_grouping"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_fixture_groups_native_and_arc_after_scope_filter"
        status: pass
    human_judgment: false
  - id: D2
    description: "Validated group detail returns exact Azure VM and Arc resource rows with evidence and environment."
    requirement: INV-02
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_detail_scope_isolation_and_unknown_review_state"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_detail_is_exact_resource_join_and_preserves_environment"
        status: pass
    human_judgment: false
  - id: D3
    description: "Software Inventory route renders real OS response data, source warnings, review-required state, and keyboard-reachable drill-down."
    requirement: INV-06
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: false
  - id: D4
    description: "Operator visually confirms the authenticated browser route and source/evidence presentation."
    requirement: INV-05
    verification: []
    human_judgment: true
    rationale: "A jsdom page test cannot establish real browser layout, focus behavior, or an Azure-backed authenticated walkthrough."

duration: 8min
completed: 2026-08-25
status: complete
---

# Phase 06 Plan 01: Scoped OS Inventory Tracer Summary

**Immutable-generation OS observations are normalized, scope-filtered, grouped across Azure VM and Arc sources, and rendered through an evidence-backed Software Inventory drill-down.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-25T15:16:04Z
- **Completed:** 2026-08-25T15:24:08Z
- **Tasks:** 2
- **Files modified:** 14

## Accomplishments

- Added frozen machine, group, evidence, and source-status contracts plus a read-only provider that resolves lifecycle state through `EOLCatalog`.
- Added `/api/v1/inventory/os` and validated `/api/v1/inventory/os/{group_key}` routes with effective ReadScope enforcement, deterministic ordering, pagination, evidence, generation metadata, and distinct partial/unavailable states.
- Added typed frontend API methods and a reachable `/software-inventory` OS tab with summary cards, source warnings, unknown-lifecycle review flags, loading/empty/error states, and machine drill-down.
- Added deterministic ARG-shaped fixture and backend/UI coverage for subscription isolation, duplicate host names, exact resource IDs, native/Arc labels, unknown versions, empty success, and provider failure.

## Task Commits

1. **Task 1: Trace one scoped OS group from an immutable fixture to the Software Inventory page** — `69d0167` (feat)
2. **Task 2: Expand the OS contract for source status and immutable-generation reads** — `6056a1e` (fix)

## Files Created/Modified

- `src/intelligence/inventory/models.py` — immutable normalized OS and source contracts.
- `src/intelligence/inventory/service.py` — scope-first grouping, detail lookup, lifecycle classification, and generation reads.
- `src/api/routers/inventory.py` — scoped collection/detail API endpoints.
- `src/api/app.py`, `src/api/dependencies.py`, `src/api/runtime.py` — API route and provider composition.
- `web/src/app/software-inventory/page.tsx` — OS Inventory tab and drill-down view.
- `web/src/lib/services.ts`, `web/src/lib/types.ts` — typed client contract.
- `tests/test_inventory_provider.py`, `tests/test_api_inventory_router.py`, `web/src/app/software-inventory/page.test.tsx`, `tests/fixtures/mock_inventory_arg.json` — fixture and contract tests.

## Decisions Made

- Implemented D-01, D-02, and D-09 exactly as specified in the phase context.
- Kept `inventory_provider` optional for readiness, but never synthesized an empty estate when no active generation exists.
- Recomputed source row counts after effective scope filtering so source metadata cannot disclose out-of-scope estate counts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Wiring] Added the inventory provider field to `ApiContext`.**
- **Found during:** Task 1
- **Issue:** The plan listed runtime and app wiring but omitted the dependency composition field required for injected test providers and non-runtime contexts.
- **Fix:** Added an optional `inventory_provider` callable to `ApiContext` while preserving all pre-existing user changes in that file.
- **Files modified:** `src/api/dependencies.py`
- **Verification:** Focused API tests and runtime fixture smoke test passed.
- **Committed in:** `69d0167`

**Total deviations:** 1 auto-fixed (Rule 2)
**Impact on plan:** Required for production/test dependency composition; no architectural change or scope expansion.

## Issues Encountered

- Existing unrelated working-tree edits touched the API runtime, app, and web contract files. They were preserved unstaged; only isolated inventory additions were included in the task commit.
- The focused backend run emitted the repository's existing Starlette/httpx deprecation warning; it did not affect test outcomes.

## Known Stubs

| File | Line | Stub | Reason |
|------|------|------|--------|
| `web/src/app/software-inventory/page.tsx` | 82-84 | Installed Software tab reports that ConfigurationData observations are coming in the next inventory slice. | Intentional tracer boundary; later Phase 6 plans implement installed software acquisition and grouping. |

The stub and the unrun manual browser walkthrough were appended to `.planning/WINDOWS.md` as open `stub` and `unrun-verify` entries.

## Verification

- `uv run pytest tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` — passed (9 tests).
- `cd web && npm run test -- src/app/software-inventory/page.test.tsx` — passed.
- `cd web && npx tsc --noEmit` — passed.
- Fixture-backed runtime provider smoke test — passed.

## User Setup Required

None - no external service configuration required for the fixture-backed tracer.

## Next Phase Readiness

- Ready for 06-02 to replace/extend the fixture path with native VM and Arc ARG acquisition while retaining `InventorySnapshot` and `InventoryService` contracts.
- The Installed Software tab remains intentionally open for later plans; the manual browser walkthrough remains an end-of-phase human check.

## Self-Check: PASSED

- Summary file exists on disk.
- Task commits `69d0167` and `6056a1e` exist in git history.
- No unresolved index entries were present.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-25*
