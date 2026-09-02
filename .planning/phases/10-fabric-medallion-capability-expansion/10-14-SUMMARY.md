---
phase: 10-fabric-medallion-capability-expansion
plan: 14
subsystem: web
tags: [fabric, medallion, frontend, connections]
requires:
  - phase: 10-13
    provides: scope-enforced Fabric medallion API routes
provides:
  - Operator-facing Fabric medallion tab on `/connections`.
  - Typed web contract and service client for `/api/v1/fabric-medallion/*`.
  - Status vocabulary coverage for dataset lifecycle and deployment states.
affects: [10-15, operators, fabric-medallion-tab]
actuals:
  tokens: 0
  tasks: 3
  commits: 5
tech-stack:
  added: []
  patterns:
    - Reused existing `useApi`, `MetricCard`, `StatusBadge`, `StatePanel`, `EvidenceBar`, table filters, and pagination primitives.
    - Added tabs to the existing `/connections` page instead of creating a new navigation surface.
key-files:
  created:
    - web/src/components/ui/StatusBadge.test.tsx
  modified:
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/components/ui/StatusBadge.tsx
    - web/src/app/connections/page.tsx
    - web/src/app/connections/page.test.tsx
key-decisions:
  - "Kept Fabric medallion visibility inside the existing Data & Integrations page to avoid a new navigation model."
  - "Each Fabric medallion section degrades independently so one failed layer does not blank the entire panel."
  - "Healthy-empty and unavailable zero-row states render distinct copy and tones."
patterns-established:
  - "API-backed tab panels can share the `/connections` page with existing subscription onboarding while preserving original subscription content."
requirements-completed: [MED-03, MED-09, MED-10]
coverage:
  - id: D1
    description: "Status vocabulary maps healthy-empty, unavailable, dormant, retired, and deployment-blocked without changing existing mappings."
    requirement: MED-03
    verification:
      - kind: unit
        ref: "cd web && npx vitest run src/components/ui/StatusBadge.test.tsx"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fabric medallion tab switching preserves the existing Subscriptions panel."
    requirement: MED-09
    verification:
      - kind: unit
        ref: "cd web && npx vitest run src/app/connections/page.test.tsx"
        status: pass
    human_judgment: false
  - id: D3
    description: "Layer degradation, healthy-empty vs unavailable copy, and retry-vs-no-retry ingestion states are covered by real page tests."
    requirement: MED-10
    verification:
      - kind: unit
        ref: "cd web && npx tsc --noEmit && npx vitest run src/app/connections/page.test.tsx"
        status: pass
    human_judgment: false
duration: 12min
completed: 2026-09-02
status: complete
---

# Phase 10 Plan 14: Fabric medallion web tab Summary

**The existing Data & Integrations page now exposes Fabric medallion health, lifecycle, governance, ingestion history, capacity, lineage, and readiness signals through a new `Subscriptions` / `Fabric medallion` tab pair.**

## Performance

- **Duration:** 12 min
- **Completed:** 2026-09-02
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added typed Fabric medallion web contracts and service methods for the API routes introduced in Plan 10-13.
- Extended `StatusBadge.statusTone()` for Phase 10 status vocabulary and added focused vitest coverage.
- Added the Fabric medallion tab to `/connections` using existing UI primitives only.
- Preserved the existing Subscriptions panel behind a tab without changing onboarding, editing, sync, or delete behavior.
- Added page tests for tab switching, per-section degradation isolation, healthy-empty vs unavailable copy, and retry-vs-no-retry ingestion states.

## Task Commits

1. **Task 1:** `432ea293` — Fabric medallion web API contract.
2. **Task 2 (RED):** `ced17abb` — status badge vocabulary coverage.
3. **Task 2 (GREEN):** `5572a301` — status badge vocabulary support.
4. **Task 3 (RED):** `ab3c7fa9` — Fabric medallion tab coverage.
5. **Task 3 (GREEN):** `98d73360` — Fabric medallion connections tab.

## Files Created/Modified

- `web/src/lib/types.ts` - Fabric medallion DTOs.
- `web/src/lib/services.ts` - `fabricMedallionApi`.
- `web/src/components/ui/StatusBadge.tsx` - status keyword mappings.
- `web/src/components/ui/StatusBadge.test.tsx` - focused status vocabulary tests.
- `web/src/app/connections/page.tsx` - tabbed Data & Integrations UI and Fabric medallion panel.
- `web/src/app/connections/page.test.tsx` - extended page behavior coverage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Narrow Promise.allSettled results before reading dataset envelopes**
- **Found during:** `cd web && npx tsc --noEmit`
- **Issue:** TypeScript could not prove every settled dataset result was fulfilled after a separate rejected-result check.
- **Fix:** Rewrote `loadLayerDatasets()` to iterate results, throw on rejected entries, and push fulfilled envelopes after control-flow narrowing.
- **Files modified:** `web/src/app/connections/page.tsx`
- **Verification:** `cd web && npx tsc --noEmit`
- **Committed in:** `98d73360`

**2. [Rule 1 - Test fixture] Default Fabric API mocks for legacy subscription tests**
- **Found during:** `cd web && npx vitest run src/app/connections/page.test.tsx`
- **Issue:** The new Fabric panel mounts even when hidden, so existing subscription tests needed default Fabric API mock responses.
- **Fix:** Added `mockFabricHealth()` defaults to the existing onboarding test setup and scoped new Fabric assertions to the Fabric panel.
- **Files modified:** `web/src/app/connections/page.test.tsx`
- **Verification:** `cd web && npx vitest run src/app/connections/page.test.tsx`
- **Committed in:** `98d73360`

---

**Total deviations:** 2 auto-fixed  
**Impact on plan:** No scope expansion; both fixes were required to make the planned implementation type-safe and its existing tests reliable.

## Verification

- `cd web && npx tsc --noEmit` — pass
- `cd web && npx vitest run src/components/ui/StatusBadge.test.tsx src/app/connections/page.test.tsx` — 16 passed

## Authentication Gates

None.

## Issues Encountered

- The first executor returned no final response after committing Tasks 1 and 2 and the RED test for Task 3; Task 3 was completed directly from the remaining working-tree diff.
- An unrelated modified `src/onboarding/defender_normalize.py` and untracked Fabric debug rollout artifacts were preserved and excluded from this plan's commits.

## User Setup Required

None.

## Next Phase Readiness

- Plan 10-15 can now validate the live rollout through both API and web surfaces.

## Self-Check: PASSED

- Summary file exists on disk.
- All task commit hashes are present in git history.
- Required web checks pass without fallback.
