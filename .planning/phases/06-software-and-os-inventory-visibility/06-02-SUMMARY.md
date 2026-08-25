---
phase: 06-software-and-os-inventory-visibility
plan: 02
subsystem: inventory
tags: [python, pytest, azure-resource-graph, os-inventory, immutable-generations]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: scoped OS inventory contracts, API provider, and immutable-generation read path from 06-01
provides:
  - independent versioned native VM and Arc OS ARG query specifications
  - tag-derived environment and source-specific machine normalization
  - immutable-generation inventory observation and source-status publication
  - latest-state deduplication by source family and exact resource identity
affects: [06-03, 06-04, software-inventory, inventory]

# Actuals (#2632)
actuals:
  tokens: 7980
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - independent source-family QuerySpec entries with explicit query versions
    - environment resolution from case-insensitive approved tags only
    - source/resource-keyed latest-state selection before immutable publication
    - inventory observations and source status stored in the established generation

key-files:
  created: []
  modified:
    - src/hermes_arg_connector/queries.py
    - src/hermes_arg_connector/normalize.py
    - src/hermes_arg_connector/service.py
    - src/hermes_arg_connector/storage.py
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - tests/test_inventory_provider.py
    - tests/test_incremental_sync.py
    - tests/fixtures/mock_inventory_arg.json

key-decisions:
  - "Native VM image SKU and latest image version remain image metadata; installed OS version is Unknown unless an installed observation supplies it."
  - "Native VM and Arc queries remain independent so an Arc failure is degraded without erasing usable native rows."
  - "Environment uses case-insensitive resource tags in environment, env, environmentName precedence and otherwise persists Unknown."

patterns-established:
  - "QuerySpec.version is propagated into source evidence, observations, and source-status rows."
  - "Machine observations deduplicate case-insensitive exact resource identity within each source family using the newest observation timestamp."

requirements-completed: [INV-01, INV-02, INV-05]

coverage:
  - id: D1
    description: "Native VM and Arc OS observations are independently acquired, normalized, and published in one immutable generation."
    requirement: INV-01
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_native_and_arc_queries_are_versioned_and_independent"
        status: pass
      - kind: integration
        ref: "tests/test_incremental_sync.py::test_inventory_generation_publishes_successful_family_when_arc_fails"
        status: pass
    human_judgment: false
  - id: D2
    description: "Generated machine rows preserve exact identity, source evidence, tag-derived environment, and honest native version uncertainty."
    requirement: INV-02
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_generated_inventory_rows_preserve_source_identity_and_image_uncertainty"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_inventory_latest_state_deduplicates_by_exact_source_and_resource"
        status: pass
    human_judgment: false
  - id: D3
    description: "Operators can inspect family-specific source degradation while successful inventory remains available."
    requirement: INV-05
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_failed_inventory_family_remains_visible_without_erasing_other_family"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_inventory_provider.py tests/test_incremental_sync.py tests/test_azure_clients.py -q"
        status: pass
    human_judgment: true
    rationale: "The automated fixture path proves status and row semantics; an Azure-backed authenticated walkthrough is still required to validate tenant permissions and live source freshness."
---

# Phase 06 Plan 02: Native and Arc OS Inventory Acquisition Summary

**Independent Azure VM and Arc ARG OS acquisition now feeds tag-aware, deduplicated machine observations and family-specific status through the existing immutable generation.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-08-25T15:25:00Z
- **Completed:** 2026-08-25T15:33:50Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Added versioned, independently executable ARG QuerySpecs for native Azure VMs and Arc machines with deterministic `id` ordering.
- Preserved native `os_type` and image metadata separately while keeping installed release state explicitly `Unknown`; Arc OS name/version/SKU/status are normalized from Arc fields.
- Derived environment only from case-insensitive approved tags with fixed precedence and persisted `Unknown` when absent.
- Published inventory observations and per-family source status in the same immutable generation consumed by `InventoryService`.
- Added exact source/resource latest-state deduplication, fixture coverage, evidence/query-version propagation, and degraded-family regression coverage.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace one native VM ARG query through normalization and the existing generation** — `57a2bcc` (feat)
2. **Task 2: Add Arc acquisition, independent failures, and source-specific normalization** — `7b84e0c` (test)

## Files Created/Modified

- `src/hermes_arg_connector/queries.py` — versioned native VM and Arc ARG query specifications.
- `src/hermes_arg_connector/normalize.py` — source-specific machine normalization, environment, deduplication, and status projection.
- `src/hermes_arg_connector/service.py` — propagates each query specification's version.
- `src/hermes_arg_connector/storage.py` — publishes inventory datasets in the immutable generation.
- `src/intelligence/inventory/models.py` — environment, image metadata, source status, and evidence-bearing machine fields.
- `src/intelligence/inventory/service.py` — latest-state deduplication for provider reads.
- `tests/test_inventory_provider.py` — query, normalization, environment, deduplication, and failure tests.
- `tests/test_incremental_sync.py` — generation publication and family failure tests.
- `tests/fixtures/mock_inventory_arg.json` — native/Arc source rows with duplicate host names and image metadata.

## Decisions Made

- Followed D-02 by keeping native VM and Arc source identity distinct while grouping through the shared machine contract.
- Treat image SKU and `latest` image version as non-authoritative image evidence, never as an installed OS release.
- Kept provider failures as degraded family status and retained successful rows from the other family.
- Reused the existing lock, watermark, normalization, and immutable-generation boundary without changing Phase 1 state semantics.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Blocking lint issue] Used runtime-compatible timestamp parsing for latest-state selection.**

- **Found during:** Task 2 (Add Arc acquisition, independent failures, and source-specific normalization)
- **Issue:** Ruff rejected redundant UTC suffix replacement in the new timestamp helpers.
- **Fix:** Used `datetime.fromisoformat` directly, which supports the project's Python runtime timestamp format.
- **Files modified:** `src/hermes_arg_connector/normalize.py`, `src/intelligence/inventory/service.py`
- **Verification:** Focused tests and targeted Ruff check passed.
- **Committed in:** `7b84e0c`

---

**Total deviations:** 1 auto-fixed (Rule 1)
**Impact on plan:** Necessary lint correction only; no architecture or scope change.

## Issues Encountered

- The worktree contained extensive unrelated user edits, including changes in connector modules. Only task-owned index hunks were committed; unrelated edits remain in the working tree.
- The repository's pre-existing Ruff scan reports an unrelated blank line at EOF in `infra/terraform/variables.tf`; it was not modified.

## User Setup Required

None - no external service configuration required for fixture-backed verification.

## Next Phase Readiness

- The next plan can add Logs Query API ConfigurationData acquisition while reusing the normalized machine identity, environment fields, exact generation publication, and source-status conventions established here.
- Run the required authenticated Azure-backed walkthrough before release to validate live permissions, freshness, and family degradation behavior.

## Verification

- `uv run pytest tests/test_inventory_provider.py tests/test_incremental_sync.py -q` — passed (29 tests).
- `uv run pytest tests/test_inventory_provider.py tests/test_incremental_sync.py tests/test_azure_clients.py -q` — passed (40 tests).
- Targeted Ruff check for all plan-owned Python files — passed.

## Self-Check: PASSED

- Summary file exists on disk.
- Task commits `57a2bcc` and `7b84e0c` exist in git history.
- No task commit deleted tracked files.
- Unrelated user edits remain unstaged and preserved.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-25*
