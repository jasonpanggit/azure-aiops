---
phase: 02-investigation-recommendation-and-approval
plan: 03
subsystem: infra
tags: [delta-lake, fabric, remediation, defender, approval-policy]

requires:
  - phase: 02-investigation-recommendation-and-approval
    provides: RemediationOpportunityEngine, ApprovalEngine, and Defender resource-signal vocabulary from 02-02

provides:
  - A governed, typed, Defender-triggerable remediation action catalog fixture (tests/fixtures/governed_remediation_catalog.json)
  - An explicit, idempotent, dry-runnable Delta seeder for the catalog and approval policies (scripts/seed_remediation_catalog.py)
  - Operator documentation of catalog location, seeding command, per-action Defender triggers, and approval roles
affects: [phase-3-allowlist-selection, remediation-plan-generation]

actuals:
  tokens: 24000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Governed configuration content lives as a versioned JSON fixture consumed by both tests and the operator seeder script, so there is one source of truth for what the planner can propose."
    - "Seeder scripts validate content through the real domain engine before writing, never trusting the file format alone."

key-files:
  created:
    - scripts/seed_remediation_catalog.py
    - tests/fixtures/governed_remediation_catalog.json
    - tests/test_remediation_catalog_seed.py
  modified:
    - docs/REMEDIATION_PLANNING_CONFIG.md

key-decisions:
  - "Six catalog actions (not five to eight arbitrarily) chosen to cover all four canonical Defender signal families (critical alert, attack path, unhealthy control, exploitable finding) plus the two existing non-Defender debt classes (patch/vulnerability, configuration/policy) already exercised by the sample fixture, avoiding duplication of coverage."
  - "Added a fourth approval policy (defender-security-response) requiring a Security Response Owner role for any action, independent of environment/criticality conditions, so newly-added Defender-triggered actions always carry at least one required approval even against a low-criticality/non-production resource."
  - "Seeder writes through OneLakeWriter(local_root=target) + DeltaWriter rather than a bespoke path-construction scheme, reusing the same table_uri/schema convention read by remediation_planning_snapshot()."

patterns-established:
  - "CLI seeder scripts for governed Silver tables: require --target explicitly, validate through the real domain engine before writing, support --dry-run, and print a written-row summary."

requirements-completed: [RECOMM-01, RECOMM-02]

coverage:
  - id: D1
    description: "Governed catalog fixture with six typed declarative actions, each accepted by RemediationOpportunityEngine, none containing runnable command text, covering all four canonical Defender signal families."
    requirement: "RECOMM-01"
    verification:
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_every_catalog_action_is_accepted_by_the_opportunity_engine"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_catalog_covers_all_four_defender_signal_families"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_defender_evidence_reaches_catalog_matching_via_identify"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_every_action_has_unique_id_and_required_labels"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_no_catalog_string_looks_like_a_runnable_command"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every seeded approval policy resolves at least one required approval role for the resource classes the actions target, so generated plans always carry approval requirements."
    requirement: "RECOMM-02"
    verification:
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_every_approval_policy_resolves_a_required_role_for_targeted_resource_classes"
        status: pass
    human_judgment: false
  - id: D3
    description: "An explicit, idempotent, dry-runnable seeder writes both governed Silver tables through DeltaWriter, refusing to run without an explicit target and refusing to write invalid catalog content."
    verification:
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_help_documents_required_target_argument"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_requires_explicit_target"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_dry_run_reports_and_writes_nothing"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_writes_both_tables_with_round_tripping_json_columns"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_is_idempotent_across_repeated_runs"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_validates_content_and_refuses_to_write_invalid_catalog"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_catalog_seed.py::test_seeder_module_reaches_no_cloud_sdk_and_spawns_no_process"
        status: pass
      - kind: manual_procedural
        ref: "Seeded a scratch local lakehouse target with `uv run python scripts/seed_remediation_catalog.py --target .scratch_verify/lakehouse`, then read silver_remediation_action_catalog via DeltaTable and confirmed 6 non-empty rows before cleaning up the scratch directory."
        status: pass
    human_judgment: false

duration: 45min
completed: 2026-09-01
status: complete
---

