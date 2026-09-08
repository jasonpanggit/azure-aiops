---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 08
subsystem: ui
tags: [copilot, page-adapters, defender, kb, patch-priorities, changes, predeploy, governance, react, typescript]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 15
    provides: Read-only remediation Copilot adapter and the shared core context builder / drawer surface
provides:
  - Typed read-only Defender posture, KB detail, and patch-priority Copilot adapters over already-loaded authorized evidence
  - Typed read-only change-correlation and predeploy-assessment Copilot adapters with temporal-proximity and predicted-vs-observed semantics
  - Shared contextual Copilot entry points on the defender-posture, KB detail, patch-priorities, changes, and predeploy pages
  - Cross-domain change starter hints that reach incident and remediation specialists without any mutation authority (D-03, D-04, D-06, D-08, D-10)
affects: [11-16]

# Actuals (#2632)
actuals:
  tokens: 17361
  tasks: 2
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Domain-specific typed page inputs map into the shared CoreCopilotAdapter, inheriting forced actionable:false/mutation_authorized:false on every evidence row"
    - "Sub-route adapters are exported builders but are NOT registered in CORE_COPILOT_PAGE_ADAPTERS (same convention as the CVE detail adapter), preserving the exact top-level registry contract"
    - "Predicted evidence (simulation/risk/CAB, blast radius) is explicitly flagged predicted:true/observed:false; change correlation carries correlation_basis:temporal_proximity/confirmed:false"

key-files:
  created: []
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/app/exposure/defender-posture/page.tsx
    - web/src/app/exposure/defender-posture/page.test.tsx
    - web/src/app/exposure/kbs/[id]/page.tsx
    - web/src/app/exposure/kbs/[id]/page.test.tsx
    - web/src/app/exposure/patch-priorities/page.tsx
    - web/src/app/exposure/patch-priorities/page.test.tsx
    - web/src/app/changes/page.tsx
    - web/src/app/changes/predeploy/page.tsx

key-decisions:
  - "Five new pure typed adapters (buildDefenderPostureCopilotContext, buildKbDetailCopilotContext, buildPatchPrioritiesCopilotContext, buildChangesCopilotContext, buildPredeployCopilotContext) route through the existing buildCoreCopilotContext / services.buildCopilotSnapshot path, so every row is forced non-actionable and non-mutation-authorized and no route-local snapshot builder exists."
  - "Canonical identities are preserved: KB and CVE are non-ARM domain identities; asset/machine/impacted resources are canonical ARM entities; patch/Defender findings keep their stable source namespace/kind/key and are never leaked into scope-validated resource fields."
  - "Unavailable-vs-empty semantics are preserved via per-section source status (available ? freshness : unavailable) and complete/truncated coverage; specialist/tool values are advisory hints only and validated in tests to exclude any write/deploy/approve/execute/remediate tool."
  - "Predeploy simulation, risk, CAB, and blast radius are explicitly predicted:true/observed:false and carry the assessment's confirmed_outcome/confirmed_cause=false; the changes stream is temporal_proximity/confirmed:false — correlation is never presented as causation."
  - "remediation/page.tsx was intentionally NOT modified: cross-domain 'remediation correlation' is delivered by the changes and predeploy adapters' starter hints (incident + remediation specialists). Editing the remediation adapter/page would have broken its Phase 11-15 safety tests (every remediation starter must be specialistId:remediation) and risked its governed mutation boundary. See Deviations."

requirements-completed: [COP-02, COP-04]

