---
phase: 10-fabric-medallion-capability-expansion
plan: 04
subsystem: fabric
tags: [fabric, medallion, health, freshness-slo, data-quality, onelake, tdd]

# Dependency graph
requires:
  - phase: 10-02
    provides: "DataQualityValidator's config-idiom (fabric.config.yaml per-environment threshold sections, DataQualityValidator.from_config) mirrored here for FreshnessSloConfig.from_config"
  - phase: 10-03
    provides: "No direct code dependency; sequencing only (10-03 committed first in this wave)"
provides:
  - "src/fabric/medallion_health.py::dataset_status(table_name) -- the single dataset-agnostic health entry point every later Phase 10 surface (health API 10-13, web tab 10-14, Data Agent grounding guardrail 10-11/10-12) calls for per-dataset health"
  - "src/fabric/medallion_health.py::FreshnessSloConfig -- per-table freshness SLO config (fabric.medallion_health.freshness_slo), never a single global threshold"
  - "metadata_source_status schema extended with row_count/lineage_ref (nullable) so any dataset's health evidence, not just Defender's, can be read back"
affects: [10-05-fabric-medallion-capability-expansion, 10-07-fabric-medallion-capability-expansion, 10-11-fabric-medallion-capability-expansion, 10-13-fabric-medallion-capability-expansion, 10-14-fabric-medallion-capability-expansion]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 6989
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dataset-agnostic health provider (src/fabric/medallion_health.py::dataset_status) generalizes VulnerabilityIntelligenceService._coverage_for_family's latest-per-scope reduction and api/runtime.py::_snapshot_failure_table's failure-materialization pattern to any table name -- new Bronze/Silver/Gold families get health for free instead of a copy-pasted per-domain implementation."
    - "FreshnessSloConfig.from_config(config_path) mirrors DataQualityValidator.from_config's config-loading idiom exactly: missing file/section/keys fall back to safe defaults, never crash."
    - "metadata_source_status is the one generalized status table for every dataset family (not just Defender) -- new columns are added nullable so every existing producer keeps working without a backfill."

key-files:
  created:
    - src/fabric/medallion_health.py
    - tests/test_medallion_health.py
  modified:
    - fabric.config.yaml
    - fabric.config.example.yaml
    - src/fabric/schema_registry.py
    - src/fabric/dataset_mapper.py
    - src/api/runtime.py

key-decisions:
  - "availability enum (healthy|healthy-empty|stale|degraded|failed|unavailable) is computed with an explicit priority order: unavailable > failed > stale > degraded > healthy-empty > healthy -- so an unreachable source is never mistaken for a healthy zero-row dataset, and a failed sync attempt is distinguished from source unreachability even though both may report 'failed'-shaped signals."
  - "dataset_status() takes table_name plus optional keyword-injected source_status/row_count/freshness_slo/clock rather than reading a live Fabric connection itself -- keeps the module fully unit-testable now, while later plans (10-13's health API) pass real rows/row counts read from OneLake/the SQL endpoint."
  - "Config keys by table name only (not a separate pipeline-name indirection layer) for this plan's scope -- 'or pipeline name with a table-name fallback' from the task text was read as future-proofing wording, not a requirement to build a second lookup layer with zero current callers."

requirements-completed: [MED-03]

coverage:
  - id: D1
    description: "Per-dataset freshness SLO is a configurable bounded multiple of the producing pipeline's own cadence (fabric.config.yaml medallion_health.freshness_slo), never a single global threshold -- verified with two independently-cadenced tables classifying the same raw age differently."
    requirement: "MED-03"
    verification:
      - kind: unit
        ref: "tests/test_medallion_health.py#test_freshness_slo_defaults_to_bounded_multiple_of_pipeline_cadence"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_freshness_slo_explicit_table_override_wins_over_default"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_freshness_fresh_under_threshold"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_freshness_stale_over_threshold"
        status: pass
    human_judgment: false
  - id: D2
    description: "dataset_status(table_name) is the single dataset-agnostic provider returning {availability, freshness, quality, row_count, last_success_at, lineage_ref}, distinguishing healthy/healthy-empty/failed/unavailable and merging multiple raw metadata_source_status rows down to a latest-per-scope verdict."
    requirement: "MED-03"
    verification:
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_healthy_with_rows"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_healthy_empty_never_unavailable_or_failed"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_failed_sync_attempt"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_unavailable_source_unreachable"
        status: pass
      - kind: unit
        ref: "tests/test_medallion_health.py#test_dataset_status_merges_latest_per_scope"
        status: pass
    human_judgment: false

