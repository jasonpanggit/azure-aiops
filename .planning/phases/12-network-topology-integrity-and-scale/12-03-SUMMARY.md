---
phase: 12-network-topology-integrity-and-scale
plan: 03
subsystem: network-topology
tags: [arm-id-normalization, topology-diagnostics, freshness, dns, flow-provenance, scope-isolation]

requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 01
    provides: canonical scoped service boundary and endpoint-filtered semantic relationships
  - phase: 12-network-topology-integrity-and-scale
    plan: 02
    provides: deterministic scale fixtures and detached pre-phase compatibility baseline
provides:
  - case-stable topology relationship projection with typed, identifier-safe drop counts
  - snapshot-backed freshness, resolvesFor DNS projection, and three-state flow-log provenance
  - scoped unresolved-peer reasons with the legacy peer-id contract preserved
  - additive-key-aware comparison against the immutable pre-phase response baseline
affects: [12-07, 12-08, 12-09, 12-10, 12-11, network-topology, downstream-contracts]

actuals:
  tokens: 13893
  tasks: 3
  commits: 8

tech-stack:
  added: []
  patterns:
    - normalize externally sourced ARM identifiers at model and service boundaries
    - report relationship loss by predicate and count without returning missing identifiers
    - derive scoped peer state only from the retained snapshot and its unscoped source
    - compare frozen responses after removing only explicitly registered additive fields

key-files:
  created:
    - .planning/phases/12-network-topology-integrity-and-scale/12-03-SUMMARY.md
  modified:
    - src/network/models.py
    - src/network/topology.py
    - src/network/loader.py
    - src/network/service.py
    - src/api/runtime.py
    - src/onboarding/graph_normalize.py
    - tests/test_network_topology_links_regression.py
    - tests/test_network_topology.py
    - tests/network_scale_fixtures.py
    - tests/network_baseline.py
    - tests/test_network_prephase_baseline.py
    - .planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json

key-decisions:
  - "C-10 peer-resolution derivation lives at NetworkIntelligenceService.scoped()/TopologyBuilder because Plan 12-01 removed the duplicate _scoped_topology seam."
  - "The legacy unresolved_peer_vnet_ids field remains unchanged; unresolved_peers is strictly additive."
  - "The detached pre-phase response body remains immutable; Plan 12-03 fields are registered and removed only for compatibility comparison."

patterns-established:
  - "Case normalization precedes graph membership checks, and emitted relationship endpoints use canonical casefolded IDs."
  - "Topology diagnostics expose relationship type and integer count only, never an absent ARM identifier."
  - "Flow provenance has three explicit states: not_ingested, ingested_not_analyzed, and analyzed."

requirements-completed: [TOPO-05, TOPO-01]

coverage:
  - id: D1
    description: Mixed-case subnet, private-endpoint, and semantic references survive topology projection while dropped edges are counted safely.
    requirement: TOPO-05
    verification:
      - kind: unit
        ref: tests/test_network_topology_links_regression.py
        status: pass
    human_judgment: false
  - id: D2
    description: Snapshot-level observation time produces real freshness and valid resolvesFor DNS edges while parentless links are rejected.
    requirement: TOPO-05
    verification:
      - kind: integration
        ref: tests/test_network_topology_links_regression.py
        status: pass
    human_judgment: false
  - id: D3
    description: Flow observations reach the analyzer and topology provenance distinguishes all three ingestion and analysis states.
    requirement: TOPO-05
    verification:
      - kind: unit
        ref: tests/test_network_topology_links_regression.py::test_flow_observations_are_forwarded_and_provenance_is_three_state
        status: pass
    human_judgment: false
  - id: D4
    description: Scoped peers distinguish excluded-by-scope from never-ingested without removing the legacy unresolved ID list.
    requirement: TOPO-01
    verification:
      - kind: unit
        ref: tests/test_network_topology.py::TestPeerResolution
        status: pass
    human_judgment: false
  - id: D5
    description: Plan 12-01 downstream scope isolation remains unchanged and green.
    requirement: TOPO-01
    verification:
      - kind: integration
        ref: tests/test_network_downstream_scope.py
        status: pass
    human_judgment: false

duration: 24min active across implementation and closeout
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 03: Network Topology Integrity and Diagnostics Summary

**Case-stable topology projection now preserves valid edges, counts safely dropped relationships, carries honest freshness and flow provenance, and explains unresolved peers without weakening scope isolation.**

## Performance

