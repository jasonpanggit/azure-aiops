---
phase: 10-fabric-medallion-capability-expansion
plan: 06
subsystem: fabric-ontology
tags: [ontology, fabric-pipelines, sync_service, change-intelligence, predictive-intelligence, incident-intelligence, delta, publication-manifest]

# Dependency graph
requires:
  - phase: 10-fabric-medallion-capability-expansion (10-02)
    provides: OntologyValidator/PendingRelationshipStore fail-closed ontology sync gate
  - phase: 10-fabric-medallion-capability-expansion (10-03)
    provides: PublicationStateStore/publication manifest lifecycle disposition pattern (MED-09)
provides:
  - "ChangePipelineResult.entities/.relationships forwarding ChangeIntelligence.knowledge_projection() into ontology publication"
  - "New predictive_pipeline.py forwarding PredictiveEngine.knowledge_projection() into ontology publication"
  - "New incident_pipeline.py forwarding IncidentEngine.knowledge_projection() into ontology publication"
  - "sync_service.py dataset-assembly wiring extends ontology_entities/ontology_relationships from all three pipelines before _synchronize_ontology() runs"
  - "assessment_change_findings Gold table now populated (was unregistered/unwritten before this plan)"
  - "Remediation-domain ontology projection explicitly dispositioned dormant via PublicationManifestStore, evidence-backed (not guessed)"
affects: [fabric-ontology-sync, change-domain, predictive-domain, incident-domain, remediation-domain]

actuals:
  tokens: 14064
  tasks: 4
  commits: 8

tech-stack:
  added: []
  patterns:
    - "fabric_pipelines/<domain>_pipeline.py: frozen dataclass Result(entities, relationships) + run(*, now=None, **snapshot) calling <Domain>Engine.from_snapshot(**snapshot).knowledge_projection() — mirrored identically across change/predictive/incident domains"
    - "sync_service.py _<domain>_pipeline_snapshot() translation helpers bridge the governed *_intelligence_snapshot() OneLake-read shape (inventory/expected_configurations/observed_configurations as separate maps) into each engine's from_snapshot() resources-shape contract"
    - "New ontology-forwarding blocks always inserted before _synchronize_ontology() runs, extending datasets['ontology_entities']/['ontology_relationships'] — identical position/pattern to the pre-existing lifecycle_catalog/remediation_decision_reader blocks, so no bypass of the fail-closed OntologyValidator/PendingRelationshipStore gate is introduced"

key-files:
  created:
    - src/fabric_pipelines/predictive_pipeline.py
    - src/fabric_pipelines/incident_pipeline.py
    - tests/test_change_pipeline_ontology_forwarding.py
    - tests/test_incident_pipeline_ontology_forwarding.py
  modified:
    - src/fabric_pipelines/change_pipeline.py
    - src/fabric/sync_service.py
    - src/fabric/schema_registry.py
    - src/intelligence/predictive/predictive_engine.py
    - tests/test_change_pipeline.py
    - tests/test_predictive_v2_requirements.py

key-decisions:
  - "Change/Predictive domain resources translation: governed *_intelligence_snapshot()'s separate inventory/expected_configurations/observed_configurations maps are merged into each engine's from_snapshot() resources shape inside new sync_service.py helper methods, since only resource_key is strictly required by ChangeContextBuilder/PredictiveContextBuilder/IncidentContextBuilder — no live semantic-engine context needed for the batch-flow forwarding case."
  - "assessment_change_findings was discovered completely unregistered (no schema_registry.py entry existed anywhere) despite being referenced as an OUTPUT_TABLE constant — registered a new schema and per-row REQUIRED_COLUMNS-shaping helper rather than skip it, per the plan's explicit Task 2 instruction."
  - "Remediation domain (PlanRepository.ontology_projection()) dispositioned 'dormant', not wired: it requires replace_generation() to have already populated plans from a planner process that only runs in live-query paths (live_operations.py, api/runtime.py) — wiring it into batch sync would mean running the remediation planner as a new sync-time side effect, an architectural change (Rule 4) out of this plan's wiring-fix scope. Predictive domain, by contrast, is a pure from_snapshot()-driven projection with no such prerequisite, so it WAS wired identically to Change/Incident."
  - "The plan's literal acceptance-criteria grep (`grep -rln \"IncidentEngine(\" src/`) is a false friend — it matches live_operations.py only because `LiveIncidentEngine(` contains that substring, unrelated to this incident_engine module. Verified this session and documented in the regression test; asserted the actual batch-flow-reachability intent instead of the coincidental text match."

