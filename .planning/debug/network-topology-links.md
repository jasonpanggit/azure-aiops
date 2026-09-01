---
slug: network-topology-links
status: resolved
trigger: "Network topology relationships regressed after recent topology/Fabric/ontology changes"
created: "2026-09-01T23:06:57.137+08:00"
updated: "2026-09-01T23:35:00+08:00"
goal: find_and_fix
---

# Debug Session: Network Topology Links

## Symptoms

- Expected Azure Firewall, Azure Bastion, NICs, and private endpoints to link to containing subnets.
- Expected Private DNS zones with VNet links to link to those VNets.
- Expected Private DNS zones without VNet links to produce an inspection-gap finding.
- Current synchronized inventory graph shows these resources disconnected.

## Current Focus

reasoning_checkpoint:
  hypothesis: "The combined regression has four code/data-contract causes: scoped hybrid requests pass raw ARG rows to an ontology-only loader, Fabric re-normalization discards canonical linkedVnetIds, private endpoint DNS-zone-group child resources are neither queried nor merged, and the DNS gap rule never inspects standalone zones."
  confirming_evidence:
    - "Removing entityType from property-complete rows reproduces the hybrid contract and yields zero network entities/relationships; grouping the same rows by NETWORK_RESOURCE_TYPES and running the existing Normalizer restores 82 resources and all firewall/Bastion/NIC/private-endpoint/DNS relationships."
    - "Current canonical files, InventoryDatasetMapper, backend topology, every scope, and TypeScript graph projection all preserve non-DNS attachments, ruling out normalization, ontology mapping, scope, and frontend loss after canonicalization."
    - "Fabric derive_edges emits all 7 non-DNS attachedTo edges but zero resolvesFor edges from three canonical PrivateDnsZone rows whose linkedVnetIds are populated."
    - "Query catalog/local inventory contain DNS virtualNetworkLinks children but no privateEndpoints/privateDnsZoneGroups children; the gap analyzer iterates endpoints only."
  falsification_test: "The hypothesis is wrong if RED tests show raw ARG rows already produce typed attachment edges, canonical linkedVnetIds already produce Fabric resolvesFor, a zone-group child already enriches its endpoint, or a standalone unlinked zone already emits a gap."
  fix_rationale: "Route raw live rows through the existing canonical Normalizer; preserve and merge canonical/child DNS references before deriving edges; request Private DNS zone-group child resources; and add a zone-level gap branch. These changes repair the first data-contract boundary rather than adding frontend edges cosmetically."
  blind_spots: "No live Azure mutation will be performed; real ARG row volume/bounds and deployed Fabric IQ visualization remain external. The current synchronized fixture contains no privateDnsZoneGroups child because the query omitted it, so that shape is verified with an Azure-contract fixture."
  candidate_causes:
    - "code: hybrid_network bypasses Normalizer and NetworkGapAnalyzer has no zone-level branch"
    - "data: Fabric receives canonical parent rows with linkedVnetIds while derive_edges expects raw virtualNetworkLinks child rows"
    - "config/query: NETWORK_RESOURCE_TYPES excludes privateEndpoints/privateDnsZoneGroups"
    - "environment: stale deployed/Fabric data could preserve the screenshot after local fixes, but current local canonical projections disprove an in-repo downstream loss"
  and_gate: "yes — the reported bundle spans independent outcomes: raw scoped graph attachments, Fabric DNS links, endpoint DNS membership, and standalone-zone findings each require its corresponding cause to be fixed."
next_action: Complete. Local repository fix is implemented and verified; deployment/live browser refresh was not performed by this debug task.
scope_check: Explicit maintenance interruption is recorded; preserve active Phase 03 remediation UI and Fabric work, do not commit or push.
bug_class: bohrbug
candidate_causes:
  - "code: relationship derivation or graph projection no longer reads Azure attachment shapes"
  - "data: synchronized snapshots store child resources or IDs in a shape not handled by the current normalizer"
  - "config: topology/ontology rollout selects a projection that excludes these relationship families"
