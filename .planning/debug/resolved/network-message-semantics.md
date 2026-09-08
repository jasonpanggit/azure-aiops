---
status: resolved
trigger: "Investigate the Network page messages shown in the attached screenshot."
created: 2026-09-08T14:20:00+08:00
updated: 2026-09-08T14:37:07.284+08:00
---

# Debug Session: Network Message Semantics

## Symptoms

### Expected behavior

- Each warning appears once, near the surface where the operator can act on it.
- Relationship-loss wording distinguishes out-of-scope endpoints from missing or unprojected endpoints.
- Confidence and freshness labels describe their exact dimensions without implying the whole result is complete.
- Metric labels agree with the population being counted.

### Actual behavior

- The provenance banner contains both a generic truncation warning and a route-specific `Showing 20 of 77` warning, while a separate callout repeats the same pagination state.
- `6 topology relationships dropped because an endpoint was absent from this scope` is shown even with All subscriptions selected.
- `high confidence` appears beside `Graph Unknown`, dropped relationships, and incomplete lists.
- The page reports `1 / 0` hub/spoke VNets but `2` inspection bypasses described as spokes.

### Error messages

- `6 topology relationships dropped because an endpoint was absent from this scope (attached_to=2, hosts=2, load_balances=2)`
- `Results are truncated; narrow the scope or use pagination for a complete view.`
- `Showing 20 of 77 inspection gaps; use pagination for the complete result`
- `Results are incomplete. Showing 20 of 77 inspection gaps and 6 of 6 rule findings.`

### Timeline

- Observed on the deployed Network page after the Phase 12 live-runtime remediation.

### Reproduction

1. Open `/network` with All subscriptions.
2. Observe the provenance banner and metric cards.
3. Compare the top warning banner with the incomplete-results callout.

## Current Focus

hypothesis: The compound Network message-semantics defect is fixed, guardrail-accepted, and confirmed by the user through independent source review plus the targeted and adjacent regressions.
test: User independently reviewed the source remediation and accepted the passing failing-first, target, adjacent, and revert-and-reconfirm evidence.
expecting: Complete — the authoritative Phase 12 UI review records source closure without claiming an undeployed live-runtime recheck.
next_action: None — session resolved and archived; the session manager owns any exact-path staging and commit.
bug_class: bohrbug
reasoning_checkpoint:
  hypothesis: "The page misleads because (1) automatic nested-truncation warnings are combined with route-specific warnings and then merged into a global EvidenceBar despite a contextual coverage callout, (2) topology relationship projection retains only dropped counts by relationship type and labels every absent endpoint as scope-excluded, (3) EvidenceBar renders the first topology evidence confidence and graph timestamp with no dimension subject, and (4) /firewall-bypass counts finding rows while route/UI copy calls them spokes."
  confirming_evidence:
    - "Direct envelope reproduction returns both the generic truncation sentence and the route-specific Showing 20 of 77 sentence for one truncated collection; NetworkPage also renders its own combined coverage callout."
    - "A missing endpoint and an endpoint deliberately excluded by NetworkScope both produce the exact same hosts=1 absent-from-scope warning."
    - "EvidenceBar uses evidence[0], NetworkPage places topology evidence first, and the badge is only high confidence while graph time is separately unknown."
    - "small_estate returns 54 firewall_bypass rows across 18 unique VNets, proving the route count is a finding-row count rather than a spoke count; public-IP NIC findings share the same category in code."
  falsification_test: "The hypothesis would be false if the pre-fix API emitted only one pagination warning, missing and scope-excluded endpoints produced different diagnostics, the confidence badge already named topology evidence/graph observation, or firewall-bypass count equaled a unique spoke-VNet population by construction."
  fix_rationale: "Suppress automatic truncation copy only where a route supplies precise count copy, keep collection pagination warnings out of the global provenance bar when the contextual coverage callout owns them, carry scope-excluded endpoint IDs into topology projection so loss reasons are classified without exposing IDs, and relabel confidence/freshness and bypass metrics to the exact evidence dimension and finding-row population."
  blind_spots: "The deployed live payload is not available locally; semantic relationships filtered before TopologyBuilder remain outside general dropped-edge diagnostics; changing shared EvidenceBar props must be regression-tested at default call sites; localization is not present."
  candidate_causes:
    - "code: warning aggregation has dual presentation owners; dropped-edge projection discards cause; trust labels omit subjects; bypass copy names the wrong population"
    - "config: an effective authorized subscription scope can filter endpoints even when the UI says All subscriptions"
    - "data: dangling or unprojected load-balancer, subnet, or backend references trigger relationship drops, while collection and gap volume triggers the misleading states"
  and_gate: "yes — the complete screenshot requires multiple independent code defects plus valid triggering data states; no single cause explains warning duplication, endpoint-loss wording, trust-label ambiguity, and metric-population mismatch together"
