---
status: resolved
trigger: "Results incomplete callout remains; route table has no firewall edge; route-table drawer says findings may be incomplete despite 83 of 83 loaded."
created: 2026-09-08T15:20:00+08:00
updated: 2026-09-08T15:36:10.121+08:00
---

# Debug Session: Network Summary Messages and Links

## Symptoms

### Expected behavior

- Server-paged lists disclose their range inside the relevant tab without a permanent page-level warning.
- Summary topology preserves a meaningful route-table-to-firewall next-hop relationship when route nodes are intentionally omitted.
- A resource is confirmed clean when the exhaustive badge loaders completed untruncated and no resource-specific findings exist, regardless of the visible tab's page size.

### Actual behavior

- A page-level yellow callout says results are incomplete whenever the 20-row gap page is shorter than the total.
- Summary topology omits route nodes and consequently displays no route-table-to-firewall edge.
- Route-table drawer says findings may be incomplete even though 83 of 83 findings were loaded.

### Error messages

- `Results are incomplete. Showing 20 of 77 inspection gaps and 6 of 6 rule findings.`
- `Findings for this resource may be incomplete. 83 of 83 findings were loaded. This resource is not confirmed clean.`

### Timeline

- Reproduced after the Network message-semantics deployment on 2026-09-08.

### Reproduction

1. Open `/network` at All subscriptions.
2. Observe the page-level incomplete-results callout.
3. Open Topology and inspect the route table: no edge reaches the firewall in Summary.
4. Select the route table: drawer reports incomplete findings despite 83/83 loaded.

## Current Focus

hypothesis: Confirmed — three deterministic boundary defects independently caused the pagination warning, missing summary next-hop, and false-incomplete drawer state.
test: Completed — independent source review plus the recorded backend, web, and mocked-Chromium regression gates.
expecting: Satisfied — the user confirmed the source remediation fixed all three reported defects.
next_action: None — Phase 12 evidence is updated and this session is archived; staging and commit remain with the session manager.
bug_class: Bohrbug
candidate_causes:
  - code: Three representation layers conflate visible page coverage with global completeness or remove an intermediate graph node without contracting its meaningful path.
  - data: The defects are exposed only when totals exceed the visible page and when a VirtualAppliance route resolves to an observed firewall; ordinary production data triggers them but is not malformed.
  - config_environment: Page size and deployment do not create the defects; they only expose deterministic source behavior.
and_gate: Each symptom requires its code defect plus a boundary-shaped dataset, but no config/environment failure is required; the three reported issues are independent code causes rather than one chained cause.
reasoning_checkpoint:
  hypothesis: Ordinary page coverage is rendered as global incompleteness because page.tsx keys a permanent callout to page `coverage.truncated`; the summary next-hop disappears because topology.py omits Route nodes and silently discards both incident edges; the clean drawer is refused because TopologyWorkspace ORs visible-page truncation into independently exhaustive badge coverage.
  confirming_evidence:
    - The page RED test directly observed the permanent warning for valid 20-row pages while the owning tabs already expose `Showing 1–20 of N`.
    - The backend RED test passed the full-detail Route→Firewall assertion and failed only the summary RouteTable→Firewall assertion on the same normalized snapshot.
    - The drawer RED test directly observed `83 of 83 findings` from the exhaustive loader and still received the incomplete state when visible-page truncation was true.
    - Git history identifies the exact independent introductions in c1a85778b, a2b44bd7c, and b2aea03b8.
  falsification_test: Any current-code run in which the page warning is absent for totals above page size, the summary already contains RouteTable→Firewall, or the drawer confirms clean at 83/83 with `findingsTruncated=true` would disprove the corresponding cause; all three produced the opposite direct observation.
  fix_rationale: Keep pagination disclosure with each TablePagination and filter pagination-only provenance warnings; when Route is intentionally omitted, preserve its next-hop semantics by sourcing the summary edge at its retained RouteTable; let only the exhaustive badge loader determine drawer truncation while loader error/loading continue to gate cleanliness.
  blind_spots: Multiple routes from one table to the same firewall collapse to one summary edge by existing relationship identity; badge collections beyond the four-page budget must remain incomplete; non-pagination backend warnings must remain globally visible.
  candidate_causes:
    - code: Cross-layer representation logic conflates page and exhaustive coverage and drops an intentionally omitted graph intermediary without path contraction.
    - data: Totals above page size and a resolvable VirtualAppliance route expose the defects, but the fixtures prove the input is valid and complete.
    - config_environment: Direct unit/component reproduction rules out deployment configuration and runtime environment as required causes.
  and_gate: No shared multi-condition root cause joins all three issues. Each independent code defect requires only its normal boundary-shaped data trigger; fixes must address all three causes.
