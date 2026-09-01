"""Normalize Defender for Cloud assessment records into exposure entities."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_CVE_PATTERN = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)


def normalize_assessment(row: Mapping[str, Any], observed: str) -> dict[str, Any] | None:
    """Return a recommendation-level Defender assessment entity."""
    properties = _mapping(row.get("properties"))
    target = _target_resource_id(properties)
    assessment_id = _text(row.get("id")).casefold()
    if not assessment_id or not target:
        return None
    status = _status(properties)
    return {
        **_base(row, observed, "DefenderAssessment"),
        "id": assessment_id,
        "targetResourceId": target,
        "status": status,
        "severity": _severity(properties),
        "recommendation": _first_text(
            properties.get("displayName"),
            properties.get("metadata", {}).get("displayName")
            if isinstance(properties.get("metadata"), Mapping)
            else "",
            row.get("name"),
        ),
        "description": _first_text(
            properties.get("description"),
            properties.get("metadata", {}).get("description")
            if isinstance(properties.get("metadata"), Mapping)
            else "",
        ),
        "remediation": _first_text(
            properties.get("remediationDescription"),
            properties.get("remediation"),
        ),
        "lastAssessedAt": _first_text(
            properties.get("statusChangeDate"),
            properties.get("timeGenerated"),
            observed,
        ),
        "resourceType": _first_text(
            _mapping(properties.get("resourceDetails")).get("resourceType"),
            _mapping(properties.get("resourceDetails")).get("ResourceType"),
        ),
    }


def normalize_vulnerability_subassessments(
    row: Mapping[str, Any], observed: str
) -> list[dict[str, Any]]:
    """Return one actionable vulnerability entity per CVE in a subassessment."""
    properties = _mapping(row.get("properties"))
    status = _status(properties)
    if status.casefold() in {"healthy", "notapplicable", "not applicable", "resolved"}:
        return []
    target = _target_resource_id(properties)
    source_id = _text(row.get("id")).casefold()
    cve_ids = _cve_ids(properties)
    if not source_id or not target or not cve_ids:
        return []

    additional = _mapping(properties.get("additionalData"))
    software = _mapping(additional.get("softwareDetails"))
    assessment_id = source_id.split("/subassessments/", 1)[0]
    recommendation = _first_text(
        properties.get("remediationDescription"),
        properties.get("remediation"),
        properties.get("displayName"),
    )
    assessed_at = _first_text(
        properties.get("timeGenerated"),
        properties.get("statusChangeDate"),
        additional.get("publishedTime"),
        observed,
    )
    result: list[dict[str, Any]] = []
    for cve_id in cve_ids:
        entity = {
            **_base(row, observed, "DefenderVulnerabilityFinding"),
            "id": f"{source_id}|{cve_id.casefold()}",
            "sourceId": _text(row.get("id")),
            "targetResourceId": target,
            "assessmentId": assessment_id,
            "cveId": cve_id,
            "status": status or "Unhealthy",
            "severity": _severity(properties),
            "recommendation": recommendation,
            "description": _first_text(
                properties.get("description"),
                additional.get("description"),
            ),
            "lastAssessedAt": assessed_at,
            "patchable": bool(additional.get("patchable", False)),
            "softwareVendor": _text(software.get("vendor")),
            "softwareName": _first_text(software.get("productName"), software.get("product")),
            "softwareVersion": _text(software.get("version")),
            "fixedVersion": _first_text(software.get("fixedVersion"), software.get("fixVersion")),
            "resourceType": _first_text(
                _mapping(properties.get("resourceDetails")).get("resourceType"),
                additional.get("assessedResourceType"),
            ),
        }
        result.append(entity)
    return result


def normalize_security_alert(
    row: Mapping[str, Any], observed: str
) -> dict[str, Any] | None:
    """Return a Defender alert while preserving its observed lifecycle state."""
    properties = _mapping(row.get("properties"))
    alert_id = _text(row.get("id")).casefold()
    if not alert_id:
        return None
    resource_ids = _resource_ids(
        properties.get("resourceIdentifiers"),
        properties.get("entities"),
        properties.get("compromisedEntity"),
    )
    remediation = properties.get("remediationSteps") or ()
    if not isinstance(remediation, (list, tuple)):
        remediation = [remediation]
    return {
        **_base(row, observed, "SecurityAlert"),
        "id": alert_id,
        "status": _first_text(properties.get("status"), "Unknown"),
        "severity": _first_text(properties.get("severity"), "Unknown"),
        "title": _first_text(
            properties.get("alertDisplayName"),
            properties.get("displayName"),
            row.get("name"),
        ),
        "description": _text(properties.get("description")),
        "alertType": _text(properties.get("alertType")),
        "intent": _text(properties.get("intent")),
        "productName": _text(properties.get("productName")),
        "vendorName": _text(properties.get("vendorName")),
        "compromisedEntity": _text(properties.get("compromisedEntity")),
        "timeGenerated": _first_text(
            properties.get("timeGeneratedUtc"),
            properties.get("timeGenerated"),
            observed,
        ),
        "processingEndTime": _first_text(
            properties.get("processingEndTimeUtc"),
            properties.get("processingEndTime"),
        ),
        "remediationSteps": [_text(value) for value in remediation if _text(value)],
        "resourceIds": list(resource_ids),
        "cveIds": sorted(
            {
                match.upper()
                for match in _CVE_PATTERN.findall(str(properties))
            }
        ),
    }


def normalize_attack_path(
    row: Mapping[str, Any], observed: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize an attack path and its graph components without guessing identities."""
    properties = _mapping(row.get("properties"))
    path_id = _text(row.get("id")).casefold()
    if not path_id:
        return None, [], []
    component = _mapping(
        properties.get("graphComponent") or properties.get("graphComponents")
    )
    raw_entities = component.get("entities") or ()
    raw_connections = component.get("connections") or ()
    if not isinstance(raw_entities, (list, tuple)):
        raw_entities = []
    if not isinstance(raw_connections, (list, tuple)):
        raw_connections = []

    nodes: list[dict[str, Any]] = []
    internal_to_node: dict[str, str] = {}
    for index, raw in enumerate(raw_entities):
        entity = _mapping(raw)
        internal_id = _first_text(
            entity.get("entityInternalId"),
            entity.get("internalId"),
            entity.get("id"),
            str(index),
        )
        node_id = f"{path_id}|node|{internal_id.casefold()}"
        internal_to_node[internal_id.casefold()] = node_id
        resource_ids = _resource_ids(entity)
        nodes.append(
            {
                **_base(row, observed, "AttackPathNode"),
                "id": node_id,
                "name": _first_text(
                    entity.get("displayName"),
                    entity.get("name"),
                    internal_id,
                ),
                "displayName": _first_text(
                    entity.get("displayName"),
                    entity.get("name"),
                    internal_id,
                ),
                "attackPathId": path_id,
                "internalId": internal_id,
                "nodeType": _first_text(
                    entity.get("entityType"),
                    entity.get("type"),
                    "Unknown",
                ),
                "resourceId": resource_ids[0] if resource_ids else "",
                "resolved": bool(resource_ids),
                "properties": dict(entity),
            }
        )

    connections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_connections):
        connection = _mapping(raw)
        source_internal = _first_text(
            connection.get("sourceEntityInternalId"),
            connection.get("source"),
            connection.get("from"),
        )
        target_internal = _first_text(
            connection.get("targetEntityInternalId"),
            connection.get("target"),
            connection.get("to"),
        )
        connection_id = f"{path_id}|connection|{index}"
        connections.append(
            {
                **_base(row, observed, "AttackPathConnection"),
                "id": connection_id,
                "name": _first_text(
                    connection.get("displayName"),
                    connection.get("type"),
                    f"Connection {index + 1}",
                ),
                "displayName": _first_text(
                    connection.get("displayName"),
                    connection.get("type"),
                    f"Connection {index + 1}",
                ),
                "attackPathId": path_id,
                "sourceNodeId": internal_to_node.get(
                    source_internal.casefold(), ""
                ),
                "targetNodeId": internal_to_node.get(
                    target_internal.casefold(), ""
                ),
                "connectionType": _first_text(
                    connection.get("type"),
                    connection.get("displayName"),
                    "Unknown",
                ),
                "properties": dict(connection),
            }
        )

    entry_internal = _text(properties.get("entryPointEntityInternalID"))
    target_internal = _text(properties.get("targetEntityInternalID"))
    resource_ids = _resource_ids(properties, raw_entities)
    path = {
        **_base(row, observed, "AttackPath"),
        "id": path_id,
        "title": _first_text(properties.get("displayName"), row.get("name")),
        "displayName": _first_text(properties.get("displayName"), row.get("name")),
        "description": _text(properties.get("description")),
        "attackPathType": _text(properties.get("attackPathType")),
        "potentialImpact": _text(properties.get("potentialImpact")),
        "riskCategories": _text_list(properties.get("riskCategories")),
        "manualRemediationSteps": _text_list(
            properties.get("manualRemediationSteps")
        ),
        "entryPointNodeId": internal_to_node.get(entry_internal.casefold(), ""),
        "targetNodeId": internal_to_node.get(target_internal.casefold(), ""),
        "resourceIds": list(resource_ids),
        "assessmentIds": _assessment_ids(
            properties.get("assessments"), _text(row.get("subscriptionId"))
        ),
        "nodeCount": len(nodes),
        "connectionCount": len(connections),
    }
    return path, nodes, connections


