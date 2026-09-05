from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from intelligence.vulnerability.normalization import normalize_aum_row
from ontology.confidence import compute_confidence

from .defender_normalize import (
    is_container_image_assessment,
    normalize_assessment,
    normalize_attack_path,
    normalize_container_image_exposure,
    normalize_secure_score,
    normalize_secure_score_control,
    normalize_security_alert,
    normalize_vulnerability_subassessments,
)
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
    private_endpoint_dns_zone_ids,
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
    "CostActual",
    "RoleAssignment",
    "RoleDefinition",
    "ManagedIdentity",
    "DefenderAssessment",
    "DefenderVulnerabilityFinding",
    "ContainerImageExposure",
    "SecurityAlert",
    "AttackPath",
    "AttackPathNode",
    "AttackPathConnection",
    "SecureScoreSnapshot",
    "SecureScoreControl",
    *_NETWORK_ENTITY_TYPES,
)


@dataclass
class NormalizedGraph:
    entities: dict[str, list[dict]] = field(default_factory=lambda: {name: [] for name in ENTITY_TYPES})
    relationships: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    # Phase 1 projections are carried alongside the established graph so the
    # immutable generation remains the single publication path.
    situations: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    audit_events: list[dict] = field(default_factory=list)
    source_status: list[dict] = field(default_factory=list)
    # Incremental-discovery support (opt-in): a stable content hash per input
    # resource id, keyed the same way as ``entities``/``changes`` above. A
    # caller (e.g. ConnectionSyncCoordinator/an ingestion pipeline) MAY
    # persist this dict and pass it back in as ``previous_row_hashes`` on the
    # next ``Normalizer.normalize()`` call to compute which resources
    # actually changed since the last sync via ``changed_resource_ids``.
    row_hashes: dict[str, str] = field(default_factory=dict)


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

    def normalize(
        self,
        payload: dict[str, list[dict]],
        observed_at: datetime,
        *,
        run_id: str = "normalization",
        requested_scope: dict[str, list[str]] | None = None,
        previous_row_hashes: dict[str, str] | None = None,
    ) -> NormalizedGraph:
        observed = _iso(observed_at)
        context = self.connection_context
        graph = NormalizedGraph()
        entity_index: dict[str, dict[str, dict]] = {name: {} for name in ENTITY_TYPES}
        edge_index: dict[str, dict] = {}
        # Incremental discovery (opt-in): hash every top-level resource row
        # by its own id so callers can diff this run's hashes against
        # ``previous_row_hashes`` (via ``changed_resource_ids``) without
        # forcing a change to how the rest of normalize() runs -- every row
        # is still fully normalized and included in the graph below, exactly
        # as before, regardless of whether its hash matched.
        previous_row_hashes = previous_row_hashes or {}
        for row in payload.get("resources", []):
            resource_id = _lower(row.get("id"))
            if resource_id:
                graph.row_hashes[resource_id] = _row_hash(row)

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
                _add_edge(edge_index, entity["id"], "belongsTo", subscription_id, "arg:ResourceContainers", observed, compute_confidence("arg:ResourceContainers"))

        for row in payload.get("resources", []):
            entity_type = _entity_type_for_resource(row)
            entity = _resource(row, observed, entity_type)
            entity_index[entity_type][entity["id"]] = entity
            rg_id = _resource_group_key(row)
            if rg_id:
                _add_edge(edge_index, entity["id"], "belongsTo", rg_id, "arg:Resources", observed, compute_confidence("arg:Resources"))
            else:
                _add_edge(edge_index, entity["id"], "belongsTo", _subscription_key(row), "arg:Resources", observed, compute_confidence("arg:Resources"))

        for row in payload.get("patch_assessments", []):
            entity = _patch_assessment(row, observed)
            entity_index["PatchAssessment"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(edge_index, target, "assessedBy", entity["id"], "arg:PatchAssessmentResources", observed, compute_confidence("arg:PatchAssessmentResources"))

        for row in payload.get("patch_assessment_details", []):
            entity = _patch_assessment_detail(row, observed)
            if entity is None:
                continue
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
                    compute_confidence("arg:PatchAssessmentResources"),
                )

        for row in payload.get("patch_installations", []):
            entity = _patch_installation(row, observed)
            if entity is None:
                continue
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
                    compute_confidence("arg:PatchInstallationResources"),
                )

        for row in payload.get("advisor_recommendations", []):
            entity = _advisor(row, observed)
            entity_index["AdvisorRecommendation"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(edge_index, entity["id"], "impacts", target, "arg:AdvisorResources", observed, compute_confidence("arg:AdvisorResources"))

        image_assessments: list[Mapping[str, Any]] = []
        for row in payload.get("defender_assessments", []):
            # Container image package findings are rolled up per image below;
            # carrying them individually buries infrastructure findings under
            # tens of thousands of per-package rows.
            if is_container_image_assessment(row):
                image_assessments.append(row)
                continue
            entity = normalize_assessment(row, observed)
            if entity is None:
                continue
            entity_index["DefenderAssessment"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(
                    edge_index,
                    entity["id"],
                    "impacts",
                    target,
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )

        for entity in normalize_container_image_exposure(image_assessments, observed):
            entity_index["ContainerImageExposure"][entity["id"]] = entity
            registry = entity.get("registryResourceId", "")
            if registry:
                _add_edge(
                    edge_index,
                    entity["id"],
                    "impacts",
                    registry,
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )

        for row in payload.get("defender_subassessments", []):
            for entity in normalize_vulnerability_subassessments(row, observed):
                entity_index["DefenderVulnerabilityFinding"][entity["id"]] = entity
                target = entity.get("targetResourceId", "")
                if target:
                    _add_edge(
                        edge_index,
                        target,
                        "hasVulnerability",
                        entity["id"],
                        "arg:SecurityResources",
                        observed,
                        compute_confidence("arg:SecurityResources"),
                    )
                assessment_id = entity.get("assessmentId", "")
                if assessment_id:
                    _add_edge(
                        edge_index,
                        entity["id"],
                        "derivedFrom",
                        assessment_id,
                        "arg:SecurityResources",
                        observed,
                        compute_confidence("arg:SecurityResources"),
                    )

        for row in payload.get("defender_alerts", []):
            entity = normalize_security_alert(row, observed)
            if entity is None:
                continue
            entity_index["SecurityAlert"][entity["id"]] = entity
            for resource_id in entity.get("resourceIds", []):
                _add_edge(
                    edge_index,
                    entity["id"],
                    "affects",
                    resource_id,
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )

        for row in payload.get("defender_attack_paths", []):
            path, nodes, connections = normalize_attack_path(row, observed)
            if path is None:
                continue
            entity_index["AttackPath"][path["id"]] = path
            for node in nodes:
                entity_index["AttackPathNode"][node["id"]] = node
                _add_edge(
                    edge_index,
                    path["id"],
                    "traverses",
                    node["id"],
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
                if node.get("resourceId"):
                    _add_edge(
                        edge_index,
                        node["id"],
                        "resolvesTo",
                        node["resourceId"],
                        "arg:SecurityResources",
                        observed,
                        compute_confidence("arg:SecurityResources"),
                    )
            if path.get("entryPointNodeId"):
                _add_edge(
                    edge_index,
                    path["id"],
                    "startsAt",
                    path["entryPointNodeId"],
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
            if path.get("targetNodeId"):
                _add_edge(
                    edge_index,
                    path["id"],
                    "targets",
                    path["targetNodeId"],
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
            for assessment_id in path.get("assessmentIds", []):
                _add_edge(
                    edge_index,
                    path["id"],
                    "supportedBy",
                    assessment_id,
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
            for connection in connections:
                entity_index["AttackPathConnection"][connection["id"]] = connection
                _add_edge(
                    edge_index,
                    path["id"],
                    "contains",
                    connection["id"],
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
                for predicate, endpoint in (
                    ("connectsFrom", connection.get("sourceNodeId")),
                    ("connectsTo", connection.get("targetNodeId")),
                ):
                    if endpoint:
                        _add_edge(
                            edge_index,
                            connection["id"],
                            predicate,
                            endpoint,
                            "arg:SecurityResources",
                            observed,
                            compute_confidence("arg:SecurityResources"),
                        )

        secure_score_snapshots: dict[str, str] = {}
        for row in payload.get("defender_secure_scores", []):
            entity = normalize_secure_score(row, observed)
            if entity is None:
                continue
            entity_index["SecureScoreSnapshot"][entity["id"]] = entity
            secure_score_snapshots[entity["sourceId"]] = entity["id"]
            _add_edge(
                edge_index,
                entity["subscriptionResourceId"],
                "hasSecureScore",
                entity["id"],
                "arg:SecurityResources",
                observed,
                compute_confidence("arg:SecurityResources"),
            )

        for row in payload.get("defender_secure_score_controls", []):
            entity = normalize_secure_score_control(row, observed)
            if entity is None:
                continue
            entity_index["SecureScoreControl"][entity["id"]] = entity
            snapshot_id = secure_score_snapshots.get(
                entity.get("secureScoreSourceId", "")
            )
            if snapshot_id:
                _add_edge(
                    edge_index,
                    snapshot_id,
                    "composedOf",
                    entity["id"],
                    "arg:SecurityResources",
                    observed,
                    compute_confidence("arg:SecurityResources"),
                )
            for assessment_id in entity.get("assessmentDefinitions", []):
                assessment_key = assessment_id.casefold()
                if assessment_key.startswith("/subscriptions/"):
                    _add_edge(
                        edge_index,
                        entity["id"],
                        "improvedBy",
                        assessment_key,
                        "arg:SecurityResources",
                        observed,
                        compute_confidence("arg:SecurityResources"),
                    )

        for row in payload.get("cost_actuals", []):
            entity = _cost_actual(row, observed)
            entity_index["CostActual"][entity["id"]] = entity
            target = entity.get("targetResourceId", "")
            if target:
                _add_edge(
                    edge_index,
                    target,
                    "incursCost",
                    entity["id"],
                    "azure:CostManagement",
                    observed,
                    compute_confidence("azure:CostManagement"),
                )

        for row in payload.get("role_assignments", []):
            entity = _role_assignment(row, observed)
            entity_index["RoleAssignment"][entity["id"]] = entity
            # The assignment scope is the resource/RG/subscription the grant
            # applies to, which is what makes blast radius computable.
            target = entity.get("assignmentScope", "")
            if target:
                _add_edge(
                    edge_index,
                    entity["id"],
                    "grantsAccessTo",
                    target,
                    "arg:AuthorizationResources",
                    observed,
                    compute_confidence("arg:AuthorizationResources"),
                )

        for row in payload.get("role_definitions", []):
            entity = _role_definition(row, observed)
            entity_index["RoleDefinition"][entity["id"]] = entity

        for row in payload.get("managed_identities", []):
            entity = _managed_identity(row, observed)
            entity_index["ManagedIdentity"][entity["id"]] = entity
            rg_id = _resource_group_key(row)
            if rg_id:
                _add_edge(
                    edge_index,
                    entity["id"],
                    "belongsTo",
                    rg_id,
                    "arg:Resources",
                    observed,
                    1.0,
                )

        graph.changes = [
            _change(row, observed)
            for row in payload.get("resource_changes", [])
            if not _failed_provider_row(row)
        ]
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
        # Keep situation/evidence projections on the same normalized graph. The
        # optional import avoids coupling the legacy entity normalizer to the
        # API layer and preserves the single immutable publication path.
        from situations.materializer import materialize_graph, normalize_signal_families

        signal_payloads = dict(payload)
        if "arg_activity_log" not in signal_payloads and "arg" not in signal_payloads:
            signal_payloads["arg_activity_log"] = [
                {
                    "id": row.get("id"),
                    "resource_id": (row.get("properties") or {}).get("targetResourceId"),
                    "observed_at": ((row.get("properties") or {}).get("changeAttributes") or {}).get("timestamp") or observed,
                    "watermark": ((row.get("properties") or {}).get("changeAttributes") or {}).get("timestamp") or observed,
                    "assertion": (row.get("properties") or {}).get("changeType") or "resource changed",
                    "status": row.get("status"),
                }
                for row in payload.get("resource_changes", [])
            ]
        signal_evidence, source_statuses = normalize_signal_families(
            signal_payloads,
            run_id=run_id,
            ingested_at=observed,
            requested_scope=requested_scope,
        )
        from situations.models import SourceStatus

        for family in (
            "defender_assessments",
            "defender_subassessments",
            "defender_alerts",
            "defender_attack_paths",
            "defender_secure_scores",
            "defender_secure_score_controls",
        ):
            rows = payload.get(family, [])
            failed = next(
                (row for row in rows if _failed_provider_row(row)),
                None,
            )
            queried = family in payload
            source_statuses.append(
                SourceStatus(
                    source_family=family,
                    run_id=run_id,
                    status="failed" if failed else "succeeded",
                    observed_at=observed,
                    ingested_at=observed,
                    watermark="" if failed else observed if queried else "",
                    query_version=str(
                        (rows[0] if rows else {}).get("query_version") or "1.0.0"
                    ),
                    requested_scope=requested_scope or {},
                    provider_status=str(
                        (failed or {}).get("provider_status")
                        or (failed or {}).get("status")
                        or "ok"
                    ),
                    freshness="unknown" if failed or not queried else "fresh",
                    availability=(
                        "unavailable"
                        if failed
                        else "available"
                        if queried
                        else "unknown"
                    ),
                    quality=(
                        "degraded"
                        if failed
                        else "complete"
                        if queried
                        else "unknown"
                    ),
                    error=str((failed or {}).get("error") or ""),
                )
            )
        if payload.get("resource_changes") and "arg_activity_log" not in payload and "arg" not in payload:
            signal_evidence = [
                item for item in signal_evidence if item.source_family != "arg_activity_log"
            ]
        generated = materialize_graph(
            graph,
            run_id,
            ingested_at=observed,
            additional_evidence=signal_evidence,
            source_statuses=source_statuses,
        )
        graph.situations = generated["situations"]
        graph.evidence = generated["evidence"]
        graph.links = generated["links"]
        graph.audit_events = generated["audit_events"]
        graph.source_status = [status.to_dict() for status in source_statuses]
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
            _add_edge(edge_index, subject, predicate, obj, source, observed, compute_confidence(source, base=confidence))

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
            firewall, classic_collections, classic_rules = normalize_firewall(base, row, observed)
            record("AzureFirewall", firewall)
            containment(row, firewall)
            if firewall.get("subnetId"):
                link(firewall["id"], "attachedTo", firewall["subnetId"], 0.99)
            if firewall.get("policyId"):
                link(firewall["id"], "enforcesPolicy", firewall["policyId"], 0.99)
            for collection in classic_collections:
                record("FirewallRuleCollection", collection)
                link(firewall["id"], "hasRuleCollection", collection["id"], 0.99)
            for rule in classic_rules:
                record("FirewallRule", rule)
                link(rule["collectionId"], "hasRule", rule["id"])

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

        endpoint_rows = payload.get("network_private_endpoints", [])
        endpoint_zone_ids: dict[str, set[str]] = {}
        for row in endpoint_rows:
            if (
                _lower(row.get("type"))
                != "microsoft.network/privateendpoints/privatednszonegroups"
            ):
                continue
            child_id = _lower(row.get("id"))
            parent_id = child_id.split("/privatednszonegroups/", 1)[0]
            endpoint_zone_ids.setdefault(parent_id, set()).update(
                private_endpoint_dns_zone_ids(row)
            )

        for row in endpoint_rows:
            if _lower(row.get("type")) != "microsoft.network/privateendpoints":
                continue
            base = _base(row, observed, source)
            base["resourceType"] = _lower(row.get("type"))
            base["tags"] = row.get("tags") or {}
            endpoint = normalize_private_endpoint(base, row, observed)
            endpoint["privateDnsZoneIds"] = sorted(
                {
                    *endpoint["privateDnsZoneIds"],
                    *endpoint_zone_ids.get(endpoint["id"], set()),
                }
            )
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
            dns_links.extend(
                (zone["id"], vnet_id)
                for vnet_id in zone["linkedVnetIds"]
            )
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


def _patch_assessment_detail(row: dict, observed: str) -> dict | None:
    """Per-KB pending/missing patch detail (the ``/softwarepatches`` sub-type
    of ``patchassessmentresources``). This is the row shape that actually
    carries a KB id, MSRC severity, and classification per outstanding
    update -- the aggregate ``PatchAssessment`` entity only has counts."""
    entity = _base(row, observed, "arg:PatchAssessmentResources")
    normalized, _failure = normalize_aum_row(
        row,
        source_family="azure_update_manager_missing",
        observed_at=observed,
    )
    if normalized is None:
        return None
    props = row.get("properties") or {}
    entity.update(
        {
            "targetResourceId": normalized.target_id,
            "updateName": normalized.title,
            "kbId": normalized.source_weakness_id,
            "classifications": list(normalized.classifications),
            "sourceClassifications": list(normalized.source_classifications),
            "msrcSeverity": normalized.source_severity,
            "severity": normalized.severity,
            "sourceFamily": normalized.source_family,
            "provenance": normalized.provenance,
            "rebootBehavior": str(props.get("rebootBehavior") or ""),
            "publishedDateTime": str(props.get("publishedDateTime") or ""),
            "lastModifiedDateTime": normalized.observed_at,
            "properties": props,
        }
    )
    return entity


def _patch_installation(row: dict, observed: str) -> dict | None:
    entity = _base(row, observed, "arg:PatchInstallationResources")
    normalized, _failure = normalize_aum_row(
        row,
        source_family="azure_update_manager_installation",
        observed_at=observed,
    )
    if normalized is None:
        return None
    props = row.get("properties") or {}
    entity.update(
        {
            "targetResourceId": normalized.target_id,
            "updateName": normalized.title,
            "kbId": normalized.source_weakness_id,
            "classifications": list(normalized.classifications),
            "sourceClassifications": list(normalized.source_classifications),
            "msrcSeverity": normalized.source_severity,
            "severity": normalized.severity,
            "sourceFamily": normalized.source_family,
            "provenance": normalized.provenance,
            # Preserve the provider operation value for existing onboarding
            # consumers while carrying the conservative canonical state
            # separately for Exposure projection.
            "status": str(
                props.get("installationState") or props.get("status") or "unknown"
            ),
            "canonicalStatus": normalized.status,
            "publishedDateTime": str(props.get("publishedDateTime") or ""),
            "lastModifiedDateTime": normalized.observed_at,
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


def _cost_actual(row: dict, observed: str) -> dict:
    subscription_id = str(row.get("subscriptionId") or _subscription_from_id(row.get("resourceId")) or "")
    usage_date = str(row.get("usageDate") or "")
    resource_id = _lower(row.get("resourceId"))
    service_name = str(row.get("serviceName") or "")
    resource_group = str(row.get("resourceGroup") or "")
    source_key = resource_id or f"/subscriptions/{subscription_id}/cost/{service_name}/{resource_group}".lower()
    digest = hashlib.sha256(
        f"{subscription_id}|{usage_date}|{source_key}|{service_name}|{resource_group}".encode()
    ).hexdigest()[:24]
    entity = _base(
        {
            "id": f"costactual://{subscription_id}/{usage_date}/{digest}",
            "name": f"{usage_date} {service_name or resource_id or subscription_id}",
            "subscriptionId": subscription_id,
            "properties": row.get("properties") or {},
        },
        observed,
        "azure:CostManagement",
    )
    entity.update(
        {
            "usageDate": usage_date,
            "cost": _float(row.get("cost")),
            "currency": str(row.get("currency") or ""),
            "targetResourceId": resource_id,
            "resourceId": resource_id,
            "resourceGroup": resource_group,
            "serviceName": service_name,
            "billingPeriodStart": str(row.get("billingPeriodStart") or usage_date),
            "billingPeriodEnd": str(row.get("billingPeriodEnd") or usage_date),
            "sourceSystem": "azure:CostManagement",
            "properties": row.get("properties") or row,
        }
    )
    return entity


def _role_assignment(row: dict, observed: str) -> dict:
    """A single RBAC grant: who, what role, over which scope."""
    entity = _base(row, observed, "arg:AuthorizationResources")
    props = row.get("properties") or {}
    role_definition_id = _lower(props.get("roleDefinitionId"))
    entity.update(
        {
            "principalId": str(props.get("principalId") or ""),
            # principalType is "User", "Group", "ServicePrincipal", or
            # "ManagedIdentity" -- the axis identity risk reports on.
            "principalType": str(props.get("principalType") or ""),
            "roleDefinitionId": role_definition_id,
            "assignmentScope": _lower(props.get("scope")),
            "createdOn": str(props.get("createdOn") or ""),
            "updatedOn": str(props.get("updatedOn") or ""),
            "properties": props,
        }
    )
    return entity


def _role_definition(row: dict, observed: str) -> dict:
    """A role's name and permissions, used to classify a grant as privileged."""
    entity = _base(row, observed, "arg:AuthorizationResources")
    props = row.get("properties") or {}
    permissions = props.get("permissions")
    actions: list[str] = []
    if isinstance(permissions, list):
        for permission in permissions:
            if isinstance(permission, dict):
                actions.extend(str(action) for action in permission.get("actions") or ())
    role_name = str(props.get("roleName") or "")
    entity.update(
        {
            "roleName": role_name,
            "displayName": role_name or entity["displayName"],
            "roleType": str(props.get("type") or ""),
            "description": str(props.get("description") or ""),
            "actions": actions,
            "properties": props,
        }
    )
    return entity


def _managed_identity(row: dict, observed: str) -> dict:
    """A user-assigned managed identity."""
    entity = _base(row, observed, "arg:Resources")
    props = row.get("properties") or {}
    entity.update(
        {
            "principalId": str(props.get("principalId") or ""),
            "clientId": str(props.get("clientId") or ""),
            "location": str(row.get("location") or ""),
            "resourceGroup": str(row.get("resourceGroup") or ""),
            "tags": row.get("tags") or {},
            "properties": props,
        }
    )
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


def _row_hash(row: Mapping[str, Any]) -> str:
    """Stable sha256 hash of a raw input row, for incremental-discovery diffing.

    ``json.dumps(..., sort_keys=True)`` gives a canonical serialization
    regardless of the source dict's key ordering, so the same logical row
    always hashes the same way across syncs -- this is the "did this
    resource actually change" signal ``Normalizer.normalize()``'s optional
    ``previous_row_hashes``/``NormalizedGraph.row_hashes`` and the
    ``changed_resource_ids`` helper below are built on."""
    canonical = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def changed_resource_ids(
    previous_row_hashes: Mapping[str, str], row_hashes: Mapping[str, str]
) -> set[str]:
    """Diffs two ``NormalizedGraph.row_hashes``-shaped dicts.

    Returns the resource ids that are new or whose hash changed between
    ``previous_row_hashes`` and ``row_hashes`` -- i.e. exactly the resources
    a caller needs to re-derive/re-process, not the full set. Ids present in
    ``previous_row_hashes`` but missing from ``row_hashes`` (no longer
    observed this run) are intentionally NOT included -- that is a removal,
    a different concern from "changed", and is already handled by the
    existing retire/lifecycle logic elsewhere in the pipeline."""
    return {
        resource_id
        for resource_id, current_hash in row_hashes.items()
        if previous_row_hashes.get(resource_id) != current_hash
    }


def _float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if number != number else number  # noqa: PLR0124 - NaN check


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _failed_provider_row(row: Mapping[str, Any]) -> bool:
    return str(row.get("status") or "").casefold() in {"failed", "unavailable"}


def _source_statuses(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    observed_at: str,
    requested_scope: dict[str, list[str]] | None,
) -> list[dict[str, Any]]:
    from situations.models import SourceStatus

    failed = next((row for row in rows if _failed_provider_row(row)), None)
    timestamps = [
        str(
            row.get("changedAt")
            or row.get("observed_at")
            or row.get("watermark")
            or ((row.get("properties") or {}).get("changeAttributes") or {}).get("timestamp")
            or ""
        )
        for row in rows
        if not _failed_provider_row(row)
    ]
    watermark = max(timestamps, default="")
    status = SourceStatus(
        source_family="arg_activity_log",
        run_id=run_id,
        status="failed" if failed else "succeeded",
        observed_at=max(timestamps, default=observed_at),
        ingested_at=observed_at,
        watermark="" if failed else watermark,
        query_version=str((rows[0] if rows else {}).get("query_version") or "1.0.0"),
        requested_scope=requested_scope or {},
        provider_status=str((failed or {}).get("status") or "ok"),
        freshness="unknown" if failed else "fresh",
        availability="unavailable" if failed else "available",
        quality="degraded" if failed else "complete",
        error=str((failed or {}).get("error") or ""),
    )
    return [status.to_dict()]


def normalize_evidence_payloads(
    payloads: Mapping[str, list[dict[str, Any]]],
    *,
    run_id: str,
    ingested_at: datetime | str,
    requested_scope: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expose the common Phase 1 envelope at the established normalizer boundary."""
    from situations.materializer import normalize_signal_families

    evidence, statuses = normalize_signal_families(
        payloads,
        run_id=run_id,
        ingested_at=ingested_at,
        requested_scope=requested_scope,
    )
    return [item.to_dict() for item in evidence], [item.to_dict() for item in statuses]
