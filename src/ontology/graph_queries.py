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

_SERVER_ENTITY_TYPES = {"Resource", "VirtualMachine", "ArcServer"}
_EXACT_IMAGE_PATH = (
    ("VulnerabilityObservation", "identifies", "CVE"),
    ("VulnerabilityObservation", "affects", "ImageDigest"),
    ("ImageDigest", "deployedAs", "WorkloadDeployment"),
)


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
        if "cve" in normalized and "workload" in normalized:
            impact = self.image_vulnerability_impact(
                entity or _extract_cve(question)
            )
            return {
                "question": question,
                "count": impact["total_count"],
                "returned": impact["represented_count"],
                "truncated": False,
                **impact,
            }
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

    def image_vulnerability_impact(self, cve_id: str) -> dict[str, Any]:
        """Return only exact, complete CVE-to-workload evidence paths.

        Mutable image aliases and generic graph reachability are intentionally
        not consulted. A workload is represented only by the approved typed
        path and only when its deployment edge and source checkpoints are
        complete. Missing, stale, or partial checkpoint evidence contributes
        explicit exclusion metadata instead of a guessed deployment.
        """

        if not isinstance(cve_id, str) or not cve_id.strip():
            raise ValueError("CVE id must be a non-empty string")
        normalized_cve = cve_id.strip().upper()
        cve_nodes = {
            entity_id
            for entity_id, row in self.entities.items()
            if row.get("entity_type") == "CVE"
            and (
                str(row.get("name") or "").strip().upper() == normalized_cve
                or str(_payload_mapping(row).get("cve_id") or "")
                .strip()
                .upper()
                == normalized_cve
            )
        }
        observation_edges = {
            edge["subject_id"]: edge
            for cve_node in cve_nodes
            for edge in self.incoming[cve_node]
            if _typed_edge(edge, _EXACT_IMAGE_PATH[0])
        }
        excluded_reasons: defaultdict[str, int] = defaultdict(int)
        digest_observations: dict[str, list[str]] = defaultdict(list)
        for observation_id in sorted(observation_edges):
            observation = self.entities.get(observation_id)
            if observation is None or not _exact_observation_evidence(
                observation,
                observation_edges[observation_id],
                normalized_cve,
            ):
                excluded_reasons["invalid_exact_evidence"] += 1
                continue
            exact_digest_found = False
            for edge in self.outgoing[observation_id]:
                if not _typed_edge(edge, _EXACT_IMAGE_PATH[1]):
                    continue
                digest = self.entities.get(edge["object_id"])
                if digest is None or not _exact_observation_digest_edge(
                    observation,
                    digest,
                    edge,
                ):
                    continue
                exact_digest_found = True
                digest_observations[edge["object_id"]].append(observation_id)
            if not exact_digest_found:
                excluded_reasons["invalid_exact_evidence"] += 1

        items_by_deployment: dict[str, dict[str, Any]] = {}
        for digest_id in sorted(digest_observations):
            digest = self.entities.get(digest_id)
            if digest is None or digest.get("entity_type") != "ImageDigest":
                continue
            digest_payload = _payload_mapping(digest)
            coverage = _coverage_for_digest(digest_payload)
            coverage_complete = bool(coverage) and all(
                str(row.get("completeness") or row.get("status") or "")
                .casefold()
                in {"complete", "healthy-empty"}
                for row in coverage
            )
            unknown_counts = _coverage_unknown_counts(coverage)
            deployment_edges = [
                edge
                for edge in self.outgoing[digest_id]
                if _typed_edge(edge, _EXACT_IMAGE_PATH[2])
            ]
            represented_for_digest = 0
            for edge in deployment_edges:
                deployment = self.entities.get(edge["object_id"])
                if deployment is None:
                    continue
                deployment_payload = _payload_mapping(deployment)
                edge_evidence = _payload_mapping(edge)
                fabric_row = deployment_payload.get("fabric_row")
                exact = _exact_deployment_edge(
                    digest_id=digest_id,
                    digest_payload=digest_payload,
                    deployment=deployment,
                    deployment_payload=deployment_payload,
                    edge_evidence=edge_evidence,
                    coverage=coverage,
                )
                if not exact or not isinstance(fabric_row, Mapping):
                    excluded_reasons["invalid_exact_evidence"] += 1
                    continue
                if not coverage_complete:
                    continue
                if bool(fabric_row.get("carried_forward")):
                    excluded_reasons["stale_workload_evidence"] += 1
                    continue
                observation = self.entities[
                    digest_observations[digest_id][0]
                ]
                observation_payload = _payload_mapping(observation)
                observation_row = observation_payload.get("fabric_row")
                if not isinstance(observation_row, Mapping):
                    excluded_reasons["invalid_exact_evidence"] += 1
                    continue
                evidence_refs = [
                    str(value)
                    for value in observation_payload.get("evidence_refs") or ()
                    if str(value)
                ]
                deployment_key = str(
                    deployment_payload.get("fabric_key") or ""
                )
                items_by_deployment[deployment_key] = {
                    "deployment_id": deployment_key,
                    "image_digest": str(
                        fabric_row.get("image_digest")
                        or digest_payload.get("digest")
                        or ""
                    ),
                    "observation_id": str(
                        evidence_refs[0]
                        if evidence_refs
                        else observation_payload.get("fabric_key") or ""
                    ),
                    "effective_generation": str(
                        edge_evidence.get("effective_generation") or ""
                    ),
                    "event_interval": dict(
                        edge_evidence.get("event_interval") or {}
                    ),
                    "provenance": dict(
                        edge_evidence.get("provenance") or {}
                    ),
                    "path": [
                        f"{subject}:{predicate}:{obj}"
                        for subject, predicate, obj in _EXACT_IMAGE_PATH
                    ],
                }
                represented_for_digest += 1
            if not coverage_complete:
                if unknown_counts:
                    for reason, count in unknown_counts.items():
                        excluded_reasons[reason] += count
                else:
                    excluded_reasons["incomplete_workload_evidence"] += max(
                        1,
                        len(deployment_edges),
                    )

        represented_count = len(items_by_deployment)
        excluded_count = sum(excluded_reasons.values())
        return {
            "cve_id": normalized_cve,
            "represented_count": represented_count,
            "total_count": represented_count + excluded_count,
            "excluded_count": excluded_count,
            "excluded_reasons": dict(sorted(excluded_reasons.items())),
            "completeness": (
                "complete" if excluded_count == 0 else "unknown"
            ),
            "items": [
                items_by_deployment[key]
                for key in sorted(items_by_deployment)
            ],
        }

    def server_vulnerability_impact(
        self,
        cve_id: str,
    ) -> list[dict[str, Any]]:
        """Return server targets for a CVE without admitting image vertices."""

        if not isinstance(cve_id, str) or not cve_id.strip():
            raise ValueError("CVE id must be a non-empty string")
        normalized_cve = cve_id.strip().upper()
        cve_nodes = {
            entity_id
            for entity_id, row in self.entities.items()
            if row.get("entity_type") == "CVE"
            and str(row.get("name") or "").strip().upper() == normalized_cve
        }
        observations = {
            edge["subject_id"]
            for cve_node in cve_nodes
            for edge in self.incoming[cve_node]
            if edge.get("predicate") == "identifies"
            and edge.get("subject_type") == "VulnerabilityObservation"
            and edge.get("object_type") == "CVE"
        }
        target_ids = {
            edge["object_id"]
            for observation in observations
            for edge in self.outgoing[observation]
            if edge.get("predicate") == "affects"
            and edge.get("subject_type") == "VulnerabilityObservation"
            and edge.get("object_type") in _SERVER_ENTITY_TYPES
        }
        return self._rows(target_ids, types=_SERVER_ENTITY_TYPES)

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