def normalize_secure_score(
    row: Mapping[str, Any], observed: str
) -> dict[str, Any] | None:
    """Return a temporal secure-score snapshot for a subscription."""
    properties = _mapping(row.get("properties"))
    score = _mapping(properties.get("score"))
    source_id = _text(row.get("id")).casefold()
    subscription_id = _text(row.get("subscriptionId"))
    if not source_id or not subscription_id:
        return None
    current = _number(score.get("current"))
    maximum = _number(score.get("max"))
    percentage = _number(score.get("percentage"))
    if not percentage and maximum > 0:
        percentage = current / maximum
    elif 1 < percentage <= 100:
        percentage /= 100
    return {
        **_base(row, observed, "SecureScoreSnapshot"),
        "id": f"{source_id}|{observed}",
        "sourceId": source_id,
        "subscriptionResourceId": f"/subscriptions/{subscription_id}".casefold(),
        "currentScore": current,
        "maxScore": maximum,
        "percentage": percentage,
        "weight": _number(properties.get("weight")),
        "observedAt": observed,
    }


def normalize_secure_score_control(
    row: Mapping[str, Any], observed: str
) -> dict[str, Any] | None:
    """Return one secure-score control with its unhealthy-resource counts."""
    properties = _mapping(row.get("properties"))
    score = _mapping(properties.get("score"))
    control_id = _text(row.get("id")).casefold()
    if not control_id:
        return None
    score_source_id = control_id.split("/securescorecontrols/", 1)[0]
    return {
        **_base(row, observed, "SecureScoreControl"),
        "id": control_id,
        "secureScoreSourceId": score_source_id,
        "title": _first_text(properties.get("displayName"), row.get("name")),
        "displayName": _first_text(properties.get("displayName"), row.get("name")),
        "currentScore": _number(score.get("current")),
        "maxScore": _number(score.get("max")),
        "percentage": _percentage(
            score,
            current=_number(score.get("current")),
            maximum=_number(score.get("max")),
        ),
        "weight": _number(properties.get("weight")),
        "healthyResourceCount": _integer(properties.get("healthyResourceCount")),
        "unhealthyResourceCount": _integer(
            properties.get("unhealthyResourceCount")
        ),
        "notApplicableResourceCount": _integer(
            properties.get("notApplicableResourceCount")
        ),
        "assessmentDefinitions": _assessment_ids(
            properties.get("assessmentDefinitions"),
            _text(row.get("subscriptionId")),
        ),
    }


