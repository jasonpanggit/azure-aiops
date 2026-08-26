---
phase: 01-evidence-and-situation-foundation
verified: 2026-08-25T14:40:58Z
status: human_needed
score: 11/12 must-haves verified
behavior_unverified: 1
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 11/12
  gaps_closed:
    - "Audit events now enforce their own scope_snapshot before serialization."
    - "Durable source-status rows, evidence confidence, and timestamp-derived freshness are now rendered and tested."
    - "Rejected audit reads now render as service-unavailable rather than successful empty history."
    - "Queue regression coverage now covers loading, search, P1/P2/P3, pagination, both empty states, errors, scope reload, and keyboard-reachable actions."
    - "The Phase 1 goal is a valid MVP user story."
  gaps_remaining:
    - "Authenticated fixture-backed API detail/audit smoke and desktop/tablet/mobile browser walkthrough remain unobserved in this terminal-only verification."
  regressions: []
behavior_unverified_items:
  - truth: "The approved UI contract is complete across responsive presentation and keyboard focus-return behavior."
    test: "Run the durable queue/detail walkthrough at desktop, tablet, and mobile widths; open and close an evidence drawer with Escape and inspect focus return."
    expected: "The first queue columns and actions remain usable at narrow widths, source trust remains readable, and focus returns to the evidence trigger after closing."
    why_human: "The repository tests prove state transitions and keyboard reachability in jsdom, but not rendered layout, viewport behavior, or integrated browser focus behavior."
human_verification:
  - test: "Authenticated fixture-backed local API walkthrough"
    expected: "The selected scope returns a successful collection envelope, a durable detail envelope containing evidence and source_status, and a service audit envelope; an empty audit remains distinct from an audit service failure."
    why_human: "The running API requires an authenticated configured token and fixture-backed durable data. This verification did not reuse or expose credentials; the unauthenticated smoke request correctly returned 401 and no detail ID was available."
  - test: "Responsive and keyboard operator walkthrough"
    expected: "At desktop/tablet/mobile widths, scope/filter reloads show loading, the two empty states are distinct, source-status and evidence trust facts are visible, linked entities and newest-first audit remain bounded, tables keep their first columns usable, Escape closes the evidence drawer and returns focus, and read-only labels remain 'View future-phase candidate' / 'Save view locally'."
    why_human: "Visual hierarchy, responsive overflow, real browser focus return, and the complete integrated operator flow cannot be established by static inspection or mocked component tests."
---

# Phase 1: Evidence and Situation Foundation Verification Report

**Phase Goal:** As a platform operator, I want to open a durable authorized situation and inspect its qualified evidence and audit history, so that I can trust the operational picture before investigation or action.
**Verified:** 2026-08-25T14:40:58Z
**Status:** human_needed
**Re-verification:** Yes — after gap-closure plan 01-03

## Goal Achievement

### User Flow Coverage

User story: “As a platform operator, I want to open a durable authorized situation and inspect its qualified evidence and audit history, so that I can trust the operational picture before investigation or action.”

| Step | Expected | Evidence | Status |
|---|---|---|---|
| Open the situation queue | A durable, scope-aware queue loads with an explicit loading/error/empty state. | `web/src/app/situations/page.tsx:25-36,91-126`; queue regression tests pass. | ✓ VERIFIED |
| Open a durable situation | An authorized row links to an encoded durable situation ID and the detail page requests it with the selected scope. | `web/src/components/SituationTable.tsx`; `web/src/app/situations/page.test.tsx:68-74`; `web/src/app/situations/[id]/page.tsx:39-62`. | ✓ VERIFIED |
| Inspect qualified evidence and audit | Detail renders durable evidence, source-status rows, linked entities, timeline, and service-recorded audit events; out-of-scope audit events are removed. | `EvidenceBar.tsx:66-91`; detail test; `src/situations/store.py:123-152`; authorization regression passes. | ✓ VERIFIED |
| Trust the operational picture before action | Freshness, availability, provenance, quality, confidence, scope, warnings, contradictions, unknowns, and read-only handoffs are visible without an approval/remediation CTA. | `web/src/app/situations/[id]/page.tsx:117-148,168-245`; `materializer.py:524-551`; automated tests pass. Direct browser/API walkthrough remains pending. | ⚠️ HUMAN CHECK |

### Observable Truths

