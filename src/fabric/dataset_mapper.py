from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ontology.entity_builder import EntityBuilder
from ontology.ontology_sync import OntologyGraphSynchronizer
from ontology.ontology_validator import OntologyValidator
from ontology.relationship_builder import RelationshipBuilder

ENTITY_FILES = (
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "PatchAssessment",
    "PatchInstallation",
    "AdvisorRecommendation",
)

ONTOLOGY_ENTITY_TYPES = (
    "Tenant",
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "KubernetesCluster",
    "PatchAssessment",
    "PatchInstallation",
    "AdvisorRecommendation",
    "LifecycleProduct",
    "Application",
    "Service",
    "Environment",
    "BusinessService",
    "BusinessFunction",
    "Owner",
    "SupportTeam",
    "RemediationPlan",
    "ApprovalRequirement",
    "RollbackPlan",
    "ExecutionStep",
    "RiskAssessment",
    "SimulationResult",
    "Prediction",
    "Forecast",
    "Trend",
    "OperationalDebt",
    "RiskDriver",
    "ChangeEvent",
    "ConfigurationBaseline",
    "ConfigurationDrift",
    "PolicyDeviation",
    "SecurityDeviation",
    "AuthorizedChange",
    "UnapprovedChange",
    "Incident",
    "OperationalEvent",
    "RootCause",
    "RiskPattern",
    "BlastRadius",
    "DependencyChain",
    "OperationalFinding",
)

ONTOLOGY_RELATIONSHIP_TYPES = (
    ("Tenant", "owns", "Subscription"),
    ("ManagementGroup", "contains", "Subscription"),
    ("Subscription", "contains", "ResourceGroup"),
    ("ArcServer", "managed_by", "Subscription"),
    ("SupportTeam", "supports", "Application"),
    ("Application", "deployed_in", "Environment"),
    ("Application", "implements", "Service"),
    ("Application", "depends_on", "Application"),
    ("BusinessService", "contains", "Application"),
    ("BusinessService", "owns", "Application"),
    ("BusinessService", "funded_by", "BusinessFunction"),
    ("Owner", "owns", "Service"),
    ("Owner", "owns", "BusinessService"),
    ("Application", "requiresPlan", "RemediationPlan"),
    ("RemediationPlan", "mitigatesRisk", "RiskAssessment"),
    ("RemediationPlan", "protectsService", "BusinessService"),
    ("RemediationPlan", "requiresApproval", "ApprovalRequirement"),
    ("RemediationPlan", "hasStep", "ExecutionStep"),
    ("RemediationPlan", "hasRollbackPlan", "RollbackPlan"),
    ("RemediationPlan", "hasSimulation", "SimulationResult"),
    ("Prediction", "hasForecast", "Forecast"),
    ("Prediction", "hasTrend", "Trend"),
    ("Prediction", "accumulatesDebt", "OperationalDebt"),
    ("Prediction", "drivenBy", "RiskDriver"),
    ("ChangeEvent", "classifiedAs", "AuthorizedChange"),
    ("ChangeEvent", "classifiedAs", "UnapprovedChange"),
    ("ChangeEvent", "evaluatedAgainst", "ConfigurationBaseline"),
    ("ChangeEvent", "resultedIn", "ConfigurationDrift"),
    ("Incident", "hasFinding", "OperationalFinding"),
    ("Incident", "hasBlastRadius", "BlastRadius"),
    ("BlastRadius", "hasDependencyChain", "DependencyChain"),
    ("Incident", "hasEvent", "OperationalEvent"),
    ("Incident", "hasProbableCause", "RootCause"),
    *(("ResourceGroup", "contains", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "member_of", "Application") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("Application", "hosted_on", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "belongs_to", "BusinessService") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "provides", "Service") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "owned_by", "Owner") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("AdvisorRecommendation", "affects", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("PatchAssessment", "evaluates", asset) for asset in ("VirtualMachine", "ArcServer")),
    *(("PatchInstallation", "records_installation_for", asset) for asset in ("VirtualMachine", "ArcServer")),
)


