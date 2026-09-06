---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T05:29:34Z
depth: deep
diff_base: d57f6137d747c344c56028d7e6211811927d0b43
diff_head: 97114a32
files_reviewed: 48
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
  - src/storage/onelake_documents.py
  - tests/network_baseline.py
  - tests/network_scale_fixtures.py
  - tests/test_api_network.py
  - tests/test_api_providers.py
  - tests/test_network_analysis.py
  - tests/test_network_downstream_contracts.py
  - tests/test_network_downstream_scope.py
  - tests/test_network_prephase_baseline.py
  - tests/test_network_scale.py
  - tests/test_network_topology.py
  - tests/test_network_topology_links_regression.py
  - tests/test_onelake_documents.py
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
  critical: 5
  warning: 6
  info: 0
  total: 11
status: resolved
resolution:
  fixed: 11
  skipped: 0
  verification: automated_passed_human_logic_review_recommended
---

# Phase 12: Independent Post-Fix Deep Code Review

**Reviewed:** 2026-09-06T05:29:34Z
**Depth:** deep
**Diff:** `d57f6137d747c344c56028d7e6211811927d0b43..97114a32`
**Files Reviewed:** 48
**Status:** resolved

## Summary

This was a fresh review of the current Phase 12 HEAD after both review-fix
series. I read the Phase 12 plans, summaries, research, UI/validation
contracts, pre-phase review, both post-implementation review states, and
`12-REVIEW-FIX.md`; then traced the current backend, API, agent, and browser
call chains independently.

The first review's scope, stale-state, pagination, selection, and drill-down
fixes remain present. Iteration 2 fixed all five blockers and six warnings
identified by this independent review, with failing-first regressions and
atomic commits for each finding.

Review-time focused verification completed:

- Backend post-fix slice: **121 passed**
- Web post-fix slice: **74 passed**
- TypeScript: **passed**
- Ruff over post-fix Python scope: **passed**
- `git diff --check` over Phase 12 source: **passed**

Before the iteration 2 fixes, the then-passing tests did not cover the failing
estate shapes below. Executed probes against the reviewed HEAD reproduced:

- **3,000 rendered graph nodes** from a summary response whose declared cap is
  1,500, while the payload stayed just under 2 MB.
- A 40-VNet mesh with all **820/820 resources returned**, but only **549/780
  links** and **629/1,560 relationships**, while top-level
  `coverage.truncated` incorrectly remained `false`.
- A policy document body read failure replacing a last-known-good governed
  policy with an empty default policy while provider health remained `ready`.
- `projected_full_node_count=1,336` for a graph that the current resource
  client renders as 1,330 nodes.

## Iteration 2 Resolution Status

All five blockers and six warnings were fixed on 2026-09-06. The topology
identity, summary budgeting, coverage, provider lifecycle, CAS, scoping, and
timestamp findings remain marked as requiring human logic verification even
though all automated gates pass.

| Finding | Status | Resolution evidence |
|---|---|---|
| CR-01 | Fixed — human verification recommended | `211a116e`; full-node projection now follows resource-client identity and excludes non-rendered synthetic shared-service IDs. |
| CR-02 | Fixed — human verification recommended | `c45f75ea`; summary budgeting covers resource, unresolved-peer, client-added, and subscription-group nodes under the 1,500-node and byte ceilings. |
| CR-03 | Fixed — human verification recommended | `949bf4b1`, `93501a4b`; top-level and nested node/group/relationship coverage now disclose every truncated collection and retain valid shared-service metadata. |
| CR-04 | Fixed — human verification recommended | `232cd91a`; provider construction uses one strict policy+revision read and preserves the last-good provider as degraded on body-read failure. |
| CR-05 | Fixed — human verification recommended | `ae8cb456`; OneLake writes use ETag preconditions, local writes use an inter-process lock plus atomic replacement, and mutation reads fail closed. |
| WR-01 | Fixed — human verification recommended | `ed8895e1`; scoped services filter flow observations by surviving endpoints. |
| WR-02 | Fixed — human verification recommended | `4c08d698`; managed, Fabric, and hybrid constructors now pass ingested traffic-analysis observations to rule analysis. |
| WR-03 | Fixed — human verification recommended | `578b0c21`; loader timestamps are parsed, UTC-normalized, and compared as instants while invalid values are ignored. |
| WR-04 | Fixed | `a85715bb`, `1634f68e`; audit timestamps remain the real clock value and only colliding filenames gain a sequence suffix. |
| WR-05 | Fixed | `fc79e096`; legacy shared-service IDs and consumers resolve through the folded identity index. |
| WR-06 | Fixed | `04203af9`, `86b5bd05`, `7a802531`; incomplete-results warnings are polite named live regions and policy status tests remain unambiguous. |

