---
phase: 06-software-and-os-inventory-visibility
plan: 08
subsystem: inventory
tags: [python, fastapi, nextjs, foundry, narrative, dashboard]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: scoped OS/software aggregates, lifecycle evidence, source status, and Software Inventory page
provides:
  - bounded deterministic inventory risk facts with optional Foundry narration
  - cited, confidence-qualified narrative route with fact-only fallback
  - dashboard charts, filters, source badges, and narrative rendering
affects: [inventory, software-review, operations-ui, foundry]

# Actuals (#2632)
actuals:
  tokens: 10715
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Narration receives only scope-filtered aggregate facts, never machine or installation rows."
    - "Deterministic fact summaries remain authoritative when optional Foundry narration is unavailable."
    - "Unsupported citations and malformed model responses are rejected without affecting inventory state."

key-files:
  created:
    - src/intelligence/inventory/narrative.py
  modified:
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - src/api/routers/inventory.py
    - tests/test_inventory_provider.py
    - tests/test_api_inventory_router.py
    - web/src/app/software-inventory/page.tsx
    - web/src/app/software-inventory/page.test.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts
    - src/intelligence/inventory/__init__.py

key-decisions:
  - "Build narration from server-owned, scope-filtered OS and approved software aggregates only."
  - "Keep fact summary, model narration, confidence, citations, source status, and warnings as separate response fields."
  - "Keep Foundry optional; timeout, malformed, ungrounded, or unavailable output degrades to fact-only inventory."

patterns-established:
  - "Inventory narrative route uses the existing Foundry retrieval/narration boundary and cannot mutate mappings, lifecycle catalog, or inventory."
  - "Dashboard filters are client-side views over the already-authorized collection and do not expand API scope."

requirements-completed: [INV-04, INV-05]

coverage:
  - id: D1
    description: "Scoped inventory endpoint returns deterministic facts with source status, evidence citations, confidence, and a visible Foundry-unavailable warning."
    requirement: INV-04
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_inventory_narrative_returns_fact_only_fallback_with_scoped_sources"
        status: pass
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_inventory_narrative_timeout_and_malformed_output_are_fact_only"
        status: pass
    human_judgment: false
  - id: D2
    description: "Only bounded scope-filtered aggregate facts are sent to Foundry, with unsupported citations excluded."
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_narrative_aggregate_limits_bound_group_payload"
        status: pass
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_inventory_narrative_sends_only_aggregates_and_preserves_facts"
        status: pass
    human_judgment: false
  - id: D3
    description: "Software Inventory renders fact-only narrative state, model/fact separation, source badges, dashboard views, filters, and drill-down controls."
    requirement: INV-05
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: true
    rationale: "jsdom verifies the rendering and interaction contract; an operator should still review the authenticated page layout and visual hierarchy."

duration: 7min
completed: 2026-08-26
status: complete
---

# Phase 06 Plan 08: Inventory risk narrative summary

**Software Inventory now presents scope-safe deterministic risk facts, optional cited Foundry narration, dashboard risk views, filters, source badges, and resilient fact-only fallback states.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-08-25T16:36:07Z
- **Completed:** 2026-08-25T16:42:58Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added an aggregate-only narrative context built after effective scope filtering, with capped OS/software groups, source status, evidence citations, confidence, and deterministic risk wording.
- Added `/api/v1/inventory/narrative`, preserving the existing read/retrieve then optional Foundry-narrate boundary; missing, timed-out, malformed, or ungrounded model output never removes inventory facts.
- Expanded the single Software Inventory page with a facts/model narrative panel, EOL and software concentration charts, search/source/lifecycle filters, source-state badges, and existing drill-down/review actions.
- Added backend and UI coverage for scope isolation, payload bounds, partial sources, empty scopes, timeout/malformed output, citation allowlisting, and fact-only rendering.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace scoped inventory aggregates through narrative and page fallback** - `3734b48` (feat)
2. **Task 2: Harden narrative grounding, bounds, and failure states** - `6ed7e44` (fix)

**Plan metadata:** pending final metadata commit.

## Files Created/Modified

