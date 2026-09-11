from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
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


def _public_payload(value: Any) -> dict[str, Any]:
    """Parse ontology payloads only to extract allowlisted scope metadata."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _tag_value(payload: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    tags = payload.get("tags")
    if not isinstance(tags, Mapping):
        return ""
    folded = {str(key).casefold(): value for key, value in tags.items()}
    for name in names:
        if folded.get(name):
            return folded[name]
    return ""


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
        self.by_connection_id: dict[str, list[str]] = defaultdict(list)
        self.outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity_id, row in self.entities.items():
            self.by_type[str(row.get("entity_type") or "")].append(entity_id)
            self.by_name[str(row.get("name") or "").casefold()].append(entity_id)
            if row.get("entity_type") == "SubscriptionConnection":
                raw_id = _connection_id_from_source(row)
                if raw_id:
                    self.by_connection_id[raw_id.casefold()].append(entity_id)
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

    def graph_only_view(self) -> SemanticIndexes:
        """Return a read-only graph view sharing immutable graph indexes."""
        view = object.__new__(type(self))
        view.entities = self.entities
        view.relationships = self.relationships
        view.by_type = self.by_type
        view.by_name = self.by_name
        view.by_connection_id = self.by_connection_id
        view.outgoing = self.outgoing
        view.incoming = self.incoming
        view.inventory = {}
        view.compliance = {}
        view.security = defaultdict(list)
        view.cost = defaultdict(list)
        return view

    def resolve(self, value: str, *, types: set[str] | None = None) -> str:
        needle = value.strip().casefold()
        candidates = list(self.by_name.get(needle, ()))
        if needle in self.entities:
            candidates.insert(0, needle)
        if types is None or "SubscriptionConnection" in types:
            for entity_id in self.by_connection_id.get(needle, ()):
                if entity_id not in candidates:
                    candidates.append(entity_id)
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
        """Return a safe entity projection with its authorization attributes.

        Scope attributes intentionally travel with every public entity.  The
        API applies caller scope after semantic traversal, so dropping these
        fields here would turn a scoped read into an unscoped one.
        """
        row = self.entities[entity_id]
        public = {
            key: str(row.get(key) or "")
            for key in (
                "entity_type",
                "name",
                "resource_type",
                "location",
                "lifecycle_status",
                "tenant_id",
                "subscription_id",
            )
        }
        payload = _public_payload(row.get("payload_json"))
        public.update(
            {
                key: str(
                    row.get(key)
                    or payload.get(key)
                    or _tag_value(payload, tag_names)
                    or ""
                )
                for key, tag_names in {
                    "subscription_connection": (
                        "subscriptionconnection",
                        "connection",
                    ),
                    "business_service": ("businessservice", "businessunit"),
                    "application": ("application", "appname"),
                    "environment": ("environment",),
                    "owner": ("owner",),
                    "support_team": ("supportteam", "supportgroup"),
                    "region": ("region",),
                    "criticality": ("criticality",),
                }.items()
            }
        )
        for target, names in {
            "subscription_connection": ("connection_id", "connectionId"),
            "business_service": (
                "business_service_name",
                "businessServiceName",
                "businessService",
            ),
            "application": ("application_name", "applicationName", "appName"),
            "environment": ("environment_name", "environmentName"),
            "support_team": ("support_team_name", "supportTeam"),
            "criticality": ("severity_tier",),
        }.items():
            if not public[target]:
                public[target] = str(
                    next((payload.get(name) for name in names if payload.get(name)), "")
                )
        if public["entity_type"] == "BusinessService" and not public["business_service"]:
            public["business_service"] = public["name"]
        if public["entity_type"] == "Application" and not public["application"]:
            public["application"] = public["name"]
        if public["entity_type"] == "Environment" and not public["environment"]:
            public["environment"] = public["name"]
        return public

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

    def connections_for_subscription(self, subscription_id: str) -> list[str]:
        key = _canonical_id(subscription_id)
        return [
            entity_id
            for entity_id in self.by_type.get("SubscriptionConnection", [])
            if self.entities[entity_id].get("subscription_id") == key
        ]

    def health_for_connection(self, connection_id: str) -> list[str]:
        """Health entities for a specific connection, matched by graph edge or
        exact identity — never by name prefix, which can match another
        connection whose id is a prefix of this one (e.g. ``prod`` vs
        ``prod-core``).
        """
        try:
            connection_key = self.resolve(connection_id, types={"SubscriptionConnection"})
        except LookupError:
            connection_key = ""
        if connection_key:
            traversed = self.related(connection_key, "has_health", types={"ConnectionHealth"})
            if traversed:
                return traversed
        key = _canonical_id(connection_id)
        return [
            entity_id
            for entity_id in self.by_type.get("ConnectionHealth", [])
            if str(self.entities[entity_id].get("connection_id") or _connection_id_from_source(self.entities[entity_id])).casefold() == key
        ]

    # ------------------------------------------------------------------
    # Network topology traversal (Prompt 16)
    #
    # The network normalizer emits camelCase predicates, matching the newer
    # Prompt 7+ triples. These helpers are the only place that convention is
    # encoded, so callers traverse by intent rather than by predicate string.
    # ------------------------------------------------------------------

    def vnets_for_connection(self, connection_id: str) -> list[str]:
        """VNets ingested by one subscription connection.

        Scoping is by the connection's subscription rather than by edge,
        because containment anchors a VNet to its resource group, not to the
        connection that observed it.
        """
        try:
            connection_key = self.resolve(
                connection_id, types={"SubscriptionConnection"}
            )
        except (LookupError, ValueError):
            return []
        subscription_id = str(
            self.entities[connection_key].get("subscription_id") or ""
        ).casefold()
        if not subscription_id:
            return []
        needle = f"/subscriptions/{subscription_id}/"
        return sorted(
            entity_id
            for entity_id in self.by_type.get("VNet", [])
            if needle in entity_id.casefold()
        )

    def subnets_for_vnet(self, vnet_id: str) -> list[str]:
        return self.related(vnet_id, "contains", types={"Subnet"})

    def peerings_for_vnet(self, vnet_id: str) -> list[str]:
        return self.related(vnet_id, "hasPeering", types={"VNetPeering"})

    def peered_vnets(self, vnet_id: str) -> list[str]:
        """VNets reachable in one peering hop, in either direction."""
        peers: set[str] = set()
        for peering_id in self.peerings_for_vnet(vnet_id):
            peers.update(self.related(peering_id, "peersWith", types={"VNet"}))
        for peering_id in self.related(
            vnet_id, "peersWith", direction="in", types={"VNetPeering"}
        ):
            peers.update(
                self.related(peering_id, "hasPeering", direction="in", types={"VNet"})
            )
        peers.discard(vnet_id)
        return sorted(peers)

    def nsg_for_subnet(self, subnet_id: str) -> list[str]:
        return self.related(subnet_id, "protectedBy", types={"NetworkSecurityGroup"})

    def rules_for_nsg(self, nsg_id: str) -> list[str]:
        return self.related(nsg_id, "hasRule", types={"NetworkSecurityRule"})

    def route_table_for_subnet(self, subnet_id: str) -> list[str]:
        return self.related(subnet_id, "routedBy", types={"RouteTable"})

    def routes_for_table(self, table_id: str) -> list[str]:
        return self.related(table_id, "hasRoute", types={"Route"})

    def firewall_rules_for_policy(self, policy_id: str) -> list[str]:
        rules: list[str] = []
        for collection_id in self.related(
            policy_id, "hasRuleCollection", types={"FirewallRuleCollection"}
        ):
            rules.extend(
                self.related(collection_id, "hasRule", types={"FirewallRule"})
            )
        return sorted(set(rules))

    def policies_for_firewall(self, firewall_id: str) -> list[str]:
        return self.related(firewall_id, "enforcesPolicy", types={"FirewallPolicy"})

    def vnets_for_dns_zone(self, zone_id: str) -> list[str]:
        return self.related(zone_id, "resolvesFor", types={"VNet"})

    def private_endpoints_for_target(self, resource_id: str) -> list[str]:
        return self.related(
            resource_id, "exposesPrivately", direction="in", types={"PrivateEndpoint"}
        )

    def resources_for_subnet(self, subnet_id: str) -> list[str]:
        """Workload resources placed in a subnet, resolved through their NICs."""
        resources: set[str] = set()
        for nic_id in self.related(
            subnet_id, "attachedTo", direction="in", types={"NetworkInterface"}
        ):
            resources.update(
                self.related(
                    nic_id, "hasNetworkInterface", direction="in", types=ASSET_TYPES
                )
            )
        return sorted(resources)

    def applications_for_resource(self, resource_id: str) -> list[str]:        return self.related(resource_id, "member_of", types={"Application"})

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


def _connection_id_from_source(row: dict[str, Any]) -> str:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return ""
    return str(payload.get("connection_id") or "")


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