tdd_checkpoint:

## Evidence

- timestamp: 2026-09-08T15:20:00+08:00
  observation: Page callout is keyed directly to `gapCoverage.truncated || findingCoverage.truncated`.
  source: web/src/app/network/page.tsx
- timestamp: 2026-09-08T15:20:00+08:00
  observation: Summary explicitly omits route resources; next-hop relationships use route as their source.
  source: src/network/topology.py
- timestamp: 2026-09-08T15:20:00+08:00
  observation: Drawer `truncated` combines `findingsTruncated` from the visible paged list with `badgeCoverage.truncated` from the exhaustive loader.
  source: web/src/components/network/TopologyWorkspace.tsx
- timestamp: 2026-09-08T15:23:00+08:00
  checked: Active project scope and working tree
  found: STATE records Phase 12 Network Topology Integrity and Scale as completed/preserved; this session is corrective Phase 12 network work. Existing modified files are unrelated remediation/Fabric work.
  implication: The requested corrective network investigation is in scope, and relevant network-only files/tests/docs must be isolated from concurrent changes.
- timestamp: 2026-09-08T15:25:00+08:00
  checked: Debug knowledge base
  found: Two prior network sessions concern provider refresh/routing and latency-budget instrumentation, not pagination messaging, summary edge projection, or drawer completeness.
  implication: No known-pattern root cause matches these symptoms; investigate the current code and Phase 12 contracts directly.
- timestamp: 2026-09-08T15:27:00+08:00
  checked: Recent history for the three involved source areas
  found: The newest shared commit is 511faadfd, titled `fix(network): clarify message semantics`, immediately preceding the reported post-deployment symptoms.
  implication: This is a falsifiable regression-point candidate for UI message semantics; summary topology behavior still requires independent history/code evidence.
- timestamp: 2026-09-08T15:32:00+08:00
  checked: Current page, summary projection, workspace, drawer, and focused tests
  found: The page renders `Results are incomplete` whenever either first server page is truncated even though each tab already owns `TablePagination`; summary excludes `Route` entities and silently drops relationships touching intentionally omitted IDs; workspace passes `findingsTruncated || badgeCoverage.truncated` although `badgeCoverage` is independently loaded to exhaustion.
  implication: The three symptoms are deterministic representation-boundary defects, not provider data loss or asynchronous timing failures.
- timestamp: 2026-09-08T15:32:00+08:00
  checked: Existing regression coverage
  found: Existing tests separately assert full-detail Route→Firewall, generic drawer truncation behavior, and exhaustive badge totals, but no test asserts summary RouteTable→Firewall contraction or that exhaustive badge coverage overrides visible-page truncation. The page test explicitly locks the unwanted page-level warning.
  implication: Missing cross-boundary assertions allowed all three issues through despite strong component-level coverage.
- timestamp: 2026-09-08T15:36:00+08:00
  checked: Introducing commits
  found: c1a85778b introduced the page-level warning alongside tab pagination; a2b44bd7c introduced summary Route omission plus silent suppression of edges touching omitted nodes; b2aea03b8 introduced the `findingsTruncated || badgeCoverage.truncated` combination.
  implication: Git history independently localizes each deterministic defect to a specific boundary change; commit 511faadfd only preserved/relabeled the page warning and did not originate the drawer defect.