coverage:
  - id: T1
    description: "Defender adapter binds selected asset finding, posture aggregates, visible/total coverage, and unavailable-vs-empty status without any actionable/authorized row"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds selected Defender asset, posture aggregates, coverage, and unavailable-vs-empty status"
        status: pass
    human_judgment: false
  - id: T2
    description: "KB detail adapter carries canonical non-ARM KB identity, CVE/machine identities, lifecycle freshness downgrade, and pagination coverage"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#carries the canonical non-ARM KB identity, CVE/machine identities, freshness, and coverage"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes an unavailable KB provider from a healthy empty finding set"
        status: pass
    human_judgment: false
  - id: T3
    description: "Patch-priority adapter binds KB/CVE/machine identities, SLA evidence, freshness, and truncation deterministically with no mutation path"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds patch priority KB/CVE/machine identities, SLA evidence, freshness, and truncation"
        status: pass
    human_judgment: false
  - id: T4
    description: "Changes adapter binds correlated change identities with temporal-proximity basis, coverage, and cross-domain incident/remediation hints"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds correlated change identities, proximity basis, coverage, and cross-domain hints"
        status: pass
    human_judgment: false
  - id: T5
    description: "Predeploy adapter carries simulation/risk/CAB as predicted (never observed) with impacted-resource coverage and no approval/execution path"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#carries predeploy simulation/risk/CAB as predicted, never observed, with impacted-resource coverage"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps a bounded predeploy context before any assessment is submitted"
        status: pass
    human_judgment: false
  - id: T6
    description: "The five integrated pages render the shared read-only Copilot drawer entry point; co-located page tests and the remediation safety regression remain green"
    requirement: COP-02
    verification:
      - kind: integration
        ref: "src/app/exposure/defender-posture/page.test.tsx (5 tests)"
        status: pass
      - kind: integration
        ref: "src/app/exposure/patch-priorities/page.test.tsx (9 tests)"
        status: pass
      - kind: integration
        ref: "src/app/exposure/kbs/[id]/page.test.tsx (7 tests)"
        status: pass
      - kind: integration
        ref: "src/app/remediation/page.test.tsx (56 tests, unchanged)"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 08: Contextual Copilot Across Security, Patch, and Change Pages Summary

**The Defender posture, KB detail, patch-priorities, changes, and predeploy pages now expose a shared read-only contextual Copilot over their already-loaded, authorized evidence — preserving canonical Defender/KB/CVE/machine identities, visible/total coverage, per-source freshness, unavailable-vs-empty semantics, temporal-proximity correlation, and predicted-vs-observed change semantics — while every evidence row stays non-actionable/non-mutation-authorized and all suggested remediation remains a governed server handoff with no Copilot approval or execution authority.**

## Accomplishments

- Added five pure typed page adapters in `page-adapters.ts`, each routed through the shared `buildCoreCopilotContext` / `services.buildCopilotSnapshot` path so they inherit the forced `actionable:false` / `mutation_authorized:false` guarantee on every row:
  - `buildDefenderPostureCopilotContext` — Defender overview aggregates, secure score, posture findings (selectable ARM asset), alerts, attack paths, and container images with per-section coverage and freshness.
  - `buildKbDetailCopilotContext` — canonical non-ARM KB identity, associated CVE identities, affected-machine ARM findings, enrichment (MSRC/NVD/EPSS) source freshness, and pagination coverage.
  - `buildPatchPrioritiesCopilotContext` — patch-priority rows with KB/CVE/machine identities, SLA state/overdue evidence, deterministic identities, and truncation.
  - `buildChangesCopilotContext` — correlated change events carrying `correlation_basis: temporal_proximity` and `confirmed: false`, with cross-domain incident + remediation starter hints.
  - `buildPredeployCopilotContext` — proposed change, simulation, risk, and CAB recommendation all flagged `predicted: true` / `observed: false` (plus the source `confirmed_outcome`/`confirmed_cause=false`), and predicted-blast-radius impacted resources with coverage/truncation.
- Wired the shared `CopilotDrawerButton` + `CopilotDrawer` (read-only props only) into all five pages: defender-posture, KB detail, patch-priorities, changes, and predeploy.
- Preserved every Phase 03 Exposure behavior on the touched pages (query state, cursor continuity, freshness, completeness, filters/sort, portal handoffs, risk-exception controls) — the Copilot context is additive and reads from already-loaded state.
- Preserved all remediation safety behavior: `remediation/page.tsx` and `REMEDIATION_STARTERS` are unchanged; the remediation regression suite (56 tests) passes untouched.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

