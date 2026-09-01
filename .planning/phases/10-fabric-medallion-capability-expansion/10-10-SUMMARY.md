---
phase: 10-fabric-medallion-capability-expansion
plan: 10
subsystem: fabric-semantic-model
tags: [fabric, direct-lake, semantic-model, medallion, med-05]

requires:
  - phase: 10-fabric-medallion-capability-expansion (10-09)
    provides: Live MED-02 rollout baseline and publication/disposition conventions consumed by semantic deployment status.
provides:
  - "Deterministic code-authored Direct Lake semantic model definition parts (`model.bim`, `definition.pbism`, `.platform`)."
  - "Idempotent semantic model deploy flow with explicit `deployment-blocked` outcomes for documented Fabric error codes."
  - "Fully mocked MED-05 regression coverage with no live Fabric dependency."
affects: [10-11-fabric-medallion-capability-expansion, 10-15-fabric-medallion-capability-expansion, medallion-health]

actuals:
  tokens: 4184
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - "Semantic model deployment follows resolve/create/update idempotency using existing FabricClient request/LRO polling."
    - "Blocked deployment outcomes are explicit and versionable (`status=deployment-blocked`, reason code, dormant disposition hint)."

key-files:
  created:
    - src/fabric/semantic_model_manager.py
    - tests/test_semantic_model_manager.py
  modified:
    - src/fabric/semantic_model_manager.py
    - tests/test_semantic_model_manager.py

key-decisions:
  - "Use `/workspaces/{workspaceId}/semanticModels` for create and generic items `getDefinition`/`updateDefinition` for idempotent reconciliation."
  - "Map documented Fabric semantic model errors to explicit deployment-blocked reasons and attach `manifest_disposition: dormant`."

patterns-established:
  - "Code-generated semantic model payloads are deterministic via canonical JSON + stable table normalization."
  - "Transient 429/503 handling is delegated to FabricClient retry policy, not reimplemented in manager code."

requirements-completed: [MED-05]

coverage:
  - id: D1
    description: "Deterministic Direct Lake semantic model definition builder emits required base64 parts and references only provided Gold tables."
    requirement: "MED-05"
    verification:
      - kind: unit
        ref: "pytest tests/test_semantic_model_manager.py -q -k build"
        status: pass
    human_judgment: false
  - id: D2
    description: "Semantic model deploy flow is idempotent (`created`/`unchanged`/`updated`) and maps documented Fabric failures to `deployment-blocked`."
    requirement: "MED-05"
    verification:
      - kind: unit
        ref: "pytest tests/test_semantic_model_manager.py -q -k deploy"
        status: pass
    human_judgment: false
  - id: D3
    description: "MED-05 regression suite runs fully offline with mocked Fabric client/transport."
    requirement: "MED-05"
    verification:
      - kind: unit
        ref: "pytest tests/test_semantic_model_manager.py -q"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-09-02
status: complete
---

# Phase 10 Plan 10: Direct Lake semantic model manager summary

**Shipped a deterministic code-authored Direct Lake semantic model manager that deploys idempotently and reports explicit deployment-blocked outcomes instead of silent success.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-09-01T16:30:53Z
- **Completed:** 2026-09-01T16:34:14Z
- **Tasks:** 3/3 completed
- **Files modified:** 2

## Accomplishments

- Added `build_semantic_model_definition(display_name, gold_tables)` producing stable base64-encoded `model.bim`, `definition.pbism`, and `.platform` definition parts.
- Added `deploy_semantic_model(...)` with resolve/create/update behavior and unchanged short-circuit based on definition comparison.
- Mapped documented Fabric semantic model deployment errors (`InvalidItemType`, `ItemDisplayNameAlreadyInUse`, `CorruptedPayload`, `WorkspaceItemsLimitExceeded`) to explicit `deployment-blocked` results.
- Added a full mocked regression suite (13 tests) covering deterministic build behavior, idempotent deploy outcomes, blocked mapping, and transient retry behavior.

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED):** `1f033606` (`test`) — failing semantic model builder tests
2. **Task 1 (TDD GREEN):** `96545c76` (`feat`) — deterministic builder implementation
3. **Task 2 (TDD RED):** `583cded0` (`test`) — failing deploy behavior tests
4. **Task 2 (TDD GREEN):** `d7ce7335` (`feat`) — idempotent deploy + blocked mapping
5. **Task 3:** `b05681a6` (`test`) — completed regression scenarios

**Plan metadata:** pending final docs/state commit.

## Files Created/Modified

- `src/fabric/semantic_model_manager.py` — Direct Lake semantic model build/deploy module.
- `tests/test_semantic_model_manager.py` — MED-05 regression suite with mocked Fabric interactions.

## Decisions Made

- Reused `FabricClient.request(..., wait_for_completion=True)` for semantic-model create/update calls so LRO/retry behavior stays centralized.
- Kept deployment failure handling explicit and machine-readable with `status=deployment-blocked`, preserving reason codes and dormant disposition guidance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Runtime operation failures did not preserve specific documented blocked reasons**
- **Found during:** Task 2 (deploy TDD GREEN)
- **Issue:** RuntimeError/TimeoutError fallback always emitted `FabricOperationFailed`, obscuring documented code-level blocked reasons in error text.
- **Fix:** Added `_map_runtime_error()` to extract known blocked codes from runtime failure messages and return specific reasons when present.
- **Files modified:** `src/fabric/semantic_model_manager.py`
- **Verification:** `pytest tests/test_semantic_model_manager.py -q -k deploy`
- **Committed in:** `d7ce7335`

---

**Total deviations:** 1 auto-fixed (Rule 1: 1)
**Impact on plan:** Deviation tightened MED-05 correctness requirement; no scope creep.

## Auth Gates

None.

## Known Stubs

None found in plan-owned source/test changes.

## Issues Encountered

None beyond expected TDD red/green iteration.

## User Setup Required

None - no external setup required for this unit-tested plan.

## Next Phase Readiness

- MED-05 unit coverage is complete and deterministic.
- Ready for downstream Phase 10 plans that consume semantic readiness/status surfaces and live rollout wiring.

## Self-Check: PASSED

- Verified `src/fabric/semantic_model_manager.py` exists.
- Verified `tests/test_semantic_model_manager.py` exists.
- Verified `.planning/phases/10-fabric-medallion-capability-expansion/10-10-SUMMARY.md` exists.
- Verified task commit hashes exist in git history: `1f033606`, `96545c76`, `583cded0`, `d7ce7335`, `b05681a6`.
