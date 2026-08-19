from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OntologyValidationReport:
    passed: bool
    entity_count: int
    relationship_count: int
    duplicate_entities: int
    duplicate_relationships: int
    dangling_relationships: int
    self_relationships: int
    invalid_entities: int = 0
    invalid_relationships: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "entity_count": self.entity_count,
            "relationship_count": self.relationship_count,
            "duplicate_entities": self.duplicate_entities,
            "duplicate_relationships": self.duplicate_relationships,
            "dangling_relationships": self.dangling_relationships,
            "self_relationships": self.self_relationships,
            "invalid_entities": self.invalid_entities,
            "invalid_relationships": self.invalid_relationships,
        }


class OntologyValidator:
    """Fail-closed structural validation for synchronized ontology graphs."""

    ENTITY_REQUIRED = (
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "entity_type",
        "name",
        "payload_json",
        "lineage_json",
        "semantic_metadata_json",
        "lifecycle_status",
        "valid_from",
        "ontology_version",
    )
    RELATIONSHIP_REQUIRED = (
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "subject_id",
        "subject_type",
        "predicate",
        "object_id",
        "object_type",
        "source",
        "payload_json",
        "lineage_json",
        "lifecycle_status",
        "valid_from",
        "ontology_version",
    )

    def validate(
        self,
        entities: Iterable[dict[str, Any]],
        relationships: Iterable[dict[str, Any]],
    ) -> OntologyValidationReport:
        entity_rows = list(entities)
        relationship_rows = list(relationships)
        valid_entities = [row for row in entity_rows if isinstance(row, Mapping)]
        valid_relationships = [
            row for row in relationship_rows if isinstance(row, Mapping)
        ]

        invalid_entities = len(entity_rows) - len(valid_entities)
        invalid_relationships = len(relationship_rows) - len(valid_relationships)
        for row in valid_entities:
            if not all(_nonempty_string(row.get(field)) for field in self.ENTITY_REQUIRED):
                invalid_entities += 1
            if row.get("lifecycle_status") not in {"active", "retired"}:
                invalid_entities += 1
            if any(
                not isinstance(row.get(field), str)
                for field in ("resource_type", "location", "retired_at")
            ):
                invalid_entities += 1
            if (
                row.get("lifecycle_status") == "active"
                and row.get("retired_at") != ""
            ) or (
                row.get("lifecycle_status") == "retired"
                and not _nonempty_string(row.get("retired_at"))
            ):
                invalid_entities += 1
            if any(
                not _valid_json_mapping(row.get(field))
                for field in (
                    "payload_json",
                    "lineage_json",
                    "semantic_metadata_json",
                )
            ):
                invalid_entities += 1

        entity_ids = [
            str(row.get("resource_id") or "").strip().casefold()
            for row in valid_entities
            if _nonempty_string(row.get("resource_id"))
        ]
        known = set(entity_ids)
        entity_types = {
            str(row.get("resource_id") or "").strip().casefold(): row.get(
                "entity_type"
            )
            for row in valid_entities
            if _nonempty_string(row.get("resource_id"))
        }
        entity_lifecycle = {
            str(row.get("resource_id") or "").strip().casefold(): row.get(
                "lifecycle_status"
            )
            for row in valid_entities
            if _nonempty_string(row.get("resource_id"))
        }
        relationship_ids: list[str] = []
        dangling = 0
        self_links = 0
        for row in valid_relationships:
            if not all(
                _nonempty_string(row.get(field))
                for field in self.RELATIONSHIP_REQUIRED
            ):
                invalid_relationships += 1
                continue
            if row.get("lifecycle_status") not in {"active", "retired"}:
                invalid_relationships += 1
            if not isinstance(row.get("retired_at"), str):
                invalid_relationships += 1
            if (
                row.get("lifecycle_status") == "active"
                and row.get("retired_at") != ""
            ) or (
                row.get("lifecycle_status") == "retired"
                and not _nonempty_string(row.get("retired_at"))
            ):
                invalid_relationships += 1
            if any(
                not _valid_json_mapping(row.get(field))
                for field in ("payload_json", "lineage_json")
            ):
                invalid_relationships += 1
            relationship_ids.append(
                str(row.get("resource_id") or "").strip().casefold()
            )
            subject = str(row.get("subject_id") or "").strip().casefold()
            object_id = str(row.get("object_id") or "").strip().casefold()
            if subject not in known or object_id not in known:
                dangling += 1
            else:
                if row.get("subject_type") != entity_types.get(subject):
                    invalid_relationships += 1
                if row.get("object_type") != entity_types.get(object_id):
                    invalid_relationships += 1
                if row.get("lifecycle_status") == "active" and (
                    entity_lifecycle.get(subject) != "active"
                    or entity_lifecycle.get(object_id) != "active"
                ):
                    invalid_relationships += 1
            if subject == object_id:
                self_links += 1
            confidence = row.get("confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                invalid_relationships += 1

        duplicate_entities = len(entity_ids) - len(set(entity_ids))
        duplicate_relationships = len(relationship_ids) - len(
            set(relationship_ids)
        )
        passed = not any(
            (
                duplicate_entities,
                duplicate_relationships,
                dangling,
                self_links,
                invalid_entities,
                invalid_relationships,
            )
        )
        return OntologyValidationReport(
            passed=passed,
            entity_count=len(entity_rows),
            relationship_count=len(relationship_rows),
            duplicate_entities=duplicate_entities,
            duplicate_relationships=duplicate_relationships,
            dangling_relationships=dangling,
            self_relationships=self_links,
            invalid_entities=invalid_entities,
            invalid_relationships=invalid_relationships,
        )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_json_mapping(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(parsed, dict)
