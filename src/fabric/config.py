from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .auth import FabricAuthConfig


@dataclass(frozen=True)
class ShortcutDefinition:
    path: str
    name: str
    target: dict[str, Any]
    conflict_policy: str = "CreateOrOverwrite"


@dataclass(frozen=True)
class OntologyRuntimeConfig:
    enabled: bool = True
    ontology_id: str = ""
    ontology_name: str = "Operational_Context_Graph"


@dataclass(frozen=True)
class PipelineToggleRuntimeConfig:
    enabled: bool = False


@dataclass(frozen=True)
class PatchPolicyRuntimeConfig:
    name: str
    environment: str
    max_patch_age_days: int
    minimum_compliance_score: int


@dataclass(frozen=True)
class PatchIntelligenceRuntimeConfig:
    enabled: bool = True
    max_resources: int = 5000
    max_evidence_rows: int = 50000
    max_output_items: int = 100
    max_serialized_bytes: int = 1_000_000


@dataclass(frozen=True)
class OperationsAgentRuntimeConfig:
    max_output_items: int = 100
    max_serialized_bytes: int = 1_000_000


@dataclass(frozen=True)
class SemanticRuntimeConfig:
    max_results: int = 50
    max_traversal_nodes: int = 500
    max_traversal_depth: int = 32
    max_source_rows: int = 50000
    max_serialized_bytes: int = 1_000_000


@dataclass(frozen=True)
class LifecycleRuntimeConfig:
    enabled: bool = True
    catalog_path: Path | None = None
    approaching_months: int = 24
    near_months: int = 12
    critical_months: int = 6
    max_output_items: int = 100
    max_serialized_bytes: int = 1_000_000


@dataclass(frozen=True)
class IncidentCausalityRuntimeConfig:
    enabled: bool = True
    lookback_hours: int = 168
    max_incidents: int = 10000
    max_evidence_rows: int = 50000


@dataclass(frozen=True)
class ChangeIntelligenceRuntimeConfig:
    enabled: bool = True
    max_changes: int = 50000
    max_output_items: int = 100


@dataclass(frozen=True)
class PredictiveRuntimeConfig:
    enabled: bool = True
    max_history_rows: int = 50000
    max_output_items: int = 100


@dataclass(frozen=True)
class RemediationRuntimeConfig:
    enabled: bool = True
    max_resources: int = 5000
    max_plans: int = 1000
    max_output_items: int = 100
    max_dependencies: int = 100


@dataclass(frozen=True)
class CapacityRuntimeConfig:
    subscription_id: str = ""
    resource_group: str = ""
    capacity_name: str = ""


