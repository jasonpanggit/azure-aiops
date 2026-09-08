---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 15
subsystem: ui
tags: [copilot, remediation, page-adapters, mutation-boundary, governance, react, typescript]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 07
    provides: Typed pure page adapters and the shared core Copilot context builder
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 14
    provides: Shared launcher/drawer surface and deterministic outage fallback
provides:
  - Typed read-only remediation Copilot adapter over the current governed workflow projection
  - Advisory Copilot explanation and governed-handoff entry point on the remediation page
  - Proof that Copilot carries no approval or execution authority (D-10)
  - Current-server-eligibility precedence over carried thread history (D-08, D-09)
affects: [11-16]

# Actuals (#2632)
actuals:
  tokens: 6400
  tasks: 2
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read-only page adapter mirrors current server eligibility as descriptive, non-authorizing facts"
    - "Carried thread history is labeled non-current and inert; current server projection always wins"
    - "Copilot drawer receives only read-only props; approval/execution stay bound to existing server endpoints"

key-files:
  created: []
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/app/remediation/page.tsx
    - web/src/app/remediation/page.test.tsx

key-decisions:
  - "buildRemediationCopilotContext binds the already-loaded governed workflow projection (plan/action identity, approval requirements, execution lifecycle, evidence, coverage, freshness) through the shared core adapter, so no route-local snapshot builder or client eligibility inference exists."
  - "Eligibility booleans (plan_executable, can_operate, can_approve, approval_current/status, has_executable_preview, recommended_step) are descriptive mirrors of the current server projection re-read on every render; they never grant Copilot any authority."
  - "Carried thread history is projected as historical_finding rows with current:false and superseded_by_current_state:true, and — like every row — is forced actionable:false/mutation_authorized:false by the shared core evidence path, so historical evidence can never override current server eligibility."
  - "The remediation page renders the shared CopilotDrawer with only read-only props (snapshot, starterQuestions, requestedScope, contextLabel); the existing server-driven Approve/Run/Recovery controls remain outside the adapter and drawer and stay bound to remediationApi endpoints."
  - "Remediation starter hints are advisory (specialist remediation, tool remediation_opportunities) and carry no mutation tool."

requirements-completed: [COP-02, COP-04, COP-05]

coverage:
  - id: T1
    description: "Remediation adapter binds current server plan/action identity, eligibility, visible/total coverage, and per-source freshness, labeling carried history non-current"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds current server plan identity, eligibility, coverage, and freshness, labeling carried history non-current"
        status: pass
    human_judgment: false
  - id: T2
    description: "Current server eligibility overrides historical thread context"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#lets current server eligibility override historical thread context"
        status: pass
    human_judgment: false
  - id: T3
    description: "No Copilot mutation path across plan/approval/execution/history evidence; advisory starters only"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#exposes no Copilot mutation path across plan, approval, execution, or history evidence"
        status: pass
      - kind: integration
        ref: "src/app/remediation/page.test.tsx#offers an advisory Copilot entry point that exposes no mutation control"
        status: pass
    human_judgment: false
  - id: T4
    description: "Approval and execution remain bound to the existing governed server endpoints, not Copilot"
    requirement: COP-02
    verification:
      - kind: integration
        ref: "src/app/remediation/page.test.tsx#keeps execution bound to the existing governed server endpoint, not Copilot"
        status: pass
    human_judgment: false
  - id: T5
    description: "Deterministic cited evidence and the governed workflow remain available without Copilot narration"
    requirement: COP-05
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#retains deterministic cited server evidence independent of optional narration"
        status: pass
      - kind: integration
        ref: "src/app/remediation/page.test.tsx#keeps deterministic cited evidence and the governed workflow available without Copilot narration"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 15: Remediation Read-Only Copilot Handoff Summary

**The governed remediation page now binds its current server-projected plan, approval, execution eligibility, evidence, freshness, and coverage into a typed read-only Copilot adapter and advisory drawer that can explain and prepare a governed handoff but carries no authority to approve or execute — approval and execution remain bound only to the existing server endpoints, and carried thread history can never override current server eligibility.**

## Accomplishments

- Added `buildRemediationCopilotContext` — a pure typed adapter over the already-loaded governed workflow projection — routed through the shared `buildCoreCopilotContext`/`services.buildCopilotSnapshot` path, so there is no route-local snapshot builder and no client-side eligibility inference.
- Carried the selected plan/action identity (canonical ARM entity when the plan targets an Azure resource), current server eligibility (`plan_executable`, `can_operate`, `can_approve`, `approval_current`/`approval_status`, `has_executable_preview`, `recommended_step`), approval-requirement lifecycle, and execution lifecycle facts as descriptive, read-only rows.
- Bound visible/total plan coverage and per-source freshness (plan-list presence plus workflow degradation), surfacing truncation and non-fresh sources as explicit uncertainty.
- Labeled carried thread history as `historical_finding` rows with `current:false` and `superseded_by_current_state:true`; like every row, they are forced `actionable:false`/`mutation_authorized:false`, so historical evidence can never replace current server eligibility (D-08, D-09).
- Wired an advisory Copilot drawer entry point ("Ask Copilot about remediation") on the remediation page that receives only read-only props; the existing server-driven Approve/Run/Recovery controls remain outside the adapter and drawer and stay bound to `remediationApi` endpoints (D-09, D-10).
- Kept deterministic cited evidence and the governed workflow available independent of optional Copilot narration.
- Registered `/remediation` as an integrated Copilot route with an explicit `integrated` disposition.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

