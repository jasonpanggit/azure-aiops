---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 07
subsystem: ui
tags: [copilot, page-adapters, exposure, cve, situations, react, typescript, evidence-snapshot]

# Dependency graph
requires:
  - phase: 11-02
    provides: Canonical Copilot request/snapshot v2 contract and drawer submission path
  - phase: 11-03
    provides: Typed evidence snapshot contract and stable evidence-id algorithm
  - phase: 11-14
    provides: Shared launcher/drawer integration surface for contextual pages
provides:
  - Typed pure page adapters for the six contextual drawer routes (overview, network, compliance, exposure, CVE detail, situations)
  - buildExposureCopilotContext, buildCveDetailCopilotContext, and buildSituationsCopilotContext with stable CVE/situation/asset/KB identities, coverage/freshness semantics, and domain starter hints
  - Removal of route-local snapshot builders from the exposure, CVE detail, and situations routes
affects: [11-15 remediation-handoff, copilot-drawer, specialist-orchestration]

# Actuals (#2632)
actuals:
  tokens: 27813
  tasks: 2
  commits: 8

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure page adapter over already-loaded authorized data feeding the shared canonical snapshot builder"
    - "Route → CoreCopilotAdapterInput mapping keeps routes responsible only for loaded data plus launcher/drawer"
    - "Canonical non-ARM domain identities (CVE/situation/patch/KB) versus canonical ARM resource identities"

key-files:
  created: []
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/app/page.tsx
    - web/src/app/network/page.tsx
    - web/src/app/compliance/page.tsx
    - web/src/app/exposure/page.tsx
    - web/src/app/exposure/cves/[id]/page.tsx
    - web/src/app/situations/page.tsx

key-decisions:
  - "Adapter inputs use narrow structural field interfaces (ExposureSummaryFields, CveSummaryFields, SituationCopilotFields, ...) rather than full domain types, so full domain objects remain assignable while the adapter stays decoupled and pure."
  - "CVE identity is carried as a canonical non-ARM domain entity (namespace vulnerability, kind cve) and is deliberately kept out of snapshot.selected_resources, replacing the prior route-local resource_type:\"CVE\" fabrication."
  - "Provider-unavailable is kept distinct from a healthy empty authorized result via coverage.available (complete=false when unavailable, complete=true when available+empty) plus an explicit unavailable freshness status."
  - "Situations list feeds the adapter with ranked durable situations (display order preserved via id→situation_id mapping) so evidence priority tracks what the operator sees while retaining durable identities."

patterns-established:
  - "type=auto tdd: RED regression commit pinning adapter behavior, then GREEN implementation + route migration."
  - "Route drawers consume context.requestedScope / context.snapshot / context.starterQuestions only — no inline buildCopilotSnapshot/copilotEvidenceRows/page-kind strings."

requirements-completed: [COP-02, COP-04, COP-05]

coverage:
  - id: D1
    description: "Exposure route uses a typed pure adapter preserving vulnerability/asset/patch identities, partial-result coverage, and unavailable-vs-empty status"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#preserves exposure vulnerability/asset/patch identities, partial coverage, and unavailable-vs-empty status"
        status: pass
    human_judgment: false
  - id: D2
    description: "CVE detail route carries the canonical non-ARM CVE identity, KB/finding identities, per-source freshness, and pagination coverage; unavailable provider distinct from healthy empty"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#carries the canonical non-ARM CVE identity, KB/finding identities, source freshness, and pagination coverage"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes an unavailable CVE provider from a healthy empty finding set"
        status: pass
    human_judgment: false
  - id: D3
    description: "Situations list route preserves filters, selected situation identity, source trust, and visible/total pagination; unavailable provider distinct from empty queue"
    requirement: COP-05
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#preserves situation filters, selected identity, source trust, and visible/total pagination"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps an unavailable situations provider distinct from an empty authorized queue"
        status: pass
    human_judgment: false
  - id: D4
    description: "Six contextual routes register as integrated Copilot adapters with no route-local snapshot builders"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#registers Overview, Network, Compliance, Exposure, and Situations as integrated routes"
        status: pass
      - kind: integration
        ref: "src/app/exposure/page.test.tsx + src/app/situations/page.test.tsx + src/app/exposure/cves/[id]/page.test.tsx (all pass)"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 07: Contextual Page Typed Adapter Migration Summary

**All six contextual drawer routes now build their Copilot snapshot through typed pure adapters over already-loaded authorized data, with complete identity/coverage/freshness semantics and no route-local snapshot drift.**

## Performance

- **Duration:** ~18 min (Task 2 this session; Task 1 completed in a prior session)
- **Started:** 2026-09-08T09:40:11Z (Task 2 session)
- **Completed:** 2026-09-08T09:56:00Z (Task 2 commits)
- **Tasks:** 2 of 2 complete
- **Files modified:** 8 (5 touched by Task 2)

## Accomplishments
- Migrated the exposure, CVE detail, and situations routes off inline `buildCopilotSnapshot`/`copilotEvidenceRows` onto three new pure registry adapters (`buildExposureCopilotContext`, `buildCveDetailCopilotContext`, `buildSituationsCopilotContext`).
- Preserved stable CVE/situation/asset/KB identities as canonical non-ARM domain entities (and canonical ARM identities where applicable), with filters/sort, source freshness/status, visible/total truncation coverage, and retained evidence citations.
- Kept provider-unavailable distinct from a healthy empty authorized result across all three routes, and carried domain starter specialist/tool hints without introducing any mutation authority.
- Left same-tab continuity intact (routes still own only their loaded data plus the shared launcher/drawer); remediation handoff remains isolated to Plan 11-15.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

