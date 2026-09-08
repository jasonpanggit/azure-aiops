---
status: awaiting_human_verify
trigger: "Troubleshoot and fix all findings and errors from the authenticated Playwright review of the deployed /network experience."
created: 2026-09-08T01:10:00+08:00
updated: 2026-09-08T11:52:00+08:00
reopened: 2026-09-08T11:13:42.686+08:00
---

# Debug Session: Network Topology Live UI

## Symptoms

### Expected behavior

- Summary topology presents the actual network structure as the primary visual, with private-link candidates available without overwhelming connected resources.
- Switching Summary/Full detail retains the populated graph and metrics with a busy state, and completes within the Phase 12 performance budget.
- Hub-dependent drill-down returns either observed dependents or an honest empty state.
- Resizing desktop/tablet/mobile keeps the graph visible without requiring a manual Fit.
- The graph uses the available canvas and keeps labels readable.
- All five tabs remain usable at the 360px floor.
- Inspection gaps are paged at a card-appropriate density.
- Cytoscape emits no avoidable wheel-sensitivity warning.

### Actual behavior

- Summary renders 103 nodes and 46 relationships; 68 nodes are mostly unattached private-link candidates, packed as a dense unreadable grid.
- Connected graph content uses roughly 37-41% of the canvas width even in fullscreen, while labels overlap.
- Full-detail topology took 146,723 ms for a 349,293-byte response with 154 nodes/98 relationships.
- During full-detail loading, the populated graph, toolbar, footnote, and several metrics are replaced with a loading panel/dashes.
- Clicking hub `demo-vnet` took 33,726 ms and returned 404 `Hub VNet not found`; the response id lost the leading `/`.
- At 390px after resize, the graph was blank until Fit; after Fit it was too small to read.
- The tab list clips Design policy beyond the mobile viewport.
- Inspection gaps renders 77 card rows in a ~15,763px page at the default limit of 100.
- Cytoscape warns about custom wheel sensitivity.

### Error messages

- `GET /api/v1/network/topology/hubs/%2Fsubscriptions.../demo-vnet/dependents` → 404:
  `{"error":{"code":"not_found","message":"Hub VNet not found",...}}`
- Cytoscape console warning: custom wheel sensitivity causes unnatural zoom on mainstream mice.
- One manually-issued unauthenticated topology request returned 401; this is audit noise and not an application defect.

### Timeline

- Reproduced on the deployed development environment on 2026-09-08 after Phase 12 was implemented and deployed.
- Prior source-only UI audit passed; this fresh authenticated runtime audit exposed data-shape, latency, resize, and routing defects.

### Reproduction

1. Open `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/network`.
2. Open Topology: observe the disconnected private-link grid and compressed connected graph.
3. Press Re-layout or fullscreen: labels remain overlapped and canvas width remains underused.
4. Select Full detail: populated UI disappears; request completes after ~146.7 seconds.
5. Click hub `demo-vnet`: dependent request returns false 404 after ~33.7 seconds.
6. Resize to 390px: graph disappears until Fit and tabs overflow.
7. Open Inspection gaps: 77 cards appear in one very long page.

## Current Focus

bug_class: bohrbug
hypothesis: "Confirmed: request-time ProviderRuntime.get I/O caused the repeated warm endpoint latency, and wildcard-path ARM-id transport caused the deployed hub 404."
test: "All source-readiness and guardrail checks are complete; the remaining check requires a later authorized redeploy and authenticated execution of the unchanged p95/routing acceptance."
expecting: "After redeploy, five immediate full-detail samples have p95 <1,000 ms and the first summary hub id returns a 200 empty/non-empty envelope through the query route."
next_action: "Await human confirmation of the source remediation, or later redeploy through the authorized process and report the authenticated p95 and hub-route results. Do not deploy or push from this session."
known_pattern_candidate: "none — MemPalace is unavailable and the durable knowledge base has no two-token match for ProviderRuntime.get request-thread I/O or slash-losing hub routes."
candidate_causes:
  - "code: ProviderRuntime.get refreshes cache identity and reads loader state synchronously; path transport embeds a slash-prefixed ARM id in a route wildcard"
  - "config/environment: one API replica and slow Fabric semantic-version access amplify any synchronous request-thread work"
  - "data: slash-prefixed ARM hub ids expose route normalization while simple policy requests do not"
and_gate: "under investigation — latency may require synchronous request-time freshness I/O plus slow deployed Fabric access; the hub 404 may require a slash-prefixed ARM id plus path normalization."
reasoning_checkpoint:
  hypothesis: "ProviderRuntime.get causes repeated network endpoint latency because it performs Fabric semantic-version/cache-key reads and can execute provider loaders on the request thread; the hub 404 persists because a slash-prefixed ARM identifier is transported through a path wildcard whose deployed normalization is lossy."
  confirming_evidence:
    - "Direct code tracing shows get() calls _refresh_changed_cache_key twice, refresh(blocking=False), and _read_cache_key; both refresh helpers execute I/O after a nonblocking lock acquisition, and the network cache key calls Fabric semantic_version()."
    - "Agent-authored regressions are RED: one get produced seven I/O calls, four concurrent gets added twelve I/O calls during a background refresh, and an initial-startup get added three I/O calls."
    - "The FastAPI TestClient query-route regression returns 404 and the web client regression still observes the encoded path contract; deployed evidence independently shows the same hub id losing its leading slash."
    - "Authenticated endpoint differential is specific: topology/gaps/rule-findings, which resolve the managed network provider, take 9–22 seconds while /network/policy, which bypasses it, takes about 0.8 seconds."
  falsification_test: "The hypothesis would be false if get() could be observed making zero cache-key/loader calls before the fix, if slow network routes bypassed ProviderRuntime.get, or if an exact slash-prefixed query parameter still arrived corrupted through TestClient."
  fix_rationale: "A state-only get() enforces the documented LKG boundary rather than masking latency, while the already-existing immediate startup and periodic background thread remains the sole refresh owner. A query parameter delegates slash encoding/decoding to URL query semantics and preserves exact ARM identity; sharing the membership helper retains honest 404/empty behavior and legacy compatibility."
  blind_spots: "This environment cannot redeploy or repeat authenticated production timing, so the unchanged live p95 <1s gate remains pending after source verification. The hybrid ARG cache and Fabric latency could still contribute after request-time provider I/O is removed, although five-minute cached rows and the endpoint differential argue against them as the repeated warm-request cause."
  candidate_causes:
    - "code: get() executes cache-key and loader paths; client/server use a lossy path-wildcard identifier contract"
    - "config/environment: one replica and 9–22 second deployed Fabric semantic-version latency amplify the request-thread code path"
    - "data: slash-prefixed ARM identifiers trigger normalization loss; ordinary policy payloads do not"
  and_gate: "yes for observed severity: synchronous get() I/O plus slow deployed Fabric access produces the multi-second warm latency, and path transport plus slash-prefixed ARM data produces the 404. The two top-level failures are otherwise independent and both require separate fixes."

