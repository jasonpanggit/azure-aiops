---
phase: 10-fabric-medallion-capability-expansion
plan: 05
subsystem: fabric
tags: [ontology, fabric, delta-schema, lifecycle-disposition, tdd]

# Dependency graph
requires:
  - phase: 10-02
    provides: "DataQualityValidator/OntologyValidator conventions confirming the referential-integrity/validation layer this manifest sits alongside, not inside"
  - phase: 10-03
    provides: "Sequencing only (10-03 committed first in this wave); no direct code dependency"
provides:
  - "src/ontology/publication_manifest.py::PublicationManifestStore -- the queryable active/dormant/retired/unknown lifecycle-disposition registry for every generated ontology projection"
  - "src/fabric/schema_registry.py::SCHEMAS['metadata_publication_manifest'] -- versioned Delta schema for durable persistence of the registry"
  - "A structurally distinct concept from the existing per-connection snapshot manifest (manifest.json in dataset_mapper.py/runtime.py) -- never conflated, never extended"
affects: [10-09-fabric-medallion-capability-expansion, 10-13-fabric-medallion-capability-expansion, 10-14-fabric-medallion-capability-expansion]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
actuals:
  tokens: 5356
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PublicationManifestStore mirrors PendingRelationshipStore's caller-persisted idiom (in-memory dict, to_list()/from_list() for durability handoff) rather than owning its own Delta write path -- consistent with how other registries (ConnectionRegistry) in this repo separate the queryable contract from the storage mechanism."
    - "get(name) returns a synthetic 'unknown'-disposition entry (never raises, never defaults to 'active') for any unregistered projection name -- the same 'never silently default to healthy/active' discipline medallion_health.py established for dataset availability in 10-04."
    - "retired disposition evidence (compatibility_version + retired_reason) is enforced identically at both register()-time and set_disposition()-time, so there is no code path that produces a retired projection without that evidence."

key-files:
  created:
    - src/ontology/publication_manifest.py
    - tests/test_publication_manifest.py
  modified:
    - src/fabric/schema_registry.py

key-decisions:
  - "Confirmed via research and direct code read that dataset_mapper.py/runtime.py's `manifest.json` is exclusively a per-connection ingestion snapshot manifest (runId/startedAt) -- structurally and conceptually unrelated to this plan's publication manifest. Neither file was touched; the new module and schema entry use 'publication manifest' terminology throughout, never bare 'manifest', per RESEARCH.md's Pitfall #4."
  - "PublicationManifestStore does not perform its own Delta write in this plan -- it defines the queryable in-memory contract (register/set_disposition/get) plus to_list()/from_list() serialization, matching medallion_health.py::dataset_status()'s pattern of accepting/returning caller-managed data rather than owning I/O. Actual persistence wiring is left to a later plan (10-09's disposition classification / a future writer), consistent with must_haves' key_links."
  - "metadata_publication_manifest schema follows the existing metadata_* convention (*_BASE plus table-specific fields) for consistency with metadata_source_status/metadata_audit_events, even though the manifest's own identity (projection_name) isn't tenant/subscription/resource-scoped the way ingestion tables are -- BASE columns are still populated by whatever writer eventually persists a row (e.g. ingestion_run_id of the publish operation that changed the disposition)."

requirements-completed: [MED-09]

coverage:
  - id: D1
    description: "Registering a new ontology projection with disposition active is queryable by name and returns active"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_register_new_projection_active_is_queryable"
        status: pass
    human_judgment: false
  - id: D2
    description: "Marking a projection dormant keeps its physical Fabric binding intact (metadata-only change, never deletion) and it is queryable as dormant"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_set_disposition_dormant_keeps_physical_binding_and_is_queryable"
        status: pass
    human_judgment: false
  - id: D3
    description: "Marking a projection retired requires compatibility_version and retired_reason; omitting either raises ValueError (enforced at both register() and set_disposition())"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_set_disposition_retired_requires_compatibility_version_and_reason"
        status: pass
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_register_retired_also_requires_compatibility_version_and_reason"
        status: pass
    human_judgment: false
  - id: D4
    description: "Querying an unregistered projection name returns a distinct unknown disposition, never silently defaulting to active"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_get_unregistered_projection_returns_unknown_disposition"
        status: pass
    human_judgment: false
  - id: D5
    description: "The publication manifest's schema/table name is structurally distinct from (never collides with or extends) the existing snapshot manifest's manifest.json structure"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "tests/test_publication_manifest.py#test_publication_manifest_schema_is_structurally_distinct_from_snapshot_manifest"
        status: pass
    human_judgment: false
  - id: D6
    description: "metadata_publication_manifest resolves as a versioned Delta schema via schema_for()"
    requirement: "MED-09"
    verification:
      - kind: unit
        ref: "python3 -c \"from fabric.schema_registry import schema_for; print(schema_for('metadata_publication_manifest'))\""
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 05: Publication Manifest & Lifecycle Disposition Registry Summary

