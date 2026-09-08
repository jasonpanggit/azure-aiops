---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-08T13:05:00+08:00
status: passed
verdict: PASS — deployed topology findings resolved; message-semantics and corrective summary-link follow-ups source-confirmed
baseline: 12-UI-SPEC.md
audit_mode: live_deployed_runtime
deployment: https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/network
repository_head_at_verification: 702a5eba894238feb3d5bbc43d44d5ef6e5617e2
screenshots: 13 captured (Playwright, authenticated) + 1 API capture
evidence_dir: session artifact `network-live-ui-audit-20260908/`
original_score: 13/24
original_weighted_score: 46.25/100
open_source_findings: 0
live_recheck_findings: 9
post_deployment_failures: 0
post_deployment_tag: network-topology-final-20260908-0440
remediation_base_head: 76df9c420
final_post_redeploy_result: "10 passed, 0 failed"
final_post_redeploy_http_p95_ms: "<3000"
final_server_handler_p95_gate: "<1000ms over five samples"
final_end_to_end_http_p95_gate: "<3000ms over the same five samples"
final_timing_source_commit: 935e956c6adb5f76f47f302dd4319fee164b4f60
final_live_verified: 2026-09-08T04:47:00Z
message_semantics_source_verified: 2026-09-08T14:37:07.284+08:00
message_semantics_live_recheck: not_run_no_deployment
message_semantics_debug_session: .planning/debug/resolved/network-message-semantics.md
corrective_network_source_verified: 2026-09-08T15:36:10.121+08:00
corrective_network_live_recheck: not_run_no_deployment
corrective_network_debug_session: .planning/debug/resolved/network-summary-messages-links.md
supersedes: 2026-09-06 source-contract audit (24/24) — retained as Appendix A
---

# Phase 12 — UI Review

**Audited:** 2026-09-08 · **Mode:** live deployed runtime (authenticated)

**Baseline:** approved `12-UI-SPEC.md` design contract

**Verdict:** **PASS after deployed topology remediation — 24/24. The
message-semantics follow-up is source-confirmed and has no open source finding;
it was not deployed or rechecked live in this debug session.**

## Follow-up Message-Semantics Remediation — 2026-09-08

A post-remediation Network screenshot exposed four deterministic presentation
defects that did not change the 24/24 topology interaction score but weakened
the page's honesty:

1. The global provenance bar repeated pagination state already owned by the
   contextual incomplete-results callout.
2. Every dropped topology relationship said an endpoint was outside scope,
   even when the endpoint was missing or not projected.
3. `high confidence` and `Graph Unknown` omitted the dimensions they described,
   allowing topology-evidence confidence to read as confidence in the complete
   page result.
4. The firewall-bypass metric counted finding rows while its API and UI copy
   described the value as spokes.

The source remediation assigns precise ownership to pagination copy, keeps
collection-pagination warnings out of global provenance only when the
contextual callout can render them, and retains the warning when that companion
surface is unavailable. Topology projection now preserves privacy-safe
cause-specific diagnostics for `excluded_by_scope` versus
`missing_or_unprojected` endpoints while retaining the legacy aggregate drop
counts. Trust labels explicitly name topology evidence and graph observation,
and firewall-bypass values are consistently labelled as finding counts rather
than spoke counts.

Verification was failing-first and causal:

| Check | Result |
|---|---|
| Backend target and boundary regressions | **PASS — 8/8** |
| Frontend target and adjacent regressions | **PASS — 43/43** |
| Adjacent Network/envelope/downstream backend suite | **PASS — 275/275** |
| Applicable EvidenceBar/Network/Inventory frontend import graph | **PASS — 59/59** |
| TypeScript, scoped Ruff, scoped ESLint, and `git diff --check` | **PASS** |
| Revert and reconfirm | **PASS — five backend and three frontend causal failures returned on implementation-only revert and returned to green on reapply** |
| Independent source review | **CONFIRMED FIXED by the user** |

The broader web run recorded 592 passing tests and one unrelated concurrent
failure outside the applicable Network import graph. It was not modified or
used to weaken this acceptance. No deployment or push was performed, so this
section records source closure only; a normal authorized release must recheck
the remediated copy in the live Network page before claiming live confirmation
for this follow-up.

## Final Authenticated Deployment Verification — 2026-09-08

Release `network-topology-final-20260908-0440` is serving from the existing
`aiops-dev-api` and `aiops-dev-web` Container Apps. The ten independent
authenticated Chromium checks all pass:

- retained summary canvas during a slow full-detail request;
- elapsed progress plus Cancel;
- five-sample server handler p95 below 1,000 ms and end-to-end HTTP p95 below
  3,000 ms;
- slash-safe hub dependents with explicit empty/non-empty disposition;
- painted canvas after 1440→390 resize;
- disclosed/toggleable unattached private-link candidates;
- more than 55% useful canvas width;
- all five tabs usable at 390px;
- 20-card inspection-gap pagination; and
- no custom wheel-sensitivity warning.

The API and web revisions are healthy at 100% traffic. `/health`, `/ready`,
`/network`, and `/api/config` return HTTP 200.

## Final Authenticated Post-Redeploy Gate Calibration — 2026-09-08

The redeployed remediation passes **9 of 10** authenticated checks, including
the exact query-transport hub check returning 200. The remaining check sampled
five full-detail requests and observed end-to-end HTTP p95 between **1,646 and
1,794 ms**, down from 14,397 ms on the prior redeploy and 146,723 ms in the
original audit.

That remaining failure was a measurement-contract defect, not grounds to relax
the Phase 12 server budget. The requirement is server topology analysis plus
response serialization p95 **<1,000 ms**; the deployed Playwright test was
applying that threshold to browser-to-Azure round-trip time, which also includes
ingress, TLS, network, and client overhead. Source now preserves both signals:

- Successful `network_topology` responses add
  `X-AIOPS-Handler-Ms: <non-negative decimal>` without changing the response
  body. The clock starts immediately before service resolution/analysis and is
  stopped by a route wrapper only after FastAPI has serialized the response.
  Authentication, validation, and error responses retain their existing
  behavior and do not fabricate a successful-handler duration.
- The deployed Playwright check uses the same five successful responses to
  assert server handler p95 **<1,000 ms** and end-to-end HTTP p95
  **<3,000 ms** independently. Its attachment and both soft-assert messages
  include each raw distribution, sorted distribution, p95, and strict budget.
