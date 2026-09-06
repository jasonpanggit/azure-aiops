---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 03
subsystem: operations-copilot
tags: [orchestration, policy, compatibility, canonical, deterministic-fallback]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 01
    provides: Canonical orchestration contract, policy, and service tracer
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 02
    provides: Evidence snapshot v2 wire contract
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 04
    provides: Twelve-specialist manifest and runtime parity
provides:
  - Generalized keyword-based deterministic fallback via select_specialists_for_turn
  - Canonical orchestration mode switch with explicit legacy/shadow/rollback seam
  - Thin canonical compatibility adapters for /copilot/investigate, /copilot/investigate-context, /agents/investigations
  - Contract version stamping on new ledger writes and legacy ledger read projection
affects: [11-05, 11-06, 11-07, 11-08, 11-09, 11-10, 11-11, 11-12, 11-14, 11-15, 11-16]
actuals:
  tokens: 6147
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns:
    - Deterministic keyword fallback passes the same policy validator as model-proposed candidates
    - Canonical/shadow/rollback seam controlled by AIOPS_AGENT_ORCHESTRATION_MODE env var
    - Legacy planners retained; retirement requires zero v1 traffic and separate review
    - Old ledgers projected on read without bulk rewrite
key-files:
  created: []
  modified:
    - src/operations/maf_orchestrator.py
    - src/operations/orchestration_service.py
    - src/operations/investigation.py
    - src/operations/autonomous_investigation.py
    - src/api/routers/copilot.py
    - src/api/routers/multi_agent.py
    - tests/test_orchestration_policy.py
    - tests/test_api_copilot_unified.py
key-decisions:
  - "Generalized fallback uses select_specialists_for_turn constrained by page_mappings, not a hardcoded specialist ID."
  - "Canonical mode is opt-in via AIOPS_AGENT_ORCHESTRATION_MODE=canonical; legacy and MAF modes preserved as rollback."
  - "Contract version is stamped unconditionally on new ledger writes; old ledgers are projected on read without mutation."
  - "Legacy planner code retained through Phase 11; retirement requires zero v1 traffic for 30 days plus separate review."
patterns-established:
  - "Mode-controlled seam: canonical_orchestration_enabled() gates canonical vs legacy routing at each surface."
  - "project_legacy_ledger provides read-time version injection without bulk data migration."
requirements-completed: [COP-01, COP-05]
coverage:
  - id: 11-03-01
    description: "Adversarial candidates rejected pre-call; keyword fallback passes same validator."
    requirement: COP-01
    verification:
      - kind: unit
        ref: "tests/test_orchestration_policy.py"
        status: pass
    human_judgment: false
  - id: 11-03-02
    description: "Three legacy routes produce equivalent contract-versioned results through compatibility adapters."
    requirement: COP-05
    verification:
      - kind: integration
        ref: "tests/test_api_copilot_unified.py"
        status: pass
    human_judgment: false
duration: 12min
completed: 2026-09-06
status: complete
---

# Phase 11 Plan 03: Canonical Orchestration Service and Legacy Compatibility Adapters Summary

**The inventory-proven orchestration service now uses a generalized keyword-based deterministic fallback, and all three legacy investigation routes migrate through thin canonical compatibility adapters with explicit rollback seams.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-06T11:35:20Z
- **Completed:** 2026-09-06T11:48:16Z
- **Tasks:** 2 (TDD: RED→GREEN each)
- **Files modified:** 8

## Accomplishments

### Task 1: Model-proposal and deterministic-policy separation

- Replaced the hardcoded inventory-only fallback with `build_deterministic_fallback` in `maf_orchestrator.py`, which uses `select_specialists_for_turn` constrained by `page_mappings` to select page-compatible specialists by question keywords.
- Added `canonical_orchestration_enabled()` mode switch and `MODE_CANONICAL` constant for the explicit legacy/shadow/rollback seam.
- Wired `OrchestrationService._fallback_candidate` to delegate to the generalized keyword fallback, ensuring the fallback passes the same policy validator as model-proposed candidates.
- Added 5 policy tests: valid candidate construction, page-constrained specialist selection, citation reference integrity, empty-evidence coverage citation, and no mutation intent.

