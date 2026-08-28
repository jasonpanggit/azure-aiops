"""Ontology metadata generation for API-owned discovery snapshots."""

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
        "name": "HermesAzureOperationalContext",
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
