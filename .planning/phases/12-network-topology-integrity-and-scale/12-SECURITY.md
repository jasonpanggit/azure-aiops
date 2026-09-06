---
phase: 12
slug: network-topology-integrity-and-scale
status: secured
threats_open: 0
asvs_level: 1
block_on: high
reviewed_head: 96e812578de28e9c128854cabb7d7e7ee9123c11
created: 2026-09-06
---

# Phase 12 — Security Threat-Mitigation Audit

**Verdict:** SECURED  
**Reviewed HEAD:** `96e812578de28e9c128854cabb7d7e7ee9123c11`  
**Register:** 67 unique plan-time threats (`T-12-01` through `T-12-66`, plus shared `T-12-SC`)  
**Result:** 67 closed, 0 open, 0 blocking at the configured `high` threshold

The audit verified the complete plan-time register against the current tree after
all fixes recorded in `12-REVIEW-FIX.md`. It did not infer closure from plan or
summary claims alone: current implementation paths were inspected and the
targeted backend, frontend, contract, scale, scope, concurrency, and static
security checks below were rerun at the reviewed HEAD.

## Inputs Reviewed

- All eleven `12-01-PLAN.md` through `12-11-PLAN.md` threat registers.
- All eleven corresponding `12-*-SUMMARY.md` completion records.
- `12-CONTEXT.md`, `12-RESEARCH.md`, `12-UI-SPEC.md`,
  `12-VALIDATION.md`, and `12-PRE-PHASE-BASELINE.json`.
- The final clean `12-REVIEW.md` and consolidated all-fixed
  `12-REVIEW-FIX.md`.
- `12-FABRIC-PRIVATE-LINK-DECISION.md` and its cited current Microsoft Learn
  guidance.
- Current Phase 12 production source, frontend source, tests, icon inventory,
  manifest diff, and Git history.

The mandatory Markdown read covered 29 artifacts and 614,397 characters. The
baseline artifact was separately parsed and its pinned base commit, fixture,
allowed additions, endpoint bodies, suite counts, and canvas measurement were
checked by the passing fail-closed baseline and downstream-contract tests.

## Trust Boundaries

| Boundary | Security property verified |
|---|---|
| Authenticated API scope → network engine | `ReadScope` is converted once to `NetworkScope`; every route resolves a scoped service before topology, gaps, findings, summaries, previews, or drill-down. |
| Scoped snapshot → derived topology and analysis | All 15 resource collections, semantic relationships, and flow observations are filtered before derivation; relationship endpoints must both survive scope. |
| Operator JSON → policy engine | The client parses syntax only. The server validates a fixed declarative target/operator vocabulary and never evaluates executable expressions. |
| Persisted policy → provider cache | Strict document/revision decoding fails closed; revision is part of the provider cache key; failed refresh retains a visibly degraded last-good provider under bounded retry. |
| Concurrent writer → policy document | In-process locking, expected-revision checks, remote ETag `If-Match`, create-if-absent, and local inter-process lock plus atomic replacement prevent lost updates. |
| Service payload → browser canvas | Summary serialization is node- and byte-bounded; all bounded collections expose totals, returned counts, and truncation; full detail requires confirmation above the measured ceiling. |
| Service payload → agents/MCP/twin | Scope is inherited and nested list results are recursively capped at 25 with explicit disclosure of true totals. |
| Bounded/partial data → operator | Loading, unavailable, partial, withheld, unknown, and confirmed-clean states are distinct and accessible; no absent data is silently represented as zero or clean. |
| Ingestion evidence → freshness/provenance | Observation timestamps are validated as timezone-aware, normalized to UTC, and left unknown when invalid; flow provenance distinguishes not ingested, ingested-not-analyzed, and analyzed. |
| Topology state → exported artifact | JSON exports always include scope, detail, coverage, badge exhaustion, node/relationship counts, filters, evidence, warnings, knowledge version, freshness, and real export time. |
| External icon source → topology UI | The repository pins an unmodified official Azure icon set, records its source, maps AI Services, and deliberately provides no misleading Fabric substitute. |

