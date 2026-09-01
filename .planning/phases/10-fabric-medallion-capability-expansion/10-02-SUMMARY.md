---
phase: 10-fabric-medallion-capability-expansion
plan: 02
subsystem: data-quality
tags: [pyarrow, pytest, yaml, ontology, data-quality, governance]

requires:
  - phase: 10-fabric-medallion-capability-expansion/10-01
    provides: Stabilized Defender/ontology baseline (confidence scoring, pending relationships, Bronze/Silver ingestion)
provides:
  - "DataQualityValidator ownership_coverage/tag_coverage rule with configurable per-environment warn|block thresholds"
  - "DataQualityValidator.from_config() entrypoint reading fabric.config.yaml's new data_quality.ownership_tag_thresholds section"
  - "QualityReport.blocking_rules decoupling of 'counted and reported' vs 'blocks publication' semantics"
  - "tests/test_ontology_validator.py regression coverage for OntologyValidator's referential-integrity behavior"
affects: [fabric-sync, ontology-publication, data-agent-grounding, health-api]

actuals:
  tokens: 6700
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - "QualityReport.blocking_rules: a per-report frozenset baked in at construction time that separates 'this rule fired' (rule_counts/failures, always populated) from 'this rule blocks publication' (failed_records/passed) -- lets a rule be advisory-by-default without touching every existing consumer of failed_records."
    - "DataQualityValidator.from_config(environment, config_path=...) as the config-driven constructor pattern for per-environment thresholds, keeping the zero-arg constructor's behavior unchanged for existing call sites."

key-files:
  created:
    - tests/test_ontology_validator.py
  modified:
    - src/fabric/data_quality.py
    - fabric.config.yaml
    - fabric.config.example.yaml
    - tests/test_data_quality.py

key-decisions:
  - "Ownership/tag-coverage rule is scoped to rows whose entity_type is in ontology.relationship_builder.ASSET_TYPES, matching the existing ontology_sync.py::_health() convention for what counts as a governed asset -- relationships and non-asset entities are never flagged."
  - "Owner/tags are read from payload_json (owner: str, tags: dict), not literal top-level owner/tags schema columns -- no schema in schema_registry.py defines those columns directly, and this matches the codebase's existing ontology_sync.py::_tags() convention of storing optional governance metadata inside payload_json."
  - "QualityReport.passed/failed_records changed from 'any failure in failures' to 'any failure whose rule is in blocking_rules' -- required because src/fabric/sync_service.py gates the whole sync run on failed_records (not passed), and a naive implementation made every existing sync fail once ownership/tag gaps were introduced, even in default warn mode. Discovered via full-suite regression run, fixed before commit (Rule 1)."
  - "DataQualityValidator() zero-arg default remains warn-mode/never-block, preserving src/fabric/runtime.py's two existing zero-arg call sites unchanged -- wiring environment-aware from_config() into runtime.py is left to a future increment, out of this plan's file scope."
  - "Task 2 (OntologyValidator regression tests) required zero changes to ontology_validator.py -- all 11 new tests passed against the existing implementation on the first run, confirming the coverage gap was real but the underlying behavior was already correct."

patterns-established:
  - "Config-driven quality-gate thresholds keyed by environment (dev/staging/prod) under fabric.<feature>: <thresholds>, mirroring the existing per-feature enabled: boolean idiom in fabric.config.yaml."

requirements-completed: [MED-06]

coverage:
  - id: D1
    description: "DataQualityValidator.validate_table() reports ownership_coverage/tag_coverage rule_counts for asset rows missing owner/tags, without ever silently dropping the gap"
    requirement: MED-06
    verification:
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_tag_coverage_ignores_populated_rows"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_coverage_flags_missing_owner"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_tag_coverage_flags_missing_tags"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_tag_coverage_only_applies_to_asset_rows"
        status: pass
    human_judgment: false
  - id: D2
    description: "Ownership/tag coverage thresholds are configurable per environment and can warn or block"
    requirement: MED-06
    verification:
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_tag_warn_mode_never_blocks"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_tag_block_mode_flips_passed_over_threshold"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_ownership_tag_block_mode_within_threshold_passes"
        status: pass
      - kind: unit
        ref: "tests/test_data_quality.py#test_data_quality_from_config_loads_environment_thresholds"
        status: pass
    human_judgment: false
  - id: D3
    description: "OntologyValidator's referential-integrity behavior (dangling, self-relationship, duplicate, confidence-range, required-field, active-vs-retired type-agreement exception) is regression-tested"
    requirement: MED-06
    verification:
      - kind: unit
        ref: "tests/test_ontology_validator.py (11 tests covering 7 documented behaviors)"
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 02: Referential Integrity & Ownership/Tag Governance Quality Gate Summary

