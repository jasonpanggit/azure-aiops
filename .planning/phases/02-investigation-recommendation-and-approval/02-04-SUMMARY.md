---
phase: 02-investigation-recommendation-and-approval
plan: 04
subsystem: remediation
tags: [business-decision-engine, defender, remediation-planning, disposition, cost-of-action]

requires:
  - phase: 02-investigation-recommendation-and-approval
    provides: DefenderRemediationCorrelator cases with citations, contradictory-evidence flag, governed action catalog
provides:
  - BusinessDecisionEngine producing disposition (act_now/schedule/defer/not_applicable/escalate), urgency rationale with reason code, cost-of-action vs cost-of-inaction, full alternatives comparison, and confidence
  - RemediationGenerator plans carrying business_decision, evidence_citations, expected_secure_score_improvement, and uncertainty
  - ImpactEstimator weighing business context (affected applications/services/owners) over raw dependency counts
affects: [remediation-api, remediation-ui, agent-narration, 02-03-catalog-seed]

actuals:
  tokens: 45000
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - "Business-consequence-first decisioning: disposition is derived from cost/evidence comparison, never from technical severity alone"
    - "Contradictory-evidence and unknown-business-mapping cases are guarded before act_now can be selected, forcing reduced confidence + escalate/review"
    - "Optional constructor-injected collaborators (defender_correlator, business_decision_engine) so existing callers without a correlator degrade to explicit unknown markers instead of failing"

key-files:
  created:
    - src/intelligence/remediation/business_decision.py
    - tests/test_remediation_business_decision.py
  modified:
    - src/intelligence/remediation/defender_correlation.py
    - src/intelligence/remediation/remediation_generator.py
    - src/intelligence/remediation/impact_estimator.py
    - tests/defender_correlation_scenario.py

key-decisions:
  - "Disposition guard order checks contradictory-evidence and unknown-business-mapping BEFORE act_now eligibility, so technical severity alone can never promote a case to immediate action."
  - "RemediationGenerator takes defender_correlator/business_decision_engine as optional constructor params rather than requiring RemediationPlanner wiring changes, keeping this plan's diff scoped to its files_modified list; production wiring through RemediationPlanner/api/runtime.py is left for a future plan."
  - "expected_secure_score_improvement reports status: unknown whenever there is no correlated case, no secure_score_control citation, or no positive effectiveness value — never fabricated from technical severity."
  - "ImpactEstimator now weighs affected applications/services/owners ahead of raw dependency counts, capped, while preserving every existing output key so no downstream consumer breaks."

patterns-established:
  - "Alternatives comparison always enumerates all four options (act now / schedule / defer / do nothing) with pros, cons, residual risk, effort, downtime, reversibility, and business impact — never just the chosen path."
  - "Not-applicable and no-safe-action findings are first-class dispositions with the same reasoning depth as act_now, not a fallback/error state."

requirements-completed: [DETECT-05, RECOMM-01, RECOMM-02, RECOMM-03]

