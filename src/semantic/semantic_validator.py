from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

BANNED_PUBLIC_FIELDS = {
    "payload_json",
    "lineage_json",
    "semantic_metadata_json",
    "tenant_id",
    "ingestion_run_id",
}

FACT_CONTRACTS = {
    "inventory": (
        ("resource_id",),
        ("name", "resource_type", "entity_type", "status", "location", "payload_json"),
    ),
    "compliance": (
        ("assessed_resource_id", "resource_id"),
        (
            "status",
            "compliance_status",
            "failed_patch_count",
            "succeeded_patch_count",
            "payload_json",
        ),
    ),
    "security": (
        ("target_resource_id", "resource_id"),
        ("title", "severity", "status", "category", "impact", "payload_json"),
    ),
    "cost": (
        ("target_resource_id", "resource_id"),
        ("amount", "currency", "cost_center", "business_function", "name", "payload_json"),
    ),
}


@dataclass(frozen=True)
class SemanticValidationReport:
    passed: bool
    errors: tuple[str, ...]


class SemanticValidator:
    def validate_context(self, payload: dict[str, Any]) -> SemanticValidationReport:
        errors: list[str] = []
        if not payload.get("context_type"):
            errors.append("context_type is required")
        subject = payload.get("subject") or {}
        if not subject.get("entity_type") or not subject.get("name"):
            errors.append("subject entity_type and name are required")
        exposed = _find_banned_fields(payload)
        if exposed:
            errors.append("unsafe fields: " + ",".join(sorted(exposed)))
        return SemanticValidationReport(not errors, tuple(errors))

    def validate_snapshot(
        self,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        *,
        inventory: list[dict[str, Any]] | None = None,
        compliance: list[dict[str, Any]] | None = None,
        security: list[dict[str, Any]] | None = None,
        cost: list[dict[str, Any]] | None = None,
    ) -> SemanticValidationReport:
        errors: list[str] = []
        for index, row in enumerate(entities):
            lifecycle = row.get("lifecycle_status", "active")
            if not _valid_nonempty_string(lifecycle):
                errors.append(f"entity lifecycle_status invalid: {index}")
            for field_name in (
                "tenant_id",
                "subscription_id",
                "timestamp",
                "change_version",
                "ingestion_run_id",
                "resource_type",
                "location",
                "payload_json",
                "lineage_json",
                "semantic_metadata_json",
                "valid_from",
                "retired_at",
                "ontology_version",
            ):
                value = row.get(field_name)
                if value is not None and not isinstance(value, str):
                    errors.append(f"entity {field_name} invalid: {index}")
        active_entities = [
            row
            for row in entities
            if row.get("lifecycle_status", "active") == "active"
        ]
        entity_ids_list = [
            str(row.get("resource_id") or "").casefold() for row in active_entities
        ]
        entity_ids = set(entity_ids_list)
        entity_types = {
            str(row.get("resource_id") or "").casefold(): str(
                row.get("entity_type") or ""
            )
            for row in active_entities
        }
        for duplicate in _duplicates(entity_ids_list):
            errors.append(f"duplicate entity_id: {duplicate}")
        for row in active_entities:
            required_values = [
                row.get(field) for field in ("resource_id", "entity_type", "name")
            ]
            if not all(required_values):
                errors.append(
                    "entity missing required fields: "
                    + str(row.get("resource_id") or "unknown")
                )
            elif not all(_valid_nonempty_string(value) for value in required_values):
                errors.append(
                    "entity required fields must be non-empty strings: "
                    + str(row.get("resource_id") or "unknown")
                )
        active_relationships = [
            row
            for row in relationships
            if row.get("lifecycle_status", "active") == "active"
        ]
        for index, row in enumerate(relationships):
            lifecycle = row.get("lifecycle_status", "active")
            if not _valid_nonempty_string(lifecycle):
                errors.append(f"relationship lifecycle_status invalid: {index}")
            for field_name in (
                "tenant_id",
                "subscription_id",
                "timestamp",
                "change_version",
                "ingestion_run_id",
                "source",
                "payload_json",
                "lineage_json",
                "valid_from",
                "retired_at",
                "ontology_version",
            ):
                value = row.get(field_name)
                if value is not None and not isinstance(value, str):
                    errors.append(f"relationship {field_name} invalid: {index}")
        relationship_ids = [
            str(row.get("resource_id") or "").casefold()
            for row in active_relationships
        ]
        for duplicate in _duplicates(relationship_ids):
            errors.append(f"duplicate relationship_id: {duplicate}")
        for relationship in active_relationships:
            relationship_id = str(relationship.get("resource_id") or "unknown")
            invalid_fields = [
                field
                for field in (
                    "resource_id",
                    "subject_id",
                    "subject_type",
                    "predicate",
                    "object_id",
                    "object_type",
                )
                if not _valid_nonempty_string(relationship.get(field))
            ]
            for field in invalid_fields:
                value = relationship.get(field)
                if not value:
                    if field in {"subject_id", "object_id"}:
                        continue
                    errors.append(f"relationship missing {field}: {relationship_id}")
                else:
                    errors.append(
                        f"relationship {field} must be a non-empty string: {relationship_id}"
                    )
            if "subject_id" in invalid_fields or "object_id" in invalid_fields:
                errors.append(f"relationship missing endpoint: {relationship_id}")
            elif (
                str(relationship.get("subject_id")).casefold() not in entity_ids
                or str(relationship.get("object_id")).casefold() not in entity_ids
            ):
                errors.append(f"dangling relationship: {relationship_id}")
            else:
                if relationship.get("subject_type") and relationship.get(
                    "subject_type"
                ) != entity_types.get(str(relationship.get("subject_id")).casefold()):
                    errors.append(f"relationship subject_type mismatch: {relationship_id}")
                if relationship.get("object_type") and relationship.get(
                    "object_type"
                ) != entity_types.get(str(relationship.get("object_id")).casefold()):
                    errors.append(f"relationship object_type mismatch: {relationship_id}")
            confidence = relationship.get("confidence")
            if confidence is not None:
                try:
                    if (
                        isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float))
                        or not math.isfinite(confidence)
                        or not 0 <= confidence <= 1
                    ):
                        errors.append(f"relationship confidence out of range: {relationship_id}")
                except (TypeError, ValueError):
                    errors.append(f"relationship confidence invalid: {relationship_id}")
        entity_keys = {entity_id.casefold() for entity_id in entity_ids}
        facts = {
            "inventory": inventory or [],
            "compliance": compliance or [],
            "security": security or [],
            "cost": cost or [],
        }
        for label, rows in facts.items():
            target_keys, content_keys = FACT_CONTRACTS[label]
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"{label} fact missing target: {index}")
                    continue
                provided_targets = [key for key in target_keys if key in row]
                for target_key in provided_targets:
                    if not _valid_nonempty_string(row.get(target_key)):
                        errors.append(
                            f"{label} fact {target_key} invalid: {index}"
                        )
                target = next(
                    (
                        row[key]
                        for key in provided_targets
                        if _valid_nonempty_string(row.get(key))
                    ),
                    "",
                )
                if not target:
                    errors.append(f"{label} fact missing target: {index}")
                    continue
                if target.casefold() not in entity_keys:
                    errors.append(f"{label} fact has dangling target: {index}")
                if not any(_has_content(row.get(key)) for key in content_keys):
                    errors.append(f"{label} fact missing content: {index}")
                for field_name in (
                    "tenant_id",
                    "subscription_id",
                    "change_version",
                    "ingestion_run_id",
                    "entity_type",
                    "resource_type",
                    "location",
                    "payload_json",
                ):
                    value = row.get(field_name)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"{label} fact {field_name} invalid: {index}")
                string_fields = {
                    "inventory": (
                        "tenant_id",
                        "subscription_id",
                        "change_version",
                        "ingestion_run_id",
                        "name",
                        "status",
                        "environment",
                        "criticality",
                        "resource_type",
                        "entity_type",
                        "location",
                        "payload_json",
                        "resource_group",
                        "os_name",
                        "os_version",
                        "vm_size",
                    ),
                    "compliance": (
                        "tenant_id",
                        "subscription_id",
                        "change_version",
                        "ingestion_run_id",
                        "entity_type",
                        "name",
                        "resource_type",
                        "location",
                        "status",
                        "compliance_status",
                        "payload_json",
                    ),
                    "security": (
                        "title",
                        "severity",
                        "status",
                        "category",
                        "impact",
                        "source",
                        "payload_json",
                    ),
                    "cost": (
                        "currency",
                        "cost_center",
                        "period",
                        "business_function",
                        "name",
                        "payload_json",
                    ),
                }[label]
                for field_name in string_fields:
                    value = row.get(field_name)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"{label} fact {field_name} invalid: {index}")
                for field_name in ("timestamp", "last_modified"):
                    value = row.get(field_name)
                    if value is not None and not isinstance(value, str):
                        errors.append(f"{label} fact {field_name} invalid: {index}")
                if label == "compliance":
                    for field_name in (
                        "available_updates",
                        "missing_critical_updates",
                        "missing_security_updates",
                        "failed_patch_count",
                        "succeeded_patch_count",
                    ):
                        value = row.get(field_name)
                        if value is not None and (
                            isinstance(value, bool)
                            or not isinstance(value, int)
                            or value < 0
                        ):
                            errors.append(
                                f"compliance fact {field_name} invalid: {index}"
                            )
                elif label == "cost":
                    amount = row.get("amount")
                    if amount is not None and (
                        isinstance(amount, bool)
                        or not isinstance(amount, (int, float))
                        or not math.isfinite(amount)
                        or amount < 0
                    ):
                        errors.append(f"cost fact amount invalid: {index}")
        return SemanticValidationReport(not errors, tuple(sorted(set(errors))))


def _find_banned_fields(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(set(value) & BANNED_PUBLIC_FIELDS)
        for item in value.values():
            found.update(_find_banned_fields(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_banned_fields(item))
    return found


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value or "unknown")
        seen.add(value)
    return sorted(duplicates)


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _valid_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
