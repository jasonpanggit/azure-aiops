---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-03T23:02:57Z
depth: deep
files_reviewed: 16
files_reviewed_list:
  - web/src/app/network/page.tsx
  - web/src/components/network/TopologyWorkspace.tsx
  - web/src/components/network/TopologyGraph.tsx
  - web/src/components/network/TopologyDetailDrawer.tsx
  - web/src/lib/network-graph.ts
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - web/src/hooks/useApi.ts
  - src/api/routers/network.py
  - src/api/evidence.py
  - src/api/runtime.py
  - src/api/dependencies.py
  - src/network/service.py
  - src/network/topology.py
  - src/network/models.py
  - src/network/loader.py
findings:
  critical: 6
  warning: 11
  info: 3
  total: 20
status: issues_found
---

# Phase 12: Network Topology Page — Deep Code Review

**Reviewed:** 2026-09-03T23:02:57Z
**Depth:** deep (cross-file call-chain and data-contract tracing)
**Files Reviewed:** 16
**Status:** issues_found

## Summary

I traced the Network Topology page end-to-end: `web/src/app/network/page.tsx` → `TopologyWorkspace` → `network-graph.ts` → `TopologyGraph`/`TopologyDetailDrawer`, against `GET /api/v1/network/{topology,gaps,rule-findings,policy}` → `NetworkIntelligenceService` → `TopologyBuilder`/`_topology_resources`/`_topology_relationships` → `NetworkSnapshotLoader` → ontology rows / live-ARG `hybrid_network`, plus the downstream agent/MCP consumers in `src/operations/tools.py`.

The frontend graph builder is the strongest part of this stack — it is well-tested (`network-graph.test.ts`, 14 cases), correctly case-folds ARM IDs when resolving relationship endpoints, and de-duplicates bidirectional peerings. **The defects are almost entirely in the backend projection and scope layers, and they are being masked by the frontend's defensive coding.**

Four of the user-reported symptoms have a proven root cause each, and I verified them by executing the real code rather than by reading it:

- **"Fabric/Foundry visibility"** — `snapshot.private_link_resources` is loaded, counted, and used to raise high-severity gaps, but is **never projected into `_topology_resources()`**. Verified: a snapshot with a Fabric capacity and an AI Foundry account renders **0** nodes for them.
- **"Red-dot findings not appearing in drawer"** — has *three* independent causes: (a) findings reference resources that have no node (above), (b) `/gaps` and `/rule-findings` silently truncate at the server default `limit=100` and the client never paginates, (c) the drawer renders `null` instead of an explicit empty state, so truncation is indistinguishable from "clean".
- **"Custom design-policy rule refresh"** — `useApi` exposes no refetch; every policy mutation updates local component state only, so gaps/badges/topology keep showing pre-edit results until a full reload. Separately, the UI hard-blocks custom rules to `BUILTIN_RULE_IDS` and always sends `parameters: {}`, making the backend's declarative rule engine unreachable.
- **"Stale sync data"** — `_load_network_service()` discards the `freshness` value it just computed (`_freshness`), unlike its sibling `_load_semantic_snapshot()` which uses it. Topology freshness therefore degrades to `unknown` whenever ontology rows carry no per-row stamp.

The single most serious finding is **not** in the reported list: `NetworkIntelligenceService.scoped()` fails to filter `private_link_resources`, so a caller scoped to one subscription receives high-severity gap findings naming Key Vaults, storage accounts and Fabric capacities **in subscriptions they did not select** — complete with ARM resource IDs and subscription GUIDs. This contradicts the explicit security invariant documented in that same file (`service.py:66-73`) and it reaches agents/MCP too. I proved it end-to-end.

A note on scope discipline, per `.planning/STATE.md`: this is a **read-only review**. No source or planning files were modified; `STATE.md`/`ROADMAP.md` inconsistencies were left untouched as instructed. Only this artifact was written.

---

## Structural Findings (fallow)

No `<structural_findings>` block was supplied with this review, so the substrate below was derived by direct cross-module tracing rather than by a structural pre-pass.

Cross-module facts established during tracing:

| Fact | Evidence |
|---|---|
| `NetworkIntelligenceService.scoped()` is on the hot path for **every** scoped request | `src/api/routers/network.py:41`; `src/operations/tools.py:377,401,430,460`; `src/api/routers/twin.py:36` |
| `_scoped_topology()` is unreachable in production | Only caller is `analyze(scope)` (`service.py:258`); no caller in `src/` or `tests/` ever passes a scope to `analyze()` |
| `scoped()` has **zero** test coverage | `grep -rn "scoped(" tests/*.py` returns only unrelated `test_governance.py` / fake stubs |
| `_topology_resources()` executes twice per `to_dict()` | Verified by instrumentation: 2 invocations (`topology.py:193` + `topology.py:753`) |
| `private_link_resources` omitted from both projection and scope filter | `topology.py:570-633` (no extend); `service.py:79-94` (not in `replace()` field list) |

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `scoped()` leaks out-of-scope resources into gap findings — authorization boundary violation