**Task 1: Migrate overview, network, and compliance adapters** (prior session)
1. `4397070a7` test(11-07): pin core page Copilot adapters
2. `6001c78db` feat(11-07): integrate core page Copilot adapters
3. `536370ac2` test(11-07): cover core adapter review regressions
4. `244119497` fix(11-07): harden core page adapter context
5. `5cd149803` test(11-07): pin adapter boundary regressions
6. `63382f7cf` fix(11-07): stabilize adapter boundary metadata

**Task 2: Migrate exposure, CVE detail, and situations list adapters** (this session)
7. `78d30abdc` test(11-07): pin exposure, CVE, and situations adapter regressions (RED)
8. `87b6d1d1d` feat(11-07): migrate exposure, CVE, and situations to typed adapters (GREEN)

_Note: TDD tasks use test → feat commit pairs._

## Files Created/Modified
- `web/src/lib/copilot/page-adapters.ts` — Added exposure/CVE/situations input contracts, `*CoreInput` mappers, three exported build functions, page configs, starter arrays, `/exposure` + `/situations` dispositions, and registry entries; widened the shared `buildCoreCopilotContext` config to accept the dynamic CVE `page_id`.
- `web/src/lib/copilot/page-adapters.test.ts` — Added the exposure/CVE/situations adapter regression matrix and extended the integrated-route registry assertion.
- `web/src/app/exposure/page.tsx` — Replaced the inline snapshot with `buildExposureCopilotContext`; added `toExposureCopilotSection` projection over loaded sections.
- `web/src/app/exposure/cves/[id]/page.tsx` — Replaced the inline snapshot with `buildCveDetailCopilotContext`; added `copilotSectionTrust` availability/freshness projection.
- `web/src/app/situations/page.tsx` — Replaced the inline snapshot with `buildSituationsCopilotContext`; feeds ranked durable situations with pagination totals and source trust.
- `web/src/app/page.tsx`, `web/src/app/network/page.tsx`, `web/src/app/compliance/page.tsx` — Task 1 (prior session) core-route migrations.

## Decisions Made
- Adapter input types are narrow structural field interfaces so pages can pass full domain objects while the adapter remains decoupled and genuinely pure (no domain-type import coupling, no data access).
- CVE identity is a domain (non-ARM) selected entity retained inside snapshot evidence and `selectedEntities`; it is intentionally excluded from `selected_resources`, correcting the prior `resource_type:"CVE"` route-local fabrication.
- `coverage.available` carries the unavailable-vs-empty distinction (complete=false when unavailable, complete=true when available+empty), reinforced by an explicit `unavailable` freshness status per source.

## Deviations from Plan

None — plan executed as written. Task 2 followed the Task 1 adapter pattern; no auto-fix (Rule 1–3) or architectural (Rule 4) deviations were required.

## Issues Encountered
- Initial adapter input interfaces referenced full domain types (`VulnerabilitySummary`, `PatchPriority`, `CveDetail["cve"]`), which made the fixtures and callers brittle under `tsc`. Resolved by switching to narrow structural field interfaces; full domain objects remain assignable.
- `rankDurableSituations` returns the UI `SituationSummary` view (field `id`), not `DurableSituation` (field `situation_id`). Resolved by mapping ranked summaries back to durable records via `id → situation_id`, preserving display order while retaining durable identities.

## Independent Code Review

The `/gsd-code-review` skill was loaded, but its `gsd-code-reviewer` subagent could not be dispatched in this direct (non-orchestrated) execution context — no Task/Agent spawn tool is exposed to the executor here. A manual critical review of the full Task 2 diff was performed instead:
- No mutation calls, write/execute tool hints, or `mutation_authorized:true` paths introduced (verified: evidence rows force `actionable:false`/`mutation_authorized:false`).
- No forbidden files touched (backend, Terraform, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, unrelated routes) — confirmed via `git diff --name-only`.
- Deterministic evidence identities verified across input reordering; unavailable-vs-empty distinction verified by dedicated tests.
- No blocking findings. One minor observation (non-blocking): the CVE "cve" source freshness is presence-based (reported `fresh` when the CVE core loaded and the drawer is rendered); acceptable because the drawer only renders when the CVE record loaded successfully.

## Verification Gates

- Task 1 focused: `page-adapters.test.ts` + `CopilotPageIntegrations.test.tsx` + `compliance/page.test.tsx` — pass.
- Task 2 focused: `page-adapters.test.ts` + `CopilotPageIntegrations.test.tsx` + `exposure/page.test.tsx` + `situations/page.test.tsx` (+ `exposure/cves/[id]/page.test.tsx`) — pass.
- Full web suite: 56 files, 567 tests — all pass.
- Lint (`next lint`): no warnings or errors.
- TypeScript (`tsc --noEmit`): clean (exit 0).
- Route-local snapshot check: no `buildCopilotSnapshot`/`copilotEvidenceRows`/`pageKind`/`page_kind`/`selectedResources` references remain in the three migrated routes.
- Git diff / scope check: only the 8 plan `files_modified` changed; forbidden paths untouched.

## Success Criteria
1. Existing drawer behavior preserved through typed adapters — met (all page + integration tests pass).
2. Coverage/freshness/identity semantics complete — met (adapter matrix asserts identities, visible/total coverage, per-source freshness, unavailable-vs-empty).
3. Routes ready for the separately isolated remediation handoff slice (Plan 11-15) — met (no mutation authority added; continuity preserved).

## Self-Check: PASSED
