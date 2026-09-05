---
phase: 12-network-topology-integrity-and-scale
plan: 08
subsystem: network-web
tags: [pagination, policy-authoring, provenance, accessibility, react, vitest]

requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 02
    provides: shared enterprise-scale network fixtures
  - phase: 12-network-topology-integrity-and-scale
    plan: 04
    provides: retained-data useApi refetch and server-owned declarative rule vocabulary
  - phase: 12-network-topology-integrity-and-scale
    plan: 07
    provides: honest coverage and pagination envelopes for gaps and rule findings
provides:
  - summary-backed network metrics with explicit server pagination and incomplete-result disclosure
  - policy mutation invalidation and server-authoritative declarative rule preview/save workflow
  - three-state flow-log provenance and unconditional graph freshness disclosure
  - page-level keyboard, focus, accessible-name, and isolated Retry regression coverage
affects: [12-09, 12-10, 12-11, network-page, evidence-bar, policy-editor]

actuals:
  tokens: 22384
  tasks: 3
  commits: 11

tech-stack:
  added: []
  patterns:
    - server-mode pagination driven by additive envelope coverage and pagination
    - successful policy writes trigger coalesced retained-data refetches
    - browser validates JSON syntax only while the server owns rule semantics
    - local freshness guard preserves the shared formatter byte-for-byte

key-files:
  created:
    - web/src/app/network/page.test.tsx
    - web/src/components/ui/EvidenceBar.test.tsx
    - .planning/phases/12-network-topology-integrity-and-scale/12-08-SUMMARY.md
  modified:
    - web/src/app/network/page.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts
    - web/src/components/ui/EvidenceBar.tsx

key-decisions:
  - "The two server-paginated network tabs explicitly request 100 rows while the shared client-side DEFAULT_PAGE_SIZE remains unchanged at 20."
  - "Policy mutations retain optimistic feedback but refetch policy and all three derived loaders; the refetched server policy wins conflicts."
  - "Only JSON syntax is checked in the browser; all well-formed JSON, including semantically invalid values, reaches the server validator."
  - "Graph freshness is unknown when absent, empty, unparseable, or at/before the Unix epoch; valid values continue through relativeTime unchanged."

patterns-established:
  - "Collection truthfulness: summary totals drive metrics, coverage drives disclosure, and unavailable data is never represented as zero."
  - "Mutation invalidation: successful writes call stable useApi refetch handles; failures preserve form contents and do not refresh derived views."
  - "Accessibility: visible Retry copy remains short while unique aria-labels begin with Retry and identify the failed surface."

requirements-completed: [TOPO-03, TOPO-04, TOPO-05]

coverage:
  - id: D1
    description: Network metrics use true summary totals, both analysis tabs paginate against server envelopes, and unavailable or partial data is disclosed honestly.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#Network page honest totals and server pagination
        status: pass
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#Network page loader recovery
        status: pass
    human_judgment: false
  - id: D2
    description: Policy mutations coalesce derived refetches while preserving rendered data, and declarative rules use server-owned semantic validation.
    requirement: TOPO-04
    verification:
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#Network page policy round-trip
        status: pass
    human_judgment: false
  - id: D3
    description: Flow-log provenance is data-derived and graph freshness is always present with one shared four-condition unknown predicate.
    requirement: TOPO-05
    verification:
      - kind: automated_ui
        ref: web/src/components/ui/EvidenceBar.test.tsx#EvidenceBar graph freshness
        status: pass
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#Network page provenance and keyboard contracts
        status: pass
    human_judgment: false
  - id: D4
    description: New pagination, Retry, rule-authoring, preview, save, and two-step-delete controls remain keyboard reachable in DOM order with unique accessible names and the global focus contract.
    verification:
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#tab-walks every introduced policy control in DOM order with unique accessible names
        status: pass
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#tab-walks the server pagers and preserves distinct labels in each rendered view
        status: pass
      - kind: other
        ref: grep -nE 'button:focus-visible|textarea:focus-visible|policy-switch input:focus-visible' web/src/app/globals.css
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 08: Honest Network Page, Policy Round-Trip, and Provenance Summary

**The network workspace now reports complete estate totals over bounded pages, refreshes derived analysis after server-validated policy edits without dropping loaded data, and exposes data-derived flow and freshness provenance with keyboard-complete controls.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-09-05T17:13:16Z
- **Completed:** 2026-09-05T17:27:56Z
- **Tasks:** 3
- **Files modified:** 7, including this summary
- **Commits:** 11, including this summary commit

