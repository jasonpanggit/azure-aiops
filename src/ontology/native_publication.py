"""Native definition publication from verified, already-published Delta tables."""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from fabric.dataset_mapper import (
    ONTOLOGY_ENTITY_TYPES,
    ontology_entity_table,
    ontology_relationship_table,
)
from fabric.lakehouse_manager import LakehouseManager
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

from .ontology_publisher import ENTITY_COLUMNS, OntologyPublisher
from .ontology_validator import OntologyValidator


class NativeOntologyPublication:
    """Publish only a native item; never replay ingestion or change pointers."""

    def __init__(
        self,
        *,
        delta: DeltaWriter,
        onelake: OneLakeWriter,
        lakehouse: LakehouseManager,
        publisher: OntologyPublisher,
        ontology_name: str,
        ontology_id: str = "",
    ) -> None:
        self.delta = delta
        self.onelake = onelake
        self.lakehouse = lakehouse
        self.publisher = publisher
        self.ontology_name = ontology_name
        self.ontology_id = ontology_id

    def preview(self, *, source_generation: str) -> dict[str, Any]:
        """Validate existing sources and return the exact hash-bound proposal."""
        if not source_generation.strip():
            raise ValueError("An explicit completed ingestion generation is required")
        marker_uri = self.onelake.table_uri("metadata", "ingestion_state")
        marker_version = self.delta.version(marker_uri)
        if marker_version is None:
            raise ValueError("Completed ingestion metadata is missing")
        markers = self.delta.read(marker_uri, version=marker_version)
        completed = [
            row for row in markers
            if row.get("status") == "completed"
            and row.get("ontology_entity_version") is not None
            and row.get("ontology_relationship_version") is not None
        ]
        if not completed:
            raise ValueError("No completed canonical ontology generation exists")
        marker = max(completed, key=lambda row: str(row.get("timestamp") or ""))
        if marker.get("ingestion_run_id") != source_generation:
            raise ValueError("Expected generation is not the latest completed ingestion")
        if marker.get("failed_records") != 0 or not marker.get("source_run_id"):
            raise ValueError("Source ingestion is incomplete or lacks provenance")
        versions = {
            name: _version(marker.get(field))
            for name, field in (
                ("entities", "ontology_entity_version"),
                ("relationships", "ontology_relationship_version"),
            )
        }
        heads = {str(marker_uri): marker_version}
        canonical: dict[str, list[dict[str, Any]]] = {}
        for name, version in versions.items():
            uri = self.onelake.table_uri("ontology", name)
            heads[str(uri)] = version
            if self.delta.version(uri) != version:
                raise ValueError("Canonical Delta head is not the completed generation")
            canonical[name] = self.delta.read(uri, version=version)
        graph = OntologyValidator().validate(
            canonical["entities"], canonical["relationships"]
        )
        if not graph.passed or not canonical["entities"]:
            raise ValueError(f"Canonical graph validation failed: {graph.to_dict()}")
        if any(
            str(row.get("source") or "").strip().casefold() in {"model", "ai", "llm"}
            or row.get("model_derived") is True
            for row in canonical["relationships"]
        ):
            raise ValueError("Model-derived relationships cannot gain native authority")
        entities: dict[str, list[dict[str, Any]]] = defaultdict(list)
        relationships: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in canonical["entities"]:
            if row.get("lifecycle_status") == "active":
                entities[row["entity_type"]].append(row)
        for row in canonical["relationships"]:
            if row.get("lifecycle_status") == "active":
                key = (row["subject_type"], row["predicate"], row["object_type"])
                if key[0] == key[2] or key[0] not in entities or key[2] not in entities:
                    raise ValueError("Native relationship lacks distinct active endpoint types")
                relationships[key].append(row)
        if not entities or set(entities) - set(ONTOLOGY_ENTITY_TYPES):
            raise ValueError("Native entity types are empty or not registered")
        catalog = self.lakehouse.list_tables(self.publisher.lakehouse_id)
        catalog_by_name = {
            str(row.get("name") or row.get("displayName") or ""): row
            for row in catalog
        }
        entity_bindings = {name: ontology_entity_table(name) for name in sorted(entities)}
        relationship_bindings = {
            key: ontology_relationship_table(*key) for key in sorted(relationships)
        }
        tables = []
        historical_rows: dict[str, set[str]] = {}
        for bindings, groups, columns in (
            (entity_bindings, entities, tuple(name for name, _ in ENTITY_COLUMNS)),
            (relationship_bindings, relationships, ("subject_id", "object_id")),
        ):
            for key, table_name in bindings.items():
                table = catalog_by_name.get(table_name)
                if table is None or str(table.get("type") or "").casefold() != "managed":
                    raise ValueError(f"Binding source is not a registered managed table: {table_name}")
                uri = self.onelake.table_uri("ontology", table_name.removeprefix("ontology_"))
                version = self.delta.version(uri)
                if version is None:
                    raise ValueError(f"Binding Delta source is missing: {table_name}")
                metadata = self.delta.describe(uri, version=version)
                schema = {
                    field["name"]: field["type"]
                    for field in metadata["schema"]["fields"]
                }
                if any(schema.get(column) != "string" for column in columns):
                    raise ValueError(f"Native binding requires existing string columns: {table_name}")
                if metadata["configuration"].get("delta.columnMapping.mode", "none") != "none":
                    raise ValueError(f"Column mapping is unsupported for native binding: {table_name}")
                actual = self.delta.read(uri, version=version)
                retained_rows = 0
                if _rows(actual) != _rows(groups[key]):
                    # Unchanged typed tables retain older completed row metadata:
                    # Delta overwrite idempotency compares resource/change versions.
                    metadata_columns = frozenset({"ingestion_run_id", "ontology_version", "timestamp"})
                    if _rows(actual, exclude=metadata_columns) != _rows(
                        groups[key], exclude=metadata_columns
                    ):
                        raise ValueError(f"Typed binding differs from the completed active graph: {table_name}")
                    kind = "entities" if isinstance(key, str) else "relationships"
                    if kind not in historical_rows:
                        historical_rows[kind] = set()
                        for previous in completed:
                            if previous.get("failed_records") != 0 or not previous.get("source_run_id"):
                                continue
                            prior = self.delta.read(
                                self.onelake.table_uri("ontology", kind),
                                version=_version(previous[f"ontology_{'entity' if kind == 'entities' else 'relationship'}_version"]),
                            )
                            historical_rows[kind].update(_rows(prior))
                    if not set(_rows(actual)) <= historical_rows[kind]:
                        raise ValueError(f"Typed binding metadata has no completed generation provenance: {table_name}")
                    retained_rows = sum((_rows(actual) - _rows(groups[key])).values())
                heads[str(uri)] = version
                tables.append({
                    "name": table_name, "version": version, "rows": len(actual),
                    "retained_generation_rows": retained_rows,
                    "row_ontology_versions": sorted({str(row["ontology_version"]) for row in actual}),
                })
        definition = self.publisher.build_definition(
            entity_bindings, relationship_bindings, self.ontology_name
        )
        item = self.publisher.manager.resolve(
            ontology_id=self.ontology_id, ontology_name=self.ontology_name
        )
        current = self.publisher.manager.get_definition(str(item["id"])) if item else None
        if item and not current.get("parts"):
            raise RuntimeError("Existing native definition could not be read")
        self._check_heads(heads)
        preview = {
            "source_generation": source_generation,
            "source_run_id": marker["source_run_id"],
            "canonical_versions": versions,
            "workspace_id": self.publisher.workspace_id,
            "lakehouse_id": self.publisher.lakehouse_id,
            "ontology_name": self.ontology_name,
            "existing_item_id": str(item["id"]) if item else "",
            "existing_definition_hash": _digest(_parts(current)) if current else "",
            "graph_validation": graph.to_dict(),
            "entity_type_count": len(entity_bindings),
            "relationship_type_count": len(relationship_bindings),
            "binding_count": len(tables),
            "entity_bindings": entity_bindings,
            "relationship_bindings": [
                [*key, table_name] for key, table_name in relationship_bindings.items()
            ],
            "tables": tables,
            "heads": heads,
            "definition": definition,
        }
        return {**preview, "preview_hash": _digest(preview)}

    def publish(
        self, *, source_generation: str, expected_preview_hash: str
    ) -> dict[str, Any]:
        """Apply an explicitly approved, still-current proposal and verify readback."""
        if not expected_preview_hash:
            raise ValueError("An approved preview hash is required before native writes")
        proposal = self.preview(source_generation=source_generation)
        if proposal["preview_hash"] != expected_preview_hash:
            raise ValueError("Native preview changed; obtain approval for a fresh preview")
        definition = proposal["definition"]
        item_id = proposal["existing_item_id"]
        unchanged = False
        if item_id:
            current = self.publisher.manager.get_definition(item_id)
            if _digest(_parts(current)) != proposal["existing_definition_hash"]:
                raise ValueError("Native definition changed after preview")
            unchanged = _parts(current) == _parts(definition)
        action = "unchanged"
        if not unchanged:
            self._check_heads(proposal["heads"])
            result = self.publisher.publish(
                ontology_id=item_id,
                ontology_name=self.ontology_name,
                entity_types=proposal["entity_bindings"],
                relationships={
                    (source, predicate, target): table
                    for source, predicate, target, table in proposal["relationship_bindings"]
                },
            )
            item = self.publisher.manager.resolve(
                ontology_id=item_id, ontology_name=self.ontology_name
            )
            if not item:
                raise RuntimeError("Native publication completed without a resolvable item")
            item_id = str(item["id"])
            action = result["action"]
        verified_item = self.publisher.manager.resolve(ontology_id=item_id)
        if not verified_item or str(verified_item.get("id") or "") != item_id:
            raise RuntimeError("Native item GET did not verify the published item")
        observed = self.publisher.manager.get_definition(item_id)
        if _parts(observed) != _parts(definition):
            raise RuntimeError(
                f"Native item {item_id} exists but definition/binding readback differs"
            )
        self._check_heads(proposal["heads"])
        return {
            key: proposal[key] for key in (
                "source_generation", "source_run_id", "canonical_versions",
                "workspace_id", "lakehouse_id", "ontology_name", "preview_hash",
                "entity_type_count", "relationship_type_count", "binding_count", "tables",
            )
        } | {"item_id": item_id, "action": action, "definition_verified": True}

    def _check_heads(self, heads: dict[str, int]) -> None:
        for uri, version in heads.items():
            if self.delta.version(uri) != version:
                raise ValueError("Source tables changed during native publication")


def _version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Completed generation contains an invalid Delta version")
    return value


def _rows(
    rows: list[dict[str, Any]], *, exclude: frozenset[str] = frozenset()
) -> Counter[str]:
    return Counter(
        json.dumps(
            {key: value for key, value in row.items() if key not in exclude},
            sort_keys=True, separators=(",", ":"),
        )
        for row in rows
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _parts(definition: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for part in definition.get("parts") or []:
        path = part["path"]
        if path in result or part.get("payloadType") != "InlineBase64":
            raise ValueError("Native definition has duplicate or unsupported parts")
        payload = json.loads(base64.b64decode(part["payload"], validate=True))
        if path == ".platform":
            metadata = payload.get("metadata") or {}
            payload = {"metadata": {key: metadata.get(key) for key in ("type", "displayName")}}
        result[path] = payload
    if not result:
        raise ValueError("Native definition has no readable parts")
    return result