| # | Truth | Status | Evidence |
|---:|---|---|---|
| 1 | Operator can open a durable situation with lifecycle, severity, priority, scope, ownership, affected resources, and related operational entities. | ✓ VERIFIED | Durable model/materializer and detail page expose the fields; consolidated backend regression passed and the queue/detail links are exercised. |
| 2 | Representative ARG/Activity Log, Monitor or Service Health, Defender, Policy, and vulnerability signals appear as normalized records with source identifiers, timestamps, watermarks, and ingestion status. | ✓ VERIFIED | `normalize_signal_families()` covers all six canonical families at `src/situations/materializer.py:377-475`; ingestion regression passed. |
| 3 | Operator can see freshness, availability, provenance, quality, and authorization scope for information used by the situation. | ✓ VERIFIED | `DurableEvidence` and `DurableSourceStatus` fields are rendered by `EvidenceBar` and the detail drawer; detail regression asserts succeeded, unavailable, empty/unknown, watermark, scope, query version, provider error, and confidence text. |
| 4 | Auditor can see immutable events for observations and lifecycle activity without unauthorized users seeing out-of-scope data. | ✓ VERIFIED | `SituationReadProvider.audit()` applies `_nested_matches()` before copying/filtering event fields; the regression event with `sub-b` scope is absent, including actor/action/timestamp/scope metadata. |
| 5 | FOUND-01: Durable situations expose required triage and timestamp fields. | ✓ VERIFIED | Existing durable model/materializer/API path remains covered by the consolidated Phase 1 backend suite. |
| 6 | FOUND-02: Situation records link the required operational entity families and project them into ontology/curated output. | ✓ VERIFIED | Existing ontology/materializer/mapper coverage remains green in the consolidated backend regression suite. |
| 7 | FOUND-03: Source freshness, availability, provenance, and quality are visible. | ✓ VERIFIED | Source-status rows are passed as `record.source_status ?? []` and rendered with provider state, availability, quality, freshness, timestamps, watermark, query version, requested scope, and error; page test passes. |
| 8 | FOUND-04: Observation and lifecycle audit events are immutable and attributable. | ✓ VERIFIED | Existing append-only event identity/replay/mutation tests remain green; detail renders actor, action, timestamp, scope snapshot, and references. |
| 9 | FOUND-05: Entra/RBAC scope protects situation, evidence, linked-entity, and audit reads, including nested fields. | ✓ VERIFIED | `store.py:165-186` checks `requested_scope` and `scope_snapshot`; authorization regression passes and proves no nested audit metadata leakage. |
| 10 | DETECT-01: Representative source families normalize through the platform ingestion path. | ✓ VERIFIED | Existing service/normalizer path and consolidated backend suite remain green. |
| 11 | DETECT-02: Deduplication preserves source IDs, timestamps, watermarks, ingestion status, and batch provenance. | ✓ VERIFIED | Ingestion, service, and incremental-sync regressions pass; freshness repair excludes only timestamp volatility from fingerprints and preserves source metadata. |
| 12 | The approved UI contract is implemented over durable situations, including trustworthy audit/error states and responsive/keyboard behavior. | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Code and jsdom tests cover the queue/detail states, Escape handling, and keyboard reachability. No test or direct observation proves responsive layout or focus return in a real browser; see Human Verification Required. |