## Accomplishments

- Replaced capped-array metrics with `summary.gap_count` and `summary.rule_finding_count`, retained unknown placeholders while unavailable, added explicit `limit=100&offset=0` requests, and rendered both tabs through the existing server-mode `TablePagination`.
- Added joint coverage disclosure only when both server envelopes are known, plus four per-surface Retry actions with stable, unique accessible names and isolated refetch behavior.
- Wired successful toggle, delete, and save mutations to coalesced policy/topology/gaps/findings refetches while retaining the populated topology and previous metric totals under `aria-busy`.
- Replaced the built-in rule-id gate with free-form declarative authoring, server-supplied target/operator help, JSON-syntax-only client checks, server semantic error rendering, preview, save, summary-total delta feedback, and cached-analysis warning feedback.
- Replaced the fixed flow-log claim with all three server provenance states and made the shared `Graph` evidence segment unconditional.
- Added keyboard tab-walk coverage for policy authoring, pagination, Retry, and two-step delete interactions, with no positive `tabIndex` and no focus-ring overrides.

## Task Commits

All planned TDD tasks have a RED commit followed by a GREEN commit:

1. **Task 1 RED — honest totals, pagination, coverage, and recovery:** `34807838`
2. **Task 1 GREEN — server-mode network pagination and isolated Retry actions:** `c1a85778`
3. **Task 2 RED — policy mutation and declarative authoring contracts:** `b17c5771`
4. **Task 2 GREEN — retained-data policy round-trip and server validation:** `22d04ca1`
5. **Task 3 RED — provenance, freshness, and A40 keyboard contracts:** `e5f72e31`
6. **Task 3 GREEN — three-state provenance and unconditional graph freshness:** `3f2a47a4`
7. **Deviation RED — well-formed JSON and PATCH semantic rejection:** `cafa2d7e`
8. **Deviation GREEN — preserve server semantic authority:** `4e0c13f5`
9. **Deviation RED — unavailable companion coverage honesty:** `0ea13f46`
10. **Deviation GREEN — suppress false zero-of-zero coverage:** `c6eabfbe`

## Files Created/Modified

- `web/src/app/network/page.test.tsx` — 23 page tests covering totals, pagination, recovery, mutation refetch, declarative authoring, provenance, and keyboard accessibility.
- `web/src/components/ui/EvidenceBar.test.tsx` — 5 graph-freshness tests for absent, empty, unparseable, epoch, and valid timestamps.
- `web/src/app/network/page.tsx` — truthful metrics and coverage, paged loaders, isolated retries, policy authoring/refetch feedback, flow provenance, and accessible controls.
- `web/src/lib/services.ts` — optional offset/limit forwarding for gaps and rule-findings requests.
- `web/src/lib/types.ts` — additive coverage, rule-engine vocabulary, declarative validation, and flow-provenance types.
- `web/src/components/ui/EvidenceBar.tsx` — unconditional graph segment with a local unknown-freshness guard.
- `.planning/phases/12-network-topology-integrity-and-scale/12-08-SUMMARY.md` — execution evidence and exact verification record.

## Honest Totals and Pagination Contract

- The initial gaps and rule-findings calls are exactly `{ limit: 100, offset: 0 }`.
- Advancing either tab changes its offset by exactly its current server page size and makes one request.
- The client-only `DEFAULT_PAGE_SIZE` remains `PAGE_SIZE_OPTIONS[0]`, whose value remains **20**.
- Metric cards render server summary totals, including the tested **340 gaps** and **620 rule findings**, while each first list page contains 100 rows.
- The page-level incomplete-results callout names both returned and true totals only when both envelopes loaded. An unavailable companion collection is never fabricated as `0 of 0`.
- Initial and failed metric states use `—`, not zero.

## Policy and Validation Contract

