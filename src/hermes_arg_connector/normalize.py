from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .network_normalize import NETWORK_ENTITY_TYPES as _NETWORK_ENTITY_TYPES
from .network_normalize import (
    normalize_firewall,
    normalize_firewall_policy,
    normalize_gateway,
    normalize_load_balancer,
    normalize_nic,
    normalize_nsg,
    normalize_private_dns_zone,
    normalize_private_endpoint,
    normalize_route_table,
    normalize_vnet,
    private_dns_link_target,
)

#: Gateway and load-balancer families share one entity bucket each; the
#: specific kind (VpnGateway, Bastion, ApplicationGateway, ...) is carried on
#: the ``entityType`` field of the row.
ENTITY_TYPES = (
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "PatchAssessment",
    "PatchAssessmentDetail",
    "PatchInstallation",
    "AdvisorRecommendation",
    *_NETWORK_ENTITY_TYPES,
)


@dataclass
class NormalizedGraph:
    entities: dict[str, list[dict]] = field(default_factory=lambda: {name: [] for name in ENTITY_TYPES})
    relationships: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)


class Normalizer:
    """Normalizes raw ARG payloads into canonical entity/relationship rows.

    ``connection_context`` carries subscription-connection identity (for example
    ``connection_id`` and ``connection_name``) onto every emitted entity so the
    ontology layer can attribute ingested data to the connection that produced it.
    """

    def __init__(self, connection_context: Mapping[str, str] | None = None) -> None:
        self.connection_context = {
            str(key): str(value)
            for key, value in dict(connection_context or {}).items()
            if str(value or "").strip()
        }

    def normalize(self, payload: dict[str, list[dict]], observed_at: datetime) -> NormalizedGraph:
        observed = _iso(observed_at)
        context = self.connection_context
        graph = NormalizedGraph()
        entity_index: dict[str, dict[str, dict]] = {name: {} for name in ENTITY_TYPES}
        edge_index: dict[str, dict] = {}

        for row in [
            *payload.get("resource_containers", []),
            *payload.get("management_groups", []),
        ]:
            resource_type = _lower(row.get("type"))
            if resource_type == "microsoft.resources/subscriptions":
                entity = _subscription(row, observed)
                entity_index["Subscription"][entity["id"]] = entity
            elif resource_type == "microsoft.management/managementgroups":
                entity = _management_group(row, observed)
                entity_index["ManagementGroup"][entity["id"]] = entity
            elif resource_type == "microsoft.resources/subscriptions/resourcegroups":
                entity = _resource_group(row, observed)
                entity_index["ResourceGroup"][entity["id"]] = entity
                subscription_id = _subscription_key(row)
                _add_edge(edge_index, entity["id"], "belongsTo", subscription_id, "arg:ResourceContainers", observed, 1.0)

        for row in payload.get("resources", []):
            entity_type = _entity_type_for_resource(row)
            entity = _resource(row, observed, entity_type)
            entity_index[entity_type][entity["id"]] = entity
            rg_id = _resource_group_key(row)
            if rg_id:
                _add_edge(edge_index, entity["id"], "belongsTo", rg_id, "arg:Resources", observed, 1.0)
            else:
                _add_edge(edge_index, entity["id"], "belongsTo", _subscription_key(row), "arg:Resources", observed, 1.0)

        for row in payload.get("patch_assessments", []):
            entity = _patch_assessment(row, observed)
            entity_index["PatchAssessment"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(edge_index, target, "assessedBy", entity["id"], "arg:PatchAssessmentResources", observed, 0.98)

        for row in payload.get("patch_assessment_details", []):
            entity = _patch_assessment_detail(row, observed)
            entity_index["PatchAssessmentDetail"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(
                    edge_index,
                    target,
                    "hasMissingPatch",
                    entity["id"],
                    "arg:PatchAssessmentResources",
                    observed,
                    0.98,
                )

        for row in payload.get("patch_installations", []):
            entity = _patch_installation(row, observed)
            entity_index["PatchInstallation"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(
                    edge_index,
                    target,
                    "hasPatchInstallation",
                    entity["id"],
                    "arg:PatchInstallationResources",
                    observed,
                    0.98,
                )

        for row in payload.get("advisor_recommendations", []):
            entity = _advisor(row, observed)
            entity_index["AdvisorRecommendation"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(edge_index, entity["id"], "impacts", target, "arg:AdvisorResources", observed, 0.98)

        graph.changes = [_change(row, observed) for row in payload.get("resource_changes", [])]
        self._normalize_network(payload, observed, entity_index, edge_index)
        if context:
            for entity_type in ENTITY_TYPES:
                for entity in entity_index[entity_type].values():
                    entity.update(context)
            for change in graph.changes:
                change.update(context)
        for entity_type in ENTITY_TYPES:
            graph.entities[entity_type] = sorted(entity_index[entity_type].values(), key=lambda item: item["id"])
        known_entity_ids = {
            entity["id"]
            for entities in graph.entities.values()
            for entity in entities
        }
        graph.relationships = sorted(
            (
                edge
                for edge in edge_index.values()
                if edge["subjectId"] in known_entity_ids and edge["objectId"] in known_entity_ids
            ),
            key=lambda item: item["relationshipId"],
        )
        return graph


    def _normalize_network(
        self,
        payload: dict[str, list[dict]],
        observed: str,
        entity_index: dict[str, dict[str, dict]],
        edge_index: dict[str, dict],
    ) -> None:
        """Flattens network payloads into entities plus topology edges.

        Sub-resources (subnets, rules, routes, peerings) become first-class
        entities because ``_add_edge`` drops any edge whose endpoints are not
        emitted, and topology analysis needs to address them individually.
        """
        source = "arg:Resources"

        def record(entity_type: str, entity: dict) -> None:
            entity_index[entity_type][entity["id"]] = entity

        def link(subject: str, predicate: str, obj: str, confidence: float = 1.0) -> None:
            _add_edge(edge_index, subject, predicate, obj, source, observed, confidence)

        def containment(row: dict, entity: dict) -> None:
            """Anchors an entity to its resource group / subscription."""
            parent = _resource_group_key(row) or _subscription_key(row)
            link(entity["id"], "belongsTo", parent)

        for row in payload.get("network_vnets", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            vnet, subnets, peerings = normalize_vnet(base, row, observed)
            record("VNet", vnet)
            containment(row, vnet)
            for subnet in subnets:
                record("Subnet", subnet)
                link(vnet["id"], "contains", subnet["id"])
                if subnet.get("nsgId"):
                    link(subnet["id"], "protectedBy", subnet["nsgId"], 0.99)
                if subnet.get("routeTableId"):
                    link(subnet["id"], "routedBy", subnet["routeTableId"], 0.99)
                if subnet.get("natGatewayId"):
                    link(subnet["id"], "egressesVia", subnet["natGatewayId"], 0.99)
            for peering in peerings:
                record("VNetPeering", peering)
                link(vnet["id"], "hasPeering", peering["id"])
                if peering.get("remoteVnetId"):
                    link(peering["id"], "peersWith", peering["remoteVnetId"], 0.99)

        for row in payload.get("network_security_groups", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            nsg, rules = normalize_nsg(base, row, observed)
            record("NetworkSecurityGroup", nsg)
            containment(row, nsg)
            for rule in rules:
                record("NetworkSecurityRule", rule)
                link(nsg["id"], "hasRule", rule["id"])

        for row in payload.get("network_route_tables", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            table, routes = normalize_route_table(base, row, observed)
            record("RouteTable", table)
            containment(row, table)
            for route in routes:
                record("Route", route)
                link(table["id"], "hasRoute", route["id"])

        for row in payload.get("network_interfaces", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            nic = normalize_nic(base, row, observed)
            record("NetworkInterface", nic)
            containment(row, nic)
            if nic.get("subnetId"):
                link(nic["id"], "attachedTo", nic["subnetId"], 0.99)
            if nic.get("nsgId"):
                link(nic["id"], "protectedBy", nic["nsgId"], 0.99)
            if nic.get("attachedResourceId"):
                link(nic["attachedResourceId"], "hasNetworkInterface", nic["id"], 0.99)

        for row in payload.get("network_firewalls", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            firewall = normalize_firewall(base, row, observed)
            record("AzureFirewall", firewall)
            containment(row, firewall)
            if firewall.get("subnetId"):
                link(firewall["id"], "attachedTo", firewall["subnetId"], 0.99)
            if firewall.get("policyId"):
                link(firewall["id"], "enforcesPolicy", firewall["policyId"], 0.99)

        for row in payload.get("network_firewall_policies", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            policy, collections, rules = normalize_firewall_policy(base, row, observed)
            if policy is not None:
                record("FirewallPolicy", policy)
                containment(row, policy)
            for collection in collections:
                record("FirewallRuleCollection", collection)
                link(collection["policyId"], "hasRuleCollection", collection["id"], 0.99)
            for rule in rules:
                record("FirewallRule", rule)
                link(rule["collectionId"], "hasRule", rule["id"])

        for row in payload.get("network_private_endpoints", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            endpoint = normalize_private_endpoint(base, row, observed)
            record("PrivateEndpoint", endpoint)
            containment(row, endpoint)
            if endpoint.get("subnetId"):
                link(endpoint["id"], "attachedTo", endpoint["subnetId"], 0.99)
            if endpoint.get("targetResourceId"):
                link(endpoint["id"], "exposesPrivately", endpoint["targetResourceId"], 0.98)

        dns_zones: dict[str, dict] = {}
        dns_links: list[tuple[str, str]] = []
        for row in payload.get("network_private_dns_zones", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            zone = normalize_private_dns_zone(base, row, observed)
            if zone is None:
                zone_id, vnet_id = private_dns_link_target(row)
                if zone_id and vnet_id:
                    dns_links.append((zone_id, vnet_id))
                continue
            dns_zones[zone["id"]] = zone
            containment(row, zone)
        for zone_id, vnet_id in dns_links:
            zone = dns_zones.get(zone_id)
            if zone is not None and vnet_id not in zone["linkedVnetIds"]:
                zone["linkedVnetIds"].append(vnet_id)
            link(zone_id, "resolvesFor", vnet_id, 0.98)
        for zone in dns_zones.values():
            record("PrivateDnsZone", zone)

        for row in payload.get("network_gateways", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            gateway = normalize_gateway(base, row, observed)
            record("NetworkGateway", gateway)
            containment(row, gateway)
            if gateway.get("subnetId"):
                link(gateway["id"], "attachedTo", gateway["subnetId"], 0.99)
            elif gateway.get("vnetId"):
                link(gateway["id"], "attachedTo", gateway["vnetId"], 0.95)

        for row in payload.get("network_load_balancers", []):
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            balancer = normalize_load_balancer(base, row, observed)
            record("LoadBalancer", balancer)
            containment(row, balancer)
            if balancer.get("subnetId"):
                link(balancer["id"], "attachedTo", balancer["subnetId"], 0.99)
            for backend in balancer.get("backendResourceIds", []):
                link(balancer["id"], "loadBalances", backend, 0.9)


def _base(row: dict, observed: str, source: str) -> dict:
    source_id = _lower(row.get("id")) or _lower(row.get("name"))
    display_name = str(row.get("name") or source_id.rsplit("/", 1)[-1])
    return {
        "id": source_id,
        "name": display_name,
        "displayName": display_name,
        "tenantId": str(row.get("tenantId") or ""),
        "subscriptionId": str(row.get("subscriptionId") or ""),
        "sourceSystem": source,
        "sourceId": str(row.get("id") or row.get("name") or ""),
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "schemaVersion": "1.0.0",
    }


def _subscription(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:ResourceContainers")
    entity["id"] = _subscription_key(row)
    entity["state"] = str((row.get("properties") or {}).get("state") or "")
    entity["managementGroupAncestorsChain"] = (
        (row.get("properties") or {}).get("managementGroupAncestorsChain") or []
    )
    entity["tags"] = row.get("tags") or {}
    return entity


def _management_group(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:ResourceContainers")
    entity["resourceType"] = "microsoft.management/managementgroups"
    entity["properties"] = row.get("properties") or {}
    entity["tags"] = row.get("tags") or {}
    return entity


def _resource_group(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:ResourceContainers")
    entity.update({"id": _resource_group_key(row), "location": str(row.get("location") or ""), "tags": row.get("tags") or {}})
    return entity


def _resource(row: dict, observed: str, entity_type: str) -> dict:
    entity = _base(row, observed, "arg:Resources")
    props = row.get("properties") or {}
    entity.update({
        "entityType": entity_type,
        "resourceType": _lower(row.get("type")),
        "resourceGroup": str(row.get("resourceGroup") or ""),
        "location": str(row.get("location") or ""),
        "tags": row.get("tags") or {},
        "properties": props,
    })
    if entity_type == "VirtualMachine":
        entity["vmSize"] = str((props.get("hardwareProfile") or {}).get("vmSize") or "")
        entity["osType"] = str(((props.get("storageProfile") or {}).get("osDisk") or {}).get("osType") or "")
    elif entity_type == "ArcServer":
        entity["status"] = str(props.get("status") or "")
        entity["osName"] = str(props.get("osName") or "")
        entity["osVersion"] = str(props.get("osVersion") or "")
    return entity


def _patch_assessment(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:PatchAssessmentResources")
    props = row.get("properties") or {}
    target = _lower(props.get("resourceId") or props.get("machineId") or _target_from_assessment_id(row.get("id")))
    entity.update({
        "targetResourceId": target,
        "status": str(props.get("status") or props.get("assessmentState") or "unknown"),
        "availablePatchCountByClassification": props.get("availablePatchCountByClassification") or {},
        "errorDetails": props.get("errorDetails") or [],
        "lastModifiedDateTime": str(props.get("lastModifiedDateTime") or ""),
        "properties": props,
    })
    return entity


def _patch_assessment_detail(row: dict, observed: str) -> dict:
    """Per-KB pending/missing patch detail (the ``/softwarepatches`` sub-type
    of ``patchassessmentresources``). This is the row shape that actually
    carries a KB id, MSRC severity, and classification per outstanding
    update -- the aggregate ``PatchAssessment`` entity only has counts."""
    entity = _base(row, observed, "arg:PatchAssessmentResources")
    props = row.get("properties") or {}
    classifications = props.get("classifications") or []
    target = _lower(
        props.get("resourceId")
        or props.get("machineId")
        or _target_from_assessment_id(row.get("id"))
    )
    entity.update(
        {
            "targetResourceId": target,
            "updateName": str(props.get("patchName") or row.get("name") or ""),
            "kbId": str(props.get("kbId") or row.get("name") or ""),
            "classifications": classifications
            if isinstance(classifications, list)
            else [str(classifications)],
            "msrcSeverity": str(props.get("msrcSeverity") or ""),
            "rebootBehavior": str(props.get("rebootBehavior") or ""),
            "publishedDateTime": str(props.get("publishedDateTime") or ""),
            "lastModifiedDateTime": str(props.get("lastModifiedDateTime") or ""),
            "properties": props,
        }
    )
    return entity


def _patch_installation(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:PatchInstallationResources")
    props = row.get("properties") or {}
    classifications = props.get("classifications") or []
    target = _lower(
        props.get("resourceId")
        or props.get("machineId")
        or _target_from_installation_id(row.get("id"))
    )
    entity.update(
        {
            "targetResourceId": target,
            "updateName": str(props.get("patchName") or row.get("name") or ""),
            "kbId": str(props.get("kbId") or row.get("name") or ""),
            "classifications": classifications
            if isinstance(classifications, list)
            else [str(classifications)],
            "status": str(
                props.get("installationState") or props.get("status") or "unknown"
            ),
            "publishedDateTime": str(props.get("publishedDateTime") or ""),
            "lastModifiedDateTime": str(props.get("lastModifiedDateTime") or ""),
            "errorDetails": props.get("errorDetails") or [],
            "properties": props,
        }
    )
    return entity


def _advisor(row: dict, observed: str) -> dict:
    entity = _base(row, observed, "arg:AdvisorResources")
    props = row.get("properties") or {}
    short = props.get("shortDescription") or {}
    target = _lower((props.get("resourceMetadata") or {}).get("resourceId") or props.get("resourceId"))
    entity.update({
        "category": str(props.get("category") or ""),
        "impact": str(props.get("impact") or ""),
        "problem": str(short.get("problem") or ""),
        "solution": str(short.get("solution") or ""),
        "targetResourceId": target,
        "properties": props,
    })
    return entity


def _change(row: dict, observed: str) -> dict:
    props = row.get("properties") or {}
    attrs = props.get("changeAttributes") or {}
    return {
        "id": _lower(row.get("id") or row.get("name")),
        "targetResourceId": _lower(props.get("targetResourceId")),
        "changeType": str(props.get("changeType") or ""),
        "changedAt": str(attrs.get("timestamp") or ""),
        "properties": props,
        "sourceSystem": "arg:ResourceChanges",
        "lastObservedTimestamp": observed,
    }


def _entity_type_for_resource(row: dict) -> str:
    resource_type = _lower(row.get("type"))
    if resource_type == "microsoft.compute/virtualmachines":
        return "VirtualMachine"
    if resource_type == "microsoft.hybridcompute/machines":
        return "ArcServer"
    return "Resource"


def _subscription_key(row: dict) -> str:
    subscription = str(row.get("subscriptionId") or _subscription_from_id(row.get("id")) or "unknown").lower()
    return f"/subscriptions/{subscription}"


def _resource_group_key(row: dict) -> str:
    source_id = _lower(row.get("id"))
    if "/resourcegroups/" in source_id:
        parts = source_id.split("/providers/", 1)[0]
        return parts
    subscription = str(row.get("subscriptionId") or "")
    group = str(row.get("resourceGroup") or row.get("name") or "")
    if subscription and group:
        return f"/subscriptions/{subscription}/resourcegroups/{group}".lower()
    return ""


def _subscription_from_id(value: Any) -> str:
    parts = str(value or "").split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        return ""


def _target_from_assessment_id(value: Any) -> str:
    text = str(value or "")
    lower = text.lower()
    for marker in ("/patchassessmentresults/", "/providers/microsoft.patchassessment/"):
        if marker in lower:
            return text[: lower.index(marker)]
    return ""


def _target_from_installation_id(value: Any) -> str:
    text = str(value or "")
    lower = text.casefold()
    marker = "/patchinstallationresults/"
    return text[: lower.index(marker)] if marker in lower else ""


def _add_edge(index: dict[str, dict], subject: str, predicate: str, obj: str, source: str, observed: str, confidence: float) -> None:
    if not subject or not obj:
        return
    digest = hashlib.sha256(f"{subject}|{predicate}|{obj}|{source}".encode()).hexdigest()[:24]
    index[digest] = {
        "relationshipId": digest,
        "subjectId": subject,
        "predicate": predicate,
        "objectId": obj,
        "confidence": confidence,
        "source": source,
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "assertionState": "accepted",
        "schemaVersion": "1.0.0",
    }


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