and_gate: "unknown — several resource families may share one normalization failure, while Private DNS may require a second independent cause."

## Constraints

- This is an explicit maintenance interruption during active Phase 03 remediation UI work.
- Preserve all unrelated uncommitted work, especially the active `fabric-topology-rollout` session.
- Do not revert, stash, overwrite, or commit its changes in `src/fabric/config.py`, `runtime.py`, `schema_registry.py`, `sync_service.py`, related tests, or other remediation tests.
- Trace the full path: inventory normalization/models, relationship/ontology derivation, API graph projection, and frontend graph.
- Inspect recent history/diffs to identify the exact regression rather than applying a cosmetic workaround.
- Reuse canonical case-insensitive Azure resource-ID normalization.
- Respect Azure attachment shapes: firewall/Bastion IP configurations, NIC `ipConfigurations[].subnet.id`, private endpoint subnet/NIC linkage, and Private DNS VNet links or child resources.
- Add regression coverage for all required relationships and Private DNS rule behavior.
- Use synchronized local fixtures/snapshots before live data and do not mutate Azure resources.
- Run targeted and adjacent tests plus applicable lint/type checks.
- Do not commit or push.

## Evidence

- timestamp: "2026-09-01T23:06:57.137+08:00"
  observation: "User-supplied synchronized-inventory screenshot shows disconnected firewall, Bastion, NIC/private endpoint, and Private DNS zone nodes."
  source: "bounded symptom report"

- timestamp: "2026-09-01T23:10:00+08:00"
  checked: ".planning/STATE.md and git status"
  found: "Phase 03 plan 03-06 is active; Fabric topology and remediation UI files contain unrelated uncommitted work explicitly protected by this session."
  implication: "The topology regression is an authorized maintenance interruption, but investigation and any fix must be surgical and must not revert, stash, commit, or overwrite protected work."

- timestamp: "2026-09-01T23:10:00+08:00"
  checked: "Configured debugger skills and project skill discovery"
  found: "No agent_skills were configured for gsd-debugger; project skills include gsd-debug and archify, with no repository-root rules/*.md directory."
  implication: "Load the two relevant skill indexes; no additional configured debugger skill block applies."

- timestamp: "2026-09-01T23:13:00+08:00"
  checked: "Debug knowledge base"
  found: "The only prior entry concerns Foundry model/tool compatibility and does not match missing topology relationships."
  implication: "No known-pattern hypothesis applies; proceed with fresh tracing."

- timestamp: "2026-09-01T23:13:00+08:00"
  checked: "Existing Fabric topology rollout session"
  found: "Uncommitted rollout wiring derives 82 topology entities and 78 edges from the local synchronized snapshot; standalone derivation existed before runtime wiring."
  implication: "The synchronized snapshot and derived topology tables provide a reproducible boundary for checking whether required relationship families disappear before frontend rendering."

- timestamp: "2026-09-01T23:13:00+08:00"
  checked: "SBFL prerequisites and bug taxonomy"
  found: "The loss is stable in synchronized inventory, but no existing failing test with per-test coverage exists."
  implication: "Classify as bohrbug; skip SBFL and use deterministic reproduction, differential tracing, and history comparison."

- timestamp: "2026-09-01T23:16:00+08:00"
  checked: "Codebase relationship search"
  found: "Both onboarding graph normalization and Fabric topology derivation import the same network_normalize helpers; downstream network models/topology already define subnet and Private DNS edge families."
  implication: "The shared normalizer is the earliest high-leverage boundary, but downstream resolution still requires direct inspection before forming a confirmed hypothesis."

- timestamp: "2026-09-01T23:16:00+08:00"
  checked: "Protected Fabric rollout diff"
  found: "The uncommitted rollout changes wire existing topology derivation into sync and govern its table envelopes; they do not modify shared network normalization or the API/frontend graph path."
  implication: "Do not blame or alter the protected rollout files; reproduce the relationship loss against the standalone derivation and synchronized source rows."

