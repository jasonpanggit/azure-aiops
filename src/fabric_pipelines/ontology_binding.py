"""Binds materialized ``topology_entities``/``topology_edges`` Delta tables
into Fabric IQ ontology (D-04a comparison arm, traversal-decision: fabric-
iq-native).

**Traversal mechanism decision (checkpoint, resolved):** blast-radius
queries against this bound topology run through **Fabric IQ's own query/
traversal surface** -- no KQL/Eventhouse `make-graph` construct, no Gremlin/
Cosmos DB graph, and no new `azure-kusto-data` dependency. This module's
ontology-registration step is therefore both the binding step and the
traversal surface; there is nothing else to stand up.

Reuses the existing ``ontology.OntologyManager`` (thin Fabric Ontology REST
wrapper, `src/ontology/ontology_manager.py`) rather than inventing a second
Fabric-item client. Does **not** reuse ``ontology.OntologyPublisher``'s
``build_definition`` directly: that publisher hardcodes an inventory-shaped
entity schema (`resource_id`-keyed `ENTITY_COLUMNS`), whereas topology
entities are keyed by `entity_id` and carry a different column set -- so
this module defines its own topology-shaped ontology definition using the
same Fabric Ontology item wire-format (parts/EntityTypes/RelationshipTypes)
`ontology_publisher.py` already establishes as correct (`_part`, numeric-ID
derivation, source-table binding all ported verbatim; see Don't Hand-Roll).

Runs strictly after both Delta tables are populated (Pitfall 2, D-10): this
step only *registers* already-derived entities/relationships as typed
ontology objects, it never asks Fabric IQ to detect or infer them.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

#: Topology entity property columns, mirrored from
#: ``topology_fabric_contracts.TOPOLOGY_ENTITIES_CONTRACT`` -- kept in sync
#: manually since Fabric Ontology's property-binding format needs an
#: explicit (name, valueType) pair per column, not just the pyarrow schema.
TOPOLOGY_ENTITY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("entity_id", "String"),
    ("entity_type", "String"),
    ("name", "String"),
    ("display_name", "String"),
    ("tenant_id", "String"),
    ("subscription_id", "String"),
    ("source_system", "String"),
    ("created_timestamp", "String"),
    ("last_observed_timestamp", "String"),
    ("schema_version", "String"),
)


class TopologyOntologyBinder:
    """Publishes a Fabric-native Ontology definition bound to the topology
    Lakehouse Delta tables, using Fabric IQ's own traversal surface."""

    def __init__(
        self,
        manager: Any,
        *,
        workspace_id: str,
        lakehouse_id: str,
        source_schema: str = "",
    ) -> None:
        self.manager = manager
        self.workspace_id = workspace_id
        self.lakehouse_id = lakehouse_id
        self.source_schema = source_schema

    def bind(
        self,
        *,
        ontology_id: str,
        ontology_name: str,
        entity_types: dict[str, str],
        relationships: dict[tuple[str, str, str], str],
    ) -> dict[str, Any]:
        """``entity_types`` maps ontology entity-type name -> Delta table
        name (e.g. ``{"VNet": "topology_entities"}`` filtered by
        ``entity_type`` at query time, or one table per type if the
        pipeline later splits them). ``relationships`` maps
        ``(source_type, predicate, target_type) -> table name`` (typically
        ``topology_edges`` for all predicates, filtered by ``predicate``).
        """
        definition = self.build_definition(entity_types, relationships, ontology_name)
        item = self.manager.resolve(ontology_id=ontology_id, ontology_name=ontology_name)
        if item:
            current = self.manager.get_definition(str(item["id"]))
            if _definitions_equal(current, definition):
                return {**item, "action": "unchanged"}
            self.manager.update_definition(str(item["id"]), definition)
            return {**item, "action": "updated"}
        created = self.manager.create(ontology_name, definition)
        return {**created, "action": "created"}

    def build_definition(
        self,
        entity_types: dict[str, str],
        relationships: dict[tuple[str, str, str], str],
        ontology_name: str,
    ) -> dict[str, Any]:
        if not entity_types:
            raise ValueError("Topology ontology binding requires at least one entity type")
        parts = [
            _part("definition.json", {}),
            _part(".platform", {"metadata": {"type": "Ontology", "displayName": ontology_name}}),
        ]
        entity_ids = {name: _numeric_id(f"topology-entity:{name}") for name in entity_types}
        property_ids = {
            (name, column): _numeric_id(f"topology-property:{name}:{column}")
            for name in entity_types
            for column, _ in TOPOLOGY_ENTITY_COLUMNS
        }
        for entity_name, table_name in sorted(entity_types.items()):
            entity_id = entity_ids[entity_name]
            properties = [
                {
                    "id": property_ids[(entity_name, column)],
                    "name": column,
                    "redefines": None,
                    "baseTypeNamespaceType": None,
                    "valueType": value_type,
                }
                for column, value_type in TOPOLOGY_ENTITY_COLUMNS
            ]
            parts.append(
                _part(
                    f"EntityTypes/{entity_id}/definition.json",
                    {
                        "id": entity_id,
                        "namespace": "usertypes",
                        "baseEntityTypeId": None,
                        "name": entity_name,
                        "entityIdParts": [property_ids[(entity_name, "entity_id")]],
                        "displayNamePropertyId": property_ids[(entity_name, "display_name")],
                        "namespaceType": "Custom",
                        "visibility": "Visible",
                        "properties": properties,
                        "timeseriesProperties": [],
                    },
                )
            )
            binding_id = _uuid5(f"topology:{entity_name}:{table_name}")
            parts.append(
                _part(
                    f"EntityTypes/{entity_id}/DataBindings/{binding_id}.json",
                    {
                        "id": binding_id,
                        "dataBindingConfiguration": {
                            "dataBindingType": "NonTimeSeries",
                            "propertyBindings": [
                                {
                                    "sourceColumnName": column,
                                    "targetPropertyId": property_ids[(entity_name, column)],
                                }
                                for column, _ in TOPOLOGY_ENTITY_COLUMNS
                            ],
                            "sourceTableProperties": self._source_table(table_name),
                        },
                    },
                )
            )

        for (source_type, predicate, target_type), table_name in sorted(relationships.items()):
            relationship_id = _numeric_id(
                f"topology-relationship:{source_type}:{predicate}:{target_type}"
            )
            parts.append(
                _part(
                    f"RelationshipTypes/{relationship_id}/definition.json",
                    {
                        "namespace": "usertypes",
                        "id": relationship_id,
                        "name": f"{predicate}_{source_type}_{target_type}",
                        "namespaceType": "Custom",
                        "source": {"entityTypeId": entity_ids[source_type]},
                        "target": {"entityTypeId": entity_ids[target_type]},
                    },
                )
            )
            contextualization_id = _uuid5(
                f"topology:{source_type}:{predicate}:{target_type}:{table_name}"
            )
            parts.append(
                _part(
                    f"RelationshipTypes/{relationship_id}/Contextualizations/{contextualization_id}.json",
                    {
                        "id": contextualization_id,
                        "dataBindingTable": self._relationship_table(table_name, predicate),
                        "sourceKeyRefBindings": [
                            {
                                "sourceColumnName": "subject_id",
                                "targetPropertyId": property_ids[(source_type, "entity_id")],
                            }
                        ],
                        "targetKeyRefBindings": [
                            {
                                "sourceColumnName": "object_id",
                                "targetPropertyId": property_ids[(target_type, "entity_id")],
                            }
                        ],
                    },
                )
            )
        return {"parts": parts}

    def _source_table(self, table_name: str) -> dict[str, str]:
        source = {
            "sourceType": "LakehouseTable",
            "workspaceId": self.workspace_id,
            "itemId": self.lakehouse_id,
            "sourceTableName": table_name,
        }
        if self.source_schema:
            source["sourceSchema"] = self.source_schema
        return source

    def _relationship_table(self, table_name: str, predicate: str) -> dict[str, Any]:
        source = self._source_table(table_name)
        source["predicateFilter"] = predicate
        return source


def _uuid5(value: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


def _numeric_id(value: str) -> str:
    number = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big") & ((1 << 63) - 1)
    return str(number or 1)


def _part(path: str, payload: dict[str, Any]) -> dict[str, str]:
    # Same base64-part encoding convention as ontology_publisher.py -- do not
    # sort_keys, for the same "sourceType must be first" import-order
    # requirement documented there.
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return {"path": path, "payload": encoded, "payloadType": "InlineBase64"}


def _definitions_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    def parts(value: dict[str, Any]) -> list[tuple[str, str, str]]:
        return sorted(
            (
                str(part.get("path") or ""),
                str(part.get("payloadType") or ""),
                str(part.get("payload") or ""),
            )
            for part in value.get("parts") or []
        )

    return parts(left) == parts(right)


__all__ = ["TOPOLOGY_ENTITY_COLUMNS", "TopologyOntologyBinder"]