class InventoryDatasetMapper:
    def load(self, snapshot: Path, ingestion_run_id: str) -> dict[str, list[dict[str, Any]]]:
        manifest = _read_json(snapshot / "manifest.json")
        ingestion_timestamp = str(manifest.get("startedAt") or "1970-01-01T00:00:00Z")
        entities = {
            entity_type: _read_jsonl(snapshot / "entities" / f"{entity_type}.jsonl")
            for entity_type in ENTITY_FILES
        }
        relationships = _read_jsonl(snapshot / "relationships/relationships.jsonl")
        changes = _read_jsonl(snapshot / "changes/resource_changes.jsonl")

        all_resources = [
            *entities["Resource"],
            *entities["VirtualMachine"],
            *entities["ArcServer"],
        ]
        inventory_entity_rows = [
            _entity_row(row, entity_type, ingestion_run_id)
            for entity_type, rows in entities.items()
            for row in rows
        ]
        resource_index = {row["resource_id"]: row for row in inventory_entity_rows}
        subscription_tenants = {
            str(row.get("subscriptionId") or "").casefold(): str(row.get("tenantId") or "")
            for row in entities["Subscription"]
        }
        relationship_rows = [
            _relationship_row(row, resource_index, ingestion_run_id)
            for row in relationships
        ]

        entity_rows = EntityBuilder().build(
            inventory_entity_rows, ingestion_run_id, ingestion_timestamp
        )
        ontology_relationships = RelationshipBuilder().build(entity_rows, ingestion_run_id)
        graph = OntologyGraphSynchronizer(OntologyValidator()).build(
            entity_rows, ontology_relationships
        )

        datasets = {
            "bronze_resources": [_asset_row(row, ingestion_run_id) for row in all_resources],
            "bronze_subscriptions": [
                _entity_row(row, "Subscription", ingestion_run_id)
                for row in entities["Subscription"]
            ],
            "bronze_resourcegroups": [
                _entity_row(row, "ResourceGroup", ingestion_run_id)
                for row in entities["ResourceGroup"]
            ],
            "bronze_advisor": [
                _entity_row(row, "AdvisorRecommendation", ingestion_run_id)
                for row in entities["AdvisorRecommendation"]
            ],
            "bronze_patchassessment": [
                _entity_row(row, "PatchAssessment", ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "bronze_patchinstallation": [
                _entity_row(row, "PatchInstallation", ingestion_run_id)
                for row in entities["PatchInstallation"]
            ],
            "bronze_resource_changes": [
                _change_row(row, resource_index, subscription_tenants, ingestion_run_id)
                for row in changes
            ],
            "silver_vm_inventory": [
                _asset_row(row, ingestion_run_id) for row in entities["VirtualMachine"]
            ],
            "silver_server_inventory": [
                _asset_row(row, ingestion_run_id)
                for row in [*entities["VirtualMachine"], *entities["ArcServer"]]
            ],
            "silver_compliance": [
                _compliance_row(row, ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "silver_patch_history": [
                _patch_history_row(row, ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "silver_patch_installations": [
                _patch_installation_row(row, ingestion_run_id)
                for row in entities["PatchInstallation"]
            ],
            "silver_resource_relationships": relationship_rows,
            "ontology_entities": graph.entities,
            "ontology_relationships": graph.relationships,
            "ontology_application_context": graph.views["application_context"],
            "ontology_infrastructure_context": graph.views["infrastructure_context"],
            "ontology_subscription_context": graph.views["subscription_context"],
            "ontology_compliance_context": graph.views["compliance_context"],
            "ontology_business_context": graph.views["business_context"],
            "ontology_health": [
                _health_row(graph.health, ingestion_run_id, ingestion_timestamp)
            ],
            "ontology_quality_report": [
                _ontology_quality_row(
                    graph.quality_report, ingestion_run_id, ingestion_timestamp
                )
            ],
        }
        for entity_type in ONTOLOGY_ENTITY_TYPES:
            datasets[ontology_entity_table(entity_type)] = [
                row for row in graph.entities if row["entity_type"] == entity_type
            ]
        relationship_types = {
            (row["subject_type"], row["predicate"], row["object_type"])
            for row in graph.relationships
        }
        for subject_type, predicate, object_type in relationship_types:
            table_name = ontology_relationship_table(subject_type, predicate, object_type)
            datasets[table_name] = [
                row
                for row in graph.relationships
                if (row["subject_type"], row["predicate"], row["object_type"])
                == (subject_type, predicate, object_type)
            ]
        for relationship_type in ONTOLOGY_RELATIONSHIP_TYPES:
            datasets.setdefault(ontology_relationship_table(*relationship_type), [])
        return datasets


def _entity_row(row: dict[str, Any], entity_type: str, run_id: str) -> dict[str, Any]:
    base = _base(row, run_id)
    return {
        **base,
        "entity_type": entity_type,
        "name": str(row.get("name") or row.get("displayName") or ""),
        "resource_type": str(row.get("resourceType") or ""),
        "location": str(row.get("location") or ""),
        "payload_json": _canonical(row),
    }


def _asset_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        **_entity_row(row, str(row.get("entityType") or "Resource"), run_id),
        "resource_group": str(row.get("resourceGroup") or ""),
        "status": str(row.get("status") or ""),
        "os_name": str(row.get("osName") or row.get("osType") or ""),
        "os_version": str(row.get("osVersion") or ""),
        "vm_size": str(row.get("vmSize") or ""),
    }


def _compliance_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _entity_row(row, "PatchAssessment", run_id)
    classifications = {
        str(key).casefold(): int(value or 0)
        for key, value in (row.get("availablePatchCountByClassification") or {}).items()
    }
    result.update(
        {
            "assessed_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "status": str(row.get("status") or "unknown"),
            "last_modified": str(row.get("lastModifiedDateTime") or ""),
            "available_updates": sum(classifications.values()),
            "missing_critical_updates": sum(
                value for key, value in classifications.items() if "critical" in key
            ),
            "missing_security_updates": sum(
                value for key, value in classifications.items() if "security" in key
            ),
        }
    )
    return result


def _patch_installation_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _entity_row(row, "PatchInstallation", run_id)
    classifications = row.get("classifications") or []
    errors = row.get("errorDetails") or []
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "update_id": str(row.get("kbId") or row.get("name") or ""),
            "update_name": str(row.get("updateName") or row.get("name") or ""),
            "category": ",".join(str(item) for item in classifications),
            "severity": "Critical"
            if any(str(item).casefold() == "critical" for item in classifications)
            else "Security"
            if any(str(item).casefold() == "security" for item in classifications)
            else "Unknown",
            "status": str(row.get("status") or "unknown"),
            "published_at": str(row.get("publishedDateTime") or ""),
            "installed_at": str(row.get("lastModifiedDateTime") or ""),
            "error": "; ".join(
                str(item.get("code") or item.get("message") or "")
                for item in errors
                if isinstance(item, dict)
            ),
        }
    )
    return result


def _patch_history_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _compliance_row(row, run_id)
    observed = str(result.get("last_modified") or result.get("timestamp") or "unknown")
    result["resource_id"] = f"{result['resource_id']}|{observed}"
    return result


def _relationship_row(
    row: dict[str, Any],
    entity_index: dict[str, dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    subject = str(row.get("subjectId") or "").casefold()
    subject_entity = entity_index.get(subject, {})
    normalized = {
        **row,
        "subjectId": subject,
        "objectId": str(row.get("objectId") or "").casefold(),
    }
    return {
        "tenant_id": str(subject_entity.get("tenant_id") or ""),
        "subscription_id": str(subject_entity.get("subscription_id") or ""),
        "resource_id": str(row.get("relationshipId") or ""),
        "timestamp": str(row.get("lastObservedTimestamp") or ""),
        "change_version": _version(normalized),
        "ingestion_run_id": run_id,
        "subject_id": subject,
        "predicate": str(row.get("predicate") or ""),
        "object_id": normalized["objectId"],
        "confidence": float(row.get("confidence") or 0),
        "source": str(row.get("source") or ""),
        "payload_json": _canonical(row),
    }


def _change_row(
    row: dict[str, Any],
    entity_index: dict[str, dict[str, Any]],
    subscription_tenants: dict[str, str],
    run_id: str,
) -> dict[str, Any]:
    resource_id = str(row.get("targetResourceId") or row.get("id") or "").casefold()
    target = entity_index.get(resource_id, {})
    subscription = _subscription_from_id(resource_id)
    return {
        "tenant_id": str(
            row.get("tenantId")
            or target.get("tenant_id")
            or subscription_tenants.get(subscription.casefold())
            or ""
        ),
        "subscription_id": (
            subscription
            or str(row.get("subscriptionId") or target.get("subscription_id") or "")
        ),
        "resource_id": str(row.get("id") or "").casefold(),
        "timestamp": str(row.get("changedAt") or row.get("lastObservedTimestamp") or ""),
        "change_version": _version(row),
        "ingestion_run_id": run_id,
        "target_resource_id": resource_id,
        "change_type": str(row.get("changeType") or ""),
        "payload_json": _canonical(row),
    }


def _base(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    resource_id = str(row.get("id") or row.get("sourceId") or "").casefold()
    semantic = {
        key: value
        for key, value in row.items()
        if key not in {"createdTimestamp", "lastObservedTimestamp", "ingestion_run_id"}
    }
    return {
        "tenant_id": str(row.get("tenantId") or ""),
        "subscription_id": str(row.get("subscriptionId") or _subscription_from_id(resource_id)),
        "resource_id": resource_id,
        "timestamp": str(row.get("lastObservedTimestamp") or ""),
        "change_version": _version(semantic),
        "ingestion_run_id": run_id,
    }


def _version(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _subscription_from_id(value: str) -> str:
    parts = value.split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def ontology_entity_table(entity_type: str) -> str:
    return f"ontology_{_slug(entity_type)}_entities"


def ontology_relationship_table(subject_type: str, predicate: str, object_type: str) -> str:
    return f"ontology_rel_{_slug(predicate)}_{_slug(subject_type)}_{_slug(object_type)}"


def _slug(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", words.casefold()).strip("_")


def _health_row(health: dict[str, Any], run_id: str, timestamp: str) -> dict[str, Any]:
    row = {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": f"ontology-health://{run_id}",
        "timestamp": timestamp,
        "change_version": _version(health),
        "ingestion_run_id": run_id,
        "entity_count": int(health["entity_count"]),
        "relationship_count": int(health["relationship_count"]),
        "orphan_resources": int(health["orphan_resources"]),
        "missing_ownership": int(health["missing_ownership"]),
        "missing_tags": int(health["missing_tags"]),
        "synchronization_errors": int(health["synchronization_errors"]),
    }
    return row


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def _ontology_quality_row(
    report: dict[str, Any], run_id: str, timestamp: str
) -> dict[str, Any]:
    return {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": f"ontology-quality://{run_id}",
        "timestamp": timestamp,
        "change_version": _version(report),
        "ingestion_run_id": run_id,
        "passed": bool(report["passed"]),
        "report_json": _canonical(report),
    }