- timestamp: "2026-09-01T23:20:00+08:00"
  checked: "Complete normalization-to-frontend relationship path"
  found: "Shared normalizers lower ARM references and explicitly read NIC/firewall/gateway/private-endpoint subnet IDs plus Private DNS child-link virtualNetwork IDs. Typed models case-fold IDs; backend relationship projection only emits edges when both endpoints exist; frontend resolves relationship endpoints case-insensitively."
  implication: "A frontend-only casing bug is unlikely. Missing source references or absent counterpart entities would be silently dropped by backend/Fabric dangling-edge filters and exactly produce disconnected nodes."

- timestamp: "2026-09-01T23:20:00+08:00"
  checked: "Private DNS gap implementation search"
  found: "The existing rule is centered on private endpoints and their referenced DNS zones; code inspection of the analyzer is still required to determine whether an unlinked standalone zone can emit the requested inspection-gap finding."
  implication: "Subnet attachment loss and missing unlinked-zone findings may be separate causes; keep the AND-gate open."

- timestamp: "2026-09-01T23:23:00+08:00"
  checked: "NetworkGapAnalyzer._dns_dependency implementation"
  found: "The rule loops only over private endpoints. It emits for endpoints with no DNS zone group or referenced zones not linked to the endpoint's consuming VNet, but never loops over PrivateDnsZone rows themselves."
  implication: "A standalone Private DNS zone with zero VNet links cannot produce the explicitly expected inspection-gap finding; this is a confirmed code-coverage omission independent of graph rendering."

- timestamp: "2026-09-01T23:23:00+08:00"
  checked: "Local synchronized data locations"
  found: "The configured .aiops-local local-spn store exists with three immutable generations; live-data contains additional historical generations. `current` was not traversed by the initial non-following find."
  implication: "Resolve the current pointer and probe synchronized generation data directly before using synthetic fixtures."

- timestamp: "2026-09-01T23:25:00+08:00"
  checked: ".aiops-local local-spn current pointer and manifest"
  found: "`current` points to completed generation ef1382d3-afbe-4de9-9d03-22dd5cae55f9, containing 1 AzureFirewall, 1 NetworkGateway, 3 NetworkInterfaces, 2 PrivateEndpoints, 3 PrivateDnsZones, 8 Subnets, and 2 VNets."
  implication: "The current synchronized generation contains every affected entity family and can reproduce the displayed disconnections without a live Azure query."

- timestamp: "2026-09-01T23:28:00+08:00"
  checked: "Direct current-generation NetworkSnapshotLoader and NetworkTopology probe"
  found: "All affected references resolve to present entities and the backend emits the expected edges: firewall↔AzureFirewallSubnet, Bastion↔AzureBastionSubnet, all 3 NICs→subnets, both private endpoints→subnets, and all 3 Private DNS zones→their VNets (82 resources, 86 relationships)."
  implication: "Shared normalization, persisted canonical entity attributes, typed loading, and backend relationship construction are not losing these links for the current synchronized generation."

- timestamp: "2026-09-01T23:28:00+08:00"
  checked: "Persisted canonical relationship rows"
  found: "relationships.jsonl already contains 7 attachedTo, 3 hasNetworkInterface, and 3 resolvesFor assertions including every reported resource family."
  implication: "The regression is downstream of canonical relationship derivation or the active runtime is not consuming this current generation; the initial normalization-loss hypothesis is eliminated for the observed local snapshot."

- timestamp: "2026-09-01T23:32:00+08:00"
  checked: "API provider selection"
  found: "Every scoped network request with subscription IDs selects hybrid_network, which runs a live ARG query and passes projected raw rows directly to NetworkIntelligenceService.from_rows; only unscoped fallback loads synchronized ontology entities/relationships."
  implication: "The user-visible route can bypass the known-good synchronized relationship set. Verify whether the live query adapter adds entity types; otherwise the typed loader cannot bucket raw ARG network rows."

- timestamp: "2026-09-01T23:32:00+08:00"
  checked: "Frontend graph construction and Cytoscape rendering"
  found: "The frontend case-folds relationship endpoints, materializes every backend relationship as an edge, and styles relationship edges visibly; default filtering resets display to element and hides only explicit shared-service nodes/edges when toggled."
  implication: "No static frontend drop condition explains only the reported resource families when the backend payload contains their edges; prioritize runtime payload differences before layout/rendering."

