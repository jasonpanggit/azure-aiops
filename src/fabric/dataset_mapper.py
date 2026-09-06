from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from intelligence.vulnerability.exposure_projection import (
    ExposureGoldProjection,
    ExposureTemporalProjection,
    build_temporal_projection,
    project_exposure_gold,
)
from intelligence.vulnerability.read_port import ExposureReadPort
from onboarding.network_normalize import NETWORK_ENTITY_TYPES
from ontology.confidence import compute_confidence
from ontology.entity_builder import (
    PAAS_ENTITY_TYPES,
    EntityBuilder,
    scoped_semantic_id,
    semantic_id,
    typed_image_semantic_id,
)
from ontology.ontology_sync import (
    TYPED_IMAGE_ONTOLOGY_VERSION,
    OntologyGraphResult,
    OntologyGraphSynchronizer,
)
from ontology.ontology_validator import OntologyValidator
from ontology.relationship_builder import RelationshipBuilder

#: The generic bucket the connector writes every unclassified ARM resource to.
#: A resource that also lands in a typed file (a Bastion in ``NetworkGateway``,
#: a VNet in ``VNet``) appears in both, and the typed row is the richer one.
GENERIC_ENTITY_FILE = "Resource"

ENTITY_FILES = (
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    GENERIC_ENTITY_FILE,
    "VirtualMachine",
    "ArcServer",
    "PatchAssessment",
    "PatchAssessmentDetail",
    "PatchInstallation",
    "AdvisorRecommendation",
    "CostActual",
    # Identity governance entities. Role assignments and definitions come from
    # the authorizationresources ARG table, managed identities from Resources.
    # Without their own typed files they would be collapsed into the generic
    # entity file and lose the principal/role/scope fields identity risk needs.
    "RoleAssignment",
    "RoleDefinition",
    "ManagedIdentity",
    "DefenderAssessment",
    "DefenderVulnerabilityFinding",
    "ContainerImageExposure",
    "LogicalImage",
    "ImageDigest",
    "VulnerabilityObservation",
    "SecurityAlert",
    "AttackPath",
    "AttackPathNode",
    "AttackPathConnection",
    "SecureScoreSnapshot",
    "SecureScoreControl",
    "Situation",
    # Network topology entities, including the sub-resources (subnets, NSG
    # rules, routes, peerings) that only ever exist in their own typed file.
    # Without these the ontology has no VNet internals, so the topology graph
    # renders nodes with no relationships between them.
    *NETWORK_ENTITY_TYPES,
)

_GRANULAR_CONTAINER_ENTITY_FILES = frozenset(
    {"LogicalImage", "ImageDigest", "VulnerabilityObservation"}
)

ONTOLOGY_ENTITY_TYPES = (
    "Tenant",
    "ManagementGroup",
    "Subscription",
    "ResourceGroup",
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "KubernetesCluster",
    "PatchAssessment",
    "PatchInstallation",
    "AdvisorRecommendation",
    "CostActual",
    "RoleAssignment",
    "RoleDefinition",
    "ManagedIdentity",
    "LifecycleProduct",
    "Application",
    "Service",
    "Environment",
    "BusinessService",
    "BusinessFunction",
    "Owner",
    "SupportTeam",
    "RemediationPlan",
    "ApprovalRequirement",
    "ApprovalDecision",
    "RollbackPlan",
    "ExecutionStep",
    "RiskAssessment",
    "SimulationResult",
    "Prediction",
    "Forecast",
    "Trend",
    "OperationalDebt",
    "RiskDriver",
    "ChangeEvent",
    "ConfigurationBaseline",
    "ConfigurationDrift",
    "PolicyDeviation",
    "SecurityDeviation",
    "AuthorizedChange",
    "UnapprovedChange",
    "Incident",
    "OperationalEvent",
    "RootCause",
    "RiskPattern",
    "BlastRadius",
    "DependencyChain",
    "OperationalFinding",
    "Situation",
    # Network topology (Prompt 16)
    "VNet",
    "Subnet",
    "NetworkInterface",
    "NetworkSecurityGroup",
    "NetworkSecurityRule",
    "RouteTable",
    "Route",
    "VNetPeering",
    "AzureFirewall",
    "FirewallPolicy",
    "FirewallRuleCollection",
    "FirewallRule",
    "PrivateEndpoint",
    "PrivateDnsZone",
    "NetworkGateway",
    "LoadBalancer",
    "KBArticle",
    "SecurityUpdate",
    "CVE",
    "AffectedProduct",
    "CVSSScore",
    "ExploitabilitySignal",
    "PatchSupersedence",
    "VulnerabilityFinding",
    "VulnerabilityExposure",
    "SubscriptionConnection",
    "ConnectionHealth",
    "MissingUpdate",
    "DefenderAssessment",
    "DefenderVulnerabilityFinding",
    "ContainerImageExposure",
    "LogicalImage",
    "ImageDigest",
    "VulnerabilityObservation",
    "WorkloadDeployment",
    "SecurityAlert",
    "AttackPath",
    "AttackPathNode",
    "AttackPathConnection",
    "SecureScoreSnapshot",
    "SecureScoreControl",
    # PaaS resource types used as relationship subject/object types by
    # RelationshipBuilder (src/ontology/relationship_builder.py). Without
    # these, any inferred relationship touching a PaaS resource fails
    # ontology publish with "relationship endpoint type is not defined".
    *sorted(PAAS_ENTITY_TYPES),
    # Synthetic subject type for observed VNet flow-log traffic (see the
    # FlowObservation -> trafficObserved -> NetworkSecurityRule relationship
    # below). It has no ARM resource id and never appears in inventory, but
    # must still be a registered entity type for that relationship to publish.
    "FlowObservation",
)


