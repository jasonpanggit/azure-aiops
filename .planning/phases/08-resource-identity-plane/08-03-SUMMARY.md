---
phase: 08-resource-identity-plane
plan: 03
subsystem: hermes-viability-decision
tags: [comparison-harness, d-09-gate, architecture-decision, hermes-removal]

requires:
  - phase: 08-resource-identity-plane
    provides: "InventoryReadPort equivalence proof (08-01), fabric_pipelines topology derivation + shared fixture (08-02)"
provides:
  - "fabric_pipelines/comparison_report.py: ArmResult/ComparisonReport/compare()/bfs_impact() -- reusable five-dimension (D-04) comparison harness reducing both arms to a uniform bounded-BFS traversal"
  - "tests/test_hermes_fabric_comparison.py: shared-fixture comparison test suite (correctness parity, D-05 explicit-state parity, dangling-edge drop parity)"
  - ".planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md: reproducible, harness-generated comparison report"
  - "Operator-approved D-09 decision: REMOVE Hermes entirely"
affects: []

actuals:
  tokens: 21000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Neither arm's native top-level API (SemanticEngine.get_impact_context()) was used directly as the comparison surface, because its cause_type branches don't cover network-topology roots -- both arms were instead reduced to a uniform bounded BFS over their own relationship/edge index, which both natively support"
    - "A real behavioral divergence (derive_edges() doesn't filter dangling/unemitted-endpoint edges the way Normalizer.normalize() does) was resolved at the harness level (filter_dangling_edges applied symmetrically to both arms) rather than by modifying topology_pipeline.py, since that file was not in this plan's files_modified scope"

key-files:
  created:
    - src/fabric_pipelines/comparison_report.py
    - tests/test_hermes_fabric_comparison.py
    - .planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md
  modified: []

key-decisions:
  - "D-09 architecture gate (operator-approved): REMOVE Hermes entirely. The comparison report showed full parity (correctness, evidence-link presence, authorization/scope) plus a Fabric-native latency advantage on the one shared network-topology blast-radius scenario measured. The operator explicitly acknowledged that Hermes's application/business-service traversal surface (SemanticEngine.get_impact_context()'s PatchAssessment/Application cause_type branches) was NOT exercised by this comparison and is not proven redundant by it -- and chose full removal anyway as a conscious tradeoff in favor of committing to the stated phase-8 hypothesis ('Hermes removal is now the default hypothesis of phase 8')."
  - "Per the plan's explicit Task 3 'remove' branch instructions: no code was deleted in this task. Hermes's modules (src/hermes_arg_connector/*, including the resources/resource_containers QuerySpecs in queries.py and the identity_source flag in config.py) remain untouched. Full removal is scoped as an explicit follow-up item below, not performed speculatively in this plan."
  - "The untested application/business-service traversal gap (get_impact_context()'s PatchAssessment/Application/ASSET_TYPES branches) is recorded here as a known unverified assumption underlying the removal decision, per the operator's explicit instruction not to silently drop this caveat."

requirements-completed: [INV-07, INV-08, INV-10, INV-11, INV-12]

status: complete

coverage:
  - id: D1
    description: "One bounded blast-radius scenario runs against both SemanticEngine's underlying Normalizer engine and the Fabric-native topology_pipeline query surface, using the identical curated snapshot, producing a reproducible five-dimension comparison report"
    requirement: "INV-07"
    verification:
      - kind: unit
        ref: "tests/test_hermes_fabric_comparison.py::test_shared_scenario_comparable_impact_both_arms"
        status: pass
      - kind: artifact
        ref: ".planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unknown/stale/conflicting/unauthorized edges remain explicit (not silently dropped or falsely confident) in both arms"
    requirement: "INV-11"
    verification:
      - kind: unit
        ref: "tests/test_hermes_fabric_comparison.py::test_non_accepted_edge_state_stays_explicit_in_both_arms"
        status: pass
    human_judgment: false
  - id: D3
    description: "An edge whose endpoint is missing from the emitted entity set is dropped consistently by both arms, not silently kept in one arm only"
    requirement: "INV-08"
    verification:
      - kind: unit
        ref: "tests/test_hermes_fabric_comparison.py::test_dangling_edge_dropped_consistently_by_both_arms"
        status: pass
    human_judgment: false
  - id: D4
    description: "D-09 architecture gate: operator makes an explicit retain/reduce/remove decision, not inferred or defaulted by the planner/executor"
    requirement: "INV-12"
    verification:
      - kind: manual
        ref: "Operator selected 'remove' via the orchestrator checkpoint response (2026-08-27)"
        status: pass
    human_judgment: true
  - id: D5
    description: "Hermes's duplicate ARG identity queries are removed only if the equivalence proof (08-01) and comparison (this plan) both passed, and per the 'remove' branch's explicit instruction, no code is deleted in this task -- a scoped follow-up removal plan is documented instead"
    requirement: "INV-10"
    verification:
      - kind: unit
        ref: "pytest tests/inventory_harness.py tests/test_impact_analysis.py tests/test_network_normalize_from_inventory.py -x -q (all pass, unchanged -- no code touched)"
        status: pass
    human_judgment: false
