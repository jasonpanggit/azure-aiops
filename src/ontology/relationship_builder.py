from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from .confidence import compute_confidence
from .entity_builder import PAAS_ENTITY_TYPES, scoped_semantic_id, stable_version

ASSET_TYPES = {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster", *PAAS_ENTITY_TYPES}


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

        def connect(
            subject: dict[str, Any] | None,
            predicate: str,
            obj: dict[str, Any] | None,
            source: str,
            details: dict[str, Any] | None = None,
        ) -> None:
            if not subject or not obj or subject["resource_id"] == obj["resource_id"]:
                return
            evidence = details or {}
            relationship_id = _relationship_id(
                subject["resource_id"],
                predicate,
                obj["resource_id"],
                evidence_identity=str(evidence.get("evidence_identity") or ""),
                event_interval=evidence.get("event_interval"),
            )
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
                "confidence": compute_confidence(source),
                "source": source,
                "payload_json": json.dumps(evidence, sort_keys=True),
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
        for connection in by_type["SubscriptionConnection"]:
            connect(
                tenants.get(connection["tenant_id"]),
                "owns",
                connection,
                "subscription_connection",
            )
            connect(
                subscriptions.get(connection["subscription_id"].casefold()),
                "contains",
                connection,
                "subscription_connection",
            )
            for health in by_lineage.get(connection["resource_id"].casefold(), []):
                if health["entity_type"] == "ConnectionHealth":
                    connect(connection, "has_health", health, "subscription_connection")
            payload = _payload(connection)
            environment_name = str(
                payload.get("environment_name")
                or payload.get("environmentName")
                or payload.get("environment")
                or ""
            ).strip()
            environment = None
            if environment_name:
                environment = by_id.get(
                    scoped_semantic_id(
                        "Environment",
                        connection["tenant_id"],
                        connection["subscription_id"],
                        environment_name,
                    )
                )
                if environment:
                    connect(connection, "mapped_to", environment, "subscription_connection")
            business_service_name = str(
                payload.get("business_service_name")
                or payload.get("businessServiceName")
                or payload.get("business_service")
                or payload.get("businessService")
                or ""
            ).strip()
            business_service = None
            if business_service_name:
                business_service = by_id.get(
                    scoped_semantic_id(
                        "BusinessService",
                        connection["tenant_id"],
                        connection["subscription_id"],
                        business_service_name,
                    )
                )
                if business_service:
                    connect(connection, "supports", business_service, "subscription_connection")
            application_name = str(
                payload.get("application_name")
                or payload.get("applicationName")
                or payload.get("application")
                or ""
            ).strip()
            if application_name:
                application = by_id.get(
                    scoped_semantic_id(
                        "Application",
                        connection["tenant_id"],
                        connection["subscription_id"],
                        application_name,
                    )
                )
                if application:
                    connect(connection, "runs", application, "subscription_connection")
                    if environment:
                        connect(application, "deployed_in", environment, "subscription_connection")
                    if business_service:
                        connect(business_service, "contains", application, "subscription_connection")
                        connect(business_service, "owns", application, "subscription_connection")
        # Tag inheritance fallback (enhancement 3b): inherit a child tag only
        # when the parent scope has one unambiguous application candidate.
        rg_application_candidates: dict[str, set[str]] = defaultdict(set)
        subscription_application_candidates: dict[str, set[str]] = defaultdict(set)
        explicit_rg_application_tags = {
            group["resource_id"].casefold(): value
            for group in by_type["ResourceGroup"]
            if (
                value := (
                    _tags(group).get("appname", "")
                    or _tags(group).get("application", "")
                )
            )
        }
        explicit_subscription_application_tags = {
            subscription["subscription_id"].casefold(): value
            for subscription in by_type["Subscription"]
            if (
                value := (
                    _tags(subscription).get("appname", "")
                    or _tags(subscription).get("application", "")
                )
            )
        }
        for asset_type in sorted(ASSET_TYPES):
            for asset in by_type[asset_type]:
                asset_tags = _tags(asset)
                own_value = asset_tags.get("appname", "") or asset_tags.get("application", "")
                if not own_value:
                    continue
                group_id = _group_id(asset["resource_id"])
                if group_id:
                    rg_application_candidates[group_id].add(own_value)
                subscription_key = asset["subscription_id"].casefold()
                if subscription_key:
                    subscription_application_candidates[subscription_key].add(
                        own_value
                    )

        def _unique_application_candidate(values: set[str]) -> str:
            normalized = {
                _normalize_tag_value(value): value
                for value in sorted(values, key=lambda item: (item.casefold(), item))
            }
            return next(iter(normalized.values())) if len(normalized) == 1 else ""

        # Fuzzy tag matching (enhancement 3a): index Applications by their
        # normalized (case/whitespace/hyphen/underscore-insensitive) name
        # scoped to (tenant, subscription) so "Order-Service" resolves to the
        # same Application entity as "order_service".
        applications_by_normalized_name: dict[tuple[str, str, str], dict[str, Any]] = {
            (
                application["tenant_id"],
                application["subscription_id"],
                _normalize_tag_value(application["name"]),
            ): application
            for application in by_type["Application"]
        }

        def _resolve_application(asset: dict[str, Any], name: str) -> dict[str, Any] | None:
            normalized_match = applications_by_normalized_name.get(
                (asset["tenant_id"], asset["subscription_id"], _normalize_tag_value(name))
            )
            if normalized_match is not None:
                return normalized_match
            exact_id = scoped_semantic_id("Application", asset["tenant_id"], asset["subscription_id"], name)
            return by_id.get(exact_id)

        for asset_type in sorted(ASSET_TYPES):
            for asset in by_type[asset_type]:
                group_id = _group_id(asset["resource_id"])
                connect(groups.get(group_id), "contains", asset, "inventory")
                if asset_type == "ArcServer":
                    connect(asset, "managed_by", subscriptions.get(asset["subscription_id"].casefold()), "inventory")

                related = by_lineage.get(asset["resource_id"], [])
                tags = _tags(asset)
                own_application_value = tags.get("appname", "") or tags.get("application", "")
                inherited_application_value = ""
                if not own_application_value:
                    subscription_key = asset["subscription_id"].casefold()
                    inherited_application_value = (
                        explicit_rg_application_tags.get(group_id, "")
                        or _unique_application_candidate(
                            rg_application_candidates.get(group_id, set())
                        )
                        or explicit_subscription_application_tags.get(
                            subscription_key, ""
                        )
                        or _unique_application_candidate(
                            subscription_application_candidates.get(
                                subscription_key, set()
                            )
                        )
                    )
                application_names = {
                    value
                    for value in (tags.get("appname", ""), tags.get("application", ""), inherited_application_value)
                    if value
                }
                applications = [
                    application
                    for application in (
                        _resolve_application(asset, name) for name in sorted(application_names)
                    )
                    if application is not None
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
                    if _normalize_tag_value(application["name"]) in {
                        _normalize_tag_value(tags.get("appname", "")),
                        _normalize_tag_value(tags.get("application", "")),
                        _normalize_tag_value(inherited_application_value),
                    }:
                        for dependency_name in dependency_names:
                            dependency_id = scoped_semantic_id(
                                "Application",
                                asset["tenant_id"],
                                asset["subscription_id"],
                                dependency_name,
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
        for assessment in by_type["DefenderAssessment"]:
            target = by_id.get(str(_payload(assessment).get("targetResourceId") or "").casefold())
            connect(assessment, "impacts", target, "defender")
        for finding in by_type["DefenderVulnerabilityFinding"]:
            payload = _payload(finding)
            target = by_id.get(str(payload.get("targetResourceId") or "").casefold())
            assessment = by_id.get(
                str(payload.get("assessmentId") or "").casefold()
            )
            connect(finding, "impacts", target, "defender")
            connect(target, "hasVulnerability", finding, "defender")
            connect(finding, "derivedFrom", assessment, "defender")
        for observation in by_type["VulnerabilityObservation"]:
            payload = _payload(observation)
            target = by_id.get(
                str(payload.get("ontology_target_id") or "").casefold()
            )
            weakness = by_id.get(
                str(payload.get("weakness_entity_id") or "").casefold()
            )
            source_families = sorted(
                {
                    str(value).casefold()
                    for value in payload.get("source_families") or ()
                    if value
                }
            )
            source = (
                f"exposure:{'+'.join(source_families)}"
                if source_families
                else "exposure"
            )
            details = _exposure_details(payload)
            connect(observation, "affects", target, source, details)
            connect(observation, "identifies", weakness, source, details)
            connect(target, "hasVulnerabilityObservation", observation, source, details)
        for image in by_type["LogicalImage"]:
            payload = _payload(image)
            connect(
                by_id.get(str(payload.get("registry_id") or "").casefold()),
                "containsImage",
                image,
                "exposure:defender",
                _exposure_details(payload),
            )
            digest_entity_ids = payload.get("digest_entity_ids") or (
                [payload["digest_entity_id"]]
                if payload.get("digest_entity_id")
                else []
            )
            for digest_entity_id in digest_entity_ids:
                connect(
                    image,
                    "hasDigest",
                    by_id.get(str(digest_entity_id).casefold()),
                    "exposure:defender",
                    _exposure_details(payload),
                )
        for deployment in by_type["WorkloadDeployment"]:
            payload = _payload(deployment)
            details = _exposure_details(payload)
            connect(
                by_id.get(str(payload.get("digest_entity_id") or "").casefold()),
                "deployedAs",
                deployment,
                "container_insights",
                details,
            )
            connect(
                by_id.get(str(payload.get("cluster_id") or "").casefold()),
                "observesDeployment",
                deployment,
                "container_insights",
                details,
            )
            application = by_id.get(
                str(payload.get("application_entity_id") or "").casefold()
            )
            connect(
                deployment,
                "runsApplication",
                application,
                "container_insights",
                details,
            )
            connect(
                by_id.get(
                    str(payload.get("business_service_entity_id") or "").casefold()
                ),
                "contains",
                application,
                "container_insights",
                details,
            )
        for alert in by_type["SecurityAlert"]:
            for resource_id in _payload(alert).get("resourceIds") or ():
                connect(alert, "affects", by_id.get(str(resource_id).casefold()), "defender")
        attack_path_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in by_type["AttackPathNode"]:
            attack_path_nodes[
                str(_payload(node).get("attackPathId") or "").casefold()
            ].append(node)
        for path in by_type["AttackPath"]:
            payload = _payload(path)
            for node in attack_path_nodes.get(
                str(path["resource_id"]).casefold(), ()
            ):
                connect(path, "traverses", node, "defender")
            connect(
                path,
                "startsAt",
                by_id.get(str(payload.get("entryPointNodeId") or "").casefold()),
                "defender",
            )
            connect(
                path,
                "targets",
                by_id.get(str(payload.get("targetNodeId") or "").casefold()),
                "defender",
            )
            for assessment_id in payload.get("assessmentIds") or ():
                connect(
                    path,
                    "supportedBy",
                    by_id.get(str(assessment_id).casefold()),
                    "defender",
                )
        for node in by_type["AttackPathNode"]:
            resource_id = str(_payload(node).get("resourceId") or "").casefold()
            connect(node, "resolvesTo", by_id.get(resource_id), "defender")
        for connection in by_type["AttackPathConnection"]:
            payload = _payload(connection)
            path = by_id.get(str(payload.get("attackPathId") or "").casefold())
            connect(path, "contains", connection, "defender")
            connect(
                connection,
                "connectsFrom",
                by_id.get(str(payload.get("sourceNodeId") or "").casefold()),
                "defender",
            )
            connect(
                connection,
                "connectsTo",
                by_id.get(str(payload.get("targetNodeId") or "").casefold()),
                "defender",
            )
        secure_scores_by_source = {
            str(_payload(score).get("sourceId") or "").casefold(): score
            for score in by_type["SecureScoreSnapshot"]
        }
        for score in by_type["SecureScoreSnapshot"]:
            subscription_id = str(
                _payload(score).get("subscriptionResourceId") or ""
            ).casefold()
            connect(by_id.get(subscription_id), "hasSecureScore", score, "defender")
        for control in by_type["SecureScoreControl"]:
            payload = _payload(control)
            connect(
                secure_scores_by_source.get(
                    str(payload.get("secureScoreSourceId") or "").casefold()
                ),
                "composedOf",
                control,
                "defender",
            )
            for assessment_id in payload.get("assessmentDefinitions") or ():
                connect(
                    control,
                    "improvedBy",
                    by_id.get(str(assessment_id).casefold()),
                    "defender",
                )
        for actual in by_type["CostActual"]:
            target = _target(actual)
            connect(by_id.get(target), "incurs_cost", actual, "cost_management")
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

        self._connect_network(by_type, by_id, connect)

        return sorted(relationships.values(), key=lambda row: row["resource_id"])

    def _connect_network(
        self,
        by_type: dict[str, list[dict[str, Any]]],
        by_id: dict[str, dict[str, Any]],
        connect: Any,
    ) -> None:
        """Rebuilds the network topology edges from entity payloads.

        The ARG normalizer emits these edges directly, but the ontology graph
        is rebuilt from entities alone -- normalizer edges only reach
        ``silver_resource_relationships``. Re-deriving them here is what makes
        network topology traversable from the Semantic Knowledge Layer.
        """

        def ref(value: Any) -> dict[str, Any] | None:
            key = str(value or "").casefold()
            return by_id.get(key) if key else None

        def link_each(subject, predicate, values) -> None:
            for value in values or ():
                connect(subject, predicate, ref(value), "network")

        for vnet in by_type["VNet"]:
            payload = _payload(vnet)
            link_each(vnet, "contains", payload.get("subnetIds"))
            link_each(vnet, "hasPeering", payload.get("peeringIds"))

        for subnet in by_type["Subnet"]:
            payload = _payload(subnet)
            connect(subnet, "protectedBy", ref(payload.get("nsgId")), "network", {"source": "subnet.nsgId"})
            connect(subnet, "routedBy", ref(payload.get("routeTableId")), "network", {"source": "subnet.routeTableId"})
            connect(subnet, "egressesVia", ref(payload.get("natGatewayId")), "network", {"source": "subnet.natGatewayId"})

        for peering in by_type["VNetPeering"]:
            payload = _payload(peering)
            connect(peering, "peersWith", ref(payload.get("remoteVnetId")), "network", _pick(payload, "peeringState", "allowForwardedTraffic", "allowGatewayTransit", "useRemoteGateways", "allowVirtualNetworkAccess"))

        for nsg in by_type["NetworkSecurityGroup"]:
            link_each(nsg, "hasRule", _payload(nsg).get("ruleIds"))

        for rule in by_type["NetworkSecurityRule"]:
            payload = _payload(rule)
            connect(ref(payload.get("nsgId")), "hasRule", rule, "network", _pick(payload, "priority", "direction", "access", "protocol", "sourceAddress", "destinationAddress", "sourcePort", "destinationPort", "description", "isDefault"))

        for table in by_type["RouteTable"]:
            link_each(table, "hasRoute", _payload(table).get("routeIds"))

        for route in by_type["Route"]:
            payload = _payload(route)
            connect(ref(payload.get("routeTableId")), "hasRoute", route, "network", _pick(payload, "addressPrefix", "nextHopType", "nextHopIp"))

        for nic in by_type["NetworkInterface"]:
            payload = _payload(nic)
            connect(nic, "protectedBy", ref(payload.get("nsgId")), "network", {"source": "nic.nsgId"})
            connect(nic, "attachedTo", ref(payload.get("subnetId")), "network", _pick(payload, "privateIps", "publicIps"))
            connect(
                ref(payload.get("attachedResourceId")),
                "hasNetworkInterface",
                nic,
                "network",
                _pick(payload, "privateIps", "publicIps", "attachedResourceId"),
            )

        for firewall in by_type["AzureFirewall"]:
            payload = _payload(firewall)
            connect(firewall, "attachedTo", ref(payload.get("subnetId")), "network", _pick(payload, "privateIp", "publicIps", "skuTier"))
            connect(
                firewall, "enforcesPolicy", ref(payload.get("policyId")), "network"
            )

        for policy in by_type["FirewallPolicy"]:
            for firewall_id in _payload(policy).get("firewallIds") or ():
                connect(ref(firewall_id), "enforcesPolicy", policy, "network")

        for collection in by_type["FirewallRuleCollection"]:
            payload = _payload(collection)
            connect(
                ref(payload.get("policyId")),
                "hasRuleCollection",
                collection,
                "network",
                _pick(payload, "priority", "action", "collectionType"),
            )
            for rule_id in payload.get("ruleIds") or ():
                rule = ref(rule_id)
                connect(
                    collection,
                    "hasRule",
                    rule,
                    "network",
                    _pick(
                        _payload(rule) if rule else {},
                        "ruleType",
                        "action",
                        "protocols",
                        "sourceAddresses",
                        "destinationAddresses",
                        "destinationPorts",
                        "destinationFqdns",
                        "sourceIpGroups",
                    ),
                )

        for rule in by_type["FirewallRule"]:
            connect(
                ref(_payload(rule).get("collectionId")),
                "hasRule",
                rule,
                "network",
                _pick(
                    _payload(rule),
                    "ruleType",
                    "action",
                    "protocols",
                    "sourceAddresses",
                    "destinationAddresses",
                    "destinationPorts",
                    "destinationFqdns",
                    "sourceIpGroups",
                ),
            )

        for endpoint in by_type["PrivateEndpoint"]:
            payload = _payload(endpoint)
            connect(endpoint, "attachedTo", ref(payload.get("subnetId")), "network", _pick(payload, "privateIps", "connectionState"))
            connect(
                endpoint,
                "exposesPrivately",
                ref(payload.get("targetResourceId")),
                "network",
                _pick(payload, "targetResourceId", "groupIds", "privateIps", "privateDnsZoneIds", "connectionState"),
            )

        for zone in by_type["PrivateDnsZone"]:
            link_each(zone, "resolvesFor", _payload(zone).get("linkedVnetIds"))

        for gateway in by_type["NetworkGateway"]:
            payload = _payload(gateway)
            connect(
                gateway,
                "attachedTo",
                ref(payload.get("subnetId")) or ref(payload.get("vnetId")),
                "network",
                _pick(payload, "gatewayType", "sku", "publicIps", "privateIps", "connectedCircuitIds"),
            )

        for balancer in by_type["LoadBalancer"]:
            payload = _payload(balancer)
            connect(balancer, "attachedTo", ref(payload.get("subnetId")), "network", _pick(payload, "sku", "frontendIps", "publicIps", "wafEnabled"))
            link_each(balancer, "loadBalances", payload.get("backendResourceIds"))
            backend_subnets = payload.get("backendSubnetIds") or payload.get("backend_subnet_ids") or ()
            if not backend_subnets:
                properties = payload.get("properties")
                pools = properties.get("backendAddressPools") if isinstance(properties, Mapping) else ()
                backend_subnets = [
                    address_properties.get("subnet", {}).get("id")
                    for pool in pools or ()
                    if isinstance(pool, Mapping)
                    for pool_properties in (pool.get("properties") or {},)
                    if isinstance(pool_properties, Mapping)
                    for address in (pool_properties.get("loadBalancerBackendAddresses") or ())
                    if isinstance(address, Mapping)
                    for address_properties in (address.get("properties") or address,)
                    if isinstance(address_properties, Mapping)
                    and isinstance(address_properties.get("subnet"), Mapping)
                    and address_properties["subnet"].get("id")
                ]
            link_each(balancer, "loadBalances", backend_subnets)
            tags = payload.get("tags") or balancer.get("tags") or {}
            if isinstance(tags, Mapping):
                managed_resource_id = next(
                    (
                        str(value)
                        for key, value in tags.items()
                        if str(key).casefold() in {"aca-managed-env-id", "managed-by-resource-id"}
                        and value
                    ),
                    "",
                )
                connect(ref(managed_resource_id), "hosts", balancer, "network", {"source": "tags"})


def _relationship_id(
    subject: str,
    predicate: str,
    obj: str,
    *,
    evidence_identity: str = "",
    event_interval: Any = None,
) -> str:
    identity = [subject.casefold(), predicate, obj.casefold()]
    if evidence_identity or event_interval:
        identity.extend(
            [
                evidence_identity,
                event_interval if isinstance(event_interval, Mapping) else {},
            ]
        )
    return "relationship://" + stable_version(identity)[:40]


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


def _normalize_tag_value(value: str) -> str:
    """Casefold and collapse hyphen/underscore/whitespace variance for tag matching.

    Lets ``Order-Service``, ``order_service``, and ``order service`` be treated
    as the same application/business-service tag value.
    """
    return "-".join(re.split(r"[-_\s]+", str(value or "").strip().casefold())).strip("-")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload_json")
    if not value:
        return {}
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _exposure_details(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = {
        "read_model_generation_id": str(
            payload.get("read_model_generation_id") or ""
        ),
        "source_families": sorted(
            {
                str(value).casefold()
                for value in payload.get("source_families") or ()
                if value
            }
        ),
        "completeness": str(payload.get("completeness") or ""),
    }
    for field_name in (
        "evidence_identity",
        "source_generation",
        "attempted_generation",
        "effective_generation",
        "event_interval",
        "provenance",
        "target_kind",
    ):
        value = payload.get(field_name)
        if value not in (None, "", [], {}):
            details[field_name] = value
    return details


def _pick(source: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source and source[key] not in (None, "")}
