---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 09
subsystem: ui
tags: [copilot, page-adapters, connections, fabric-medallion, governance, identity, finops, resource-health, react, typescript]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 05
    provides: Specialist manifest and the four new domain specialists (inventory_data_health, identity_access, finops, resource_health_observability)
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 08
    provides: Shared CoreCopilotAdapter path, sub-route builder convention, and read-only drawer wiring pattern
provides:
  - Typed read-only data-health, Fabric medallion, governance, identity, FinOps, and resource-health Copilot adapters over already-loaded authorized evidence
  - Shared contextual Copilot entry points on the connections, connections/fabric, governance, identity, finops, and resource-health pages
  - Bounded exact-manifest specialist hints for the four new domain specialists without any mutation authority (D-03, D-04, D-05, D-06, D-08, D-09)
affects: [11-16]

# Actuals (#2632)
actuals:
  tokens: 20543
  tasks: 2
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Six new pure typed page inputs map into the shared CoreCopilotAdapter, inheriting forced actionable:false/mutation_authorized:false on every evidence row"
    - "Sub-route/top-level adapters are exported builders but are NOT registered in CORE_COPILOT_PAGE_ADAPTERS (same convention as CVE detail and the Plan 11-08 adapters), preserving the exact top-level registry contract"
    - "Independent optional-source degradation is modelled per-section (settings vs access-reviews vs exports; layers vs capacity) so an unavailable enrichment never blanks a page"
    - "Custom uncertainty is appended by the builder for deployment-blocked capacity and genuinely-unavailable cost/health metrics (states buildCoreCopilotContext does not derive from coverage/freshness alone)"

key-files:
  created: []
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/app/connections/page.tsx
    - web/src/app/connections/page.test.tsx
    - web/src/app/connections/fabric/page.tsx
    - web/src/app/connections/fabric/page.test.tsx
    - web/src/app/governance/page.tsx
    - web/src/app/identity/page.tsx
    - web/src/app/finops/page.tsx
    - web/src/app/resource-health/page.tsx

key-decisions:
  - "Six new pure typed adapters (buildConnectionsCopilotContext, buildFabricMedallionCopilotContext, buildGovernanceCopilotContext, buildIdentityCopilotContext, buildFinOpsCopilotContext, buildResourceHealthCopilotContext) route through the existing buildCoreCopilotContext / services.buildCopilotSnapshot path, so every row is forced non-actionable/non-mutation-authorized and no route-local snapshot builder exists."
  - "Identity principals, subscription owners, stale-access assignments, and SPN credentials are non-ARM domain identities (namespace 'identity'); the principal id lives only in the domain source_key and is never leaked into a scope-validated Azure resource field (T-11-29 redaction). FinOps opportunity/waste resources and resource-health resources are canonical ARM entities."
  - "Independent optional-provider degradation is preserved: connection sync-failed is a distinct deployment_blocked state; Fabric paused capacity is a distinct deployment-blocked uncertainty separate from an unavailable layer read; governance settings stay usable when access-review/export enrichment is unavailable; a cached resource-health snapshot is still fresh evidence; FinOps null savings stay 'not quantified' and unavailable_metrics are surfaced as uncertainty."
  - "Every starter hint uses only specialist IDs and tools drawn from src/operations/specialists.v1.json: inventory_data_health/inventory_resources (connections, connections_fabric), governance/{business_service_context,risk_context,impact_context}, identity_access/{risk_context,business_service_context,search}, finops/{business_service_context,risk_context,search}, resource_health_observability/{incidents,impact_context,search}. Plan 11-16 compares every hint and route mapping exactly."
  - "The Fabric medallion page adds four page-level medallion reads (layers/manifest/governance/capabilities) to feed the read-only adapter because the embedded FabricMedallionPanel owns its own reads and src/components/fabric/medallion.tsx is not in this plan's scope; the panel is left untouched."

requirements-completed: [COP-02, COP-03, COP-04]

