---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 02
subsystem: orchestration
tags: [durable-coordinator, cas, leases, retries, manual-sync, async-cli]

requires:
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 01
    provides: fail-closed dependency preflight and non-authoritative ontology contract tracer
provides:
  - deterministic durable ontology run identities shared by scheduled and manual triggers
  - status-and-revision CAS claims with renewable leases and monotonic fencing tokens
  - bounded retry, deadline, cancellation, restart recovery, and immutable lifecycle events
  - enqueue-only Manual Sync compatibility and a finite asynchronous run-once CLI
affects: [13-03, 13-06, 13-09, 13-10, 13-12, 13-15]

actuals:
  tokens: 16846
  tasks: 2
  commits: 5

tech-stack:
  added: []
  patterns:
    - deterministic connection-and-source-generation run identity
    - file-locked atomic JSON ledger with record and document revisions
    - monotonic fencing token on every claim and cancellation invalidation
    - transport-independent bounded async run-once coordinator

key-files:
  created:
    - src/ontology_discovery/__init__.py
    - src/ontology_discovery/contracts.py
    - src/ontology_discovery/store.py
    - src/ontology_discovery/coordinator.py
    - src/ontology_discovery/cli.py
    - tests/test_ontology_discovery_store.py
    - tests/test_ontology_discovery_coordinator.py
  modified:
    - src/onboarding/service.py
    - src/api/routers/connections.py
    - pyproject.toml

key-decisions:
  - "Derive run identity only from canonical connection ID and source generation, so trigger type and caller cannot create duplicate logical work."
  - "Keep the coordinator dependent on a proposal-only RunProcessor; publisher access is status-only and no stage, pointer, Fabric, or OneLake mutation primitive is available."
  - "Preserve the legacy Sync response status and sync_state shape while adding durable_run details and leaving non-API ingestion sync methods unchanged."
  - "Preserve root STATE.md ownership for active Phase 03.1; record this concurrent Phase 13 plan only in its summary and commits."

patterns-established:
  - "Durable claim: status plus revision CAS acquires a finite lease and a strictly increasing fence."
  - "Stale worker safety: a rejected consequential transition appends a non-consequential lease_lost audit event without changing the winning checkpoint."
  - "Compatibility intake: API run-now and scheduled callers use one get-or-create path, while unrelated ingestion retains its existing synchronous/background methods."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-06]

coverage:
  - id: D1
    description: "Independent stores converge duplicate triggers and allow exactly one fenced CAS claim."
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_store.py#test_independent_stores_converge_duplicate_triggers_and_cas_claim_once"
        status: pass
    human_judgment: false
  - id: D2
    description: "Restart, retry, deadline, cancellation, renewal, and lost-lease outcomes are durable and bounded."
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: "uv run pytest -q tests/test_ontology_discovery_store.py tests/test_ontology_discovery_coordinator.py -x"
        status: pass
    human_judgment: false
  - id: D3
    description: "Manual Sync is an authorized enqueue-only compatibility path sharing scheduled run identity and exposing no publication primitive."
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_coordinator.py#test_manual_and_scheduled_sync_intake_share_one_durable_run_without_executor"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_discovery_coordinator.py#test_manual_sync_route_preserves_authorization_and_uses_durable_intake"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 02: Durable Coordinator and Manual Sync Intake Summary

**A fenced, restart-safe ontology run ledger now unifies scheduled and manual triggers behind bounded async coordination without granting any authoritative publication capability.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-06T10:46:04Z
- **Completed:** 2026-09-06T10:55:00Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added deterministic get-or-create runs, deep-copy reads, safe legacy defaults, immutable events, atomic local replacement, and status-plus-revision CAS.
- Added finite claims with renewable leases, monotonic fencing, restart recovery, bounded exponential retry, durable deadlines, safe cancellation, and terminal exhaustion.
- Added a browser-independent async `run_once(now, limit)` coordinator with per-record isolation and no direct staging, active-pointer, Fabric, or OneLake operation.
- Changed the existing authorized Sync route to enqueue ontology work durably and return its run reference while preserving compatibility fields and unrelated ingestion methods.

## Task Commits

Each TDD task was committed with a RED test before its GREEN implementation:

1. **Task 1 RED: durable lifecycle contracts** - `b66efea7`
2. **Task 1 GREEN: durable run store and coordinator** - `55f06a6e`
3. **Task 2 RED: durable Sync intake contracts** - `b94db709`
4. **Task 2 GREEN: CLI and enqueue-only Manual Sync** - `b9a5ef42`
5. **Lifecycle hardening: lease renewal and abandoned-attempt termination** - `cfbed186`

