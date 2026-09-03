# Phase 12: Network Topology Integrity and Scale - Research

**Researched:** 2025-06-09
**Domain:** Azure network topology projection, scope isolation, API contract evolution, graph rendering at scale
**Confidence:** HIGH (in-repo, verified by reading source and executing the real code); LOW on two external questions (Azure Fabric private-link semantics, Cytoscape interactive node ceiling) — no web/Context7 provider was reachable this session.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Scope isolation is the first tracer and a security gate.** The confirmed cross-subscription leak in
   `NetworkIntelligenceService.filter_snapshot` / `scoped()` is fixed first, with a regression test that fails
   on the current code, before any new projection or UI work lands.
2. **Private Link resources become first-class topology nodes.** `private_link_resources` are projected into the
   topology graph (not merely counted), including Fabric capacities and AI Foundry accounts, so that gaps and
   findings referencing them resolve to a rendered node.
3. **Scale is solved by level-of-detail plus honest truncation, not by silently dropping data.** The API gains an
   explicit detail contract and pagination; whenever the response is not complete, the envelope says so.
4. **The design-policy workspace must round-trip.** Policy mutations invalidate the derived analysis so gaps and
   rule findings reflect the saved policy without a manual page reload.
5. **Evidence and freshness must be truthful.** Any banner, badge, or count shown in the UI is derived from
   observed data, not hardcoded, and unknown freshness is displayed as unknown rather than as fresh.
6. **Contract changes are additive or explicitly deprecated.** Existing agent, MCP, and export consumers of the
   topology payload keep working; any default change is announced and covered by a compatibility test.
7. **Phase 11 scope is preserved.** This phase does not absorb, redefine, or defer Phase 11 work.

### In Scope

- `src/network/` — service scope filtering, topology projection, gaps, tightening, freshness threading.
- `src/api/routers/network.py` and the shared envelope, scope, and pagination helpers.
- `web/src/app/network/` and `web/src/components/network/` — page, workspace, graph, drawer, export.
- Upstream normalization only where it demonstrably corrupts the network snapshot (identifier casing,
  observed-at threading, dangling predicates).
- Downstream compatibility for agents and MCP consumers of the topology contract.

### Out of Scope (Deferred)

- Any Phase 11 deliverable.
- New data sources beyond those already normalized into the ontology.
- A rewrite of the graph rendering library or the layout engine.
- Live flow-log ingestion as a new pipeline (only truthful representation of its absence, plus the wiring seam).

### Delivery Order

1. Scope isolation fix + failing-first regression test (security gate).
2. Correctness cluster: identifier casing, dropped relationships, freshness threading, dead code removal.
3. Private Link projection and entity-type/icon mapping.
4. Level-of-detail, pagination, truncation honesty, drill-down, and downstream compatibility window.
5. Design-policy round-trip and declarative rule editor surface (may run in parallel from the start).

### Verification Expectations

