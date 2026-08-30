---
phase: 09-consumer-pivot
plan: 07
subsystem: api
tags: [mcp, fastapi, scope, evidence, ledger, snapshots]
requires:
  - phase: 09-consumer-pivot
    provides: governed Operations tool registry, effective scope, page snapshots, and investigation ledger
provides:
  - Native bounded MCP initialize/tools-list/tools-call HTTP surface
  - Exact reviewed read-only tool catalog with registry-only dispatch
  - Snapshot submission and non-rehydrating ledger replay endpoints
  - Protocol, scope, status, budget, and audit contract tests
affects: [foundry, apim, operations-copilot]
actuals:
  tokens: 4500
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns: [JSON-RPC MCP adapter, server-derived effective scope, bounded structured audit metadata]
key-files:
  created:
    - src/operations/mcp_server.py
    - src/api/routers/mcp.py
    - tests/test_mcp_protocol.py
    - tests/test_mcp_tools.py
    - tests/test_mcp_snapshot_contract.py
    - tests/fixtures/mcp_protocol.json
  modified:
    - src/api/app.py
    - src/api/__init__.py
key-decisions:
  - "MCP exposes only the ten reviewed read-only Operations tools; all execution remains in TOOL_REGISTRY."
  - "Snapshot replay returns the recorded ledger and never silently rehydrates provider state."
patterns-established:
  - "Protocol errors are JSON-RPC errors; operational empty, unavailable, and denied states remain structured tool data."
requirements-completed: [INV-09, INV-10]
coverage:
  - id: D1
    description: "Bounded, authenticated, scope-safe MCP protocol and reviewed read-only catalog"
    requirement: INV-09
    verification:
      - kind: unit
        ref: "tests/test_mcp_protocol.py"
        status: pass
      - kind: unit
        ref: "tests/test_mcp_tools.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Typed page snapshot submission with evidence-linked ledger replay"
    requirement: INV-10
    verification:
      - kind: unit
        ref: "tests/test_mcp_snapshot_contract.py"
        status: pass
      - kind: integration
        ref: "uv run python -m pytest tests/test_mcp_protocol.py tests/test_mcp_tools.py tests/test_mcp_snapshot_contract.py tests/test_api_runtime.py -q"
        status: pass
    human_judgment: false
---

# Phase 9 Plan 7: Operations MCP Summary

**Governed read-only Operations MCP facade with bounded JSON-RPC transport, server-derived scope, evidence-aware statuses, and snapshot ledger replay.**

## Performance

- **Duration:** approximately 20 min
- **Started:** 2026-08-28T17:12:38+08:00
- **Completed:** 2026-08-28
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Added native `/api/v1/mcp` initialize, tools/list, and tools/call transport.
- Enforced reviewed catalog, strict arguments, message/argument/response/call budgets, and authenticated effective scope.
- Added snapshot submission/replay seam and audit metadata while preserving ToolResult status/evidence serialization.
- Added protocol fixtures and focused contract/security tests.

## Task Commits

1. **Task 1: Trace one governed Network MCP call end to end** - `ccc80f8b` (feat)
2. **Task 2 RED: Add MCP audit metadata contract** - `202d6d38` (test)
3. **Task 2 GREEN: Harden MCP audit and response budgets** - `fa41f695` (feat)

## Tests

- `uv run python -m pytest tests/test_mcp_protocol.py tests/test_mcp_tools.py tests/test_mcp_snapshot_contract.py tests/test_api_runtime.py -q` — passed.
- `uv run python -m pytest tests/test_mcp_protocol.py tests/test_mcp_tools.py tests/test_mcp_snapshot_contract.py tests/test_inventory_consumer_guards.py tests/test_foundry_agent.py tests/test_fabric_client.py -q` — passed.

## Deviations from Plan

### Auto-fixed Issues

**1. Rule 3 - Blocking import cycle**
- **Found during:** Task 2 RED
- **Issue:** Importing the MCP server through the API app caused a circular initialization between `api`, `operations.tools`, and the router.
- **Fix:** Lazily import the MCP registry at dispatch time and make API package exports lazy.
- **Files modified:** `src/operations/mcp_server.py`, `src/api/__init__.py`
- **Verification:** Focused MCP suite passed.
- **Committed in:** `202d6d38`

**Total deviations:** 1 auto-fixed (Rule 3).

## Issues Encountered

Pre-existing unrelated working-tree changes were left untouched and unstaged.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The governed MCP seam is ready for the later APIM and client integration plans. Plans 09-08 and 09-09 were not executed.

## Self-Check: PASSED

- All implementation, test, fixture, and summary files exist.
- Task commits `ccc80f8b`, `202d6d38`, and `fa41f695` exist in git history.
- `git diff --check` passed for the repository.
