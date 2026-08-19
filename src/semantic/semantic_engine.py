from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics

from intelligence.incident.incident_intelligence import IncidentIntelligence

from .semantic_cache import SemanticCache
from .semantic_indexes import ASSET_TYPES, SemanticIndexes
from .semantic_models import (
    RiskAssessment,
    RiskInputs,
    RiskScorer,
    SemanticContext,
    SemanticEntity,
)
from .semantic_query import SemanticIntent, SemanticQuery
from .semantic_registry import SemanticRegistry
from .semantic_validator import SemanticValidator


class _SemanticTelemetry:
    def __init__(self, meter=None) -> None:
        meter = meter or metrics.get_meter("hermes.operations_graph.semantic", "0.1.0")
        self.query_latency = meter.create_histogram("semantic.query.latency", unit="s")
        self.traversal_latency = meter.create_histogram("semantic.graph.traversal.latency", unit="s")
        self.context_latency = meter.create_histogram("semantic.context.generation.latency", unit="s")
        self.cache_requests = meter.create_counter("semantic.cache.requests")
        self.cache_hit_ratio = meter.create_histogram("semantic.cache.hit_ratio", unit="1")
        self.knowledge_freshness = meter.create_histogram("semantic.knowledge.freshness", unit="s")
        self.ontology_lag = meter.create_histogram("semantic.ontology.synchronization.lag", unit="s")

    def record_cache(self, hit: bool, ratio: float) -> None:
        self.cache_requests.add(1, {"result": "hit" if hit else "miss"})
        self.cache_hit_ratio.record(ratio)