- Successful toggle, delete, and save paths call `policy.refetch()` and the parent callback that coalesces `topology.refetch()`, `gaps.refetch()`, and `findings.refetch()` through the existing 400 ms `useApi` window.
- Populated data stays mounted during refetch. The topology wrapper carries `aria-busy="true"` while the existing canvas and summary-backed metrics remain visible.
- The author controls accept a free-form rule id and a JSON assertion body. Help text is generated from `supported_targets` and `supported_operators`.
- The browser catches JSON parser failures only. Every syntactically valid JSON value is passed to preview; semantic acceptance remains exclusively server-owned.
- Preview-returned `invalid_reason` and PATCH `invalid_request` errors render adjacent to the assertion in `role="alert"`, mark the textarea invalid, describe it by id, make no follow-up save, and preserve the entered body.
- A successful save reports `Rule saved. Inspection gaps {before} → {after}.` from summary totals. An unchanged total accompanied by a server cache/staleness signal instead reports `Saved. Derived analysis has not refreshed yet — retry in a moment.`

## Provenance and Freshness Contract

The page header maps `topology.flow_log_provenance` to exactly:

1. `Flow logs: not ingested — findings are configuration-derived`
2. `Flow logs: ingested, not yet analyzed — findings remain configuration-derived`
3. `Flow logs: {n} observed flows analyzed`

The previous fixed claim is absent from `web/src`.

`EvidenceBar` always emits the `Graph` segment. Its local, non-exported `freshnessChip(value)` uses this exact predicate, which Plan 12-09's long-form guard must match:

1. `!value` — absent or empty;
2. `new Date(value).getTime()` is `Number.isNaN(ms)` — unparseable;
3. `ms <= 0` — at or before the Unix epoch;
4. otherwise call the existing `relativeTime(value)` unchanged.

The four unknown paths render the literal `Unknown`; a valid recent timestamp renders relative time. `web/src/lib/format.ts` remains byte-identical at SHA-256 `f2eb82e1c051b6a8b884792dd65618ca15746295d06326a9ae5669c387dd3309`.

## Accessibility Evidence

- **Policy tab walk:** 11 introduced controls were reached in DOM order: Analyzer template, Rule ID, Name, Category, Severity, Description, Rule assertion, Preview rule, Save rule, Delete Custom one, and Delete Custom two.
- **Pagination tab walks:** each rendered server page exposed the rows-per-page selector, Previous, and Next controls through keyboard navigation after moving to page 2.
- **Two-step deletion:** the first activation changes visible copy to `Confirm delete`, supplies the unique accessible name `Confirm delete {rule name}`, and exposes the required polite live-region warning.
- **Retry controls:** topology, inspection gaps, rule findings, and design policy use four distinct names beginning with visible `Retry`; each test proves only its own loader is refetched.
- **Tab order:** every collected control has `tabIndex <= 0`; no positive `tabIndex` exists in the changed production surfaces.
- **Focus visibility:** the global `button`, `input`, `select`, and `textarea` `:focus-visible` rule remains active, and the policy switch retains its dedicated `:focus-visible + .policy-switch-track` ring. No changed control overrides either outline.
- **Accessible names:** all 11 simultaneously rendered introduced policy controls have unique names; both delete controls include their rule names.

## Shared Evidence-Bar Impact

Every page that uses `EvidenceBar` without `graphFreshness` now receives the intended `Graph Unknown` segment. No other page's evidence-bar assertion required an update; the complete 41-file web suite passed unchanged outside the two Plan 12-08 test files.

## Verification

- `cd web && npx vitest run src/app/network/page.test.tsx src/components/ui/EvidenceBar.test.tsx` — **2 files passed, 28 tests passed**.
- `cd web && npx vitest run` — **41 files passed; 284 tests passed; 15 pre-existing todos; 299 total tests**.
- `cd web && npx tsc --noEmit` — **passed with zero diagnostics**.
- `cd web && npm run lint` — **passed with zero warnings and zero errors**.
- `git diff --exit-code c84d41d6b028e39d149d504f42bf3e4deb7ea678 -- web/src/lib/format.ts` — **passed; byte-identical**.
- `git diff --exit-code c84d41d6b028e39d149d504f42bf3e4deb7ea678 -- web/package.json web/package-lock.json` — **passed; no dependency change**.
- Base-versus-current `DEFAULT_PAGE_SIZE` declaration comparison — **passed; unchanged at 20**.
- Fixed-claim grep, positive-`tabIndex` grep, `git diff --check`, and `STATE.md`/`ROADMAP.md` base-diff checks — **passed**.
- Required Copilot co-author trailer — **present on all 10 implementation/test commits**.

## Decisions Made