tdd_checkpoint:

## Evidence

- timestamp: 2026-09-08T14:20:00+08:00
  observation: Envelope automatically adds a generic warning for any nested `truncated: true`.
  source: src/api/evidence.py
- timestamp: 2026-09-08T14:20:00+08:00
  observation: `/network/gaps` also adds a route-specific count warning, and the page renders a separate contextual coverage callout.
  source: src/api/routers/network.py; web/src/app/network/page.tsx
- timestamp: 2026-09-08T14:20:00+08:00
  observation: `firewall_bypass_spokes()` returns every `firewall_bypass` gap, including public-IP bypasses, not a unique spoke-VNet count.
  source: src/network/service.py; src/network/gaps.py
- timestamp: 2026-09-08T14:22:00+08:00
  observation: Scope check passed: STATE marks Phase 12 complete and its network behavior preserved; the worktree has no competing code edits, only this untracked debug session.
  source: .planning/STATE.md; git status --short --branch
- timestamp: 2026-09-08T14:24:00+08:00
  observation: MemPalace is not enabled/configured in .planning/config.json, so semantic recall is unavailable. Keyword fallback found only Network latency/route-identity entries; none overlaps the pagination, dropped-edge wording, confidence, freshness, or bypass-population symptoms by two tokens.
  source: .planning/config.json; .planning/debug/knowledge-base.md
- timestamp: 2026-09-08T14:26:00+08:00
  observation: Exact-string search locates the generic truncation sentence only in the shared evidence envelope, while the separate incomplete-results heading is authored in the Network page and asserted by its component test. Graph Unknown is independently authored/tested in EvidenceBar.
  source: src/api/evidence.py; tests/test_api_primitives.py; web/src/app/network/page.tsx; web/src/app/network/page.test.tsx; web/src/components/ui/EvidenceBar.tsx; web/src/components/ui/EvidenceBar.test.tsx
- timestamp: 2026-09-08T14:31:00+08:00
  observation: Envelope.to_dict recursively emits a generic warning for nested truncated=true; /network/gaps and /network/rule-findings each add count-specific warnings; NetworkPage merges all envelope warnings into EvidenceBar and independently renders the combined coverage callout. Deduplication removes exact duplicates only, so all three differently worded pagination disclosures remain.
  source: src/api/evidence.py:200-353; src/api/routers/network.py:354-457; web/src/app/network/page.tsx:190-292
- timestamp: 2026-09-08T14:31:00+08:00
  observation: EvidenceBar selects evidence[0], and NetworkPage orders topology evidence first. It labels that item as an unqualified “high confidence” badge while separately rendering Graph Unknown and merging warnings from incomplete result collections; the high value therefore describes topology evidence confidence but visually reads as confidence in the whole page.
  source: web/src/app/network/page.tsx:187-205,234-240; web/src/components/ui/EvidenceBar.tsx:42-75
- timestamp: 2026-09-08T14:31:00+08:00
  observation: The firewall-bypass route count is len(all gaps whose category is firewall_bypass). That category combines one row per bypassing subnet with public-IP-on-NIC rows, while the metric says “Spokes”; it is neither a unique spoke-VNet count nor limited to spokes with route bypass.
  source: src/network/service.py:470-472; src/network/gaps.py:199-263,863-905; src/api/routers/network.py:301-311; web/src/app/network/page.tsx:247-252
- timestamp: 2026-09-08T14:36:00+08:00
  observation: _topology_relationships.add() checks only whether both endpoint IDs are in the rendered resource-id set. For any absent endpoint not intentionally omitted by summary detail, it increments a relationship-type count and discards endpoint/cause identity. NetworkTopology.to_dict() then unconditionally explains every such count as “absent from this scope.”
  source: src/network/topology.py:301-318,473-486,1466-1501
