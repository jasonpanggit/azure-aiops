---
phase: 03-safe-remediation-execution
plan: 06
subsystem: remediation-ui
tags: [nextjs, react, typescript, vitest, governed-execution, polling]
requires:
  - phase: 03-05
    provides: durable approval-bound execution lifecycle, verification, history, cancellation, and server-owned eligibility
provides:
  - Business-impact-first governed remediation preview and approval-bound execution workspace
  - Bounded scope-safe polling with verified outcomes, retry, cancellation, rollback guidance, and immutable history
  - Read-only patch inventory handoff with no direct mutation client or caller-supplied approval form
affects: [phase-04, remediation-ui, patching, operator-uat]
actuals:
  tokens: 22703
  tasks: 3
  commits: 5
tech-stack:
  added: []
  patterns:
    - Browser consumes server-owned execution eligibility without recomputing approval or retry policy
    - Selection and scope changes invalidate in-flight detail reads and bounded execution polling
    - Patch inventory carries context into governance but never submits provider mutations
key-files:
  created: []
  modified:
    - web/src/lib/services.ts
    - web/src/app/remediation/page.tsx
    - web/src/app/remediation/page.test.tsx
    - web/src/components/exposure/PatchInventory.tsx
    - web/src/components/exposure/PatchInventory.test.tsx
key-decisions:
  - "The browser treats executable, retryable, cancellable, remaining_attempts, and ineligibility_reason as authoritative server projections."
  - "Approval sends only the current server preview hash; stale previews are refetched for explicit operator review."
  - "Patch inventory is read-only and transfers resource, KB, and business-service context into governed remediation."
patterns-established:
  - "Verified-state polling: provider submission remains queued/running/retrying until the backend returns a terminal status."
  - "Stale-response isolation: request generations and effect cleanup prevent prior plan or scope responses from updating the current selection."
requirements-completed: [EXEC-02, EXEC-04, EXEC-05, EXEC-06]
coverage:
  - id: D1
    description: Approved controlled patch plans show business evidence and an exact immutable execution preview
    requirement: EXEC-02
    verification:
      - kind: automated_ui
        ref: "web/src/app/remediation/page.test.tsx#loads the governed preview and business evidence before exposing execution"
        status: pass
    human_judgment: false
  - id: D2
    description: Operators can execute once, poll durable status, inspect verified outcomes, retry, and cancel according to server eligibility
    requirement: EXEC-04
    verification:
      - kind: automated_ui
        ref: "web/src/app/remediation/page.test.tsx#execution lifecycle tests"
        status: pass
    human_judgment: false
  - id: D3
    description: Failure details, rollback guidance, actors, attempts, and transitions remain visible and auditable
    requirement: EXEC-05
    verification:
      - kind: automated_ui
        ref: "web/src/app/remediation/page.test.tsx#renders verified failure details, rollback guidance, immutable history, and retries only when eligible"
        status: pass
    human_judgment: false
  - id: D4
    description: Patch inventory provides governed handoff and contains no direct mutation affordance
    requirement: EXEC-06
    verification:
      - kind: automated_ui
        ref: "web/src/components/exposure/PatchInventory.test.tsx"
        status: pass
    human_judgment: false
duration: 12min
completed: 2026-09-01
status: complete
---

# Phase 3 Plan 6: Remediation Operator UI Summary

**Approval-bound patch execution now joins business evidence, exact server preview, bounded durable polling, verified outcomes, and auditable lifecycle controls in one operator workspace.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-09-01T15:01:19Z
- **Completed:** 2026-09-01T15:13:42Z
- **Tasks:** 3
- **Files modified:** 5
- **Focused tests:** 32 passed
- **Quality gates:** ESLint passed; production build passed

## Accomplishments

- Added strict Phase 3 TypeScript contracts and a scoped remediation client covering plan detail, preview, approval, business decision, execute, poll/list, retry, and cancel.
- Replaced the Phase 2 approval-only boundary with an operator flow that shows business impact and the exact approved target, patch selection, ARM operation, preconditions, expected effect, and collateral impact before confirmation.
- Added execute-once submission and bounded polling that never claims success before the backend returns an Azure-verified terminal outcome.
- Rendered all lifecycle states, actual verified state, provider reference, failure details, rollback guidance, attempt and transition history, actors, timestamps, and server-controlled retry/cancel eligibility.
- Removed direct patch mutation from the inventory UI and client, replacing it with a governed resource/KB/business-service handoff.

## Task Commits

1. **Task 1 RED:** `f4fb8684` — failing governed preview and eligibility tests.
2. **Task 1 GREEN:** `62dd4d86` — typed client, business evidence, exact preview, and snapshot-bound approval.
3. **Task 2 RED:** `9493c01e` — failing execution lifecycle, polling, and patch handoff tests.
4. **Task 2 GREEN:** `64140bfb` — execute/poll/outcome/retry/cancel UI and read-only inventory handoff.
5. **Task 3:** `c0a11c55` — lint cleanup and removal of the unused patch mutation client.

## Files Created/Modified

- `web/src/lib/services.ts` — strict remediation preview/execution contracts and complete scoped API client.
- `web/src/app/remediation/page.tsx` — business-impact preview, snapshot-bound approval, confirmation, polling, outcome, retry, cancel, and audit history.
- `web/src/app/remediation/page.test.tsx` — approval, preview, execute-once, terminal verification, failure, retry, cancellation, and stale-poll cleanup coverage.
- `web/src/components/exposure/PatchInventory.tsx` — read-only readiness inventory and encoded governed remediation handoff.
- `web/src/components/exposure/PatchInventory.test.tsx` — proves no direct mutation affordance and validates VM/AKS handoff context.

## Decisions Made

- Execution controls rely on backend eligibility fields and current approval snapshot equality; the browser does not infer authorization.
- Polling is capped at 40 checks, backs off after errors, and is cancelled on unmount, plan change, or scope change.
- Running provider work with `provider_not_cancellable` is reported truthfully instead of presenting a misleading cancel control.

## Deviations from Plan

None - implementation followed the planned remediation UI and inventory-handoff scope.

## Issues Encountered

- The full frontend run completed with **198 passed and 1 unrelated pre-existing failure**: `web/src/app/compliance/page.test.tsx` mocks `@/lib/services` without the `complianceApi` export already consumed by the compliance page. The same failure reproduces in isolation. Per scope rules, that file was not modified; details are recorded in `deferred-items.md`.
- Existing unrelated Fabric changes and debug artifacts remained untouched, unstaged, and excluded from all commits.
- Production build succeeds while emitting existing MSAL `window is not defined` prerender diagnostics.

## TDD Gate Compliance

- RED commits `f4fb8684` and `9493c01e` failed for the intended missing behavior.
- GREEN commits `62dd4d86` and `64140bfb` made the focused 32-test remediation suite pass.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no new external service configuration is required.

## Next Phase Readiness

- Phase 3 now has an end-to-end operator surface over the hardened remediation backend.
- Real Azure UAT can validate one approved patch job from submission through ARM-authoritative terminal state.
- The unrelated compliance test mock remains deferred outside this plan.

## Self-Check: PASSED

All five plan-owned frontend files, the summary, and all five task commits were verified on disk.

---
*Phase: 03-safe-remediation-execution*
*Completed: 2026-09-01*