- FastAPI `TestClient` coverage proves header presence/format, unchanged JSON,
  and the exact start → serialized response bytes → stop ordering. Vitest
  covers header parsing, independent p95 calculations, strict 1,000/3,000 ms
  boundaries, and 4/5/6 sample-count neighbors.

Final source-readiness evidence:

| Check | Result |
|---|---|
| Failing-first timing regressions | **PASS after fix — API header/serialization and dual-distribution suites were RED before implementation** |
| Focused provider/runtime/network backend | **PASS — 145 tests** |
| Focused network web | **PASS — 4 files / 83 tests** |
| Full backend pytest | **PASS — 3,834 collected / 0 failed** |
| Full web Vitest | **PASS — 58 files / 589 tests** |
| TypeScript / ESLint / production build | **PASS** |
| Ruff over `src` and `tests` | **PASS** |
| Phase 12 local Playwright | **PASS — 3 local scenarios / 10 authenticated checks explicitly skipped without live mode** |
| Complete local Playwright | **Phase 12 clean — 10 passed / 10 skipped; one unchanged Phase 13 HTTPS-only test fails against localhost HTTP** |
| Revert-and-reconfirm | **PASS — server timing and dual-distribution regressions returned to RED when only their production files were removed and returned to GREEN on reapply** |

No deployment or push was performed. The current deployed 1,646–1,794 ms HTTP
observations satisfy the newly explicit user-visible budget, but the server
header itself requires a later normal redeploy before a live server p95 can be
claimed.

## First Authenticated Post-Deployment Recheck — 2026-09-08

Deployment tag `network-topology-fix-20260908-0115` passed eight of the ten
authenticated checks and exposed two deterministic residual defects:

1. Five immediate full-detail samples produced **p95 14,397 ms**, still above
   the unchanged **p95 <1,000 ms** acceptance gate. Direct authenticated
   summary, full-detail, gaps, and rule-findings requests each took
   approximately 9–22 seconds, while `/network/policy` took approximately
   0.8 seconds.
2. Hub dependents still returned 404 for an ARM id present in the same topology
   summary; the live failure continued to show the leading slash missing.

Both failures are now fixed and regression-covered in source, but this
remediation has **not** been redeployed:

- `ProviderRuntime.get()` is a strict state-lock-only last-known-good read. It
  performs no cache-key, freshness, metadata, or loader I/O. The existing
  immediate startup refresh and periodic `provider-refresh` thread exclusively
  own those operations. Failing-first tests cover a normal changed key, four
  concurrent readers during refresh, and an initial request while startup
  loading is blocked.
- Hub identity now uses
  `GET /api/v1/network/topology/hubs/dependents?vnet_id=<exact ARM id>`. The web
  client and authenticated deployed test use this query contract; the legacy
  path route remains as a compatibility adapter. A FastAPI `TestClient`
  regression proves the exact slash-prefixed id traverses actual routing and
  returns the matching envelope.

### Post-deployment remediation gates

| Check | Result |
|---|---|
| Failing-first causal regressions | **PASS after fix — 4 backend + 1 web; all five RED before source edits** |
| Focused provider/runtime/network API | **PASS — 131 tests** |
| Focused network web | **PASS — 4 files, 100 tests** |
| Full backend pytest | **PASS — 3,831 tests** |
| Full web Vitest | **PASS — 57 files, 583 tests** |
| TypeScript / ESLint / production build | **PASS** |
| Ruff on every changed Python path | **PASS** |
| Phase 12 local Playwright | **PASS — 3 local scenarios; 10 authenticated checks explicitly skipped without live mode** |
| Complete local Playwright invocation | **Phase 12 clean; one unrelated pre-existing Phase 13 ontology test requires an HTTPS deployed URL and fails against the local HTTP server** |
| Repository-wide Ruff | **PRE-EXISTING RED — unchanged 27 findings under unrelated `infra/scripts/` and `scripts/`** |
| Revert-and-reconfirm | **PASS — all 4 backend and 1 web causal regressions returned to RED on source-only revert and GREEN on reapply** |

At this point in the chronology, the source was ready for a normal redeployment
but the live acceptance was still open. The later calibration above preserves
the server p95 **<1,000 ms** requirement, adds a distinct HTTP p95
**<3,000 ms** requirement, and records that the hub query now returns 200.

## Remediation Update — 2026-09-08

**Historical pre-deployment verdict:** **SOURCE READY — local acceptance pass;
authenticated runtime suite retained as a post-deploy gate.**

All nine findings below are fixed in the working tree and covered by focused
regressions. The implementation has not been pushed or deployed, so the
historical deployed score above remains the last valid live score. Deployment
is outside this source-debug session's terminal criterion: local source
readiness is complete, while the authenticated suite below remains explicitly
pending for the normal post-deploy process. Its pending state is neither a
claim that the live application is fixed nor a request to deploy from this
session.

### Pre-deployment review closure — 2026-09-08

A second source review found five release-readiness gaps. All five now have
explicit dispositions:

1. A failed full-detail refresh no longer replaces retained topology:
   `TopologyWorkspace` uses the replacement error panel only for
   `error && !topology`; retained data renders with an assertive, non-destructive
   refresh alert. A failing-first regression pins the summary-labelled canvas.
2. Full-detail confirmation is invalidated when either operating scope or
   summary observation changes. Warning copy now checks the duration explicitly;
   there is no `topologyBuildDurationMs!`/`NaN` path. Summary-change and
   scope-change regressions both ran RED→GREEN.
3. `.gitignore` now covers `infra/terraform/*.tfstate*`, including timestamped
   backups. Verification used a hypothetical `git check-ignore --no-index`
   pathname; no existing Terraform state or backup was inspected, printed,
   hashed, moved, or deleted.
4. The resize/wheel source-string tests were removed. Mounted-component tests
   now drive a controlled `ResizeObserver` with fake timers and verify:
   sub-threshold resize-only, supra-threshold resize+fit, teardown timer cleanup,
   and omission of a custom Cytoscape wheel option.
5. `network-topology-deployed.spec.ts` now exposes ten independent,
   finding-labelled tests. Missing hub/candidate/gap live data produces an
   explicit reasoned skip; both p95 latency gates, retained/progress behavior, painted
   canvas, >55% canvas use, mobile containment/all-five-tab interaction, and
   console cleanliness remain unconditional. The slow-request UI checks delay
   only pass-through live traffic; they do not replace API responses.