- **Duration:** 24 minutes active across the original implementation and continuation closeout
- **Implementation window:** 2026-09-05T02:06:05Z to 2026-09-05T02:14:57Z
- **Closeout resumed:** 2026-09-05T13:08:29Z
- **Completed:** 2026-09-05
- **Tasks:** 3
- **Files modified:** 13, including this summary
- **Commits:** 8, including this summary commit

## Accomplishments

- Normalized private-endpoint and semantic relationship ARM IDs, made resource-membership checks case-stable, and exposed typed `dropped_relationships` counts with identifier-safe warnings.
- Threaded snapshot observation time through the loader, projected ontology `resolvesFor` relationships, suppressed parentless DNS links with a warning, and replaced constant flow-log claims with three-state data-derived provenance.
- Added an additive `unresolved_peers` contract that distinguishes `excluded_by_scope` from `not_ingested` while retaining `unresolved_peer_vnet_ids` byte-for-byte for existing consumers.
- Preserved the detached pre-phase response body by registering the three additive Plan 12-03 fields and canonicalizing only those fields during baseline replay.

## Measured Relationship Changes

### Casefold edge-count delta

The authoritative mixed-case subnet fixture was replayed at the pre-change commit and at the completed implementation:

| Measurement | Before | After | Delta |
|---|---:|---:|---:|
| Total relationships | 1,336 | 1,337 | **+1** |
| `hosts` relationships | 78 | 79 | **+1** |

This fixture removes the endpoint-side subnet reference so the subnet's mixed-case `private_endpoint_ids` value is the sole source of the edge. The ordinary complete mixed-case estate remained 1,414 relationships before and after because its endpoint-side derivation already emitted the same relationship and stable identity de-duplicated it.

### First observed `dropped_relationships` values

- Fully consistent fixture: `{}`
- First deliberate dangling-endpoint fixture: `{"hosts": 1}`
- First warning: `1 topology relationships dropped because an endpoint was absent from this scope (hosts=1)`
- Missing endpoint identifier disclosed by warning: **false**

## Task Commits

Each TDD task was committed as a RED test followed by its GREEN implementation:

1. **Task 1 RED: Topology integrity regressions** — `b061745f`
2. **Task 1 GREEN: Preserve and diagnose topology relationships** — `0d41d7e3`
3. **Task 2 RED: Freshness, DNS, and flow provenance regressions** — `ea921bf8`
4. **Task 2 GREEN: Truthful freshness, DNS, and flow provenance** — `2883590f`
5. **Task 3 RED: Peer-resolution contract regressions** — `eafdb54a`
6. **Task 3 GREEN: Explain unresolved peer scope state** — `8627128b`
7. **Closeout fix: Preserve detached compatibility baseline** — `1712d808`

All seven existing commits carry the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer.

## Files Created/Modified

- `src/network/models.py` — normalizes every subnet private-endpoint reference.
- `src/network/topology.py` — case-stable endpoint checks, drop diagnostics, flow provenance, `resolvesFor`, and peer-resolution projection.
- `src/network/loader.py` — accepts snapshot-level `observed_at` fallback.
- `src/network/service.py` — canonicalizes semantic endpoints, forwards flow observations, and derives scoped peer state.
- `src/api/runtime.py` — retains ontology freshness when constructing the network service.
- `src/onboarding/graph_normalize.py` — warns and suppresses a virtual-network link whose parent DNS zone is absent.
- `tests/test_network_topology_links_regression.py` — mixed-case, drop-count, freshness, DNS, and flow-provenance regressions.
- `tests/test_network_topology.py` — closed peer-resolution vocabulary and scope behavior.
- `tests/network_scale_fixtures.py` — opt-in mixed-case endpoint references without mutating the frozen G-4 fixture.
- `tests/network_baseline.py` — fail-closed removal of explicitly registered additive keys for baseline comparison.
- `tests/test_network_prephase_baseline.py` — validates post-change responses against immutable pre-phase bytes modulo the declared additions.
- `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json` — registers the three additive topology fields introduced by Plan 12-03.

## Verification

- Plan-level network suite:
  `.venv/bin/python -m pytest -o addopts='' tests/test_network_topology_links_regression.py tests/test_network_topology.py tests/test_network_analysis.py tests/test_network_ontology.py tests/test_network_flow.py tests/test_api_network.py -q`
  — **186 passed**, 1 warning, 6.30s.
- Full backend suite:
  `.venv/bin/python -m pytest -o addopts='' -q`
  — **2,650 passed, 35 skipped**, 9 warnings, 96.45s.
