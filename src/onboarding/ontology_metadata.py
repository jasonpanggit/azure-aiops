"""Ontology metadata generation for API-owned discovery snapshots.

Scope warning: :data:`RELATIONSHIP_TYPES` below is **not** the full ontology
relationship vocabulary. It describes only the three predicates the
API-owned *discovery snapshot* publishes. The authoritative, typed
``(subject_type, predicate, object_type)`` vocabulary the graph actually
writes -- ~70 entries including the whole network topology
(``peersWith``, ``protectedBy``, ``routedBy``, ``hasRule``, ``attachedTo``,
``trafficObserved``, ...) -- lives in
``fabric.dataset_mapper.ONTOLOGY_RELATIONSHIP_TYPES`` and drives the Fabric
relationship tables.

These two lists are intentionally not merged here: ``onboarding`` does not
depend on ``fabric``, and ``test_ontology_pipeline`` pins this snapshot's
vocabulary to exactly these three entries as a Fabric-parity contract.
Treat this as a *snapshot-scoped subset*, not as the ontology schema; do not
infer from it that the graph only models three relationship types.
"""

from __future__ import annotations

from typing import Any

RELATIONSHIP_TYPES = {
    "belongsTo": {
        "description": "Administrative containment",
        "properties": ["confidence", "source", "createdTimestamp", "lastObservedTimestamp", "assertionState"],
    },
    "assessedBy": {
        "description": "Resource has a patch assessment",
        "properties": ["confidence", "source", "createdTimestamp", "lastObservedTimestamp", "assertionState"],
    },
    "impacts": {
        "description": "Recommendation or finding impacts a resource",
        "properties": ["confidence", "source", "createdTimestamp", "lastObservedTimestamp", "assertionState"],
    },
}


def generate_ontology_metadata(entities: dict[str, list[dict]]) -> dict[str, Any]:
    """Generate the additive ontology schema for normalized entities."""
    entity_types: dict[str, dict[str, Any]] = {}
    for entity_type, rows in sorted(entities.items()):
        properties: dict[str, str] = {"id": "string"}
        for row in rows:
            for key, value in row.items():
                properties[key] = _type_name(value)
        entity_types[entity_type] = {
            "key": "id",
            "dataset": f"entities/{entity_type}",
            "properties": dict(sorted(properties.items())),
        }
    return {
        "name": "AIOpsAzureOperationalContext",
        "schemaVersion": "1.0.0",
        "entityTypes": entity_types,
        "relationshipTypes": RELATIONSHIP_TYPES,
        "expansion": {
            "strategy": "additive entity types and source assertions",
            "sourceOfTruth": "Azure Resource Graph and Azure operational services",
            "contextSystem": "Microsoft Fabric Ontology",
        },
    }


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "double"
    if isinstance(value, (dict, list)):
        return "string(json)"
    return "string"
