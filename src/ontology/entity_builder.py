from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

TAG_ENTITY_TYPES = {
    "appname": "Application",
    "application": "Application",
    "environment": "Environment",
    "businessunit": "BusinessService",
    "businessservice": "BusinessService",
    "costcenter": "BusinessFunction",
    "owner": "Owner",
    "supportgroup": "SupportTeam",
    "supportteam": "SupportTeam",
    "service": "Service",
    "servicename": "Service",
    "subscriptionconnection": "SubscriptionConnection",
    "connection": "SubscriptionConnection",
}

DEPENDENCY_TAGS = {"dependson", "dependencies", "applicationdependencies"}

RESOURCE_ENTITY_TYPES = {
    "microsoft.compute/virtualmachines": "VirtualMachine",
    "microsoft.hybridcompute/machines": "ArcServer",
    "microsoft.containerservice/managedclusters": "KubernetesCluster",
    "microsoft.kubernetes/connectedclusters": "KubernetesCluster",
    "microsoft.management/managementgroups": "ManagementGroup",
    "microsoft.compute/virtualmachines/patchassessmentresults": "PatchAssessment",
    "microsoft.hybridcompute/machines/patchassessmentresults": "PatchAssessment",
    "microsoft.advisor/recommendations": "AdvisorRecommendation",
    # Network topology (Prompt 16). Sub-resources (Subnet, NetworkSecurityRule,
    # Route, VNetPeering, FirewallRuleCollection, FirewallRule) have no ARM
    # resourceType of their own and are classified from their `entity_type`.
    "microsoft.network/virtualnetworks": "VNet",
    "microsoft.network/networkinterfaces": "NetworkInterface",
    "microsoft.network/networksecuritygroups": "NetworkSecurityGroup",
    "microsoft.network/routetables": "RouteTable",
    "microsoft.network/azurefirewalls": "AzureFirewall",
    "microsoft.network/firewallpolicies": "FirewallPolicy",
    "microsoft.network/privateendpoints": "PrivateEndpoint",
    "microsoft.network/privatednszones": "PrivateDnsZone",
    "microsoft.network/virtualnetworkgateways": "NetworkGateway",
    "microsoft.network/natgateways": "NetworkGateway",
    "microsoft.network/expressroutegateways": "NetworkGateway",
    "microsoft.network/vpngateways": "NetworkGateway",
    "microsoft.network/bastionhosts": "NetworkGateway",
    "microsoft.network/dnsresolvers": "NetworkGateway",
    "microsoft.network/loadbalancers": "LoadBalancer",
    "microsoft.network/applicationgateways": "LoadBalancer",
    # PaaS resource identity (inventory Azure/PaaS tab). Kept distinct from the
    # generic "Resource" fallback so the graph and relationship builder can
    # target them by type instead of lumping every managed service together.
    "microsoft.storage/storageaccounts": "StorageAccount",
    "microsoft.sql/servers": "SqlServer",
    "microsoft.sql/servers/databases": "SqlDatabase",
    "microsoft.dbforpostgresql/flexibleservers": "PostgresServer",
    "microsoft.dbformysql/flexibleservers": "MySqlServer",
    "microsoft.documentdb/databaseaccounts": "CosmosAccount",
    "microsoft.web/sites": "AppService",
    "microsoft.web/serverfarms": "AppServicePlan",
    "microsoft.keyvault/vaults": "KeyVault",
    "microsoft.containerregistry/registries": "ContainerRegistry",
    "microsoft.servicebus/namespaces": "ServiceBusNamespace",
    "microsoft.eventhub/namespaces": "EventHubNamespace",
    "microsoft.cache/redis": "RedisCache",
    "microsoft.insights/components": "AppInsights",
    "microsoft.operationalinsights/workspaces": "LogAnalyticsWorkspace",
    "microsoft.cognitiveservices/accounts": "CognitiveServicesAccount",
}

