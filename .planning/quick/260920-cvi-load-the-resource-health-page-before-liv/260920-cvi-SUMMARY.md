---
phase: quick-260920-cvi
plan: "01"
subsystem: api-ui
tags: [resource-health, inventory, fastapi, react, abort-controller, concurrency]
requires: []
provides:
  - Scope-authorized per-resource health API backed by the inventory read port
  - Inventory-first resource cards with independent health states
  - Page-lifetime six-request scheduler with generation-safe cancellation
affects: [resource-health, inventory, azure-monitor]
actuals:
  tokens: 15138
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns:
    - Authorize inventory identity before cache or live-provider access
    - Keep aborted requests in the global concurrency count until settlement
key-files:
  created:
    - web/src/app/resource-health/page.test.tsx
  modified:
    - src/api/routers/resource_health.py
    - src/intelligence/health/service.py
    - tests/test_api_resource_health.py
    - tests/test_resource_health_service.py
    - web/src/app/resource-health/page.tsx
    - web/src/lib/services.ts
    - web/package.json
key-decisions:
  - "The single-resource service explicitly normalizes inventory snake_case fields and never invokes resource_lister."
  - "Per-resource cache keys combine normalized effective subscription scope with the case-insensitive canonical resource ID."
  - "One page-lifetime queue owns initial hydration, refresh, retries, scope changes, and unmount cancellation; aborted work releases capacity only when its promise settles."
patterns-established:
  - "Inventory-first rendering: stable resource identities render before independent live details."
  - "Generation-safe scheduling: stale completions are ignored even when a transport does not honor abort."
requirements-completed: [QUICK-260920-CVI]
coverage:
  - id: D1
    description: "One inventory-authorized resource can be hydrated without ARG identity discovery or cross-scope disclosure."
    requirement: QUICK-260920-CVI
    verification:
      - kind: integration
        ref: "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Inventory cards render immediately and hydrate independently under one global six-request scheduler."
    requirement: QUICK-260920-CVI
    verification:
      - kind: unit
        ref: "web/src/app/resource-health/page.test.tsx"
        status: pass
      - kind: integration
        ref: "cd web && npm test"
        status: pass
    human_judgment: false
duration: 7min
completed: 2026-09-20
status: complete
---

# Quick Task 260920-cvi: Inventory-First Resource Health Summary

**Scoped VM and Container App cards now render from inventory immediately, then hydrate through an authorization-first per-resource API under one abort-aware six-request scheduler.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-20T16:24:46Z
- **Completed:** 2026-09-20T16:31:47Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Added `GET /api/v1/resource-health/resource`, which resolves the requested identity through `InventoryReadPort.get_resource()` before cache or provider access and preserves the aggregate endpoint.
- Added `ResourceHealthService.snapshot_resource(...)` with explicit snake_case-to-internal normalization, canonical ID propagation, supported-type and subscription checks, matching active-connection selection, guest metric merging, and isolated metric errors.
- Reworked `/resource-health` to render supported inventory resources first and hydrate cards independently with local loading, error, and retry states.
- Enforced a single page-lifetime active-request count of six across initial load, refresh, retry, scope replacement, and unmount, with stale-generation completion guards.

## Task Commits

1. **Task 1 RED: Per-resource backend contracts** - `5460bcad`
2. **Task 1 GREEN: Scoped per-resource endpoint** - `3b84e98f`
3. **Task 2 RED: Inventory-first scheduler contracts** - `0a22dbd4`
4. **Task 2 GREEN: Inventory-first cards and bounded scheduler** - `01860673`

## Files Created/Modified

- `src/api/routers/resource_health.py` - Adds the authorization-first per-resource route and isolated TTL cache.
- `src/intelligence/health/service.py` - Adds documented single-resource snapshot hydration from a normalized inventory row.
- `tests/test_api_resource_health.py` - Covers endpoint authorization, normalization, cache isolation, and force refresh.
- `tests/test_resource_health_service.py` - Covers no-list single-resource behavior, validation, provider selection, and metric failure isolation.
- `web/src/app/resource-health/page.tsx` - Implements inventory-first rendering and the page-lifetime bounded scheduler.
- `web/src/app/resource-health/page.test.tsx` - Proves early cards, six-request ceiling, transition safety, local retry, and unmount cancellation.
- `web/src/lib/services.ts` - Adds the typed AbortSignal-aware per-resource API client.
- `web/package.json` - Adds the required `lint:fix` script.

## Decisions Made

- Reused `ResourceHealthSnapshot` for the one-resource response, avoiding a second detail contract.
- Preserved exact canonical inventory IDs in provider calls and responses while case-folding only comparisons, state keys, and cache identity.
- Kept inventory failures page-level and health failures card-local.

## Deviations from Plan

None - plan implementation followed the specified architecture and file scope.

## Issues Encountered

- The exact backend command `uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py` cannot collect tests because the environment auto-loads the installed `phoenix` pytest plugin, whose `mappingproxy` dataclass default is incompatible with the active Python 3.11 runtime. The same targeted suite passes 37/37 with third-party plugin auto-loading disabled.
- Repository-wide `git diff --check` reports pre-existing trailing blank lines in the user-owned dirty files `.github/copilot-instructions.md` and `AGENTS.md`. The scoped diff check for every quick-task file passes.
- The full frontend suite emits existing React `act(...)` and Keyborg cleanup diagnostics on unrelated tests, but all 60 files and 683 tests pass.

## Verification

- `uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py` — blocked during third-party Phoenix plugin import before collection.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py` — 37 passed.
- `cd web && npm test -- src/app/resource-health/page.test.tsx && npx tsc --noEmit` — 5 tests passed; type check passed.
- `cd web && npm run lint:fix && npm test` — no ESLint warnings/errors; 60 files and 683 tests passed.
- `git diff --check` — reports only the two pre-existing unrelated files noted above.
- Scoped `git diff --check -- <nine allowed plan paths>` — passed.

## Known Stubs

None.

## User Setup Required

None.

## Next Phase Readiness

- The resource-health page is ready for browser-level UAT against live inventory and Azure Monitor data.
- The unrelated Phoenix pytest plugin compatibility issue remains in the local test environment.

## Self-Check: PASSED

All eight implementation/test files, the required summary, and all four task
commits were verified on disk. No task file remains modified or staged.

---
*Quick task: 260920-cvi*
*Completed: 2026-09-20*
