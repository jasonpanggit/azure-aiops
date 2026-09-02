---
phase: 10-fabric-medallion-capability-expansion
plan: 11
subsystem: fabric-data-agent-grounding
tags: [fabric, mcp, pydantic, otel, med-08]

requires:
  - phase: 10-fabric-medallion-capability-expansion (10-09)
    provides: Gold topology restoration baseline and deployment conventions consumed by grounding clients.
provides:
  - "Fail-closed MCP retrieval client (`query_gold_grounding`) with bounded retry/backoff and explicit unavailable errors."
  - "Typed Gold grounding contract (`GoldGroundedCitation`/`GoldGroundedFinding`) with citation-presence and scoped-resource validators."
  - "Gold grounding telemetry meter with low-cardinality counters/histograms and reason truncation discipline."
affects: [10-12-fabric-medallion-capability-expansion, gold-grounding-specialist, medallion-health]

actuals:
  tokens: 4193
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "MCP tool-call retrieval is isolated in a stateless client and never acts as a second orchestrator."
    - "Fail-closed structured output uses Pydantic model validation with degraded fallback after bounded retries."
    - "Telemetry follows existing no-payload/no-resource-id recording discipline."

key-files:
  created:
    - src/fabric/gold_grounding_client.py
    - src/fabric_pipelines/gold_grounding_contract.py
    - src/operations/gold_grounding_metrics.py
    - tests/test_gold_grounding_client.py
    - tests/test_gold_grounded_finding.py
  modified:
    - src/fabric/gold_grounding_client.py
    - src/fabric_pipelines/gold_grounding_contract.py
    - src/operations/gold_grounding_metrics.py
    - tests/test_gold_grounding_client.py
    - tests/test_gold_grounded_finding.py

key-decisions:
  - "Use explicit `GoldGroundingUnavailable` for MCP transport/json/isError failures so callers degrade instead of fabricating evidence."
  - "Enforce citation presence and ARM scope shape at model-construction time via Pydantic validators."
  - "Record only degraded boolean and truncated reason in query telemetry attributes."

patterns-established:
  - "Line-delimited Data Agent parsing tolerates prose/fences, validates each JSON line, and degrades after retry budget exhaustion."
  - "Gold-grounding metrics include safety/health counters without high-cardinality payload dimensions."

requirements-completed: [MED-08]

coverage:
  - id: D1
    description: "Gold MCP query client retries transient failures and fails closed on MCP isError."
    requirement: "MED-08"
    verification:
      - kind: unit
        ref: "pytest tests/test_gold_grounding_client.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Gold grounding contract enforces citation/resource-id validity and degraded fallback on unparseable evidence."
    requirement: "MED-08"
    verification:
      - kind: unit
        ref: "pytest tests/test_gold_grounded_finding.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Combined MED-08 grounding client + contract suite passes deterministically."
    requirement: "MED-08"
    verification:
      - kind: unit
        ref: "pytest tests/test_gold_grounding_client.py tests/test_gold_grounded_finding.py -q"
        status: pass
    human_judgment: false

duration: 4min
completed: 2026-09-02
status: complete
---

# Phase 10 Plan 11: Gold-grounding MCP retrieval client summary

**Shipped a fail-closed Gold-grounding client, typed evidence contract, and privacy-safe telemetry so MED-08 retrieval degrades safely without fabricating citations.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-09-01T16:38:33Z
- **Completed:** 2026-09-01T16:43:05Z
- **Tasks:** 3/3 completed
- **Files modified:** 5

## Accomplishments

- Implemented `query_gold_grounding()` with MCP `tools/call`, exponential retry backoff, and explicit `GoldGroundingUnavailable` degradation on transport/json/MCP-isError failures.
- Added `GoldGroundedCitation` and `GoldGroundedFinding` Pydantic contracts with mandatory citation fields, `citations` min-length enforcement, and ARM-ID scope validation.
- Added line-delimited Gold evidence parsing that retries validation failures and returns a degraded finding after exhausting retries.
- Added `GoldGroundingMetrics` with the AI-SPEC-defined counters/histograms and low-cardinality `record_query()` attributes.
- Added deterministic unit tests validating retry/degrade semantics, contract fail-closed behavior, and telemetry privacy constraints.

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED):** `217cc7ba` (`test`) — failing MCP client retry/degrade tests.
2. **Task 1 (TDD GREEN):** `662b8d92` (`feat`) — fail-closed MCP query client implementation.
3. **Task 2 (TDD RED):** `4c30fe98` (`test`) — failing Gold grounded contract/validator tests.
4. **Task 2 (TDD GREEN):** `29a63d48` (`feat`) — Pydantic contract + degraded parser implementation.
5. **Task 3 (TDD RED):** `6d8e2854` (`test`) — metrics low-cardinality/privacy contract test.
6. **Task 3 (TDD GREEN):** `f6767f06` (`feat`) — Gold grounding OTel meter implementation.

**Plan metadata:** pending final docs/state commit.

## Files Created/Modified

- `src/fabric/gold_grounding_client.py` — MCP tools/call client with bounded retry and fail-closed unavailable exception.
- `src/fabric_pipelines/gold_grounding_contract.py` — Gold citation/finding models and line-delimited parser with degraded fallback.
- `src/operations/gold_grounding_metrics.py` — Gold-grounding OpenTelemetry counters/histograms and query recorder.
- `tests/test_gold_grounding_client.py` — retry/degrade/isError and telemetry privacy tests.
- `tests/test_gold_grounded_finding.py` — citation/finding validation and parser degradation tests.

## Decisions Made

- Implemented AI-SPEC §3 `query_gold_grounding()` behavior verbatim (2 retries, exponential backoff, immediate raise on `isError`).
- Enforced critical fail-closed guardrails in type validation (`citations` min length, `/subscriptions/` resource ID prefix) before narration boundary use.
- Telemetry remains counters/histograms only and truncates degradation reason to 40 chars to avoid high-cardinality leakage.

## Deviations from Plan

None - plan executed exactly as written.

## Auth Gates

None.

## Known Stubs

None found in plan-owned source/test changes.

## Issues Encountered

None beyond expected TDD red→green iteration.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MED-08 Gold grounding retrieval/contract core is complete and deterministic.
- Ready for downstream specialist wiring plans that consume `query_gold_grounding()` and `GoldGroundedFinding`.

## Self-Check: PASSED

- Verified `src/fabric/gold_grounding_client.py` exists.
- Verified `src/fabric_pipelines/gold_grounding_contract.py` exists.
- Verified `src/operations/gold_grounding_metrics.py` exists.
- Verified `tests/test_gold_grounding_client.py` exists.
- Verified `tests/test_gold_grounded_finding.py` exists.
- Verified `.planning/phases/10-fabric-medallion-capability-expansion/10-11-SUMMARY.md` exists.
- Verified task commit hashes exist in git history: `217cc7ba`, `662b8d92`, `4c30fe98`, `29a63d48`, `6d8e2854`, `f6767f06`.