patterns-established:
  - "Domain-specific ontology pipeline modules (change/predictive/incident) all mirror change_pipeline.py's exact shape: frozen dataclass result + run(*, now=None, **snapshot)."

requirements-completed: [MED-04]

coverage:
  - id: D1
    description: "ChangeIntelligence.knowledge_projection()'s ConfigurationDrift/PolicyDeviation/SecurityDeviation/AuthorizedChange/UnapprovedChange rows reach ontology publication (were silently discarded before)"
    requirement: "MED-04"
    verification:
      - kind: unit
        ref: "tests/test_change_pipeline.py#test_change_pipeline_forwards_knowledge_projection_entities"
        status: pass
      - kind: integration
        ref: "tests/test_change_pipeline_ontology_forwarding.py#test_change_pipeline_ontology_rows_reach_ontology_entities"
        status: pass
    human_judgment: false
  - id: D2
    description: "Predictive/remediation domain disposition resolved with evidence: Predictive fixed identically to Change domain (new predictive_pipeline.py wired into sync_service.py); Remediation explicitly dispositioned dormant via PublicationManifestStore"
    requirement: "MED-04"
    verification:
      - kind: unit
        ref: "tests/test_change_pipeline_ontology_forwarding.py#test_predictive_pipeline_forwards_knowledge_projection_entities"
        status: pass
      - kind: unit
        ref: "tests/test_change_pipeline_ontology_forwarding.py#test_remediation_plan_domain_is_registered_dormant_pending_plan_generation"
        status: pass
    human_judgment: false
  - id: D3
    description: "IncidentEngine.knowledge_projection()'s Incident/OperationalFinding/BlastRadius/DependencyChain/OperationalEvent/RootCause rows reach ontology publication (previously confined to live_operations.py's on-demand query path)"
    requirement: "MED-04"
    verification:
      - kind: unit
        ref: "tests/test_incident_pipeline_ontology_forwarding.py#test_incident_pipeline_forwards_knowledge_projection_entities"
        status: pass
      - kind: integration
        ref: "tests/test_incident_pipeline_ontology_forwarding.py#test_incident_pipeline_ontology_rows_reach_ontology_entities"
        status: pass
    human_judgment: false

duration: 32min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 06: Change/Predictive/Incident Ontology Forwarding Fix (MED-04) Summary

**Closed the "computed but discarded" ontology-forwarding gap across three domains — Change, Predictive, and Incident — by wiring each domain's existing `knowledge_projection()` output into `sync_service.py`'s pre-`_synchronize_ontology()` dataset assembly, and gave the Remediation domain an evidence-backed `dormant` disposition instead of a guess.**

## Performance

- **Duration:** 32 min
- **Started:** 2026-09-01T08:52:21Z
- **Completed:** 2026-09-01T09:24:45Z
- **Tasks:** 4/4 completed
- **Files modified:** 10 (4 created, 6 modified)

## Accomplishments

- `ChangePipelineResult` gained `entities`/`relationships` fields, populated from `ChangeIntelligence.knowledge_projection()`; `sync_service.py` now forwards these into `datasets["ontology_entities"]`/`["ontology_relationships"]` before `_synchronize_ontology()` runs — identical position/pattern to the existing `lifecycle_catalog`/`remediation_decision_reader` blocks, so the fail-closed `OntologyValidator`/`PendingRelationshipStore` gate applies with no bypass.
- Registered a previously-unregistered `assessment_change_findings` Delta schema and wired `ChangePipelineResult.findings` into it — this Gold table existed only as an `OUTPUT_TABLE` constant with no schema or write path before this plan.
- Investigated the predictive/remediation domain (RESEARCH.md Assumptions Log A4) with evidence, not a guess: **Predictive** shares the identical "computed but discarded" bug (fixed identically — new `predictive_pipeline.py`, wired into `sync_service.py`); **Remediation** is genuinely different (`PlanRepository.ontology_projection()` needs planner-generated plans that only exist in live-query paths, never in batch sync) — dispositioned `dormant` via `PublicationManifestStore` with a regression test recording the current, verified state.
- Created `incident_pipeline.py` mirroring `change_pipeline.py`'s shape exactly, wired `IncidentEngine.knowledge_projection()`'s `Incident`/`OperationalFinding`/`BlastRadius`/`DependencyChain`/`OperationalEvent`/`RootCause`/`RiskPattern` rows into the same forwarding pattern — closing MED-04's third and final confirmed domain gap.
- Fixed a pre-existing bug in `PredictiveEngine._relationship()` (non-schema `relationship_type` field duplicating `predicate`) discovered only because this plan's wiring made these rows reach `DataQualityValidator`'s `schema_validation` rule for the first time.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend ChangePipelineResult with entities/relationships from knowledge_projection()** - `e5f71493` (test, RED) + `f7779683` (feat, GREEN)
2. **Task 2: Wire change_pipeline output into the ontology sync dataset assembly** - `1a8f6bff` (test, RED) + `d2ede0d7` (feat, GREEN)
3. **Task 3: Investigate and disposition the predictive/remediation domain** - `b64e795b` (fix — pre-existing schema bug found during investigation) + `0dfccfc6` (feat — predictive wiring + remediation dormant disposition + tests)
4. **Task 4: Wire IncidentEngine.knowledge_projection() into ontology publication (Incident domain)** - `d51011e9` (test, RED) + `7b0de718` (feat, GREEN)