| # | Original finding | Source disposition | Acceptance evidence |
|---:|---|---|---|
| 1 | Detail switch destroys populated canvas | **Fixed locally.** `useApi` can retain data for explicitly soft dependency changes while still clearing on scope changes. The topology page binds the footnote/export detail to the dependency tuple that produced the retained payload. A failed refresh also retains the canvas and reports an in-workspace alert; only `error && !topology` uses the replacement panel. | RED→GREEN: `useApi.test.ts` soft/hard dependency test; `page.test.tsx` retained summary test; `TopologyWorkspace.test.tsx` retained-error test; Playwright retains the summary canvas and `aria-busy` during delayed full detail. |
| 2 | 146-second full-detail request, no useful guard/progress/cancel | **Fixed locally at the repeat-amplification root.** The hybrid cache TTL now starts after ARG acquisition, not before it, and covers a five-minute operator workflow instead of expiring between Summary, Full detail, and drawer interactions. The cached provider duration is exposed as `summary.topology_build_duration_ms`; requests above 3 seconds trigger confirmation, and an in-flight full-detail request gets elapsed status plus browser abort. Pending confirmation resets on summary/scope replacement and every warning branch handles absent duration without `NaN`. The final acceptance contract also separates post-serialization server timing from end-to-end HTTP timing. | RED→GREEN: completion-time and five-minute cache-boundary test, API duration test, latency-aware workspace guard, summary/scope context regressions, `useApi` abort test, delayed-response Playwright test, post-serialization header test, and strict dual-p95 utility tests. |
| 3 | Hub drill-down false 404 | **Fixed locally.** The browser strips the leading slash before encoding the path; the service restores canonical ARM form; the router checks actual scoped snapshot membership instead of result truthiness; drawer failures are assertive critical callouts. | RED→GREEN: client URL test, two HTTP route tests (path-safe id and existing isolated VNet), and drawer error-state test. |
| 4 | Blank graph after resize | **Fixed locally.** `ResizeObserver` now debounces for 150ms, always resizes Cytoscape, and reapplies the reduced-motion-aware fit after a significant viewport delta. | Mounted behavioral tests cover 47px resize-only, 49px resize+fit, and teardown timer cleanup; real Chromium covers 1440→390 resize with non-transparent canvas pixels after the debounce. |
| 5 | 68 unattached private-link candidates dominate | **Fixed locally.** Only unattached candidates are hidden by default when primary topology exists; attached candidates remain. The exact hidden count and an opt-in checkbox preserve honesty and access. Private-link-only estates remain visible. | Pure graph projection boundaries, workspace toggle/disclosure tests, and real-Chromium default-hidden/opt-in acceptance. |
| 6 | Connected graph uses 37–41% of canvas | **Fixed locally as the composition consequence of #5.** Layout quality is based on connected nodes rather than hidden singleton context, and the default fit no longer includes the orphan grid. | Unit layout regression and real-Chromium ink-bound measurement requiring the graph to occupy >55% of canvas width. Live screenshot recheck remains required. |
| 7 | Five tabs overflow at 390px | **Fixed locally.** `.workspace-tabs` is a width-bounded horizontal scroll container; buttons do not shrink and scroll-snap within the tablist instead of widening the page. | CSS contract test plus real-Chromium 390px bounding-box and Design-policy interaction check. |
| 8 | 77 gap cards render as one 15,763px page | **Fixed locally with an explicit C-1 amendment.** Both card lists now request 20 rows initially and reset to 20 on scope changes; badge collection remains independently paged at 500. | Updated `12-UI-SPEC.md`, page request/range tests, and real-Chromium assertion of 20 cards plus `Showing 1–20 of 77 inspection gaps`. |
| 9 | Cytoscape wheel-sensitivity warning | **Fixed locally.** The custom `wheelSensitivity` override was removed, restoring Cytoscape's platform default. | Mounted constructor-options regression proves no custom wheel option is passed; real-Chromium console-warning assertion remains unconditional. |

### Self-verified gates

| Check | Result |
|---|---|
| Focused backend topology/API/scale/contracts | **PASS — 152 tests** |
| Focused web topology suite | **PASS — 8 files, 194 tests** |
| Full backend pytest suite | **PASS** |
| Full web Vitest suite | **PASS — 57 files, 583 tests** |
| TypeScript `npx --no-install tsc --noEmit` | **PASS — zero diagnostics** |
| Next.js ESLint `npm run lint` | **PASS — zero warnings/errors** |
| Next.js production build | **PASS** |
| Full local Playwright suite | **PASS — 10 passed, 10 independently named deployment-gated tests skipped** |
| Ruff on changed Python paths | **PASS** |
| Repository-wide Ruff | **PRE-EXISTING RED — 27 findings under unrelated `infra/scripts/` and `scripts/`; no Phase 12 changed path is implicated** |
| Revert-and-reconfirm | **PASS — 5 backend/CSS and 15 web behavior assertions failed with only production fixes stashed; the same focused suites passed after reapply** |
| Mutation runner | **SKIPPED — no Stryker configuration/binary is present** |

The production build logs the existing non-fatal `@azure/msal-browser`
`window is not defined` messages during static page generation. The build exits
zero and this remediation does not touch authentication code.

### Preserved post-deploy authenticated acceptance

The repository now includes ten independent checks in
`web/e2e/network-topology-deployed.spec.ts`. They are intentionally skipped
during local mocked runs and do not replace live API responses. Two UI-state
checks delay only pass-through full-detail traffic so retained/progress states
are observable. When a later authorized release deploys these changes through
the normal deployment process, provide a Playwright storage-state file for an
authenticated, authorized operator and run:

```bash
cd web
AIOPS_LIVE_NETWORK_E2E=1 \
PLAYWRIGHT_BASE_URL=https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io \
PLAYWRIGHT_STORAGE_STATE=/secure/path/to/authenticated-storage-state.json \
npx playwright test e2e/network-topology-deployed.spec.ts --project=chromium
```

Acceptance evidence required from that run:

1. The summary response succeeds and the topology canvas contains painted pixels.
2. The exact count of unattached private-link candidates is disclosed and hidden by default.
3. Full detail retains the summary-labelled canvas while busy; if it exceeds 3 seconds, Cancel is visible.
4. The same five immediate authenticated full-detail responses have server
   handler p95 below 1 second and end-to-end HTTP p95 below 3 seconds.
5. The first returned hub ARM id succeeds through the routable dependents path; zero dependents is a 200 empty envelope.
6. A 1440→390 resize leaves painted graph pixels without pressing Fit.
7. The tablist stays inside the 390px viewport and all five tabs remain reachable.
8. Inspection gaps renders no more than 20 cards on the first page.
9. No console warning mentions wheel sensitivity.
10. The Playwright output attachment includes a 390px full-page screenshot for visual review.