## Verification Suites

The table uses these run identifiers:

- **B295** — 12 backend modules covering scope, APIs, provider refresh,
  persistence CAS, scale, baseline, downstream contracts, topology, and agent
  bounds: **295 passed**.
- **B101** — rule-engine, flow, ontology, and model modules: **101 passed**.
- **W169** — seven Network-page Vitest files: **7 files / 169 tests passed**.
- **S1** — dynamic execution, debug/secret, dependency-manifest, icon, and
  identifier-bearing logging scans: **passed**.
- **D1** — official Microsoft Learn checks for Azure icon usage, Fabric
  tenant/workspace private-link semantics, and Foundry Tools per-resource
  private endpoints: **confirmed current on 2026-09-06**.

## Threat Register

| Threat ID | Category | Severity | Disposition | Current mitigation evidence | Verification | Status |
|---|---|---:|---|---|---|---|
| T-12-01 | Information Disclosure | critical | mitigate | `NetworkScope.filter_snapshot()` filters `private_link_resources` with the same predicate as all 14 other collections (`src/network/service.py:66-100`). | B295; `test_network_analysis.py:170` | closed |
| T-12-02 | Information Disclosure | high | mitigate | `_scope_relationships()` keeps an edge only when both case-folded endpoints survive the scoped snapshot (`src/network/service.py:190-204,391-424`). | B295; downstream scope tests | closed |
| T-12-03 | Information Disclosure | high | mitigate | Policy preview starts from `_service(context, scope)` and forwards only that service's snapshot, relationships, observations, and peer resolutions (`src/api/routers/network.py:582-609`). | B295; API scope/preview tests | closed |
| T-12-04 | Elevation of Privilege | high | mitigate | `_service()` is the single route boundary; `_scoped_topology` is absent from production and explicitly asserted absent (`src/api/routers/network.py:45-66`; `tests/test_api_network.py:1229`). | B295; static symbol search | closed |
| T-12-05 | Tampering | high | mitigate | Scope filtering applies symmetrically to endpoints and candidate targets before `NetworkGapAnalyzer` derives protection (`src/network/service.py:66-100`; `src/network/gaps.py:377-430`). | B295; scope-isolation analysis tests | closed |
| T-12-06 | Information Disclosure | medium | mitigate | Scope/drop diagnostics expose counts and predicate/type names, not ARM IDs; logging AST scan found no identifier-bearing logger call in the 17 Phase 12 Python production files. | B295; S1 | closed |
| T-12-07 | Tampering | medium | mitigate | Scale builders use real model constructors, whose `__post_init__` methods normalize ARM IDs (`src/network/models.py:107-133` and related models). | B295; `test_network_scale.py:122` | closed |
| T-12-08 | Denial of Service | low | mitigate | Enterprise fixtures are invoked only by explicit scale tests and measured against latency/payload gates. | B295; `test_network_scale.py` | closed |
| T-12-09 | Information Disclosure | low | accept | Fixture identifiers are deterministic synthetic index-derived values; no tenant data is embedded. | B295; fixture inspection | closed — accepted |
| T-12-10 | Repudiation | critical | mitigate | The baseline records detached base commit `d57f6137d747c344c56028d7e6211811927d0b43`; `load_baseline()` rejects missing/invalid artifacts. | B295; `test_network_prephase_baseline.py:22,137,157` | closed |
| T-12-11 | Repudiation | high | mitigate | G-4 strips only an explicit allowed-additions list and rejects unregistered nodes before byte/body comparison. | B295; `test_network_downstream_contracts.py:409` | closed |
| T-12-12 | Denial of Service | medium | mitigate | The measured browser guard is shared as `FULL_DETAIL_GUARD_NODES = 1_500`, and full detail above it requires a second explicit action (`TopologyWorkspace.tsx:35,457-470`). | W169; `TopologyWorkspace.test.tsx:165-183` | closed |
| T-12-13 | Tampering | high | mitigate | `flow_log_provenance` has exactly `not_ingested`, `ingested_not_analyzed`, and `analyzed` paths based on actual evidence/analysis inputs (`src/network/service.py:344-370`). | B101/B295; `test_network_topology_links_regression.py:439-480` | closed |
| T-12-14 | Tampering | medium | mitigate | Parentless DNS links are skipped; only a bounded count/reason is warned (`src/onboarding/graph_normalize.py:768-782`). | B295; `test_network_topology_links_regression.py:409-436` | closed |
| T-12-15 | Spoofing | medium | mitigate | Model construction and relationship membership case-fold ARM IDs (`src/network/models.py:107-133`; `src/network/topology.py:1465-1501`). | B295/W169; mixed-case relationship tests | closed |
| T-12-16 | Tampering | high | mitigate | Network provider cache key contains the strict policy revision; writes advance and immediately cache the revision (`src/api/runtime.py:2258-2271`; `src/network/design.py:519-547`). | B295; policy invalidation tests | closed |
| T-12-17 | Injection | high | mitigate | Rules use allowlisted targets/operators and structural comparisons only (`src/network/rule_engine.py:281-424`); AST/static scans found no dynamic execution primitive. | B101/B295; S1 | closed |
| T-12-18 | Denial of Service | medium | mitigate | `useApi` coalesces refetches for 400 ms and retains prior data when dependencies are unchanged (`web/src/hooks/useApi.ts:11-83`); server caches remain in place. | W169; `useApi.test.ts:23-107` | closed |
| T-12-19 | Tampering | medium | mitigate | Store update checks expected revision; OneLake uses ETag `If-Match`/create-if-absent and local inter-process lock plus atomic replace (`src/network/design.py:519-547`; `src/storage/onelake_documents.py:193-282`). | B295; `test_onelake_documents.py:35,215`; `test_api_network.py:840-846` | closed |
| T-12-20 | Information Disclosure | low | accept | Validation reasons are fixed structural messages derived from the submitted body and supported vocabulary; persisted corruption maps to generic `provider_unavailable`. | B101/B295; corrupt/invalid policy tests | closed — accepted |
| T-12-21 | Tampering | high | mitigate | The decision artifact confirms Fabric private-link is tenant/workspace scoped, so per-capacity missing-endpoint findings are suppressed (`src/network/gaps.py:394-399`). | B295; D1 | closed |
| T-12-22 | Repudiation | medium | mitigate | Fabric nodes carry explicit tenant/workspace qualification and the phase exposes no provisioning endpoint (`src/network/topology.py:1354-1363`). | B295/W169; D1 | closed |
| T-12-23 | Spoofing | low | mitigate | Decision artifact requires an icon-less Fabric tile; no `fabric.svg` or borrowed Service Fabric glyph exists. | W169; S1; D1 | closed |
| T-12-24 | Information Disclosure | critical | mitigate | Private-link projection consumes only `snapshot.private_link_resources` after route-level scoping and uses no unscoped side channel (`src/network/topology.py:1284-1293`). | B295; `test_network_topology.py:527` and downstream scope tests | closed |
| T-12-25 | Spoofing | medium | mitigate | `ai-services.svg` is documented as unmodified Azure Public Service Icons V21, SHA-256 `7f1d2831085f00103df5f6fd6305bdbbbe4c4530e98831d7ce6508d236c467c2`; Fabric remains icon-less. | W169; S1; D1; icon commit `52617d99` | closed |
| T-12-26 | Tampering | medium | mitigate | Resource projection is keyed by case-folded ID, with authoritative private-link candidates replacing placeholders (`src/network/topology.py:1284-1293`; `web/src/lib/network-graph.ts:444-461`). | B295/W169 | closed |
| T-12-27 | Denial of Service | medium | mitigate | Private-link growth is included in `projected_full_node_count` and the measured summary/full-detail limits. | B295/W169; scale and graph tests | closed |
| T-12-28 | Tampering | high | mitigate | Current server behavior applies the decision verbatim: suppress Fabric per-capacity gaps, preserve Cognitive Services gaps, and publish scope qualification. | B295/W169; D1 | closed |
| T-12-29 | Denial of Service | high | mitigate | Summary uses caps of 1,500 nodes, 250 KB for small estates, and 2 MB otherwise, with binary-fit serialization over the complete envelope (`src/network/topology.py:59-62,493-590`). | B295; `test_network_scale.py:216-389` | closed |
| T-12-30 | Elevation of Privilege | critical | mitigate | Drill-down resolves only against `_service(context, scope).snapshot`; an out-of-scope ID returns no items (`src/api/routers/network.py:112-205`). | B295; `test_api_network.py:246` | closed |
| T-12-31 | Tampering | high | mitigate | Topology, gap, finding, agent, and export paths expose total/returned/truncated state; nested agent collections are recursively bounded with disclosure (`src/network/topology.py:419-472`; `src/operations/tools.py:79-121`). | B295/W169; G-5/G-6 tests | closed |
| T-12-32 | Denial of Service | medium | mitigate | Shared API `Page.limit` remains constrained to 1..500 (`src/api/dependencies.py:307`). | B295; paging tests | closed |
| T-12-33 | Tampering | high | mitigate | `NetworkTopology.to_dict()` still defaults to `full`; G-4 pins exact bytes and SHA for the default path (`src/network/topology.py:300-306`; `tests/test_network_scale.py:198-213`). | B295 | closed |
| T-12-34 | Repudiation | medium | mitigate | Rule findings include case-folded `affected_resource_ids` derived from protected resources (`src/network/tightening.py:898-930`). | B295/W169 | closed |
| T-12-35 | Tampering | high | mitigate | Page metric cards consume server summary totals; unavailable totals render an unknown placeholder, while partial lists disclose both returned and total (`web/src/app/network/page.tsx:268-280`). | W169; `page.test.tsx:195-245` | closed |
| T-12-36 | Repudiation | high | mitigate | Each failed loader renders a named retry targeting only its own refetch; asynchronous critical errors use alerts. | W169; `page.test.tsx` loader-recovery tests | closed |
| T-12-37 | Injection | high | mitigate | Client accepts only syntactically valid JSON and forwards every well-formed value to server-only semantic validation; no client rule schema can bypass the engine (`page.tsx:938-1102`). | W169; `page.test.tsx:670-800`; B101/B295 | closed |
| T-12-38 | Denial of Service | medium | mitigate | Successful policy changes call one 400 ms-coalesced refetch path; failures do not trigger derived reloads (`page.tsx:128-174`; `useApi.ts:28-38`). | W169 | closed |
| T-12-39 | Repudiation | high | mitigate | Flow provenance is three-state and the workspace always renders either a validated timestamp sentence or explicit unknown (`TopologyWorkspace.tsx:533-545`). | B101/B295/W169 | closed |
| T-12-40 | Tampering | medium | mitigate | Phase-range hygiene test asserts `web/src/lib/format.ts` is unchanged; Network uses a local presentation guard. | B295; `test_network_downstream_contracts.py:689` | closed |
| T-12-41 | Tampering | high | mitigate | Badge fetch is capped at four 500-item pages and publishes mapped/total/truncated coverage (`TopologyWorkspace.tsx:35-37,180-202,761-769`). | W169; `TopologyWorkspace.test.tsx:421-454` | closed |
| T-12-42 | Repudiation | high | mitigate | Badge and drawer maps fan findings to both control and affected IDs case-insensitively, with role-specific text (`TopologyWorkspace.tsx:72-148`; `TopologyDetailDrawer.tsx:258-375`). | W169 | closed |
| T-12-43 | Denial of Service | high | mitigate | A full-detail request above 1,500 projected nodes is blocked until `Load full detail` is pressed (`TopologyWorkspace.tsx:457-470,742-758`). | W169; guard tests | closed |
| T-12-44 | Repudiation | medium | mitigate | Partial topology, badge coverage, reductions, peer resolution, selection changes, and freshness have `role=status`/DOM text equivalents (`TopologyWorkspace.tsx:701-868`). | W169 | closed |
| T-12-45 | Tampering | high | mitigate | Missing peer-resolution data defaults to `unknown`, never `not_ingested`; server emits only the explicit four-state vocabulary (`network-graph.ts:330-372`; `service.py:391-424`). | B295/W169 | closed |
| T-12-46 | Tampering | medium | mitigate | Every inserted unresolved node is immediately registered in the folded-ID index, preventing case-variant duplicates (`web/src/lib/network-graph.ts:343-372,444-490`). | W169; `network-graph.test.ts:157-198` | closed |
| T-12-47 | Information Disclosure | medium | mitigate | `showFindings` controls only canvas badge input; drawer findings always receive the complete loaded mapping (`TopologyWorkspace.tsx:680-817`). | W169; `TopologyWorkspace.test.tsx:295` | closed |
| T-12-48 | Repudiation | high | mitigate | Drawer findings render explicit error, loading, incomplete, confirmed-clean, or findings-present states and never silently return nothing (`TopologyDetailDrawer.tsx:258-375`). | W169; drawer tests `84-191` | closed |
| T-12-49 | Repudiation | critical | mitigate | Incomplete/withheld findings explicitly state “not confirmed clean”; summary-hidden endpoint targets are distinguished from scope exclusion (`TopologyDetailDrawer.tsx:286-328,742-784`). | W169; drawer tests `109,578` | closed |
| T-12-50 | Tampering | high | mitigate | Peer wording is driven by the server resolution enum; legacy absence renders undetermined/unknown rather than outside-scope. | B295/W169; drawer test `191` | closed |
| T-12-51 | Information Disclosure | critical | mitigate | The drill-down API returns uniform empty data for out-of-scope/unknown IDs, avoiding both disclosure and an existence oracle; the UI renders no protected facts (`router/network.py:112-205`). | B295; `test_api_network.py:246` | closed |
| T-12-52 | Repudiation | high | mitigate | JSON export unconditionally emits the ten-part provenance contract, including badge-fetch exhaustion and node/relationship/dropped counts (`TopologyGraph.tsx:300-377`). | W169; `TopologyGraph.test.tsx:178-284` | closed |
| T-12-53 | Tampering | medium | mitigate | Export filenames use UTC seconds plus a collision sequence while `exported_at` retains the real clock instant (`TopologyGraph.tsx:379-412`). | W169; `TopologyGraph.test.tsx:286` | closed |
| T-12-54 | Repudiation | medium | mitigate | Selection is cleared when filtering, scope, detail, or refreshed topology invalidates the selected node, with an accessible status announcement. | W169; `TopologyWorkspace.test.tsx:496-584` | closed |
| T-12-55 | Denial of Service | high | mitigate | Default route bodies remain byte-identical to the frozen baseline after enumerated additions, protecting agent/twin/MCP consumers. | B295; G-4 downstream contract tests | closed |
| T-12-56 | Information Disclosure | critical | mitigate | Final scope tracer covers API, direct service, agent tools, twin, and MCP relay after every Phase 12 change. | B295; `test_network_downstream_scope.py` | closed |
| T-12-57 | Denial of Service | high | mitigate | G-1/G-2/G-3/G-6 execute against measured small/enterprise/agent fixtures, including dense 4,950-edge serialization. | B295; scale/downstream tests | closed |
| T-12-58 | Repudiation | medium | mitigate | Validation and summary records reconcile pre-phase and post-fix counts; no tests are silently removed, and current targeted collections pass. | B295/B101/W169; `12-VALIDATION.md` | closed |
| T-12-59 | Repudiation | medium | mitigate | Tests require explicit zero/false coverage and truncation states; UI omits neither incomplete nor confirmed-complete state. | B295/W169; G-5 and workspace/drawer tests | closed |
| T-12-60 | Repudiation | high | mitigate | `load_baseline()` raises named missing/invalid errors rather than returning defaults (`tests/network_baseline.py:195-218`). | B295; baseline fail-closed tests | closed |
| T-12-61 | Repudiation | high | mitigate | Contract tests bind G-1 to small, G-2/G-3 to enterprise, and G-6 to the agent surface using production constants (`test_network_downstream_contracts.py:280-330,617`). | B295 | closed |
| T-12-62 | Repudiation | high | mitigate | Hygiene resolves and validates the full baseline SHA, rejects an empty range, then diffs `phase_base_commit..HEAD` (`test_network_downstream_contracts.py:332-357`). | B295 | closed |
| T-12-63 | Repudiation | medium | mitigate | A39 was executed at 360 px with 322/322 width and no overflow; evidence is retained in `12-11-A39-360px.png` and closure artifacts. | `12-11-SUMMARY.md`; `12-VALIDATION.md` | closed |
| T-12-64 | Information Disclosure | high | mitigate | Dropped-edge payloads contain relationship-type counters only; warning text names type/count and never endpoint IDs (`src/network/topology.py:1465-1501`). | B295; `test_network_topology_links_regression.py:347-365`; S1 | closed |
| T-12-65 | Information Disclosure | high | mitigate | Scoped peer resolution emits only an already-visible peer ID and four-state selector, never properties from the filtered VNet (`src/network/service.py:391-424`). | B295; peer scope tests | closed |
| T-12-66 | Repudiation | medium | mitigate | Loader parses only timezone-aware timestamps, normalizes UTC, and leaves malformed/naive values unknown; route evidence uses snapshot `observed_at` (`loader.py:583-600`; `router/network.py:73-89`). | B295/B101; freshness tests | closed |
| T-12-SC | Tampering | low | accept | No dependency manifest changed in the phase range; the only added external artifact is the pinned static official SVG, and no package install was introduced. | S1; A37 contract test | closed — accepted |

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---|---|---|---|---|
| AR-12-01 | T-12-09 | Synthetic fixture IDs intentionally resemble ARM paths but are deterministic and contain no real tenant/subscription GUIDs. | Phase 12 plan authority | 2026-09-06 |
| AR-12-02 | T-12-20 | Operator-visible validation reasons describe only submitted declarative fields and the public supported vocabulary; internal persisted-state errors are replaced by a generic provider-unavailable response. | Phase 12 plan authority | 2026-09-06 |
| AR-12-03 | T-12-SC | Phase 12 adds no package dependency. Official icon files are static repository assets governed by the recorded Microsoft terms and source policy. | Phase 12 plan authority | 2026-09-06 |

