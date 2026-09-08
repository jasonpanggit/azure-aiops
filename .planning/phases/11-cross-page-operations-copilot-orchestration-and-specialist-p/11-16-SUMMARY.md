---
phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
plan: 16
subsystem: ui
tags: [copilot, page-adapters, route-disposition, specialist-manifest, parity, react, typescript, read-only]

# Dependency graph
requires:
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 05
    provides: Versioned specialist manifest projected across deployment boundaries with the read-only parity gate for specialist/tool/catalog/page-mapping checks
  - phase: 11-cross-page-operations-copilot-orchestration-and-specialist-p
    plan: 10
    provides: Final typed page adapters (situation detail, services, service detail, twin) and the note that Plan 11-16 owns the exhaustive 28-route/manifest parity gate
provides:
  - Exhaustive COPILOT_ROUTE_DISPOSITIONS registry giving all 28 routes exactly one reviewed disposition (integrated | dedicated | redirect | excluded)
  - Filesystem-derived 28-route disposition gate and integrated-route launcher coverage gate
  - COPILOT_ROUTE_STARTER_HINTS registry and an exact cross-language manifest/API/adapter specialist parity gate
affects: []

# Actuals (#2632)
actuals:
  tokens: 5600
  tasks: 2
  commits: 5

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Route disposition is a discriminated union (integrated pageKind anchor | dedicated surface | redirect target | excluded reason); the disposition gate derives the route inventory from web/src/app/**/page.tsx and requires it to equal the registry inventory exactly"
    - "The versioned committed manifest src/operations/specialists.v1.json is the single cross-language authority: the Vitest parity gate mirrors specialist_manifest.page_mapping_projection (owner-first stable order) and asserts exact bidirectional equality, while tests/test_orchestration_parity.py independently proves the Python side loads the same file"
    - "Adapter starter hints carry advisory routing only; every (specialistId, tool) hint must resolve to an authorized manifest specialist and a granted operations_mcp tool, and backend policy still authorizes execution (D-03, D-05, D-06)"

key-files:
  created:
    - web/src/lib/copilot/page-adapters.manifest-parity.test.ts
  modified:
    - web/src/lib/copilot/page-adapters.ts
    - web/src/lib/copilot/page-adapters.test.ts
    - web/src/components/ui/CopilotPageIntegrations.test.tsx
    - web/src/app/search/page.tsx
    - web/src/app/vulnerabilities/page.tsx

key-decisions:
  - "COPILOT_ROUTE_DISPOSITIONS encodes the resolved research disposition table exactly: 23 integrated, 3 dedicated (/copilot, /investigate, /agents), 1 redirect (/vulnerabilities), 1 excluded (/search). The filesystem gate reads every web/src/app/**/page.tsx, derives its route path, and asserts registry keys equal the discovered routes in both directions so no route can ship without exactly one reviewed disposition (absent, duplicate, or extra all fail)."
  - "copilotPageDisposition now derives from the new registry (integrated/excluded surfaced; dedicated and redirect map to the legacy 'deferred' value for backward compatibility), and the 7-entry PAGE_DISPOSITIONS map was removed. The existing CopilotPageDisposition public type and its consumers are unchanged."
  - "The launcher coverage gate (CopilotPageIntegrations.test.tsx) reads each route source and requires every integrated route to render the shared CopilotDrawerButton entry point and every non-integrated route (3 dedicated + redirect + excluded) to omit it. All 23 integrated routes already rendered the shared launcher, so no page wiring changed."
  - "Each integrated route declares a pageKind anchor that mirrors the page kind its adapter already emits and is a key in the manifest page_mapping. The parity gate resolves route specialists through the manifest (never frontend-owned) and asserts the union of page-kind anchor owners and starter hints equals the 12-specialist portfolio exactly in both directions, catching an invented frontend specialist and an orphaned manifest specialist alike."
  - "COPILOT_ROUTE_STARTER_HINTS references the exact starter constants each adapter emits; the inline inventory starters were extracted into a shared INVENTORY_STARTERS constant so the registry cannot drift from the adapter. All 26 distinct (specialist, tool) hint pairs were already manifest-authorized, so no hint changed."
  - "The /vulnerabilities alias keeps its existing redirect behavior (it redirects into the Exposure product); the registry records kind 'redirect' with target '/exposure' and the gate asserts it hosts no duplicate adapter. /search keeps its existing behavior; the registry records kind 'excluded' with the stable-evidence reason and the gate asserts it is the single reasoned exclusion. Both source pages carry an auditability comment documenting their disposition (T-11-49, T-11-50). Neither the vulnerabilities redirect target URL nor the search behavior was changed, so no out-of-scope tests were touched."
  - "The API catalog projection is normalized in-test from the same committed manifest (id + page_mappings, matching specialist_manifest.catalog_projection) and asserted to produce the same page mapping as the raw manifest; the backend-side loader is independently exercised by tests/test_orchestration_parity.py, which stays green."

