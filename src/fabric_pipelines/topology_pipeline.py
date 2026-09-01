"""Fabric-backed topology derivation pipeline.

Reproduces the onboarding normalizer's ``_normalize_network`` behavior.
deterministic predicate vocabulary and ``_add_edge``'s content-addressed
relationship-ID scheme verbatim, but sources rows from inventory-owned
identity data (via the same ``network_normalize`` sub-resource flatteners
AIOps already uses) instead of a direct ARG query.

This module owns *only* topology entity/edge derivation. It never re-derives
or re-queries identity fields already owned by inventory — every row must
already carry ``resource_id``/``properties`` from the inventory read port
(Anti-Pattern guard, D-11/D-12 boundary).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from onboarding.network_normalize import (
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
from storage.delta_writer import DeltaWriteMode, DeltaWriter, DeltaWriteResult
from storage.onelake_writer import OneLakeWriter

from .topology_fabric_contracts import (
    TOPOLOGY_EDGES_CONTRACT,
    TOPOLOGY_ENTITIES_CONTRACT,
    TopologyFabricContract,
)

#: Fixed 1.0 schema version tag, matching the ingestion entity/edge envelope
#: (normalize.py:_base / _add_edge) so downstream consumers see identical
#: envelope shape regardless of which arm produced the row.
_SCHEMA_VERSION = "1.0.0"

#: Source tag recorded on every derived edge -- distinct from AIOps's own
#: "arg:Resources" tag so provenance is unambiguous about which arm produced
#: a given relationship (T-08-06: source must remain explicit, never implied).
SOURCE_TAG = "fabric_pipeline:topology"


def derive_edges(
    entity_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    observed: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derives ``(topology_entities, topology_edges)`` rows.

    ``entity_rows`` carries the same logical keys ``_normalize_network``
    consumes (``network_vnets``, ``network_security_groups``, ...), each row
    already inventory-shaped (``resource_id``, ``properties``, ``tags``)
    per the read-port adapter proven in 08-01.
    """
    entities: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def record(entity_type: str, entity: dict[str, Any]) -> None:
        entities[entity["id"]] = _to_topology_entity_row(entity_type, entity)

    def link(subject: str, predicate: str, obj: str, confidence: float = 1.0) -> None:
        _add_edge(edges, subject, predicate, obj, SOURCE_TAG, observed, confidence)

    def containment(row: Mapping[str, Any], entity: dict[str, Any]) -> None:
        parent = _resource_group_key(row) or _subscription_key(row)
        if parent:
            link(entity["id"], "belongsTo", parent)

    for row in entity_rows.get("network_vnets", []):
        base = _base(row, observed)
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

    for row in entity_rows.get("network_security_groups", []):
        base = _base(row, observed)
        nsg, rules = normalize_nsg(base, row, observed)
        record("NetworkSecurityGroup", nsg)
        containment(row, nsg)
        for rule in rules:
            record("NetworkSecurityRule", rule)
            link(nsg["id"], "hasRule", rule["id"])

    for row in entity_rows.get("network_interfaces", []):
        base = _base(row, observed)
        nic = normalize_nic(base, row, observed)
        record("NetworkInterface", nic)
        containment(row, nic)
        if nic.get("subnetId"):
            link(nic["id"], "attachedTo", nic["subnetId"], 0.99)
        if nic.get("nsgId"):
            link(nic["id"], "protectedBy", nic["nsgId"], 0.99)
        if nic.get("attachedResourceId"):
            link(nic["attachedResourceId"], "hasNetworkInterface", nic["id"], 0.99)

    for row in entity_rows.get("network_route_tables", []):
        base = _base(row, observed)
        table, routes = normalize_route_table(base, row, observed)
        record("RouteTable", table)
        containment(row, table)
        for route in routes:
            record("Route", route)
            link(table["id"], "hasRoute", route["id"])

    for row in entity_rows.get("network_firewalls", []):
        base = _base(row, observed)
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

    for row in entity_rows.get("network_firewall_policies", []):
        base = _base(row, observed)
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

    for row in entity_rows.get("network_private_endpoints", []):
        base = _base(row, observed)
        endpoint = normalize_private_endpoint(base, row, observed)
        record("PrivateEndpoint", endpoint)
        containment(row, endpoint)
        if endpoint.get("subnetId"):
            link(endpoint["id"], "attachedTo", endpoint["subnetId"], 0.99)
        if endpoint.get("targetResourceId"):
            link(endpoint["id"], "exposesPrivately", endpoint["targetResourceId"], 0.98)

    dns_zones: dict[str, dict[str, Any]] = {}
    dns_links: list[tuple[str, str]] = []
    for row in entity_rows.get("network_private_dns_zones", []):
        base = _base(row, observed)
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

    for row in entity_rows.get("network_gateways", []):
        base = _base(row, observed)
        gateway = normalize_gateway(base, row, observed)
        record("NetworkGateway", gateway)
        containment(row, gateway)
        if gateway.get("subnetId"):
            link(gateway["id"], "attachedTo", gateway["subnetId"], 0.99)
        elif gateway.get("vnetId"):
            link(gateway["id"], "attachedTo", gateway["vnetId"], 0.95)

    for row in entity_rows.get("network_load_balancers", []):
        base = _base(row, observed)
        balancer = normalize_load_balancer(base, row, observed)
        record("LoadBalancer", balancer)
        containment(row, balancer)
        if balancer.get("subnetId"):
            link(balancer["id"], "attachedTo", balancer["subnetId"], 0.99)
        for backend in balancer.get("backendResourceIds", []):
            link(balancer["id"], "loadBalances", backend, 0.9)

    # Port of ``normalize.normalize()``'s ``known_entity_ids`` dangling-edge
    # filter (src/onboarding/graph_normalize.py). Without this,
    # any edge whose subject/object was never actually emitted as an entity
    # (e.g. a reference to a resource type outside this pipeline's coverage)
    # would be written straight to the topology_edges Delta table / Fabric IQ
    # ontology by the sync path, unlike AIOps's engine which always
    # drops such edges before publication (CR-01, 08-REVIEW.md).
    known_entity_ids = set(entities.keys())
    filtered_edges = [
        edge
        for edge in edges.values()
        if edge["subjectId"] in known_entity_ids and edge["objectId"] in known_entity_ids
    ]
    return list(entities.values()), filtered_edges


