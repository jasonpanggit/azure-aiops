---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 17
subsystem: ontology-publisher
tags: [onelake, fabric, etag-cas, managed-identity, rollback, fault-injection]

requires:
  - phase: 13-16
    provides: Content-addressed publisher dispatches and exact process capability matrix
  - phase: 13-09
    provides: Service-enforced ETag CAS, monotonic fencing, immutable generations, and five consumer families
provides:
  - Finite production publisher worker and CLI under the publisher managed identity
  - Ordered immutable stage, persisted validation, five-family staged compatibility, Fabric materialization, final preconditions, pointer CAS, and post-check
  - Reauthorized immutable rollback intake and automatic newer-fence predecessor restoration
  - Validation-only publisher drill control and 100 deterministic publication/concurrency trials
affects: [13-18, 13-19, ontology-publisher, fabric-runtime, live-validation]

actuals:
  tokens: 77457
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - Dispatch-root-only narrow publisher capabilities
    - Publisher-specific immutable Fabric credential rebinding
    - Receipt-driven restart recovery across ordered publication steps
    - Post-CAS verification as a commit check with compensating newer-fence rollback
    - Isolated expiring one-shot validation drill controls

key-files:
  created:
    - src/ontology_discovery/publisher_worker.py
    - src/ontology_discovery/publisher_cli.py
    - src/ontology_discovery/drill_control.py
    - tests/test_ontology_publisher_runtime.py
    - tests/test_ontology_drill_control.py
  modified:
    - src/ontology_discovery/publisher.py
    - src/ontology_discovery/dispatch_store.py
    - src/ontology_discovery/command_intake.py
    - src/fabric/sync_service.py

key-decisions:
  - "Fabric materialization is generation-scoped and completes before pointer CAS; the old pointer remains reader-visible on stage, validation, compatibility, or Fabric failure."
  - "Rollback intake is untrusted until the publisher re-resolves connection scope, expiry, target audit/validation/compatibility, active generation, and exact pointer ETag."
  - "The shared Fabric YAML is never authoritative for publisher identity: its auth block is replaced with a managed-identity config carrying AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID before build_runtime."
  - "A failed post-CAS consumer check is terminal even after successful compensation; success is never reported for a generation that required automatic rollback."
  - "Validation drills remain absent by default and require publisher identity, three independent validation-environment assertions, an isolated root, expiry, and single-use audit transitions."

patterns-established:
  - "Publisher composition: claim immutable dispatch, resume only matching durable receipts, and derive identity/fence/pointer conditions inside the worker."
  - "Safe visibility: persisted stage and Fabric writes precede one service-conditional pointer update; five consumers verify both staged and live generations."
  - "Compensating transition: re-read the failed active generation, allocate a strictly newer fence, conditionally restore the retained predecessor, and persist old/new/old evidence."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: A dispatch-root-only publisher worker performs the fixed stage-to-post-check production sequence and survives restart.
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_worker_consumes_coordinator_dispatch_in_fixed_visibility_order
        status: pass
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_fabric_failure_never_exposes_generation_and_restart_uses_same_payload
        status: pass
    human_judgment: false
  - id: D2
    description: Rollback intake is reauthorized under publisher authority and executes as a fenced immutable dispatch.
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_rollback_intake_reauthorizes_before_authoritative_dispatch
        status: pass
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_explicit_rollback_uses_newer_fence_and_restores_retained_generation
        status: pass
    human_judgment: false
  - id: D3
    description: Fabric runtime composition replaces any API credential with the explicit publisher managed-identity client ID.
    requirement: AUTO-ONT-05
    verification:
      - kind: unit
        ref: tests/test_ontology_publisher_runtime.py#test_runtime_builder_passes_only_publisher_identity_to_fabric
        status: pass
    human_judgment: false
  - id: D4
    description: A failed live consumer check automatically restores the predecessor under a newer fence without claiming success.
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_failed_post_check_automatically_restores_predecessor_with_newer_fence
        status: pass
    human_judgment: false
  - id: D5
    description: Publisher-only validation drill controls are default-disabled, allowlisted, expiring, audited, one-shot, and self-cleaning.
    requirement: AUTO-ONT-07
    verification:
      - kind: unit
        ref: tests/test_ontology_drill_control.py
        status: pass
    human_judgment: false
  - id: D6
    description: One hundred deterministic fault trials preserve one complete validated reader-visible generation.
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: tests/test_ontology_publisher_runtime.py#test_deterministic_fault_trials_preserve_one_complete_visible_generation[seed-00..99]
        status: pass
    human_judgment: false

