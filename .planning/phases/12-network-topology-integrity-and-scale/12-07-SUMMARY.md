---
phase: 12-network-topology-integrity-and-scale
plan: 07
subsystem: network-topology
tags: [topology-detail, pagination, truncation, drill-down, agent-tools, tdd]
requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 01
    provides: canonical scoped NetworkIntelligenceService security boundary
  - phase: 12-network-topology-integrity-and-scale
    plan: 02
    provides: G-1 through G-4 fixtures, constants, and compatibility artifact
  - phase: 12-network-topology-integrity-and-scale
    plan: 06
    provides: complete private-link topology projection
provides:
  - additive summary/full topology detail contract with byte-identical full default
  - bounded lean summary projection and scoped paginated detail drill-down
  - honest coverage and pagination for gaps and rule findings
  - affected-resource attribution and bounded-agent disclosure
affects: [12-08, 12-09, 12-10, 12-11, network-api, operations-tools]
actuals:
  tokens: 12059
  tasks: 3
  commits: 8
tech-stack:
  added: []
  patterns:
    - additive Literal detail contract with unchanged full default
    - coverage triples drive automatic envelope truncation warnings
    - scoped service resolution precedes drill-down lookup
    - TDD RED and GREEN commits per task
key-files:
  created:
    - tests/test_operations_tools.py
  modified:
    - src/network/topology.py
    - src/api/routers/network.py
    - src/network/tightening.py
    - src/operations/tools.py
    - tests/test_network_scale.py
    - tests/test_api_network.py
    - tests/test_network_topology.py
    - tests/network_baseline.py
    - tests/test_network_prephase_baseline.py
    - .planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json
key-decisions:
  - "TopologyDetail is exactly Literal['summary', 'full']; full remains the API default."
  - "Summary omits unattached leaf NICs in addition to rule-level nodes so Plan 12-02's post-research filler does not consume the useful topology budget."
  - "The drill-down route resolves only against the already-scoped service and returns an empty covered page for an out-of-scope resource."
  - "Agent bound tuning remains unchanged at 25; only truthful disclosure was added."
requirements-completed: [TOPO-03]
coverage:
  - id: D1
    description: Default full topology is byte-identical while summary is lean and bounded by measured node and byte ceilings.
    requirement: TOPO-03
    verification:
      - kind: unit
        ref: tests/test_network_scale.py#test_g4_default_detail_is_byte_identical_to_the_pre_change_contract
        status: pass
      - kind: performance
        ref: tests/test_network_scale.py#test_g1_small_summary_payload_budget
        status: pass
      - kind: performance
        ref: tests/test_network_scale.py#test_g2_enterprise_summary_payload_budget
        status: pass
    human_judgment: false
  - id: D2
    description: Withheld rules, routes, and rule collections are paginated and scope-enforced through the topology drill-down route.
    requirement: TOPO-03
    verification:
      - kind: integration
        ref: tests/test_api_network.py#TestTopology
        status: pass
    human_judgment: false
  - id: D3
    description: Gaps and rule findings carry additive coverage and pagination with meaningful truncation warnings.
    requirement: TOPO-03
    verification:
      - kind: integration
        ref: tests/test_api_network.py#TestGaps
        status: pass
      - kind: integration
        ref: tests/test_api_network.py#TestRuleFindings
        status: pass
    human_judgment: false
  - id: D4
    description: Findings identify affected resources and agent lists disclose their 25-item bound and true totals.
    requirement: TOPO-03
    verification:
      - kind: unit
        ref: tests/test_network_topology.py#TestRuleFindingAffectedResources
        status: pass
      - kind: integration
        ref: tests/test_operations_tools.py
        status: pass
      - kind: integration
        ref: tests/test_network_downstream_scope.py
        status: pass
    human_judgment: false
duration: 15 min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 07: Bounded and Honest Topology Contracts Summary

