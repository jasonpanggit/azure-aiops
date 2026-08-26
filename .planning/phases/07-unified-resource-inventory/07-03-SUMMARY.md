---
phase: 07-unified-resource-inventory
plan: 03
subsystem: inventory
tags: [fabric, onelake, inventory, datasetstore, hermes]
requires:
  - phase: 07-unified-resource-inventory
    provides: [07-01 characterization baseline, 07-02 neutral DatasetStore]
provides:
  - Fabric-native inventory table contract aliases for current OS/software datasets
  - Standalone inventory-owned refresh pipeline for OS and software inventory
  - Hermes lifecycle removal for inventory query, normalization, retention, and publication ownership
affects: [phase-7, phase-8, phase-9, inventory, hermes, fabric]
actuals:
  tokens: 8645
  tasks: 5
  commits: 5
tech-stack:
  added: []
  patterns:
    - Inventory-owned Fabric contract module with compatibility logical dataset aliases
    - Inventory pipeline publishes current read-shape datasets through Fabric-backed publication adapter
key-files:
  created:
    - src/intelligence/inventory/fabric_contracts.py
    - src/intelligence/inventory/fabric_publication.py
    - src/intelligence/inventory/normalization.py
    - src/intelligence/inventory/pipeline.py
    - src/intelligence/inventory/sources/arg.py
    - src/intelligence/inventory/sources/logs.py
    - tests/test_inventory_fabric_contract.py
  modified:
    - src/fabric/schema_registry.py
    - src/hermes_arg_connector/cli.py
    - src/hermes_arg_connector/normalize.py
    - src/hermes_arg_connector/queries.py
    - src/hermes_arg_connector/service.py
    - src/hermes_arg_connector/storage.py
    - src/intelligence/inventory/service.py
    - src/intelligence/inventory/software_normalization.py
    - tests/inventory_harness.py
    - tests/test_api_inventory_router.py
    - tests/test_api_runtime.py
    - tests/test_incremental_sync.py
    - tests/test_inventory_provider.py
key-decisions:
  - "Selected new-fabric-names-with-adapter: Fabric tables use inventory_os_observations, inventory_source_status, inventory_software_observations, and inventory_software_source_status while logical inventory/* dataset names remain the compatibility/read boundary."
  - "DatasetStore remains the compatibility/local-staging writer; inventory-owned Fabric contracts are the publication authority for the current inventory pipeline."
patterns-established:
  - "Fabric schemas for inventory are registered through inventory.fabric_contracts and discovered by fabric.schema_registry without embedding inventory knowledge in generic Fabric code."
  - "Hermes sync no longer emits inventory datasets; standalone inventory-refresh invokes intelligence.inventory.pipeline.InventoryPipeline as a peer lifecycle."
requirements-completed: [INV-07]
coverage:
  - id: D1
    description: "Fabric-backed OS/software inventory contract aliases and quality gates"
    requirement: INV-07
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_inventory_fabric_contract.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D2
    description: "Standalone inventory refresh publishes OS/software compatibility datasets without Hermes sync"
    requirement: INV-07
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D3
    description: "Hermes no longer owns inventory lifecycle publication"
    requirement: INV-07
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_incremental_sync.py tests/test_service.py tests/test_api_runtime.py -p no:cacheprovider"
        status: pass
      - kind: other
        ref: "grep acceptance checks for Hermes inventory symbols and intelligence->Hermes imports"
        status: pass
    human_judgment: false
duration: 11min
completed: 2026-08-26
status: complete
---

# Phase 7 Plan 03: Fabric-backed Ownership Inversion and Inventory Publication Contracts Summary

**Inventory now owns OS/software acquisition, normalization, retention, and Fabric-backed publication while Hermes remains only a consumer.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-08-26T06:44:13Z
- **Completed:** 2026-08-26T06:55:00Z
- **Tasks:** 5
- **Files modified:** 21

## Accomplishments

- Defined Fabric-native inventory table mappings with compatibility aliases for all four current `inventory/*` logical datasets.
- Added inventory-owned quality validation for required fields, duplicate identity keys, invalid source states, and assessment-domain field leakage.
- Added a standalone `InventoryPipeline` and `InventoryFabricPublisher` so OS/software inventory refreshes without a Hermes graph sync.
- Moved OS query definitions and ConfigurationData normalization into `src/intelligence/inventory/`.
- Removed Hermes publication of inventory logical datasets and added a peer `inventory-refresh` CLI entry point.

