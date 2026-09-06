---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T04:45:57Z
depth: deep
files_reviewed: 45
files_reviewed_list:
  - src/api/providers.py
  - src/api/routers/network.py
  - src/api/runtime.py
  - src/network/design.py
  - src/network/gaps.py
  - src/network/loader.py
  - src/network/models.py
  - src/network/rule_engine.py
  - src/network/service.py
  - src/network/tightening.py
  - src/network/topology.py
  - src/onboarding/graph_normalize.py
  - src/operations/tools.py
  - tests/network_baseline.py
  - tests/network_scale_fixtures.py
  - tests/test_api_network.py
  - tests/test_network_analysis.py
  - tests/test_network_downstream_contracts.py
  - tests/test_network_downstream_scope.py
  - tests/test_network_prephase_baseline.py
  - tests/test_network_scale.py
  - tests/test_network_topology.py
  - tests/test_network_topology_links_regression.py
  - tests/test_operations_tools.py
  - web/public/azure-icons/README.md
  - web/public/azure-icons/ai-services.svg
  - web/src/app/globals.css
  - web/src/app/network/page.test.tsx
  - web/src/app/network/page.tsx
  - web/src/components/network/TopologyDetailDrawer.test.tsx
  - web/src/components/network/TopologyDetailDrawer.tsx
  - web/src/components/network/TopologyGraph.test.tsx
  - web/src/components/network/TopologyGraph.tsx
  - web/src/components/network/TopologyWorkspace.test.tsx
  - web/src/components/network/TopologyWorkspace.tsx
  - web/src/components/ui/EvidenceBar.test.tsx
  - web/src/components/ui/EvidenceBar.tsx
  - web/src/components/ui/StatusBadge.test.tsx
  - web/src/hooks/useApi.test.ts
  - web/src/hooks/useApi.ts
  - web/src/lib/network-graph.test.ts
  - web/src/lib/network-graph.ts
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - web/src/test/network-fixtures.ts
findings:
  critical: 8
  warning: 2
  info: 0
  total: 10
status: resolved
resolution:
  fixed: 10
  skipped: 0
  verification: automated_passed_human_logic_review_recommended
---

# Phase 12: Code Review Report

**Reviewed:** 2026-09-06T04:45:57Z
**Depth:** deep
**Files Reviewed:** 45
**Status:** resolved

## Summary

The Phase 12 implementation was reviewed from the frozen phase base
`d57f6137d747c344c56028d7e6211811927d0b43` through `HEAD`, including all
changed production files, tests, API/client boundaries, scope propagation,
topology state transitions, and drill-down/export call chains.

The implementation closed many of the original defects, and this review
identified ten additional high-confidence issues. All ten are now resolved;
the most serious fixes address scope loss in follow-up requests, stale
cross-scope client state, topology state being discarded during refetch, and
incorrect empty/guard decisions for valid topology payloads.

## Resolution Status

All eight blockers and both warnings were fixed on 2026-09-06. Because these
findings concern request scope, asynchronous state, pagination, cache identity,
and selection transitions, the fixes remain marked as requiring human logic
verification even though the targeted and full automated suites pass.

| Finding | Status | Resolution evidence |
|---|---|---|
| CR-01 | Fixed — human verification recommended | `543c9be4`, `99c03223`; active scope now reaches hub/detail requests and scopes the module cache key. |
| CR-02 | Fixed — human verification recommended | `dadf80ce`; `useApi` clears data on dependency changes while retaining it only for manual refetch. |
| CR-03 | Fixed — human verification recommended | `0bc94e7c`; populated workspaces remain mounted and busy during refetch. |
| CR-04 | Fixed — human verification recommended | `e910226a`; empty state now follows rendered graph nodes, including private-link-only graphs. |
| CR-05 | Fixed — human verification recommended | `dca12bd2`; server publishes the exact de-duplicated full projection count and the guard consumes only that count. |
| CR-06 | Fixed — human verification recommended | `c71bb46a`; scope changes reset page/page-size before requests and out-of-range pages cannot claim clean. |
| CR-07 | Fixed — human verification recommended | `12d62358`; scope/detail changes and graph membership changes clear stale node or edge selection. |
| CR-08 | Fixed — human verification recommended | `2a0ac8ba`, `43efb950`; all drill-down loads use one keyed, in-flight-deduplicated request path with stale-response rejection. |
| WR-01 | Fixed — human verification recommended | `d44467c8`; failed gap refresh clears pending state and renders an explicit warning. |
| WR-02 | Fixed | `0bc94e7c`; the real `TopologyWorkspace` now has a direct retained-canvas regression test. |

Post-fix automated checks:

- Added backend regressions: **21 passed**
- Phase-owned web regression slice: **74 passed**
- Full backend suite: **2,695 passed, 33 skipped**
- Full web suite: **339 passed, 15 pre-existing todo**
- Ruff, TypeScript, ESLint, and `git diff --check`: passed