## Post-Deployment Reopen Symptoms

### Expected behavior

- Five immediate authenticated full-detail samples preserve the unchanged deployed acceptance gate: observed p95 must be below 1 second.
- `ProviderRuntime.get()` returns the last-known-good provider without loader or freshness I/O on the request thread; startup/background refresh owns cache-key and loader work.
- A hub ARM id returned by topology summary round-trips through the public API and returns 200 with dependents or an honest empty envelope.

### Actual behavior

- After deployment tag `network-topology-fix-20260908-0115`, authenticated Playwright passed 8 checks and failed 2.
- Five-sample full-detail p95 was 14,397 ms. Authenticated summary/full/gaps/rule-findings requests each took approximately 9–22 seconds on every request, while `/network/policy` took approximately 0.8 seconds.
- The API has `min=max=1` replica.
- `ProviderRuntime.get()` still invokes `_refresh_changed_cache_key`, `refresh(blocking=False)`, and `_read_cache_key`, even though its docstring promises no request-thread loader/freshness I/O. The network cache key invokes Fabric `semantic_version()` plus policy revision.
- Hub dependents returned 404 for a hub id present in the same summary; the live response still omitted the leading slash.

### Reproduction

1. Run the authenticated deployed Playwright suite against deployment tag `network-topology-fix-20260908-0115`.
2. Observe 8 passed and 2 failed.
3. Sample full-detail five times; observed p95 is 14,397 ms rather than below 1 second.
4. Issue authenticated requests to summary/full/gaps/rule-findings; each remains approximately 9–22 seconds, while `/network/policy` is approximately 0.8 seconds.
5. Select a hub ARM id from summary and request dependents through the deployed route; observe 404 and a response id without the leading slash.

### Started

- Observed after deployment tag `network-topology-fix-20260908-0115` during the required authenticated post-deployment acceptance run.

## Evidence

- timestamp: 2026-09-08T01:10:00+08:00
  observation: Live UI audit scored 13/24 with 4 blockers and 5 warnings.
  source: .planning/phases/12-network-topology-integrity-and-scale/12-UI-REVIEW.md
- timestamp: 2026-09-08T01:10:00+08:00
  observation: Full-detail API duration was 146,723 ms for 349,293 bytes.
  source: Playwright network request 170
- timestamp: 2026-09-08T01:10:00+08:00
  observation: Hub dependents request returned 404 after 33,726 ms and response id lacked the leading slash.
  source: Playwright network request 163
- timestamp: 2026-09-08T01:10:00+08:00
  observation: Summary payload contains 103 resources, 46 relationships, and 68 private-link resources.
  source: authenticated deployed topology response
- timestamp: 2026-09-08T01:11:43.597+08:00
  checked: Repository status and active planning scope before edits.
  found: Branch main is ahead of origin/main by one commit; the only working-tree path is this untracked debug session. Phase 03.1 remains active, and this Phase 12 post-implementation remediation is explicitly authorized.
  implication: No concurrent source edits need merging; all Phase 03.1 and unrelated paths must remain untouched.
- timestamp: 2026-09-08T01:11:43.597+08:00
  checked: Failure taxonomy and authoritative nine-finding live review.
  found: All nine symptoms reproduced deterministically in the captured deployed workflow; no evidence currently indicates timing nondeterminism or a concurrency defect.
  implication: Classify this session as a Bohrbug cluster and use deterministic failing-first regressions plus working-backwards/differential tracing.
- timestamp: 2026-09-08T01:13:00+08:00
  checked: Semantic and durable debug knowledge bases.
  found: MemPalace CLI is unavailable. Keyword fallback found no prior resolution with at least two matching topology/routing/layout identifiers; the only topology KB entry concerns Fabric table publication, not this UI/API path.
  implication: No known-pattern candidate is applicable; continue open-ended evidence gathering without importing an unrelated root cause.
- timestamp: 2026-09-08T01:16:00+08:00
  checked: web/src/hooks/useApi.ts and its complete test suite.
  found: Dependency changes unconditionally replace loaded data with null, while nonce-based refetches deliberately retain it; the tests explicitly pin both behaviors.
  implication: A detail-level change currently takes the destructive dependency path. Any fix must preserve data only for detail changes while retaining immediate clearing for authorization/scope changes.
- timestamp: 2026-09-08T01:16:00+08:00
  checked: web/src/app/network/page.tsx and its complete test suite.
  found: Both card-shaped finding collections initialize and reset to NETWORK_PAGE_SIZE=100; the current tests assert 100 for both. The page already renders TopologyWorkspace under aria-busy whenever topology.data survives, and policy-triggered nonce refetch has a passing retention regression.
  implication: Finding 1 is upstream state-reset behavior, not conditional rendering. Finding 8 requires a deliberate card-density contract change with test updates, not a pagination rewrite.
- timestamp: 2026-09-08T01:19:00+08:00
  checked: src/api/routers/network.py, src/network/service.py, web/src/lib/services.ts, and network client tests.
  found: The client places the entire slash-prefixed ARM id in one percent-encoded path segment; the deployed ASGI route drops its leading slash. Independently, the router declares not-found when both hub_name and dependent_count are false, although NetworkIntelligenceService returns a real isolated VNet as hub_name plus dependent_count=0 only when the id matches exactly. The client regression currently requires the lossy encoded-path form.
  implication: Finding 3 is an AND-gate across transport identity corruption and an invalid zero-dependents absence heuristic. A query parameter can preserve ARM identity; existence must be checked explicitly rather than inferred from dependents.
- timestamp: 2026-09-08T01:19:00+08:00
  checked: NetworkIntelligenceService lazy analysis behavior.
  found: Topology, gaps, and rule findings are memoized only within one service instance; the router resolves a hybrid provider on every request before analysis. Hub dependents also accesses topology, so its 33.7s delay and the full endpoint's 146.7s delay can share provider/build work.
  implication: Instrument and test runtime provider acquisition separately from in-memory projection before attributing latency to payload size or Cytoscape.
- timestamp: 2026-09-08T01:23:00+08:00
  checked: src/api/runtime.py hybrid_network cache and existing TTL-cache regressions.
  found: hybrid_network captures now before live_resources.query(), then stores (now, rows). With TTL=30 seconds, any query taking longer than 30 seconds creates an entry that is stale at insertion. The generic _ttl_cached_value helper already has a regression and completion_clock design specifically preventing this bug, but hybrid_network uses bespoke cache logic and does not use the fixed completion-time behavior.
  implication: The deployed 33.7s and 146.7s calls both exceed the TTL and make every following topology/hub request cold. This is a direct repeat-amplification root cause; a completion-time timestamp is the minimal backend correction.
