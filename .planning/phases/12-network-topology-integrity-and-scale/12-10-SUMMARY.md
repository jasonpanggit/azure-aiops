---
phase: 12-network-topology-integrity-and-scale
plan: 10
subsystem: network-web
tags: [react, topology-drawer, drill-down, export-provenance, accessibility, tdd]

requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 03
    provides: reasoned unresolved-peer projection
  - phase: 12-network-topology-integrity-and-scale
    plan: 06
    provides: private-link candidate projection and facts
  - phase: 12-network-topology-integrity-and-scale
    plan: 07
    provides: summary detail contract, scoped paginated drill-down, and coverage
  - phase: 12-network-topology-integrity-and-scale
    plan: 09
    provides: bounded badge loading and topology reduction state
provides:
  - five explicit and honest drawer findings states for every selected node
  - lazy paginated fact drill-down with per-node session caching
  - private-endpoint and private-link-service facts with explicit unknown and out-of-scope states
  - ten-key self-describing topology JSON exports and collision-free timestamped JSON/PNG filenames
  - visible partial-export status and filter-driven selection clearing
affects: [12-11, network-canvas, topology-drawer, topology-export]

actuals:
  tokens: 13350
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - independent findings and withheld-fact state machines
    - module-session cache keyed by case-folded node id and page offset
    - ordered provenance envelope around the unchanged topology payload
    - monotonic second-resolution UTC export identities

key-files:
  created:
    - web/src/components/network/TopologyDetailDrawer.test.tsx
    - .planning/phases/12-network-topology-integrity-and-scale/12-10-SUMMARY.md
  modified:
    - web/src/app/network/page.tsx
    - web/src/components/network/TopologyDetailDrawer.tsx
    - web/src/components/network/TopologyGraph.tsx
    - web/src/components/network/TopologyGraph.test.tsx
    - web/src/components/network/TopologyWorkspace.tsx
    - web/src/components/network/TopologyWorkspace.test.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts

key-decisions:
  - "Findings completeness and summary-withheld fact detail remain independent state machines; one never answers for the other."
  - "Drill-down pages are cached by case-folded node id plus offset for the browser session, and only selection changes move focus."
  - "The export keeps the existing topology object byte-for-byte in the final top-level topology key while provenance precedes it."
  - "A module-local monotonic second allocator preserves the exact YYYYMMDD-HHmmss filename contract while preventing same-session collisions."

patterns-established:
  - "Drawer honesty: zero findings becomes confirmed clean only after successful, untruncated, exhausted loading."
  - "Export honesty: every provenance key is unconditional and unknown values are serialized as null."

requirements-completed: [TOPO-02, TOPO-03, TOPO-05]

coverage:
  - id: D1
    description: Every selected node renders exactly one of the five C-5 findings states, with strict clean-state gating, unique retry recovery, and drawer-first Escape.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyDetailDrawer.test.tsx#TopologyDetailDrawer findings states
        status: pass
      - kind: automated_ui
        ref: web/src/components/network/TopologyDetailDrawer.test.tsx#TopologyDetailDrawer peer copy and keyboard behavior
        status: pass
    human_judgment: false
  - id: D2
    description: Withheld rules, routes, and rule collections load only on demand, paginate at 50 rows, recover without closing, preserve focus, and reuse session-cached pages.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyDetailDrawer.test.tsx#TopologyDetailDrawer on-demand facts
        status: pass
    human_judgment: false
  - id: D3
    description: Private endpoint and private link service drawers expose connection, target, subnet, alias, load-balancer, public-access, and out-of-scope facts without silent omissions.
    requirement: TOPO-02
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyDetailDrawer.test.tsx#renders private endpoint and private-link service facts without silent unknowns
        status: pass
    human_judgment: false
  - id: D4
    description: JSON exports carry the ordered ten-key provenance envelope, explicit nulls, badge and graph bounds, and the unchanged topology object.
    requirement: TOPO-05
    verification:
      - kind: unit
        ref: web/src/components/network/TopologyGraph.test.tsx#topology export provenance
        status: pass
    human_judgment: false
  - id: D5
    description: JSON and PNG exports use collision-free timestamped filenames; PNG identifies itself as image-only and partial topology is visible before export.
    requirement: TOPO-05
    verification:
      - kind: unit
        ref: web/src/components/network/TopologyGraph.test.tsx#creates collision-free JSON and PNG filenames with 15-character timestamp segments
        status: pass
      - kind: automated_ui
        ref: web/src/components/network/TopologyWorkspace.test.tsx#shows a Partial badge beside honest JSON and PNG export controls
        status: pass
    human_judgment: false
  - id: D6
    description: Filtering a selected node out of the rendered graph clears the drawer and prevents a hidden Cytoscape node from retaining selection styling.
    requirement: TOPO-03
    verification:
      - kind: automated_ui
        ref: web/src/components/network/TopologyWorkspace.test.tsx#clears a selected node when a changed filter hides it
        status: pass
    human_judgment: false