### Task 2: Thin canonical compatibility adapters for legacy routes

- Added `canonicalize_investigation` to `investigation.py` — projects a legacy `Investigation` result into the canonical wire contract by stamping `contract_version`.
- Stamped `contract_version` unconditionally on new autonomous (`run_autonomous_investigation`) and context (`run_context_investigation`) ledger writes.
- Added `project_legacy_ledger` to `autonomous_investigation.py` — injects `contract_version` into old ledgers on read without mutating the persisted record.
- Adapted `/copilot/investigate` to use `canonicalize_investigation` when canonical mode is enabled; legacy wire shape preserved otherwise.
- Adapted `/agents/investigations/{ledger_id}` GET to project old ledgers through `project_legacy_ledger` when canonical mode is enabled.
- Added 6 integration tests: contract version stamping on investigate, context, and multi-agent routes; legacy wire field preservation; old ledger projection; and GET read compatibility.

## Task Commits

1. **Task 1 RED** — `805c672f` (test): 5 failing policy/fallback tests
2. **Task 1 GREEN** — `a564d08a` (feat): Generalized keyword fallback and canonical mode
3. **Task 2 RED** — `d15e24a7` (test): 6 failing compatibility adapter tests
4. **Task 2 GREEN** — `07d7f2a0` (feat): Thin canonical compatibility adapters

## Files Modified

- `src/operations/maf_orchestrator.py` — `build_deterministic_fallback`, `canonical_orchestration_enabled`, `MODE_CANONICAL`
- `src/operations/orchestration_service.py` — Generalized `_fallback_candidate` delegation
- `src/operations/investigation.py` — `canonicalize_investigation`, `CONTRACT_VERSION`
- `src/operations/autonomous_investigation.py` — `project_legacy_ledger`, `CONTRACT_VERSION`, stamped on new ledger writes
- `src/api/routers/copilot.py` — Canonical mode adapter for `/copilot/investigate`
- `src/api/routers/multi_agent.py` — Legacy ledger projection for GET route
- `tests/test_orchestration_policy.py` — 5 new keyword fallback and policy tests
- `tests/test_api_copilot_unified.py` — 6 new compatibility adapter tests

## Decisions Made

- The generalized fallback uses the existing `select_specialists_for_turn` keyword matching rather than duplicating a second specialist-selection path, keeping the two orchestration paths from silently drifting apart.
- Contract version stamping is unconditional on new writes — the mode switch controls routing, not versioning. This ensures every new ledger is self-describing regardless of the active mode.
- Legacy planners are retained in full through Phase 11; the `AIOPS_AGENT_ORCHESTRATION_MODE` env var provides three positions: `deterministic` (page-anchored rollback), `maf` (existing MAF behavior), and `canonical` (canonical service routing).

## Verification Evidence

- `python3 -m pytest tests/test_orchestration_policy.py tests/test_context_specialist_routing.py -q` — **32 passed**
- `python3 -m pytest tests/test_api_copilot_unified.py tests/test_api_copilot_investigation.py tests/test_api_copilot_snapshot.py tests/test_api_multi_agent.py -q` — **62 passed**
- `python3 -m pytest tests/test_foundry_agent.py tests/test_mcp_tools.py tests/test_mcp_protocol.py tests/test_orchestration_parity.py -q` — **64 passed**
- `python3 -m ruff check` on all changed files — **passed**
- `python3 -m compileall -q` on all changed source files — **passed**
- `git diff --check` — **passed**

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all adapter paths are wired to real execution logic.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- The canonical orchestration mode is opt-in and does not change default behavior.
- Later Phase 11 plans expanding page adapters (11-06 through 11-12) and specialist portfolio (11-14 through 11-16) can use the same canonical service path.
- The contract's `page_kind` Literal remains limited to inventory/connections/connections_fabric; full canonical routing for other page kinds requires the contract expansion scheduled in later plans.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged as requested.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-06*
