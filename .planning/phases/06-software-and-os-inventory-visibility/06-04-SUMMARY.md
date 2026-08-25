---
phase: 06-software-and-os-inventory-visibility
plan: 04
subsystem: inventory
tags: [python, pytest, azure-monitor-logs, configurationdata, immutable-generation, runtime]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: exact OS/software normalization and scope-aware inventory provider
provides:
  - server-owned connection-to-Log-Analytics workspace configuration
  - ConfigurationData ingestion and immutable-generation publication
  - runtime loading with source-specific empty, degraded, partial, unavailable, and stale semantics
affects: [06-05, 06-06, software-inventory, inventory]

# Actuals (#2632)
actuals:
  tokens: 8044
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - validated server-owned workspace mappings are resolved by connection identity, never browser input
    - ARG and Logs software data share the complete immutable DatasetStore generation
    - failed Logs refreshes retain last-known software rows while preserving degraded source status

key-files:
  created: []
  modified:
    - src/hermes_arg_connector/config.py
    - src/hermes_arg_connector/logs.py
    - src/hermes_arg_connector/normalize.py
    - src/hermes_arg_connector/service.py
    - src/hermes_arg_connector/storage.py
    - src/intelligence/inventory/__init__.py
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - src/onboarding/runtime.py
    - tests/test_logs_client.py
    - tests/test_inventory_provider.py
    - tests/test_api_runtime.py

key-decisions:
  - "Only validated workspace IDs mapped to the active server connection are queried; missing mappings are unavailable and never accept arbitrary workspace input."
  - "A successful zero-row Logs response is ready/empty; all-workspace failures are degraded, mixed results are partial, and prior rows are retained for failed refreshes."
  - "Inventory provider freshness comes from the active generation manifest so ProviderRuntime can mark old data stale without discarding rows."

patterns-established:
  - "ConfigurationData software observations are normalized after ARG machine observations and published as inventory/software_observations in the same generation."
  - "Source status carries workspace count, requested subscription scope, query version, timestamps, and bounded errors."

requirements-completed: [INV-01, INV-02, INV-05]

coverage:
  - id: D1
    description: "Configured Log Analytics workspaces feed canonical, exact-joined software observations through immutable publication."
    requirement: INV-01
    verification:
      - kind: integration
        ref: "tests/test_inventory_provider.py::test_configured_workspace_publishes_software_in_the_active_generation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Workspace omission, successful empty results, partial access, degraded failure, and last-known-row retention remain distinct."
    requirement: INV-05
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_workspace_failures_retain_last_known_rows_and_mark_degraded"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_successful_empty_workspace_replaces_previous_rows_as_ready_empty"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_missing_workspace_mapping_is_unavailable_and_never_queries_arbitrary_id"
        status: pass
    human_judgment: false
  - id: D3
    description: "Runtime reads generation metadata and marks an old inventory generation stale without erasing its observations."
    requirement: INV-02
    verification:
      - kind: integration
        ref: "tests/test_api_runtime.py::test_inventory_runtime_marks_old_generation_stale_without_erasing_rows"
        status: pass
    human_judgment: false
  - id: D4
    description: "Authenticated UI/API walkthrough of healthy and failed workspace refresh states."
    verification: []
    human_judgment: true
    rationale: "This non-interactive executor cannot perform the requested browser walkthrough."

duration: 18min
completed: 2026-08-26
status: complete
---

# Phase 06 Plan 04: Workspace-backed software inventory summary

**Server-owned Log Analytics workspace mappings now feed ConfigurationData software through the ARG inventory lifecycle, with atomic generation publication and honest refresh health.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-08-25T23:44:18+08:00
- **Completed:** 2026-08-26T00:02:00+08:00
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments

- Added frozen connector configuration for one or more validated Log Analytics workspaces per connection, with case-insensitive connection lookup and no browser-controlled workspace selection.
- Added independent Logs ingestion to `IngestionService`, exact machine joining, software normalization, and publication of software observations/status alongside ARG data in the existing complete immutable generation.
- Preserved last-known software rows on failed refreshes, while distinguishing unavailable configuration, degraded failures, partial multi-workspace results, successful empty results, and stale generation health.
- Added manifest-backed runtime provider freshness and regression coverage for workspace access, timeout/malformed failures, environment propagation, exact joins, generation publication, and stale retention.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace one configured workspace through ingestion, generation, and the software provider** — `9c351d1` (feat)
2. **Task 2: Complete workspace omission, refresh, and source degradation semantics** — `b93bc40` (test)

**Plan metadata:** pending final metadata commit.

## Files Created/Modified

