---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 02
subsystem: operations-copilot-evidence
tags: [copilot, snapshots, evidence, authorization, deterministic-identity]
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 01
    provides: Canonical orchestration contract and policy
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 13
    provides: Inventory canonical route and typed page adapter
provides:
  - Strict evidence snapshot v2 wire contract shared by backend and browser
  - Authorization-first Azure and domain identity canonicalization
  - Deterministic duplicate, conflict, ranking, retention, and citation closure
  - Coverage-, freshness-, and insufficiency-aware canonical evidence
  - Bounded Inventory adapter with backend-compatible stable keys and selectors
affects: [11-03, 11-06, 11-07, 11-08, 11-09, 11-10, 11-11, 11-12, 11-14, 11-15, 11-16]
actuals:
  tasks: 2
  commits: 13
tech-stack:
  added: []
  patterns:
    - Browser evidence is observational and is reauthorized before retention
    - Stable identity excludes row order and observation time
    - Conflict variants are retained atomically and material claims remain citation-closed
    - Browser bounds and selector validation mirror the canonical server route
key-files:
  created:
    - tests/test_page_context_v2.py
    - tests/test_api_copilot_snapshot_v2.py
  modified:
    - src/operations/orchestration_contract.py
    - src/operations/page_context.py
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
key-decisions:
  - "Azure identity derives only from canonical ARM IDs; non-Azure identity is a server-resolved namespace, kind, and source key."
  - "Scope authorization happens before ranking or retention, and browser observations never confer authority."
  - "Conflicting variants share one stable claim identity and are retained or rejected as an atomic set."
  - "Incomplete coverage, unavailable freshness, and missing usable evidence produce explicit uncertainty or insufficiency."
  - "Inventory filter, sort, pagination, and selector context remains bounded observational data rather than a top-level authority assertion."
requirements-completed: [COP-02, COP-04]
completed: 2026-09-06
status: complete
---

# Phase 11 Plan 02: Evidence Snapshot v2 Summary

**Operations Copilot now receives one bounded, deterministic snapshot-v2 contract that preserves canonical Azure and domain identity, conflicts, coverage, freshness, uncertainty, and retained citation closure without trusting browser authority.**

## Accomplishments

- Added strict backend contracts for typed entities, material claims, evidence rows, coverage, freshness, canonical variants, conflicts, and insufficiency classification.
- Implemented authorization-first canonicalization with deterministic SHA-256 identity, exact-duplicate merging, atomic conflict retention, stable ranking, strict bounds, and citation closure.
- Added shared browser wire types and a pure Inventory adapter with Python-compatible case folding and stable SHA-256 evidence identity.
- Preserved visible filters, sort, pagination, selection, empty-result context, and provider uncertainty while matching canonical route selector limits.
- Moved canonical request I/O into `services.ts` and retained the existing adapter import as a compatibility entry point.
- Added adversarial backend, API, adapter, parity, conflict, reorder, unavailable-source, Unicode, empty-page, and oversized-input coverage.

## Task Commits

1. **Task 1 RED: Canonical snapshot-v2 evidence requirements** - `804e9bda`
2. **Task 1 implementation: Canonical evidence pipeline** - `19914ae1`
3. **Task 1 review fixes: Retention edge cases** - `fc801c3b`
4. **Task 1 review fixes: Citation closure** - `339553a3`
5. **Task 1 review fixes: Material-claim ordering** - `b210fff6`
6. **Task 2 RED: Complete typed adapter contract** - `c9568722`
7. **Task 2 implementation: Shared types and pure adapter** - `70b23c55`
8. **Task 2 review fixes: Determinism and bounds** - `9032c2b6`
9. **Task 2 review fixes: Unicode identity** - `d85ac5ba`
10. **Task 2 review fixes: Runtime parity** - `280226cc`
11. **Task 2 review fixes: Inventory selector context** - `6a6b182c`
12. **Task 2 review fixes: Selector field bounds** - `46a64d9e`
13. **Task 2 review fixes: Assembled selector limits** - `a037a84d`

The branch also contains merge commit `6e00b84d`, which merged `origin/main` at `4dd346b6` without rebasing and preserved the accepted Task 1 work plus Phase 12/Exposure changes.

## Files Created/Modified