- timestamp: 2026-09-08T14:36:00+08:00
  observation: Existing peer diagnostics already prove the codebase can distinguish excluded_by_scope from not_ingested by comparing the original and filtered snapshots, but this resolution vocabulary is applied only to unresolved VNet peers, not general topology relationship endpoints.
  source: src/network/service.py:400-433; src/network/topology.py:768-818; tests/test_network_topology.py:234-280
- timestamp: 2026-09-08T14:36:00+08:00
  observation: The only dropped-relationship regression creates a dangling private-endpoint reference in an unscoped snapshot and asserts count/privacy, not wording. It therefore locks no truthful reason and currently passes while the message falsely says the missing endpoint was outside scope.
  source: tests/test_network_topology_links_regression.py:340-365
- timestamp: 2026-09-08T14:39:00+08:00
  observation: Focused frontend baseline passes 39/39 tests, including existing Network page pagination and EvidenceBar tests. No current test rejects repeated pagination warnings, unqualified confidence copy, or the “Spokes” bypass population label. Phase 1.25 SBFL is skipped because there is no failing test/per-test coverage spectrum yet.
  source: npm test -- --run src/app/network/page.test.tsx src/components/ui/EvidenceBar.test.tsx
- timestamp: 2026-09-08T14:42:00+08:00
  observation: Resource projection synthesizes placeholder nodes for NIC-attached workloads, private-endpoint targets, and a load balancer's managed resource, but not arbitrary load-balancer backend_resource_ids. Relationship projection separately attempts load_balances edges to every backend ID, so an unprojected backend is a concrete non-scope cause of dropped relationships.
  source: src/network/topology.py:1194-1300,1373-1418,1621-1633
- timestamp: 2026-09-08T14:42:00+08:00
  observation: The first backend baseline command did not execute tests because two guessed pytest node IDs used the wrong class name. This is a test-selection error, not product evidence; rerun will use discovered node IDs or -k expressions.
  source: uv run pytest (exit 4: node not found)
- timestamp: 2026-09-08T14:44:00+08:00
  observation: Corrected focused API test selection passes 3/3 pagination and firewall-bypass baseline tests. These tests assert count presence and count-specific warning inclusion but do not reject the additional generic warning or validate bypass population semantics.
  source: uv run pytest tests/test_api_network.py -k 'coverage_and_pagination_are_additive_and_honest or TestFirewallBypass' -q
- timestamp: 2026-09-08T14:48:00+08:00
  observation: A controlled counterfactual produced the same count and exact warning for two different causes: removing a referenced private endpoint from an unscoped snapshot (missing/unprojected) and filtering that known endpoint out by subscription scope (excluded_by_scope) both returned hosts=1 with “endpoint was absent from this scope.”
  source: uv run python in-memory small_estate counterfactual
- timestamp: 2026-09-08T14:52:00+08:00
  observation: Direct API-envelope reproduction for coverage 20/77 returns two warnings for one pagination state: the automatic generic truncation warning and the explicit route-specific count warning.
  source: uv run python direct envelope reproduction
- timestamp: 2026-09-08T14:52:00+08:00
  observation: small_estate produces 54 firewall_bypass gap rows across only 18 unique VNet IDs. Therefore the endpoint count is definitively per finding row, even before considering public-IP NIC rows that use the same category.
  source: uv run python NetworkIntelligenceService(small_estate()).firewall_bypass_spokes()
- timestamp: 2026-09-08T15:05:00+08:00
  observation: RED backend slice reproduced six failures: unknown automatic_truncation_warning ownership control, two exact-warning mismatches caused by the extra generic warning, and three missing dropped_relationship_reasons assertions. The bypass count-equals-gap-rows test passed.
  source: uv run pytest focused 7-test backend slice
- timestamp: 2026-09-08T15:05:00+08:00
  observation: RED frontend slice reproduced three failures: pagination copy remained in global provenance, custom trust-dimension labels were ignored, and the Network page still lacked qualified trust/bypass copy. Forty adjacent/boundary tests passed, including retention of pagination warning when the contextual owner is unavailable.
  source: npm test -- --run src/components/ui/EvidenceBar.test.tsx src/app/network/page.test.tsx