patterns-established:
  - "Filesystem-derived coverage gate: enumerate the real route files on disk and require a hand-maintained registry to equal that inventory exactly, so a new route mechanically forces a reviewed disposition."
  - "Cross-language contract parity without a runtime bridge: the browser test mirrors the Python projection algorithm over the single committed manifest file, and each language's own test suite proves its side reads that file correctly."

requirements-completed: [COP-02, COP-03]

coverage:
  - id: D1
    description: "All 28 route files have exactly one integrated/dedicated/redirect/excluded disposition; registry inventory equals the filesystem inventory in both directions; counts are 23/3/1/1; /vulnerabilities is a tested redirect with no duplicate adapter and /search is the single reasoned exclusion"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.test.ts#28-route Copilot disposition gate (COP-02, COP-03)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every integrated route renders the shared CopilotDrawerButton entry point and every dedicated/redirect/excluded route omits it"
    requirement: COP-02
    verification:
      - kind: unit
        ref: "src/components/ui/CopilotPageIntegrations.test.tsx#integrated route launcher coverage (COP-02)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The raw manifest and the API catalog projection normalize to the same page mapping; every integrated route anchors on a real manifest page-mapping key; every adapter starter hint maps to an authorized manifest specialist and granted tool; anchor owners plus hints equal the specialist portfolio exactly in both directions; extra/missing/unknown/misspelled mappings fail"
    requirement: COP-03
    verification:
      - kind: unit
        ref: "src/lib/copilot/page-adapters.manifest-parity.test.ts#manifest / API / adapter specialist parity (COP-03, D-03, D-05, D-06)"
        status: pass
      - kind: unit
        ref: "src/lib/copilot/page-adapters.manifest-parity.test.ts#parity gate rejects manifest / adapter drift"
        status: pass
      - kind: contract
        ref: "tests/test_orchestration_parity.py"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-09-08
status: complete
---

# Phase 11 Plan 11-16: Exhaustive Route Disposition & Manifest Parity Gate Summary

**All 28 web routes now carry exactly one reviewed Copilot disposition derived from the filesystem, every integrated route provably renders the shared launcher, and every adapter page-kind anchor and starter hint is proven — in both directions — to map exactly onto the versioned specialist manifest, so COP-02 route coverage and COP-03 specialist mapping are mechanically enforced rather than frontend-owned.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 (both TDD RED/GREEN)
- **Commits:** 5 (4 task commits + this summary)

## Accomplishments

### Task 1 — One disposition for all 28 routes
- Added `COPILOT_ROUTE_DISPOSITIONS`, an exhaustive discriminated-union registry (`integrated` pageKind anchor | `dedicated` surface | `redirect` target | `excluded` reason) covering every route.
- Added a filesystem-derived gate that enumerates `web/src/app/**/page.tsx`, derives each route path, and requires the registry inventory to equal the discovered inventory exactly (no absent, duplicate, or extra disposition), with the resolved counts 23 integrated / 3 dedicated / 1 redirect / 1 excluded and the specific `/copilot|/investigate|/agents` dedicated, `/vulnerabilities` redirect, and `/search` exclusion assertions.
- Added a launcher coverage gate requiring every integrated route to render the shared `CopilotDrawerButton` and every non-integrated route to omit it.
- Re-derived `copilotPageDisposition` from the registry and removed the stale 7-entry `PAGE_DISPOSITIONS` map; documented the redirect/exclusion dispositions at their source pages for auditability.

