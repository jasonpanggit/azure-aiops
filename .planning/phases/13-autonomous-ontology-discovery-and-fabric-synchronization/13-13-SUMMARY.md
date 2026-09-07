---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 13
subsystem: ui
tags: [nextjs, react, vitest, ontology-automation, evaluation-snapshot, fabric]

requires:
  - phase: 13-12
    provides: scope-first durable ontology lifecycle, generation, publication, and EvaluationSnapshot APIs
  - phase: 13-UI-SPEC
    provides: approved Connections-tab information architecture, exact copy, state, and accessibility contract
provides:
  - typed connection-scoped ontology automation client with revision, ETag, eligibility, pagination, and EvaluationSnapshot contracts
  - approved Ontology automation tab inside the existing Connections page and design system
  - independent scheduler, run, incremental, proposal, generation, publication, and evaluation states
  - stale EvaluationSnapshot visibility with fail-closed release eligibility and durable history reconstruction
affects: [13-14, 13-15, connections, ontology-automation-ui, evaluation-operations]

actuals:
  tokens: 23021
  tasks: 2
  commits: 5

tech-stack:
  added: []
  patterns:
    - selected connection ID and effective scope accompany every ontology request
    - section-local useApi resources preserve successful siblings when one source fails
    - server-projected eligibility, revision, ETag, and disabled reasons remain authoritative
    - durable EvaluationSnapshot state is rendered without browser-owned release inference

key-files:
  created:
    - web/src/components/ontology/OntologyAutomationPanel.tsx
  modified:
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/components/ui/StatusBadge.tsx
    - web/src/app/connections/page.tsx
    - web/src/app/connections/page.test.tsx
    - web/src/app/globals.css

key-decisions:
  - "Extend the existing /connections tab model and shared primitives rather than adding a route or design system."
  - "Clear an ontology connection selection as soon as it leaves effective scope and cancel stale status/section updates through effect cleanup."
  - "Render durable stale evaluation evidence while keeping release disabled from the exact server-projected reason."
  - "Keep lifecycle mutations revision/ETag-bound and refresh every durable section plus status after successful actions."

patterns-established:
  - "Ontology reads: selected connection + effective ScopeSelection -> typed API method -> independent section state."
  - "Ontology mutations: server eligibility -> confirmation/reason -> observed revision or pointer ETag -> full durable refresh."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Every ontology read and mutation is typed, connection-scoped, and concurrency-aware while preserving the existing connection sync API."
    requirement: AUTO-ONT-06
    verification:
      - kind: unit
        ref: "web/src/app/connections/page.test.tsx#Ontology automation typed client contract"
        status: pass
      - kind: other
        ref: "cd web && npx tsc --noEmit"
        status: pass
    human_judgment: false
  - id: D2
    description: "The approved Ontology automation workspace is integrated into /connections with selection invalidation and independent durable sections."
    requirement: AUTO-ONT-01
    verification:
      - kind: automated_ui
        ref: "web/src/app/connections/page.test.tsx#Connections page Ontology automation tab"
        status: pass
    human_judgment: false
  - id: D3
    description: "Fresh, stale, missing, invalid, partial, error, and empty evaluation/lifecycle states remain distinct and fail closed."
    requirement: AUTO-ONT-07
    verification:
      - kind: automated_ui
        ref: "web/src/app/connections/page.test.tsx#uses only server eligibility and preserves stale evaluation evidence with the disabled reason"
        status: pass
      - kind: automated_ui
        ref: "web/src/app/connections/page.test.tsx#keeps successful sections visible when sibling ontology sources fail"
        status: pass
    human_judgment: false
  - id: D4
    description: "Cancel, retry, proposal review, run-now, and rollback actions use server state plus observed revision or ETag rather than browser-owned authority."
    requirement: AUTO-ONT-04
    verification:
      - kind: automated_ui
        ref: "web/src/app/connections/page.test.tsx#uses exact destructive confirmations and observed concurrency values"
        status: pass
    human_judgment: false
  - id: D5
    description: "Keyboard flow, focus behavior, copy, and overflow remain usable at 1280px and 390px."
    requirement: AUTO-ONT-05
    verification: []
    human_judgment: true
    rationale: "The approved UI-SPEC explicitly reserves responsive overflow and assistive-technology reading order for end-of-phase human verification."

duration: 12min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 13: Ontology Automation UI Summary

**A connection-scoped ontology operations workspace now reconstructs durable discovery, review, publication, rollback, and EvaluationSnapshot state inside the approved `/connections` experience.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-07T02:24:33Z
- **Completed:** 2026-09-07T02:36:25Z
- **Tasks:** 2
- **Files modified:** 7 implementation/test files

## Accomplishments