**Score:** 11/12 truths verified (1 present but behavior-unverified)

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/situations/store.py` | Nested authorization projection including audit `scope_snapshot` | ✓ VERIFIED | Exists, substantive, and used by `get()`, `evidence()`, and `audit()`; `_nested_matches()` rejects out-of-scope snapshots before event copying. |
| `src/situations/materializer.py` | Timestamp-based fallback freshness derivation | ✓ VERIFIED | Actual implementation boundary; `_freshness()` and `_parse_utc()` at lines 524-551 preserve explicit bands and derive fresh/aging/stale/unknown. |
| `src/hermes_arg_connector/normalize.py` | Production normalization boundary | ✓ VERIFIED (adapter) | Exists and is wired; `Normalizer.normalize()` delegates signal-family normalization at lines 255-276. The plan’s `contains: _freshness` check is a path mismatch: the helper is intentionally in `materializer.py`, as recorded in 01-03-SUMMARY.md. |
| `web/src/components/ui/EvidenceBar.tsx` | Durable evidence and source-status trust rendering | ✓ VERIFIED | Typed `DurableSourceStatus` input and visible rows at lines 79-90; durable evidence includes quality, availability, freshness, provenance, and confidence. |
| `web/src/app/situations/[id]/page.tsx` | Separate durable audit success-empty and service-unavailable states | ✓ VERIFIED | `Promise.allSettled()` preserves `auditError`; success-empty and rejected-audit copy are distinct at lines 39-58 and 220-230. |
| `web/src/app/situations/page.tsx` | Distinct empty states and scope-aware pagination/reload | ✓ VERIFIED | Empty headings, loading reset, filters, offset navigation, and scoped API request are implemented at lines 25-36 and 91-126. |
| `web/src/app/situations/page.test.tsx` | Complete durable queue regression matrix | ✓ VERIFIED | Seven page tests cover loading, rows/search, P1/P2/P3, pagination, both empty states, provider error, scope reload, and keyboard row action. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `SituationReadProvider.audit` | `ReadScope` | `_nested_matches()` evaluates the event’s own `scope_snapshot` before evidence/reference projection. | ✓ WIRED | `store.py:137-151,165-186`; authorization regression passes. |
| `normalize_signal_families` | `DurableEvidence` | `_freshness()` receives observed/ingested timestamps and persists the band. | ✓ WIRED | `materializer.py:430-458,524-551`; six-family and freshness boundary tests pass. |
| `SituationDetailPage` | `EvidenceBar` | Detail passes `record.source_status ?? []` and durable evidence. | ✓ WIRED | `page.tsx:144-148`; detail test asserts rendered source-status facts. |
| `SituationDetailPage` | `situationsApi.audit` | `Promise.allSettled()` preserves a rejected audit request as an unavailable state. | ✓ WIRED | `page.tsx:45-57,223-229`; rejected-audit test passes. |
| `SituationsPage` | `situationsApi.list` | Queue sends selected scope, search, priority, offset, and limit and replaces stale envelopes on reload. | ✓ WIRED | `page.tsx:25-36`; queue scope/pagination tests pass. |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Durable evidence | `graph.evidence` / `record.evidence` | Provider payloads → `normalize_signal_families()` → `materialize_graph()` → immutable dataset → read provider | Yes; six-family fixture normalization and persistence tests pass. | ✓ FLOWING |
| Source trust | `record.source_status` | Per-family provider rows → `SourceStatus` → materialized situation → detail page → `EvidenceBar` | Yes; succeeded, failed, unavailable, empty, and unknown fixtures are asserted. | ✓ FLOWING |
| Freshness | `DurableEvidence.freshness` | Persisted observed/ingested timestamps → `_parse_utc()` → named one-hour/twenty-four-hour bands | Yes; fresh, aging, stale, future, invalid, and explicit-band cases pass. | ✓ FLOWING |
| Audit timeline | `audit.data` | Durable audit dataset → scoped provider → `situationsApi.audit()` → detail page | Yes on successful reads; rejected reads are explicitly unavailable rather than static empty data. | ✓ FLOWING |
| Queue rows | `envelope.data` | `situationsApi.list(scope, query, priority, offset, limit)` → `rankDurableSituations()` → `SituationTable` | Yes; API adapter and page tests pass with real fixture-shaped rows. | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Targeted authorization/ingestion/API regressions | `uv run pytest tests/test_situations_authorization.py tests/test_situations_ingestion.py tests/test_situations_api.py -q` | 7 tests passed | ✓ PASS |
| Consolidated Phase 1 backend regression | `uv run pytest tests/test_situations_model.py tests/test_situations_ingestion.py tests/test_situations_authorization.py tests/test_situations_api.py tests/test_situations_audit.py tests/test_service.py tests/test_incremental_sync.py -q` | 35 tests passed | ✓ PASS |
| Frontend detail/queue regressions | `cd web && npm test -- --run 'src/app/situations/[id]/page.test.tsx' 'src/app/situations/page.test.tsx'` | 2 files, 11 tests passed | ✓ PASS |
| Consolidated Phase 1 frontend regressions | `cd web && npm test -- --run src/lib/situations.test.ts src/components/SituationTable.test.tsx src/app/situations/page.test.tsx 'src/app/situations/[id]/page.test.tsx'` | 4 files, 14 tests passed | ✓ PASS |
| Backend lint | `uv run ruff check src/situations/store.py src/hermes_arg_connector/normalize.py tests/test_situations_authorization.py tests/test_situations_ingestion.py` | All checks passed | ✓ PASS |
| Frontend lint | `cd web && npm run lint` | No ESLint warnings or errors | ✓ PASS |
| Production web build | `cd web && npm run build` | Exit 0; existing MSAL `window is not defined` generation diagnostics remain | ✓ PASS WITH WARNING |
| Running local route availability | `curl ... http://127.0.0.1:8080/api/v1/situations?limit=1` and `curl ... http://127.0.0.1:3000/situations` | API returned expected unauthenticated 401; web route returned 200 | ? AUTH/API WALKTHROUGH PENDING |
| Whitespace integrity | `git diff --check -- <Phase 1 implementation/test files>` | No output/errors | ✓ PASS |