def temporal_inputs_from_legacy(
    datasets: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Translate retained patch/Defender/image rows without inventing time."""

    inputs: list[dict[str, Any]] = []
    for row in datasets.get("silver_patch_findings", ()):
        status = str(row.get("status") or "").strip().casefold()
        is_install = status in {
            "installed",
            "succeeded",
            "success",
            "completedwithwarnings",
            "installation_failed",
            "failed",
        }
        inputs.append(
            _legacy_temporal_input(
                row,
                source_family=(
                    "azure_update_manager_installation"
                    if is_install
                    else "azure_update_manager_missing"
                ),
                target_id=str(row.get("target_resource_id") or ""),
                target_kind="server",
                weakness_id=str(row.get("kb_id") or row.get("update_id") or ""),
                weakness_kind="kb",
                status=(
                    "installation_failed"
                    if status in {"installation_failed", "failed"}
                    else ("installed" if is_install else "missing")
                ),
                provider_time=str(
                    row.get("installed_at")
                    if is_install and row.get("installed_at")
                    else row.get("last_modified") or ""
                ),
            )
        )
    for row in datasets.get("silver_defender_findings", ()):
        weakness_id = str(row.get("cve_id") or row.get("assessment_id") or "")
        inputs.append(
            _legacy_temporal_input(
                row,
                source_family="defender_subassessment",
                target_id=str(row.get("target_resource_id") or ""),
                target_kind="server",
                weakness_id=weakness_id,
                weakness_kind=(
                    "cve" if weakness_id.upper().startswith("CVE-") else "assessment"
                ),
                status=str(row.get("status") or "unknown"),
                provider_time=str(row.get("last_assessed_at") or ""),
            )
        )
    for row in datasets.get("silver_container_image_exposure", ()):
        for weakness_id in sorted(
            {str(value).upper() for value in row.get("cve_ids") or () if value}
        ):
            inputs.append(
                _legacy_temporal_input(
                    row,
                    source_family="defender_image",
                    target_id=str(
                        row.get("image_digest")
                        or row.get("target_resource_id")
                        or ""
                    ),
                    target_kind="container_image",
                    weakness_id=weakness_id,
                    weakness_kind="cve",
                    status=str(row.get("status") or "unknown"),
                    provider_time=str(row.get("last_assessed_at") or ""),
                )
            )
    return sorted(
        inputs,
        key=lambda row: (
            str(row.get("tenant_id") or ""),
            str(row.get("target_id") or ""),
            str(row.get("weakness_id") or ""),
            str(row.get("provider_operation_id") or ""),
        ),
    )


def temporal_products_from_legacy(
    datasets: Mapping[str, list[dict[str, Any]]],
    *,
    generation_id: str,
    ingested_at: str,
) -> ExposureTemporalProjection:
    """Build additive temporal products while legacy products remain intact."""

    return build_temporal_projection(
        temporal_inputs_from_legacy(datasets),
        generation_id=generation_id,
        ingested_at=ingested_at,
        run_at=ingested_at,
    )


def exposure_gold_products_from_datasets(
    datasets: Mapping[str, list[dict[str, Any]]],
    *,
    generation_id: str,
    projected_at: str,
) -> dict[str, list[dict[str, Any]]]:
    """Map current typed Exposure products into one validated Gold generation."""

    projection: ExposureGoldProjection = project_exposure_gold(
        datasets,
        generation_id=generation_id,
        projected_at=projected_at,
    )
    return projection.as_tables()


def _legacy_temporal_input(
    row: Mapping[str, Any],
    *,
    source_family: str,
    target_id: str,
    target_kind: str,
    weakness_id: str,
    weakness_kind: str,
    status: str,
    provider_time: str,
) -> dict[str, Any]:
    subscription_id = str(row.get("subscription_id") or "").strip().casefold()
    return {
        "tenant_id": str(row.get("tenant_id") or "legacy-unknown-tenant"),
        "connection_id": str(
            row.get("connection_id") or f"legacy:{subscription_id or 'unknown'}"
        ),
        "source_family": source_family,
        "source_id": str(
            row.get("resource_id")
            or row.get("assessment_id")
            or row.get("update_id")
            or ""
        ),
        "target_id": target_id,
        "target_kind": target_kind,
        "weakness_id": weakness_id,
        "weakness_kind": weakness_kind,
        "status": status,
        "provider_operation_id": str(
            row.get("provider_operation_id")
            or row.get("resource_id")
            or row.get("assessment_id")
            or row.get("update_id")
            or ""
        ),
        "provider_status": str(row.get("provider_status") or status),
        "operation_succeeded": status.casefold()
        not in {"failed", "installation_failed", "unknown"},
        "provider_event_time": provider_time or None,
        "provider_event_time_quality": "provider" if provider_time else "unknown",
        "source_sequence": str(row.get("change_version") or ""),
        "source_generation": str(row.get("ingestion_run_id") or ""),
        "title": str(
            row.get("update_name")
            or row.get("recommendation")
            or row.get("repository")
            or ""
        ),
        "subscription_id": subscription_id,
        "legacy_payload": dict(row),
    }

#: Entity types that can appear as the object of a network containment edge.
_NETWORK_CONTAINED = (
    "VNet",
    "NetworkInterface",
    "NetworkSecurityGroup",
    "RouteTable",
    "AzureFirewall",
    "FirewallPolicy",
    "PrivateEndpoint",
    "PrivateDnsZone",
    "NetworkGateway",
    "LoadBalancer",
)

#: Entity types that can be attached to a subnet.
_SUBNET_ATTACHED = (
    "NetworkInterface",
    "AzureFirewall",
    "PrivateEndpoint",
    "NetworkGateway",
    "LoadBalancer",
)

ONTOLOGY_RELATIONSHIP_TYPES = (
    ("Tenant", "owns", "Subscription"),
    ("ManagementGroup", "contains", "Subscription"),
    ("Subscription", "contains", "ResourceGroup"),
    ("ArcServer", "managed_by", "Subscription"),
    ("SupportTeam", "supports", "Application"),
    ("Application", "deployed_in", "Environment"),
    ("Application", "implements", "Service"),
    ("Application", "depends_on", "Application"),
    ("BusinessService", "contains", "Application"),
    ("BusinessService", "owns", "Application"),
    ("BusinessService", "funded_by", "BusinessFunction"),
    ("Owner", "owns", "Service"),
    ("Owner", "owns", "BusinessService"),
    ("MissingUpdate", "identifiedBy", "KBArticle"),
    ("SecurityUpdate", "addresses", "CVE"),
    ("CVE", "affects", "AffectedProduct"),
    ("CVE", "hasScore", "CVSSScore"),
    ("CVE", "hasExploitabilitySignal", "ExploitabilitySignal"),
    ("SecurityUpdate", "supersedes", "PatchSupersedence"),
    ("VulnerabilityFinding", "forCVE", "CVE"),
    ("VulnerabilityFinding", "onResource", "Resource"),
    ("VulnerabilityFinding", "affectsApplication", "Application"),
    ("VulnerabilityFinding", "impactsBusinessService", "BusinessService"),
    ("VulnerabilityExposure", "aggregates", "VulnerabilityFinding"),
    ("Application", "requiresPlan", "RemediationPlan"),
    ("RemediationPlan", "mitigatesRisk", "RiskAssessment"),
    ("RemediationPlan", "protectsService", "BusinessService"),
    ("RemediationPlan", "requiresApproval", "ApprovalRequirement"),
    ("RemediationPlan", "hasApprovalDecision", "ApprovalDecision"),
    ("RemediationPlan", "hasStep", "ExecutionStep"),
    ("RemediationPlan", "hasRollbackPlan", "RollbackPlan"),
    ("RemediationPlan", "hasSimulation", "SimulationResult"),
    ("RemediationPlan", "addressesFinding", "DefenderAssessment"),
    ("RemediationPlan", "addressesAlert", "SecurityAlert"),
    ("RemediationPlan", "breaksAttackPath", "AttackPath"),
    ("RemediationPlan", "improvesControl", "SecureScoreControl"),
    ("Prediction", "hasForecast", "Forecast"),
    ("Prediction", "hasTrend", "Trend"),
    ("Prediction", "accumulatesDebt", "OperationalDebt"),
    ("Prediction", "drivenBy", "RiskDriver"),
    ("ChangeEvent", "classifiedAs", "AuthorizedChange"),
    ("ChangeEvent", "classifiedAs", "UnapprovedChange"),
    ("ChangeEvent", "evaluatedAgainst", "ConfigurationBaseline"),
    ("ChangeEvent", "resultedIn", "ConfigurationDrift"),
    ("Incident", "hasFinding", "OperationalFinding"),
    ("Incident", "hasBlastRadius", "BlastRadius"),
    ("BlastRadius", "hasDependencyChain", "DependencyChain"),
    ("Incident", "hasEvent", "OperationalEvent"),
    ("Incident", "hasProbableCause", "RootCause"),
    *(
        ("Situation", "affects", asset)
        for asset in (
            "Resource",
            "VirtualMachine",
            "ArcServer",
            "KubernetesCluster",
            *sorted(PAAS_ENTITY_TYPES),
        )
    ),
    ("Tenant", "owns", "SubscriptionConnection"),
    ("Subscription", "contains", "SubscriptionConnection"),
    ("SubscriptionConnection", "has_health", "ConnectionHealth"),
    ("SubscriptionConnection", "mapped_to", "Environment"),
    ("SubscriptionConnection", "supports", "BusinessService"),
    ("SubscriptionConnection", "runs", "Application"),
    *(("ResourceGroup", "contains", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "member_of", "Application") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("Application", "hosted_on", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "belongs_to", "BusinessService") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "provides", "Service") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "owned_by", "Owner") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("AdvisorRecommendation", "affects", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("Resource", "incurs_cost", "CostActual"), ("VirtualMachine", "incurs_cost", "CostActual"), ("ArcServer", "incurs_cost", "CostActual"), ("KubernetesCluster", "incurs_cost", "CostActual")),
    *(("PatchAssessment", "evaluates", asset) for asset in ("VirtualMachine", "ArcServer")),
    *((asset, "assessedBy", "PatchAssessment") for asset in ("VirtualMachine", "ArcServer")),
    *(("PatchInstallation", "records_installation_for", asset) for asset in ("VirtualMachine", "ArcServer")),
    *(("AdvisorRecommendation", "impacts", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("DefenderAssessment", "impacts", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *(("DefenderVulnerabilityFinding", "impacts", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    *((asset, "hasVulnerability", "DefenderVulnerabilityFinding") for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")),
    ("DefenderVulnerabilityFinding", "derivedFrom", "DefenderAssessment"),
    ("ContainerImageExposure", "impacts", "Resource"),
    ("Resource", "hasImageExposure", "ContainerImageExposure"),
    *(
        ("VulnerabilityObservation", "affects", asset)
        for asset in ("Resource", "VirtualMachine", "ArcServer", "ImageDigest")
    ),
    ("VulnerabilityObservation", "identifies", "CVE"),
    *(
        (asset, "hasVulnerabilityObservation", "VulnerabilityObservation")
        for asset in ("Resource", "VirtualMachine", "ArcServer", "ImageDigest")
    ),
    ("ContainerRegistry", "containsImage", "LogicalImage"),
    ("LogicalImage", "hasDigest", "ImageDigest"),
    ("ImageDigest", "deployedAs", "WorkloadDeployment"),
    ("KubernetesCluster", "observesDeployment", "WorkloadDeployment"),
    ("WorkloadDeployment", "runsApplication", "Application"),
    *(("SecurityAlert", "affects", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster", *sorted(PAAS_ENTITY_TYPES))),
    ("AttackPath", "traverses", "AttackPathNode"),
    ("AttackPath", "startsAt", "AttackPathNode"),
    ("AttackPath", "targets", "AttackPathNode"),
    ("AttackPath", "supportedBy", "DefenderAssessment"),
    ("AttackPath", "contains", "AttackPathConnection"),
    ("AttackPathConnection", "connectsFrom", "AttackPathNode"),
    ("AttackPathConnection", "connectsTo", "AttackPathNode"),
    *(("AttackPathNode", "resolvesTo", asset) for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster", *sorted(PAAS_ENTITY_TYPES))),
    ("Subscription", "hasSecureScore", "SecureScoreSnapshot"),
    ("SecureScoreSnapshot", "composedOf", "SecureScoreControl"),
    ("SecureScoreControl", "improvedBy", "DefenderAssessment"),
    # Network topology (Prompt 16)
    ("VNet", "contains", "Subnet"),
    ("VNet", "hasPeering", "VNetPeering"),
    ("VNetPeering", "peersWith", "VNet"),
    ("Subnet", "protectedBy", "NetworkSecurityGroup"),
    ("Subnet", "routedBy", "RouteTable"),
    ("Subnet", "egressesVia", "NetworkGateway"),
    ("NetworkSecurityGroup", "hasRule", "NetworkSecurityRule"),
    ("RouteTable", "hasRoute", "Route"),
    ("NetworkInterface", "protectedBy", "NetworkSecurityGroup"),
    ("AzureFirewall", "enforcesPolicy", "FirewallPolicy"),
    ("FirewallPolicy", "hasRuleCollection", "FirewallRuleCollection"),
    ("FirewallRuleCollection", "hasRule", "FirewallRule"),
    ("PrivateDnsZone", "resolvesFor", "VNet"),
    *((entity, "belongsTo", "ResourceGroup") for entity in _NETWORK_CONTAINED),
    *((entity, "attachedTo", "Subnet") for entity in _SUBNET_ATTACHED),
    *(
        ("PrivateEndpoint", "exposesPrivately", asset)
        for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")
    ),
    *(
        (asset, "hasNetworkInterface", "NetworkInterface")
        for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")
    ),
    *(
        ("LoadBalancer", "loadBalances", asset)
        for asset in ("Resource", "VirtualMachine", "ArcServer", "KubernetesCluster")
    ),
    # Observed traffic (VNet flow logs / Traffic Analytics). Unlike every
    # relationship above, this one is *behavioral* rather than structural: it
    # records that traffic matching a rule was actually seen on the wire, so
    # "this rule permits traffic nothing has ever exercised" becomes an
    # answerable question. The subject is a synthetic content-addressed
    # observation id (flow logs carry no ARM resource id), not a real resource.
    ("FlowObservation", "trafficObserved", "NetworkSecurityRule"),
)


def allowed_relationship_triples() -> frozenset[tuple[str, str, str]]:
    """Return the exact authoritative relationship vocabulary.

    Consumers intentionally derive their allowlist from
    ``ONTOLOGY_RELATIONSHIP_TYPES`` on every call.  Keeping this as a helper
    rather than a second constant prevents policy, validation, and MCP
    projections from drifting to a copied vocabulary.
    """

    return frozenset(ONTOLOGY_RELATIONSHIP_TYPES)


def is_allowed_relationship_triple(
    subject_type: object,
    predicate: object,
    object_type: object,
) -> bool:
    """Check exact, direction-sensitive vocabulary membership."""

    return (
        str(subject_type),
        str(predicate),
        str(object_type),
    ) in allowed_relationship_triples()


@dataclass
class ExposureOntologyMapper:
    """Project one scoped persisted Exposure generation into ontology v2.

    The read port is the only input seam, so authorization filtering happens
    before graph construction. The mapper then delegates entity, relationship,
    and synchronization semantics to the same production builders used by the
    inventory and Fabric ontology pipelines.
    """

    read_port: ExposureReadPort
    entity_builder: EntityBuilder = field(default_factory=EntityBuilder)
    relationship_builder: RelationshipBuilder = field(
        default_factory=RelationshipBuilder
    )
    synchronizer: OntologyGraphSynchronizer = field(
        default_factory=lambda: OntologyGraphSynchronizer(OntologyValidator())
    )
    page_size: int = 1_000
    max_findings: int = 50_000

    def project(
        self,
        scope: Any,
        *,
        tenant_id: str = "",
        previous_entities: list[dict[str, Any]] | None = None,
        previous_relationships: list[dict[str, Any]] | None = None,
    ) -> OntologyGraphResult:
        page = self.read_port.list_exposures(
            scope,
            offset=0,
            limit=self.page_size,
        )
        total_count = int(page["total_count"])
        if total_count > self.max_findings:
            raise ValueError("Exposure ontology finding source exceeds configured bound")
        findings = [dict(row) for row in page["findings"]]
        generation_id = str(page["read_model_generation_id"])
        offset = len(findings)
        while offset < total_count:
            next_page = self.read_port.list_exposures(
                scope,
                offset=offset,
                limit=min(self.page_size, total_count - offset),
            )
            if str(next_page["read_model_generation_id"]) != generation_id:
                raise ValueError(
                    "Exposure ontology projection crossed read-model generations"
                )
            next_findings = [dict(row) for row in next_page["findings"]]
            if not next_findings:
                raise ValueError("Exposure ontology projection pagination stalled")
            findings.extend(next_findings)
            offset += len(next_findings)

        tenant_values = {
            str(row.get("tenant_id") or "").strip()
            for row in findings
            if str(row.get("tenant_id") or "").strip()
        }
        if not isinstance(tenant_id, str):
            raise TypeError("Exposure ontology projection tenant_id must be a string")
        tenant_id = tenant_id.strip()
        if not tenant_id:
            if len(tenant_values) != 1:
                raise ValueError(
                    "Exposure ontology projection requires one persisted tenant identity"
                )
            tenant_id = next(iter(tenant_values))
        source_rows = _exposure_ontology_source_rows(
            findings,
            tenant_id=tenant_id,
            generation_id=generation_id,
        )
        entities = self.entity_builder.build(
            source_rows,
            generation_id,
        )
        relationships = self.relationship_builder.build(entities, generation_id)
        return self.synchronizer.synchronize(
            entities,
            relationships,
            previous_entities=previous_entities or (),
            previous_relationships=previous_relationships or (),
            ontology_version=TYPED_IMAGE_ONTOLOGY_VERSION,
        )


_GRANULAR_EXPOSURE_TABLE_KEYS = {
    "silver_container_registries": "registry_id",
    "silver_container_logical_images": "logical_image_id",
    "silver_container_image_digests": "image_digest_id",
    "silver_container_vulnerability_observations": (
        "vulnerability_observation_id"
    ),
    "silver_workload_deployments": "deployment_id",
    "metadata_workload_source_checkpoints": "checkpoint_key",
}


@dataclass
class GranularExposureOntologyMapper:
    """Losslessly project the durable granular Fabric contract into ontology v2.

    Unlike :class:`ExposureOntologyMapper`, which consumes the summarized
    Exposure read model, this adapter consumes the Plan 10 granular products.
    Every source row is retained in the entity payload so the approved Fabric
    keys, generation evidence, event interval, provenance, and completeness
    can be reconstructed without reinterpretation.
    """

    entity_builder: EntityBuilder = field(default_factory=EntityBuilder)
    relationship_builder: RelationshipBuilder = field(
        default_factory=RelationshipBuilder
    )
    synchronizer: OntologyGraphSynchronizer = field(
        default_factory=lambda: OntologyGraphSynchronizer(OntologyValidator())
    )

    def project(
        self,
        datasets: Mapping[str, list[dict[str, Any]]],
        *,
        ontology_generation_id: str,
        previous_entities: list[dict[str, Any]] | None = None,
        previous_relationships: list[dict[str, Any]] | None = None,
    ) -> OntologyGraphResult:
        if (
            not isinstance(ontology_generation_id, str)
            or not ontology_generation_id.strip()
        ):
            raise ValueError("Ontology generation id must be a non-empty string")
        source_rows = _granular_exposure_ontology_source_rows(datasets)
        entities = self.entity_builder.build(
            source_rows,
            ontology_generation_id,
        )
        relationships = self.relationship_builder.build(
            entities,
            ontology_generation_id,
        )
        return self.synchronizer.synchronize(
            entities,
            relationships,
            previous_entities=previous_entities or (),
            previous_relationships=previous_relationships or (),
            ontology_version=TYPED_IMAGE_ONTOLOGY_VERSION,
        )

    def to_fabric(
        self,
        graph: OntologyGraphResult,
    ) -> dict[str, list[dict[str, Any]]]:
        """Reconstruct the granular Fabric rows embedded by :meth:`project`."""

        restored: dict[str, dict[str, dict[str, Any]]] = {
            table_name: {} for table_name in _GRANULAR_EXPOSURE_TABLE_KEYS
        }

        def restore(table_name: str, row: Any) -> None:
            if table_name not in restored or not isinstance(row, Mapping):
                return
            candidate = dict(row)
            key_field = _GRANULAR_EXPOSURE_TABLE_KEYS[table_name]
            key = str(candidate.get(key_field) or "")
            if not key:
                raise ValueError(
                    f"Ontology round trip is missing Fabric key {key_field}"
                )
            previous = restored[table_name].get(key)
            if previous is not None and previous != candidate:
                raise ValueError(
                    f"Ontology round trip contains conflicting Fabric key {key}"
                )
            restored[table_name][key] = candidate

        for entity in graph.entities:
            if entity.get("lifecycle_status", "active") != "active":
                continue
            payload = _json_mapping(
                entity.get("payload_json"),
                field_name="ontology entity payload_json",
            )
            restore(
                str(payload.get("fabric_table") or ""),
                payload.get("fabric_row"),
            )
            for checkpoint in payload.get("coverage_checkpoints") or ():
                restore("metadata_workload_source_checkpoints", checkpoint)

        return {
            table_name: [
                rows[key]
                for key in sorted(rows)
            ]
            for table_name, rows in restored.items()
        }


def _granular_exposure_ontology_source_rows(
    datasets: Mapping[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not isinstance(datasets, Mapping):
        raise TypeError("Granular Exposure datasets must be a mapping")
    indexed = {
        table_name: _index_granular_rows(
            datasets.get(table_name, ()),
            table_name=table_name,
            key_field=key_field,
        )
        for table_name, key_field in _GRANULAR_EXPOSURE_TABLE_KEYS.items()
    }
    registries = indexed["silver_container_registries"]
    logical_images = indexed["silver_container_logical_images"]
    digests = indexed["silver_container_image_digests"]
    observations = indexed["silver_container_vulnerability_observations"]
    deployments = indexed["silver_workload_deployments"]
    checkpoints = indexed["metadata_workload_source_checkpoints"]
    digest_pattern = re.compile(r"^sha256:[0-9a-f]{64}$")

    if not logical_images or not observations:
        raise ValueError(
            "Granular Exposure ontology requires logical image and "
            "vulnerability observation rows"
        )

    logical_entity_ids: dict[str, str] = {}
    digest_entity_ids: dict[str, str] = {}
    observation_entity_ids: dict[str, str] = {}
    deployment_entity_ids: dict[str, str] = {}
    source_rows: list[dict[str, Any]] = []

    for key, row in logical_images.items():
        _require_granular_scope(row, table_name="silver_container_logical_images")
        registry_id = str(row.get("registry_id") or "")
        registry = registries.get(registry_id)
        if registry is None:
            raise ValueError("Container logical image references an unknown registry")
        if _granular_scope(registry) != _granular_scope(row):
            raise ValueError(
                "Container logical image crosses its registry scope"
            )
        logical_entity_ids[key] = typed_image_semantic_id(
            "LogicalImage",
            str(row["tenant_id"]),
            str(row["subscription_id"]),
            key,
        )

    for key, row in digests.items():
        _require_granular_scope(
            row,
            table_name="silver_container_image_digests",
        )
        digest = str(row.get("image_digest") or "").casefold()
        if not digest_pattern.fullmatch(digest):
            raise ValueError("Container image digest is not an immutable sha256")
        references = list(row.get("logical_image_ids") or ())
        if not references or any(
            reference not in logical_entity_ids for reference in references
        ):
            raise ValueError("Container image digest references an unknown logical image")
        if any(
            _granular_scope(logical_images[reference])
            != _granular_scope(row)
            for reference in references
        ):
            raise ValueError(
                "Container image digest crosses its logical image scope"
            )
        digest_entity_ids[key] = typed_image_semantic_id(
            "ImageDigest",
            str(row["tenant_id"]),
            str(row["subscription_id"]),
            key,
        )

    for key, row in observations.items():
        _require_granular_scope(
            row,
            table_name="silver_container_vulnerability_observations",
        )
        if str(row.get("target_kind") or "") != "container_image":
            raise ValueError(
                "Container vulnerability observation has an unsafe target kind"
            )
        digest_key = str(row.get("image_digest_id") or "")
        digest_row = digests.get(digest_key)
        if digest_row is None:
            raise ValueError(
                "Container vulnerability observation references an unknown image digest"
            )
        if str(digest_row.get("image_digest") or "") != str(
            row.get("image_digest") or ""
        ):
            raise ValueError(
                "Container vulnerability observation has conflicting digest evidence"
            )
        if str(row.get("logical_image_id") or "") not in logical_entity_ids:
            raise ValueError(
                "Container vulnerability observation references an unknown logical image"
            )
        if _granular_scope(digest_row) != _granular_scope(row) or _granular_scope(
            logical_images[str(row["logical_image_id"])]
        ) != _granular_scope(row):
            raise ValueError(
                "Container vulnerability observation crosses an evidence scope"
            )
        observation_entity_ids[key] = typed_image_semantic_id(
            "VulnerabilityObservation",
            str(row["tenant_id"]),
            str(row["subscription_id"]),
            key,
        )

    digest_keys_by_value: dict[tuple[str, str, str], str] = {}
    for key, row in digests.items():
        digest = str(row.get("image_digest") or "").casefold()
        scoped_digest = (*_granular_scope(row), digest)
        previous = digest_keys_by_value.get(scoped_digest)
        if previous is not None and previous != key:
            raise ValueError(
                "Container image digest value maps to multiple keys in one scope"
            )
        digest_keys_by_value[scoped_digest] = key

    for key, row in deployments.items():
        _require_granular_scope(row, table_name="silver_workload_deployments")
        digest_key = digest_keys_by_value.get(
            (
                *_granular_scope(row),
                str(row.get("image_digest") or "").casefold(),
            )
        )
        if digest_key is None:
            raise ValueError("Workload deployment references an unknown image digest")
        checkpoint_key = str(row.get("checkpoint_key") or "")
        checkpoint = checkpoints.get(checkpoint_key)
        if checkpoint is None:
            raise ValueError("Workload deployment references an unknown checkpoint")
        if _granular_scope(checkpoint) != _granular_scope(row):
            raise ValueError("Workload deployment crosses its checkpoint scope")
        if (
            str(row.get("connection_id") or "")
            != str(checkpoint.get("connection_id") or "")
            or str(row.get("workspace_id") or "")
            != str(checkpoint.get("workspace_id") or "")
        ):
            raise ValueError(
                "Workload deployment conflicts with checkpoint source identity"
            )
        if str(row.get("effective_generation") or "") != str(
            checkpoint.get("effective_generation") or ""
        ):
            raise ValueError(
                "Workload deployment conflicts with checkpoint effective generation"
            )
        deployment_entity_ids[key] = typed_image_semantic_id(
            "WorkloadDeployment",
            str(row["tenant_id"]),
            str(row["subscription_id"]),
            key,
        )

    checkpoints_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for checkpoint in checkpoints.values():
        _require_granular_scope(
            checkpoint,
            table_name="metadata_workload_source_checkpoints",
        )
        checkpoints_by_scope.setdefault(
            _granular_scope(checkpoint),
            [],
        ).append(dict(checkpoint))
    for rows in checkpoints_by_scope.values():
        rows.sort(key=lambda row: str(row["checkpoint_key"]))

    def add_fabric_entity(
        *,
        table_name: str,
        fabric_key: str,
        entity_type: str,
        entity_id: str,
        row: Mapping[str, Any],
        name: str,
        extra_payload: Mapping[str, Any],
    ) -> None:
        payload = {
            "fabric_table": table_name,
            "fabric_key": fabric_key,
            "fabric_row": dict(row),
            **dict(extra_payload),
        }
        source_rows.append(
            {
                "tenant_id": str(row["tenant_id"]),
                "subscription_id": str(row["subscription_id"]),
                "resource_id": entity_id,
                "entity_type": entity_type,
                "name": name,
                "timestamp": str(
                    row.get("observed_at")
                    or row.get("timestamp")
                    or "1970-01-01T00:00:00Z"
                ),
                "payload_json": _canonical(payload),
                "discovery": "granular_exposure_fabric",
            }
        )

    for key, row in registries.items():
        _require_granular_scope(row, table_name="silver_container_registries")
        registry_entity_id = (
            str(row.get("registry_resource_id") or "").strip().casefold()
        )
        if not registry_entity_id:
            raise ValueError("Container registry requires a canonical resource id")
        add_fabric_entity(
            table_name="silver_container_registries",
            fabric_key=key,
            entity_type="ContainerRegistry",
            entity_id=registry_entity_id,
            row=row,
            name=str(row.get("registry_host") or key),
            extra_payload={
                "id": registry_entity_id,
                "resourceType": "Microsoft.ContainerRegistry/registries",
            },
        )

    registry_entity_ids = {
        key: str(row.get("registry_resource_id") or "").strip().casefold()
        for key, row in registries.items()
    }
    for key, row in logical_images.items():
        digest_links = sorted(
            digest_entity_ids[digest_key]
            for digest_key, digest_row in digests.items()
            if key in (digest_row.get("logical_image_ids") or ())
        )
        add_fabric_entity(
            table_name="silver_container_logical_images",
            fabric_key=key,
            entity_type="LogicalImage",
            entity_id=logical_entity_ids[key],
            row=row,
            name=str(row.get("repository") or key),
            extra_payload={
                "target_kind": "container_image",
                "registry_id": registry_entity_ids[str(row["registry_id"])],
                "digest_entity_ids": digest_links,
                "source_generation": str(row.get("ingestion_run_id") or ""),
                "provenance": _json_mapping(
                    row.get("provenance_json"),
                    field_name="logical image provenance_json",
                ),
            },
        )

    for key, row in digests.items():
        add_fabric_entity(
            table_name="silver_container_image_digests",
            fabric_key=key,
            entity_type="ImageDigest",
            entity_id=digest_entity_ids[key],
            row=row,
            name=str(row["image_digest"]),
            extra_payload={
                "target_kind": "container_image",
                "digest": str(row["image_digest"]),
                "logical_image_entity_ids": [
                    logical_entity_ids[value]
                    for value in row.get("logical_image_ids") or ()
                ],
                "source_generation": str(row.get("ingestion_run_id") or ""),
                "provenance": _json_mapping(
                    row.get("provenance_json"),
                    field_name="image digest provenance_json",
                ),
                "coverage_checkpoints": checkpoints_by_scope.get(
                    _granular_scope(row),
                    [],
                ),
            },
        )

    for key, row in observations.items():
        weakness_id = str(row.get("cve_id") or "").strip().upper()
        if not weakness_id:
            raise ValueError("Container vulnerability observation requires a CVE")
        weakness_entity_id = semantic_id(
            "CVE",
            str(row["tenant_id"]),
            weakness_id,
        )
        source_rows.append(
            {
                "tenant_id": str(row["tenant_id"]),
                "subscription_id": "not-applicable",
                "resource_id": weakness_entity_id,
                "entity_type": "CVE",
                "name": weakness_id,
                "payload_json": _canonical({"cve_id": weakness_id}),
                "discovery": "granular_exposure_fabric",
            }
        )
        add_fabric_entity(
            table_name="silver_container_vulnerability_observations",
            fabric_key=key,
            entity_type="VulnerabilityObservation",
            entity_id=observation_entity_ids[key],
            row=row,
            name=key,
            extra_payload={
                "target_kind": "container_image",
                "ontology_target_id": digest_entity_ids[
                    str(row["image_digest_id"])
                ],
                "weakness_entity_id": weakness_entity_id,
                "source_families": [str(row.get("source_family") or "")],
                "source_generation": str(row.get("ingestion_run_id") or ""),
                "evidence_identity": key,
                "event_interval": {
                    "from": str(row.get("provider_event_time") or ""),
                    "to": str(row.get("observed_at") or ""),
                },
                "provenance": _json_mapping(
                    row.get("provenance_json"),
                    field_name="vulnerability observation provenance_json",
                ),
                "completeness": "complete",
            },
        )

    for key, row in deployments.items():
        digest_key = digest_keys_by_value[
            (
                *_granular_scope(row),
                str(row["image_digest"]).casefold(),
            )
        ]
        checkpoint = checkpoints[str(row["checkpoint_key"])]
        add_fabric_entity(
            table_name="silver_workload_deployments",
            fabric_key=key,
            entity_type="WorkloadDeployment",
            entity_id=deployment_entity_ids[key],
            row=row,
            name=(
                f"{row.get('controller_kind')}/{row.get('controller_name')}"
            ),
            extra_payload={
                "target_kind": "container_image",
                "digest_entity_id": digest_entity_ids[digest_key],
                "cluster_id": str(row.get("cluster_id") or "").casefold(),
                "workload_state": "observed-exact-digest",
                "evidence_identity": key,
                "source_generation": str(row.get("ingestion_run_id") or ""),
                "attempted_generation": str(
                    row.get("attempted_generation") or ""
                ),
                "effective_generation": str(
                    row.get("effective_generation") or ""
                ),
                "event_interval": {
                    "from": str(row.get("defender_observed_at") or ""),
                    "to": str(row.get("observed_at") or ""),
                },
                "provenance": _json_mapping(
                    row.get("provenance_json"),
                    field_name="workload deployment provenance_json",
                ),
                "completeness": str(
                    checkpoint.get("completeness")
                    or checkpoint.get("status")
                    or "unknown"
                ),
            },
        )
        cluster_id = str(row.get("cluster_id") or "").strip().casefold()
        if not cluster_id:
            raise ValueError("Workload deployment requires a cluster identity")
        source_rows.append(
            {
                "tenant_id": str(row["tenant_id"]),
                "subscription_id": str(row["subscription_id"]),
                "resource_id": cluster_id,
                "entity_type": "KubernetesCluster",
                "name": cluster_id.rsplit("/", 1)[-1],
                "resource_type": "Microsoft.ContainerService/managedClusters",
                "payload_json": _canonical(
                    {
                        "id": cluster_id,
                        "resourceType": (
                            "Microsoft.ContainerService/managedClusters"
                        ),
                    }
                ),
                "discovery": "granular_exposure_fabric",
            }
        )

    return sorted(
        source_rows,
        key=lambda row: (
            str(row.get("entity_type") or ""),
            str(row.get("resource_id") or ""),
        ),
    )


def _index_granular_rows(
    rows: Any,
    *,
    table_name: str,
    key_field: str,
) -> dict[str, dict[str, Any]]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, (list, tuple)):
        raise TypeError(f"{table_name} must contain a bounded row sequence")
    indexed: dict[str, dict[str, Any]] = {}
    for value in rows:
        if not isinstance(value, Mapping):
            raise TypeError(f"{table_name} rows must be mappings")
        row = dict(value)
        key = str(row.get(key_field) or "")
        if not key:
            raise ValueError(f"{table_name} row is missing {key_field}")
        previous = indexed.get(key)
        if previous is not None and previous != row:
            raise ValueError(f"{table_name} contains conflicting key {key}")
        indexed[key] = row
    return indexed


def _require_granular_scope(
    row: Mapping[str, Any],
    *,
    table_name: str,
) -> None:
    if not str(row.get("tenant_id") or "").strip() or not str(
        row.get("subscription_id") or ""
    ).strip():
        raise ValueError(f"{table_name} row requires tenant and subscription scope")


def _granular_scope(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("tenant_id") or "").strip().casefold(),
        str(row.get("subscription_id") or "").strip().casefold(),
    )


def _json_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a JSON mapping")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} is malformed") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"{field_name} must contain a mapping")
    return parsed


def _exposure_ontology_source_rows(
    findings: list[dict[str, Any]],
    *,
    tenant_id: str,
    generation_id: str,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}

    def add(
        resource_id: str,
        entity_type: str,
        name: str,
        subscription_id: str,
        payload: dict[str, Any],
    ) -> None:
        key = resource_id.strip().casefold()
        if not key:
            raise ValueError("Exposure ontology entity identity must not be empty")
        source = {
            "tenant_id": tenant_id,
            "subscription_id": subscription_id,
            "resource_id": key,
            "entity_type": entity_type,
            "name": name,
            "payload_json": _canonical(payload),
            "discovery": "authoritative_exposure",
        }
        existing = candidates.get(key)
        if existing is not None and existing != source:
            raise ValueError(
                f"Exposure ontology identity collision for {entity_type}"
            )
        candidates[key] = source

    for finding in findings:
        exposure_id = str(finding.get("exposure_id") or "").strip()
        target_id = str(finding.get("target_id") or "").strip()
        target_kind = str(finding.get("target_kind") or "").strip().casefold()
        weakness_id = str(finding.get("weakness_id") or "").strip().upper()
        subscription_id = str(finding.get("subscription_id") or "").strip()
        row_tenant_id = str(finding.get("tenant_id") or tenant_id).strip()
        if row_tenant_id.casefold() != tenant_id.casefold():
            raise ValueError("Exposure ontology row tenant does not match projection tenant")
        source_families = sorted(
            {
                str(value).strip().casefold()
                for value in finding.get("source_families") or ()
                if str(value).strip()
            }
        )
        common = {
            "exposure_id": exposure_id,
            "target_kind": target_kind,
            "weakness_id": weakness_id,
            "source_families": source_families,
            "connection_ids": sorted(
                {
                    str(value).strip()
                    for value in finding.get("connection_ids") or ()
                    if str(value).strip()
                }
            ),
            "read_model_generation_id": generation_id,
            "completeness": str(finding.get("completeness") or ""),
        }
        weakness_entity_id = semantic_id("CVE", tenant_id, weakness_id)
        add(
            weakness_entity_id,
            "CVE",
            weakness_id,
            "not-applicable",
            {
                "cve_id": weakness_id,
                "read_model_generation_id": generation_id,
            },
        )

        if target_kind == "container_image":
            digest = target_id.casefold()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Exposure image target must be an immutable sha256 digest")
            target_entity_id = typed_image_semantic_id(
                "ImageDigest",
                tenant_id,
                subscription_id,
                digest,
            )
            add(
                target_entity_id,
                "ImageDigest",
                digest,
                subscription_id,
                {
                    **common,
                    "digest": digest,
                },
            )
            registry_id = str(finding.get("registry_id") or "").strip()
            repository = str(finding.get("image_repository") or "").strip()
            if registry_id and repository:
                logical_image_id = typed_image_semantic_id(
                    "LogicalImage",
                    tenant_id,
                    subscription_id,
                    registry_id,
                    repository,
                )
                add(
                    registry_id,
                    "ContainerRegistry",
                    registry_id.rsplit("/", 1)[-1],
                    subscription_id,
                    {
                        "id": registry_id,
                        "resourceType": "Microsoft.ContainerRegistry/registries",
                        "read_model_generation_id": generation_id,
                    },
                )
                add(
                    logical_image_id,
                    "LogicalImage",
                    repository,
                    subscription_id,
                    {
                        **common,
                        "registry_id": registry_id.casefold(),
                        "repository": repository,
                        "image_tags": sorted(
                            {
                                str(value).strip()
                                for value in finding.get("image_tags") or ()
                                if str(value).strip()
                            }
                        ),
                        "digest_entity_id": target_entity_id,
                    },
                )

            if str(finding.get("workload_state") or "").casefold() == (
                "observed-exact-digest"
            ):
                workload_identity = tuple(
                    str(finding.get(name) or "").strip()
                    for name in (
                        "workload_cluster_id",
                        "workload_namespace",
                        "workload_controller_kind",
                        "workload_controller_name",
                        "workload_pod_uid",
                    )
                )
                if any(not value for value in workload_identity):
                    raise ValueError(
                        "Observed Exposure workload requires complete exact-digest identity"
                    )
                (
                    cluster_id,
                    namespace,
                    controller_kind,
                    controller_name,
                    pod_uid,
                ) = workload_identity
                application_name = str(finding.get("application_id") or "").strip()
                business_service_name = str(
                    finding.get("business_service_id") or ""
                ).strip()
                if not application_name or not business_service_name:
                    raise ValueError(
                        "Observed Exposure workload requires application and business service"
                    )
                workload_id = typed_image_semantic_id(
                    "WorkloadDeployment",
                    tenant_id,
                    subscription_id,
                    cluster_id,
                    namespace,
                    controller_kind,
                    controller_name,
                    pod_uid,
                    digest,
                )
                application_id = scoped_semantic_id(
                    "Application",
                    tenant_id,
                    subscription_id,
                    application_name,
                )
                business_service_id = scoped_semantic_id(
                    "BusinessService",
                    tenant_id,
                    subscription_id,
                    business_service_name,
                )
                add(
                    cluster_id,
                    "KubernetesCluster",
                    cluster_id.rsplit("/", 1)[-1],
                    subscription_id,
                    {
                        "id": cluster_id,
                        "resourceType": "Microsoft.ContainerService/managedClusters",
                        "read_model_generation_id": generation_id,
                    },
                )
                add(
                    application_id,
                    "Application",
                    application_name,
                    subscription_id,
                    {
                        "application_id": application_name,
                        "read_model_generation_id": generation_id,
                    },
                )
                add(
                    business_service_id,
                    "BusinessService",
                    business_service_name,
                    subscription_id,
                    {
                        "business_service_id": business_service_name,
                        "read_model_generation_id": generation_id,
                    },
                )
                add(
                    workload_id,
                    "WorkloadDeployment",
                    f"{controller_kind}/{controller_name}",
                    subscription_id,
                    {
                        **common,
                        "cluster_id": cluster_id.casefold(),
                        "namespace": namespace,
                        "controller_kind": controller_kind,
                        "controller_name": controller_name,
                        "pod_uid": pod_uid,
                        "digest_entity_id": target_entity_id,
                        "application_entity_id": application_id,
                        "business_service_entity_id": business_service_id,
                        "workload_state": "observed-exact-digest",
                    },
                )
        elif target_kind == "server":
            folded_target = target_id.casefold()
            target_entity_id = folded_target
            if "/microsoft.hybridcompute/machines/" in folded_target:
                entity_type = "ArcServer"
            elif "/microsoft.compute/virtualmachines/" in folded_target:
                entity_type = "VirtualMachine"
            else:
                entity_type = "Resource"
            add(
                folded_target,
                entity_type,
                target_id.rsplit("/", 1)[-1],
                subscription_id,
                {
                    "id": target_id,
                    "target_kind": "server",
                    "read_model_generation_id": generation_id,
                },
            )
        else:
            raise ValueError(f"Unsupported Exposure ontology target kind: {target_kind}")

        observation_id = typed_image_semantic_id(
            "VulnerabilityObservation",
            tenant_id,
            subscription_id,
            exposure_id,
        )
        add(
            observation_id,
            "VulnerabilityObservation",
            exposure_id,
            subscription_id,
            {
                **common,
                "ontology_target_id": target_entity_id,
                "weakness_entity_id": weakness_entity_id,
            },
        )

    return [candidates[key] for key in sorted(candidates)]


class InventoryDatasetMapper:
    def load(
        self,
        snapshot: str | Path,
        ingestion_run_id: str,
        fs: Any | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Load one connection's mapped inventory from its dataset snapshot.

        ``snapshot`` is the *already-resolved* generation path/directory
        returned by ``DatasetStore.current_generation()`` - for remote (ADLS)
        roots that string has no ``abfss://`` scheme (it's the bare
        ``container/path`` fsspec uses internally), so re-resolving it here
        would silently fall back to the local filesystem and read nothing.
        Callers with a remote ``DatasetStore`` must pass its ``fs`` through;
        only bare local-path callers (e.g. CLI/tests) may omit it.
        """
        if fs is None:
            from storage.fs import resolve_fs

            fs, root = resolve_fs(str(snapshot))
        else:
            root = str(snapshot)
        manifest = _read_json(fs, f"{root}/manifest.json")
        ingestion_timestamp = str(manifest.get("startedAt") or "1970-01-01T00:00:00Z")
        entities = {
            entity_type: _read_jsonl(fs, f"{root}/entities/{entity_type}.jsonl")
            for entity_type in ENTITY_FILES
        }
        relationships = _read_jsonl(fs, f"{root}/relationships/relationships.jsonl")
        changes = _read_jsonl(fs, f"{root}/changes/resource_changes.jsonl")
        situations = _read_jsonl(fs, f"{root}/situations/situations.jsonl")
        situation_evidence = _read_jsonl(fs, f"{root}/situations/evidence.jsonl")
        situation_links = _read_jsonl(fs, f"{root}/situations/links.jsonl")
        audit_events = _read_jsonl(fs, f"{root}/situations/audit_events.jsonl")
        source_status = _read_jsonl(fs, f"{root}/situations/source_status.jsonl")

        all_resources = [
            *entities["Resource"],
            *entities["VirtualMachine"],
            *entities["ArcServer"],
        ]
        inventory_entity_rows = _dedupe_entity_rows(
            [
                _entity_row(row, entity_type, ingestion_run_id)
                for entity_type, rows in entities.items()
                if entity_type not in _GRANULAR_CONTAINER_ENTITY_FILES
                for row in rows
            ]
        )
        resource_index = {row["resource_id"]: row for row in inventory_entity_rows}
        subscription_tenants = {
            str(row.get("subscriptionId") or "").casefold(): str(row.get("tenantId") or "")
            for row in entities["Subscription"]
        }
        relationship_rows = [
            _relationship_row(row, resource_index, ingestion_run_id)
            for row in relationships
        ]

        entity_rows = EntityBuilder().build(
            inventory_entity_rows, ingestion_run_id, ingestion_timestamp
        )
        ontology_relationships = RelationshipBuilder().build(entity_rows, ingestion_run_id)
        graph = OntologyGraphSynchronizer(OntologyValidator()).build(
            entity_rows, ontology_relationships
        )

        datasets = {
            "bronze_resources": [_asset_row(row, ingestion_run_id) for row in all_resources],
            "bronze_subscriptions": [
                _entity_row(row, "Subscription", ingestion_run_id)
                for row in entities["Subscription"]
            ],
            "bronze_resourcegroups": [
                _entity_row(row, "ResourceGroup", ingestion_run_id)
                for row in entities["ResourceGroup"]
            ],
            "bronze_advisor": [
                _entity_row(row, "AdvisorRecommendation", ingestion_run_id)
                for row in entities["AdvisorRecommendation"]
            ],
            "bronze_cost_actuals": [
                _cost_actual_row(row, ingestion_run_id, subscription_tenants)
                for row in entities["CostActual"]
            ],
            "silver_cost_actuals": [
                _cost_actual_row(row, ingestion_run_id, subscription_tenants)
                for row in entities["CostActual"]
            ],
            "bronze_patchassessment": [
                _entity_row(row, "PatchAssessment", ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "bronze_patchassessmentdetail": [
                _entity_row(row, "PatchAssessmentDetail", ingestion_run_id)
                for row in entities["PatchAssessmentDetail"]
            ],
            "bronze_patchinstallation": [
                _entity_row(row, "PatchInstallation", ingestion_run_id)
                for row in entities["PatchInstallation"]
            ],
            "bronze_defender_assessments": [
                _entity_row(row, "DefenderAssessment", ingestion_run_id)
                for row in entities["DefenderAssessment"]
            ],
            "bronze_defender_findings": [
                _entity_row(row, "DefenderVulnerabilityFinding", ingestion_run_id)
                for row in entities["DefenderVulnerabilityFinding"]
            ],
            "bronze_container_image_exposure": [
                _entity_row(row, "ContainerImageExposure", ingestion_run_id)
                for row in entities["ContainerImageExposure"]
            ],
            **{
                f"bronze_defender_{dataset}": [
                    _entity_row(row, entity_type, ingestion_run_id)
                    for row in entities[entity_type]
                ]
                for dataset, entity_type in (
                    ("alerts", "SecurityAlert"),
                    ("attack_paths", "AttackPath"),
                    ("attack_path_nodes", "AttackPathNode"),
                    ("attack_path_connections", "AttackPathConnection"),
                    ("secure_scores", "SecureScoreSnapshot"),
                    ("secure_score_controls", "SecureScoreControl"),
                )
            },
            "bronze_resource_changes": [
                _change_row(row, resource_index, subscription_tenants, ingestion_run_id)
                for row in changes
            ],
            "silver_vm_inventory": [
                _asset_row(row, ingestion_run_id) for row in entities["VirtualMachine"]
            ],
            "silver_server_inventory": [
                _asset_row(row, ingestion_run_id)
                for row in [*entities["VirtualMachine"], *entities["ArcServer"]]
            ],
            "silver_compliance": [
                _compliance_row(row, ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "silver_patch_history": [
                _patch_history_row(row, ingestion_run_id)
                for row in entities["PatchAssessment"]
            ],
            "silver_patch_installations": [
                _patch_installation_row(row, ingestion_run_id)
                for row in entities["PatchInstallation"]
            ],
            "silver_patch_findings": [
                *(
                    _patch_finding_row(row, ingestion_run_id, status="missing")
                    for row in entities["PatchAssessmentDetail"]
                ),
                *(
                    _patch_finding_row(row, ingestion_run_id, status="installed")
                    for row in entities["PatchInstallation"]
                ),
            ],
            "silver_defender_findings": [
                _defender_finding_row(row, ingestion_run_id)
                for row in entities["DefenderVulnerabilityFinding"]
            ],
            "silver_defender_assessments": [
                _defender_assessment_row(row, ingestion_run_id)
                for row in entities["DefenderAssessment"]
            ],
            "silver_container_image_exposure": [
                _container_image_exposure_row(row, ingestion_run_id)
                for row in entities["ContainerImageExposure"]
            ],
            "silver_container_registries": _container_registry_rows(
                entities["LogicalImage"],
                ingestion_run_id,
            ),
            "silver_container_logical_images": [
                _container_logical_image_row(row, ingestion_run_id)
                for row in entities["LogicalImage"]
            ],
            "silver_container_image_digests": [
                _container_image_digest_row(row, ingestion_run_id)
                for row in entities["ImageDigest"]
            ],
            "silver_container_vulnerability_observations": [
                _container_vulnerability_observation_row(
                    row,
                    ingestion_run_id,
                )
                for row in entities["VulnerabilityObservation"]
            ],
            **{
                f"silver_defender_{dataset}": [
                    _entity_row(row, entity_type, ingestion_run_id)
                    for row in entities[entity_type]
                ]
                for dataset, entity_type in (
                    ("alerts", "SecurityAlert"),
                    ("attack_paths", "AttackPath"),
                    ("attack_path_nodes", "AttackPathNode"),
                    ("attack_path_connections", "AttackPathConnection"),
                    ("secure_scores", "SecureScoreSnapshot"),
                    ("secure_score_controls", "SecureScoreControl"),
                )
            },
            "silver_resource_relationships": relationship_rows,
            "silver_situations": [_situation_row(row, ingestion_run_id) for row in situations],
            "silver_situation_evidence": [
                _situation_evidence_row(row, ingestion_run_id) for row in situation_evidence
            ],
            "silver_situation_links": [
                _situation_link_row(row, ingestion_run_id) for row in situation_links
            ],
            "metadata_audit_events": [
                _audit_event_row(row, ingestion_run_id) for row in audit_events
            ],
            "metadata_source_status": [
                _source_status_row(row, ingestion_run_id) for row in source_status
            ],
            "ontology_entities": graph.entities,
            "ontology_relationships": graph.relationships,
            "ontology_application_context": graph.views["application_context"],
            "ontology_infrastructure_context": graph.views["infrastructure_context"],
            "ontology_subscription_context": graph.views["subscription_context"],
            "ontology_compliance_context": graph.views["compliance_context"],
            "ontology_business_context": graph.views["business_context"],
            "ontology_health": [
                _health_row(graph.health, ingestion_run_id, ingestion_timestamp)
            ],
            "ontology_quality_report": [
                _ontology_quality_row(
                    graph.quality_report, ingestion_run_id, ingestion_timestamp
                )
            ],
        }
        for entity_type in ONTOLOGY_ENTITY_TYPES:
            datasets[ontology_entity_table(entity_type)] = [
                row for row in graph.entities if row["entity_type"] == entity_type
            ]
        relationship_types = {
            (row["subject_type"], row["predicate"], row["object_type"])
            for row in graph.relationships
        }
        for subject_type, predicate, object_type in relationship_types:
            table_name = ontology_relationship_table(subject_type, predicate, object_type)
            datasets[table_name] = [
                row
                for row in graph.relationships
                if (row["subject_type"], row["predicate"], row["object_type"])
                == (subject_type, predicate, object_type)
            ]
        for relationship_type in ONTOLOGY_RELATIONSHIP_TYPES:
            datasets.setdefault(ontology_relationship_table(*relationship_type), [])
        situation_entity_rows = [
            _situation_ontology_entity(row, ingestion_run_id) for row in situations
        ]
        datasets["ontology_entities"].extend(situation_entity_rows)
        datasets["ontology_situation_entities"] = situation_entity_rows
        known_types = {
            row["resource_id"]: str(row.get("entity_type") or "Resource")
            for row in datasets["ontology_entities"]
        }
        situation_relationships = [
            _situation_ontology_relationship(row, situations, known_types, ingestion_run_id)
            for row in situation_links
        ]
        situation_relationships = [row for row in situation_relationships if row]
        datasets["ontology_relationships"].extend(situation_relationships)
        datasets["ontology_rel_situation_affects_resource"] = situation_relationships
        _validate_granular_container_products(datasets)
        return datasets


def remediation_decision_ontology_rows(
    decisions: list[dict[str, Any]],
    ingestion_run_id: str,
    timestamp: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project durable remediation decisions into ontology-shaped rows."""
    entities: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    seen_plans: set[str] = set()
    for decision in decisions:
        plan_id = str(decision.get("plan_id") or "").strip()
        decision_id = str(decision.get("decision_id") or "").strip()
        if not plan_id or not decision_id:
            continue
        if plan_id not in seen_plans:
            entities.append(
                _remediation_ontology_entity(
                    plan_id,
                    "RemediationPlan",
                    f"Remediation plan {plan_id}",
                    {"plan_id": plan_id},
                    ingestion_run_id,
                    timestamp,
                )
            )
            seen_plans.add(plan_id)
        entities.append(
            _remediation_ontology_entity(
                decision_id,
                "ApprovalDecision",
                f"{decision.get('decision', 'unknown')} decision for {plan_id}",
                decision,
                ingestion_run_id,
                str(decision.get("decided_at") or timestamp),
            )
        )
        relationships.append(
            _remediation_ontology_relationship(
                plan_id,
                "hasApprovalDecision",
                decision_id,
                ingestion_run_id,
                str(decision.get("decided_at") or timestamp),
                payload={"decision": decision.get("decision", "")},
            )
        )
    return entities, relationships


def remediation_plan_ontology_rows(
    projection: dict[str, Any],
    ingestion_run_id: str,
    timestamp: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities = [
        _remediation_ontology_entity(
            row["entity_id"],
            row["entity_type"],
            row["name"],
            row,
            ingestion_run_id,
            timestamp,
        )
        for row in projection.get("entities", [])
    ]
    relationships: list[dict[str, Any]] = []
    for row in projection.get("relationships", []):
        relationships.append(
            _remediation_ontology_relationship(
                str(row.get("subject_id") or ""),
                str(row.get("relationship_type") or ""),
                str(row.get("object_id") or ""),
                ingestion_run_id,
                timestamp,
                payload={
                    **({"payload": json.loads(str(row["payload_json"]))} if row.get("payload_json") else {}),
                    "confidence": float(row.get("confidence") or compute_confidence("inventory")),
                    "source": str(row.get("source") or "remediation-plan"),
                },
                object_type=str(row.get("object_type") or _remediation_object_type(str(row.get("relationship_type") or ""))),
                confidence=float(row.get("confidence") or compute_confidence("inventory")),
                source=str(row.get("source") or "remediation-plan"),
            )
        )
    return entities, relationships


def _dedupe_entity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapses rows that describe the same resource, keeping the typed one.

    The connector writes a Bastion host to both ``Resource.jsonl`` and
    ``NetworkGateway.jsonl``. Only the typed row carries the network payload
    (``subnetId``, ``vnetId``, ...), and feeding both to the entity builder
    raises a canonical-duplicate conflict, so the typed row wins.
    """
    by_id: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for row in rows:
        resource_id = str(row.get("resource_id") or "")
        if not resource_id:
            unkeyed.append(row)
            continue
        existing = by_id.get(resource_id)
        if existing is not None:
            # Whichever order the files were read in, the typed row wins and a
            # second generic row never displaces it.
            existing_generic = existing["entity_type"] == GENERIC_ENTITY_FILE
            row_generic = row["entity_type"] == GENERIC_ENTITY_FILE
            if row_generic or not existing_generic:
                continue
        by_id[resource_id] = row
    return [*by_id.values(), *unkeyed]


def _entity_row(row: dict[str, Any], entity_type: str, run_id: str) -> dict[str, Any]:
    base = _base(row, run_id)
    return {
        **base,
        "entity_type": entity_type,
        "name": str(row.get("name") or row.get("displayName") or ""),
        "resource_type": str(row.get("resourceType") or ""),
        "location": str(row.get("location") or ""),
        "payload_json": _canonical(row),
    }


def _asset_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        **_entity_row(row, str(row.get("entityType") or "Resource"), run_id),
        "resource_group": str(row.get("resourceGroup") or ""),
        "status": str(row.get("status") or ""),
        "os_name": str(row.get("osName") or row.get("osType") or ""),
        "os_version": str(row.get("osVersion") or ""),
        "vm_size": str(row.get("vmSize") or ""),
    }


def _cost_actual_row(
    row: dict[str, Any],
    run_id: str,
    subscription_tenants: dict[str, str],
) -> dict[str, Any]:
    result = _entity_row(row, "CostActual", run_id)
    if not result["tenant_id"]:
        result["tenant_id"] = subscription_tenants.get(result["subscription_id"].casefold(), "")
    result.update(
        {
            "usage_date": str(row.get("usageDate") or ""),
            "cost": float(row.get("cost") or 0),
            "currency": str(row.get("currency") or ""),
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "resource_group": str(row.get("resourceGroup") or ""),
            "service_name": str(row.get("serviceName") or ""),
            "billing_period_start": str(row.get("billingPeriodStart") or ""),
            "billing_period_end": str(row.get("billingPeriodEnd") or ""),
        }
    )
    return result


def _compliance_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _entity_row(row, "PatchAssessment", run_id)
    classifications = {
        str(key).casefold(): int(value or 0)
        for key, value in (row.get("availablePatchCountByClassification") or {}).items()
    }
    result.update(
        {
            "assessed_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "status": str(row.get("status") or "unknown"),
            "last_modified": str(row.get("lastModifiedDateTime") or ""),
            "available_updates": sum(classifications.values()),
            "missing_critical_updates": sum(
                value for key, value in classifications.items() if "critical" in key
            ),
            "missing_security_updates": sum(
                value for key, value in classifications.items() if "security" in key
            ),
        }
    )
    return result


def _patch_installation_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _entity_row(row, "PatchInstallation", run_id)
    classifications = row.get("classifications") or []
    errors = row.get("errorDetails") or []
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "update_id": str(row.get("kbId") or row.get("name") or ""),
            "update_name": str(row.get("updateName") or row.get("name") or ""),
            "category": ",".join(str(item) for item in classifications),
            "severity": "Critical"
            if any(str(item).casefold() == "critical" for item in classifications)
            else "Security"
            if any(str(item).casefold() == "security" for item in classifications)
            else "Unknown",
            "status": str(row.get("status") or "unknown"),
            "published_at": str(row.get("publishedDateTime") or ""),
            "installed_at": str(row.get("lastModifiedDateTime") or ""),
            "error": "; ".join(
                str(item.get("code") or item.get("message") or "")
                for item in errors
                if isinstance(item, dict)
            ),
        }
    )
    return result


def _patch_finding_row(row: dict[str, Any], run_id: str, *, status: str) -> dict[str, Any]:
    """Holistic per-KB row combining pending (``PatchAssessmentDetail``) and
    installed (``PatchInstallation``) patches so downstream consumers (the
    vulnerability intelligence service) can see both what is still missing
    and what has already been remediated for the same KB/target, rather than
    only the aggregate counts in ``silver_compliance``."""
    entity_type = "PatchAssessmentDetail" if status == "missing" else "PatchInstallation"
    result = _entity_row(row, entity_type, run_id)
    classifications = row.get("classifications") or []
    classifications = classifications if isinstance(classifications, list) else [str(classifications)]
    severity = str(row.get("msrcSeverity") or "").strip()
    if not severity:
        severity = (
            "Critical"
            if any(str(item).casefold() == "critical" for item in classifications)
            else "Security"
            if any(str(item).casefold() == "security" for item in classifications)
            else "Unknown"
        )
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "kb_id": str(row.get("kbId") or "").strip(),
            "update_name": str(row.get("updateName") or ""),
            "category": ",".join(str(item) for item in classifications),
            "severity": severity,
            "status": status,
            "published_at": str(row.get("publishedDateTime") or ""),
            "last_modified": str(row.get("lastModifiedDateTime") or ""),
        }
    )
    return result


def _defender_finding_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Flatten a Defender subassessment into the exposure-service contract."""
    result = _entity_row(row, "DefenderVulnerabilityFinding", run_id)
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "assessment_id": str(row.get("assessmentId") or "").casefold(),
            "cve_id": str(row.get("cveId") or "").upper(),
            "severity": str(row.get("severity") or "Unknown"),
            "status": str(row.get("status") or "Unhealthy"),
            "recommendation": str(row.get("recommendation") or ""),
            "description": str(row.get("description") or ""),
            "last_assessed_at": str(
                row.get("lastAssessedAt") or row.get("lastObservedTimestamp") or ""
            ),
            "patchable": bool(row.get("patchable", False)),
            "software_vendor": str(row.get("softwareVendor") or ""),
            "software_name": str(row.get("softwareName") or ""),
            "software_version": str(row.get("softwareVersion") or ""),
            "fixed_version": str(row.get("fixedVersion") or ""),
        }
    )
    return result


def _defender_assessment_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Flatten a Defender recommendation across any protected resource type."""
    result = _entity_row(row, "DefenderAssessment", run_id)
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "target_resource_type": str(row.get("resourceType") or ""),
            "status": str(row.get("status") or "Unhealthy"),
            "severity": str(row.get("severity") or "Unknown"),
            "recommendation": str(row.get("recommendation") or ""),
            "description": str(row.get("description") or ""),
            "remediation": str(row.get("remediation") or ""),
            "last_assessed_at": str(
                row.get("lastAssessedAt") or row.get("lastObservedTimestamp") or ""
            ),
        }
    )
    return result