Post-fix verification:

- Targeted backend regression slice: **240 passed**
- Targeted web regression slice: **129 passed**
- G-1/G-2/G-3/G-6 modules: **19 passed**
- G-4/G-5 and downstream contracts: **16 passed**
- Downstream scope tracer: **4 passed**
- Full backend suite: **2,708 passed, 33 skipped**
- Full web suite: **340 passed, 15 todo**
- TypeScript, ESLint, Ruff, and committed `git diff --check`: passed

## Prior Review-Fix Verification

| Prior finding | Independent HEAD result |
|---|---|
| Original CR-01 — drill-down scope loss | **Closed.** Scope is threaded through both clients, drawer calls, and cache keys. |
| Original CR-02 — old-scope `useApi` records retained | **Closed.** Dependency changes clear data; manual refetch retains it. |
| Original CR-03 — populated canvas unmounted on refetch | **Closed.** Loading takeover is limited to the no-data state. |
| Original CR-04 — private-link-only topology shown empty | **Closed.** Empty state follows the rendered graph. |
| Original CR-05 — exact full graph count | **Not closed.** See CR-01 below. |
| Original CR-06 — pagination survives scope changes | **Closed.** Effective page and size synchronously fall back to page 0/default until state resets. |
| Original CR-07 — stale topology selection | **Closed.** Scope/detail and graph-membership changes clear selection. |
| Original CR-08 — duplicate/out-of-order drill-down | **Closed.** Requests are keyed, shared in flight, and stale completions are ignored. |
| Original WR-01 — policy refresh never settles on failure | **Closed.** The error branch clears pending state and emits warning feedback. |
| Original WR-02 — retained-canvas test mocked away the bug | **Closed.** Direct real-workspace coverage exists and passes. |
| Later CR-01 — complete summary payload bounding | **Partial/regressed.** Byte bounding improved, but node and completeness contracts remain broken; see CR-02 and CR-03. |
| Later CR-02 — recursively bounded agent lists | **Closed.** `_bound()` now recurses and the nested-list regression passes. |
| Later CR-03 — revision read failure behavior | **Partial.** Cache-key failures retain the provider, but policy body failures still publish an empty policy; see CR-04. |
| Later WR-09 — tests bound to production constants | **Closed.** The constants are imported and compared directly. |

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER] [RESOLVED]: The “exact” projected full-node count does not match the client graph

**File:** `src/network/topology.py:218-233`
**Also affected:** `web/src/lib/network-graph.ts:439-500`,
`web/src/components/network/TopologyWorkspace.tsx:435-449`

**Issue:** `projected_full_node_count()` adds every synthetic
`shared_services[].resource_id`. The active client path for any payload with
`resources` is `buildResourceTopologyGraph()`, which builds nodes from
`topology.resources` and unresolved peers but does not add
`topology.shared_services`. Those synthetic IDs therefore inflate the count.

The committed small fixture reproduces the mismatch: the resource graph has
1,330 nodes, while the server publishes 1,336 because it adds six
non-rendered shared-service IDs. Around the 1,500 threshold this creates an
unnecessary confirmation gate and means original CR-05's requested exact
count is not closed.

**Fix:** Define one server-side client-node identity projection matching
`buildResourceTopologyGraph()` exactly, or render the synthetic shared-service
nodes in that client path. Add a contract test comparing the published count
to `buildTopologyGraph(payload).nodes.length`, including shared services and
unresolved peers.

