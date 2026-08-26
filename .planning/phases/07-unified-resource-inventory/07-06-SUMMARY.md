---
phase: 07-unified-resource-inventory
plan: 06
subsystem: inventory
tags: [fabric, inventory, read-port, hermes, verification]
requires:
  - phase: 07-unified-resource-inventory
    provides: [07-05 PaaS inventory and per-family availability]
provides:
  - Scope-required internal inventory read port
  - Guard tests blocking direct inventory dataset reads outside inventory
  - Guard tests blocking Hermes inventory lifecycle ownership regression
  - Phase 7 exit evidence with unresolved human/live checks recorded
affects: [phase-7, phase-8, phase-9, inventory, hermes, api]
actuals:
  tokens: 2225
  tasks: 3
  commits: 2
tech-stack:
  added: []
  patterns:
    - Scope is mandatory for InventoryReadPort list and lookup methods
    - API cross-family inventory route shares the read-port query path
    - Source-tree guard tests enforce the inventory domain boundary
key-files:
  created:
    - src/intelligence/inventory/read_port.py
    - tests/test_inventory_read_port.py
  modified:
    - src/api/routers/inventory.py
    - src/hermes_arg_connector/cli.py
    - src/hermes_arg_connector/inventory_normalize.py
    - src/intelligence/inventory/__init__.py
    - .planning/WINDOWS.md
requirements-completed: [INV-07, INV-09, INV-10]
key-decisions:
  - "InventoryReadPort is the only intended cross-domain inventory access path and requires a caller-supplied effective scope on every public method."
  - "Out-of-scope single-resource lookup returns the same `None` result as absent resources to avoid enumeration."
patterns-established:
  - "Use InventoryReadPort.list_resources/get_resource for internal consumers instead of direct DatasetStore inventory reads."
  - "Guard tests scan source for direct inventory dataset reads and Hermes lifecycle ownership symbols."
duration: 8min
completed: 2026-08-26
status: complete
---

# Phase 7 Plan 06: Fabric-backed Inventory Read Port and Exit Evidence Summary

**A scope-required inventory read port now serves Fabric-backed cross-family inventory while guard tests keep consumers and Hermes out of inventory lifecycle ownership.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-26T07:10:00Z
- **Completed:** 2026-08-26T07:18:00Z
- **Tasks:** 3
- **Files modified:** 6 plus `.planning/WINDOWS.md`

## Accomplishments

- Added `InventoryReadPort` with mandatory effective scope for list and single-resource lookup.
- Routed `/api/v1/inventory/resources` through the read port so API behavior and internal consumers share the same cross-family query path.
- Added source guard tests preventing direct `inventory/*` dataset reads outside `src/intelligence/inventory/`.
- Added Hermes lifecycle guard tests and removed the legacy Hermes software normalizer module.
- Recorded Phase 7 exit evidence and re-recorded human/live or unrelated full-suite gaps in `.planning/WINDOWS.md`.

## Task Commits

1. **Task 1 RED: Inventory read port and guard tests** - `ca18d68` (test)
2. **Tasks 1-2 GREEN: Scoped read port and guard enforcement** - `aa7f1ab` (feat)

## Decisions Made

- Read port results expose only identity-plane projections and per-family availability; raw provider payload remains internal to inventory.
- `inventory-refresh` is retained as a CLI peer entry point, but wording avoids representing Hermes/Fabric command help as lifecycle ownership.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added source-tree guard enforcement**
- **Found during:** Task 2.
- **Issue:** Boundary requirements needed executable protection against future direct reads and Hermes lifecycle reintroduction.
- **Fix:** Added tests that scan source files and fail with offending files.
- **Files modified:** `tests/test_inventory_read_port.py`
- **Verification:** `uv run pytest tests/test_inventory_read_port.py tests/test_inventory_retention_characterization.py tests/test_service.py tests/test_incremental_sync.py -p no:cacheprovider`
- **Committed in:** `aa7f1ab`

## Issues Encountered

- Full suite completed with 1410 passing tests and 3 failures unrelated to this plan: `tests/test_onelake_fs.py::test_resolve_fs_selects_the_dfs_native_backend`, `tests/test_situations_ontology.py::test_situations_are_registered_as_ontology_entities_with_typed_links`, and `tests/test_storage.py::test_partial_publish_preserves_hash_baseline_for_next_full_publish`. These were recorded in `.planning/WINDOWS.md` as open deviations.
- Authenticated Azure/Fabric/browser Phase 7 exit walkthrough could not be performed in this non-interactive local execution and was recorded in `.planning/WINDOWS.md`.

## Verification

- `uv run pytest tests/test_inventory_read_port.py tests/test_inventory_paas.py tests/test_inventory_family_availability.py -p no:cacheprovider` — passed (12 tests).
- `uv run pytest tests/test_inventory_read_port.py tests/test_inventory_retention_characterization.py tests/test_service.py tests/test_incremental_sync.py -p no:cacheprovider` — passed (37 tests).
- Guard grep: `read_dataset('inventory/...')` outside `src/intelligence/inventory/` — no matches.
- Guard grep: Hermes inventory lifecycle ownership symbols — no matches.
- Full suite: `uv run pytest tests/ -p no:cacheprovider -o addopts=""` — 1410 passed, 3 failed; failures recorded above as unrelated/open.

## Phase 7 Success-Criteria Evidence

- Inventory refreshes and publishes without Hermes sync: 07-03 `InventoryPipeline` tests and 07-06 read-port tests.
- PaaS inventory grouped/drill-down with scope, evidence, freshness, and pagination: 07-05 PaaS tests.
- Per-family degraded/absent availability: 07-05 and 07-06 availability/read-port tests.
- Single scoped cross-family read path: `InventoryReadPort` tests and API route equality test.
- Existing OS/software behavior preserved: 07-01 characterization and retention tests passed unchanged.
- Direct reads removed outside inventory: 07-06 guard tests and grep evidence.

## Known Stubs

None.

## User Setup Required

Human/live verification remains required in a configured Azure/Fabric environment: run standalone inventory refresh, then verify OS/software pages, failed-refresh retention, unknown-OS lifecycle review, exact software/version search, EOL citation behavior, PaaS grouped/drill-down inventory, per-family degradation, and responsive/keyboard UX without recording sensitive tenant/resource identifiers.

## Next Phase Readiness

Phase 8 can consume `InventoryReadPort` and `ResourceObservation` to move Hermes resource-identity discovery to the unified Fabric-backed inventory plane.

## Self-Check: PASSED

- Summary file created at `.planning/phases/07-unified-resource-inventory/07-06-SUMMARY.md`.
- Task commits exist: `ca18d68`, `aa7f1ab`.

---
*Phase: 07-unified-resource-inventory*
*Completed: 2026-08-26*
