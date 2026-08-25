---
phase: 06-software-and-os-inventory-visibility
plan: 09
subsystem: inventory
tags: [nextjs, react, typescript, csv, accessibility, authorization]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: scoped OS/software collections, exact group-detail APIs, lifecycle and mapping review, and risk narrative
provides:
  - discoverable two-tab Software Inventory dashboard
  - authorized OS and software machine drill-down with evidence and scope context
  - spreadsheet-safe CSV export for exact software/version detail rows
affects: [inventory, operations-ui, software-review, operator-workbench]

# Actuals (#2632)
actuals:
  tokens: 9829
  tasks: 2
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Keep subscription narrowing server-authoritative while presentation search, source, and lifecycle filters operate only on returned scoped groups."
    - "Export only the exact detail response held in page state; never export from a cache or caller-supplied machine list."
    - "Quote every CSV cell and prefix formula-leading string values before spreadsheet download."

key-files:
  created:
    - web/src/lib/csv.ts
    - web/src/lib/csv.test.ts
  modified:
    - web/src/app/software-inventory/page.tsx
    - web/src/app/software-inventory/page.test.tsx
    - web/src/lib/types.ts
    - web/src/components/AppShell.tsx
    - web/src/app/globals.css

key-decisions:
  - "Use semantic ARIA tabs and keep OS Inventory and Installed Software under one discoverable route and navigation entry."
  - "Narrow subscription selection through the existing authorized API scope, while keeping other page filters non-authoritative views over returned rows."
  - "Make CSV export a client-side serialization of the server-returned exact software/version detail envelope, with visible row count, scope, evidence, and source status."

patterns-established:
  - "Machine drill-down tables expose source type, environment, subscription, resource group, canonical/raw identity, resource ID, timestamps, and join/evidence state."
  - "Filtered summary cards and charts derive from the same scope-filtered groups rendered in their table."

requirements-completed: [INV-05, INV-06]

coverage:
  - id: D1
    description: "Discoverable Software Inventory route with exactly two accessible tabs, dashboard summaries/charts, filters, lifecycle badges, and source states."
    requirement: INV-05
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: true
    rationale: "Automated page coverage verifies the interaction contract; desktop and narrow-width visual hierarchy still needs operator review."
  - id: D2
    description: "OS and exact software/version drill-down tables show affected machines with authorized scope, source, environment, identity, resource, timestamp, and evidence context."
    requirement: INV-05
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_software_routes_return_canonical_exact_details_and_unlinked_status"
        status: pass
    human_judgment: false
  - id: D3
    description: "Software detail CSV export includes canonical/raw identity and environment/resource context and protects spreadsheet-sensitive values."
    requirement: INV-06
    verification:
      - kind: unit
        ref: "web/src/lib/csv.test.ts"
        status: pass
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: false
  - id: D4
    description: "Inventory UI remains responsive and production-buildable."
    verification:
      - kind: other
        ref: "cd web && npm run lint && npm run build"
        status: pass
    human_judgment: true
    rationale: "Build and lint validate implementation; visual behavior at desktop and narrow widths requires human judgment."

# Metrics
duration: 13min
completed: 2026-08-26
status: complete
---

# Phase 06 Plan 09: Software Inventory drill-down and export summary

**Software Inventory now provides a discoverable two-tab dashboard with scope-safe machine drill-down, evidence-aware exact lookup, responsive tables, and spreadsheet-safe CSV export.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-25T16:44:29Z
- **Completed:** 2026-08-25T16:57:00Z
- **Tasks:** 2
- **Files modified:** 7 plan-owned files, plus one deferred-items note

## Accomplishments