**File:** `src/network/service.py:66-95` (`filter_snapshot`), `src/network/service.py:264-271` (`scoped`)

**Issue:** `NetworkScope.filter_snapshot()` rebuilds the snapshot with `replace()`, enumerating 14 collections — but **omits `private_link_resources`**. That tuple therefore survives scoping intact. `NetworkGapAnalyzer._unprotected_resources()` (`gaps.py:384-425`) iterates it directly and emits `missing_private_endpoint` gaps carrying `resource_id`, `resource_name`, `resource_type`, `subscription_id` and `connection_id`.

Because the router calls `service.analyze()` with **no** scope argument (`network.py:85`), `active.matches(gap)` is a no-op pass-through, so nothing downstream re-filters the leak.

Proven by executing the real code path:

```
LEAKED GAP -> missing_private_endpoint | kv-finance-prod | sub-b | /subscriptions/sub-b/rg/kv-finance-prod
summary gap_count: 1
counts leaked: 1
```

A caller scoped to `sub-a` received a high-severity finding naming a Key Vault in `sub-b`. This directly contradicts the invariant documented at `service.py:66-73`, which states that failing to filter would be "a disclosure across the same authorization boundary the scope exists to enforce."

There is a **second, compounding** defect: `private_endpoints` *is* scope-filtered while `private_link_resources` is not. `_private_endpoint_targets()` therefore loses the endpoints that protect out-of-scope resources, so those resources are reported as unprotected. The leak does not merely disclose data — it fabricates **false-positive high-severity security findings**.

Blast radius includes agents and MCP: `src/operations/tools.py:377,401,430,460` use the same `scoped()`.

**Fix:**
```python
# src/network/service.py, inside filter_snapshot()'s replace(...) call
    shared_services=tuple(i for i in snapshot.shared_services if keep(i)),
    private_link_resources=tuple(
        i for i in snapshot.private_link_resources if keep(i)
    ),
)
```
Add a regression test asserting that a service scoped to `sub-a` yields no gap whose `subscription_id != "sub-a"`.

---

### CR-02: `scoped()` silently discards `semantic_relationships`, changing the graph shape whenever a scope is selected

**File:** `src/network/service.py:264-271`

**Issue:** `scoped()` forwards `policy` but not `semantic_relationships`:

```python
return NetworkIntelligenceService(
    scope.filter_snapshot(self.snapshot),
    policy=self.policy,          # semantic_relationships dropped
)
```

`runtime.py:542-546` deliberately loads them (`semantic_relationships=relationships`), and `TopologyBuilder.build()` consumes them (`service.py:240`) to emit `attached_to` / `load_balances` / `hosts` edges (`topology.py:775-790`). Every scoped request throws that work away.

Verified:
```
unscoped semantic_relationships: 1
SCOPED  semantic_relationships: 0
```

This is worse than a simple data loss, because `topology.py:878` branches on it:

```python
if not topology.semantic_relationships:   # load-balancer fallback
```

So scoped and unscoped requests take **different code paths** and produce **different edge sets** for the same estate. A user who selects a subscription gets fallback LB edges but loses semantic `attached_to` edges; deselecting inverts it. This is a strong contributor to the "missing or broken subnet links" report, and it is completely silent.

**Fix:**
```python
return NetworkIntelligenceService(
    scope.filter_snapshot(self.snapshot),
    policy=self.policy,
    semantic_relationships=self.semantic_relationships,
)
```
Then remove the `if not topology.semantic_relationships:` branch at `topology.py:878` in favour of an unconditional, de-duplicated LB derivation, so edge sets no longer depend on provenance.

---

### CR-03: Private-link resources (Fabric, AI Foundry, PaaS) are never rendered as topology nodes

**File:** `src/network/topology.py:559-635` (`_topology_resources`)

**Issue:** The projection extends nodes from vnets, subnets, nics, nsgs, nsg rules, route tables, routes, peerings, firewalls, policies, collections, firewall rules, private endpoints, DNS zones, gateways, load balancers, and `_attached_workload_nodes(...)` — but **never from `snapshot.private_link_resources`**.

`PRIVATE_LINK_RESOURCE_TYPES` (`models.py:47-63`) explicitly includes `microsoft.fabric/capacities` → "Microsoft Fabric" and `microsoft.cognitiveservices/accounts` → "Azure AI Services", and `_WORKLOAD_ENTITY_TYPE_BY_PROVIDER` (`topology.py:664-678`) maps them to `FabricCapacity` / `AIFoundryAccount` node types that the frontend already has icons and styling for (`network-graph.ts:139-140`).

Verified:
```
snapshot private_link count: 2
rendered resource nodes  : [('vnet1', 'VNet')]
relationships            : 0
```

The only way such a resource reaches the canvas today is via `_attached_workload_nodes()`, which requires a NIC, private endpoint, or LB to *already* target it. **The resources that are missing a private endpoint — precisely the ones gap analysis flags as high severity — are exactly the ones that cannot appear.**

This produces an orphaned finding: a red high-severity gap whose `resource_id` matches no node, so it can never be badged (`TopologyGraph.tsx:449`) and never opened in the drawer (`TopologyWorkspace.tsx:245`). This is a second independent cause of "red-dot findings not appearing in drawer".