- Added a typed ontology client spanning status, run history/actions, proposal review, generations, publication attempts, rollback, and durable evaluation history. Every method requires the selected connection and effective scope; mutations carry observed revision or pointer ETag data.
- Extended the existing `/connections` tabs, header, and selector behavior with the approved Ontology automation surface while preserving Subscriptions, Fabric Medallion, and `connectionsApi.sync`.
- Built independent scheduler, current-run, incremental discovery, proposal, generation, run-history, publication-history, and evaluation sections with exact UI-SPEC empty/error/degraded/stale copy.
- Kept stale EvaluationSnapshot versions, timestamps, thresholds, slices, and failures visible while release remains disabled using the server-projected reason.
- Covered selection invalidation, scope propagation, sibling failure isolation, destructive confirmations, server eligibility, stale evidence, and existing Connections/Fabric behavior.

## Task Commits

Each TDD task has a RED contract commit followed by its GREEN implementation:

1. **Task 1 RED: typed connection-scoped client contracts** - `946e4dfe`
2. **Task 1 GREEN: scoped ontology automation client** - `0e58106e`
3. **Task 2 RED: ontology workspace UI contracts** - `baa9dd59`
4. **Task 2 GREEN: accessible durable ontology workspace** - `ccb409c2`
5. **Task 2 corrective verification: scope dependency safety** - `21c563ef`

## Files Created/Modified

- `web/src/components/ontology/OntologyAutomationPanel.tsx` - Independent durable ontology sections, tables, mutations, confirmations, and evaluation evidence.
- `web/src/lib/types.ts` - Exact run, proposal, generation, evaluation, revision, ETag, pagination, and eligibility contracts.
- `web/src/lib/services.ts` - Connection- and scope-required ontology API methods while preserving existing connection sync behavior.
- `web/src/app/connections/page.tsx` - Approved third tab, active in-scope connection selector, header action, status lifecycle, and selection invalidation.
- `web/src/app/connections/page.test.tsx` - TDD contract, scope, state, failure-isolation, stale-evaluation, confirmation, and regression coverage.
- `web/src/components/ui/StatusBadge.tsx` - Existing status primitive extended for ontology lifecycle vocabulary.
- `web/src/app/globals.css` - Responsive section rhythm and bounded long-value layout using existing design tokens.

## Decisions Made

- Reused the existing Connections route, one `PageHeader`, shared cards/tables/badges, and Fabric selector pattern; no route, registry package, or parallel visual primitive was introduced.
- Kept selected connection identity separate from subscription identity because the API authorizes both the explicit `connection_id` and effective global scope.
- Treated absent server fields as “Not reported” rather than inferring lease ownership, agent mode, reconciliation counts, or release state in the browser.
- Refreshed parent status and all sibling durable sections after mutation so a successful local response never becomes browser-owned lifecycle truth.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added the effective scope object to status request dependencies**
- **Found during:** Overall web lint verification after Task 2
- **Issue:** The first implementation keyed the status request by a serialized scope while closing over the scope object, producing a React exhaustive-deps warning and weakening the explicit stale-request invalidation guarantee.
- **Fix:** Depend directly on the effective scope object; effect cleanup now cancels the prior status projection before the replacement scope request can update state.
- **Files modified:** `web/src/app/connections/page.tsx`
- **Verification:** Connections tests, TypeScript, and ESLint pass without warnings.
- **Committed in:** `21c563ef`

---

**Total deviations:** 1 auto-fixed bug.
**Impact on plan:** The fix strengthens the planned scope isolation behavior without changing architecture or product scope.

## Issues Encountered

- The worktree initially had no restored `web/node_modules`; `npm ci` restored only the lockfile-pinned dependency graph and produced no tracked changes.
- `npm run build` compiled the Phase 13 UI and completed its lint/type stage, then failed during static export on pre-existing `/exposure`, `/exposure/defender-posture`, and `/exposure/patch-priorities` `useSearchParams()` Suspense violations. These unrelated routes were not modified; the issue is recorded in `deferred-items.md`.

## Verification

- `cd web && npm test -- --run src/app/connections/page.test.tsx` — 16 passed.
- `cd web && npm test -- --run` — 54 files, 520 tests passed.
- `cd web && npx tsc --noEmit` — passed.
- `cd web && npm run lint` — passed with no warnings or errors.
- `cd web && npm run build` — application compilation plus lint/type validation passed; static export failed only on three pre-existing Exposure route Suspense issues.
- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- `git diff --check` — passed.
- All five TDD/task correction commits contain the required Copilot trailer.

## Known Stubs

None. Unavailable server projections are rendered explicitly as unavailable or “Not reported”; no mock or browser-derived lifecycle authority ships.

## User Setup Required

None - no deployment, push, merge, credential change, or external service mutation was performed.

## Next Phase Readiness

- Plan 13-14 can add pinned evaluation and sanitized trace inspection against the durable EvaluationSnapshot contract.
- End-of-phase verification should perform the UI-SPEC keyboard/focus/copy/overflow backstop at 1280px and 390px.
- Root Phase 03.1 remains globally active; only Phase 13 completed-plan accounting is updated.

## Self-Check: PASSED

- All seven implementation/test artifacts and this summary exist.
- All five RED/GREEN/corrective task commits are present in repository history.
- Summary status is `complete`; required automated tests, typecheck, lint, and Phase 13 preflight passed.