- Unchanged Plan 12-01 security gate:
  `.venv/bin/python -m pytest -o addopts='' tests/test_network_downstream_scope.py -q`
  — **4 passed**, 3 warnings, 1.08s.
- `tests/test_network_downstream_scope.py` has no diff from the Plan 12-03 base.
- Ruff over all closeout-fix Python files — **passed**.
- All warnings are existing FastAPI/Starlette deprecation warnings; no test failed or errored.

## Decisions Made

- **C-10 derivation-site deviation:** `12-UI-SPEC.md` named `_scoped_topology`, but Plan 12-01 deliberately removed that duplicate enforcement point. Peer resolution is therefore derived at the surviving `NetworkIntelligenceService.scoped()` boundary and passed into `TopologyBuilder`. This preserves the UI contract's intent and locked decision 1 while avoiding a second authorization seam.
- `observed` remains in the closed peer-resolution vocabulary for contract completeness, but resolved peers are represented as real VNet resources rather than as entries in `unresolved_peers`.
- Compatibility replay strips only artifact-registered additive paths; it does not rewrite the detached pre-phase body or relax comparisons for existing fields.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Kept the opt-in mixed-case relationship fixture out of the frozen default estate**
- **Found during:** Full backend verification.
- **Issue:** Task 1's fixture change populated `private_endpoint_ids` for every estate, changing two resource details in the frozen G-4 default response.
- **Fix:** Restricted those authoritative subnet references to `mixed_case_ids=True`, the mode that owns the regression.
- **Files modified:** `tests/network_scale_fixtures.py`
- **Verification:** Baseline/topology suite passed; the complete backend suite passed.
- **Committed in:** `1712d808`

**2. [Rule 3 - Blocking] Made the detached baseline gate recognize declared additive topology fields**
- **Found during:** Full backend verification.
- **Issue:** The pre-phase self-consistency test compared current response bytes directly even though Plan 12-03 intentionally added `counts.dropped_relationships`, `flow_log_provenance`, and `unresolved_peers`.
- **Fix:** Registered those exact paths with introducing plan `12-03` and added fail-closed canonicalization that removes only registered fields before comparing against immutable pre-phase bytes.
- **Files modified:** `tests/network_baseline.py`, `tests/test_network_prephase_baseline.py`, `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json`
- **Verification:** The baseline test and full backend suite passed.
- **Committed in:** `1712d808`

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking issue).
**Impact on plan:** Both fixes preserve the frozen compatibility evidence and constrain the new regression fixture; no production scope was added.

## TDD Gate Compliance

- Task 1: RED `b061745f` precedes GREEN `0d41d7e3`.
- Task 2: RED `ea921bf8` precedes GREEN `2883590f`.
- Task 3: RED `eafdb54a` precedes GREEN `8627128b`.

## Threat Model Verification

- Drop diagnostics return relationship type and count only; the deliberate secret-like ARM identifier was not present in the warning.
- Peer resolution emits only an ID already referenced by an in-scope peering and a closed resolution selector; no unscoped properties are projected.
- Snapshot freshness and flow provenance are data-derived rather than asserted constants.
- Parentless DNS relationships are rejected rather than projected as dangling edges.
- No unplanned endpoint, authentication path, file-access boundary, or schema trust boundary was introduced.

## Known Stubs

None. The word “placeholder” appears only in an existing docstring describing intentionally materialized topology context nodes; no placeholder values, TODOs, FIXMEs, skipped tests, or unwired data sources were introduced by this plan.

## Issues Encountered

- The first full backend run exposed the pre-phase compatibility failure described above. After the atomic fix, the entire backend suite passed.
- Existing FastAPI and Starlette deprecation warnings remain out of scope and do not affect verification.

## User Setup Required

None.

## Next Phase Readiness

- Plans 12-07 through 12-10 can consume typed drop diagnostics, flow provenance, and peer-resolution fields.
- Plan 12-11 can enforce default-path compatibility using the artifact's explicit additive-key registry.
- No blocker remains, and the Plan 12-01 scope-isolation gate is unchanged and green.

## Self-Check: PASSED

- All seven pre-summary Plan 12-03 commits resolve in git and carry the required co-author trailer.
- All declared source, test, and baseline files exist in the assigned isolated worktree.
- The plan-level suite, full backend suite, and unchanged Plan 12-01 security gate all pass with the exact counts recorded above.
- `tests/test_network_downstream_scope.py` is unchanged from the Plan 12-03 base.
- No generated or temporary files remain untracked.
- `STATE.md` and `ROADMAP.md` were not modified, as explicitly requested.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
