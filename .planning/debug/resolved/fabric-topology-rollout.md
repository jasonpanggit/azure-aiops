---
status: resolved
trigger: "Topology staged rollout verification failed: topology_entities and topology_edges were not present_known or active after enabling topology_pipeline and running the Fabric sync."
created: 2026-09-01T18:10:35+08:00
updated: 2026-09-01T15:32:39Z
---

# Debug Session: Fabric Topology Rollout

## Symptoms

- **Expected behavior:** Enabling only `topology_pipeline.enabled` and running the documented Fabric sync publishes `topology_entities` and `topology_edges`, with both classified as `present_known` and active.
- **Actual behavior:** The sync completes without those tables becoming `present_known`; the validator reports both tables missing/inactive and 14 expected missing tables without dispositions.
- **Error messages:** `ERROR: topology tables not present_known: topology_entities, topology_edges` and `ERROR: topology tables not active: topology_entities, topology_edges`.
- **Timeline:** Discovered during Phase 10 plan 10-09 Task 3 staged live rollout verification.
- **Reproduction:** Securely load the SPN from `web/.env.local`, enable topology while ontology remains disabled, run the documented `aiops-inventory fabric` sync, then run `scripts/validate-lakehouse-tables.py` against the configured dev Fabric workspace.

## Current Focus

