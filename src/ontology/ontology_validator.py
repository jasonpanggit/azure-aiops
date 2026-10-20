from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping
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


@dataclass(frozen=True)
class OntologyPublicationValidationReport:
    """Complete graph, authority, lineage, and consumer validation result."""

    passed: bool
    graph: OntologyValidationReport
    model_derived_relationships: int
    lineage_complete: bool
    consumers_complete: bool
    consumers_compatible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "graph": self.graph.to_dict(),
            "model_derived_relationships": self.model_derived_relationships,
            "lineage_complete": self.lineage_complete,
            "consumers_complete": self.consumers_complete,
            "consumers_compatible": self.consumers_compatible,
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
    REQUIRED_CONSUMER_FAMILIES = frozenset(
        {"api", "fabric", "agent", "export", "semantic"}
    )

    def __init__(
        self,
        *,
        allowed_triples: Iterable[tuple[str, str, str]] | None = None,
    ) -> None:
        if allowed_triples is None:
            # Late import avoids the dataset mapper -> validator import cycle
            # while retaining one authoritative vocabulary definition.
            from fabric.dataset_mapper import allowed_relationship_triples

            allowed_triples = allowed_relationship_triples()
        self._allowed_triples = frozenset(
            (str(subject), str(predicate), str(object_type))
            for subject, predicate, object_type in allowed_triples
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
        entity_scopes = {
            str(row.get("resource_id") or "").strip().casefold(): _row_scope(row)
            for row in valid_entities
            if _nonempty_string(row.get("resource_id"))
        }
        relationship_ids: list[str] = []
        relationship_keys: list[tuple[str, str, str]] = []
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
            relationship_keys.append(
                (
                    subject,
                    str(row.get("predicate") or ""),
                    object_id,
                )
            )
            triple = (
                str(row.get("subject_type") or ""),
                str(row.get("predicate") or ""),
                str(row.get("object_type") or ""),
            )
            if subject not in known or object_id not in known:
                dangling += 1
            elif row.get("lifecycle_status") == "active":
                # The current vocabulary is authoritative for active edges.
                # Retired rows preserve the vocabulary and endpoint types that
                # were valid when captured; historical rows are never queried
                # as active topology and must survive additive vocabulary
                # evolution for replay/audit.
                if triple not in self._allowed_triples:
                    invalid_relationships += 1
                # Only active relationships must agree with the *current*
                # entity_type. A retired relationship's subject_type/object_type
                # reflects the type at the time it was captured; the referenced
                # entity may have since been reclassified (e.g. ManagedIdentity
                # <-> Resource), which is expected and not a data-quality defect.
                if row.get("subject_type") != entity_types.get(subject):
                    invalid_relationships += 1
                if row.get("object_type") != entity_types.get(object_id):
                    invalid_relationships += 1
                if (
                    entity_lifecycle.get(subject) != "active"
                    or entity_lifecycle.get(object_id) != "active"
                ):
                    invalid_relationships += 1
                # Phase 13 candidates carry an explicit server-derived scope.
                # Legacy ontology rows predate that field and continue through
                # their existing tenant/subscription validation path.
                relationship_scope = str(row.get("scope") or "").strip().casefold()
                if relationship_scope and (
                    entity_scopes.get(subject) != relationship_scope
                    or entity_scopes.get(object_id) != relationship_scope
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
        duplicate_relationships = max(
            len(relationship_ids) - len(set(relationship_ids)),
            len(relationship_keys) - len(set(relationship_keys)),
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

    def validate_publication(
        self,
        *,
        entities: Iterable[dict[str, Any]],
        relationships: Iterable[dict[str, Any]],
        source_generation: str,
        proposal_lineage: Iterable[str],
        decision_lineage: Iterable[str],
        consumer_compatibility: Mapping[str, bool],
        model_authorizer: Callable[[list[dict[str, Any]]], bool] | None = None,
    ) -> OntologyPublicationValidationReport:
        """Validate every input that can make a generation authoritative.

        Without an explicit ``model_authorizer`` port (Phase 14 maintenance)
        any model-derived relationship keeps failing validation.  The port
        returns whether every model row is independently authorized; a caller
        boolean cannot replace it.
        """

        entity_rows = list(entities)
        relationship_rows = list(relationships)
        graph = self.validate(entity_rows, relationship_rows)
        model_rows = [
            row
            for row in relationship_rows
            if str(row.get("source") or "").strip().casefold()
            in {"model", "ai", "llm"}
            or row.get("model_derived") is True
        ]
        model_derived = len(model_rows)
        model_authorized = model_derived == 0
        if model_derived and model_authorizer is not None:
            try:
                model_authorized = model_authorizer(model_rows) is True
            except Exception:  # noqa: BLE001 - authorizer failure is a denial
                model_authorized = False
        proposals = tuple(proposal_lineage)
        decisions = tuple(decision_lineage)
        lineage_complete = bool(str(source_generation).strip()) and all(
            isinstance(value, str) and bool(value.strip())
            for value in (*proposals, *decisions)
        )
        consumer_keys = set(consumer_compatibility)
        consumers_complete = (
            consumer_keys == self.REQUIRED_CONSUMER_FAMILIES
            and all(
                isinstance(value, bool)
                for value in consumer_compatibility.values()
            )
        )
        consumers_compatible = consumers_complete and all(
            consumer_compatibility.values()
        )
        return OntologyPublicationValidationReport(
            passed=(
                graph.passed
                and model_authorized
                and lineage_complete
                and consumers_compatible
            ),
            graph=graph,
            model_derived_relationships=model_derived,
            lineage_complete=lineage_complete,
            consumers_complete=consumers_complete,
            consumers_compatible=consumers_compatible,
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


def _row_scope(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("scope") or "").strip().casefold()
    if explicit:
        return explicit
    tenant = str(row.get("tenant_id") or "").strip().casefold()
    subscription = str(row.get("subscription_id") or "").strip().casefold()
    return f"{tenant}/{subscription}" if tenant and subscription else ""
