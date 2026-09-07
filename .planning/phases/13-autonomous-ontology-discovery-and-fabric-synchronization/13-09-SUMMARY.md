---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 09
subsystem: ontology-publication
tags: [onelake, etag-cas, fencing, immutable-generations, rollback, shadow-mode]

requires:
  - phase: 13-05
    provides: hard shadow admission and disabled synthetic pair-release controls
  - phase: 13-06
    provides: five-family generation resolver and compatibility aliases
  - phase: 13-07
    provides: live-verified dedicated publisher identity and RBAC separation
  - phase: 13-08
    provides: approved pointer cutover, publisher RBAC, and prompt-agent runtime
provides:
  - service-enforced ETag CAS, create-only records, finite lease-loss detection, and monotonic fences
  - publisher-identity-only immutable generation staging with complete validation and audit
  - conditional promotion and rollback retaining deterministic generations
  - authoritative E2E tracer proving exact AI bounds, shadow exclusion, consumer resolution, and stale-writer rejection
affects: [13-10, 13-12, ontology-publication, generation-consumers, fabric-sync]

actuals:
  tokens: 21606
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - storage-service ETag CAS and create-only writes as the consequential-write authority
    - finite lease for liveness plus separately allocated monotonic fence for stale-writer exclusion
    - immutable stage and audit intent before one conditional pointer transition
    - stable generation and previous-generation aliases retained for existing consumers

key-files:
  created:
    - src/ontology_discovery/publisher.py
    - tests/test_ontology_generation_publication.py
    - tests/test_ontology_discovery_e2e.py
  modified:
    - src/storage/onelake_documents.py
    - src/storage/datasets.py
    - src/storage/locking.py
    - src/ontology/ontology_validator.py
    - src/ontology_discovery/generation_resolver.py
    - tests/test_onelake_documents.py
    - tests/test_run_lock.py

key-decisions:
  - "Use storage-returned ETags and create-only conditions as the authority for pointer and immutable-record writes; revision-based write remains a compatibility API."
  - "Treat lease renewal failure as permanent loss for that holder and require an independently monotonic per-scope fence before promotion."
  - "Persist a complete immutable stage and promotion audit intent before CAS, then append an immutable result receipt after successful visibility change."
  - "Keep Phase 13 publication hard-shadowed: any model-derived relationship fails complete publication validation even when synthetic pair-release machinery is exercised in tests."
  - "Resolve local current.json metadata for authoritative tests and local operation while preserving the existing symlink-only DatasetStore fallback."

patterns-established:
  - "Consequential transition: authorize publisher/checkpoints -> validate -> immutable stage -> durable audit intent -> recheck cancellation/lease/fence/source/current/ETag -> CAS."
  - "Rollback: validate retained target and its audit/compatibility evidence -> persist rollback intent -> apply the same fenced conditional pointer transition."

