"""D-04a-style comparison harness for the full AIOps operational-context
graph (not just network topology): runs the identical shared fixture
(``tests/ontology_comparison_scenario.py``) through both arms --

- **AIOps** -- the real ``ontology.entity_builder.EntityBuilder`` /
  ``ontology.relationship_builder.RelationshipBuilder`` /
  ``onboarding.ontology_metadata.generate_ontology_metadata`` (the engine
  AIOps itself runs in production).
- **Fabric-native** -- ``fabric_pipelines.ontology_pipeline``'s
  ``derive_entities``/``derive_relationships``/``derive_ontology_metadata``.

and asserts *actual graph equivalence*, not just "both produce an
Application entity type": the same set of entity ids (by ``resource_id``),
the same set of relationships (by ``(subject_id, predicate, object_id)``
triple), and the same ontology metadata schema document. Mirrors
``tests/test_aiops_fabric_comparison.py``'s comparison-harness style
(D-04/D-04a), scoped to the full entity/relationship graph instead of a
bounded network-topology BFS blast radius (which has no single meaningful
"root" for a heterogeneous ontology graph -- so this harness compares the
*entire* derived graph produced from the shared fixture, rather than a
BFS-reachable subset from one root).

Note: because ``ontology_pipeline.derive_entities``/``derive_relationships``/
``derive_ontology_metadata`` are direct pass-through calls into
``EntityBuilder``/``RelationshipBuilder``/``generate_ontology_metadata`` (no
re-implementation -- see ``ontology_pipeline.py``'s module docstring), the
two arms are, by construction, the same code path. This harness still
performs the full independent-arm comparison (as if they were two different
implementations) so the equivalence is demonstrated by evidence, not merely
asserted by code-reading -- and so it would immediately catch any future
regression where one arm's call is changed to no longer match the other's
input/output contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ontology_comparison_scenario import TIMESTAMP, ontology_comparison_scenario

from fabric_pipelines.ontology_pipeline import (
    derive_entities,
    derive_ontology_metadata,
    derive_relationships,
)
from onboarding.ontology_metadata import generate_ontology_metadata
from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder

RUN_ID = "ontology-comparison-harness"


@dataclass(frozen=True)
class OntologyGraphResult:
    """Arm-agnostic projection of one arm's derived operational context
    graph: entity ids/types, relationship subject/predicate/object triples,
    and the ontology metadata document -- the actual comparable surface for
    "did both arms build the same graph"."""

    arm_name: str
    entity_ids: set[str]
    entity_id_to_type: dict[str, str]
    relationship_triples: set[tuple[str, str, str]]
    metadata: dict
    raw_entities: list[dict] = field(default_factory=list)
    raw_relationships: list[dict] = field(default_factory=list)


def _aiops_arm() -> OntologyGraphResult:
    rows = ontology_comparison_scenario()
    entities = EntityBuilder().build(rows, RUN_ID, timestamp=TIMESTAMP)
    relationships = RelationshipBuilder().build(entities, RUN_ID)
    by_type: dict[str, list[dict]] = {}
    for row in entities:
        by_type.setdefault(str(row["entity_type"]), []).append(row)
    metadata = generate_ontology_metadata(by_type)
    return OntologyGraphResult(
        arm_name="semantic",
        entity_ids={str(e["resource_id"]) for e in entities},
        entity_id_to_type={str(e["resource_id"]): str(e["entity_type"]) for e in entities},
        relationship_triples={
            (str(r["subject_id"]), str(r["predicate"]), str(r["object_id"])) for r in relationships
        },
        metadata=metadata,
        raw_entities=entities,
        raw_relationships=relationships,
    )


def _fabric_arm() -> OntologyGraphResult:
    rows = ontology_comparison_scenario()
    entities = derive_entities(rows, run_id=RUN_ID, timestamp=TIMESTAMP)
    relationships = derive_relationships(entities, RUN_ID)
    metadata = derive_ontology_metadata(entities)
    return OntologyGraphResult(
        arm_name="fabric",
        entity_ids={str(e["resource_id"]) for e in entities},
        entity_id_to_type={str(e["resource_id"]): str(e["entity_type"]) for e in entities},
        relationship_triples={
            (str(r["subject_id"]), str(r["predicate"]), str(r["object_id"])) for r in relationships
        },
        metadata=metadata,
        raw_entities=entities,
        raw_relationships=relationships,
    )


def test_both_arms_derive_the_same_entity_id_set_from_the_shared_fixture():
    """Same entity ids (not just same entity *types*): every id emitted by
    one arm is emitted by the other, for the identical shared fixture."""
    semantic = _aiops_arm()
    fabric = _fabric_arm()

    assert semantic.entity_ids == fabric.entity_ids, (
        f"entity id sets diverge: semantic_only={semantic.entity_ids - fabric.entity_ids} "
        f"fabric_only={fabric.entity_ids - semantic.entity_ids}"
    )
    assert len(semantic.entity_ids) > 30  # sanity: fixture is the comprehensive one, not the minimal 3-row one


def test_both_arms_classify_every_shared_entity_id_identically():
    """For every entity id both arms emit, the entity_type assigned must
    match -- proves not just "same ids" but "same classification per id"."""
    semantic = _aiops_arm()
    fabric = _fabric_arm()

    assert semantic.entity_id_to_type == fabric.entity_id_to_type


def test_both_arms_derive_the_same_relationship_triple_set():
    """Same relationships, identified by (subject_id, predicate, object_id)
    -- not just "same predicate vocabulary" but the same actual edges
    connecting the same actual entities."""
    semantic = _aiops_arm()
    fabric = _fabric_arm()

    assert semantic.relationship_triples == fabric.relationship_triples, (
        f"relationship triples diverge: semantic_only={semantic.relationship_triples - fabric.relationship_triples} "
        f"fabric_only={fabric.relationship_triples - semantic.relationship_triples}"
    )
    assert len(semantic.relationship_triples) > 30


def test_both_arms_produce_the_same_ontology_metadata_schema():
    """Same Fabric IQ-consumable ontology schema document -- entity/
    relationship type property maps derived from the same underlying rows."""
    semantic = _aiops_arm()
    fabric = _fabric_arm()

    assert semantic.metadata == fabric.metadata
    assert semantic.metadata["entityTypes"].keys() == fabric.metadata["entityTypes"].keys()
    assert semantic.metadata["relationshipTypes"] == fabric.metadata["relationshipTypes"]


def test_ontology_parity_report_shows_zero_diff():
    """Produces and asserts a zero-diff parity report -- entity count match,
    relationship count match, empty semantic-only/fabric-only sets -- the
    explicit pass/fail parity proof (mirrors 08-COMPARISON-REPORT.md's
    format for the full entity/relationship graph, not just topology)."""
    semantic = _aiops_arm()
    fabric = _fabric_arm()

    entity_ids_match = semantic.entity_ids == fabric.entity_ids
    relationship_triples_match = semantic.relationship_triples == fabric.relationship_triples
    metadata_match = semantic.metadata == fabric.metadata

    report = {
        "entity_count": {"semantic": len(semantic.entity_ids), "fabric": len(fabric.entity_ids)},
        "relationship_count": {
            "semantic": len(semantic.relationship_triples),
            "fabric": len(fabric.relationship_triples),
        },
        "entity_ids_match": entity_ids_match,
        "relationship_triples_match": relationship_triples_match,
        "metadata_match": metadata_match,
        "semantic_only_entities": sorted(semantic.entity_ids - fabric.entity_ids),
        "fabric_only_entities": sorted(fabric.entity_ids - semantic.entity_ids),
        "semantic_only_relationships": sorted(semantic.relationship_triples - fabric.relationship_triples),
        "fabric_only_relationships": sorted(fabric.relationship_triples - semantic.relationship_triples),
    }

    assert report["entity_count"]["semantic"] == report["entity_count"]["fabric"]
    assert report["relationship_count"]["semantic"] == report["relationship_count"]["fabric"]
    assert report["entity_ids_match"] is True
    assert report["relationship_triples_match"] is True
    assert report["metadata_match"] is True
    assert report["semantic_only_entities"] == []
    assert report["fabric_only_entities"] == []
    assert report["semantic_only_relationships"] == []
    assert report["fabric_only_relationships"] == []
