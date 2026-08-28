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
from .relationship_suggestions_contract import (
    ACCEPTED_SUGGESTION_STATUS,
    accepted_suggestion_to_relationship_row,
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
class RelationshipMergeResult:
    """Outcome of unioning approved-suggestion relationship rows into the
    deterministic ``RelationshipBuilder`` output.

    ``conflicts`` records every case where an approved suggestion's content-
    addressed ``resource_id`` (relationship id) collided with a
    deterministically-derived relationship for the *same*
    subject/predicate/object -- per the user's explicit requirement,
    deterministic always wins in that case; the approved-suggestion version
    is dropped from ``merged`` but the collision is still reported here so
    it's visible (e.g. logged or surfaced in the sync result)
    rather than silently discarded."""

    merged: list[dict[str, Any]]
    approved_count: int
    conflict_count: int
    conflicts: list[dict[str, Any]]


def merge_approved_relationship_suggestions(
    deterministic_relationships: list[dict[str, Any]],
    approved_suggestion_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
) -> RelationshipMergeResult:
    """Feedback-loop step: folds already-**accepted**
    ``relationship_suggestions`` rows into the deterministic relationships
    output, tagged with ``source="data_agent_suggested_approved"``
    (``relationship_suggestions_contract.APPROVED_SUGGESTION_RELATIONSHIP_SOURCE``)
    so provenance is never ambiguous.

    This keeps the pipeline fully deterministic/idempotent: given the same
    deterministic entities/relationships and the same set of accepted
    suggestion rows, this always produces the same merged output (content-
    addressed ``relationship_id``s, no randomness, no mutation of either
    input). Re-running the sync after a suggestion is accepted simply
    adds that edge to the graph going forward; re-running it again is a
    no-op (same accepted row -> same relationship row every time).

    Conflict rule (explicit, non-negotiable per the user's design):
    deterministic relationships always win. If an approved suggestion's
    ``(subject_id, predicate, object_id)`` collides with a relationship
    ``RelationshipBuilder`` already derived (same content-addressed
    ``relationship_id``), the deterministic row is kept unchanged and the
    approved-suggestion row is *not* added a second time -- but the
    collision is recorded in the returned ``conflicts`` list so it's never
    silently dropped."""
    caller_expects_only_accepted = [
        row for row in approved_suggestion_rows if str(row.get("status") or "") == ACCEPTED_SUGGESTION_STATUS
    ]

    by_relationship_id = {
        str(row["resource_id"]): row for row in deterministic_relationships
    }
    merged = list(deterministic_relationships)
    conflicts: list[dict[str, Any]] = []

    for suggestion_row in caller_expects_only_accepted:
        promoted = accepted_suggestion_to_relationship_row(
            dict(suggestion_row), run_id=run_id
        )
        relationship_id = str(promoted["resource_id"])
        existing = by_relationship_id.get(relationship_id)
        if existing is not None:
            conflicts.append(
                {
                    "relationship_id": relationship_id,
                    "subject_id": promoted["subject_id"],
                    "predicate": promoted["predicate"],
                    "object_id": promoted["object_id"],
                    "deterministic_source": existing.get("source"),
                    "suggestion_id": suggestion_row.get("suggestion_id"),
                    "resolution": "deterministic_kept",
                }
            )
            continue
        merged.append(promoted)
        by_relationship_id[relationship_id] = promoted

    return RelationshipMergeResult(
        merged=merged,
        approved_count=len(caller_expects_only_accepted),
        conflict_count=len(conflicts),
        conflicts=conflicts,
    )


@dataclass(frozen=True)
class OntologyPipelineSummary:
    entity_count: int
    relationship_count: int
    entities_write: OntologyTableWrite
    relationships_write: OntologyTableWrite
    ontology_metadata: dict[str, Any]
    approved_suggestions_merged: int = 0
    approved_suggestions_conflicts: list[dict[str, Any]] = field(default_factory=list)


def run(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    onelake: OneLakeWriter,
    timestamp: str = "",
    delta_writer: DeltaWriter | None = None,
    approved_suggestion_rows: Iterable[Mapping[str, Any]] = (),
) -> OntologyPipelineSummary:
    """Notebook entrypoint: derives entities/relationships/ontology metadata
    from ``source_rows`` and writes the entity/relationship tables to the
    lakehouse via the shared Delta writer path, mirroring
    ``topology_pipeline``'s run contract (read -> pure-Python derive -> write
    via Delta).

    ``approved_suggestion_rows`` closes the Data Agent feedback loop
    (see ``docs/fabric-data-agent-relationship-suggestions.md``): pass in
    the ``relationship_suggestions`` table's rows (typically read via
    ``spark.read.table(...).collect()`` and converted to dicts in the
    sync input) and any row already marked
    ``status="accepted"`` by a human reviewer is folded into this run's
    relationships output, tagged with a distinct ``source`` so it's never
    confused with a deterministically-derived edge. Deterministic
    relationships always win on conflict (see
    ``merge_approved_relationship_suggestions``). Passing nothing (the
    default) reproduces the exact deterministic-only behavior this pipeline
    had before the feedback loop existed -- this parameter is purely
    additive."""
    entities = derive_entities(source_rows, run_id=run_id, timestamp=timestamp)
    relationships = derive_relationships(entities, run_id)
    metadata = derive_ontology_metadata(entities)

    merge_result = merge_approved_relationship_suggestions(
        relationships, approved_suggestion_rows, run_id=run_id
    )
    relationships = merge_result.merged

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
        approved_suggestions_merged=merge_result.approved_count - merge_result.conflict_count,
        approved_suggestions_conflicts=merge_result.conflicts,
    )


__all__ = [
    "SOURCE_TAG",
    "OntologyOneLakePublisher",
    "OntologyPipelineSummary",
    "OntologyTableWrite",
    "RelationshipMergeResult",
    "derive_entities",
    "derive_ontology_metadata",
    "derive_relationships",
    "merge_approved_relationship_suggestions",
    "run",
]