class SemanticEngine:
    """Single read-only knowledge interface over Fabric Ontology projections."""

    def __init__(
        self,
        indexes: SemanticIndexes,
        *,
        knowledge_version: str,
        freshness: str,
        ontology_synchronized_at: str = "",
        registry: SemanticRegistry | None = None,
        cache: SemanticCache | None = None,
        scorer: RiskScorer | None = None,
        validator: SemanticValidator | None = None,
        telemetry=None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_results: int = 50,
        max_traversal_nodes: int = 500,
        max_traversal_depth: int = 32,
        max_source_rows: int = 50000,
        max_serialized_bytes: int = 1_000_000,
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in (
                max_results,
                max_traversal_nodes,
                max_traversal_depth,
                max_source_rows,
            )
        ):
            raise ValueError("Semantic limits must be positive integers")
        if max_traversal_depth > 256:
            raise ValueError("Semantic max_traversal_depth must not exceed 256")
        if (
            isinstance(max_serialized_bytes, bool)
            or not isinstance(max_serialized_bytes, int)
            or max_serialized_bytes < 1024
        ):
            raise ValueError(
                "Semantic max_serialized_bytes must be an integer of at least 1024"
            )
        self.indexes = indexes
        self.knowledge_version = knowledge_version
        self.freshness = self._timestamp(freshness, "freshness")
        self.ontology_synchronized_at = self._timestamp(
            ontology_synchronized_at or freshness,
            "ontology_synchronized_at",
        )
        self.registry = registry or SemanticRegistry.default()
        self.cache = cache or SemanticCache()
        self.scorer = scorer or RiskScorer()
        self.validator = validator or SemanticValidator()
        self.telemetry = telemetry or _SemanticTelemetry()
        self.clock = clock
        self.now = now
        self.max_results = max_results
        self.max_traversal_nodes = max_traversal_nodes
        self.max_traversal_depth = max_traversal_depth
        self.max_source_rows = max_source_rows
        self.max_serialized_bytes = max_serialized_bytes
        snapshot_fingerprint = json.dumps(
            {
                "entities": self.indexes.entities,
                "relationships": self.indexes.relationships,
                "inventory": self.indexes.inventory,
                "compliance": self.indexes.compliance,
                "security": self.indexes.security,
                "cost": self.indexes.cost,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        self.cache_namespace = hashlib.sha256(
            f"{snapshot_fingerprint}:{id(self.scorer)}".encode()
        ).hexdigest()[:24]

    @property
    def knowledge_version(self) -> str:
        return self._knowledge_version

    @knowledge_version.setter
    def knowledge_version(self, value: str) -> None:
        if not value:
            self._knowledge_version = "semantic-unversioned"
        elif value.startswith("semantic-"):
            self._knowledge_version = value
        else:
            digest = hashlib.sha256(value.encode()).hexdigest()[:16]
            self._knowledge_version = f"semantic-{digest}"

    @classmethod
    def from_rows(
        cls,
        *,
        entities: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        inventory: list[dict[str, Any]] | None = None,
        compliance: list[dict[str, Any]] | None = None,
        security: list[dict[str, Any]] | None = None,
        cost: list[dict[str, Any]] | None = None,
        knowledge_version: str = "",
        freshness: str = "",
        ontology_synchronized_at: str = "",
        **kwargs,
    ) -> SemanticEngine:
        max_source_rows = kwargs.get("max_source_rows", 50000)
        if (
            isinstance(max_source_rows, bool)
            or not isinstance(max_source_rows, int)
            or max_source_rows < 1
        ):
            raise ValueError("Semantic max_source_rows must be a positive integer")
        collections = {
            "entities": entities,
            "relationships": relationships,
            "inventory": inventory if inventory is not None else [],
            "compliance": compliance if compliance is not None else [],
            "security": security if security is not None else [],
            "cost": cost if cost is not None else [],
        }
        if any(not isinstance(rows, list) for rows in collections.values()):
            raise TypeError("Semantic snapshot collections must be lists")
        for name, rows in collections.items():
            if any(not isinstance(row, dict) for row in rows):
                raise TypeError(f"Semantic {name} rows must be mappings")
            if len(rows) > max_source_rows:
                raise ValueError(f"Semantic {name} exceeds configured source bound")
        semantic_validator = kwargs.pop("validator", None) or SemanticValidator()
        report = semantic_validator.validate_snapshot(
            entities,
            relationships,
            inventory=inventory,
            compliance=compliance,
            security=security,
            cost=cost,
        )
        if not report.passed:
            raise ValueError("Invalid semantic snapshot: " + "; ".join(report.errors))
        indexes = SemanticIndexes(
            entities,
            relationships,
            inventory=inventory or [],
            compliance=compliance or [],
            security=security or [],
            cost=cost or [],
        )
        return cls(
            indexes,
            knowledge_version=knowledge_version,
            freshness=freshness,
            ontology_synchronized_at=ontology_synchronized_at,
            validator=semantic_validator,
            **kwargs,
        )

    def get_application_context(self, application: str) -> dict[str, Any]:
        return self._cached_context(
            "application",
            application,
            lambda: self._build_application_context(application),
        )

    def get_service_context(
        self, service: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self._cached_context(
            "service",
            f"{subject_type}:{service}",
            lambda: self._build_service_context(
                service, subject_type=subject_type
            ),
        )

    def get_resource_context(
        self, resource: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self._cached_context(
            "resource",
            f"{subject_type}:{resource}",
            lambda: self._build_resource_context(
                resource, subject_type=subject_type
            ),
        )

    def get_subscription_context(self, subscription: str) -> dict[str, Any]:
        return self._cached_context(
            "subscription",
            subscription,
            lambda: self._build_subscription_context(subscription),
        )

    def get_environment_context(self, environment: str) -> dict[str, Any]:
        return self._cached_context(
            "environment",
            environment,
            lambda: self._build_environment_context(environment),
        )

    def application_context(self, application: str) -> dict[str, Any]:
        return self.get_application_context(application)

    def service_context(
        self, service: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self.get_service_context(service, subject_type=subject_type)

    def resource_context(
        self, resource: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self.get_resource_context(resource, subject_type=subject_type)

    def subscription_context(self, subscription: str) -> dict[str, Any]:
        return self.get_subscription_context(subscription)

    def risk_context(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self.get_risk_context(subject, subject_type=subject_type)

    def impact_context(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        return self.get_impact_context(subject, subject_type=subject_type)

    def search(self, query: str) -> dict[str, Any]:
        return self.search_operational_context(query)

    def get_risk_context(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        started = self.clock()
        entity_id = self.indexes.resolve(
            subject, types={subject_type} if subject_type else None
        )
        resources = self._subject_resources(entity_id)
        risk = self._aggregate_risk(resources)
        result = {
            "subject": self.indexes.public(entity_id),
            "risk": risk.to_dict(),
            "freshness": self.freshness,
            "knowledge_version": self.knowledge_version,
        }
        self.telemetry.query_latency.record(self.clock() - started, {"intent": "risk"})
        self._record_freshness()
        return self._bounded_public(result)

    def get_impact_context(
        self, subject: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        key = self._cache_key(
            f"impact:{subject_type.casefold()}:{subject.casefold()}"
        )
        cached = self.cache.get(key, knowledge_version=self.knowledge_version)
        self.telemetry.record_cache(cached is not None, self.cache.stats().hit_ratio)
        if cached is not None:
            return cached
        started = self.clock()
        impact_types = {
            "PatchAssessment",
            "Subscription",
            "Application",
            *ASSET_TYPES,
        }
        root_id = self.indexes.resolve(
            subject, types={subject_type} if subject_type else impact_types
        )
        root = self.indexes.entities[root_id]
        cause_type = str(root.get("entity_type") or "")
        resources: set[str]
        if cause_type == "PatchAssessment":
            resources = set(
                self.indexes.related(root_id, "evaluates", types=ASSET_TYPES)
            )
        elif cause_type == "Subscription":
            subscription_id = str(root.get("subscription_id") or root.get("name") or "")
            marker = f"/subscriptions/{subscription_id.casefold()}/"
            resources = {
                entity_id
                for entity_id in self.indexes.by_type.get("VirtualMachine", [])
                + self.indexes.by_type.get("ArcServer", [])
                + self.indexes.by_type.get("KubernetesCluster", [])
                + self.indexes.by_type.get("Resource", [])
                if marker in entity_id.casefold()
            }
        elif cause_type == "Application":
            resources = set(self.indexes.resources_for_application(root_id))
        elif cause_type in ASSET_TYPES:
            resources = {root_id}
        else:
            resources = set()
        discovered_applications = {
            application
            for resource_id in resources
            for application in self.indexes.applications_for_resource(resource_id)
        }
        discovered_applications.update(
            {root_id} if cause_type == "Application" else set()
        )
        graph_truncated = len(discovered_applications) > self.max_traversal_nodes
        applications = set(
            sorted(discovered_applications)[: self.max_traversal_nodes]
        )
        direct_applications = set(applications)
        queue = deque(applications)
        while queue:
            application_id = queue.popleft()
            for dependent in self.indexes.downstream_dependents(application_id):
                if dependent not in applications:
                    if len(applications) >= self.max_traversal_nodes:
                        graph_truncated = True
                        break
                    applications.add(dependent)
                    queue.append(dependent)
        business_services = {
            service
            for application_id in applications
            for service in self.indexes.business_services_for_application(application_id)
        }
        services = {
            service
            for application_id in applications
            for service in self.indexes.related(
                application_id, "implements", types={"Service"}
            )
        }
        application_rows = self._public_rows(applications)
        business_rows = self._public_rows(business_services)
        service_rows = self._public_rows(services)
        tree_budget = {
            "remaining": self.max_traversal_nodes
            - (0 if cause_type == "Application" else 1),
            "truncated": False,
        }
        if cause_type == "Application":
            tree = self._impact_application_node(root_id, set(), budget=tree_budget)
        else:
            children = [
                node
                for application_id in sorted(direct_applications)
                if (
                    node := self._impact_application_node(
                        application_id, set(), budget=tree_budget
                    )
                )
                is not None
            ]
            tree = {
                "node": self.indexes.public(root_id),
                "children": children,
            }
        collection_metadata = {
            "impacted_applications": _collection_metadata(
                max(len(discovered_applications), len(applications)),
                len(application_rows),
            ),
            "impacted_business_services": _collection_metadata(
                len(business_services), len(business_rows)
            ),
            "impacted_services": _collection_metadata(len(services), len(service_rows)),
        }
        truncated = (
            graph_truncated
            or bool(tree_budget["truncated"])
            or any(item["truncated"] for item in collection_metadata.values())
        )
        result = {
            "root": self.indexes.public(root_id),
            "cause_type": cause_type,
            "impacted_applications": application_rows,
            "impacted_business_services": business_rows,
            "impacted_services": service_rows,
            "blast_radius": {
                "resource_count": len(resources),
                "application_count": max(
                    len(discovered_applications), len(applications)
                ),
                "business_service_count": len(business_services),
                "service_count": len(services),
            },
            "tree": tree,
            "collection_metadata": collection_metadata,
            "truncated": truncated,
            "freshness": self.freshness,
            "knowledge_version": self.knowledge_version,
        }
        self.telemetry.traversal_latency.record(
            self.clock() - started, {"cause_type": cause_type}
        )
        self._record_freshness()
        result = self._bounded_public(result)
        self.cache.set(key, result, knowledge_version=self.knowledge_version)
        return result

    def search_operational_context(self, query: str) -> dict[str, Any]:
        key = self._cache_key(f"search:{' '.join(query.casefold().split())}")
        cached = self.cache.get(key, knowledge_version=self.knowledge_version)
        self.telemetry.record_cache(cached is not None, self.cache.stats().hit_ratio)
        if cached is not None:
            return cached
        started = self.clock()
        normalized = " ".join(query.strip().rstrip(".?!").casefold().split())
        if "production applications" in normalized:
            ids = {
                application_id
                for application_id in self.indexes.by_type.get("Application", [])
                if any(
                    self.indexes.entities[environment]["name"].casefold()
                    in {"production", "prod", "live"}
                    for environment in self.indexes.related(
                        application_id, "deployed_in", types={"Environment"}
                    )
                )
            }
        elif "applications owned by" in normalized:
            owner = normalized.split("applications owned by", 1)[1].strip()
            ids = {
                application_id
                for application_id in self.indexes.by_type.get("Application", [])
                if self._application_owned_by(application_id, owner)
            }
        elif "servers with failed patches" in normalized:
            ids = {
                entity_id
                for entity_id in self.indexes.by_type.get("VirtualMachine", [])
                + self.indexes.by_type.get("ArcServer", [])
                if self._patch_compliant(entity_id) is False
            }
        elif "production" in normalized and "failed patch" in normalized:
            ids = {
                entity_id
                for entity_id in self.indexes.by_type.get("VirtualMachine", [])
                + self.indexes.by_type.get("ArcServer", [])
                if self._patch_compliant(entity_id) is False
                and self._environment(entity_id).casefold()
                in {"production", "prod", "live"}
            }
        elif "resources missing ownership" in normalized:
            ids = {
                entity_id
                for entity_id in self.indexes.inventory
                if entity_id in self.indexes.entities
                and not self.indexes.owners_for_resource(entity_id)
            }
        elif "applications missing ownership" in normalized:
            ids = {
                application_id
                for application_id in self.indexes.by_type.get("Application", [])
                if not any(
                    self.indexes.owners_for_resource(resource_id)
                    for resource_id in self.indexes.resources_for_application(application_id)
                )
            }
        elif "resources related to business service" in normalized:
            name = normalized.split("resources related to business service", 1)[1].strip()
            service_id = self.indexes.resolve(name, types={"BusinessService"})
            applications = self.indexes.related(
                service_id, "contains", types={"Application"}
            )
            ids = {
                resource_id
                for application_id in applications
                for resource_id in self.indexes.resources_for_application(application_id)
            }
        elif "critical infrastructure by business service" in normalized:
            name = normalized.split(
                "critical infrastructure by business service", 1
            )[1].strip()
            service_id = self.indexes.resolve(name, types={"BusinessService"})
            applications = self.indexes.related(
                service_id, "contains", types={"Application"}
            )
            ids = {
                resource_id
                for application_id in applications
                for resource_id in self.indexes.resources_for_application(application_id)
                if self._criticality(resource_id).casefold() == "critical"
            }
        elif "critical infrastructure" in normalized:
            ids = {
                entity_id
                for entity_id in self.indexes.inventory
                if self._criticality(entity_id).casefold() == "critical"
                and entity_id in self.indexes.entities
            }
        elif "services" in normalized and "operational risk" in normalized:
            ids = {
                entity_id
                for entity_type in ("BusinessService", "Service")
                for entity_id in self.indexes.by_type.get(entity_type, [])
                if (
                    self._aggregate_risk(self._subject_resources(entity_id)).score
                    or 0
                )
                >= 50
            }
        else:
            raise ValueError(
                "Supported semantic searches: production applications; applications owned by; "
                "servers with failed patches; resources missing ownership; applications missing ownership; resources related "
                "to Business Service; critical infrastructure"
            )
        result = {
            "intent": "semantic_search",
            "count": len(ids),
            "items": self._public_rows(ids),
            "truncated": len(ids) > self.max_results,
            "freshness": self.freshness,
            "knowledge_version": self.knowledge_version,
        }
        self.telemetry.query_latency.record(self.clock() - started, {"intent": "search"})
        self._record_freshness()
        result = self._bounded_public(result)
        self.cache.set(key, result, knowledge_version=self.knowledge_version)
        return result

    def query(
        self, question: str, *, subject: str = "", subject_type: str = ""
    ) -> dict[str, Any]:
        started = self.clock()
        query = SemanticQuery.parse(question, subject=subject)
        if query.intent is SemanticIntent.APPLICATION_CONTEXT:
            result = self.get_application_context(query.subject)
        elif query.intent is SemanticIntent.SERVICE_CONTEXT:
            result = self.get_service_context(query.subject)
        elif query.intent is SemanticIntent.RESOURCE_CONTEXT:
            result = self.get_resource_context(query.subject)
        elif query.intent is SemanticIntent.SUBSCRIPTION_CONTEXT:
            result = self.get_subscription_context(query.subject)
        elif query.intent is SemanticIntent.ORPHAN_RESOURCES:
            contextual_predicates = {"member_of", "owned_by", "belongs_to", "provides"}
            ids = {
                entity_id
                for entity_id in self.indexes.inventory
                if entity_id in self.indexes.entities
                and not any(
                    edge.get("predicate") in contextual_predicates
                    for edge in self.indexes.outgoing[entity_id]
                )
            }
            result = self._result_items(question, ids)
        elif query.intent is SemanticIntent.OWNERSHIP_GAPS:
            ids = {
                entity_id
                for entity_id in self.indexes.inventory
                if entity_id in self.indexes.entities
                and not self.indexes.owners_for_resource(entity_id)
            }
            result = self._result_items(question, ids)
        elif query.intent is SemanticIntent.UPSTREAM_DEPENDENCIES:
            application_id = self.indexes.resolve(
                query.subject, types={"Application"}
            )
            ids, traversal_truncated = self._dependency_closure(
                application_id, "upstream"
            )
            result = self._result_items(question, ids)
            result["truncated"] = result["truncated"] or traversal_truncated
        elif query.intent is SemanticIntent.DOWNSTREAM_IMPACT:
            application_id = self.indexes.resolve(
                query.subject, types={"Application"}
            )
            ids, traversal_truncated = self._dependency_closure(
                application_id, "downstream"
            )
            result = self._result_items(question, ids)
            result["truncated"] = result["truncated"] or traversal_truncated
        elif query.intent is SemanticIntent.DEPENDENCY_CHAINS:
            application_id = self.indexes.resolve(
                query.subject, types={"Application"}
            )
            upstream, upstream_truncated = self._dependency_closure(
                application_id, "upstream"
            )
            downstream, downstream_truncated = self._dependency_closure(
                application_id, "downstream"
            )
            result = {
                "intent": "dependency_chains",
                "upstream": self._public_rows(upstream),
                "downstream": self._public_rows(downstream),
                "truncated": upstream_truncated or downstream_truncated,
                "freshness": self.freshness,
                "knowledge_version": self.knowledge_version,
            }
        elif query.intent is SemanticIntent.OPERATIONAL_RISK:
            result = self.get_risk_context(query.subject)
        elif query.intent is SemanticIntent.IMPACT_CONTEXT:
            result = self.get_impact_context(
                query.subject, subject_type=subject_type
            )
        elif query.intent is SemanticIntent.SEARCH:
            result = self.search_operational_context(question)
        else:  # pragma: no cover - enum exhaustiveness.
            raise ValueError(f"Unsupported semantic intent: {query.intent}")
        if result.get("intent") == "semantic_list":
            result = {**result, "intent": query.intent.value}
        self.telemetry.query_latency.record(
            self.clock() - started, {"intent": query.intent.value}
        )
        return self._bounded_public(result)

    def _build_resource_context(
        self, resource: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        allowed_types = {subject_type} if subject_type else ASSET_TYPES
        if not allowed_types <= ASSET_TYPES:
            raise ValueError("Resource context subject_type must be an asset type")
        entity_id = self.indexes.resolve(resource, types=allowed_types)
        applications = self.indexes.applications_for_resource(entity_id)
        owners = self.indexes.owners_for_resource(entity_id)
        business_services = {
            service
            for application in applications
            for service in self.indexes.business_services_for_application(application)
        }
        support_teams = {
            team
            for application in applications
            for team in self.indexes.support_teams_for_application(application)
        }
        compliance = self._compliance_summary(entity_id)
        inventory = self.indexes.inventory.get(entity_id.casefold(), {})
        advisors = self.indexes.advisors_for_resource(entity_id)
        security_findings = self._security_findings(entity_id)
        sections = {
            "applications": self._public_rows(set(applications)),
            "business_services": self._public_rows(business_services),
            "ownership": self._public_rows(set(owners)),
            "support_teams": self._public_rows(support_teams),
            "compliance": compliance,
            "patching": compliance,
            "advisor_findings": self._public_rows(set(advisors)),
            "security_findings": security_findings[: self.max_results],
            "cost_context": self._public_rows(
                set(self.indexes.business_functions_for_resource(entity_id))
            ),
            "resource_health": {"status": str(inventory.get("status") or "unknown")},
            "operational_classification": {
                "environment": self._environment(entity_id) or "Unknown",
                "criticality": self._criticality(entity_id) or "Unknown",
            },
            "lifecycle": {
                "status": str(self.indexes.entities[entity_id].get("lifecycle_status") or "active")
            },
        }
        return self._context(
            "resource",
            entity_id,
            sections,
            self._risk_for_resource(entity_id),
            section_totals={
                "applications": len(applications),
                "business_services": len(business_services),
                "ownership": len(owners),
                "support_teams": len(support_teams),
                "advisor_findings": len(advisors),
                "security_findings": len(security_findings),
                "cost_context": len(
                    self.indexes.business_functions_for_resource(entity_id)
                ),
            },
        )

    def _build_application_context(self, application: str) -> dict[str, Any]:
        application_id = self.indexes.resolve(application, types={"Application"})
        resources = set(self.indexes.resources_for_application(application_id))
        owners = {
            owner
            for resource_id in resources
            for owner in self.indexes.owners_for_resource(resource_id)
        }
        support = set(self.indexes.support_teams_for_application(application_id))
        advisors = {
            advisor
            for resource_id in resources
            for advisor in self.indexes.advisors_for_resource(resource_id)
        }
        security_by_resource = {
            resource_id: findings
            for resource_id in sorted(resources)
            if (findings := self._security_findings(resource_id))
        }
        security_resources = list(security_by_resource)
        upstream_dependencies, upstream_truncated = self._dependency_closure(
            application_id, "upstream"
        )
        downstream_dependents, downstream_truncated = self._dependency_closure(
            application_id, "downstream"
        )
        sections = {
            "infrastructure": self._public_rows(resources),
            "ownership": self._public_rows(owners),
            "support_teams": self._public_rows(support),
            "business_services": self._public_rows(
                set(self.indexes.business_services_for_application(application_id))
            ),
            "services": self._public_rows(
                set(
                    self.indexes.related(
                        application_id, "implements", types={"Service"}
                    )
                )
            ),
            "upstream_dependencies": self._public_rows(upstream_dependencies),
            "downstream_dependents": self._public_rows(downstream_dependents),
            "compliance": [
                {"resource": self.indexes.public(resource_id), **self._compliance_summary(resource_id)}
                for resource_id in sorted(resources)[: self.max_results]
            ],
            "patch_status": {
                "failed_resource_count": sum(
                    1
                    for resource_id in resources
                    if self._patch_compliant(resource_id) is False
                ),
                "resource_count": len(resources),
            },
            "advisor_findings": self._public_rows(advisors),
            "security_findings": [
                {
                    "resource": self.indexes.public(resource_id),
                    "findings": security_by_resource[resource_id][
                        : self.max_results
                    ],
                    "findings_metadata": _collection_metadata(
                        len(security_by_resource[resource_id]),
                        min(
                            len(security_by_resource[resource_id]),
                            self.max_results,
                        ),
                    ),
                }
                for resource_id in security_resources[: self.max_results]
            ],
            "resource_health": [
                {
                    "resource": self.indexes.public(resource_id),
                    "status": str(
                        self.indexes.inventory.get(resource_id, {}).get("status")
                        or "unknown"
                    ),
                }
                for resource_id in sorted(resources)[: self.max_results]
            ],
            "lifecycle": {"status": "active"},
            "cost_context": self._public_rows(
                {
                    function
                    for resource_id in resources
                    for function in self.indexes.business_functions_for_resource(
                        resource_id
                    )
                }
            ),
        }
        return self._context(
            "application",
            application_id,
            sections,
            self._aggregate_risk(resources),
            section_totals={
                "infrastructure": len(resources),
                "ownership": len(owners),
                "support_teams": len(support),
                "business_services": len(
                    self.indexes.business_services_for_application(application_id)
                ),
                "services": len(
                    self.indexes.related(
                        application_id, "implements", types={"Service"}
                    )
                ),
                "upstream_dependencies": len(upstream_dependencies),
                "downstream_dependents": len(downstream_dependents),
                "compliance": len(resources),
                "advisor_findings": len(advisors),
                "security_findings": len(security_resources),
                "resource_health": len(resources),
                "cost_context": len(
                    {
                        function
                        for resource_id in resources
                        for function in self.indexes.business_functions_for_resource(
                            resource_id
                        )
                    }
                ),
            },
            section_truncated={
                "upstream_dependencies": upstream_truncated,
                "downstream_dependents": downstream_truncated,
            },
        )

    def _build_service_context(
        self, service: str, *, subject_type: str = ""
    ) -> dict[str, Any]:
        allowed_types = (
            {subject_type} if subject_type else {"BusinessService", "Service"}
        )
        if not allowed_types <= {"BusinessService", "Service"}:
            raise ValueError("Service context subject_type must be a service type")
        service_id = self.indexes.resolve(service, types=allowed_types)
        entity_type = self.indexes.entities[service_id]["entity_type"]
        if entity_type == "BusinessService":
            applications = set(
                self.indexes.related(service_id, "contains", types={"Application"})
            )
        else:
            applications = set(
                self.indexes.related(
                    service_id,
                    "implements",
                    direction="in",
                    types={"Application"},
                )
            )
        resources = {
            resource_id
            for application_id in applications
            for resource_id in self.indexes.resources_for_application(application_id)
        }
        dependencies = {
            dependency
            for application_id in applications
            for dependency in self.indexes.upstream_dependencies(application_id)
        }
        sections = {
            "applications": self._public_rows(applications),
            "infrastructure": self._public_rows(resources),
            "dependencies": self._public_rows(dependencies),
            "risk_summary": [
                {
                    "application": self.indexes.public(application_id),
                    "risk": self._aggregate_risk(
                        set(self.indexes.resources_for_application(application_id))
                    ).to_dict(),
                }
                for application_id in sorted(applications)[: self.max_results]
            ],
            "cost_context": self._public_rows(
                {
                    function
                    for resource_id in resources
                    for function in self.indexes.business_functions_for_resource(
                        resource_id
                    )
                }
            ),
        }
        return self._context(
            "service",
            service_id,
            sections,
            self._aggregate_risk(resources),
            section_totals={
                "applications": len(applications),
                "infrastructure": len(resources),
                "dependencies": len(dependencies),
                "risk_summary": len(applications),
                "cost_context": len(
                    {
                        function
                        for resource_id in resources
                        for function in self.indexes.business_functions_for_resource(
                            resource_id
                        )
                    }
                ),
            },
        )

    def _build_subscription_context(self, subscription: str) -> dict[str, Any]:
        subscription_id = self.indexes.resolve(subscription, types={"Subscription"})
        source = self.indexes.entities[subscription_id]
        value = str(source.get("subscription_id") or source.get("name") or "").casefold()
        marker = f"/subscriptions/{value}/"
        resources = {
            entity_id
            for entity_id in self.indexes.inventory
            if marker in entity_id.casefold() and entity_id in self.indexes.entities
        }
        compliance = [self._compliance_summary(entity_id) for entity_id in resources]
        sections = {
            "resource_count": len(resources),
            "resources": self._public_rows(resources),
            "health": {
                "unhealthy_count": sum(
                    1
                    for entity_id in resources
                    if str(self.indexes.inventory[entity_id].get("status") or "").casefold()
                    not in {"available", "healthy", "running"}
                )
            },
            "compliance": {
                "noncompliant_count": sum(
                    1 for row in compliance if row["status"] not in {"compliant", "succeeded"}
                )
            },
            "cost": (
                [
                    {
                        key: item[key]
                        for key in ("amount", "currency", "cost_center", "period")
                        if key in item
                    }
                    for entity_id in sorted(resources)
                    for item in self.indexes.cost.get(entity_id, [])
                ][: self.max_results]
            ),
        }
        return self._context(
            "subscription",
            subscription_id,
            sections,
            self._aggregate_risk(resources),
            section_totals={
                "resources": len(resources),
                "cost": sum(
                    len(self.indexes.cost.get(entity_id, []))
                    for entity_id in resources
                ),
            },
        )

    def _build_environment_context(self, environment: str) -> dict[str, Any]:
        environment_id = self.indexes.resolve(environment, types={"Environment"})
        applications = set(
            self.indexes.related(
                environment_id,
                "deployed_in",
                direction="in",
                types={"Application"},
            )
        )
        resources = {
            resource_id
            for application_id in applications
            for resource_id in self.indexes.resources_for_application(application_id)
        }
        unhealthy_count = sum(
            str(self.indexes.inventory.get(resource_id, {}).get("status") or "").casefold()
            not in {"available", "healthy", "running"}
            for resource_id in resources
        )
        noncompliant_count = sum(
            self._patch_compliant(resource_id) is False for resource_id in resources
        )
        sections = {
            "applications": self._public_rows(applications),
            "resources": self._public_rows(resources),
            "health": {
                "status": "healthy" if unhealthy_count == 0 else "degraded",
                "unhealthy_count": unhealthy_count,
            },
            "compliance": {"noncompliant_count": noncompliant_count},
        }
        return self._context(
            "environment",
            environment_id,
            sections,
            self._aggregate_risk(resources),
            section_totals={
                "applications": len(applications),
                "resources": len(resources),
            },
        )

    def _context(
        self,
        context_type: str,
        entity_id: str,
        sections: dict[str, Any],
        risk: RiskAssessment,
        *,
        section_totals: dict[str, int] | None = None,
        section_truncated: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        row = self.indexes.public(entity_id)
        subject = SemanticEntity(
            row["entity_type"], row["name"], row["lifecycle_status"]
        )
        model_name = {
            "application": "Application",
            "service": "Service",
            "resource": "Infrastructure",
            "subscription": "Infrastructure",
            "environment": "Infrastructure",
        }[context_type]
        model = self.registry.build(model_name, subject, sections)
        context = SemanticContext(
            context_type=context_type,
            subject=subject,
            sections=model.facts,
            freshness=self.freshness,
            knowledge_version=self.knowledge_version,
            risk=risk,
        ).to_dict()
        totals = section_totals or {}
        context["section_metadata"] = {
            name: _collection_metadata(totals.get(name, len(items)), len(items))
            for name, items in context["sections"].items()
            if isinstance(items, list)
        }
        for name, truncated in (section_truncated or {}).items():
            if truncated and name in context["section_metadata"]:
                context["section_metadata"][name]["truncated"] = True
        context = self._bounded_public(context)
        report = self.validator.validate_context(context)
        if not report.passed:
            raise ValueError("Unsafe semantic context: " + "; ".join(report.errors))
        return context

    def _cached_context(
        self, context_type: str, subject: str, builder: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        key = self._cache_key(f"context:{context_type}:{subject.casefold()}")
        cached = self.cache.get(key, knowledge_version=self.knowledge_version)
        self.telemetry.record_cache(cached is not None, self.cache.stats().hit_ratio)
        if cached is not None:
            return cached
        started = self.clock()
        context = builder()
        self.telemetry.context_latency.record(
            self.clock() - started, {"context_type": context_type}
        )
        self._record_freshness()
        self.cache.set(key, context, knowledge_version=self.knowledge_version)
        return context

    def _subject_resources(self, entity_id: str) -> set[str]:
        entity_type = self.indexes.entities[entity_id]["entity_type"]
        if entity_type in ASSET_TYPES:
            return {entity_id}
        if entity_type == "Application":
            return set(self.indexes.resources_for_application(entity_id))
        if entity_type == "Subscription":
            source = self.indexes.entities[entity_id]
            value = str(
                source.get("subscription_id") or source.get("name") or ""
            ).casefold()
            marker = f"/subscriptions/{value}/"
            return {
                resource_id
                for resource_id in self.indexes.inventory
                if marker in resource_id.casefold()
                and resource_id in self.indexes.entities
            }
        if entity_type in {"Service", "BusinessService"}:
            if entity_type == "BusinessService":
                applications = self.indexes.related(
                    entity_id, "contains", types={"Application"}
                )
            else:
                applications = self.indexes.related(
                    entity_id,
                    "implements",
                    direction="in",
                    types={"Application"},
                )
            return {
                resource_id
                for application_id in applications
                for resource_id in self.indexes.resources_for_application(application_id)
            }
        return set()

    def _risk_for_resource(self, resource_id: str) -> RiskAssessment:
        environment = self._environment(resource_id)
        return self.scorer.score(
            RiskInputs(
                missing_owner=not bool(self.indexes.owners_for_resource(resource_id)),
                patch_compliant=self._patch_compliant(resource_id),
                advisor_recommendation_count=len(
                    self.indexes.advisors_for_resource(resource_id)
                ),
                security_finding_count=len(self._security_findings(resource_id)),
                criticality=self._criticality(resource_id),
                environment=environment,
            )
        )

    def _aggregate_risk(self, resources: set[str]) -> RiskAssessment:
        assessments = [self._risk_for_resource(item) for item in resources]
        if not assessments:
            return RiskAssessment(None, "Unknown", {})
        selected = max(
            assessments,
            key=lambda item: (item.score, tuple(sorted(item.factors.items()))),
        )
        return RiskAssessment(
            selected.score,
            selected.level,
            dict(selected.factors),
        )

    def _compliance_summary(self, resource_id: str) -> dict[str, Any]:
        row = self.indexes.compliance.get(resource_id.casefold(), {})
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(str(row.get("payload_json") or "{}"))
            payload = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        properties_value = payload.get("properties")
        properties = properties_value if isinstance(properties_value, dict) else payload
        return {
            "status": str(
                row.get("status")
                or properties.get("status")
                or properties.get("assessmentState")
                or "unknown"
            ).casefold(),
            "failed_patch_count": _int_value(
                row.get("failed_patch_count")
                or properties.get("failedPatchCount")
                or properties.get("failedPatchInstallations")
            ),
            "last_modified": str(row.get("last_modified") or row.get("timestamp") or ""),
        }

    def _patch_compliant(self, resource_id: str) -> bool | None:
        status = self._compliance_summary(resource_id)["status"]
        if status in {"compliant", "succeeded", "success", "completed"}:
            return True
        if status in {"failed", "error", "noncompliant", "non-compliant"}:
            return False
        return None

    def _criticality(self, resource_id: str) -> str:
        inventory = self.indexes.inventory.get(resource_id.casefold(), {})
        direct = str(inventory.get("criticality") or "")
        if direct:
            return direct
        try:
            parsed = json.loads(
                str(self.indexes.entities[resource_id].get("payload_json") or "{}")
            )
        except json.JSONDecodeError:
            return ""
        payload = parsed if isinstance(parsed, dict) else {}
        raw_tags = payload.get("tags") or {}
        tags = (
            {str(key).casefold(): str(value) for key, value in raw_tags.items()}
            if isinstance(raw_tags, dict)
            else {}
        )
        return tags.get("criticality", "")

    def _environment(self, resource_id: str) -> str:
        inventory = self.indexes.inventory.get(resource_id.casefold(), {})
        direct = str(inventory.get("environment") or "")
        if direct:
            return direct
        try:
            parsed = json.loads(
                str(self.indexes.entities[resource_id].get("payload_json") or "{}")
            )
        except json.JSONDecodeError:
            parsed = {}
        payload = parsed if isinstance(parsed, dict) else {}
        raw_tags = payload.get("tags") or {}
        if isinstance(raw_tags, dict):
            environment = next(
                (
                    str(value)
                    for key, value in raw_tags.items()
                    if str(key).casefold() in {"environment", "env"}
                ),
                "",
            )
            if environment:
                return environment
        environments = {
            environment
            for application in self.indexes.applications_for_resource(resource_id)
            for environment in self.indexes.related(
                application, "deployed_in", types={"Environment"}
            )
        }
        return next(
            (
                str(self.indexes.entities[item].get("name") or "")
                for item in sorted(environments)
            ),
            "",
        )

    def _application_owned_by(self, application_id: str, owner: str) -> bool:
        needle = owner.casefold()
        teams = self.indexes.support_teams_for_application(application_id)
        if any(self.indexes.entities[item]["name"].casefold() == needle for item in teams):
            return True
        return any(
            self.indexes.entities[owner_id]["name"].casefold() == needle
            for resource_id in self.indexes.resources_for_application(application_id)
            for owner_id in self.indexes.owners_for_resource(resource_id)
        )

    def _impact_application_node(
        self,
        application_id: str,
        visited: set[str],
        relation: str = "impacts",
        *,
        budget: dict[str, int | bool],
        depth: int = 0,
    ) -> dict[str, Any] | None:
        if int(budget["remaining"]) <= 0:
            budget["truncated"] = True
            return None
        budget["remaining"] = int(budget["remaining"]) - 1
        if application_id in visited:
            return {
                "relation": relation,
                "node": self.indexes.public(application_id),
                "cycle": True,
                "children": [],
            }
        if depth >= self.max_traversal_depth:
            has_children = bool(
                self.indexes.business_services_for_application(application_id)
                or self.indexes.related(
                    application_id, "implements", types={"Service"}
                )
                or self.indexes.downstream_dependents(application_id)
            )
            budget["truncated"] = bool(budget["truncated"]) or has_children
            return {
                "relation": relation,
                "node": self.indexes.public(application_id),
                "children": [],
            }
        path = {*visited, application_id}
        children: list[dict[str, Any]] = []
        for relation_name, service_ids in (
            (
                "business_impact",
                self.indexes.business_services_for_application(application_id),
            ),
            (
                "service_impact",
                self.indexes.related(
                    application_id, "implements", types={"Service"}
                ),
            ),
        ):
            for service_id in service_ids[: self.max_results]:
                if int(budget["remaining"]) <= 0:
                    budget["truncated"] = True
                    break
                budget["remaining"] = int(budget["remaining"]) - 1
                children.append(
                    {
                        "relation": relation_name,
                        "node": self.indexes.public(service_id),
                    }
                )
            if len(service_ids) > self.max_results:
                budget["truncated"] = True
        dependents = self.indexes.downstream_dependents(application_id)
        if len(dependents) > self.max_results:
            budget["truncated"] = True
        children.extend(
            node
            for dependent_id in dependents[: self.max_results]
            if (
                node := self._impact_application_node(
                    dependent_id,
                    path,
                    relation="downstream_dependency",
                    budget=budget,
                    depth=depth + 1,
                )
            )
            is not None
        )
        if len(children) > self.max_results:
            budget["truncated"] = True
        return {
            "relation": relation,
            "node": self.indexes.public(application_id),
            "children": children[: self.max_results],
        }

    def _dependency_closure(
        self, application_id: str, direction: str
    ) -> tuple[set[str], bool]:
        if direction not in {"upstream", "downstream"}:
            raise ValueError("Dependency direction must be upstream or downstream")
        seen: set[str] = set()
        queue = deque([application_id])
        truncated = False
        while queue:
            current = queue.popleft()
            adjacent = (
                self.indexes.upstream_dependencies(current)
                if direction == "upstream"
                else self.indexes.downstream_dependents(current)
            )
            for related in adjacent:
                if related != application_id and related not in seen:
                    if len(seen) >= self.max_traversal_nodes:
                        truncated = True
                        return seen, truncated
                    seen.add(related)
                    queue.append(related)
        return seen, truncated

    def _security_findings(self, resource_id: str) -> list[dict[str, str]]:
        findings = [
            {
                "title": str(row.get("title") or ""),
                "severity": str(row.get("severity") or ""),
                "source": str(row.get("source") or "security"),
            }
            for row in self.indexes.security.get(resource_id.casefold(), [])
        ]
        for advisor_id in self.indexes.advisors_for_resource(resource_id):
            advisor = self.indexes.entities[advisor_id]
            try:
                parsed = json.loads(str(advisor.get("payload_json") or "{}"))
                payload = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                continue
            if str(payload.get("category") or "").casefold() != "security":
                continue
            findings.append(
                {
                    "title": str(advisor.get("name") or "Security recommendation"),
                    "severity": str(payload.get("impact") or "unknown"),
                    "source": "Azure Advisor",
                }
            )
        unique = {
            (row["title"], row["severity"], row["source"]): row
            for row in findings
        }
        return sorted(
            unique.values(), key=lambda row: (row["severity"], row["title"])
        )

    def _public_rows(self, ids: set[str]) -> list[dict[str, str]]:
        rows = sorted(
            (self.indexes.public(entity_id) for entity_id in ids if entity_id in self.indexes.entities),
            key=lambda row: (row["entity_type"], row["name"]),
        )
        return rows[: self.max_results]

    def _result_items(self, question: str, ids: set[str]) -> dict[str, Any]:
        items = self._public_rows(ids)
        return {
            "intent": "semantic_list",
            "count": len(ids),
            "items": items,
            "truncated": len(ids) > self.max_results,
            "freshness": self.freshness,
            "knowledge_version": self.knowledge_version,
        }

    def _bounded_public(self, value: Any) -> Any:
        def sanitize(item: Any) -> Any:
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    safe_key = IncidentIntelligence._safe_identifier(key, "field")
                    if safe_key in result:
                        raise ValueError("Semantic public mapping key collision")
                    result[safe_key] = sanitize(child)
                return result
            if isinstance(item, (list, tuple)):
                return [sanitize(child) for child in item]
            if isinstance(item, str):
                return IncidentIntelligence._safe_text(item)
            return item

        result = sanitize(value)
        if (
            len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
            > self.max_serialized_bytes
        ):
            raise ValueError("Semantic output exceeds configured bound")
        return result

    def _cache_key(self, key: str) -> str:
        return f"{self.cache_namespace}:{key}"

    @staticmethod
    def _timestamp(value: str, field_name: str) -> str:
        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Semantic {field_name} timestamp is invalid") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _record_freshness(self) -> None:
        now = self.now().astimezone(UTC)
        for value, instrument in (
            (self.freshness, self.telemetry.knowledge_freshness),
            (self.ontology_synchronized_at, self.telemetry.ontology_lag),
        ):
            if not value:
                continue
            try:
                observed = datetime.fromisoformat(value).astimezone(UTC)
            except ValueError:
                continue
            instrument.record(max(0.0, (now - observed).total_seconds()))


def _int_value(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _collection_metadata(count: int, returned: int) -> dict[str, int | bool]:
    return {
        "count": count,
        "returned": returned,
        "truncated": returned < count,
    }