- timestamp: "2026-09-01T23:35:00+08:00"
  checked: "First Fabric/raw differential probe invocation"
  found: "The diagnostic assumed snake_case edge fields, but derive_edges returns the canonical camelCase edge envelope and the script stopped with KeyError before reporting results."
  implication: "This is a probe-shape error, not product evidence; rerun unchanged apart from reading subjectId/objectId."

- timestamp: "2026-09-01T23:38:00+08:00"
  checked: "Fabric topology derivation from current canonical entity files"
  found: "Fabric emits all 7 expected attachedTo edges plus 8 VNet→Subnet contains edges and 2 private-endpoint→NIC edges, but emits zero resolvesFor edges despite all 3 canonical PrivateDnsZone rows carrying linkedVnetIds."
  implication: "The Fabric re-normalization path is not the cause of firewall/Bastion/NIC/private-endpoint disconnection, but it definitively loses Private DNS links by ignoring the canonical linkedVnetIds field."

- timestamp: "2026-09-01T23:38:00+08:00"
  checked: "Raw-live-like rows through NetworkIntelligenceService.from_rows"
  found: "Removing entityType/entity_type from otherwise property-complete network rows yields zero typed network families, zero resources, and zero relationships."
  implication: "The scoped hybrid_network implementation is contract-incompatible with its raw ARG query; it must normalize/classify raw rows before typed loading. This causes an empty scoped graph, not the reproduced floating-node symptom."

- timestamp: "2026-09-01T23:42:00+08:00"
  checked: "InventoryDatasetMapper and Fabric semantic network-service projection"
  found: "Mapper output preserves all affected subnet/VNet attributes and emits 7 attachedTo, 3 resolvesFor, and 3 hasNetworkInterface relationships. Feeding mapped ontology entities/relationships to NetworkIntelligenceService yields 82 resources and 89 relationships, including all affected hosts/attached_to/serves edges."
  implication: "Ontology mapping and the Fabric semantic service are not the source of the reported non-DNS disconnections for the synchronized local generation."

- timestamp: "2026-09-01T23:46:00+08:00"
  checked: "Exact frontend/Cytoscape probe setup and artifact search"
  found: "No recent screenshot artifact exists in the repository, and the first direct TypeScript probe could not run because web/node_modules has no tsx binary; Python exited on the closed pipe before emitting a payload."
  implication: "This is tooling setup, not product evidence. Use existing Vitest/Node tooling or a temporary test added only after the cause is confirmed."

- timestamp: "2026-09-01T23:50:00+08:00"
  checked: "Network scope and page request path"
  found: "The page passes the global scope to all network endpoints. NetworkScope filters every entity family independently by connection/subscription/environment/business service/application/owner, after which relationship guards drop edges with a missing endpoint."
  implication: "Scope mismatch is a plausible mechanism in general, but must reproduce with synchronized metadata before it can explain this report."

- timestamp: "2026-09-01T23:50:00+08:00"
  checked: "Private endpoint DNS child-resource ingestion"
  found: "No query or local generic resource row covers `microsoft.network/privateEndpoints/privateDnsZoneGroups`; normalize_private_endpoint only checks a singular nested `privateDnsZoneGroup` object."
  implication: "Real Azure private DNS zone-group child resources are currently invisible, so endpoint DNS membership can be reported missing even when configured. This is adjacent to the requested DNS inspection behavior and needs contract coverage."

- timestamp: "2026-09-01T23:55:00+08:00"
  checked: "Every current NetworkScope dimension"
  found: "Connection, subscription, environment, business-service, application, and owner filters each retain all 82 resources and 86 reconstructed relationships for the synchronized local generation."
  implication: "Scope filtering does not reproduce the reported current local disconnections; eliminate it for this dataset."