---

# Phase 8 Plan 3: Hermes vs. Fabric-Native Comparison and Removal Gate Summary

**One-liner:** Built a shared-fixture, five-dimension comparison harness between Hermes's `Normalizer` engine and the Fabric-native `topology_pipeline`, found full correctness/evidence/authorization parity plus a Fabric-native latency edge on the one network-topology scenario measured, and the operator approved full removal of Hermes at the D-09 gate — with the untested application/business-service traversal gap explicitly flagged as a known, accepted risk rather than silently assumed away.

## What Was Built

### Task 1: Comparison harness (`tests/test_hermes_fabric_comparison.py`, `src/fabric_pipelines/comparison_report.py`)

`comparison_report.py` defines `ArmResult`/`ComparisonReport`/`compare()`/`bfs_impact()`. Both arms
are reduced to a uniform interface before comparison: `SemanticEngine.get_impact_context()`'s native
`cause_type` branches (`PatchAssessment`/`Subscription`/`Application`/`ASSET_TYPES`) don't cover
network-topology entity types (VNet/Subnet/NSG) — a network root would fall into its
`else: resources = set()` branch and report a near-empty blast radius regardless of graph richness.
Instead, both arms are reduced to a bounded BFS over their own relationship/edge index starting from
the same root — the one traversal capability both `Normalizer.normalize()`'s
`NormalizedGraph.relationships` and `derive_edges()`'s edge dict actually support identically. This
divergence from the plan's literal API name is documented in the module docstring, not silently
worked around.

Three tests (TDD RED→GREEN, tracer task):
1. Shared NSG-rooted scenario produces a matching impacted-entity set from both arms.
2. A deliberately-injected `"conflicting"` assertion-state edge survives explicitly in both arms'
   output (D-05).
