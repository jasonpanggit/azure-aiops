---
phase: 12-network-topology-integrity-and-scale
plan: 09
subsystem: network-web
tags: [react, cytoscape, topology-detail, finding-badges, accessibility, tdd]

requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 02
    provides: measured 1,500-node canvas interactivity ceiling
  - phase: 12-network-topology-integrity-and-scale
    plan: 03
    provides: dropped-relationship diagnostics and reasoned unresolved peers
  - phase: 12-network-topology-integrity-and-scale
    plan: 07
    provides: summary/full topology contract, collection coverage, and affected resource ids
  - phase: 12-network-topology-integrity-and-scale
    plan: 08
    provides: explicit paged APIs and the four-condition freshness predicate
provides:
  - guarded Summary / Full detail control with explicit request parameters and incremental position preservation
  - casefolded control-and-affected-resource badge fan-out with a bounded disclosed fetch
  - live unresolved-peer identity resolution and complete accessible topology reduction footnote
affects: [12-10, 12-11, network-canvas, topology-drawer, topology-export]

actuals:
  tokens: 16821
  tasks: 3
  commits: 8

tech-stack:
  added: []
  patterns:
    - measured client payload guard with explicit operator confirmation
    - bounded multi-page collection loading with visible coverage
    - casefolded graph identity updated at node insertion time
    - canvas-only signals mirrored as DOM text

key-files:
  created:
    - web/src/components/network/TopologyWorkspace.test.tsx
    - .planning/phases/12-network-topology-integrity-and-scale/12-09-SUMMARY.md
  modified:
    - web/src/components/network/TopologyWorkspace.tsx
    - web/src/components/network/TopologyGraph.tsx
    - web/src/components/network/TopologyGraph.test.tsx
    - web/src/components/network/TopologyDetailDrawer.tsx
    - web/src/lib/network-graph.ts
    - web/src/lib/network-graph.test.ts
    - web/src/lib/services.ts
    - web/src/lib/types.ts
    - web/src/app/network/page.tsx
    - web/src/app/network/page.test.tsx

key-decisions:
  - "The full-detail guard is exactly the measured 1,500-node ceiling recorded by Plan 12-02; the enterprise check supported rather than lowered the contract maximum."
  - "Badge loading is bounded independently for gaps and rule findings at four pages of 500 items, for at most 2,000 items per collection."
  - "Detail changes preserve prior Cytoscape positions; the existing layout algorithm is unchanged and only the explicit Re-layout action forces randomization."
  - "Legacy unresolved-peer ids map to unknown, never not_ingested, when the reasoned unresolved_peers array is absent."

patterns-established:
  - "Badge identity: casefold both node and finding resource ids and count each finding once per resource."
  - "Topology honesty strip: always disclose rendered/total nodes, filter-hidden nodes, badge coverage, finding-bearing nodes, and freshness; show non-zero drop and peer-resolution facts."

requirements-completed: [TOPO-03, TOPO-05, TOPO-01, TOPO-02]

coverage:
  - id: D1
    description: Summary/full topology selection explicitly requests its chosen detail and guards full detail above the measured ceiling.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyWorkspace.test.tsx#TopologyWorkspace detail level
        status: pass
      - kind: automated_ui
        ref: web/src/app/network/page.test.tsx#Network page topology detail requests
        status: pass
    human_judgment: false
  - id: D2
    description: Findings badge controls and every distinct affected resource through casefolded ids, with role-aware text and bounded disclosed coverage.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyWorkspace.test.tsx#TopologyWorkspace badge coverage
        status: pass
      - kind: unit
        ref: web/src/components/network/TopologyGraph.test.tsx#uses the role-aware title supplied by the badge map
        status: pass
    human_judgment: false
  - id: D3
    description: One real peer VNet produces one node across ARM casing, and missing resolution metadata remains explicitly unknown.
    requirement: TOPO-01
    verification:
      - kind: unit
        ref: web/src/lib/network-graph.test.ts#deduplicates one unresolved peer referenced in two ARM casings
        status: pass
      - kind: unit
        ref: web/src/lib/network-graph.test.ts#maps peer resolution and gives legacy unresolved ids the unknown state
        status: pass
    human_judgment: false
  - id: D4
    description: The visual-only badge toggle and complete DOM footnote expose every canvas reduction, peer state, finding count, and freshness state accessibly.
    requirement: TOPO-05
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyWorkspace.test.tsx#TopologyWorkspace disclosure and visual-only controls
        status: pass
      - kind: other
        ref: cd web && npx --no-install tsc --noEmit
        status: pass
    human_judgment: false

duration: 13 min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 09: Bounded Topology Detail and Complete Canvas Disclosure Summary

**The topology workspace now defaults to an explicitly requested summary, guards full detail at the measured 1,500-node ceiling, fans badges across affected resources within a disclosed 2,000-item-per-collection budget, and mirrors every canvas reduction in accessible DOM text.**

## Performance

- **Duration:** 13 minutes
- **Started:** 2026-09-05T17:32:01Z
- **Completed:** 2026-09-05T17:45:11Z
- **Tasks:** 3
- **Files modified:** 11 before this summary
- **Implementation/test commits:** 7