- timestamp: "2026-09-01T23:55:00+08:00"
  checked: "Exact backend payload through TypeScript buildTopologyGraph"
  found: "Frontend projection produced 82 nodes and 89 edges, including firewall/Bastion/NIC/private-endpoint hosts/attached_to edges and all 3 DNS serves edges with resolved node IDs."
  implication: "Frontend graph projection is not dropping current canonical links. Non-DNS disconnections are explained by bypassing canonical normalization in the scoped raw-live path, not by the synchronized canonical or frontend paths."

- timestamp: "2026-09-01T23:55:00+08:00"
  checked: "Generic synchronized Azure resource types"
  found: "The inventory includes parent Private DNS zones and virtualNetworkLinks child resources, but includes no privateEndpoints/privateDnsZoneGroups child resources because the query catalog never requests them."
  implication: "The DNS-zone link path demonstrates the required parent/child merge pattern; private endpoint DNS groups need equivalent handling."

- timestamp: "2026-09-02T00:02:00+08:00"
  checked: "Canonical-normalization counterfactual on raw-like current Resource rows"
  found: "Grouping rows with NETWORK_RESOURCE_TYPES and passing them through Normalizer restored 2 VNets, 8 subnets, 1 firewall, 1 Bastion, 3 NICs, 2 private endpoints, 3 DNS zones, and every expected hosts/attached_to/serves edge."
  implication: "The raw-hybrid cause is causal rather than correlational: changing only the missing canonicalization boundary restores the affected graph families."

- timestamp: "2026-09-02T00:07:00+08:00"
  checked: "Agent-authored regression test design"
  found: "Created tests/test_network_topology_links_regression.py with specified-oracle cases for raw ARG attachment edges, Private DNS zone-group child merging, canonical Fabric DNS links, an unlinked standalone zone, and its linked boundary neighbor."
  implication: "The tests exercise each confirmed root-cause boundary without modifying the protected fabric-topology-rollout test files."

- timestamp: "2026-09-02T00:10:00+08:00"
  checked: "Focused RED run"
  found: "Four root-cause tests fail exactly at their boundaries: from_arg_rows is absent, endpoint privateDnsZoneIds stays empty, Fabric resolvesFor is absent, and zone-only gaps are empty. The linked-zone boundary neighbor passes."
  implication: "The regression suite reproduces every confirmed omission before production changes; implement one boundary at a time."

- timestamp: "2026-09-02T00:14:00+08:00"
  checked: "Raw-ARG regression after adding canonical entry point"
  found: "The test advances past method construction and reports multiple attachment edges, but the expected NIC-to-workloads attachment is absent."
  implication: "The canonical entry point is active, but the exact NIC output must be observed before deciding whether production code or the test oracle is wrong."

- timestamp: "2026-09-02T00:16:00+08:00"
  checked: "Raw topology relationships after canonicalizing the regression fixture"
  found: "Firewall, Bastion, and private endpoint each emit attached_to plus reverse hosts; NIC emits reverse hosts only. The DNS zone emits serves to the VNet. All reported resources are therefore visually linked."
  implication: "The scoped-live fix restores every reported link, but the new test may over-specify an attached_to direction for NIC; check the established typed-topology contract before changing production behavior."

- timestamp: "2026-09-02T00:19:00+08:00"
  checked: "Existing typed and semantic topology contracts"
  found: "The typed display builder intentionally emits Subnet-hosts-NIC, while ontology tests separately require NetworkInterface-attachedTo-Subnet. Normalizer produces the semantic edge, but the new raw entry point currently flattens only entities."
  implication: "Preserving Normalizer relationships in from_arg_rows may satisfy both established contracts without adding a redundant rule to the healthy direct-edge builder."

- timestamp: "2026-09-02T00:22:00+08:00"
  checked: "Topology semantic-edge merge path"
  found: "NetworkIntelligenceService.from_rows accepts semantic_relationships and TopologyBuilder maps canonical attachedTo into display attached_to only when both endpoint resources exist."
  implication: "The raw entry point should preserve the graph it normalized, not discard its relationships; this is narrower than changing global topology derivation."

