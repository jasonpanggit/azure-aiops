---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 10
subsystem: ui
tags: [copilot, page-adapters, situations, services, operational-twin, react, typescript, read-only, provenance]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 09
    provides: Shared CoreCopilotAdapter path, sub-route builder convention, unregistered-sub-route registry contract, and read-only CopilotDrawer wiring pattern
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 08
    provides: buildCoreCopilotContext / services.buildCopilotSnapshot pipeline that forces actionable:false / mutation_authorized:false on every row
provides:
  - Typed read-only situation-detail, services-list, service-detail, and operational-twin Copilot adapters over already-loaded authorized evidence
  - Shared contextual Copilot entry points on the situation detail, services list, service detail, and operational twin pages
  - Replacement of the service-detail /copilot query-link handoff with the shared in-place drawer (same-tab continuity)
  - Bounded exact-manifest specialist hints (incident, resource_health_observability, network) with no mutation authority (D-03, D-04, D-08, D-09)
affects: [11-16]

# Actuals (#2632)
actuals:
  tokens: 16755
  tasks: 2
  commits: 5

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Four new pure typed page inputs map into the shared CoreCopilotAdapter, inheriting forced actionable:false/mutation_authorized:false on every evidence row"
    - "Detail-page sub-route adapters (situation:{id}, service:{name}, twin) are exported builders but are NOT registered in CORE_COPILOT_PAGE_ADAPTERS — the same CVE-detail convention preserved by Plans 11-08/11-09; Plan 11-16 owns the exhaustive 28-route/manifest parity gate"
    - "Canonical ARM identities (affected resources, service dependencies, twin resource nodes) are retained as scope-validated azure entities; non-ARM identities (situations, business services, twin domain nodes) stay namespace 'operations' domain entities"
    - "Scenario projections are marked observed:false and unsupported twin edges / prior twin revisions are appended as builder uncertainty so hypothetical or historical data never reads as asserted current reality (D-09)"

key-files:
  created: []
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/app/situations/[id]/page.tsx
    - web/src/app/situations/[id]/page.test.tsx
    - web/src/app/services/page.tsx
    - web/src/app/services/[name]/page.tsx
    - web/src/app/twin/page.tsx
    - web/src/app/twin/page.test.tsx

key-decisions:
  - "Four new pure typed adapters (buildSituationDetailCopilotContext, buildServicesCopilotContext, buildServiceDetailCopilotContext, buildTwinCopilotContext) route through the existing buildCoreCopilotContext / services.buildCopilotSnapshot path, so every row is forced non-actionable/non-mutation-authorized and no route-local snapshot builder exists."
  - "The service-detail page's /copilot?service= query-link handoff is replaced with the shared CopilotDrawer entry point; investigation now continues in the same tab with the current page snapshot becoming current context (D-03, D-08)."
  - "Situation detail binds the selected situation identity, per-row durable evidence trust (quality/availability/freshness), affected ARM resources, bounded links, and recorded audit context; source-status freshness is retained independently of row order and an unavailable source stays distinct from a fresh one."
  - "Services list binds visible services with ownership/scope/health-risk facts and active-situation counts, honest visible/total coverage (filters reduce visible count as legitimate partial coverage), and keeps an unavailable connections/incidents provider distinct from an authorized empty catalog."
  - "Service detail binds the selected service identity plus ownership from the semantic subject and dependency/blast-radius names harvested from the typed section keys (impacted_resources, impacted_applications, impacted_services, impacted_business_services, upstream_dependencies, downstream_dependents); each of context/risk/impact is an independently-available source."
  - "Operational twin binds entity/relationship/temporal/scenario/traversal identities with provenance and ARM-vs-domain distinction; bounded graph/relationship/timeline results expose visible/total/truncated coverage; unsupported relationships and prior twin revisions stay uncertain and scenario projections stay non-observed. The twin source_status metadata (e.g. request_time) is intentionally NOT fed to freshness mapping — availability drives the synthesized twin freshness so live request-time reads are not mislabelled unavailable."
  - "Every starter hint uses only specialist IDs and tools drawn from src/operations/specialists.v1.json and each page's own page_mappings owner: situation_detail->incident (incidents, business_service_context, impact_context); services/service_detail->resource_health_observability (incidents, impact_context, search); twin->network (impact_context, network_topology, hub_dependents). Plan 11-16 compares every hint and route mapping exactly."

patterns-established:
  - "Detail-page in-place Copilot: replace cross-page query-link handoffs with the shared drawer so the new page snapshot becomes current thread context without leaving the tab."
  - "Uncertainty-first twin projection: hypothetical (scenario) and historical (prior revision / unsupported edge) facts are surfaced as explicit uncertainty rather than asserted rows."

requirements-completed: [COP-02, COP-04, COP-05]