def _add_edge(
    index: dict[str, dict[str, Any]],
    subject: str,
    predicate: str,
    obj: str,
    source: str,
    observed: str,
    confidence: float,
) -> None:
    """Byte-for-byte port of ``normalize._add_edge``'s ID derivation.

    Same hash input order (``subject|predicate|object|source``), same
    truncation (24 hex chars of sha256), same envelope fields -- this is
    the exact scheme the 08-03 comparison harness checks for equality
    against AIOps's own edge index.
    """
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
        "schemaVersion": _SCHEMA_VERSION,
    }


def _base(row: Mapping[str, Any], observed: str) -> dict[str, Any]:
    """Mirrors ``normalize._base`` exactly (same field names/values)."""
    source_id = _lower(row.get("id")) or _lower(row.get("name"))
    display_name = str(row.get("name") or source_id.rsplit("/", 1)[-1])
    return {
        "id": source_id,
        "name": display_name,
        "displayName": display_name,
        "tenantId": str(row.get("tenantId") or ""),
        "subscriptionId": str(row.get("subscriptionId") or ""),
        "sourceSystem": SOURCE_TAG,
        "sourceId": str(row.get("id") or row.get("name") or ""),
        "createdTimestamp": observed,
        "lastObservedTimestamp": observed,
        "schemaVersion": _SCHEMA_VERSION,
        "resourceType": _lower(row.get("type")),
        "tags": row.get("tags") or {},
    }