- timestamp: "2026-09-02T00:23:00+08:00"
  checked: "Raw-ARG regression with normalized relationships preserved"
  found: "The NIC attached_to assertion still fails, so passing graph.relationships did not add that edge."
  implication: "The assumption that Normalizer emits the NIC semantic relationship may be wrong; inspect its concrete output."

- timestamp: "2026-09-02T00:25:00+08:00"
  checked: "Concrete Normalizer output for the raw NIC"
  found: "Normalizer emits the NetworkInterface entity and an attachedTo relationship to the workloads subnet, but uses subjectId/objectId. NetworkTopology consumes subject_id/object_id."
  implication: "The raw canonical adapter must translate relationship field names as well as preserve the relationships."

- timestamp: "2026-09-02T00:28:00+08:00"
  checked: "Raw-ARG regression after relationship key adaptation"
  found: "test_raw_arg_rows_build_all_reported_network_links passes."
  implication: "Scoped live raw rows now produce all specified attachment/hosting and DNS-to-VNet relationships; proceed to the independent DNS child-resource boundary."

- timestamp: "2026-09-02T00:32:00+08:00"
  checked: "Private DNS zone-group regression after query and merge changes"
  found: "test_private_endpoint_dns_zone_group_child_enriches_parent passes; the parent endpoint has the normalized child zone ID and the child is not emitted as a duplicate endpoint."
  implication: "The missing child query/merge boundary is repaired; proceed to Fabric's independent canonical PrivateDnsZone omission."

- timestamp: "2026-09-02T00:35:00+08:00"
  checked: "Fabric canonical Private DNS regression"
  found: "test_fabric_derivation_preserves_canonical_dns_links passes after normalize_private_dns_zone preserves linkedVnetIds and both onboarding/Fabric derivation enqueue those canonical links."
  implication: "Fabric now emits resolvesFor from both raw child-link and canonical parent shapes; proceed to zone-only gap analysis."

- timestamp: "2026-09-02T00:38:00+08:00"
  checked: "Standalone Private DNS zone gap and linked boundary"
  found: "Both boundary tests pass: an unlinked zone yields one zone-targeted dns_dependency_gap, while a linked zone yields none."
  implication: "Zone-only gap analysis is repaired without false-positive findings for linked zones."

- timestamp: "2026-09-02T00:40:00+08:00"
  checked: "Combined focused regression file"
  found: "All five tests pass together."
  implication: "The four defect boundaries and linked-zone neighbor are green; inspect adjacent pipeline contracts before broader verification."

- timestamp: "2026-09-02T00:43:00+08:00"
  checked: "Fabric topology input path"
  found: "Fabric sync reads canonical PrivateEndpoint.jsonl into network_private_endpoints, so endpoint zone-group children are merged upstream by Normalizer and are not expected as direct derive_edges inputs."
  implication: "No duplicate child merge is needed in topology_pipeline; keep the Fabric change limited to canonical linkedVnetIds."

- timestamp: "2026-09-02T00:45:00+08:00"
  checked: "Working-tree status and query catalog"
  found: "Only four production files appear modified even though service/runtime/query were edited, and query_catalog's endpoint tuple is malformed on one line."
  implication: "Those paths may carry assume-unchanged/skip-worktree flags or pre-existing hidden edits; inspect index state before further verification."

- timestamp: "2026-09-02T00:48:00+08:00"
  checked: "Git index flags and object hashes"
  found: "All inspected paths are ordinary tracked files and their local/index/HEAD object hashes match; HEAD now contains the raw-ARG changes, regression test, and malformed query tuple. This occurred without any agent-issued commit command."
  implication: "Treat concurrent/external HEAD advancement as the new baseline, do not reset it, and make the formatting correction as a normal working-tree edit."

- timestamp: "2026-09-02T00:51:00+08:00"
  checked: "Focused Ruff checks"
  found: "Lint reports six local issues: unnecessary Z replacement, one import-order swap, and four unparenthesized split test literals. Format check also reports broad pre-existing formatting drift, especially in runtime.py."
  implication: "Fix only local lint findings; do not mass-format large files or protected unrelated code."