**An additive `summary`/`full` topology contract now preserves the historical default byte-for-byte while bounding enterprise responses, exposing scoped paginated drill-down, reporting collection coverage honestly, and disclosing agent truncation.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-09-05T16:55:23Z
- **Completed:** 2026-09-05T17:10:34Z
- **Tasks:** 3
- **Implementation/test commits:** 7
- **Files changed before this summary:** 11

## Accomplishments

- Added the exact public detail enum `TopologyDetail = Literal["summary", "full"]`; `GET /api/v1/network/topology` defaults to `full`, and no-parameter output remains byte-identical to explicit full detail.
- Added lean summary projection that omits `NetworkSecurityRule`, `Route`, and `FirewallRule` nodes; strips embedded list/dict detail collections; applies node and serialized-byte ceilings; reports coverage; and computes `_topology_resources` once per response.
- Added scope-enforced `GET /api/v1/network/topology/resources/{resource_id:path}/details` with the existing `offset`/`limit` dependency. Its data contract is `resource_id`, `detail_type`, `items`, and `coverage`.
- Added the exact coverage keys `total`, `returned`, and `truncated` to gaps, rule findings, topology summary, and drill-down pages, preserving all previous keys and types.
- Added `RuleFinding.affected_resource_ids` as an optional tuple serialized as `affected_resource_ids: string[]`, populated from NSG subnet/NIC associations and firewall collection network associations.
- Added G-6 coverage solely in `tests/test_operations_tools.py`; truncated network-agent lists state the unchanged bound of 25 and each true total, while complete lists stay silent.

## Public Contract

| Surface | Exact contract |
|---|---|
| Detail enum | `TopologyDetail = Literal["summary", "full"]` |
| API default | `detail="full"` |
| Coverage | `{"total": int, "returned": int, "truncated": bool}` |
| Drill-down route | `GET /api/v1/network/topology/resources/{resource_id:path}/details` |
| Drill-down pagination | Existing `offset` and `limit` dependency, maximum 500 |
| Finding attribution | `affected_resource_ids` |
| Agent gate module | `tests/test_operations_tools.py` |

## Measured Gates

| Gate | Measured value | Result |
|---|---|---|
| G-1 | Small summary: **151 nodes**, **247,717 bytes**; coverage 151 returned of 190 total, truncated | PASS — ≤ `G1_NODE_CAP` 200 and ≤ `G1_BYTE_CEILING` 250,000 |
| G-2 | Enterprise summary: **1,481 nodes**, **1,998,030 bytes**; coverage 1,481 returned of 3,100 total, truncated | PASS — ≤ `G2_NODE_CAP` 1,500 and ≤ `G2_BYTE_CEILING` 2,000,000 |
| G-3 | Enterprise `build_topology`: **0.005392250000113563 s** | PASS — < 1.0 s |
| G-4 | Default equals explicit full: **true**; canonical **111,155 bytes**, SHA-256 `86d8d899a856e64b9aca1974471e6cf8eee4d4abc2dbad02b26930a6a0091440` | PASS |
| G-5 | Gaps coverage **1/5 truncated**; rule findings coverage **1/14 truncated**; both emitted automatic and shown-versus-total warnings | PASS |
| G-6 | Agent returned **25/30 gaps** and **25/40 rule findings** with `Agent result bound 25...` | PASS |

## Task Commits

1. **Task 1 RED — detail, budget, drill-down, and projection tests:** `d81cf8f6`
2. **Task 1 GREEN — bounded topology detail contract:** `a2b44bd7`
3. **Task 2 RED — gaps/findings coverage and pagination tests:** `c97e2a17`
4. **Task 2 GREEN — honest analysis coverage and warnings:** `817fc3a7`
5. **Task 3 RED — affected-resource and dedicated agent tests:** `a7b29ce5`
6. **Task 3 GREEN — finding attribution and bound disclosure:** `150a81c9`
7. **Verification fix — register additive compatibility fields:** `8c390b21`

## Verification