coverage:
  - id: D1
    description: "BusinessDecisionEngine assigns one of act_now/schedule/defer/not_applicable/escalate with a reason code naming the justifying evidence"
    requirement: "RECOMM-01"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_act_now_disposition_names_active_business_impact_path"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_contradictory_evidence_reduces_confidence_without_picking_a_family"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every recommendation states cost-of-action vs cost-of-inaction, each traced to named evidence"
    requirement: "RECOMM-02"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py -k cost_of_action_and_cost_of_inaction"
        status: pass
    human_judgment: false
  - id: D3
    description: "Full alternatives comparison (act now / schedule / defer / do nothing) with pros/cons/residual risk/effort/downtime/reversibility/business impact for every recommendation, including not_applicable and no-safe-action cases"
    requirement: "RECOMM-03"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py -k alternatives_comparison"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py -k not_applicable"
        status: pass
    human_judgment: false
  - id: D4
    description: "Unknown business mapping or contradictory evidence reports reduced confidence and a named review requirement, and is never promoted to act_now on technical severity alone"
    requirement: "DETECT-05"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_contradictory_evidence_reduces_confidence_without_picking_a_family"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py -k unknown_business_mapping"
        status: pass
    human_judgment: false
  - id: D5
    description: "Generated plans carry business_decision, evidence_citations, expected_secure_score_improvement, and uncertainty alongside existing objective/scope/prerequisites/risk/rollback/verification sections"
    requirement: "RECOMM-01"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_defender_sourced_plan_carries_full_business_decision_section"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_plan_carries_expected_secure_score_improvement_or_unknown_marker"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_plan_carries_uncertainty_section_from_unknowns_grouping"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_plan_and_opportunity_carry_evidence_citations_alongside_evidence_list"
        status: pass
    human_judgment: false
  - id: D6
    description: "Non-Defender-sourced opportunities and generators without a wired correlator degrade to explicit unknown markers, never fail or fabricate a decision"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_non_defender_opportunity_still_generates_with_unknown_business_decision"
        status: pass
    human_judgment: false
  - id: D7
    description: "Read-only/no-execution-authorization posture unchanged by the new business-decision wiring"
    verification:
      - kind: unit
        ref: "tests/test_remediation_business_decision.py#test_plan_still_reports_read_only_posture_with_no_execution_authorization"
        status: pass
      - kind: integration
        ref: "uv run pytest -k remediation -q"
        status: pass
    human_judgment: false

duration: unspecified (multi-session)
completed: 2025-11-25
status: complete
---

# Phase 02 Plan 04: Business Decision Engine Summary

**BusinessDecisionEngine turning correlated Defender remediation cases into business-consequence-first decisions (disposition, urgency rationale, cost-of-action/inaction, four-way alternatives comparison, confidence), threaded through RemediationGenerator's plan payload.**

## Performance

