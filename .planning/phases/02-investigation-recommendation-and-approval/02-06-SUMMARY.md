---
phase: 02-investigation-recommendation-and-approval
plan: 06
subsystem: fabric-ontology
tags: [remediation, defender, ontology, fabric, onelake]
requires:
  - phase: 02-02
    provides: Defender remediation correlation and fixed intent-only predicate vocabulary
  - phase: 02-04
    provides: Remediation plans carrying typed Defender evidence citations
provides:
  - Four distinct remediation-to-Defender evidence relationships published through Fabric ontology datasets
  - Typed relationship projection validated against the complete ontology graph
  - Durable shared remediation-plan storage wired into local and remote Fabric runtimes
  - Fail-closed citation resolution against real typed Defender entities and canonical resource associations
affects: [remediation, defender, ontology, fabric-sync, approval]
actuals:
  tokens: 11262
  tasks: 2
  commits: 6
tech-stack:
  added: []
  patterns:
    - Durable OneLake document projection shared by remediation planning and Fabric sync
    - Entity-backed citation resolution before ontology relationship publication
    - Explicit subject and object types on every remediation ontology relationship
key-files:
  created:
    - .planning/phases/02-investigation-recommendation-and-approval/02-06-SUMMARY.md
  modified:
    - src/fabric/dataset_mapper.py
    - src/fabric/runtime.py
    - src/fabric/sync_service.py
    - src/intelligence/remediation/plan_repository.py
    - src/intelligence/remediation/remediation_generator.py
    - src/intelligence/remediation/remediation_planner.py
    - tests/remediation_scenario.py
    - tests/test_remediation_ontology_alignment.py
    - docs/ontology-model.md
    - ontology-schema.md
key-decisions:
  - "Fabric sync resolves plan citations against the current authoritative ontology entity snapshot before publishing an edge."
  - "Remediation plans use a revisioned OneLake document shared by the production planner and sync service so publication survives runtime reconstruction."
  - "Relationship rows carry explicit endpoint types; requiresPlan is Application to RemediationPlan rather than relying on remediation-specific defaults."
patterns-established:
  - "Citation resolution fails closed: stale IDs, source-type mismatches, and cross-resource matches are omitted with a recorded pending reason."
  - "Plan and approval readers are merged by ontology resource ID before validation so shared durable data cannot create duplicate graph rows."
requirements-completed: [DETECT-03, DETECT-07]
coverage:
  - id: D1
    description: "Plans publish four distinct intent-only relationships to real Defender assessments, alerts, attack paths, and secure-score controls."
    requirement: "DETECT-03"
    verification:
      - kind: integration
        ref: "tests/test_remediation_ontology_alignment.py#test_sync_writes_all_plan_defender_relationships_to_published_dataset"
        status: pass
      - kind: integration
        ref: "tests/test_incremental_sync.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every remediation relationship preserves explicit endpoint types and the complete generated projection passes OntologyValidator."
    requirement: "DETECT-07"
    verification:
      - kind: unit
        ref: "tests/test_remediation_ontology_alignment.py#test_plan_relationship_rows_publish_through_sync_path"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_validator.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Stale, mistyped, and cross-resource Defender citations cannot create placeholder entities or dangling ontology relationships."
    requirement: "DETECT-07"
    verification:
      - kind: unit
        ref: "tests/test_remediation_ontology_alignment.py#test_plan_projection_records_unresolved_citations_without_synthesized_ids"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_ontology_alignment.py#test_plan_projection_rejects_mistyped_and_cross_resource_citations"
        status: pass
    human_judgment: false
  - id: D4
    description: "Every production Fabric runtime shares a durable remediation repository with its sync service."
    requirement: "DETECT-03"
    verification:
      - kind: integration
        ref: "tests/test_remediation_ontology_alignment.py#test_production_runtime_shares_and_durably_reloads_plan_projection"
        status: pass
      - kind: integration
        ref: "tests/test_api_runtime.py"
        status: pass
    human_judgment: false
duration: 14 min
completed: 2026-09-07
status: complete
---

# Phase 02 Plan 06: Remediation Evidence Ontology Summary

**Validated remediation-to-Defender intent relationships now survive production runtime reconstruction and publish through the real Fabric ontology path without synthetic evidence entities.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-09-07T13:39:48Z
- **Completed:** 2026-09-07T13:53:12Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Registered, projected, documented, and published `addressesFinding`, `addressesAlert`, `breaksAttackPath`, and `improvesControl` as distinct intent-only relationships.
- Preserved explicit source and target types for every plan relationship, including `Application --requiresPlan--> RemediationPlan`, with complete `OntologyValidator` coverage.
- Replaced synthesized Defender targets with fail-closed resolution against typed ontology entities and their canonical inventory resource association.
- Wired one revisioned OneLake-backed `PlanRepository` into both production Fabric runtime construction paths and the sync reader.
- Preserved production correlator injection by routing `RemediationPlanner.defender_correlator` to the generator that creates evidence-bearing plans.

## Task Commits

Each task and closeout correction was committed atomically:

1. **Task 1 RED: Register and project plan-to-Defender relationships** - `10dd1b1ce` (test)
2. **Tasks 1-2 GREEN: Project, publish, and document Defender relationships** - `56bd19c6e` (feat)
3. **Closeout RED: Expose publication, typing, persistence, and citation-resolution gaps** - `db1700cc7` (test)
4. **Closeout RED: Cover the production correlator handoff** - `87206dead` (test)
5. **Closeout RED: Cover duplicate plan/decision publication** - `deabfd13c` (test)
6. **Closeout GREEN: Publish validated durable remediation evidence links** - `b16f9254f` (fix)

**Plan metadata:** pending

## Files Created/Modified

