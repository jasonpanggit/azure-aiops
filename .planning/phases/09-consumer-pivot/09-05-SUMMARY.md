---
phase: 09-consumer-pivot
plan: 05
subsystem: copilot-runtime
tags: [copilot, orchestration, fabric-iq, governance, budgets]
requires:
  - phase: 09-consumer-pivot
    provides: snapshot integrity and freshness-aware contextual findings
provides:
  - bounded contextual plan/observe/delegate/request-evidence/reassess execution
  - optional managed Fabric IQ provider resolution with governed metadata
affects: [consumer-pivot, operations-copilot, fabric-runtime]
tech-stack:
  added: []
  patterns: [allowlisted specialist delegation, optional ProviderRuntime capability]
key-files:
  created: []
  modified:
    - src/operations/autonomous_investigation.py
    - src/api/runtime.py
    - tests/test_api_runtime.py
    - tests/test_fabric_client.py
decisions:
  - "Contextual page kind selects a narrow specialist set; model output cannot select tools."
  - "Fabric IQ is resolved as an optional ProviderRuntime capability and remains non-authoritative for identity."
metrics:
  duration: 12min
  completed: 2026-08-28
  status: complete
actuals:
  tokens: 5900
  tasks: 2
  commits: 3
status: complete
---

# Phase 09 Plan 05: Governed Agentic Runtime Summary

**Contextual Copilot now performs bounded governed delegation and evidence requests, while Fabric IQ is reachable only through an optional managed runtime provider.**

## Accomplishments

- Replaced contextual stage-only bookkeeping with actual allowlisted specialist tool calls, named evidence rechecks, deterministic reassessment, specialist metadata, operation statuses, and stop reasons.
- Enforced contextual specialist, tool, step, retry, and wall-clock bounds while preserving partial results and explicit unavailable/denied outcomes.
- Replaced the unconditional Fabric IQ `None` composition-root provider with a configuration-driven adapter backed by the existing Fabric runtime ontology service.
- Preserved Fabric IQ scope filtering, provenance/freshness/authorization metadata, optional fallback behavior, and `identity_authority: false`.
- Added TDD coverage for governed Fabric IQ enrichment and runtime loader resolution.

## Task Commits

1. `7338fe62` — `feat(09-05): execute governed contextual investigation loop`
2. `898915dd` — `test(09-05): cover configurable Fabric IQ provider`
3. `8b0d7a35` — `feat(09-05): wire optional Fabric IQ runtime provider`

## Verification

- `uv run python -m pytest tests/test_api_copilot_snapshot.py tests/test_api_copilot_investigation.py -q` — passed.
- `uv run python -m pytest tests/test_api_runtime.py tests/test_fabric_client.py tests/test_foundry_agent.py tests/test_api_copilot_snapshot.py -q` — passed.
- Full focused Phase 9 backend set from `09-VERIFICATION.md` — passed (134 tests).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Used the repository-managed Python runner**
- **Found during:** Task 1 verification
- **Issue:** The environment has no `python` executable on PATH.
- **Fix:** Re-ran compilation and tests with `uv run python`, matching the project’s existing verification convention.
- **Files modified:** None.

No other deviations; unrelated working-tree changes were preserved.

## Auth Gates

None.

## Known Stubs

None. Fabric IQ remains intentionally optional; no-configuration and provider failures are explicit unavailable states rather than fabricated enrichment.

## TDD Gate Compliance

- RED gate: `898915dd` (`test(09-05)`)
- GREEN gate: `8b0d7a35` (`feat(09-05)`)

## Self-Check: PASSED

- `src/operations/autonomous_investigation.py` exists.
- `src/api/runtime.py` exists.
- `tests/test_api_runtime.py` and `tests/test_fabric_client.py` exist.
- Commits `7338fe62`, `898915dd`, and `8b0d7a35` are present.
- All plan and focused Phase 9 verification commands passed.
