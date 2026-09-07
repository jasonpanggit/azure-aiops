---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 10
subsystem: ontology-publication
tags: [durable-coordinator, dedicated-publisher, fabric-sync, manual-sync, identity-boundary]

requires:
  - phase: 13-02
    provides: durable run ledger, shared manual/scheduled identity, and enqueue-only Sync intake
  - phase: 13-09
    provides: approved publisher identity, immutable generations, fenced pointer CAS, and rollback
provides:
  - narrow validated-candidate dispatch from the durable coordinator to the dedicated publisher
  - publisher-owned identity binding and post-promotion Fabric materialization
  - restart-safe Sync and health projections from durable run and publication checkpoints
  - removal of the API-owned process-local authoritative publication runner
affects: [13-12, 13-13, 13-15, manual-sync, fabric-sync, ontology-publication]

actuals:
  tokens: 10488
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - coordinator sees only validated-candidate publish and publication-status operations
    - dedicated adapter binds publisher identity and materializes Fabric only after promotion
    - legacy Sync envelopes project durable run state without persisting process-local ownership

key-files:
  created: []
  modified:
    - src/ontology_discovery/coordinator.py
    - src/ontology_discovery/store.py
    - src/onboarding/service.py
    - src/onboarding/runtime.py
    - src/fabric/sync_service.py
    - tests/test_ontology_discovery_coordinator.py
    - tests/test_subscription_onboarding.py
    - tests/test_fabric_sync_service.py

key-decisions:
  - "Bind publisher identity inside DedicatedOntologyPublisherAdapter; coordinator and API input can supply neither identity nor candidate overrides."
  - "Promote the immutable generation before invoking FabricSyncService, and recover only a same-run immutable retry confirmed by durable publisher status."
  - "Project durable publication state into existing Sync and health fields at read time, while allowing newer unrelated ingestion state to remain authoritative."
  - "Remove _InventoryRefreshRunner instead of retaining a dormant second authoritative path."

patterns-established:
  - "Publication boundary: candidate provider -> narrow coordinator dispatch -> identity-bound publisher adapter -> generation promotion -> Fabric materialization."
  - "Compatibility projection: latest durable run augments and, when newer, projects the legacy SyncState without depending on process memory."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-05, AUTO-ONT-06]

coverage:
  - id: D1
    description: "Manual and scheduled origins converge on one durable run and one dedicated publisher dispatch."
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_coordinator.py#test_manual_and_scheduled_origins_share_publisher_dispatch_and_idempotency"
        status: pass
    human_judgment: false
  - id: D2
    description: "Coordinator and API identities cannot substitute publisher identity or access stage/pointer primitives."
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: "tests/test_fabric_sync_service.py#test_dedicated_publisher_rejects_identity_override_from_request_factory"
        status: pass
      - kind: unit
        ref: "tests/test_subscription_onboarding.py#test_sync_route_and_service_cannot_resolve_authoritative_storage_methods"
        status: pass
    human_judgment: false
  - id: D3
    description: "Sync and health preserve legacy fields while reconstructing durable success or denial after restart."
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: "tests/test_subscription_onboarding.py#test_health_reconstructs_durable_publication_after_restart"
        status: pass
      - kind: integration
        ref: "tests/test_subscription_onboarding.py#test_health_reconstructs_publisher_denial_without_moving_generation"
        status: pass
    human_judgment: false

duration: 9min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 10: Dedicated Publisher Manual Sync Summary

**Manual and scheduled ontology runs now share a durable coordinator-to-publisher path with publisher-bound identity, post-promotion Fabric materialization, and restart-safe legacy Sync/health projections.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-07T02:00:35Z
- **Completed:** 2026-09-07T02:08:42Z
- **Tasks:** 2
- **Files modified:** 8 implementation/test files

## Accomplishments

- Added a narrow `PublisherDispatchProcessor` that accepts validated candidates, records publication success or denial durably, and has no stage, pointer, storage, or publisher-identity capability.
- Added `DedicatedOntologyPublisherAdapter`, which binds the approved publisher identity internally, promotes through the Plan 13-09 publisher, then materializes Fabric through `FabricSyncService`.
- Removed `_InventoryRefreshRunner` and its API-runtime factory wiring, eliminating the separate process-local authoritative publication path while retaining unrelated `sync` and `sync_async` ingestion.
- Added durable latest-run lookup and compatibility projection so existing Sync and health clients retain their fields and receive additive generation/Fabric references after restart.