hypothesis: "Resolved: topology rollout blocker required a coordinated AND-gate fix across config/runtime/sync wiring, schema registration, governed topology envelope mapping, and topology manifest active upserts."
test: "Re-confirm focused topology regression trio on current branch and confirm human verification in real rollout workflow."
expecting: "Focused topology tests pass and user confirms issue is fixed end-to-end."
next_action: "Archive resolved session, update knowledge base, and commit only debug documentation artifacts."

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
- Local snapshot probe over `.aiops-local/.../entities/*.jsonl` fed to `topology_pipeline.derive_edges` produced non-zero outputs (`82` topology entities, `78` topology edges), confirming data availability for topology generation in this workspace.
- Differential probe with and without a `resourceType -> type` adapter produced identical counts (`82` entities, `78` edges), so row-shape adaptation is not a contributing blocker for current snapshot data.
- Code search found no runtime path that writes `metadata_publication_manifest` (no references in `src/fabric/sync_service.py`, `src/fabric/runtime.py`, or `src/fabric_pipelines/*`), so disposition values remain `unknown` unless populated externally.
- Added RED regression assertion in `tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths` expecting `config.topology_pipeline.enabled` and `config.ontology_pipeline.enabled`; this currently fails due to missing config fields.
- Added RED regression test `tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables` expecting topology tables plus active manifest entries when `topology_enabled=True`; current service ctor does not accept topology flag and has no manifest writer path.
- Added RED regression test `tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables` asserting `SCHEMAS` includes `topology_entities`/`topology_edges`; current schema registry lacks these keys.
- Targeted rerun after wiring changes produced `.F.`: `test_fabric_runtime_config_resolves_local_paths` and `test_validator_known_table_set_includes_topology_contract_tables` now pass, but `test_sync_with_topology_flag_publishes_topology_tables` fails with `ValueError: Fabric data quality validation failed: 9 records` during `FabricSyncService.sync()`.
- `DataQualityValidator` enforces base required fields (`tenant_id`, `subscription_id`, `resource_id`, `timestamp`, `change_version`, `ingestion_run_id`) and exact schema parity (`set(row) == set(schema.names)`), while currently generated topology rows use topology-only keys (`entity_id`, `relationship_id`, etc.), making validation failure expected unless sync maps topology payloads into the governed base-envelope schema.
- `src/fabric/sync_service.py::_validate` validates every dataset entry via `validate_table`/`validate_relationships` before any table writes; thus topology row-shape mismatch blocks sync completion prior to topology table publish/manifest writes.
- Direct import probe initially failed because `tests/test_incremental_sync.py` imports `topology_comparison_scenario` from `tests/fixtures`, requiring PYTHONPATH adjustment (or equivalent) for standalone debug scripts.
- Located fixture module at `tests/topology_comparison_scenario.py`; prior `PYTHONPATH=tests/fixtures` was incorrect for this import path.
- Focused validation probe (`PYTHONPATH=tests`) isolated the 9 quality failures entirely to topology datasets: `topology_entities` has 5 `required_fields` failures missing `resource_id,timestamp,change_version,ingestion_run_id`; `topology_edges` has 4 `required_fields` failures missing `tenant_id,subscription_id,resource_id,timestamp,change_version,ingestion_run_id`.
- `_validate` runs before any table write, and failures are `required_fields` only (not schema parity), confirming the blocker is DataQuality base-envelope expectations versus topology row shape introduced in sync path.
- Implemented envelope mapping in `FabricSyncService._extend_with_topology_tables` to emit governed topology rows containing required base fields while retaining topology contract columns (`entity_id`/`relationship_id` etc.), with deterministic `change_version` hashing and fallback tenant/subscription derivation from linked entity IDs.
- Re-running targeted tests still fails with the same 9-record quality error, and code inspection shows `_validate` now receives governed topology rows (base fields added). This falsifies the “missing required_fields remains the blocker” sub-hypothesis; next likely blocker is schema-registry shape mismatch because topology schemas currently reference raw contract-only columns.
- Updated `schema_registry` topology entries to governed schemas (`_BASE` envelope + topology contract columns), aligning `validate_table` schema parity with the governed topology rows emitted by sync.
- Targeted regression rerun is now green: `tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths`, `tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables`, and `tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables` all pass.
- Adjacent regression suites passed cleanly: `tests/test_incremental_sync.py`, `tests/test_fabric_client.py`, `tests/test_topology_pipeline.py`, `tests/test_publication_manifest.py`, and `tests/test_data_quality.py`.
- Current working tree confirms the topology fixset is present in code and tests (`config.py`, `runtime.py`, `sync_service.py`, `schema_registry.py`, targeted tests), with `git status` showing only these intended files plus the debug session file modified.
- Guardrail signal #1 (target test greens) passed: `.venv/bin/python -m pytest -q tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables` returned `... [100%]` exit 0.
- Guardrail signal #2 (mutation check) skipped: no Stryker config present (`STRYKER_CONFIG_MISSING`) and no mutation tooling references found in project manifests, so scoped mutant run is unavailable in this environment.
- Guardrail signal #3 (no-op/deletion detector) passed: `git diff --stat` across fix files reports `381 insertions(+), 0 deletions(-)`, and patch inspection shows additive wiring (config flags, runtime propagation, sync topology derivation + manifest upsert, schema registration, regression tests) with no branch short-circuit or behavior suppression.
- Guardrail signal #4 (adjacent tests) passed: `.venv/bin/python -m pytest -q tests/test_incremental_sync.py tests/test_fabric_client.py tests/test_topology_pipeline.py tests/test_publication_manifest.py tests/test_data_quality.py` completed green (`90 passed`, exit 0).
- Guardrail signal #5 first revert probe was inconclusive: after stashing topology fix files, newly added targeted test nodes no longer existed in baseline files (`pytest` reported test node not found). Need baseline-compatible failing assertions to complete the "bug returns on revert" leg without relying on removed test definitions.
- Baseline-compatible revert probe attempt failed due helper import coupling: `_source_snapshot_with_topology` is absent once topology test changes are stashed, so revert probe must avoid importing test helper functions from modified test files.
- Revert-and-reconfirm attempt left only the debug file modified in working tree and one stash (`stash@{0}`) containing the topology fixset; fix code must be reapplied before continued verification.
- Guardrail signal #5 revert leg confirmed (non-destructive): `git show HEAD:` probe of baseline code reports all required topology mechanisms absent (`topology_pipeline`/`ontology_pipeline` config fields missing, runtime does not pass `topology_enabled`, sync has no topology ctor/manifest path, schema registry lacks `topology_entities`/`topology_edges`), matching original failure mechanism.
- Guardrail signal #5 reapply leg confirmed: after reapplying stashed fixset, targeted trio rerun returned `... [100%]` exit 0 again, proving fix presence restores expected topology behavior.
- Temporary rollout config `.planning/debug/tmp-fabric-topology-rollout.yaml` created from `fabric.config.yaml` with rollout-safe overrides applied: `topology_pipeline.enabled=true`, `ontology_pipeline.enabled=false`, and `source_data_root=./.aiops-local/connections/local-spn`.
- Staged sync failed before execution because temporary config path was resolved relative to `.planning/debug` (config file directory), producing missing snapshot path `/Users/jasonmba/workspace/azure-aiops/.planning/debug/.aiops-local/...`; confirms local rollout config must use absolute `source_data_root` when staged config lives outside repo root.
- Temporary rollout config was corrected to absolute `source_data_root: /Users/jasonmba/workspace/azure-aiops/.aiops-local/connections/local-spn`, preserving staged-only topology enablement (`topology_pipeline.enabled=true`, `ontology_pipeline.enabled=false`) without modifying baseline `fabric.config.yaml`.
- Latest staged validator artifact `.planning/debug/tmp-topology-validate-report.json` (`mtime=2026-09-01T23:17:27Z`) reports `present_total=431`, `present_known_count=61`, `expected_missing_undispositioned_count=13`, `topology_entities ∈ present_known`, `topology_edges ∈ present_known`, and both dispositions set to `active`.
- Baseline safety check confirms `fabric.config.yaml` remains `fabric.topology_pipeline.enabled=False` and `fabric.ontology_pipeline.enabled=False` after staged validation.
- Re-confirmed focused topology regression trio on current branch passed green: `.venv/bin/python -m pytest -q tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables` returned `... [100%]` exit 0.
- Persistence check confirmed topology wiring remains present in current branch code (`config.py`, `runtime.py`, `sync_service.py`, `schema_registry.py`) via targeted `rg` probe for `topology_pipeline`, `topology_enabled`, `topology_entities`, and `topology_edges`.
- Human verification checkpoint response received: "Confirmed fixed."

## Resolution

- **root_cause:** Topology rollout required an AND-gate fix across three missing mechanisms: runtime/config never enabled topology sync, schema registry omitted topology tables from known set, and sync lacked publication-manifest active upserts; additionally topology rows had to be mapped into governed envelope shape to satisfy data-quality validation.
- **fix:** Added topology/ontology pipeline flag parsing in config, passed `topology_enabled` through runtime into sync service, derived and emitted governed topology rows (`topology_entities`, `topology_edges`) during sync, upserted active publication-manifest records for topology tables, and registered governed topology schemas in schema registry.
- **verification:** Guardrail signals passed (target tests, adjacent suites, no-op/deletion, revert/reconfirm), mutation unavailable (`STRYKER_CONFIG_MISSING`), and staged validator report confirms both topology tables are present_known and active while baseline rollout flags stayed false.
- **files_changed:** `src/fabric/config.py`, `src/fabric/runtime.py`, `src/fabric/sync_service.py`, `src/fabric/schema_registry.py`, `tests/test_fabric_client.py`, `tests/test_incremental_sync.py`, `tests/test_topology_pipeline.py`