# Metrics
duration: ~45min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 04: Dataset-Agnostic Freshness/Status/Quality Health Provider Summary

**Generalized the Defender-only `_coverage_for_family`/`_snapshot_failure_table` freshness/status/quality pattern into one reusable `src/fabric/medallion_health.py::dataset_status(table_name)` provider with configurable per-dataset freshness SLOs (MED-03), fully unit-tested (9/9 scenarios) with zero regressions against the full suite.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-09-01 (session start)
- **Completed:** 2026-09-01
- **Tasks:** 3/3 completed
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- Implemented `FreshnessSloConfig` (per-table `cadence_minutes`/`slo_multiplier` config, mirroring `DataQualityValidator.from_config`'s loading idiom) and `_freshness_slo_seconds(table_name)`, so every dataset's freshness objective is its own configured multiple of its own cadence -- never a single hardcoded global threshold.
- Implemented `dataset_status(table_name)`, lifting `VulnerabilityIntelligenceService._coverage_for_family`'s latest-per-scope reduction and `api/runtime.py::_snapshot_failure_table`'s failure-materialization pattern, generalized to any table name. Returns `{availability, freshness, quality, row_count, last_success_at, lineage_ref}` with `availability` distinguishing `healthy`/`healthy-empty`/`stale`/`degraded`/`failed`/`unavailable` -- zero rows never implies success or failure on its own, and source-unreachable is distinct from a failed-but-reachable sync attempt.
- Wrote `tests/test_medallion_health.py` covering all 9 required scenarios (4 freshness + 5 status), all passing.
- Extended `metadata_source_status`'s schema with `row_count`/`lineage_ref` (nullable) so the new provider has real row-count and lineage evidence to read, and fixed the two existing producers of that table (`dataset_mapper.py::_source_status_row`, `api/runtime.py::_snapshot_failure_table`) to populate the new columns -- keeping the sync pipeline's strict per-table schema validation passing for every existing caller.

## Task Commits

Each task was committed atomically:

1. **Task 1+2 (TDD RED): failing tests for freshness SLO and dataset status** - `b0d33442` (test)
2. **Task 1+2 (TDD GREEN): implement medallion_health.py** - `af291029` (feat)
3. **Deviation fix: extend metadata_source_status schema + existing producers** - `86bff31f` (fix)

_Note: Task 3 (regression test file) was produced together with Tasks 1/2's RED commit -- all 9 scenarios were written and verified together in `tests/test_medallion_health.py` from the start, then re-verified standalone (`pytest tests/test_medallion_health.py -q` -- 9 passed) as Task 3's own acceptance step, with no additional code changes required._

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `src/fabric/medallion_health.py` - New module: `FreshnessSloConfig`, `_freshness_slo_seconds`, `dataset_status`
- `tests/test_medallion_health.py` - New: 9 unit tests covering both freshness-SLO and dataset-status behaviors
- `fabric.config.yaml` / `fabric.config.example.yaml` - New `fabric.medallion_health.freshness_slo` section (per-table `cadence_minutes`/`slo_multiplier` overrides; `fabric.config.yaml` itself is gitignored, only the `.example` copy is tracked in git)
- `src/fabric/schema_registry.py` - `metadata_source_status` schema extended with nullable `row_count`/`lineage_ref` columns
- `src/fabric/dataset_mapper.py` - `_source_status_row` now populates `row_count`/`lineage_ref`
- `src/api/runtime.py` - `_snapshot_failure_table` now populates `row_count` (`None`, never `0`) and `lineage_ref`

## Decisions Made

- **Availability priority order:** `unavailable > failed > stale > degraded > healthy-empty > healthy`, computed from the latest-per-scope-merged rows. This is what lets a source-unreachable connection and a reachable-but-failed sync attempt both resolve to distinct, correct states rather than collapsing into one generic "bad" bucket.
- **Injectable, not connection-bound:** `dataset_status()` takes `table_name` plus optional keyword-only `source_status`/`row_count`/`freshness_slo`/`clock` overrides rather than owning a live Fabric/OneLake read itself. This keeps the module fully unit-testable in isolation (no live Fabric dependency for this plan) while leaving the door open for 10-13's health API to pass real rows.
- **Config keyed by table name only** for this plan's scope. The task text's "(or pipeline name with a table-name fallback)" was read as forward-looking wording for a future indirection layer, not a requirement to build a second name-resolution mechanism with no current caller needing it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality, explicitly required by the task's own action text] Extended `metadata_source_status` schema (not in `files_modified`, but required by Task 2's action)**
- **Found during:** Task 2
- **Issue:** Task 2's action explicitly instructs "extend its schema in `schema_registry.py` if it lacks a needed column" for `row_count`/`lineage_ref`, but `src/fabric/schema_registry.py` was not listed in this plan's frontmatter `files_modified`.
- **Fix:** Added two new nullable columns (`row_count: int64`, `lineage_ref: string`) to the existing `metadata_source_status` schema entry rather than creating a second status table.
- **Files modified:** `src/fabric/schema_registry.py`
- **Verification:** `pytest tests/test_medallion_health.py -q` (9/9); full suite re-run below.
- **Committed in:** `86bff31f`

