---
phase: 10-fabric-medallion-capability-expansion
plan: 13
subsystem: api
tags: [fabric, medallion, fastapi, rbac, lineage]
requires:
  - phase: 10-04
    provides: dataset-level medallion status contract
  - phase: 10-05
    provides: publication manifest lifecycle metadata
  - phase: 10-07
    provides: capacity, roles, maintenance, lineage helpers
  - phase: 10-10
    provides: semantic model deployment status vocabulary
  - phase: 10-12
    provides: gold grounding readiness signal
provides:
  - Scope-enforced `/api/v1/fabric-medallion/*` read API for layer health, dataset status, manifest, governance, ingestion history, and capabilities.
  - Read-only capability composition for capacity state, OneLake role summary, maintenance status, semantic readiness, Data Agent readiness, and lineage deep links.
affects: [10-14, fabric-medallion-tab, operators, data-agent-readiness]
actuals:
  tokens: 10312
  tasks: 3
  commits: 5
tech-stack:
  added: []
  patterns:
    - Reused `ReadScope` + `Context` dependency chain and `envelope(..., evidence, scope)` for all new routes.
    - Composed existing Fabric/ontology modules only; no new mutation surface.
key-files:
  created:
    - src/api/routers/fabric_medallion.py
  modified:
    - src/api/app.py
    - tests/test_api_http.py
key-decisions:
  - "Kept router strictly GET-only and summarized data-access roles read-only to satisfy MED-10 least-privilege constraints."
  - "Exposed lineage as both internal per-dataset summary (`entity_lineage_summary`) and native Fabric deep link (`native_lineage_url`)."
  - "Reported semantic readiness as `deployment-blocked` when no recorded deployment terminal state exists, rather than inferring success."
patterns-established:
  - "Dedicated medallion API routes follow existing auth/scope/evidence envelope conventions from `connections.py`."
  - "Capability routes degrade to explicit unknown/unavailable states instead of raising hard failures when optional inputs are missing."
requirements-completed: [MED-03, MED-09, MED-10]
coverage:
  - id: D1
    description: "Fabric medallion layer, dataset-detail, and manifest API routes are scope-enforced and envelope-shaped."
    requirement: MED-03
    verification:
      - kind: integration
        ref: "pytest tests/test_api_http.py -k fabric_medallion -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Governance, ingestion-history, and capabilities composition routes expose read-only health/readiness state including lineage deep links."
    requirement: MED-10
    verification:
      - kind: integration
        ref: "pytest tests/test_api_http.py -k fabric_medallion -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Application wiring registers the new medallion router in the FastAPI factory."
    requirement: MED-09
    verification:
      - kind: integration
        ref: "python3 -c \"from api.app import create_app; ...; '/api/v1/fabric-medallion/layers' in app.openapi()['paths']\""
        status: pass
    human_judgment: false
duration: 9min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 13: Fabric medallion API composition Summary

**Scope-enforced Fabric medallion APIs now expose dataset health, publication lifecycle, governance/ingestion risk, and read-only platform capabilities with lineage summaries and native Fabric lineage deep links.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-01T17:57:28Z
- **Completed:** 2026-09-01T18:06:28Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added new `src/api/routers/fabric_medallion.py` with GET-only routes: `/layers`, `/datasets/{table_name}`, `/manifest`, `/governance`, `/ingestion-history`, and `/capabilities`.
- Composed existing modules for capacity health, data-access roles, maintenance status, semantic readiness, Data Agent readiness, and lineage (`entity_lineage_summary` + `native_lineage_url`) without adding mutation endpoints.
- Registered the router in `create_app()` and expanded HTTP integration coverage for all medallion endpoints and read-only method guarantees.

## Task Commits

1. **Task 1 (RED):** `a42abd88` — failing coverage for layer/dataset/manifest routes
2. **Task 1 (GREEN):** `b82abf1a` — implemented scoped layer/dataset/manifest routes
3. **Task 2 (RED):** `bb1b84e8` — failing governance/ingestion/capabilities coverage
4. **Task 2 (GREEN):** `84ae9204` — implemented governance/ingestion/capabilities route composition
5. **Task 3:** `27528ea2` — registered router in app factory and aligned integration tests

## Files Created/Modified

- `src/api/routers/fabric_medallion.py` - New composed Fabric medallion API router.
- `src/api/app.py` - Router registration in FastAPI app factory.
- `tests/test_api_http.py` - End-to-end HTTP coverage for medallion routes and GET-only guarantees.

## Decisions Made

- Reused existing `connections.py` auth/scope/envelope patterns instead of introducing a new auth mechanism.
- Kept all medallion routes read-only (GET decorators only), including OneLake roles exposure as summaries.
- Surfaced semantic readiness conservatively as `deployment-blocked` when durable deployment state is not recorded.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Prevented stale test fixture timestamps from causing false `stale` dataset status**
- **Found during:** Task 1 GREEN verification
- **Issue:** Fixed literal timestamps in HTTP fixtures produced time-dependent stale results.
- **Fix:** Switched fixture timestamps to current UTC values at test runtime.
- **Files modified:** `tests/test_api_http.py`
- **Verification:** `pytest tests/test_api_http.py -k fabric_medallion -q`
- **Committed in:** `b82abf1a`

**2. [Rule 3 - Blocking] Corrected Task 3 verify command mismatch for app factory**
- **Found during:** Task 3 verification
- **Issue:** Plan verify command used `from api.app import app`, but `api.app` exposes `create_app()` factory and runtime auth env may be unset.
- **Fix:** Verified factory startup with explicit `ApiContext` injection and asserted route registration via generated OpenAPI paths.
- **Files modified:** none (verification command adaptation only)
- **Verification:** `python3 -c "from api.app import create_app; ...; '/api/v1/fabric-medallion/layers' in app.openapi()['paths']"`
- **Committed in:** `27528ea2`

---

**Total deviations:** 2 auto-fixed (1 Rule 1, 1 Rule 3)  
**Impact on plan:** No scope creep; both fixes were required for deterministic verification and successful task completion.

## Authentication Gates

None.

## Issues Encountered

- Task 3 plan verification command referenced a non-existent module-level `app`; verification was adapted to the app-factory pattern.

## User Setup Required

None - no external service configuration required for this plan’s API/test execution.

## Next Phase Readiness

- Plan 10-14 can consume `/api/v1/fabric-medallion/{layers,datasets,manifest,governance,ingestion-history,capabilities}` immediately.
- Route output now includes both internal lineage summaries and workspace-native Fabric lineage deep links required by the revised UI contract.

## Self-Check: PASSED

- Summary file exists on disk.
- All task commit hashes are present in git history.
