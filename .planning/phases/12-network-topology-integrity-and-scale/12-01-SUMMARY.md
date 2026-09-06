---
phase: 12-network-topology-integrity-and-scale
plan: 01
subsystem: network-security
tags: [scope-isolation, private-link, semantic-relationships, fastapi, mcp]

requires:
  - phase: 10-fabric-medallion-capability-expansion
    provides: normalized network inventory and semantic relationship inputs
provides:
  - exhaustive scope filtering across all 15 NetworkSnapshot collections
  - endpoint-filtered semantic relationship preservation for scoped services
  - one canonical scope enforcement seam across REST, agent, twin, and MCP relay consumers
  - provenance-independent, de-duplicated load-balancer relationship derivation
affects: [12-03, network-topology, policy-preview, operations-tools, operational-twin]

actuals:
  tokens: 7058
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - filter immutable snapshots once before deriving topology, gaps, and findings
    - retain semantic edges only when both endpoints survive authorization scoping
    - merge semantic and inventory relationships by stable relationship identity

key-files:
  created:
    - tests/test_network_downstream_scope.py
  modified:
    - src/network/service.py
    - src/network/topology.py
    - src/api/routers/network.py
    - tests/test_network_analysis.py
    - tests/test_api_network.py

key-decisions:
  - "NetworkIntelligenceService.scoped() is the sole scope enforcement point; analyze(scope) and _scoped_topology were removed."
  - "Semantic relationships are retained only when both endpoint IDs exist in the already-filtered snapshot."
  - "Load-balancer edges are always derived from inventory and de-duplicated against semantic edges by relationship identity."
  - "Plan 12-03 peer-resolution work moves from the removed _scoped_topology method to the surviving scoped()/TopologyBuilder seam."

patterns-established:
  - "Authorization before derivation: every downstream consumer receives an isolated service rather than filtering derived output."
  - "Provenance-independent graph completeness: semantic availability cannot suppress inventory-backed edges."

requirements-completed: [TOPO-01]

coverage:
  - id: D1
    description: Cross-subscription private-link resources and gaps are removed from scoped services.
    requirement: TOPO-01
    verification:
      - kind: unit
        ref: tests/test_network_analysis.py::TestScopeIsolation
        status: pass
    human_judgment: false
  - id: D2
    description: Policy preview and scoped network REST routes preserve authorization isolation and semantic context.
    requirement: TOPO-01
    verification:
      - kind: integration
        ref: tests/test_api_network.py::TestPolicy
        status: pass
    human_judgment: false
  - id: D3
    description: Agent, digital-twin, and MCP-relay paths inherit the canonical scope seam.
    requirement: TOPO-01
    verification:
      - kind: integration
        ref: tests/test_network_downstream_scope.py
        status: pass
    human_judgment: false
  - id: D4
    description: Scoped semantic provenance preserves complete, de-duplicated load-balancer edges.
    requirement: TOPO-01
    verification:
      - kind: unit
        ref: tests/test_network_downstream_scope.py::test_scoped_semantic_provenance_preserves_deduplicated_lb_edges
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 01: Scope-Isolation Security Gate Summary

**A single authorization boundary now filters every network snapshot collection and semantic edge before REST, agent, twin, or relay consumers derive topology and findings.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-09-05T01:41:27Z
- **Completed:** 2026-09-05T01:49:14Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Closed the confirmed cross-subscription Private Link disclosure by filtering `private_link_resources` with the same scope predicate as all other snapshot collections.
- Preserved only semantic relationships whose two endpoints remain in the filtered snapshot, eliminating the previous all-or-nothing relationship loss without reopening the authorization boundary.
- Removed `_scoped_topology` and the `analyze(scope)` compatibility path so `scoped()` is the sole enforcement seam used by network routes and downstream consumers.
- Forwarded scoped semantic provenance into policy preview and made load-balancer relationship derivation independent of whether semantic relationships are present.
- Added failing-first coverage for REST policy preview, all scoped network routes, Operations Copilot tools, digital-twin composition, MCP relay boundaries, and load-balancer edge integrity.

## Task Commits

Each TDD task was committed as a failing test followed by its implementation:

