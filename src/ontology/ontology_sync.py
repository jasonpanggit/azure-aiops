from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .entity_builder import stable_version
from .ontology_validator import OntologyValidator

ASSET_TYPES = {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"}


@dataclass(frozen=True)
class OntologyGraphResult:
    entities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    views: dict[str, list[dict[str, Any]]]
    health: dict[str, Any]
    quality_report: dict[str, Any]


class OntologyGraphSynchronizer:
    """Versions graph snapshots and preserves removed entities as retired records."""

    def __init__(
        self,
        validator: OntologyValidator,
        *,
        max_entities: int = 100_000,
        max_relationships: int = 250_000,
    ) -> None:
        for name, value in (
            ("max_entities", max_entities),
            ("max_relationships", max_relationships),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Ontology synchronization {name} must be positive")
        self.validator = validator
        self.max_entities = max_entities
        self.max_relationships = max_relationships

    def build(
        self,
        entities: Iterable[dict[str, Any]],
        relationships: Iterable[dict[str, Any]],
    ) -> OntologyGraphResult:
        return self.synchronize(list(entities), list(relationships))

    def synchronize(
        self,
        current_entities: Iterable[dict[str, Any]],
        current_relationships: Iterable[dict[str, Any]],
        *,
        previous_entities: Iterable[dict[str, Any]] = (),
        previous_relationships: Iterable[dict[str, Any]] = (),
        ontology_version: str = "1",
        timestamp: str = "",
    ) -> OntologyGraphResult:
        current_entity_rows = list(current_entities)
        current_relationship_rows = list(current_relationships)
        previous_entity_rows = list(previous_entities)
        previous_relationship_rows = list(previous_relationships)
        if any(
            len(rows) > bound
            for rows, bound in (
                (current_entity_rows, self.max_entities),
                (previous_entity_rows, self.max_entities),
            )
        ):
            raise ValueError("Ontology synchronization entity source exceeds bound")
        if any(
            len(rows) > bound
            for rows, bound in (
                (current_relationship_rows, self.max_relationships),
                (previous_relationship_rows, self.max_relationships),
            )
        ):
            raise ValueError("Ontology synchronization relationship source exceeds bound")
        current_report = self.validator.validate(
            current_entity_rows, current_relationship_rows
        )
        if not current_report.passed:
            raise ValueError("Invalid ontology graph: current snapshot validation failed")
        if previous_entity_rows or previous_relationship_rows:
            previous_report = self.validator.validate(
                previous_entity_rows, previous_relationship_rows
            )
            if not previous_report.passed:
                raise ValueError("Invalid ontology graph: previous snapshot validation failed")

        entities = {
            _canonical_id(row["resource_id"]): _normalize_entity(row)
            for row in current_entity_rows
        }
        relationships = {
            _canonical_id(row["resource_id"]): _normalize_relationship(row)
            for row in current_relationship_rows
        }
        previous_entity_index = {
            _canonical_id(row["resource_id"]): _normalize_entity(row)
            for row in previous_entity_rows
        }
        previous_relationship_index = {
            _canonical_id(row["resource_id"]): _normalize_relationship(row)
            for row in previous_relationship_rows
        }
        for row in entities.values():
            row["ontology_version"] = ontology_version
            previous = previous_entity_index.get(row["resource_id"])
            if previous:
                row["valid_from"] = previous.get("valid_from") or row["valid_from"]
        for row in relationships.values():
            row["ontology_version"] = ontology_version
            previous = previous_relationship_index.get(row["resource_id"])
            if previous:
                row["valid_from"] = previous.get("valid_from") or row["valid_from"]
        for previous in previous_entity_index.values():
            if previous["resource_id"] not in entities:
                entities[previous["resource_id"]] = _retire(previous, ontology_version, timestamp)
        for previous in previous_relationship_index.values():
            if previous["resource_id"] not in relationships:
                relationships[previous["resource_id"]] = _retire(previous, ontology_version, timestamp)
        if len(entities) > self.max_entities:
            raise ValueError("Ontology synchronized entity graph exceeds bound")
        if len(relationships) > self.max_relationships:
            raise ValueError("Ontology synchronized relationship graph exceeds bound")

        entity_rows = sorted(entities.values(), key=lambda row: row["resource_id"])
        relationship_rows = sorted(relationships.values(), key=lambda row: row["resource_id"])
        report = self.validator.validate(entity_rows, relationship_rows).to_dict()
        if not report["passed"]:
            raise ValueError("Invalid ontology graph: synchronized snapshot validation failed")
        health = _health(entity_rows, relationship_rows)
        return OntologyGraphResult(
            entity_rows,
            relationship_rows,
            _views(entity_rows, relationship_rows),
            health,
            report,
        )


def _canonical_id(value: Any) -> str:
    return str(value or "").strip().casefold()


def _normalize_entity(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["resource_id"] = _canonical_id(normalized.get("resource_id"))
    return normalized


def _normalize_relationship(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["resource_id"] = _canonical_id(normalized.get("resource_id"))
    normalized["subject_id"] = _canonical_id(normalized.get("subject_id"))
    normalized["object_id"] = _canonical_id(normalized.get("object_id"))
    return normalized


def _retire(row: dict[str, Any], version: str, timestamp: str) -> dict[str, Any]:
    if row.get("lifecycle_status") == "retired":
        return dict(row)
    retired = dict(row)
    retired["lifecycle_status"] = "retired"
    retired["retired_at"] = timestamp
    retired["ontology_version"] = version
    retired["change_version"] = stable_version(
        {key: value for key, value in retired.items() if key not in {"timestamp", "ingestion_run_id", "change_version"}}
    )
    return retired


def _health(entities: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> dict[str, Any]:
    active = [row for row in entities if row.get("lifecycle_status") == "active"]
    active_relationships = [
        row for row in relationships if row.get("lifecycle_status") == "active"
    ]
    owned = {
        row["subject_id"]
        for row in active_relationships
        if row["predicate"] == "owned_by"
    }
    connected = {row["subject_id"] for row in active_relationships} | {
        row["object_id"] for row in active_relationships
    }
    assets = [row for row in active if row["entity_type"] in ASSET_TYPES]
    missing_ownership = sum(1 for row in assets if row["resource_id"] not in owned)
    orphan_resources = sum(1 for row in assets if row["resource_id"] not in connected)
    missing_tags = sum(1 for row in assets if not _tags(row))
    return {
        "entity_count": len(active),
        "relationship_count": len(active_relationships),
        "orphan_resources": orphan_resources,
        "missing_ownership": missing_ownership,
        "missing_tags": missing_tags,
        "synchronization_errors": 0,
    }


def _tags(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    tags = payload.get("tags") or {}
    return tags if isinstance(tags, dict) else {}


def _views(
    entities: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    by_id = {
        row["resource_id"]: row
        for row in entities
        if row.get("lifecycle_status") == "active"
    }
    active_relationships = [
        row for row in relationships if row.get("lifecycle_status") == "active"
    ]

    def view(root_types: set[str]) -> list[dict[str, Any]]:
        roots = {
            row["resource_id"]
            for row in by_id.values()
            if row["entity_type"] in root_types
        }
        relevant = [
            row
            for row in active_relationships
            if row["subject_id"] in roots or row["object_id"] in roots
        ]
        ids = roots | {row["subject_id"] for row in relevant} | {row["object_id"] for row in relevant}
        return [by_id[entity_id] for entity_id in sorted(ids) if entity_id in by_id]

    return {
        "application_context": view({"Application"}),
        "infrastructure_context": view({"Subscription", "ResourceGroup"}),
        "subscription_context": view({"Subscription"}),
        "compliance_context": view({"PatchAssessment", "AdvisorRecommendation"}),
        "business_context": view({"BusinessService", "Service"}),
    }