**Task 1: Bind remediation evidence and current server eligibility into a typed adapter**
1. `20de0c8b3` test(11-15): pin remediation read-only adapter contract (RED)
2. `cddb00a9d` feat(11-15): bind remediation into a read-only typed adapter (GREEN)

**Task 2: Prove Copilot cannot approve or execute remediation**
3. `4c81490ea` test(11-15): pin remediation read-only Copilot handoff (RED)
4. `4f0b8beda` feat(11-15): add read-only Copilot handoff to remediation (GREEN)

Every commit includes the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer.

## Files Created/Modified

- `web/src/lib/copilot/page-adapters.ts` — Added the remediation input contracts, `remediationCoreInput` mapper, `buildRemediationCopilotContext`, `REMEDIATION_STARTERS`, `CORE_PAGE_CONFIG.remediation`, the `/remediation` registry entry, and the `/remediation` integrated disposition.
- `web/src/lib/copilot/page-adapters.test.ts` — Added the remediation adapter regression matrix (identity/eligibility/coverage/freshness, current-wins-over-history, no-mutation-path, narration-independent evidence, bounded no-plan context) and extended the integrated-route registry assertion.
- `web/src/app/remediation/page.tsx` — Built the read-only `remediationCopilot` context from the current workflow projection and rendered the advisory `CopilotDrawerButton`/`CopilotDrawer` with read-only props; no change to the existing governed approval/execution/recovery controls.
- `web/src/app/remediation/page.test.tsx` — Added the read-only Copilot handoff proof (advisory entry point with no mutation control, execution stays server-bound, deterministic evidence/governed workflow without narration) and mocked `buildCopilotSnapshot` for the context build.

## Mutation-Boundary Decisions

- The CopilotDrawer receives only `snapshot`, `starterQuestions`, `requestedScope`, and `contextLabel`. It has no `onApprove`/`onExecute` callback and no route to mutate state. Approval and execution flow only through the pre-existing `remediationApi.approve`/`execute`/`retry`/`cancel`/`supersede` controls, which were not modified.
- Eligibility fields carried into the snapshot are descriptive projections of the current server workflow; they are re-read every render and never consulted by any client-side authorization decision.
- Historical evidence is inert: `current:false`, `superseded_by_current_state:true`, `actionable:false`, `mutation_authorized:false`. The current server projection is the sole source of eligibility.

## Deviations from Plan

None — the plan executed as written. No auto-fix (Rule 1–3) or architectural (Rule 4) deviations were required. The `services.ts:405-460` reference in the plan action pointed at stale line numbers (inventory services); the intended pure adapter/page split pattern was followed from the existing `buildCoreCopilotContext` core adapters instead.

## Threat Model Verification

- **T-11-47 (Elevation, remediation handoff, critical):** Mitigated. No mutation operation exists in the adapter or drawer; server eligibility and existing approval/execution routes remain authoritative. Proven by `exposes no Copilot mutation path...` (adapter) and `offers an advisory Copilot entry point that exposes no mutation control` + `keeps execution bound to the existing governed server endpoint` (page).
- **T-11-48 (Tampering, historical eligibility, high):** Mitigated. Current server projection wins and historical evidence is visibly non-current. Proven by `lets current server eligibility override historical thread context`.

No new security-relevant surface (network endpoints, auth paths, file access, schema) was introduced beyond the plan's threat register.

## Independent Code Review

The `claude` CLI is present but could not reach its API in this sandbox (`ConnectionRefused`), so an automated independent review pass was unavailable. A rigorous manual critical review of the full implementation diff was performed instead:
- No mutation calls, write/execute hints, `actionable:true`, or `mutation_authorized:true` paths introduced (scan clean; every row forced non-actionable/non-authorized by the shared core path).
- No forbidden files touched (backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, unrelated routes) — confirmed via `git diff --name-only`, only the 4 plan files changed.
- Eligibility read from the current workflow projection each render; historical evidence proven inert and non-overriding.
- No blocking findings. One minor, non-blocking observation: the synthetic `plans` source freshness is presence-based (`fresh` once the plan list loaded), consistent with the Plan 11-07 CVE-source pattern; real degradation is carried from `workflow.degradation`.

## Verification Gates

| Gate | Result |
|---|---|
| Task 1 focused (`page-adapters.test.ts`) | 32 passed |
| Task 2 focused (`page-adapters.test.ts` + `remediation/page.test.tsx`) | 88 passed |
| Full web Vitest suite | 56 files, 575 tests passed |
| ESLint (`next lint`, full project) | No warnings or errors |
| TypeScript (`tsc --noEmit`) | Clean (exit 0) |
| Diff / scope check | Only the 4 plan `files_modified` changed; no forbidden paths |
| Working tree | Clean |

The existing Vite CommonJS deprecation notice and unrelated Keyborg warnings remain non-failing.

## Success Criteria

1. Remediation has complete typed context — met (adapter binds plan/action identity, eligibility, requirements, execution, evidence, visible/total coverage, and freshness).
2. Copilot cannot authorize or execute mutation — met (drawer read-only; approval/execution bound only to existing server endpoints; every row non-actionable/non-authorized).
3. Current server state overrides historical context — met (historical evidence labeled non-current and inert; eligibility read from current projection).

## Delivery Status

- No backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, drawer, or unrelated-route implementation was changed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged (consistent with Plans 11-07/11-14 worktree convention); Phase 11 is not marked complete.
- Nothing was pushed, merged, deployed, built for release, or integrated with `origin/main`. The merge/deployment freeze is preserved.

## Self-Check: PASSED