## Why this audit disagrees with the previous one

The 2026-09-06 audit scored **24/24** and it was not wrong about what it measured.
It verified *source contracts*: class names, copy strings, tone mappings, weight
tokens, media-query presence, DOM structure. Every one of those still holds — I
re-verified them against `702a5eb` and found no regression.

What that audit could not see is that **Phase 12's own C-3 private-link
projection changed the shape of the runtime data enough to break the layout,
performance, and interaction contracts that the same spec sets.** The contract
was satisfied string-by-string and violated system-wide. This live audit is
therefore authoritative for shipping; Appendix A is retained as the source-contract
record.

Concretely, on the real estate:

| Signal | Contract expectation | Deployed reality |
|---|---|---|
| Nodes at summary detail | "no new visual language" | 103 nodes, **68 of them (66%) unattached private-link candidates** |
| Layout quality | `proof` below 100 nodes | 103 > `LAYOUT_NODE_BUDGET` → permanently degraded `default`/`randomize:false` |
| Full-detail fetch | server build p95 **< 1 s** | **146,723 ms** for 349 KB / 154 nodes — **146× the budget** |
| Canvas during refetch | "populated canvas is retained with `aria-busy`" | canvas, toolbar, footnote, and metrics **all destroyed** for 2.5 minutes |
| Hub drill-down | dependent list or honest empty state | **404 `Hub VNet not found`** after 33,726 ms |

---

## Pillar Scores

| Pillar | Weight | Score | Weighted | Key finding |
|---|---:|---:|---:|---|
| 1. Copywriting | 10% | **3**/4 | 7.5 | Honesty chrome is exact and contract-conformant, but the hub 404 asserts a resource that is on screen "not found". |
| 2. Visuals | 20% | **1**/4 | 5.0 | 66% of the canvas is a meaningless label-collided grid; the real graph uses ~41% of the canvas width. |
| 3. Color | 15% | **3**/4 | 11.25 | Seven-tone palette and accent reservation hold; canvas colour mass is now dominated by semantically-irrelevant icons. |
| 4. Typography | 10% | **3**/4 | 7.5 | Token contract holds in DOM; canvas labels render illegibly at every captured viewport. |
| 5. Spacing | 15% | **2**/4 | 7.5 | Horizontal overflow at 390px (explicit 360px-floor violation) and a 15,763px single-scroll gaps list. |
| 6. Experience Design | 30% | **1**/4 | 7.5 | 146 s blocking load with full UI teardown, 34 s false 404, blank canvas on resize, no cancel anywhere. |

**Overall: 13/24 · Weighted: 46.25/100**

---

## Top Priority Fixes

### 1. BLOCKER — Detail-level switch destroys the populated canvas for 146 seconds

**Root cause (two files, one interaction):**

- `web/src/app/network/page.tsx:59-62` puts `topologyDetail` in the `useApi` dependency list:
  ```ts
  const topology = useApi(
    () => networkApi.topology(scope, { detail: topologyDetail }),
    [scope, topologyDetail],
  );
  ```
- `web/src/hooks/useApi.ts:57-61` nulls `data` whenever *any* dependency changes:
  ```ts
  setState((prev) => ({
    data: dependencyChanged ? null : prev.data,
    loading: true,
    error: null,
  }));
  ```

A detail switch is a dependency change, so `data` → `null`, `summary` → `undefined`,
and `page.tsx:305-313` falls through to the loading `StatePanel`. Observed in
`network-topology-full-detail.png`: the canvas, toolbar, legend, coverage callouts
and footnote are gone; "Observed network" and "Unhealthy peerings" show `—`;
PageHeader shows `— subscription connections`; the EvidenceBar confidence badge
**downgrades from `high confidence` to `medium confidence`** purely because a
request is in flight.

This directly violates two spec clauses:
- UI Considerations → *"loading | topology canvas | on refetch the populated canvas is retained with `aria-busy` (C-6)"*
- C-2 → *"switching Summary → Full detail must run the incremental layout (`randomize: false`) so existing node positions survive"* — impossible once the component unmounts. C-2 acceptance #7 cannot hold at runtime.

**Fix:** treat a detail change as a refetch, not a scope change. Preserve data for
"soft" dependency changes — e.g. add a `preserveDataOn` / `keepPreviousData` option
to `useApi.ts:57-61`, and pass `topologyDetail` through it from `page.tsx:59-62`.
Then gate `page.tsx:314` on `aria-busy={topology.loading}` (already present) while
continuing to render `TopologyWorkspace` from the previous `topology.data`.
The confidence badge must be derived from evidence, never from `loading`.

### 2. BLOCKER — Full detail exceeds the performance budget by 146× with no guard, progress, or cancel

`GET /api/v1/network/topology?detail=full` → **200 in 146,723 ms** for 349,293 bytes,
154 nodes, 98 relationships. The spec's budget is *"Server topology build p95 < 1 s
at enterprise size (646 ms measured)"* and explicitly *"no client-side timeout is
introduced"* — so the operator has no escape for two and a half minutes.

The C-2 guard is implemented correctly (`TopologyWorkspace.tsx:469-483`,
`FULL_DETAIL_GUARD_NODES = 1_500` at `:35`) but **is the wrong proxy**. It gates on
`summary.projected_full_node_count`, which is **154** here — far under 1,500 — so the
warning callout at `TopologyWorkspace.tsx:752-769` never renders. Cost is dominated by
server build time, not client node count, and nothing measures that.

**Fix (three parts):**
- Root-cause the 146 s server build for a 154-node estate first — this is a backend defect, not a UI one. 349 KB in 146 s is ~2.4 KB/s.
- Make the guard latency-aware: have the topology envelope carry a server-side build-cost estimate and gate on it in `chooseDetailLevel` (`TopologyWorkspace.tsx:469-483`) in addition to node count.
- Give any request past ~3 s a determinate-or-elapsed progress affordance and a **Cancel** control that reverts the segmented control to Summary.

### 3. BLOCKER — Hub drill-down returns a false 404 after 34 seconds

`GET /api/v1/network/topology/hubs/%2Fsubscriptions%2F…%2Fdemo-vnet/dependents`
→ **404 `Hub VNet not found`** in 33,726 ms, for a hub that is rendered, selected,
and fully described in the drawer beside the error.

**Two independent root causes, both real:**

