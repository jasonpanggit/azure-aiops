---
quick_task: 260903-rkn
scope: Detailed progress reporting for Fabric table writes
status: complete
key_files:
  modified:
    - src/fabric/sync_service.py
    - src/onboarding/runtime.py
    - src/onboarding/sync.py
    - web/src/lib/types.ts
    - web/src/app/connections/page.tsx
  created:
    - tests/test_fabric_sync_service.py
  tests:
    - tests/test_subscription_onboarding.py
---

# Quick Task 260903-rkn Summary

Implemented end-to-end Fabric table-write progress reporting. Concurrent
publication now emits successful-write events, the onboarding coordinator maps
them to truthful active sync messages and percentages, and the connections UI
renders server-provided detail with legacy fallbacks.

## Changes

- Added typed `FabricTableWriteProgress` callbacks to Fabric sync.
- Forwarded callbacks through `_InventoryRefreshRunner` and the coordinator,
  preserving no-argument publisher compatibility and timeout behavior.
- Kept active progress below 100% until the existing terminal callback.
- Added backend coverage for callback ordering, totals, callback isolation, and
  coordinator rendering.
- Added nullable table-count fields and detailed active-progress rendering in
  the connections UI.

## Verification

- `uv run pytest -q tests/test_fabric_sync_service.py tests/test_subscription_onboarding.py tests/test_ontology_publish_durability.py tests/test_inventory_fabric_contract.py` — passed (65 tests).
- `cd web && npm test -- --run src/app/connections/page.test.tsx` — passed (9 tests).
- `cd web && npx tsc --noEmit` — passed.
- `uv run ruff check ...` — passed after formatting fixes.
- `git diff --check` — passed.

## Deviations from Plan

None. Existing uncommitted user changes, including the pre-existing
`src/onboarding/sync.py` timeout implementation, were preserved outside the
task commit.

## Commit

`321228ca` — `feat(260903-rkn): report detailed Fabric table sync progress`

## Self-Check: PASSED

- Summary file exists.
- Commit `321228ca` exists.
- Product/test commit contains only the planned task files.
- Unrelated working-tree modifications remain untouched.