- timestamp: 2026-09-08T15:16:00+08:00
  observation: The exact backend target/boundary slice is GREEN (8/8), including default automatic truncation, explicit warning ownership, complete and singleton topology diagnostics, scope-excluded versus missing causes, exact route warnings, and bypass count equality.
  source: uv run pytest focused backend target slice
- timestamp: 2026-09-08T15:16:00+08:00
  observation: The exact frontend target/adjacent slice is GREEN (43/43), including qualified trust labels, contextual-only pagination copy, companion-unavailable warning retention, bypass finding copy, and all pre-existing Network page tests.
  source: npm test -- --run src/components/ui/EvidenceBar.test.tsx src/app/network/page.test.tsx
- timestamp: 2026-09-08T15:19:00+08:00
  observation: git diff --check passes. No Stryker, mutmut, or other mutation runner is configured in project package/pyproject files, so guardrail signal 2 must degrade to a logged skip.
  source: git diff --check; mutation-tool configuration search
- timestamp: 2026-09-08T15:19:00+08:00
  observation: Three unrelated modified files appeared during verification (web compliance page, remediation page, and services.ts). This session did not edit them; all further diff, test, and revert operations will use explicit debug-owned pathspecs.
  source: git status --short
- timestamp: 2026-09-08T15:22:00+08:00
  observation: Scoped diff review shows 289 additions and 37 replacements/deletions across implementation plus tests. Every deletion is a directly replaced generic label, warning merge, signature, or assertion; behavior is added rather than short-circuited, and no branch/test was removed to make the symptom disappear.
  source: git diff --numstat and per-file implementation diffs
- timestamp: 2026-09-08T15:28:00+08:00
  observation: Adjacent backend run passed 274 tests and failed only the frozen G-4 no-drop payload byte contract: always serializing dropped_relationship_reasons={} added 34 bytes. The compatibility-preserving correction is to emit the additive diagnostic only when drops exist.
  source: adjacent uv run pytest Network/envelope/downstream suites
- timestamp: 2026-09-08T15:28:00+08:00
  observation: TypeScript no-emit, scoped Ruff, and scoped ESLint all pass. The full web suite exited 1; its large saved output must be inspected before attribution.
  source: npx tsc --noEmit; ruff check; eslint; full vitest run
- timestamp: 2026-09-08T15:31:00+08:00
  observation: The sole full-web failure is in the concurrently modified compliance page: its services mock lacks the concurrently added isCanonicalAzureResourceId export (1 failed, 592 passed). No debug-owned file imports or defines that symbol, so this is not caused by the Network fix and will not be edited.
  source: saved full vitest failure output; git status --short
- timestamp: 2026-09-08T15:31:00+08:00
  observation: Compatibility adjustment now omits dropped_relationship_reasons when there are no drops, preserving frozen payload bytes, while cause diagnostics remain additive on dropped-edge payloads.
  source: src/network/topology.py; tests/test_network_topology_links_regression.py
- timestamp: 2026-09-08T15:35:00+08:00
  observation: Corrected adjacent backend suite passes 275/275, including the frozen G-4 byte contract. Applicable frontend import-graph suites pass 59/59 (EvidenceBar, Network page, Inventory page). The full web run otherwise had 592 passing tests and only the independently modified compliance/services failure.
  source: adjacent uv run pytest; explicit vitest import-graph paths; prior full vitest output
- timestamp: 2026-09-08T15:39:00+08:00
  observation: Reverting only the six implementation files while retaining agent-authored tests restored five backend failures and three frontend failures matching the original mechanisms; unaffected boundary tests still passed. The bug therefore returns when this fix is absent.
  source: pathspec-limited git stash plus exact target test rerun
- timestamp: 2026-09-08T15:43:00+08:00
  observation: Unique fix symbols are absent after the attempted pop. Commit df3d2a83... is an unrelated exposure stash containing only runtime.py and change_intelligence.py, proving a concurrent stash index race; no Network source was overwritten.
  source: fix-symbol search; git show df3d2a83c50be7d25b77c53890669c6fa8c2b2e8
- timestamp: 2026-09-08T15:46:00+08:00
  observation: Applying immutable Network stash hash a82881e5... restored all six implementation files and unique fix symbols. The unrelated exposure stash race did not alter Network tests or source.
  source: git stash apply a82881e5e18db483c0f312fb49519e4a9b9f974a; scoped symbol/status checks
