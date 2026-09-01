---
phase: 02-investigation-recommendation-and-approval
plan: 05
subsystem: api
tags: [defender, remediation, foundry, mcp]
requires:
  - phase: 02-02
    provides: DefenderRemediationCorrelator for correlated Defender cases
  - phase: 02-04
    provides: BusinessDecisionEngine business decision payloads
provides:
  - Read-only Defender evidence MCP tools for alerts, attack paths, and secure score
  - Read-only remediation case and business decision MCP tools for governed specialist reasoning
  - Stronger remediation specialist prompt and contract validation for business-consequence recommendations
affects: [remediation, vulnerability, foundry, mcp, copilot]
actuals:
  tokens: 2361
  tasks: 3
  commits: 3
tech-stack:
  added: []
  patterns: ["Four-surface MCP registration kept in lockstep via contract tests", "Remediation specialist outputs require explicit business-consequence fields"]
key-files:
  created: []
  modified: [src/operations/tools.py, src/operations/mcp_server.py, infra/terraform/foundry.tf, src/operations/foundry_prompts/remediation_prompt.txt, tests/test_mcp_tools.py, tests/test_foundry_tool_registry_matches_implementation.py, tests/test_remediation_specialist.py]
key-decisions:
  - "Expose Defender evidence and remediation business decisions only through read-only, scope-filtered operations-mcp tools."
  - "Require remediation specialist findings to include pros, cons, and urgency reasoning so business consequence is explicit."
patterns-established:
  - "Pattern 1: New operations-mcp tools must be added atomically to TOOL_REGISTRY, REVIEWED_TOOLS, foundry_tool_registry, and specialist assignments."
  - "Pattern 2: Remediation narration is valid only when cited evidence, uncertainty, and next safe check are present together."
requirements-completed: [DETECT-04, DETECT-07, RECOMM-02]
coverage:
  - id: D1
    description: "Defender evidence tools expose scoped alerts, attack paths, and secure score with governed evidence envelopes."
    requirement: "DETECT-04"
    verification:
      - kind: unit
        ref: "tests/test_mcp_tools.py#test_defender_alerts_tool_returns_evidence_and_empty_status_when_no_rows"
        status: pass
      - kind: unit
        ref: "tests/test_mcp_tools.py#test_defender_attack_paths_tool_inherits_scope_filtering_and_bounds_results"
        status: pass
      - kind: unit
        ref: "tests/test_mcp_tools.py#test_defender_secure_score_tool_returns_overview_and_unhealthy_controls"
        status: pass
      - kind: unit
        ref: "tests/test_foundry_tool_registry_matches_implementation.py#test_new_defender_tools_are_advertised_and_assigned"
        status: pass
    human_judgment: false
  - id: D2
    description: "Correlated remediation case and business decision tools expose governed business reasoning without mutation paths."
    requirement: "RECOMM-02"
    verification:
      - kind: unit
        ref: "tests/test_mcp_tools.py#test_remediation_cases_tool_filters_by_business_service_and_keeps_no_safe_action_visible"
        status: pass
      - kind: unit
        ref: "tests/test_mcp_tools.py#test_remediation_business_decision_tool_returns_business_decision_by_plan_or_case"
        status: pass
      - kind: unit
        ref: "tests/test_defender_remediation_correlation.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Remediation specialist prompt and contract require business consequence, uncertainty, and governed recommendations while preserving delegation."
    requirement: "DETECT-07"
    verification:
      - kind: unit
        ref: "tests/test_remediation_specialist.py"
        status: pass
      - kind: unit
        ref: "tests/test_remediation_agent.py"
        status: pass
    human_judgment: false
duration: 24 min
completed: 2026-09-01
status: complete
---

# Phase 02 Plan 05: Investigation Recommendation and Approval Summary

**Read-only Defender evidence and remediation business-decision tools now ground remediation specialist answers in cited business consequence.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-09-01T09:30:28Z
- **Completed:** 2026-09-01T09:54:28Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- Added governed Defender evidence tools for alerts, attack paths, and secure score, registered across MCP and Foundry surfaces.
- Added read-only remediation case and business-decision tools so specialists can explain urgency and no-safe-action outcomes from governed data.
- Rewrote the remediation specialist contract/prompt to center business consequence, explicit uncertainty, and human-approved governed actions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Read-only Defender evidence tools** - `b74124dd` (feat)
2. **Task 2: Correlated case and business decision tools** - `a0198316` (feat)
3. **Task 3: Remediation specialist contract and Copilot delegation** - `12481c75` (feat)

**Plan metadata:** `pending` (docs: complete plan)

## Files Created/Modified
- `src/operations/tools.py` - Added five read-only remediation/Defender MCP handlers and registry entries.
- `src/operations/mcp_server.py` - Allowlisted the new reviewed tools for MCP advertisement and authorization.
- `infra/terraform/foundry.tf` - Advertised new operations-mcp tools and assigned them to remediation/vulnerability specialists.
- `src/operations/foundry_prompts/remediation_prompt.txt` - Reframed remediation specialist behavior around business consequence and governed recommendations.
- `tests/test_mcp_tools.py` - Added tool-behavior coverage for new Defender and remediation decision tools.
- `tests/test_foundry_tool_registry_matches_implementation.py` - Added registration drift assertions for all new tools.
- `tests/test_remediation_specialist.py` - Added prompt, contract, and delegation assertions for remediation narration.

## Decisions Made
- Expose Defender evidence and remediation business decisions only through read-only, scope-filtered operations-mcp tools.
- Require remediation specialist findings to include pros, cons, and urgency reasoning so business consequence is explicit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Prompt contract fixture lagged behind remediation schema**
- **Found during:** Task 3 (Remediation specialist contract and Copilot delegation)
- **Issue:** Existing remediation test fixtures lacked the new pros/cons/urgency fields, causing contract validation to fail before the intended assertions ran.
- **Fix:** Updated the shared remediation finding fixture and adjusted the missing-field regression to remove one of the newly-required fields explicitly.
- **Files modified:** tests/foundry_test_fixtures.py, tests/test_remediation_specialist.py
- **Verification:** `uv run pytest tests/test_remediation_specialist.py tests/test_remediation_agent.py -q`
- **Committed in:** 12481c75

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Fixture repair was required to validate the intended stronger remediation contract. No scope creep.

## Issues Encountered
- None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Remediation and vulnerability specialists can now retrieve cited Defender evidence and business-decision context through governed read-only tools.
- Ready for downstream phases that consume remediation narration or approval workflows.

---
*Phase: 02-investigation-recommendation-and-approval*
*Completed: 2026-09-01*