**Fix:** Add the missing projection, marking these as unattached context nodes:
```python
# src/network/topology.py, in _topology_resources(), before _attached_workload_nodes
existing = {node["id"] for node in nodes}
nodes.extend(
    _resource_node(
        resource,
        details={
            "service_kind": resource.service_kind,
            "public_network_access": resource.public_network_access,
            "private_link_candidate": True,
        },
    )
    for resource in snapshot.private_link_resources
    if resource.resource_id not in existing
)
```
Ensure `PrivateLinkResource.entity_type` resolves to the same `FabricCapacity`/`AIFoundryAccount`/etc. names the frontend already styles, so no client change is needed.

---

### CR-04: Gap and rule-finding badges silently truncate at 100 — metric cards under-report real estates

**File:** `web/src/lib/services.ts:878-893`; `src/api/dependencies.py:299-303`; `src/api/routers/network.py:187,220`

**Issue:** `networkApi.gaps()` and `networkApi.ruleFindings()` set only `severity`/`category` query params. They never send `limit` or `offset`, so the server applies its default `limit: int = Query(100, ge=1, le=500)` and slices:

```python
visible = gaps[page.offset : page.offset + page.limit]     # network.py:187
visible = findings[page.offset : page.offset + page.limit] # network.py:220
```

There is no follow-up request and no client-side reading of the returned `pagination` block. Consequences on any estate with >100 findings:

1. **Badges are wrong.** `buildFindingSeverityMap` (`TopologyWorkspace.tsx:14-34`) is built from the truncated array, so nodes 101+ silently lose their red dots.
2. **Metric cards contradict the API.** `page.tsx:104-106` renders `findings.data.data.findings.length` and `gaps.data.data.gaps.length` — both hard-capped at 100 — while `summary.rule_finding_count` / `summary.gap_count` (`service.py:128,131`) carry the true totals from the *unpaginated* analysis. The card freezes at "100" while the underlying summary says 340.
3. **Tabs lose data.** The "Inspection gaps" and "Rule findings" tabs render the same truncated list with no pagination control.

Note the codebase already has the right instinct elsewhere: `_truncation_warnings()` (`evidence.py:182-196`) exists to surface bounded results, but these two routes never emit a truncation warning despite being the two that truncate.

**Fix (server, cheap and honest):** emit a warning so truncation can never be silent:
```python
truncated = len(gaps) > page.offset + page.limit
return envelope(
    {...},
    warnings=(
        [f"Showing {len(visible)} of {len(gaps)} gaps; badges reflect this page only."]
        if truncated else []
    ),
    pagination=page.to_dict(len(gaps)),
)
```
**Fix (client):** drive badge maps from `summary.*_by_severity` totals, or page until exhausted, and switch the metric cards to `summary.gap_count` / `summary.rule_finding_count`.

---

### CR-05: `/topology` is unbounded — payload and canvas grow without any cap or level-of-detail

**File:** `src/network/topology.py:585,596,628` (per-rule nodes); `src/api/routers/network.py:82-95`; `web/src/components/network/TopologyGraph.tsx:249-265`

**Issue:** `_topology_resources()` materialises **every NSG rule, every route, and every firewall rule as its own graph node**:

```python
nodes.extend(_resource_node(rule) for nsg in snapshot.nsgs for rule in nsg.rules)          # :585
nodes.extend(_resource_node(route) for table in snapshot.route_tables for route in ...)    # :596
nodes.extend(_resource_node(rule) for collection in ... for rule in collection.rules)      # :628
```

`/topology` has no pagination, no node cap, and no level-of-detail parameter. I measured a deliberately **modest** estate (20 VNets, 60 subnets, 40 NSGs × 25 rules):

```
nodes: 1120  edges: 1060
payload MB: 1.80
```

That is ~1.8 MB for an estate far smaller than the enterprise target, and NSG default rules are synthesised on top (`models.py:414`). A realistic estate (hundreds of VNets, thousands of NSG rules) lands in the tens of megabytes and tens of thousands of Cytoscape elements. `layoutFor()` only downgrades fCoSE *quality* past `LAYOUT_NODE_BUDGET = 100`; it never reduces element count, so the fCoSE force simulation still runs on the main thread over the full set and the tab will lock.

This is a correctness-of-experience blocker, not a micro-optimisation: the page becomes unusable at exactly the scale it exists to serve.

**Fix:** Add a `detail` query parameter to `/topology` (`summary` = VNets/subnets/services only; `full` = current behaviour), defaulting to `summary`. Exclude rule-level nodes unless a specific parent is requested, and serve them through a `/topology/resources/{id}/children` drill-down that the drawer calls on demand. Emit a truncation warning in the envelope whenever nodes are withheld.

---

### CR-06: Policy edits never refresh derived views, and custom declarative rules are unreachable from the UI

**File:** `web/src/hooks/useApi.ts:19-46`; `web/src/app/network/page.tsx:623-694,710-739`