- Task 1 exact suite — **102 passed**.
- Task 2 filtered API suite — **14 passed**.
- Task 3 exact suite — **101 passed**.
- Plan-targeted backend suite — **172 passed**.
- Full backend per-wave gate — **2,678 passed, 33 skipped**; all skips are pre-existing and none occur in Plan 12-07-owned tests.
- Ruff across all Plan 12-07 Python files — **passed**.
- Required trailer check across all seven implementation/test commits — **passed**.
- `STATE.md` and `ROADMAP.md` diff from the worktree base — **empty**, as required for parallel execution.

## Scope Security

- The drill-down handler calls `_service(context, scope)` before looking up any resource, preserving Plan 12-01's single authorization boundary.
- An out-of-scope resource identifier returns an empty page with zero coverage and exposes no detail.
- `tests/test_network_downstream_scope.py` remains green, including agent, twin, relay, and scoped topology regressions.

## Decisions Made

- Kept the server default at `full`; later web work must request `summary` explicitly.
- Used a byte-aware stable-prefix cap after node capping. The byte ceiling remains authoritative when long ARM identifiers or relationships make 1,500 nodes exceed 2 MB.
- Omitted leaf NICs with neither an attached resource nor an NSG from summary detail. They remain available in full detail, and summary coverage reports their omission.
- Kept `affected_resource_ids` optional with an empty tuple default so legacy model payloads still construct without changes.
- Kept `_MAX_ITEMS = 25`; this plan changes disclosure, not policy tuning.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected stale natural-summary assumptions after the Plan 12-02 fixture rebalance**
- **Found during:** Task 1 GREEN verification
- **Issue:** The research-era natural summary counts assumed rule-heavy fixtures. Plan 12-02 later replaced expensive firewall filler with 5,860 real leaf NICs at enterprise size, making the uncapped summary 8,960 nodes and the small summary 266 nodes.
- **Fix:** Summary detail now omits leaf NICs with neither an attached workload nor NSG and then enforces the named node and byte ceilings. The stale exact-total assertion was replaced with the contract-relevant `total > G2_NODE_CAP` assertion.
- **Files modified:** `src/network/topology.py`, `tests/test_network_scale.py`
- **Verification:** G-1 measured 151 nodes/247,717 bytes; G-2 measured 1,481 nodes/1,998,030 bytes.
- **Commit:** `a2b44bd7`

**2. [Rule 3 - Blocking] Extended the fail-closed pre-phase baseline normalizer for planned additive fields**
- **Found during:** Full backend per-wave verification
- **Issue:** The G-4 replay correctly rejected new `coverage` and `affected_resource_ids` fields because the additive-key registry did not yet name Plan 12-07 and could not traverse list items.
- **Fix:** Added wildcard list traversal and registered only the three Plan 12-07 additive paths while retaining exact comparison of every legacy field and representative item key.
- **Files modified:** `tests/network_baseline.py`, `tests/test_network_prephase_baseline.py`, `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json`
- **Verification:** Baseline suite 4 passed; full backend gate 2,678 passed and 33 pre-existing skips.
- **Commit:** `8c390b21`

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking issue).
**Impact:** Both changes were required to enforce the planned measured budgets and additive compatibility contract; neither widens scope or changes the default response.

## Known Stubs

None. No placeholders, TODOs, FIXMEs, skipped owned tests, or unrun verification steps were introduced.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-09 can request `detail=summary`, consume the `coverage` triple, and call the exact drill-down route.
- Plan 12-11 can rerun `tests/test_operations_tools.py` verbatim as G-6 and use the registered additive baseline paths for G-4.
- No blocker remains for plans 12-08 through 12-11.

## Self-Check: PASSED

All declared source/test files exist in the assigned worktree, all seven task/fix commits resolve and carry the required co-author trailer, the exact 172-test targeted suite and 2,711-test full collection completed with 2,678 passes plus 33 pre-existing skips, G-1 through G-6 were measured from the committed code, and `STATE.md`/`ROADMAP.md` remain unchanged.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