**(a) Leading slash is lost in transit.** `web/src/lib/services.ts:1191`:
```ts
`/network/topology/hubs/${encodeURIComponent(vnetId)}/dependents`
```
`encodeURIComponent` encodes the leading `/` as `%2F`. The route is
`@router.get("/topology/hubs/{vnet_id:path}/dependents")` (`src/api/routers/network.py:209`);
ASGI decodes `%2F` back to `/`, producing `hubs//subscriptions/…`, and path
normalisation drops the leading empty segment. `vnet_id` therefore arrives as
`subscriptions/…/demo-vnet` — exactly the missing leading slash observed in the
response body. `src/network/service.py:436` then casefolds that and misses every
ARM id in `self.snapshot.vnets`, which are stored *with* the leading slash.

Note `web/src/lib/network-services.test.ts:72-78` asserts the `%2F` encoding is
present, so the unit test **pins the buggy behaviour** and passes. It never
exercises real ASGI routing.

**(b) "No dependents" is conflated with "not found".** `src/api/routers/network.py:214-219`:
```python
if not result.get("hub_name") and not result.get("dependent_count"):
    raise ApiError(ErrorCode.NOT_FOUND, "Hub VNet not found", ...)
```
This estate has `peering_count: 0` and `spoke_count: 0`. **Even with a perfectly
correct id, a legitimately isolated hub 404s.** Meanwhile
`TopologyDetailDrawer.tsx:862-864` already has the correct empty state —
*"No dependent networks were observed."* — which is unreachable because the API
raises instead of returning an empty list. This is a textbook breach of the spec's
three-way honesty rule (empty ≠ error ≠ unknown).

**Fix:**
- `services.ts:1191`: stop double-encoding the path segment — send the ARM id in a
  query parameter, or strip the leading slash client-side and re-add it server-side.
  Update `network-services.test.ts:72` to assert the *routable* form.
- `network.py:214-219`: 404 only when the VNet is genuinely absent from the snapshot.
  Return a 200 envelope with `dependent_vnets: []` when the hub exists with no peers.
- `TopologyDetailDrawer.tsx:846`: render failures in `.callout.callout-critical`
  with `role="alert"`, not `.muted` — today an error is styled identically to an
  empty state.
- Investigate the 33.7 s latency separately; it shares a cause with fix #2.

### 4. BLOCKER — Canvas is blank after viewport resize until the user presses Fit

`web/src/components/network/TopologyGraph.tsx:547-550`:
```ts
const observer = new ResizeObserver(() => {
  cy.resize();
});
```
`cy.resize()` updates the renderer's canvas geometry but **retains the pan/zoom
computed for the previous viewport**. Resizing 1440 → 390px leaves the graph panned
entirely outside the visible extent. `network-topology-mobile.png` shows an empty
`.topology-canvas-wrap` under a footnote that confidently reads *"Rendering 154 of
154 nodes at full detail"* — the honesty chrome is asserting content the operator
cannot see. `network-topology-mobile-after-fit.png` confirms the graph exists and
appears only after a manual **Fit**.

**Fix:** debounce the observer (~150 ms) and follow `cy.resize()` with the existing
reduced-motion-aware fit path at `TopologyGraph.tsx:324-332` when the viewport
delta is significant.

### 5. WARNING — 68 unattached private-link candidates dominate and destroy the canvas

`network-topology-response.json` confirms `counts.private_link_resources: 68` of
103 total resources, against only 46 relationships. C-3 projects all of them as
`kind="workload"` nodes, and the great majority have no edge.

Three compounding effects in `TopologyGraph.tsx:253-268`:
- `LAYOUT_NODE_BUDGET = 100` (`:253`). C-3 pushed this estate from ~35 to **103**
  nodes, tipping it permanently into `large` → `quality: "default"`, `randomize: false`.
  **A Phase-12 feature degraded its own layout quality for a median-sized estate.**
- `packComponents: true` (`:266`) packs 60+ singleton components into the tight
  rectangular grid visible at the top of every desktop, tablet, and fullscreen capture.
- `nodeSeparation: 110` / `idealEdgeLength: 130` are tuned for connected graphs;
  in the packed grid, node pitch falls below the `text-max-width: 96px` label width,
  so labels overlap into an unreadable smear.

`network-topology-relayout.png` confirms Re-layout changes positions but fixes
neither collision nor grouping.

**Fix (no new library, no new visual language — stays in scope):**
- Collapse unattached private-link candidates into a single labelled compound node
  (e.g. *"68 private link candidates"*) that expands on demand, or put them behind
  the existing Filter toggle, defaulted off with a legend/footnote disclosure so the
  honesty contract is preserved.
- Recompute `LAYOUT_NODE_BUDGET` against *connected* node count, not total, so the
  private-link projection stops degrading layout quality.
- Raise `nodeSeparation` for disconnected components, or set `packComponents: false`
  and place orphans in an explicit gutter.

### 6. WARNING — Graph uses 37–41% of available canvas width

Desktop: graph occupies ~460px of a 1124px stage. Fullscreen
(`network-topology-fullscreen.png`): ~530px of ~1400px, i.e. roughly the left half,
with the entire right half blank. Full-detail-loaded is similar. `cy.fit(undefined, 40)`
(`TopologyGraph.tsx:514`) fits the *bounding box including the packed orphan grid*,
so the aspect-ratio mismatch between a tall grid+graph stack and a wide canvas
wastes most of the horizontal budget. Fixing #5 largely resolves this; verify
`fit()` padding after that change.

### 7. WARNING — Horizontal overflow at 390px violates the explicit 360px floor

`network-topology-mobile.png` shows the `workspace-tabs` tablist clipped mid-word
("Design policy" truncated to "D") with the page scrolling horizontally. The spec's
Responsive Constraints table is unambiguous: *"360px (floor) — No horizontal
scrollbar on `.topology-toolbar`, `.topology-footnote`, `.topology-coverage`, or
`.topology-drawer-body`."* The tablist is not named in that list but the page-level
horizontal scroll it induces defeats the constraint's intent. The `≤900px` block in
`globals.css:3018-3030` correctly stacks the stage; the tablist has no equivalent
wrap or scroll-snap treatment.

**Fix:** allow `.workspace-tabs` to wrap, or give it a contained
`overflow-x: auto` with `scroll-snap-type` so it scrolls *within* itself rather than
widening the document.

### 8. WARNING — Inspection gaps renders 77 cards in one 15,763px scroll

`NETWORK_PAGE_SIZE = 100` (`web/src/app/network/page.tsx:25`) is **exactly what C-1
mandates**, so this is spec-conformant. The spec is the defect: C-1's justification
reasons about table rows and `Showing 1–100 of 340` strings, but `FindingList`
renders ~200px cards. 100 cards is ~26 viewport heights, and at 77 items pagination
never engages at all. Scanning and comparison are impractical.

