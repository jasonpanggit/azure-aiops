---
phase: 10-fabric-medallion-capability-expansion
plan: 12
subsystem: fabric-data-agent-grounding
tags: [fabric, foundry, maf, grounding, inventory, med-08]

requires:
  - phase: 10-fabric-medallion-capability-expansion (10-11)
    provides: Gold-grounding MCP client, typed contract parser, and grounding telemetry meter consumed by specialist wiring.
provides:
  - "Gold-grounding specialist pre-stage merges evidence into the existing narration context with safe degradation."
  - "Inventory-authority precedence guardrail cross-checks Gold citations and surfaces explicit conflict notices."
  - "Evaluation harness reference set expanded to 23 deterministic cases with a baseline scaffold for first live run."
affects: [copilot-specialists, evaluation-harness, medallion-grounding, inventory-authority]

actuals:
  tokens: 9481
  tasks: 4
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Gold evidence remains a qualifying layer inside the existing single-turn narration payload."
    - "Inventory read-port authority is enforced pre-narration via per-citation cross-check and conflict escalation."
    - "Gold-grounding evaluation remains deterministic and out-of-CI with scheduled/manual execution."

key-files:
  created:
    - src/operations/gold_grounding_specialist.py
    - tests/test_gold_grounding_specialist.py
    - .planning/eval/gold-grounding-baseline.json
  modified:
    - src/operations/foundry_agent.py
    - scripts/evaluate_agents.py
    - src/operations/gold_grounding_specialist.py
    - tests/test_gold_grounding_specialist.py

key-decisions:
  - "Kept Gold-grounding in the existing context handoff to narration; no second prompt turn/orchestrator path introduced."
  - "Implemented fail-closed inventory precedence by folding explicit citation/resource conflict notices into narration context and incrementing telemetry per conflicting citation."
  - "Committed a placeholder baseline artifact with empty summary/results to avoid fabricated evaluation numbers."

patterns-established:
  - "Async-safe specialist execution path awaits MAF calls directly and preserves safe degradation boundaries."
  - "Citation truncation ranking stays confidence-desc/as_of-desc while ontology payload remains untouched."

requirements-completed: [MED-08]

coverage:
  - id: D1
    description: "Gold-grounding specialist merges evidence safely and still answers when Gold-grounding is unavailable."
    requirement: MED-08
    verification:
      - kind: unit
        ref: "pytest tests/test_gold_grounding_specialist.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Inventory-authority precedence guardrail detects not-found/ownership/lifecycle conflicts and records per-citation telemetry."
    requirement: MED-08
    verification:
      - kind: unit
        ref: "pytest tests/test_gold_grounding_specialist.py -q -k inventory"
        status: pass
    human_judgment: false
  - id: D3
    description: "Gold-grounding evaluation dataset includes all 13 AI-SPEC additions (23 total cases)."
    requirement: MED-08
    verification:
      - kind: other
        ref: "cd scripts && python3 -c \"from evaluate_agents import CASES; assert len(CASES) == 23, len(CASES)\""
        status: pass
    human_judgment: false
  - id: D4
    description: "CI selector for grounding/relationship deterministic checks passes with specialist tests."
    requirement: MED-08
    verification:
      - kind: unit
        ref: "pytest tests/ -k \"gold_grounding or gold_grounded_finding or relationship_suggestion\" -q"
        status: pass
    human_judgment: false

duration: 7min
completed: 2026-09-02
status: complete
---

# Phase 10 Plan 12: Gold-grounding specialist wiring summary

**Shipped Gold-grounding specialist context merge with fail-closed inventory-authority conflict signaling and full 23-case deterministic evaluation coverage for MED-08.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-01T16:58:52Z
- **Completed:** 2026-09-01T17:05:56Z
- **Tasks:** 4/4 completed
- **Files modified:** 5

## Accomplishments

- Implemented `answer_with_gold_grounding()` safe-degradation flow that merges Gold evidence into the existing narration context and preserves ontology-only continuity on failures.
- Enforced inventory-authority precedence by cross-checking citation resource IDs against `InventoryReadPort.get_resource(...)` and folding explicit conflicts into narration context.
- Added/verified all 13 required AI-SPEC dataset cases in `scripts/evaluate_agents.py` for a deterministic 23-case set.
- Added baseline scaffold `.planning/eval/gold-grounding-baseline.json` for first live/scheduled evaluation without fabricated baseline values.

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED):** `0742a152` (`test`) — failing Gold-grounding specialist behavior tests.
2. **Task 1 (TDD GREEN):** `89cb281b` (`feat`) — Gold-grounding specialist implementation + token-bound narration path support.
3. **Task 2:** `2ecf9570` (`feat`) — evaluate harness extended with 13 AI-SPEC Gold-grounding cases (23 total).
4. **Task 3:** `dc02fc3f` (`chore`) — baseline artifact scaffold added with empty structure for first live run.
5. **Task 4 (TDD RED):** `3dd775f6` (`test`) — failing inventory-authority precedence guardrail tests.
6. **Task 4 (TDD GREEN):** `0f11ff7a` (`feat`) — per-citation inventory conflict cross-check + context conflict notice + telemetry increments.

**Plan metadata:** `ae7f2a9e` (`docs`) — summary/state/roadmap synchronization.

## Files Created/Modified

- `src/operations/gold_grounding_specialist.py` — Gold-grounding merge path, truncation, and inventory-authority conflict cross-check logic.
- `src/operations/foundry_agent.py` — narration `max_output_tokens` support path used by Gold-grounding specialist flow.
- `scripts/evaluate_agents.py` — expanded deterministic reference case tuple to 23 entries.
- `tests/test_gold_grounding_specialist.py` — behavior + inventory guardrail unit coverage.
- `.planning/eval/gold-grounding-baseline.json` — placeholder baseline scaffold for first live scheduled run.

## Decisions Made

- Kept Gold-grounding evidence in the same existing narration payload to preserve single-orchestrator boundaries.
- Used inventory read-port responses as identity/lifecycle authority and surfaced disagreements explicitly in context for fail-closed handling.
- Left baseline metrics intentionally empty to preserve evaluation integrity until real run data is captured.

## Deviations from Plan

None - plan executed exactly as written.

## Auth Gates

None.

## Known Stubs

| File | Line | Stub | Reason |
|------|------|------|--------|
| `.planning/eval/gold-grounding-baseline.json` | 5 | `"status": "placeholder"` | Intentional scaffold pending first live/scheduled evaluation run; no fabricated baseline values committed. |

## Threat Flags

None.

## Issues Encountered

- Best-effort WINDOWS ledger append for the intentional baseline placeholder
  stub failed because `.planning/WINDOWS.md` currently contains a pre-existing
  invalid kind value (`"live-source-data"`). Logged to phase
  `deferred-items.md`; plan deliverables remained complete.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- MED-08 specialist grounding path and inventory-authority guardrail behavior are now codified and test-covered.
- Scheduled/manual evaluation can now populate the scaffolded baseline artifact.

## Self-Check: PASSED

- Verified `src/operations/gold_grounding_specialist.py` exists.
- Verified `src/operations/foundry_agent.py` exists.
- Verified `scripts/evaluate_agents.py` exists.
- Verified `tests/test_gold_grounding_specialist.py` exists.
- Verified `.planning/eval/gold-grounding-baseline.json` exists.
- Verified `.planning/phases/10-fabric-medallion-capability-expansion/10-12-SUMMARY.md` exists.
- Verified task commit hashes exist in git history: `0742a152`, `89cb281b`, `2ecf9570`, `dc02fc3f`, `3dd775f6`, `0f11ff7a`.