- timestamp: 2026-09-08T01:23:00+08:00
  checked: tests/test_network_scale.py and src/network/topology.py.
  found: The in-memory TopologyBuilder has an enterprise build gate below one second and the full/summary serializer operates on already acquired rows; detail does not change the live ARG query. Summary serialization performs additional bounded-payload searches, but the audited estate has only 154 full nodes and a 349KB full payload.
  implication: Payload projection cannot plausibly account for the observed multi-minute request; live provider acquisition/cache expiry is the differentiating latency branch.
- timestamp: 2026-09-08T01:27:00+08:00
  checked: web/src/components/network/TopologyGraph.tsx and its test suite.
  found: Cytoscape is created with wheelSensitivity=0.2; layoutFor compares total node count to 100 and always packComponents=true; the ResizeObserver only calls cy.resize(); initial and manual re-layout call cy.fit but resize does not. No regression covers resize-triggered fit or console-clean wheel configuration.
  implication: Findings 4, 5, 6, and 9 follow directly from current deterministic configuration. The resize fix should reuse fitTopology after a bounded debounce; the layout fix must distinguish connected topology from private-link-only singleton context rather than merely raise a global node threshold.
- timestamp: 2026-09-08T01:27:00+08:00
  checked: web/src/components/network/TopologyWorkspace.tsx and its complete test suite.
  found: The workspace has toggles for search filtering, shared services, and findings but no control/default for unattached private-link candidates. Its full-detail guard uses only projected node count, and the loaded workspace already correctly remains mounted when passed loading=true.
  implication: Findings 1 and 2 must be fixed at request/state boundaries; finding 5 needs an explicit disclosed private-link visibility policy or projection change rather than relying on current toolbar controls.
- timestamp: 2026-09-08T01:31:00+08:00
  checked: web/src/lib/network-graph.ts and tests plus TopologyDetailDrawer.tsx.
  found: The graph projection retains all resources without computing degree or private-link attachment, so every unattached candidate enters Cytoscape and its compound group. Hub dependency failures are rendered as a plain muted span, while the honest zero-dependent state already exists behind the success branch.
  implication: A pure visible-graph projection can be tested without Cytoscape and can preserve attached candidates. The drawer failure needs critical alert semantics; the existing empty state needs no redesign once the API returns 200.
- timestamp: 2026-09-08T01:31:00+08:00
  checked: web/src/app/globals.css topology and tab rules.
  found: .workspace-tabs is an unbounded no-wrap flex row with no overflow containment; the 900px responsive block adjusts topology stage/drawer only and has no tab treatment.
  implication: Finding 7 is a deterministic CSS containment bug. A narrow-screen contained horizontal tab scroller is the smallest fix and keeps all five labels available without widening the document.
- timestamp: 2026-09-08T01:35:00+08:00
  checked: 12-UI-SPEC.md C-1/C-2/C-3, responsive, accessibility, and performance clauses.
  found: C-3 requires candidates to remain searchable/filterable but does not require unattached candidates to be shown by default. C-1 explicitly hard-codes 100 rows for card lists and therefore must be amended before using the review-approved 20-25 density. The current performance contract has a node-only guard and explicitly forbids automatic timeouts, but does not forbid an operator Cancel control.
  implication: Default-hiding only unattached private-link candidates behind an explicit checkbox is contract-compatible; finding 8 requires a spec amendment to 20 cards; long full-detail loads should retain context, show elapsed progress, and offer explicit abort rather than a timeout.
- timestamp: 2026-09-08T01:35:00+08:00
  checked: SBFL prerequisites.
  found: The existing suites have no failing tests for these nine findings, so there is no failing/passing spectrum to rank.
  implication: SBFL is skipped with a logged reason; use direct deterministic regression tests and working-backwards fault localization.
- timestamp: 2026-09-08T01:39:00+08:00
  checked: Pre-change focused baseline.
  found: Backend topology/API/contract baseline passed 112 tests; focused web baseline passed 176 tests across seven files. Only known Cytoscape mapping warnings and the existing Vite CJS notice appeared.
  implication: New focused regressions can be attributed to the nine reported behaviors rather than pre-existing test failures.
- timestamp: 2026-09-08T01:44:00+08:00
  checked: Failing-first backend regressions.
  found: 5 focused failures reproduce absent server build timing, path-safe ARM id 404, isolated-existing VNet 404, stale-at-insertion hybrid cache re-query (2 calls instead of 1), and missing mobile tab containment; 127 adjacent assertions passed.
  implication: Backend/routing/responsive hypotheses are confirmed with specified or derived-contract oracles.
- timestamp: 2026-09-08T01:44:00+08:00
  checked: Failing-first web regressions.
  found: 15 focused failures reproduce destructive detail transition, missing abort, 100-card paging, lossy client path, unfiltered unattached candidates, all-node degraded layout, missing resize refit, wheel override, missing latency guard/progress/cancel, missing candidate disclosure, and non-alert dependency errors; 168 adjacent assertions passed.
  implication: All nine review findings now have a RED regression or a directly coupled regression pair before production edits.
- timestamp: 2026-09-08T01:57:00+08:00
  checked: First post-fix focused run.
  found: All behavior regressions passed except two source-test path mistakes; TypeScript exposed an internal-state Omit type and mock-prop typing issue. Backend behavior regressions passed, but dynamically measuring each route response broke the frozen default/full byte identity.
  implication: The fixes are behaviorally aligned, but build duration must come from the cached provider observation (stable across detail requests) rather than per-response wall time; test harness path/types must be corrected without weakening assertions.
- timestamp: 2026-09-08T02:00:00+08:00
  checked: Corrected focused GREEN run.
  found: Backend suite passed 133 tests, focused web suite passed 188 tests, and TypeScript completed with zero diagnostics. The server now publishes the cached provider build duration, preserving byte-identical default/full behavior for managed snapshots.
  implication: Unit/integration behavior for all nine findings is green; remaining work is contract documentation, real-browser acceptance, broader gates, and anti-overfitting checks.
- timestamp: 2026-09-08T02:05:00+08:00
  checked: C-1 specification and browser-acceptance coverage.
  found: The UI spec now explicitly uses 20 cards for both server-paged finding lists and documents the deployed 15,763px evidence that invalidated the original 100-row assumption. A new isolated Playwright spec mocks the network APIs and checks candidate disclosure/toggle, retained summary plus delayed-load Cancel, painted canvas after resize, and tab containment/usability at 390px.
  implication: Finding 8 is now an explicit contract amendment rather than a silent implementation drift, and findings 1/2/4/5/6/7 have browser-ready acceptance coverage.