coverage:
  - id: T1
    description: "Connections adapter binds subscription-connection source identities, capacity, deployment-blocked state, coverage, and inventory_data_health hints; healthy-empty vs unavailable stay distinct"
    requirement: COP-03
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds connection source identities, capacity, deployment-blocked state, coverage, and inventory hints"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes a healthy-empty connection registry from an unavailable one"
        status: pass
    human_judgment: false
  - id: T2
    description: "Fabric medallion adapter binds layer/manifest/governance/readiness with partial freshness; deployment-blocked capacity stays distinct from an unavailable provider"
    requirement: COP-03
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds medallion layer, manifest, governance, and readiness evidence with partial freshness"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps deployment-blocked capacity distinct from an unavailable Fabric provider"
        status: pass
    human_judgment: false
  - id: T3
    description: "Governance adapter binds roles/policies/audiences/export kinds with bounded totals and independent optional-source availability"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds governance roles, policies, audiences, and export kinds with bounded totals"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#treats settings, audiences, and export kinds as independent optional sources"
        status: pass
    human_judgment: false
  - id: T4
    description: "Identity adapter binds principal/owner/access-review/SPN as scope-safe domain identities with redaction; unavailable vs healthy-empty stay distinct"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds principal, owner, access-review, and SPN identities as scope-safe domain identities"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#distinguishes an unavailable identity provider from a healthy-empty scope"
        status: pass
    human_judgment: false
  - id: T5
    description: "FinOps adapter binds attribution/opportunity/waste with currency, observation window, totals, not-quantified nulls, and unavailable-metric uncertainty"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds FinOps attribution, opportunity, and waste with currency, window, totals, and uncertainty"
        status: pass
    human_judgment: false
  - id: T6
    description: "Resource-health adapter binds ARM resource identities, observation windows, and missing-series status; unavailable vs empty stay distinct"
    requirement: COP-04
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#binds resource-health identities, observation windows, and missing-series status"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#keeps an unavailable resource-health provider distinct from an empty scope"
        status: pass
    human_judgment: false
  - id: T7
    description: "The six integrated pages render the shared read-only Copilot drawer entry point; co-located connection/fabric page tests remain green"
    requirement: COP-03
    verification:
      - kind: integration
        ref: "src/app/connections/page.test.tsx (17 tests)"
        status: pass
      - kind: integration
        ref: "src/app/connections/fabric/page.test.tsx (5 tests)"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 09: Contextual Copilot Across Data-Health, Governance, Identity, Cost, and Observability Pages Summary

**The connections, Fabric medallion, governance, identity, FinOps, and resource-health pages now expose a shared read-only contextual Copilot over their already-loaded, authorized evidence — preserving stable source/layer/manifest/role/principal/cost/resource identities, visible/total coverage, per-source freshness, and every independent optional-provider degradation state (healthy-empty, deployment-blocked, partial, stale, unavailable) — while identity principals stay scope-safe non-ARM domain identities, cost figures stay currency/window/coverage-honest with null savings preserved as "not quantified", and every evidence row remains non-actionable/non-mutation-authorized with exact-manifest specialist hints for the four new domain specialists.**

## Accomplishments

- Added six pure typed page adapters in `page-adapters.ts`, each routed through the shared `buildCoreCopilotContext` / `services.buildCopilotSnapshot` path so they inherit the forced `actionable:false` / `mutation_authorized:false` guarantee on every row:
  - `buildConnectionsCopilotContext` — subscription-connection sources with health, sync, record-count capacity, business context, and a derived `deployment_blocked` flag; coverage + freshness distinguish healthy-empty from unavailable.
  - `buildFabricMedallionCopilotContext` — Bronze/Silver/Gold layer counts, manifest projections, governance gaps, and capacity/semantic/Data-Agent readiness with a distinct deployment-blocked uncertainty and partial-freshness handling; optional Gold/Data-Agent grounding is never treated as a prerequisite.
  - `buildGovernanceCopilotContext` — enterprise roles (ownership/privileged), policy-section summaries, access-review audiences (identity-collaboration evidence), and audit-export kinds with bounded totals and independent settings/access-review/export availability.
  - `buildIdentityCopilotContext` — principal risk, subscription owners, stale-access assignments, and SPN credentials as scope-safe non-ARM domain identities with bounded fields.
  - `buildFinOpsCopilotContext` — cost summary (currency + observation window), attribution groups, savings opportunities (canonical ARM resources), and waste, with null savings preserved as "not quantified" and genuinely-unavailable metrics surfaced as uncertainty.
  - `buildResourceHealthCopilotContext` — Azure Monitor resource utilization as canonical ARM identities with observation windows, per-resource and page-level missing-series status, and cached-still-fresh freshness.
- Wired the shared `CopilotDrawerButton` + `CopilotDrawer` (read-only props only) into all six pages: connections, connections/fabric, governance, identity, finops, and resource-health.
- Preserved every existing behavior on the touched pages — connection Sync polling and delete, ontology automation run/refresh, Fabric subscription picker and same-tab URL continuity, governance pack generation / settings save / JSON download, identity filters/pagination, FinOps dimension switching, and resource-health cached refresh — the Copilot context is additive and reads from already-loaded state.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

**Task 1: Connections, Fabric medallion, and governance**
1. `076983855` test(11-09): pin connections, Fabric medallion, and governance adapter contracts (RED)
2. `be64014bd` feat(11-09): add contextual Copilot to connections, Fabric, and governance pages (GREEN)

**Task 2: Identity, FinOps, and resource health**
3. `d3b888d45` test(11-09): pin identity, FinOps, and resource-health adapter contracts (RED)
4. `bb66958e9` feat(11-09): add contextual Copilot to identity, FinOps, and resource-health pages (GREEN)