No additional risk was accepted during this audit.

## Residual Non-Blocking Characteristics

- A PNG export is intentionally image-only and explicitly warns that it lacks
  scope/freshness metadata; JSON is the auditable export.
- An unknown and an out-of-scope drill-down ID intentionally receive the same
  empty response, preventing a resource-existence oracle.
- During a newer policy-body outage, requests intentionally receive the
  last-good provider while health reports `degraded`, `cache_key_stale`, retry
  count, and next retry time.
- Local policy persistence is suitable for a single-process development
  fallback; deployed replicas use OneLake ETag compare-and-swap.

## Exact Commands and Results

### Backend security, scope, policy, scale, and contract suite

```bash
.venv/bin/python -m pytest -o addopts='' \
  tests/test_network_analysis.py \
  tests/test_network_downstream_scope.py \
  tests/test_network_topology_links_regression.py \
  tests/test_api_network.py \
  tests/test_api_providers.py \
  tests/test_api_runtime.py \
  tests/test_onelake_documents.py \
  tests/test_network_scale.py \
  tests/test_network_prephase_baseline.py \
  tests/test_network_downstream_contracts.py \
  tests/test_network_topology.py \
  tests/test_operations_tools.py -q
```

Result: **295 passed**, 9 deprecation warnings, exit 0, 25.32 s.

