---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 18
subsystem: ontology-api
tags: [command-intake, rbac, onelake, etag, reconciliation, rollback]

requires:
  - phase: 13-16
    provides: OneLake coordinator state, typed commands, and publisher dispatch
  - phase: 13-17
    provides: dedicated publisher worker, rollback intake, and fenced publication
provides:
  - exact four-root API composition for connection, state, publication, and command capabilities
  - immutable manual-run, rollback, and maintenance command intake without publisher authority
  - distinct ontology maintenance RBAC and coordinator-owned cadence CAS
  - fresh-process manual publish and rollback topology proof through API, coordinator, publisher, and API reload
affects: [13-19, 13-20, 13-21, ontology-api, connections-ui]

actuals:
  tokens: 12582
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - four explicit pairwise-distinct API capability roots in production
    - create-only content-addressed commands with worker reauthorization
    - non-inherited maintenance authority with coordinator-owned cadence mutation
    - fresh-process topology tests across every authority boundary

key-files:
  created:
    - tests/test_ontology_command_topology.py
  modified:
    - src/ontology_discovery/command_intake.py
    - src/ontology_discovery/generation_resolver.py
    - src/ontology_discovery/runtime.py
    - src/ontology_discovery/store.py
    - src/api/runtime.py
    - src/api/routers/ontology_discovery.py
    - src/api/models.py
    - src/api/rbac.py
    - src/api/dependencies.py
    - src/onboarding/service.py
    - tests/test_api_ontology_discovery.py

key-decisions:
  - "API processes receive only connection read, ontology state read, publication read, and command create/read/status roots; dispatch, drill, stage, fence, pointer, and publisher credentials remain absent."
  - "Manual Sync and run-now create the same typed manual command; only the coordinator converts accepted intent into authoritative run state."
  - "Full reconciliation maintenance uses a dedicated ontology_maintainer role and expected cadence revision; reader, operator, approver, and admin grants do not imply this authority."

patterns-established:
  - "Idempotency identity is command type + connection + idempotency key; retry timestamps do not create duplicate intent."
  - "Rollback eligibility uses the exact storage ETag projected by the generation resolver and rechecked by the publisher."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Default API runtime reconstructs durable state from four explicit roots and enqueues manual and rollback commands without authoritative write capability.
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: tests/test_api_ontology_discovery.py#test_default_runtime_enqueues_manual_and_rollback_commands_without_authority
        status: pass
    human_judgment: false
  - id: D2
    description: Only a dedicated maintenance principal can request a non-production full reconciliation, which the coordinator reauthorizes before cadence CAS.
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: tests/test_api_ontology_discovery.py#test_maintenance_command_requires_distinct_authority_and_coordinator_cas
        status: pass
    human_judgment: false
  - id: D3
    description: Fresh API, coordinator, publisher, and API instances reconstruct manual publication and rollback old/new/old state.
    requirement: AUTO-ONT-05
    verification:
      - kind: e2e
        ref: tests/test_ontology_command_topology.py#test_manual_publish_and_rollback_survive_every_process_reconstruction
        status: pass
    human_judgment: false
  - id: D4
    description: Default OpenAPI exposes the run, rollback, and guarded maintenance command surface while the existing Connections UI remains hard-shadow only.
    requirement: AUTO-ONT-04
    verification:
      - kind: integration
        ref: tests/test_ontology_command_topology.py#test_default_openapi_exposes_complete_ontology_command_surface
        status: pass
      - kind: automated_ui
        ref: web/src/app/connections/page.test.tsx
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 18: Four-Root API and Reconstructed Command Topology Summary

**A four-root read/create API now sends manual, rollback, and guarded maintenance intent through immutable commands while fresh coordinator and publisher processes own every authoritative transition.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-07T07:04:04Z
- **Completed:** 2026-09-07T07:16:04Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Replaced the default API's local shared-state assumptions with explicit connection, state, publication, and command roots; production requires all four to be distinct OneLake URIs.
- Routed ontology run-now, legacy Manual Sync, rollback, and maintenance through content-addressed create-only commands instead of API-owned run, stage, Fabric, fence, pointer, or rollback mutations.
- Added a non-inherited ontology maintenance role and coordinator reauthorization with cadence revision CAS.
- Proved manual command to run to publish to API reload and rollback command to authoritative old/new/old restoration across reconstructed process objects.