coverage:
  - id: D1
    description: "Situation detail adapter binds identity, timeline, per-row evidence/source trust, affected ARM resources, links, and audit context with incident hints; unavailable vs fresh and unavailable vs empty stay distinct"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds situation identity, timeline, evidence trust, affected resources, and links"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps an unavailable source distinct from a fresh source and retains stale freshness"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes an unavailable situation record from an authorized empty detail"
        status: pass
    human_judgment: false
  - id: D2
    description: "Situation detail page exposes a read-only Copilot entry point that opens the shared drawer in place"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/app/situations/[id]/page.test.tsx#offers a read-only Copilot entry point that opens the shared drawer in place"
        status: pass
    human_judgment: false
  - id: D3
    description: "Services list adapter binds visible services with ownership/health facts, filters, and honest total coverage; unavailable vs empty catalog stays distinct; resource_health_observability hints"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds visible services with ownership/health facts, filters, and honest total coverage"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps an unavailable services catalog distinct from an authorized empty catalog"
        status: pass
    human_judgment: false
  - id: D4
    description: "Service detail adapter binds selected identity, ownership, ARM/domain dependencies, cited evidence, and per-section availability; replaces the query-link handoff"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds selected service identity, ownership, dependencies, and cited evidence"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps an unavailable service section distinct from a fresh one"
        status: pass
    human_judgment: false
  - id: D5
    description: "Operational twin adapter binds entity/relationship/timeline/traversal/scenario identities with provenance, ARM/domain distinction, bounded truncation coverage, uncertain unsupported edges, non-observed scenarios, and unavailable-vs-empty distinction; network hints"
    requirement: COP-05
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds twin entity, relationship, timeline, traversal, and scenario identities with provenance"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#exposes visible/total/truncated coverage for bounded graph and traversal results"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps unsupported relationships and stale temporal evidence uncertain rather than asserted"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes an unavailable twin from an empty authorized twin"
        status: pass
    human_judgment: false
  - id: D6
    description: "Operational twin page exposes a read-only Copilot entry point that opens the shared drawer in place"
    requirement: COP-05
    verification:
      - kind: unit
        ref: "src/app/twin/page.test.tsx#offers a read-only Copilot entry point that opens the shared drawer in place"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 11-10: Situation/Service/Twin Contextual Copilot Integration Summary

**Situation detail, services list/detail, and the operational twin now open a read-only, evidence-aged Copilot in place over their already-loaded authorized data — replacing the service-detail redirect handoff and keeping identities, freshness, coverage bounds, and scenario/historical uncertainty honest ahead of the isolated 28-route parity gate.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 (both TDD RED/GREEN)
- **Commits:** 5

## Accomplishments

- **Situation detail** binds the selected situation identity, evidence timeline, per-row source trust (quality/availability/freshness), affected ARM resources, bounded labelled links, and recorded audit context; independent source-status freshness is retained and an unavailable source is distinct from a fresh one.
- **Services list** binds visible services with ownership/scope/health-risk facts and active-situation counts, exposes honest visible/total coverage, and keeps an unavailable connections/incidents provider distinct from an authorized empty catalog.
- **Service detail** replaces the fragile `/copilot?service=` query-link with the shared in-place drawer, binding the selected service identity, ownership from the semantic subject, ARM/domain dependency names from typed section keys, cited evidence, and independent per-section (context/risk/impact) availability.
- **Operational twin** binds entity/relationship/temporal/scenario/traversal identities with provenance and ARM-vs-domain distinction, exposes visible/total/truncated coverage for bounded graph results, and keeps unsupported edges and prior revisions uncertain while scenario projections stay explicitly non-observed.
- All four adapters route through the shared `buildCoreCopilotContext` / `services.buildCopilotSnapshot` pipeline, so every row is forced non-actionable / non-mutation-authorized and no route-local snapshot builder exists. Detail sub-route builders stay unregistered in `CORE_COPILOT_PAGE_ADAPTERS`, matching the CVE-detail convention.

## Verification

- Focused adapter + page suites (Task 1 and Task 2 `<verify>` commands): pass.
- Full web suite: **606 passed / 56 files**.
- `tsc --noEmit`: clean. `next lint`: no warnings or errors.
- Diff scope: exactly the 8 plan-declared files; working tree clean; no backend, Terraform, `services.ts`, `types.ts`, drawer/thread-context, STATE/ROADMAP, or unrelated routes touched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored an accidentally-removed situation-detail test**
- **Found during:** Task 1 self-check (test-count reconciliation).
- **Issue:** While adding the situation-detail Copilot entry-point test in the RED step, the edit replaced the existing "shows audit service failure separately from successful empty history" test instead of appending, dropping one existing assertion.
- **Fix:** Restored the audit-failure test so it coexists with the new Copilot entry test (5 tests total in `situations/[id]/page.test.tsx`).
- **Files modified:** web/src/app/situations/[id]/page.test.tsx
- **Commit:** 5e157934c

## Notes for 11-16 (parity gate)

- Route → specialist mappings implemented here follow each page's `specialists.v1.json` `page_mappings` owner exactly: `situation_detail→incident`, `services`/`service_detail→resource_health_observability`, `twin→network`. Every starter tool exists in the owning specialist's `operations_mcp_tools`.
- The new detail/list adapters are intentionally NOT registered in `CORE_COPILOT_PAGE_ADAPTERS`; 11-16 derives the 28-route inventory from the filesystem and asserts one disposition per route.

## Independent Review

An independent cross-AI reviewer was not available (only a same-family `claude` CLI is installed, which is not an independent second opinion, and the phase freeze prohibits live external API calls). Verification relied on the full TDD suite, `tsc`, `next lint`, and diff-scope inspection, all green.

## Self-Check: PASSED