### Declarative-rule and provenance suite

```bash
.venv/bin/python -m pytest -o addopts='' \
  tests/test_network_rule_engine.py \
  tests/test_network_flow.py \
  tests/test_network_ontology.py \
  tests/test_network_models.py -q
```

Result: **101 passed**, exit 0, 0.49 s.

### Frontend incomplete-state, drill-down, bounds, and export suite

```bash
cd web && npx --no-install vitest run \
  src/app/network/page.test.tsx \
  src/components/network/TopologyWorkspace.test.tsx \
  src/components/network/TopologyDetailDrawer.test.tsx \
  src/components/network/TopologyGraph.test.tsx \
  src/hooks/useApi.test.ts \
  src/lib/network-graph.test.ts \
  src/lib/network-services.test.ts
```

Result: **7 files passed, 169 tests passed**, exit 0, 6.68 s. Vitest emitted
the existing Vite CJS deprecation notice and five non-failing Cytoscape
missing-data mapping warnings.

### Static security and provenance checks

```bash
# Python AST scan over the 17 Phase 12 production Python files for calls to:
# eval, exec, compile, and __import__
```

Result: **no dynamic-execution calls**, exit 0.

```bash
rg -n --glob '*.ts' --glob '*.tsx' \
  '(^|[^[:alnum:]_.])(eval|Function)\s*\(' \
  web/src/app/network web/src/components/network web/src/hooks/useApi.ts \
  web/src/lib/network-graph.ts web/src/lib/services.ts
```