duration: 16min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 17: Dedicated Publisher Runtime Summary

**A publisher-credential-bound finite worker now materializes Fabric before conditional pointer cutover, verifies all five consumer families, and restores the predecessor under a newer fence on post-CAS failure.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-09-07T06:47:53Z
- **Completed:** 2026-09-07T07:03:24Z
- **Tasks:** 3
- **Files modified:** 9 implementation/test files

## Accomplishments

- Added the production publisher worker and finite CLI with the exact publisher capability row: connection read, rollback command claim/status, no state root, dispatch claim/status plus rollback creation, and publication stage/pointer authority.
- Reworked publication into immutable stage, read-back validation, five staged checks, generation-scoped Fabric materialization, final mutable-precondition checks, one pointer CAS, and five live post-checks with durable receipts.
- Added rollback intake reauthorization and explicit rollback execution through the same retained-generation and fenced pointer primitive.
- Added automatic newer-fence predecessor restoration on post-check failure, including terminal critical handling when compensation cannot complete.
- Added publisher-only validation drills and 100 deterministic fault/concurrency trials spanning stage, validation, compatibility, Fabric, final checks, CAS, all consumer families, restart, and rollback failure.

## Task Commits

1. **Task 1: Ordered durable publisher worker**
   - `6621f880` — RED publisher integration contracts
   - `2cee6fdd` — ordered stage/materialize/CAS/post-check worker
2. **Task 2: Publisher credential and deterministic rollback**
   - `d2b97828` — RED rollback/identity contracts
   - `59a16c25` — reauthorized rollback intake and identity-bound CLI
3. **Task 3: Drill control and automatic rollback**
   - `54a37df9` — RED drill/rollback/100-seed contracts
   - `6ca94f0f` — newer-fence compensation and validation drills
   - `0ea279ef` — guarded drill lifecycle CLI completion

## Files Created/Modified

- `src/ontology_discovery/publisher_worker.py` — bounded publish/rollback processor, durable receipts, restart recovery, rollback intake authorization.
- `src/ontology_discovery/publisher_cli.py` — exact-root production composition, Fabric auth rebinding, finite worker and guarded drill commands.
- `src/ontology_discovery/drill_control.py` — publisher-only validation gate with arm/ready/resume/consume/expire/clean audit.
- `src/ontology_discovery/publisher.py` — ordered visibility state machine and automatic compensating pointer transition.
- `src/ontology_discovery/dispatch_store.py` — narrow publish/rollback claim, lease, receipt, and terminal CAS capabilities rooted only in dispatch home.
- `src/ontology_discovery/command_intake.py` — rollback-specific publisher consumer and observed generation/ETag contract.
- `src/fabric/sync_service.py` — Fabric materialization callback moved before pointer promotion.
- `tests/test_ontology_publisher_runtime.py` — production composition, identity, rollback, restart, stale writer, consumers, and 100-seed coverage.
- `tests/test_ontology_drill_control.py` — disabled/default, environment, identity, allowlist, pause/resume, one-shot, expiry, and cleanup coverage.

## Decisions Made