**Issue — stale derived state:** `useApi` returns only `{ data, error, loading }`. It exposes **no refetch/mutate handle**, and its effect is keyed on `deps` (`[scope]`). `toggleRule` (`:641-643`), `deleteRule` (`:653-656`) and `submitNewRule` (`:681-691`) each mutate *local* component state (`pending`, `removed`, `added`) after a successful `PATCH`, and nothing invalidates the `gaps`, `findings`, or `topology` loaders declared at `page.tsx:26-29`.

Result: an operator enables a rule, the toggle flips, and the Topology tab's red badges plus the Inspection-gaps tab keep showing pre-edit results until a full page reload or a scope change. This is the reported "custom design-policy rule refresh behavior" defect exactly.

The backend compounds it: `PATCH /policy` (`network.py:366-408`) persists via `store.update()` but does not invalidate the memoised `NetworkIntelligenceService`, whose `_gaps` are cached per instance (`service.py:161,244-247`) and whose policy was bound at construction (`runtime.py:544`). Depending on provider lifetime, a refetch may *still* return gaps computed under the old policy.

**Issue — declarative rules unreachable:** `submitNewRule` gates on `BUILTIN_RULE_IDS` (`:664`) and hardcodes `parameters: {}` (`:677`); `previewRule` does the same (`:730`). The backend supports declarative rules via `parameters.assert` and validates them through `validate_rule_parameters` (`network.py:266-276,341-363`), and `_policy_payload` reports `declarative` / `invalid_reason`. **None of that is reachable from the UI**, so "custom rule" support is effectively dead server-side capability.

**Fix:**
```ts
// useApi.ts — add a refetch handle
const [nonce, setNonce] = useState(0);
useEffect(() => { /* ...existing... */ }, [...deps, nonce]);
return { ...state, refetch: () => setNonce(n => n + 1) };
```
Call `gaps.refetch()` / `findings.refetch()` / `topology.refetch()` in each policy-mutation `.then()`. Lift the three loaders to a shared parent so `DesignPolicyWorkspace` can reach them. Server-side, key the policy-derived cache on a policy version/etag bumped by `store.update()`. Separately, add a `parameters` (assert-body) editor wired to `POST /policy/preview` so declarative rules become usable.

---

## Warnings

### WR-01: `Subnet.private_endpoint_ids` is the only ID collection not normalised to lowercase

**File:** `src/network/models.py:152-161`

**Issue:** Every sibling ID field is `_lower()`-ed (`vnet_id`, `nsg_id`, `route_table_id`, `nat_gateway_id`), as are the analogous collections elsewhere (`NSG.subnet_ids`/`nic_ids` `:396-397`, `RouteTable.subnet_ids` `:475`, `PrivateDnsZone.linked_vnet_ids` `:704`, `PrivateEndpoint.private_dns_zone_ids` `:679`). But:

```python
object.__setattr__(self, "private_endpoint_ids", _tuple(self.private_endpoint_ids))  # no _lower
```

`_topology_relationships` uses it at `topology.py:807-808`, and `_has_resource()` (`:747-748`) is an exact-case `in` test against all-lowercase node IDs. Any ARM-cased entry is dropped. The edge usually survives because `topology.py:862` re-derives it from the `PrivateEndpoint` side with lowercased IDs — but only when that endpoint is inside the snapshot. If the PE lives in an un-onboarded or out-of-scope subscription, the subnet→endpoint link is lost.

**Fix:** `object.__setattr__(self, "private_endpoint_ids", tuple(_lower(x) for x in _tuple(self.private_endpoint_ids)))`

### WR-02: Semantic relationship endpoints are not normalised before membership testing

**File:** `src/network/topology.py:784-790`; `src/network/service.py:222-229`

**Issue:** `subject_id`/`object_id` are passed to `add()` as raw strings (`str(semantic.get("subject_id") or "")`), and `from_arg_rows` copies them straight from `relationship.get("subjectId")`. Node IDs are uniformly lowercase (`models.py:116`), while semantic-graph IDs originate outside the network models and carry no such guarantee. Any casing mismatch causes a silent drop at `_has_resource`.

**Fix:** Apply `_lower()` to both endpoints in the `predicate_map` loop, or make `_has_resource` casefold both sides (see WR-03).

### WR-03: `add()` drops relationships silently, with no counter or diagnostic

**File:** `src/network/topology.py:747-760`

**Issue:** `add()` returns early whenever either endpoint is absent, and `_has_resource` is an exact-case test. There is no counter, log, or warning. When subnet links go missing in production there is **no way to tell** whether the edge was never derived, was dropped for a missing endpoint, or was dropped for a casing mismatch. This is why the reported "missing subnet links" issue is hard to diagnose.

Note the frontend already defends against casing (`network-graph.ts:300-308`, `indexNodesByFoldedId`/`resolveNodeId`, with a dedicated test at `network-graph.test.ts:235` — "keeps resource relationships when Azure resource ID casing differs"). That defence is useless for edges the backend discarded first.

**Fix:** Make `_has_resource` casefold both sides, and accumulate `dropped_relationships: dict[str, int]` keyed by `relationship_type`, surfaced in `to_dict()["counts"]` and as an envelope warning when non-zero.

