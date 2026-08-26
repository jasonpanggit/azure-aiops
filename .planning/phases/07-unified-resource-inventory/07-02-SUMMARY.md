---
phase: 07-unified-resource-inventory
plan: 02
subsystem: storage
tags: [inventory, datasets, storage, onelake, hermes]

# Dependency graph
requires:
  - phase: 07-unified-resource-inventory
    provides: 07-01 characterization baseline
provides:
  - Neutral storage.datasets DatasetStore publication primitive
  - Hermes compatibility shim for graph-shaped DatasetStore.publish
  - Neutral storage.fs, storage.onelake_fs, and storage.locking helpers
affects: [07-unified-resource-inventory, hermes, inventory, situations, onboarding, fabric]

# Actuals (#2632)
actuals:
  tokens: 72349
  tasks: 2
  commits: 1

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Neutral storage modules own reusable filesystem, lock, and dataset generation machinery
    - Hermes-specific graph-to-dataset publication remains behind a compatibility shim

key-files:
  created:
    - src/storage/datasets.py
    - src/storage/fs.py
    - src/storage/onelake_fs.py
    - src/storage/locking.py
  modified:
    - src/hermes_arg_connector/storage.py
    - src/hermes_arg_connector/fs.py
    - src/hermes_arg_connector/locking.py
    - src/storage/__init__.py
    - src/intelligence/inventory/service.py
    - src/api/runtime.py
    - src/fabric/dataset_mapper.py
    - src/onboarding/activation.py
    - src/situations/store.py
    - tests/test_storage.py

key-decisions:
  - "Neutral DatasetStore.publish accepts explicit dataset mappings plus caller-supplied ontology metadata; it no longer imports NormalizedGraph or Hermes ontology generation."
  - "The old hermes_arg_connector.storage path remains as a compatibility shim for Hermes graph-shaped publish callers."
  - "Shared OneLake filesystem and run-lock helpers moved with DatasetStore so src/storage has zero hermes_arg_connector imports."

patterns-established:
  - "Domain-specific publishers assemble their dataset mapping before calling storage.datasets.DatasetStore."
  - "Legacy Hermes paths re-export neutral storage primitives only where compatibility is still required."

requirements-completed: [INV-07]

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "DatasetStore and generation/pointer/hash machinery live in neutral storage modules with no Hermes imports."
    requirement: INV-07
    verification:
      - kind: other
        ref: "grep -rn 'hermes_arg_connector' src/storage/ --include=*.py"
        status: pass
      - kind: other
        ref: "grep -v '^#' src/storage/datasets.py | grep -E 'NormalizedGraph|generate_ontology_metadata'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Existing Hermes graph-shaped publish behavior is preserved through a compatibility shim while neutral store reads the same generations."
    requirement: INV-07
    verification:
      - kind: unit
        ref: "tests/test_storage.py#test_generation_written_through_hermes_shim_reads_through_neutral_store"
        status: pass
    human_judgment: false
  - id: D3
    description: "Source dependents import DatasetStore and filesystem helpers from neutral storage where required; inventory no longer imports Hermes for publication."
    requirement: INV-07
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_storage.py tests/test_incremental_sync.py tests/test_agent_queries.py tests/test_api_runtime.py tests/test_onboarding_activation.py tests/test_inventory_provider.py tests/test_inventory_mapping.py tests/test_inventory_eol.py tests/test_api_inventory_router.py tests/test_service.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-08-26
status: complete
---

# Phase 7 Plan 02 Summary: Neutral Dataset Storage

**DatasetStore moved to neutral storage with Hermes graph publication preserved by a shim.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-26T06:02:02Z
- **Completed:** 2026-08-26T06:09:48Z
- **Tasks:** 2
- **Files modified:** 26

## Accomplishments

- Created `src/storage/datasets.py` as the neutral owner of immutable generation writes, current pointers, dataset hashes, retention, JSONL, and Parquet output.
- Replaced `hermes_arg_connector.storage.DatasetStore` with a compatibility subclass that assembles Hermes `NormalizedGraph` datasets and delegates to the neutral store.
- Moved shared OneLake filesystem and run-lock helpers into `src/storage` so the storage package has no Hermes imports.
- Repointed inventory, runtime, onboarding, Fabric, situation, and helper imports to neutral storage modules where applicable.

## Task Commits

Each task is committed atomically in the plan completion commit:

1. **Task 1: Move store into neutral storage package with graph coupling severed** - included in this commit
2. **Task 2: Repoint dependents at neutral module** - included in this commit

**Plan metadata:** `b82133e` (docs: final Phase 7 plans)

## Files Created/Modified

- `src/storage/datasets.py` - Neutral graph-agnostic dataset publication store.
- `src/storage/fs.py` - Neutral filesystem/root helpers for local and OneLake dataset roots.
- `src/storage/onelake_fs.py` - Neutral DFS-native OneLake filesystem adapter.
- `src/storage/locking.py` - Neutral run-lock helper.
- `src/hermes_arg_connector/storage.py` - Compatibility shim preserving Hermes graph-shaped `publish()`.
- `src/hermes_arg_connector/fs.py` and `src/hermes_arg_connector/locking.py` - Compatibility re-exports.
- `tests/test_storage.py` - Adds shim-write/neutral-read compatibility coverage.

## Decisions Made

- Kept the legacy Hermes import path available to avoid forcing test and CLI churn in this plan.
- Passed ontology metadata into the neutral store instead of letting storage import Hermes ontology logic.
- Added dataset-name containment validation to the mapping-based publish signature because callers can now provide dataset names directly.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- `src/storage/onelake_documents.py` and `src/storage/onelake_writer.py` already depended on Hermes filesystem/lock helpers, so 07-02 had to move those helpers into `src/storage` as well to satisfy the neutral-package grep gate.
- The explicit compatibility test initially asserted a stale fixture resource suffix and was corrected to the current normalized VM ID.

## Verification

- `uv run pytest tests/test_storage.py tests/test_incremental_sync.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider` — 33 passed.
- `uv run pytest tests/test_storage.py tests/test_incremental_sync.py tests/test_agent_queries.py tests/test_api_runtime.py tests/test_onboarding_activation.py tests/test_inventory_provider.py tests/test_inventory_mapping.py tests/test_inventory_eol.py tests/test_api_inventory_router.py tests/test_service.py tests/test_inventory_characterization.py tests/test_inventory_retention_characterization.py -p no:cacheprovider` — 116 passed, 3 warnings.
- `grep -rn 'hermes_arg_connector' src/storage/ --include=*.py` — no matches.
- `grep -v '^#' src/storage/datasets.py | grep -E 'NormalizedGraph|generate_ontology_metadata'` — no matches.
- `grep -rnE '^\s*(from|import)\s+hermes_arg_connector' src/intelligence/ --include=*.py | grep -v 'software_normalization.py'` — no matches.
- Dry import check for `hermes_arg_connector.cli`, `hermes_arg_connector.service`, `storage.datasets`, `api.runtime`, and `intelligence.inventory.service` — passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

07-03 can begin. Dataset publication is now available from a neutral module, but the publication safety/hash-state hazard still exists and must be addressed before inventory publishes independently.

---
*Phase: 07-unified-resource-inventory*
*Completed: 2026-08-26*