**Fix:** this needs a C-1 amendment, not a silent code change. Either set the
card-shaped lists to a 20–25 initial page size (keeping the explicit
`limit`/`offset` request contract and the truncation disclosure intact), or add
severity grouping with collapsed sections. Record the decision in `12-UI-SPEC.md`
before implementing.

### 9. WARNING — Cytoscape wheel-sensitivity console warning

`TopologyGraph.tsx:504` sets `wheelSensitivity: 0.2`. Cytoscape logs a warning that
custom wheel sensitivity is discouraged and platform-dependent. Cosmetic and
non-blocking, but it is noise in the production console and trivially removable
unless the value is deliberately tuned — in which case add a comment recording the
measurement that justified it.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4) — WARNING

**What passes.** The honesty chrome is the strongest part of this implementation and
every C-1/C-7/C-10 copy contract renders verbatim at runtime:

- `Rendering 103 of 103 nodes at summary detail.` — C-1 "even when equal" ✅
- `Badges: 83 of 83 findings` · `80 nodes with open findings` — C-1, C-5 a11y mirror ✅
- `6 relationships dropped (attached_to, hosts, load_balances) — endpoints were not present in this scope.` ✅
- `Snapshot age unknown — no observation timestamp was recorded.` — C-7 exact string ✅
- `Graph Unknown` segment present in the EvidenceBar — C-7 unconditional segment ✅
- `Flow logs: not ingested — findings are configuration-derived` — data-derived from `flow_log_provenance.state: "not_ingested"` ✅
- `Export PNG (image only)` — C-9 ✅ · legend `Private link candidate`, `Peer VNet not shown` — C-3, C-10 ✅

**Defects.**
- `TopologyDetailDrawer.tsx:846` renders `Dependencies are unavailable: Hub VNet not found`
  for a hub that is selected and fully described immediately above. The copy asserts
  a falsehood to the operator's face. Breaks the three-way honesty rule.
- `page.tsx:227` renders `— subscription connections` during load. An em-dash in a
  leading noun slot reads as a broken template, not as "unknown". C-1 uses `—` for
  *metric values*; prose needs a word.
- `page.tsx` loading panel *"Building cross-subscription topology / Stitching VNets,
  peerings, and shared services."* sets an expectation of seconds and was on screen
  for 146 s. No copy anywhere prepares the operator for that.

### Pillar 2: Visuals (1/4) — BLOCKER

No usable visual hierarchy at any captured viewport. Evidence: findings #5, #6, #4.

- The dominant visual mass — a ~7×10 grid of 68 icon tiles with fully collided
  labels — carries **no network meaning**. The actual hub/spoke/subnet graph, which
  is the page's stated primary anchor ("The topology canvas remains the primary
  visual anchor"), is visually subordinate to it.
- Desktop, tablet, fullscreen and full-detail-loaded all reproduce it.
- Mobile renders **nothing** until Fit; after Fit the graph is ~250px square and
  unreadable.
- Re-layout does not resolve collision or grouping.

The Phase-12 node styling itself is correct: private-link candidates do use the
existing dashed `46×46` workload treatment with no new shape, size, or colour
(`TopologyGraph.tsx:115`), exactly as C-3 requires. The failure is composition
and density, not styling.

### Pillar 3: Color (3/4) — WARNING

**What passes.** The seven-tone `StatusTone` union is unchanged; no eighth tone was
added. Accent `--color-brand` remains reserved — `segmented-active` on the detail
control, hub node border, focus ring, primary CTA. Severity dots on canvas are
mirrored by text in the footnote and drawer, satisfying the colour-independence
constraint. All 33 hex literals in the network surfaces are confined to the
Cytoscape `STYLESHEET`, which the spec classifies as canvas paint rather than DOM
colour — no violation.

**Defects.**
- The canvas 60/30/10 distribution is broken in practice. The intended dominant is
  the calm `#eef2f6` stage; in reality 68 saturated multi-colour Azure icons occupy
  the largest contiguous region. Colour weight now tracks resource *count* rather
  than network *significance*. Resolved by fix #5.
- The EvidenceBar confidence badge shifts `high confidence` → `medium confidence`
  during a refetch (`network-topology-full-detail.png`). An evidence-semantic colour
  is being driven by request state. Fixed alongside blocker #1.

### Pillar 4: Typography (3/4) — WARNING

**What passes.** The DOM token contract holds exactly. No inline `fontSize` anywhere
in `components/network/*.tsx` or `app/network/page.tsx`. Sizes stay within the
permitted 10/11/12/13px set; weights stay 400/700 plus the declared legacy 600/650
inherited via `.status-badge`, `.segmented-active`, and the global `h2`/`h3` rules.
The drawer in `network-topology-fullscreen-drawer.png` confirms 10px/700 uppercase
tracked fact labels and a 12px/650 `Open findings (5)` heading, per the spec's
measured table.

**Defects.** Canvas type is illegible at runtime. `TopologyGraph.tsx:115` and `:125`
set `font-size: 9`, `:156` sets `font-size: 8`. These are exempt as canvas geometry,
but at the fit-zoom forced by fix #6 they render below ~6px effective, and inside the
packed orphan grid the node pitch is smaller than `text-max-width: 96px`, so
labels overlap instead of ellipsising. After mobile Fit, labels are ~3–4px — pure
texture. Type that cannot be read fails the pillar regardless of token conformance.

### Pillar 5: Spacing (2/4) — WARNING

**What passes.** No Phase-12 rule restates a declared exception. No inline `style={{`
spacing in any network component. `.topology-coverage` composes on `.callout` as
specified. The `≤900px` block (`globals.css:3018-3030`) correctly stacks
`.topology-stage`, sets `.topology-canvas-wrap` to 420px and caps `.topology-drawer`
at 340px — the tablet capture confirms this renders as contracted.