### WR-04: `_load_network_service()` discards the freshness value it computes

**File:** `src/api/runtime.py:538-546`

**Issue:**
```python
entities, relationships, _freshness = _load_ontology_rows()   # discarded
```
The sibling `_load_semantic_snapshot()` (`:525-535`) uses it: `freshness=freshness or "1970-01-01T00:00:00Z"`. Network topology instead relies solely on per-row stamps via `_observed_at()` (`loader.py:559-574`). When ontology rows lack `last_observed_timestamp`/`observed_at`, `snapshot.observed_at` is `""`, `_evidence()` (`network.py:78`) emits an empty timestamp, and `classify_freshness` returns `unknown`. The operator cannot tell a fresh topology from a week-old one — the "stale sync data" complaint.

**Fix:** `NetworkIntelligenceService.from_rows(..., observed_at=freshness)` and have the loader fall back to that snapshot-level stamp when no row carries one.

### WR-05: `_scoped_topology()` is dead code carrying three latent defects

**File:** `src/network/service.py:313-333`

**Issue:** Reachable only via `analyze(scope)` with a non-empty scope; no caller in `src/` or `tests/` ever passes one. It nonetheless contains three bugs that will activate the moment someone does:
- drops `semantic_relationships` (not forwarded to the `NetworkTopology` constructor);
- filters links to `local_vnet_id in kept and remote_vnet_id in kept` (`:322-326`), deleting every cross-scope peering — including its `unresolved` representation;
- keeps the **unscoped** `unresolved_peer_vnet_ids` (`:330`), so the frontend materialises orphan "not onboarded" nodes (`network-graph.ts:402-404`) whose edges were just filtered away, and leaks out-of-scope VNet ARM IDs.

**Fix:** Delete the method and the unused `scope` parameter on `analyze()`, or fix all three and add coverage. Do not leave it as an unexercised trap.

### WR-06: Rule findings are badged against the control, not the affected resource

**File:** `web/src/components/network/TopologyWorkspace.tsx:32,57`

**Issue:** `bump(finding.control_id, finding.severity)` and `entry(finding.control_id).ruleFindings.push(finding)` key on `control_id`, which `tightening.py` populates with `nsg.resource_id` or `collection.resource_id` (`:175,328,395,450,604,757,794,838`). `RuleFinding` has **no** `resource_id` field (`types.ts:1680-1695`).

So an overly-broad NSG rule badges the NSG node only. An operator inspecting the *subnet* or *VNet* that the NSG protects sees no badge and an empty drawer, even though the finding is about their exposure. The frontend comment claims the map is "per resource id" — it is per *control* id.

**Fix:** Have the backend add an `affected_resource_ids: tuple[str, ...]` to `RuleFinding` (subnets/NICs from `nsg.subnet_ids`/`nic_ids`) and fan out the badge across control **and** affected resources.

### WR-07: Drawer renders `null` for no findings — truncation is indistinguishable from "clean"

**File:** `web/src/components/network/TopologyDetailDrawer.tsx:136-139`

**Issue:** `if (gaps.length === 0 && ruleFindings.length === 0) return null;`. Combined with CR-03 (orphaned findings) and CR-04 (100-item cap), a node that genuinely has open findings shows a drawer with the "Open findings" section entirely absent — reading as "this resource is clean". For a security-facing view that is a dangerous default, and it is the same failure mode `network.py:1-8` warns about at the API layer.

**Fix:** Render an explicit `<StatePanel>`: "No open findings for this resource" vs. "Findings unavailable (results truncated — N of M loaded)", driven by the pagination metadata from CR-04.

### WR-08: Badge visibility and drawer content disagree under the "Gap / rule badges" toggle

**File:** `web/src/components/network/TopologyWorkspace.tsx:239,245`

**Issue:** `findingSeverityByResource={showFindings ? findingSeverityByResource : undefined}` gates badges, but `findings={... findingsByResource.get(...)}` is unconditional. Turning badges off leaves the drawer still listing findings, so the toggle's meaning is ambiguous.

**Fix:** Gate both on `showFindings`, or rename the control to "Show badges" to make it purely visual.

### WR-09: Node-ID fold index goes stale as unresolved nodes are appended

**File:** `web/src/lib/network-graph.ts:407,418-419`

**Issue:** `nodeIds` is built once (`:407`) before the peering loop. Inside the loop, unresolved remote VNets are appended to `nodes` (`:419`) but never registered in `nodeIds`. A later link referencing the same remote VNet with different casing fails `resolveNodeId`, falls through to its raw ID, and creates a **duplicate** unresolved node for one real VNet.

**Fix:** `byFoldedId.set(remoteVnetId.toLowerCase(), remoteVnetId)` when inserting, or resolve against a live `Map` helper.

### WR-10: Dangling `resolvesFor` edges emitted for zones absent from the payload

**File:** `src/onboarding/graph_normalize.py:753-757`