duration: 57 min
completed: 2026-09-06
status: complete
---

# Phase 12 Plan 10: Honest Drawer Drill-Down and Export Provenance Summary

**Every topology selection now produces an explicit findings answer, summary-withheld facts load through cached scoped pagination, and JSON/PNG exports disclose their scope, limits, filters, freshness, and completeness.**

## Performance

- **Duration:** 57 min
- **Started:** 2026-09-06T00:41:36Z
- **Completed:** 2026-09-06T01:38:57Z
- **Tasks:** 3
- **Files modified:** 9 before this summary
- **Implementation/test commits:** 6

## Accomplishments

- Replaced the silent empty drawer branch with all five C-5 states: findings present, confirmed clean, possibly incomplete, unavailable, and loading. Confirmed clean requires successful loaders, untruncated collection coverage, an exhausted badge fetch, and zero mapped findings.
- Added grouped direct/affected findings, exact peer-resolution copy, unique R-5 recovery, and event propagation control so the first Escape closes the drawer while full screen remains active.
- Added lazy `rules`, `routes`, and `rule_collections` drill-down through the existing scope-enforced endpoint, with a 50-row server page, in-flight duplicate suppression, distinct R-6 recovery, stable focus, and session caching by node/page.
- Added explicit private-endpoint and private-link-service facts, including candidate/public-access badges, unknown public-access state, target scope disclosure, connection state, subnet, alias, and load-balancer association.
- Wrapped the unchanged topology object in an ordered provenance envelope, preserved null provenance explicitly, recorded badge and graph bounds, and exposed partial coverage beside both export controls.
- Added monotonic UTC timestamp filename derivation for both JSON and PNG and cleared selection whenever filtering removes the selected node.

## Drawer Semantics

| State | Heading | Body / behavior |
|---|---|---|
| Findings present | `Open findings (N)` | Grouped gaps, control findings, and affected-resource findings |
| Confirmed clean | `Open findings (0)` | Only after both loaders succeed, collection coverage is untruncated, badge loading is exhausted, and no findings map to the node |
| Possibly incomplete | `Open findings` | Polite warning with loaded-versus-total values and `This resource is not confirmed clean.` |
| Unavailable | `Open findings` | Critical alert with the loader error and R-5 `Retry loading findings for {resource name}` |
| Loading | `Open findings` | `Checking open findings…` under `aria-busy="true"` |

The findings state remains independent of the badge visibility toggle and of summary-withheld rule/route detail. Peer nodes separately identify `not_ingested`, `excluded_by_scope`, and unrecorded resolution; legacy id-only peers always use the unrecorded state.

## Drill-Down and Cache Contract

- Endpoint: `GET /network/topology/resources/{resource_id:path}/details`
- Initial page: `offset=0&limit=50`
- Withheld controls: `Load rules`, `Load routes`, `Load rule collections`
- Cache key: case-folded node id plus page offset
- Cache lifetime: browser module session
- Completion behavior: loaded, empty, and error states replace only the affected fact section; the drawer stays open and focus is not moved
- Retry names: R-5 findings and R-6 fact-detail recovery remain distinct even when both render together