**Added a configurable, per-environment ownership/tag-coverage rule to `DataQualityValidator` (warn-vs-block by dev/staging/prod), and closed the regression-test gap for `OntologyValidator`'s existing referential-integrity checks with an 11-test suite that passed unmodified — confirming the code was already correct, only untested.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-09-01T07:53:00Z (approx, session start)
- **Completed:** 2026-09-01T08:13:01Z
- **Tasks:** 2/2 completed
- **Files modified:** 4 (+1 created)

## Accomplishments

- `DataQualityValidator.validate_table()` now has `ownership_coverage`/`tag_coverage` rule counters, scoped to asset-typed rows (`entity_type in ASSET_TYPES`), reading `owner`/`tags` out of each row's `payload_json`.
- New `fabric.config.yaml`/`fabric.config.example.yaml` section `fabric.data_quality.ownership_tag_thresholds` with per-environment (`dev`/`staging`/`prod`) `mode: warn|block` + `max_missing_ownership_pct`/`max_missing_tag_pct`, loadable via the new `DataQualityValidator.from_config(environment, config_path=...)` classmethod.
- `QualityReport` gained a `blocking_rules` frozenset that decouples "counted and reported" (`rule_counts`/`failures`, always populated regardless of mode) from "blocks publication" (`failed_records`/`passed`) — this is what makes `warn` mode genuinely non-blocking while still fully visible.
- New `tests/test_ontology_validator.py` (11 tests) locks in `OntologyValidator`'s dangling/self-relationship/duplicate/confidence-range/required-field checks and the documented active-vs-retired type-agreement exception — all pass against the unmodified validator.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ownership/tag-coverage rule to DataQualityValidator**
   - `a98acb94` (test) — RED: 8 failing tests + populated `BASE` fixture
   - `b3722abf` (feat) — GREEN: rule implementation, config sections, `blocking_rules` redesign
   - `adc20daa` (fix) — corrected a test bug (duplicate `resource_id` masking the threshold assertion)
2. **Task 2: Add the missing OntologyValidator regression test file**
   - `d4e70e49` (test) — 11 new tests, all passing against unmodified `OntologyValidator`; no source changes

_Note: Task 1 required an unplanned mid-task redesign (see Deviations) between the `test`/`feat` commits — both are still atomic, self-consistent commits; the fix was folded into the `feat` commit before it landed, and only a minor test-only correction needed a separate follow-up commit._

**Plan metadata:** (this commit)

## Files Created/Modified

- `src/fabric/data_quality.py` — `ownership_coverage`/`tag_coverage` rule, `DataQualityValidator.from_config()`, `QualityReport.blocking_rules`
- `fabric.config.yaml` — new `fabric.data_quality.ownership_tag_thresholds` section (gitignored; not committed, but present in the local working copy for runtime pickup)
- `fabric.config.example.yaml` — same section, committed as the template
- `tests/test_data_quality.py` — populated `BASE` fixture with owner/tags; 8 new tests
- `tests/test_ontology_validator.py` — new file, 11 tests

## Decisions Made