**Issue:**
```python
for zone_id, vnet_id in dns_links:
    zone = dns_zones.get(zone_id)
    if zone is not None and vnet_id not in zone["linkedVnetIds"]:
        zone["linkedVnetIds"].append(vnet_id)
    link(zone_id, "resolvesFor", vnet_id, 0.98)   # emitted even when zone is None
```
When a `virtualNetworkLinks` child row is present but its parent zone is not (common when the zone lives in a subscription outside the sync scope), a relationship is written to a non-existent entity. The topology projection then discards it silently at `_has_resource`, so private-DNS→VNet links vanish with no diagnostic — the reported "private DNS VNet linking" symptom.

Note also that `resolvesFor` is **not** in `topology.py`'s `predicate_map` (`:775-779`, only `attachedto`/`loadbalances`/`hosts`), so the topology page relies entirely on `zone.linked_vnet_ids` and ignores the semantic edge even when it is valid.

**Fix:** Only `link(...)` when `zone is not None`; otherwise record a normalisation warning. Add `"resolvesfor": "linked_to"` to `predicate_map` so a valid semantic edge can stand in when zone properties are thin.

### WR-11: UI and API hardcode "no flow logs" while a flow-log ingestion pipeline exists

**File:** `web/src/app/network/page.tsx:73`; `src/api/routers/network.py:226-227`; `web/src/lib/types.ts:1636-1638`

**Issue:** The page header renders a fixed `<span>No flow logs assumed</span>`, `/rule-findings` hardcodes `CONFIDENCE_MEDIUM` with the comment "no flow logs are ingested", and the `NetworkGap.basis` doc comment repeats the claim. Meanwhile `src/fabric_pipelines/flowlog_ingest.py` supports live `NTANetAnalytics` ingestion (`:113 live_flow_logs_from_rows`), and `tightening.py` explicitly consumes `trafficObserved` provenance and `allowedVsObserved` verdicts (`:646,653,699,877`).

When flow logs *are* ingested, the page still tells the operator they are not, and confidence stays pinned at medium — under-reporting evidence quality and misrepresenting the basis of findings.

**Fix:** Derive the banner and confidence from actual provenance (presence of `FLOWLOG_SOURCE_TAG`-marked edges in the snapshot) rather than from a constant.

---

## Info

### IN-01: `_topology_resources()` computed twice per response

**File:** `src/network/topology.py:193,753`

**Issue:** `to_dict()` calls it directly, and `_topology_relationships()` calls it again to build `resource_ids`. Verified: 2 invocations per `to_dict()`. Beyond the wasted work at the scale described in CR-05, the two projections could in principle diverge.

**Fix:** Compute once in `to_dict()` and pass the node list into `_topology_relationships(self, resources)`.

### IN-02: Export JSON serialises the raw payload with no scope or evidence context

**File:** `web/src/components/network/TopologyGraph.tsx:399-403`

**Issue:** The exported file contains only `topology`, losing the evidence envelope, scope selection, and freshness band. An exported diagram cannot be audited later for what scope or snapshot age it represents.

**Fix:** Wrap the export as `{ exported_at, scope, evidence, knowledge_version, topology }`.

### IN-03: Selected element remains styled while hidden in filter mode

**File:** `web/src/components/network/TopologyGraph.tsx:429-440`

**Issue:** In `filterMode`, non-matches get `display: none`, but the `selectedId` block afterwards still applies `.cy-selected` to a hidden element. The drawer stays open describing a node that is no longer visible.

**Fix:** Clear the selection when the selected element falls outside `keep`, or skip the selection styling when it is hidden.

---

## Prioritised Recommendations (implementation-ready)

Exactly five, ordered by (user/operator value × defect severity) ÷ change risk.

---

### REC-1 — Restore the scope boundary in `filter_snapshot` and `scoped`

**Addresses:** CR-01, CR-02
**Evidence:** `src/network/service.py:66-95` (`filter_snapshot`, missing `private_link_resources`), `service.py:264-271` (`scoped`, missing `semantic_relationships`). Proven: scoped-to-`sub-a` service emitted `missing_private_endpoint | kv-finance-prod | sub-b`; `semantic_relationships` 1 → 0.

**Value:** Closes an authorization-boundary disclosure that currently reaches the web UI, agents, and MCP (`operations/tools.py:377,401,430,460`). Simultaneously eliminates the false-positive high-severity gaps caused by asymmetric filtering, and makes scoped/unscoped topologies return the same edge set.

**Change surfaces:**
- `src/network/service.py` — add `private_link_resources` to the `replace()` list; forward `semantic_relationships` in `scoped()`.
- `src/network/topology.py:878` — remove the provenance-dependent LB fallback branch; derive LB edges unconditionally with de-duplication.
- `tests/test_network_analysis.py` — new scope-isolation and semantic-preservation cases.

**Dependencies:** None. Self-contained in the network package.

**Risks:** Removing the `:878` branch could duplicate LB edges if the semantic graph already supplies them — mitigated because `relationships` is a dict keyed by `_relationship` id (`topology.py:760`), so duplicates collapse naturally. Gap counts will *drop* for scoped callers; communicate this as a correction, not a regression.