_Note: Tasks 1, 2, and 4 are `tdd="true"` and each show a test-then-feat commit pair. Task 3 is `tdd="false"`; its two commits reflect a genuine pre-existing bug fix discovered mid-investigation plus the combined predictive-wiring/remediation-disposition implementation._

## Files Created/Modified

- `src/fabric_pipelines/change_pipeline.py` - `ChangePipelineResult` gains `entities`/`relationships`; `run()` calls `knowledge_projection()`
- `src/fabric_pipelines/predictive_pipeline.py` (new) - mirrors `change_pipeline.py` for the Predictive domain
- `src/fabric_pipelines/incident_pipeline.py` (new) - mirrors `change_pipeline.py` for the Incident domain
- `src/fabric/sync_service.py` - new `_change_pipeline_snapshot()`/`_predictive_pipeline_snapshot()`/`_incident_pipeline_snapshot()` translation helpers, `_assessment_change_finding_rows()` shaping helper, and three new forwarding blocks in `_sync_locked()` before `_synchronize_ontology()`
- `src/fabric/schema_registry.py` - new `assessment_change_findings` schema entry
- `src/intelligence/predictive/predictive_engine.py` - removed non-schema `relationship_type` field from `_relationship()` rows
- `tests/test_change_pipeline.py` - 3 new tests for Task 1
- `tests/test_change_pipeline_ontology_forwarding.py` (new) - Task 2 (change-domain sync forwarding) + Task 3 (predictive fix + remediation dormant disposition) tests
- `tests/test_incident_pipeline_ontology_forwarding.py` (new) - Task 4 tests
- `tests/test_predictive_v2_requirements.py` - updated one assertion from `relationship_type` to `predicate` to match the schema fix

## Decisions Made

- **Resources translation, not semantic-engine reuse:** `change_intelligence_snapshot()`/`predictive_intelligence_snapshot()`/`incident_intelligence_snapshot()` return a governed-inventory shape distinct from each engine's `from_snapshot()` `resources` contract (separate `expected_configurations`/`observed_configurations` maps vs. nested per-resource fields). Rather than reusing `from_semantic_engine()` (which needs a live semantic engine unavailable in the batch sync flow), new small translation helpers merge the governed maps into the minimal `resources` shape each `ContextBuilder` actually requires (only `resource_key` is mandatory; everything else defaults to "Unknown").
- **assessment_change_findings registered, not skipped:** confirmed via grep that this Gold table had zero prior registration anywhere in the codebase (not even a schema), despite being an `OUTPUT_TABLE` constant since `change_pipeline.py` was first written. Registered a schema and row-shaping helper per the plan's explicit instruction, rather than silently discarding `ChangePipelineResult.findings` again.
- **Predictive wired, Remediation dispositioned dormant:** both domains have a `knowledge_projection()`/`ontology_projection()` producer, but only Predictive is a pure, stateless `from_snapshot()` computation analogous to Change/Incident. Remediation's producer requires a stateful planner-generation prerequisite that never runs in the batch flow — wiring it in would mean running the remediation planner as a new, unplanned sync-time side effect (an architectural change, Rule 4), so it was dispositioned `dormant` instead of force-fit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Non-schema `relationship_type` field in PredictiveEngine relationships**
- **Found during:** Task 3, while wiring `predictive_pipeline.run()` output into `sync_service.py` and running the full integration test — the second `sync()` call failed `DataQualityValidator`'s `schema_validation` rule with `columns missing=[] extra=['relationship_type']` on 30 records across `ontology_relationships` and several per-relationship-type tables.
- **Issue:** `PredictiveEngine._relationship()` included a `relationship_type` key duplicating the value already carried by `predicate` — not part of the `_ONTOLOGY_RELATIONSHIP` pyarrow schema. This was a pre-existing bug, invisible until this plan made these rows reach ontology publication (and therefore validation) for the first time.
- **Fix:** Removed the `relationship_type` key from the row dict in `src/intelligence/predictive/predictive_engine.py`.
- **Files modified:** `src/intelligence/predictive/predictive_engine.py`, `tests/test_predictive_v2_requirements.py` (updated the one existing test that read `relationship_type` to read `predicate` instead).
- **Verification:** Full sync-service integration test passed after the fix (`test_predictive_pipeline_ontology_rows_reach_ontology_entities`); broader predictive/remediation regression suites (10 test files) re-run clean.
- **Committed in:** `b64e795b`