def _to_topology_entity_row(entity_type: str, entity: dict[str, Any]) -> dict[str, Any]:
    import json

    attributes = {
        key: value
        for key, value in entity.items()
        if key
        not in {
            "id",
            "name",
            "displayName",
            "tenantId",
            "subscriptionId",
            "sourceSystem",
            "sourceId",
            "createdTimestamp",
            "lastObservedTimestamp",
            "schemaVersion",
        }
    }
    return {
        "entity_id": entity["id"],
        "entity_type": entity_type,
        "name": entity["name"],
        "display_name": entity["displayName"],
        "tenant_id": entity["tenantId"],
        "subscription_id": entity["subscriptionId"],
        "source_system": entity["sourceSystem"],
        "source_id": entity["sourceId"],
        "created_timestamp": entity["createdTimestamp"],
        "last_observed_timestamp": entity["lastObservedTimestamp"],
        "schema_version": entity["schemaVersion"],
        "attributes_json": json.dumps(attributes, sort_keys=True, separators=(",", ":")),
    }


def to_topology_edge_row(edge: Mapping[str, Any]) -> dict[str, Any]:
    """Maps a AIOps-style camelCase edge dict onto the Delta table schema."""
    return {
        "relationship_id": edge["relationshipId"],
        "subject_id": edge["subjectId"],
        "predicate": edge["predicate"],
        "object_id": edge["objectId"],
        "confidence": edge["confidence"],
        "source": edge["source"],
        "created_timestamp": edge["createdTimestamp"],
        "last_observed_timestamp": edge["lastObservedTimestamp"],
        "assertion_state": edge["assertionState"],
        "schema_version": edge["schemaVersion"],
    }


@dataclass(frozen=True)
class TopologyTableWrite:
    table_name: str
    table_uri: str
    result: DeltaWriteResult


@dataclass
class TopologyOneLakePublisher:
    """Writes derived topology rows to governed OneLake Delta tables.

    Deliberately reuses the exact ``DeltaWriter``/``OneLakeWriter`` machinery
    ``InventoryOneLakePublisher`` uses (Don't Hand-Roll) -- this pipeline adds
    no new writer, only new contracts/rows for the existing writer to persist.
    """

    onelake: OneLakeWriter
    delta_writer: DeltaWriter = field(default_factory=DeltaWriter)

    def publish_entities(self, rows: list[dict]) -> TopologyTableWrite:
        return self._publish(TOPOLOGY_ENTITIES_CONTRACT, rows)

    def publish_edges(self, rows: list[dict]) -> TopologyTableWrite:
        return self._publish(TOPOLOGY_EDGES_CONTRACT, rows)

    def _publish(
        self, contract: TopologyFabricContract, rows: list[dict]
    ) -> TopologyTableWrite:
        table_uri = self.onelake.table_uri(
            "topology", contract.table_name.removeprefix("topology_")
        )
        result = self.delta_writer.write(
            table_uri,
            rows,
            mode=DeltaWriteMode.OVERWRITE,
            key_columns=contract.identity_fields,
            schema=contract.schema,
            required_columns=contract.required_fields,
        )
        return TopologyTableWrite(
            table_name=contract.table_name,
            table_uri=table_uri,
            result=result,
        )


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _resource_group_key(row: Mapping[str, Any]) -> str:
    """Byte-for-byte port of ``normalize._resource_group_key``."""
    source_id = _lower(row.get("id"))
    if "/resourcegroups/" in source_id:
        return source_id.split("/providers/", 1)[0]
    subscription = str(row.get("subscriptionId") or "")
    group = str(row.get("resourceGroup") or row.get("name") or "")
    if subscription and group:
        return f"/subscriptions/{subscription}/resourcegroups/{group}".lower()
    return ""


def _subscription_key(row: Mapping[str, Any]) -> str:
    """Byte-for-byte port of ``normalize._subscription_key``."""
    subscription = str(
        row.get("subscriptionId") or _subscription_from_id(row.get("id")) or "unknown"
    ).lower()
    return f"/subscriptions/{subscription}"


def _subscription_from_id(value: Any) -> str:
    """Byte-for-byte port of ``normalize._subscription_from_id``."""
    parts = str(value or "").split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        return ""


__all__ = [
    "SOURCE_TAG",
    "TopologyOneLakePublisher",
    "TopologyTableWrite",
    "derive_edges",
    "to_topology_edge_row",
]