**Acceptance criteria:**
1. A service scoped to `sub-a` yields zero gaps with `subscription_id != "sub-a"`.
2. `scoped(...).semantic_relationships == service.semantic_relationships`.
3. `to_dict()["counts"]["private_link_resources"]` reflects only in-scope resources.
4. Scoped and unscoped topologies produce identical `relationship_type` sets for a fixture with a load balancer.
5. A test asserts a private endpoint in scope still marks its target protected (no false positive).

---

### REC-2 — Project private-link resources onto the canvas

**Addresses:** CR-03; unblocks part of the "red dot" symptom
**Evidence:** `src/network/topology.py:559-635` omits `snapshot.private_link_resources`; `models.py:47-63` maps Fabric/Cognitive Services; `topology.py:664-678` already names the entity types; `network-graph.ts:139-140` already styles them. Proven: 2 private-link resources → 0 rendered nodes.

**Value:** Makes Fabric capacities and AI Foundry accounts visible — the reported "Fabric/Foundry visibility" gap. More importantly, gives every `missing_private_endpoint` finding a node to attach to, so its red badge and drawer entry become reachable.

**Change surfaces:**
- `src/network/topology.py` — extend `_topology_resources()` (dedupe against `_attached_workload_nodes`).
- `src/network/models.py` — ensure `PrivateLinkResource.entity_type` resolves to the frontend's known names.
- Optionally `topology.py` — add a `reachable_publicly` relationship or node flag so exposure is visually distinct.
- `tests/test_network_topology.py` — node-presence assertions.

**Dependencies:** Ships after REC-1 (scope filter must exist first, or newly-visible nodes would widen the CR-01 leak to the canvas).

**Risks:** Node-count growth on estates with many PaaS resources — bounded by REC-3's level-of-detail work. Duplicate nodes if a resource is both a private-link candidate and an attached workload; the `existing` guard handles it and needs a test.

**Acceptance criteria:**
1. A snapshot with a Fabric capacity and an AI Foundry account renders nodes with `entity_type` `FabricCapacity` / `AIFoundryAccount`.
2. A resource that is both PE-targeted and a private-link candidate renders exactly once.
3. Every `missing_private_endpoint` gap's `resource_id` matches a node id in the same response.
4. Frontend test: such a node renders its official icon and is badgeable.

---

### REC-3 — Make truncation and payload bounds explicit and honest

**Addresses:** CR-04, CR-05, WR-07
**Evidence:** `services.ts:878-893` (no `limit`); `dependencies.py:299-303` (default 100); `network.py:187,220` (silent slice); `page.tsx:104-106` (capped counts rendered as totals); `topology.py:585,596,628` (per-rule nodes); measured 1,120 nodes / 1.8 MB on a modest estate; `TopologyGraph.tsx:249-265` (quality-only degradation).

**Value:** Stops the page under-reporting security findings, and keeps it usable at enterprise scale. Directly resolves the "red dots not appearing" complaint for estates over 100 findings.

**Change surfaces:**
- `src/api/routers/network.py` — truncation warnings on `/gaps` and `/rule-findings`; add `detail=summary|full` to `/topology`.
- `src/network/topology.py` — gate rule/route-level nodes behind `detail=full`; add `/topology/resources/{id}/children` for drill-down.
- `web/src/lib/services.ts` — accept and forward `limit`/`offset`; page until exhausted for badge maps.
- `web/src/app/network/page.tsx` — metric cards read `summary.gap_count` / `summary.rule_finding_count`.
- `web/src/components/network/TopologyDetailDrawer.tsx` — explicit empty vs. truncated states.

**Dependencies:** REC-2 lands first so the drill-down contract covers the new node types.

**Risks:** Changing the default `/topology` shape is a breaking contract change for agents/MCP (`operations/tools.py:375-392`) and the JSON export. Mitigate by defaulting `detail=full` for one release while emitting a deprecation warning in the envelope, then flipping.

**Acceptance criteria:**
1. Requesting 101+ gaps returns a `warnings` entry naming shown-vs-total counts.
2. Metric cards match `summary.*_count` exactly at >100 findings.
3. `detail=summary` returns no `NetworkSecurityRule`/`Route`/`FirewallRule` nodes.
4. The 20-VNet/40-NSG fixture yields <200 nodes and <250 KB at `detail=summary`.
5. Drawer distinguishes "no open findings" from "results truncated".

---

### REC-4 — Give policy edits a refresh path and expose declarative rules

**Addresses:** CR-06
**Evidence:** `useApi.ts:19-46` (no refetch); `page.tsx:641-643,653-656,681-691` (local-only state updates); `page.tsx:664,677,730` (`BUILTIN_RULE_IDS` gate, `parameters: {}`); `network.py:266-276,341-363` (unreachable declarative validation); `service.py:161,244-247` (per-instance gap cache).

**Value:** Resolves the "custom design-policy rule refresh" report. An operator toggling a rule sees badges and gaps update immediately, and can finally author the declarative rules the backend already validates.

