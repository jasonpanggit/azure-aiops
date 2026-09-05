---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 13
subsystem: inventory-copilot
tags: [copilot, inventory, authorization, citations, continuity]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 01
    provides: Canonical governed orchestration service and inventory specialist
provides:
  - Authenticated canonical Operations Copilot HTTP route
  - Typed Inventory v2 page adapter and `/inventory` drawer entry
  - Deterministic cited fallback with explicit coverage and uncertainty
  - Opaque principal- and scope-reauthorized thread continuity
affects: [11-02, 11-03, 11-04, 11-06]
actuals:
  tasks: 2
  commits: 4
tech-stack:
  added: []
  patterns:
    - Browser context selects governed work but is never promoted into server authority
    - Copilot availability is bound to the loaded response for the current effective scope
    - Only pattern-validated opaque thread IDs persist in browser session storage
key-files:
  created:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
  modified:
    - src/api/routers/copilot.py
    - tests/test_api_copilot_unified.py
    - web/src/app/inventory/page.tsx
    - web/src/app/inventory/page.test.tsx
    - web/src/components/ui/CopilotDrawer.tsx
    - web/src/components/ui/CopilotDrawer.test.tsx
key-decisions:
  - "Browser hints remain untrusted candidate inputs and execute only after canonical server policy validation."
  - "Browser rows are removed from canonical server citations; browser coverage is forced incomplete and browser freshness unavailable until governed tools corroborate it."
  - "The inventory launcher is unavailable while its active-tab response is loading, failed, or belongs to a different effective scope."
  - "A server-rejected thread ID is cleared before retry so the next request creates a newly authorized thread."
requirements-completed: [COP-01, COP-02, COP-03, COP-04, COP-05]
completed: 2026-09-06
status: complete
---

# Phase 11 Plan 13: Inventory Copilot Tracer Summary

**The `/inventory` page now submits exact visible context through one authenticated, policy-governed Copilot route and renders deterministic cited results without granting browser observations, hints, or continuity state any authority.**

## Accomplishments

- Added authenticated `POST /api/v1/copilot/investigations` dependency injection for the current principal and effective read scope, with bounded policy and thread errors.
- Added a strict Inventory v2 adapter carrying stable evidence IDs, filters, selection, freshness, visible/total coverage, non-Azure identity, and typed specialist hints.
- Added the Inventory drawer entry and deterministic result projection for policy status, fallback reason, coverage, uncertainty, tool results, and citations, with no approval or execution affordance.
- Persisted only a pattern-validated opaque server thread ID across remounts and recovered safely when the server expires, evicts, or rejects that ID.
- Preserved the ownership fence around `web/src/lib/services.ts` and `web/src/lib/types.ts`; neither file changed.

## Task Commits

1. **Canonical route and typed Inventory adapter** - `f90d29ba` (`feat`)
2. **Governed `/inventory` drawer projection** - `18f82fad` (`feat`)
3. **Coverage and expired-thread review fixes** - `4bcd70fd` (`fix`)
4. **Browser-authority and stale-scope review fixes** - `ae29ded2` (`fix`)

## Files Created/Modified

- `src/api/routers/copilot.py` - Authenticated canonical route, policy-input hints, browser trust-boundary sanitization, and bounded thread errors.
- `tests/test_api_copilot_unified.py` - Authentication, scope, policy, authority, fallback, coverage, uncertainty, citation, and continuity route coverage.
- `web/src/lib/copilot/page-adapters.ts` - Pure typed Inventory v2 adapter and canonical client.
- `web/src/lib/copilot/page-adapters.test.ts` - Stable identity, reorder, freshness, filtering, selection, coverage, and hint tests.
- `web/src/app/inventory/page.tsx` - Current visible Inventory projection and scope-bound drawer availability.
- `web/src/app/inventory/page.test.tsx` - Exact filtered request and unresolved-scope suppression tests.
- `web/src/components/ui/CopilotDrawer.tsx` - Canonical result rendering and opaque thread lifecycle.
- `web/src/components/ui/CopilotDrawer.test.tsx` - Fallback, citation, uncertainty, no-mutation, remount, and expired-thread recovery tests.

## Trust and Policy Decisions

- Hints are submitted as candidate specialist/tool inputs only. The server's canonical orchestration policy remains the sole authority and rejected candidates fall back through the same governed path.
- Client evidence is useful page context but is not a server citation. The route removes browser rows from canonical citations, marks browser freshness unavailable, and prevents browser-declared coverage from becoming complete.
- The Inventory launcher binds the already-loaded response to its returned requested scope. Retained rows cannot be submitted while a new scope is unresolved or failed.
- Continuity stores no scope, evidence, coverage, hints, or authority in the browser. A rejected opaque ID remains visible as an error, is removed, and Retry starts a fresh server-authorized thread.

## Independent Review

Two independent review rounds found and verified fixes for four high-confidence issues:

1. Expired or evicted thread IDs could poison all later retries in the tab. The drawer now clears only a canonical thread-not-found response and retries without the stale ID.
2. Coverage completeness incorrectly depended on freshness. Coverage now represents visible versus total rows only; freshness remains a separate uncertainty dimension.
3. Browser rows, completeness, and freshness could be promoted into canonical citations and certainty. The route now preserves them only as untrusted context and excludes browser rows from server citations.
4. Retained Inventory rows could briefly pair with a newly selected scope. Copilot now remains closed and unavailable until the active response matches the effective scope.

The targeted re-review of `ae29ded2` reported both final findings resolved with no remaining high-confidence actionable issues.

## Verification Evidence

- `.venv/bin/python -m pytest tests/test_api_copilot.py tests/test_api_copilot_investigation.py tests/test_api_copilot_snapshot.py tests/test_api_copilot_unified.py -q` - **61 passed**.
- `cd web && npm test` - **39 files passed; 254 tests passed; 15 todo**.
- `cd web && npm run lint` - **passed with no warnings or errors**.
- `cd web && npx tsc --noEmit` - **passed**.
- `.venv/bin/ruff check src tests` - **passed**.
- `.venv/bin/python -m compileall -q src tests` - **passed**.
- `git diff --check` - **passed**.

## Deviations from Plan

### Auto-fixed Review Findings

The four review fixes above strengthened the plan's declared browser-to-server trust boundary without expanding beyond the eight declared implementation/test files. No Plan 11-02 or later work, network/exposure/remediation paths, infrastructure, Terraform, deployment, or push was performed.

## User Setup Required

None.

## Next Phase Readiness

- Plan 11-13 is complete and independently reviewed.
- Later Phase 11 tracers can reuse the canonical page-adapter and opaque-thread patterns while retaining server-side policy authority.
- `.planning/STATE.md` remains unchanged as requested.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-06*