## Accomplishments

- Added the `Summary` / `Full detail` pressed-button group using the winning `segmented-active` class. The network page explicitly sends `detail=summary` initially and `detail=full` after selection; no request is issued above the guard until `Load full detail` is pressed.
- Preserved search, filter mode, shared-service visibility, finding-badge visibility, and existing Cytoscape positions across detail payload transitions. `layoutFor()` and all color values remain unchanged; only explicit `Re-layout` randomizes.
- Fanned each rule finding to its control and every distinct affected resource through casefolded ARM ids, retained maximum severity, emitted role-specific badge titles, and prevented self-referential double counting.
- Loaded gaps and rule findings in 500-item pages up to four pages per collection. A stopped-short fetch renders `Badge coverage is partial.` above the stage and reports `Badges: {mapped} of {total} findings` in the footnote.
- Relabelled `Finding badges` as a visual-only switch while leaving drawer findings populated, de-duplicated unresolved peer nodes with a live fold index, and mapped legacy unresolved ids to `unknown`.
- Added a complete DOM honesty strip for rendered versus total nodes, filter-hidden nodes, relationship drops and types, split peer-resolution counts, finding-bearing nodes, badge coverage, and long-form freshness.

## Measured Threshold and Badge Budget

| Control | Implemented value | Evidence |
|---|---:|---|
| Full-detail confirmation guard | **1,500 nodes** | `12-PRE-PHASE-BASELINE.json` measured 1,500 nodes at 224.298 ms under the 250 ms ceiling |
| Contract maximum | **1,500 nodes** | Guard equals and does not exceed the UI contract maximum |
| Badge page size | **500 items** | `BADGE_FETCH_PAGE_SIZE` |
| Badge page budget | **4 pages per collection** | `BADGE_FETCH_MAX_PAGES` |
| Maximum loaded for badge mapping | **2,000 gaps + 2,000 rule findings** | Each collection is independently bounded |

The empirical enterprise-fixture canvas check **supported** the 1,500-node maximum; it did not require lowering it.

## Exact Operator Disclosures

- Full-detail guard: `Full detail renders about {n} nodes and may make the canvas slow to interact with.`
- Badge coverage: `Badge coverage is partial. {mapped} of {total} findings were loaded, so some nodes may be missing a badge. Open a resource to see its confirmed findings.`
- Node coverage: `Rendering {rendered} of {total} nodes at {detail} detail.`
- Filter reduction: `{n} hidden by filter`
- Dropped relationships: `{n} relationships dropped ({types}) — endpoints were not present in this scope.`
- Peer resolution: `{n} peers not ingested`, `{n} peers outside current scope`, and `{n} peers with unrecorded resolution`, with zero-valued entries omitted.
- Canvas badge mirror: `{n} nodes with open findings`
- Badge fetch: `Badges: {mapped} of {total} findings`
- Unknown freshness: `Snapshot age unknown — no observation timestamp was recorded.`
- Known freshness: `Snapshot observed {relative time} ({formatted timestamp}).`

## Accessibility Evidence

- The detail options are buttons inside `role="group"` with `aria-label="Topology detail level"`; exactly one carries `aria-pressed="true"` and `segmented-active`.
- The detail group remains between the search field and checkbox toggles in DOM order.
- The full-detail, partial-coverage, zero-match, and selection-cleared notices use polite `role="status"` regions.
- The badge switch label carries the exact visual-only hint; disabling it removes the canvas map but does not remove drawer findings.
- The zero-match notice names the search term and unfiltered resource count.
- Every badge and unresolved-peer visual state has a text mirror in the drawer or footnote; legacy `Not onboarded` copy is absent from `web/src/components/network/`.
- Existing global focus styles, node colors, edge colors, node shapes, layout algorithm, and spacing CSS are unchanged.

## Task Commits

1. **Task 1 RED — detail control and request behavior:** `380ec63b`
2. **Task 1 RED — incremental position preservation:** `7e9ea67f`
3. **Task 1 GREEN — guarded explicit detail selection:** `1d859b4f`
4. **Task 2 RED — affected-resource fan-out and coverage:** `f24f2c92`
5. **Task 2 GREEN — bounded role-aware badge mapping:** `d3689578`
6. **Task 3 RED — disclosure, peer, toggle, and freshness behavior:** `e326aa47`
7. **Task 3 GREEN — complete accessible topology disclosure:** `02270e79`

Every commit carries `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>`.

## Verification

- Plan-targeted web gate — **4 files passed, 116 tests passed**.
- Task 3 exact gate — **3 files passed, 92 tests passed**.
- Full web gate — **42 files passed; 306 tests passed; 15 pre-existing todos; 321 total tests**.
- TypeScript — `npx --no-install tsc --noEmit` passed with zero diagnostics.
- ESLint — `npm run lint` passed with zero warnings and zero errors.
- Baseline threshold check — guard **1,500 = measured 1,500 = contract maximum 1,500**.
- Badge budget check — **4 × 500 = 2,000 items per collection**.
- Dependency manifests — unchanged from worktree base.
- Layout stylesheet and color additions — none.
- Hygiene — `git diff --check`, no new TODO/FIXME/skipped tests, no bare legacy `active` class, and no legacy peer labels all passed.
- Worktree isolation — `STATE.md` and `ROADMAP.md` are byte-unchanged from the worktree base.