Result: **no matches**, expected `rg` status 1, interpreted as pass. An initial
broader expression matched JavaScript regex method
`/subscriptions/.../.exec(resourceId)`; review confirmed this was not dynamic
execution and replaced the check with the qualified scan above.

```bash
# Python AST scan of logger calls in the 17 Phase 12 production Python files
# for resource_id, subscription_id, vnet_id, endpoint_id, or zone_id arguments
```

Result: **35 logger calls inspected; no identifier-bearing logger call**, exit
0.

```bash
rg -n --glob '*.py' --glob '*.ts' --glob '*.tsx' \
  '(print\(|console\.(log|debug)|debugger;|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16})' \
  src/network src/api/providers.py src/api/routers/network.py src/api/runtime.py \
  src/onboarding/graph_normalize.py src/operations/tools.py \
  src/storage/onelake_documents.py web/src/app/network \
  web/src/components/network web/src/hooks/useApi.ts \
  web/src/lib/network-graph.ts web/src/lib/services.ts
```

Result: **no matches**, expected `rg` status 1, interpreted as pass.

```bash
git diff --name-only d57f6137d747c344c56028d7e6211811927d0b43..HEAD \
  -- package.json web/package.json pyproject.toml uv.lock \
  package-lock.json web/package-lock.json Cargo.toml
```

