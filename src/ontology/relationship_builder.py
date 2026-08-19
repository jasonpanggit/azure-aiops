from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .entity_builder import semantic_id, stable_version

ASSET_TYPES = {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"}


class RelationshipBuilder:
    """Infers deterministic structural, operational, and tag-derived relationships."""

    def __init__(
        self, *, max_entities: int = 100_000, max_relationships: int = 250_000
    ) -> None:
        for name, value in (
            ("max_entities", max_entities),
            ("max_relationships", max_relationships),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Ontology {name} must be a positive integer")
        self.max_entities = max_entities
        self.max_relationships = max_relationships

    def build(self, entities: Iterable[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
        rows = list(entities)
        if len(rows) > self.max_entities:
            raise ValueError("Ontology relationship entity source exceeds configured bound")
        if any(not isinstance(row, Mapping) for row in rows):
            raise TypeError("Ontology relationship entities must be mappings")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Ontology relationship run_id must be a non-empty string")
        by_id = {str(row["resource_id"]).casefold(): row for row in rows}
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_lineage: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_type[str(row["entity_type"])].append(row)
            for source_id in _lineage(row):
                by_lineage[source_id].append(row)

        relationships: dict[str, dict[str, Any]] = {}

        def connect(subject: dict[str, Any] | None, predicate: str, obj: dict[str, Any] | None, source: str) -> None:
            if not subject or not obj or subject["resource_id"] == obj["resource_id"]:
                return
            relationship_id = _relationship_id(subject["resource_id"], predicate, obj["resource_id"])
            if (
                relationship_id not in relationships
                and len(relationships) >= self.max_relationships
            ):
                raise ValueError("Ontology relationship bound exceeded")
            row = {
                "tenant_id": str(subject.get("tenant_id") or obj.get("tenant_id") or ""),
                "subscription_id": str(subject.get("subscription_id") or obj.get("subscription_id") or ""),
                "resource_id": relationship_id,
                "timestamp": str(subject.get("timestamp") or obj.get("timestamp") or ""),
                "change_version": "",
                "ingestion_run_id": run_id,
                "subject_id": subject["resource_id"],
                "subject_type": subject["entity_type"],
                "predicate": predicate,
                "object_id": obj["resource_id"],
                "object_type": obj["entity_type"],
                "confidence": 1.0,
                "source": source,
                "payload_json": "{}",
                "lineage_json": json.dumps(
                    {"source_entity_ids": [subject["resource_id"], obj["resource_id"]]},
                    sort_keys=True,
                ),
                "lifecycle_status": "active",
                "valid_from": str(subject.get("timestamp") or obj.get("timestamp") or ""),
                "retired_at": "",
                "ontology_version": "1",
            }
            row["change_version"] = stable_version(
                {
                    key: value
                    for key, value in row.items()
                    if key
                    not in {
                        "timestamp",
                        "ingestion_run_id",
                        "change_version",
                        "valid_from",
                        "retired_at",
                        "ontology_version",
                    }
                }
            )
            relationships[relationship_id] = row

        tenants = {row["tenant_id"]: row for row in by_type["Tenant"]}
        subscriptions = {row["subscription_id"].casefold(): row for row in by_type["Subscription"]}
        management_groups = {
            row["resource_id"].casefold(): row for row in by_type["ManagementGroup"]
        }
        groups = {row["resource_id"].casefold(): row for row in by_type["ResourceGroup"]}
        for subscription in by_type["Subscription"]:
            connect(tenants.get(subscription["tenant_id"]), "owns", subscription, "inventory")
            for management_group_id in _management_group_ancestors(subscription):
                connect(
                    management_groups.get(management_group_id),
                    "contains",
                    subscription,
                    "inventory",
                )
        for group in by_type["ResourceGroup"]:
            connect(subscriptions.get(group["subscription_id"].casefold()), "contains", group, "inventory")
        for asset_type in ASSET_TYPES:
            for asset in by_type[asset_type]:
                group_id = _group_id(asset["resource_id"])
                connect(groups.get(group_id), "contains", asset, "inventory")
                if asset_type == "ArcServer":
                    connect(asset, "managed_by", subscriptions.get(asset["subscription_id"].casefold()), "inventory")

                related = by_lineage.get(asset["resource_id"], [])
                tags = _tags(asset)
                application_names = {
                    value
                    for value in (tags.get("appname", ""), tags.get("application", ""))
                    if value
                }
                applications = [
                    by_id[semantic_id("Application", asset["tenant_id"], name)]
                    for name in sorted(application_names)
                    if semantic_id("Application", asset["tenant_id"], name) in by_id
                ]
                services = _of_type(related, "Service")
                business_services = _of_type(related, "BusinessService")
                owners = _of_type(related, "Owner")
                support_teams = _of_type(related, "SupportTeam")
                environments = _of_type(related, "Environment")
                business_functions = _of_type(related, "BusinessFunction")
                dependency_names = _tag_values(
                    tags.get("dependson", "")
                    or tags.get("dependencies", "")
                    or tags.get("applicationdependencies", "")
                )
                for application in applications:
                    connect(asset, "member_of", application, "resource_tag")
                    connect(application, "hosted_on", asset, "resource_tag")
                    for environment in environments:
                        connect(application, "deployed_in", environment, "resource_tag")
                    for team in support_teams:
                        connect(team, "supports", application, "resource_tag")
                    for service in services:
                        connect(application, "implements", service, "resource_tag")
                    for business_service in business_services:
                        connect(business_service, "contains", application, "resource_tag")
                        connect(business_service, "owns", application, "resource_tag")
                    if application["name"].casefold() in {
                        tags.get("appname", "").casefold(),
                        tags.get("application", "").casefold(),
                    }:
                        for dependency_name in dependency_names:
                            dependency_id = semantic_id(
                                "Application", asset["tenant_id"], dependency_name
                            )
                            connect(
                                application,
                                "depends_on",
                                by_id.get(dependency_id),
                                "dependency_tag",
                            )
                for business_service in business_services:
                    connect(asset, "belongs_to", business_service, "resource_tag")
                    for owner in owners:
                        connect(owner, "owns", business_service, "resource_tag")
                    for function in business_functions:
                        connect(business_service, "funded_by", function, "resource_tag")
                for service in services:
                    connect(asset, "provides", service, "resource_tag")
                    for owner in owners:
                        connect(owner, "owns", service, "resource_tag")
                for owner in owners:
                    connect(asset, "owned_by", owner, "resource_tag")

        for recommendation in by_type["AdvisorRecommendation"]:
            target = _target(recommendation)
            connect(recommendation, "affects", by_id.get(target), "advisor")
        for assessment in by_type["PatchAssessment"]:
            target = _target(assessment)
            connect(assessment, "evaluates", by_id.get(target), "patch_assessment")
        for installation in by_type["PatchInstallation"]:
            target = _target(installation)
            connect(
                installation,
                "records_installation_for",
                by_id.get(target),
                "patch_installation",
            )

        return sorted(relationships.values(), key=lambda row: row["resource_id"])


def _relationship_id(subject: str, predicate: str, obj: str) -> str:
    return "relationship://" + stable_version([subject.casefold(), predicate, obj.casefold()])[:40]


def _lineage(row: dict[str, Any]) -> list[str]:
    try:
        payload = json.loads(str(row.get("lineage_json") or "{}"))
    except json.JSONDecodeError:
        return []
    return [str(value).casefold() for value in payload.get("source_resource_ids", []) if value]


def _of_type(rows: list[dict[str, Any]], entity_type: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["entity_type"] == entity_type]


def _group_id(resource_id: str) -> str:
    marker = "/providers/"
    prefix = resource_id.casefold().split(marker, 1)[0]
    return prefix if "/resourcegroups/" in prefix else ""


def _target(row: dict[str, Any]) -> str:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return ""
    return str(payload.get("targetResourceId") or payload.get("resourceId") or "").casefold()


def _management_group_ancestors(row: dict[str, Any]) -> list[str]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return []
    ancestors = []
    for item in payload.get("managementGroupAncestorsChain", []):
        value = str(item.get("id") or item.get("name") or "").casefold()
        if value and not value.startswith("/"):
            value = f"/providers/microsoft.management/managementgroups/{value}"
        if value:
            ancestors.append(value)
    return ancestors


def _tags(row: dict[str, Any]) -> dict[str, str]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    return {
        str(key).casefold(): str(value).strip()
        for key, value in (payload.get("tags") or {}).items()
    }


def _tag_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