PAAS_ENTITY_TYPES = frozenset(
    {
        "StorageAccount",
        "SqlServer",
        "SqlDatabase",
        "PostgresServer",
        "MySqlServer",
        "CosmosAccount",
        "AppService",
        "AppServicePlan",
        "KeyVault",
        "ContainerRegistry",
        "ServiceBusNamespace",
        "EventHubNamespace",
        "RedisCache",
        "AppInsights",
        "LogAnalyticsWorkspace",
        "CognitiveServicesAccount",
    }
)


def semantic_id(entity_type: str, tenant_id: str, value: str) -> str:
    normalized = " ".join(value.casefold().split())
    digest = hashlib.sha256(f"{tenant_id.casefold()}|{entity_type}|{normalized}".encode()).hexdigest()
    return f"ontology://{_slug(entity_type)}/{digest[:32]}"


def scoped_semantic_id(
    entity_type: str, tenant_id: str, subscription_id: str, value: str
) -> str:
    """Create a business-context identity isolated to one subscription."""
    return semantic_id(entity_type, tenant_id, f"{subscription_id}:{value}")


def stable_version(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class EntityBuilder:
    """Builds structural and tag-derived ontology entities without fixed tag values."""

    def __init__(
        self,
        *,
        max_source_rows: int = 50_000,
        max_entities: int = 100_000,
        max_tags_per_resource: int = 100,
        max_tag_value_chars: int = 1024,
    ) -> None:
        for name, value in (
            ("max_source_rows", max_source_rows),
            ("max_entities", max_entities),
            ("max_tags_per_resource", max_tags_per_resource),
            ("max_tag_value_chars", max_tag_value_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Ontology {name} must be a positive integer")
        self.max_source_rows = max_source_rows
        self.max_entities = max_entities
        self.max_tags_per_resource = max_tags_per_resource
        self.max_tag_value_chars = max_tag_value_chars

    def build(
        self,
        source_rows: Iterable[dict[str, Any]],
        run_id: str,
        timestamp: str = "",
    ) -> list[dict[str, Any]]:
        rows = list(source_rows)
        if len(rows) > self.max_source_rows:
            raise ValueError("Ontology source rows exceed configured bound")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("Ontology run_id must be a non-empty string")
        if not isinstance(timestamp, str):
            raise TypeError("Ontology timestamp must be a string")
        candidates: dict[str, dict[str, Any]] = {}
        source_versions: dict[str, str] = {}
        lineage: dict[str, set[str]] = defaultdict(set)
        for source in rows:
            if not isinstance(source, Mapping):
                raise TypeError("Ontology source rows must be mappings")
            row = dict(source)
            if not row.get("timestamp") and timestamp:
                row["timestamp"] = timestamp
            for field_name in ("lineage_json", "semantic_metadata_json"):
                if field_name in row:
                    _validate_json_mapping_field(row[field_name], field_name)
            payload = _payload(row)
            tags_value = payload.get("tags") or {}
            if not isinstance(tags_value, dict):
                raise TypeError("Ontology resource tags must be a mapping")
            if len(tags_value) > self.max_tags_per_resource:
                raise ValueError("Ontology resource tags exceed configured bound")
            if any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or len(value) > self.max_tag_value_chars
                for key, value in tags_value.items()
            ):
                raise ValueError("Ontology tag value is invalid or exceeds configured bound")
            resource_id = str(row.get("resource_id") or payload.get("id") or "").casefold()
            tenant_id = str(row.get("tenant_id") or payload.get("tenantId") or "")
            subscription_id = str(row.get("subscription_id") or payload.get("subscriptionId") or "")
            entity_type = _classify(row)
            if resource_id:
                candidate = self._entity(
                    resource_id=resource_id,
                    entity_type=entity_type,
                    name=str(row.get("name") or payload.get("name") or resource_id.rsplit("/", 1)[-1]),
                    tenant_id=tenant_id,
                    subscription_id=subscription_id,
                    run_id=run_id,
                    source=row,
                    lineage_ids=[resource_id],
                )
                existing_version = source_versions.get(resource_id)
                if existing_version and existing_version != candidate["change_version"]:
                    raise ValueError(
                        "Ontology canonical duplicate source entities conflict"
                    )
                source_versions[resource_id] = candidate["change_version"]
                candidates[resource_id] = candidate

            if tenant_id:
                tenant_key = semantic_id("Tenant", tenant_id, tenant_id)
                if resource_id:
                    lineage[tenant_key].add(resource_id)
                candidates.setdefault(
                    tenant_key,
                    self._entity(
                        resource_id=tenant_key,
                        entity_type="Tenant",
                        name=tenant_id,
                        tenant_id=tenant_id,
                        subscription_id="not-applicable",
                        run_id=run_id,
                        source={"discovery": "tenant_id", "timestamp": timestamp},
                        lineage_ids=[resource_id] if resource_id else [],
                    ),
                )
            if subscription_id:
                subscription_key = f"/subscriptions/{subscription_id}".casefold()
                if resource_id:
                    lineage[subscription_key].add(resource_id)
                candidates.setdefault(
                    subscription_key,
                    self._entity(
                        resource_id=subscription_key,
                        entity_type="Subscription",
                        name=subscription_id,
                        tenant_id=tenant_id,
                        subscription_id=subscription_id,
                        run_id=run_id,
                        source={"discovery": "subscription_id", "timestamp": timestamp},
                        lineage_ids=[resource_id] if resource_id else [],
                    ),
                )
            resource_group = str(payload.get("resourceGroup") or _resource_group(resource_id))
            if resource_group and subscription_id:
                group_key = f"/subscriptions/{subscription_id}/resourcegroups/{resource_group}".casefold()
                if resource_id:
                    lineage[group_key].add(resource_id)
                candidates.setdefault(
                    group_key,
                    self._entity(
                        resource_id=group_key,
                        entity_type="ResourceGroup",
                        name=resource_group,
                        tenant_id=tenant_id,
                        subscription_id=subscription_id,
                        run_id=run_id,
                        source={"discovery": "resource_id", "timestamp": timestamp},
                        lineage_ids=[resource_id],
                    ),
                )

            connection_id = _connection_id(row)
            if connection_id:
                connection_key = _connection_key(tenant_id, subscription_id, connection_id)
                if not resource_id:
                    resource_id = connection_key
                connection_source: dict[str, Any] = {
                    "discovery": "subscription_connection",
                    "connection_id": connection_id,
                    "timestamp": timestamp or row.get("timestamp", ""),
                }
                connection_source.update(_connection_lineage(row, tags_value))
                connection_display_name = (
                    _connection_field(row, ("connection_name", "connectionName"))
                    or str(row.get("name") or "")
                    or connection_id
                )
                candidates.setdefault(
                    connection_key,
                    self._entity(
                        resource_id=connection_key,
                        entity_type="SubscriptionConnection",
                        name=connection_display_name,
                        tenant_id=tenant_id,
                        subscription_id=subscription_id,
                        run_id=run_id,
                        source=connection_source,
                        lineage_ids=[resource_id] if resource_id else [connection_key],
                    ),
                )
                health_status = _connection_field(
                    row,
                    (
                        "connection_health_status",
                        "connectionHealthStatus",
                        "health_status",
                        "connectionHealth",
                        "healthStatus",
                    ),
                )
                if health_status:
                    health_key = semantic_id("ConnectionHealth", tenant_id, f"{connection_id}:{health_status}")
                    candidates.setdefault(
                        health_key,
                        self._entity(
                            resource_id=health_key,
                            entity_type="ConnectionHealth",
                            name=f"{connection_id} status {health_status}",
                            tenant_id=tenant_id,
                            subscription_id=subscription_id,
                            run_id=run_id,
                            source={
                                "discovery": "connection_health",
                                "connection_id": connection_id,
                                "status": health_status,
                                "timestamp": timestamp or row.get("timestamp", ""),
                            },
                            lineage_ids=[connection_key],
                        ),
                    )

                # Connection metadata is authoritative business context, so the
                # Environment/Application/BusinessService it names must exist for
                # the mapped_to/runs/supports lineage edges to resolve.
                for field_name, lineage_type in (
                    ("environment_name", "Environment"),
                    ("application_name", "Application"),
                    ("business_service_name", "BusinessService"),
                ):
                    value = connection_source.get(field_name, "")
                    if not value:
                        continue
                    lineage_key = scoped_semantic_id(
                        lineage_type, tenant_id, subscription_id, value
                    )
                    lineage[lineage_key].add(connection_key)
                    candidates.setdefault(
                        lineage_key,
                        self._entity(
                            resource_id=lineage_key,
                            entity_type=lineage_type,
                            name=value,
                            tenant_id=tenant_id,
                            subscription_id=subscription_id,
                            run_id=run_id,
                            source={
                                "discovery": "subscription_connection_metadata",
                                "connection_id": connection_id,
                                "timestamp": timestamp or row.get("timestamp", ""),
                            },
                            lineage_ids=[connection_key],
                        ),
                    )

            tags = {
                key.casefold(): value.strip() for key, value in tags_value.items()
            }
            for tag_name, entity_type_from_tag in TAG_ENTITY_TYPES.items():
                value = tags.get(tag_name, "")
                if not value:
                    continue
                entity_id = scoped_semantic_id(
                    entity_type_from_tag, tenant_id, subscription_id, value
                )
                lineage[entity_id].add(resource_id)
                candidates.setdefault(
                    entity_id,
                    self._entity(
                        resource_id=entity_id,
                        entity_type=entity_type_from_tag,
                        name=value,
                        tenant_id=tenant_id,
                        subscription_id=subscription_id,
                        run_id=run_id,
                        source={
                            "discovery": "resource_tag",
                            "tag": tag_name,
                            "timestamp": timestamp or row.get("timestamp", ""),
                        },
                        lineage_ids=[resource_id],
                    ),
                )

            for dependency_tag in DEPENDENCY_TAGS:
                for value in _tag_values(tags.get(dependency_tag, "")):
                    entity_id = scoped_semantic_id(
                        "Application", tenant_id, subscription_id, value
                    )
                    lineage[entity_id].add(resource_id)
                    candidates.setdefault(
                        entity_id,
                        self._entity(
                            resource_id=entity_id,
                            entity_type="Application",
                            name=value,
                            tenant_id=tenant_id,
                            subscription_id=subscription_id,
                            run_id=run_id,
                            source={
                                "discovery": "dependency_tag",
                                "tag": dependency_tag,
                                "timestamp": timestamp or row.get("timestamp", ""),
                            },
                            lineage_ids=[resource_id],
                        ),
                    )

            if len(candidates) > self.max_entities:
                raise ValueError("Ontology entity bound exceeded")

        for entity_id, source_ids in lineage.items():
            row = candidates[entity_id]
            row["lineage_json"] = _canonical({"source_resource_ids": sorted(source_ids)})
            row["change_version"] = stable_version(_semantic(row))
        return sorted(candidates.values(), key=lambda row: (row["entity_type"], row["resource_id"]))

    def _entity(
        self,
        *,
        resource_id: str,
        entity_type: str,
        name: str,
        tenant_id: str,
        subscription_id: str,
        run_id: str,
        source: dict[str, Any],
        lineage_ids: list[str],
    ) -> dict[str, Any]:
        payload = _payload(source)
        timestamp = str(
            source.get("timestamp")
            or payload.get("lastObservedTimestamp")
            or payload.get("createdTimestamp")
            or "1970-01-01T00:00:00Z"
        )
        row = {
            "tenant_id": tenant_id or "not-applicable",
            "subscription_id": subscription_id or "not-applicable",
            "resource_id": resource_id.casefold(),
            "timestamp": timestamp,
            "change_version": "",
            "ingestion_run_id": run_id,
            "entity_type": entity_type,
            "name": name,
            "resource_type": str(source.get("resource_type") or payload.get("resourceType") or ""),
            "location": str(source.get("location") or payload.get("location") or ""),
            "payload_json": _canonical(payload or _source_payload(source)),
            "lineage_json": _canonical({"source_resource_ids": sorted(x for x in lineage_ids if x)}),
            "semantic_metadata_json": _canonical(
                {"builder": "aiops-ontology", "discovery": source.get("discovery", "inventory")}
            ),
            "lifecycle_status": "active",
            "valid_from": timestamp,
            "retired_at": "",
            "ontology_version": "1",
        }
        row["change_version"] = stable_version(_semantic(row))
        return row


def _classify(row: dict[str, Any]) -> str:
    declared_type = str(row.get("entity_type") or "")
    if declared_type and declared_type != "Resource":
        return declared_type
    resource_type = str(row.get("resource_type") or _payload(row).get("resourceType") or "").casefold()
    return RESOURCE_ENTITY_TYPES.get(resource_type, declared_type or "Resource")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload_json")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Ontology payload_json is malformed") from exc
        if not isinstance(parsed, dict):
            raise TypeError("Ontology payload_json must contain a mapping")
        return parsed
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Ontology payload_json must be a string or mapping")
    return value


def _validate_json_mapping_field(value: Any, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"Ontology {field_name} must be a JSON string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ontology {field_name} is malformed") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"Ontology {field_name} must contain a mapping")