def _base(
    row: Mapping[str, Any], observed: str, entity_type: str
) -> dict[str, Any]:
    source_id = _text(row.get("id"))
    name = _text(row.get("name")) or source_id.rsplit("/", 1)[-1]
    return {
        "id": source_id.casefold(),
        "name": name,
        "displayName": name,
        "entityType": entity_type,
        "tenantId": _text(row.get("tenantId")),
        "subscriptionId": _text(row.get("subscriptionId")),
        "sourceSystem": "arg:SecurityResources",
        "sourceId": source_id,
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "schemaVersion": "1.0.0",
    }


def _target_resource_id(properties: Mapping[str, Any]) -> str:
    details = _mapping(properties.get("resourceDetails"))
    return _first_text(
        details.get("id"),
        details.get("Id"),
        details.get("nativeResourceId"),
        properties.get("resourceId"),
    ).casefold()


def _status(properties: Mapping[str, Any]) -> str:
    status = properties.get("status")
    if isinstance(status, Mapping):
        return _first_text(status.get("code"), status.get("status"))
    return _text(status)


def _severity(properties: Mapping[str, Any]) -> str:
    status = _mapping(properties.get("status"))
    additional = _mapping(properties.get("additionalData"))
    return _first_text(
        additional.get("severity"),
        status.get("severity"),
        properties.get("severity"),
        "Unknown",
    )