**Task 1: Defender posture, KB detail, patch priorities**
1. `5104db463` test(11-08): pin Defender, KB, and patch-priority adapter contracts (RED)
2. `9d47e1b16` feat(11-08): add contextual Copilot to Defender, KB, and patch pages (GREEN)

**Task 2: Changes, predeploy assessment, and remediation correlation**
3. `1a1c0e309` test(11-08): pin changes and predeploy adapter contracts (RED)
4. `5cdf4c629` feat(11-08): add contextual Copilot to changes and predeploy pages (GREEN)

Every commit includes the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer.

## Files Modified

- `web/src/lib/copilot/page-adapters.ts` — Added Defender/KB/patch/changes/predeploy input contracts, four starter sets, five `*CoreInput` mappers + `kbDetailStarters`, and five exported builders. No change to `CORE_COPILOT_PAGE_ADAPTERS` or `PAGE_DISPOSITIONS` (sub-routes follow the CVE-detail convention).
- `web/src/lib/copilot/page-adapters.test.ts` — Added the Defender/KB/patch and changes/predeploy adapter regression matrices.
- `web/src/app/exposure/defender-posture/page.tsx`, `.../kbs/[id]/page.tsx`, `.../patch-priorities/page.tsx`, `web/src/app/changes/page.tsx`, `web/src/app/changes/predeploy/page.tsx` — Built the read-only Copilot context from already-loaded sections and rendered the advisory drawer entry point.
- `web/src/app/exposure/defender-posture/page.test.tsx`, `.../kbs/[id]/page.test.tsx`, `.../patch-priorities/page.test.tsx` — Added `buildCopilotSnapshot` to the co-located `@/lib/services` mocks so the newly-rendered drawer builds a snapshot (mirrors the Plan 11-15 remediation test change).

## Mutation-Boundary Decisions

- Every drawer receives only `snapshot`, `starterQuestions`, `requestedScope`, and `contextLabel`. No `onApprove`/`onExecute`/`onDeploy` callback exists on any of the five pages.
- All new starter hints resolve to read-only tools (`cve_exposure`, `cve_attack_path`, `incidents`, `remediation_opportunities`); tests assert none match a write/deploy/approve/execute/remediate/run pattern.
- The shared core evidence path forces `actionable:false`/`mutation_authorized:false` on every row; a diff scan confirms no `actionable:true`/`mutation_authorized:true` was introduced.
- Existing governed controls (Defender portal handoff, KB "Open governed remediation" link, patch risk-exception dialog, predeploy assessment submit) were not modified and remain the only mutation/handoff paths.

## Deviations from Plan

### 1. [Rule 3 - Blocking test support] Added `buildCopilotSnapshot` to three co-located page-test service mocks
- **Found during:** Task 1 (defender/patch page tests) and re-used for KB.
- **Issue:** Rendering the new `CopilotDrawer` calls `services.buildCopilotSnapshot`, which the existing `vi.mock("@/lib/services", …)` in `defender-posture/page.test.tsx`, `kbs/[id]/page.test.tsx`, and `patch-priorities/page.test.tsx` did not export, throwing during render.
- **Fix:** Added `buildCopilotSnapshot: (input) => input` to each mock — the identical, minimal shim Plan 11-15 added to the remediation page test.
- **Files modified:** the three `page.test.tsx` files listed above.
- **Commit:** `9d47e1b16` (Task 1 GREEN).

### 2. [Scope-preserving] `remediation/page.tsx` intentionally not modified
- **Plan reference:** Task 2 listed `web/src/app/remediation/page.tsx` in `files_modified` for "remediation correlation."
- **Decision:** The cross-domain "change plus incident/remediation specialists" behavior is delivered by the `buildChangesCopilotContext` and `buildPredeployCopilotContext` starter hints (which include `incident` and `remediation` specialists). Modifying the remediation adapter/page would have broken its Phase 11-15 safety test (`exposes no Copilot mutation path…` asserts every remediation starter is `specialistId:"remediation"`) and touched the governed mutation boundary the plan explicitly requires be preserved.
- **Effect:** The plan's cross-domain correlation acceptance criteria are met via the changes/predeploy adapters; the remediation regression suite runs unchanged (56 tests pass) as the required guard.