- `src/operations/orchestration_contract.py` - Strict snapshot-v2 input and canonical output models with list, field, row, and snapshot bounds.
- `src/operations/page_context.py` - Scope-first identity resolution, stable deduplication, conflict grouping, ranking, retention, coverage, uncertainty, and citation closure.
- `tests/test_page_context_v2.py` - Canonicalization, ordering, scope, retention, freshness, coverage, conflict, and insufficiency regressions.
- `tests/test_api_copilot_snapshot_v2.py` - Strict API-boundary and browser-authority regressions.
- `web/src/lib/types.ts` - Shared snapshot-v2 entity, evidence, freshness, coverage, material-claim, request, and result contracts.
- `web/src/lib/services.ts` - Authenticated canonical investigation request client.
- `web/src/lib/copilot/page-adapters.ts` - Pure bounded Inventory adapter, deterministic serializer, stable key construction, and compatibility export.
- `web/src/lib/copilot/page-adapters.test.ts` - Adapter wire parity, reorder, Unicode, conflict, empty-page, freshness, selection, and bounds coverage.

## Trust and Determinism Decisions

- Browser-provided namespace, kind, source key, scope, and selection remain observations. The server resolves domain authority and validates ARM scope before retaining evidence.
- Stable evidence identity hashes normalized source, source key, canonical entity key, and claim type. Observation timestamps and input order do not participate.
- Exact duplicates merge deterministically; contradictory data remains separate variants under one stable identity.
- Material claims are validated against both submitted and retained evidence, preventing aliases to discarded rows.
- The browser uses the deployed Python 3.12 Unicode case-fold behavior and locale-independent code-point ordering so stable keys do not vary by browser locale.
- Provider freshness is aggregated under the evidence source used by canonicalization, while provider-specific uncertainty remains visible to the drawer.
- Empty filtered pages retain one bounded context observation while coverage correctly remains zero visible rows.

## Independent Review

Independent reviews found and verified fixes for:

- Partial conflict-set truncation, browser-controlled canonical identity, order-sensitive hashes, optimistic missing freshness, citation overflow, discarded-reference aliases, freshness priority, bounded uncertainty text, and material-claim ordering in the backend.
- Selected-row compatibility, commutative duplicate merging, locale-independent ordering, Unicode case-fold parity, exact field/row/snapshot bounds, source-aligned freshness, deterministic conflict selection, empty-page filter retention, and canonical selector limits in the browser adapter.

The final review reported no remaining high-confidence findings.

## Verification Evidence

- `python3 -m pytest tests/test_page_context_v2.py tests/test_api_copilot_snapshot_v2.py tests/test_orchestration_policy.py tests/test_api_copilot_unified.py tests/test_api_copilot_snapshot.py tests/test_page_context.py tests/test_api_copilot_investigation.py -q` - **89 passed**.
- `cd web && npm test` - **39 files passed; 268 tests passed; 15 todo**.
- `cd web && npx tsc --noEmit` - **passed**.
- `cd web && npm run lint` - **passed with no warnings or errors**.
- `python3 -m ruff check src/operations/orchestration_contract.py src/operations/page_context.py tests/test_page_context_v2.py tests/test_api_copilot_snapshot_v2.py` - **passed**.
- `python3 -m compileall -q src` - **passed**.
- Deployed runtime Unicode parity probe (Node 22 versus Python 3.12) - **zero case-fold mismatches**.
- `git diff --check` - **passed**.

## Deviations from Plan

### Auto-fixed Review Findings

The independent review fixes strengthened the declared browser-to-server trust boundary and deterministic parity without expanding beyond the plan's eight source/test files. The canonical API compatibility export was retained so existing Inventory and drawer consumers required no out-of-scope edits.

### Environment

The repository-local `.venv` was absent, so backend pytest, Ruff, and compileall gates ran with the available project Python. Existing web dependencies were restored from `web/package-lock.json` with `npm ci`; no dependency manifests changed.

## User Setup Required

None.

## Next Phase Readiness

- Both Plan 11-02 tasks are complete and independently reviewed.
- Later page adapters can reuse the shared v2 types, stable identity helper, deterministic serialization, strict bounds, and observational-context pattern.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged as requested.

---
*Phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p*
*Completed: 2026-09-06*