- **Tasks:** 3 completed
- **Files modified:** 6 (all within plan's `files_modified` scope)

## Accomplishments
- `BusinessDecisionEngine` (`src/intelligence/remediation/business_decision.py`) computes disposition (`act_now`/`schedule`/`defer`/`not_applicable`/`escalate`) with a reason code naming the evidence, cost-of-action vs cost-of-inaction traced to named evidence, a full four-option alternatives comparison (act now / schedule / defer / do nothing) each with pros, cons, residual risk, effort, downtime, reversibility, and business impact, and a confidence score.
- Contradictory-evidence and unknown-business-mapping cases are guarded ahead of `act_now` eligibility in the disposition logic, so a case can never be promoted to immediate action on technical severity alone — it reports reduced confidence and a named review requirement instead.
- `RemediationGenerator.generate()` now threads a `BusinessDecisionEngine` decision into every plan via an optional `defender_correlator` constructor param and a per-call case lookup, adding `business_decision`, `evidence_citations`, `expected_secure_score_improvement` (known/unknown), and `uncertainty` to the plan payload — without breaking any existing plan consumer or the read-only/no-execution-authorization posture.
- `ImpactEstimator.estimate()` now weighs business context (affected applications, affected services, owners) ahead of raw dependency counts, while preserving every existing output key.

## Task Commits

Each task was committed as a TDD red/green pair:

1. **Task 1+2: Disposition/cost/alternatives engine** - `fa0d28d2` (test) / `dabb7a33` (feat)
2. **Task 3: Thread business decisions into generated plans** - `019dd277` (test) / `d07a0b22` (feat)

**Plan metadata:** this commit (docs: complete 02-04 plan)

_Note: commits `fa0d28d2`/`dabb7a33`/`019dd277`/`d07a0b22` are interleaved in `git log` with unrelated commits from other plans (10-06) running concurrently in this shared worktree; only the four hashes above belong to this plan._

## Files Created/Modified
- `src/intelligence/remediation/business_decision.py` - New `BusinessDecisionEngine`: disposition, urgency rationale, cost-of-action/inaction, alternatives comparison, confidence.
- `src/intelligence/remediation/defender_correlation.py` - Added `not_applicable_evidence` field so cases can carry evidence for a `not_applicable` disposition.
- `src/intelligence/remediation/remediation_generator.py` - Threaded `BusinessDecisionEngine` into `generate()`; added `_case_for()` and `_secure_score_improvement()` helpers; extended plan payload.
- `src/intelligence/remediation/impact_estimator.py` - Reweighted `estimate()` toward business context over raw dependency counts; output keys unchanged.
- `tests/defender_correlation_scenario.py` - Added a not-applicable fixture case for the new disposition path.
- `tests/test_remediation_business_decision.py` - 25 tests covering disposition, cost-of-action/inaction, alternatives comparison, confidence/unknowns, and generated-plan integration.

## Decisions Made
- Disposition guard order (contradictory/unknown-mapping checked before act_now) is the mechanism that structurally prevents "remediation for the sake of remediation" — this was treated as the single most important invariant in the plan and tested explicitly (`test_contradictory_evidence_reduces_confidence_without_picking_a_family`).
- `RemediationGenerator` takes the correlator/engine as optional constructor params rather than expanding `RemediationPlanner`'s or `api/runtime.py`'s wiring, keeping this plan's diff exactly within its declared `files_modified` list. Production end-to-end wiring (so a live correlator actually reaches `RemediationGenerator` through `RemediationPlanner`) is intentionally left open for a future plan, since those files are out of this plan's scope.
- Kept `ImpactEstimator`'s existing output keys byte-identical while changing the internal weighting formula, since no test or downstream caller asserted the exact numeric score — verified via grep before changing.

## Deviations from Plan

None functionally — plan executed as specified across all 3 tasks with the required TDD red/green commit pairs. Two small housekeeping items surfaced during verification and were folded into the Task 3 feat commit rather than treated as separate deviations:

**1. Test fixture completeness bug found during Task 1 test run**
- **Found during:** first run of `tests/test_remediation_business_decision.py`
- **Issue:** `ExecutionSimulator` requires all 4 effectiveness percentage keys; the shared `ACTION_CATALOG[0]` fixture only set `risk_reduction_percent`.
- **Fix:** Added a local `_full_action()` helper in the new test file (not the shared fixture) that fills in the remaining 3 keys as 0.
- **Committed in:** `fa0d28d2`.

**2. Ruff lint findings in touched test/scenario files**
- **Found during:** final plan-level lint pass.
- **Issue:** import-sort ordering and a `set((...))` -> `{...}` style finding in `tests/test_remediation_business_decision.py` and `tests/defender_correlation_scenario.py`.
- **Fix:** `ruff check --fix` plus one manual edit; re-ran the full test suite afterward to confirm no regression. Two pre-existing lint findings in `defender_correlation.py` (from plan 02-02, predating this plan's edits) were confirmed via `git show` on the prior commit and left untouched as out of scope.
- **Committed in:** `d07a0b22`.

**Impact on plan:** Both items are test-hygiene fixes with no behavioral impact; no scope creep.

## Issues Encountered
- The same fixture case (`MAPPED_RESOURCE_ID`) naturally carries `contradictory_evidence: True` from its mixed severities, which meant the act_now-path test and the contradictory-evidence test couldn't both assert on the unmodified fixture. Resolved by having the act_now test operate on a local copy of the case with `contradictory_evidence` forced to `False`, leaving the fixture and the contradictory-evidence test's assertions on real data untouched.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `BusinessDecisionEngine` and its `RemediationGenerator` integration are fully tested and ready for the API/UI layer to surface `business_decision`, `evidence_citations`, `expected_secure_score_improvement`, and `uncertainty` to operators and agents.
- Production wiring gap: `RemediationPlanner` does not yet pass a `defender_correlator` into `RemediationGenerator`, so a future plan must close that loop (likely alongside `src/api/runtime.py`'s existing `_attach_defender_correlator` bolt-on) before this reaches production plans end-to-end.
- Plan 02-03 (catalog seeding) was running concurrently in this shared worktree and was not touched by this work.

---
*Phase: 02-investigation-recommendation-and-approval*
*Completed: 2025-11-25*