def _container_image_exposure_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Flatten a rolled-up container image exposure into the exposure-service contract."""
    result = _entity_row(row, "ContainerImageExposure", run_id)
    result.update(
        {
            "target_resource_id": str(row.get("targetResourceId") or "").casefold(),
            "registry_resource_id": str(row.get("registryResourceId") or "").casefold(),
            "registry_host": str(row.get("registryHost") or ""),
            "repository": str(row.get("repository") or ""),
            "image_digest": str(row.get("imageDigest") or ""),
            "image_tags": list(row.get("imageTags") or []),
            "image_uri": str(row.get("imageUri") or ""),
            "last_pushed_at": str(row.get("lastPushedAt") or ""),
            "status": str(row.get("status") or "Unhealthy"),
            "severity": str(row.get("severity") or "Unknown"),
            "critical_count": int(row.get("criticalCount") or 0),
            "high_count": int(row.get("highCount") or 0),
            "vulnerable_package_count": int(row.get("vulnerablePackageCount") or 0),
            "cve_count": int(row.get("cveCount") or 0),
            "cve_ids": list(row.get("cveIds") or []),
            "vulnerable_packages": list(row.get("vulnerablePackages") or []),
            "recommendation": str(row.get("recommendation") or ""),
            "last_assessed_at": str(row.get("lastAssessedAt") or ""),
        }
    )
    return result


def _container_registry_rows(
    logical_images: list[dict[str, Any]],
    run_id: str,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for logical_image in logical_images:
        registry_id = str(logical_image.get("registryId") or "")
        candidate = {
            **_base(
                {**logical_image, "id": registry_id},
                run_id,
            ),
            "registry_id": registry_id,
            "identity_version": str(
                logical_image.get("identityVersion") or ""
            ),
            "contract_version": str(
                logical_image.get("contractVersion") or ""
            ),
            "registry_resource_id": str(
                logical_image.get("registryResourceId") or ""
            ).casefold(),
            "registry_host": str(
                logical_image.get("registryHost") or ""
            ).casefold(),
            "connection_id": _connection_id(logical_image),
            "source_system": str(
                logical_image.get("sourceSystem") or ""
            ),
            "source_ids": sorted(
                {
                    str(value)
                    for value in logical_image.get("sourceIds") or ()
                    if str(value)
                }
            ),
            "observed_at": str(
                logical_image.get("observedAt")
                or logical_image.get("lastObservedTimestamp")
                or ""
            ),
            "ingested_at": str(
                logical_image.get("ingestedAt")
                or logical_image.get("createdTimestamp")
                or ""
            ),
            "provenance_json": _canonical(
                logical_image.get("provenance") or {}
            ),
        }
        previous = rows.get(registry_id)
        if previous is None:
            rows[registry_id] = candidate
            continue
        invariant_fields = (
            "tenant_id",
            "subscription_id",
            "registry_resource_id",
            "registry_host",
            "identity_version",
            "contract_version",
        )
        if any(
            previous[field] != candidate[field]
            for field in invariant_fields
        ):
            raise ValueError("Container registry identity has conflicting content")
        previous["source_ids"] = sorted(
            {*previous["source_ids"], *candidate["source_ids"]}
        )
        previous["observed_at"] = max(
            previous["observed_at"],
            candidate["observed_at"],
        )
        previous["change_version"] = _version(
            {
                key: value
                for key, value in previous.items()
                if key != "change_version"
            }
        )
    return [rows[key] for key in sorted(rows)]


def _container_logical_image_row(
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    result = _base(row, run_id)
    result.update(
        {
            "logical_image_id": str(row.get("logicalImageId") or ""),
            "identity_version": str(row.get("identityVersion") or ""),
            "contract_version": str(row.get("contractVersion") or ""),
            "registry_id": str(row.get("registryId") or ""),
            "registry_resource_id": str(
                row.get("registryResourceId") or ""
            ).casefold(),
            "registry_host": str(row.get("registryHost") or "").casefold(),
            "repository": str(row.get("repository") or "").casefold(),
            "image_tags": sorted(
                {
                    str(value)
                    for value in row.get("imageTags") or ()
                    if str(value)
                }
            ),
            "connection_id": _connection_id(row),
            "source_system": str(row.get("sourceSystem") or ""),
            "source_ids": sorted(
                {
                    str(value)
                    for value in row.get("sourceIds") or ()
                    if str(value)
                }
            ),
            "observed_at": str(
                row.get("observedAt")
                or row.get("lastObservedTimestamp")
                or ""
            ),
            "ingested_at": str(
                row.get("ingestedAt")
                or row.get("createdTimestamp")
                or ""
            ),
            "provenance_json": _canonical(row.get("provenance") or {}),
        }
    )
    return result


def _container_image_digest_row(
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    result = _base(row, run_id)
    result.update(
        {
            "image_digest_id": str(row.get("imageDigestId") or ""),
            "identity_version": str(row.get("identityVersion") or ""),
            "contract_version": str(row.get("contractVersion") or ""),
            "image_digest": str(row.get("imageDigest") or "").casefold(),
            "logical_image_ids": sorted(
                {
                    str(value)
                    for value in row.get("logicalImageIds") or ()
                    if str(value)
                }
            ),
            "registry_ids": sorted(
                {
                    str(value)
                    for value in row.get("registryIds") or ()
                    if str(value)
                }
            ),
            "image_tags": sorted(
                {
                    str(value)
                    for value in row.get("imageTags") or ()
                    if str(value)
                }
            ),
            "connection_id": _connection_id(row),
            "source_system": str(row.get("sourceSystem") or ""),
            "source_ids": sorted(
                {
                    str(value)
                    for value in row.get("sourceIds") or ()
                    if str(value)
                }
            ),
            "observed_at": str(
                row.get("observedAt")
                or row.get("lastObservedTimestamp")
                or ""
            ),
            "ingested_at": str(
                row.get("ingestedAt")
                or row.get("createdTimestamp")
                or ""
            ),
            "provenance_json": _canonical(row.get("provenance") or {}),
        }
    )
    return result


def _container_vulnerability_observation_row(
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    result = _base(row, run_id)
    result["ingestion_run_id"] = str(
        row.get("sourceGeneration") or run_id
    )
    provider_event_time = row.get("providerEventTime")
    result.update(
        {
            "vulnerability_observation_id": str(
                row.get("vulnerabilityObservationId") or ""
            ),
            "identity_version": str(row.get("identityVersion") or ""),
            "contract_version": str(row.get("contractVersion") or ""),
            "registry_id": str(row.get("registryId") or ""),
            "logical_image_id": str(row.get("logicalImageId") or ""),
            "image_digest_id": str(row.get("imageDigestId") or ""),
            "image_digest": str(row.get("imageDigest") or "").casefold(),
            "target_kind": str(row.get("targetKind") or ""),
            "cve_id": str(row.get("cveId") or "").upper(),
            "assessment_id": str(row.get("assessmentId") or ""),
            "source_event_id": str(row.get("sourceEventId") or ""),
            "source_family": str(row.get("sourceFamily") or ""),
            "status": str(row.get("status") or ""),
            "severity": str(row.get("severity") or "Unknown"),
            "software_name": str(row.get("softwareName") or ""),
            "package_version": str(row.get("packageVersion") or ""),
            "fixed_version": str(row.get("fixedVersion") or ""),
            "provider_event_time": (
                str(provider_event_time) if provider_event_time else None
            ),
            "provider_event_time_quality": str(
                row.get("providerEventTimeQuality") or "unknown"
            ),
            "observed_at": str(
                row.get("observedAt")
                or row.get("lastObservedTimestamp")
                or ""
            ),
            "ingested_at": str(
                row.get("ingestedAt")
                or row.get("createdTimestamp")
                or ""
            ),
            "connection_id": _connection_id(row),
            "source_event_payload_json": _canonical(
                row.get("sourceEventPayload") or {}
            ),
            "provenance_json": _canonical(row.get("provenance") or {}),
        }
    )
    return result


def _validate_granular_container_products(
    datasets: Mapping[str, list[dict[str, Any]]],
) -> None:
    registries = {
        str(row.get("registry_id") or "")
        for row in datasets.get("silver_container_registries", ())
    }
    logical_images = {
        str(row.get("logical_image_id") or ""): row
        for row in datasets.get("silver_container_logical_images", ())
    }
    digests = {
        str(row.get("image_digest_id") or ""): row
        for row in datasets.get("silver_container_image_digests", ())
    }
    digest_pattern = re.compile(r"^sha256:[0-9a-f]{64}$")
    for row in logical_images.values():
        if str(row.get("registry_id") or "") not in registries:
            raise ValueError("Container logical image references an unknown registry")
    for row in digests.values():
        if not digest_pattern.fullmatch(str(row.get("image_digest") or "")):
            raise ValueError("Container image digest is not an immutable sha256")
        if not row.get("logical_image_ids") or any(
            logical_image_id not in logical_images
            for logical_image_id in row["logical_image_ids"]
        ):
            raise ValueError(
                "Container image digest references an unknown logical image"
            )
    for row in datasets.get(
        "silver_container_vulnerability_observations",
        (),
    ):
        if str(row.get("target_kind") or "") != "container_image":
            raise ValueError(
                "Container vulnerability observation has an unsafe target kind"
            )
        digest = digests.get(str(row.get("image_digest_id") or ""))
        if digest is None or digest.get("image_digest") != row.get("image_digest"):
            raise ValueError(
                "Container vulnerability observation has conflicting digest evidence"
            )
        if str(row.get("logical_image_id") or "") not in logical_images:
            raise ValueError(
                "Container vulnerability observation references an unknown logical image"
            )


def _connection_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("connection_id")
        or row.get("connectionId")
        or row.get("subscription_connection_id")
        or row.get("subscriptionConnectionId")
        or ""
    )


def _patch_history_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _compliance_row(row, run_id)
    observed = str(result.get("last_modified") or result.get("timestamp") or "unknown")
    result["resource_id"] = f"{result['resource_id']}|{observed}"
    return result


def _relationship_row(
    row: dict[str, Any],
    entity_index: dict[str, dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    subject = str(row.get("subjectId") or "").casefold()
    subject_entity = entity_index.get(subject, {})
    normalized = {
        **row,
        "subjectId": subject,
        "objectId": str(row.get("objectId") or "").casefold(),
    }
    return {
        "tenant_id": str(subject_entity.get("tenant_id") or ""),
        "subscription_id": str(subject_entity.get("subscription_id") or ""),
        "resource_id": str(row.get("relationshipId") or ""),
        "timestamp": str(row.get("lastObservedTimestamp") or ""),
        "change_version": _version(normalized),
        "ingestion_run_id": run_id,
        "subject_id": subject,
        "predicate": str(row.get("predicate") or ""),
        "object_id": normalized["objectId"],
        "confidence": float(row.get("confidence") or 0),
        "source": str(row.get("source") or ""),
        "payload_json": _canonical(row),
    }


def _change_row(
    row: dict[str, Any],
    entity_index: dict[str, dict[str, Any]],
    subscription_tenants: dict[str, str],
    run_id: str,
) -> dict[str, Any]:
    resource_id = str(row.get("targetResourceId") or row.get("id") or "").casefold()
    target = entity_index.get(resource_id, {})
    subscription = _subscription_from_id(resource_id)
    return {
        "tenant_id": str(
            row.get("tenantId")
            or target.get("tenant_id")
            or subscription_tenants.get(subscription.casefold())
            or ""
        ),
        "subscription_id": (
            subscription
            or str(row.get("subscriptionId") or target.get("subscription_id") or "")
        ),
        "resource_id": str(row.get("id") or "").casefold(),
        "timestamp": str(row.get("changedAt") or row.get("lastObservedTimestamp") or ""),
        "change_version": _version(row),
        "ingestion_run_id": run_id,
        "target_resource_id": resource_id,
        "change_type": str(row.get("changeType") or ""),
        "payload_json": _canonical(row),
    }


def _base(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    resource_id = str(row.get("id") or row.get("sourceId") or "").casefold()
    semantic = {
        key: value
        for key, value in row.items()
        if key not in {"createdTimestamp", "lastObservedTimestamp", "ingestion_run_id"}
    }
    return {
        "tenant_id": str(row.get("tenantId") or ""),
        "subscription_id": str(row.get("subscriptionId") or _subscription_from_id(resource_id)),
        "resource_id": resource_id,
        "timestamp": str(row.get("lastObservedTimestamp") or ""),
        "change_version": _version(semantic),
        "ingestion_run_id": run_id,
    }


def _situation_base(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    scope = row.get("scope") or {}
    subscription_ids = scope.get("subscription") if isinstance(scope, dict) else ()
    return {
        "tenant_id": str(row.get("tenant_id") or "unknown"),
        "subscription_id": str((subscription_ids or ["unknown"])[0]),
        "resource_id": str(row.get("resource_id") or row.get("situation_id") or "").casefold(),
        "timestamp": str(
            row.get("last_observed_at")
            or row.get("observed_at")
            or row.get("timestamp")
            or row.get("started_at")
            or "unknown"
        ),
        "change_version": _version(row),
        "ingestion_run_id": run_id,
    }


def _situation_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _situation_base(row, run_id)
    return {
        **result,
        "situation_id": str(row.get("situation_id") or result["resource_id"]),
        "title": str(row.get("title") or ""),
        "situation_type": str(row.get("situation_type") or ""),
        "lifecycle_state": str(row.get("lifecycle_state") or "open"),
        "severity": str(row.get("severity") or "unknown"),
        "priority": str(row.get("priority") or "P3"),
        "scope_json": _canonical(row.get("scope") or {}),
        "owner": str(row.get("owner") or ""),
        "support_team": str(row.get("support_team") or ""),
        "affected_resource_ids_json": _canonical(row.get("affected_resource_ids") or []),
        "linked_evidence_ids_json": _canonical(row.get("linked_evidence_ids") or []),
        "started_at": str(row.get("started_at") or ""),
        "last_observed_at": str(row.get("last_observed_at") or ""),
        "evidence_state": str(row.get("evidence_state") or "unknown"),
        "warnings_json": _canonical(row.get("warnings") or []),
        "contradiction_ids_json": _canonical(row.get("contradiction_ids") or []),
        "unknowns_json": _canonical(row.get("unknowns") or []),
    }


def _situation_evidence_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _situation_base(row, run_id)
    result["resource_id"] = str(row.get("evidence_id") or result["resource_id"]).casefold()
    return {
        **result,
        "evidence_id": str(row.get("evidence_id") or result["resource_id"]),
        "situation_id": str(row.get("situation_id") or ""),
        "source_family": str(row.get("source_family") or ""),
        "source_object_id": str(row.get("source_object_id") or ""),
        "locator": str(row.get("locator") or ""),
        "resource_ids_json": _canonical(row.get("resource_ids") or []),
        "observed_at": str(row.get("observed_at") or ""),
        "ingested_at": str(row.get("ingested_at") or ""),
        "watermark": str(row.get("watermark") or ""),
        "ingestion_status": str(row.get("ingestion_status") or "unknown"),
        "provenance_json": _canonical(row.get("provenance") or {}),
        "freshness": str(row.get("freshness") or "unknown"),
        "quality": str(row.get("quality") or "unknown"),
        "availability": str(row.get("availability") or "unknown"),
        "confidence": _confidence_number(row.get("confidence")),
        "assertion": str(row.get("assertion") or ""),
        "fingerprint": str(row.get("fingerprint") or ""),
    }


def _situation_link_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _situation_base(row, run_id)
    result["resource_id"] = str(row.get("link_id") or result["resource_id"]).casefold()
    return {
        **result,
        "link_id": str(row.get("link_id") or result["resource_id"]),
        "situation_id": str(row.get("situation_id") or ""),
        "entity_type": str(row.get("entity_type") or ""),
        "entity_id": str(row.get("entity_id") or "").casefold(),
        "relation": str(row.get("relation") or ""),
        "quality": str(row.get("quality") or "unresolved"),
        "provenance_json": _canonical(row.get("provenance") or {}),
    }


def _audit_event_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _situation_base(row, run_id)
    event_timestamp = str(row.get("timestamp") or "")
    result["resource_id"] = str(row.get("event_id") or result["resource_id"]).casefold()
    result["timestamp"] = event_timestamp
    result["change_version"] = _version(row)
    return {
        **result,
        "event_id": str(row.get("event_id") or result["resource_id"]),
        "actor": str(row.get("actor") or ""),
        "action": str(row.get("action") or ""),
        "scope_snapshot_json": _canonical(row.get("scope_snapshot") or {}),
        "event_timestamp": event_timestamp,
        "situation_id": str(row.get("situation_id") or ""),
        "evidence_ids_json": _canonical(row.get("evidence_ids") or []),
        "source_references_json": _canonical(row.get("source_references") or []),
    }


def _source_status_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    source_family = str(row.get("source_family") or "unknown")
    requested_scope = row.get("requested_scope") or {}
    subscriptions = requested_scope.get("subscription") if isinstance(requested_scope, dict) else []
    resource_id = f"source-status://{source_family}/{row.get('run_id') or run_id}".casefold()
    timestamp = str(row.get("ingested_at") or row.get("observed_at") or "unknown")
    return {
        "tenant_id": "unknown",
        "subscription_id": str((subscriptions or ["unknown"])[0]),
        "resource_id": resource_id,
        "timestamp": timestamp,
        "change_version": _version(row),
        "ingestion_run_id": run_id,
        "source_family": source_family,
        "status": str(row.get("status") or "unknown"),
        "observed_at": str(row.get("observed_at") or ""),
        "ingested_at": str(row.get("ingested_at") or ""),
        "watermark": str(row.get("watermark") or ""),
        "query_version": str(row.get("query_version") or ""),
        "requested_scope_json": _canonical(requested_scope),
        "provider_status": str(row.get("provider_status") or ""),
        "freshness": str(row.get("freshness") or "unknown"),
        "availability": str(row.get("availability") or "unknown"),
        "quality": str(row.get("quality") or "unknown"),
        "error": str(row.get("error") or ""),
        # MED-03: dataset-agnostic health provider
        # (`src/fabric/medallion_health.py::dataset_status`) evidence.
        # `None` (unknown row count) stays `None` -- callers must not
        # confuse "row count not reported by this source" with zero rows.
        "row_count": _optional_int(row.get("row_count")),
        "lineage_ref": str(row.get("lineage_ref") or ""),
    }


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _situation_ontology_entity(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    result = _situation_base(row, run_id)
    payload = {
        "situation_id": str(row.get("situation_id") or ""),
        "title": str(row.get("title") or ""),
        "severity": str(row.get("severity") or ""),
        "priority": str(row.get("priority") or ""),
        "scope": row.get("scope") or {},
    }
    return {
        **result,
        "entity_type": "Situation",
        "name": payload["title"] or payload["situation_id"],
        "resource_type": "aiops/situation",
        "location": "",
        "payload_json": _canonical(payload),
        "lineage_json": _canonical({"source_resource_ids": row.get("affected_resource_ids") or []}),
        "semantic_metadata_json": _canonical({"projection": "situation", "source": "delta"}),
        "lifecycle_status": "active",
        "valid_from": str(row.get("started_at") or result["timestamp"]),
        "retired_at": "",
        "ontology_version": "1",
    }


def _confidence_number(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.4,
        "unknown": 0.0,
    }.get(str(value or "unknown").casefold(), 0.0)
def _situation_ontology_relationship(
    link: dict[str, Any],
    situations: list[dict[str, Any]],
    known_types: dict[str, str],
    run_id: str,
) -> dict[str, Any] | None:
    situation_id = str(link.get("situation_id") or "")
    entity_id = str(link.get("entity_id") or "").casefold()
    if (
        str(link.get("quality") or "") != "resolved"
        or not entity_id
        or entity_id not in known_types
    ):
        return None
    situation = next((row for row in situations if row.get("situation_id") == situation_id), {})
    subject_id = str(situation.get("resource_id") or situation_id).casefold()
    entity_type = known_types[entity_id]
    relation = str(link.get("relation") or "affects")
    relationship_id = _version([subject_id, relation, entity_id, entity_type])
    return {
        "tenant_id": "unknown",
        "subscription_id": str((situation.get("scope") or {}).get("subscription", ["unknown"])[0]),
        "resource_id": relationship_id,
        "timestamp": str(situation.get("last_observed_at") or ""),
        "change_version": relationship_id,
        "ingestion_run_id": run_id,
        "subject_id": subject_id,
        "subject_type": "Situation",
        "predicate": relation,
        "object_id": entity_id,
        "object_type": entity_type,
        "confidence": 1.0,
        "source": "situation-link",
        "payload_json": _canonical({"relation": relation}),
        "lineage_json": _canonical({"source_entity_ids": [subject_id, entity_id]}),
        "lifecycle_status": "active",
        "valid_from": str(situation.get("started_at") or ""),
        "retired_at": "",
        "ontology_version": "1",
    }


def _remediation_ontology_entity(
    resource_id: str,
    entity_type: str,
    name: str,
    payload: dict[str, Any],
    run_id: str,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": resource_id,
        "timestamp": timestamp,
        "change_version": _version(payload),
        "ingestion_run_id": run_id,
        "entity_type": entity_type,
        "name": name,
        "resource_type": "aiops/remediation",
        "location": "",
        "payload_json": _canonical(payload),
        "lineage_json": _canonical({"source_resource_ids": [resource_id]}),
        "semantic_metadata_json": _canonical(
            {"projection": "remediation", "source": "decision-store"}
        ),
        "lifecycle_status": "active",
        "valid_from": timestamp,
        "retired_at": "",
        "ontology_version": "1",
    }


def _remediation_ontology_relationship(
    subject_id: str,
    predicate: str,
    object_id: str,
    run_id: str,
    timestamp: str,
    *,
    payload: dict[str, Any],
    object_type: str = "ApprovalDecision",
    confidence: float = 1.0,
    source: str = "remediation-decision-store",
) -> dict[str, Any]:
    relationship_id = "remediation-rel://" + _version(
        {"subject_id": subject_id, "predicate": predicate, "object_id": object_id}
    )[:32]
    return {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": relationship_id,
        "timestamp": timestamp,
        "change_version": _version(payload),
        "ingestion_run_id": run_id,
        "subject_id": subject_id,
        "subject_type": "RemediationPlan",
        "predicate": predicate,
        "object_id": object_id,
        "object_type": object_type,
        "confidence": confidence,
        "source": source,
        "payload_json": _canonical(payload),
        "lineage_json": _canonical({"source_entity_ids": [subject_id, object_id]}),
        "lifecycle_status": "active",
        "valid_from": timestamp,
        "retired_at": "",
        "ontology_version": "1",
    }


def _remediation_object_type(predicate: str) -> str:
    return {
        "hasApprovalDecision": "ApprovalDecision",
        "addressesFinding": "DefenderAssessment",
        "addressesAlert": "SecurityAlert",
        "breaksAttackPath": "AttackPath",
        "improvesControl": "SecureScoreControl",
        "requiresApproval": "ApprovalRequirement",
        "hasStep": "ExecutionStep",
        "hasRollbackPlan": "RollbackPlan",
        "hasSimulation": "SimulationResult",
        "mitigatesRisk": "RiskAssessment",
        "protectsService": "BusinessService",
    }.get(predicate, "ApprovalDecision")


def _version(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _subscription_from_id(value: str) -> str:
    parts = value.split("/")
    try:
        return parts[parts.index("subscriptions") + 1]
    except (ValueError, IndexError):
        return ""


def _read_jsonl(fs, path: str) -> list[dict[str, Any]]:
    if not fs.exists(path):
        return []
    with fs.open(path, "rt") as handle:
        return [json.loads(line) for line in handle.read().splitlines() if line.strip()]


def ontology_entity_table(entity_type: str) -> str:
    return f"ontology_{_slug(entity_type)}_entities"


def ontology_relationship_table(subject_type: str, predicate: str, object_type: str) -> str:
    return f"ontology_rel_{_slug(predicate)}_{_slug(subject_type)}_{_slug(object_type)}"


def _slug(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", words.casefold()).strip("_")


def _health_row(health: dict[str, Any], run_id: str, timestamp: str) -> dict[str, Any]:
    row = {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": f"ontology-health://{run_id}",
        "timestamp": timestamp,
        "change_version": _version(health),
        "ingestion_run_id": run_id,
        "entity_count": int(health["entity_count"]),
        "relationship_count": int(health["relationship_count"]),
        "orphan_resources": int(health["orphan_resources"]),
        "missing_ownership": int(health["missing_ownership"]),
        "missing_tags": int(health["missing_tags"]),
        "synchronization_errors": int(health["synchronization_errors"]),
    }
    return row


def _read_json(fs, path: str) -> dict[str, Any]:
    if not fs.exists(path):
        return {}
    with fs.open(path, "rt") as handle:
        return json.loads(handle.read())


def _ontology_quality_row(
    report: dict[str, Any], run_id: str, timestamp: str
) -> dict[str, Any]:
    return {
        "tenant_id": "system",
        "subscription_id": "system",
        "resource_id": f"ontology-quality://{run_id}",
        "timestamp": timestamp,
        "change_version": _version(report),
        "ingestion_run_id": run_id,
        "passed": bool(report["passed"]),
        "report_json": _canonical(report),
    }