**2. [Rule 1 - Bug, caused by change #1 above] Existing `metadata_source_status` producers broke strict schema validation after the column addition**
- **Found during:** Task 2 (full-suite regression check)
- **Issue:** `DataQualityValidator.validate_table`'s `_schema_error` requires `set(row) == set(schema.names)` exactly. Adding `row_count`/`lineage_ref` to the schema without updating the table's two existing row-producers (`dataset_mapper.py::_source_status_row`, `api/runtime.py::_snapshot_failure_table`) caused 18 previously-passing tests in `tests/test_incremental_sync.py` (plus 1 in `tests/test_api_vulnerability_router.py`) to fail with spurious `schema_validation` errors -- a regression directly introduced by this plan's own schema change, in scope to fix.
- **Fix:** Both producers now populate `row_count` (`None` when unknown -- deliberately never `0`, since an unreachable connection has no known row count and that is a different fact from an observed zero) and `lineage_ref` (empty-string default) alongside their existing fields.
- **Files modified:** `src/fabric/dataset_mapper.py`, `src/api/runtime.py`
- **Verification:** Full suite re-run after fix: back to exactly the 2 known pre-existing unrelated failures.
- **Committed in:** `86bff31f`

---

**Total deviations:** 2 auto-fixed (1 Rule 2, 1 Rule 1). Both were directly caused by faithfully implementing Task 2's own action text (schema extension) and fixing the regression that extension caused in this plan's own change -- no unrelated scope creep.
**Impact on plan:** Necessary for correctness; without these fixes, adding `dataset_status()`'s row_count/lineage_ref evidence source would have silently broken the existing sync pipeline's data-quality gate for every Defender-family sync.

## Issues Encountered

None beyond the deviations documented above -- both were caught immediately by re-running the full test suite before considering the plan complete, per the executor's baseline-failure contract (2 known pre-existing failures, both confirmed unrelated to this plan's changes).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `medallion_health.dataset_status(table_name)` is ready to be called by 10-13 (Fabric medallion health & capabilities API), 10-14 (web "Fabric medallion" tab), and 10-11/10-12 (Data Agent grounding freshness-SLO guardrail) exactly as CONTEXT.md/RESEARCH.md intended -- no further generalization work needed on this provider.
- `fabric.config.yaml`/`fabric.config.example.yaml`'s `medallion_health.freshness_slo` section is ready for later plans to add per-table entries as new Silver/Gold datasets are onboarded (e.g. 10-08's historical retention extension, 10-09's Gold/Silver restoration).
- No blockers identified for 10-05 onward.

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

- FOUND: src/fabric/medallion_health.py
- FOUND: tests/test_medallion_health.py
- FOUND: .planning/phases/10-fabric-medallion-capability-expansion/10-04-SUMMARY.md
- FOUND: b0d33442 (test commit)
- FOUND: af291029 (feat commit)
- FOUND: 86bff31f (fix commit)
