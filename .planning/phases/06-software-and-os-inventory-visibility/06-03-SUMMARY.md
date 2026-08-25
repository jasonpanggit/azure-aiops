---
phase: 06-software-and-os-inventory-visibility
plan: 03
subsystem: inventory
tags: [python, pytest, nextjs, vitest, azure-monitor-logs, configurationdata, software-inventory]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: scoped OS inventory contracts, exact machine identity, environment enrichment, and immutable-generation read conventions from 06-02
provides:
  - bounded Azure Monitor Logs Query API ConfigurationData client
  - canonical current-state installed-software normalization with exact machine joins
  - scoped software group/detail API routes and typed Installed Software tab
affects: [06-04, 06-05, 06-06, software-inventory, inventory]

# Actuals (#2632)
actuals:
  tokens: 17306
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fixed KQL is parsed through a strict tables/columns/rows boundary with response byte, row, and timeout limits
    - canonical software identity is selected by exact machine and canonical name, then guarded by exact machine and canonical identity
    - ConfigurationData rows inherit subscription, resource group, source type, and tag-derived environment only from an exact case-insensitive resource join

key-files:
  created:
    - src/hermes_arg_connector/logs.py
    - src/hermes_arg_connector/inventory_normalize.py
    - tests/fixtures/mock_configurationdata.json
    - tests/test_logs_client.py
  modified:
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - src/api/routers/inventory.py
    - web/src/app/software-inventory/page.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts
    - tests/test_inventory_provider.py
    - tests/test_api_inventory_router.py
    - web/src/app/software-inventory/page.test.tsx
    - src/intelligence/inventory/__init__.py

key-decisions:
  - "ConfigurationData is queried through Azure Monitor Logs Query API at api.loganalytics.azure.com, not Azure Resource Graph."
  - "Canonicalization precedes latest-state selection; a newer software version replaces an older one for the same exact machine and canonical name."
  - "Only case-insensitive exact _ResourceId joins inherit machine context; unmatched rows remain explicitly unlinked with Unknown environment and no inferred source type."
  - "Successful zero-row Logs results remain ready/empty, while malformed, bounded, HTTP-failed, and degraded results retain distinct source status."

patterns-established:
  - "SoftwareObservation preserves raw identity, canonical identity, observation timestamp, source join status, evidence, and machine context."
  - "InventoryService applies effective ReadScope before software counts, groups, details, source row counts, and evidence projection."

requirements-completed: [INV-01, INV-02, INV-05]

coverage:
  - id: D1
    description: "Bounded Logs Query API parsing accepts typed ConfigurationData tables and distinguishes valid empty data from malformed, failed, or oversized responses."
    requirement: INV-05
    verification:
      - kind: unit
        ref: "tests/test_logs_client.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Canonical installed-software observations deduplicate representation/version history and preserve exact linked or explicitly unlinked machine context."
    requirement: INV-01
    verification:
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_software_latest_guard_handles_duplicates_case_changes_and_hostname_collisions"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_provider.py::test_configuration_data_normalizes_and_exactly_joins_machine_context"
        status: pass
    human_judgment: false
  - id: D3
    description: "Authorized operators can view grouped canonical software/version rows and exact detail rows in the Installed Software tab with source and join warnings."
    requirement: INV-02
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_software_routes_return_canonical_exact_details_and_unlinked_status"
        status: pass
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: true
    rationale: "Automated API and jsdom tests cannot establish the authenticated browser walkthrough and visual inspection requested by the plan."

duration: 9min
completed: 2026-08-25
status: complete
---

# Phase 06 Plan 03: ConfigurationData Software Inventory Summary

**Azure Monitor Logs ConfigurationData now feeds canonical, scope-first installed-software groups and exact machine details with honest linked, unlinked, empty, and degraded source states.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-08-25T15:35:19Z
- **Completed:** 2026-08-25T15:42:46Z
- **Tasks:** 2
- **Files modified:** 14

## Accomplishments

- Added a fixed-query Azure Monitor Logs client for `ConfigurationData` using the documented Logs Query API endpoint, bearer token scope, strict typed table parsing, and bounded timeout/bytes/rows.
- Added deterministic software normalization that canonicalizes `7-Zip 19.00` and `7-Zip v19.00`, selects current state, retains raw identity, and performs only exact case-insensitive `_ResourceId` machine joins.
- Extended immutable inventory DTOs and `InventoryService` with scope-first software grouping and exact name/version detail lookup, including subscription, resource group, source type, environment, join status, evidence, and timestamps.
- Replaced the Installed Software placeholder with typed API-backed summary, grouped rows, source degradation/empty states, and linked/unlinked detail presentation.
- Added fixture-backed backend and frontend coverage for source limits, malformed schemas, empty success, representation/version changes, duplicate rows, resource-ID case changes, missing IDs, hostname collisions, scope isolation, and exact lookup.
- The source correction is explicit in the implementation: `ConfigurationData` is a Log Analytics table queried through Azure Monitor Logs, not ARG.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace one ConfigurationData row to an exact grouped software lookup and detail response** — `873bd9b` (feat)
2. **Task 2: Prove canonical latest-state and environment propagation edge cases** — `aaf5e45` (test)