- `src/hermes_arg_connector/config.py` — validated server-owned workspace mapping.
- `src/hermes_arg_connector/service.py` — Logs fetch, normalization, status, and last-known retention.
- `src/hermes_arg_connector/storage.py` — software datasets in immutable generations.
- `src/intelligence/inventory/service.py` — active manifest metadata and workspace status projection.
- `src/onboarding/runtime.py` — connection credential wiring for the Logs client.
- `tests/test_inventory_provider.py`, `tests/test_logs_client.py`, `tests/test_api_runtime.py` — lifecycle, failure, and stale-runtime coverage.

## Decisions Made

- Kept Logs and ARG as independent source families while publishing both through the established `DatasetStore` generation boundary.
- Treated successful empty data as a valid ready state, but never represented a failed refresh as an unqualified empty inventory.
- Retained normalized exact-join context, including environment and source type, in the persisted software observation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved environment when rehydrating normalized machine rows**
- **Found during:** Task 1 verification
- **Issue:** The graph stores machine observations as mappings; rehydrating those mappings recomputed environment only from absent tags and lost the exact joined environment.
- **Fix:** `MachineObservation.from_mapping` now honors an already normalized environment before tag fallback.
- **Files modified:** `src/intelligence/inventory/models.py`
- **Verification:** Exact workspace publication and provider tests pass.
- **Committed in:** `9c351d1`

**2. [Rule 1 - Bug] Prevented refresh timestamps from falsely changing semantic dataset hashes**
- **Found during:** Task 2 regression verification
- **Issue:** Repeated no-Logs-config refreshes changed `inventory/source_status` only because the attempt timestamp changed, breaking the existing unchanged-generation contract.
- **Fix:** Treat normalized `observed_at` timestamps as volatile for semantic hashing while retaining them in stored rows.
- **Files modified:** `src/hermes_arg_connector/storage.py`
- **Verification:** Existing incremental sync tests and full backend suite pass.
- **Committed in:** `9c351d1`

**3. [Rule 3 - Blocking] Avoided inventory model/service import recursion**
- **Found during:** Task 1 integration verification
- **Issue:** Direct source-normalizer imports could recursively load the inventory package service before its definitions were complete.
- **Fix:** Lazily expose service exports from the inventory package and keep the normalizer import at the ingestion boundary.
- **Files modified:** `src/intelligence/inventory/__init__.py`, `src/hermes_arg_connector/service.py`
- **Verification:** Focused tests and direct normalization import pass.
- **Committed in:** `9c351d1`

**4. [Rule 2 - Missing Critical] Wired connection credentials to the server-owned Logs adapter**
- **Found during:** Task 1 runtime integration
- **Issue:** Configuration alone could not query a workspace unless connection-scoped credential construction passed the existing connection identity to the Logs client.
- **Fix:** Connection ingestion now constructs the bounded Logs client only when that connection has configured workspaces, using the existing credential resolver.
- **Files modified:** `src/onboarding/runtime.py`
- **Verification:** Onboarding regressions and focused inventory tests pass.
- **Committed in:** `9c351d1`

---

**Total deviations:** 4 auto-fixed (2 Rule 1, 1 Rule 2, 1 Rule 3)
**Impact on plan:** All fixes were directly required for exact context, lifecycle correctness, safe runtime wiring, or importability; no parallel store or architectural scope was added.

## Issues Encountered

- The working tree contained extensive unrelated user edits. Only task-owned hunks were staged; those edits remain in the working tree.
- The repository's existing Starlette/httpx and FastAPI lifecycle deprecation warnings remain; they do not affect test outcomes.

## Auth Gates

None.

## Known Stubs

None in files created or modified by this plan.

The requested human browser walkthrough was not run and is recorded in `.planning/WINDOWS.md` as an open `unrun-verify` entry.

## Verification

- `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_runtime.py -q` — passed.
- `uv run pytest tests/test_subscription_onboarding.py tests/test_service.py -q` — passed.
- `uv run pytest -q` — passed.
- Targeted Ruff checks for all plan-owned Python files — passed.
- Tracer feedback gate rerun after Task 1 — passed.
- Human browser walkthrough — not run; tracked in `.planning/WINDOWS.md`.

## Next Phase Readiness

- 06-05 can build its server-owned EOL repository and request-time review workflow on the now durable, manifest-backed inventory provider.
- 06-06 can add candidate adapters without changing the ARG/Logs ingestion boundary or browser trust model.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-26*

## Self-Check: PASSED

- Summary exists and both task commits are present in git history.
- Task-owned tests and targeted lint checks passed.
- The only `git diff --check` warning is a pre-existing unrelated blank line in `infra/terraform/variables.tf`.