def _typed_edge(
    row: Mapping[str, Any],
    expected: tuple[str, str, str],
) -> bool:
    return (
        str(row.get("subject_type") or ""),
        str(row.get("predicate") or ""),
        str(row.get("object_type") or ""),
    ) == expected


def _payload_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("payload_json")
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coverage_for_digest(
    digest_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fabric_row = digest_payload.get("fabric_row")
    connection_id = (
        str(fabric_row.get("connection_id") or "")
        if isinstance(fabric_row, Mapping)
        else ""
    )
    checkpoints = [
        dict(row)
        for row in digest_payload.get("coverage_checkpoints") or ()
        if isinstance(row, Mapping)
    ]
    if not connection_id:
        return checkpoints
    return [
        row
        for row in checkpoints
        if str(row.get("connection_id") or "") == connection_id
    ]


def _coverage_unknown_counts(
    checkpoints: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for checkpoint in checkpoints:
        value = checkpoint.get("unknown_reason_counts_json")
        try:
            parsed = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, Mapping):
            for reason, count in parsed.items():
                if (
                    isinstance(count, int)
                    and not isinstance(count, bool)
                    and count > 0
                ):
                    counts[str(reason)] += count
    return dict(counts)


def _exact_observation_evidence(
    observation: Mapping[str, Any],
    identifies_edge: Mapping[str, Any],
    cve_id: str,
) -> bool:
    payload = _payload_mapping(observation)
    fabric_row = payload.get("fabric_row")
    evidence = _payload_mapping(identifies_edge)
    if not isinstance(fabric_row, Mapping):
        return False
    fabric_key = str(payload.get("fabric_key") or "")
    fabric_identity = str(
        fabric_row.get("container_exposure_id")
        or fabric_row.get("vulnerability_observation_id")
        or ""
    )
    evidence_refs = {
        str(value)
        for value in payload.get("evidence_refs") or ()
        if str(value)
    }
    return (
        observation.get("entity_type") == "VulnerabilityObservation"
        and payload.get("target_kind") == "container_image"
        and fabric_row.get("target_kind") == "container_image"
        and str(fabric_row.get("cve_id") or "").strip().upper() == cve_id
        and fabric_identity == fabric_key
        and (
            bool(evidence_refs)
            if fabric_row.get("container_exposure_id")
            else True
        )
        and str(evidence.get("evidence_identity") or "") == fabric_key
    )


def _exact_observation_digest_edge(
    observation: Mapping[str, Any],
    digest: Mapping[str, Any],
    edge: Mapping[str, Any],
) -> bool:
    observation_payload = _payload_mapping(observation)
    digest_payload = _payload_mapping(digest)
    observation_row = observation_payload.get("fabric_row")
    digest_row = digest_payload.get("fabric_row")
    evidence = _payload_mapping(edge)
    if not isinstance(observation_row, Mapping) or not isinstance(
        digest_row,
        Mapping,
    ):
        return False
    return (
        digest.get("entity_type") == "ImageDigest"
        and digest_payload.get("target_kind") == "container_image"
        and observation_payload.get("ontology_target_id")
        == digest.get("resource_id")
        and observation_row.get("image_digest_id")
        == digest_row.get("image_digest_id")
        and str(observation_row.get("image_digest") or "").casefold()
        == str(digest_row.get("image_digest") or "").casefold()
        and evidence.get("evidence_identity")
        == observation_payload.get("fabric_key")
    )


def _exact_deployment_edge(
    *,
    digest_id: str,
    digest_payload: Mapping[str, Any],
    deployment: Mapping[str, Any],
    deployment_payload: Mapping[str, Any],
    edge_evidence: Mapping[str, Any],
    coverage: Iterable[Mapping[str, Any]],
) -> bool:
    fabric_row = deployment_payload.get("fabric_row")
    digest_row = digest_payload.get("fabric_row")
    if not isinstance(fabric_row, Mapping) or not isinstance(
        digest_row,
        Mapping,
    ):
        return False
    checkpoint = next(
        (
            row
            for row in coverage
            if row.get("checkpoint_key") == fabric_row.get("checkpoint_key")
        ),
        None,
    )
    if checkpoint is None:
        return False
    try:
        provenance = json.loads(str(fabric_row.get("provenance_json") or "{}"))
    except json.JSONDecodeError:
        return False
    expected_interval = {
        "from": str(fabric_row.get("defender_observed_at") or ""),
        "to": str(fabric_row.get("observed_at") or ""),
    }
    return (
        deployment.get("entity_type") == "WorkloadDeployment"
        and deployment_payload.get("workload_state") == "observed-exact-digest"
        and deployment_payload.get("digest_entity_id") == digest_id
        and str(fabric_row.get("deployment_id") or "")
        == str(deployment_payload.get("fabric_key") or "")
        and str(fabric_row.get("image_digest") or "").casefold()
        == str(digest_row.get("image_digest") or "").casefold()
        and not fabric_row.get("unknown_reason")
        and edge_evidence.get("evidence_identity")
        == deployment_payload.get("fabric_key")
        and edge_evidence.get("event_interval") == expected_interval
        and edge_evidence.get("provenance") == provenance
        and edge_evidence.get("effective_generation")
        == fabric_row.get("effective_generation")
        == checkpoint.get("effective_generation")
        and str(edge_evidence.get("completeness") or "").casefold()
        == str(
            checkpoint.get("completeness")
            or checkpoint.get("status")
            or ""
        ).casefold()
    )


def _extract_cve(question: str) -> str:
    for word in question.strip().rstrip(".?!").split():
        candidate = word.strip(",:;()[]{}").upper()
        if candidate.startswith("CVE-"):
            return candidate
    return ""


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
