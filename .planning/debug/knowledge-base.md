# GSD Debug Knowledge Base

Resolved debug sessions. Used by `gsd-debugger` to surface known-pattern hypotheses at the start of new investigations.

---

## fabric-topology-rollout — Topology tables missing from present_known/active during staged Fabric rollout
- **Date:** 2026-09-01
- **Error patterns:** topology_entities missing present_known, topology_edges missing present_known, topology tables not active, expected_missing_undispositioned
- **Root cause(s):** Topology rollout required an AND-gate fix across three missing mechanisms: runtime/config never enabled topology sync, schema registry omitted topology tables from known set, and sync lacked publication-manifest active upserts; additionally topology rows had to be mapped into governed envelope shape to satisfy data-quality validation.
- **Fix:** Added topology/ontology pipeline flag parsing in config, passed `topology_enabled` through runtime into sync service, derived and emitted governed topology rows (`topology_entities`, `topology_edges`) during sync, upserted active publication-manifest records for topology tables, and registered governed topology schemas in schema registry.
- **Files changed:** src/fabric/config.py, src/fabric/runtime.py, src/fabric/sync_service.py, src/fabric/schema_registry.py, tests/test_fabric_client.py, tests/test_incremental_sync.py, tests/test_topology_pipeline.py
- **Why not caught:** Existing gates only exercised standalone topology pipeline behavior; no integration gate validated topology-flag runtime wiring + known-table classification + manifest disposition under staged rollout conditions.
- **Recurrence guard:** Regression tests now lock the integration contract end-to-end (`tests/test_fabric_client.py::test_fabric_runtime_config_resolves_local_paths`, `tests/test_incremental_sync.py::test_sync_with_topology_flag_publishes_topology_tables`, `tests/test_topology_pipeline.py::test_validator_known_table_set_includes_topology_contract_tables`) plus governed topology schema registration.
---

## foundry-portal-model-support — Foundry portal rejected the prompt-agent model for Azure AI Search
- **Date:** 2026-09-01
- **Error patterns:** model not supported, Foundry portal, gpt-5-mini, Azure AI Search, Knowledge section
- **Root cause(s):** The specialists used `gpt-5-mini`, which Microsoft supports for MCP and Responses but not for the direct Azure AI Search prompt-agent tool; the portal correctly reported the unsupported model/tool combination even though the backend executed it successfully.
- **Fix:** Updated the managed prompt-agent model defaults to supported GA `gpt-5.4-mini` `2026-03-17` and applied the model/agent-only Terraform cutover.
- **Files changed:** infra/terraform/variables.tf, infra/README.md
- **Why not caught:** No gate existed for Foundry portal model/tool compatibility; runtime Search success could not detect a combination that works on the data plane but is explicitly unsupported by the portal contract.
- **Recurrence guard:** The config-default change in `infra/terraform/variables.tf` selects `gpt-5.4-mini` `2026-03-17`, whose current official matrix row supports both Azure AI Search and MCP; this KB pattern records that runtime success is not a substitute for compatibility-matrix validation.
---