**2. [Rule 2 - Missing critical functionality] `assessment_change_findings` schema was never registered**
- **Found during:** Task 2, per the plan's explicit instruction to grep for this table before wiring it.
- **Issue:** `change_pipeline.py`'s `OUTPUT_TABLE = "assessment_change_findings"` constant had no corresponding `schema_registry.py` entry or write path anywhere in the codebase — writing `ChangePipelineResult.findings` directly would have failed `DeltaWriter`'s `REQUIRED_COLUMNS` validation (findings rows have no `tenant_id`/`subscription_id`/`resource_id`/etc.).
- **Fix:** Registered a new `assessment_change_findings` pyarrow schema in `schema_registry.py` and added `_assessment_change_finding_rows()` in `sync_service.py` to shape each finding row with the six required governed-row columns plus a stable per-row identity/version hash.
- **Files modified:** `src/fabric/schema_registry.py`, `src/fabric/sync_service.py`.
- **Verification:** `test_assessment_change_findings_populated_exactly_once` passes; table populated with unique `change_id`s, no duplicates.
- **Committed in:** `d2ede0d7`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug fix, 1 Rule 2 missing functionality)
**Impact on plan:** Both were necessary for correctness — the Rule 1 fix was a genuine pre-existing bug that this plan's own wiring surfaced; the Rule 2 fix was explicitly instructed by the plan's Task 2 action text after confirming the gap via grep. No scope creep beyond what the plan itself specified.

## Issues Encountered

**Concurrent commits from an unrelated agent (02-04 plan) landed in the same shared git history mid-session**, despite the task briefing stating "single shared working directory, sequential execution (no concurrency)." Observed via `git status` showing unexpected staged files (`src/intelligence/remediation/business_decision.py`, `src/intelligence/remediation/defender_correlation.py`) that were never touched by this plan's work. Resolved by verifying `git diff --cached --stat` immediately before every commit in this plan and confirming each commit's `git show --stat` afterward — all 8 of this plan's commits contain only the 10 files this plan actually modified, with no cross-contamination. No action was taken on the other agent's files (out of scope, left untouched per the scope-boundary rule).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

MED-04 is fully implemented for all three domains this phase's research flagged (Change, Predictive, Incident), plus an evidence-backed disposition for the fourth (Remediation, dormant). `assessment_change_findings` Gold table is now live. Downstream plans that consume `ontology_entities`/`ontology_relationships` (e.g., health/status APIs, `compliance_context`/future `predictive_context`/`incident_context` ontology views) can now expect populated rows for `ConfigurationDrift`/`PolicyDeviation`/`SecurityDeviation`/`AuthorizedChange`/`UnapprovedChange`/`ChangeEvent`/`ConfigurationBaseline` (Change), `Prediction`/`Forecast`/`Trend`/`OperationalDebt`/`RiskDriver` (Predictive), and `Incident`/`OperationalFinding`/`BlastRadius`/`DependencyChain`/`OperationalEvent`/`RootCause`/`RiskPattern` (Incident). No blockers for subsequent phase 10 plans.

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

All 11 claimed files verified present on disk; all 8 claimed commit hashes verified present in `git log --oneline --all`.