See `key-decisions` in frontmatter. Highlights:
- Ownership/tags live in `payload_json`, not literal schema columns (no schema defines `owner`/`tags` columns directly; this matches the codebase's existing `ontology_sync.py::_tags()` convention).
- The rule only applies to `entity_type in ASSET_TYPES` rows (reusing `ontology.relationship_builder.ASSET_TYPES`), so relationships and non-asset entities are never flagged — matches the live baseline's own "84 missing ownership"/"52 missing tags" framing, which counts *assets*, not edges.
- `QualityReport.passed`/`failed_records` redefinition to a `blocking_rules`-filtered view (see Deviations below) — this was the one substantive design decision this plan required beyond what the plan text specified verbatim.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `failed_records`/`passed` naive design broke every existing Fabric sync test**
- **Found during:** Task 1, immediately after the first GREEN implementation, via a full-suite regression run (`uv run pytest -q`) — not part of the plan's own `<verify>` command, but run proactively before considering Task 1 complete.
- **Issue:** The first GREEN implementation made `QualityReport.passed` a plain field set once by `validate_table()`/`validate_relationships()`, with ownership/tag-coverage failures always appended to the shared `failures` list. `src/fabric/sync_service.py` gates the entire sync run on `report.failed_records` (a property counting distinct row indices with ANY entry in `failures`) — **not** on `.passed`. Because real fixture/test data has no `owner`/`tags` in `payload_json`, this made `failed_records > 0` for nearly every existing sync test, hard-failing 19 previously-passing tests across `tests/test_incremental_sync.py` and `tests/test_api_vulnerability_router.py`, even though the new rule was only meant to be advisory in the default (warn) mode.
- **Fix:** Redesigned `QualityReport` to carry a `blocking_rules: frozenset[str]` computed at construction time (`_blocking_rules()` helper) — the five pre-existing hard rules are always blocking; `ownership_coverage`/`tag_coverage` are added to the blocking set only when `mode == "block"` AND that specific rule's missing-percentage threshold is exceeded. `failed_records`/`passed` are now both derived from `blocking_rules`-filtered `failures`, so `rule_counts`/`failures` stay fully populated for visibility (nothing is "silently dropped or guessed" per the must-have truth) while the blocking signal only fires when actually configured to.
- **Files modified:** `src/fabric/data_quality.py` (same commit as the rule itself — no separate commit, since this was discovered before the GREEN commit landed).
- **Verification:** `uv run pytest -q` — full suite rerun after the fix; `tests/test_incremental_sync.py` (22/22) and `tests/test_api_vulnerability_router.py` (30/30) both back to green.
- **Committed in:** `b3722abf`

**2. [Rule 1 - Bug] Test fixture bug in the block-mode-within-threshold test**
- **Found during:** Task 1, verifying the new tests after the `blocking_rules` redesign.
- **Issue:** `test_data_quality_ownership_tag_block_mode_within_threshold_passes` reused `BASE`'s `resource_id` for its second row, which the pre-existing `duplicates` rule (an unconditional blocking rule) correctly flagged — making the test fail for a reason unrelated to what it was testing (the ownership-threshold math).
- **Fix:** Gave the second row a distinct `resource_id`.
- **Files modified:** `tests/test_data_quality.py`
- **Verification:** `uv run pytest tests/test_data_quality.py -q` — 14/14 pass.
- **Committed in:** `adc20daa`

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs found and fixed before their respective commits landed).
**Impact on plan:** No scope creep. Both fixes were necessary for correctness — the first prevents a genuine production regression (silent hard-failure of the entire Fabric sync pipeline the moment this plan's rule shipped); the second is a self-contained test-only correction. The plan's file scope (`src/fabric/data_quality.py`, `fabric.config.yaml`, `fabric.config.example.yaml`, `tests/test_data_quality.py`, `tests/test_ontology_validator.py`) was not exceeded.

## Issues Encountered

**Shared, non-isolated working directory.** This execution ran in the plain repository (not a git worktree — `.git` is a directory), and another concurrent process was executing plan 10-03 in the same working tree at the same time (interleaved commits visible in `git log`: `3dd0877a`, `e83f1c5b`, `4bf4f217`, `48fccc69`). This was handled by staging files individually (`git add <specific-path>`, never `git add -A`/`.`) at every commit, so only this plan's intended files were ever committed. Two full-suite test failures (`tests/test_service.py::test_end_to_end_mock_ingestion_tracks_incremental_state`, `tests/test_situations_tracer.py::test_production_ingestion_retains_failed_arg_status_without_watermark`) were observed throughout — confirmed unrelated to this plan's changes (they exercise `onboarding.ingestion_service`, not `fabric.data_quality`/`ontology_validator`) and logged to `.planning/phases/10-fabric-medallion-capability-expansion/deferred-items.md` rather than fixed, per the scope-boundary rule.

## Known Stubs

None.

## User Setup Required

None — no external service configuration required. Note: `fabric.config.yaml` is gitignored, so the new `data_quality.ownership_tag_thresholds` section exists in the local working copy but was not committed; `fabric.config.example.yaml` (committed) carries the same section as the reference template for anyone provisioning a fresh `fabric.config.yaml`.

## Next Phase Readiness

- MED-06 is closed: `DataQualityValidator` has a first-class, configurable ownership/tag-coverage rule, and `OntologyValidator`'s referential-integrity behavior is now regression-tested.
- `DataQualityValidator.from_config()` exists but is not yet wired into `src/fabric/runtime.py`'s `build_runtime()` (which still calls the zero-arg `DataQualityValidator()`, defaulting to warn-mode/never-block) — a future plan wanting environment-aware enforcement in the live sync pipeline should wire `from_config(environment)` there.
- Two full-suite test failures remain, tracked in `deferred-items.md`, unrelated to this plan and believed to originate from concurrent in-progress work on plan 10-03 in this shared working directory.

## Self-Check: PASSED

- FOUND: src/fabric/data_quality.py
- FOUND: fabric.config.example.yaml
- FOUND: tests/test_data_quality.py
- FOUND: tests/test_ontology_validator.py
- FOUND commit a98acb94
- FOUND commit b3722abf
- FOUND commit adc20daa
- FOUND commit d4e70e49

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*