**Greenfield `PublicationManifestStore` (active/dormant/retired/unknown lifecycle disposition per ontology projection) with its own versioned `metadata_publication_manifest` Delta schema, kept structurally and semantically distinct from the existing per-connection ingestion snapshot manifest.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-09-01
- **Tasks:** 3/3 completed
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- Built `src/ontology/publication_manifest.py`: `PublicationManifestEntry` dataclass + `PublicationManifestStore` with `register()`, `set_disposition()`, `get()` — the full MED-09 lifecycle-disposition contract.
- `retired` disposition is guarded by `ValueError` unless both `compatibility_version` and `retired_reason` are supplied, enforced identically whether set at initial `register()` or later via `set_disposition()`.
- `dormant`/`retired` never delete or otherwise mutate any physical binding — the store only ever changes its own metadata; `get()` on an unregistered name returns a synthetic `unknown` disposition rather than silently defaulting to `active`.
- Registered a new `metadata_publication_manifest` PyArrow schema in `schema_registry.py`, following the existing `metadata_*` table conventions, so the registry has a durable, versioned Delta table to eventually persist to.
- Verified — via a dedicated regression test — that the new schema shares no keys with, and is not the same table as, the existing per-connection snapshot manifest (`manifest.json`), directly guarding against RESEARCH.md's documented Pitfall #4.

## Task Commits

Each task was committed atomically, following the TDD RED → GREEN cycle for Task 1:

1. **Task 1 (RED): failing test for publication manifest lifecycle disposition** — `f4cf3c7b` (test)
2. **Task 1 (GREEN): implement publication manifest lifecycle disposition registry** — `0f451f5c` (feat)
3. **Task 2: register `metadata_publication_manifest` Delta schema** — `782b3cd4` (feat)
4. **Task 3: regression test file** — satisfied by the Task 1 RED commit (`f4cf3c7b`); no additional commit needed (see Deviations).

_Note: Task 1 (`tdd="true"`) produced two commits (RED test → GREEN implementation); no REFACTOR commit was needed since the initial implementation required no cleanup pass._

**Plan metadata:** pending (this SUMMARY + STATE/ROADMAP/REQUIREMENTS commit, made immediately after this document).

## Files Created/Modified

- `tests/test_publication_manifest.py` - 8 regression tests covering all 5 plan-specified behaviors plus dataclass-shape and timestamp-tracking coverage
- `src/ontology/publication_manifest.py` - `PublicationManifestEntry` dataclass + `PublicationManifestStore` registry (register/set_disposition/get/to_list/from_list)
- `src/fabric/schema_registry.py` - new `metadata_publication_manifest` SCHEMAS entry

## Decisions Made

See `key-decisions` in frontmatter above — summarized: (1) confirmed and preserved the greenfield distinction from the existing snapshot manifest; (2) scoped this plan to the in-memory queryable contract + schema declaration only, deferring actual Delta write wiring to a later plan per the plan's own `key_links`; (3) followed the existing `metadata_*` schema convention (`*_BASE` + table-specific fields) for consistency even though the manifest's own identity isn't tenant/subscription/resource-scoped the way ingestion tables are.

## Deviations from Plan

**1. [Process note, not a Rule 1-4 deviation] Task 3 produced no additional commit**
- **Found during:** Task 3
- **Issue:** Task 1 is `tdd="true"`, so its RED phase required writing `tests/test_publication_manifest.py` (the same file Task 3's action names) *before* the GREEN implementation existed. To satisfy Task 1's own `<verify>` (`pytest tests/test_publication_manifest.py -q -k "register or disposition"`), the RED commit necessarily included full coverage of all 5 plan-specified behaviors, not a partial subset.
- **Resolution:** Task 3's action ("Write `tests/test_publication_manifest.py` covering Task 1's 5 behaviors") was already fully satisfied by the Task 1 RED commit (`f4cf3c7b`). Re-running Task 3's verify (`pytest tests/test_publication_manifest.py -q`) confirms all 8 tests pass; no file changes were needed, so no additional commit was made for Task 3.
- **Files modified:** None (verification-only).
- **Verification:** `pytest tests/test_publication_manifest.py -q` → 8 passed.

---

**Total deviations:** 0 auto-fixes (Rules 1-4 did not trigger). 1 process note documenting commit-sequencing overlap between the plan's TDD task and its dedicated test-file task.
**Impact on plan:** None on scope or correctness — all 5 required behaviors plus the schema-registration behavior are implemented and tested exactly as specified.

## Issues Encountered

None. RED phase confirmed the expected `ModuleNotFoundError` before implementation existed; GREEN phase passed on first implementation attempt; full repository test suite (`pytest -q`, all ~1587 tests) run after all commits shows exactly the 2 known pre-existing unrelated failures called out in this task's instructions (`test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state`, `test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`) and no new failures.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`src/ontology/publication_manifest.py::PublicationManifestStore` and the `metadata_publication_manifest` schema are ready to be consumed by:
- Plan 10-09's `scripts/validate-lakehouse-tables.py` disposition classification.
- The later Fabric medallion health API (10-13) and web tab (10-14), which can surface a projection's disposition alongside `medallion_health.py::dataset_status()`'s existing freshness/availability signals.

No blockers for subsequent Phase 10 plans.

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

All created files verified present on disk; all 3 task commit hashes (`f4cf3c7b`, `0f451f5c`, `782b3cd4`) verified present in `git log --oneline --all`.