## Task Commits

Each TDD task has a RED contract commit followed by its GREEN implementation:

1. **Task 1 RED: publisher dispatch and identity contracts** - `cac49f00`
2. **Task 1 GREEN: dedicated publisher dispatch and legacy runner removal** - `9441d741`
3. **Task 2 RED: durable Sync/health projection contracts** - `b4660b29`
4. **Task 2 GREEN: restart-safe compatibility projections** - `4ed2b25f`

## Files Created/Modified

- `src/ontology_discovery/coordinator.py` - Validated candidate provider and narrow publisher dispatch processor with durable denial status.
- `src/ontology_discovery/store.py` - Deterministic latest-run lookup for restart-safe reads.
- `src/onboarding/service.py` - Additive durable run references and legacy Sync/health projection with newer-ingestion precedence.
- `src/onboarding/runtime.py` - Removed API-owned `_InventoryRefreshRunner` construction and implementation.
- `src/fabric/sync_service.py` - Dedicated identity-bound generation publisher and Fabric materialization adapter.
- `tests/test_ontology_discovery_coordinator.py` - Shared-origin idempotency, denial durability, and structural boundary tests.
- `tests/test_subscription_onboarding.py` - Restart, legacy compatibility, denial, and no-authoritative-storage tests.
- `tests/test_fabric_sync_service.py` - Promotion ordering and identity-substitution denial tests.

## Decisions Made

- Publisher identity is immutable adapter configuration, never data from a coordinator run or API request.
- A generation becomes authoritative before Fabric table materialization; a crash retry is accepted only for an immutable conflict whose durable status names the same run and active generation.
- Durable ontology status is projected at read time rather than copied into registry state, avoiding false process-local orphan reconciliation after restart.
- A newer unrelated ingestion sync remains visible over an older ontology run, preserving Phase 03.1/11 ingestion behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Expanded the file set for complete removal and restart-safe reads**
- **Found during:** Tasks 1 and 2
- **Issue:** The plan action required removing `_InventoryRefreshRunner` and reconstructing durable health, but `src/onboarding/runtime.py` and `src/ontology_discovery/store.py` were omitted from `files_modified`.
- **Fix:** Removed the runner/factory wiring and added a public latest-run lookup used by the compatibility projection.
- **Files modified:** `src/onboarding/runtime.py`, `src/ontology_discovery/store.py`
- **Verification:** Required tests, API/runtime regressions, Ruff, and Phase 13 preflight passed.
- **Committed in:** `9441d741`, `4ed2b25f`

---

**Total deviations:** 1 auto-fixed (1 missing critical functionality).
**Impact on plan:** The extra files were the exact ownership and persistence seams required to meet the stated plan; no later Phase 13 work was started.

## Issues Encountered

- Terminal retry exhaustion intentionally retains `attempts_exhausted` as the run failure class; the specific publisher denial and unchanged active generation remain durable in the publication checkpoint and message.
- The repository continues to emit one pre-existing Starlette/httpx deprecation warning in API tests.

## Verification

- `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_subscription_onboarding.py tests/test_fabric_sync_service.py -x` — 69 passed.
- `uv run pytest -q tests/test_ontology_generation_publication.py tests/test_ontology_discovery_e2e.py tests/test_ontology_discovery_store.py -x` — 16 passed.
- `uv run pytest -q tests/test_api_http.py tests/test_api_runtime.py -k 'sync or health or connection' -x` — 16 passed.
- Required and expanded Ruff checks over all modified source and test files — passed.
- `uv run python .planning/scripts/preflight_phase_13.py` — passed before implementation and after final verification.
- `git diff --check` — passed.
- All four task commits contain the required Copilot trailer.

## Known Stubs

None.

## User Setup Required

None - no deployment, push, merge, credential change, or external service mutation was performed.

## Next Phase Readiness

- Plan 13-12 can expose the durable lifecycle and generation references through scope-enforced operational APIs.
- Plan 13-13 can consume the preserved Sync/health envelope without depending on browser-owned execution.
- Root Phase 03.1 remains the active workstream; only Phase 13 completed-plan accounting is updated.

## Self-Check: PASSED

- All eight modified implementation/test artifacts exist.
- All four RED/GREEN task commits are present in repository history.
- Root `STATE.md` still names Phase 03.1 / Plan 03.1-19 as active; only completed-plan count and list changed.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