1. **Task 1 RED: Scope isolation regression coverage** - `5ee8c8cb` (test)
2. **Task 1 GREEN: Complete snapshot and relationship filtering** - `cd14fb5c` (fix)
3. **Task 2 RED: Scoped API and single-seam regressions** - `b4631a3d` (test)
4. **Task 2 GREEN: Preview forwarding and duplicate-scope removal** - `1707afd2` (fix)
5. **Task 3 RED: Downstream and load-balancer regressions** - `a9967e16` (test)
6. **Task 3 GREEN: Unconditional de-duplicated load-balancer derivation** - `44714b89` (fix)

## Files Created/Modified

- `src/network/service.py` - Filters all snapshot collections, scope-filters semantic endpoints, and exposes one canonical scoped service.
- `src/api/routers/network.py` - Carries scoped semantic relationships into policy preview.
- `src/network/topology.py` - Derives load-balancer edges regardless of semantic provenance and relies on stable identity de-duplication.
- `tests/test_network_analysis.py` - Failing-first service isolation and protected-target regressions.
- `tests/test_api_network.py` - Scoped policy preview and topology/gap/finding route regressions.
- `tests/test_network_downstream_scope.py` - Agent, twin, MCP relay, and load-balancer provenance coverage.

## Verification

- `.venv/bin/python -m pytest tests/test_network_analysis.py -k ScopeIsolation -x -q` — passed.
- `.venv/bin/python -m pytest tests/test_api_network.py tests/test_network_analysis.py -x -q` — passed.
- `.venv/bin/python -m pytest tests/test_network_downstream_scope.py tests/test_network_topology.py tests/test_network_analysis.py tests/test_api_network.py -x -q` — passed.
- Full plan-owned targeted suite across network analysis, API, topology, topology-link regression, downstream scope, twin API, and MCP tools — passed.
- `grep -R "_scoped_topology" -n src/` — no matches.
- Ruff on all touched Python files — passed.

The synthetic disclosure fixture now reports 3 scoped gaps instead of 10 estate-wide gaps, and scoped missing-private-endpoint gaps fall from 1 to 0. This is the expected authorization correction, not a regression.

## Decisions Made

- Endpoint membership in the filtered `NetworkSnapshot` is the authorization proof for retaining a semantic relationship. Both endpoints must survive.
- Policy preview reuses the already-scoped service snapshot and relationships rather than implementing a second filtering path.
- The dead `_scoped_topology` implementation was removed rather than repaired. Plan 12-03 must implement peer resolution at `scoped()`/`TopologyBuilder`, the surviving derivation seam.
- Inventory-backed load-balancer hosting, attachment, and backend edges are always emitted; matching semantic edges overwrite the same stable identity rather than creating duplicates.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated legacy tests from removed `analyze(scope)` API**
- **Found during:** Task 2 verification
- **Issue:** Existing `TestScoping` cases still called the deliberately removed `analyze(scope)` compatibility path.
- **Fix:** Updated those tests to call `service.scoped(scope).analyze()`, matching the single-enforcement-point contract.
- **Files modified:** `tests/test_network_analysis.py`
- **Verification:** Task 2's complete API and analysis suite passed.
- **Committed in:** `1707afd2`

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The adjustment was required by the planned public-surface removal and introduced no scope expansion.

## Issues Encountered

- The first load-balancer RED assertion compared only global relationship-type sets and passed unexpectedly because other resources already supplied the missing types. The test was strengthened before its RED commit to compare the exact load-balancer endpoint/type edge set; it then failed for the intended reason.
- The isolated worktree initially had no virtual environment. `uv sync --frozen --extra test` created `.venv` strictly from the committed lockfile so the plan's exact verification commands could run.

## Known Stubs

None. No new placeholders, TODOs, skipped tests, or unrun verification steps were introduced.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- TOPO-01 is green and the security gate is ready for later Phase 12 plans.
- Plan 12-03 can add peer resolution and identifier normalization at `NetworkIntelligenceService.scoped()` and `TopologyBuilder`; `_scoped_topology` no longer exists.
- No blockers remain for dependent topology completeness and scale work.

## Self-Check: PASSED

All six implementation/test commits resolve in git, all seven declared files
exist in the assigned worktree, the targeted verification suite passed, and
the summary is ready for its dedicated metadata commit.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