**Defects.**
- **Explicit constraint violation:** horizontal overflow at 390px (finding #7). The
  Responsive Constraints table names a 360px floor with no horizontal scroll.
- Canvas node pitch in the packed orphan grid falls below label width (finding #5).
- Inspection gaps is a 15,763px single scroll with no density control (finding #8).

### Pillar 6: Experience Design (1/4) — BLOCKER

Four blockers land here. Aggregate state coverage:

| State | Contract | Deployed |
|---|---|---|
| Loading — first load | StatePanel `tone="loading"` | ✅ correct |
| Loading — **refetch** | retain populated canvas + `aria-busy` | ❌ **full teardown for 146 s** (#1) |
| Loading — long request | budget p95 < 1 s | ❌ **146,723 ms, no progress, no cancel** (#2) |
| Error — topology | StatePanel + Retry R-1 | ✅ implemented (`page.tsx:307-312`) |
| Error — drawer dependents | honest, distinguishable | ❌ **false 404, `.muted` styling, no `role="alert"`** (#3) |
| Empty — no dependents | "No dependent networks were observed." | ❌ **unreachable — API 404s first** (#3) |
| Resize | viewport stays correct | ❌ **blank canvas until manual Fit** (#4) |
| Reduced motion | disabled fit animation | ✅ `TopologyGraph.tsx:326` |
| Focus management | canvas refocus, no steal on refetch | ✅ `focusCanvas` at `:553` |
| Retry accessible names | R-1…R-6 distinct | ✅ verified in source |

**What passes.** Path analysis is coherent and correctly inactive until both inputs
are supplied. Rule findings (6) and Design policy (3) render cleanly with correct
severity treatment. The C-1 pagination envelope, C-4 badge fan-out (`80 nodes with
open findings`, `Badges: 83 of 83`), and the C-5 always-present drawer findings
section all work as contracted — `Open findings (5)` with the *"Findings affecting
this resource"* group heading is visible in the fullscreen drawer capture.

**Assessment.** Every long-running interaction on this page either destroys the
operator's context, lies about the outcome, or leaves them with no way out. That is
a 1.

---

## Explicitly Not Counted Against the Implementation

Per the audit brief, and confirmed independently:

- **Sticky-header duplication in full-page screenshots** — Playwright stitching
  artifact, visible in `network-topology-mobile-after-fit.png`. Not an app defect.
- **One 401** from a manual unauthenticated `fetch` probe. Not an app defect.
- **Keyboard navigation of individual Cytoscape nodes** — accepted pre-existing
  limitation recorded in `12-REVIEW-FIX.md`, out of Phase-12 scope. All Phase-12
  controls and every canvas-only signal retain DOM equivalents.
- **Source-contract items resolved by the 2026-09-06 remediation** (W-UI-01…W-UI-08)
  — re-verified as still holding at `702a5eb`; not re-reported.

---

## Verification Performed

| Check | Result |
|---|---|
| Screenshot storage git-safe | ✅ Evidence archived outside the repository in the session artifact `network-live-ui-audit-20260908/` |
| Live deployment reachable and authenticated | ✅ 13 screenshots + 1 API capture |
| Topology API payload analysed | ✅ `network-topology-response.json` — 103 resources, 46 relationships, 68 private-link |
| Source root-cause traced for every runtime defect | ✅ file:line cited for all 9 findings |
| Prior source-contract items re-verified | ✅ `segmented-active` used, no standalone `"active"` class, reduced motion present, 14 `role="status"`/`role="alert"` regions, no inline spacing/type |
| Registry safety audit | ⏭️ **skipped — not applicable.** No `components.json`; UI-SPEC Registry Safety declares zero third-party registries and zero new npm packages. |
| Application source modified | ❌ none — audit only |
| Committed | ❌ no |

### Housekeeping

The 13 PNGs and `network-topology-response.json` were removed from the repository
root after the audit. Copies are preserved outside Git in the session artifact
`network-live-ui-audit-20260908/`.

---

## Files Audited

**Frontend**
- `web/src/app/network/page.tsx` (1278 lines)
- `web/src/components/network/TopologyWorkspace.tsx` (879)
- `web/src/components/network/TopologyGraph.tsx` (679)
- `web/src/components/network/TopologyDetailDrawer.tsx` (1050)
- `web/src/lib/network-graph.ts` (532)
- `web/src/lib/services.ts`
- `web/src/lib/network-services.test.ts`
- `web/src/hooks/useApi.ts` (88)
- `web/src/app/globals.css`

**Backend**
- `src/api/routers/network.py`
- `src/network/service.py`

**Evidence** — session artifact `network-live-ui-audit-20260908/` (13 PNG + 1 JSON)

**Planning** — `12-UI-SPEC.md`, `12-CONTEXT.md`, `12-01`…`12-11` PLAN/SUMMARY,
`12-REVIEW-FIX.md`, `12-UI-REVIEW.md` (prior)

---
---

# Appendix A — Superseded source-contract audit (2026-09-06)

> Retained for historical context. **Not authoritative.** This audit verified source
> contracts against HEAD `207c7c78` and correctly recorded 24/24 for what it
> measured. It did not exercise the deployed runtime. Where it conflicts with the
> live audit above, the live audit governs.


### Prior verdict (superseded)

**Audited:** 2026-09-06

**Baseline:** approved `12-UI-SPEC.md` design contract

**Verdict:** **PASS — all eight warnings resolved**

**Verified source:** `207c7c78b4b90dfa9561054fdd9c840be74c8764`

The review was repeated against current source, not the stale SHA recorded by the
previous audit. The two source commits under review are:

- `10ed335b` — `fix(network): align topology canvas interactions`
- `207c7c78` — `fix(network): complete policy UI contracts`

No blocker or warning remains. The accepted pre-existing limitation from
`12-REVIEW-FIX.md`—direct keyboard navigation of Cytoscape nodes—remains outside
Phase 12 scope; all Phase-12 controls and every canvas-only signal retain DOM
equivalents.

#### Final Pillar Scores

| Pillar | Weight | Score | Weighted | Final result |
|---|---:|---:|---:|---|
| 1. Copywriting | 10% | 4/4 | 10.0 | Exact policy empty-state next step and bounded-preview disclosure are present. |
| 2. Visuals | 20% | 4/4 | 20.0 | Canvas/drawer stack at ≤900px; private-link candidates have an exact labelled, dashed legend treatment. |
| 3. Color | 15% | 4/4 | 15.0 | Existing seven-tone palette is preserved and all Phase-12 state keywords map to permitted tones. |
| 4. Typography | 10% | 4/4 | 10.0 | Phase-12 policy labels use the permitted 700 weight. |
| 5. Spacing | 15% | 4/4 | 15.0 | Tablet and mobile topology composition now share the contracted dimensions without new spacing values. |
| 6. Experience Design | 30% | 4/4 | 30.0 | Canvas focus restoration, reduced-motion Fit, and single-alert validation are enforced and tested. |

**Overall: 24/24**

**Weighted overall: 100/100**

#### Warning Resolution

| ID | Result | Resolution and evidence |
|---|---|---|
| W-UI-01 | **RESOLVED** | `.topology-stage`, `.topology-canvas-wrap`, and `.topology-drawer` stack in the existing `@media (max-width: 900px)` block. The ≤560px block retains its other mobile rules. `test_ui_review_responsive_contract` pins the source contract. |
| W-UI-02 | **RESOLVED** | The legend now includes exact copy `Private link candidate` and a muted dashed swatch matching the existing workload-node treatment without a new color or node kind. DOM and CSS contract tests pin both parts. |
| W-UI-03 | **RESOLVED** | The canvas is programmatically focusable with `tabIndex={-1}`. The graph handle exposes `focusCanvas()`, and explicit drawer close plus selection-clear paths restore focus. Topology refetch still does not move focus. |
| W-UI-04 | **RESOLVED** | `fitTopology()` queries `matchMedia("(prefers-reduced-motion: reduce)")`; reduced motion uses immediate `cy.fit()`, while the existing 200ms animation remains for other users. |
| W-UI-05 | **RESOLVED** | Policy form validation renders one prioritized assertive region for semantic, form, or save errors. The out-of-form save alert is mutually exclusive with the form alert. |
| W-UI-06 | **RESOLVED** | Policy empty copy is exactly: “No design rules are configured for this estate. Add a rule to start checking for gaps.” |
| W-UI-07 | **RESOLVED** | Previews still render at most five examples and now visibly append `and N more` when additional gaps exist. |
| W-UI-08 | **RESOLVED** | `statusTone()` additively maps `complete`, `partial`, `not-analyzed`, `private-link-candidate`, `public-access-enabled`, `peer-not-ingested`, `peer-out-of-scope`, and `peer-resolution-unknown`; the seven-member tone union is unchanged. Policy labels now resolve to weight 700. |

#### Regression Coverage

Failing-first coverage was added before implementation:

- Initial focused Vitest run: **8 failed, 76 passed**.
- Initial responsive/private-link source contracts: **2 failed**.
- Initial policy-label source contract: **1 failed**.

Final checks:

| Check | Result |
|---|---|
| Warning-specific CSS source contracts | **PASS — 3 selected backend tests** |
| Warning-specific affected Vitest files | **PASS — 4 files, 84 tests** |
| Targeted Phase-12 frontend suite | **PASS — 9 files, 188 tests** |
| Complete web Vitest suite | **PASS — 43 files, 354 passed, 15 todo** |
| TypeScript `npx --no-install tsc --noEmit` | **PASS — zero diagnostics** |
| Next.js ESLint `npm run lint` | **PASS — zero warnings/errors** |
| Phase-12 UI hygiene/source contracts | **PASS — 8 selected tests** |
| Scoped Phase-12 backend contract suite | **PASS — 298 tests, 9 deprecation warnings** |
| `git diff --check` across both source commits | **PASS** |
| Protected planning artifacts | **PASS — no changes to STATE, ROADMAP, REQUIREMENTS, VALIDATION, VERIFICATION, or SECURITY** |

The full web run retains the existing non-failing Vite CJS notice. No source,
test, TypeScript, ESLint, hygiene, or diff failure remains.

All final verification commands ran in the user-supplied isolated worktree
`/Users/jasonmba/workspace/copilot-worktrees/azure-aiops/jasonpanggit-potential-broccoli`
against source HEAD `207c7c78`.

### Exact final verification commands

```bash
.venv/bin/python -m pytest tests/test_network_downstream_contracts.py \
  -k 'ui_review_responsive_contract or ui_review_policy_labels_use_permitted_weight or ui_review_private_link_legend_matches_canvas_treatment' -q

cd web && npx vitest run \
  src/app/network/page.test.tsx \
  src/components/network/TopologyGraph.test.tsx \
  src/components/network/TopologyWorkspace.test.tsx \
  src/components/ui/StatusBadge.test.tsx

cd web && npx vitest run
cd web && npx --no-install tsc --noEmit
cd web && npm run lint

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

#### Files Changed by the Remediation

- `tests/test_network_downstream_contracts.py`
- `web/src/app/globals.css`
- `web/src/app/network/page.tsx`
- `web/src/app/network/page.test.tsx`
- `web/src/components/network/TopologyGraph.tsx`
- `web/src/components/network/TopologyGraph.test.tsx`
- `web/src/components/network/TopologyWorkspace.tsx`
- `web/src/components/network/TopologyWorkspace.test.tsx`
- `web/src/components/ui/StatusBadge.tsx`
- `web/src/components/ui/StatusBadge.test.tsx`

#### Unresolved Items

None within the eight-warning remediation scope.

## Corrective Network Message and Summary-Link Addendum — 2026-09-08

**Local source status:** PASS. **Independent source review:** confirmed fixed.
**Deployment/live workflow status:** not run; this corrective pass did not
deploy or push.

Three post-deployment presentation defects were reproduced with specified,
failing-first regressions and corrected:

- ordinary server pagination no longer creates a permanent page-level
  incomplete-results warning; the Inspection gaps and Rule findings tabs own
  their exact `Showing X–Y of N` ranges;
- summary topology still omits route-level nodes, but now contracts an observed
  `RouteTable → Route → AzureFirewall` virtual-appliance path into a meaningful
  `RouteTable → AzureFirewall` next-hop relationship;
- exhaustive topology badge loading is the drawer completeness authority, so a
  clean resource is confirmed after all 83 of 83 findings are checked even
  when the visible list remains on a truncated 20-row server page.

Corrective verification:

| Check | Result |
|---|---|
| Three exact failing-first regressions | **RED before source changes; GREEN after** |
| Scoped source revert and reapply | **All three defects returned; all three fixes reconfirmed** |
| Adjacent backend network suites | **PASS — 159 tests** |
| Adjacent web network suites | **PASS — 8 files, 199 tests** |
| Mocked Chromium Phase 12 regressions | **PASS — 3 scenarios** |
| TypeScript, Next ESLint, scoped Ruff | **PASS** |
| Next.js production build | **PASS — 28 routes** |
| Python source and wheel build | **PASS** |
| Independent source review | **CONFIRMED FIXED by the user** |

An additional full-web sweep passed 594 tests in 57 files and exposed one
unrelated existing Compliance-page test-mock defect
(`isCanonicalAzureResourceId` missing from that test's `@/lib/services` mock).
That out-of-scope file was not changed.

This addendum is source-verification evidence only. No deployment or
authenticated live recheck was performed, so the earlier deployed-runtime
evidence remains the authoritative live result.