Every commit includes the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer.

## Files Modified

- `web/src/lib/copilot/page-adapters.ts` — Added six input contracts, three new starter sets per task (CONNECTIONS/FABRIC_MEDALLION/GOVERNANCE and IDENTITY/FINOPS/RESOURCE_HEALTH), six `*CoreInput` mappers, and six exported builders. No change to `CORE_COPILOT_PAGE_ADAPTERS` or `PAGE_DISPOSITIONS` (top-level/sub-route builders follow the CVE-detail / Plan 11-08 convention).
- `web/src/lib/copilot/page-adapters.test.ts` — Added the connections/Fabric/governance and identity/FinOps/resource-health adapter regression matrices.
- `web/src/app/connections/page.tsx`, `web/src/app/connections/fabric/page.tsx`, `web/src/app/governance/page.tsx`, `web/src/app/identity/page.tsx`, `web/src/app/finops/page.tsx`, `web/src/app/resource-health/page.tsx` — Built the read-only Copilot context from already-loaded sections and rendered the advisory drawer entry point.
- `web/src/app/connections/page.test.tsx`, `web/src/app/connections/fabric/page.test.tsx` — Added `buildCopilotSnapshot: (input) => input` to the co-located `@/lib/services` mocks so the newly-rendered drawer builds a snapshot (identical, minimal shim used by Plan 11-08).

## Mutation-Boundary Decisions

- Every drawer receives only `open`, `onClose`, `contextLabel`, `requestedScope`, `snapshot`, and `starterQuestions`. No `onApprove`/`onExecute`/`onDeploy`/sync callback exists on any of the six pages.
- All new starter hints resolve to read-only tools; tests assert none match a `write|update|delete|execute|remediate|approve|run|deploy` pattern, and every hint uses a specialist/tool pair drawn from `src/operations/specialists.v1.json`.
- The shared core evidence path forces `actionable:false`/`mutation_authorized:false` on every row; a diff scan confirms no `actionable:true`/`mutation_authorized:true`, `onApprove`, `onExecute`, or `onDeploy` was introduced.
- Existing governed controls (connection Sync/delete, ontology run, governance settings save + pack download, resource-health refresh) were not modified and remain the only mutation paths.

## Deviations from Plan

### 1. [Rule 3 - Blocking test support] Added `buildCopilotSnapshot` to two co-located page-test service mocks
- **Found during:** Task 1 (connections and fabric page tests, both named in Task 1's `<verify>`).
- **Issue:** Rendering the new `CopilotDrawer` calls `services.buildCopilotSnapshot`, which the existing `vi.mock("@/lib/services", …)` in `connections/page.test.tsx` and `connections/fabric/page.test.tsx` did not export, throwing during render.
- **Fix:** Added `buildCopilotSnapshot: (input) => input` to each mock — the identical, minimal shim Plan 11-08 added to its co-located page tests.
- **Files modified:** `web/src/app/connections/page.test.tsx`, `web/src/app/connections/fabric/page.test.tsx`.
- **Commit:** `be64014bd` (Task 1 GREEN).

### 2. [Rule 3 - Blocking data plumbing] Fabric medallion page adds page-level medallion reads
- **Found during:** Task 1 (Fabric medallion adapter).
- **Issue:** The plan's key link feeds a "medallion health/coverage/freshness adapter" from `connections/fabric/page.tsx`, but that page previously held only the subscription list; the medallion layer/manifest/governance/capability reads live inside `FabricMedallionPanel` (`src/components/fabric/medallion.tsx`), which is not in this plan's scope.
- **Fix:** Added four page-level `useApi` reads (layers/manifest/governance/capabilities) scoped to the selected subscription to feed the read-only adapter, leaving the panel untouched. This is additive data loading, not a route-local snapshot builder — the snapshot is still produced by the shared adapter.
- **Effect:** The page issues the four medallion reads independently of the embedded panel (a minor duplicate-fetch); no behavior change to the panel.
- **Commit:** `be64014bd` (Task 1 GREEN).

### 3. [Scope-preserving] Identity non-human identities folded into the summary
- The identity page's non-human identity table is unchanged; the adapter carries the non-human principal count via `summary.non_human_principal_count` rather than adding a distinct evidence section, keeping the principal/owner/access-review/SPN identity set bounded and focused (per the plan's identity behavior).

## Threat Model Verification