def _cve_ids(properties: Mapping[str, Any]) -> tuple[str, ...]:
    additional = _mapping(properties.get("additionalData"))
    values: list[Any] = [
        additional.get("cveId"),
        properties.get("cveId"),
        additional.get("cve"),
    ]
    found: set[str] = set()
    for value in values:
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            candidate = (
                _first_text(item.get("title"), item.get("id"), item.get("cveId"))
                if isinstance(item, Mapping)
                else _text(item)
            )
            found.update(match.upper() for match in _CVE_PATTERN.findall(candidate))
    return tuple(sorted(found))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    return next((_text(value) for value in values if _text(value)), "")


def _text_list(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    return [_text(item) for item in items if _text(item)]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _percentage(score: Mapping[str, Any], *, current: float, maximum: float) -> float:
    value = _number(score.get("percentage"))
    if not value and maximum > 0:
        return current / maximum
    return value / 100 if 1 < value <= 100 else value


def _resource_ids(*values: Any) -> tuple[str, ...]:
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key).casefold() in {
                    "azureresourceid",
                    "resourceid",
                    "resource_id",
                }:
                    candidate = _text(nested)
                    if candidate.casefold().startswith("/subscriptions/"):
                        found.add(candidate.casefold())
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value.casefold().startswith(
            "/subscriptions/"
        ):
            found.add(value.casefold())

    for value in values:
        visit(value)
    return tuple(sorted(found))


def _assessment_ids(value: Any, subscription_id: str) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    result: set[str] = set()
    for item in values:
        candidate = _first_text(
            _mapping(item).get("id") if isinstance(item, Mapping) else "",
            _mapping(item).get("assessmentId") if isinstance(item, Mapping) else "",
            item if isinstance(item, str) else "",
        )
        if not candidate:
            continue
        if candidate.casefold().startswith("/subscriptions/"):
            result.add(candidate.casefold())
        elif subscription_id:
            result.add(
                (
                    f"/subscriptions/{subscription_id}/providers/"
                    f"microsoft.security/assessments/{candidate}"
                ).casefold()
            )
    return sorted(result)