- timestamp: 2026-09-08T02:10:00+08:00
  checked: First Playwright acceptance run and accompanying focused gates.
  found: Backend passed 150 tests and TypeScript passed. Two of three Playwright tests passed (candidate projection and 390px canvas/tabs). The slow-detail test found a real race: requested detail changed to full one render before useApi committed loading=true, so an effect incorrectly relabelled retained summary data as full. One source-contract test also sliced too few characters to reach the debounce constant.
  implication: Preserve the dependency identity associated with resolved data inside useApi; derive the rendered detail from that identity. This fixes truthful footnote/export labeling without changing request semantics.
- timestamp: 2026-09-08T02:15:00+08:00
  checked: Corrected focused suites and strengthened browser acceptance.
  found: Focused web passed 189 tests, backend passed 150 tests, TypeScript and ESLint passed, Ruff passed, and all 3 real-Chromium network acceptance tests passed. Browser checks include painted canvas after a 1440→390 resize, >55% horizontal ink use with candidates hidden, all tabs usable at 390px, 20-card gaps pagination, no wheel-sensitivity warning, retained summary labeling, elapsed progress, and Cancel.
  implication: The implemented behavior is ready for full-suite regression validation.
- timestamp: 2026-09-08T02:21:00+08:00
  checked: Full backend and web quality gates.
  found: Full pytest passed; full web Vitest passed 578 tests across 56 files; TypeScript, Next ESLint, and the production build passed. The build retained pre-existing non-fatal MSAL server-render logs. Repository-wide Ruff reported 27 pre-existing findings confined to unrelated infra/scripts paths; Ruff on every changed Python path passed.
  implication: No product regression is detected. The repository-wide Ruff baseline remains red outside this session's ownership and must be recorded rather than modified.
- timestamp: 2026-09-08T02:28:00+08:00
  checked: Full Playwright and fix-acceptance guardrail.
  found: Full Playwright passed 10 tests with the credential-gated deployed test skipped. With only production fixes temporarily stashed, all 5 backend/CSS probes and the web behavior regressions returned to RED; after reapply, the same focused set passed. No Stryker binary or configuration exists. The production diff adds behavior and tests and is not deletion-only.
  implication: Revert-and-reconfirm and no-op/deletion signals pass; mutation testing is explicitly skipped as unavailable. One remaining performance boundary is that the 30-second cache can expire during an ordinary multi-minute inspection even after completion-time stamping.
- timestamp: 2026-09-08T02:31:00+08:00
  checked: Hybrid-cache interaction-window boundary.
  found: A strengthened regression failed with the 30-second value after simulating a 45-second acquisition and a follow-up 155 seconds after completion; it passed after the scoped hybrid network TTL changed to 300 seconds. Full pytest and changed-path Ruff passed afterward.
  implication: Summary, Full detail, and hub/drill-down interactions now reuse one completed observation throughout a normal operator workflow without changing unrelated provider-cache intervals.
- timestamp: 2026-09-08T02:33:00+08:00
  checked: Concurrent repository activity.
  found: While this session was running, commit dd79802c3 moved HEAD/origin and included the hybrid-network completion-time refactor plus its initial runtime regression under a concurrent exposure commit. This session did not create or push that commit; subsequent work preserved it and adds only the five-minute boundary plus the remaining topology paths.
  implication: Do not rewrite or revert the concurrent commit. Final staging/commit, if later authorized after human verification, must explicitly include only still-uncommitted session paths.
- timestamp: 2026-09-08T02:35:00+08:00
  checked: Required planning artifacts and deployment-ready acceptance.
  found: 12-UI-SPEC.md contains the 20-card, latency, candidate-visibility, responsive, and five-minute cache amendments. 12-UI-REVIEW.md dispositions all nine findings and records the exact credential-gated Playwright command and evidence requirements. Final diff whitespace and changed-path Ruff checks pass; no generated browser artifacts are untracked.
  implication: Self-verification is complete. The session must remain open at the human/deployment checkpoint because the live app still runs the pre-fix revision.
- timestamp: 2026-09-08T09:58:00+08:00
  checked: Pre-deployment review response, repository status excluding protected Terraform state paths, and active planning scope.
  found: Review identified five deterministic source/test hardening issues. Phase 03.1 remains active, but the user explicitly authorized this Phase 12 post-implementation remediation. The worktree contains concurrent modified files, so edits must stay limited to the topology review paths and .gitignore while preserving all unrelated changes.
  implication: Reopen the session as investigating, reproduce each review issue failing-first, and rerun every requested gate before returning to the deployment checkpoint.
- timestamp: 2026-09-08T10:04:00+08:00
  checked: Complete TopologyWorkspace, TopologyGraph, their tests, the deployed Playwright spec, page integration, and .gitignore.
  found: "Workspace has an unconditional `if (error)` replacement branch; `fullDetailPending` has no context-reset effect; its final warning-copy branch dereferences `topologyBuildDurationMs!`; graph resize/wheel assertions read source text instead of mounting the component; the deployed spec combines all findings and silently bypasses candidate, confirmation, duration, and empty-dependent branches; .gitignore names only two fixed Terraform state filenames."
  implication: "The review findings are directly observable deterministic code/test gaps. Add RED workspace and ignore regressions first, replace graph source inspection with component behavior tests, and split live acceptance into named independent outcomes with explicit skips only for absent live data."
- timestamp: 2026-09-08T10:01:00+08:00
  checked: "Failing-first TopologyWorkspace regressions (33 focused tests)."
  found: "Exactly the three new assertions failed while 30 adjacent tests passed: retained topology was replaced by the error StatePanel, and full-detail confirmation remained visible after both summary and scope changes."
  implication: "The supplied workspace findings are reproduced independently of the already-green adjacent behavior; the error-branch and pending-context hypotheses are confirmed."
- timestamp: 2026-09-08T10:02:00+08:00
  checked: "Single retained-summary error regression after the minimal branch change."
  found: "The new regression passed: retained graph and summary labeling remained mounted while the request failure rendered as an alert."
  implication: "Review issue 1 is fixed at its causal branch without changing the no-topology StatePanel path."
- timestamp: 2026-09-08T10:03:00+08:00
  checked: "Pending-detail context regressions after the scoped state reset and total duration branch."
  found: "Both summary-change/NaN and scope-change regressions passed."
  implication: "Review issue 2 is fixed: confirmation state no longer crosses its source context and undefined duration is never formatted."