### 3. [Test refinement in GREEN] Patch adapter assertion + source-status vocabulary
- The RED patch test selected the patch evidence row by array index; because snapshot evidence is sorted by canonical `evidence_id`, the GREEN commit refined the assertion to select by `data.exposure_id` and corrected a source-status `freshness` fixture from the evidence vocabulary (`aging`) to the v2 vocabulary (`partial`) the page actually emits.

## Threat Model Verification

- **T-11-26 (Tampering, partial security evidence, high):** Mitigated. Every section carries explicit visible/total coverage, `complete`/`truncated`, and `available ? freshness : unavailable` source status; deterministic insufficiency prevents unsupported definitive claims. Proven by the Defender/KB/patch unavailable-vs-empty and truncation assertions.
- **T-11-27 (Elevation, patch/change handoff, high):** Mitigated. Hints are advisory read-only tools; all mutations stay behind existing approval/execution/portal endpoints. Proven by the no-mutation-path and starter-tool assertions plus the unchanged remediation regression suite.
- **T-11-28 (Spoofing, KB/change identity, medium):** Mitigated. Stable domain namespace/kind/key identities (KB, CVE, change correlation) and canonical ARM identities (assets, machines, impacted resources) with retained citations. Proven by the identity assertions in the adapter matrix.

No new security-relevant surface (network endpoints, auth paths, file access, schema) was introduced beyond the plan's threat register.

## Independent Code Review

The `claude` CLI is installed but could not reach its API in this sandbox (`Execution error`, consistent with Plan 11-15), so an automated independent pass was unavailable. A rigorous manual critical review of the full implementation diff was performed:
- No mutation calls, write/execute/deploy hints, `actionable:true`, or `mutation_authorized:true` paths introduced (diff scan clean; every row forced non-actionable/non-authorized by the shared core path).
- No forbidden files touched (backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, `remediation/page.tsx`, unrelated routes) — confirmed via `git diff --name-only`.
- Predeploy predicted/observed flags present on all four predicted record kinds; change correlation basis is temporal-proximity/`confirmed:false`.
- No blocking findings. One non-blocking observation: `changes`/`predeploy` freshness is presence-based (`fresh` once data loads / `unavailable` on error), consistent with the Plan 11-07 CVE-source pattern; the Exposure pages carry real per-section status.

## Verification Gates

| Gate | Result |
|---|---|
| Task 1 focused (`page-adapters.test.ts` + `CopilotPageIntegrations.test.tsx`) | 36 + 3 passed |
| Task 1 co-located page tests (defender, patch, KB) | 5 + 9 + 7 passed |
| Task 2 focused (`page-adapters.test.ts` + integration + remediation regression) | 39 + 3 + 56 passed |
| Full web Vitest suite | 56 files, 582 tests passed |
| ESLint (`next lint`, full project) | No warnings or errors |
| TypeScript (`tsc --noEmit`) | Clean (exit 0) |
| Diff / scope check | Only the 8 plan files + 2 predeploy/changes pages changed; no forbidden paths |
| Working tree | Clean |

The existing Vite CommonJS deprecation notice and unrelated Keyborg warnings remain non-failing.

## Success Criteria

1. Security, patch, and change pages have typed contextual entry points — met (five adapters + five wired drawers).
2. Cross-domain correlation is cited and scope-safe — met (changes/predeploy starters reach incident + remediation specialists; correlation is temporal-proximity, predeploy is predicted, all evidence cited and bounded).
3. No page bypasses approval or tool policy — met (read-only drawer props only; all mutations stay behind existing server endpoints; remediation regression unchanged).

## Delivery Status

- No backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, `remediation/page.tsx`, or unrelated-route implementation was changed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged (consistent with the Plan 11-07/11-14/11-15 worktree convention); Phase 11 is not marked complete.
- Nothing was pushed, merged, deployed, built for release, or integrated with `origin/main`. The merge/deployment/live-API freeze is preserved.

## Self-Check: PASSED
