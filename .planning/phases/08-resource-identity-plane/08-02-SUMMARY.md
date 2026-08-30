---
phase: 08-resource-identity-plane
plan: 02
subsystem: fabric-topology-pipeline
tags: [fabric-iq, delta-tables, ontology-binding, nsg, flow-log, notebook, hermes-comparison]

requires:
  - phase: 08-resource-identity-plane
    provides: "InventoryReadPort containment + lossless-properties adapter, byte-identical normalizer equivalence proof (08-01)"
provides:
  - "topology_pipeline.derive_edges() reproducing Hermes's full _add_edge/_normalize_network predicate vocabulary verbatim, sourced from inventory-shaped rows"
  - "topology_entities/topology_edges Delta table contracts + TopologyOneLakePublisher (reuses existing DeltaWriter/OneLakeWriter, no new writer)"
  - "flowlog_ingest.py: fixture-only NSG-rule x flow-log directional join with explicit allowed/observed classification (D-11)"
  - "ontology_binding.py: TopologyOntologyBinder registering topology tables into Fabric IQ using its own native traversal surface (no KQL/Gremlin/new dependency)"
  - "notebook_manager.py: genuine Fabric-hosted Notebook item definition + NotebookManager (create/update/run-on-demand) satisfying the fabric-hosted-notebook compute-architecture decision"
  - "tests/topology_comparison_scenario.py: shared VNet/Subnet/NSG fixture usable by both this pipeline and (08-03) Hermes's SemanticEngine"
affects: [08-03-comparison-and-removal-gate]

actuals:
  tokens: 16400
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Ported deterministic derivation logic verbatim from hermes_arg_connector rather than re-implementing (same _add_edge hash scheme, same network_normalize.py normalizer calls, same _base/_resource_group_key/_subscription_key ports)"
    - "Fabric-hosted notebook cells call this repo's own pure Python package functions rather than re-authoring the predicate vocabulary a second time inside notebook code"
    - "Ontology-binding wire format (parts/EntityTypes/RelationshipTypes/base64 InlineBase64) copied from the existing ontology_publisher.py convention rather than inventing a second Fabric-item encoding"

key-files:
  created:
    - src/fabric_pipelines/__init__.py
    - src/fabric_pipelines/topology_fabric_contracts.py
    - src/fabric_pipelines/topology_pipeline.py
    - src/fabric_pipelines/flowlog_ingest.py
    - src/fabric_pipelines/ontology_binding.py
    - src/fabric_pipelines/notebook_manager.py
    - tests/topology_comparison_scenario.py
    - tests/test_topology_pipeline.py
  modified:
    - fabric.config.yaml
    - fabric.config.example.yaml
    - pyproject.toml

key-decisions:
  - "Checkpoint 1 (compute architecture): fabric-hosted-notebook — a genuine Fabric workspace Notebook item (NotebookManager + build_notebook_definition), not merely an extension of the existing Python DeltaWriter/OneLakeWriter pattern. Operator explicitly wants this demoable to users visually."
  - "Checkpoint 2 (flow logs): fixture only — no live NSG Flow Logs/Traffic Analytics provisioning this phase. flowlog_ingest.py is built entirely against a synthetic/curated flow-log fixture; every derived edge is tagged source=fabric_pipeline:flowlog_fixture, assertionState=fixture_only, and attributes.dataSource=fixture so the 08-03 comparison report can flag 'allowed vs. observed' results as fixture-only, not live-data-validated."
  - "Checkpoint 3 (traversal mechanism): fabric-iq-native — blast-radius queries run through Fabric IQ's own query/traversal surface. No azure-kusto-data dependency, no KQL/Eventhouse make-graph construct, no Gremlin/Cosmos DB graph. ontology_binding.py's registration step is both the binding and the traversal surface."
  - "The tracer task (Task 1) used the Python-writer pattern for the Delta-materialization layer even after the fabric-hosted-notebook decision was recorded, because that decision governs the compute-architecture claim (where derivation actually executes), not the write-to-Delta step, which correctly reuses proven Phase 7 machinery regardless of compute surface (Don't Hand-Roll). Task 2's notebook_manager.py is where the genuine Fabric-hosted compute claim is satisfied."
  - "ontology_binding.py deliberately does not reuse ontology.OntologyPublisher's build_definition() directly — that publisher's ENTITY_COLUMNS/property scheme is keyed to inventory's resource_id-shaped rows, while topology entities are entity_id-keyed with a different column set. Reused the same wire-format conventions (parts, base64 encoding, numeric-ID derivation, non-sort_keys JSON) instead of forcing an incompatible shared function."