**Change surfaces:**
- `web/src/hooks/useApi.ts` — add a `refetch` handle (nonce-based).
- `web/src/app/network/page.tsx` — lift `topology`/`gaps`/`findings` loaders so `DesignPolicyWorkspace` can invalidate them; call `refetch()` in every mutation `.then()`.
- `web/src/app/network/page.tsx` — `parameters` (assert-body) editor wired to `POST /policy/preview`; drop the `BUILTIN_RULE_IDS` hard gate in favour of server validation.
- `src/api/runtime.py` / `src/network/service.py` — policy version/etag bumped by `store.update()`, keyed into the derived-analysis cache.

**Dependencies:** Independent of REC-1..3; can run in parallel.

**Risks:** Refetch-on-every-toggle can burst requests against the live-ARG `hybrid_network` path — mitigated by the existing 30 s `_hybrid_network_cache` (`runtime.py:2686-2694`) and by debouncing. Allowing arbitrary `rule_id`s increases the validation surface; `validate_rule_parameters` already rejects malformed bodies before persistence (`network.py:380-393`).

**Acceptance criteria:**
1. Toggling a rule updates the Inspection-gaps list and topology badges without a reload.
2. A declarative rule with an `assert` body can be created, previewed, and saved from the UI.
3. An invalid `assert` body is rejected with the server's `invalid_reason` shown inline, and nothing is persisted.
4. After `PATCH /policy`, the next `/gaps` reflects the new policy (no stale cache).
5. Test: two rapid toggles issue at most one refetch per loader.

---

### REC-5 — Make relationship loss observable, and cover the scope seam with tests

**Addresses:** WR-01, WR-02, WR-03, WR-04, WR-05, WR-10; test blind spots
**Evidence:** `topology.py:747-760` (silent exact-case drop, no counter); `models.py:159` (`private_endpoint_ids` unnormalised); `service.py:222-229`/`topology.py:784-790` (unnormalised semantic endpoints); `runtime.py:539` (`_freshness` discarded); `graph_normalize.py:753-757` (dangling `resolvesFor`); `scoped()` has zero test coverage.

**Value:** Converts the entire class of "missing subnet / DNS / Fabric links" from unfalsifiable user reports into a number an operator can read off the response. Restores honest freshness banding for the "stale sync data" complaint.

**Change surfaces:**
- `src/network/topology.py` — casefold both sides in `_has_resource`; accumulate `dropped_relationships` by type into `to_dict()["counts"]`; emit an envelope warning when non-zero; add `"resolvesfor"` to `predicate_map`.
- `src/network/models.py` — `_lower()` on `Subnet.private_endpoint_ids`.
- `src/network/service.py` — normalise semantic endpoint IDs; delete `_scoped_topology` (or fix all three latent bugs).
- `src/api/runtime.py` — thread `freshness` into `NetworkIntelligenceService.from_rows`.
- `src/onboarding/graph_normalize.py` — suppress `resolvesFor` when the zone is absent; record a normalisation warning.
- `tests/` — first-ever coverage of `scoped()`; casing-mismatch relationship fixtures; freshness-banding assertions.

**Dependencies:** Best landed alongside REC-1 (same files, same tests).

**Risks:** Casefolding in `_has_resource` will *increase* edge counts on estates with mixed casing — that is the intended correction, but it will visibly change the canvas and should be called out in the phase summary. `dropped_relationships` counts may be alarming on first run; frame as newly-surfaced pre-existing loss, not new breakage.

**Acceptance criteria:**
1. A fixture whose subnet references its VNet with different ARM casing produces the `contains` edge.
2. `to_dict()["counts"]["dropped_relationships"]` is present and zero for a fully-consistent fixture.
3. A fixture with a deliberately dangling endpoint reports a non-zero drop count **and** an envelope warning.
4. Topology evidence reports `fresh`/`aging`/`stale` (never `unknown`) when ontology rows carry only a snapshot-level stamp.
5. `scoped()` has direct tests for scope isolation, semantic preservation, and `private_link_resources` filtering.
6. A `virtualNetworkLinks` row without its parent zone emits no dangling `resolvesFor`.

---

## Test Blind Spots

| Area | Status | Note |
|---|---|---|
| `NetworkIntelligenceService.scoped()` | **none** | Hot path for every scoped request; two proven defects (CR-01, CR-02) |
| `_scoped_topology()` | **none** | Unreachable; three latent defects (WR-05) |
| `private_link_resources` projection | **none** | Only asserted via `service_kind` in `test_network_analysis.py:430` |
| Pagination / truncation of gaps & findings | **none** | No test pins the 100-item boundary |
| `TopologyWorkspace` finding-map construction | **none** | No test file; `control_id` keying (WR-06) unverified |
| Policy-save → derived-view refresh | **none** | CR-06 would have been caught by one integration test |
| Topology payload size / node budget | **none** | No performance or shape assertion at scale |
| Graph builder (`network-graph.ts`) | **good** | 14 cases incl. casing (`:235`) — the strongest area |
| Cytoscape stylesheet & hover | **good** | 13 cases in `TopologyGraph.test.tsx` |

---

_Reviewed: 2026-09-03T23:02:57Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
_Note: read-only review. No source or planning files were modified; `STATE.md`/`ROADMAP.md` inconsistencies were left untouched per instruction._