- timestamp: 2026-09-08T10:04:00+08:00
  checked: "Non-creating Git ignore probe for `infra/terraform/review-probe.tfstate.20260908`."
  found: "Probe exited 1 before the fix."
  implication: "Review issue 3 is reproduced without inspecting, creating, or exposing any Terraform state artifact."
- timestamp: 2026-09-08T10:05:00+08:00
  checked: "The exact hypothetical timestamped-state ignore probe after adding the directory-scoped wildcard."
  found: "Probe exited 0; no state file was created, enumerated, read, moved, hashed, or deleted."
  implication: "Review issue 3 is fixed while respecting the protected Terraform-state constraint."
- timestamp: 2026-09-08T10:06:00+08:00
  checked: "Mounted TopologyGraph behavior suite with controlled ResizeObserver, fake timers, and a Cytoscape option probe."
  found: "All four tests passed: 47px resize called only resize; 49px resize called resize then reduced-motion fit; unmount disconnected and removed the pending timer; the actual Cytoscape constructor options omitted wheelSensitivity."
  implication: "Behavioral coverage can replace the two source-string assertions without reducing the protected contract."
- timestamp: 2026-09-08T10:07:00+08:00
  checked: "Focused TopologyGraph suite after deleting source-string assertions."
  found: "Both files passed: 18 pure behavior/contracts plus 4 mounted browser-integration tests."
  implication: "Review issue 4 is fixed; resize, teardown, and constructor-option behavior is now tested through execution rather than source text."
- timestamp: 2026-09-08T10:13:00+08:00
  checked: "TypeScript and Playwright discovery for the rewritten deployed acceptance."
  found: "TypeScript completed with zero diagnostics. Playwright listed 10 independent finding-labelled tests: two explicit finding-2 tests and one test for each other finding."
  implication: "Review issue 5 is structurally fixed; live-data skips are reasoned, while latency, painted canvas, width, mobile tabs, and console checks are unconditional."
- timestamp: 2026-09-08T10:14:00+08:00
  checked: "Focused backend and web regressions after all five review fixes."
  found: "Backend passed 152 tests; web passed 194 tests across eight topology/page/hook files, including all three new workspace regressions and four new mounted graph behaviors."
  implication: "Focused validation is green; proceed to real-browser acceptance and then the full gate matrix."
- timestamp: 2026-09-08T10:15:00+08:00
  checked: "Focused local Chromium acceptance."
  found: "All 3 mocked topology browser scenarios passed; the 10 independent deployed tests were explicitly skipped because AIOPS_LIVE_NETWORK_E2E is disabled."
  implication: "Real browser behavior remains green locally and deployed-only coverage no longer appears as one opaque skipped test."
- timestamp: 2026-09-08T10:17:00+08:00
  checked: "Full backend, web unit, type, and lint gates."
  found: "Full pytest exited 0; full Vitest passed 57 files and 583 tests; TypeScript reported zero diagnostics; Next ESLint reported zero warnings or errors. Only pre-existing deprecation and component-library test warnings were emitted."
  implication: "No backend, unit, type, or lint regression remains; proceed to full browser and production-build gates."
- timestamp: 2026-09-08T10:18:00+08:00
  checked: "Complete local Playwright suite."
  found: "10 locally runnable Chromium tests passed and all 10 deployed topology tests skipped with the explicit live-mode gate."
  implication: "The full browser gate is green; only the production build and final source/diff review remain."
- timestamp: 2026-09-08T10:20:00+08:00
  checked: "Next.js production build, diff whitespace, unsafe-pattern scan, worktree scope, and repository-wide Ruff."
  found: "Production build compiled, type/lint checked, generated all 28 pages, and exited 0 with the pre-existing non-fatal MSAL server-render logs. Diff whitespace passed and forbidden source-test/non-null/wheel patterns are absent. Repository-wide Ruff still reports the same 27 pre-existing findings confined to unrelated infra/scripts paths."
  implication: "All requested application gates are green. The documented Ruff technical-debt exception remains outside this authorized remediation and must not be altered; verify changed topology Python paths separately."
- timestamp: 2026-09-08T10:22:00+08:00
  checked: "Changed topology Python lint and scoped diff shape."
  found: "Ruff passed every changed topology backend/test path. The continuation diff is additive/behavioral: it adds explicit state handling and regressions rather than deleting or short-circuiting product behavior."
  implication: "The no-op/deletion guardrail passes; update the authoritative review and perform final read-only hygiene checks."
- timestamp: 2026-09-08T10:24:00+08:00
  checked: "Final source hygiene, test structure, worktree scope, and authoritative Phase 12 review."
  found: "Diff whitespace is clean; no generated artifacts appeared; deployed acceptance contains 10 finding-labelled tests and exactly 3 reasoned live-data precondition messages; unsafe/source-string patterns are absent; 12-UI-REVIEW.md records all five follow-up dispositions and final gate counts."
  implication: "The source is clean and ready for deployment. The session remains open only for authorized deployment and authenticated end-to-end verification."
- timestamp: 2026-09-08T10:26:00+08:00
  checked: "Terminal-criterion reconciliation against the debug record, authoritative UI review, scoped diff, and current repository status."
  found: "git diff --check exits 0; the topology source contains no asserted-duration, custom wheel-option, or source-string graph-test pattern; the deployed spec still exposes 10 independent finding-labelled tests, with one suite-level live/auth gate and exactly three data-precondition skips; the timestamped Terraform-state ignore probe exits 0. Unrelated concurrent Phase 03.1 work remains present and untouched."
  implication: "No source inconsistency requires another code change. The user-defined terminal criterion is met: close this source-debug session without deploying, committing, or pushing, and retain authenticated runtime acceptance as pending post-deploy evidence."
- timestamp: 2026-09-08T11:13:42.686+08:00
  checked: "Authenticated post-deployment acceptance for tag network-topology-fix-20260908-0115."
  found: "The deployed suite passed 8 checks and failed 2: five-sample full-detail p95 was 14,397 ms, and the hub-dependents request returned 404 for a hub present in the same summary. Direct authenticated requests kept summary/full/gaps/rule-findings at approximately 9–22 seconds while /network/policy was approximately 0.8 seconds."
  implication: "The preserved p95 <1s gate is genuinely red after deployment; both failures are deterministic enough for failing-first Bohrbug regressions rather than acceptance-gate relaxation."
- timestamp: 2026-09-08T11:14:00+08:00
  checked: "Repository status, recent commits, active scope, and concurrent work before reopening."
  found: "HEAD is 76df9c420 on main. Phase 03.1 remains active, but the user explicitly authorizes this Phase 12 post-deployment remediation. .azure/deployment-plan.md and web/e2e/network-topology-deployed.spec.ts already contain unstaged concurrent edits; neither may be overwritten or broadly staged."
  implication: "Move the resolved record to the canonical active path, preserve unrelated hunks, and stage only exact owned paths/hunks after all gates pass."