- `src/fabric/dataset_mapper.py` - Registers the four predicates and preserves explicit relationship endpoint types.
- `src/fabric/runtime.py` - Shares a bounded, durable plan repository with both local and remote production sync construction paths.
- `src/fabric/sync_service.py` - Resolves plans against current ontology entities and deduplicates plan/decision publication rows.
- `src/intelligence/remediation/plan_repository.py` - Persists plans and resolves citations against typed Defender entities plus canonical resource associations.
- `src/intelligence/remediation/remediation_generator.py` - Preserves Defender evidence citations in generated plans.
- `src/intelligence/remediation/remediation_planner.py` - Routes production correlator injection to the generator.
- `tests/remediation_scenario.py` - Supplies canonical resource context for remediation ontology scenarios.
- `tests/test_remediation_ontology_alignment.py` - Covers registry alignment, invalid citations, full validation, durable runtime wiring, and real sync publication.
- `docs/ontology-model.md` - Documents intent-only Defender remediation traversal semantics.
- `ontology-schema.md` - Documents the four typed remediation-to-Defender relationships and canonical identity rule.

## Decisions Made

- Use the mapped ontology entity snapshot as the authority for citation type and resource membership instead of trusting plan citation strings.
- Resolve secure-score controls through their referenced `DefenderAssessment` entities to retain the canonical inventory resource join.
- Persist generated plans in a revisioned OneLake document and inject one repository instance into planning and sync within each Fabric runtime.
- Keep direct decision publication and plan projection compatible by deduplicating ontology rows by canonical resource ID before graph validation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Production sync had no remediation plan reader**
- **Found during:** Closeout review of Task 2
- **Issue:** Both `FabricSyncService` construction paths left `remediation_plan_reader` unset, so projected relationships never reached production datasets.
- **Fix:** Added revisioned plan persistence and shared the repository between runtime planning and sync publication in local and remote construction paths.
- **Files modified:** `src/fabric/runtime.py`, `src/intelligence/remediation/plan_repository.py`
- **Verification:** Production runtime durable-reload test and Fabric sync publication test.
- **Committed in:** `b16f9254f`

**2. [Rule 1 - Bug] Remediation relationship mapping discarded endpoint types**
- **Found during:** Closeout review of Task 2
- **Issue:** Every mapped relationship hardcoded `RemediationPlan` as subject and defaulted unknown objects to `ApprovalDecision`, invalidating `Application --requiresPlan--> RemediationPlan`.
- **Fix:** Carried explicit `subject_type` and `object_type` through projection and mapping, then validated the complete graph.
- **Files modified:** `src/fabric/dataset_mapper.py`, `src/intelligence/remediation/plan_repository.py`
- **Verification:** Complete projection validation with `OntologyValidator`.
- **Committed in:** `b16f9254f`

**3. [Rule 2 - Missing Critical] Citation IDs were trusted without entity or resource verification**
- **Found during:** Closeout review of Task 1
- **Issue:** Any non-empty source ID produced a fabricated Defender entity and relationship, including stale, mistyped, and cross-resource citations.
- **Fix:** Indexed actual typed Defender ontology entities, verified canonical resource association, resolved controls through assessment definitions, and recorded explicit pending reasons for rejected citations.
- **Files modified:** `src/intelligence/remediation/plan_repository.py`
- **Verification:** Stale, mistyped, cross-resource, and no-placeholder regression tests.
- **Committed in:** `b16f9254f`

**4. [Rule 1 - Bug] Production correlator assignment bypassed the plan generator**
- **Found during:** Production construction-path review
- **Issue:** Runtime composition assigned `planner.defender_correlator`, while plan generation read `planner.generator.defender_correlator`.
- **Fix:** Added a documented delegating property without modifying the actively owned API runtime.
- **Files modified:** `src/intelligence/remediation/remediation_planner.py`
- **Verification:** Production correlator handoff regression test and API runtime suites.
- **Committed in:** `b16f9254f`

**5. [Rule 1 - Bug] Shared plan and decision readers duplicated ontology rows**
- **Found during:** Independent post-GREEN review
- **Issue:** An approved plan appeared through both readers, causing duplicate entities and relationships to fail ontology validation.
- **Fix:** Added canonical resource-ID deduplication before synchronization, preserving the authoritative base graph and one remediation row per identity.
- **Files modified:** `src/fabric/sync_service.py`
- **Verification:** Sync-level approved-plan publication test.
- **Committed in:** `b16f9254f`

---

**Total deviations:** 5 auto-fixed (4 bugs, 1 missing critical safeguard)
**Impact on plan:** All fixes are required to make the planned ontology contract valid and reachable in production. No web, Terraform, onboarding, ontology-discovery, STATE, or ROADMAP files were changed.

## Issues Encountered

- The implementation landed before a summary existed; closeout therefore retained the original RED/GREEN commits and added focused RED tests plus one GREEN correction commit.
- An integration freeze remained active throughout closeout. No push, merge, deployment, Terraform apply, or live publication was performed.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: durable-state | `src/intelligence/remediation/plan_repository.py` | Generated plans now use a revisioned OneLake document; writes use the existing compare-and-swap document-store boundary and citations are revalidated against the current ontology snapshot before publication. |

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02-06 behavior is complete and covered through the published Delta ontology dataset.
- The branch is ready for merge review after the Fabric integration freeze is explicitly released.

## Self-Check: PASSED

- Summary output exists at the required Phase 02 path.
- All six task and closeout commits resolve in local history.
- Every implementation, test, and documentation file named above exists.
- No goal-blocking stubs, skipped tests, or unrun verification commands remain.

---
*Phase: 02-investigation-recommendation-and-approval*
*Completed: 2026-09-07*