requirements-completed: [INV-10, INV-11]

coverage:
  - id: D1
    description: "topology_pipeline.derive_edges() reproduces Hermes's _add_edge content-addressed relationshipId scheme byte-identically for the same subject/predicate/object/source inputs"
    requirement: "INV-10"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_protects_by_edge_relationship_id_matches_hermes_add_edge_scheme"
        status: pass
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_derive_edges_produces_expected_entities_and_predicates"
        status: pass
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_derive_edges_covers_default_deny_rule_and_hasrule_predicate"
        status: pass
    human_judgment: false
  - id: D2
    description: "confidence/source/assertionState survive unchanged through to the topology_edges Delta row (T-08-06, D-05: unknown/stale/conflicting must remain explicit)"
    requirement: "INV-11"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_edge_rows_preserve_confidence_source_and_assertion_state"
        status: pass
    human_judgment: false
  - id: D3
    description: "topology_entities/topology_edges rows are written to real Delta tables via the reused DeltaWriter/OneLakeWriter machinery (no new writer)"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_pipeline_writes_topology_entities_and_edges_to_delta_tables"
        status: pass
    human_judgment: false
  - id: D4
    description: "flowlog_ingest.py joins NSG rules against a fixture-only flow-log dataset and explicitly classifies allowed-vs-observed (not silently collapsed)"
    requirement: "INV-11"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_flowlog_ingest_join_is_fixture_only_and_classifies_allowed_vs_observed"
        status: pass
    human_judgment: false
  - id: D5
    description: "ontology_binding.py registers topology tables into Fabric IQ without any 'detect'/'infer' relationship-discovery language (Pitfall 2/D-10 boundary)"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_ontology_binding_registers_topology_tables_without_inferring_relationships"
        status: pass
    human_judgment: false
  - id: D6
    description: "A genuine Fabric-hosted Notebook item definition exists whose cells call this package's own derive_edges/join functions (fabric-hosted-notebook compute-architecture decision)"
    verification:
      - kind: unit
        ref: "tests/test_topology_pipeline.py::test_notebook_definition_authors_genuine_fabric_hosted_notebook_item"
        status: pass
    human_judgment: true
    rationale: "Unit tests prove the notebook definition's structure and cell content, but actually creating/running the item against a live Fabric workspace (Fabric REST API create + on-demand run) was not exercised this session — no live Fabric credentials/workspace access in this environment. A human must verify the notebook item actually deploys and runs successfully against the real workspace before 08-03's comparison relies on its output."

duration: 55min
completed: 2026-08-27
status: complete
---

# Phase 08 Plan 02: Fabric-Native Topology Comparison-Arm Pipeline Summary

**Built a genuine Fabric-hosted-notebook pipeline that reproduces Hermes's `_add_edge`/`_normalize_network` predicate vocabulary and content-addressed relationship-ID scheme byte-for-byte against inventory-owned identity data, plus a fixture-only NSG-rule/flow-log directional topology join, both landed as `topology_entities`/`topology_edges` Delta tables and bound into Fabric IQ ontology via its own native traversal surface — the technical comparison arm 08-03's Hermes viability gate will measure against.**

## Performance

- **Duration:** ~55 min (including 3 blocking checkpoint round-trips)
- **Tasks:** 4/4 completed (1 checkpoint:decision, 1 tracer, 1 checkpoint:human-verify, 1 checkpoint:decision, 1 auto task — see Task Commits)
- **Files modified:** 11 (8 created, 3 modified)

## Accomplishments

