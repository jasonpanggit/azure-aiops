---
status: resolved
trigger: "Troubleshoot and fix all findings and errors from the authenticated Playwright review of the deployed /network experience."
created: 2026-09-08T01:10:00+08:00
updated: 2026-09-08T10:27:00+08:00
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
hypothesis: "Confirmed: all requested source fixes satisfy the user-defined source-readiness terminal criterion; deployment and authenticated live execution belong to the later post-deploy gate."
test: "Completed focused/full local gates, final diff hygiene, scoped unsafe-pattern checks, deployed-suite structure checks, and cross-artifact review."
expecting: "Complete — the source-ready result is closed without claiming deployment, while the authenticated runtime suite remains explicitly pending post-deploy."
next_action: "None in this session. A later authorized deployment process owns the documented authenticated Playwright gate."
reasoning_checkpoint:
  hypothesis: "The five pre-deployment findings came from an unconditional retained-error replacement, unscoped pending confirmation plus a partial numeric branch, exact-only ignore config, non-behavioral source tests, and monolithic conditional live acceptance."
  confirming_evidence:
    - "Three agent-authored workspace regressions failed before the fixes and passed afterward; the synthetic timestamped-state ignore probe likewise changed from exit 1 to exit 0."
    - "Mounted graph tests execute all four required observer/options behaviors, and Playwright discovery now exposes ten independent finding-labelled tests with three explicit data-precondition skip reasons."
    - "Focused and full backend/web/type/lint/Playwright/build gates pass; diff checks show no forbidden source-test, non-null duration, or custom wheel-option pattern."
  falsification_test: "A deployed run that loses retained canvas state, emits NaN/wheel warnings, misses resize fit, silently bypasses a data disposition, or fails any unconditional latency/canvas/mobile/console check would invalidate source readiness."
  fix_rationale: "Each production change is at its state/config boundary, and each test change executes observable behavior or isolates one live disposition instead of scanning implementation text or aggregating failures."
  blind_spots: "The working tree has not been deployed and this session has no authenticated storage state, so real-estate latency and visuals remain a required post-deployment checkpoint."
  candidate_causes:
    - "code: unconditional error rendering, stale local state, unsafe assertion, and weak test control flow"
    - "config: exact-only Terraform state ignore rules"
    - "environment: deployed auth/data/timing determine which live preconditions are available"
    - "data: retained topology plus a failed request, and replacement summaries with absent duration, expose the state defects"
  and_gate: "yes — the destructive error requires retained data plus a failed refresh; NaN required stale confirmation plus an absent replacement duration. The ignore/test-structure findings are independent."
review_follow_up:
  - "Retain topology on full-detail error and show a non-destructive alert."
  - "Reset fullDetailPending on scope/summary changes and remove the topologyBuildDurationMs non-null NaN path."
  - "Ignore infra/terraform/*.tfstate* without touching existing state backups."
  - "Replace source-string resize/wheel tests with behavioral ResizeObserver/fake-timer coverage."
  - "Split and harden deployed Playwright findings with explicit precondition skips."

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

## Eliminated

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
oracle_type: specified and derived-contract, to be recorded per focused regression

## Prevention

why_not_caught: "The earlier source-contract audit did not exercise deployed data shape, routing normalization, acquisition latency/cache age, real resize behavior, or retained request state; several follow-up tests also inspected source text or aggregated live dispositions instead of executing independent behavior."
recurrence_guard: "Focused RED→GREEN backend/web regressions, mounted ResizeObserver/Cytoscape behavior coverage, three mocked Chromium topology scenarios, and ten independent authenticated post-deploy checks in web/e2e/network-topology-deployed.spec.ts."
post_deploy_gate: "Pending by design and outside this session. Run only after a later authorized deployment with secure authenticated storage state; preserve explicit data-precondition skips and do not treat the pending gate as a current live pass."