- timestamp: 2026-09-08T11:14:20+08:00
  checked: "Semantic/durable knowledge recall and SBFL prerequisites."
  found: "MemPalace is unavailable; keyword fallback in knowledge-base.md has no two-token match for ProviderRuntime.get request-thread I/O or slash-losing ARM hub routes. Existing suites are green and no failing per-test coverage spectrum exists yet, so SBFL is skipped."
  implication: "No known resolution is assumed. Use failing-first focused regressions, working backwards from the slow request and actual ASGI route."
- timestamp: 2026-09-08T11:16:00+08:00
  checked: "Current hub route, service canonicalization, web client contract, and deployed Playwright route construction."
  found: "The server still exposes /topology/hubs/{vnet_id:path}/dependents; both the web client and deployed acceptance strip the leading slash and percent-encode the remainder into that path. The service re-adds a slash, but the live route still delivers an identifier without it and returns 404."
  implication: "The previous strip-and-readd compatibility fix did not make the public contract robust across the deployed route stack. A query-param route must be exercised through FastAPI TestClient, with the path form retained only as a legacy adapter if compatibility requires."
- timestamp: 2026-09-08T11:19:00+08:00
  checked: "Complete ProviderRuntime implementation, network provider cache-key construction, background startup loop, and provider lifecycle tests."
  found: "ProviderRuntime.get calls _refresh_changed_cache_key twice, refresh(blocking=False) once, and _read_cache_key once. _refresh_changed_cache_key can acquire _refresh_lock and call _refresh_provider synchronously; refresh(blocking=False) also runs every provider loader synchronously whenever the lock is free and the interval is due. Each network cache-key read calls Fabric semantic_version() and policy revision. The dedicated app thread already force-refreshes immediately at startup and periodically thereafter."
  implication: "The get() docstring's nonblocking guarantee is false: blocking=False controls lock acquisition, not loader/cache-key I/O after acquisition. The deployed endpoint differential is explained because topology/gaps/findings resolve the managed network provider while /network/policy does not. get() must become a state-only LKG read; startup/background refresh already owns the required freshness work."
- timestamp: 2026-09-08T11:19:30+08:00
  checked: "Existing provider regressions."
  found: "The suite currently pins the defect: changed cache keys are expected to rebuild from get(), including one test where a get() caller becomes the refresh owner and blocks in the loader. No startup test proves an unloaded request remains I/O-free while the initial background refresh is in flight."
  implication: "Replace the defect-pinning expectations with specified LKG/nonblocking concurrency and startup contracts, then confirm they fail before changing ProviderRuntime."
- timestamp: 2026-09-08T11:22:00+08:00
  checked: "Failing-first provider, startup, routing, and web client regressions."
  found: "All five intended assertions failed before production edits. A single changed-key get made seven cache-key/loader calls; four concurrent gets added twelve calls while a background refresh owned the lock; an initial get during background startup added three cache-key calls; the FastAPI query route returned 404; and the web client still built /hubs/{encoded-id}/dependents."
  implication: "Both post-deployment failures are reproduced at their causal boundaries with specified-contract oracles. The root causes are confirmed; proceed to surgical fixes."
- timestamp: 2026-09-08T11:24:00+08:00
  checked: "First GREEN run of the exact failing-first regressions."
  found: "All four Python provider/startup/TestClient route tests passed, and all 10 web network client tests passed. The p95 assertion remains unchanged at less than 1,000 ms; the legacy hub path remains registered."
  implication: "The minimal code changes satisfy both causal regressions. Adjacent provider refresh, runtime, API, client, and browser structure suites must now confirm no collateral regression."
- timestamp: 2026-09-08T11:26:00+08:00
  checked: "Complete focused provider/runtime/network suites plus focused web, type, and changed-path lint."
  found: "Web passed 100 tests, TypeScript passed, and Ruff passed. Python passed 129 tests but exposed two old lifecycle assumptions: build_context was expected to lazy-load without app startup, and a policy request was expected to synchronously rebuild the provider on the next request."
  implication: "These assertions conflict with the confirmed strict-LKG contract. Preserve their underlying behavior by moving loading/invalidation to explicit startup/background refresh in the tests; do not regress to request-thread I/O."
- timestamp: 2026-09-08T11:28:00+08:00
  checked: "Focused rerun after aligning lifecycle tests with startup/background ownership."
  found: "Backend provider/runtime/network suites passed 131 tests; focused web passed 100 tests; changed-path Ruff and TypeScript passed; Playwright discovery lists all 10 independent deployed checks, including the unchanged five-sample p95 <1,000 ms test and the query-based hub check."
  implication: "Focused and adjacent verification is clean. Proceed to the full source-readiness and anti-overfitting guardrails."
- timestamp: 2026-09-08T11:34:00+08:00
  checked: "First full backend/web and repository lint gates."
  found: "Full Vitest passed 57 files and 583 tests. Full pytest passed 3,825 tests but six tests in test_exposure_consumer_parity.py failed because their production_consumers fixture resolved exposure_read_port from a freshly built context before any API startup/background refresh. Repository-wide Ruff remains at the same 27 unrelated infra/scripts findings recorded before this remediation."
  implication: "The product fix is not accepted yet. Align the isolated direct-context fixture with the new startup lifecycle, rerun its module, then rerun full pytest. Do not touch the unrelated Ruff baseline."
- timestamp: 2026-09-08T11:36:00+08:00
  checked: "Phase 03.1 exposure consumer parity after fixture lifecycle alignment."
  found: "All 11 tests passed and Ruff is clean for the adjusted fixture. The domain assertions are unchanged; setup now explicitly runs the startup refresh that create_app normally starts."
  implication: "The full-suite failures were isolated to test lifecycle setup and are corrected without altering Phase 03.1 behavior. Rerun the definitive full backend gate."
- timestamp: 2026-09-08T11:43:00+08:00
  checked: "Definitive full backend, full web, ESLint, TypeScript, production build, and changed-path Ruff gates."
  found: "Full pytest passed 3,831 tests; full Vitest passed 57 files and 583 tests; TypeScript, ESLint, production build, and Ruff on every changed Python path passed. The build emitted only the previously documented non-fatal MSAL server-render logs. Repository-wide Ruff remains the unchanged 27 unrelated infra/scripts findings."
  implication: "All application source-readiness gates run so far are clean. Complete local browser acceptance and anti-overfitting/revert proof next."