- timestamp: "2026-09-02T00:54:00+08:00"
  checked: "Formatter diagnostic inventory"
  found: "Ruff format would rewrite all eight inspected files, including very large pre-existing sections unrelated to this fix."
  implication: "A mass-format is not a minimal or safe fix; rely on zero focused lint findings and diff review for changed-line style."

- timestamp: "2026-09-02T00:56:00+08:00"
  checked: "Focused lint and regression rerun"
  found: "Ruff lint passes all eight focused paths and all five focused regressions remain green."
  implication: "Proceed to adjacent regression suites and frontend/API integration checks."

- timestamp: "2026-09-02T00:59:00+08:00"
  checked: "Adjacent Python network/onboarding/query/Fabric suites"
  found: "The combined adjacent suite completed at 100% with zero failures."
  implication: "Existing topology, analysis, ontology, query-catalog, and Fabric-pipeline behavior remains compatible."

- timestamp: "2026-09-02T01:03:00+08:00"
  checked: "API runtime and frontend graph integration"
  found: "tests/test_api_runtime.py passes (18 tests) and web/src/lib/network-graph.test.ts passes all 53 tests. Existing frontend tests explicitly preserve arbitrary resource relationships and case-insensitive ARM endpoint matching."
  implication: "The API provider remains healthy and no frontend adapter change is required for the restored backend relationships."

- timestamp: "2026-09-02T01:14:00+08:00"
  checked: "Complete Python suite and frontend type check"
  found: "Frontend npx tsc --noEmit passes. Full Python suite reaches 100% with five failures in unrelated MCP catalog, remediation fixture/projection, DefenderAssessment incremental state, and source-status tests; the focused import-graph suites remain green and none of these failures exercise the network fix. Several directly reflect the concurrent Defender/remediation commit."
  implication: "Record the full-suite baseline failures but treat the adjacent-test guardrail as passing based on the network/onboarding/API/Fabric suites; proceed to isolated revert-and-reconfirm."

- timestamp: "2026-09-02T01:19:00+08:00"
  checked: "Guardrail revert in detached HEAD^ worktree"
  found: "The agent-authored regression test returns exactly four failures and one pass: from_arg_rows absent, child zone IDs empty, canonical Fabric resolvesFor absent, and standalone-zone gaps empty."
  implication: "The original defect boundaries return when the complete fix is absent, without modifying or stashing the active protected working tree."

- timestamp: "2026-09-02T01:20:00+08:00"
  checked: "Guardrail reapply confirmation in active worktree"
  found: "The same focused regression test passes all five cases in the active fixed tree."
  implication: "Revert-and-reconfirm passes: bug_returned_on_revert=true and fixed_on_reapply=true."

- timestamp: "2026-09-02T01:24:00+08:00"
  checked: "Fix-acceptance no-op/deletion and mutation-tool signals"
  found: "The complete production diff is behavior-adding (171 additions, 12 replacements/deletions across target files), has no whitespace errors, and contains no short-circuit or assertion weakening. No Stryker configuration exists and the fix is Python, so the prescribed mutation signal is explicitly skipped."
  implication: "No-op/deletion passes; mutation_check is skipped per the guardrail degradation rule; all other applicable signals pass."

- timestamp: "2026-09-01T23:34:00+08:00"
  checked: "Autonomous resume verification"
  found: "Focused topology backend guardrails pass, frontend graph/topology tests pass 64/64, TypeScript no-emit passes, Ruff focused lint passes, and git diff whitespace checks pass."
  implication: "The repository fix is complete for the reported topology relationship and Private DNS gap behavior; the remaining live-network refresh is an operational deployment/sync step outside this local code task."

- timestamp: "2026-09-01T23:34:00+08:00"
  checked: "Full Python suite baseline"
  found: "Full Python suite still has five unrelated failures in MCP catalog ordering, remediation dependency/projection fixtures, DefenderAssessment incremental state, and source-status handling."
  implication: "These failures are outside the topology relationship fix path and do not block this maintenance fix; they remain separate existing work."

