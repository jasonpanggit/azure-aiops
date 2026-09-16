"""Fabric-native operational-context-graph derivation pipeline.

Reproduces ``ontology.entity_builder.EntityBuilder`` and
``ontology.relationship_builder.RelationshipBuilder``'s full deterministic
entity/relationship inference (Application, BusinessService, VirtualMachine,
PatchAssessment, AdvisorRecommendation, ... plus belongsTo/assessedBy/
impacts/dependsOn, ...) for the API-triggered Fabric sync path, covering the
full AIOps ontology scope rather than only network topology.

This module owns *only* orchestration/Delta-publication glue: it never
re-implements ``EntityBuilder``/``RelationshipBuilder``/
``generate_ontology_metadata``'s classification or inference logic a second
time (Don't Hand-Roll / Anti-Pattern guard) -- it calls the exact same
classes/functions this repo's local pipeline and test suite already exercise,
so the API sync and local/CI-tested pipeline are provably the same
logic, run through the same deterministic code path (same guarantee
``topology_pipeline.py`` gives for topology).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from onboarding.ontology_metadata import generate_ontology_metadata
from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.onelake_writer import OneLakeWriter

from .ontology_fabric_contracts import (
    ONTOLOGY_ENTITIES_CONTRACT,
    ONTOLOGY_RELATIONSHIPS_CONTRACT,
    OntologyFabricContract,
)

#: Source tag recorded in this pipeline's Fabric run summary -- distinct from
#: AIOps's own ingestion path so provenance is unambiguous about which arm
#: produced a given ontology snapshot (mirrors topology_pipeline.SOURCE_TAG).
SOURCE_TAG = "fabric_pipeline:ontology"


def derive_entities(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    timestamp: str = "",
) -> list[dict[str, Any]]:
    """Ports ``EntityBuilder.build`` faithfully: same entity type names
    (Application, BusinessService, VirtualMachine, PatchAssessment,
    AdvisorRecommendation, Tenant, Subscription, ResourceGroup, ...), same
    tag-key normalization, same content-addressed ``resource_id``/
    ``change_version`` scheme. ``source_rows`` carries the same logical
    shape ``EntityBuilder.build`` already consumes: inventory-shaped rows
    with ``resource_id``/``payload_json`` (or raw ``tags``/``resourceType``
    fields), each row already inventory-owned identity data per the
    read-port adapter proven in Phase 8 (Anti-Pattern guard: this pipeline
    never re-derives identity fields inventory already owns)."""
    builder = EntityBuilder()
    return builder.build(source_rows, run_id, timestamp=timestamp)


def derive_relationships(
    entities: Iterable[Mapping[str, Any]], run_id: str
) -> list[dict[str, Any]]:
    """Ports ``RelationshipBuilder.build`` faithfully: same predicate
    vocabulary (belongsTo/owns/contains/member_of/hosted_on/deployed_in/
    supports/implements/depends_on/affects/incurs_cost/evaluates/
    records_installation_for, plus the full re-derived network-topology
    edge set), same content-addressed ``relationship_id`` scheme."""
    return RelationshipBuilder().build(entities, run_id)


def derive_ontology_metadata(entities: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Ports ``onboarding.ontology_metadata.generate_ontology_metadata``
    faithfully: groups already-derived entities by ``entity_type`` and infers
    the Fabric IQ-consumable ontology schema document (entity/relationship
    type property maps) from their observed fields."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in entities:
        by_type.setdefault(str(row["entity_type"]), []).append(dict(row))
    return generate_ontology_metadata(by_type)


@dataclass(frozen=True)
class OntologyTableWrite:
    table_name: str
    table_uri: str
    result: DeltaWriteResult


@dataclass
class OntologyOneLakePublisher:
    """Writes derived ontology rows to governed OneLake Delta tables.

    Deliberately reuses the exact ``DeltaWriter``/``OneLakeWriter`` machinery
    ``TopologyOneLakePublisher`` uses (Don't Hand-Roll) -- this pipeline adds
    no new writer, only new contracts/rows for the existing writer to
    persist.
    """

    onelake: OneLakeWriter
    delta_writer: DeltaWriter = field(default_factory=DeltaWriter)

    def publish_entities(self, rows: list[dict]) -> OntologyTableWrite:
        return self._publish(ONTOLOGY_ENTITIES_CONTRACT, rows)

    def publish_relationships(self, rows: list[dict]) -> OntologyTableWrite:
        return self._publish(ONTOLOGY_RELATIONSHIPS_CONTRACT, rows)

    def _publish(
        self, contract: OntologyFabricContract, rows: list[dict]
    ) -> OntologyTableWrite:
        table_uri = self.onelake.table_uri(
            "ontology", contract.table_name.removeprefix("ontology_")
        )
        result = self.delta_writer.write(
            table_uri,
            rows,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=contract.identity_fields,
            schema=contract.schema,
            required_columns=contract.required_fields,
        )
        return OntologyTableWrite(
            table_name=contract.table_name,
            table_uri=table_uri,
            result=result,
        )


@dataclass(frozen=True)
class OntologyPipelineSummary:
    entity_count: int
    relationship_count: int
    entities_write: OntologyTableWrite
    relationships_write: OntologyTableWrite
    ontology_metadata: dict[str, Any]


def run(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    onelake: OneLakeWriter,
    timestamp: str = "",
    delta_writer: DeltaWriter | None = None,
) -> OntologyPipelineSummary:
    """Notebook entrypoint: derives entities/relationships/ontology metadata
    from ``source_rows`` and writes the entity/relationship tables to the
    lakehouse via the shared Delta writer path, mirroring
    ``topology_pipeline``'s run contract (read -> pure-Python derive -> write
    via Delta).

    Data Agent output is intentionally absent from this authoritative writer.
    Advisory proposals and append-only review decisions flow through the
    Phase 13 durable hard-shadow lifecycle instead."""
    entities = derive_entities(source_rows, run_id=run_id, timestamp=timestamp)
    relationships = derive_relationships(entities, run_id)
    metadata = derive_ontology_metadata(entities)

    publisher = OntologyOneLakePublisher(
        onelake=onelake, delta_writer=delta_writer or DeltaWriter()
    )
    entities_write = publisher.publish_entities(entities)
    relationships_write = publisher.publish_relationships(relationships)

    return OntologyPipelineSummary(
        entity_count=len(entities),
        relationship_count=len(relationships),
        entities_write=entities_write,
        relationships_write=relationships_write,
        ontology_metadata=metadata,
    )


__all__ = [
    "SOURCE_TAG",
    "OntologyOneLakePublisher",
    "OntologyPipelineSummary",
    "OntologyTableWrite",
    "derive_entities",
    "derive_ontology_metadata",
    "derive_relationships",
    "run",
]