- timestamp: 2026-09-08T11:45:00+08:00
  checked: "Complete local Playwright invocation."
  found: "All 3 local topology scenarios passed and all 10 authenticated deployed topology checks skipped behind their explicit live gate. The overall command reported 10 passed, 10 skipped, and one unrelated pre-existing Phase 13 ontology test failure because that test requires an https deployed URL while the local runner uses http://127.0.0.1."
  implication: "Phase 12 browser source readiness is clean; the repository-wide Playwright baseline has one out-of-scope environment-contract failure in an untouched file. Preserve it and record the exact exception rather than editing concurrent Phase 13 scope."
- timestamp: 2026-09-08T11:48:00+08:00
  checked: "Fix-acceptance revert-and-reconfirm."
  found: "With only src/api/providers.py, src/api/routers/network.py, and web/src/lib/services.ts restored to HEAD, all four backend causal tests and the web query-contract test returned to RED. Reapplying the exact minimal source hunks restored 4/4 backend and 10/10 web tests to GREEN; focused Phase 12 Playwright passed 3 local tests with 10 deployment-gated skips."
  implication: "The production changes, rather than test weakening or ambient state, cause both fixes. Guardrail signal 5 passes."
- timestamp: 2026-09-08T11:50:00+08:00
  checked: "Authoritative Phase 12 readiness and review records."
  found: "12-UI-REVIEW.md and 12-VERIFICATION.md now record the 8-pass/2-fail deployed result, p95 14,397 ms, exact two root causes, RED-to-GREEN evidence, full gate results, pending redeploy status, and the unchanged p95 <1,000 ms acceptance criterion."
  implication: "Planning evidence no longer presents the failed deployment as merely pending or live-passing; source readiness and remaining live verification are separated explicitly."
- timestamp: 2026-09-08T11:52:00+08:00
  checked: "Final source and scope hygiene."
  found: "git diff --check passed; the deployed acceptance still asserts p95 <1,000 ms; no _refresh_changed_cache_key, request-time refresh(blocking=False), or request-time cache-key read remains in ProviderRuntime.get; query route/client/test references agree. No Stryker dependency or configuration exists."
  implication: "The source fix passes the acceptance guardrail. Commit only owned paths and only the route hunk from the concurrently modified deployed spec; leave .azure/deployment-plan.md and session-storage edits unstaged."

## Eliminated

- hypothesis: "The five-minute hybrid ARG cache TTL or topology serialization is the primary cause of every 9–22 second warm request."
  evidence: "The cache already reuses completed ARG rows for five minutes, in-memory scale gates are sub-second, and the slow endpoints all execute ProviderRuntime.get cache-key I/O while the fast policy endpoint bypasses it."
  timestamp: 2026-09-08T11:22:00+08:00
- hypothesis: "One API replica alone causes the latency."
  evidence: "Replica count can amplify contention but cannot explain deterministic cache-key/loader calls in get(); the policy route on the same replica remains approximately 0.8 seconds."
  timestamp: 2026-09-08T11:22:00+08:00
- hypothesis: "Server-side slash re-addition makes the current hub path contract safe."
  evidence: "The deployed response still loses the leading slash and 404s, while the new TestClient query route is absent and RED. Canonicalization after a lossy transport cannot recover an identifier that routing changed ambiguously."
  timestamp: 2026-09-08T11:22:00+08:00
- hypothesis: The 349KB topology payload or in-memory projection algorithm is the primary cause of the 146-second response.
  evidence: Enterprise TopologyBuilder remains below the one-second gate; detail does not alter live ARG acquisition, while both slow endpoints cross the stale-at-insertion cache path.
  timestamp: 2026-09-08T01:23:00+08:00
- hypothesis: The resize blank and request latency are intermittent concurrency defects.
  evidence: Both reproduce from deterministic pan/zoom retention and cache age predicates, and the focused tests fail on every pre-fix run.
  timestamp: 2026-09-08T01:35:00+08:00

## Resolution

root_cause:
  - Detail level is treated as a destructive useApi identity change, so the previous topology envelope is nulled instead of retained.
  - hybrid_network stores the cache timestamp from before live ARG acquisition; requests slower than the 30-second TTL are stale immediately, and even completion-time entries expire during an ordinary multi-minute workflow, causing topology and hub requests to repeat the upstream query. No server build-duration signal, elapsed UI state, or cancellation path exists.
  - The client encodes a slash-prefixed ARM id as one path segment, the deployed route stack loses the leading slash, the service does not canonicalize it, and the router infers absence from empty result values instead of explicit snapshot membership.
  - All unattached private-link candidates enter the primary graph, node budget, component packing, and fit bounds; this overwhelms and horizontally compresses the connected topology.
  - ResizeObserver updates Cytoscape canvas dimensions without recomputing fit, leaving the old pan/zoom off-screen after major viewport changes.
  - The five-tab flex row has no narrow-width overflow containment.
  - C-1 incorrectly selected a 100-row table default for approximately 200px finding cards, so 77 records never paginate.
  - TopologyGraph sets Cytoscape wheelSensitivity=0.2 despite the library warning against custom values.
  - TopologyWorkspace treats any refresh error as terminal even when retained topology exists.
  - Full-detail confirmation state is not invalidated by scope/summary replacement, and its fallback warning formats an asserted duration that may be absent.
  - Terraform ignore configuration enumerates fixed state filenames but omits timestamp-suffixed `.tfstate` backups.
  - Resize/wheel regressions inspect source strings rather than executing observer, timer, teardown, and constructor-option behavior.
  - The deployed acceptance combines every finding into one test and silently bypasses data-dependent branches.
post_deployment_root_cause:
  - "ProviderRuntime.get was not a last-known-good read: it synchronously resolved cache keys up to three times and could execute provider loaders after acquiring a nonblocking refresh lock. For the network provider, every cache-key resolution called Fabric semantic_version() plus policy revision, putting 9–22 second freshness I/O on each request thread."
  - "Hub ARM identity was still transported in a wildcard path segment. The deployed route stack normalized the slash-bearing value and the service received a non-identical id, so membership validation returned 404 even though the summary contained the hub."
fix:
  - Added scoped dependency retention and AbortController cancellation to useApi; the network detail request retains summary data only when the canonical scope key is unchanged, tracks rendered detail separately, and exposes elapsed full-detail progress plus Cancel.
  - Timestamped the hybrid network cache after live ARG completion, extended only that scoped cache to a five-minute operator window, and added measured topology build duration to the summary for a latency-aware full-detail guard.
  - Canonicalized slash-stripped hub path ids server-side, switched the client to a routable encoded path, and made 404 depend on actual snapshot membership.
  - Default-filtered only unattached private-link candidates when primary topology exists, disclosed/toggled them in the toolbar, and based fCoSE quality on connected nodes.
  - Debounced resize handling and refit the viewport, removed custom wheelSensitivity, contained the tab row horizontally, reduced card-list pages to 20, and rendered dependency failures as critical alerts.
  - Kept retained topology mounted on refresh errors with a non-destructive alert, reset pending confirmation on scope/summary changes, and made all duration-warning branches total.
  - Added the directory-scoped `infra/terraform/*.tfstate*` ignore rule without accessing existing state artifacts.
  - Replaced source-string graph assertions with four mounted ResizeObserver/fake-timer/Cytoscape-option tests.
  - Split deployed acceptance into ten independent finding-labelled tests with explicit live-data skips and unconditional latency/canvas/mobile/console checks.