- `topology_pipeline.derive_edges()` reproduces the **full** predicate vocabulary from Hermes's `_normalize_network` (`belongsTo`, `contains`, `protectedBy`, `routedBy`, `egressesVia`, `hasPeering`/`peersWith`, `hasRule`, `attachedTo`, `hasNetworkInterface`, `enforcesPolicy`, `hasRuleCollection`, `exposesPrivately`, `resolvesFor`, `loadBalances`) by calling the real `network_normalize.py` normalizer functions verbatim (`normalize_vnet`, `normalize_nsg`, `normalize_nic`, `normalize_route_table`, `normalize_firewall`, `normalize_firewall_policy`, `normalize_private_endpoint`, `normalize_private_dns_zone`, `normalize_gateway`, `normalize_load_balancer`) — no re-derivation, no parallel reimplementation.
- `_add_edge`'s exact `sha256(subject|predicate|object|source)[:24]` content-addressed ID scheme is ported byte-for-byte; cross-verified directly against `hermes_arg_connector.normalize._add_edge` for the same inputs producing an identical `relationshipId`.
- `topology_fabric_contracts.py` defines `TOPOLOGY_ENTITIES_CONTRACT`/`TOPOLOGY_EDGES_CONTRACT` mirroring `InventoryFabricContract`'s shape; `TopologyOneLakePublisher` reuses the exact `DeltaWriter`/`OneLakeWriter` machinery `InventoryOneLakePublisher` already uses — no new writer was built.
- `flowlog_ingest.py` joins NSG rule rows (matching `network_normalize.py:198-251`'s exact shape, including the retained `isDefault` implicit-deny rule) against a curated/synthetic flow-log fixture on source/dest/port/protocol, producing directional edges with an explicit four-way classification (`allowed_and_observed`, `denied_and_blocked`, `allowed_but_not_observed_as_permitted`, `denied_but_traffic_observed`) rather than collapsing to one verdict — this is fixture-only, tagged `assertionState=fixture_only` and `source=fabric_pipeline:flowlog_fixture`, per the resolved human-verify checkpoint (no live NSG Flow Logs/Traffic Analytics ingestion exists in this subscription).
- `ontology_binding.py`'s `TopologyOntologyBinder` registers the materialized `topology_entities`/`topology_edges` tables into Fabric IQ ontology using Fabric IQ's own native query/traversal surface (per the resolved `fabric-iq-native` checkpoint) — no KQL/Eventhouse `make-graph`, no Gremlin/Cosmos DB graph, no new `azure-kusto-data` dependency. Runs strictly after both Delta tables are populated and never configures Fabric IQ to "detect" or "infer" relationships (test explicitly greps the built definition for those words).
- `notebook_manager.py` authors a genuine Fabric-hosted Notebook item definition (per the resolved `fabric-hosted-notebook` checkpoint) whose cells import and call this package's own `derive_edges`/`join_flow_logs_with_nsg_rules` functions rather than re-implementing the predicate vocabulary a second time inside notebook code — one derivation implementation, two execution surfaces (local/CI-tested Python and genuine Fabric Spark compute).
- `tests/topology_comparison_scenario.py` is the single shared VNet/Subnet/NSG fixture (Pitfall 3 guard) structured to feed both this pipeline's `derive_edges()` and, in 08-03, Hermes's `SemanticEngine.from_rows()`/`Normalizer` identically.
- `fabric.config.example.yaml`/`fabric.config.yaml` extended with a `topology_pipeline` block (notebook item id/name, ontology id/name, `flow_log_source: fixture`) following the existing schema pattern rather than hardcoding new identifiers in the pipeline.

## Task Commits

1. **Checkpoint: Fabric-native compute architecture decision** — `fabric-hosted-notebook` selected (no code commit; decision recorded)
2. **Task 1 (tracer): End-to-end topology derivation for one edge type, landed and bound** - `281bdf7` (feat)
3. **Checkpoint: NSG Flow Logs / Traffic Analytics provisioning decision** — `fixture only` selected (no code commit; decision recorded)
4. **Checkpoint: Traversal-mechanism decision** — `fabric-iq-native` selected (no code commit; decision recorded)
5. **Task 2 (auto): Full predicate vocabulary + NSG/flow-log join + ontology binding + Fabric-hosted notebook** - `dcab93b` (feat)

**Plan metadata:** (this commit, see below)

## Files Created/Modified

- `src/fabric_pipelines/__init__.py` - Package docstring establishing this as the D-04a comparison arm
- `src/fabric_pipelines/topology_fabric_contracts.py` - `TopologyFabricContract` dataclasses + `TOPOLOGY_ENTITIES_CONTRACT`/`TOPOLOGY_EDGES_CONTRACT` (mirrors `InventoryFabricContract`)
- `src/fabric_pipelines/topology_pipeline.py` - `derive_edges()` (full predicate vocabulary via real `network_normalize.py` calls), `_add_edge`/`_base`/`_resource_group_key`/`_subscription_key` byte-for-byte ports, `TopologyOneLakePublisher` (reuses `DeltaWriter`/`OneLakeWriter`)
- `src/fabric_pipelines/flowlog_ingest.py` - `FlowLogRecord`, `curated_flow_log_fixture()`, `join_flow_logs_with_nsg_rules()` with explicit allowed/observed classification, fixture-only tagging
- `src/fabric_pipelines/ontology_binding.py` - `TopologyOntologyBinder` (Fabric IQ ontology registration using its own native traversal surface, wire-format ported from `ontology_publisher.py`)
- `src/fabric_pipelines/notebook_manager.py` - `NotebookManager` (Fabric Items API resolve/create/update/run-on-demand), `build_notebook_definition()`, `ensure_notebook()`
- `tests/topology_comparison_scenario.py` - Shared VNet/Subnet/NSG raw-ARG-shaped fixture (Pitfall 3), plus `nsg_rule_rows()` helper for the flow-log join
- `tests/test_topology_pipeline.py` - 8 tests covering full predicate coverage, relationshipId cross-verification against Hermes's real `_add_edge`, confidence/source/assertionState preservation, Delta-table write proof, fixture-only flow-log classification, ontology non-inference guard, notebook-definition content
- `fabric.config.yaml`/`fabric.config.example.yaml` - New `topology_pipeline` config block (`fabric.config.yaml` is gitignored — real workspace/tenant IDs — so only the example file is committed; the real file was still edited on disk for local config parity)
- `pyproject.toml` - Registered `src/fabric_pipelines` as an editable package

## Decisions Made

See `key-decisions` in frontmatter for the three resolved checkpoints (compute architecture, flow-log provisioning, traversal mechanism) plus two implementation-scope decisions (tracer's writer-layer vs. compute-architecture-claim distinction; ontology_binding.py's independent wire format rather than reusing `OntologyPublisher.build_definition()` directly).

## Deviations from Plan

None — plan executed exactly as written, including all three blocking checkpoints resolved via operator input rather than auto-selected.

## Issues Encountered

- Same 3 pre-existing test failures noted in 08-01-SUMMARY.md observed again in the full-suite run (`tests/test_onelake_fs.py::test_resolve_fs_selects_the_dfs_native_backend`, `tests/test_situations_ontology.py::test_situations_are_registered_as_ontology_entities_with_typed_links`, `tests/test_storage.py::test_partial_publish_preserves_hash_baseline_for_next_full_publish`). Out of scope per the executor's scope-boundary rule — none of the touched files are in this plan's `files_modified` list. Not fixed, logged for visibility.
- `ruff check` initially flagged implicit string concatenation across the notebook's multi-line cell-source tuple and an f-string opportunity in the fixture module; both fixed inline before committing (not deviations — pure lint cleanup within files this plan already touched).

## User Setup Required

**External Fabric workspace deployment requires manual verification** (see D6 above, `human_judgment: true`):
- The Notebook item definition (`notebook_manager.build_notebook_definition()`) has not been deployed against a live Fabric workspace in this session — no live Fabric credentials/workspace access available in this environment.
- Before 08-03's comparison harness relies on this pipeline's live output, a human (or a follow-up plan with Fabric credentials) must run `ensure_notebook()` against the real workspace (`fabric.config.yaml`'s `topology_pipeline.notebook_item_id`/`notebook_display_name`), trigger `NotebookManager.run_on_demand()`, and confirm `topology_entities`/`topology_edges` land in the lakehouse and the ontology binds successfully via `TopologyOntologyBinder.bind()`.
- Until then, all unit-level proof (predicate parity, relationshipId scheme, Delta-write mechanics, ontology-definition shape) stands on local/CI-run pyarrow+deltalake, not a live Fabric Spark session.

## Next Phase Readiness

- The Fabric-native comparison arm (entity/edge derivation + fixture-only flow-log topology + ontology binding + genuine Fabric-hosted notebook) is code-complete and unit-tested, ready for 08-03's comparison harness to run the same blast-radius scenarios against its bound ontology as against Hermes's real engine.
- 08-03 must explicitly flag any flow-log-derived "allowed vs. observed" comparison result as fixture-only, not live-traffic-validated, per this plan's resolved checkpoint.
- 08-03 must also account for the live-deployment gap noted in "User Setup Required" above — if the comparison needs to run against a genuinely deployed Fabric notebook rather than local pytest execution, that deployment step (Fabric REST API create + run) has not yet been exercised against real credentials and should be verified first.

---
*Phase: 08-resource-identity-plane*
*Completed: 2026-08-27*

## Self-Check: PASSED

All 8 created/modified files verified present on disk. Both commit hashes (281bdf7, dcab93b) verified present in git log.

