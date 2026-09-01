---
status: investigating
trigger: "Topology staged rollout verification failed: topology_entities and topology_edges were not present_known or active after enabling topology_pipeline and running the Fabric sync."
created: 2026-09-01T18:10:35+08:00
updated: 2026-09-01T22:44:00+08:00
---

# Debug Session: Fabric Topology Rollout

## Symptoms

- **Expected behavior:** Enabling only `topology_pipeline.enabled` and running the documented Fabric sync publishes `topology_entities` and `topology_edges`, with both classified as `present_known` and active.
- **Actual behavior:** The sync completes without those tables becoming `present_known`; the validator reports both tables missing/inactive and 14 expected missing tables without dispositions.
- **Error messages:** `ERROR: topology tables not present_known: topology_entities, topology_edges` and `ERROR: topology tables not active: topology_entities, topology_edges`.
- **Timeline:** Discovered during Phase 10 plan 10-09 Task 3 staged live rollout verification.
- **Reproduction:** Securely load the SPN from `web/.env.local`, enable topology while ontology remains disabled, run the documented `aiops-inventory fabric` sync, then run `scripts/validate-lakehouse-tables.py` against the configured dev Fabric workspace.

## Current Focus

- hypothesis: rollout failure root cause remains dual deterministic code gap; topology inputs already exist via mapper network entity files, so missing link is sync orchestration plus known-table registration
- test: inspect sync-service and config test suites to place failing tests that prove missing config flag parsing and missing topology table publication in sync output
- expecting: identify smallest RED tests that fail pre-fix and pass post-fix without touching unrelated behavior
- next_action: read existing FabricSyncService tests and complete `InventoryDatasetMapper.load` dataset-key section

## Evidence

- The live validation artifact reported `present_total: 412`, `present_known: 58`, `expected_missing: 14`, and `expected_missing_undispositioned: 14`.
- The executor restored both topology and ontology flags to `false` after the failed checkpoint.
- Knowledge base lookup found no prior topology/fabric rollout pattern match; proceed with fresh hypothesis testing.
- `scripts/validate-lakehouse-tables.py` classifies `present_known` strictly from `fabric.schema_registry.SCHEMAS` plus inventory schemas; `topology_entities` and `topology_edges` are not declared in `SCHEMAS`.
- `src/fabric/schema_registry.py` contains ontology/silver/metadata schemas but no `topology_entities` or `topology_edges` entries, so those tables can never be `present_known` even if physically present.
- Code search found no runtime/sync references to `topology_pipeline` in `src/fabric/runtime.py` or `src/fabric/sync_service.py`; `topology_pipeline` is referenced only in standalone pipeline/tests/docs modules.
- Runtime probe attempt with `python` failed (`python: command not found`), indicating this environment requires `python3` or `.venv/bin/python` for scripted verification.
- `.venv/bin/python` probe of `FabricRuntimeConfig.load('fabric.config.yaml')` showed `has_topology_attr=False` and `has_ontology_pipeline_attr=False`; the loaded config object has no fields for either staged rollout flag.
- `src/fabric/sync_service.py` writes whatever `InventoryDatasetMapper.load(...)` returns and does not call `fabric_pipelines.topology_pipeline` anywhere, so enabling `topology_pipeline.enabled` currently cannot add `topology_entities`/`topology_edges`.
- `src/fabric/dataset_mapper.py` currently generates ontology/silver/bronze tables but no `topology_entities` or `topology_edges` keys in returned datasets.
- `fabric.config.yaml` currently sets `source_data_root: ./.hermes-local/connections/local-spn`, but that path is absent in this workspace snapshot while `.aiops-local/connections/local-spn/current` exists as the available local generation root.
- Code search (`rg`) confirms no `topology_pipeline`/`ontology_pipeline` references in `src/fabric/config.py` and `src/fabric/sync_service.py`; validator known-table classification is isolated to `scripts/validate-lakehouse-tables.py::known_table_names()` and `fabric.schema_registry.SCHEMAS`.
- `src/fabric/config.py::FabricRuntimeConfig` has no fields for `topology_pipeline` or `ontology_pipeline`; `load()` parses `fabric.ontology` but ignores those staged flags.
- `src/fabric/runtime.py::build_runtime()` constructs `FabricSyncService` without any topology enablement parameters; only legacy ontology publisher options are passed.
- `src/fabric/sync_service.py::_sync_locked()` writes datasets from `InventoryDatasetMapper.load(...)` and never calls topology pipeline derivation/publisher code.
- `src/fabric/schema_registry.py::schema_for` has pattern support for generated ontology tables only; neither `SCHEMAS` nor dynamic branches include `topology_entities`/`topology_edges`.
- `src/fabric/dataset_mapper.py` includes `NETWORK_ENTITY_TYPES` in `ENTITY_FILES` and ontology relationship vocabulary, confirming network inputs are already loaded from snapshots.
- `tests/test_topology_pipeline.py` proves standalone topology derivation and publisher can write `topology_entities`/`topology_edges` Delta tables, so failure is integration/wiring rather than missing pipeline implementation.