## Export Contract

The JSON top-level key order is exactly:

1. `exported_at`
2. `scope`
3. `detail_level`
4. `coverage`
5. `filters`
6. `evidence`
7. `warnings`
8. `knowledge_version`
9. `graph_freshness`
10. `topology`

`topology` is the previous export payload unchanged. `coverage` records topology total/returned/truncated values, the four-page badge budget and exhaustion state, mapped badge findings, rendered/total nodes, rendered/total relationships, and dropped relationships. `filters` records search, filter mode, shared-service visibility, and finding-badge visibility. Missing provenance values are serialized as `null`.

The filename patterns are exactly:

- `network-topology-YYYYMMDD-HHmmss.json`
- `network-topology-YYYYMMDD-HHmmss.png`

The collision fix required **no change outside filename derivation**. A module-local monotonic second allocator advances repeated same-session exports while retaining the exact 15-character `YYYYMMDD-HHmmss` segment. The JSON `exported_at` uses the same generated identity. PNG remains intentionally metadata-free, and its control says `Export PNG (image only)` with a title directing operators to JSON for an auditable record.

## Task Commits

1. **Task 1 RED — five drawer states, peer copy, and Escape:** `74defcc3`
2. **Task 1 GREEN — honest drawer finding states:** `b2aea03b`
3. **Task 2 RED — drill-down, cache, focus, and private-link facts:** `9fc7cc57`
4. **Task 2 GREEN — cached paginated fact drill-down:** `9645917b`
5. **Task 3 RED — export provenance, timestamp, partial, and selection tests:** `99b57339`
6. **Task 3 GREEN — self-describing topology exports:** `692c9247`

Every commit carries `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>`.

## Files Created/Modified

- `web/src/components/network/TopologyDetailDrawer.test.tsx` — five-state, peer, keyboard, drill-down, cache, focus, and private-link acceptance coverage.
- `web/src/components/network/TopologyDetailDrawer.tsx` — honest findings state machine, scoped detail loading, cache, pagination, and private-link facts.
- `web/src/components/network/TopologyGraph.test.tsx` — ordered export, null provenance, coverage, and filename tests.
- `web/src/components/network/TopologyGraph.tsx` — export envelope/identity helpers and hidden-selection guard.
- `web/src/components/network/TopologyWorkspace.test.tsx` — partial-export, badge exhaustion, and selection-clearing coverage.
- `web/src/components/network/TopologyWorkspace.tsx` — findings loader state, export context, partial badge, PNG disclosure, and visible-node scope context.
- `web/src/app/network/page.tsx` — loader/error/retry and topology envelope provenance wiring.
- `web/src/lib/services.ts` — existing scoped drill-down route client.
- `web/src/lib/types.ts` — additive resource-detail response contract.

## Decisions Made

- Kept findings completeness independent from withheld fact detail so a confirmed-clean node may still offer `Load rules`, while unavailable findings do not block fact retrieval.
- Cached successful drill-down pages only. Errors remain retryable and never poison the session cache.
- Inferred a private endpoint target as outside collected scope only from an explicit server flag or absence from the current scoped node set; no unauthorized target facts are invented.
- Preserved the existing topology object under the final `topology` key and placed all provenance before it for human readability.
- Used monotonic UTC second allocation to preserve the required filename grammar while preventing rapid same-session collisions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wired loader and provenance integration seams omitted from the task file lists**
- **Found during:** Tasks 1–3
- **Issue:** The drawer could not know both loader outcomes, invoke the failed loader's retry, consume the scoped drill-down route, infer visible target scope, or export envelope provenance from only the two component files named in the task lists.
- **Fix:** Added narrow additive props/types and service wiring in the existing page, workspace, service client, and shared type modules.
- **Files modified:** `web/src/app/network/page.tsx`, `web/src/components/network/TopologyWorkspace.tsx`, `web/src/lib/services.ts`, `web/src/lib/types.ts`
- **Verification:** Targeted 54/54, full web 330/330 executed tests, TypeScript, and ESLint passed.
- **Committed in:** `b2aea03b`, `9645917b`, `692c9247`