## Probe Execution

No phase-declared or conventional `scripts/*/tests/probe-*.sh` probes were found. Step 7c: SKIPPED (no probes).

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| FOUND-01 | `01-01/02/03` | Durable situation with required triage fields | ✓ SATISFIED | Durable model/materializer/provider path and consolidated backend regressions. |
| FOUND-02 | `01-01/02` | Links to required operational entity families | ✓ SATISFIED | Existing ontology/materializer/mapper tests remain green. |
| FOUND-03 | `01-02/03` | Freshness, availability, provenance, and data quality | ✓ SATISFIED | Durable source-status/evidence fields are rendered; detail tests and freshness tests pass. |
| FOUND-04 | `01-01/02/03` | Immutable observation/lifecycle audit events | ✓ SATISFIED | Existing append identity/replay/mutation coverage remains green; detail distinguishes service audit states. |
| FOUND-05 | `01-01/02/03` | Entra/RBAC scope boundaries | ✓ SATISFIED | Nested audit scope snapshot regression proves full event absence and no metadata leakage. |
| DETECT-01 | `01-01/02` | Representative source-family normalization | ✓ SATISFIED | Six-family normalizer and service-path regression coverage remains green. |
| DETECT-02 | `01-02/03` | Deduplication and preservation of source/run metadata | ✓ SATISFIED | Ingestion/service/incremental-sync tests plus freshness boundary tests pass. |

No orphaned Phase 1 requirement IDs were found.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `web/src/app/situations/page.tsx` | 74 | `placeholder="Service, application, owner, cause, or incident ID"` | ℹ️ INFO | Legitimate search-input hint, not a product stub. |
| Next.js build output | — | Pre-existing MSAL `window is not defined` diagnostics during static generation | ⚠️ WARNING | Build still completes successfully; unrelated to Phase 1 situation implementation. |
| `src/hermes_arg_connector/normalize.py` vs plan artifact declaration | — | `_freshness` is not defined in the declared file | ⚠️ WARNING | Documented path mismatch only; the actual wired helper is substantive in `src/situations/materializer.py` and tests pass. |

No unreferenced `TBD`, `FIXME`, or `XXX` markers, empty rendered implementations, hardcoded rendered data, or product-code stubs were found in the Phase 1 files.

## Human Verification Required

### 1. Authenticated fixture-backed local API walkthrough

**Test:** With the documented local fixture API and an authorized local token, load the collection, choose an encoded durable situation ID, then load its detail and audit endpoints. Exercise a successful empty audit and an audit service failure if available.

**Expected:** The selected scope appears in successful envelopes; detail contains source-status/evidence fields; audit events are newest-first and scope-bounded; successful empty history says `No audit events are visible in this scope.` while a rejected request says `Audit history unavailable from the service`.

**Why human:** This run cannot safely obtain or expose configured bearer credentials, and the unauthenticated API check returned 401. The available web route returned 200, but no authenticated fixture-backed detail ID was available.

### 2. Responsive and keyboard operator walkthrough

**Test:** At desktop, tablet, and mobile widths, change scope and filters, inspect queue empty/loading/error states, open a durable situation, inspect every source-status/evidence trust field, linked entities, contradictions/unknowns, audit, and evidence drawer. Use keyboard focus, Enter, Escape, and focus return.

**Expected:** Narrow layouts keep the first queue columns and actions understandable; source trust and qualified states remain readable; scope reloads replace stale rows only after loading; audit failure is not shown as empty; drawer Escape returns focus; the page stays read-only with `View future-phase candidate` and `Save view locally`.

**Why human:** Visual appearance, responsive overflow, real browser keyboard semantics, focus return, and the complete integrated user journey are not proven by jsdom or static build checks.

## Gaps Summary

Plan 01-03 closed all previously observed product blockers: nested audit `scope_snapshot` filtering, freshness derivation, durable source-status trust rendering, audit failure versus empty-history handling, queue regression coverage, and the valid MVP goal. Current code and targeted tests support 11 of 12 verification truths.

The remaining issue is not an observed product failure. It is an Escalation Gate for two unobserved runtime checks: authenticated fixture-backed detail/audit API smoke and the desktop/tablet/mobile browser walkthrough. The current environment only established an unauthenticated API 401 and a web route 200, so those checks remain `human_needed` rather than being claimed as passed.

---

_Verified: 2026-08-25T14:40:58Z_
_Verifier: the agent (gsd-verifier)_