post_deployment_fix:
  - "Made ProviderRuntime.get a state-lock-only last-known-good read with no cache-key, metadata, freshness, or loader calls; the existing immediate-startup and periodic background refresh loop remains the sole refresh owner."
  - "Added GET /api/v1/network/topology/hubs/dependents?vnet_id=... with exact query transport and shared membership/empty-envelope behavior, retained the legacy wildcard route, and switched the web client and deployed acceptance to the query route."
post_deployment_verification:
  target_test:
    result: pass
    details: "4 backend causal regressions and 10 web client assertions pass; the three provider tests cover ordinary, concurrent, and initial-startup reads, and FastAPI TestClient covers actual query routing."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker dependency or configuration is present."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    details: "Deleting request-triggered refresh/cache-key logic is the causal fix; background refresh remains intact and is directly covered. Routing adds a query contract while retaining the legacy path."
  adjacent_tests:
    result: pass
    suites_run:
      - "focused provider/runtime/network backend — 131 passed"
      - "focused network web — 4 files, 100 passed"
      - "full pytest — 3,831 passed"
      - "full Vitest — 57 files, 583 passed"
      - "TypeScript noEmit"
      - "Next ESLint"
      - "Next production build"
      - "Phase 12 local Playwright — 3 passed, 10 deployment-gated skipped"
      - "Ruff on every changed Python path"
    caveat: "Complete local Playwright has one unrelated pre-existing Phase 13 HTTPS-only failure; repository-wide Ruff retains 27 unrelated infra/scripts findings."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    details: "Restoring only the three causal production files made all four backend and the web client regression fail; reapplying restored every test to green."
  guardrail_verdict: accepted
  deployed_live:
    result: pending_redeploy
    details: "No deployment or push was performed. The unchanged five-sample p95 <1,000 ms and query-route hub 200 checks require a later authorized deployment."
  source_ready_terminal:
    result: pass
    details: "Both post-deployment failures are regression-covered and all Phase 12 source-readiness gates are clean."
verification:
  target_test:
    result: pass
    details: "152 focused backend assertions, 194 focused web assertions, 4 mounted graph behaviors, and 3 mocked real-Chromium topology scenarios pass."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker binary or configuration is present."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    details: "Production diff is additive/behavioral, not deletion-only; removal of wheelSensitivity is explicitly justified by finding 9."
  adjacent_tests:
    result: pass
    suites_run:
      - "full pytest"
      - "full web Vitest — 57 files, 583 tests"
      - "TypeScript noEmit"
      - "Next ESLint"
      - "Next production build"
      - "full local Playwright — 10 passed, 10 independently named deployment-gated skipped"
      - "Ruff on every changed Python path"
    caveat: "Repository-wide Ruff remains pre-existing red with 27 unrelated infra/scripts findings."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    details: "The prior five backend/CSS and web behavior probes returned to RED with production fixes removed and passed after reapply; the new retained-error and two pending-context regressions ran RED before their source fixes and GREEN afterward; the timestamped-state probe changed from exit 1 to exit 0."
  guardrail_verdict: accepted
  deployed_live:
    result: pending_post_deploy
    in_session_scope: false
    details: "Not run against a deployed revision. The historical deployed 13/24 review remains authoritative for the currently deployed application; this pending gate must not be represented as a live pass."
    command: "AIOPS_LIVE_NETWORK_E2E=1 PLAYWRIGHT_BASE_URL=<deployed-origin> PLAYWRIGHT_STORAGE_STATE=<secure-auth-state> npx playwright test e2e/network-topology-deployed.spec.ts --project=chromium"
  source_ready_terminal:
    result: pass
    details: "All requested focused/full local gates and final hygiene checks pass. Per the user's explicit terminal criterion, this is sufficient to complete the source-debug session without deployment."
files_changed:
  - .gitignore
  - src/api/routers/network.py
  - src/api/runtime.py
  - src/network/service.py
  - tests/test_api_network.py
  - tests/test_api_runtime.py
  - tests/test_network_downstream_contracts.py
  - web/src/app/globals.css
  - web/src/app/network/page.tsx
  - web/src/app/network/page.test.tsx
  - web/src/components/network/TopologyDetailDrawer.tsx
  - web/src/components/network/TopologyDetailDrawer.test.tsx
  - web/src/components/network/TopologyGraph.tsx
  - web/src/components/network/TopologyGraph.test.tsx
  - web/src/components/network/TopologyGraph.behavior.test.tsx
  - web/src/components/network/TopologyWorkspace.tsx
  - web/src/components/network/TopologyWorkspace.test.tsx
  - web/src/hooks/useApi.ts
  - web/src/hooks/useApi.test.ts
  - web/src/lib/network-graph.ts
  - web/src/lib/network-graph.test.ts
  - web/src/lib/network-services.test.ts
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - web/e2e/network-topology-live-ui.spec.ts
  - web/e2e/network-topology-deployed.spec.ts
  - web/playwright.config.ts
  - .planning/phases/12-network-topology-integrity-and-scale/12-UI-SPEC.md
  - .planning/phases/12-network-topology-integrity-and-scale/12-UI-REVIEW.md
  - src/api/providers.py
  - tests/test_api_providers.py
  - src/api/app.py
  - tests/test_exposure_consumer_parity.py
  - .planning/phases/12-network-topology-integrity-and-scale/12-VERIFICATION.md
oracle_type: specified and derived-contract
post_deployment_oracle_type: specified

## Prevention

why_not_caught: "The earlier source-contract audit did not exercise deployed data shape, routing normalization, acquisition latency/cache age, real resize behavior, or retained request state; several follow-up tests also inspected source text or aggregated live dispositions instead of executing independent behavior."
recurrence_guard: "Focused RED→GREEN backend/web regressions, mounted ResizeObserver/Cytoscape behavior coverage, three mocked Chromium topology scenarios, and ten independent authenticated post-deploy checks in web/e2e/network-topology-deployed.spec.ts."
post_deploy_gate: "Pending by design and outside this session. Run only after a later authorized deployment with secure authenticated storage state; preserve explicit data-precondition skips and do not treat the pending gate as a current live pass."
