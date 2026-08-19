from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

ASSET_TYPES = {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"}
CASE_INSENSITIVE_FACT_FIELDS = {
    "business_function",
    "category",
    "compliance_status",
    "cost_center",
    "currency",
    "environment",
    "impact",
    "name",
    "period",
    "severity",
    "source",
    "status",
    "title",
}


class SemanticIndexes:
    """In-memory query indexes over an authoritative Fabric Ontology snapshot."""

    def __init__(
        self,
        entities: Iterable[dict[str, Any]],
        relationships: Iterable[dict[str, Any]],
        *,
        inventory: Iterable[dict[str, Any]] = (),
        compliance: Iterable[dict[str, Any]] = (),
        security: Iterable[dict[str, Any]] = (),
        cost: Iterable[dict[str, Any]] = (),
    ) -> None:
        self.entities: dict[str, dict[str, Any]] = {}
        for row in entities:
            if row.get("lifecycle_status", "active") != "active":
                continue
            entity_id = _canonical_id(row["resource_id"])
            normalized = dict(row)
            normalized["resource_id"] = entity_id
            self.entities[entity_id] = normalized
        self.relationships: list[dict[str, Any]] = []
        for row in relationships:
            if row.get("lifecycle_status", "active") != "active":
                continue
            normalized = dict(row)
            normalized["subject_id"] = _canonical_id(row.get("subject_id"))
            normalized["object_id"] = _canonical_id(row.get("object_id"))
            if (
                normalized["subject_id"] in self.entities
                and normalized["object_id"] in self.entities
            ):
                self.relationships.append(normalized)
        self.by_type: dict[str, list[str]] = defaultdict(list)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity_id, row in self.entities.items():
            self.by_type[str(row.get("entity_type") or "")].append(entity_id)
            self.by_name[str(row.get("name") or "").casefold()].append(entity_id)
        for edge in self.relationships:
            self.outgoing[str(edge["subject_id"])].append(edge)
            self.incoming[str(edge["object_id"])].append(edge)
        self.inventory = {
            _canonical_id(row.get("resource_id")): dict(row)
            for row in inventory
            if row.get("resource_id")
        }
        self.compliance: dict[str, dict[str, Any]] = {}
        for row in compliance:
            key = str(
                row.get("assessed_resource_id") or row.get("resource_id") or ""
            ).casefold()
            if not key:
                continue
            current = self.compliance.get(key)
            observed = _fact_order(row)
            current_observed = _fact_order(current or {})
            if current is None or observed >= current_observed:
                self.compliance[key] = dict(row)
        self.security: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in security:
            target = _canonical_id(
                row.get("target_resource_id") or row.get("resource_id")
            )
            if target and not _contains_fact(self.security[target], row):
                self.security[target].append(dict(row))
        self.cost: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in cost:
            target = _canonical_id(
                row.get("target_resource_id") or row.get("resource_id")
            )
            if target and not _contains_fact(self.cost[target], row):
                self.cost[target].append(dict(row))

    def resolve(self, value: str, *, types: set[str] | None = None) -> str:
        needle = value.strip().casefold()
        candidates = list(self.by_name.get(needle, ()))
        if needle in self.entities:
            candidates.insert(0, needle)
        if types is not None:
            candidates = [
                entity_id
                for entity_id in candidates
                if self.entities[entity_id].get("entity_type") in types
            ]
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            raise LookupError(f"No semantic entity matches {value!r}")
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous semantic entity {value!r}; specify a domain type")
        return candidates[0]

    def public(self, entity_id: str) -> dict[str, str]:
        row = self.entities[entity_id]
        return {
            key: str(row.get(key) or "")
            for key in (
                "entity_type",
                "name",
                "resource_type",
                "location",
                "lifecycle_status",
            )
        }

    def related(
        self,
        entity_id: str,
        predicate: str,
        *,
        direction: str = "out",
        types: set[str] | None = None,
    ) -> list[str]:
        if direction == "out":
            ids = [
                str(edge["object_id"])
                for edge in self.outgoing[entity_id]
                if edge.get("predicate") == predicate
            ]
        elif direction == "in":
            ids = [
                str(edge["subject_id"])
                for edge in self.incoming[entity_id]
                if edge.get("predicate") == predicate
            ]
        else:
            raise ValueError("direction must be 'in' or 'out'")
        if types is not None:
            ids = [
                item
                for item in ids
                if self.entities[item].get("entity_type") in types
            ]
        return sorted(set(ids))

    def applications_for_resource(self, resource_id: str) -> list[str]:
        return self.related(resource_id, "member_of", types={"Application"})

    def resources_for_application(self, application_id: str) -> list[str]:
        return self.related(application_id, "hosted_on", types=ASSET_TYPES)

    def business_services_for_application(self, application_id: str) -> list[str]:
        return self.related(
            application_id,
            "contains",
            direction="in",
            types={"BusinessService"},
        )

    def owners_for_resource(self, resource_id: str) -> list[str]:
        return self.related(resource_id, "owned_by", types={"Owner"})

    def business_functions_for_resource(self, resource_id: str) -> list[str]:
        business_services = set(
            self.related(resource_id, "belongs_to", types={"BusinessService"})
        )
        for application_id in self.applications_for_resource(resource_id):
            business_services.update(
                self.business_services_for_application(application_id)
            )
        return sorted(
            {
                function_id
                for service_id in business_services
                for function_id in self.related(
                    service_id, "funded_by", types={"BusinessFunction"}
                )
            }
        )

    def support_teams_for_application(self, application_id: str) -> list[str]:
        return self.related(
            application_id,
            "supports",
            direction="in",
            types={"SupportTeam"},
        )

    def advisors_for_resource(self, resource_id: str) -> list[str]:
        return self.related(
            resource_id,
            "affects",
            direction="in",
            types={"AdvisorRecommendation"},
        )

    def upstream_dependencies(self, application_id: str) -> list[str]:
        return self.related(application_id, "depends_on", types={"Application"})

    def downstream_dependents(self, application_id: str) -> list[str]:
        return self.related(
            application_id,
            "depends_on",
            direction="in",
            types={"Application"},
        )


def _fact_order(row: dict[str, Any]) -> tuple[datetime, str]:
    value = str(row.get("last_modified") or row.get("timestamp") or "")
    try:
        observed = datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, TypeError):
        observed = datetime.min.replace(tzinfo=UTC)
    return observed, json.dumps(row, sort_keys=True, default=str)


def _canonical_id(value: Any) -> str:
    return str(value or "").strip().casefold()


def _fact_identity(row: dict[str, Any]) -> str:
    normalized = _normalize_fact_value(dict(row))
    for field_name in ("resource_id", "target_resource_id", "assessed_resource_id"):
        if field_name in normalized:
            normalized[field_name] = _canonical_id(normalized[field_name])
    for field_name in CASE_INSENSITIVE_FACT_FIELDS:
        value = normalized.get(field_name)
        if isinstance(value, str):
            normalized[field_name] = " ".join(value.casefold().split())
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)


def _normalize_fact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_fact_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_normalize_fact_value(child) for child in value]
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def _contains_fact(rows: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    identity = _fact_identity(candidate)
    return any(_fact_identity(row) == identity for row in rows)
