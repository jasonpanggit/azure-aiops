---
phase: 09-consumer-pivot
plan: 04
subsystem: api
tags: [fastapi, pydantic, copilot, scope, freshness, network]
requires:
  - phase: 09-consumer-pivot
    provides: typed contextual snapshot API and deterministic Network findings
provides:
  - Canonical resource-ID validation for selected and evidence snapshot resources
  - Freshness-aware, non-actionable stale and partial Network findings
  - Contextual ledger warnings for degraded source freshness
affects: [consumer-pivot, network-copilot, inventory-scope]
tech-stack:
  added: []
  patterns: [server-derived ARM identity scope, deterministic freshness downgrade]
key-files:
  created: []
  modified:
    - src/operations/page_context.py
    - src/operations/autonomous_investigation.py
    - tests/test_page_context.py
    - tests/test_api_copilot_snapshot.py
decisions:
  - "Canonical Azure resource IDs, not browser-declared attributes, are the authorization identity for contextual snapshots."
  - "Any stale, partial, or unavailable source freshness downgrades otherwise verified findings to medium-confidence hypotheses."
metrics:
  duration: 2min
  completed: 2026-08-28
  status: complete
actuals:
  tokens: 3486
  tasks: 2
  commits: 4
status: complete
---

# Phase 09 Plan 04: Snapshot Integrity Summary

**Contextual Copilot now rejects unverifiable or out-of-scope resource identities and visibly downgrades degraded Network evidence instead of presenting it as actionable.**

## Accomplishments

- Added canonical Azure resource-ID parsing and server-derived scope checks for every selected resource and every evidence row carrying a resource ID.
- Rejected malformed IDs, client attribute/ID disagreements, and identities outside the effective read scope before contextual orchestration.
- Centralized deterministic finding classification so stale, partial, and unavailable freshness cannot produce verified, high-confidence, actionable findings.
- Preserved `empty`, `unavailable`, and `denied` row statuses, bounded next checks, evidence citations, and explicit source-freshness warnings in the contextual ledger response.
- Added direct and API regression coverage for ID-only resources, evidence scope, malformed IDs, freshness degradation, non-OK statuses, and route warnings.

## Task Commits

1. `3cf73244` — `test(09-04): cover contextual snapshot scope identity gaps`
2. `ec41395b` — `feat(09-04): enforce canonical snapshot resource scope`
3. `5bc6f65f` — `test(09-04): cover stale and partial finding semantics`
4. `d1fe3b83` — `feat(09-04): downgrade stale contextual findings`

## Verification

- `uv run python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py -q` — passed.
- `uv run python -m pytest tests/test_page_context.py tests/test_api_copilot_snapshot.py tests/test_network_analysis.py -q` — passed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Preserve freshness warnings in the contextual ledger**
- **Found during:** Task 2
- **Issue:** The route returned ledger warnings but the orchestration layer did not add warnings for stale, partial, or unavailable freshness records.
- **Fix:** Added explicit source-freshness warnings while retaining deterministic findings.
- **Files modified:** `src/operations/autonomous_investigation.py`
- **Commit:** `d1fe3b83`

## Known Stubs

None. Empty defaults on optional snapshot model fields are contract defaults, not rendered or analysis stubs.

## Self-Check: PASSED

- `src/operations/page_context.py` exists.
- `src/operations/autonomous_investigation.py` exists.
- `tests/test_page_context.py` and `tests/test_api_copilot_snapshot.py` exist.
- Commits `3cf73244`, `ec41395b`, `5bc6f65f`, and `d1fe3b83` are present.
- Both plan verification commands passed.