The original green tests did not invalidate the findings below; in particular,
the page test replaced the real `TopologyWorkspace` with a permissive test
double. The post-fix suite now includes direct real-workspace coverage.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER] [RESOLVED]: Drawer follow-up requests drop the active scope and can return broader-scope data

**File:** `web/src/lib/services.ts:945-962`
**Also affected:** `web/src/components/network/TopologyDetailDrawer.tsx:460-466,555-580,749`

**Issue:** The primary topology, gaps, findings, and policy calls serialize the
current `ScopeSelection`, but both follow-up clients omit it:
`hubDependents(vnetId)` sends no query at all, and
`topologyResourceDetails(resourceId, offset, limit)` sends only pagination.
`TopologyDetailDrawer` calls both functions without access to the active scope.
The backend therefore computes `ReadScope` from the caller's full grant rather
than the scope selected on the page. A broadly-authorized operator viewing one
subscription or business service can open a scoped node and receive dependent
VNet details or rule collections from the broader grant.

The module-level drill-down cache compounds this: `detailCacheKey()` contains
only node ID and offset, so a response fetched under one scope can be reused
after the user narrows scope.

**Fix:**

```ts
hubDependents: (vnetId: string, scope: ScopeSelection = {}) =>
  apiRequest<HubDependents>(
    `/network/topology/hubs/${encodeURIComponent(vnetId)}/dependents`,
    { query: scopeToSearchParams(scope) },
  ),

topologyResourceDetails: (
  resourceId: string,
  scope: ScopeSelection,
  offset = 0,
  limit = 50,
) => {
  const query = scopeToSearchParams(scope);
  query.set("offset", String(offset));
  query.set("limit", String(limit));
  // ...
}
```

Pass `scope` through `TopologyWorkspace` into the drawer and include a stable
serialized scope key in `detailCacheKey`, or clear the cache whenever scope
changes. Add client URL tests and an integration test using a globally
authorized principal with a narrower requested scope.

### CR-02 [BLOCKER] [RESOLVED]: `useApi` retains prior-scope records while a new scope is loading

**File:** `web/src/hooks/useApi.ts:51-65`
**Also affected:** `web/src/app/network/page.tsx:43-55,649-684`

**Issue:** Every dependency change executes
`setState(prev => ({ ...prev, loading: true }))`, preserving the previous
payload. That behavior is appropriate for a manual policy refetch, but the same
path is used when `scope` changes. The gaps/rule-findings lists continue to
render non-empty prior-scope rows while `loading` is true, and page metrics and
evidence likewise continue to describe the old scope. A broad-to-narrow scope
transition can therefore display out-of-scope records under the newly selected
scope until the replacement request completes.

**Fix:** Distinguish a manual refetch from a dependency/key change. Preserve
data only for `refetchNonce` changes; clear data synchronously when a stable
request key such as `JSON.stringify(scope)` changes. Add a test that switches
from a broad scope to a narrow scope while the second request is pending and
asserts that no old resource ID remains rendered.

### CR-03 [BLOCKER] [RESOLVED]: The real workspace unmounts the populated canvas during every refetch

**File:** `web/src/components/network/TopologyWorkspace.tsx:545-552`
**Also affected:** `web/src/app/network/page.tsx:245-252`

**Issue:** `useApi` deliberately retains `data` while setting `loading=true`,
and the page passes both retained topology and the loading flag to
`TopologyWorkspace`. The workspace nevertheless returns a loading
`StatePanel` unconditionally whenever `loading` is true. This removes the
canvas during policy refresh and detail-level changes. It also destroys
`TopologyGraph` and its component-local `positionsRef`, so the promised
incremental Summary/Full transition cannot preserve positions.

The passing page test does not exercise this path because
`web/src/app/network/page.test.tsx:38-63` mocks `TopologyWorkspace` with a
component that ignores `loading`.

**Fix:**

```tsx
if (loading && !topology) {
  return <StatePanel ... />;
}
```

Keep the populated workspace mounted with `aria-busy="true"` during refresh,
and render any refresh indicator inside it. Add an integration test using the
real `TopologyWorkspace` and assert that the canvas remains mounted while a
refetch promise is pending.

### CR-04 [BLOCKER] [RESOLVED]: Valid private-link-only topologies are rendered as empty

**File:** `web/src/components/network/TopologyWorkspace.tsx:557-563`

**Issue:** The empty-state gate checks only
`hubs + spokes + isolated === 0`. Phase 12 explicitly added standalone
private-link candidates to `topology.resources`; a scope containing Fabric,
Azure AI Services, or another private-link workload but no VNet has valid graph
nodes and findings, yet the workspace returns “No observed network topology”
before rendering them. Backend projection tests cover private-link-only
snapshots, but the workspace test fixture always includes VNet classifications.

**Fix:** Base emptiness on the graph actually rendered:

```tsx
if (!topology || !renderedGraph || renderedGraph.nodes.length === 0) {
  return <StatePanel ... />;
}
```

Add a workspace test with empty hub/spoke/isolated arrays and one
`PrivateLinkResource`/`AIFoundryAccount` resource.