- **T-11-29 (Information disclosure, identity adapter, high):** Mitigated. Principals, owners, stale-access assignments, and SPN credentials are non-ARM domain identities; the principal id lives only in the domain `source_key`, never in a scope-validated Azure resource field. Fields are bounded (principal_type, privileged, stale, widest_scope_breadth, assignment_count, role_count, bounded roles). Server-side entity resolution and reauthorization are unchanged. Proven by the redaction assertions (`resource_id === undefined`, `entity.type === "domain"`).
- **T-11-30 (Tampering, cost/health completeness, medium):** Mitigated. FinOps carries explicit currency, observation window (`actual_spend_period_start`/`end`), visible/total coverage, and preserves null savings as "not quantified"; genuinely-unavailable metrics surface as uncertainty. Resource-health carries observation windows, per-resource and page-level missing-series status, and coverage. Proven by the FinOps window/uncertainty and resource-health missing-series assertions.
- **T-11-31 (Tampering, optional provider state, high):** Mitigated. Connection sync-failed → distinct `deployment_blocked`; Fabric paused capacity → distinct deployment-blocked uncertainty separate from an unavailable layer read; governance settings stay usable when access-review/export enrichment is unavailable; identity/resource-health distinguish unavailable from healthy-empty. Proven by the distinct-state assertions across all four cases.

No new security-relevant surface (network endpoints, auth paths, file access, schema) was introduced beyond the plan's threat register; the four page-level Fabric reads use existing authenticated `fabricMedallionApi` endpoints.

## Independent Code Review

The `claude` CLI is installed but its API was unreachable in this sandbox (`timeout`/exit 124, consistent with Plan 11-08), so an automated independent pass was unavailable. A rigorous manual critical review of the full implementation diff was performed:
- No mutation calls, write/execute/deploy hints, `actionable:true`, or `mutation_authorized:true` paths introduced (diff scan clean; every row forced non-actionable/non-authorized by the shared core path).
- No forbidden files touched (backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, `medallion.tsx`, `remediation/page.tsx`, `STATE.md`, `ROADMAP.md`, unrelated routes) — confirmed via `git diff --name-only`.
- Identity redaction verified: principals never carry a `resourceId`, so `coreRecordEntity` resolves them to domain identities; the principal id is confined to the domain source_key.
- Optional-provider degradation verified distinct across connection deployment-blocked, Fabric deployment-blocked-vs-unavailable, governance independent sources, identity/resource-health unavailable-vs-empty.
- Starter specialist/tool pairs verified against `specialists.v1.json` for exact Plan 11-16 parity.
- No blocking findings. One non-blocking observation: the Fabric page duplicates the panel's four medallion reads (documented in Deviation 2); a future consolidation could lift panel state, but that requires modifying the out-of-scope panel component.

## Verification Gates

| Gate | Result |
|---|---|
| Task 1 focused (`page-adapters.test.ts` + `connections/page.test.tsx` + `connections/fabric/page.test.tsx`) | 45 + 17 + 5 passed |
| Task 2 focused (`page-adapters.test.ts` + `CopilotPageIntegrations.test.tsx`) | 50 + 3 passed |
| Full web Vitest suite | 56 files, 593 tests passed |
| ESLint (`next lint`, full project) | No warnings or errors |
| TypeScript (`tsc --noEmit`) | Clean (exit 0) |
| Diff / scope check | Only the 8 plan files + 2 co-located page-test mocks changed; no forbidden paths |
| Working tree | Clean |

The existing Vite CommonJS deprecation notice, React `act()` async warnings from `FabricMedallionPanel`, and unrelated Keyborg warnings remain non-failing.

## Success Criteria

1. The four new specialist domains have real page integrations — met (inventory_data_health on connections + connections/fabric, governance, identity_access, finops, resource_health_observability all wired to real page evidence).
2. Optional services remain enrichments only — met (unavailable Foundry/Fabric/Search/Azure MCP/Gold grounding never blanks a page; Fabric Gold/Data-Agent readiness and governance access-review/export enrichment are non-prerequisite; deployment-blocked/partial/stale/unavailable/healthy-empty stay distinct).
3. Identity/cost/health data stays scoped, cited, and coverage-honest — met (identity principals are scope-safe redacted domain identities; FinOps carries currency/window/coverage with not-quantified nulls; resource-health carries observation windows and missing-series status; all evidence cited and bounded).

## Delivery Status

- No backend, Terraform/infra, `services.ts`, `types.ts`, `CopilotDrawer.tsx`, thread-context, `src/components/fabric/medallion.tsx`, `remediation/page.tsx`, or unrelated-route implementation was changed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` remain unchanged (consistent with the Plan 11-07/11-08/11-14/11-15 worktree convention); Phase 11 is not marked complete.
- No route was added to `CORE_COPILOT_PAGE_ADAPTERS` or `PAGE_DISPOSITIONS` (exact top-level registry contract preserved); the exact manifest-to-adapter route/hint parity gate remains Plan 11-16's responsibility.
- Nothing was pushed, merged, deployed, built for release, or integrated with `origin/main`. The merge/deployment/live-API freeze is preserved.

## Self-Check: PASSED
