---
phase: 07-unified-resource-inventory
plan: 01
subsystem: testing
tags: [inventory, characterization, dataset-store, hermes, pytest]

# Dependency graph
requires:
  - phase: 07-unified-resource-inventory
    provides: Phase 7 planning decisions and characterization requirements
provides:
  - Contract-level characterization suite for the current inventory publication/read/API envelope
  - Single inventory refresh harness seam for later ownership inversion
  - Golden inventory observation fixtures for machine and software rows
affects: [07-unified-resource-inventory, 08-resource-identity-plane, 09-consumer-pivot, hermes, inventory]

# Actuals (#2632)
actuals:
  tokens: 3342
  tasks: 3
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Single test seam isolates characterization assertions from the current Hermes-owned ingestion driver
    - Golden published dataset rows assert the external contract instead of implementation internals

key-files:
  created:
    - tests/inventory_harness.py
    - tests/test_inventory_characterization.py
    - tests/test_inventory_retention_characterization.py
    - tests/fixtures/inventory_golden/machine_web_01.json
    - tests/fixtures/inventory_golden/software_7zip.json
  modified:
    - .planning/STATE.md

key-decisions:
  - "Inventory characterization asserts only published inventory/* datasets, InventoryService.from_store(), and API evidence envelopes; it does not depend on NormalizedGraph or normalization module internals."
  - "The current inventory pipeline has no timestamp or source-watermark preservation behavior to carry forward; 07-03 task 2's preservation requirement is dropped unless new behavior is deliberately introduced."
  - "Native Azure VM image OS fields currently publish as Windows|Unknown for the web-01 fixture; that observable contract is pinned rather than corrected during characterization."

patterns-established:
  - "tests/inventory_harness.py owns the refresh driver; later plans may repoint its body without editing characterization assertions."
  - "Golden fixture rows under tests/fixtures/inventory_golden/ pin representative MachineObservation and SoftwareObservation payloads field-for-field."

requirements-completed: [INV-07]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "End-to-end inventory characterization covers fixture refresh, published inventory datasets, read model, and API evidence envelope."
    requirement: INV-07
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py tests/test_inventory_provider.py tests/test_inventory_mapping.py tests/test_inventory_eol.py tests/test_api_inventory_router.py tests/test_incremental_sync.py tests/test_service.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D2
    description: "Failed-refresh retention, successful empty refresh, no-snapshot-before-generation, and no inventory watermark preservation are pinned by two-run tests."
    requirement: INV-07
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_inventory_retention_characterization.py -p no:cacheprovider"
        status: pass
    human_judgment: false
  - id: D3
    description: "Characterization suite remains decoupled from relocating internals and reaches the current driver only through the harness seam."
    requirement: INV-07
    verification:
      - kind: other
        ref: "grep acceptance checks for NormalizedGraph, inventory_normalize, and IngestionService"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-08-26
status: complete
---

# Phase 7 Plan 01 Summary: Inventory Characterization

**Published inventory contract regression suite with a single refresh seam and golden dataset rows.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-08-26T05:27:00Z
- **Completed:** 2026-08-26T06:02:02Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added `tests/inventory_harness.py` as the single refresh seam all characterization tests use.
- Added end-to-end characterization for fixture refresh -> published `inventory/*` datasets -> `InventoryService.from_store()` -> API evidence envelope.
- Added golden row fixtures for one machine observation and one software observation.
- Pinned failed software refresh retention, successful empty refresh behavior, no active-generation snapshot behavior, pagination, group keys, source status vocabularies, and evidence fields.

## Task Commits

Each task is committed atomically in the plan completion commit:

1. **Task 1: End-to-end inventory contract characterization tracer** - included in this commit
2. **Task 2: Pin high-risk retention/timing behavior** - included in this commit
3. **Task 3: Pin group keys, source status, evidence, and pagination** - included in this commit

**Plan metadata:** `b82133e` (docs: final Phase 7 plans)

## Files Created/Modified

- `tests/inventory_harness.py` - Provides the single refresh driver seam for characterization tests.
- `tests/test_inventory_characterization.py` - Pins dataset names, row shapes, golden rows, read-model grouping, source status, evidence, and pagination.
- `tests/test_inventory_retention_characterization.py` - Pins failed-refresh retention, successful empty refresh, no pre-generation snapshot, and lack of inventory preservation behavior.
- `tests/fixtures/inventory_golden/machine_web_01.json` - Golden machine observation row.
- `tests/fixtures/inventory_golden/software_7zip.json` - Golden software observation row.
- `.planning/STATE.md` - Records plan completion and empirical preservation finding.

## Decisions Made

- Asserted current observable dataset contracts rather than correcting source semantics during characterization.
- Recorded that inventory timestamp/watermark preservation does not exist today; later inventory ownership inversion does not need to reproduce nonexistent preservation behavior.
- Kept `IngestionService` references out of characterization and retention tests so 07-03 can repoint only the harness.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- Initial expected source-status keys and grouping expectations were adjusted to match the actual published contract: OS source status includes `run_id`; software source status includes `workspace_count`; the scoped native VM source row count is one for `sub-a`; the web-01 native VM group key is currently `Windows|Unknown`.

## Verification

- `uv run pytest tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider` — 7 passed.
- `uv run pytest tests/test_incremental_sync.py tests/test_storage.py -p no:cacheprovider` — 26 passed.
- `uv run pytest tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py tests/test_inventory_provider.py tests/test_inventory_mapping.py tests/test_inventory_eol.py tests/test_api_inventory_router.py tests/test_incremental_sync.py tests/test_service.py -p no:cacheprovider` — 86 passed, 1 warning.
- Acceptance grep checks all returned 0 for forbidden dependencies: `NormalizedGraph`, `inventory_normalize`, and direct `IngestionService` usage in characterization tests.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

07-02 can begin. The regression suite now pins the observable inventory contract and must remain unchanged while storage extraction and ownership inversion proceed.

---
*Phase: 07-unified-resource-inventory*
*Completed: 2026-08-26*