### CR-02 [BLOCKER] [RESOLVED]: Summary responses can render twice the 1,500-node canvas cap

**File:** `src/network/topology.py:397-554`
**Also affected:** `web/src/lib/network-graph.ts:453-500`,
`tests/test_network_scale.py:162-231`

**Issue:** The summary cap applies only to `resources`. The client additionally
materializes unresolved remote VNet nodes from `unresolved_peer_vnet_ids`,
`unresolved_peers`, and returned links. Those node-producing collections are
byte-bounded but not included in the node budget.

An executed 1,600-VNet/1,600-unresolved-peering probe returned 1,500 resources,
1,500 unresolved IDs, and 1,014 links. The client-equivalent ID union contains
**3,000 nodes**, despite `SUMMARY_NODE_CAP == 1_500`; payload size was
1,999,990 bytes. This bypasses the measured canvas safety ceiling on the
default web path.

The scale tests only assert `len(payload["resources"])`, not the number of
nodes the browser builds.

**Fix:** Budget a single de-duplicated set of all client node identities:
resource IDs plus unresolved remote IDs introduced by returned links/peer
collections. Stop adding unresolved entries once the union reaches
`SUMMARY_NODE_CAP`. Change G-1/G-2 tests to build the client graph and assert
its node count, with a production-shaped unresolved-peer fixture.

### CR-03 [BLOCKER] [RESOLVED]: Summary top-level coverage claims completeness while edges are truncated

**File:** `src/network/topology.py:322-340,492-554`
**Also affected:** `web/src/components/network/TopologyWorkspace.tsx:480-543`

**Issue:** Top-level `coverage.truncated` is computed only as
`len(resources) < len(all_resources)`. The new bounding algorithm can truncate
links, relationships, classifications, shared services, unresolved peers, or
connection IDs while returning every resource. The UI's Partial badge and
export's top-level completeness flag read only this false top-level value.

Executed proof with a 40-VNet full mesh:

```text
resources:     820 / 820   (top-level truncated=false)
links:         549 / 780   (truncated=true)
relationships: 629 / 1560  (truncated=true)
payload:       1,999,886 bytes
```

The canvas and exported audit artifact therefore present a materially
incomplete topology as complete.

**Fix:** Set top-level truncation to the OR of resource truncation and every
collection's truncation. Publish graph-node and relationship totals with clear
semantics, type the nested collection coverage in the client, and make the UI
and export consume those authoritative totals. Add a sub-1,500-resource dense
mesh test where only edge collections truncate.

### CR-04 [BLOCKER] [RESOLVED]: A policy body read failure can replace the last-good provider with an empty policy

**File:** `src/api/runtime.py:638-646`
**Also affected:** `src/network/design.py:463-501`,
`src/api/providers.py:207-265`,
`src/storage/onelake_documents.py:89-145`

**Issue:** The revision cache key now uses strict `revision_or_raise()`, but
`_load_network_service()` still loads the actual policy through fail-open
`store.read()`. `OneLakeDocumentStore.read()` converts transport, parse, and
HTTP failures to `{}`. If strict revision reads succeed while the separate
policy body read fails, the cache key remains unchanged and
`ProviderRuntime` publishes a newly built service using the empty default
policy, marks it `ready`, and discards the governed last-good instance.

The executed probe changed policy description from `"governed"` to `""`,
changed provider identity, and reported `state: ready`, with revision still 7.
The added regression only tests a failing revision read, so this second read
path is uncovered.

**Fix:** Load the policy body through a strict read for provider construction,
so failure raises and `_refresh_provider()` retains the last-good instance as
degraded. Prefer one atomic `read_with_revision_or_raise()` result so the
policy and cache key cannot come from different reads. Add a test where
`read_or_raise()` returns revision 7 but the policy body read fails.

### CR-05 [BLOCKER] [RESOLVED]: OneLake “compare-and-swap” is not atomic across replicas

**File:** `src/storage/onelake_documents.py:151-178`