requirements-completed: [AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Independent writers are serialized by service ETag conditions, finite lease loss, and monotonic fences rather than process-local revision checks."
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: "tests/test_onelake_documents.py and tests/test_run_lock.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Only the approved publisher can stage a complete immutable, validated, compatible, audited generation and conditionally promote or roll it back."
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: "tests/test_ontology_generation_publication.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "The real deterministic tracer enforces 50/200/40, 8000/1200, and 60-second bounds while excluding model edges, resolving all consumer families, rejecting a paused stale writer, and rolling back."
    requirement: AUTO-ONT-07
    verification:
      - kind: e2e
        ref: "tests/test_ontology_discovery_e2e.py"
        status: pass
      - kind: integration
        ref: "77-test Plan 13-09 storage/locking/publication/consumer regression matrix"
        status: pass
    human_judgment: false

duration: 21min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 09: Authoritative Deterministic Ontology Publication Summary

**Service-enforced CAS, immutable audited generations, monotonic writer fences, hard shadow exclusion, consumer cutover, and fenced rollback now form the first authoritative deterministic ontology publication tracer.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-09-07T01:37:52Z
- **Completed:** 2026-09-07T01:58:26Z
- **Tasks:** 3
- **Files modified:** 10 implementation/test files

## Accomplishments

- Added fail-closed JSON snapshot, create-only, text create-only, and ETag replacement primitives. Independent clients cannot both commit against one predecessor, and immutable stage artifacts cannot be overwritten.
- Added finite lease-loss state and a CAS-backed monotonic per-scope fence allocator, then required pointer transitions to match predecessor owner, fence, source generation, active generation, and ETag.
- Added a dedicated `OntologyGenerationPublisher` that requires the approved publisher identity and both cutover checkpoints, excludes every model-derived edge, performs complete graph/lineage/compatibility validation, writes immutable stages and audit intent, rechecks mutable safety facts immediately before CAS, and uses the same transition for rollback.
- Preserved `generation`/`previous_generation` compatibility aliases and the legacy local symlink fallback while making local and remote generation resolution expose authoritative source, prior-generation, and pointer-ETag metadata.
- Added a real coordinator-backed E2E tracer covering split 51/201/41 inputs under exact 50/200/40 per-batch limits, normal 8,000/1,200 token ceilings, a clamped 60-second attempt deadline, disabled synthetic release machinery, deterministic-only publication, all five consumer families, paused stale-writer loss, and rollback.

## Task Commits

Each TDD task has a RED contract commit followed by its implementation:

1. **Task 1 RED: storage fencing contracts** - `d7f1a0ec`
2. **Task 1 GREEN: service CAS, finite lease loss, and monotonic fences** - `93b377ce`
3. **Task 2 RED: immutable publication safety contracts** - `484cb025`
4. **Task 2 GREEN: complete publisher, promotion, and rollback** - `a2086c1e`
5. **Task 3 RED: authoritative E2E tracer** - `656fde00`
6. **Task 3 GREEN: local authoritative pointer resolution** - `260bd130`
7. **Task 3 GREEN: bounded real-coordinator tracer flow** - `8cbb1853`

## Files Created/Modified

- `src/storage/onelake_documents.py` - Storage ETag snapshots, create-only JSON/text, and conditional replacement while retaining revision-write compatibility.
- `src/storage/datasets.py` - Approved-publisher adapter, immutable generation artifacts, compatibility pointer schema, conditional promotion, and rollback audit support.
- `src/storage/locking.py` - Finite lease-loss state and durable monotonic fence allocation.
- `src/ontology_discovery/publisher.py` - Complete stage/validate/audit/recheck/CAS publication and rollback service.
- `src/ontology/ontology_validator.py` - Publication-level graph, authority, lineage, and five-family compatibility validation.
- `src/ontology_discovery/generation_resolver.py` - Local authoritative pointer metadata with legacy symlink fallback.
- `tests/test_onelake_documents.py` - Independent-client ETag, create-only, publisher identity, and full pointer-condition tests.
- `tests/test_run_lock.py` - Lease-loss and monotonic-fence tests.
- `tests/test_ontology_generation_publication.py` - Valid promotion/rollback and stale, cancelled, lease-lost, partial, unaudited, incompatible, immutable, and shadow failures.
- `tests/test_ontology_discovery_e2e.py` - Real bounded coordinator, curator budget, shadow policy, deterministic publication, consumer resolution, stale writer, and rollback tracer.

## Decisions Made

- ADLS/OneLake ETag conditions, not JSON revision fields or process locks, decide contested authoritative writes.
- A lease provides temporary mutual exclusion only; the monotonic fence prevents an expired holder from resuming consequential work.
- `current.json` retains established `generation` and `previous_generation` names alongside explicit active/prior fields, so cutover does not break production consumers.
- Publication audit is two-phase and immutable: authorization intent exists before pointer CAS, and the successful pointer ETag is recorded in a result receipt.
- Synthetic tests may prove disabled release behavior, but the production `ProposalPolicy()` default remains shadow-only and the publisher independently rejects model-derived rows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added local authoritative pointer metadata resolution**
- **Found during:** Task 3 consumer-cutover E2E
- **Issue:** `GenerationResolver` ignored `current.json` for local stores, so the synthetic authoritative path could resolve rows but omitted the real pointer ETag/source/prior metadata and could infer the wrong rollback predecessor when a stale staged generation remained.
- **Fix:** Read and hash local pointer content when present, while retaining the legacy symlink-only fallback for existing DatasetStore users.
- **Files modified:** `src/ontology_discovery/generation_resolver.py`
- **Verification:** E2E old/new/old resolution and existing generation-consumer regressions passed.
- **Committed in:** `260bd130`

---

**Total deviations:** 1 auto-fixed (1 missing critical correctness control).
**Impact on plan:** The additional resolver change was required to prove complete consumer resolution and rollback without changing public aliases or starting Plan 13-10 integration.

## Issues Encountered

- Context7 CLI was unavailable; the installed `azure-storage-file-datalake` 12.x method signatures were inspected directly before using its ETag and create-only request conditions.
- Ruff found import-order and exception-type issues during Task 1; both were corrected before the GREEN commit.

## Verification

- `uv run pytest -q tests/test_onelake_documents.py tests/test_run_lock.py -x` — passed.
- `uv run pytest -q tests/test_ontology_generation_publication.py -x` — passed.
- `uv run pytest -q tests/test_ontology_discovery_e2e.py tests/test_ontology_generation_publication.py -x` — passed.
- Storage, locking, publication, E2E, generation-consumer, and publication-durability matrix — 77 passed.
- Required Ruff checks over all Plan 13-09 source and test files — passed.
- `uv run python .planning/scripts/preflight_phase_13.py` — passed before implementation and after final verification.
- `git diff --check` — passed.
- All seven task commits contain the required Copilot trailer.

## Known Stubs

None.

## User Setup Required

None - no deployment, push, merge, credential change, or external service mutation was performed.

## Next Phase Readiness

- The authoritative storage and publisher boundary is ready for Plan 13-10 to integrate `FabricSyncService` through the dedicated publisher.
- The production runtime remains prompt-agent and shadow-only; no model-derived relationship can enter an authoritative generation.
- Root Phase 03.1 remains the active workstream; only Phase 13 completed-plan accounting is updated.

## Self-Check: PASSED

- All three created artifacts and all seven modified implementation/test artifacts exist.
- All seven RED/GREEN/corrective task commits are present in repository history.
- Root STATE.md still names Phase 03.1 / Plan 03.1-19 as active; only the completed-plan count and list changed.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