- timestamp: 2026-09-08T15:36:00+08:00
  checked: Spectrum-based fault localization eligibility
  found: Existing focused suites have passing tests but no pre-existing failing test for these reported behaviors.
  implication: SBFL is skipped because there is no failing spectrum; failing-first regressions will supply direct reproduction instead.
- timestamp: 2026-09-08T15:39:00+08:00
  checked: Failing-first page regression
  found: The new test fails because the DOM contains the permanent `Incomplete network analysis results` status with `Results are incomplete` for ordinary 20-of-340 and 20-of-620 server pages.
  implication: The first reported issue is reproduced directly and the page-level coverage predicate is confirmed as its cause.
- timestamp: 2026-09-08T15:39:00+08:00
  checked: Failing-first drawer integration regression
  found: After the exhaustive badge loader reports `83 of 83 findings`, selecting the clean route table still renders the heading `Open findings` rather than `Open findings (0)`.
  implication: Visible-page `findingsTruncated=true` overrides directly observed exhaustive coverage and reproduces the third reported issue.
- timestamp: 2026-09-08T15:42:00+08:00
  checked: Failing-first summary relationship regression
  found: On one valid snapshot, full detail contains Route→Firewall `next_hop`, the Route node is intentionally absent from summary, and summary has no RouteTable→Firewall `next_hop`.
  implication: Summary omission destroys the meaningful next-hop path instead of contracting it; malformed data and unresolved firewall lookup are ruled out.
- timestamp: 2026-09-08T15:49:00+08:00
  checked: Focused post-fix regressions
  found: The exact page-range, summary next-hop, and exhaustive 83/83 drawer tests all pass after the minimal source changes.
  implication: Guardrail signal 1 (target tests) passes for all three reported issues; adjacent and revert/reconfirm signals remain pending.
- timestamp: 2026-09-08T15:55:00+08:00
  checked: Adjacent backend and web network suites
  found: All 159 adjacent Python tests passed. Of 198 adjacent web tests, 197 passed and one obsolete test failed because it explicitly expected the now-rejected permanent page callout after confirming pagination warnings were absent from provenance.
  implication: No production regression is exposed; the contradictory old oracle must be updated to the specified tab-owned range behavior before rerunning the held-out web gate.
- timestamp: 2026-09-08T16:00:00+08:00
  checked: Adjacent web rerun after correcting the obsolete oracle
  found: All 198 tests across page, workspace, drawer, graph, graph behavior, network graph mapping, services, and latency passed.
  implication: Guardrail signal 4 is green for focused adjacent Python and web import-graph coverage.
- timestamp: 2026-09-08T16:06:00+08:00
  checked: Guardrail source-only revert
  found: With only the three production fixes stashed, all three causes returned: the permanent page warning reappeared, summary RouteTable→Firewall was absent, and the page again forwarded `findingsTruncated=true`.
  implication: Guardrail signal 5 has proven `bug_returned_on_revert=true`; fixed-on-reapply remains to be reconfirmed.
- timestamp: 2026-09-08T16:09:00+08:00
  checked: Guardrail source reapply
  found: After popping the exact scoped stash, the same three tests all passed again; unrelated worktree changes remained present.
  implication: Guardrail signal 5 passes with both `bug_returned_on_revert=true` and `fixed_on_reapply=true`.
- timestamp: 2026-09-08T16:14:00+08:00
  checked: Static gates and optional full web sweep
  found: TypeScript `tsc --noEmit`, Next ESLint, and scoped Python Ruff passed. The full web sweep passed 594 tests across 57 files but one unrelated compliance test failed because its `@/lib/services` mock lacks `isCanonicalAzureResourceId`; all 198 adjacent network tests had already passed.
  implication: Applicable network/static gates are green. The pre-existing compliance mock defect is outside this fix and is not modified under the user's concurrent-change constraint.