**Issue:** `write()` protects only threads in one process. Two replicas can
both read revision N, both pass the comparison, and both call
`upload_data(..., overwrite=True)` with revision N+1. The second upload silently
clobbers the first. No ETag, lease, conditional request, or atomic create is
used, despite the docstring claiming cross-replica safety. A transient
fail-open read can also return `{}`, causing the same path to compare against
revision 0 before overwriting.

This is a lost-update/data-integrity risk for network policy and every other
document using this store.

**Fix:** Use OneLake/ADLS conditional writes with the ETag from the read
(`If-Match`/match condition), or a supported lease/transaction mechanism.
Treat read failures as errors on mutation paths. For local storage, use an
inter-process lock plus atomic temporary-file replacement. Add a two-writer
test whose second stale write is rejected at the storage boundary.

## Warnings

### WR-01 [WARNING] [RESOLVED]: Scoped services retain estate-wide flow observations

**File:** `src/network/service.py:397-405`

**Issue:** Snapshot collections and semantic relationships are scoped, but
`flow_observations=self.flow_observations` is passed through unchanged.
`flow_log_provenance.observed_flow_count` can therefore disclose and report an
estate-wide count in a subscription-scoped response once flow ingestion is
wired.

**Fix:** Scope flow observations to surviving endpoints/resources using the
same endpoint-membership rule as semantic relationships, or omit provenance
when an observation cannot be attributed safely.

### WR-02 [WARNING] [RESOLVED]: The advertised `analyzed` flow-log state is unreachable in production

**File:** `src/api/runtime.py:638-646,2855-2862`

**Issue:** Production constructors do not pass `flow_observations`; the only
uses are internal to `NetworkIntelligenceService`. Consequently the UI's
three-state contract has an unreachable `analyzed` branch.

**Fix:** Wire the flow-log ingestion result into both managed and hybrid
network constructors, or remove/defer the state until a producer exists.

### WR-03 [WARNING] [RESOLVED]: Unvalidated observation timestamps can poison API evidence

**File:** `src/network/loader.py:212-228`

**Issue:** External `observed_at` is accepted as any string and combined with
row timestamps using lexicographic `max`. An invalid value such as
`"not-a-date"` can win and is then emitted as evidence freshness. The web
degrades it to unknown, but API, agent, and MCP consumers still receive the
invalid provenance value.

**Fix:** Parse and normalize timestamps at the loader boundary; reject or
ignore invalid values and compare parsed datetimes rather than raw strings.

### WR-04 [WARNING] [RESOLVED]: Rapid exports fabricate future `exported_at` timestamps

**File:** `web/src/components/network/TopologyGraph.tsx:379-401`

**Issue:** Filename collision avoidance increments the timestamp itself.
Multiple exports in one second therefore claim to have been exported in future
seconds, corrupting the audit provenance field.

**Fix:** Keep `exported_at` equal to the real clock value and add a filename-only
sequence suffix (for example `-2`, `-3`) for collisions.

### WR-05 [WARNING] [RESOLVED]: Legacy shared-service edges still use case-sensitive IDs

**File:** `web/src/lib/network-graph.ts:346-358,401-408`

**Issue:** In the legacy no-`resources` path, shared services are added after
the folded-ID index is built, and consumer lookup uses `nodes.has(consumerId)`.
Mixed ARM casing silently drops service-to-consumer edges.

**Fix:** Register shared-service IDs in the folded index and resolve consumer
IDs through `resolveNodeId()` before creating edges. Add a mixed-case legacy
payload regression.

### WR-06 [WARNING] [RESOLVED]: The dynamic incomplete-results warning is not announced

**File:** `web/src/app/network/page.tsx:264-273`

**Issue:** The safety-critical callout appears after bounded loaders resolve
but has neither `role="status"` nor an `aria-live` region, unlike the workspace
coverage callouts. Screen-reader users may never be told that the displayed
security findings are incomplete.

**Fix:** Add `role="status"` (or an appropriate polite live region) and retain
the visible copy.

---

_Reviewed: 2026-09-06T05:29:34Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
_Scope: read-only; no source or tracking files modified_
