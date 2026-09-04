---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 01
subsystem: operations-copilot
tags: [pydantic, orchestration, mcp, inventory, authorization]
requires:
  - phase: 10-fabric-medallion-capability-expansion
    provides: Scoped inventory read port and explicit provider status contracts
provides:
  - Canonical v2 Inventory & Data Health request/result tracer
  - Strict credential-free specialist manifest and reviewed inventory MCP grant
  - Deterministic pre-I/O policy with reason-coded fallback
  - Principal- and scope-bound bounded investigation continuity
affects: [11-02, 11-03, 11-04, 11-06, 11-13]
actuals:
  tokens: 15350
  tasks: 2
  commits: 1
tech-stack:
  added: []
  patterns:
    - Untrusted coordinator plans are fully validated before governed tool I/O
    - Specialist grants derive from a strict versioned manifest
    - Continuity IDs are server-issued and reauthorized by principal and current scope
key-files:
  created:
    - src/operations/specialists.v1.json
    - src/operations/specialist_manifest.py
    - src/operations/orchestration_contract.py
    - src/operations/orchestration_policy.py
    - src/operations/orchestration_service.py
    - src/operations/investigation_thread_store.py
    - tests/test_orchestration_policy.py
    - tests/test_api_copilot_unified.py
  modified:
    - src/operations/mcp_server.py
    - tests/test_mcp_tools.py
    - tests/test_mcp_protocol.py
key-decisions:
  - "Inventory & Data Health keeps the stable `inventory_data_health` ID and exactly one read-only Operations MCP grant: `inventory_resources`."
  - "Rejected or unavailable planner output falls back to a separately constructed candidate that passes the same deterministic policy."
  - "Thread mismatches use not-found semantics and current scope is checked again for continuation and history reads."
patterns-established:
  - "Whole-plan authorization: scope, specialist, grant, arguments, budget, DAG, citations, and mutation intent pass before execution."
  - "Citation retention: page evidence and governed tool provenance are normalized into one canonical result."
requirements-completed: [COP-01, COP-03, COP-04, COP-05]
coverage:
  - id: D1
    description: "Inventory requests execute through the canonical contract, deterministic policy, governed tool, retained citations, fallback, and principal-bound thread."
    requirement: COP-01
    verification:
      - kind: integration
        ref: "tests/test_api_copilot_unified.py"
        status: pass
      - kind: unit
        ref: "tests/test_orchestration_policy.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "The reviewed inventory MCP grant is exact, scoped by the existing read port, and mutation-free."
    requirement: COP-03
    verification:
      - kind: integration
        ref: "tests/test_mcp_tools.py#test_inventory_tool_is_an_exact_specialist_bound_reviewed_grant"
        status: pass
      - kind: integration
        ref: "tests/test_mcp_protocol.py#test_initialize_and_exact_read_only_catalog"
        status: pass
    human_judgment: false
duration: 14min
completed: 2026-09-04
status: complete
---

# Phase 11 Plan 01: Inventory & Data Health Orchestration Tracer Summary

**A read-only Inventory & Data Health request now crosses one strict manifest, canonical contract, pre-I/O authorization policy, deterministic fallback, governed inventory tool, citation result, and principal-bound thread.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-09-04T08:44:13Z
- **Completed:** 2026-09-04T08:58:27Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Added strict canonical request, candidate, evidence, coverage, citation, and result models for the inventory tracer.
- Proved scope, grant, argument, DAG, budget, citation, and mutation rejections happen before rejected candidate I/O.
- Added reason-coded planner fallback, elapsed-budget stopping, governed inventory execution, and bounded principal/scope continuity.
- Derived the reviewed `inventory_resources` MCP grant from the credential-free Inventory & Data Health manifest entry.

## Task Commits

1. **Tasks 1-2: Governed inventory tracer and reviewed MCP grant** - `354e7beb` (feat)

## Files Created/Modified

- `src/operations/specialists.v1.json` - Versioned Inventory & Data Health specialist definition.
- `src/operations/specialist_manifest.py` - Strict credential-free manifest loader.
- `src/operations/orchestration_contract.py` - Canonical request, plan, snapshot, citation, and result models.
- `src/operations/orchestration_policy.py` - Whole-plan deterministic authorization and bounds.
- `src/operations/orchestration_service.py` - Validated planner/fallback execution and cited result assembly.
- `src/operations/investigation_thread_store.py` - Bounded server-issued principal/scope continuity.
- `src/operations/mcp_server.py` - Manifest-derived reviewed inventory grant and reusable argument validation.
- `tests/test_orchestration_policy.py` - Pre-I/O rejection matrix.
- `tests/test_api_copilot_unified.py` - End-to-end service, fallback, citation, budget, and continuity tests.
- `tests/test_mcp_tools.py` - Exact inventory grant and dispatch coverage.
- `tests/test_mcp_protocol.py` - Updated exact reviewed-tool catalog contract.

## Decisions Made

- The shared MCP server advertises the manifest-derived reviewed tool; specialist authorization remains enforced by the canonical policy before dispatch, avoiding an unusable out-of-band HTTP identity.
- A required-citation specialist cannot execute a candidate with empty or foreign snapshot references.
- Planner connection, timeout, and parse failures have distinct deterministic fallback reason codes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Reauthorized history reads**
- **Found during:** Post-implementation review
- **Issue:** Ownership-only history reads could expose retained evidence after scope narrowing.
- **Fix:** History now repeats expiry, principal, and current-scope authorization.
- **Files modified:** `src/operations/investigation_thread_store.py`, `tests/test_api_copilot_unified.py`
- **Verification:** Scope-narrowing history test and focused suite pass.
- **Committed in:** `354e7beb`

**2. [Rule 2 - Missing Critical] Enforced citations and elapsed budget**
- **Found during:** Post-implementation review
- **Issue:** Empty citation claims and declarative-only wall-clock limits were not fail-safe.
- **Fix:** Required snapshot citations are validated pre-I/O and execution stops between calls after the approved elapsed budget.
- **Files modified:** `src/operations/orchestration_policy.py`, `src/operations/orchestration_service.py`, tests
- **Verification:** Policy rejection and zero-call elapsed-budget tests pass.
- **Committed in:** `354e7beb`

**Total deviations:** 2 auto-fixed correctness/security issues.
**Impact on plan:** Both fixes strengthen the declared threat mitigations without expanding product scope.

## Issues Encountered

- The worktree initially lacked Phase 11 artifacts; the creator supplied four local planning refs, which were cherry-picked before execution.
- The repository-local `.venv` was absent, so the same pytest and Ruff gates ran with the available project Python environment.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The canonical tracer seams are ready for later Phase 11 plans to expand, but this branch intentionally contains no Plan 11-13 or later implementation.
- The three support artifacts remain uncommitted as requested and should not be included when merging this implementation.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-04*
