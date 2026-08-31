from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from typing import Any

from .ontology_validator import OntologyValidator

ASSET_TYPES = {
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "KubernetesCluster",
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

# Predicates that carry network reachability, grouped by the direction traffic
# flows relative to the edge. Reachability is NOT the same as the structural
# containment used by _impact: an application depending on another says nothing
# about whether a packet can traverse between them.
#
# Forward edges are walked subject -> object (a subnet's egress gateway is
# reachable *from* the subnet). Reverse edges are walked object -> subject
# (a NIC attached to a subnet means the subnet reaches the NIC).
_REACHABILITY_FORWARD = {
    "egressesVia",
    "hasPeering",
    "peersWith",
    "attachedTo",
    "hasNetworkInterface",
    # A private endpoint is a network presence *for* a backing resource, so
    # reaching the endpoint means reaching what it fronts.
    "exposesPrivately",
    "loadBalances",
}
_REACHABILITY_REVERSE = {
    "attachedTo",
    "hasNetworkInterface",
    "contains",
    "exposesPrivately",
    "loadBalances",
}

# Entities that represent a boundary between the virtual network and something
# outside it. The ontology collapses six distinct Azure gateway types into one
# ``NetworkGateway`` entity, but they do not all mean the same thing for
# exposure, so the direction is recovered from the ARM resource type:
#
#   inbound  - traffic can originate outside and land on the workload
#   outbound - the workload can initiate traffic to the internet
#   internal - a boundary-shaped resource that is neither (e.g. a DNS resolver)
#
# Reporting the direction rather than collapsing everything to "exposed" keeps
# the finding actionable: a NAT gateway is an egress path, not an open door.
_BOUNDARY_DIRECTION_BY_RESOURCE_TYPE = {
    "microsoft.network/virtualnetworkgateways": "inbound",
    "microsoft.network/vpngateways": "inbound",
    "microsoft.network/expressroutegateways": "inbound",
    "microsoft.network/expressroutecircuits": "inbound",
    "microsoft.network/bastionhosts": "inbound",
    "microsoft.network/azurefirewalls": "inbound",
    "microsoft.network/loadbalancers": "inbound",
    "microsoft.network/applicationgateways": "inbound",
    "microsoft.network/publicipaddresses": "inbound",
    "microsoft.network/natgateways": "outbound",
    "microsoft.network/dnsresolvers": "internal",
}

# Fallback when an entity carries no resource_type (sub-resources, or rows
# projected without it). Direction is unknown, so these are reported as
# "unknown" rather than silently dropped - an unclassifiable boundary is a
# finding a reviewer should see, not one the engine should decide is safe.
_BOUNDARY_TYPES = {
    "NetworkGateway",
    "AzureFirewall",
    "LoadBalancer",
    "PublicIp",
    "PublicIPAddress",
}


class OntologyQueryService:
    """Read-only deterministic traversals over Fabric-backed ontology projections."""

    def __init__(
        self,
        entities: Iterable[dict[str, Any]],
        relationships: Iterable[dict[str, Any]],
        *,
        max_source_entities: int = 50_000,
        max_source_relationships: int = 100_000,
        max_results: int = 100,
        max_traversal_nodes: int = 1_000,
    ) -> None:
        for name, value in (
            ("max_source_entities", max_source_entities),
            ("max_source_relationships", max_source_relationships),
            ("max_results", max_results),
            ("max_traversal_nodes", max_traversal_nodes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"Ontology query {name} must be a positive integer")
        entity_rows = list(entities)
        relationship_rows = list(relationships)
        if len(entity_rows) > max_source_entities:
            raise ValueError("Ontology query entity source exceeds configured bound")
        if len(relationship_rows) > max_source_relationships:
            raise ValueError("Ontology query relationship source exceeds configured bound")
        if any(not isinstance(row, Mapping) for row in entity_rows):
            raise TypeError("Ontology query entities must be mappings")
        if any(not isinstance(row, Mapping) for row in relationship_rows):
            raise TypeError("Ontology query relationships must be mappings")
        if not OntologyValidator().validate(entity_rows, relationship_rows).passed:
            raise ValueError("Ontology query graph validation failed")
        active_entities = [
            dict(row)
            for row in entity_rows
            if row.get("lifecycle_status", "active") == "active"
        ]
        canonical_ids = [str(row.get("resource_id") or "").casefold() for row in active_entities]
        if len(canonical_ids) != len(set(canonical_ids)):
            raise ValueError("Ontology query entities contain canonical duplicates")
        self.entities = {
            str(row["resource_id"]).casefold(): {**row, "resource_id": str(row["resource_id"]).casefold()}
            for row in active_entities
        }
        active_relationships = [
            dict(row)
            for row in relationship_rows
            if row.get("lifecycle_status", "active") == "active"
        ]
        relationship_ids = [
            str(row.get("resource_id") or "").casefold()
            for row in active_relationships
        ]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("Ontology query relationships contain canonical duplicates")
        if any(
            not all(
                isinstance(row.get(field), str) and bool(row[field].strip())
                for field in ("resource_id", "subject_id", "predicate", "object_id")
            )
            for row in active_relationships
        ):
            raise ValueError("Ontology query relationships are malformed")
        self.relationships = [
            {
                **row,
                "resource_id": str(row.get("resource_id") or "").casefold(),
                "subject_id": str(row.get("subject_id") or "").casefold(),
                "object_id": str(row.get("object_id") or "").casefold(),
            }
            for row in active_relationships
        ]
        if any(
            row["subject_id"] not in self.entities or row["object_id"] not in self.entities
            for row in self.relationships
        ):
            raise ValueError("Ontology query relationships contain dangling endpoints")
        self.max_results = max_results
        self.max_traversal_nodes = max_traversal_nodes
        self._traversal_truncated = False
        self.outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self.relationships:
            self.outgoing[row["subject_id"]].append(row)
            self.incoming[row["object_id"]].append(row)

    def answer(self, question: str, *, entity: str = "") -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Ontology question must be a non-empty string")
        if not isinstance(entity, str):
            raise TypeError("Ontology entity selector must be a string")
        self._traversal_truncated = False
        normalized = " ".join(question.strip().rstrip(".?!").casefold().split())
        roots = self._find(entity or _extract_subject(question))
        if "missing ownership" in normalized or "without owners" in normalized:
            items = self._missing_ownership()
        elif "orphan infrastructure" in normalized:
            items = self._orphans()
        elif "patch failures" in normalized and ("application" in normalized or "service" in normalized):
            types = (
                {"Application"}
                if "application" in normalized
                else {"Service", "BusinessService"}
            )
            items = self._affected_by_patch_failures(types)
        elif "compliance by application" in normalized:
            items = self._compliance_by_application()
        elif "business service owns" in normalized or "what business service" in normalized:
            items = self._business_services_for(roots)
        elif "who owns" in normalized or "vm ownership" in normalized:
            items = self._owners(roots)
        elif "belong to" in normalized and "vm" in normalized:
            items = self._neighbors(roots, predicates={"member_of"})
        elif "resources belong" in normalized or "business service" in normalized and "resources" in normalized:
            items = self._resources_for_context(roots)
        elif "dependencies" in normalized or "topology" in normalized:
            items = self._application_topology(roots)
        elif "network exposure" in normalized or "internet reachable" in normalized:
            items = self._network_exposure(roots)
        elif "network reachable" in normalized or "network blast radius" in normalized:
            items = self._network_reachable(roots)
        elif "impacted business service" in normalized:
            items = self._impact(roots, types={"BusinessService"})
        elif "impacted" in normalized or "server fails" in normalized:
            items = self._impact(roots)
        else:
            raise ValueError(
                "Supported ontology queries: application dependencies; VM ownership; application topology; "
                "impacted business services; resources without owners; orphan infrastructure; "
                "compliance by application; patch failures by service; network reachable; "
                "network exposure"
            )
        returned = items[: self.max_results]
        return {
            "question": question,
            "count": len(items),
            "returned": len(returned),
            "truncated": self._traversal_truncated or len(returned) < len(items),
            "items": returned,
        }

    def _find(self, value: str) -> set[str]:
        needle = value.casefold().strip()
        if not needle:
            return set()
        return {
            entity_id
            for entity_id, row in self.entities.items()
            if needle in {entity_id.casefold(), str(row.get("name") or "").casefold()}
            or needle in str(row.get("name") or "").casefold()
        }

    def _neighbors(self, roots: set[str], *, predicates: set[str]) -> list[dict[str, Any]]:
        ids: set[str] = set()
        for root in roots:
            ids.update(
                edge["object_id"] for edge in self.outgoing[root] if edge["predicate"] in predicates
            )
            ids.update(
                edge["subject_id"] for edge in self.incoming[root] if edge["predicate"] in predicates
            )
        return self._rows(ids)

    def _owners(self, roots: set[str]) -> list[dict[str, Any]]:
        owner_ids: set[str] = set()
        for entity_id in roots:
            owner_ids.update(
                edge["object_id"]
                for edge in self.outgoing[entity_id]
                if edge["predicate"] == "owned_by"
            )
            owner_ids.update(
                edge["subject_id"]
                for edge in self.incoming[entity_id]
                if edge["predicate"] == "owns"
            )
        return self._rows(owner_ids, types={"Owner"})


    def _business_services_for(self, roots: set[str]) -> list[dict[str, Any]]:
        applications = self._application_ids(roots)
        ids = {
            edge["object_id"]
            for root in roots
            for edge in self.outgoing[root]
            if edge["predicate"] == "belongs_to"
        }
        ids.update(
            edge["subject_id"]
            for application in applications
            for edge in self.incoming[application]
            if edge["predicate"] in {"contains", "owns"}
            and edge.get("subject_type") == "BusinessService"
        )
        return self._rows(ids, types={"BusinessService"})

    def _resources_for_context(self, roots: set[str]) -> list[dict[str, Any]]:
        applications: set[str] = set()
        resources: set[str] = set()
        for root in roots:
            root_type = self.entities[root]["entity_type"]
            if root_type == "BusinessService":
                applications.update(
                    edge["object_id"]
                    for edge in self.outgoing[root]
                    if edge["predicate"] == "contains"
                )
                resources.update(
                    edge["subject_id"]
                    for edge in self.incoming[root]
                    if edge["predicate"] == "belongs_to"
                )
            elif root_type == "Service":
                applications.update(
                    edge["subject_id"]
                    for edge in self.incoming[root]
                    if edge["predicate"] == "implements"
                )
                resources.update(
                    edge["subject_id"]
                    for edge in self.incoming[root]
                    if edge["predicate"] == "provides"
                )
            elif root_type == "Application":
                applications.add(root)
        resources.update(
            edge["object_id"]
            for application in applications
            for edge in self.outgoing[application]
            if edge["predicate"] == "hosted_on"
        )
        return self._rows(resources, types=ASSET_TYPES)

    def _application_topology(self, roots: set[str]) -> list[dict[str, Any]]:
        applications = self._application_ids(roots)
        ids: set[str] = set()
        allowed = {"depends_on", "hosted_on", "implements", "deployed_in"}
        for application in applications:
            ids.update(
                edge["object_id"]
                for edge in self.outgoing[application]
                if edge["predicate"] in allowed
            )
            ids.update(
                edge["subject_id"]
                for edge in self.incoming[application]
                if edge["predicate"] in {"depends_on", "supports", "contains"}
            )
        return self._rows(ids | applications - roots)

    def _impact(
        self, roots: set[str], types: set[str] | None = None
    ) -> list[dict[str, Any]]:
        discovered = self._application_ids(roots)
        self._traversal_truncated = (
            self._traversal_truncated
            or len(discovered) > self.max_traversal_nodes
        )
        applications = set(sorted(discovered)[: self.max_traversal_nodes])
        queue = deque(applications)
        while queue:
            application = queue.popleft()
            for edge in self.incoming[application]:
                if edge["predicate"] == "depends_on" and edge["subject_id"] not in applications:
                    if len(applications) >= self.max_traversal_nodes:
                        self._traversal_truncated = True
                        continue
                    applications.add(edge["subject_id"])
                    queue.append(edge["subject_id"])
        ids = set(applications)
        ids.update(
            edge["subject_id"]
            for application in applications
            for edge in self.incoming[application]
            if edge["predicate"] in {"contains", "owns"}
            and edge.get("subject_type") == "BusinessService"
        )
        ids.update(
            edge["object_id"]
            for application in applications
            for edge in self.outgoing[application]
            if edge["predicate"] == "implements"
        )
        ids.update(
            edge["object_id"]
            for root in roots
            for edge in self.outgoing[root]
            if edge["predicate"] in {"belongs_to", "provides"}
        )
        return self._rows(ids - roots, types=types)

    def _reachable(self, roots: set[str]) -> tuple[set[str], dict[str, list[str]]]:
        """BFS over network-carrying edges, recording the path to each node.

        Returns the reachable set (excluding the roots themselves) and, for each
        node, the shortest edge-predicate path that reached it. The path is what
        makes a finding actionable: "exposed" is an assertion, "exposed via
        subnet -> gateway" is evidence someone can verify or refute.
        """
        seen = set(roots)
        paths: dict[str, list[str]] = {root: [] for root in roots}
        queue = deque(roots)
        while queue:
            current = queue.popleft()
            neighbours: list[tuple[str, str]] = [
                (edge["object_id"], edge["predicate"])
                for edge in self.outgoing[current]
                if edge["predicate"] in _REACHABILITY_FORWARD
            ]
            neighbours.extend(
                (edge["subject_id"], edge["predicate"])
                for edge in self.incoming[current]
                if edge["predicate"] in _REACHABILITY_REVERSE
            )
            for neighbour, predicate in neighbours:
                if neighbour in seen:
                    continue
                if len(seen) >= self.max_traversal_nodes:
                    # Stop expanding, but keep draining the queue so the
                    # truncation flag is set deterministically rather than
                    # depending on which node happened to hit the bound first.
                    self._traversal_truncated = True
                    continue
                seen.add(neighbour)
                paths[neighbour] = [*paths[current], predicate]
                queue.append(neighbour)
        return seen - roots, paths

    def _network_reachable(self, roots: set[str]) -> list[dict[str, Any]]:
        if not roots:
            return []
        reachable, paths = self._reachable(roots)
        rows = []
        for entity_id in reachable:
            if entity_id not in self.entities:
                continue
            row = _public_entity(self.entities[entity_id])
            row["path"] = paths.get(entity_id, [])
            row["hops"] = len(row["path"])
            rows.append(row)
        return sorted(rows, key=lambda row: (row["hops"], row["entity_type"], row["name"]))

    def _network_exposure(self, roots: set[str]) -> list[dict[str, Any]]:
        """Workloads that can reach a network boundary, and in which direction.

        Reports the boundary reached, the direction it carries traffic, and the
        path taken. A workload with no path is simply absent - this is
        deliberately not an assertion that it is safe, only that no boundary was
        found in the modelled graph. A boundary whose direction cannot be
        determined is reported as ``unknown`` rather than dropped.
        """
        if not roots:
            return []
        reachable, paths = self._reachable(roots)
        rows = []
        for entity_id in reachable:
            entity = self.entities.get(entity_id)
            if entity is None or entity["entity_type"] not in _BOUNDARY_TYPES:
                continue
            resource_type = str(entity.get("resource_type") or "").casefold()
            direction = _BOUNDARY_DIRECTION_BY_RESOURCE_TYPE.get(resource_type, "unknown")
            if direction == "internal":
                continue
            row = _public_entity(entity)
            row["path"] = paths.get(entity_id, [])
            row["hops"] = len(row["path"])
            row["direction"] = direction
            row["exposure"] = "reaches_boundary"
            rows.append(row)
        return sorted(rows, key=lambda row: (row["hops"], row["entity_type"], row["name"]))

    def _application_ids(self, roots: set[str]) -> set[str]:
        applications = {
            root for root in roots if self.entities[root]["entity_type"] == "Application"
        }
        applications.update(
            edge["object_id"]
            for root in roots
            for edge in self.outgoing[root]
            if edge["predicate"] == "member_of"
        )
        return applications

    def _missing_ownership(self) -> list[dict[str, Any]]:
        owned = {
            edge["subject_id"] for edge in self.relationships if edge["predicate"] == "owned_by"
        }
        return [
            _public_entity(row)
            for row in self.entities.values()
            if row["entity_type"] in ASSET_TYPES and row["resource_id"] not in owned
        ]

    def _orphans(self) -> list[dict[str, Any]]:
        connected = set(self.outgoing) | set(self.incoming)
        return [
            _public_entity(row)
            for row in self.entities.values()
            if row["entity_type"] in ASSET_TYPES and row["resource_id"] not in connected
        ]

    def _affected_by_patch_failures(
        self, types: set[str] | None = None
    ) -> list[dict[str, Any]]:
        failed = {
            row["resource_id"]
            for row in self.entities.values()
            if row["entity_type"] == "PatchAssessment" and _failed(row)
        }
        servers = {
            edge["object_id"]
            for assessment in failed
            for edge in self.outgoing[assessment]
            if edge["predicate"] == "evaluates"
        }
        impacted = set()
        for server in servers:
            impacted.update(
                edge["object_id"]
                for edge in self.outgoing[server]
                if edge["predicate"] in {"member_of", "belongs_to", "provides"}
            )
        return self._rows(
            impacted, types=types or {"Application", "Service", "BusinessService"}
        )

    def _compliance_by_application(self) -> list[dict[str, Any]]:
        results = []
        for application in self.entities.values():
            if application["entity_type"] != "Application":
                continue
            servers = {
                edge["object_id"]
                for edge in self.outgoing[application["resource_id"]]
                if edge["predicate"] == "hosted_on"
            }
            assessments = [
                self.entities[edge["subject_id"]]
                for server in servers
                for edge in self.incoming[server]
                if edge["predicate"] == "evaluates"
                and edge["subject_id"] in self.entities
            ]
            assessed_servers = {
                edge["object_id"]
                for assessment in assessments
                for edge in self.outgoing[assessment["resource_id"]]
                if edge["predicate"] == "evaluates"
            }
            failed = sum(1 for assessment in assessments if _failed(assessment))
            results.append(
                {
                    "application_id": application["resource_id"],
                    "application_name": application["name"],
                    "server_count": len(servers),
                    "assessed_server_count": len(assessed_servers),
                    "failed_assessment_count": failed,
                    "compliant": bool(servers)
                    and len(assessed_servers) == len(servers)
                    and failed == 0,
                }
            )
        return sorted(results, key=lambda row: row["application_name"])

    def _rows(self, ids: set[str], types: set[str] | None = None) -> list[dict[str, Any]]:
        return sorted(
            (
                _public_entity(self.entities[entity_id])
                for entity_id in ids
                if entity_id in self.entities
                and (types is None or self.entities[entity_id]["entity_type"] in types)
            ),
            key=lambda row: (row["entity_type"], row["name"]),
        )


def _failed(row: dict[str, Any]) -> bool:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return False
    status = str(payload.get("status") or payload.get("assessmentStatus") or "").casefold()
    return status in {"failed", "error", "noncompliant", "non-compliant"} or int(
        payload.get("failedPatchCount") or payload.get("failedPatchInstallations") or 0
    ) > 0


def _extract_subject(question: str) -> str:
    words = question.strip().rstrip(".?!").split()
    return words[-1] if words else ""


def _public_entity(row: dict[str, Any]) -> dict[str, Any]:
    # resource_id / tenant_id / subscription_id are deliberately excluded: an
    # Azure resource id embeds the subscription GUID, so projecting it would
    # leak tenant topology into query answers. See
    # test_query_projection_excludes_raw_inventory_and_lineage.
    return {
        key: row[key]
        for key in (
            "entity_type",
            "name",
            "resource_type",
            "location",
            "lifecycle_status",
        )
        if key in row
    }
