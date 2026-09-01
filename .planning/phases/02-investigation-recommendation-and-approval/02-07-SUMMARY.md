---
phase: 02-investigation-recommendation-and-approval
plan: 07
subsystem: api
tags: [remediation, defender, prioritization, risk, fabric]
requires:
  - phase: 02-02
    provides: Defender remediation correlation cases and canonical Defender resource-signal vocabulary
  - phase: 02-03
    provides: Remediation catalog trigger flow for correlated Defender evidence
  - phase: 02-04
    provides: Business impact estimator inputs and business mapping completeness behavior
provides:
  - Business-impact-first priority scoring with a hard Priority-1 ceiling for unmapped resources
  - Defender operational signals merged into remediation opportunity and risk scoring
  - Hardened Defender correlation handling for truncated, stale, contradictory, and malformed inputs
affects: [remediation, defender, prioritization, business-impact, risk-analysis]
actuals:
  tokens: 5810
  tasks: 3
  commits: 4
tech-stack:
  added: []
  patterns: [Business-impact-first weighting, Defender evidence citations on opportunities, Bounded degraded-input qualification]
key-files:
  created: [tests/test_defender_remediation_correlation_hardening.py]
  modified:
    - src/intelligence/remediation/plan_prioritizer.py
    - src/intelligence/remediation/risk_analyzer.py
    - src/intelligence/remediation/remediation_opportunity_engine.py
    - src/intelligence/remediation/defender_correlation.py
    - tests/test_remediation_risk_and_priority.py
key-decisions:
  - "Business-impact weighting stays the dominant ranking term and unknown business mapping contributes zero to that bucket, preserving the Priority-1 ceiling for unmapped resources."
  - "Defender evidence enters opportunity matching through the existing resource-signal path and adds structured evidence citations without changing the string evidence contract."
  - "Oversized and degraded Defender inputs are bounded and surfaced as qualified unknowns instead of crashing correlation."
patterns-established:
  - "Priority ceilings by arithmetic: top priority remains unreachable when the business-impact bucket is zeroed."
  - "Opportunity evidence duality: keep legacy string evidence while adding structured citations for downstream inspection."
requirements-completed: [DETECT-06, RECOMM-01]
coverage:
  - id: D1
    description: "Business-impact-first priority scoring with explicit factor breakdown and an unmapped-resource Priority-1 ceiling"
    requirement: "RECOMM-01"
    verification:
      - kind: unit
        ref: "tests/test_remediation_risk_and_priority.py"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_remediation_planner.py tests/test_remediation_repository_and_reports.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Defender signals merged into remediation opportunity and risk scoring with structured evidence citations"
    requirement: "RECOMM-01"
    verification:
      - kind: unit
        ref: "tests/test_remediation_risk_and_priority.py"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_incremental_sync.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Defender correlation degrades safely for stale, contradictory, oversized, unresolved, and malformed inputs"
    requirement: "DETECT-06"
    verification:
      - kind: unit
        ref: "tests/test_defender_remediation_correlation_hardening.py"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_defender_remediation_correlation.py tests/test_remediation_business_decision.py -q"
        status: pass
    human_judgment: false
  - id: D4
    description: "Full remediation/defender regression status after plan changes"
    verification:
      - kind: other
        ref: "uv run pytest -k \"remediation or defender\" -q"
        status: fail
    human_judgment: true
    rationale: "Two pre-existing remediation regressions outside this plan's file list remained failing and require separate owner follow-up."
duration: 5 min
completed: 2026-09-01
status: complete
---

# Phase 2 Plan 07: Investigation Recommendation And Approval Summary

**Business-impact-first remediation ranking now caps unmapped resources below Priority 1 while Defender evidence flows through scoring and degraded correlation inputs stay qualified**

## Performance

- **Duration:** 5 min
- **Started:** 2026-09-01T09:31:00Z
- **Completed:** 2026-09-01T09:36:43Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- Rebalanced remediation priority scoring around business impact with inspectable bucket-level factors and an arithmetic ceiling that keeps unmapped resources out of Priority 1.
- Routed Defender signals into remediation opportunity matching and operational risk evidence, preserving legacy evidence strings while adding structured citations.
- Hardened Defender correlation against truncation, stale timestamps, contradictions, unresolved resources, and malformed identifiers with explicit qualification instead of crashes.

## Task Commits

Each task was committed atomically:

1. **Task 1: Rebalance priority to business impact first** - `d4a2ab45` (test), `bc0cd9ff` (feat)
2. **Task 2: Merge Defender signals into the resource pipeline and fix risk evidence status** - `523b2eb8` (feat)
3. **Task 3: Harden the correlation path against real-environment inputs** - `4f6e8320` (feat)

**Plan metadata:** pending

## Files Created/Modified
- `src/intelligence/remediation/plan_prioritizer.py` - Replaced the old overweight formula with inspectable business-impact-first weighting and Defender exposure buckets.
- `src/intelligence/remediation/risk_analyzer.py` - Counted Defender secure-score gap as a fifth operational signal and fixed evidence-status classification.
- `src/intelligence/remediation/remediation_opportunity_engine.py` - Added structured Defender evidence citations alongside legacy evidence strings.
- `src/intelligence/remediation/defender_correlation.py` - Preserved resource lookup rows and bounded degraded correlation output with explicit truncation and unknown handling.
- `tests/test_remediation_risk_and_priority.py` - Added prioritization, opportunity, and risk-regression coverage for the new weighting and Defender signal flow.
- `tests/test_defender_remediation_correlation_hardening.py` - Added hardening coverage for oversized, stale, contradictory, unresolved, and malformed Defender inputs.

## Decisions Made
- Business mapping completeness remains the gating input for top-band priority because the business-impact bucket zeros out when mapping is unknown.
- Defender opportunity matching stays in the existing resource-signal pipeline instead of a separate correlation-only path.
- Bounded degraded-input handling reports qualification through case unknowns rather than suppressing problematic evidence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored correlator resource rows for test fixture compatibility**
- **Found during:** Task 1 (Rebalance priority to business impact first)
- **Issue:** Existing remediation scenario helpers expected `DefenderRemediationCorrelator.resources`, which the current class no longer exposed.
- **Fix:** Persisted the passed resource rows on the correlator while keeping the canonical lookup map unchanged.
- **Files modified:** `src/intelligence/remediation/defender_correlation.py`
- **Verification:** `uv run pytest tests/test_remediation_risk_and_priority.py -q`
- **Committed in:** `bc0cd9ff`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The deviation was required to keep existing remediation fixtures working while adding the new plan coverage. No scope creep.

## Issues Encountered
- `uv run pytest -k "remediation or defender" -q` still fails in pre-existing tests `tests/test_remediation_dependencies.py::test_dependency_analysis_includes_business_and_technical_context` and `tests/test_remediation_hardening.py::test_ontology_projection_is_referentially_complete`. These failures were not introduced in this plan's file list and were left unchanged.
- Repository-level `npm run lint:fix` and `npm test` could not run because this repo has no root `package.json`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Priority scoring, Defender signal flow, and correlation hardening for this plan are complete and covered by targeted tests.
- Pre-existing remediation regressions should be resolved before treating the broader `-k "remediation or defender"` suite as green.

---
*Phase: 02-investigation-recommendation-and-approval*
*Completed: 2026-09-01*