### Task 2 — Exact manifest/API/adapter specialist parity
- Added `web/src/lib/copilot/page-adapters.manifest-parity.test.ts`, a Vitest gate that loads the committed `src/operations/specialists.v1.json`, mirrors `page_mapping_projection` (owner-first stable order), and normalizes both the raw manifest and an API-catalog-shaped projection to the same page mapping.
- Added `COPILOT_ROUTE_STARTER_HINTS` (referencing each adapter's real hint constants; inventory starters extracted into a shared `INVENTORY_STARTERS`) and proved every hint maps to an authorized manifest specialist and granted tool, that every integrated route anchors on a real manifest page-mapping key, and that anchor owners ∪ starter hints equal the 12-specialist portfolio exactly in both directions.
- Added drift tests proving extra, missing, unknown, and misspelled mappings fail; additionally verified live teeth by temporarily injecting an extra owner and a missing owner into the committed manifest (both failed the gate) before reverting the manifest to its committed state.

## Verification

- Task 1 web verify (`page-adapters.test.ts` + `CopilotPageIntegrations.test.tsx`): pass.
- Task 2 verify (`tests/test_orchestration_parity.py` **32 passed**; `page-adapters.manifest-parity.test.ts` + `page-adapters.test.ts`): pass.
- Focused suite (3 files): **86 passed**.
- Full web suite: **628 passed / 57 files**.
- `tsc --noEmit`: clean. `next lint`: no warnings or errors.
- Live parity teeth: injected extra owner → gate failed; injected missing owner → gate failed; manifest reverted (working tree clean, unchanged from HEAD).
- Diff scope: exactly the 6 plan-declared files (`page-adapters.ts`, `page-adapters.test.ts`, `page-adapters.manifest-parity.test.ts`, `CopilotPageIntegrations.test.tsx`, `search/page.tsx`, `vulnerabilities/page.tsx`); working tree clean. No backend, Terraform, `services.ts`, `types.ts`, drawer/thread-context, STATE/ROADMAP, or unrelated routes touched. No push, merge, deploy, production build, Terraform, or live API run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Downlevel-iteration and inventory hint typing fixed in GREEN**
- **Found during:** Task 2 GREEN `tsc --noEmit`.
- **Issue:** `tsc` reported (a) `Map`/`Set` iteration in the parity test requires `--downlevelIteration`, and (b) `InventoryCopilotContext.starterQuestions` requires `tool: string` while `CoreCopilotStarterQuestion.tool` is optional, so the extracted `INVENTORY_STARTERS` was not assignable.
- **Fix:** Iterate manifest projections via `Array.from(...)`; type `INVENTORY_STARTERS` with the stricter required-`tool` element shape (still assignable to `readonly CoreCopilotStarterQuestion[]`).
- **Files modified:** web/src/lib/copilot/page-adapters.manifest-parity.test.ts, web/src/lib/copilot/page-adapters.ts
- **Commit:** 6abcd06eb

### Scope clarifications (no behavior change)
- The research table renders the redirect as `/vulnerabilities → /exposure`; the implemented page redirects into the Exposure product (`/exposure/patch-priorities`). The registry records the disposition kind `redirect` with target `/exposure` and the gate asserts the alias hosts no duplicate adapter, preserving the existing redirect behavior and leaving the out-of-scope `vulnerabilities/page.test.tsx` green. The plan MUST-HAVE truth ("/vulnerabilities is a tested redirect") is satisfied by kind + test, not by an exact URL change.
- `/search` behavior is unchanged; only an auditability comment was added alongside the `excluded` disposition.

## Notes for the phase
- COP-02 and COP-03 route/mapping coverage are now mechanically enforced; adding a new route or drifting a specialist mapping/hint fails a committed gate on either side of the language boundary.
- Phase 11 is **not** marked complete by this plan; STATE.md and ROADMAP.md were intentionally left unchanged per plan scope.

## Independent Review

An independent cross-AI reviewer was not available: only a same-family `claude` CLI is installed (not an independent second opinion), and the phase freeze prohibits live external API calls. Verification relied on the full TDD suite, the backend contract test, live manifest-mutation teeth checks, `tsc`, `next lint`, and diff-scope inspection — all green.

## Self-Check: PASSED