**Plan metadata:** pending final metadata commit.

## Files Created/Modified

- `src/hermes_arg_connector/logs.py` — bounded Logs Query API client and strict parser.
- `src/hermes_arg_connector/inventory_normalize.py` — canonical software selection and exact machine joining.
- `src/intelligence/inventory/models.py` — software observations/groups and Logs source status contracts.
- `src/intelligence/inventory/service.py` — scope-first software collection and exact detail projection.
- `src/api/routers/inventory.py` — `/inventory/software` collection and exact software/version detail routes.
- `web/src/app/software-inventory/page.tsx` — Installed Software tab, summaries, source states, and details.
- `web/src/lib/services.ts`, `web/src/lib/types.ts` — typed client methods and DTOs.
- `tests/fixtures/mock_configurationdata.json`, `tests/test_logs_client.py` — Logs and ConfigurationData fixtures/tests.
- `tests/test_inventory_provider.py`, `tests/test_api_inventory_router.py`, `web/src/app/software-inventory/page.test.tsx` — normalization, scope, API, and UI regression coverage.

## Decisions Made

- Kept the Logs source separate from ARG, preserving the Microsoft-documented source-plane boundary for Change Tracking & Inventory.
- Used exact resource identity as the only authoritative machine join and retained unmatched observations rather than guessing from hostnames.
- Treats raw identity as evidence and canonical identity as the grouping/current-state key, allowing representation changes without losing source values.
- Kept source status independent from row presence so a ready empty result cannot hide a Logs failure or malformed response.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved `ConfigDataType` in the fixed Logs projection.**
- **Found during:** Task 2 (Prove canonical latest-state and environment propagation edge cases)
- **Issue:** The initial KQL filtered `ConfigDataType` but did not project it, so the normalizer could not enforce the source-type boundary on client-returned rows.
- **Fix:** Added `ConfigDataType` to the projected columns and retained strict filtering in normalization.
- **Files modified:** `src/hermes_arg_connector/logs.py`
- **Verification:** Focused Logs, provider, API, and UI tests passed.
- **Committed in:** `aaf5e45`

**2. [Rule 1 - Lint] Corrected runtime-compatible timestamp parsing and strict parser exception types.**
- **Found during:** Task 1 verification
- **Issue:** Ruff rejected redundant UTC suffix replacement and flagged invalid-payload errors as value errors rather than type errors.
- **Fix:** Used direct `datetime.fromisoformat` parsing and typed schema errors as `TypeError`.
- **Files modified:** `src/hermes_arg_connector/inventory_normalize.py`, `src/hermes_arg_connector/logs.py`, `tests/test_logs_client.py`
- **Verification:** Targeted Ruff and focused tests passed.
- **Committed in:** `873bd9b`

---

**Total deviations:** 2 auto-fixed (Rule 1)
**Impact on plan:** Both fixes were required for source correctness and repository lint compliance; no architectural scope was added.

## Issues Encountered

- The working tree contained extensive unrelated user edits, including large changes in `web/src/lib/services.ts` and `web/src/lib/types.ts`. Only the installed-software hunks were staged; all unrelated edits remain unstaged and preserved.
- Focused backend tests emit the repository's existing Starlette/httpx deprecation warning; it does not affect outcomes.

## Auth Gates

None.

## Known Stubs

None in files created or modified by this plan. The prior Installed Software placeholder was replaced by the ConfigurationData-backed path.

The required human browser walkthrough was not run in this non-interactive execution and was recorded as an open `unrun-verify` entry in `.planning/WINDOWS.md`.

## Verification

- `uv run pytest tests/test_logs_client.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` — passed (26 tests).
- `cd web && npm run test -- src/app/software-inventory/page.test.tsx` — passed (2 tests).
- Targeted Ruff check for all plan-owned Python files — passed.
- Tracer feedback gate rerun — backend and UI commands both passed.
- Human browser walkthrough — not run; tracked in `.planning/WINDOWS.md`.

## Next Phase Readiness

- Ready for 06-04 to add server-owned workspace configuration, Logs/ARG ingestion orchestration, and immutable-generation publication while preserving these software and exact-join contracts.
- The source boundary, canonicalization, scope enforcement, and degraded/empty semantics are now available for runtime integration.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-25*

## Self-Check: PASSED

- Summary and all created production/test files exist on disk.
- Task commits `873bd9b` and `aaf5e45` exist in git history.
- No task commit deleted tracked files.
- Unrelated user changes remain unstaged and preserved.