Result: **empty output**; no dependency manifest changed.

```bash
test -f web/public/azure-icons/ai-services.svg
test ! -e web/public/azure-icons/fabric.svg
grep -q 'Public Service Icons, V21' web/public/azure-icons/README.md
grep -q 'unmodified' web/public/azure-icons/README.md
shasum -a 256 web/public/azure-icons/ai-services.svg
```

Result: all assertions passed; SHA-256
`7f1d2831085f00103df5f6fd6305bdbbbe4c4530e98831d7ce6508d236c467c2`.

Official Microsoft Learn was rechecked on 2026-09-06:

- Azure Architecture Center provides the official icon archive and forbids
  cropping, flipping, rotation, distortion, or repurposing.
- Fabric documents tenant-level and workspace-level private links.
- Foundry Tools documents private endpoints for the individual account
  resource.

## Security Audit Trail

| Audit Date | Reviewed HEAD | Threats Total | Closed | Open | Blocking Open | Run By |
|---|---|---:|---:|---:|---:|---|
| 2026-09-06 | `96e812578de28e9c128854cabb7d7e7ee9123c11` | 67 | 67 | 0 | 0 | GitHub Copilot secure-phase audit |

## Sign-Off

- [x] Every unique plan-time threat ID was enumerated exactly once.
- [x] Every threat has a plan-authored disposition.
- [x] Current source placement was inspected after all review fixes.
- [x] Plan-authored accepted risks are documented; no new risk was accepted.
- [x] Targeted backend, frontend, security, scope, concurrency, scale, and
  contract checks passed.
- [x] `threats_open: 0` confirmed at reviewed HEAD.
- [x] `status: secured` set in frontmatter.

**Approval:** secured 2026-09-06