- Every defect fixed lands with a test that fails on the pre-fix code.
- Scale claims are measured against a fixture, not asserted.
- The security gate is verified by an explicit cross-subscription isolation test.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (from REQUIREMENTS.md:91-95) | Research Support |
|----|------------------------------------------|------------------|
| **TOPO-01** | Network scope filtering must isolate subscriptions/resource groups across every derived artifact (snapshot collections, gaps, rule findings, semantic relationships). | §Defect Map D-01..D-04 (executed reproduction), §Code Examples E-1/E-2, §Security Domain (ASVS V4). Fix is 3 files, ~15 lines; regression test in `tests/test_network_analysis.py`. |
| **TOPO-02** | Private Link resources (incl. Fabric capacities and AI Foundry accounts) must be projected as topology nodes so findings resolve to a rendered entity. | §Defect Map D-05/D-06, §Code Examples E-3 (projection + entity-type mapping), §Pitfall P-2 (icon gap — the review's "already styled" claim is only half true), `web/public/azure-icons/README.md` procedure. |
| **TOPO-03** | The topology and analysis APIs must remain performant and truthful at enterprise estate size (level-of-detail, pagination, explicit truncation). | §Scale Budgets (measured at 3 estate sizes), §Code Examples E-4/E-5, §Architecture Patterns AP-1/AP-2/AP-3. **The review's ≤250 KB target is unachievable without also stripping embedded `details` blobs — proven below.** |
| **TOPO-04** | The design-policy workspace must round-trip: saved policy invalidates derived analysis, and the rule editor reflects the real engine contract. | §Defect Map D-13..D-16, §Code Examples E-6 (refetch nonce), §Don't Hand-Roll DH-4 (`validate_rule_parameters`), §Runtime State Inventory (30 s provider cache is the true blocker). |
| **TOPO-05** | Topology evidence must be truthful: freshness derived from observed data, no hardcoded banners, dropped relationships counted rather than silently discarded. | §Defect Map D-08..D-12, §Flow-Log Provenance (deeper than the review: findings can never fire in production today), §Code Examples E-2. |
</phase_requirements>

## Summary

Phase 12 is a **correctness-and-contract** phase, not a feature phase. Every deliverable already has a home in
existing modules; the work is repairing four classes of defect in code that is otherwise well-factored, then
extending three contracts additively. No new runtime dependency is required in either the Python or the web
workspace — the only new *assets* are two official Azure icon SVGs.

I verified the review's findings by reading the source **and by executing the real code** in throwaway probe
scripts outside the repository. All six critical findings reproduce. Two of them are worse than the review
states, and one recommendation as written is **not achievable**:

- The cross-subscription leak is not one bug but **four call sites** (`filter_snapshot` omits one collection,
  `scoped()` drops `semantic_relationships`, `preview_policy` drops it again — the review missed this third one —
  and `_scoped_topology` is dead code carrying three latent bugs).
- REC-3's acceptance criterion ("<200 nodes and <250 KB at `detail=summary`") **fails** if you only drop
  rule-level nodes: my measurement is 130 nodes but **729.4 KB**, because NSG and route-table nodes embed their
  entire `details.rules` / `details.routes` collections. It passes at **151.3 KB** only when the level-of-detail
  contract *also* strips embedded detail collections and serves them via drill-down. This changes the shape of
  the API work from "filter node types" to "filter node types **and** project a lean node payload".
- Flow-log findings can never fire in production, at any scale, because `NetworkIntelligenceService.rule_findings`
  never passes `flow_observations` to `analyze_rules`. Fixing the hardcoded banner without wiring the seam would
  replace one lie with another.

**Primary recommendation:** land the scope-isolation fix (all four call sites) as a self-contained first tracer
with a failing-first cross-subscription regression test, and treat it as the phase's security gate — it is an
ASVS V4 access-control defect that discloses out-of-scope ARM resource identifiers, and it is ~15 lines across
three files with zero contract impact. Everything else builds on a snapshot you can trust.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Identifier normalization (ARM ID casing) | Database/Ontology (`src/network/models.py` `__post_init__`) | Ontology normalize (`src/onboarding/graph_normalize.py`) | Casefolding must happen once, at the model boundary where every other field is already lowered — not at each comparison site. |
| Observed-at / freshness derivation | Database/Ontology (`src/network/loader.py`) | API/Backend (`src/api/runtime.py`) | The loader already computes `max(observed)`; it simply has no parameter to accept an externally supplied stamp and no consumer that keeps it. |
| Scope filtering | API/Backend (`src/network/service.py`) | — | Scope is a request-time concern applied to an immutable snapshot; it must not leak into the loader or the router. |
| Topology projection (nodes/edges) | API/Backend (`src/network/topology.py`) | — | Single pure function over a snapshot; the graph library must never decide what exists. |
| Level-of-detail / pagination / truncation | API/Backend (`src/api/routers/network.py` + `src/api/evidence.py`) | Browser/Client (render budget) | The server owns the truth about completeness; the client owns only presentation. Doing LOD client-side would still ship the 78 MB payload. |
| Policy persistence + revision (etag) | Database/Ontology (`src/network/design.py`) | API/Backend (`src/api/providers.py` cache) | The store already versions documents; the API needs to stop serving a 30 s-stale derived analysis. |
| Graph rendering, layout, selection | Browser/Client (`web/src/components/network/`) | — | Cytoscape/fCoSE is a presentation concern. |
| Refetch orchestration | Browser/Client (`web/src/hooks/useApi.ts`) | — | `useApi` is the only place a refetch handle can live without duplicating loading/error state in every page. |
| Export payload provenance | Browser/Client (`TopologyGraph.tsx`) | API/Backend (envelope) | The export must carry the scope/freshness/truncation metadata the server produced. |
| Agent/MCP topology access | Downstream (`src/operations/tools.py`) | API/Backend (REST relay) | `src/mcp_server/app.py` is a relay with no network tools; MCP reaches topology only through REST, so REST contract stability is the whole compatibility story. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | in-repo (`src/api/`) | Routers, `Depends` scope/pagination injection | Already the API framework; `get_pagination` / `read_scope` dependencies exist. [VERIFIED: src/api/dependencies.py:264-306] |
| pytest | in-repo (`pyproject.toml` `testpaths=["tests"]`, `addopts="-q"`) | Backend tests | Existing suite; `tests/conftest.py` puts `src/` on `sys.path`. [VERIFIED: executed `.venv/bin/python -m pytest`] |
| vitest + jsdom | `web/vitest.config.ts` | Web tests | Existing suite; alias `@ → ./src`, setup `src/test/setup.ts`. [VERIFIED: web/vitest.config.ts] |
| cytoscape | ^3.34.1 (`web/package.json`) | Graph rendering | Already integrated in `TopologyGraph.tsx`. [VERIFIED: web/package.json] |
| cytoscape-fcose | ^2.2.0 | Force layout | Already integrated; `LAYOUT_NODE_BUDGET` degrades quality above 100 nodes. [VERIFIED: web/src/components/network/TopologyGraph.tsx:249] |
| Next.js | 14.2.35 | App router pages | Existing. [VERIFIED: web/package.json] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| — | — | — | **No new library is required by this phase.** Every capability (pagination, truncation warnings, freshness banding, declarative rule validation) already has an in-repo implementation to reuse. |

### New Assets (not packages)

| Asset | Purpose | Procedure |
|-------|---------|-----------|
| Microsoft Fabric icon SVG | `RESOURCE_ICONS["FabricCapacity"]` | `web/public/azure-icons/README.md` mandates official, **unmodified** Azure architecture icons (V21 set) placed in `web/public/azure-icons/` and mapped in `network-graph.ts`. [VERIFIED: web/public/azure-icons/README.md] |
| Azure AI Services icon SVG | `RESOURCE_ICONS["AIFoundryAccount"]` | Same. |

**Installation:** none. Do not add packages for this phase; if a plan proposes one, that is a signal the work
drifted out of scope.

## Package Legitimacy Audit

**This phase installs no external packages.** The Package Legitimacy Gate is therefore not applicable: there are
no registry lookups to perform, no `[SLOP]` or `[SUS]` verdicts to record, and no `checkpoint:human-verify`
install gates for the planner to insert.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| *(none)* | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

If the planner concludes an icon must be sourced from an npm icon pack rather than the official Azure SVG set,
that decision **reverses a documented repository rule** (`web/public/azure-icons/README.md`) and requires a
`checkpoint:human-verify` plus a fresh legitimacy audit.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────────────────────────────────────┐
   Azure Resource   │  UPSTREAM NORMALIZATION                                  │
   Graph rows  ────▶│  loader.load_network_snapshot(rows)                      │
   OneLake/Fabric   │    ├─ per-ARM-type row collection  (loader.py:208-282)   │
   ontology rows ──▶│    ├─ observed = max(observed, _observed_at(row))        │
                    │    └─ model __post_init__ lowercases identifiers  ◀── D-08 casing gap
                    └────────────────────────┬─────────────────────────────────┘
                                             │  NetworkSnapshot (15 collections)
                                             ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │  ANALYSIS TIER  src/network/service.py                    │
   NetworkScope ───▶│    scoped(scope) ─▶ filter_snapshot()  ◀── D-01 drops 1 collection
   (sub/rg)         │                   ─▶ NetworkIntelligenceService(...)      │
                    │                        ◀── D-02 drops semantic_relationships
                    │    ├─ topology  ─▶ topology.build_topology()  ◀── D-05 no PL nodes
                    │    ├─ gaps      ─▶ gaps.analyze()                         │
                    │    └─ findings  ─▶ tightening.analyze_rules(snapshot)     │
                    │                        ◀── D-12 flow_observations never passed
                    └────────────┬───────────────────────────┬─────────────────┘
                                 │                           │
                    ┌────────────▼───────────┐   ┌───────────▼──────────────────┐
                    │ REST  routers/network  │   │ AGENTS  operations/tools.py  │
                    │  /topology  ◀── no LOD │   │  _tool_topology → scoped()   │
                    │  /gaps      [:limit]   │   │  _bound(..., _MAX_ITEMS=25)  │
                    │  /rule-findings[:limit]│   │  ◀── D-17 silent truncation  │
                    │  /policy PATCH ◀─ D-13 │   └───────────┬──────────────────┘
                    │  Envelope + warnings   │               │
                    └────────────┬───────────┘   ┌───────────▼──────────────────┐
                                 │               │ MCP  mcp_server/app.py       │
                                 │               │  relay only — no network     │
                                 │               │  tools; reaches topology     │
                                 │               │  solely via REST above       │
                                 │               └──────────────────────────────┘
                    ┌────────────▼─────────────────────────────────────────────┐
                    │  WEB  app/network/page.tsx                                │
                    │    useApi(fn, [scope])  ◀── D-14 no refetch handle        │
                    │    metric cards use .length  ◀── D-15 shows capped counts  │
                    │    flow-log banner hardcoded ◀── D-11                      │
                    │      ├─ TopologyWorkspace ─ badges keyed on control_id ◀ D-18
                    │      │     └─ TopologyGraph (cytoscape/fcose)             │
                    │      │           └─ exportJson: bare topology ◀── D-19    │
                    │      └─ TopologyDetailDrawer: return null ◀── D-20        │
                    └──────────────────────────────────────────────────────────┘
```

### Reusable Patterns Validated In This Repository

#### AP-1: Honest truncation via the envelope warning seam
**What:** `evidence._truncation_warnings()` walks the payload and auto-emits a warning whenever *any* nested
mapping carries `"truncated": true`; `Envelope.to_dict` merges those with explicit warnings.
**When to use:** every response in this phase that can be incomplete (topology at `detail=summary`, gaps,
rule findings, drill-down pages).
**Why it matters:** the planner does not need to invent a truncation protocol — emitting the flag is sufficient
and the warning appears automatically, which the web layer already surfaces.
[VERIFIED: src/api/evidence.py:182-196]

```python
# src/api/evidence.py:182-196 (verbatim)
def _truncation_warnings(payload: Any) -> list[str]:
    warnings: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            if node.get("truncated") is True:
                label = path or "payload"
                warnings.append(f"{label} truncated; refine the query or increase the limit")
            for key, value in node.items():
                _walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for item in node:
                _walk(item, path)

    _walk(payload, "")
    return warnings
```

#### AP-2: Coverage metadata shape
**What:** `{"total": N, "returned": M, "truncated": bool}` is the established in-repo shape for describing a
partial collection.
**When to use:** the `counts` / `coverage` block of the topology response and of each analysis collection.
[VERIFIED: src/api/routers/context.py:80-84]

#### AP-3: Server-side pagination
**What:** `Pagination` dataclass with `offset`/`limit`, injected by `get_pagination`, and `to_dict(total)`
producing `{offset, limit, total, next_offset}`.
**When to use:** `/gaps` and `/rule-findings`, replacing the current bare `[: pagination.limit]` slice.
[VERIFIED: src/api/dependencies.py:280-306] — `limit: int = Query(100, ge=1, le=500)`, default `Pagination(offset=0, limit=100)`.
The web-side counterpart is `inventoryApi.os(scope, offset, limit)` plus `use-table-pagination.ts` and the
`TablePagination` component. [VERIFIED: web/src/lib/services.ts:215-276; web/src/lib/use-table-pagination.ts]

#### AP-4: Drill-down endpoint precedent
**What:** the inventory routers already pair a summarized list endpoint with a per-key detail endpoint that takes
its own pagination. Use the same shape for topology detail expansion
(`GET /network/topology/resources/{resource_id}/details`) rather than inventing a new RPC style.
[VERIFIED: src/api/routers/network.py:169-231 for the analysis endpoints; src/api/dependencies.py:280-306 for the pagination dependency]

#### AP-5: Refresh nonce for client-side invalidation
**What:** the repository's existing idiom for forcing a re-fetch is a `refreshKey` `useState` counter included in
the dependency array, combined with `scopeKey = JSON.stringify(scope)` to avoid object-identity churn.
**When to use:** TOPO-04 policy round-trip. Extend `useApi` to return a `refetch` handle implemented with this
nonce rather than adding a data-fetching library.
[VERIFIED: web/src/hooks/useApi.ts:18-47 — the hook returns only `{ data, error, loading }` today]

#### AP-6: Web test doubles
**What:** `vi.hoisted` service mocks, as used in `web/src/app/connections/page.test.tsx`.
**When to use:** the new `web/src/app/network/page.test.tsx` (does not exist yet — Wave 0 gap).

### Anti-Patterns to Avoid

- **Filtering by node type alone to hit the payload budget.** Measured: 729.4 KB at 130 nodes. The `details`
  blob dominates the payload, not the node count. See §Scale Budgets.
- **Client-side level of detail.** The 78.7 MB enterprise payload is produced server-side; hiding elements in
  Cytoscape does not reduce transfer, parse, or memory cost.
- **Comparing ARM identifiers with `in` against mixed-case collections.** `_has_resource` does exactly this today
  and silently drops edges. Normalize at the model boundary instead of at each comparison.
- **Silently dropping data.** `topology.add()` discards unresolvable edges with no counter; `_bound()` truncates
  agent lists at 25 with no warning. Both must become counted-and-reported.
- **Duplicating the scope filter.** `_scoped_topology` is a second, buggy implementation of scoping. Delete it
  rather than fixing it.

## Verified Defect Map

Every row was confirmed by reading the cited source **this session**; rows marked ▶ were additionally reproduced
by executing the real code.

| # | Review ID | Location | Defect | Requirement |
|---|-----------|----------|--------|-------------|
| D-01 ▶ | CR-01 | `src/network/service.py:66-95` | `filter_snapshot()` rebuilds the snapshot with `replace()` listing **14** collections; `NetworkSnapshot` has **15**. `private_link_resources` is passed through unfiltered → out-of-scope resources leak. | TOPO-01 |
| D-02 ▶ | CR-02 | `src/network/service.py:264-271` | `scoped()` forwards `policy=` only; `semantic_relationships` is dropped entirely from the scoped service. | TOPO-01 |
| D-03 | *(new — not in review)* | `src/api/routers/network.py:431` | `preview_policy` constructs `NetworkIntelligenceService(service.snapshot, policy=policy)` — the **same** omission as D-02, at a second call site. A fix that only touches `scoped()` leaves policy preview broken. | TOPO-01 |
| D-04 | CR-06 | `src/network/service.py:313-333` | `_scoped_topology()` is dead code (its only caller `analyze(scope)` is never invoked with a scope) and carries three latent bugs. Delete rather than repair. | TOPO-01 |
| D-05 ▶ | CR-03 | `src/network/topology.py:559-635` | `_topology_resources()` never extends from `snapshot.private_link_resources`. They are counted in `counts.private_link_resources` but never projected → gaps and findings reference node ids that do not exist in the graph. | TOPO-02 |
| D-06 | CR-03 | `src/network/models.py:840-869` vs `src/network/topology.py:664-678` | `PrivateLinkResource.entity_type` is the literal `"PrivateLinkResource"`. The names `FabricCapacity` / `AIFoundryAccount` exist only in `_WORKLOAD_ENTITY_TYPE_BY_PROVIDER`. A provider→entity-type mapping step is therefore **mandatory**, not optional. | TOPO-02 |
| D-07 ▶ | CR-04/CR-05 | `src/network/topology.py:585,596,628` | Per-rule and per-route nodes are always emitted; there is no detail level. | TOPO-03 |
| D-08 ▶ | WR-01 | `src/network/models.py:161` | `Subnet.__post_init__` lowercases `resource_id` but **not** `private_endpoint_ids` → mixed-case comparisons fail. | TOPO-05 |
| D-09 | WR-05 | `src/network/topology.py:747-760` | `_has_resource()` uses an exact-case `in`; `add()` silently returns on miss with no counter. | TOPO-05 |
| D-10 | WR-06 | `src/network/topology.py:775-779` | `predicate_map` covers `{attachedto, loadbalances, hosts}` only — ontology `resolvesFor` edges are discarded. | TOPO-05 |
| D-11 | WR-08 | `web/src/app/network/page.tsx:73` | Flow-log banner text is hardcoded ("No flow logs assumed") regardless of observed data. | TOPO-05 |
| D-12 ▶ | WR-04 | `src/network/loader.py:530-578`; `src/api/runtime.py:538-546` | `load_network_snapshot(rows)` accepts **no** `observed_at`; `NetworkIntelligenceService.from_rows` has no `observed_at` kwarg (only `from_arg_rows` does); `_load_network_service()` discards `_freshness` that its sibling `_load_semantic_snapshot()` keeps. Result: `observed_at=''` → `classify_freshness('') == 'unknown'`. | TOPO-05 |
| D-13 | CR-?/WR-07 | `src/api/providers.py:93-107` | `refresh_interval_seconds = 30`; policy is bound at service construction, so a `PATCH /policy` leaves derived gaps stale for up to ~30 s. | TOPO-04 |
| D-14 | WR-02 | `web/src/hooks/useApi.ts:18-47` | Hook returns `{data, error, loading}` with no refetch handle → mutations cannot invalidate loaders. | TOPO-04 |
| D-15 | WR-03 | `web/src/app/network/page.tsx:104-106` | Metric cards render `.length` of the (server-capped) arrays instead of `summary.*_count` → the dashboard understates the estate. | TOPO-03 |
| D-16 | WR-10 | `web/src/app/network/page.tsx:570-583, 664-730` | `ANALYZER_RULES`/`BUILTIN_RULE_IDS` are a hardcoded mirror of the engine; custom rules are gated and forced to `parameters: {}`. `GET /policy` does not expose the engine's supported targets/operators. | TOPO-04 |
| D-17 | *(new — not in review)* | `src/operations/tools.py:52,79-85` | `_MAX_ITEMS = 25`; `_bound()` truncates agent-facing lists with **no** warning. At enterprise scale agents see 0.03 % of findings as if complete. | TOPO-03 |
| D-18 | WR-?; workspace | `web/src/components/network/TopologyWorkspace.tsx:32,57` | Badges/drawer key findings on `finding.control_id`; `RuleFinding` has **no** `resource_id` field. `:239` gates badges on `showFindings` but `:245` leaves the drawer ungated. | TOPO-03 |
| D-19 | WR-?; export | `web/src/components/network/TopologyGraph.tsx:399-403` | `exportJson` serializes the bare `topology` — no scope, evidence, freshness, or truncation metadata travels with the export. | TOPO-05 |
| D-20 | WR-?; drawer | `web/src/components/network/TopologyDetailDrawer.tsx:136-139` | Returns `null` when a selected node has no findings — the user gets no feedback that selection registered. | TOPO-03 |
| D-21 | WR-09 | `web/src/lib/network-graph.ts:398-455` | The `nodeIds` fold index is built once; unresolved nodes are appended without registration, so later lookups miss. | TOPO-03 |
| D-22 | *(deeper than WR-11)* | `src/network/service.py:250-253`; `src/network/tightening.py:868` | `rule_findings` calls `analyze_rules(self.snapshot)` with **no** `flow_observations`. Only tests ever pass them. `ObservedTrafficAnalyzer` further requires `attributes["dataSource"] == "traffic_analytics"`. Flow-log findings can never fire in production. | TOPO-05 |

### Executed reproduction (probe output, this session)

```
CR-01 leaked gaps: [('missing_private_endpoint', 'kv-finance-prod', 'sub-b')]   # scope was sub-a
CR-01 scoped private_link count: 2   (expected 1)
CR-02 unscoped semantic: 1 → scoped semantic: 0
CR-03 rendered nodes: VNets only; both private-link finding resource ids are orphaned
CR-03 counts.private_link_resources: 2   (counted, never projected)
WR-01 subnet.resource_id '/subs/rg/vneta/subnets/s1'  BUT private_endpoint_ids '/Subs/RG/PE1'
WR-04 observed_at derived from unstamped rows: ''  → classify_freshness('') == 'unknown'
IN-01 _topology_resources invocations per to_dict(): 2
```

## Scale Budgets

Measured this session by building synthetic estates with the real `build_topology` / `analyze` code paths and
serializing with `json.dumps`. These numbers are the phase's acceptance targets.

### Topology payload

| Estate (VNets / subnets each / NSGs × rules) | Full nodes | Full edges | Full payload | Build time | Summary (rule nodes dropped) | Summary **+ `details` stripped** |
|---|---|---|---|---|---|---|
| Small — 20 / 3 / 40 × 25 | 1,330 | 1,260 | 2.99 MB | 11 ms | 130 nodes / **729.4 KB** | 130 nodes / **151.3 KB** |
| Mid — 60 / 6 / 150 × 30 | 6,930 | 6,660 | 15.65 MB | 57 ms | 630 nodes / 3,782 KB | 630 nodes / **778 KB** |
| Enterprise — 200 / 8 / 600 × 40 | 34,600 | 33,600 | 78.70 MB | 646 ms | 2,600 nodes / 17,990 KB | 2,600 nodes / **3,311 KB** |

**Byte cost per node:** full 1,477 B · after dropping rule nodes **6,744 B** (survivors are NSG/route-table nodes
that embed `details.rules` / `details.routes`) · after stripping `details` **963 B**.

> **Correction to REC-3.** The review's criterion "<200 nodes and <250 KB at `detail=summary`" is **unachievable
> by dropping rule-level nodes alone** — that yields 729.4 KB. It is achieved (151.3 KB) only when the
> level-of-detail contract *also* omits embedded detail collections and serves them through drill-down. The
> planner must treat "lean node payload" as a first-class part of the LOD task, not a follow-up.

### Analysis volume and latency

| Estate | Gaps (time) | Rule findings (time) | Cold `analyze()` | UI shows at `limit=100` | Agent shows at `_MAX_ITEMS=25` |
|---|---|---|---|---|---|
| Mid | 870 (6 ms) | 13,500 (144 ms) | — | 0.74 % | 0.19 % |
| Enterprise | 3,800 | 72,000 | ≈ 840 ms | **0.14 %** | **0.03 %** |

Both presentations claim completeness today. This is the quantitative justification for TOPO-03's honesty
requirement and locked decision 3.

### Proposed gates for the planner

| Gate | Target | Measured on | Basis |
|---|---|---|---|
| G-1 | `detail=summary` ≤ 200 nodes and ≤ 250 KB on the small fixture | new perf test | 130 nodes / 151.3 KB achieved with `details` stripping |
| G-2 | `detail=summary` on the enterprise fixture emits `truncated: true` and a node cap; no response exceeds an explicit byte ceiling | new perf test | 2,600 nodes / 3.3 MB uncapped |
| G-3 | `/topology` p95 server build < 1 s at enterprise size | new perf test | 646 ms measured |
| G-4 | `detail=full` remains byte-identical to today for a fixed fixture (compatibility) | contract test | locked decision 6 |
| G-5 | Every capped collection carries `{total, returned, truncated}` and produces an envelope warning | contract test | AP-1/AP-2 |
| G-6 | Agent tool output states its bound when `_bound` truncates | `tests/test_operations_tools.py` | D-17 |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Telling the client a response is partial | A bespoke `partial: true` flag or a custom header | Emit `"truncated": true` inside the payload; `evidence._truncation_warnings()` produces the warning automatically | [VERIFIED: src/api/evidence.py:182-196] — already wired into `Envelope.to_dict` at `:136-153` |
| Offset/limit plumbing | New query params on each route | `Depends(get_pagination)` + `pagination.to_dict(total)` | [VERIFIED: src/api/dependencies.py:280-306] — yields `{offset, limit, total, next_offset}` |
| Paginated tables in the UI | A new pager component | `use-table-pagination.ts` + `TablePagination` + the `inventoryApi.os(scope, offset, limit)` call shape | [VERIFIED: web/src/lib/services.ts:215-276] |
| Freshness banding | A new age→label function | the existing `classify_freshness` used by the semantic snapshot loader | [VERIFIED: reproduced `classify_freshness('') == 'unknown'` by execution] |
| Validating custom rule bodies in the editor | Client-side rule schema | `rule_engine.validate_rule_parameters` server-side; expose `SUPPORTED_TARGETS` / `SUPPORTED_OPERATORS` additively from `GET /policy` so the editor cannot drift | [VERIFIED: src/network/rule_engine.py:74-109, 291-327] |
| Scope parsing | A second scope reader | `read_scope` / `_network_scope` | [VERIFIED: src/api/dependencies.py:264-277; src/api/routers/network.py:35-57] |
| Policy concurrency control | A new etag column | `NetworkDesignPolicyStore.update()` already writes `{"policy": …, "revision": rev+1}` with `expected_revision` | [VERIFIED: src/network/design.py:443-458] — note the in-memory fallback carries no revision, so an accessor must be added |
| Client cache invalidation | A data-fetching library (SWR/React Query) | `refreshKey` nonce in `useApi`'s dependency array | AP-5; adding a library would be a new dependency for a 6-line change |

**Key insight:** this codebase already solved every generic problem this phase touches. The failures are all
*omissions at a call site*, not missing capability. Plans that introduce new mechanisms are almost certainly
re-implementing something in the table above.

## Common Pitfalls

### P-1: Optimizing node count instead of payload bytes
**What goes wrong:** the team drops rule nodes, celebrates 130 nodes, and ships a 729 KB "summary".
**Why it happens:** node count is the visible metric; `details.rules` is invisible until you serialize.
**How to avoid:** make the LOD contract specify the *node payload shape*, not just which node types survive.
**Warning signs:** a perf test that asserts node count without asserting `len(json.dumps(payload))`.

### P-2: Assuming the frontend already styles the new node types
**What goes wrong:** private-link nodes render as unstyled/icon-less blobs after TOPO-02 lands.
**Why it happens:** the review states the frontend "already styles them". Half true: `FabricCapacity` and
`AIFoundryAccount` **are** in `WORKLOAD_ENTITY_TYPES` (`network-graph.ts:127-141`) so they render — but they have
**no** entries in `RESOURCE_ICONS` (`:87-122`) and there is **no** Fabric or AI-Services SVG in
`web/public/azure-icons/`. [VERIFIED: web/src/lib/network-graph.ts:87-141; directory listing of web/public/azure-icons]
**How to avoid:** make icon sourcing an explicit task with the README procedure, not an assumed freebie.

### P-3: Forgetting the second and third scope call sites
**What goes wrong:** `scoped()` is fixed, tests pass, and `preview_policy` (D-03) still leaks.
**How to avoid:** the isolation test must exercise `/policy/preview` as well as `/gaps`, `/rule-findings`, and `/topology`.

### P-4: Duplicate nodes when projecting private-link resources
**What goes wrong:** a PaaS resource already surfaced by `_attached_workload_nodes` is emitted a second time by the
new private-link projection, producing duplicate ids and confusing `_disambiguate_duplicate_names`
(`topology.py:634`).
**How to avoid:** project into the same de-duplicated resource map and reconcile on the (already lowercased)
`resource_id` before appending.

### P-5: Edge duplication when touching the load-balancer provenance branch
**What goes wrong:** `topology.py:878` guards LB edge synthesis on `if not topology.semantic_relationships`.
Once D-02 is fixed, scoped services *will* have semantic relationships, silently changing which branch runs.
**Why it happens:** the fix for one defect changes the input condition of an unrelated branch.
**How to avoid:** add a regression test asserting LB edge count for a scoped service **with** semantic
relationships, before changing `scoped()`.

### P-6: Casefolding increases edge counts and looks like a regression
**What goes wrong:** after D-08/D-09 are fixed, previously-dropped edges appear and existing snapshot assertions
fail.
**How to avoid:** treat increased edge counts as the *intended* correction; update fixtures deliberately and
record the delta in the plan so it is not mistaken for a bug.

### P-7: Fixing the flow-log banner without wiring the seam
**What goes wrong:** the banner becomes data-driven, reads "flow logs observed", and still produces zero
flow-based findings, because `analyze_rules` is never given observations (D-22).
**How to avoid:** TOPO-05 must include an explicit wiring path from ontology `trafficObserved` edges into
`NetworkIntelligenceService`, or the banner must state that observations are not yet analyzed.

### P-8: Changing the `/topology` default detail level in the same release
**What goes wrong:** agents (`operations/tools.py`) and the web export break simultaneously.
**How to avoid:** locked decision 6 — add `detail` as an opt-in parameter defaulting to today's behaviour, ship a
compatibility test, and flip the default in a later, announced change.

## Code Examples

All examples are **skeletons derived from the verified current source**; every literal value below appears in a
quoted verbatim block elsewhere in this document.

### E-1: Close the scope leak (TOPO-01, first tracer)

```python
# src/network/service.py:66-95 — add the omitted collection to the replace() call
return replace(
    snapshot,
    # ... existing 14 collections ...
    private_link_resources=_in_scope(snapshot.private_link_resources),
)

# src/network/service.py:264-271 — forward semantic relationships through scoping
def scoped(self, scope: NetworkScope) -> "NetworkIntelligenceService":
    return NetworkIntelligenceService(
        self.filter_snapshot(scope),
        policy=self._policy,
        semantic_relationships=_scope_relationships(self._semantic_relationships, scope),
    )

# src/api/routers/network.py:431 — the SAME omission at a second call site (D-03)
preview = NetworkIntelligenceService(
    service.snapshot,
    policy=policy,
    semantic_relationships=service.semantic_relationships,
)
```

Then delete `_scoped_topology` (`src/network/service.py:313-333`) — it is unreachable and duplicates the logic above.

### E-2: Thread observed-at and freshness (TOPO-05)

```python
# src/network/loader.py — accept an externally supplied stamp (currently absent)
def load_network_snapshot(rows, *, observed_at: str | None = None) -> NetworkSnapshot:
    ...
    resolved = observed_at or observed   # observed = max(observed, _observed_at(row))

# src/api/runtime.py:538-546 — stop discarding the freshness the sibling loader keeps
entities, relationships, freshness = _load_ontology_rows()
service = NetworkIntelligenceService.from_rows(rows, observed_at=freshness.observed_at)
```

### E-3: Project private-link resources with entity-type mapping (TOPO-02)

```python
# src/network/topology.py:559-635, inside _topology_resources()
for item in snapshot.private_link_resources:
    entity_type = _WORKLOAD_ENTITY_TYPE_BY_PROVIDER.get(_provider_of(item), item.entity_type)
    node = _resource_node(item, role="private_link")
    node["entity_type"] = entity_type      # PrivateLinkResource → FabricCapacity / AIFoundryAccount
    resources.setdefault(node["id"], node)  # setdefault avoids P-4 duplicates
```

`_resource_node(resource, *, role: str = "", details: dict | None = None)` is the existing constructor.
[VERIFIED: src/network/topology.py:492-509]

### E-4: Level-of-detail parameter (TOPO-03)

```python
# src/api/routers/network.py:82-95
@router.get("/topology")
def topology(
    detail: Literal["summary", "full"] = Query("full"),   # default preserves today's contract (P-8)
    ...
):
    payload = service.topology.to_dict(detail=detail)
```

At `detail="summary"` the projection must (a) omit per-rule/per-route nodes
(`topology.py:585, 596, 628`) **and** (b) omit embedded `details` collections from surviving nodes — both are
required to reach G-1.

### E-5: Real pagination + honest truncation (TOPO-03)

```python
# src/api/routers/network.py:169-199 — replace the bare slice
items = service.gaps
window = items[pagination.offset : pagination.offset + pagination.limit]
payload = {
    "gaps": [g.to_dict() for g in window],
    "coverage": {"total": len(items), "returned": len(window), "truncated": len(window) < len(items)},
    "pagination": pagination.to_dict(len(items)),
}
# no extra work: _truncation_warnings() emits the warning from "truncated": True
```

### E-6: Refetch handle (TOPO-04)

```ts
// web/src/hooks/useApi.ts — add a nonce; keep the existing return shape additive
const [nonce, setNonce] = useState(0);
const refetch = useCallback(() => setNonce((n) => n + 1), []);
useEffect(() => { /* existing body */ }, [...deps, nonce]);
return { data, error, loading, refetch };
```

The policy mutation handlers in `web/src/app/network/page.tsx:623-694` then call `refetch()` on the gaps and
rule-findings loaders instead of mutating local state only. Server-side, the 30 s provider cache (D-13,
`src/api/providers.py:93-107` `refresh_interval_seconds = 30`) must also be bypassed or invalidated on write, or
the refetch will return the pre-save analysis.

## Runtime State Inventory

This phase is not a rename, but it *does* change data that is cached or persisted outside the source tree, so the
inventory is included rather than skipped.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `NetworkDesignPolicyStore` documents `{"policy": …, "revision": N}` persisted via the configured store. [VERIFIED: src/network/design.py:443-458] | No migration — the policy document shape is unchanged. Add a **revision accessor** so the API can use it as an etag; note the in-memory fallback (`self._memory`) carries no revision. |
| Live service config | None. No externally-managed dashboards, workflows, or ACLs reference the topology contract. | None — verified by inspecting `src/mcp_server/app.py` (relay only, no network tools) and `src/operations/tools.py`. |
| OS-registered state | None. | None — no scheduled tasks or daemons reference network topology. |
| Secrets / env vars | None introduced or renamed. | None. |
| Build artifacts / caches | `ProviderRuntime` in-process cache with `refresh_interval_seconds = 30` serving the last completed refresh. [VERIFIED: src/api/providers.py:93-107] | **This is the real TOPO-04 blocker.** A policy write must invalidate or bypass this cache; a client-side refetch alone cannot fix it. |
| Downstream consumers of the payload shape | Agents (`src/operations/tools.py:373-392, 401, 430, 460`), digital-twin router (`src/api/routers/twin.py:33-44`), web export JSON (`TopologyGraph.tsx:399-403`). | Three contract consumers must be covered by the compatibility test in G-4 before any default changes. |

## Compatibility and Migration Strategy (topology detail levels)

Locked decision 6 requires additive-or-deprecated changes. Concretely:

1. **Add `detail` as an optional query parameter defaulting to `full`.** Today's callers are unchanged; G-4
   asserts byte-identical output for a fixed fixture.
2. **Add coverage/pagination blocks additively.** New keys (`coverage`, `pagination`) alongside existing keys;
   no existing key is removed or retyped. Web `types.ts` interfaces gain optional fields.
3. **Add drill-down before flipping anything.** `GET /network/topology/resources/{id}/details` must exist and be
   consumed by the drawer before `summary` becomes attractive to callers.
4. **Migrate consumers explicitly, in this order:** web page → export JSON → `operations/tools.py` agent tools →
   digital-twin router. Each gets a test asserting it requests the detail level it needs.
5. **Only then announce the default flip**, in a subsequent change, with the compatibility test updated in the
   same commit. Do not flip within this phase.
6. **MCP requires no separate work.** `src/mcp_server/app.py` exposes no network tools; MCP consumes topology
   solely through the REST endpoints above, so REST stability is sufficient.

## Dependency Order (recommended wave plan)

| Wave | Work | Rationale / gate |
|---|---|---|
| **0** | Create missing test scaffolding: `web/src/app/network/page.test.tsx`, `web/src/components/network/TopologyWorkspace.test.tsx`, a scale/perf test module, and enterprise-size fixtures. | Nothing below can be verified without these; §Validation Architecture lists them as gaps. |
| **1 (gate)** | D-01, D-02, **D-03**, D-04 — scope isolation across all call sites + failing-first cross-subscription regression test. | **Security gate.** Must be green before any wave below merges. Small, contract-neutral. |
| **2** | Correctness cluster: D-08 casing, D-09 dropped-edge counters, D-10 `resolvesfor` predicate, D-12 freshness threading. Touches the same files/tests as wave 1 — schedule immediately after, not in parallel. | Produces a snapshot worth projecting. Expect edge-count deltas (P-6). |
| **3** | D-05, D-06 — private-link projection + entity-type mapping + icon assets (P-2). | Depends on wave 1 (must not project leaked resources) and wave 2 (needs correct identifiers). |
| **4** | D-07, D-15, D-17, D-18..D-21 — LOD, lean node payload, pagination, truncation honesty, drill-down, export provenance, agent bound disclosure, compatibility window. | Depends on wave 3 so the new node types are included in the LOD contract from day one. Carries gates G-1..G-6. |
| **4′ (parallel from the start)** | D-13, D-14, D-16 — policy round-trip, `useApi` refetch, declarative rule editor surface. | Independent files (`providers.py`, `design.py`, `useApi.ts`, policy router/page). Can begin alongside wave 1. |

## Exact Files, Functions, and Tests

### Backend — files to change

| File | Function / line | Change |
|---|---|---|
| `src/network/service.py` | `filter_snapshot` `:66-95` | add `private_link_resources` to `replace()` |
| | `scoped` `:264-271` | forward scoped `semantic_relationships` |
| | `_scoped_topology` `:313-333` | delete (dead) |
| | `rule_findings` `:250-253` | accept/forward `flow_observations` (D-22 seam) |
| `src/api/routers/network.py` | `preview_policy` `:411-453` (esp. `:431`) | forward `semantic_relationships` |
| | `/topology` `:82-95` | add `detail` param |
| | `/gaps` `:169-199`, `/rule-findings` `:202-231` | real pagination + coverage + `truncated` |
| | `_policy_payload` `:246-291` | expose `supported_targets` / `supported_operators` additively |
| | new route | topology drill-down details |
| `src/network/topology.py` | `_topology_resources` `:559-635` | project private-link resources; honour detail level at `:585, :596, :628` |
| | `_has_resource`/`add` `:747-760` | casefold compare; count drops |
| | `predicate_map` `:775-779` | add `resolvesfor` |
| | LB branch `:878` | re-verify under scoped semantic relationships (P-5) |
| `src/network/models.py` | `Subnet.__post_init__` `:154-163` | lowercase `private_endpoint_ids` |
| `src/network/loader.py` | `load_network_snapshot` `:530-578` | `observed_at` parameter |
| `src/api/runtime.py` | `_load_network_service` `:538-546` | keep and pass `_freshness` |
| `src/api/providers.py` | `:93-107, 245-265` | invalidate on policy write |
| `src/network/design.py` | `:422-482` | revision accessor incl. in-memory fallback |
| `src/operations/tools.py` | `_bound` `:79-85`, `_MAX_ITEMS` `:52` | disclose truncation |

### Web — files to change

`web/src/hooks/useApi.ts` (refetch) · `web/src/lib/services.ts:840-911` (`networkApi` offset/limit) ·
`web/src/lib/types.ts:36-54, 1561-1695` (additive fields) · `web/src/app/network/page.tsx`
(`:26-29` loaders, `:73` banner, `:104-106` counts, `:570-583` rule mirror, `:608-739` policy workspace) ·
`web/src/components/network/TopologyWorkspace.tsx:14-60, 239-246` · `TopologyDetailDrawer.tsx:136-139` ·
`TopologyGraph.tsx:249-265, 399-403, 429-440` · `web/src/lib/network-graph.ts:87-141, 398-455` ·
`web/public/azure-icons/` (two new official SVGs).

### Tests

| Requirement | Test location | Kind |
|---|---|---|
| TOPO-01 | `tests/test_network_analysis.py::TestScopeIsolation` (new) + `tests/test_api_network.py` policy-preview case | failing-first regression |
| TOPO-02 | `tests/test_network_topology.py` (projection + entity-type mapping) ; `web/src/lib/network-graph.test.ts` (icon mapping) | unit |
| TOPO-03 | `tests/test_api_network.py` (detail/pagination/coverage/warnings, compatibility G-4) + new perf module (G-1..G-3) + new `web/src/app/network/page.test.tsx` | unit + perf + contract |
| TOPO-04 | `tests/test_api_network.py::TestPolicy` (invalidation, supported targets) + `web/src/app/network/page.test.tsx` (refetch after save) | unit |
| TOPO-05 | `tests/test_network_topology_links_regression.py` (casing, `resolvesfor`, dropped-edge counters) + new freshness cases + banner test | regression |

Existing helpers to reuse: `tests/test_api_network.py` `_client` factory, `tests/network_scenario.py`
`network_rows()`, and the `vi.hoisted` service-mock pattern from `web/src/app/connections/page.test.tsx`.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Backend framework | pytest (`pyproject.toml`: `testpaths=["tests"]`, `addopts="-q"`) |
| Backend config file | `pyproject.toml`; `tests/conftest.py` places `src/` on `sys.path` |
| Backend quick run | `.venv/bin/python -m pytest tests/test_network_analysis.py -q` |
| Backend full suite | `.venv/bin/python -m pytest -q` |
| Web framework | vitest + jsdom (`web/vitest.config.ts`, setup `src/test/setup.ts`, alias `@ → ./src`) |
| Web quick run | `cd web && npx vitest run src/lib/network-graph.test.ts` |
| Web full suite | `cd web && npx vitest run` |
| **Baseline (measured this session)** | `pytest tests/test_network_topology.py tests/test_network_analysis.py tests/test_api_network.py tests/test_network_topology_links_regression.py -q` → **123 passed**; `npx vitest run src/lib/network-graph.test.ts src/components/network/TopologyGraph.test.tsx src/lib/network-services.test.ts` → **73 passed (3 files)** |

> `python` is not on PATH in this environment; use `.venv/bin/python`.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOPO-01 | Scoped service exposes no out-of-scope resource, gap, finding, or relationship, at every call site incl. policy preview | unit | `.venv/bin/python -m pytest tests/test_network_analysis.py -k ScopeIsolation -x` | ❌ Wave 0 |
| TOPO-02 | Private-link resources appear as nodes with mapped entity types and icons | unit | `.venv/bin/python -m pytest tests/test_network_topology.py -x` ; `cd web && npx vitest run src/lib/network-graph.test.ts` | ✅ (extend) |
| TOPO-03 | `detail=summary` meets G-1; capped collections report `{total,returned,truncated}`; `detail=full` unchanged | unit + perf | `.venv/bin/python -m pytest tests/test_api_network.py -x` + new perf module | ❌ Wave 0 (perf) |
| TOPO-03 | Metric cards show summary counts, not array lengths; drawer/badges behave on selection | unit | `cd web && npx vitest run src/app/network/page.test.tsx` | ❌ Wave 0 |
| TOPO-04 | Saving policy changes derived gaps without reload; editor offers engine-supported targets | unit | `.venv/bin/python -m pytest tests/test_api_network.py -k Policy -x` ; `cd web && npx vitest run src/app/network/page.test.tsx` | ❌ Wave 0 (web) |
| TOPO-05 | Mixed-case ids link; `resolvesFor` edges survive; dropped edges are counted; unknown freshness renders as unknown | regression | `.venv/bin/python -m pytest tests/test_network_topology_links_regression.py -x` | ✅ (extend) |

### Sampling Rate

- **Per task commit:** the targeted quick-run command for the file touched.
- **Per wave merge:** `.venv/bin/python -m pytest -q` **and** `cd web && npx vitest run`.
- **Phase gate:** both full suites green, plus G-1..G-6, before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `web/src/app/network/page.test.tsx` — covers TOPO-03, TOPO-04 (does not exist)
- [ ] `web/src/components/network/TopologyWorkspace.test.tsx` — covers TOPO-03 badge/drawer behaviour (does not exist)
- [ ] Backend perf/scale test module + enterprise fixture — covers TOPO-03 gates G-1..G-3 (does not exist)
- [ ] `tests/test_network_analysis.py::TestScopeIsolation` — covers TOPO-01 (must fail on pre-fix code)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Scope is applied once, at the analysis boundary (`service.filter_snapshot`); remove the duplicate `_scoped_topology` path so there is a single enforcement point. |
| V2 Authentication | no | Unchanged by this phase. |
| V3 Session Management | no | Unchanged by this phase. |
| **V4 Access Control** | **yes — the phase gate** | The cross-subscription leak (D-01/D-02/D-03) is an authorization-boundary defect: a caller scoped to one subscription receives another subscription's ARM resource identifiers, names, and posture gaps. Control: complete `replace()` coverage, forward scoped relationships at *every* construction site, and a failing-first isolation test. |
| **V5 Input Validation** | yes | Custom rule bodies must be validated server-side by `validate_rule_parameters` (`rule_engine.py:291-327`). The engine is deliberately non-Turing-complete with no `eval` — preserve that property; the UI editor must not gain a client-only validation path. |
| V6 Cryptography | no | No cryptographic operations introduced. |
| V7 Error Handling & Logging | yes | New dropped-relationship and truncation diagnostics must not log out-of-scope ARM identifiers; log counts and predicates, not full ids. |
| V13 API | yes | Additive contract evolution with an explicit deprecation window (locked decision 6); pagination limits bounded by `Query(100, ge=1, le=500)`. |

Config: `security_enforcement: true`, ASVS level 1, `block_on: high`. [VERIFIED: .planning/config.json]

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant/subscription data disclosure through incomplete scope projection | Information Disclosure | Single enforcement point + exhaustive collection coverage + isolation regression test (wave 1 gate) |
| Resource exhaustion via unbounded topology payload (78.7 MB measured) | Denial of Service | LOD contract, node cap, bounded `limit` (`le=500`), explicit truncation |
| Silent data loss presented as complete results (0.14 % of findings shown as if total) | Tampering / integrity of reporting | `{total, returned, truncated}` coverage metadata + envelope warnings + agent-side bound disclosure |
| Rule-body injection through a custom-rule editor | Injection (V5) | Server-side `validate_rule_parameters`; declarative, no-`eval` engine |
| Misleading assurance from a hardcoded "no flow logs" banner | Repudiation / integrity | Data-derived banner **and** an honest statement about the unwired analyzer path (D-22) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Microsoft.Fabric/capacities` supports per-resource private endpoints (rather than only tenant-level Private Link). `PRIVATE_LINK_RESOURCE_TYPES` maps it to "Microsoft Fabric" and the `missing_private_endpoint` gap therefore fires on Fabric capacities. `[ASSUMED]` — no in-repo evidence beyond the type map; no external source reachable. | TOPO-02 | If tenant-level only, TOPO-02 makes an existing **false positive** far more visible. Needs `checkpoint:human-verify` before shipping the projection. |
| A2 | A practical interactive ceiling exists for Cytoscape + fCoSE somewhere below the measured 2,600-node summary. `[ASSUMED]` — the Context7 lookup for cytoscape performance guidance was planned but no provider was available. | TOPO-03 | An arbitrary node cap could be set too low (hiding needed detail) or too high (freezing the browser). Validate empirically in wave 0 with the enterprise fixture. |
| A3 | Flipping the `/topology` default `detail` within one release would break agents and export. `[ASSUMED]` on the release-cadence side; the breakage itself is `[VERIFIED]`. | Compatibility | If consumers are updated in lockstep, the deprecation window is unnecessary overhead — but locked decision 6 already mandates the conservative path. |
| A4 | Official Azure architecture icons exist for Microsoft Fabric and Azure AI Services in the V21 set referenced by the README. `[ASSUMED]` — not verified against the icon distribution. | TOPO-02 | If absent, the icon task needs an alternative that still respects the "official, unmodified" rule. |

## Open Questions

1. **Fabric private-link semantics (A1)**
   - What we know: the type map treats `microsoft.fabric/capacities` as a private-link resource and gaps fire on it.
   - What's unclear: whether per-resource private endpoints are the correct control for Fabric capacities.
   - Recommendation: `checkpoint:human-verify` in wave 3 before the projection makes these gaps prominent.
2. **Interactive node ceiling (A2)**
   - What we know: summary is 2,600 nodes / 3.3 MB at enterprise size; `LAYOUT_NODE_BUDGET = 100` only degrades layout quality, never element count.
   - What's unclear: the empirical frame-rate cliff.
   - Recommendation: measure in wave 0 against the enterprise fixture; set the cap from data, not intuition.
3. **Flow-observation wiring scope (D-22)**
   - What we know: `analyze_rules` never receives observations in production; `ObservedTrafficAnalyzer` requires `dataSource == "traffic_analytics"`.
   - What's unclear: whether wiring ontology `trafficObserved` edges is in scope here or belongs to a later phase.
   - Recommendation: minimum viable honesty in this phase (banner states observations are not analyzed) **plus** the service-level seam; full ingestion deferred per the out-of-scope list.
4. **Agent bound (`_MAX_ITEMS = 25`)**
   - What we know: agents see 0.03 % of enterprise findings with no warning.
   - What's unclear: whether the right fix is a larger bound, a summarized rollup, or disclosure only.
   - Recommendation: disclosure first (cheap, honest); bound tuning is a separate decision.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python venv (`.venv/bin/python`) | Backend tests | ✓ | 3.11 | — |
| pytest | Backend tests | ✓ | via venv | — |
| Node / npx | Web tests | ✓ | — | — |
| vitest + jsdom | Web tests | ✓ | per `web/package.json` | — |
| cytoscape / cytoscape-fcose | Graph rendering | ✓ | ^3.34.1 / ^2.2.0 | — |
| Brave/web search | External verification | ✗ | — | none — external claims tagged `[ASSUMED]` |
| Context7 MCP | Library docs | ✗ | — | none — see A2 |

**Missing dependencies with no fallback:** none that block implementation. The two missing *research* providers
constrain only external verification, which is why A1–A4 exist.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Return the whole graph and let the client cope | Server-side level of detail + drill-down + explicit coverage metadata | this phase | The only approach that survives the measured 78.7 MB enterprise payload |
| Truncate silently at a fixed limit | Truncate explicitly with `{total, returned, truncated}` and an auto-generated envelope warning | this phase (mechanism already exists) | Restores trust in every count the UI and agents display |
| Two scope implementations (`filter_snapshot` + `_scoped_topology`) | One enforcement point | this phase | Removes an entire class of access-control drift |

**Deprecated/outdated:**
- `NetworkIntelligenceService._scoped_topology` — unreachable dead code with latent bugs; delete it.
- The hardcoded `ANALYZER_RULES` / `BUILTIN_RULE_IDS` mirror in `page.tsx` — replace with engine-supplied lists.

## Sources

### Primary (HIGH confidence) — in-repo reads and executed code, this session

- `src/network/service.py` (full, 342 lines) — `filter_snapshot:66-95`, `scoped:264-271`, `rule_findings:250-253`, `_scoped_topology:313-333`
- `src/network/topology.py:100-260, 488-509, 540-910` — projection, `_resource_node`, `_has_resource`/`add`, `predicate_map`, LB branch, `_WORKLOAD_ENTITY_TYPE_BY_PROVIDER:664-678`
- `src/network/models.py:47-62, 154-163, 840-869, 872-940` — private-link type map, `Subnet.__post_init__`, `PrivateLinkResource`, `NetworkSnapshot` (15 collections) + `counts()`
- `src/network/loader.py:190-300, 530-578` — private-link row collection, `_observed_at`, `load_network_snapshot`
- `src/network/gaps.py`, `src/network/tightening.py:51-85, 651, 868-889`, `src/network/rule_engine.py:74-109, 291-327`, `src/network/design.py:422-482`
- `src/api/routers/network.py` (full, 453 lines), `src/api/evidence.py` (full, 197 lines), `src/api/dependencies.py:250-320`, `src/api/runtime.py:505-560`, `src/api/providers.py:93-300`, `src/api/routers/twin.py:25-45`, `src/api/routers/context.py:80-84`
- `src/operations/tools.py:52, 79-85, 360-475`; `src/mcp_server/app.py` (relay, no network tools); `src/onboarding/graph_normalize.py:735-770`
- `web/src/hooks/useApi.ts`; `web/src/lib/services.ts:215-276, 840-911`; `web/src/lib/types.ts:36-54, 1561-1695`; `web/src/lib/network-graph.ts:60-200, 280-455`; `web/src/lib/use-table-pagination.ts`; `web/src/app/network/page.tsx`; `web/src/components/network/{TopologyWorkspace,TopologyGraph,TopologyDetailDrawer}.tsx`; `web/public/azure-icons/README.md`; `web/vitest.config.ts`
- **Executed probes** (throwaway, outside the repo — the repository was not modified): `/tmp/topo_probe.py` (reproduces D-01, D-02, D-05, D-08, D-12), `/tmp/topo_scale.py`, `/tmp/topo_lod.py`, `/tmp/topo_bd.py`, `/tmp/topo_perf.py`
- **Baseline test runs:** 123 pytest passed; 73 vitest passed (3 files)

### Secondary (MEDIUM confidence)

- `.planning/phases/12-network-topology-integrity-and-scale/12-REVIEW.md` — 6 critical, 11 warnings, 3 info, REC-1..5. Every claim used here was independently re-verified; two were corrected (REC-3 payload target, "frontend already styles them").

### Tertiary (LOW confidence)

- None. The `research-plan` seam selected providers `websearch` and `context7`; **neither MCP tool was available**
  and `gsd-tools query websearch` returned `{"available": false, "reason": "BRAVE_API_KEY not set"}`. No external
  sources were consulted, so nothing in this document is attributed to one. Untestable external claims are
  confined to the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Defect map: **HIGH** — every entry read at line level; five reproduced by executing the shipped code.
- Scale budgets: **HIGH** — measured against real code paths at three estate sizes this session.
- Standard stack: **HIGH** — no new dependencies; all reuse targets read directly.
- Architecture patterns: **HIGH** — every pattern cited to an existing in-repo implementation.
- External Azure semantics (Fabric private link), Cytoscape ceiling: **LOW** — no provider reachable; see A1/A2.

**Research date:** 2025-06-09
**Valid until:** 30 days (in-repo findings are stable; re-verify line numbers if `src/network/` changes)

## RESEARCH COMPLETE
