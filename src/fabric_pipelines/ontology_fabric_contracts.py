"""Fabric/OneLake table contracts for the Fabric-native ontology pipeline.

Mirrors ``fabric_pipelines.topology_fabric_contracts``: generic Fabric
publication code can look up schemas here, but this module stays
ontology-pipeline-owned so it doesn't leak entity/relationship knowledge
into shared Fabric plumbing (Don't Hand-Roll — reuse the same contract
shape as the existing topology contracts instead of inventing a new one).
"""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa


@dataclass(frozen=True)
class OntologyFabricContract:
    logical_name: str
    table_name: str
    schema: pa.Schema
    required_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]


#: Mirrors ``EntityBuilder._entity``'s emitted row exactly (field-for-field)
#: so entity provenance/lineage survive unchanged into the Delta table
#: (Anti-Pattern guard — this pipeline never re-derives entity_builder's
#: identity/versioning logic, only writes its output).
_ONTOLOGY_ENTITY_SCHEMA = pa.schema(
    [
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("timestamp", pa.string(), nullable=False),
        pa.field("change_version", pa.string(), nullable=False),
        pa.field("ingestion_run_id", pa.string(), nullable=False),
        pa.field("entity_type", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("resource_type", pa.string(), nullable=False),
        pa.field("location", pa.string(), nullable=False),
        pa.field("payload_json", pa.string(), nullable=False),
        pa.field("lineage_json", pa.string(), nullable=False),
        pa.field("semantic_metadata_json", pa.string(), nullable=False),
        pa.field("lifecycle_status", pa.string(), nullable=False),
        pa.field("valid_from", pa.string(), nullable=False),
        pa.field("retired_at", pa.string(), nullable=False),
        pa.field("ontology_version", pa.string(), nullable=False),
    ]
)

#: Mirrors ``RelationshipBuilder.build``'s ``connect()``-emitted row exactly
#: (field-for-field) so confidence/source/lifecycle survive unchanged
#: through ontology binding (Security Domain requirement, T-08-06 analog).
_ONTOLOGY_RELATIONSHIP_SCHEMA = pa.schema(
    [
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("timestamp", pa.string(), nullable=False),
        pa.field("change_version", pa.string(), nullable=False),
        pa.field("ingestion_run_id", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("subject_type", pa.string(), nullable=False),
        pa.field("predicate", pa.string(), nullable=False),
        pa.field("object_id", pa.string(), nullable=False),
        pa.field("object_type", pa.string(), nullable=False),
        pa.field("confidence", pa.float64(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("payload_json", pa.string(), nullable=False),
        pa.field("lineage_json", pa.string(), nullable=False),
        pa.field("lifecycle_status", pa.string(), nullable=False),
        pa.field("valid_from", pa.string(), nullable=False),
        pa.field("retired_at", pa.string(), nullable=False),
        pa.field("ontology_version", pa.string(), nullable=False),
    ]
)

ONTOLOGY_ENTITIES_CONTRACT = OntologyFabricContract(
    logical_name="ontology/entities",
    table_name="ontology_entities",
    schema=_ONTOLOGY_ENTITY_SCHEMA,
    required_fields=(
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "entity_type",
        "name",
    ),
    identity_fields=("resource_id",),
)

ONTOLOGY_RELATIONSHIPS_CONTRACT = OntologyFabricContract(
    logical_name="ontology/relationships",
    table_name="ontology_relationships",
    schema=_ONTOLOGY_RELATIONSHIP_SCHEMA,
    required_fields=(
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "subject_id",
        "predicate",
        "object_id",
    ),
    identity_fields=("resource_id",),
)

ONTOLOGY_FABRIC_CONTRACTS: dict[str, OntologyFabricContract] = {
    ONTOLOGY_ENTITIES_CONTRACT.logical_name: ONTOLOGY_ENTITIES_CONTRACT,
    ONTOLOGY_RELATIONSHIPS_CONTRACT.logical_name: ONTOLOGY_RELATIONSHIPS_CONTRACT,
}

__all__ = [
    "ONTOLOGY_ENTITIES_CONTRACT",
    "ONTOLOGY_FABRIC_CONTRACTS",
    "ONTOLOGY_RELATIONSHIPS_CONTRACT",
    "OntologyFabricContract",
]