- timestamp: 2026-09-08T15:49:00+08:00
  observation: Reapplied implementation reconfirmed GREEN: backend target/boundary slice 8/8 and frontend target/adjacent slice 43/43. Combined with the preceding RED-on-revert run, causality is proven.
  source: exact target test rerun after immutable-hash stash apply
- timestamp: 2026-09-08T15:52:00+08:00
  observation: Exact Network stash cleanup succeeded by immutable hash; git diff --check remains clean and all eleven debug-owned implementation/test files remain present. Other concurrent worktree modifications were neither stashed nor edited.
  source: exact-hash git stash drop; scoped git status; git diff --check
- timestamp: 2026-09-08T14:37:07.284+08:00
  observation: The user confirmed the remediation fixed through independent source review and the passing targeted/adjacent message-semantics regressions. No deployment or live-runtime recheck was requested or performed.
  source: human verification checkpoint response

## Eliminated

- hypothesis: The hub/spoke and bypass discrepancy is caused by corrupt or stale bypass totals.
  evidence: The service deterministically returns one count per firewall_bypass NetworkGap; a fixture produced 54 rows across 18 VNets, so the value is internally correct and the Spokes copy names the wrong population.
  timestamp: 2026-09-08T14:52:00+08:00
- hypothesis: Selecting All subscriptions should prevent all dropped-edge warnings, so effective scope configuration alone causes the wording defect.
  evidence: An unscoped snapshot with a genuinely missing endpoint emits the same absent-from-scope sentence as a deliberately scope-filtered endpoint.
  timestamp: 2026-09-08T14:52:00+08:00
- hypothesis: The backend incorrectly computes high confidence for the entire Network result.
  evidence: Route code assigns high only to topology evidence and medium to gaps/bypass; NetworkPage orders topology evidence first and EvidenceBar drops the subject, so overgeneralization occurs in presentation rather than confidence computation.
  timestamp: 2026-09-08T14:52:00+08:00

## Resolution

root_cause: "Compound message-semantics defect: shared and route-level pagination warnings have overlapping ownership and the page promotes them into global provenance despite a contextual callout; topology projection discards absent-endpoint cause and labels every dropped relationship as scope loss; EvidenceBar omits the subject of topology confidence and graph observation time; firewall-bypass counts NetworkGap rows but backend/frontend copy describes the value as spokes."
fix: "Added opt-out ownership for automatic truncation copy on routes with precise count warnings; filtered only owned collection-pagination warnings from Network global provenance while retaining them when the contextual callout cannot render; preserved legacy dropped relationship counts while adding cause-specific missing_or_unprojected versus excluded_by_scope diagnostics; qualified Network confidence and graph-observation labels; relabeled firewall-bypass values as finding rows."
verification:
  target_test: {result: pass}
  mutation_check: {result: skipped, reason_if_skipped: "No Stryker or other mutation runner is configured", mutant_killed: false}
  no_op_deletion: {result: pass, deletion_justified_by_rca: true}
  adjacent_tests: {result: pass, suites_run: ["backend Network/envelope/downstream: 275 passed", "frontend EvidenceBar/Network/Inventory import graph: 59 passed", "full web: 592 passed plus 1 unrelated concurrent compliance/services failure excluded from applicable graph", "tsc: pass", "ruff: pass", "eslint: pass"]}
  revert_and_reconfirm: {result: pass, bug_returned_on_revert: true, fixed_on_reapply: true}
  human_confirmation: {result: pass, basis: "independent source review plus passing targeted and adjacent message-semantics regressions", live_runtime_recheck: "not run; no deployment was authorized or performed"}
  guardrail_verdict: accepted
oracle_type: specified
files_changed:
  - src/api/evidence.py
  - src/api/routers/network.py
  - src/network/service.py
  - src/network/topology.py
  - web/src/components/ui/EvidenceBar.tsx
  - web/src/app/network/page.tsx
  - tests/test_api_primitives.py
  - tests/test_api_network.py
  - tests/test_network_topology_links_regression.py
  - web/src/components/ui/EvidenceBar.test.tsx
  - web/src/app/network/page.test.tsx
