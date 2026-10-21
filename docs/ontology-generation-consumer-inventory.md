# Ontology Generation Consumer Inventory

This inventory is the executable cutover contract for ontology readers. The
matching `CONSUMER_INVENTORY` manifest and repository scanner live in
`src/ontology_discovery/generation_resolver.py`; tests fail when a new direct
read marker appears outside this table.

`ontology-generation-alias/v1` preserves the public
`ontology_entities`/`ontology_relationships` names while binding each operation
to one immutable generation. A resolver disposition means the consumer pins a
`GenerationSelection`; compatibility-alias means an external Fabric surface
keeps the logical names but receives generation metadata; indirect means the
surface reads an already-pinned provider or is a schema/write/evidence seam
that is deliberately tracked to prevent accidental reader drift.

| Consumer ID | Family | File | Call site | Contract owner | Read path | Disposition | Rollback assertion |
|---|---|---|---|---|---|---|---|
| api-runtime-snapshot | api | `src/api/runtime.py` | `_load_snapshot_tables` | API runtime | DatasetStore pointer → GenerationResolver → mapper | resolver | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-inventory-orchestration | api | `src/api/inventory_orchestration.py` | combined generation lookup | API inventory | combined store active pointer | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-context-router | api | `src/api/routers/context.py` | semantic context routes | API context | request semantic provider | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-copilot-router | api | `src/api/routers/copilot.py` | copilot context retrieval | API Copilot | request provider and evidence alias | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-governance-router | api | `src/api/routers/governance.py` | governance projection | API governance | request provider and evidence alias | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-graph-router | api | `src/api/routers/graph.py` | graph traversal | API graph | request semantic provider | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| api-network-router | api | `src/api/routers/network.py` | network projection | API network | request network provider | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-data-agent | fabric | `src/fabric/data_agent_manager.py` | `build_data_agent_definition` | Fabric Data Agent | versioned logical table aliases | compatibility-alias | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-gold-grounding-agent | fabric | `src/fabric/gold_grounding_definition.py` | `build_gold_grounding_definition` | Fabric Gold grounding | delegates ontology selection to the Data Agent definition builder | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-semantic-model | fabric | `src/fabric/semantic_model_manager.py` | `build_semantic_model_definition` | Fabric semantic model | versioned logical table aliases | compatibility-alias | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-dataset-mapper | fabric | `src/fabric/dataset_mapper.py` | `InventoryDatasetMapper.load` | Fabric mapping | resolver-selected generation directory | resolver | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-sync-reader | fabric | `src/fabric/sync_service.py` | `semantic_snapshot` and `ontology_query` | Fabric runtime | compatibility alias over selected generation | compatibility-alias | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-schema-registry | fabric | `src/fabric/schema_registry.py` | ontology table schemas | Fabric schema | logical schema only | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-telemetry | fabric | `src/fabric/telemetry.py` | ontology metrics | Fabric telemetry | post-read aggregate only | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-runtime-config | fabric | `src/fabric/config.py` | `ONTOLOGY_TABLES` | Fabric runtime configuration | logical ontology table declarations consumed by Fabric readers | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-exposure-scalar-migration | fabric | `src/fabric/exposure_scalar_migration.py` | one-table exposure scalar migration | Fabric exposure migration | version-pinned canonical Delta heads; guarded single-table write | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| fabric-exposure-scalar-migration-cli | fabric | `src/fabric/exposure_scalar_migration_cli.py` | read-only authority observer and caller | Fabric exposure migration | read-only observation of pinned Delta heads and source pointer | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| operations-tools | agent | `src/operations/tools.py` | `_semantic_result` and network tools | Operations agent | request provider and evidence alias | indirect | Rollback re-resolves the prior immutable generation without mixed rows. |
| twin-export | export | `src/api/routers/twin.py` | `_composer` and `export` | Operational twin | one request-selected semantic generation | resolver | Rollback re-resolves the prior immutable generation without mixed rows. |
| semantic-registry | semantic | `src/semantic/semantic_registry.py` | `SemanticRegistry.default` | Semantic knowledge layer | versioned logical source aliases | compatibility-alias | Rollback re-resolves the prior immutable generation without mixed rows. |

## Cutover invariant

Every operation resolves once, passes the returned `GenerationSelection` to
all dataset reads, and reports the alias version with generation provenance.
Promotion and rollback only affect the next operation; an in-flight operation
cannot combine rows from two generations. The versioned alias remains in place
until the Plan 13-08 checkpoint decides its retirement policy.

## Inventory publication ownership

The inventory refresh orchestrator pins only the five datasets declared by
`intelligence.inventory.combine.INVENTORY_DATASETS` from its exact combined
inventory generation. DatasetStore manifests also contain carried-forward
datasets; their presence does not transfer ownership to inventory. In
particular, workload checkpoints, observations, deployments, source partitions
and discovery source status must come from the refreshed discovery roots, not
from an older inventory manifest. The entities-aware activation combines those
fresh discovery datasets with the pinned inventory datasets before Fabric replay.
`sourceRunIds` alone is not proof of propagated checkpoint contents; compare the
selected generation's rows and integrity hashes before downstream qualification.