**2. [Rule 1 - Bug] Narrowed a contradictory legacy-peer RED assertion**
- **Found during:** Task 1 GREEN verification
- **Issue:** The RED test rejected the words `never ingested` anywhere, while the required unknown-resolution sentence itself says the response did not record whether the VNet was never ingested.
- **Fix:** The assertion now forbids the false definitive sentence `This peer was never ingested.` while preserving the exact required uncertainty sentence.
- **Files modified:** `web/src/components/network/TopologyDetailDrawer.test.tsx`
- **Verification:** Task 1 exact suite and full web suite passed.
- **Committed in:** `b2aea03b`

---

**Total deviations:** 2 auto-fixed (1 blocking integration issue, 1 test bug).
**Impact on plan:** Both fixes were required to exercise the planned contracts end to end. No new endpoint, dependency, visual primitive, status tone, or architecture was introduced.

## TDD Gate Compliance

- Task 1 RED `74defcc3` precedes GREEN `b2aea03b`.
- Task 2 RED `9fc7cc57` failed 7 new acceptance cases before GREEN `9645917b`.
- Task 3 RED `99b57339` failed 4 new acceptance cases before GREEN `692c9247`.
- All six task commits include the required co-author trailer.

## Verification

- Drawer exact gate — **1 file, 18 tests passed**.
- Network component gate — **3 files, 54 tests passed**.
- Full web wave gate — **43 files passed; 330 tests passed; 15 pre-existing todos; 345 total tests**.
- TypeScript — `npx --no-install tsc --noEmit` passed with zero diagnostics.
- ESLint — `npm run lint` passed with zero warnings and zero errors.
- Accessibility interaction slice — **4 passed** covering R-5/R-6 unique names, focus stability, and drawer-first Escape.
- Hygiene — `git diff --check`, no new TODO/FIXME/skipped tests, no legacy peer labels, and no dependency-manifest changes all passed.
- Worktree isolation — `.planning/STATE.md` and `.planning/ROADMAP.md` are unchanged.

## Threat Model Verification

- **T-12-48:** Every selected node has a terminal findings state; `OpenFindings` no longer returns `null`.
- **T-12-49:** Withheld facts use explicit detail-level disclosure and independent on-demand loading.
- **T-12-50:** Peer copy follows the server resolution value; legacy payloads remain undetermined.
- **T-12-51:** Drill-down uses the existing scope-enforced route, and private endpoint targets outside the visible scoped node set are disclosed without rendering hidden target facts.
- **T-12-52:** Every export carries ordered scope, detail, bounds, filters, evidence, warnings, knowledge, freshness, and topology fields.
- **T-12-53:** Every export receives a monotonic timestamped filename.
- **T-12-54:** Parent state clears a hidden selection, and Cytoscape refuses to reapply `.cy-selected` to a hidden element.
- No unplanned endpoint, authentication path, package, file-access pattern, or schema trust boundary was introduced.

## Known Stubs

None. No placeholder implementation, TODO, FIXME, skipped owned test, mock production data, or unwired data source was introduced.

## Issues Encountered

- The existing headless Cytoscape tests continue to print non-failing style-mapping warnings for deliberately sparse test nodes.
- The full web suite still reports 15 pre-existing todo tests; Plan 12-10 introduced no skipped or todo test.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-11 can assert the exact export key order and filename patterns recorded above.
- Drawer, drill-down, export, accessibility, TypeScript, lint, and full-web gates are green.
- `STATE.md` and `ROADMAP.md` remain untouched for orchestrator-owned parallel closeout.

## Self-Check: PASSED

All declared source and test files exist in the isolated worktree; all six task commits resolve and carry the required co-author trailer; drawer, network-component, full-web, TypeScript, ESLint, accessibility, dependency, stub, whitespace, and legacy-copy checks passed; the export key order and filename patterns are recorded verbatim; and `STATE.md`/`ROADMAP.md` remain unchanged.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-06*