- Kept pagination state local to each server-backed tab rather than modifying the shared in-memory pagination hook.
- Used the collection-specific summary for each metric so a capped list can never become an estate total.
- Preserved the existing `useApi` coalescing and retained-data semantics instead of adding a store or data-fetching dependency.
- Treated the server rule engine as the only semantic authority; the browser performs only `JSON.parse`.
- Kept the freshness predicate local to `EvidenceBar` so shared formatting behavior on other pages cannot drift.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved server-only validation for every well-formed JSON value**
- **Found during:** Overall Task 2 review
- **Issue:** Using `null` as the parse-failure sentinel also swallowed the valid JSON literal `null`, creating an accidental client semantic gate. PATCH semantic failures also rendered away from the assertion.
- **Fix:** Replaced the sentinel with a discriminated parse result and routed server `invalid_request` errors into the adjacent assertion alert while retaining the form body.
- **Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`
- **Verification:** Two regression tests fail-first in `cafa2d7e` and pass after `4e0c13f5`; targeted suite passes 28/28.
- **Commits:** `cafa2d7e`, `4e0c13f5`

**2. [Rule 1 - Bug] Prevented unavailable data from being described as zero coverage**
- **Found during:** Overall Task 1 truthfulness review
- **Issue:** If one collection failed while the other was truncated, the joint callout could interpolate the unavailable side as `0 of 0`, violating the three-state honesty rule.
- **Fix:** Emit the joint incomplete-results callout only after both server envelopes are available; the failed tab retains its explicit unavailable panel and Retry.
- **Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`
- **Verification:** The regression fails first in `0ea13f46`, passes after `c6eabfbe`, and the full web suite remains green.
- **Commits:** `0ea13f46`, `c6eabfbe`

**Total deviations:** 2 auto-fixed bugs.
**Impact:** Both fixes tighten the planned honesty and server-authority guarantees without adding dependencies, routes, stores, or new architecture.

## TDD Gate Compliance

- Task 1: RED `34807838` precedes GREEN `c1a85778`.
- Task 2: RED `b17c5771` precedes GREEN `22d04ca1`.
- Task 3: RED `e5f72e31` precedes GREEN `3f2a47a4`.
- Both review-discovered correctness fixes also have fail-first regression commits followed by fixes.
- Every RED run failed on the intended absent behavior before production changes.

## Threat Model Verification

- **T-12-35:** Server summary totals and availability-aware placeholders prevent capped or failed collections from masquerading as estate counts.
- **T-12-36:** Each page-level failure has its own recovery action and loader-scoped refetch.
- **T-12-37:** The browser has no rule schema; only parse syntax is checked before server preview/save.
- **T-12-38:** Derived refresh calls use the existing stable 400 ms coalescing handle.
- **T-12-39:** Flow-log analysis and graph freshness are derived from server data and always disclosed.
- **T-12-40:** The shared formatter was not modified.
- No unplanned endpoint, authentication path, file access, dependency, or schema trust boundary was introduced.

## Known Stubs

None. The changed production code contains no TODO, FIXME, coming-soon branch, mock data source, or hardcoded empty value that prevents the plan goal. Input `placeholder` attributes are intentional form guidance, not implementation stubs. The 15 full-suite todos pre-date this plan; no test was added, skipped, or left unrun by Plan 12-08.

## Issues Encountered

- The isolated worktree did not initially contain `web/node_modules`; `npm ci` restored the committed lockfile exactly and changed neither dependency manifest.
- Existing Vite CJS deprecation and Keyborg cleanup diagnostics remain non-failing, pre-existing suite output.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-09 can reuse the documented four-condition freshness predicate for its long-form topology footnote and drawer guard.
- The page now consumes Plan 12-07's bounded collection envelopes and Plan 12-04's stable refetch handles without changing either shared default.
- No blocker remains for subsequent topology workspace, export, or compatibility plans.

## Self-Check: PASSED

- All seven declared source, test, and summary files exist in the isolated worktree.
- All 10 implementation/test commit hashes resolve and all 10 carry the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer.
- Targeted tests passed 28/28; the complete web suite passed 284 tests across 41 files with 15 pre-existing todos.
- TypeScript, ESLint, format-byte identity, dependency-manifest, default-page-size, fixed-copy, positive-`tabIndex`, whitespace, and worktree-state checks all passed.
- `STATE.md` and `ROADMAP.md` are byte-unchanged from the worktree base, as required for this parallel executor.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
