from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from types import MethodType
from typing import Any, Callable

from ontology.ontology_manager import OntologyManager
from ontology.ontology_publisher import OntologyPublisher
from storage.delta_writer import DeltaWriter
from storage.onelake_writer import OneLakeWriter

from .auth import build_credential, build_delta_storage_options
from .config import FabricRuntimeConfig
from .data_quality import DataQualityValidator
from .fabric_client import FabricClient
from .lakehouse_manager import LakehouseManager
from .sync_service import FabricSyncService
from .workspace_manager import WorkspaceManager


def _select_factory_kwargs(
    factory: Callable[..., Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Keep only the snapshot keys a factory (or its constructor) accepts.

    Governed snapshots are shared across providers and may carry keys that a
    given intelligence factory does not model. Those factories accept
    ``**kwargs`` and forward them to their constructor, so an undeclared key
    raises ``TypeError`` and takes down every provider refresh. When the
    factory itself declares ``**kwargs`` the surplus keys are still meaningful
    to the constructor, so both signatures are consulted before filtering.
    """

    def declared(func: Callable[..., Any]) -> tuple[set[str], bool]:
        parameters = inspect.signature(func).parameters
        names = {
            name
            for name, parameter in parameters.items()
            if parameter.kind
            in (parameter.KEYWORD_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        }
        accepts_extra = any(
            parameter.kind is parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        return names, accepts_extra

    accepted, accepts_extra = declared(factory)
    if accepts_extra and isinstance(factory, MethodType):
        # Bound classmethod: surplus kwargs are forwarded to the constructor.
        accepted |= declared(factory.__self__.__init__)[0]
    return {key: value for key, value in snapshot.items() if key in accepted}


@dataclass(frozen=True)
class FabricRuntime:
    config: FabricRuntimeConfig
    workspace: dict
    lakehouse: dict
    service: FabricSyncService
    _semantic: Any = field(default=None, init=False, repr=False, compare=False)
    _semantic_version: str = field(default="", init=False, repr=False, compare=False)
    _operations: Any = field(default=None, init=False, repr=False, compare=False)
    _operations_semantic: Any = field(default=None, init=False, repr=False, compare=False)

    def semantic_engine(self):
        from semantic.semantic_engine import SemanticEngine

        snapshot = None
        if hasattr(self.service, "semantic_version"):
            version = str(self.service.semantic_version())
        else:
            snapshot = self.service.semantic_snapshot()
            version = str(snapshot.get("knowledge_version") or "")
        if self._semantic is not None and self._semantic_version == version:
            return self._semantic
        snapshot = snapshot or self.service.semantic_snapshot()
        semantic_config = self.config.semantic if self.config is not None else None
        engine = SemanticEngine.from_rows(
            **snapshot,
            max_results=(semantic_config.max_results if semantic_config else 50),
            max_traversal_nodes=(
                semantic_config.max_traversal_nodes if semantic_config else 500
            ),
            max_traversal_depth=(
                semantic_config.max_traversal_depth if semantic_config else 32
            ),
            max_source_rows=(
                semantic_config.max_source_rows if semantic_config else 50000
            ),
            max_serialized_bytes=(
                semantic_config.max_serialized_bytes
                if semantic_config
                else 1_000_000
            ),
        )
        object.__setattr__(self, "_semantic", engine)
        object.__setattr__(self, "_semantic_version", version)
        return engine

    def operations_agent(self):
        from agents.operations import OperationsAgent
        from intelligence.change import ChangeIntelligence
        from intelligence.incident import IncidentIntelligence
        from intelligence.lifecycle import LifecycleIntelligence
        from intelligence.patch import PatchIntelligence
        from intelligence.predictive import PredictiveIntelligence
        from intelligence.predictive.predictive_context_builder import (
            PredictiveContextBuilder,
        )
        from intelligence.remediation import RemediationPlanner

        semantic = self.semantic_engine()
        if self._operations is not None and self._operations_semantic is semantic:
            return self._operations
        patch_intelligence = None
        if (
            hasattr(self.service, "patch_intelligence_snapshot")
            and self.config is not None
            and self.config.patch_intelligence.enabled
        ):
            patch_config = self.config.patch_intelligence
            # The governed patch snapshot also carries KB-level `findings`
            # (silver.patch_findings), which are consumed by the vulnerability
            # provider rather than PatchIntelligence. Only forward the keys the
            # factory actually declares so snapshot growth cannot break startup.
            patch_snapshot = _select_factory_kwargs(
                PatchIntelligence.from_semantic_engine,
                self.service.patch_intelligence_snapshot(),
            )
            patch_intelligence = PatchIntelligence.from_semantic_engine(
                semantic,
                **patch_snapshot,
                max_resources=patch_config.max_resources,
                max_evidence_rows=patch_config.max_evidence_rows,
                max_output_items=patch_config.max_output_items,
                max_serialized_bytes=patch_config.max_serialized_bytes,
            )
        lifecycle_intelligence = None
        if (
            self.config is not None
            and self.config.lifecycle.enabled
            and hasattr(self.service, "lifecycle_intelligence_snapshot")
        ):
            lifecycle_intelligence = LifecycleIntelligence.from_semantic_engine(
                semantic,
                patch_posture=(
                    patch_intelligence.internal_resource_posture()
                    if patch_intelligence is not None
                    else {}
                ),
                approaching_months=self.config.lifecycle.approaching_months,
                near_months=self.config.lifecycle.near_months,
                critical_months=self.config.lifecycle.critical_months,
                max_output_items=self.config.lifecycle.max_output_items,
                max_serialized_bytes=self.config.lifecycle.max_serialized_bytes,
                **_select_factory_kwargs(
                    LifecycleIntelligence.from_semantic_engine,
                    self.service.lifecycle_intelligence_snapshot(),
                ),
            )
        incident_intelligence = None
        if (
            self.config is not None
            and self.config.incident_causality.enabled
            and hasattr(self.service, "incident_intelligence_snapshot")
        ):
            snapshot = self.service.incident_intelligence_snapshot()
            patch_findings = []
            if patch_intelligence is not None:
                patch_findings = [
                    {
                        "finding_id": f"patch-posture-{index}",
                        "status": str(posture.get("status") or "Unknown"),
                        "severity": "Critical"
                        if int(posture.get("risk_score") or 0) >= 75
                        else "High",
                        "observed_at": str(posture.get("observed_at") or ""),
                        "resource_key": resource_key,
                        "summary": "Patch Intelligence reports failed or elevated patch posture.",
                    }
                    for index, (resource_key, posture) in enumerate(
                        sorted(patch_intelligence.internal_resource_posture().items())
                    )
                    if str(posture.get("status") or "").casefold()
                    in {"failed", "failure", "noncompliant", "error"}
                    and posture.get("observed_at")
                ]
            lifecycle_findings = []
            if lifecycle_intelligence is not None:
                lifecycle_findings = [
                    {
                        "finding_id": f"lifecycle-posture-{index}",
                        "status": str(posture.get("status") or "Unknown"),
                        "risk_score": int(posture.get("risk_score") or 0),
                        "severity": "Critical"
                        if int(posture.get("risk_score") or 0) >= 75
                        else "High",
                        "observed_at": str(posture.get("observed_at") or semantic.freshness),
                        "resource_key": resource_key,
                        "summary": "Lifecycle Intelligence reports elevated lifecycle posture.",
                    }
                    for index, (resource_key, posture) in enumerate(
                        sorted(lifecycle_intelligence.internal_resource_posture().items())
                    )
                    if str(posture.get("status") or "").casefold()
                    not in {"supported"}
                ]
            incident_intelligence = IncidentIntelligence.from_semantic_engine(
                semantic,
                patch_findings=patch_findings,
                lifecycle_findings=lifecycle_findings,
                correlation_lookback_hours=self.config.incident_causality.lookback_hours,
                max_incidents=self.config.incident_causality.max_incidents,
                max_evidence_rows=self.config.incident_causality.max_evidence_rows,
                **_select_factory_kwargs(
                    IncidentIntelligence.from_semantic_engine, snapshot
                ),
            )
        change_intelligence = None
        if (
            self.config is not None
            and self.config.change_intelligence.enabled
            and hasattr(self.service, "change_intelligence_snapshot")
        ):
            change_intelligence = ChangeIntelligence.from_semantic_engine(
                semantic,
                max_changes=self.config.change_intelligence.max_changes,
                max_output_items=self.config.change_intelligence.max_output_items,
                **_select_factory_kwargs(
                    ChangeIntelligence.from_semantic_engine,
                    self.service.change_intelligence_snapshot(),
                ),
            )
        predictive_intelligence = None
        if (
            self.config is not None
            and self.config.predictive.enabled
            and hasattr(self.service, "predictive_intelligence_snapshot")
        ):
            snapshot = self.service.predictive_intelligence_snapshot()
            signals = {
                PredictiveContextBuilder.canonical_key(row.get("resource_id")): {}
                for row in snapshot["inventory"]
                if row.get("resource_id")
            }
            if patch_intelligence is not None:
                for key, posture in patch_intelligence.internal_resource_posture().items():
                    key = PredictiveContextBuilder.canonical_key(key)
                    signals.setdefault(key, {}).update(
                        patch_risk_score=int(posture.get("risk_score") or 0),
                        patch_debt=int(posture.get("patch_debt") or 0),
                    )
            if lifecycle_intelligence is not None:
                for key, posture in lifecycle_intelligence.internal_resource_posture().items():
                    key = PredictiveContextBuilder.canonical_key(key)
                    signals.setdefault(key, {})["lifecycle_risk_score"] = int(
                        posture.get("risk_score") or 0
                    )
            if incident_intelligence is not None:
                for key, posture in incident_intelligence.internal_resource_posture().items():
                    key = PredictiveContextBuilder.canonical_key(key)
                    signals.setdefault(key, {}).update(posture)
            if change_intelligence is not None:
                for key, posture in change_intelligence.internal_resource_posture().items():
                    key = PredictiveContextBuilder.canonical_key(key)
                    signals.setdefault(key, {}).update(posture)
            predictive_intelligence = PredictiveIntelligence.from_semantic_engine(
                semantic,
                inventory=snapshot["inventory"],
                resource_signals=signals,
                history=snapshot["history"],
                max_history_rows=self.config.predictive.max_history_rows,
                max_output_items=self.config.predictive.max_output_items,
            )
        remediation_planner = None
        if (
            self.config is not None
            and self.config.remediation.enabled
            and hasattr(self.service, "remediation_planning_snapshot")
        ):
            snapshot = self.service.remediation_planning_snapshot()
            signals = {
                PredictiveContextBuilder.canonical_key(row.get("resource_id")): {}
                for row in snapshot["inventory"]
                if row.get("resource_id")
            }

            def merge_posture(posture, mapping):
                for raw_key, row in posture.items():
                    key = PredictiveContextBuilder.canonical_key(raw_key)
                    target = signals.setdefault(key, {})
                    for target_name, source_name in mapping.items():
                        if source_name in row:
                            target[target_name] = row[source_name]

            if patch_intelligence is not None:
                merge_posture(
                    patch_intelligence.internal_resource_posture(),
                    {
                        "patch_risk_score": "risk_score",
                        "patch_debt": "patch_debt",
                        "failed_update": "failed_update",
                    },
                )
            if lifecycle_intelligence is not None:
                merge_posture(
                    lifecycle_intelligence.internal_resource_posture(),
                    {
                        "lifecycle_risk_score": "risk_score",
                        "eol": "eol",
                        "modernization_candidate": "modernization_candidate",
                    },
                )
            if incident_intelligence is not None:
                merge_posture(
                    incident_intelligence.internal_resource_posture(),
                    {"incident_count_90d": "incident_count_90d"},
                )
            if change_intelligence is not None:
                merge_posture(
                    change_intelligence.internal_resource_posture(),
                    {
                        "configuration_drift_count": "configuration_drift_count",
                        "change_risk_score": "change_risk_score",
                    },
                )
            if predictive_intelligence is not None:
                merge_posture(
                    predictive_intelligence.internal_planning_posture(),
                    {
                        "predictive_risk_score": "predictive_risk_score",
                        "operational_debt_score": "operational_debt_score",
                    },
                )
            remediation_planner = RemediationPlanner.from_semantic_engine(
                semantic,
                inventory=snapshot["inventory"],
                resource_signals=signals,
                action_catalog=snapshot["action_catalog"],
                approval_policies=snapshot["approval_policies"],
                max_resources=self.config.remediation.max_resources,
                max_plans=self.config.remediation.max_plans,
                max_output_items=self.config.remediation.max_output_items,
                max_dependencies=self.config.remediation.max_dependencies,
            )
        operations_config = self.config.operations_agent if self.config is not None else None
        agent = OperationsAgent(
            semantic,
            patch_intelligence=patch_intelligence,
            lifecycle_intelligence=lifecycle_intelligence,
            incident_intelligence=incident_intelligence,
            change_intelligence=change_intelligence,
            predictive_intelligence=predictive_intelligence,
            remediation_planner=remediation_planner,
            max_output_items=(operations_config.max_output_items if operations_config else 100),
            max_serialized_bytes=(
                operations_config.max_serialized_bytes if operations_config else 1_000_000
            ),
        )
        object.__setattr__(self, "_operations", agent)
        object.__setattr__(self, "_operations_semantic", semantic)
        return agent


def build_runtime(config: FabricRuntimeConfig) -> FabricRuntime:
    lifecycle_catalog = _lifecycle_catalog(config)
    if config.local_onelake_root is not None:
        workspace = {
            "id": config.workspace_id or config.workspace_name,
            "displayName": config.workspace_name or config.workspace_id,
        }
        lakehouse = {
            "id": config.lakehouse_id or config.lakehouse_name,
            "displayName": config.lakehouse_name or config.lakehouse_id,
        }
        onelake = OneLakeWriter(
            str(workspace["id"]),
            str(lakehouse["id"]),
            table_schema=config.table_schema,
            local_root=config.local_onelake_root,
        )
        service = FabricSyncService(
            source_root=config.source_data_root,
            onelake=onelake,
            delta_writer=DeltaWriter(),
            validator=DataQualityValidator(),
            ontology_id=config.ontology.ontology_id,
            ontology_name=config.ontology.ontology_name,
            patch_policies=config.patch_policies,
            lifecycle_catalog=lifecycle_catalog,
        )
        return FabricRuntime(config, workspace, lakehouse, service)

    credential = build_credential(config.auth)
    client = FabricClient(credential)
    workspace = WorkspaceManager(client).resolve(
        workspace_id=config.workspace_id,
        workspace_name=config.workspace_name,
    )
    manager = LakehouseManager(client, str(workspace["id"]))
    lakehouse = manager.resolve(
        lakehouse_id=config.lakehouse_id,
        lakehouse_name=config.lakehouse_name,
        create_if_missing=config.create_lakehouse_if_missing,
        enable_schemas=bool(config.table_schema),
    )
    storage_options = build_delta_storage_options(credential)
    onelake = OneLakeWriter(
        str(workspace["id"]),
        str(lakehouse["id"]),
        workspace_name=str(workspace.get("displayName") or ""),
        lakehouse_name=str(lakehouse.get("displayName") or ""),
        table_schema=config.table_schema,
        credential=credential,
        storage_options=storage_options,
    )
    ontology_publisher = None
    if config.ontology.enabled:
        ontology_publisher = OntologyPublisher(
            OntologyManager(client, str(workspace["id"])),
            workspace_id=str(workspace["id"]),
            lakehouse_id=str(lakehouse["id"]),
            source_schema=config.table_schema,
        )
    service = FabricSyncService(
        source_root=config.source_data_root,
        onelake=onelake,
        delta_writer=DeltaWriter(
            storage_options=storage_options,
            storage_options_provider=lambda: build_delta_storage_options(credential),
        ),
        validator=DataQualityValidator(),
        lakehouse_manager=manager,
        lakehouse_id=str(lakehouse["id"]),
        shortcuts=config.shortcuts,
        registration_attempts=config.registration_attempts,
        write_workers=config.write_workers,
        ontology_publisher=ontology_publisher,
        ontology_id=config.ontology.ontology_id,
        ontology_name=config.ontology.ontology_name,
        patch_policies=config.patch_policies,
        lifecycle_catalog=lifecycle_catalog,
    )
    return FabricRuntime(config, workspace, lakehouse, service)


def _lifecycle_catalog(config: FabricRuntimeConfig) -> tuple[dict[str, Any], ...]:
    if not config.lifecycle.enabled:
        return ()
    from intelligence.lifecycle import EOLCatalog

    kwargs = {
        "approaching_months": config.lifecycle.approaching_months,
        "near_months": config.lifecycle.near_months,
        "critical_months": config.lifecycle.critical_months,
    }
    catalog = (
        EOLCatalog.from_file(config.lifecycle.catalog_path, **kwargs)
        if config.lifecycle.catalog_path is not None
        else EOLCatalog.default(**kwargs)
    )
    return tuple(catalog.rows())
