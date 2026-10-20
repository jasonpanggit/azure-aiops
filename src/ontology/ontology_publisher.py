from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections import Counter
from typing import Any

from .definition_compatibility import assert_legacy_publisher_compatible

ENTITY_COLUMNS = (
    ("resource_id", "String"),
    ("name", "String"),
    ("tenant_id", "String"),
    ("subscription_id", "String"),
    ("resource_type", "String"),
    ("location", "String"),
    ("lifecycle_status", "String"),
    ("ontology_version", "String"),
    ("change_version", "String"),
    ("lineage_json", "String"),
    ("semantic_metadata_json", "String"),
)


class OntologyPublisher:
    """Publishes Fabric-native Ontology definitions bound to Lakehouse Delta tables."""

    def __init__(
        self,
        manager,
        *,
        workspace_id: str,
        lakehouse_id: str,
        source_schema: str = "dbo",
    ) -> None:
        self.manager = manager
        self.workspace_id = workspace_id
        self.lakehouse_id = lakehouse_id
        self.source_schema = source_schema

    def publish(
        self,
        *,
        ontology_id: str,
        ontology_name: str,
        entity_types: dict[str, str],
        relationships: dict[tuple[str, str, str], str],
        expected_item_id: str | None = None,
    ) -> dict[str, Any]:
        definition = self.build_definition(entity_types, relationships, ontology_name)
        item = self.manager.resolve(ontology_id=ontology_id, ontology_name=ontology_name)
        if item:
            current = self.manager.get_definition(str(item["id"]))
            # Format/target gate: a legacy replacement must never reach
            # updateDefinition for TMDL, mixed, unknown or wrong-target items.
            assert_legacy_publisher_compatible(
                current,
                item_id=str(item["id"]),
                expected_item_id=expected_item_id,
            )
            if _definitions_equal(current, definition):
                return {**item, "action": "unchanged"}
            try:
                self.manager.update_definition(str(item["id"]), definition)
            except Exception as update_error:
                try:
                    observed = self.manager.get_definition(str(item["id"]))
                except Exception:  # noqa: BLE001 - rollback still uses captured definition.
                    observed = {}
                if _definitions_equal(observed, definition):
                    return {**item, "action": "updated-reconciled"}
                self._restore_definition(
                    str(item["id"]),
                    current,
                    update_error=update_error,
                )
                raise
            return {**item, "action": "updated"}
        try:
            created = self.manager.create(ontology_name, definition)
        except Exception:
            recovered = self.manager.resolve(ontology_name=ontology_name)
            if recovered and _definitions_equal(
                self.manager.get_definition(str(recovered["id"])), definition
            ):
                return {**recovered, "action": "created-reconciled"}
            raise
        return {**created, "action": "created"}

    def _restore_definition(
        self,
        ontology_id: str,
        previous: dict[str, Any],
        *,
        update_error: Exception,
    ) -> None:
        """Restore the prior active definition after a partial Fabric update."""

        try:
            self.manager.update_definition(ontology_id, previous)
            restored = self.manager.get_definition(ontology_id)
        except Exception as rollback_error:
            try:
                restored = self.manager.get_definition(ontology_id)
            except Exception:  # noqa: BLE001 - verify whether rollback landed.
                restored = {}
            if _definitions_equal(restored, previous):
                return
            raise RuntimeError(
                "Ontology update failed and the previous active definition "
                "could not be restored"
            ) from rollback_error
        if not _definitions_equal(restored, previous):
            raise RuntimeError(
                "Ontology update failed and rollback verification did not "
                "restore the previous active definition"
            ) from update_error

    def build_definition(
        self,
        entity_types: dict[str, str],
        relationships: dict[tuple[str, str, str], str],
        ontology_name: str,
    ) -> dict[str, Any]:
        if not isinstance(ontology_name, str) or not ontology_name.strip():
            raise ValueError("Ontology display name must be a non-empty string")
        if not isinstance(entity_types, dict) or not entity_types:
            raise ValueError("Ontology entity type bindings must be a non-empty mapping")
        if any(
            not isinstance(entity_name, str)
            or not entity_name.strip()
            or not isinstance(table_name, str)
            or not table_name.strip()
            for entity_name, table_name in entity_types.items()
        ):
            raise ValueError("Ontology entity type binding is invalid")
        if not isinstance(relationships, dict):
            raise TypeError("Ontology relationship bindings must be a mapping")
        for relationship, table_name in relationships.items():
            if (
                not isinstance(relationship, tuple)
                or len(relationship) != 3
                or any(
                    not isinstance(value, str) or not value.strip()
                    for value in relationship
                )
                or not isinstance(table_name, str)
                or not table_name.strip()
            ):
                raise ValueError("Ontology relationship binding is invalid")
            source_type, predicate, target_type = relationship
            if source_type not in entity_types or target_type not in entity_types:
                missing = [
                    value
                    for value in (source_type, target_type)
                    if value not in entity_types
                ]
                raise ValueError(
                    "Ontology relationship endpoint type is not defined: "
                    f"relationship=({source_type!r}, {predicate!r}, {target_type!r}) "
                    f"missing_types={missing!r} table={table_name!r}"
                )
        parts = [
            _part("definition.json", {}),
            _part(".platform", {"metadata": {"type": "Ontology", "displayName": ontology_name}}),
        ]
        entity_ids = {name: _numeric_id(f"entity:{name}") for name in entity_types}
        property_ids = {
            (name, column): _numeric_id(f"property:{name}:{column}")
            for name in entity_types
            for column, _ in ENTITY_COLUMNS
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
                for column, value_type in ENTITY_COLUMNS
            ]
            parts.append(
                _part(
                    f"EntityTypes/{entity_id}/definition.json",
                    {
                        "id": entity_id,
                        "namespace": "usertypes",
                        "baseEntityTypeId": None,
                        "name": entity_name,
                        "entityIdParts": [property_ids[(entity_name, "resource_id")]],
                        "displayNamePropertyId": property_ids[(entity_name, "name")],
                        "namespaceType": "Custom",
                        "visibility": "Visible",
                        "properties": properties,
                        "timeseriesProperties": [],
                    },
                )
            )
            binding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiops:{entity_name}:{table_name}"))
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
                                for column, _ in ENTITY_COLUMNS
                            ],
                            "sourceTableProperties": self._source_table(table_name),
                        },
                    },
                )
            )

        predicate_counts = Counter(predicate for _, predicate, _ in relationships)
        for (source_type, predicate, target_type), table_name in sorted(relationships.items()):
            relationship_id = _numeric_id(
                f"relationship:{source_type}:{predicate}:{target_type}"
            )
            parts.append(
                _part(
                    f"RelationshipTypes/{relationship_id}/definition.json",
                    {
                        "namespace": "usertypes",
                        "id": relationship_id,
                        "name": (
                            predicate
                            if predicate_counts[predicate] == 1
                            else f"{predicate}_{source_type}_{target_type}"
                        ),
                        "namespaceType": "Custom",
                        "source": {"entityTypeId": entity_ids[source_type]},
                        "target": {"entityTypeId": entity_ids[target_type]},
                    },
                )
            )
            contextualization_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"aiops:{source_type}:{predicate}:{target_type}:{table_name}",
                )
            )
            parts.append(
                _part(
                    f"RelationshipTypes/{relationship_id}/Contextualizations/{contextualization_id}.json",
                    {
                        "id": contextualization_id,
                        "dataBindingTable": self._relationship_table(table_name),
                        "sourceKeyRefBindings": [
                            {
                                "sourceColumnName": "subject_id",
                                "targetPropertyId": property_ids[(source_type, "resource_id")],
                            }
                        ],
                        "targetKeyRefBindings": [
                            {
                                "sourceColumnName": "object_id",
                                "targetPropertyId": property_ids[(target_type, "resource_id")],
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

    def _relationship_table(self, table_name: str) -> dict[str, str]:
        return self._source_table(table_name)


def _numeric_id(value: str) -> str:
    number = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big") & ((1 << 63) - 1)
    return str(number or 1)


def _part(path: str, payload: dict[str, Any]) -> dict[str, str]:
    # Do NOT sort_keys here: Fabric's Ontology import requires the
    # polymorphism discriminator ("sourceType") to be the first property of
    # sourceTableProperties objects, or import fails with
    # ALMOperationImportFailed ("metadata property is ... not the first
    # property in the deserialized JSON object"). Payload dicts are built in
    # a fixed, deterministic key order in code, so relying on Python's
    # guaranteed dict insertion order keeps encoding stable for
    # _definitions_equal comparisons while satisfying that requirement.
    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return {"path": path, "payload": encoded, "payloadType": "InlineBase64"}


def _definitions_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return definition_parts(left) == definition_parts(right)


def definition_parts(definition: dict[str, Any]) -> dict[str, Any]:
    """Decode parts, preserving semantics while removing known Fabric export defaults."""
    result: dict[str, Any] = {}
    schema_root = "https://developer.microsoft.com/json-schemas/fabric/item/ontology"
    for part in definition.get("parts") or []:
        path = part["path"]
        if path in result or part.get("payloadType") != "InlineBase64":
            raise ValueError("Native definition has duplicate or unsupported parts")
        payload = json.loads(base64.b64decode(part["payload"], validate=True))
        if not isinstance(payload, dict):
            raise TypeError("Native definition part must be a JSON object")
        segments = path.split("/")
        kind = ""
        if len(segments) == 3 and segments[-1] == "definition.json":
            kind = {"EntityTypes": "entityType", "RelationshipTypes": "relationshipType"}.get(
                segments[0], ""
            )
        elif len(segments) == 4 and segments[-1].endswith(".json"):
            kind = {
                ("EntityTypes", "DataBindings"): "dataBinding",
                ("RelationshipTypes", "Contextualizations"): "contextualization",
            }.get((segments[0], segments[2]), "")
        if kind and payload.get("$schema") == f"{schema_root}/{kind}/1.0.0/schema.json":
            payload.pop("$schema")
        if kind == "entityType" and payload.get("untypedProperties") == []:
            payload.pop("untypedProperties")
        source = None
        if kind == "dataBinding":
            source = (payload.get("dataBindingConfiguration") or {}).get("sourceTableProperties")
        elif kind == "contextualization":
            source = payload.get("dataBindingTable")
        if isinstance(source, dict) and source.get("sourceSchema") is None:
            source.pop("sourceSchema", None)
        if path == ".platform":
            metadata = payload.get("metadata") or {}
            payload = {"metadata": {key: metadata.get(key) for key in ("type", "displayName")}}
        result[path] = payload
    return result
