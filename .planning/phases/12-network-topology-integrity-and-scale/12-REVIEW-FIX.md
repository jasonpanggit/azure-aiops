---
phase: 12
fixed_at: 2026-09-06T05:17:55Z
review_path: .planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 10
skipped: 0
status: all_fixed
---

# Phase 12: Code Review Fix Report

**Fixed at:** 2026-09-06T05:17:55Z
**Source review:** `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 10
- Fixed: 10
- Skipped: 0

All state-transition and request-scope fixes are marked **fixed: requires
human verification** because syntax and automated tests cannot by themselves
prove asynchronous ordering or authorization semantics.

## Fixed Issues

### CR-01: Drawer follow-up requests preserve active scope

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/lib/services.ts`, `web/src/app/network/page.tsx`, `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyDetailDrawer.tsx`, `web/src/components/network/TopologyDetailDrawer.test.tsx`  
**Commits:** `543c9be4`, `99c03223`  
**Applied fix:** Threaded the selected `ScopeSelection` through hub and resource-detail requests and included a stable serialized scope in the session cache key. Added coverage proving two scopes do not share cached pages.

### CR-02: Prior-scope records are cleared on dependency changes

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/hooks/useApi.ts`, `web/src/hooks/useApi.test.ts`  
**Commit:** `dadf80ce`  
**Applied fix:** Distinguished dependency changes from manual refetches. Dependency changes clear prior data before loading; manual refetches retain populated data.

### CR-03: Populated canvas remains mounted during refetch

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`  
**Commit:** `0bc94e7c`  
**Applied fix:** Limited the loading takeover to first load, retained the graph when topology data exists, and marked the real workspace busy during refresh.

### CR-04: Private-link-only topology is not treated as empty

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`  
**Commit:** `e910226a`  
**Applied fix:** Based the empty state on the rendered graph node count instead of VNet classifications, with an AI Foundry-only regression fixture.

### CR-05: Full-detail guard uses the exact projected graph size

**Status:** Fixed — requires human verification  
**Files modified:** `src/network/topology.py`, `src/network/service.py`, `tests/test_network_topology.py`, `web/src/lib/types.ts`, `web/src/test/network-fixtures.ts`, `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`, `.planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json`, `tests/test_network_prephase_baseline.py`, `tests/test_network_downstream_contracts.py`  
**Commit:** `dca12bd2`  
**Applied fix:** Published `projected_full_node_count` from the full, case-folded, de-duplicated projection, including attached workloads, shared services, and unresolved peers. The UI no longer infers this value from snapshot collection counts.

### CR-06: Pagination resets safely across scope changes

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`  
**Commit:** `c71bb46a`  
**Applied fix:** Keyed pager state to a stable scope serialization, reset page and page size before new-scope requests, returned out-of-range pages to page zero, and prevented positive-total empty pages from claiming a clean state.

### CR-07: Selection resets across scope and detail changes

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/components/network/TopologyWorkspace.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`  
**Commit:** `12d62358`  
**Applied fix:** Cleared selection on scope/detail context changes and whenever the selected node or edge is absent from the newly rendered graph.

### CR-08: Drill-down pagination is ordered and de-duplicated

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/components/network/TopologyDetailDrawer.tsx`, `web/src/components/network/TopologyDetailDrawer.test.tsx`  
**Commits:** `2a0ac8ba`, `43efb950`  
**Applied fix:** Routed initial load, retry, and page changes through one keyed request function; de-duplicated in-flight requests; set loading during page transitions; and ignored stale responses whose node/scope/offset key no longer matches.

### WR-01: Failed policy refresh settles with explicit feedback

**Status:** Fixed — requires human verification  
**Files modified:** `web/src/app/network/page.tsx`, `web/src/app/network/page.test.tsx`  
**Commit:** `d44467c8`  
**Applied fix:** Added the failed-refetch branch to the pending policy-refresh effect, cleared pending state, and rendered a warning that the policy save succeeded but derived analysis did not refresh.

### WR-02: Retained-canvas test exercises the real workspace

**Status:** Fixed  
**Files modified:** `web/src/components/network/TopologyWorkspace.test.tsx`  
**Commit:** `0bc94e7c`  
**Applied fix:** Added a direct `TopologyWorkspace` regression test that renders populated topology with `loading=true` and verifies the graph stays mounted under `aria-busy`.

## Verification

Verification ran in the **main Phase 12 checkout**
`/Users/jasonmba/workspace/copilot-worktrees/azure-aiops/jasonpanggit-potential-broccoli`
after fast-forwarding the isolated fix commits, because the isolated worktree
intentionally had no `node_modules`.

- Targeted backend regressions: **21 passed**
- Targeted web regressions: **74 passed across 4 files**
- Full backend suite: **2,695 passed, 33 skipped**
- Full web suite: **339 passed, 15 pre-existing todo**
- TypeScript: passed with zero diagnostics
- ESLint: passed with zero warnings or errors
- Ruff on changed Python files: passed
- JSON/Python syntax and `git diff --check`: passed for fixer-owned changes

## Skipped Issues

None.

---

_Fixed: 2026-09-06T05:17:55Z_  
_Fixer: the agent (gsd-code-fixer)_  
_Iteration: 1_
