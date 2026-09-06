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
  commits: 5
tech-stack:
  added: []
  patterns:
    - Browser context selects governed work but is never promoted into server authority
    - Browser request identity is tracked separately from the server-derived effective scope
    - Inventory selectors are resolved through scope-enforcing server read providers
    - Transcript and opaque thread continuity are bound to normalized page context
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
  - "Browser rows are removed from canonical server citations; only server-resolved tool evidence is cited."
  - "The inventory launcher is unavailable while its active-tab response is loading, failed, or stale, while its request uses the response's server-derived effective scope."
  - "Visible tab, filter, and selected-group context becomes bounded selectors that remain subject to canonical policy and server-side scope enforcement."
  - "A server-rejected thread ID is cleared before retry so the next request creates a newly authorized thread."
  - "Each normalized context owns one transcript, one opaque thread, and at most one in-flight request."
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
- Converted visible OS, Installed Software, and Azure context into bounded selectors that are re-resolved through scope-enforcing server providers; browser observations never become citations.
- Persisted only a pattern-validated opaque server thread ID per normalized page context, redacted stale transcripts, ignored stale responses, and serialized same-context turns.
- Preserved the ownership fence around `web/src/lib/services.ts` and `web/src/lib/types.ts`; neither file changed.

## Task Commits

1. **Canonical route and typed Inventory adapter** - `f90d29ba` (`feat`)
2. **Governed `/inventory` drawer projection** - `18f82fad` (`feat`)
3. **Coverage and expired-thread review fixes** - `4bcd70fd` (`fix`)
4. **Browser-authority and stale-scope review fixes** - `ae29ded2` (`fix`)
5. **Governed selector, context isolation, and final review fixes** - `84b519a6` (`fix`)

## Files Created/Modified

- `src/api/routers/copilot.py` - Authenticated canonical route, policy-input hints, bounded server selectors, scope-enforcing Inventory execution, server-only citations, evidence limits, and bounded thread errors.
- `tests/test_api_copilot_unified.py` - Authentication, scope, policy, authority, selector, software, evidence-bound, fallback, coverage, uncertainty, citation, and continuity route coverage.
- `web/src/lib/copilot/page-adapters.ts` - Pure typed Inventory v2 adapter and canonical client.
- `web/src/lib/copilot/page-adapters.test.ts` - Stable identity, reorder, freshness, filtering, selection, coverage, and hint tests.
- `web/src/app/inventory/page.tsx` - Current visible Inventory projection, request freshness identity, raw ARM selectors, and server-scope-bound canonical requests.
- `web/src/app/inventory/page.test.tsx` - Exact filtered request, RBAC-narrowed scope, raw ARM selector, and unresolved-scope suppression tests.
- `web/src/components/ui/CopilotDrawer.tsx` - Canonical result rendering, context-bound opaque thread lifecycle, transcript redaction, stale-response suppression, and serialized turns.
- `web/src/components/ui/CopilotDrawer.test.tsx` - Fallback, citation, uncertainty, no-mutation, remount, expiry, context change, stale response, and request serialization tests.

## Trust and Policy Decisions

- Hints are submitted as candidate specialist/tool inputs only. The server's canonical orchestration policy remains the sole authority and rejected candidates fall back through the same governed path.
- Client evidence is useful selector context but is not a server citation. The route discards browser rows before orchestration, resolves bounded OS/software/Azure selectors against the authorized server scope, and returns only `tool:` citations.
- The Inventory launcher binds rows to a browser request fingerprint while canonical scope comes from the matching response's server-derived `requested_scope`, including RBAC-narrowed grants.
- Exact Installed Software reads use the scoped Inventory provider rather than the generic resource port. Exact OS/PaaS groups use the same provider, while generic OS/Azure type reads use the governed `inventory_resources` tool.
- Server evidence is capped at 255 citations, preserves the full result total, and emits an explicit truncation warning.
- Continuity stores no scope, evidence, coverage, hints, or authority in the browser. Context changes redact the transcript, clear the old opaque thread, and invalidate old responses; a rejected opaque ID remains visible as an error and Retry starts a fresh server-authorized thread.

## Independent Review

Independent review rounds found and verified fixes for ten high-confidence issues:

1. Expired or evicted thread IDs could poison all later retries in the tab. The drawer now clears only a canonical thread-not-found response and retries without the stale ID.
2. Coverage completeness incorrectly depended on freshness. Coverage now represents visible versus total rows only; freshness remains a separate uncertainty dimension.
3. Browser rows, completeness, and freshness could be promoted into canonical citations and certainty. The route now preserves them only as untrusted context and excludes browser rows from server citations.
4. Retained Inventory rows could briefly pair with a newly selected scope. Copilot now remains closed and unavailable until the active response matches the effective scope.
5. RBAC-narrowed server scope hid the launcher because it was compared directly with browser scope. Request freshness and server-derived canonical scope are now tracked separately.
6. Visible tab, filter, selected entity, and software context did not influence governed retrieval. Bounded selectors now drive scope-enforcing server reads, with Installed Software routed through its dedicated Inventory provider.
7. Scope, tab, or page changes retained transcripts and allowed old responses to append. Normalized context fingerprints now redact turns, partition opaque threads, and invalidate stale requests.
8. Azure filter labels such as `Container Apps` were sent where raw ARM types were required. Option values and canonical selectors now retain `microsoft.app/containerapps` while labels remain friendly.
9. Same-context requests could race into different server threads. A synchronous in-flight guard now serializes every starter, Enter, Send, and Retry path.
10. Large PaaS groups could exceed the 256-citation contract. Server evidence is capped at 255, full totals remain structured, and truncation is explicit.

The final targeted re-review reported all six corrective findings resolved with no remaining high-confidence actionable issues.

## Verification Evidence

- `.venv/bin/python -m pytest -o addopts='' -q tests/test_api_copilot.py tests/test_api_copilot_investigation.py tests/test_api_copilot_snapshot.py tests/test_api_copilot_unified.py` - **65 passed; 1 dependency deprecation warning**.
- `cd web && npm test` - **39 files passed; 260 tests passed; 15 todo**.
- `cd web && npm run lint` - **passed with no warnings or errors**.
- `cd web && npx tsc --noEmit` - **passed**.
- `.venv/bin/ruff check src tests` - **passed**.
- `.venv/bin/python -m compileall -q src tests` - **passed**.
- `git diff --check` - **passed**.

## Deviations from Plan

### Auto-fixed Review Findings

The ten review fixes above strengthened the plan's declared browser-to-server trust boundary without expanding beyond the eight declared implementation/test files. No Plan 11-02 or later work, network/exposure/remediation paths, infrastructure, Terraform, deployment, or push was performed.

## User Setup Required

None.

## Next Phase Readiness

- Plan 11-13 is complete and independently reviewed.
- Later Phase 11 tracers can reuse the canonical page-adapter and opaque-thread patterns while retaining server-side policy authority.
- `.planning/STATE.md` remains unchanged as requested.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-06*