## Files Created/Modified

- `src/ontology_discovery/contracts.py` - Async processor and non-authoritative dependency protocols.
- `src/ontology_discovery/store.py` - Versioned atomic run ledger, CAS transitions, retries, deadlines, cancellation, leases, and fencing.
- `src/ontology_discovery/coordinator.py` - Bounded durable-state dispatch with per-record error isolation.
- `src/ontology_discovery/cli.py` - One-pass async command entry point.
- `src/ontology_discovery/__init__.py` - Public package exports.
- `src/onboarding/service.py` - Durable ontology enqueue seam while retaining unrelated ingestion methods.
- `src/api/routers/connections.py` - Existing authorized Sync endpoint now delegates to durable intake.
- `tests/test_ontology_discovery_store.py` - Duplicate, contention, legacy, retry, cancellation, renewal, and lease-loss coverage.
- `tests/test_ontology_discovery_coordinator.py` - Restart, deadline, bounded-pass, CLI, Sync compatibility, and no-publication coverage.
- `pyproject.toml` - Includes the ontology discovery package in built distributions.

## Decisions Made

- Trigger origin is audit metadata, not identity: manual and scheduled requests for one source generation converge.
- Cancellation immediately invalidates the active fence, so an already-running stale worker cannot persist a later checkpoint.
- The existing `sync()` and `sync_async()` ingestion methods remain intact for non-API ingestion callers; only the API ontology-refresh path moved to the durable ledger.
- The root planning state remains owned by active Phase 03.1 and was deliberately not advanced or rewritten.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Included the new package in wheel builds**
- **Found during:** Task 1
- **Issue:** The repository uses an explicit Hatch package list, so the new package would work from source but disappear from built artifacts.
- **Fix:** Added `src/ontology_discovery` to `tool.hatch.build.targets.wheel.packages`.
- **Files modified:** `pyproject.toml`
- **Verification:** Editable package rebuild and all imports/tests passed.
- **Committed in:** `55f06a6e`

**2. [Rule 1 - Bug] Closed abandoned final-attempt and lease-renewal gaps**
- **Found during:** Overall lifecycle review after Task 2
- **Issue:** A worker crash after consuming the final claim could leave an expired run perpetually due, and long-running workers had no durable lease-renewal transition.
- **Fix:** Added terminal attempt exhaustion and fenced lease renewal with restart-window tests.
- **Files modified:** `src/ontology_discovery/store.py`, `src/ontology_discovery/coordinator.py`, `tests/test_ontology_discovery_store.py`, `tests/test_ontology_discovery_coordinator.py`
- **Verification:** Fourteen lifecycle/coordinator tests and the full relevant regression suite passed.
- **Committed in:** `cfbed186`

---

**Total deviations:** 2 auto-fixed (1 missing critical functionality, 1 bug)
**Impact on plan:** Both fixes are required for distributable and genuinely bounded durable execution; no later Phase 13 feature was started.

## Issues Encountered

- The initial RED runs failed on the expected missing ontology-discovery modules and CLI.
- The repository's existing FastAPI tests emit one upstream Starlette/httpx deprecation warning; no Plan 13-02 failure or new warning was introduced.

## Verification

- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- `uv run pytest -q tests/test_ontology_discovery_store.py tests/test_ontology_discovery_coordinator.py -x` — 14 passed.
- `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_subscription_onboarding.py -k 'sync or restart or timeout' -x` — 25 passed.
- `uv run ruff check src/ontology_discovery src/onboarding/service.py src/api/routers/connections.py` — passed.
- Relevant full regressions for onboarding, API HTTP, Phase 13 contracts/preflight, and remediation coordinator — 120 passed.

## Known Stubs

None. The CLI's record-only processor is the intentional non-authoritative Plan 13-02 boundary; later plans compose evidence/proposal processing and the separately authorized publisher.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 13-03 can persist incremental evidence and batch checkpoints against the durable run/fence contract.
- Plan 13-10 can later replace the compatibility projection with publisher-backed durable status without restoring an API-owned worker.
- Phase 03.1 remains the active root planning workstream; no root state, roadmap, requirements, deployment, or later Phase 13 plan was changed.

## Self-Check: PASSED

- All eight created Plan 13-02 artifacts exist.
- All five RED/GREEN/hardening commits are present in repository history.
- Root `.planning/STATE.md` is byte-identical to the inherited Phase 13-01 state and still identifies Phase 03.1 as active.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