@dataclass(frozen=True)
class FabricRuntimeConfig:
    auth: FabricAuthConfig
    source_data_root: Path
    workspace_id: str = ""
    workspace_name: str = ""
    lakehouse_id: str = ""
    lakehouse_name: str = ""
    capacity: CapacityRuntimeConfig = field(default_factory=CapacityRuntimeConfig)
    create_lakehouse_if_missing: bool = False
    local_onelake_root: Path | None = None
    shortcuts: tuple[ShortcutDefinition, ...] = field(default_factory=tuple)
    registration_attempts: int = 20
    write_workers: int = 4
    table_schema: str = ""
    # Read acceleration via the Lakehouse SQL analytics endpoint. Enabled by
    # default and degrades silently to Delta reads when the endpoint or an
    # ODBC driver is unavailable.
    sql_endpoint_enabled: bool = True
    ontology: OntologyRuntimeConfig = field(default_factory=OntologyRuntimeConfig)
    topology_pipeline: PipelineToggleRuntimeConfig = field(
        default_factory=PipelineToggleRuntimeConfig
    )
    ontology_pipeline: PipelineToggleRuntimeConfig = field(
        default_factory=PipelineToggleRuntimeConfig
    )
    patch_policies: tuple[PatchPolicyRuntimeConfig, ...] = field(default_factory=tuple)
    patch_intelligence: PatchIntelligenceRuntimeConfig = field(
        default_factory=PatchIntelligenceRuntimeConfig
    )
    operations_agent: OperationsAgentRuntimeConfig = field(
        default_factory=OperationsAgentRuntimeConfig
    )
    semantic: SemanticRuntimeConfig = field(default_factory=SemanticRuntimeConfig)
    lifecycle: LifecycleRuntimeConfig = field(default_factory=LifecycleRuntimeConfig)
    incident_causality: IncidentCausalityRuntimeConfig = field(
        default_factory=IncidentCausalityRuntimeConfig
    )
    change_intelligence: ChangeIntelligenceRuntimeConfig = field(
        default_factory=ChangeIntelligenceRuntimeConfig
    )
    predictive: PredictiveRuntimeConfig = field(default_factory=PredictiveRuntimeConfig)
    remediation: RemediationRuntimeConfig = field(default_factory=RemediationRuntimeConfig)

    @classmethod
    def load(cls, path: str | Path) -> FabricRuntimeConfig:
        config_path = Path(path).expanduser().resolve()
        payload = yaml.safe_load(config_path.read_text()) or {}
        fabric = payload.get("fabric") or {}
        source = _resolve_path(config_path.parent, fabric.get("source_data_root") or "./data")
        local_value = fabric.get("local_onelake_root")
        local = _resolve_path(config_path.parent, local_value) if local_value else None
        shortcuts = tuple(
            ShortcutDefinition(
                path=str(item.get("path") or ""),
                name=str(item.get("name") or ""),
                target=dict(item.get("target") or {}),
                conflict_policy=str(item.get("conflict_policy") or "CreateOrOverwrite"),
            )
            for item in (fabric.get("shortcuts") or [])
        )
        ontology_payload = fabric.get("ontology") or {}
        raw_topology_payload = fabric.get("topology_pipeline", {})
        if raw_topology_payload is False:
            topology_payload = {"enabled": False}
        elif isinstance(raw_topology_payload, dict):
            topology_payload = raw_topology_payload
        else:
            raise TypeError("fabric.topology_pipeline must be a mapping or false")
        topology_enabled = topology_payload.get("enabled", False)
        if not isinstance(topology_enabled, bool):
            raise TypeError("fabric.topology_pipeline.enabled must be boolean")
        raw_ontology_pipeline_payload = fabric.get("ontology_pipeline", {})
        if raw_ontology_pipeline_payload is False:
            ontology_pipeline_payload = {"enabled": False}
        elif isinstance(raw_ontology_pipeline_payload, dict):
            ontology_pipeline_payload = raw_ontology_pipeline_payload
        else:
            raise TypeError("fabric.ontology_pipeline must be a mapping or false")
        ontology_pipeline_enabled = ontology_pipeline_payload.get("enabled", False)
        if not isinstance(ontology_pipeline_enabled, bool):
            raise TypeError("fabric.ontology_pipeline.enabled must be boolean")
        raw_patch_payload = fabric.get("patch_intelligence", {})
        if raw_patch_payload is False:
            patch_payload = {"enabled": False}
        elif isinstance(raw_patch_payload, dict):
            patch_payload = raw_patch_payload
        else:
            raise TypeError("fabric.patch_intelligence must be a mapping or false")
        patch_enabled = patch_payload.get("enabled", True)
        if not isinstance(patch_enabled, bool):
            raise TypeError("fabric.patch_intelligence.enabled must be boolean")
        raw_operations_payload = fabric.get("operations_agent", {})
        if not isinstance(raw_operations_payload, dict):
            raise TypeError("fabric.operations_agent must be a mapping")
        raw_semantic_payload = fabric.get("semantic", {})
        if not isinstance(raw_semantic_payload, dict):
            raise TypeError("fabric.semantic must be a mapping")
        raw_patch_policies = fabric.get("patch_policies") or []
        raw_capacity_payload = fabric.get("capacity", {})
        if not isinstance(raw_capacity_payload, dict):
            raise TypeError("fabric.capacity must be a mapping")
        if not isinstance(raw_patch_policies, list) or any(
            not isinstance(item, dict) for item in raw_patch_policies
        ):
            raise TypeError("fabric.patch_policies must be a list of mappings")
        for item in raw_patch_policies:
            age = item.get("max_patch_age_days")
            score = item.get("minimum_compliance_score")
            if isinstance(age, bool) or not isinstance(age, int):
                raise TypeError(
                    "fabric.patch_policies.max_patch_age_days must be an integer"
                )
            if isinstance(score, bool) or not isinstance(score, int):
                raise TypeError(
                    "fabric.patch_policies.minimum_compliance_score must be an integer"
                )
        raw_lifecycle_payload = fabric.get("lifecycle", {})
        if raw_lifecycle_payload is False:
            lifecycle_payload = {"enabled": False}
        elif isinstance(raw_lifecycle_payload, dict):
            lifecycle_payload = raw_lifecycle_payload
        else:
            raise TypeError("fabric.lifecycle must be a mapping or false")
        lifecycle_enabled = lifecycle_payload.get("enabled", True)
        if not isinstance(lifecycle_enabled, bool):
            raise TypeError("fabric.lifecycle.enabled must be boolean")
        raw_incident_payload = fabric.get("incident_causality", {})
        if raw_incident_payload is False:
            incident_payload = {"enabled": False}
        elif isinstance(raw_incident_payload, dict):
            incident_payload = raw_incident_payload
        else:
            raise TypeError("fabric.incident_causality must be a mapping or false")
        incident_enabled = incident_payload.get("enabled", True)
        if not isinstance(incident_enabled, bool):
            raise TypeError("fabric.incident_causality.enabled must be boolean")
        raw_change_payload = fabric.get("change_intelligence", {})
        if raw_change_payload is False:
            change_payload = {"enabled": False}
        elif isinstance(raw_change_payload, dict):
            change_payload = raw_change_payload
        else:
            raise ValueError("fabric.change_intelligence must be a mapping or false")
        change_enabled = change_payload.get("enabled", True)
        if not isinstance(change_enabled, bool):
            raise TypeError("fabric.change_intelligence.enabled must be boolean")
        raw_predictive_payload = fabric.get("predictive", {})
        if raw_predictive_payload is False:
            predictive_payload = {"enabled": False}
        elif isinstance(raw_predictive_payload, dict):
            predictive_payload = raw_predictive_payload
        else:
            raise TypeError("fabric.predictive must be a mapping or false")
        predictive_enabled = predictive_payload.get("enabled", True)
        if not isinstance(predictive_enabled, bool):
            raise TypeError("fabric.predictive.enabled must be boolean")
        raw_remediation_payload = fabric.get("remediation", {})
        if raw_remediation_payload is False:
            remediation_payload = {"enabled": False}
        elif isinstance(raw_remediation_payload, dict):
            remediation_payload = raw_remediation_payload
        else:
            raise TypeError("fabric.remediation must be a mapping or false")
        remediation_enabled = remediation_payload.get("enabled", True)
        if not isinstance(remediation_enabled, bool):
            raise TypeError("fabric.remediation.enabled must be boolean")
        lifecycle_catalog = lifecycle_payload.get("catalog_path")
        config = cls(
            auth=FabricAuthConfig.from_mapping(fabric.get("auth") or {}),
            source_data_root=source,
            workspace_id=str(fabric.get("workspace_id") or ""),
            workspace_name=str(fabric.get("workspace_name") or ""),
            lakehouse_id=str(fabric.get("lakehouse_id") or ""),
            lakehouse_name=str(fabric.get("lakehouse_name") or ""),
            capacity=CapacityRuntimeConfig(
                subscription_id=str(raw_capacity_payload.get("subscription_id") or ""),
                resource_group=str(raw_capacity_payload.get("resource_group") or ""),
                capacity_name=str(raw_capacity_payload.get("capacity_name") or ""),
            ),
            create_lakehouse_if_missing=bool(fabric.get("create_lakehouse_if_missing", False)),
            local_onelake_root=local,
            shortcuts=shortcuts,
            registration_attempts=int(fabric.get("registration_attempts") or 20),
            write_workers=int(fabric.get("write_workers") or 4),
            table_schema=str(fabric.get("table_schema") or ""),
            sql_endpoint_enabled=bool(fabric.get("sql_endpoint_enabled", True)),
            ontology=OntologyRuntimeConfig(
                enabled=bool(ontology_payload.get("enabled", True)),
                ontology_id=str(ontology_payload.get("ontology_id") or ""),
                ontology_name=str(
                    ontology_payload.get("ontology_name") or "Operational_Context_Graph"
                ),
            ),
            topology_pipeline=PipelineToggleRuntimeConfig(enabled=topology_enabled),
            ontology_pipeline=PipelineToggleRuntimeConfig(
                enabled=ontology_pipeline_enabled
            ),
            patch_policies=tuple(
                PatchPolicyRuntimeConfig(
                    name=str(item.get("name") or ""),
                    environment=str(item.get("environment") or ""),
                    max_patch_age_days=item["max_patch_age_days"],
                    minimum_compliance_score=item["minimum_compliance_score"],
                )
                for item in raw_patch_policies
            ),
            patch_intelligence=PatchIntelligenceRuntimeConfig(
                enabled=patch_enabled,
                max_resources=_strict_section_int(
                    patch_payload, "patch_intelligence", "max_resources", 5000
                ),
                max_evidence_rows=_strict_section_int(
                    patch_payload,
                    "patch_intelligence",
                    "max_evidence_rows",
                    50000,
                ),
                max_output_items=_strict_section_int(
                    patch_payload, "patch_intelligence", "max_output_items", 100
                ),
                max_serialized_bytes=_strict_section_int(
                    patch_payload,
                    "patch_intelligence",
                    "max_serialized_bytes",
                    1_000_000,
                ),
            ),
            operations_agent=OperationsAgentRuntimeConfig(
                max_output_items=_strict_section_int(
                    raw_operations_payload,
                    "operations_agent",
                    "max_output_items",
                    100,
                ),
                max_serialized_bytes=_strict_section_int(
                    raw_operations_payload,
                    "operations_agent",
                    "max_serialized_bytes",
                    1_000_000,
                ),
            ),
            semantic=SemanticRuntimeConfig(
                max_results=_strict_section_int(
                    raw_semantic_payload, "semantic", "max_results", 50
                ),
                max_traversal_nodes=_strict_section_int(
                    raw_semantic_payload,
                    "semantic",
                    "max_traversal_nodes",
                    500,
                ),
                max_traversal_depth=_strict_section_int(
                    raw_semantic_payload,
                    "semantic",
                    "max_traversal_depth",
                    32,
                ),
                max_source_rows=_strict_section_int(
                    raw_semantic_payload, "semantic", "max_source_rows", 50000
                ),
                max_serialized_bytes=_strict_section_int(
                    raw_semantic_payload,
                    "semantic",
                    "max_serialized_bytes",
                    1_000_000,
                ),
            ),
            lifecycle=LifecycleRuntimeConfig(
                enabled=lifecycle_enabled,
                catalog_path=(
                    _resolve_path(config_path.parent, lifecycle_catalog)
                    if lifecycle_catalog
                    else None
                ),
                approaching_months=_strict_section_int(
                    lifecycle_payload, "lifecycle", "approaching_months", 24
                ),
                near_months=_strict_section_int(
                    lifecycle_payload, "lifecycle", "near_months", 12
                ),
                critical_months=_strict_section_int(
                    lifecycle_payload, "lifecycle", "critical_months", 6
                ),
                max_output_items=_strict_section_int(
                    lifecycle_payload, "lifecycle", "max_output_items", 100
                ),
                max_serialized_bytes=_strict_section_int(
                    lifecycle_payload,
                    "lifecycle",
                    "max_serialized_bytes",
                    1_000_000,
                ),
            ),
            incident_causality=IncidentCausalityRuntimeConfig(
                enabled=incident_enabled,
                lookback_hours=_strict_section_int(
                    incident_payload, "incident_causality", "lookback_hours", 168
                ),
                max_incidents=_strict_section_int(
                    incident_payload, "incident_causality", "max_incidents", 10000
                ),
                max_evidence_rows=_strict_section_int(
                    incident_payload,
                    "incident_causality",
                    "max_evidence_rows",
                    50000,
                ),
            ),
            change_intelligence=ChangeIntelligenceRuntimeConfig(
                enabled=change_enabled,
                max_changes=int(change_payload.get("max_changes", 50000)),
                max_output_items=int(change_payload.get("max_output_items", 100)),
            ),
            predictive=PredictiveRuntimeConfig(
                enabled=predictive_enabled,
                max_history_rows=_strict_positive_int(
                    predictive_payload, "max_history_rows", 50000
                ),
                max_output_items=_strict_positive_int(
                    predictive_payload, "max_output_items", 100
                ),
            ),
            remediation=RemediationRuntimeConfig(
                enabled=remediation_enabled,
                max_resources=_strict_section_int(
                    remediation_payload, "remediation", "max_resources", 5000
                ),
                max_plans=_strict_section_int(
                    remediation_payload, "remediation", "max_plans", 1000
                ),
                max_output_items=_strict_section_int(
                    remediation_payload, "remediation", "max_output_items", 100
                ),
                max_dependencies=_strict_section_int(
                    remediation_payload, "remediation", "max_dependencies", 100
                ),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.workspace_id and not self.workspace_name:
            raise ValueError("Configure fabric.workspace_id or fabric.workspace_name")
        if not self.lakehouse_id and not self.lakehouse_name:
            raise ValueError("Configure fabric.lakehouse_id or fabric.lakehouse_name")
        if self.registration_attempts < 1:
            raise ValueError("fabric.registration_attempts must be positive")
        if self.write_workers < 1:
            raise ValueError("fabric.write_workers must be positive")
        if self.ontology.enabled and not self.ontology.ontology_name and not self.ontology.ontology_id:
            raise ValueError("Configure fabric.ontology.ontology_name or ontology_id")
        for shortcut in self.shortcuts:
            if not shortcut.path or not shortcut.name or not shortcut.target:
                raise ValueError("Fabric shortcuts require path, name, and target")
        for policy in self.patch_policies:
            if (
                not policy.name
                or not policy.environment
                or policy.max_patch_age_days < 1
                or not 0 <= policy.minimum_compliance_score <= 100
            ):
                raise ValueError("Fabric patch policies require valid names, environments, ages, and scores")
        if (
            min(
                self.patch_intelligence.max_resources,
                self.patch_intelligence.max_evidence_rows,
                self.patch_intelligence.max_output_items,
            )
            < 1
            or self.patch_intelligence.max_serialized_bytes < 1024
        ):
            raise ValueError("Fabric patch intelligence bounds are invalid")
        if (
            self.operations_agent.max_output_items < 1
            or self.operations_agent.max_serialized_bytes < 1024
        ):
            raise ValueError("Fabric Operations Agent output bounds are invalid")
        if (
            min(
                self.semantic.max_results,
                self.semantic.max_traversal_nodes,
                self.semantic.max_traversal_depth,
                self.semantic.max_source_rows,
            )
            < 1
            or self.semantic.max_serialized_bytes < 1024
            or self.semantic.max_traversal_depth > 256
        ):
            raise ValueError("Fabric Semantic Layer bounds are invalid")
        if not (
            self.lifecycle.approaching_months
            > self.lifecycle.near_months
            > self.lifecycle.critical_months
            > 0
        ):
            raise ValueError(
                "Fabric lifecycle thresholds must descend: approaching > near > critical > 0"
            )
        if (
            self.lifecycle.max_output_items < 1
            or self.lifecycle.max_serialized_bytes < 1024
        ):
            raise ValueError("Fabric lifecycle output bounds are invalid")
        incident_bounds = (
            self.incident_causality.lookback_hours,
            self.incident_causality.max_incidents,
            self.incident_causality.max_evidence_rows,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in incident_bounds
        ) or not isinstance(self.incident_causality.enabled, bool):
            raise ValueError("Fabric incident causality bounds must be positive")
        if (
            self.change_intelligence.max_changes < 1
            or self.change_intelligence.max_output_items < 1
        ):
            raise ValueError("Fabric change intelligence bounds must be positive")
        if (
            self.predictive.max_history_rows < 1
            or self.predictive.max_output_items < 1
        ):
            raise ValueError("Fabric predictive bounds must be positive")
        if min(
            self.remediation.max_resources,
            self.remediation.max_plans,
            self.remediation.max_output_items,
            self.remediation.max_dependencies,
        ) < 1:
            raise ValueError("Fabric remediation bounds must be positive")


def _resolve_path(base: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _strict_positive_int(payload: dict[str, object], name: str, default: int) -> int:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"fabric.predictive.{name} must be an integer")
    return value


def _strict_section_int(
    payload: dict[str, object], section: str, name: str, default: int
) -> int:
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"fabric.{section}.{name} must be an integer")
    return value
