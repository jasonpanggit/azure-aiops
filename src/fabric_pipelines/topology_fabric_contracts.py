"""Fabric/OneLake table contracts for the topology comparison-arm pipeline.

Mirrors ``intelligence.inventory.fabric_contracts.InventoryFabricContract``:
generic Fabric publication code can look up schemas here, but this module
stays topology-pipeline-owned so it doesn't leak lifecycle knowledge into
shared Fabric plumbing (Don't Hand-Roll — reuse the same contract shape as
the existing inventory contracts instead of inventing a new one).
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa


@dataclass(frozen=True)
class TopologyFabricContract:
    logical_name: str
    table_name: str
    schema: pa.Schema
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]


#: Mirrors the entity envelope fields emitted by ``normalize._base`` plus the
#: minimal typed fields the topology pipeline itself adds. Kept intentionally
#: narrow: this pipeline joins to inventory by ``resource_id`` and does not
#: re-derive or duplicate typed inventory fields (Anti-Pattern guard).
_TOPOLOGY_ENTITY_SCHEMA = pa.schema(
    [
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("entity_type", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("display_name", pa.string(), nullable=False),
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("source_system", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("created_timestamp", pa.string(), nullable=False),
        pa.field("last_observed_timestamp", pa.string(), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("attributes_json", pa.string(), nullable=False),
    ]
)

#: Mirrors ``_add_edge``'s emitted relationship row exactly (field-for-field,
#: same names transposed to snake_case for the Delta table) so
#: confidence/source/assertionState survive unchanged through ontology
#: binding (Security Domain requirement, T-08-06).
_TOPOLOGY_EDGE_SCHEMA = pa.schema(
    [
        pa.field("relationship_id", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("predicate", pa.string(), nullable=False),
        pa.field("object_id", pa.string(), nullable=False),
        pa.field("confidence", pa.float64(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("created_timestamp", pa.string(), nullable=False),
        pa.field("last_observed_timestamp", pa.string(), nullable=False),
        pa.field("assertion_state", pa.string(), nullable=False),
        pa.field("schema_version", pa.string(), nullable=False),
    ]
)

TOPOLOGY_ENTITIES_CONTRACT = TopologyFabricContract(
    logical_name="topology/entities",
    table_name="topology_entities",
    schema=_TOPOLOGY_ENTITY_SCHEMA,
    required_fields=(
        "entity_id",
        "entity_type",
        "name",
        "source_system",
        "created_timestamp",
        "last_observed_timestamp",
        "schema_version",
    ),
    identity_fields=("entity_id",),
)

TOPOLOGY_EDGES_CONTRACT = TopologyFabricContract(
    logical_name="topology/edges",
    table_name="topology_edges",
    schema=_TOPOLOGY_EDGE_SCHEMA,
    required_fields=(
        "relationship_id",
        "subject_id",
        "predicate",
        "object_id",
        "confidence",
        "source",
        "assertion_state",
        "schema_version",
    ),
    identity_fields=("relationship_id",),
)

TOPOLOGY_FABRIC_CONTRACTS: dict[str, TopologyFabricContract] = {
    TOPOLOGY_ENTITIES_CONTRACT.logical_name: TOPOLOGY_ENTITIES_CONTRACT,
    TOPOLOGY_EDGES_CONTRACT.logical_name: TOPOLOGY_EDGES_CONTRACT,
}

__all__ = [
    "TOPOLOGY_EDGES_CONTRACT",
    "TOPOLOGY_ENTITIES_CONTRACT",
    "TOPOLOGY_FABRIC_CONTRACTS",
    "TopologyFabricContract",
]