## Task Commits

1. **Task 1 RED** - `f616714c`
2. **Task 1 GREEN** - `3c5f4d2e`
3. **Task 2 RED** - `98334d23`
4. **Task 2 GREEN** - `ba723cce`
5. **Task 3 RED** - `733d122b`
6. **Task 3 GREEN** - `8dbb802a`
7. **Checkpoint integration** - `98a217d6`

## Files Created/Modified

- `src/ontology_discovery/command_intake.py` - Stable idempotency and maintenance cadence revision envelope.
- `src/ontology_discovery/generation_resolver.py` - Exact local service ETag projection.
- `src/ontology_discovery/runtime.py` / `store.py` - Coordinator maintenance revision reauthorization and CAS.
- `src/api/runtime.py` - Four-root production API composition.
- `src/api/routers/ontology_discovery.py` - Command-backed run-now, rollback, and maintenance actions.
- `src/api/models.py`, `rbac.py`, `dependencies.py` - Bounded maintenance request and distinct authority.
- `src/onboarding/service.py` - Manual Sync command producer.
- `tests/test_api_ontology_discovery.py` - Root, authority, idempotency, restart, and cadence tests.
- `tests/test_ontology_command_topology.py` - Reconstructed process-boundary tracer.

## Decisions Made

- Preserved direct rollback callbacks only for injected legacy tests; the default runtime always uses command intake.
- Kept maintenance absent from general admin inheritance so production cadence changes require an explicit grant.
- Used the publication store's quoted service-style local ETag instead of a resolver-specific raw digest.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Aligned local resolver ETags with publisher CAS**
- **Found during:** Task 3 rollback reconstruction
- **Issue:** The resolver returned an unquoted raw SHA while the publisher compared the service-style quoted `sha256:` ETag, causing valid rollback intent to fail as stale.
- **Fix:** Project the exact local document ETag format used by the storage CAS.
- **Files modified:** `src/ontology_discovery/generation_resolver.py`
- **Committed in:** `8dbb802a`

**2. [Rule 1 - Bug] Made retries converge on the original command**
- **Found during:** Task 1 duplicate command test
- **Issue:** Retry timestamps participated in immutable equality, so the same idempotency key conflicted instead of returning the original command.
- **Fix:** Keep timestamps on the original immutable record but exclude them from duplicate request equality.
- **Files modified:** `src/ontology_discovery/command_intake.py`
- **Committed in:** `3c5f4d2e`

**Total deviations:** 2 auto-fixed bugs required for CAS and idempotency correctness.

## Issues Encountered

None remaining.

## Checkpoint Integration

- Merged main checkpoint `10236c31` without reverting the completed Plan 18 or pre-existing branch history.
- Preserved the Phase 03.1 active-phase fields while retaining both the Phase 03.1 evidence blocker and the pre-existing Phase 13 Plan 19 deployment blocker.
- Re-ran the complete 192-test Plan 18 backend regression gate, 16-test Connections UI gate, TypeScript, Ruff, and Phase 13 dependency preflight after integration.

## Known Stubs

None.

## User Setup Required

Production API configuration requires four pairwise-distinct OneLake URI values:

- `AIOPS_CONNECTION_HOME`
- `AIOPS_ONTOLOGY_STATE_HOME`
- `AIOPS_ONTOLOGY_PUBLICATION_HOME`
- `AIOPS_ONTOLOGY_COMMAND_HOME`

## Next Phase Readiness

Plan 13-19 can deploy the now-complete coordinator, publisher, API route, and command-root topology. Plans 13-20 and 13-21 can consume deployed state without substituting local tests.

## Self-Check: PASSED

All declared files, six TDD task commits, and the checkpoint integration commit exist; the complete 192-test backend gate, 16-test web gate, TypeScript, Ruff, and dependency preflight pass.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