- Added a single Software Inventory navigation entry and semantic OS Inventory / Installed Software tab boundary.
- Completed affected-machine tables with source type, environment, subscription, resource group, canonical/raw identity, resource IDs, timestamps, join status, and evidence/scope context.
- Added subscription narrowing through the API scope, filter-consistent summary/chart counts, responsive presentation styles, and explicit loading, empty, unavailable, stale, and partial-source states.
- Added tested RFC-4180 CSV serialization with formula-leading value protection and an export action limited to the currently returned authorized exact software/version detail rows.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace both grouped views through typed API data and accessible page controls** - `b6e0a0c` (feat)
2. **Task 2: Add scoped CSV export, responsive polish, and phase-wide UI/API regression matrix** - `9a6bad4` (feat)
3. **Task 2 follow-up: Remove the inventory CSS compatibility warning** - `94f8646` (fix)

**Plan metadata:** pending final metadata commit.

## Files Created/Modified

- `web/src/app/software-inventory/page.tsx` - semantic tabs, scope-aware filters, dashboard views, machine detail tables, evidence context, and exact-detail export action.
- `web/src/app/software-inventory/page.test.tsx` - tab, filter, drill-down, review, mapping, narrative, source-state, and export-context behavior coverage.
- `web/src/lib/csv.ts` - RFC-4180 serializer, formula protection, and browser download helper.
- `web/src/lib/csv.test.ts` - delimiter, quote, newline, formula, numeric, and download coverage.
- `web/src/lib/types.ts` - software mapping metadata fields on detail rows.
- `web/src/components/AppShell.tsx` - one Software Inventory navigation entry.
- `web/src/app/globals.css` - responsive inventory tabs, cards, charts, filters, tables, and detail presentation.

## Decisions Made

- The page keeps exactly two semantic tabs and one top-level route; OS and software remain grouped views rather than separate navigation destinations.
- Subscription filtering narrows the existing API scope, so authorization remains server-owned and all displayed counts/charts use returned authorized groups.
- CSV serialization is deliberately small and dependency-free; all cells are quoted and string formula prefixes are neutralized.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test contract] Updated page tests for semantic tabs and detail table output**
- **Found during:** Task 1 verification
- **Issue:** Existing tracer assertions expected the tab controls to retain a button role and the previous list-based raw identity text.
- **Fix:** Updated assertions to target the accessible `tab` role and the new table cell content.
- **Files modified:** `web/src/app/software-inventory/page.test.tsx`
- **Verification:** Focused page suite passes.
- **Committed in:** `b6e0a0c`

**2. [Rule 1 - Build warning] Replaced an unsupported flex alignment value**
- **Found during:** Task 2 full verification
- **Issue:** The new inventory filter style used `align-items: end`, producing an Autoprefixer compatibility warning during production build.
- **Fix:** Changed the value to `flex-end`.
- **Files modified:** `web/src/app/globals.css`
- **Verification:** `npm run lint` and `npm run build` pass without the CSS warning.
- **Committed in:** `94f8646`

---

**Total deviations:** 2 auto-fixed (2 Rule 1)
**Impact on plan:** Fixes were limited to the touched inventory tests and new styles; no new retrieval, mutation, or authorization architecture was introduced.

## Issues Encountered

- The full frontend suite reports 131 passing tests and one unrelated existing failure in `src/app/compliance/page.test.tsx` because the current working-tree compliance page does not render its expected firewall-bypass Copilot link. This is recorded in `deferred-items.md`; the compliance page and test were not modified.
- Frontend tests emit existing React `act(...)` warnings while passing.
- The production build still logs existing MSAL `window is not defined` messages during static generation, but completes successfully.
- The working tree contained extensive unrelated tracked and untracked changes. Only plan-owned hunks were staged; unrelated shell and stylesheet edits remain preserved.

## User Setup Required

None - no external service configuration is required.

## Next Phase Readiness

- The authenticated `/software-inventory` route is ready for desktop and narrow-width operator review.
- API scope, exact group-key validation, lifecycle/mapping review, and source/evidence contracts remain server-authoritative.
- The unrelated compliance test failure should be addressed separately before treating the entire frontend suite as green.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-26*

## Self-Check: PASSED

- Summary and created CSV/page files exist.
- Task commits `b6e0a0c`, `9a6bad4`, and `94f8646` exist and include Copilot co-author trailers.