3. An edge with an unemitted endpoint (the fixture's `belongsTo` edges to a never-emitted
   resource-group container) is dropped consistently by both arms once passed through the harness's
   shared `filter_dangling_edges()` — this test also captures and asserts the raw-output divergence
   discovered: `derive_edges()` does NOT drop these internally (unlike `Normalizer.normalize()`,
   which already filters via its `known_entity_ids` check at `normalize.py:218-234`), resolved at the
   harness level rather than by modifying `topology_pipeline.py` (out of this plan's declared scope).

### Task 2: Comparison report (`.planning/phases/08-resource-identity-plane/08-COMPARISON-REPORT.md`)

Generated by actually running the Task 1 harness against the shared fixture (not hand-authored). Covers
all five D-04 dimensions: correctness (parity), evidence-link presence (parity), authorization/scope
(parity), latency (Fabric-native faster in this single-run measurement — Hermes's `Normalizer.normalize()`
processes all ~15 ARG entity families regardless of what's populated, `derive_edges()` only processes
network-shaped input), operational cost (documented proxy — query-count/edge-count, explicitly labeled
as equal-by-construction and inconclusive from a fixture-only harness, never silently omitted). Also
documents the D-05 dangling-edge divergence and its harness-level resolution, and explicitly flags that
this comparison did not exercise Hermes's application/business-service traversal surface.

### Task 3 (checkpoint:decision): D-09 architecture gate

Presented to the operator via the orchestrator with the full measured comparison data (not the plan's
pre-written "retain" pros text, which didn't match what was actually measured — parity/Fabric-favored
on every dimension tested within scope). Operator selected **remove**, explicitly acknowledging the
untested application/business-service traversal gap as an accepted risk in favor of committing to the
stated phase-8 hypothesis.

### Task 4 (plan's "Task 3", auto): Execute the "remove" branch

Per the plan's explicit instruction for the "remove" outcome: **no code was deleted in this task.**
Full removal of Hermes's identity acquisition path is a larger cross-cutting change with its own blast
radius and is recorded here as a scoped follow-up, not performed speculatively. Verification suite
(`tests/inventory_harness.py`, `tests/test_impact_analysis.py`,
`tests/test_network_normalize_from_inventory.py`) re-run and confirmed passing unchanged, since no
code was touched — this confirms the pre-existing equivalence proof (08-01) and this plan's
comparison both still hold as of this decision.

## Follow-up: Scoped Hermes Removal (not performed in this plan)

Per the operator's "remove" decision, a future phase/plan should:
1. Flip `ConnectorConfig.identity_source` default from `"arg"` to `"inventory"` in
   `src/hermes_arg_connector/config.py`.
2. Remove the `"resources"`/`"resource_containers"` `QuerySpec` entries from
   `QueryCatalog.build()` in `src/hermes_arg_connector/queries.py`.
3. Given "remove" (not "reduce") was chosen, plan the full decommission of
   `src/hermes_arg_connector/*` (source acquisition, normalization ownership, inventory
   publication, "discovery agent" branding) and its `SemanticEngine`/`semantic_indexes`
   dependents — this is a larger cross-cutting change requiring its own dependency/impact
   analysis, not appropriate to perform inline here.
4. **Before or during that removal work**, explicitly re-verify (or consciously accept as a
   documented risk) that Hermes's application/business-service dependency-traversal capability
   (`get_impact_context()`'s `PatchAssessment`/`Application`/`ASSET_TYPES` branches) has either
   (a) a Fabric-native equivalent built, or (b) is confirmed genuinely unused/non-critical by the
   operator — since this comparison did not measure that surface at all, and the operator's
   "remove" decision was made with this gap explicitly disclosed and accepted, not resolved.
5. Patch/vulnerability/policy/advisor/cost/role ARG specs are explicitly out of scope for this
   removal (per INV-12) and must remain untouched.

## Deviations from Plan

### Auto-fixed / clarified during execution (no Rule 1-3 code bugs found)

**1. [Design clarification, not a deviation from files_modified] Comparison surface is BFS-based, not a direct `get_impact_context()` call**
- **Found during:** Task 1 design
- **Issue:** The plan's `<behavior>` names `SemanticEngine.from_rows(**scenario).get_impact_context(root_id)` explicitly, but that API's `cause_type` branching has no path for network-topology entity types (VNet/Subnet/NSG) — calling it directly on the shared fixture's NSG root would always yield a near-empty blast radius regardless of the underlying graph, making it an unfair/uninformative comparison point.
- **Resolution:** Comparison is instead built on a bounded BFS over each arm's own relationship/edge index (their one shared, natively-supported traversal primitive), documented explicitly in the module docstring and report rather than silently substituted. `SemanticEngine.get_impact_context()`'s actual cause_type gap for network entities is called out as a real, disclosed API limitation, not hidden.
- **Files:** `src/fabric_pipelines/comparison_report.py`, `tests/test_hermes_fabric_comparison.py`
- **Commit:** `63569f9`

**2. [Rule-1-adjacent, resolved without modifying out-of-scope file] `derive_edges()` doesn't filter dangling edges**
- **Found during:** Task 1 (Test 3)
- **Issue:** `fabric_pipelines.topology_pipeline.derive_edges()` returns `belongsTo` edges to a never-emitted resource-group container (dangling), while Hermes's `Normalizer.normalize()` already filters these internally. `topology_pipeline.py` is not in this plan's declared `files_modified`, so it was not modified directly.
- **Fix:** Comparison harness (`filter_dangling_edges()`) applies the same "drop unemitted-endpoint edges" rule symmetrically to both arms' raw output before comparing, and the test explicitly asserts the raw-output divergence (documenting it, not hiding it) before confirming both arms converge to the same dangling-edge-free state post-filter.
- **Files:** `src/fabric_pipelines/comparison_report.py`, `tests/test_hermes_fabric_comparison.py`
- **Commit:** `63569f9`
- **Flagged as follow-up:** `derive_edges()` itself should likely gain the same internal filter, for any consumer that doesn't route through this comparison harness. Recorded in `08-COMPARISON-REPORT.md` and the Follow-up section above.

No Rule 1-4 bugs, missing-critical-functionality gaps, blocking issues, or architectural-change triggers were found beyond the above two design clarifications.

### Auth gates

None encountered.

## Known Stubs

None. No hardcoded empty values, placeholder text, or unwired data sources introduced.

## Threat Flags

None beyond the plan's own registered T-08-07/T-08-08 threats, both mitigated as designed (report generated programmatically from the actual test run; removal strictly gated behind equivalence proof + operator approval, and in this plan no removal code was executed at all).