## Decisions Made

- Kept the API default unchanged and made the primary Network page explicit instead: every request generated there includes its chosen detail.
- Reused the measured Plan 12-02 threshold verbatim rather than copying an unverified larger literal.
- Preserved position data between topology payloads and overrode only the transition's randomization flag; the established `layoutFor()` algorithm and explicit re-layout behavior remain intact.
- Counted each finding once per casefolded resource while retaining separate control/affected role sets for truthful tooltip copy.
- Treated a legacy unresolved id without a matching reason record as `unknown`, never as evidence that ingestion did not occur.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wired required request, canvas, drawer, and type integration seams omitted from the file list**
- **Found during:** Tasks 1–3
- **Issue:** The planned workspace could not send explicit detail requests, preserve Cytoscape positions, apply role-aware tooltip text, or remove legacy peer wording without small changes in the parent page, service client, canvas, drawer, and shared types.
- **Fix:** Added only the required additive props/types and narrow integration logic; no route, dependency, store, layout algorithm, or color changed.
- **Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`, `web/src/lib/services.ts`, `web/src/lib/types.ts`, `web/src/components/network/TopologyGraph.tsx`, `web/src/components/network/TopologyGraph.test.tsx`, `web/src/components/network/TopologyDetailDrawer.tsx`
- **Verification:** Targeted 116/116, full web 306/306, TypeScript, lint, and hygiene gates passed.
- **Commits:** `1d859b4f`, `d3689578`, `02270e79`

**2. [Rule 2 - Missing Critical] Kept badge-fetch failures from claiming complete coverage**
- **Found during:** Task 3 final review
- **Issue:** A rejected bounded badge fetch could otherwise become an unhandled promise or leave the initial page labelled as complete.
- **Fix:** Retain the last successful rows and compare their mapped count with summary-backed gap/finding totals, causing the partial-coverage disclosure whenever the retained rows are incomplete.
- **Files modified:** `web/src/components/network/TopologyWorkspace.tsx`
- **Verification:** Task 3 exact gate and full web suite passed.
- **Commit:** `02270e79`

**Total deviations:** 2 auto-fixed (1 blocking integration issue, 1 missing critical honesty safeguard).
**Impact:** Both were necessary to satisfy the stated client and trust-boundary behavior. No architecture, dependency, endpoint, layout algorithm, or visual palette changed.

## TDD Gate Compliance

- Task 1 RED commits `380ec63b` and `7e9ea67f` precede GREEN `1d859b4f`.
- Task 2 RED `f24f2c92` precedes GREEN `d3689578`.
- Task 3 RED `e326aa47` precedes GREEN `02270e79`.
- Every RED run failed on the intended absent behavior before its GREEN implementation.

## Threat Model Verification

- **T-12-41:** Badge loading is bounded and its incomplete coverage is disclosed above the stage and in the footnote.
- **T-12-42:** Control and affected-resource ids are casefolded, de-duplicated per finding/resource pair, and carry role-specific titles.
- **T-12-43:** Full detail above the measured ceiling cannot fetch until explicit confirmation.
- **T-12-44:** Canvas reductions, badges, peer reasons, drops, and freshness have DOM text equivalents.
- **T-12-45:** Legacy peer responses resolve to `unknown`, never a fabricated `not_ingested`.
- **T-12-46:** Every inserted unresolved node immediately updates the live fold index.
- **T-12-47:** The badge toggle controls only canvas badge rendering and never gates drawer data.
- No unplanned endpoint, authentication path, file-access path, package, or external trust boundary was introduced.

## Known Stubs

None. No placeholder implementation, TODO, FIXME, skipped owned test, mock production source, or unrun verification was introduced.

## Issues Encountered

- The isolated worktree did not contain `web/node_modules`; `npm ci` restored the committed lockfile without changing either dependency manifest. Existing audit findings and deprecation notices were not modified.
- Cytoscape's existing headless style warnings and the suite's existing Keyborg cleanup notices remain non-failing and pre-date this plan.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-10 can consume `detailLevel`, reasoned peer node data, and complete badge mappings for drawer drill-down and export provenance.
- Plan 12-11 can run the compatibility and baseline gates against an explicitly summary-requesting web client.
- `STATE.md` and `ROADMAP.md` remain untouched for orchestrator-owned parallel closeout.

## Self-Check: PASSED

All declared source and test files exist in the assigned isolated worktree; all seven TDD implementation/test commits resolve and carry the required trailer; targeted, full-web, TypeScript, lint, baseline-threshold, badge-budget, dependency, layout/color, text, and whitespace gates passed with the exact counts recorded above; and `STATE.md`/`ROADMAP.md` remain unchanged.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