## Task Commits

1. **Task 2 RED: Fabric contract tests** - `99821a4` (test)
2. **Task 2 GREEN: Fabric inventory contracts** - `a9adbf7` (feat)
3. **Task 3: Standalone Fabric-backed inventory pipeline** - `3ab6e38` (feat)
4. **Task 4: Software normalization ownership move** - `6b9b1e7` (feat)
5. **Task 5: Hermes lifecycle removal** - `d27ffe1` (feat)

## Files Created/Modified

- `src/intelligence/inventory/fabric_contracts.py` - Inventory logical-to-Fabric table mappings, schemas, and quality gates.
- `src/intelligence/inventory/fabric_publication.py` - Fabric-backed publication adapter over the compatibility DatasetStore.
- `src/intelligence/inventory/pipeline.py` - Standalone inventory refresh orchestration.
- `src/intelligence/inventory/sources/arg.py` - Inventory-owned OS ARG query specs moved from Hermes.
- `src/intelligence/inventory/sources/logs.py` - Inventory-owned ConfigurationData source status/acquisition helper.
- `src/intelligence/inventory/normalization.py` - Inventory-owned OS normalization.
- `src/intelligence/inventory/software_normalization.py` - Inventory-owned software normalization and canonical identity.
- `src/hermes_arg_connector/*` - Removed inventory lifecycle publication/query ownership and added `inventory-refresh` command.
- `tests/*inventory*`, `tests/test_api_runtime.py`, `tests/test_incremental_sync.py` - Updated tests to exercise inventory-owned seams.

## Decisions Made

- Used `new-fabric-names-with-adapter`: `inventory/os_observations -> inventory_os_observations`, `inventory/source_status -> inventory_source_status`, `inventory/software_observations -> inventory_software_observations`, `inventory/software_source_status -> inventory_software_source_status`.
- Kept DatasetStore as compatibility/local staging and publication plumbing while making inventory contracts authoritative.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Broke API circular import after removing Hermes dependency**
- **Found during:** Task 4 verification.
- **Issue:** Moving software normalization into inventory exposed `api.scope` import cycles through `api.__init__`.
- **Fix:** Made inventory service/API helper imports lazy and removed the top-level `api.scope` import from software normalization.
- **Files modified:** `src/intelligence/inventory/service.py`, `src/intelligence/inventory/software_normalization.py`
- **Verification:** Task 4 and Task 5 pytest suites passed.
- **Committed in:** `6b9b1e7`

---

**Total deviations:** 1 auto-fixed (Rule 3)
**Impact on plan:** Required for correctness after ownership inversion; no added product scope.

## Issues Encountered

- Existing worktree had many unrelated dirty files. All task commits used path-limited and index-only staging to avoid reverting or committing unrelated work.
- Some unrelated pre-existing changes remain dirty in plan-touched files after index-only commits; they were intentionally left uncommitted.

## Verification

- `uv run pytest tests/test_inventory_fabric_contract.py -p no:cacheprovider` — passed (7 tests).
- `uv run pytest tests/test_inventory_fabric_contract.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider` — passed (15 tests).
- `uv run pytest tests/test_inventory_retention_characterization.py tests/test_inventory_characterization.py tests/test_inventory_provider.py tests/test_inventory_mapping.py tests/test_inventory_eol.py tests/test_api_inventory_router.py -p no:cacheprovider` — passed (58 tests).
- `uv run pytest tests/test_inventory_fabric_contract.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py tests/test_incremental_sync.py tests/test_service.py tests/test_api_runtime.py -p no:cacheprovider` — passed (58 tests).
- Grep checks confirmed no `NormalizedGraph` usage in `src/intelligence/inventory/pipeline.py`, no `src/intelligence` imports from `hermes_arg_connector`, no `inventory_normalize` references in `src`, and no Hermes inventory lifecycle/dataset symbols in `service.py`, `normalize.py`, or `storage.py`.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

07-04 can build `ResourceObservation` and family registry on the inventory-owned Fabric contract and standalone pipeline introduced here.

## Self-Check: PASSED

- Summary file created at `.planning/phases/07-unified-resource-inventory/07-03-SUMMARY.md`.
- Task commits exist: `99821a4`, `a9adbf7`, `3ab6e38`, `6b9b1e7`, `d27ffe1`.

---
*Phase: 07-unified-resource-inventory*
*Completed: 2026-08-26*