# Phase 2, Plan 03: Governed Remediation Catalog Seeding Summary

**Six typed, Defender-triggerable remediation actions seeded via an explicit, idempotent, validate-before-write Delta seeder, closing the blocking gap where the planner read an always-empty catalog.**

## Performance

- **Duration:** 45 min
- **Started:** 2026-09-01T08:50:00Z
- **Completed:** 2026-09-01T09:08:04Z
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- Authored `tests/fixtures/governed_remediation_catalog.json` with six declarative catalog actions covering all four canonical Defender resource-signal families (`defender_active_critical_alert_count`, `defender_attack_path_membership_count`, `defender_unhealthy_control_count`, `defender_exploitable_finding_count`) plus patch/vulnerability and configuration/policy debt, and four approval policies (including a new `defender-security-response` policy guaranteeing every action always resolves at least one approval role)
- Every action passes `RemediationOpportunityEngine` construction validation, none contains runnable command text (verified by pattern scan), and feeding Defender-signal-bearing resources through `identify()` returns matching opportunities citing the fired signal
- Shipped `scripts/seed_remediation_catalog.py`: requires an explicit `--target`, validates catalog content through the real `RemediationOpportunityEngine`/`ApprovalEngine` before writing, supports `--dry-run`, writes both Silver tables through `DeltaWriter` in overwrite mode keyed on identifiers (idempotent across repeated runs), imports no cloud SDK, spawns no process
- Documented the catalog location, seeding command, per-action Defender triggers, and required approval roles in `docs/REMEDIATION_PLANNING_CONFIG.md`, with an explicit statement that seeding grants no execution authority

## Task Commits

Each task was committed atomically:

1. **Task 1: Author the governed, typed, Defender-triggerable action catalog** - `a9491032` (test)
2. **Task 2: Ship an explicit idempotent catalog seeder and document the catalog** - `f81ec66b` (feat)

**Plan metadata:** (this commit) (docs: complete plan)

_Note: Task 1's fixture and tests were green on first write (no separate red/green split needed beyond the pre-existing red state of the file not existing); Task 2 went red (seeder script missing, 6 failing tests) then green after the seeder was implemented._

## Files Created/Modified
- `tests/fixtures/governed_remediation_catalog.json` - Governed catalog content: 6 typed declarative actions and 4 approval policies
- `tests/test_remediation_catalog_seed.py` - Catalog-acceptance, Defender-matching, no-runnable-text, and seeder behavior tests
- `scripts/seed_remediation_catalog.py` - Explicit, idempotent, dry-runnable, validate-before-write Delta seeder
- `docs/REMEDIATION_PLANNING_CONFIG.md` - Added catalog location, seeding command, trigger/approval table, and no-execution-authority statement

## Decisions Made
- Added a fourth approval policy (`defender-security-response`) not present in the original sample fixture, so newly-added Defender-triggered actions always carry at least one required approval role even against a low-criticality, non-production resource (satisfies D-20 for the new action set specifically, not just the pre-existing three actions).
- Seeder reuses `OneLakeWriter(local_root=target).table_uri(...)` + `DeltaWriter` rather than constructing paths manually, so it stays schema- and path-consistent with `remediation_planning_snapshot()`'s reader.
- Marked `secure-score-control-remediation`, `controlled-patch-recovery`, and `configuration-baseline-recovery` as Phase 3 low-risk allowlist candidates in action metadata (documentation only, read by nothing in this phase), per D-23/D-29; left the three Defender alert/attack-path/exploitable-finding actions unmarked since they more often require case-by-case scoping.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. Operators seed a real lakehouse by running `scripts/seed_remediation_catalog.py --target <uri>` against their own Fabric OneLake target; this is documented in `docs/REMEDIATION_PLANNING_CONFIG.md`.

## Next Phase Readiness
- The remediation pipeline no longer returns an empty opportunity/plan set by construction in a real deployment once an operator runs the documented seed command.
- Generated plans now always carry at least one approval requirement for every seeded action class.
- Phase 3 has a documented, non-behavioral starting point for which action types are reasonable low-risk allowlist candidates.

---
*Phase: 02-investigation-recommendation-and-approval*
*Completed: 2026-09-01*