- `src/intelligence/inventory/narrative.py` - bounded aggregate narrative builder, deterministic facts, citation filtering, and fallback.
- `src/intelligence/inventory/models.py` - safe narrative citation contract.
- `src/intelligence/inventory/service.py` - scope-first aggregate projection for narration.
- `src/api/routers/inventory.py` - scoped inventory narrative route.
- `tests/test_inventory_provider.py` - aggregate bounds and unsupported citation coverage.
- `tests/test_api_inventory_router.py` - fallback, source isolation, timeout, malformed output, and grounded narration coverage.
- `web/src/app/software-inventory/page.tsx` - narrative panel, charts, filters, badges, and existing inventory drill-down integration.
- `web/src/app/software-inventory/page.test.tsx` - narrative and filter rendering coverage.
- `web/src/lib/services.ts`, `web/src/lib/types.ts` - typed narrative client contract.
- `src/intelligence/inventory/__init__.py` - narrative citation export.

## Decisions Made

- Facts are assembled from InventoryService's existing effective-scope aggregates; the narrative layer has no independent retrieval or mutation path.
- Source degradation remains explicit in both source statuses and warnings, while successful empty scopes remain fact-only rather than being treated as provider failure.
- Foundry output is labeled as model narration and bounded/validated; deterministic facts and citations remain the authority.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Type/contract bug] Corrected the narrative panel state type**
- **Found during:** Task 1 verification
- **Issue:** The page passed an envelope state to a panel typed as the inner narrative payload.
- **Fix:** Typed the panel against `Envelope<InventoryNarrative>` so fact, warning, and citation fields are read from the correct response layer.
- **Files modified:** `web/src/app/software-inventory/page.tsx`
- **Verification:** `npx tsc --noEmit` and the focused Vitest suite pass.
- **Committed in:** `3734b48`

**2. [Rule 1 - Reliability bug] Preserved fact-only output for timeout and malformed narration**
- **Found during:** Task 2 hardening
- **Issue:** Timeout-style exceptions and unsupported evidence citations could otherwise escape the optional narration boundary.
- **Fix:** Catch bounded Foundry failure types and timeouts, reject unsupported citation tables, and retain deterministic facts with a warning.
- **Files modified:** `src/intelligence/inventory/narrative.py`
- **Verification:** Focused provider/API tests pass, including timeout, malformed output, and citation tests.
- **Committed in:** `6ed7e44`

**3. [Rule 3 - Blocking lint] Removed an unused touched-file import**
- **Found during:** Task 1 targeted Ruff verification
- **Issue:** The existing `annotate_mapping` import in the touched inventory service caused the required targeted Ruff command to fail.
- **Fix:** Removed the unused import and formatted the import block.
- **Files modified:** `src/intelligence/inventory/service.py`
- **Verification:** Targeted Ruff checks pass.
- **Committed in:** `3734b48`

**4. [Rule 2 - Missing critical presentation] Completed the requested inventory dashboard controls**
- **Found during:** Task 1 page implementation
- **Issue:** The existing page had summary cards and drill-down but no dashboard risk visualizations, collection search, or source filters.
- **Fix:** Added EOL/top-group bar visualizations, OS/software search and source/lifecycle filters, and explicit source-state badges while preserving the server-authorized data source.
- **Files modified:** `web/src/app/software-inventory/page.tsx`, `web/src/app/software-inventory/page.test.tsx`
- **Verification:** Focused UI tests and TypeScript compilation pass.
- **Committed in:** `3734b48`

---

**Total deviations:** 4 auto-fixed (2 Rule 1, 1 Rule 2, 1 Rule 3)
**Impact on plan:** All changes directly protect narrative correctness or complete the explicitly requested inventory page experience; no new retrieval, mutation, or infrastructure architecture was introduced.

## Issues Encountered

- Focused UI tests emit existing React `act(...)` warnings while passing; no tests were skipped.
- The working tree contained extensive unrelated tracked and untracked changes. Only the ten plan-owned files were staged in task commits; unrelated edits remain preserved.
- The repository's existing stylesheet has unrelated working-tree changes; no stylesheet changes were staged.

## User Setup Required

None - Foundry remains optional. Configure the existing `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_AGENT_NAME` contract to enable model narration; without them the page shows deterministic facts and warnings.

## Next Phase Readiness

- The narrative route and page are ready for authenticated UI review with Foundry disabled and enabled, including source warnings, citations, confidence, facts/model separation, filters, and drill-down.
- No inventory, mapping, or lifecycle mutation is reachable from the narrative path.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-26*

## Self-Check: PASSED

- Summary file exists.
- Created narrative implementation exists.
- Task commits `3734b48` and `6ed7e44` exist.