### CR-05 [BLOCKER] [RESOLVED]: The 1,500-node full-detail guard uses a non-equivalent count and can be bypassed

**File:** `web/src/components/network/TopologyWorkspace.tsx:402-423`
**Also affected:** `src/network/topology.py:217-268`

**Issue:** The guard sums `summary.resource_counts`, which counts snapshot
records, not projected topology nodes. `_topology_resources()` additionally
creates attached-workload nodes for private-endpoint and load-balancer targets.
Those nodes are absent from `NetworkSnapshot.counts()`. A reproduced snapshot
with 800 private endpoints and unique targets reports a count sum of **802**,
while both summary `coverage.total` and the full graph contain **1,602** nodes.
The UI therefore fetches full detail without the mandatory confirmation even
though the graph exceeds the measured 1,500-node ceiling.

**Fix:** Have the server publish an exact `projected_full_node_count` computed
from the same deduplicated projection identity rules, and use only that value
for the guard. Do not infer a full graph count by summing heterogeneous
collection counts. Add a regression fixture with many unique attached targets.

### CR-06 [BLOCKER] [RESOLVED]: Pagination survives scope changes and can falsely report a non-empty scope as clean

**File:** `web/src/app/network/page.tsx:27-53,299-324,649-659`

**Issue:** `gapPage` and `findingPage` reset only when page size changes, not
when `scope` changes. If an operator is on page 4 and switches to a scope with
fewer than 301 records, the new request still uses the old offset. The server
returns an empty page with a positive total, but `FindingList` immediately
renders “No inspection gaps detected” or “No rule findings detected” whenever
`items.length === 0`, before rendering pagination. This is a false clean-state
claim.

**Fix:** Reset both page indices when a stable scope key changes, and treat
`items.length === 0 && pagination.total > 0` as an out-of-range page that must
return to page zero—not as a genuinely empty collection.

### CR-07 [BLOCKER] [RESOLVED]: Selection is not cleared when a new topology no longer contains the selected element

**File:** `web/src/components/network/TopologyWorkspace.tsx:259,333-343,373-400,720-745`

**Issue:** Selection is cleared only when an active text filter hides it.
After a scope change or a Full→Summary transition, a selected rule/resource can
disappear from `renderedGraph`, but the old `selection` object remains and the
drawer continues rendering that stale node. On a scope change this can expose
facts from the previous broader scope after the new topology has loaded; on a
detail change it leaves the drawer describing a node absent from the canvas.

**Fix:** Add an effect keyed by `visibleNodeIds` and the rendered edge IDs that
clears any selected node/edge no longer present, independent of filter mode.
Also clear selection immediately when the scope key changes.

### CR-08 [BLOCKER] [RESOLVED]: Drill-down page changes can issue duplicate requests and render the wrong page

**File:** `web/src/components/network/TopologyDetailDrawer.tsx:535-595`

**Issue:** Initial loading uses the guarded `load()` path, but
`changePage()` bypasses it. It does not set `loading`, has no in-flight
deduplication, and commits every response without checking that its offset is
still current. While an uncached page request is pending, the component renders
the ordinary “Load rules” button again; pressing it starts a duplicate request.
Rapid Previous/Next navigation can also resolve out of order and display rows
from one offset beside pagination state for another.

**Fix:** Route initial load, Retry, and page changes through one request
function keyed by `{nodeId, offset, scope}`. Track an in-flight promise/request
token, set `loading` for page changes, and ignore a response unless its key
still matches the current key.

## Warnings

### WR-01 [WARNING] [RESOLVED]: Policy refresh state never settles when the gaps refetch fails

**File:** `web/src/app/network/page.tsx:73-110`

**Issue:** A successful policy mutation sets `pendingPolicyRefresh`, but the
completion effect returns whenever `!gaps.data`. `useApi` sets `data: null` on
a failed refetch, so the pending state is never cleared and the policy panel
continues to display “Refreshing derived analysis…” indefinitely.

**Fix:** Handle `gaps.error` explicitly: clear `pendingPolicyRefresh` and render
a warning that the policy was saved but derived analysis could not be
refreshed. Include `gaps.error` in the effect dependencies.

### WR-02 [WARNING] [RESOLVED]: The retained-canvas regression test replaces the component that contains the bug

**File:** `web/src/app/network/page.test.tsx:38-63,529-552`

**Issue:** The test titled “retains the populated topology ... while a
policy-triggered refetch is in flight” mocks `TopologyWorkspace` with a test
double that ignores its `loading` prop. It therefore passes while the real
component returns a loading `StatePanel` and unmounts the graph. This is a
false-positive regression gate for a release-critical interaction.

**Fix:** Keep unit tests for page request orchestration, but add a non-mocked
integration test for `NetworkPage` + `TopologyWorkspace`, or directly rerender
the real workspace with `{topology, loading: true}` and assert that the graph
and current metric state remain present.

---

_Reviewed: 2026-09-06T04:45:57Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