## Eliminated

- hypothesis: "The shared normalizers omit the firewall, Bastion, NIC, private endpoint, or Private DNS attachment references in the current synchronized snapshot."
  evidence: "Read-only direct loading found every referenced subnet/VNet present and both persisted and API-projected relationship sets contain the expected edges."
  timestamp: "2026-09-01T23:28:00+08:00"

- hypothesis: "InventoryDatasetMapper or the ontology projection drops firewall, Bastion, NIC, private endpoint, or Private DNS references from the current generation."
  evidence: "Mapped ontology rows retain the attributes and relationships, and the exact Fabric semantic network-service path emits all expected connections."
  timestamp: "2026-09-01T23:42:00+08:00"

- hypothesis: "NetworkScope filtering or frontend buildTopologyGraph drops current canonical relationship endpoints."
  evidence: "All supported synchronized scope filters retained the complete graph, and exact TypeScript projection retained 89 edges including every reported family."
  timestamp: "2026-09-01T23:55:00+08:00"

## Resolution

root_cause:
  - "Scoped hybrid network requests pass raw ARG rows without entityType through NetworkSnapshotLoader, which only buckets canonical ontology entity types, so canonical attachment relationships are never built."
  - "Fabric topology derivation re-normalizes canonical PrivateDnsZone rows as raw parents, resets linkedVnetIds, and only emits resolvesFor from absent virtualNetworkLinks child rows."
  - "Private endpoint privateDnsZoneGroups child resources are excluded from the network query contract and are not merged into parent endpoint privateDnsZoneIds."
  - "The private-DNS gap rule only iterates private endpoints, so a standalone PrivateDnsZone with no VNet links can never produce an inspection-gap finding."
fix:
  - "Added a raw-ARG service constructor that runs the shared Normalizer, adapts canonical relationship keys, and is used by scoped hybrid network requests."
  - "Queried and merged privateEndpoints/privateDnsZoneGroups child resources into parent endpoint DNS zone IDs."
  - "Preserved canonical PrivateDnsZone.linkedVnetIds and emitted resolvesFor in onboarding and Fabric derivation."
  - "Added a zone-level dns_dependency_gap for enabled-policy Private DNS zones with no VNet links."
verification:
  target_test:
    result: pass
    suite: "tests/test_network_topology_links_regression.py — 5 passed"
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker configuration is present and the changed implementation is Python; isolated revert-and-reconfirm covered all four agent-authored defect assertions."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: false
    evidence: "Production changes add canonicalization, child merge, relationship derivation, and gap creation; no behavior-deleting shortcut or weakened assertion."
  adjacent_tests:
    result: pass
    suites_run:
      - "tests/test_network_topology.py"
      - "tests/test_network_analysis.py"
      - "tests/test_network_semantic.py"
      - "tests/test_network_ontology.py"
      - "tests/test_queries.py"
      - "tests/test_topology_pipeline.py"
      - "tests/test_api_runtime.py — 18 passed"
      - "web/src/lib/network-graph.test.ts — 53 passed"
    note: "The full Python suite reached 100% with five unrelated failures in MCP/remediation/Defender/source-status areas introduced or exposed by concurrent work; no adjacent network suite failed."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    evidence: "Detached HEAD^ worktree produced 4 failed/1 passed; active tree produced 5 passed."
  additional_checks:
    ruff: pass
    typescript_no_emit: pass
    diff_check: pass
    formatter: "not applied — Ruff would mass-format all inspected files due pre-existing baseline drift"
  guardrail_verdict: accepted
files_changed:
  - src/network/service.py
  - src/api/runtime.py
  - src/onboarding/query_catalog.py
  - src/onboarding/network_normalize.py
  - src/onboarding/graph_normalize.py
  - src/fabric_pipelines/topology_pipeline.py
  - src/network/gaps.py
  - tests/test_network_topology_links_regression.py
oracle_type: "specified — all Azure subnet/VNet attachments in the report must produce graph edges, and every enabled-policy PrivateDnsZone without a VNet link must produce a gap."