def _source_payload(source: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "payload_json",
        "lineage_json",
        "semantic_metadata_json",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "lifecycle_status",
        "valid_from",
        "retired_at",
        "ontology_version",
    }
    payload = {key: value for key, value in source.items() if key not in excluded}
    for field_name in ("resource_id", "tenant_id", "subscription_id"):
        if field_name in payload:
            payload[field_name] = str(payload[field_name]).casefold()
    return payload


def _resource_group(resource_id: str) -> str:
    match = re.search(r"/resourcegroups/([^/]+)", resource_id, re.IGNORECASE)
    return match.group(1) if match else ""


def _tag_values(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,;]", value) if item.strip()]


def _connection_id(row: dict[str, Any]) -> str:
    payload = _payload(row)
    for key in (
        "subscription_connection_id",
        "subscriptionConnectionId",
        "connection_id",
        "connectionId",
        "connection",
    ):
        value = row.get(key) or payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _connection_field(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    """First non-empty value for ``keys``, checking the row then its payload."""
    payload = _payload(row)
    for key in keys:
        value = row.get(key)
        if value is None:
            value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _connection_lineage(row: dict[str, Any], tags: dict[str, str]) -> dict[str, str]:
    """Environment, application and business-service names used to build connection
    lineage edges.

    Explicit connection metadata wins; resource tags are the fallback so a
    connection still links to business context when metadata is not yet mapped.
    """
    folded = {key.casefold(): str(value).strip() for key, value in tags.items()}
    lineage: dict[str, str] = {}
    for target, keys, tag_names in (
        (
            "environment_name",
            ("environment_name", "environmentName", "environment"),
            ("environment",),
        ),
        (
            "application_name",
            ("application_name", "applicationName", "application", "appName"),
            ("application", "appname"),
        ),
        (
            "business_service_name",
            (
                "business_service_name",
                "businessServiceName",
                "business_service",
                "businessService",
            ),
            ("businessservice", "businessunit"),
        ),
    ):
        value = _connection_field(row, keys)
        if not value:
            for tag_name in tag_names:
                if folded.get(tag_name):
                    value = folded[tag_name]
                    break
        if value:
            lineage[target] = value
    return lineage


def _connection_key(tenant_id: str, subscription_id: str, connection_id: str) -> str:
    scope = f"{tenant_id}:{subscription_id}:{connection_id}".casefold()
    return semantic_id("SubscriptionConnection", tenant_id, scope)


def _semantic(row: dict[str, Any]) -> dict[str, Any]:
    semantic = {
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
    for field in ("payload_json", "semantic_metadata_json"):
        try:
            semantic[field] = _canonical(_without_observation_fields(json.loads(semantic[field])))
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    return semantic


def _without_observation_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_observation_fields(item)
            for key, item in value.items()
            if key.casefold()
            not in {
                "timestamp",
                "createdtimestamp",
                "lastobservedtimestamp",
                "ingestion_timestamp",
                "ingestion_run_id",
            }
        }
    if isinstance(value, list):
        return [_without_observation_fields(item) for item in value]
    return value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