- timestamp: 2026-09-08T16:18:00+08:00
  checked: Production build gates
  found: Next.js production build completed successfully for all 28 routes and `uv build` produced both source and wheel distributions.
  implication: The fix passes applicable web and Python build gates; MSAL emitted its pre-existing server-render logging but did not fail the build.
- timestamp: 2026-09-08T16:25:00+08:00
  checked: Final adjacent web and local browser verification
  found: All 199 tests in the eight adjacent network Vitest files passed, and all 3 mocked Chromium Phase 12 live-review scenarios passed.
  implication: Final UI-adjacent and responsive browser behavior remains green after the last regression-hardening assertion.
- timestamp: 2026-09-08T15:36:10.121+08:00
  checked: Human verification checkpoint
  found: The user confirmed the remediation fixed based on independent source review plus the passing 159 backend, 199 web, and 3 mocked-Chromium regressions.
  implication: End-to-end source acceptance is confirmed; the session can be archived without deployment, push, or commit.

## Eliminated

## Resolution

root_cause: "Three independent code causes: (1) page.tsx promotes ordinary first-page `coverage.truncated` to a permanent page-level incomplete-results warning; (2) topology.py intentionally removes Route nodes in summary and suppresses their RouteTable→Route→Firewall edges without contracting the path; (3) TopologyWorkspace combines visible-page `findingsTruncated` with independently exhaustive `badgeCoverage.truncated`, so paged lists can veto confirmed-clean state."
fix: "Filtered pagination-only collection warnings from global provenance and removed the permanent page callout; contracted intentionally omitted Route next hops to retained RouteTable nodes in summary; removed visible-page truncation from the drawer completeness contract so exhaustive badge coverage is authoritative."
verification:
  target_test:
    result: pass
    suites_run:
      - "web/src/app/network/page.test.tsx -t keeps ordinary server-page ranges inside their owning tabs without a page warning"
      - "tests/test_network_topology.py::TestResourceTopologyProjection::test_virtual_appliance_route_links_to_the_firewall_it_targets"
      - "web/src/components/network/TopologyWorkspace.test.tsx -t confirms a resource clean after exhaustive badge loading despite visible-page truncation"
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker configuration or @stryker-mutator/core dependency exists in the repository."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    evidence: "The diff removes only the RCA-confirmed permanent pagination-warning promotion and obsolete visible-page truncation prop; it adds summary edge contraction and preserves true exhaustive truncation/error/loading behavior."
  adjacent_tests:
    result: pass
    suites_run:
      - "pytest: test_network_topology.py, test_network_topology_links_regression.py, test_network_scale.py, test_api_network.py (159 passed)"
      - "vitest: page, workspace, drawer, graph, graph behavior, network graph, services, latency (199 passed)"
      - "playwright: network-topology-live-ui.spec.ts (3 passed)"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  quality_gates:
    typescript: pass
    eslint: pass
    ruff: pass
    next_build: pass
    python_build: pass
    full_web_sweep: "594 passed; 1 unrelated compliance test failed because its services mock omits isCanonicalAzureResourceId"
  scoped_diff_check: pass
  guardrail_verdict: accepted
  human_verification:
    result: pass
    confirmed_at: 2026-09-08T15:36:10.121+08:00
    basis: "Independent source review plus 159 passing backend tests, 199 passing adjacent web tests, and 3 passing mocked-Chromium Phase 12 regressions."
    deployment_performed: false
files_changed:
  - web/src/app/network/page.tsx
  - web/src/app/network/page.test.tsx
  - web/src/components/network/TopologyWorkspace.tsx
  - web/src/components/network/TopologyWorkspace.test.tsx
  - src/network/topology.py
  - tests/test_network_topology.py
oracle_type: specified