- Followed `13-PATTERNS.md` by preserving immutable manifest-last staging and fail-closed persisted-stage validation, while retaining service ETag/fence CAS as the only remote pointer authority.
- Kept D-04 hard-shadow exclusion independently enforced both when converting a dispatch candidate and during publication validation.
- Kept deployed Plan 07 identities/workspaces untouched; deployment and RBAC remain Plan 19 work.
- Preserved the active Phase 03.1 STATE position fields while recording Plan 13-17 completion metadata.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Allowed byte-identical immutable-stage recovery**
- **Found during:** Task 1 restart verification
- **Issue:** A failed Fabric materialization left a correct immutable stage, but the original publisher treated every retry as an immutable conflict.
- **Fix:** Read back and compare every staged artifact; resume only an exact match and reject changed content as immutable.
- **Files modified:** `src/ontology_discovery/publisher.py`, `src/ontology_discovery/publisher_worker.py`
- **Verification:** Restart integration test and full targeted suite.
- **Committed in:** `2cee6fdd`

**2. [Rule 2 - Missing Critical] Added explicit CLI lifecycle for drill control**
- **Found during:** Task 3 overall verification
- **Issue:** The worker could consume drill state, but the required publisher-only arm/inspect/resume/clean operations were not reachable through the finite CLI.
- **Fix:** Added guarded drill subcommands that reuse publisher identity and validation-environment checks.
- **Files modified:** `src/ontology_discovery/publisher_cli.py`, `src/ontology_discovery/drill_control.py`
- **Verification:** Targeted drill tests and changed-file Ruff.
- **Committed in:** `0ea279ef`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical)
**Impact on plan:** Both fixes were required for deterministic restart and operational drill correctness; no deployment, API, Terraform, or Plan 18 scope was added.

## Issues Encountered

- Full repository `pytest` retains three pre-existing failures in unchanged ontology graph/network behavior tests:
  `test_graph_network_traversal.py::test_private_endpoint_exposure_path_reaches_the_backing_resource`,
  `test_operational_context_graph_v2_hardening.py::test_retired_relationship_with_reclassified_endpoint_type_passes_validation`, and
  `test_operational_context_graph_v2_hardening.py::test_synchronize_resolves_deferred_edge_once_target_entity_appears`.
- Repository-wide Ruff retains 27 pre-existing findings in legacy scripts. All Plan 13-17 changed files pass Ruff.

## Verification

- Complete targeted Plan 17 suite — **140 passed**
- Task 3 focused drill/rollback/100-seed gate — **106 passed**
- Changed-file `uv run ruff check ...` — **passed**
- `uv run python .planning/scripts/preflight_phase_13.py` — **passed**
- Full `uv run pytest -q` — **3 pre-existing out-of-scope failures**
- Full `uv run ruff check .` — **27 pre-existing out-of-scope findings**

## Known Stubs

None. Empty strings, collections, and optional values found by the scan are fail-closed configuration defaults, transient accumulators, or test fixtures; no production publisher data source is unwired.

## User Setup Required

Production must provide explicit pairwise-distinct values for:

- `AIOPS_CONNECTION_HOME`
- `AIOPS_ONTOLOGY_COMMAND_HOME`
- `AIOPS_ONTOLOGY_DISPATCH_HOME`
- `AIOPS_ONTOLOGY_PUBLICATION_HOME`
- `AIOPS_FABRIC_CONFIG`
- `AIOPS_IDENTITY_CLASS=publisher`
- matching `AZURE_CLIENT_ID` and `AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID`

Drills remain disabled unless explicitly enabled in `AIOPS_ENVIRONMENT=validation` with independent validation connection/workspace assertions and an isolated `AIOPS_ONTOLOGY_DRILL_HOME`.

## Next Phase Readiness

- Plan 13-18 may expose lifecycle/API status against this narrow durable command topology without receiving publisher authority.
- Plan 13-19 may deploy and validate the publisher worker, identity assignments, roots, and RBAC. No deployment was performed here.
- The active Phase 03.1 position remains unchanged, and Plan 18 was not started.

## Self-Check: PASSED

All five created files, four modified implementation files, and seven TDD/task/fix commits were found in the target worktree.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
