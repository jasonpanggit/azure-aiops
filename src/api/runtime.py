"""Default runtime wiring for the Operations API.

Builds an :class:`ApiContext` from the environment so the app can be served
directly:

    uvicorn --factory api.app:create_app

Production deployments should construct :class:`ApiContext` explicitly and call
:func:`api.create_app` with it. This module exists so the documented one-liner
works, and so misconfiguration fails loudly at startup rather than as a 500 on
the first request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from api.exposure_refresh import ExposurePatchRefreshCoordinator
from fabric.auth import FabricAuthConfig, build_credential
from fabric.config import (
    ExposureRolloutRuntimeConfig,
    ExposureRolloutStage,
    FabricRuntimeConfig,
    OntologyRuntimeConfig,
)
from fabric.dataset_mapper import ExposureOntologyMapper, InventoryDatasetMapper
from fabric.gold_grounding_client import query_gold_grounding
from fabric.runtime import FabricRuntime, build_runtime
from fabric.sql_endpoint import require_exposure_ready
from fabric_pipelines.gold_grounding_contract import parse_gold_grounded_findings
from intelligence.governance import EnterpriseSettingsStore
from intelligence.health.service import ResourceHealthService
from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.incidents.incident_engine import IncidentEngine
from intelligence.vulnerability.connector import (
    EpssScoreConnector,
    KevCatalogConnector,
    MsrcKbLookupConnector,
    NvdCveEnrichmentConnector,
    canonical_enrichment_identifier,
)
from intelligence.vulnerability.enrichment_cache import (
    EXPOSURE_ENRICHMENT_DOCUMENT,
    EnrichmentCache,
)
from intelligence.vulnerability.enrichment_worker import (
    EnrichmentTarget,
    EnrichmentWorker,
)
from intelligence.vulnerability.exposure_contracts import EXPOSURE_METADATA_DATASET
from intelligence.vulnerability.models import CVE, RiskException
from intelligence.vulnerability.read_port import ExposureReadPort
from intelligence.vulnerability.service import (
    VulnerabilityIntelligenceService,
    _defender_payload,
)
from onboarding.config import ConnectorConfig
from onboarding.query_contract import QuerySpec

_LOGGER = logging.getLogger(__name__)

from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.approval_gate import policy_version_for
from intelligence.remediation.defender_correlation import DefenderRemediationCorrelator
from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
from intelligence.remediation.execution_service import (
    VERIFICATION_DEADLINE_SECONDS,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import (
    RemediationExecutionStore,
    execution_scope_attributes,
)
from intelligence.remediation.execution_verifier import (
    ExecutionVerificationUnavailable,
    ExecutionVerifier,
)
from intelligence.remediation.plan_repository import PlanRepository
from intelligence.remediation.verification_coordinator import (
    RemediationVerificationCoordinator,
)
from network.design import NetworkDesignPolicyStore
from network.flow import FlowQuery
from network.models import PRIVATE_LINK_RESOURCE_TYPES
from network.service import NetworkIntelligenceService
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.monitor_prometheus import (
    resource_scoped_endpoint,
    workspace_scoped_endpoint,
)
from onboarding.registry import ConnectionRegistry
from onboarding.runtime import (
    build_connection_arg_client,
    build_connection_credential,
    build_connection_logs_client,
    build_connection_monitor_metrics_client,
    build_connection_prometheus_client,
    build_onboarding_service,
    connection_cache_identity,
)
from onboarding.service import SubscriptionOnboardingService
from onboarding.sync import _slug
from ontology_discovery.evaluation_store import EvaluationSnapshotStore
from ontology_discovery.generation_resolver import (
    GenerationResolver,
    GenerationSelection,
)
from operations.autonomous_investigation import configure_ledger_store
from operations.copilot_canary_authorization import (
    canary_authorization_required,
    require_canary_authorization_if_requested,
)
from operations.defender_configuration import (
    AzureArmDefenderConfigurationAdapter,
    DefenderConfigurationUnavailable,
    UnconfiguredDefenderConfigurationAdapter,
)
from operations.foundry_agent import (
    SPECIALIST_IDS,
    FoundryPromptAgent,
    MicrosoftAgentFrameworkFoundryAgent,
    select_foundry_agent_class,
)
from operations.maf_orchestrator import (
    ENV_AGENT_ORCHESTRATION_MODE,
    MODE_CANONICAL,
    MODE_MAF,
    maf_mode_enabled,
)
from operations.patching import (
    InMemoryPatchRunStore,
    PatchExecutionUnavailable,
    PatchingService,
    UnconfiguredPatchExecutionAdapter,
)
from operations.tools import FabricIQToolAdapter
from semantic.hybrid_query import HybridQueryService
from semantic.live_operations import (
    LiveRemediationPlanner,
    collect_live_patch_snapshot,
    live_incident_engine,
    live_vulnerability_service,
)
from semantic.live_provider import ConnectionScopedLiveResourceProvider
from semantic.semantic_engine import SemanticEngine
from storage.fs import is_onelake_uri
from storage.onelake_documents import OneLakeDocumentStore

from .auth import (
    EntraJwtAuthenticator,
    GatewayOrDirectAuthenticator,
    HeaderPrincipalAuthenticator,
    StaticTokenAuthenticator,
)
from .dependencies import ApiContext
from .governance_snapshot import GovernanceSnapshot
from .providers import ProviderRuntime, ProviderSpec, ProviderValue
from .rbac import Authorizer, Grant, Principal
from .scope import Scope, subscription_ids_for_scope
from .telemetry import ApiTelemetry

ENV_HOME = "AIOPS_HOME"
ENV_AUTH_MODE = "AIOPS_API_AUTH"
ENV_TOKENS = "AIOPS_API_TOKENS"
ENV_GATEWAY_GRANTS = "AIOPS_API_GATEWAY_GRANTS"
ENV_ENTRA_TENANT_ID = "AIOPS_ENTRA_TENANT_ID"
ENV_ENTRA_AUDIENCE = "AIOPS_ENTRA_AUDIENCE"
# Optional path to the onboarding YAML config (see config.example.yaml)
# used only to source ingestion defaults (page size, timeouts, MCP command,
# ...). Per-connection subscription/tenant scoping always comes from the
# connection itself, so this file need not list any subscriptions.
ENV_ARG_CONFIG = "AIOPS_ARG_CONFIG"
ENV_CONNECTION_KEY_VAULT = "AIOPS_CONNECTION_KEY_VAULT"
ENV_FABRIC_CONFIG = "AIOPS_FABRIC_CONFIG"
ENV_RUNTIME_MODE = "AIOPS_RUNTIME_MODE"
ENV_PROVIDER_REFRESH_SECONDS = "AIOPS_PROVIDER_REFRESH_SECONDS"
ENV_PROVIDER_STALE_HOURS = "AIOPS_PROVIDER_STALE_HOURS"
ENV_FOUNDRY_PROJECT_ENDPOINT = "FOUNDRY_PROJECT_ENDPOINT"
ENV_APPROVED_SEARCH_API_ENDPOINT = "APPROVED_SEARCH_API_ENDPOINT"
ENV_APPROVED_SEARCH_API_KEY = "APPROVED_SEARCH_API_KEY"
# Opt-in switch for real Azure patch execution. Absent it, patch runs refuse.
ENV_PATCH_EXECUTION = "AIOPS_PATCH_EXECUTION"
ENV_SRE_AGENT_ENDPOINT = "AIOPS_SRE_AGENT_ENDPOINT"
ENV_SRE_AGENT_TRIGGER_URL = "AIOPS_SRE_AGENT_TRIGGER_URL"
ENV_SRE_AGENT_TRIGGER_ID = "AIOPS_SRE_AGENT_TRIGGER_ID"
ENV_SRE_AGENT_TRIGGER_ORIGIN = "AIOPS_SRE_AGENT_TRIGGER_ORIGIN"
ENV_SRE_AGENT_TRIGGER_SCOPE = "AIOPS_SRE_AGENT_TRIGGER_SCOPE"
ENV_SRE_AGENT_THREAD_SCOPE = "AIOPS_SRE_AGENT_THREAD_SCOPE"
ENV_SRE_AGENT_SUBSCRIPTION_ID = "AIOPS_SRE_AGENT_SUBSCRIPTION_ID"
ENV_SRE_AGENT_TARGET_PREFIX = "AIOPS_SRE_AGENT_TARGET_PREFIX"
ENV_DEFENDER_CONFIGURATION_EXECUTION = "AIOPS_DEFENDER_CONFIGURATION_EXECUTION"
ENV_GATEWAY_ASSERTION = "AIOPS_GATEWAY_ASSERTION"
# Override for how long a submitted remediation execution may stay
# unverified before the autonomous coordinator (Phase 03.4) reports it
# terminal-unknown. Absent, RemediationExecutionService's own default
# (VERIFICATION_DEADLINE_SECONDS, PT2H + 15 minutes) applies.
ENV_REMEDIATION_VERIFICATION_DEADLINE_SECONDS = (
    "AIOPS_REMEDIATION_VERIFICATION_DEADLINE_SECONDS"
)
ENV_CONNECTION_HOME = "AIOPS_CONNECTION_HOME"
ENV_ONTOLOGY_STATE_HOME = "AIOPS_ONTOLOGY_STATE_HOME"
ENV_ONTOLOGY_PUBLICATION_HOME = "AIOPS_ONTOLOGY_PUBLICATION_HOME"
ENV_ONTOLOGY_COMMAND_HOME = "AIOPS_ONTOLOGY_COMMAND_HOME"
ENV_EXPOSURE_ROLLOUT_AUTHORIZED = "AIOPS_EXPOSURE_ROLLOUT_AUTHORIZED"
ENV_EXPOSURE_WRITE_STAGE = "AIOPS_EXPOSURE_WRITE_STAGE"
ENV_EXPOSURE_READ_STAGE = "AIOPS_EXPOSURE_READ_STAGE"
ENV_EXPOSURE_WEB_STAGE = "AIOPS_EXPOSURE_WEB_STAGE"
ENV_EXPOSURE_HANDOFF_STAGE = "AIOPS_EXPOSURE_HANDOFF_STAGE"
ENV_EXPOSURE_WRITE_GENERATION_ID = "AIOPS_EXPOSURE_WRITE_GENERATION_ID"
ENV_EXPOSURE_READ_GENERATION_ID = "AIOPS_EXPOSURE_READ_GENERATION_ID"
ENV_EXPOSURE_ROLLBACK_GENERATION_ID = "AIOPS_EXPOSURE_ROLLBACK_GENERATION_ID"

_GOVERNANCE_ENTITY_DATASETS = (
    "AdvisorRecommendation",
    "CostActual",
    "Resource",
    "VirtualMachine",
    "ArcServer",
    "RoleAssignment",
    "RoleDefinition",
    "ManagedIdentity",
)
_MAX_GOVERNANCE_ROWS = 100_000
_MAX_GOVERNANCE_BYTES = 128 * 1024 * 1024
_MAX_GOVERNANCE_ROW_BYTES = 2 * 1024 * 1024
_MAX_GOVERNANCE_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_GOVERNANCE_POINTER_BYTES = 64 * 1024
_GOVERNANCE_SOURCE_STATUS_DATASET = "situations/source_status"


def _governance_dataset_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    declared = manifest.get("datasets")
    if not isinstance(declared, Mapping):
        raise TypeError("Governance generation manifest has no dataset declarations")
    counts: dict[str, int] = {}
    for entity_type in _GOVERNANCE_ENTITY_DATASETS:
        name = f"entities/{entity_type}"
        details = declared.get(name)
        if details is None:
            raise TypeError(f"Governance dataset declaration is missing: {name}")
        if not isinstance(details, Mapping):
            raise TypeError(f"Governance dataset declaration is invalid: {name}")
        count = details.get("rowCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise TypeError(f"Governance dataset row count is invalid: {name}")
        counts[name] = count
    return counts


def _read_governance_dataset(
    store: Any,
    generation: str,
    name: str,
    *,
    expected_rows: int,
    expected_integrity_hash: str = "",
    max_bytes: int = _MAX_GOVERNANCE_BYTES,
) -> tuple[list[dict[str, Any]], int]:
    if store.is_remote:
        path = f"{generation}/{name}.jsonl"
        if not store.fs.exists(path):
            raise FileNotFoundError(path)
        handle = store.fs.open(path, "rb")
    else:
        path = (Path(generation) / name).with_suffix(".jsonl")
        if not path.is_file():
            raise FileNotFoundError(path)
        handle = path.open("rb")
    rows = []
    bytes_read = 0
    with handle:
        while True:
            raw_line = handle.readline(_MAX_GOVERNANCE_ROW_BYTES + 1)
            if not raw_line:
                break
            if isinstance(raw_line, str):
                raw_line = raw_line.encode("utf-8")
            if len(raw_line) > _MAX_GOVERNANCE_ROW_BYTES:
                raise ValueError(f"Governance dataset row exceeds its byte limit: {name}")
            bytes_read += len(raw_line)
            if bytes_read > max_bytes:
                raise ValueError(f"Governance snapshot exceeds its byte limit: {name}")
            if not raw_line.strip():
                continue
            if len(rows) >= expected_rows:
                raise ValueError(f"Governance dataset exceeds its declared row count: {name}")
            row = json.loads(raw_line.decode("utf-8"))
            if not isinstance(row, dict):
                raise TypeError(f"Governance dataset contains a non-object row: {name}")
            rows.append(row)
    if len(rows) != expected_rows:
        raise ValueError(f"Governance dataset row count does not match its manifest: {name}")
    if (
        expected_integrity_hash
        and _governance_integrity_hash(rows) != expected_integrity_hash
    ):
        raise ValueError(
            f"Governance dataset integrity does not match its manifest: {name}"
        )
    return rows, bytes_read


def _read_governance_manifest(store: Any, generation: str) -> dict[str, Any]:
    if store.is_remote:
        path = f"{generation}/manifest.json"
        if not store.fs.exists(path):
            raise FileNotFoundError(path)
        handle = store.fs.open(path, "rb")
    else:
        path = Path(generation) / "manifest.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        handle = path.open("rb")
    with handle:
        raw = handle.read(_MAX_GOVERNANCE_MANIFEST_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > _MAX_GOVERNANCE_MANIFEST_BYTES:
        raise ValueError("Governance generation manifest exceeds its byte limit")
    manifest = json.loads(raw.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Governance generation manifest must be an object")
    from storage.datasets import _manifest_integrity_hash

    expected = str(manifest.get("integrityHash") or "")
    if len(expected) != 64 or _manifest_integrity_hash(manifest) != expected:
        raise ValueError("Governance generation manifest integrity mismatch")
    return manifest


def _governance_active_generation(store: Any) -> str:
    if store.is_remote:
        path = str(store.pointer_path)
        if not store.fs.exists(path):
            raise LookupError("Governance generation pointer is missing")
        handle = store.fs.open(path, "rb")
    else:
        pointer = Path(store.pointer_path)
        if not pointer.exists():
            current = Path(store.current)
            if not current.exists():
                raise LookupError("Governance generation pointer is missing")
            return str(current.resolve())
        handle = pointer.open("rb")
    with handle:
        raw = handle.read(_MAX_GOVERNANCE_POINTER_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > _MAX_GOVERNANCE_POINTER_BYTES:
        raise ValueError("Governance generation pointer exceeds its byte limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("Governance generation pointer must be an object")
    name = str(
        payload.get("active_generation")
        or payload.get("generation")
        or ""
    ).strip()
    if not name:
        raise LookupError("Governance generation pointer has no active generation")
    generation = store.generation_path(name)
    if generation is None:
        raise LookupError("Governance active generation is missing")
    return str(generation)


def _governance_integrity_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    for chunk in encoder.iterencode(rows):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def _governance_connection_scope(connection: Mapping[str, Any]) -> dict[str, str]:
    metadata = connection.get("metadata")
    business = metadata.get("business") if isinstance(metadata, Mapping) else None
    business = business if isinstance(business, Mapping) else {}
    environment_mappings = connection.get("environment_mappings")
    environment = (
        environment_mappings[0]
        if isinstance(environment_mappings, list)
        and environment_mappings
        and isinstance(environment_mappings[0], Mapping)
        else {}
    )
    linkages = connection.get("business_service_linkages")
    linkage = (
        linkages[0]
        if isinstance(linkages, list)
        and linkages
        and isinstance(linkages[0], Mapping)
        else {}
    )
    application_ids = linkage.get("application_ids")
    application = (
        str(application_ids[0])
        if isinstance(application_ids, list) and application_ids
        else ""
    )
    subscription_id = str(connection.get("subscription_id") or "")
    connection_id = str(connection.get("connection_id") or "")
    return {
        "subscription": subscription_id,
        "subscription_id": subscription_id,
        "subscription_connection": connection_id,
        "connection_id": connection_id,
        "business_service": str(
            business.get("business_service")
            or linkage.get("business_service_id")
            or ""
        ),
        "application": str(business.get("application") or application),
        "environment": str(
            business.get("environment")
            or environment.get("environment_name")
            or linkage.get("environment_name")
            or ""
        ),
        "owner": str(business.get("project_owner") or business.get("owner") or ""),
        "support_team": str(business.get("support_team") or ""),
        "criticality": str(business.get("criticality") or ""),
        "region": str(business.get("region") or ""),
    }


def _governance_entity(
    entity_type: str,
    row: Mapping[str, Any],
    *,
    connection_scope: Mapping[str, str],
) -> dict[str, Any]:
    payload = dict(row)
    trusted_subscription = connection_scope.get("subscription_id", "")
    trusted_connection = connection_scope.get("connection_id", "")
    for alias in ("subscription", "subscription_id", "subscriptionId"):
        value = str(payload.get(alias) or "")
        if value and trusted_subscription and value.casefold() != trusted_subscription.casefold():
            raise PermissionError("Governance row subscription conflicts with its connection")
        if trusted_subscription:
            payload[alias] = trusted_subscription
    for alias in ("subscription_connection", "connection_id", "connectionId"):
        value = str(payload.get(alias) or "")
        if value and trusted_connection and value.casefold() != trusted_connection.casefold():
            raise PermissionError("Governance row connection conflicts with its source")
        if trusted_connection:
            payload[alias] = trusted_connection
    for field in ("id", "resource_id", "targetResourceId", "assignmentScope", "scope"):
        value = str(payload.get(field) or "")
        match = re.search(r"/subscriptions/([^/]+)", value, flags=re.IGNORECASE)
        if match and trusted_subscription and match.group(1).casefold() != trusted_subscription.casefold():
            raise PermissionError("Governance row ARM scope conflicts with its connection")
    for key, value in connection_scope.items():
        if value:
            payload[key] = value
    return {
        "resource_id": str(row.get("id") or row.get("resource_id") or ""),
        "entity_type": entity_type,
        "subscription_id": str(
            row.get("subscriptionId")
            or row.get("subscription_id")
            or connection_scope.get("subscription_id")
        ),
        **{key: value for key, value in connection_scope.items() if value},
        "payload_json": payload,
    }


def _governance_source_degradation(row: Mapping[str, Any]) -> str:
    degraded = {"degraded", "failed", "partial", "stale", "unavailable", "unknown"}
    for field in ("completeness", "freshness", "status", "availability"):
        value = str(row.get(field) or "").strip().casefold()
        if value in degraded:
            return value
    return ""


def _governance_connection_home() -> str:
    """Use the durable connection boundary, retaining the local validation root."""
    return os.environ.get(ENV_CONNECTION_HOME, "").strip() or str(aiops_home())


def _load_governance_generation_snapshot(
    scope: Scope,
) -> GovernanceSnapshot | None:
    """Reuse one aggregate generation snapshot for concurrent unrestricted reads."""

    if not scope.is_unrestricted():
        return _build_governance_generation_snapshot(scope)

    connection_signature = tuple(
        sorted(
            "|".join(
                (
                    str(row.get("connection_id") or ""),
                    str(row.get("subscription_id") or ""),
                    str(row.get("is_active") is not False),
                    str(row.get("last_sync") or row.get("last_sync_at") or ""),
                )
            )
            for row in _governance_connections()
        )
    )
    cache_key = (
        _governance_connection_home(),
        ("generation", *connection_signature),
    )
    return _ttl_cached_value(
        _governance_snapshot_cache,
        cache_key,
        ttl_seconds=_SNAPSHOT_TABLES_CACHE_TTL_SECONDS,
        now=time.time(),
        build=lambda: _build_governance_generation_snapshot(scope),
        completion_clock=time.time,
    )


def _build_governance_generation_snapshot(
    scope: Scope,
) -> GovernanceSnapshot | None:
    """Read bounded governance families from authorized active generations."""

    scoped_connections = [
        row
        for row in _governance_connections()
        if scope.matches(
            _governance_connection_scope(row)
        )
    ]
    connections = [
        row for row in scoped_connections if row.get("is_active") is not False
    ]
    inactive_connections = [
        {
            **row,
            **_governance_connection_scope(row),
        }
        for row in scoped_connections
        if row.get("is_active") is False
    ]
    registry_connections = [
        {
            **row,
            **_governance_connection_scope(row),
        }
        for row in scoped_connections
    ]
    if not connections:
        if not inactive_connections:
            return None
        return GovernanceSnapshot(
            [],
            connections=inactive_connections,
            warnings=["No active governance generation is available"],
            generation_available=False,
        )
    from storage.datasets import DatasetStore

    entities: list[dict[str, Any]] = []
    observed_times: list[str] = []
    loaded_connections: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_rows = 0
    total_bytes = 0
    for connection in connections:
        store = DatasetStore(
            _connection_dataset_dir(
                _governance_connection_home(),
                str(connection.get("connection_id") or ""),
            )
        )
        try:
            active_generation = _governance_active_generation(store)
            manifest = _read_governance_manifest(
                store,
                active_generation,
            )
            counts = _governance_dataset_counts(manifest)
            source_details = manifest["datasets"].get(
                _GOVERNANCE_SOURCE_STATUS_DATASET
            )
            source_row_count = 0
            source_hash = ""
            if isinstance(source_details, Mapping):
                source_rows = source_details.get("rowCount")
                source_hash = str(source_details.get("integrityHash") or "")
                if (
                    isinstance(source_rows, bool)
                    or not isinstance(source_rows, int)
                    or source_rows < 0
                    or len(source_hash) != 64
                ):
                    raise TypeError("Governance source status declaration is invalid")
                source_row_count = source_rows
            connection_rows = sum(counts.values()) + source_row_count
            if total_rows + connection_rows > _MAX_GOVERNANCE_ROWS:
                raise ValueError(
                    f"Governance snapshot exceeds the {_MAX_GOVERNANCE_ROWS}-row limit"
                )
            connection_scope = _governance_connection_scope(connection)
            connection_entities: list[dict[str, Any]] = []
            connection_bytes = 0
            for name, expected_rows in counts.items():
                entity_type = name.rsplit("/", 1)[-1]
                details = manifest["datasets"][name]
                integrity_hash = str(details.get("integrityHash") or "")
                if len(integrity_hash) != 64:
                    raise TypeError(
                        f"Governance dataset integrity hash is invalid: {name}"
                    )
                rows, bytes_read = _read_governance_dataset(
                    store,
                    active_generation,
                    name,
                    expected_rows=expected_rows,
                    expected_integrity_hash=integrity_hash,
                    max_bytes=(
                        _MAX_GOVERNANCE_BYTES - total_bytes - connection_bytes
                    ),
                )
                connection_bytes += bytes_read
                connection_entities.extend(
                    _governance_entity(
                        entity_type,
                        row,
                        connection_scope=connection_scope,
                    )
                    for row in rows
                )
            source_statuses: list[dict[str, Any]] = []
            if source_row_count or isinstance(source_details, Mapping):
                source_statuses, bytes_read = _read_governance_dataset(
                    store,
                    active_generation,
                    _GOVERNANCE_SOURCE_STATUS_DATASET,
                    expected_rows=source_row_count,
                    expected_integrity_hash=source_hash,
                    max_bytes=(
                        _MAX_GOVERNANCE_BYTES - total_bytes - connection_bytes
                    ),
                )
                connection_bytes += bytes_read
            else:
                warnings.append(
                    "Governance source status is unavailable for connection "
                    f"{connection.get('connection_id') or 'unknown'}; empty "
                    "results are not proven clean"
                )
        except (LookupError, OSError, TypeError, ValueError, json.JSONDecodeError):
            _LOGGER.warning(
                "governance_generation_load_failed connection_id=%s",
                connection.get("connection_id") or "",
                exc_info=True,
            )
            warnings.append(
                "Governance data is unavailable for connection "
                f"{connection.get('connection_id') or 'unknown'}"
            )
            continue
        entities.extend(connection_entities)
        total_rows += connection_rows
        total_bytes += connection_bytes
        loaded_connections.append({
            **connection,
            **connection_scope,
        })
        manifest_time = str(
            manifest.get("startedAt")
            or manifest.get("observed_at")
            or manifest.get("created_at")
            or ""
        )
        degraded_statuses = [
            (row, _governance_source_degradation(row))
            for row in source_statuses
            if _governance_source_degradation(row)
        ]
        stale_times = [
            str(row.get("last_success_at") or "")
            for row, _status in degraded_statuses
        ]
        observed_times.append(
            ""
            if any(not value for value in stale_times)
            else min(stale_times)
            if degraded_statuses
            else ""
            if not manifest_time
            else manifest_time
        )
        warnings.extend(
            "Governance source "
            f"{row.get('source_family') or 'unknown'} is "
            f"{status} for connection "
            f"{connection.get('connection_id') or 'unknown'}"
            for row, status in degraded_statuses
        )
    if not loaded_connections:
        if not registry_connections:
            return None
        return GovernanceSnapshot(
            [],
            connections=registry_connections,
            warnings=[*warnings, "No active governance generation is available"],
            generation_available=False,
        )
    return GovernanceSnapshot(
        entities,
        observed_at=(
            ""
            if any(not value for value in observed_times)
            else min(observed_times, default="")
        ),
        connections=registry_connections,
        warnings=warnings,
    )


def _load_ontology_discovery_api(
    onboarding: SubscriptionOnboardingService,
    roots: Mapping[str, str],
) -> Any:
    """Build a restart-safe API facade with no publisher credential."""

    from api.routers.ontology_discovery import OntologyDiscoveryApi
    from ontology_discovery.command_intake import CommandIntakeService
    from ontology_discovery.store import OntologyRunStore
    from storage.datasets import DatasetStore

    def generation_resolver(connection_id: str) -> GenerationResolver:
        del connection_id
        return GenerationResolver(DatasetStore(roots["publication"]))

    return OntologyDiscoveryApi(
        onboarding=onboarding,
        run_store=OntologyRunStore(
            Path("."),
            document_store=OneLakeDocumentStore(roots["state"]),
        ),
        evaluation_store=EvaluationSnapshotStore(
            document_store=OneLakeDocumentStore(roots["state"])
        ),
        generation_resolver_factory=generation_resolver,
        command_intake=CommandIntakeService(roots["command"]),
        connection_reader=ConnectionRegistry(roots["connection"]).get,
        rollback_action=None,
    )


def _ontology_api_roots(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve the API's exact read/read/read/create capability roots."""

    from storage.fs import join_root

    values = dict(os.environ if environ is None else environ)
    mode = str(values.get(ENV_RUNTIME_MODE) or "validation").strip().casefold()
    base = str(values.get(ENV_HOME) or str(Path.home() / ".aiops")).strip()
    env_names = {
        "connection": ENV_CONNECTION_HOME,
        "state": ENV_ONTOLOGY_STATE_HOME,
        "publication": ENV_ONTOLOGY_PUBLICATION_HOME,
        "command": ENV_ONTOLOGY_COMMAND_HOME,
    }
    if mode == "production":
        roots = {
            name: str(values.get(env_name) or "").strip()
            for name, env_name in env_names.items()
        }
        for name, value in roots.items():
            if not value:
                raise ValueError(f"{env_names[name]} must not be empty")
            if not is_onelake_uri(value):
                raise ValueError(
                    f"{env_names[name]} must be an explicit OneLake URI"
                )
    else:
        roots = {
            "connection": str(
                values.get(ENV_CONNECTION_HOME) or base
            ).strip(),
            "state": str(
                values.get(ENV_ONTOLOGY_STATE_HOME)
                or join_root(base, "ontology-api-state")
            ).strip(),
            "publication": str(
                values.get(ENV_ONTOLOGY_PUBLICATION_HOME)
                or join_root(base, "ontology-publication")
            ).strip(),
            "command": str(
                values.get(ENV_ONTOLOGY_COMMAND_HOME)
                or join_root(base, "ontology-command-intake")
            ).strip(),
        }
    normalized = {value.rstrip("/").casefold() for value in roots.values()}
    if len(normalized) != len(roots):
        raise ValueError("Ontology API capability roots must be pairwise distinct")
    return roots

AUTH_GATEWAY = "gateway"
AUTH_ENTRA = "entra"
AUTH_TOKEN = "token"


@dataclass(frozen=True, slots=True)
class ExposurePromotionEvidence:
    """Redacted prerequisite outcomes consumed by the rollout decision."""

    adapter_ready: bool
    cursor_keys_ready: bool
    source_coverage_ready: bool
    reconciliation_passed: bool
    telemetry_ready: bool
    alerts_ready: bool
    slo_passed: bool
    ui_api_contract_passed: bool
    live_validation_passed: bool
    ingestion_healthy: bool
    read_path_healthy: bool
    key_rotation_healthy: bool


@dataclass(frozen=True, slots=True)
class ExposurePromotionDecision:
    """Fail-closed effective pointers for one evaluated rollout."""

    allowed: bool
    blocked_reasons: tuple[str, ...]
    active_writer_generation_id: str
    active_reader_generation_id: str
    candidate_generation_id: str
    rollback_required: bool
    preserve_evidence: bool = True
    destructive_actions: tuple[str, ...] = ()


# Sentinel distinguishing "not yet resolved" from a resolved-but-absent agent,
# so an unconfigured deployment is probed once rather than on every request.
_UNSET: Any = object()
_foundry_agent: Any = _UNSET
_foundry_specialist_agents: dict[str, Any] = {}


def aiops_home() -> Path | str:
    """Root for all persisted state: connection dataset snapshots.

    Plain paths use the local disk (the default for development). Set to a
    ``abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>/Files/<path>``
    URI to persist synced dataset snapshots in OneLake instead -- the same
    `DatasetStore`/`InventoryDatasetMapper` code path handles both
    transparently through the storage filesystem adapters.
    """
    from storage.fs import resolve_root

    return resolve_root(os.environ.get(ENV_HOME) or str(Path.home() / ".aiops"))


def _token_principals() -> dict[str, Principal]:
    """Parse ``AIOPS_API_TOKENS`` as JSON: ``{token: {subject, grants: [...]}}``."""
    raw = os.environ.get(ENV_TOKENS, "").strip()
    if not raw:
        raise RuntimeError(
            f"{ENV_AUTH_MODE}={AUTH_TOKEN} requires {ENV_TOKENS} to be set. "
            "Refusing to start an API with no way to authenticate callers."
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{ENV_TOKENS} is not valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"{ENV_TOKENS} must be a non-empty JSON object")
    return {
        str(token): Principal.from_mapping(spec) for token, spec in payload.items()
    }


def _gateway_grants():
    """Build an explicit subject-to-grant resolver for gateway deployments."""
    raw = os.environ.get(ENV_GATEWAY_GRANTS, "").strip()
    if not raw:
        raise RuntimeError(
            f"{ENV_AUTH_MODE}={AUTH_GATEWAY} requires {ENV_GATEWAY_GRANTS}. "
            "Gateway headers establish identity, not authorization."
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{ENV_GATEWAY_GRANTS} is not valid JSON") from exc
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError(f"{ENV_GATEWAY_GRANTS} must be a non-empty JSON object")
    principals = {
        str(subject).casefold(): Principal.from_mapping(
            {"subject": subject, "grants": grants}
        )
        for subject, grants in payload.items()
    }

    def resolve(subject: str, roles: list[str]) -> tuple[Grant, ...]:
        principal = principals.get(subject.casefold())
        if principal is None:
            return ()
        # APIM validates the token and forwards only its trusted subject. The
        # subject-to-grant map is the authorization source; no client header is
        # allowed to manufacture roles. Direct gateway deployments may still
        # provide explicit roles as an additional configured constraint.
        if not roles:
            return principal.grants
        asserted = set(roles)
        return tuple(grant for grant in principal.grants if grant.role in asserted)

    return resolve


def build_authenticator():
    mode = (os.environ.get(ENV_AUTH_MODE) or AUTH_TOKEN).strip().casefold()
    if mode == AUTH_GATEWAY:
        resolver = _gateway_grants()
        gateway = HeaderPrincipalAuthenticator(
            grants_resolver=resolver,
            assertion_value=os.environ.get(ENV_GATEWAY_ASSERTION, ""),
        )
        # APIM fronts only the governed MCP route; the browser calls every
        # other route directly and can never produce a gateway assertion.
        # Pair the two so enabling APIM does not lock the web app out of the
        # entire API. Entra config is required for that direct path -- without
        # it, gateway mode would silently 401 all browser traffic.
        tenant_id = os.environ.get(ENV_ENTRA_TENANT_ID, "").strip()
        audience = os.environ.get(ENV_ENTRA_AUDIENCE, "").strip()
        if not tenant_id or not audience:
            raise RuntimeError(
                f"{ENV_AUTH_MODE}={AUTH_GATEWAY} requires {ENV_ENTRA_TENANT_ID} and "
                f"{ENV_ENTRA_AUDIENCE} so non-gateway callers can still authenticate."
            )
        return GatewayOrDirectAuthenticator(
            gateway=gateway,
            direct=EntraJwtAuthenticator(
                tenant_id=tenant_id,
                audience=audience,
                grants_resolver=resolver,
            ),
        )
    if mode == AUTH_ENTRA:
        return EntraJwtAuthenticator(
            tenant_id=os.environ.get(ENV_ENTRA_TENANT_ID, ""),
            audience=os.environ.get(ENV_ENTRA_AUDIENCE, ""),
            grants_resolver=_gateway_grants(),
        )
    if mode == AUTH_TOKEN:
        return StaticTokenAuthenticator(_token_principals())
    raise RuntimeError(
        f"Unknown {ENV_AUTH_MODE}={mode!r}; expected {AUTH_ENTRA!r}, "
        f"{AUTH_GATEWAY!r}, or {AUTH_TOKEN!r}"
    )


def _onboarding_service(
    output_dir: str | Path | None = None,
    command_home: str | None = None,
) -> SubscriptionOnboardingService:
    """Build the onboarding service with a real ingestion factory wired in.

    Without this, `SubscriptionOnboardingService` falls back to no
    `ingestion_factory`, and the connection-scoped `/sync` route fails with
    "No ingestion factory is configured" on every call. `build_onboarding_service`
    is the one place (also used by the CLI) that wires ingestion; per-connection
    subscription/tenant scoping comes from the connection itself at sync time,
    so an unconfigured AIOPS_ARG_CONFIG defaults safely to base ingestion
    settings.
    """
    config_path = os.environ.get(ENV_ARG_CONFIG, "").strip()
    config = (
        ConnectorConfig.load(config_path)
        if config_path
        else ConnectorConfig(output_dir=output_dir or aiops_home())
    )
    if output_dir is not None and str(config.output_dir) != str(output_dir):
        import dataclasses

        config = dataclasses.replace(config, output_dir=output_dir)
    vault = os.environ.get(ENV_CONNECTION_KEY_VAULT, "").strip()
    service = build_onboarding_service(
        config,
        secret_writer=KeyVaultSecretWriter(vault) if vault else None,
        config_path=config_path,
        fabric_config_path=os.environ.get(ENV_FABRIC_CONFIG, "").strip(),
    )
    if command_home is not None:
        from ontology_discovery.command_intake import CommandIntakeService

        service.ontology_command_intake = CommandIntakeService(command_home)
    return service


def _connection_dataset_dir(root: str, connection_id: str) -> str:
    """Mirror `ConnectionSyncCoordinator.connection_output_dir()` without
    constructing a full sync coordinator just to resolve a path."""
    from storage.fs import join_root

    return join_root(root, "connections", _slug(connection_id))


def _load_ontology_rows() -> tuple[list[dict], list[dict], str]:
    """Read every registered connection's ingested data and convert it to
    ontology-shaped rows.

    Each connection's `current/` dataset is ARG-shaped (camelCase fields such as
    `entityType`/`id`) as written by `DatasetStore`. `InventoryDatasetMapper`
    already knows how to read that layout and run it through
    `EntityBuilder`/`RelationshipBuilder` to produce ontology-shaped rows
    (`resource_id`, `entity_type`, `subject_id`/`object_id`, ...) that both
    `SemanticEngine.from_rows` and `NetworkIntelligenceService.from_rows`
    require. Reusing it here is what was missing: previously nothing converted
    synced connection data into a queryable snapshot for the API, so
    search/context/network routes always reported `upstream_unavailable` even
    after a successful sync.

    Returns ``(entities, relationships, freshness)``; all empty/blank when no
    connection has synced any data yet.
    """
    tables, freshness = _load_snapshot_tables()
    entities: list[dict] = []
    relationships: list[dict] = []
    for table in tables:
        entities.extend(table.get("ontology_entities") or [])
        relationships.extend(table.get("ontology_relationships") or [])
    return entities, relationships, freshness


# `_load_snapshot_tables()` is invoked by `/health` on every liveness/readiness
# probe (every ~10s) as well as by every semantic/network/vulnerability route.
# It performs a real OneLake read (list connections, open each manifest, map each
# dataset) which can easily exceed the Container Apps probe's 1s timeout under
# real network latency, causing repeated probe failures and a
# CrashLoopBackOff that silently reverts traffic to an older revision. Cache
# the result with a short TTL so the probe never triggers a fresh remote read.
# The cache is keyed by the resolved `AIOPS_HOME` root, because that root is
# resolved from the environment on every call and a value loaded for one root
# must never be served for another.
_SNAPSHOT_TABLES_CACHE_TTL_SECONDS = 30
_snapshot_tables_cache: dict[str, tuple[float, tuple[list[dict[str, list[dict]]], str]]] = {}
_governance_snapshot_cache: dict[
    tuple[str, tuple[str, ...]],
    tuple[float, GovernanceSnapshot | None],
] = {}

# Scoped network requests bypass the persisted snapshot and query ARG live, so
# without a cache every page interaction costs a round trip. Keep a completed
# observation for a five-minute operator workflow: live ARG can take longer
# than 30 seconds, and expiring it between Summary, Full detail, and drawer
# interactions recreates that cost on every click. The observed timestamp
# remains in the response so this bounded staleness is explicit.
_HYBRID_NETWORK_CACHE_TTL_SECONDS = 300
_DURABLE_LIVE_PATCH_CACHE_TTL_SECONDS = 300
_hybrid_network_cache: dict[
    tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]],
    tuple[float, tuple[list[dict], str, int]],
] = {}
_HYBRID_VULNERABILITY_CACHE_TTL_SECONDS = 30
_hybrid_vulnerability_cache: dict[
    tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]],
    tuple[float, Any],
] = {}
# Resolves the request-consistency half of WR-07: both the router's scope-
# validation path (operations.py::_require's remediation branch) and the
# execution-construction path (runtime.py::_execution_service_for_scope) call
# hybrid_remediation independently within one HTTP request. Without a cache
# they could observe two different LiveRemediationPlanner/PlanRepository
# generations even though 03.2-01 already made plan_id itself stable.
_hybrid_remediation_cache: dict[
    tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]],
    tuple[float, Any],
] = {}


# WR-05: guards creation of the per-(cache, key) locks below. Held only
# long enough to look up or insert a single lock object -- never across a
# `build()` call -- so it can never itself become a contention point.
_ttl_cache_locks_guard = threading.Lock()
# Keyed by the cache dict's identity (`id(cache)`) and then by cache key, so
# a lock is scoped to one specific `(cache, key)` pair. This is what lets two
# callers racing the *same* key serialize on each other while callers
# resolving *different* keys (e.g. different subscription scopes, or a
# different TTL-cache family entirely) never block on each other, even while
# a build() for another key is in flight.
_ttl_cache_locks: dict[int, dict[Any, threading.RLock]] = {}


def _ttl_cache_lock(cache: dict, key: Any) -> threading.RLock:
    """Return the lock serializing builds for one ``(cache, key)`` pair.

    A :class:`threading.RLock` is used (not a plain ``Lock``) so that if a
    future ``build()`` ever re-entered :func:`_ttl_cached_value` for the same
    ``(cache, key)`` on the *same thread*, it would not deadlock against
    itself -- it would simply re-acquire the lock it already holds. The lock
    is created lazily on first use and never removed, mirroring the existing
    unbounded-lifetime cache dicts it protects.
    """
    with _ttl_cache_locks_guard:
        per_cache_locks = _ttl_cache_locks.setdefault(id(cache), {})
        lock = per_cache_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            per_cache_locks[key] = lock
        return lock


def _ttl_cached_value(
    cache: dict[tuple[str, tuple[str, ...]], tuple[float, Any]],
    key: tuple[str, tuple[str, ...]],
    *,
    ttl_seconds: float,
    now: float,
    build: Callable[[], Any],
    completion_clock: Callable[[], float] | None = None,
) -> Any:
    """Return ``cache[key]`` if it is younger than ``ttl_seconds``, else rebuild.

    Standalone and module-scoped (not nested inside :func:`build_context`) so
    it is importable and unit-testable on its own, independent of any request
    context.

    Thread-safe (WR-05): Starlette dispatches plain ``def`` routes -- like
    every route that resolves ``hybrid_remediation`` -- to a worker thread
    pool, so two genuinely concurrent requests can race this function for the
    same key. A lock-free read serves the common warm-cache case with no
    locking at all. On a miss, callers serialize on a lock scoped to this
    specific ``(cache, key)`` pair (see :func:`_ttl_cache_lock`) -- never a
    single module-wide lock -- so concurrent callers for *different* keys are
    never blocked by a build in flight for another key. The lock is held
    across `build()` for the racing key so exactly one build happens and
    every concurrent same-key caller observes the identical cached object,
    instead of each caller building (and one silently overwriting another's)
    its own competing value. A second check inside the lock covers a caller
    that queued behind another that already refreshed the entry while it
    waited.
    """
    cached = cache.get(key)
    if cached is not None and now - cached[0] < ttl_seconds:
        return cached[1]

    with _ttl_cache_lock(cache, key):
        cached = cache.get(key)
        if cached is not None and now - cached[0] < ttl_seconds:
            return cached[1]
        value = build()
        cache[key] = (
            completion_clock() if completion_clock is not None else now,
            value,
        )
        return value


def _optional_configuration_data_rows(
    logs_client: Any,
    workspace_id: str,
) -> list[dict[str, Any]]:
    """Read optional software inventory without disabling patch remediation."""
    try:
        return list(logs_client.query_configuration_data(workspace_id))
    except RuntimeError as exc:
        if (
            "Failed to resolve table or column expression named "
            "'ConfigurationData'"
        ) in str(exc):
            _LOGGER.info(
                "live_patch_configuration_data_absent workspace_id=%s",
                workspace_id,
            )
            return []
        _LOGGER.warning(
            "live_patch_configuration_data_unavailable workspace_id=%s",
            workspace_id,
            exc_info=True,
        )
        return []
    except (OSError, TypeError, ValueError):
        _LOGGER.warning(
            "live_patch_configuration_data_unavailable workspace_id=%s",
            workspace_id,
            exc_info=True,
        )
        return []


def _load_snapshot_tables() -> tuple[list[dict[str, list[dict]]], str]:
    """Load the mapped datasets for every registered synced connection.

    Cached per `AIOPS_HOME` root with a short TTL (see module docstring above)
    so repeated calls (notably the health probe, hit every ~10s) don't each
    perform a fresh remote OneLake read.
    """
    from storage.datasets import DatasetStore

    root = aiops_home()
    cache_key = str(root)
    now = time.time()
    cached = _snapshot_tables_cache.get(cache_key)
    if cached is not None:
        cached_at, cached_value = cached
        if now - cached_at < _SNAPSHOT_TABLES_CACHE_TTL_SECONDS:
            return cached_value

    connections = ConnectionRegistry(root).list()
    mapper = InventoryDatasetMapper()
    tables_by_connection: list[dict[str, list[dict]]] = []
    freshness = ""
    failure_freshness = ""
    for connection in connections:
        connection_root = _connection_dataset_dir(root, connection.connection_id)
        store = DatasetStore(connection_root)
        try:
            selection = GenerationResolver(store).resolve()
        except (LookupError, OSError, TypeError, ValueError):
            continue  # connection registered but never synced
        snapshot_dir = selection.active_generation
        manifest_path = f"{snapshot_dir}/manifest.json"
        if store.is_remote:
            if not store.fs.exists(manifest_path):
                failed_at = datetime.now(UTC).isoformat()
                tables_by_connection.append(
                    _snapshot_failure_table(
                        connection,
                        "Snapshot manifest is missing",
                        failed_at,
                    )
                )
                failure_freshness = max(failure_freshness, failed_at)
                _LOGGER.warning(
                    "Snapshot manifest missing for connection %s at %s",
                    connection.connection_id,
                    manifest_path,
                )
                continue
            try:
                with store.fs.open(manifest_path, "rt") as handle:
                    manifest = json.loads(handle.read())
            except (OSError, json.JSONDecodeError) as exc:
                failed_at = datetime.now(UTC).isoformat()
                tables_by_connection.append(
                    _snapshot_failure_table(
                        connection,
                        "Snapshot manifest could not be read",
                        failed_at,
                    )
                )
                failure_freshness = max(failure_freshness, failed_at)
                _LOGGER.warning(
                    "Snapshot manifest read failed for connection %s: %s",
                    connection.connection_id,
                    exc,
                )
                continue
        else:
            manifest_file = Path(manifest_path)
            if not manifest_file.exists():
                failed_at = datetime.now(UTC).isoformat()
                tables_by_connection.append(
                    _snapshot_failure_table(
                        connection,
                        "Snapshot manifest is missing",
                        failed_at,
                    )
                )
                failure_freshness = max(failure_freshness, failed_at)
                _LOGGER.warning(
                    "Snapshot manifest missing for connection %s at %s",
                    connection.connection_id,
                    manifest_file,
                )
                continue
            try:
                manifest = json.loads(manifest_file.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                failed_at = datetime.now(UTC).isoformat()
                tables_by_connection.append(
                    _snapshot_failure_table(
                        connection,
                        "Snapshot manifest could not be read",
                        failed_at,
                    )
                )
                failure_freshness = max(failure_freshness, failed_at)
                _LOGGER.warning(
                    "Snapshot manifest read failed for connection %s: %s",
                    connection.connection_id,
                    exc,
                )
                continue
        run_id = str(manifest.get("runId") or connection.connection_id)
        try:
            tables, _selection = _load_generation_tables(
                store,
                mapper,
                run_id,
                selection=selection,
            )
        except Exception as exc:  # noqa: BLE001 - isolate malformed connection snapshots.
            failed_at = datetime.now(UTC).isoformat()
            tables_by_connection.append(
                _snapshot_failure_table(
                    connection,
                    "Snapshot mapping failed",
                    failed_at,
                    run_id=run_id,
                )
            )
            failure_freshness = max(failure_freshness, failed_at)
            _LOGGER.warning(
                "Snapshot mapping failed for connection %s run %s: %s",
                connection.connection_id,
                run_id,
                exc,
            )
            continue
        tables_by_connection.append(tables)
        started_at = str(manifest.get("startedAt") or "")
        freshness = max(freshness, started_at)
    result = (tables_by_connection, freshness or failure_freshness)
    _snapshot_tables_cache[cache_key] = (now, result)
    return result


def _load_generation_tables(
    store: Any,
    mapper: InventoryDatasetMapper,
    run_id: str,
    *,
    selection: GenerationSelection | None = None,
) -> tuple[dict[str, list[dict]], GenerationSelection]:
    """Map one pointer selection without re-reading it between table reads."""
    selected = selection or GenerationResolver(store).resolve()
    tables = mapper.load(
        selected.active_generation,
        run_id,
        fs=store.fs if store.is_remote else None,
    )
    return tables, selected


_DEFENDER_SOURCE_FAMILIES = (
    "defender_assessments",
    "defender_alerts",
    "defender_attack_paths",
    "defender_secure_scores",
)


def _snapshot_failure_table(
    connection: Any,
    error: str,
    observed_at: str,
    *,
    run_id: str = "",
) -> dict[str, list[dict[str, Any]]]:
    """Represent one failed connection as degraded Defender source coverage."""
    subscription_id = str(getattr(connection, "subscription_id", "") or "")
    connection_id = str(getattr(connection, "connection_id", "") or "")
    requested_scope = {"subscription": [subscription_id]} if subscription_id else {}
    return {
        "metadata_source_status": [
            {
                "source_family": family,
                "run_id": run_id or connection_id,
                "status": "failed",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "requested_scope": requested_scope,
                "requested_scope_json": json.dumps(requested_scope, sort_keys=True),
                "subscription_id": subscription_id,
                "subscription_connection": connection_id,
                "provider_status": "failed",
                "freshness": "unknown",
                "availability": "unavailable",
                "quality": "degraded",
                "error": error,
                # MED-03: an unreachable connection has no known row count
                # (never `0` -- that would misread as `healthy-empty`).
                "row_count": None,
                "lineage_ref": "",
            }
            for family in _DEFENDER_SOURCE_FAMILIES
        ]
    }


def _load_semantic_snapshot() -> SemanticEngine | None:
    root = aiops_home()
    entities, relationships, freshness = _load_ontology_rows()
    if not entities:
        return None
    return SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        knowledge_version=f"semantic-{root}",
        freshness=freshness or "1970-01-01T00:00:00Z",
    )


def _traffic_analysis_observations(
    relationships: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...] | None:
    observations: list[dict[str, Any]] = []
    for relationship in relationships:
        if str(relationship.get("predicate") or "").casefold() != "trafficobserved":
            continue
        payload: Mapping[str, Any] = {}
        raw_payload = relationship.get("payload_json")
        if isinstance(raw_payload, Mapping):
            payload = raw_payload
        elif isinstance(raw_payload, str) and raw_payload:
            try:
                decoded = json.loads(raw_payload)
            except (TypeError, ValueError):
                decoded = {}
            if isinstance(decoded, Mapping):
                payload = decoded
        attributes = relationship.get("attributes")
        if not isinstance(attributes, Mapping):
            attributes = payload.get("attributes")
        if (
            not isinstance(attributes, Mapping)
            or attributes.get("dataSource") != "traffic_analytics"
        ):
            continue
        normalized = dict(relationship)
        normalized["attributes"] = dict(attributes)
        normalized["subject_id"] = str(
            relationship.get("subject_id")
            or payload.get("subjectId")
            or payload.get("subject_id")
            or ""
        ).casefold()
        normalized["object_id"] = str(
            relationship.get("object_id")
            or payload.get("objectId")
            or payload.get("object_id")
            or ""
        ).casefold()
        observations.append(normalized)
    return tuple(observations) or None


def _load_network_service() -> NetworkIntelligenceService | None:
    entities, relationships, freshness = _load_ontology_rows()
    if not entities:
        return None
    policy, _revision = _network_policy_store().read_with_revision_or_raise()
    return NetworkIntelligenceService.from_rows(
        entities,
        observed_at=freshness,
        policy=policy,
        semantic_relationships=relationships,
        flow_observations=_traffic_analysis_observations(relationships),
    )


def _load_incident_engine() -> IncidentEngine | None:
    semantic = _load_semantic_snapshot()
    if semantic is None:
        return None
    inventory = [
        entity
        for entity in _load_ontology_rows()[0]
        if entity.get("entity_type")
        in {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"}
    ]
    intelligence = IncidentIntelligence.from_semantic_engine(
        semantic,
        inventory=inventory,
        incidents=[],
        alerts=[],
        resource_changes=[],
        patch_findings=[],
        lifecycle_findings=[],
        history=[],
    )
    return IncidentEngine.from_intelligence(
        intelligence,
        network_provider=_load_network_service,
        vulnerability_provider=_load_vulnerability_service,
    )


# KB->CVE (MSRC) and CVE->detail (NVD) lookups are best-effort external
# enrichment. `_load_vulnerability_service()` is rebuilt on every request (see
# `build_context()` below), so results are memoized with a TTL to avoid an
# external API call storm and to respect NVD's rate limits.
#
# The caches are backed by OneLake (see `EnrichmentCache`) whenever
# AIOPS_HOME points at Fabric, so they survive restarts and are shared by
# every replica instead of each one cold-starting its own copy and
# multiplying load on rate-limited public feeds. A local home keeps them
# purely in memory. Failures never break the endpoint.
_KB_CVE_CACHE_TTL_SECONDS = 6 * 60 * 60
_DURABLE_CATALOG_CACHE_TTL_SECONDS = 5
_durable_catalog_cache: dict[
    tuple[str, tuple[str, ...]],
    tuple[float, dict[str, tuple[dict[str, Any], ...]]],
] = {}


@cache
def _enrichment_cache_for(name: str, root: str) -> EnrichmentCache:
    return EnrichmentCache(
        f"cache/{name}.json",
        store=OneLakeDocumentStore(root) if is_onelake_uri(root) else None,
        ttl_seconds=_KB_CVE_CACHE_TTL_SECONDS,
    )


def _enrichment_cache(name: str) -> EnrichmentCache:
    """One durable cache per feed, reused per process.

    Keyed by the resolved `AIOPS_HOME` as well as the feed name: the root is
    read from the environment on every call, and entries cached under one
    root must never be served for another.
    """
    return _enrichment_cache_for(name, str(aiops_home()))


def _durable_enrichment_records() -> tuple[dict[str, Any], ...]:
    """Read fresh validated worker checkpoints without invoking a provider.

    A new cache facade is intentional: ``EnrichmentCache`` keeps an L1 once
    loaded, while this API process must observe records committed by the
    separately scheduled Container Apps Job without requiring a restart.
    """

    return EnrichmentCache(
        EXPOSURE_ENRICHMENT_DOCUMENT,
        store=OneLakeDocumentStore(str(aiops_home())),
        ttl_seconds=_KB_CVE_CACHE_TTL_SECONDS,
    ).records()


def _durable_catalog_records(item_id: str) -> tuple[dict[str, Any], ...]:
    identifier = str(item_id or "").strip().upper()
    root = str(aiops_home())
    index = _ttl_cached_value(
        _durable_catalog_cache,
        (root, ()),
        ttl_seconds=_DURABLE_CATALOG_CACHE_TTL_SECONDS,
        now=time.monotonic(),
        build=_durable_catalog_index,
        completion_clock=time.monotonic,
    )
    return tuple(dict(record) for record in index.get(identifier, ()))


def _refresh_durable_catalog_records(
    item_id: str,
) -> tuple[dict[str, Any], ...]:
    """Refresh one CVE for explicit maintenance callers, never API reads."""

    identifier = canonical_enrichment_identifier("nvd", item_id)
    cache = EnrichmentCache(
        EXPOSURE_ENRICHMENT_DOCUMENT,
        store=OneLakeDocumentStore(str(aiops_home())),
        ttl_seconds=_KB_CVE_CACHE_TTL_SECONDS,
    )
    worker = EnrichmentWorker(cache, max_items=3)
    worker.refresh(
        tuple(
            EnrichmentTarget(source, identifier)
            for source in ("nvd", "epss", "kev")
        )
    )
    return tuple(
        record
        for source in ("nvd", "epss", "kev")
        if (record := cache.get_record(source, identifier)) is not None
    )


def _durable_catalog_index() -> dict[str, tuple[dict[str, Any], ...]]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for record in _durable_enrichment_records():
        source = str(record.get("source") or "").casefold()
        record_identifier = str(record.get("identifier") or "").upper()
        payload = record.get("payload")
        identifiers = (
            {record_identifier}
            if source in {"nvd", "epss", "kev", "msrc"} and record_identifier
            else set()
        )
        if source == "msrc" and isinstance(payload, Mapping):
            identifiers.update(
                str(value).upper() for value in payload.get("cve_ids") or ()
            )
        for mapped_identifier in identifiers:
            selected.setdefault(mapped_identifier, []).append(dict(record))
    return {key: tuple(records) for key, records in selected.items()}


def _durable_enrichment_payloads(
    records: tuple[dict[str, Any], ...],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index usable LKG payloads by their validated source/item identity."""

    payloads: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        payloads[
            (
                str(record.get("source") or ""),
                str(record.get("identifier") or ""),
            )
        ] = payload
    return payloads


def _durable_probability(
    payload: Mapping[str, Any] | None,
    field: str,
) -> float | None:
    """Return a finite public-feed probability in the closed unit interval."""

    if payload is None:
        return None
    try:
        value = float(payload.get(field))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _resolve_kb_metadata(kb_ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Resolve KB ids to their MSRC metadata (CVE ids and publication date).

    Cached alongside the CVE mapping because both come from the same single
    MSRC query -- fetching the publication date separately would double the
    request volume against a public, unauthenticated feed for no benefit.
    Returns an empty dict on any network failure so callers fall back to the
    `KB-<kbId>` proxy identifier and an unknown date.
    """
    resolved: dict[str, dict[str, Any]] = {}
    to_fetch: list[str] = []
    cache = _enrichment_cache("msrc_kb_cve")
    for kb_id in kb_ids:
        hit, value = cache.get(kb_id)
        if not hit:
            to_fetch.append(kb_id)
            continue
        # Entries cached before publication dates were captured are plain
        # CVE-id lists. Read them as "CVEs known, date unknown" rather than
        # discarding the cache and re-querying MSRC for every KB.
        if isinstance(value, Mapping):
            resolved[kb_id] = {
                "cve_ids": tuple(value.get("cve_ids") or ()),
                "published_at": str(value.get("published_at") or ""),
            }
        else:
            resolved[kb_id] = {"cve_ids": tuple(value or ()), "published_at": ""}
    if to_fetch:
        try:
            updates = MsrcKbLookupConnector().fetch(tuple(to_fetch))
        except Exception:
            _LOGGER.warning("MSRC KB-to-CVE lookup failed; falling back to KB proxy ids", exc_info=True)
            updates = ()
        fetched_kbs = {update.kb_id for update in updates}
        pending: dict[str, Any] = {}
        for update in updates:
            entry = {
                "cve_ids": list(update.cve_ids),
                "published_at": update.published_at,
            }
            pending[update.kb_id] = entry
            resolved[update.kb_id] = {
                "cve_ids": update.cve_ids,
                "published_at": update.published_at,
            }
        for kb_id in to_fetch:
            if kb_id not in fetched_kbs:
                pending[kb_id] = {"cve_ids": [], "published_at": ""}
                resolved[kb_id] = {"cve_ids": (), "published_at": ""}
        cache.set_many(pending)
    return resolved


def _resolve_kb_to_cves(kb_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Resolve KB ids to real CVE ids via the public MSRC Security Update
    Guide feed, memoized with a TTL so repeated requests don't re-query MSRC
    for the same KBs. Returns an empty tuple for KBs MSRC has no CVE for
    (e.g. Servicing Stack Updates, which are commonly advisory-only) and an
    empty dict entirely on any network failure, so callers can safely fall
    back to the `KB-<kbId>` proxy identifier.
    """
    return {
        kb_id: tuple(entry.get("cve_ids") or ())
        for kb_id, entry in _resolve_kb_metadata(kb_ids).items()
    }


# Failed enrichment lookups (e.g. NVD 429 rate-limiting) are cached for a
# much shorter TTL than successes: long enough that the background refresh
# thread doesn't hammer a throttled upstream every cycle, short enough that
# real recovery is picked up well within a work day. An empty dict is stored
# as the cached row for a negatively-cached id so callers keep their existing
# "no detail available" behavior for free.
_NEGATIVE_CACHE_TTL_SECONDS = 15 * 60


def _resolve_cve_details(cve_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """Enrich real CVE ids with full detail (description, CVSS) from NVD,
    memoized with a TTL. Requires the `NVD_API_KEY` environment variable;
    returns no rows (and never raises) if it is unset or the request fails,
    so enrichment is always optional.
    """
    rows: list[dict[str, Any]] = []
    to_fetch: list[str] = []
    cache = _enrichment_cache("nvd_cve_detail")
    for cve_id in cve_ids:
        found, value, age = cache.get_entry(cve_id)
        # Negative entries (an empty row) expire far sooner than successful
        # ones, so a throttled upstream is retried within the hour rather
        # than being written off for a whole day.
        ttl = _KB_CVE_CACHE_TTL_SECONDS if (found and value) else _NEGATIVE_CACHE_TTL_SECONDS
        if found and age < ttl:
            if value:
                rows.append(value)
            continue
        to_fetch.append(cve_id)
    if to_fetch:
        pending: dict[str, Any] = {}
        try:
            cves = NvdCveEnrichmentConnector().fetch_cves(tuple(to_fetch))
        except Exception:
            _LOGGER.warning("NVD CVE enrichment failed; CVEs will be surfaced without detail", exc_info=True)
            # Negative-cache the whole failed batch (a rate-limited request
            # aborts the connector's per-id loop, so ids after the failing
            # one never got a chance to succeed either) with a short TTL, so
            # the ~30s background refresh doesn't retry an upstream that
            # just told us to back off.
            for cve_id in to_fetch:
                pending[cve_id] = {}
            cves = ()
        for cve in cves:
            row = cve.to_dict()
            pending[cve.cve_id] = row
            rows.append(row)
        cache.set_many(pending)
    return rows


# EPSS scores drift slowly (FIRST.org publishes new scores roughly daily) and
# the KEV catalog changes even less often, so both share the same long TTL
# used for the other public-feed enrichments above, and the same durable
# OneLake backing.


def _resolve_epss_scores(cve_ids: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """Fetch EPSS exploitation-probability scores for `cve_ids` from
    FIRST.org, memoized with a TTL. Returns an empty dict (never raises) on
    any network failure so EPSS enrichment is always optional.
    """
    scores: dict[str, dict[str, float]] = {}
    to_fetch: list[str] = []
    cache = _enrichment_cache("epss_scores")
    for cve_id in cve_ids:
        hit, value = cache.get(cve_id)
        if hit:
            scores[cve_id] = dict(value or {})
        else:
            to_fetch.append(cve_id)
    if to_fetch:
        try:
            fetched = EpssScoreConnector().fetch_scores(tuple(to_fetch))
        except Exception:
            _LOGGER.warning("EPSS score lookup failed; CVEs will be surfaced without EPSS", exc_info=True)
            fetched = {}
        pending: dict[str, Any] = {}
        for cve_id in to_fetch:
            row = fetched.get(cve_id, {"epss_score": 0.0, "epss_percentile": 0.0})
            pending[cve_id] = row
            scores[cve_id] = row
        cache.set_many(pending)
    return scores


def _resolve_kev_catalog() -> dict[str, dict[str, str]]:
    """Fetch the full CISA KEV catalog, memoized with a TTL. Returns an empty
    dict (never raises) on any network failure so KEV enrichment is always
    optional; every CVE is simply treated as not-known-exploited.
    """
    cache = _enrichment_cache("cisa_kev")
    hit, value = cache.get("catalog")
    if hit:
        return dict(value or {})
    found, stale, _age = cache.get_entry("catalog")
    try:
        catalog = KevCatalogConnector().fetch_catalog()
    except Exception:
        _LOGGER.warning("CISA KEV catalog lookup failed; KEV status will be unavailable", exc_info=True)
        # Serve the expired catalog rather than nothing: a stale KEV listing
        # is far more useful than treating every CVE as not-exploited.
        return dict(stale or {}) if found else {}
    cache.set("catalog", catalog)
    return catalog


def _build_vulnerability_service(
    tables: list[dict[str, list[dict]]],
    freshness: str,
    *,
    semantic: SemanticEngine | None = None,
    network: NetworkIntelligenceService | None = None,
    connection_context: Mapping[str, Mapping[str, Any]] | None = None,
    use_temporal_projection: bool = False,
    projection_generation_id: str | None = None,
    enrichment_records: tuple[dict[str, Any], ...] | None = None,
) -> VulnerabilityIntelligenceService | None:
    """Build vulnerability intelligence from one authoritative snapshot."""
    if not freshness:
        return None
    pending: list[dict[str, Any]] = []
    projected_current: list[dict[str, Any]] = []
    temporal_observations: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    defender_findings: list[dict[str, Any]] = []
    defender_assessments: list[dict[str, Any]] = []
    container_image_exposures: list[dict[str, Any]] = []
    defender_signals: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "alerts",
            "attack_paths",
            "attack_path_nodes",
            "attack_path_connections",
            "secure_scores",
            "secure_score_controls",
            "source_status",
        )
    }
    installed_kbs: set[tuple[str, str]] = set()
    # WR-06: every target_resource_id seen in a raw silver_patch_findings
    # row, regardless of kb_id or installed/missing status -- proves the
    # target was actually observed by this snapshot's source data, so
    # `VulnerabilityIntelligenceService.is_asset_observed()` can tell "this
    # target genuinely has zero remaining exposures" apart from "this
    # target was never observed at all" (e.g. the wrong subscription).
    observed_target_ids: set[str] = set()
    for table in tables:
        if use_temporal_projection:
            current_rows = table.get("gold_exposure_current") or []
            projected_current.extend(current_rows)
            temporal_observations.extend(
                table.get("silver_exposure_observations") or []
            )
            source_status.extend(table.get("metadata_source_status") or [])
            observed_target_ids.update(
                str(row.get("target_id") or "")
                for row in current_rows
                if str(row.get("target_id") or "").strip()
            )
        for row in table.get("silver_patch_findings") or []:
            kb_id = str(row.get("kb_id") or "").strip()
            target = str(row.get("target_resource_id") or "")
            if target:
                observed_target_ids.add(target)
            if not kb_id or not target:
                continue
            status = str(row.get("status") or "missing")
            if status == "installed":
                installed_kbs.add((target, kb_id))
                continue
            pending.append(
                {
                    "finding_id": str(row.get("resource_id") or f"{target}|{kb_id}"),
                    "server_id": target,
                    "subscription_id": str(
                        row.get("subscription_id")
                        or row.get("subscriptionId")
                        or ""
                    ),
                    "missing_kb": kb_id,
                    "severity": row.get("severity") or "Unknown",
                    "recommended_patch": row.get("update_name") or kb_id,
                    "first_observed_at": row.get("published_at") or row.get("timestamp") or "",
                    "source": "Azure Update Manager",
                }
            )
        for row in table.get("silver_defender_findings") or []:
            cve_id = str(row.get("cve_id") or "").strip().upper()
            target = str(row.get("target_resource_id") or "")
            status = str(row.get("status") or "Unhealthy")
            if (
                not cve_id.startswith("CVE-")
                or not target
                or status.casefold() in {"healthy", "notapplicable", "not applicable", "resolved"}
            ):
                continue
            defender_findings.append(
                {
                    "finding_id": str(row.get("resource_id") or f"{target}|{cve_id}|defender"),
                    "server_id": target,
                    "cve_id": cve_id,
                    "severity": row.get("severity") or "Unknown",
                    "recommended_patch": row.get("fixed_version")
                    or row.get("recommendation")
                    or "",
                    "first_observed_at": row.get("last_assessed_at")
                    or row.get("timestamp")
                    or "",
                    "source": "Microsoft Defender for Cloud",
                    "defender_assessment_id": row.get("assessment_id") or "",
                    "defender_recommendation": row.get("recommendation") or "",
                    "defender_status": status,
                    "defender_last_assessed_at": row.get("last_assessed_at") or "",
                    "defender_patchable": bool(row.get("patchable", False)),
                    "defender_software_vendor": row.get("software_vendor") or "",
                    "defender_software_name": row.get("software_name") or "",
                    "defender_software_version": row.get("software_version") or "",
                    "defender_fixed_version": row.get("fixed_version") or "",
                }
            )
        for row in table.get("silver_defender_assessments") or []:
            target = str(row.get("target_resource_id") or "")
            if not target:
                continue
            defender_assessments.append(
                {
                    "assessment_id": str(row.get("resource_id") or ""),
                    "server_id": target,
                    "target_resource_id": target,
                    "resource_type": str(row.get("target_resource_type") or _resource_type_from_id(target)),
                    "status": str(row.get("status") or "Unknown"),
                    "severity": str(row.get("severity") or "Unknown"),
                    "recommendation": str(row.get("recommendation") or ""),
                    "description": str(row.get("description") or ""),
                    "remediation": str(row.get("remediation") or ""),
                    "last_assessed_at": str(row.get("last_assessed_at") or ""),
                    "subscription_id": str(row.get("subscription_id") or ""),
                }
            )
        for row in table.get("silver_container_image_exposure") or []:
            registry = str(row.get("registry_resource_id") or row.get("target_resource_id") or "")
            if not registry:
                continue
            container_image_exposures.append(
                {
                    "id": str(row.get("resource_id") or ""),
                    "server_id": registry,
                    "target_resource_id": str(row.get("target_resource_id") or ""),
                    "registry_resource_id": registry,
                    "registry_host": str(row.get("registry_host") or ""),
                    "repository": str(row.get("repository") or ""),
                    "image_digest": str(row.get("image_digest") or ""),
                    "image_tags": list(row.get("image_tags") or []),
                    "image_uri": str(row.get("image_uri") or ""),
                    "last_pushed_at": str(row.get("last_pushed_at") or ""),
                    "status": str(row.get("status") or "Unhealthy"),
                    "severity": str(row.get("severity") or "Unknown"),
                    "critical_count": int(row.get("critical_count") or 0),
                    "high_count": int(row.get("high_count") or 0),
                    "vulnerable_package_count": int(row.get("vulnerable_package_count") or 0),
                    "cve_count": int(row.get("cve_count") or 0),
                    "cve_ids": list(row.get("cve_ids") or []),
                    "vulnerable_packages": list(row.get("vulnerable_packages") or []),
                    "recommendation": str(row.get("recommendation") or ""),
                    "last_assessed_at": str(row.get("last_assessed_at") or ""),
                    "subscription_id": str(row.get("subscription_id") or ""),
                }
            )
        for name, signal_rows in defender_signals.items():
            rows = table.get(f"silver_defender_{name}") or []
            if name == "source_status" and not rows:
                rows = [
                    row
                    for row in table.get("metadata_source_status") or []
                    if str(row.get("source_family") or "").startswith(
                        "defender_"
                    )
                ]
            signal_rows.extend(rows)
    # The rollback reader retains its legacy membership suppression exactly.
    # On the temporal path these rows provide detail only; projected current
    # state below is the sole authority for whether an exposure is active.
    findings = (
        pending
        if use_temporal_projection
        else [
            item
            for item in pending
            if (item["server_id"], item["missing_kb"]) not in installed_kbs
        ]
    )

    # Read only checkpoints written by the scheduled enrichment worker.
    # Request-time construction must never invoke MSRC/NVD/EPSS/KEV.
    durable_records = (
        _durable_enrichment_records()
        if enrichment_records is None
        else tuple(enrichment_records)
    )
    durable_payloads = _durable_enrichment_payloads(durable_records)

    # Resolve real CVE ids for each pending KB from durable MSRC LKG records.
    # Some KBs genuinely have no CVE association and retain the historical
    # `KB-<kbId>` proxy identity without a provider fallback.
    temporal_kb_ids = {
        str(row.get("weakness_id") or "").strip()
        for row in projected_current
        if str(row.get("weakness_kind") or "").casefold() == "kb"
        and str(row.get("weakness_id") or "").strip()
    }
    requested_kb_ids = tuple(
        sorted(
            {
                str(item["missing_kb"])
                for item in findings
                if item.get("missing_kb")
            }
            | temporal_kb_ids
        )
    )
    kb_metadata: dict[str, dict[str, Any]] = {}
    for kb_id in requested_kb_ids:
        canonical_kb = str(kb_id).strip().upper()
        try:
            canonical_kb = canonical_enrichment_identifier("msrc", kb_id)
        except ValueError:
            # Legacy fixtures and pre-worker snapshots may carry short KB
            # identifiers. They cannot be newly written by the worker, but a
            # caller-supplied durable-record fixture may still describe them.
            pass
        payload = durable_payloads.get(("msrc", canonical_kb))
        if payload is None:
            continue
        cve_ids: list[str] = []
        for value in payload.get("cve_ids") or ():
            try:
                cve_ids.append(canonical_enrichment_identifier("nvd", value))
            except ValueError:
                continue
        kb_metadata[kb_id] = {
            "cve_ids": tuple(sorted(set(cve_ids))),
            "published_at": str(payload.get("published_at") or ""),
        }
    kb_to_cves = {
        kb_id: tuple(entry.get("cve_ids") or ()) for kb_id, entry in kb_metadata.items()
    }
    expanded_findings: list[dict[str, Any]] = []
    for item in findings:
        cve_ids = kb_to_cves.get(item["missing_kb"]) or (
            f"KB-{item['missing_kb']}",
        )
        expanded_findings.extend(
            {
                **item,
                "finding_id": f"{item['finding_id']}|{cve_id}",
                "cve_id": cve_id,
            }
            for cve_id in cve_ids
        )
    findings = _merge_vulnerability_finding_rows(
        [*expanded_findings, *defender_findings]
    )
    _attach_connection_business_context(findings, connection_context)
    temporal_findings = (
        _temporal_runtime_finding_rows(
            projected_current,
            observations=temporal_observations,
            source_status=source_status,
            kb_metadata=kb_metadata,
        )
        if use_temporal_projection
        else []
    )

    all_cve_ids = tuple(
        sorted(
            {
                item["cve_id"]
                for item in (*findings, *temporal_findings)
                if item.get("cve_id", "").upper().startswith("CVE-")
            }
        )
    )
    cve_rows: list[dict[str, Any]] = []
    epss_scores: dict[str, dict[str, float]] = {}
    kev_catalog: dict[str, dict[str, str]] = {}
    for cve_id in all_cve_ids:
        nvd_payload = durable_payloads.get(("nvd", cve_id))
        nvd_row = dict(nvd_payload or {})
        # The authorized finding owns membership and identity. Provider
        # content may describe it but cannot replace that canonical id.
        nvd_row["cve_id"] = cve_id
        try:
            cve_rows.append(CVE.from_mapping(nvd_row).to_dict())
        except (TypeError, ValueError, OverflowError):
            cve_rows.append(CVE(cve_id=cve_id, title=cve_id).to_dict())

        epss_payload = durable_payloads.get(("epss", cve_id))
        score = _durable_probability(epss_payload, "epss_score")
        percentile = _durable_probability(epss_payload, "epss_percentile")
        if score is not None or percentile is not None:
            epss_scores[cve_id] = {
                "epss_score": score or 0.0,
                "epss_percentile": percentile or 0.0,
            }

        kev_payload = durable_payloads.get(("kev", cve_id))
        if kev_payload is not None:
            kev_catalog[cve_id] = {
                "kev_date_added": str(kev_payload.get("kev_date_added") or ""),
                "kev_due_date": str(kev_payload.get("kev_due_date") or ""),
                "kev_ransomware_use": str(
                    kev_payload.get("kev_ransomware_use") or ""
                ),
            }

    _attach_business_context(findings, semantic)
    _attach_business_context(defender_assessments, semantic)
    _attach_business_context(container_image_exposures, semantic)
    # CR-05: `alerts`/`attack_paths`/.../`secure_score_controls` are all
    # mapped by `InventoryDatasetMapper.load()` through the generic
    # `_entity_row()` helper (both the Fabric-backed silver tables and the
    # onboarding/non-Fabric snapshot path funnel through the same mapper),
    # whose output schema only exposes `entity_type`/`name`/`resource_type`/
    # `location`/`payload_json` as top-level columns — every Defender-
    # specific field (`resourceIds`, `resourceId`, `attackPathId`, etc.) is
    # serialized *inside* the `payload_json` string. `_attach_defender_signal_
    # context()` below needs those fields as flat keys to resolve per-
    # resource scope attribution (`_resource_scope`) and the aggregate
    # environment/business_service/etc. dimensions. Previously that
    # unpacking only happened later, inside
    # `VulnerabilityIntelligenceService.__init__`/`_defender_payload()` --
    # *after* `_attach_defender_signal_context` had already run against the
    # still-nested rows and found nothing, so restricted-scope callers saw
    # empty Defender responses regardless of what had actually synced. Reuse
    # the exact same `_defender_payload()` unpacking here, before
    # attribution runs, for every signal family that carries a
    # `payload_json` blob. (`source_status` is a distinct schema that is
    # never unpacked via `_defender_payload` and is intentionally excluded.)
    for _signal_name in (
        "alerts",
        "attack_paths",
        "attack_path_nodes",
        "attack_path_connections",
        "secure_scores",
        "secure_score_controls",
    ):
        defender_signals[_signal_name] = [
            _defender_payload(row) for row in defender_signals[_signal_name]
        ]
        _attach_defender_signal_context(defender_signals[_signal_name], semantic)

    service = VulnerabilityIntelligenceService.from_rows(
        findings=findings,
        projected_current=(
            temporal_findings if use_temporal_projection else None
        ),
        projection_generation_id=projection_generation_id,
        defender_assessments=defender_assessments,
        container_image_exposures=container_image_exposures,
        defender_alerts=defender_signals["alerts"],
        defender_attack_paths=defender_signals["attack_paths"],
        defender_attack_path_nodes=defender_signals["attack_path_nodes"],
        defender_attack_path_connections=defender_signals[
            "attack_path_connections"
        ],
        defender_secure_scores=defender_signals["secure_scores"],
        defender_secure_score_controls=defender_signals[
            "secure_score_controls"
        ],
        defender_source_status=defender_signals["source_status"],
        security_updates=[
            {
                "kb_id": item["missing_kb"],
                "cve_ids": [item["cve_id"]],
                # MSRC's release date is the KB's actual publication. Falling
                # back to the assessment's observation date would be wrong,
                # so an unresolved KB stays honestly blank.
                "published_at": (
                    kb_metadata.get(item["missing_kb"], {}).get("published_at") or ""
                ),
            }
            for item in (*findings, *temporal_findings)
            if item.get("missing_kb")
        ],
        cves=cve_rows,
        freshness=freshness,
        metadata_connector=None,
        epss_scores=epss_scores,
        kev_catalog=kev_catalog,
        observed_asset_ids=observed_target_ids,
        enrichment_records=durable_records,
    )

    resolver = _network_reachability_resolver(network)
    if resolver is not None:
        service = service.correlate_network(resolver)
    risk_exceptions = list_risk_exceptions()
    if risk_exceptions:
        service = service.apply_risk_exceptions(risk_exceptions)
    return service


def _temporal_runtime_finding_rows(
    current_rows: list[dict[str, Any]],
    *,
    observations: list[dict[str, Any]],
    source_status: list[dict[str, Any]],
    kb_metadata: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join projected state to its exact event and compatibility identities.

    ``gold_exposure_current`` owns whether an exposure is active. Legacy
    patch/Defender rows are detail-only on this path, so an undated installed
    membership can neither close a newer missing episode nor reopen a closed
    one. The last immutable observation contributes event/publication
    timestamps without substituting any of them for tenant first detection.
    """
    observations_by_id: dict[str, dict[str, Any]] = {}
    for value in observations:
        row = dict(value)
        observation_id = str(
            row.get("observation_id") or row.get("resource_id") or ""
        ).strip()
        if not observation_id:
            continue
        previous = observations_by_id.get(observation_id)
        if previous is not None and json.dumps(
            previous, sort_keys=True, default=str
        ) != json.dumps(row, sort_keys=True, default=str):
            raise ValueError(
                "Conflicting immutable Exposure observation "
                f"{observation_id}"
            )
        observations_by_id[observation_id] = row

    result: list[dict[str, Any]] = []
    for value in sorted(
        current_rows,
        key=lambda row: (
            str(row.get("projection_generation_id") or ""),
            str(row.get("current_key") or row.get("resource_id") or ""),
        ),
    ):
        current = dict(value)
        current_key = str(
            current.get("current_key") or current.get("resource_id") or ""
        ).strip()
        last_observation_id = str(
            current.get("last_observation_id") or ""
        ).strip()
        observation = observations_by_id.get(last_observation_id, {})
        enriched = {
            **current,
            "current_key": current_key,
            "event_at": observation.get("event_time"),
            "ingested_at": observation.get("ingested_at"),
            "run_at": observation.get("run_at"),
            "published_at": observation.get("published_at"),
            "enriched_at": observation.get("enriched_at"),
            "source_completeness": _temporal_source_completeness(
                current, source_status
            ),
        }
        weakness_id = str(current.get("weakness_id") or "").strip()
        weakness_kind = str(current.get("weakness_kind") or "").casefold()
        if weakness_kind == "kb":
            cve_ids = tuple(kb_metadata.get(weakness_id, {}).get("cve_ids") or ())
            if not cve_ids:
                cve_ids = (f"KB-{weakness_id}",)
            result.extend(
                {
                    **enriched,
                    "finding_id": f"{current_key}|{cve_id}",
                    "cve_id": cve_id,
                    "missing_kb": weakness_id,
                }
                for cve_id in cve_ids
            )
        else:
            result.append(
                {
                    **enriched,
                    "finding_id": current_key,
                    "cve_id": weakness_id if weakness_kind == "cve" else "",
                    "missing_kb": "",
                }
            )
    return result


def _temporal_source_completeness(
    current: Mapping[str, Any],
    statuses: list[dict[str, Any]],
) -> str:
    explicit = str(
        current.get("source_completeness") or current.get("completeness") or ""
    ).strip()
    if explicit:
        return explicit
    families = {
        str(value).strip().casefold()
        for value in current.get("active_source_families") or ()
        if str(value).strip()
    }
    matched = [
        str(row.get("completeness") or row.get("state") or "").casefold()
        for row in statuses
        if _temporal_source_family(row.get("source_family")) in families
        and str(row.get("completeness") or row.get("state") or "").strip()
    ]
    if not matched:
        return "unknown"
    rank = {
        "unavailable": 0,
        "failed": 0,
        "stale": 1,
        "partial": 2,
        "healthy-empty": 3,
        "complete": 3,
    }
    return min(matched, key=lambda value: (rank.get(value, -1), value))


def _temporal_source_family(value: Any) -> str:
    family = str(value or "").strip().casefold()
    if family.startswith(("azure_update_manager", "aum")):
        return "aum"
    if family.startswith("defender"):
        return "defender"
    return family


def _merge_vulnerability_finding_rows(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge one exposure deterministically while retaining every evidence id."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for finding in findings:
        key = (
            str(finding.get("server_id") or "").casefold(),
            str(finding.get("cve_id") or "").casefold(),
        )
        grouped.setdefault(key, []).append(finding)

    merged: list[dict[str, Any]] = []
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=_finding_evidence_sort_key)
        primary = rows[0]
        latest_defender = _latest_defender_observation(rows)
        if (
            latest_defender is not None
            and str(primary.get("source") or "") == "Microsoft Defender for Cloud"
        ):
            primary = latest_defender
        combined = dict(primary)
        defender_bundle_fields = {
            field
            for row in rows
            for field in row
            if field.startswith("defender_") and field != "defender_evidence_ids"
        }

        # Fill source-specific fields without allowing ingestion order to
        # select a different value. Explicit operational fields below use
        # their own semantics instead of this stable fallback.
        explicit_fields = {
            "finding_id",
            "id",
            "source",
            "severity",
            "first_observed_at",
            "missing_kb",
            "recommended_patch",
            "evidence_ids",
            "sources",
            "recommendations",
            "software_observations",
            "defender_evidence_ids",
        } | defender_bundle_fields
        for field in sorted({name for row in rows for name in row} - explicit_fields):
            values = [
                row[field]
                for row in rows
                if field in row and row[field] not in (None, "", [], ())
            ]
            if not values:
                continue
            if all(isinstance(value, bool) for value in values):
                combined[field] = any(values)
            elif all(isinstance(value, (list, tuple, set)) for value in values):
                combined[field] = sorted(
                    {
                        str(item)
                        for value in values
                        for item in value
                        if str(item)
                    }
                )
            else:
                combined[field] = min(values, key=_stable_finding_value_key)

        if latest_defender is not None:
            for field in defender_bundle_fields:
                # Copy the observation as one coherent bundle, including
                # explicit empty/false values that supersede stale details.
                combined[field] = latest_defender.get(field)

        evidence_ids = {
            str(value)
            for row in rows
            for value in (
                *(row.get("evidence_ids") or ()),
                row.get("finding_id") or row.get("id") or "",
            )
            if str(value)
        }
        sources = {
            str(value)
            for row in rows
            for value in (*(row.get("sources") or ()), row.get("source") or "")
            if str(value)
        }
        recommendations = {
            str(value)
            for row in rows
            for value in (
                *(row.get("recommendations") or ()),
                row.get("recommended_patch") or "",
                row.get("defender_recommendation") or "",
            )
            if str(value)
        }
        software_observations = {
            str(value)
            for row in rows
            for value in row.get("software_observations") or ()
            if str(value)
        }
        software_observations.update(
            software
            for row in rows
            if (
                software := " ".join(
                    str(value)
                    for value in (
                        row.get("defender_software_vendor"),
                        row.get("defender_software_name"),
                        row.get("defender_software_version"),
                        row.get("defender_fixed_version"),
                    )
                    if value
                )
            )
        )
        primary_evidence_id = str(
            primary.get("finding_id") or primary.get("id") or ""
        )
        combined["finding_id"] = primary_evidence_id
        combined["source"] = str(primary.get("source") or "")
        combined["severity"] = _strongest_finding_severity(rows)
        combined["first_observed_at"] = _earliest_finding_observation(rows)
        combined["missing_kb"] = min(
            (str(row.get("missing_kb")) for row in rows if row.get("missing_kb")),
            key=str.casefold,
            default="",
        )
        remediation_rows = [row for row in rows if row.get("recommended_patch")]
        combined["recommended_patch"] = (
            str(min(remediation_rows, key=_finding_evidence_sort_key)["recommended_patch"])
            if remediation_rows
            else ""
        )
        combined["evidence_ids"] = sorted(evidence_ids)
        combined["sources"] = sorted(sources)
        combined["recommendations"] = sorted(recommendations)
        combined["software_observations"] = sorted(software_observations)
        combined["defender_evidence_ids"] = sorted(
            {
                str(value)
                for row in rows
                if str(row.get("source") or "") == "Microsoft Defender for Cloud"
                for value in (
                    *(row.get("defender_evidence_ids") or ()),
                    row.get("finding_id") or row.get("id") or "",
                )
                if str(value)
            }
        )
        merged.append(combined)
    return merged


def _resource_type_from_id(resource_id: str) -> str:
    parts = [part for part in str(resource_id or "").split("/") if part]
    lower_parts = [part.casefold() for part in parts]
    if len(parts) == 2 and lower_parts[0] == "subscriptions":
        return "microsoft.resources/subscriptions"
    if len(parts) == 4 and lower_parts[0] == "subscriptions" and lower_parts[2] == "resourcegroups":
        return "microsoft.resources/subscriptions/resourcegroups"
    try:
        index = lower_parts.index("providers")
    except ValueError:
        return ""
    tail = parts[index + 1 :]
    if len(tail) < 2:
        return ""
    return "/".join([tail[0], *tail[1::2]]).casefold()


def _finding_evidence_sort_key(row: Mapping[str, Any]) -> tuple[int, str, str, str]:
    source = str(row.get("source") or "")
    source_rank = {
        "Azure Update Manager": 0,
        "Microsoft Defender for Cloud": 1,
    }.get(source, 2)
    evidence_id = str(row.get("finding_id") or row.get("id") or "")
    return (
        source_rank,
        source.casefold(),
        evidence_id.casefold(),
        json.dumps(dict(row), sort_keys=True, default=str),
    )


def _latest_defender_observation(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for row in sorted(rows, key=_finding_evidence_sort_key):
        if str(row.get("source") or "") != "Microsoft Defender for Cloud":
            continue
        value = str(
            row.get("defender_last_assessed_at")
            or row.get("first_observed_at")
            or ""
        )
        if not value:
            continue
        try:
            observed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)
        candidates.append((observed.astimezone(UTC), row))
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def _stable_finding_value_key(value: Any) -> tuple[str, str]:
    rendered = json.dumps(value, sort_keys=True, default=str)
    return (rendered.casefold(), rendered)


def _strongest_finding_severity(rows: list[dict[str, Any]]) -> str:
    rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
    values = {
        str(row.get("severity") or "Unknown")
        for row in rows
        if row.get("severity")
    }
    return min(
        values or {"Unknown"},
        key=lambda value: (-rank.get(value.casefold(), 0), value.casefold(), value),
    )


def _earliest_finding_observation(rows: list[dict[str, Any]]) -> str:
    observations: list[tuple[datetime, str]] = []
    invalid: list[str] = []
    for row in rows:
        value = str(row.get("first_observed_at") or "")
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            observations.append((parsed.astimezone(UTC), value))
        except ValueError:
            invalid.append(value)
    if observations:
        return min(observations, key=lambda item: (item[0], item[1]))[1]
    return min(invalid, key=str.casefold, default="")


def _load_vulnerability_service() -> VulnerabilityIntelligenceService | None:
    tables, freshness = _load_snapshot_tables()
    return _build_vulnerability_service(
        tables,
        freshness,
        use_temporal_projection=_temporal_exposure_reader_enabled(),
    )


def _temporal_exposure_reader_enabled() -> bool:
    """Select projected serving only through the typed default-off flag."""
    config_path = os.environ.get(ENV_FABRIC_CONFIG, "").strip()
    if not config_path:
        return False
    exposure = FabricRuntimeConfig.load(config_path).exposure
    rollout = exposure_rollout_from_environment(exposure.rollout)
    return (
        exposure.enabled
        and not exposure.rollback_mode
        and rollout.authorized
        and rollout.read_stage
        in {ExposureRolloutStage.CANARY, ExposureRolloutStage.ON}
    )


# Risk exceptions are user-submitted mutations that must survive both a
# provider rebuild and a container restart, and must be consistent across
# replicas. They are persisted as a single OneLake document whenever
# AIOPS_HOME points at Fabric; a local (development) home keeps them in
# memory, which is sufficient for a single-process run.
_risk_exception_store: dict[str, RiskException] = {}
_RISK_EXCEPTION_DOCUMENT = "state/risk_exceptions.json"


def _document_store() -> Any:
    """Return the OneLake document store, or None for a local home.

    Shared by every caller that keeps small revisioned control-plane documents
    (risk exceptions, investigation ledgers).
    """
    root = aiops_home()
    if not is_onelake_uri(root):
        return None
    return OneLakeDocumentStore(str(root))


def _risk_exception_documents() -> Any:
    """Return the OneLake document store, or None for a local home."""
    return _document_store()


def _read_risk_exceptions() -> tuple[Any, dict[str, Any], int]:
    documents = _risk_exception_documents()
    payload = documents.read(_RISK_EXCEPTION_DOCUMENT) if documents else {}
    entries = payload.get("exceptions")
    return (
        documents,
        dict(entries) if isinstance(entries, dict) else {},
        int(payload.get("revision") or 0),
    )


def _write_risk_exceptions(
    documents: Any, entries: dict[str, Any], revision: int
) -> None:
    documents.write(
        _RISK_EXCEPTION_DOCUMENT,
        {"exceptions": entries, "revision": revision + 1},
        expected_revision=revision,
    )


def list_risk_exceptions() -> list[RiskException]:
    """Return every active risk exception, unfiltered by caller scope.

    WR-02: this contract is load-bearing for `revoke_risk_exception`'s
    restricted-scope authorization path (see `vulnerability.py`). If this
    function is ever changed to pre-filter by scope, add an equivalent
    unfiltered accessor rather than changing this one; the regression test
    `test_revoke_denies_when_risk_exception_list_pre_filters_by_scope`
    exists specifically to catch a violation of this contract, but only
    if the contract is not silently narrowed here.

    This function does quarantine (drop) malformed or expired entries at
    load time -- that filtering is a data-integrity concern, not a
    scope/authorization concern, and does not violate the contract above.
    """
    documents, entries, _revision = _read_risk_exceptions()
    if documents is None:
        candidates: list[Any] = list(_risk_exception_store.values())
    else:
        candidates = []
        for key in sorted(entries):
            payload = entries[key]
            if not isinstance(payload, Mapping):
                _LOGGER.warning("Quarantining malformed risk exception %s", key)
                continue
            try:
                candidates.append(RiskException(**payload))
            except (TypeError, ValueError):
                _LOGGER.warning("Quarantining malformed risk exception %s", key)

    active: list[RiskException] = []
    now_iso = datetime.now(UTC).isoformat()
    for exception in candidates:
        if not isinstance(exception, RiskException):
            _LOGGER.warning("Quarantining malformed in-memory risk exception")
            continue
        try:
            if exception.is_expired(now_iso=now_iso):
                continue
        except (TypeError, ValueError, OverflowError):
            _LOGGER.warning(
                "Quarantining risk exception %s with invalid expiry",
                exception.exception_id,
            )
            continue
        active.append(exception)
    return active


def add_risk_exception(exception: RiskException) -> None:
    documents, entries, revision = _read_risk_exceptions()
    if documents is None:
        _risk_exception_store[exception.exception_id] = exception
        return
    entries[exception.exception_id] = exception.to_dict()
    _write_risk_exceptions(documents, entries, revision)


def revoke_risk_exception(exception_id: str) -> bool:
    documents, entries, revision = _read_risk_exceptions()
    if documents is None:
        return _risk_exception_store.pop(exception_id, None) is not None
    if entries.pop(exception_id, None) is None:
        return False
    _write_risk_exceptions(documents, entries, revision)
    return True



def _attach_business_context(
    findings: list[dict[str, Any]], semantic: SemanticEngine | None = None
) -> None:
    """Populate application/business-service/owner/environment/criticality
    metadata on each pending finding, keyed by its ``server_id``.

    Previously these fields were left at their dataclass defaults (empty
    strings), which starved the composite risk model and the exposure UI of
    the business-impact context they display. The semantic engine already
    resolves this exact context (ownership, applications, business services,
    environment/criticality tags) for every observed resource, so this reuses
    it instead of re-deriving it from raw ontology rows.
    """
    semantic = semantic or _load_semantic_snapshot()
    if semantic is None:
        return
    entities = semantic.indexes.entities
    for item in findings:
        server_id = str(item.get("server_id") or "").casefold()
        if not server_id or server_id not in entities:
            continue
        public = semantic.indexes.public(server_id)
        for field in (
            "application",
            "business_service",
            "owner",
            "environment",
            "criticality",
            "subscription_id",
            "subscription_connection",
            "region",
        ):
            # A live provider may already have authoritative connection-level
            # context.  An empty semantic field must not erase that fallback.
            value = str(public.get(field) or "")
            if value:
                item[field] = value


def _attach_connection_business_context(
    findings: list[dict[str, Any]],
    contexts: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    """Fill missing live finding context from an active subscription mapping.

    Subscription onboarding deliberately stores business metadata against the
    connection/subscription scope.  This is a fallback for request-time
    observations whose exact resource is not present in the semantic snapshot;
    explicit resource metadata always wins.
    """
    if not contexts:
        return
    fields = (
        "business_service",
        "application",
        "owner",
        "environment",
        "criticality",
        "region",
    )
    for finding in findings:
        subscription_id = str(finding.get("subscription_id") or "").strip()
        context = contexts.get(subscription_id.casefold())
        if not context:
            continue
        for field in fields:
            if not str(finding.get(field) or "").strip():
                value = str(context.get(field) or "").strip()
                if value:
                    finding[field] = value
        if not str(finding.get("subscription_connection") or "").strip():
            connection_id = str(context.get("subscription_connection") or "").strip()
            if connection_id:
                finding["subscription_connection"] = connection_id


def _attach_defender_signal_context(
    rows: list[dict[str, Any]], semantic: SemanticEngine | None
) -> None:
    """Attach aggregate and per-resource scope values to a Defender signal."""
    if semantic is None:
        return
    entities = semantic.indexes.entities
    dimensions = (
        "application",
        "business_service",
        "owner",
        "environment",
        "criticality",
        "subscription_id",
        "subscription_connection",
        "region",
    )
    plural_names = {
        "application": "applications",
        "business_service": "business_services",
        "owner": "owners",
        "environment": "environments",
        "criticality": "criticalities",
        "subscription_id": "subscription_ids",
        "subscription_connection": "subscription_connections",
        "region": "regions",
    }
    for row in rows:
        resource_ids = {
            str(resource_id).casefold()
            for resource_id in row.get("resourceIds") or ()
            if str(resource_id).strip()
        }
        resource_id = str(row.get("resourceId") or "").casefold()
        if resource_id:
            resource_ids.add(resource_id)
        public_rows = [
            semantic.indexes.public(resource_id)
            for resource_id in sorted(resource_ids)
            if resource_id in entities
        ]
        resource_scope: dict[str, dict[str, str]] = {}
        for resource_id in sorted(resource_ids):
            if resource_id not in entities:
                continue
            public = semantic.indexes.public(resource_id)
            resource_scope[resource_id] = {
                "application": str(public.get("application") or ""),
                "business_service": str(public.get("business_service") or ""),
                "owner": str(public.get("owner") or ""),
                "environment": str(public.get("environment") or ""),
                "criticality": str(public.get("criticality") or ""),
                "subscription": str(public.get("subscription_id") or ""),
                "subscription_connection": str(
                    public.get("subscription_connection") or ""
                ),
                "region": str(public.get("region") or ""),
            }
        if resource_scope:
            # Retain attribution so request-time projection can remove
            # unauthorized resources instead of authorizing an aggregate row
            # merely because any one resource matched.
            row["_resource_scope"] = resource_scope
        for dimension in dimensions:
            values = sorted(
                {
                    str(public.get(dimension) or "")
                    for public in public_rows
                    if public.get(dimension)
                }
            )
            if values:
                row[plural_names[dimension]] = values
                if len(values) == 1:
                    row[dimension] = values[0]


def _network_reachability_resolver(
    network: NetworkIntelligenceService | None = None,
) -> Any:
    """Build a ``server_id -> {verdict, network_exposure, ...}`` resolver
    backed by the network engine, or ``None`` when no network data has been
    synced yet.

    Reachability is evaluated as "can the internet reach this server", which
    is the exposure question that matters for prioritizing vulnerabilities:
    a missing patch on an internet-facing box is materially more urgent than
    the same gap on a fully internal one. Findings whose server can't be
    resolved to an observed NIC are left indeterminate rather than guessed at.
    """
    network = network or _load_network_service()
    if network is None:
        return None

    def resolve(server_id: str) -> dict[str, Any] | None:
        target = str(server_id or "").casefold()
        if not target:
            return None
        nic = next(
            (
                candidate
                for candidate in network.snapshot.nics
                if candidate.attached_resource_id.casefold() == target
            ),
            None,
        )
        if nic is None:
            return {"verdict": "indeterminate", "network_exposure": "unknown"}
        if nic.has_public_ip:
            return {"verdict": "allowed", "network_exposure": "internet"}
        try:
            result = network.validate_flow(FlowQuery(source="internet", destination=server_id))
        except (LookupError, ValueError):
            return {"verdict": "indeterminate", "network_exposure": "internal"}
        return {
            "verdict": result.verdict,
            "network_exposure": "internet" if result.is_allowed else "internal",
            "firewall_path": [
                hop.rule_id or hop.control_id for hop in result.hops if hop.control == "azure_firewall"
            ],
            "nsg_path": [hop.rule_id or hop.control_id for hop in result.hops if hop.control == "nsg"],
        }

    return resolve


def _load_foundry_agent() -> FoundryPromptAgent | None:
    """Resolve the Copilot's Foundry prompt agent from the environment.

    Built once and memoized: unlike the snapshot providers, the agent is a
    stateless HTTP client whose configuration cannot change without a restart,
    and rebuilding it per request would discard its cached access token.
    """
    require_canary_authorization_if_requested()
    global _foundry_agent
    if _foundry_agent is _UNSET:
        # Operations Copilot is the shared narrator/orchestrator. Specialist
        # agents are resolved separately through `_load_foundry_specialist_agent`;
        # using the Network specialist here would make MAF mode page-biased
        # before it ever delegates.
        agent_class = select_foundry_agent_class(
            prefer_maf=maf_mode_enabled(),
            rest_agent_class=FoundryPromptAgent,
            maf_agent_class=MicrosoftAgentFrameworkFoundryAgent,
        )
        candidate = agent_class.from_env()
        if candidate is not None:
            candidate.validate_access()
        _foundry_agent = candidate
        if candidate is None:
            _LOGGER.info(
                "No Foundry prompt agent configured (%s/%s unset); the Operations "
                "Copilot will answer with retrieved context only.",
                "FOUNDRY_PROJECT_ENDPOINT",
                "FOUNDRY_AGENT_NAME",
            )
    return _foundry_agent


def _load_foundry_specialist_agent(specialist_id: str) -> FoundryPromptAgent | None:
    """Resolve and cache one page specialist independently of the narrator.

    Every specialist resolves through the same path, network included. The
    previous ``if specialist_id == "network": return _load_foundry_agent()``
    special case was harmless -- ``_load_foundry_agent`` itself calls
    ``from_env("network")``, and ``from_env`` already prefers
    ``FOUNDRY_NETWORK_AGENT_NAME`` over the legacy ``FOUNDRY_AGENT_NAME`` --
    but it read as though the network page deliberately answered as the
    shared narrator. Routing every page identically, with the narrator kept
    only as an explicit last resort, removes that ambiguity.
    """
    require_canary_authorization_if_requested()
    if specialist_id not in _foundry_specialist_agents:
        agent_class = select_foundry_agent_class(
            specialist_id,
            prefer_maf=maf_mode_enabled(),
            rest_agent_class=FoundryPromptAgent,
            maf_agent_class=MicrosoftAgentFrameworkFoundryAgent,
        )
        candidate = agent_class.from_env(specialist_id)
        if candidate is None:
            # Only fall back to the shared narrator when this specialist has no
            # agent of its own; never in preference to one.
            candidate = _load_foundry_agent()
        else:
            candidate.validate_access()
        _foundry_specialist_agents[specialist_id] = candidate
    return _foundry_specialist_agents[specialist_id]


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() in {"1", "true", "yes", "on"}


def _strict_boolean_environment(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a strict boolean value")


def _rollout_stage_environment(
    name: str,
    default: ExposureRolloutStage,
) -> ExposureRolloutStage:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return ExposureRolloutStage(raw.strip().casefold())
    except ValueError as exc:
        allowed = ", ".join(stage.value for stage in ExposureRolloutStage)
        raise ValueError(f"{name} must be one of: {allowed}") from exc


def exposure_rollout_from_environment(
    base: ExposureRolloutRuntimeConfig | None = None,
) -> ExposureRolloutRuntimeConfig:
    """Resolve one centralized, strict deployment override.

    The YAML contract remains authoritative for typed configuration. Container
    Apps can override only the non-secret stage and generation metadata needed
    to advance or roll back a revision.
    """

    rollout = base or ExposureRolloutRuntimeConfig()
    resolved = replace(
        rollout,
        authorized=_strict_boolean_environment(
            ENV_EXPOSURE_ROLLOUT_AUTHORIZED,
            rollout.authorized,
        ),
        write_stage=_rollout_stage_environment(
            ENV_EXPOSURE_WRITE_STAGE,
            rollout.write_stage,
        ),
        read_stage=_rollout_stage_environment(
            ENV_EXPOSURE_READ_STAGE,
            rollout.read_stage,
        ),
        web_stage=_rollout_stage_environment(
            ENV_EXPOSURE_WEB_STAGE,
            rollout.web_stage,
        ),
        handoff_stage=_rollout_stage_environment(
            ENV_EXPOSURE_HANDOFF_STAGE,
            rollout.handoff_stage,
        ),
        write_generation_id=os.environ.get(
            ENV_EXPOSURE_WRITE_GENERATION_ID,
            rollout.write_generation_id,
        ).strip(),
        read_generation_id=os.environ.get(
            ENV_EXPOSURE_READ_GENERATION_ID,
            rollout.read_generation_id,
        ).strip(),
        rollback_generation_id=os.environ.get(
            ENV_EXPOSURE_ROLLBACK_GENERATION_ID,
            rollout.rollback_generation_id,
        ).strip(),
    )
    resolved.validate()
    return resolved


def evaluate_exposure_promotion(
    rollout: ExposureRolloutRuntimeConfig,
    evidence: ExposurePromotionEvidence,
) -> ExposurePromotionDecision:
    """Return effective non-destructive pointers for a requested promotion."""

    rollout.validate()
    stages = (
        rollout.write_stage,
        rollout.read_stage,
        rollout.web_stage,
        rollout.handoff_stage,
    )
    if all(stage is ExposureRolloutStage.OFF for stage in stages):
        return ExposurePromotionDecision(
            allowed=True,
            blocked_reasons=(),
            active_writer_generation_id="",
            active_reader_generation_id=rollout.rollback_generation_id,
            candidate_generation_id=(
                rollout.read_generation_id or rollout.write_generation_id
            ),
            rollback_required=False,
        )

    checks = (
        ("adapter_not_ready", evidence.adapter_ready),
        ("cursor_keys_not_ready", evidence.cursor_keys_ready),
        ("source_coverage_incomplete", evidence.source_coverage_ready),
        ("semantic_reconciliation_failed", evidence.reconciliation_passed),
        ("telemetry_missing", evidence.telemetry_ready),
        ("alerts_missing", evidence.alerts_ready),
        ("slo_failed", evidence.slo_passed),
        ("ui_api_contract_failed", evidence.ui_api_contract_passed),
        ("live_validation_failed", evidence.live_validation_passed),
        ("ingestion_unhealthy", evidence.ingestion_healthy),
        ("read_path_unhealthy", evidence.read_path_healthy),
        ("key_rotation_unhealthy", evidence.key_rotation_healthy),
    )
    blocked_reasons = tuple(reason for reason, passed in checks if not passed)
    rollback_required = bool(
        blocked_reasons
        and rollout.read_stage
        in {ExposureRolloutStage.CANARY, ExposureRolloutStage.ON}
    )
    if blocked_reasons:
        return ExposurePromotionDecision(
            allowed=False,
            blocked_reasons=blocked_reasons,
            active_writer_generation_id="",
            active_reader_generation_id=rollout.rollback_generation_id,
            candidate_generation_id=(
                rollout.read_generation_id or rollout.write_generation_id
            ),
            rollback_required=rollback_required,
        )
    return ExposurePromotionDecision(
        allowed=True,
        blocked_reasons=(),
        active_writer_generation_id=(
            rollout.write_generation_id
            if rollout.write_stage is not ExposureRolloutStage.OFF
            else ""
        ),
        active_reader_generation_id=(
            rollout.read_generation_id
            if rollout.read_stage
            in {ExposureRolloutStage.CANARY, ExposureRolloutStage.ON}
            else rollout.rollback_generation_id
        ),
        candidate_generation_id=(
            rollout.read_generation_id or rollout.write_generation_id
        ),
        rollback_required=False,
    )


def _fabric_is_configured() -> bool:
    return bool(os.environ.get(ENV_FABRIC_CONFIG, "").strip()) or (
        _truthy("AIOPS_ENABLE_FABRIC")
        and bool(os.environ.get("FABRIC_WORKSPACE_ID", "").strip())
        and bool(os.environ.get("FABRIC_LAKEHOUSE_ID", "").strip())
    )


def _fabric_remediation_enabled() -> bool:
    """Whether the configured Fabric runtime enables remediation planning."""
    config_path = os.environ.get(ENV_FABRIC_CONFIG, "").strip()
    if not config_path:
        return True
    return FabricRuntimeConfig.load(config_path).remediation.enabled


def _fabric_exposure_query_enabled() -> bool:
    """Whether production should load and require the Fabric SQL read path."""

    config_path = os.environ.get(ENV_FABRIC_CONFIG, "").strip()
    if not config_path:
        return True
    exposure = FabricRuntimeConfig.load(config_path).exposure
    return exposure.enabled and not exposure.rollback_mode


def _fabric_runtime_from_environment() -> FabricRuntime | None:
    """Build the authoritative Fabric reader from a file or Container Apps env."""
    config_path = os.environ.get(ENV_FABRIC_CONFIG, "").strip()
    if config_path:
        return build_runtime(FabricRuntimeConfig.load(config_path))
    if not _fabric_is_configured():
        return None
    config = FabricRuntimeConfig(
        auth=FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID", "").strip(),
        ),
        # The API reads published OneLake tables. This source path is used only
        # by explicit publication commands, never by request handling.
        source_data_root=Path(
            os.environ.get("AIOPS_FABRIC_SOURCE_DATA_ROOT", "/data/fabric-source")
        ),
        workspace_id=os.environ["FABRIC_WORKSPACE_ID"].strip(),
        lakehouse_id=os.environ["FABRIC_LAKEHOUSE_ID"].strip(),
        ontology=OntologyRuntimeConfig(
            ontology_id=os.environ.get("FABRIC_ONTOLOGY_ID", "").strip(),
            ontology_name=os.environ.get(
                "FABRIC_ONTOLOGY_NAME", "Operational_Context_Graph"
            ).strip(),
        ),
    )
    return build_runtime(config)


#: Provenance for the ontology projection this runtime actually queries.
#:
#: ``sync_service.ontology_query`` reads the ``ontology`` Delta tables from
#: OneLake and traverses them in-process via ``OntologyQueryService`` -- it
#: does **not** call a Fabric IQ ontology/graph query surface. Evidence
#: citations must name the source that was really consulted, so this path is
#: labelled as the local projection it is. When the Fabric IQ traversal
#: surface is wired (``fabric_pipelines/ontology_binding.py``), that path
#: gets its own provenance value rather than reusing this one.
_ONTOLOGY_PROJECTION_PROVENANCE = "onelake-ontology-projection"
_FABRIC_DATA_AGENT_PROVENANCE = "fabric-data-agent"


def _data_agent_findings(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content")
    if not isinstance(content, list):
        raise TypeError("Fabric Data Agent returned no content")
    lines = [
        str(item.get("text") or "")
        for item in content
        if isinstance(item, Mapping) and str(item.get("text") or "").strip()
    ]
    findings = parse_gold_grounded_findings(
        "\n".join(lines),
        tool_call_id="fabric-iq-grounding",
    )
    if not findings:
        raise ValueError("Fabric Data Agent returned no structured findings")
    if any(finding.degraded or not finding.scope_ok for finding in findings):
        raise PermissionError("Fabric Data Agent evidence failed scope validation")
    return [finding.model_dump(mode="json") for finding in findings]


def _data_agent_findings_in_scope(
    findings: Sequence[Mapping[str, Any]],
    scope: Scope,
) -> bool:
    """Verify Data Agent resource identities against enforceable scope axes."""
    if set(scope.dimensions) - {"subscription"}:
        return False
    subscriptions = scope.values("subscription")
    if not subscriptions:
        return scope.is_unrestricted()
    for finding in findings:
        resource_ids = finding.get("resource_ids")
        if not isinstance(resource_ids, list) or not resource_ids:
            return False
        for resource_id in resource_ids:
            segments = [segment for segment in str(resource_id).split("/") if segment]
            normalized_segments = [segment.casefold() for segment in segments]
            try:
                subscription_index = normalized_segments.index("subscriptions")
                subscription_id = segments[subscription_index + 1].casefold()
            except (ValueError, IndexError):
                return False
            if subscription_id not in subscriptions:
                return False
    return True


def _load_fabric_iq_adapter() -> FabricIQToolAdapter | None:
    """Resolve optional semantic enrichment through the managed Fabric runtime.

    The runtime's ontology service is a semantic source only.  The adapter
    receives the request scope and stamps its response; it is never used to
    enumerate inventory or authorize a resource.

    The enrichment is served today by the OneLake ontology projection, not by
    Fabric IQ itself; responses are stamped accordingly so a downstream
    citation never overstates the source.
    """
    if not _truthy("AIOPS_ENABLE_FABRIC_IQ"):
        return None
    runtime = _fabric_runtime_from_environment()
    if runtime is None:
        return None
    data_agent_id = os.environ.get("FABRIC_GOLD_GROUNDING_AGENT_ID", "").strip()
    data_agent_tool = (
        os.environ.get(
            "FABRIC_GOLD_GROUNDING_TOOL_NAME",
            "DataAgent_AI_Ops_Data_Agent",
        ).strip()
        or "DataAgent_AI_Ops_Data_Agent"
    )
    use_data_agent = _truthy("AIOPS_ENABLE_FABRIC_DATA_AGENT_GROUNDING")
    if use_data_agent and not data_agent_id:
        return None
    credential = build_credential(runtime.config.auth) if use_data_agent else None

    def query(kind: str, args: dict[str, Any], scope: Any) -> dict[str, Any]:
        subject = str(args.get("subject") or "").strip()
        if not subject:
            raise ValueError("Ontology enrichment subject is required")
        if use_data_agent:
            generation_id = str(args.get("generation_id") or "").strip()
            if not generation_id:
                raise ValueError(
                    "Fabric Data Agent grounding requires an immutable generation"
                )
            scoped_question = (
                "Return line-delimited structured findings only. "
                f"Review {kind} context for {subject}. "
                f"Immutable generation: {generation_id}. "
                f"Authorized scope: {json.dumps(scope.to_dict(), sort_keys=True)}."
            )
            token = credential.get_token(
                "https://api.fabric.microsoft.com/.default"
            ).token
            result = query_gold_grounding(
                workspace_id=runtime.config.workspace_id,
                data_agent_id=data_agent_id,
                tool_name=data_agent_tool,
                question=scoped_question,
                token=token,
            )
            findings = _data_agent_findings(result)
            if not _data_agent_findings_in_scope(findings, scope):
                raise PermissionError(
                    "Fabric Data Agent evidence is outside the authorized scope"
                )
            return {
                "data": {
                    "findings": findings,
                    "generation_id": generation_id,
                },
                "freshness": "generation-bound",
                "authorization": "application-scope-checked",
                "provenance": _FABRIC_DATA_AGENT_PROVENANCE,
            }
        result = runtime.service.ontology_query(
            f"{kind} context for {subject}", entity=kind
        )
        if not isinstance(result, dict):
            raise TypeError("Ontology enrichment returned an invalid result")
        return {
            "data": result,
            "freshness": str(result.get("freshness") or "runtime"),
            "authorization": "scope-checked",
            "provenance": _ONTOLOGY_PROJECTION_PROVENANCE,
        }

    source = (
        _FABRIC_DATA_AGENT_PROVENANCE
        if use_data_agent
        else _ONTOLOGY_PROJECTION_PROVENANCE
    )
    return FabricIQToolAdapter(query=query, source=source)


def _fabric_network_service(runtime: FabricRuntime) -> NetworkIntelligenceService:
    snapshot = runtime.service.semantic_snapshot()
    relationships = snapshot.get("relationships", [])
    policy, _revision = _network_policy_store().read_with_revision_or_raise()
    return NetworkIntelligenceService.from_rows(
        snapshot["entities"],
        policy=policy,
        semantic_relationships=relationships,
        flow_observations=_traffic_analysis_observations(relationships),
    )


def _fabric_vulnerability_service(
    runtime: FabricRuntime,
) -> VulnerabilityIntelligenceService | None:
    try:
        semantic = runtime.semantic_engine()
    except (RuntimeError, TypeError, ValueError):
        _LOGGER.warning(
            "fabric_vulnerability_semantic_enrichment_unavailable",
            exc_info=True,
        )
        semantic = None
    try:
        network = _fabric_network_service(runtime)
    except (RuntimeError, TypeError, ValueError):
        _LOGGER.warning(
            "fabric_vulnerability_network_enrichment_unavailable",
            exc_info=True,
        )
        network = None
    patch = runtime.service.patch_intelligence_snapshot()
    defender = runtime.service.defender_intelligence_snapshot()
    findings = [
        {
            **row,
            "kb_id": row.get("kb_id") or row.get("missing_kb") or "",
            "target_resource_id": row.get("target_resource_id")
            or row.get("resource_key")
            or row.get("resource_id")
            or "",
        }
        for row in patch.get("findings") or []
    ]
    defender_findings = [
        {
            **row,
            "target_resource_id": row.get("target_resource_id")
            or row.get("resource_key")
            or row.get("resource_id")
            or "",
        }
        for row in patch.get("defender_findings") or []
    ]
    defender_assessments = [
        {
            **row,
            "target_resource_id": row.get("target_resource_id")
            or row.get("resource_key")
            or "",
        }
        for row in defender.get("assessments") or []
    ]
    exposure = getattr(runtime.config, "exposure", None)
    use_temporal_projection = bool(
        exposure is not None
        and exposure.enabled
        and not exposure.rollback_mode
    )
    temporal_tables = (
        _fabric_temporal_exposure_tables(runtime)
        if use_temporal_projection
        else {}
    )
    freshness = str(getattr(semantic, "freshness", "") or "")
    if not freshness:
        freshness = max(
            (
                str(
                    row.get("timestamp")
                    or row.get("observed_at")
                    or row.get("last_assessed_at")
                    or row.get("last_observed_at")
                    or row.get("published_at")
                    or ""
                )
                for rows in (
                    findings,
                    defender_findings,
                    defender_assessments,
                    *temporal_tables.values(),
                )
                for row in rows
            ),
            default="",
        )
    return _build_vulnerability_service(
        [
            {
                "silver_patch_findings": findings,
                "silver_defender_findings": defender_findings,
                "silver_defender_assessments": defender_assessments,
                **temporal_tables,
                **{
                    f"silver_defender_{name}": rows
                    for name, rows in defender.items()
                },
            }
        ],
        freshness,
        semantic=semantic,
        network=network,
        use_temporal_projection=use_temporal_projection,
    )


def _fabric_temporal_exposure_tables(
    runtime: FabricRuntime,
) -> dict[str, list[dict[str, Any]]]:
    """Read Plan 08 temporal products without replacing Fabric composition."""

    def read(
        layer: str,
        name: str,
        *,
        columns: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        uri = runtime.service.onelake.table_uri(layer, name)
        if runtime.service.delta.version(uri) is None:
            return []
        return runtime.service.delta.read(uri, columns=columns)

    return {
        "gold_exposure_current": read("gold", "exposure_current"),
        "silver_exposure_observations": read(
            "silver",
            "exposure_observations",
            columns=(
                "observation_id",
                "event_time",
                "ingested_at",
                "run_at",
                "published_at",
                "enriched_at",
            ),
        ),
        "metadata_source_status": read("metadata", "source_status"),
    }


def _fabric_incident_engine(runtime: FabricRuntime) -> IncidentEngine | None:
    agent = runtime.operations_agent()
    intelligence = getattr(agent, "incident_intelligence", None)
    if intelligence is None:
        return None
    return IncidentEngine.from_intelligence(
        intelligence,
        network_provider=lambda: _fabric_network_service(runtime),
        vulnerability_provider=lambda: _fabric_vulnerability_service(runtime),
    )


def _attach_remediation_decisions(planner: Any) -> Any:
    if planner is not None and hasattr(planner, "repository"):
        planner.repository.decisions = _remediation_decision_store()
    return planner


def _merge_trigger_signals(
    planner: Any, correlator: Any, vulnerability_service: Any
) -> None:
    """Flatten Defender/vulnerability signals onto the planner's resources.

    ``RemediationPlanner.from_semantic_engine`` flattens ``resource_signals``
    onto each resource at construction time, but the Defender correlator is
    only attached afterwards -- and correlation itself runs at plan
    *generation* time, which is strictly later than opportunity
    *identification*. Without this merge the ``defender_*`` and
    ``critical_vulnerability_count`` trigger fields are never present on the
    rows that ``RemediationOpportunityEngine.identify`` matches against, so
    the governed catalog actions keyed on them can never fire.

    Read-only and defensive: a partial snapshot (missing Defender tables or
    exposure rows) degrades to leaving the affected signal absent rather
    than failing the planner.
    """
    from intelligence.predictive.predictive_context_builder import (
        PredictiveContextBuilder,
    )

    resources = getattr(planner, "resources", None)
    if not resources:
        return

    signals: dict[str, dict[str, Any]] = {}

    def _slot(raw_key: Any) -> dict[str, Any] | None:
        key = PredictiveContextBuilder.canonical_key(raw_key)
        return signals.setdefault(key, {}) if key else None

    if correlator is not None:
        try:
            posture = correlator.posture_by_resource()
        except Exception:  # noqa: BLE001 - partial snapshot must not break planning
            posture = {}
        for raw_key, row in (posture or {}).items():
            slot = _slot(raw_key)
            if slot is not None:
                slot.update(row)

    if vulnerability_service is not None:
        try:
            exposures = vulnerability_service.asset_exposures()
        except Exception:  # noqa: BLE001 - see above
            exposures = []
        for row in exposures or ():
            slot = _slot(row.get("asset_id"))
            if slot is None:
                continue
            slot["critical_vulnerability_count"] = int(row.get("critical_count") or 0)

    if not signals:
        return

    for resource in resources:
        key = PredictiveContextBuilder.canonical_key(resource.get("resource_key"))
        if key and key in signals:
            resource.update(signals[key])


def _attach_defender_correlator(planner: Any, runtime: FabricRuntime) -> Any:
    """Attach a read-only Defender remediation correlator to ``planner``.

    Reuses the already-resolved vulnerability service and the planner's own
    canonicalized resources/action catalog rather than opening a new
    inventory read path. No-ops defensively when required inputs are
    missing (partial snapshot), leaving the planner unchanged.
    """
    if planner is None or not hasattr(planner, "resources"):
        return planner
    vulnerability_service = _fabric_vulnerability_service(runtime)
    if vulnerability_service is None:
        return planner
    opportunities = getattr(planner, "opportunities", None)
    catalog = getattr(opportunities, "catalog", None)
    if catalog is None:
        return planner
    planner.defender_correlator = DefenderRemediationCorrelator(
        vulnerability_service=vulnerability_service,
        dependency_analyzer=DependencyAnalyzer(),
        resource_lookup=planner.resources,
        action_catalog=catalog,
    )
    _merge_trigger_signals(planner, planner.defender_correlator, vulnerability_service)
    return planner


def _fabric_remediation_planner(runtime: FabricRuntime) -> Any:
    planner = _attach_remediation_decisions(
        getattr(runtime.operations_agent(), "remediation_planner", None)
    )
    if planner is None:
        return None
    catalog = getattr(getattr(planner, "opportunities", None), "catalog", ())
    policies = getattr(
        getattr(getattr(planner, "generator", None), "approvals", None),
        "policies",
        (),
    )
    if not catalog or not policies:
        raise RuntimeError(
            "Governed remediation catalog is empty; deployment must publish "
            "the versioned action catalog and approval policies"
        )
    return _attach_defender_correlator(planner, runtime)


def _fabric_remediation_catalog(runtime: FabricRuntime) -> dict[str, int]:
    """Validate the lightweight governed catalog readiness dependency."""
    snapshot = runtime.service.remediation_planning_snapshot()
    actions = snapshot["action_catalog"]
    policies = snapshot["approval_policies"]
    if not actions or not policies:
        raise RuntimeError(
            "Governed remediation catalog is empty; deployment must publish "
            "the versioned action catalog and approval policies"
        )
    return {
        "action_count": len(actions),
        "policy_count": len(policies),
    }


def _attach_live_defender_correlator(
    planner: Any, vulnerability_service: Any
) -> Any:
    """Attach a read-only Defender remediation correlator to a live planner.

    Mirrors ``_attach_defender_correlator`` for the Fabric-snapshot path, but
    for ``LiveRemediationPlanner`` instances, whose resources/action-catalog
    are derived directly from live asset exposures rather than a persisted
    action catalog. No-ops defensively when the vulnerability service is
    unavailable, leaving the planner unchanged (surfaced by the API as
    "Defender remediation correlation is unavailable" rather than failing).
    """
    if planner is None or vulnerability_service is None:
        return planner
    resources = [
        {
            "resource_key": row.get("asset_id", ""),
            **row,
        }
        for row in vulnerability_service.asset_exposures()
    ]
    # No declarative action catalog is attached here (unlike the Fabric
    # snapshot path, which reads a governed catalog table): the live path has
    # no persisted, human-reviewed catalog to match against yet, so every
    # case honestly reports the "no_safe_action" outcome rather than
    # fabricating a match. Correlation itself (evidence citations, severity,
    # confidence, cost-of-action/inaction) is still fully available.
    planner.defender_correlator = DefenderRemediationCorrelator(
        vulnerability_service=vulnerability_service,
        dependency_analyzer=DependencyAnalyzer(),
        resource_lookup=resources,
    )
    _merge_trigger_signals(planner, planner.defender_correlator, vulnerability_service)
    return planner


def _fabric_change_intelligence(runtime: FabricRuntime) -> Any:
    """Resolve the compliance/change-intelligence engine for this snapshot.

    Compliance must remain available without hydrating every OperationsAgent
    domain into the API process. Build only ChangeIntelligence from its
    governed snapshot and the shared semantic engine; the monolithic agent
    also constructs patch, lifecycle, incident, predictive, and remediation
    state and exceeds the production API's bounded memory envelope.
    """
    from intelligence.change import ChangeIntelligence

    config = getattr(runtime.config, "change_intelligence", None)
    if config is None or not config.enabled:
        return None
    snapshot = runtime.service.change_intelligence_snapshot()
    return ChangeIntelligence.from_semantic_engine(
        runtime.semantic_engine(),
        max_changes=config.max_changes,
        max_output_items=config.max_output_items,
        **snapshot,
    )


def _latest_discovery(onboarding: SubscriptionOnboardingService) -> str:
    timestamps = [
        str(connection.sync_state.last_successful_sync_at or "")
        for connection in onboarding.registry.list()
        if connection.sync_state is not None
    ]
    return max(timestamps, default="")


def _runtime_metadata(
    onboarding: SubscriptionOnboardingService,
    fabric_supplier: Callable[[], FabricRuntime | None],
    *,
    fabric_configured: bool = False,
) -> dict[str, Any]:
    runtime = fabric_supplier()
    last_discovery = _latest_discovery(onboarding)
    if runtime is None:
        if fabric_configured:
            return {
                "ontology_version": "",
                "freshness": "",
                "last_discovery_run": last_discovery,
                "last_ontology_publication": "",
                "degraded_reason": "Fabric runtime is unavailable",
            }
        semantic = _load_semantic_snapshot()
        return {
            "ontology_version": getattr(semantic, "knowledge_version", ""),
            "freshness": getattr(semantic, "freshness", ""),
            "last_discovery_run": last_discovery,
            "last_ontology_publication": getattr(semantic, "freshness", ""),
        }
    health = runtime.service.ontology_health()
    freshness = str(
        health.get("timestamp")
        or health.get("synchronized_at")
        or health.get("published_at")
        or ""
    )
    return {
        "ontology_version": str(runtime.service.semantic_version() or ""),
        "freshness": freshness,
        "last_discovery_run": last_discovery,
        "last_ontology_publication": freshness,
    }


def _build_provider_runtime(
    onboarding: SubscriptionOnboardingService,
) -> ProviderRuntime:
    mode = (os.environ.get(ENV_RUNTIME_MODE) or "production").strip().casefold()
    if mode not in {"production", "demo"}:
        raise RuntimeError(f"{ENV_RUNTIME_MODE} must be 'production' or 'demo'")
    use_fabric = _fabric_is_configured()
    if mode == "production" and not use_fabric:
        _LOGGER.error(
            "Production runtime has no Fabric configuration; readiness will remain degraded"
        )

    holder: dict[str, FabricRuntime | None] = {}

    def fabric() -> FabricRuntime | None:
        if "runtime" not in holder:
            try:
                holder["runtime"] = _fabric_runtime_from_environment()
            except Exception:
                # Do not cache a permanent failure: a transient auth/network
                # error building the Fabric client would otherwise poison
                # every fabric-backed provider for the lifetime of the
                # process, since this holder is only ever populated once.
                _LOGGER.exception(
                    "fabric_runtime_build_failed; will retry on next refresh"
                )
                return None
            if holder["runtime"] is None:
                _LOGGER.warning(
                    "fabric_runtime_not_configured; _fabric_is_configured() "
                    "returned False or no config path was set"
                )
        return holder["runtime"]

    def with_fabric(loader: Callable[[FabricRuntime], Any]) -> Any:
        runtime = fabric()
        if runtime is None:
            return None
        ontology_version = runtime.service.semantic_version()
        if ontology_version == "semantic-unversioned":
            if _truthy("AIOPS_ALLOW_EMPTY_FABRIC_SNAPSHOT"):
                # A newly created validation lakehouse is intentionally empty
                # until the first activation sync completes.
                return None
            raise RuntimeError(
                "Fabric semantic snapshot has no version; publish the ontology "
                "and ingestion state before activating providers"
            )
        try:
            instance = loader(runtime)
        except Exception:
            _LOGGER.exception("with_fabric_loader_failed loader=%r", loader)
            raise
        return ProviderValue(
            instance,
            ontology_version=ontology_version,
        )

    def fabric_provider_cache_key(name: str) -> tuple[object, ...]:
        runtime = fabric()
        if runtime is None:
            raise RuntimeError("Fabric runtime is unavailable")
        generation_key: tuple[object, ...] = (
            "fabric-generation",
            runtime.service.semantic_version(),
        )
        if name == "network":
            return (
                *generation_key,
                "network-policy",
                _network_policy_store().revision_or_raise(),
            )
        return generation_key

    if use_fabric:
        loaders: dict[str, Callable[[], Any]] = {
            "semantic": lambda: with_fabric(lambda item: item.semantic_engine()),
            "semantic_graph": lambda: with_fabric(
                lambda item: item.semantic_graph_engine()
            ),
            "network": lambda: with_fabric(_fabric_network_service),
            "vulnerability": lambda: with_fabric(_fabric_vulnerability_service),
            "exposure_query": lambda: _fabric_exposure_query_from_config(
                onboarding,
                fabric,
            ),
            "incidents": lambda: with_fabric(_fabric_incident_engine),
            "remediation_catalog": lambda: with_fabric(
                _fabric_remediation_catalog
            ),
            "remediation": lambda: with_fabric(_fabric_remediation_planner),
            "change": lambda: with_fabric(_fabric_change_intelligence),
        }
    elif mode == "demo":
        loaders = {
            "semantic": _load_semantic_snapshot,
            "network": _load_network_service,
            "vulnerability": _load_vulnerability_service,
            "incidents": _load_incident_engine,
            "remediation": lambda: None,
            "change": lambda: None,
        }
    else:
        loaders = {name: (lambda: None) for name in (
            "semantic",
            "network",
            "vulnerability",
            "exposure_query",
            "incidents",
            "remediation",
            "change",
        )}

    foundry_configured = bool(
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        and (
            os.environ.get("FOUNDRY_NETWORK_AGENT_NAME", "").strip()
            or os.environ.get("FOUNDRY_AGENT_NAME", "").strip()
        )
    )
    orchestration_mode = os.environ.get(
        ENV_AGENT_ORCHESTRATION_MODE,
        "",
    ).strip().casefold()
    coordinator_required = orchestration_mode in {MODE_MAF, MODE_CANONICAL}
    bootstrap = _truthy("AIOPS_ALLOW_EMPTY_FABRIC_SNAPSHOT")
    # External intelligence providers must never make the API process
    # unroutable. Their routes fail closed with provider_unavailable and their
    # state remains visible in /health; /ready only proves the process can
    # safely answer requests.
    deferred_providers = {
        "incidents",
        "network",
        "remediation",
        "remediation_catalog",
        "semantic",
        "semantic_graph",
    }
    remediation_enabled = _fabric_remediation_enabled() if use_fabric else False
    exposure_query_enabled = (
        _fabric_exposure_query_enabled() if use_fabric else False
    )
    # Fabric-backed reads are independently guarded at their route boundary.
    # A transient Fabric capacity or OneLake outage must keep the affected
    # provider visibly unavailable without making the API process itself
    # unroutable.
    core_readiness_providers: set[str] = set()
    specs = {
        name: ProviderSpec(
            loader=loader,
            configured=not (
                name in {"remediation", "remediation_catalog"}
                and use_fabric
                and not remediation_enabled
            )
            and not (
                name == "exposure_query"
                and use_fabric
                and not exposure_query_enabled
            ),
            required=name in core_readiness_providers and not bootstrap,
            cache_key=(
                (lambda provider_name=name: fabric_provider_cache_key(provider_name))
                if use_fabric and name != "exposure_query"
                else None
            ),
            scheduled=not (use_fabric and name in deferred_providers),
        )
        for name, loader in loaders.items()
    }
    specs["copilot"] = ProviderSpec(
        loader=_load_foundry_agent,
        configured=foundry_configured or coordinator_required,
        required=coordinator_required,
    )
    authorization_required = canary_authorization_required()
    specs["copilot_canary_authorization"] = ProviderSpec(
        loader=require_canary_authorization_if_requested,
        configured=authorization_required,
        required=authorization_required,
    )
    for specialist_id in SPECIALIST_IDS:
        specialist_configured = bool(
            os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
            and (
                os.environ.get(
                    f"FOUNDRY_{specialist_id.upper()}_AGENT_NAME", ""
                ).strip()
                or os.environ.get("FOUNDRY_AGENT_NAME", "").strip()
            )
        )
        specs[f"{specialist_id}_agent"] = ProviderSpec(
            loader=lambda agent_id=specialist_id: _load_foundry_specialist_agent(
                agent_id
            ),
            configured=specialist_configured,
            required=False,
        )
    specs["fabric_iq"] = ProviderSpec(
        loader=_load_fabric_iq_adapter,
        configured=_fabric_is_configured(),
        required=False,
    )
    # Inventory is optional for readiness but never synthesized as an empty
    # estate. The service reads only the active immutable generation.
    specs["inventory"] = ProviderSpec(
        loader=_load_inventory_service,
        configured=True,
        required=False,
        cache_key=(
            (lambda: fabric_provider_cache_key("inventory"))
            if use_fabric
            else None
        ),
    )
    provider_holder: dict[str, ProviderRuntime] = {}

    def load_inventory_read_port() -> Any:
        provider_runtime = provider_holder.get("runtime")
        if provider_runtime is None:
            return None
        return _load_inventory_read_port(
            provider_runtime.get("inventory", optional=True)
        )

    specs["inventory_read_port"] = ProviderSpec(
        loader=load_inventory_read_port,
        configured=True,
        required=False,
    )
    specs["exposure_read_port"] = ProviderSpec(
        loader=_load_exposure_read_port,
        configured=True,
        required=False,
    )
    # FinOps/identity/SPN governance is a projection of the same ontology
    # snapshot as the other providers above, always configured (it reads
    # from whatever has synced) but never required for overall readiness:
    # a deployment with no identity data synced yet must not be reported
    # as degraded on /health, since the governance routes already surface
    # their own honest "unavailable, not yet synced" state per-request.
    specs["governance"] = ProviderSpec(
        loader=_load_governance_snapshot,
        configured=True,
        required=False,
        scheduled=not use_fabric,
    )
    # Patch remediation projects the same vulnerability snapshot into
    # patchable inventory and owns the guarded trigger path. It is never
    # required for readiness: a deployment with no execution adapter still
    # serves the inventory read and reports the missing capability per-request.
    _vulnerability_loader = loaders.get("vulnerability")
    if _vulnerability_loader is not None:
        specs["patching"] = ProviderSpec(
            loader=lambda: _load_patching_service(_vulnerability_loader),
            configured=True,
            required=False,
            scheduled=not use_fabric,
        )
    provider_runtime = ProviderRuntime(
        specs,
        metadata_loader=lambda: _runtime_metadata(
            onboarding,
            fabric,
            fabric_configured=use_fabric,
        ),
        refresh_interval_seconds=int(
            os.environ.get(ENV_PROVIDER_REFRESH_SECONDS, "30")
        ),
        stale_after_hours=int(os.environ.get(ENV_PROVIDER_STALE_HOURS, "24")),
    )
    provider_holder["runtime"] = provider_runtime
    return provider_runtime


# Patch runs are operator-submitted mutations, not snapshot projections, so
# they use a process-level store handle like risk exceptions. The store is
# shared across provider rebuilds so a rebuild never loses run history.
_patch_run_store = InMemoryPatchRunStore()
class _ConnectionCredentialRouter:
    """Resolve a fresh selected-connection SPN for one subscription operation."""

    def __init__(
        self,
        onboarding: SubscriptionOnboardingService,
        scope: Scope | None = None,
    ) -> None:
        self._onboarding = onboarding
        self._allowed_subscriptions = {
            value.casefold() for value in (scope.values("subscription") if scope else ())
        }
        self._allowed_connections = {
            value.casefold()
            for value in (scope.values("subscription_connection") if scope else ())
        }

    def credential(
        self,
        subscription_id: str,
        *,
        connection_id: str = "",
    ) -> Any:
        subscription = str(subscription_id or "").strip()
        selected_connection = str(connection_id or "").strip()
        if not subscription:
            raise RuntimeError("Azure subscription scope is required")
        if (
            self._allowed_subscriptions
            and subscription.casefold() not in self._allowed_subscriptions
        ):
            raise RuntimeError("Azure subscription is outside the authorized scope")
        candidates = [
            connection
            for connection in self._onboarding.registry.list(include_disabled=False)
            if str(connection.subscription_id).casefold() == subscription.casefold()
            and (
                not selected_connection
                or str(connection.connection_id).casefold()
                == selected_connection.casefold()
            )
            and (
                not self._allowed_connections
                or str(connection.connection_id).casefold()
                in self._allowed_connections
            )
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                "Exactly one active subscription connection must match the Azure operation"
            )
        return build_connection_credential(candidates[0], self._onboarding.resolver)


class _ConnectionScopedPatchExecutionAdapter:
    name = "azure-arm"

    def __init__(self, router: _ConnectionCredentialRouter) -> None:
        self._router = router

    def submit(self, run: Any, target: Any) -> Any:
        try:
            subscription_id = str(
                getattr(target, "subscription_id", "") or ""
            ) or _subscription_id_from_resource_id(
                str(getattr(target, "target_id", "") or "")
            )
            credential = self._router.credential(
                subscription_id,
                connection_id=str(
                    getattr(target, "subscription_connection", "") or ""
                ),
            )
        except Exception as exc:
            raise PatchExecutionUnavailable(
                f"Could not resolve the target subscription connection: {exc}",
                provider_submitted=False,
                failure_class="provider_authorization",
            ) from exc
        from operations.patching.azure_adapter import AzureArmPatchExecutionAdapter

        return AzureArmPatchExecutionAdapter(credential).submit(run, target)


class _ConnectionScopedDefenderConfigurationAdapter:
    name = "azure-arm-defender-configuration"

    def __init__(self, router: _ConnectionCredentialRouter) -> None:
        self._router = router

    def inspect(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._adapter_for_target(str(request.get("path") or "")).inspect(request)

    def submit(self, snapshot: dict[str, Any]) -> Any:
        return self._adapter_for_target(str(snapshot.get("target_id") or "")).submit(
            snapshot
        )

    def _adapter_for_target(
        self, target_id: str
    ) -> AzureArmDefenderConfigurationAdapter:
        try:
            credential = self._router.credential(
                _subscription_id_from_resource_id(target_id)
            )
        except Exception as exc:
            raise DefenderConfigurationUnavailable(
                f"Could not resolve the target subscription connection: {exc}",
                reason="azure_arm_token_unavailable",
                provider_submitted=False,
                failure_class="provider_authorization",
            ) from exc
        return AzureArmDefenderConfigurationAdapter(credential)


class _ConnectionScopedExecutionVerifier:
    def __init__(self, router: _ConnectionCredentialRouter) -> None:
        self._router = router

    def verify(self, execution_record: dict[str, Any]) -> dict[str, Any]:
        attributes = execution_scope_attributes(execution_record)
        try:
            credential = self._router.credential(
                attributes.get("subscription", ""),
                connection_id=attributes.get("subscription_connection", ""),
            )
        except Exception as exc:
            raise ExecutionVerificationUnavailable(
                f"Could not resolve the execution's subscription connection: {exc}",
                capability="azure_arm_token",
            ) from exc
        return ExecutionVerifier(credential=credential).verify(execution_record)


class _RoutingExecutionVerifier:
    """Route persisted provider handles to their matching verifier."""

    def __init__(self, *, arm: Any | None, sre_agent: Any | None) -> None:
        self._arm = arm
        self._sre_agent = sre_agent

    def verify(self, execution_record: dict[str, Any]) -> dict[str, Any]:
        provider = str(execution_record.get("provider") or "").strip()
        if provider == "sre-agent":
            if self._sre_agent is None:
                raise ExecutionVerificationUnavailable(
                    "Azure SRE Agent verification is not configured.",
                    capability="sre_agent_verification",
                )
            return self._sre_agent.verify(execution_record)
        if self._arm is None:
            raise ExecutionVerificationUnavailable(
                "Azure ARM verification is not configured.",
                capability="execution_verification",
            )
        return self._arm.verify(execution_record)

    def cancel(
        self,
        execution_record: dict[str, Any],
        *,
        requested_by: str = "",
    ) -> dict[str, Any]:
        """Cancel only provider-owned SRE approvals; ARM writes stay immutable."""
        provider = str(execution_record.get("provider") or "").strip()
        if provider != "sre-agent" or self._sre_agent is None:
            raise ExecutionVerificationUnavailable(
                "This provider does not expose safe remediation cancellation.",
                capability="provider_cancellation",
            )
        return self._sre_agent.cancel(
            execution_record,
            requested_by=requested_by,
        )

    def approve_review(
        self,
        execution_record: dict[str, Any],
        *,
        requested_by: str,
    ) -> dict[str, Any]:
        """Approve only an exact typed SRE CLI Review action."""
        provider = str(execution_record.get("provider") or "").strip()
        if provider != "sre-agent" or self._sre_agent is None:
            raise ExecutionVerificationUnavailable(
                "This provider does not expose an approvable CLI review.",
                capability="sre_agent_review_approve",
            )
        return self._sre_agent.approve_review(
            execution_record,
            requested_by=requested_by,
        )

    def read_approvals(self, execution_record: dict[str, Any]) -> list[object]:
        """Read approval history only through the persisted SRE provider."""
        provider = str(execution_record.get("provider") or "").strip()
        if provider != "sre-agent" or self._sre_agent is None:
            raise ExecutionVerificationUnavailable(
                "This provider does not expose SRE approval history.",
                capability="sre_agent_approval_read",
            )
        return self._sre_agent.read_approvals(execution_record)


def _subscription_id_from_resource_id(resource_id: str) -> str:
    parts = [part for part in str(resource_id or "").strip("/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "subscriptions":
            return parts[index + 1]
    return ""


def _sre_agent_settings() -> dict[str, str]:
    """Load and validate the explicit SRE Agent execution configuration."""
    from operations.patching.sre_agent_adapter import (
        SRE_AGENT_THREAD_SCOPE,
        SRE_AGENT_TRIGGER_SCOPE,
        validate_sre_agent_endpoint,
    )

    settings = {
        "agent_endpoint": os.environ.get(ENV_SRE_AGENT_ENDPOINT, "").strip(),
        "trigger_url": os.environ.get(ENV_SRE_AGENT_TRIGGER_URL, "").strip(),
        "trigger_id": os.environ.get(ENV_SRE_AGENT_TRIGGER_ID, ""),
        "trigger_origin": os.environ.get(
            ENV_SRE_AGENT_TRIGGER_ORIGIN, ""
        ).strip(),
        "trigger_scope": (
            os.environ.get(ENV_SRE_AGENT_TRIGGER_SCOPE, "").strip()
            or SRE_AGENT_TRIGGER_SCOPE
        ),
        "thread_scope": (
            os.environ.get(ENV_SRE_AGENT_THREAD_SCOPE, "").strip()
            or SRE_AGENT_THREAD_SCOPE
        ),
        "subscription_id": os.environ.get(
            ENV_SRE_AGENT_SUBSCRIPTION_ID, ""
        ).strip(),
        "target_prefix": os.environ.get(ENV_SRE_AGENT_TARGET_PREFIX, "").strip(),
        "client_id": os.environ.get("AZURE_CLIENT_ID", "").strip(),
    }
    required = {
        name
        for name in (
            "agent_endpoint",
            "trigger_url",
            "trigger_id",
            "trigger_origin",
            "subscription_id",
            "target_prefix",
            "client_id",
        )
        if not settings[name]
    }
    if required:
        names = ", ".join(sorted(required))
        raise RuntimeError(
            f"AIOPS_PATCH_EXECUTION=sre-agent requires configured values for: {names}"
        )
    if not settings["trigger_scope"].endswith("/.default"):
        raise RuntimeError("The SRE Agent trigger scope must end with '/.default'.")
    if not settings["thread_scope"].endswith("/.default"):
        raise RuntimeError("The SRE Agent thread scope must end with '/.default'.")
    settings["agent_endpoint"] = validate_sre_agent_endpoint(
        settings["agent_endpoint"]
    )
    return settings


def _sre_agent_verification_settings() -> dict[str, str] | None:
    """Load read-only SRE settings independently of the active write mode."""
    endpoint = os.environ.get(ENV_SRE_AGENT_ENDPOINT, "").strip()
    if not endpoint:
        return None
    from operations.patching.sre_agent_adapter import (
        SRE_AGENT_THREAD_SCOPE,
        validate_sre_agent_endpoint,
    )

    client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
    thread_scope = (
        os.environ.get(ENV_SRE_AGENT_THREAD_SCOPE, "").strip()
        or SRE_AGENT_THREAD_SCOPE
    )
    if not client_id:
        raise RuntimeError(
            f"{ENV_SRE_AGENT_ENDPOINT} requires AZURE_CLIENT_ID for thread polling."
        )
    if not thread_scope.endswith("/.default"):
        raise RuntimeError("The SRE Agent thread scope must end with '/.default'.")
    return {
        "agent_endpoint": validate_sre_agent_endpoint(endpoint),
        "thread_scope": thread_scope,
        "client_id": client_id,
    }


def _sre_agent_managed_identity_credential(client_id: str) -> Any:
    """Build the API workload's user-assigned managed identity credential."""
    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential(client_id=client_id)


def _patch_execution_adapter(
    onboarding: SubscriptionOnboardingService,
    scope: Scope | None = None,
) -> Any:
    """Resolve the configured execution backend.

    Defaults to the refusing adapter: triggering real Azure writes must be an
    explicit deployment decision, never an accident of configuration. Setting
    ``AIOPS_PATCH_EXECUTION=azure`` opts a deployment in to live ARM calls.
    ``AIOPS_PATCH_EXECUTION=sre-agent`` separately opts in to the pre-created
    SRE HTTP-trigger path and requires its complete fail-closed configuration.
    """
    mode = (os.environ.get(ENV_PATCH_EXECUTION) or "").strip().casefold()
    if mode == "sre-agent":
        from operations.patching.sre_agent_adapter import (
            SreAgentPatchExecutionAdapter,
        )

        settings = _sre_agent_settings()
        return SreAgentPatchExecutionAdapter(
            _sre_agent_managed_identity_credential(settings["client_id"]),
            trigger_url=settings["trigger_url"],
            trigger_id=settings["trigger_id"],
            trigger_origin=settings["trigger_origin"],
            agent_endpoint=settings["agent_endpoint"],
            trigger_scope=settings["trigger_scope"],
            subscription_id=settings["subscription_id"],
            target_prefix=settings["target_prefix"],
        )
    if mode not in {"azure", "arm", "azure-arm"}:
        return UnconfiguredPatchExecutionAdapter()
    return _ConnectionScopedPatchExecutionAdapter(
        _ConnectionCredentialRouter(onboarding, scope)
    )


def _defender_configuration_adapter(
    onboarding: SubscriptionOnboardingService,
    scope: Scope | None = None,
) -> Any:
    """Resolve the opt-in Defender adapter through the selected connection."""
    mode = (
        os.environ.get(ENV_DEFENDER_CONFIGURATION_EXECUTION) or ""
    ).strip().casefold()
    if mode not in {"azure", "arm", "azure-arm"}:
        return UnconfiguredDefenderConfigurationAdapter()
    return _ConnectionScopedDefenderConfigurationAdapter(
        _ConnectionCredentialRouter(onboarding, scope)
    )


def _execution_verifier(
    onboarding: SubscriptionOnboardingService,
    scope: Scope | None = None,
) -> Any | None:
    """Build lazy ARM routing plus SRE routing when its read config exists."""
    arm_verifier = _ConnectionScopedExecutionVerifier(
        _ConnectionCredentialRouter(onboarding, scope)
    )
    sre_verifier = None
    sre_settings = _sre_agent_verification_settings()
    if sre_settings is not None:
        from intelligence.remediation.sre_agent_verifier import (
            SreAgentExecutionVerifier,
        )

        sre_verifier = SreAgentExecutionVerifier(
            credential=_sre_agent_managed_identity_credential(
                sre_settings["client_id"]
            ),
            agent_endpoint=sre_settings["agent_endpoint"],
            thread_scope=sre_settings["thread_scope"],
        )
    return _RoutingExecutionVerifier(
        arm=arm_verifier,
        sre_agent=sre_verifier,
    )


def _load_patching_service(vulnerability_loader: Callable[[], Any]) -> Any | None:
    """Project the current vulnerability snapshot into patchable inventory."""
    raw = vulnerability_loader()
    service = raw.instance if isinstance(raw, ProviderValue) else raw
    if service is None:
        return None
    return PatchingService(
        service,
        store=_patch_run_store,
        adapter=_patch_execution_adapter(_onboarding_service()),
        require_human_approval=_require_human_approval,
        allow_self_approval=_allow_self_approval,
    )


def _load_governance_snapshot() -> GovernanceSnapshot | None:
    """Build the scoped governance view from synced ontology rows.

    Returns None when nothing has been synced, so the governance routes report
    the capability as unavailable rather than returning empty results a UI
    would render as "no cost waste and no privileged access".
    """
    cache_key = (str(aiops_home()), ("legacy",))

    def build() -> GovernanceSnapshot | None:
        entities, _relationships, freshness = _load_ontology_rows()
        if not entities:
            return None
        return GovernanceSnapshot(
            entities,
            observed_at=freshness,
            connections=_governance_connections(),
        )

    return _ttl_cached_value(
        _governance_snapshot_cache,
        cache_key,
        ttl_seconds=_SNAPSHOT_TABLES_CACHE_TTL_SECONDS,
        now=time.time(),
        build=build,
        completion_clock=time.time,
    )


def _governance_connections() -> list[dict[str, Any]]:
    """Connection registry rows for SPN governance.

    Reads the registry directly rather than resolving credentials: governance
    reports on credential *metadata* (owner, scope, expiry, use) and must never
    need the secret itself, so a Key Vault outage cannot break this view.
    """
    try:
        connections = ConnectionRegistry(_governance_connection_home()).list(
            include_disabled=True
        )
    except Exception:
        _LOGGER.exception("governance_connection_load_failed")
        return []
    return [
        connection.to_dict() if hasattr(connection, "to_dict") else dict(connection)
        for connection in connections
    ]


def _require_human_approval() -> bool:
    """Read ``agent_policy.require_human_approval`` at the moment of use.

    Fails closed: if the settings document is unreadable we require approval
    rather than silently allowing an unapproved change to a customer host.
    """
    try:
        settings = _settings_store().read()
    except Exception:
        _LOGGER.warning("could not read enterprise settings; requiring approval", exc_info=True)
        return True
    agent_policy = settings.get("agent_policy")
    if not isinstance(agent_policy, Mapping):
        return True
    return bool(agent_policy.get("require_human_approval", True))


def _allow_self_approval() -> bool:
    """Read ``agent_policy.allow_self_approval`` at the moment of use.

    Fails closed: if the settings document is unreadable or the flag is
    absent, separation of duties stays enforced (approver != requester).
    This exists only for single-operator/demo environments that lack a
    second approver identity; production deployments should leave it off.
    """
    try:
        settings = _settings_store().read()
    except Exception:
        _LOGGER.warning(
            "could not read enterprise settings; not allowing self-approval", exc_info=True
        )
        return False
    agent_policy = settings.get("agent_policy")
    if not isinstance(agent_policy, Mapping):
        return False
    return bool(agent_policy.get("allow_self_approval", False))


def _settings_store() -> EnterpriseSettingsStore:
    """Settings persisted to OneLake when available, in memory otherwise."""
    root = aiops_home()
    documents = OneLakeDocumentStore(str(root)) if is_onelake_uri(root) else None
    return EnterpriseSettingsStore(documents)


#: Module-level so every provider closure that builds a NetworkIntelligenceService
#: (local, fabric, hybrid) shares one store and observes the same edits.
_NETWORK_POLICY_STORE: NetworkDesignPolicyStore | None = None


def _network_policy_store() -> NetworkDesignPolicyStore:
    global _NETWORK_POLICY_STORE
    if _NETWORK_POLICY_STORE is None:
        root = aiops_home()
        documents = OneLakeDocumentStore(str(root)) if is_onelake_uri(root) else None
        _NETWORK_POLICY_STORE = NetworkDesignPolicyStore(documents)
    return _NETWORK_POLICY_STORE


_REMEDIATION_DECISION_STORE: RemediationDecisionStore | None = None


def _remediation_decision_store() -> RemediationDecisionStore:
    global _REMEDIATION_DECISION_STORE
    if _REMEDIATION_DECISION_STORE is None:
        root = aiops_home()
        documents = OneLakeDocumentStore(str(root)) if is_onelake_uri(root) else None
        path = (
            None
            if documents is not None
            else Path(str(root)) / "state" / "remediation_decisions.json"
        )
        _REMEDIATION_DECISION_STORE = RemediationDecisionStore(
            path=path,
            document_store=documents,
        )
    return _REMEDIATION_DECISION_STORE


_REMEDIATION_EXECUTION_STORE: RemediationExecutionStore | None = None


def _remediation_execution_store() -> RemediationExecutionStore:
    global _REMEDIATION_EXECUTION_STORE
    if _REMEDIATION_EXECUTION_STORE is None:
        root = aiops_home()
        documents = OneLakeDocumentStore(str(root)) if is_onelake_uri(root) else None
        path = (
            None
            if documents is not None
            else Path(str(root)) / "state" / "remediation_executions.json"
        )
        _REMEDIATION_EXECUTION_STORE = RemediationExecutionStore(
            path=path,
            document_store=documents,
        )
    return _REMEDIATION_EXECUTION_STORE


def _load_situation_provider() -> Any:
    """Read the durable Phase 1 projection from the active generation."""
    from situations.store import SituationReadProvider
    from storage.datasets import DatasetStore

    return SituationReadProvider(DatasetStore(aiops_home()))


def _load_inventory_service() -> Any:
    """Load inventory from the compatibility snapshot or Fabric tables."""
    from intelligence.inventory.mapping_repository import SoftwareMappingRepository
    from intelligence.inventory.service import InventoryService, InventorySnapshot
    from storage.datasets import DatasetStore

    eol_review = _load_eol_review_service()
    root = aiops_home()
    mapping_repository = SoftwareMappingRepository(
        document_store=OneLakeDocumentStore(str(root)),
        document_name="state/software_mappings.json",
    )
    fixture = os.environ.get("AIOPS_INVENTORY_FIXTURE", "").strip()
    if fixture:
        return InventoryService.from_fixture(
            fixture,
            eol_review=eol_review,
            mapping_repository=mapping_repository,
        )
    service = InventoryService.from_store(
        DatasetStore(root),
        eol_review=eol_review,
        mapping_repository=mapping_repository,
    )
    if service is not None:
        return service

    # Production refreshes publish governed inventory tables to OneLake while
    # the compatibility generation may live on a different local filesystem.
    # Read those tables directly so the API does not report an empty provider.
    if os.environ.get("AIOPS_ENABLE_FABRIC", "").strip().casefold() != "true":
        return None
    workspace_id = os.environ.get("FABRIC_WORKSPACE_ID", "").strip()
    lakehouse_id = os.environ.get("FABRIC_LAKEHOUSE_ID", "").strip()
    if not workspace_id or not lakehouse_id:
        return None
    from fabric.auth import (
        FabricAuthConfig,
        build_credential,
        build_delta_storage_options,
    )
    from storage.delta_writer import DeltaWriter
    from storage.onelake_writer import OneLakeWriter

    credential = build_credential(
        FabricAuthConfig(
            mode="managed_identity",
            managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID", "").strip(),
        )
    )
    storage_options = build_delta_storage_options(credential)
    onelake = OneLakeWriter(
        workspace_id,
        lakehouse_id,
        credential=credential,
        storage_options=storage_options,
    )
    delta = DeltaWriter(storage_options=storage_options)
    datasets = {
        name: delta.read(onelake.table_uri("inventory", table))
        for name, table in {
            "inventory/os_observations": "os_observations",
            "inventory/source_status": "source_status",
            "inventory/software_observations": "software_observations",
            "inventory/software_source_status": "software_source_status",
            "inventory/resource_observations": "resource_observations",
        }.items()
    }
    if not any(datasets.values()):
        return None
    return InventoryService(
        InventorySnapshot.from_payload(
            {
                "observations": datasets["inventory/os_observations"],
                "source_status": datasets["inventory/source_status"],
                "software_observations": datasets["inventory/software_observations"],
                "software_source_status": datasets["inventory/software_source_status"],
                "resource_observations": datasets["inventory/resource_observations"],
                "query_version": "fabric-inventory-v1",
            }
        ),
        eol_review=eol_review,
        mapping_repository=mapping_repository,
    )


def _load_inventory_read_port(service: Any) -> Any:
    """Build the internal identity contract over the active inventory."""
    from intelligence.inventory.read_port import InventoryReadPort

    return InventoryReadPort(service) if service is not None else None


def _load_exposure_read_port() -> ExposureReadPort | None:
    """Load the authoritative Exposure port only after a generation exists."""
    from storage.datasets import DatasetStore

    store = DatasetStore(aiops_home())
    if not store.read_dataset(EXPOSURE_METADATA_DATASET):
        return None
    return ExposureReadPort(store)


def _exposure_query_authorization(
    onboarding: SubscriptionOnboardingService,
    principal: Any,
    scope: Scope,
) -> Any:
    """Derive the Plan 13 SQL boundary from trusted connection metadata."""

    from .exposure_query import ExposureAuthorization

    requested_subscriptions = {
        str(value).casefold() for value in scope.values("subscription")
    }
    requested_connections = {
        str(value).casefold()
        for value in scope.values("subscription_connection")
    }
    connections = [
        connection
        for connection in onboarding.registry.list(include_disabled=False)
        if (
            not requested_subscriptions
            or str(connection.subscription_id).casefold()
            in requested_subscriptions
        )
        and (
            not requested_connections
            or str(connection.connection_id).casefold()
            in requested_connections
        )
    ]
    if not connections:
        raise PermissionError(
            "Exposure authorization has no active in-scope connection"
        )
    tenant_ids = {
        str(connection.tenant_id).strip().casefold()
        for connection in connections
        if str(connection.tenant_id).strip()
    }
    if len(tenant_ids) != 1:
        raise PermissionError(
            "Exposure query requires one unambiguous tenant boundary"
        )
    return ExposureAuthorization(
        subject=str(getattr(principal, "subject", "") or ""),
        tenant_id=next(iter(tenant_ids)),
        connection_ids=tuple(
            str(connection.connection_id) for connection in connections
        ),
        connection_subscriptions={
            str(connection.connection_id): str(connection.subscription_id)
            for connection in connections
        },
        scope=scope.to_dict(),
    )


def _exposure_generation_window() -> Any:
    """Load the current/retained Gold pointer without exposing storage errors."""

    from api.exposure_query import (
        ExposureGenerationWindow,
        ExposureQueryUnavailableError,
    )
    from fabric_pipelines.vulnerability_pipeline import (
        EXPOSURE_GOLD_POINTER_DOCUMENT,
    )

    pointer = OneLakeDocumentStore(str(aiops_home())).read(
        EXPOSURE_GOLD_POINTER_DOCUMENT
    )
    active = str(pointer.get("readable_generation_id") or "").strip()
    retained_payload = pointer.get("retained_generations")
    retained: dict[str, datetime | None] = {}
    if isinstance(retained_payload, Mapping):
        for generation_id, metadata in retained_payload.items():
            if not isinstance(metadata, Mapping):
                continue
            retain_until = str(metadata.get("retain_until") or "").strip()
            try:
                retained[str(generation_id)] = (
                    datetime.fromisoformat(retain_until)
                    if retain_until
                    else None
                )
            except ValueError:
                continue
    if not active:
        read_port = _load_exposure_read_port()
        metadata_rows = (
            read_port.store.read_dataset(EXPOSURE_METADATA_DATASET)
            if read_port is not None
            else []
        )
        active_generations = {
            str(row.get("read_model_generation_id") or "").strip()
            for row in metadata_rows
            if row.get("read_model_generation_id")
        }
        if len(active_generations) == 1:
            active = next(iter(active_generations))
    if not active:
        raise ExposureQueryUnavailableError(
            "Exposure readable generation is unavailable"
        )
    return ExposureGenerationWindow(
        active_generation=active,
        retained_generations=retained,
    )


def _fabric_exposure_query_service(
    runtime: FabricRuntime,
    onboarding: SubscriptionOnboardingService,
) -> Any:
    """Compose the production Plan 13 service without a Delta fallback."""

    return _exposure_query_service_from_reader(
        runtime.service.sql_reader,
        onboarding,
    )


def _fabric_exposure_query_from_config(
    onboarding: SubscriptionOnboardingService,
    fabric_supplier: Callable[[], FabricRuntime | None],
) -> Any:
    """Build Exposure SQL directly when deployment config names its endpoint."""

    config_path = os.environ.get(ENV_FABRIC_CONFIG, "").strip()
    if config_path:
        config = FabricRuntimeConfig.load(config_path)
        endpoint = config.sql_endpoint
        if (
            config.exposure.enabled
            and not config.exposure.rollback_mode
            and endpoint.server
            and endpoint.database
        ):
            reader = require_exposure_ready(
                {
                    "server": endpoint.server,
                    "database": endpoint.database,
                    "schema": endpoint.schema,
                },
                build_credential(config.auth),
                endpoint_source="deployment_config",
            )
            return _exposure_query_service_from_reader(reader, onboarding)
    runtime = fabric_supplier()
    if runtime is None:
        raise RuntimeError("Fabric runtime is unavailable")
    return _fabric_exposure_query_service(runtime, onboarding)


def _exposure_query_service_from_reader(
    reader: Any,
    onboarding: SubscriptionOnboardingService,
) -> Any:
    if reader is None:
        raise RuntimeError("Fabric SQL Exposure reader is unavailable")
    if not reader.query("SELECT 1 AS probe", max_rows=1):
        raise RuntimeError("Fabric SQL Exposure connectivity probe returned no rows")

    from .exposure_query import (
        ExposureCursorCodec,
        ExposureCursorKeyRing,
        ExposureQueryService,
    )

    return ExposureQueryService(
        reader,
        cursor_codec=ExposureCursorCodec(
            ExposureCursorKeyRing.from_environment()
        ),
        generation_window=_exposure_generation_window,
        authorization_resolver=lambda principal, scope: (
            _exposure_query_authorization(
                onboarding,
                principal,
                scope,
            )
        ),
        catalog_records_resolver=_durable_catalog_records,
    )


def _load_eol_review_service() -> Any:
    """Build the request-time catalog/review provider from server-owned state."""
    from intelligence.inventory.eol_repository import LocalEOLCatalogRepository
    from intelligence.inventory.eol_review import (
        ApprovedSearchApiLifecycleProvider,
        CandidateResolver,
        EOLReviewService,
        UnavailableLifecycleSearchProvider,
    )

    root = aiops_home()
    document_store = OneLakeDocumentStore(str(root))
    endpoint = os.environ.get(ENV_APPROVED_SEARCH_API_ENDPOINT, "").strip()
    credential = os.environ.get(ENV_APPROVED_SEARCH_API_KEY, "").strip()
    if endpoint:
        try:
            search_provider = ApprovedSearchApiLifecycleProvider(
                endpoint, credential=credential
            )
        except ValueError:
            _LOGGER.warning("approved_lifecycle_provider_invalid_endpoint")
            search_provider = UnavailableLifecycleSearchProvider()
    else:
        # FOUNDRY_PROJECT_ENDPOINT is intentionally not treated as a web
        # search provider: the existing Foundry client is narration-only.
        # External search remains disabled until an approved search contract
        # is explicitly configured.
        if os.environ.get(ENV_FOUNDRY_PROJECT_ENDPOINT, "").strip():
            _LOGGER.info("foundry_lifecycle_search_not_configured")
        search_provider = UnavailableLifecycleSearchProvider()
    return EOLReviewService(
        repository=LocalEOLCatalogRepository(
            base_catalog=None,
            document_store=document_store,
            document_name="state/eol_catalog.json",
        ),
        resolver=CandidateResolver(web_search_fetch=search_provider.resolve),
    )


def build_context() -> ApiContext:
    """Assemble the default context from the environment."""
    ontology_roots = _ontology_api_roots()
    onboarding = _onboarding_service(
        ontology_roots["connection"],
        command_home=ontology_roots["command"],
    )
    providers = _build_provider_runtime(onboarding)
    exposure_patch_refresh = ExposurePatchRefreshCoordinator(
        start_refresh=lambda scope: onboarding.sync_async(
            scope.connection_id,
            mode="scheduled",
        ),
        read_status=lambda scope: dict(
            onboarding.detail(scope.connection_id).get("sync_state") or {}
        ),
    )
    # Investigation ledgers are the audit trail for operator decisions, so they
    # are written through to OneLake and survive replica restarts. A local
    # AIOPS_HOME has no document store; the ledger falls back to memory.
    configure_ledger_store(_document_store())
    arg_config = (
        ConnectorConfig.load(os.environ[ENV_ARG_CONFIG])
        if os.environ.get(ENV_ARG_CONFIG, "").strip()
        else ConnectorConfig(output_dir=aiops_home())
    )
    live_resources = ConnectionScopedLiveResourceProvider(
        lambda: onboarding.registry.list(include_disabled=False),
        lambda connection: build_connection_arg_client(
            arg_config, connection, onboarding.resolver
        ),
        # The default bound suits single-resource lookups. Network topology
        # reads the whole network plane of every connected subscription, which
        # exceeds 100 rows in any real estate.
        max_rows=50_000,
    )

    def live_connection_cache_key(
        subscription_ids: list[str],
    ) -> tuple[tuple[str, ...], ...]:
        requested = {str(value).casefold() for value in subscription_ids}
        return tuple(
            sorted(
                connection_cache_identity(connection)
                for connection in onboarding.registry.list(include_disabled=False)
                if str(connection.subscription_id).casefold() in requested
            )
        )

    def live_connection_business_context() -> dict[str, dict[str, Any]]:
        contexts: dict[str, dict[str, Any]] = {}
        for connection in onboarding.registry.list(include_disabled=False):
            subscription_id = str(getattr(connection, "subscription_id", "") or "").strip()
            if not subscription_id:
                continue
            business = onboarding.registry.metadata_for(connection)
            contexts[subscription_id.casefold()] = {
                "business_service": business.business_service or "",
                "application": business.application or "",
                "environment": business.environment or "",
                "owner": business.project_owner or "",
                "support_team": business.support_team or "",
                "criticality": business.criticality or "",
                "region": business.region or "",
                "subscription_connection": str(
                    getattr(connection, "connection_id", "") or ""
                ),
            }
        return contexts

    def hybrid_resource(resource_id: str, subscription_ids: list[str]) -> dict[str, Any]:
        return HybridQueryService(
            providers.get("semantic_graph"),
            live_resources,
        ).resource_context(resource_id, subscription_ids=subscription_ids)

    def hybrid_search(query: str, subscription_ids: list[str]) -> dict[str, Any]:
        return HybridQueryService(
            providers.get("semantic_graph", optional=True),
            live_resources,
        ).search(query, subscription_ids=subscription_ids)

    def hybrid_business_service(
        service: str, subscription_ids: list[str]
    ) -> dict[str, Any]:
        graph = providers.get("semantic_graph", optional=True)
        if graph is None:
            requested = {value.casefold() for value in subscription_ids}
            connection_rows = [
                {
                    "subscription_id": subscription_id,
                    **business,
                }
                for subscription_id, business in sorted(
                    live_connection_business_context().items()
                )
                if subscription_id in requested
                and str(business.get("business_service") or "").casefold()
                == service.casefold()
            ]

            def unique_value(field: str) -> str:
                values = {
                    str(row.get(field) or "").strip()
                    for row in connection_rows
                    if str(row.get(field) or "").strip()
                }
                return next(iter(values)) if len(values) == 1 else ""

            return {
                "subject": {
                    "entity_type": "BusinessService",
                    "name": service,
                    "business_service": service,
                    "owner": unique_value("owner"),
                    "support_team": unique_value("support_team"),
                    "environment": unique_value("environment"),
                    "criticality": unique_value("criticality"),
                },
                "sections": {
                    "subscription_connections": connection_rows,
                },
                "graph_freshness": "",
                "live_observed_at": "",
                "source_status": {
                    "semantic-graph": "unavailable",
                    "subscription-connections": (
                        "ok" if connection_rows else "empty"
                    ),
                },
                "warnings": [
                    (
                        "Semantic graph service context is unavailable; "
                        "only retained subscription-connection facts are shown."
                    )
                ],
            }
        return HybridQueryService(
            graph,
            live_resources,
        ).service_context(
            service,
            subject_type="BusinessService",
            subscription_ids=subscription_ids,
        )

    def hybrid_impact(subject: str, subscription_ids: list[str]) -> dict[str, Any]:
        graph = providers.get("semantic_graph", optional=True)
        if graph is None:
            return {
                "root": {
                    "name": subject,
                    "business_service": subject,
                },
                "sections": {},
                "source_status": {"semantic-graph": "unavailable"},
                "warnings": [
                    (
                        "Dependency evidence is unavailable; "
                        "no dependency facts are asserted."
                    )
                ],
            }
        result = graph.get_impact_context(subject)
        result["source_status"] = {"semantic-graph": "ok"}
        return result

    def hybrid_risk(subject: str, subscription_ids: list[str]) -> dict[str, Any]:
        # Full semantic graph hydration is intentionally deferred in the
        # bounded production runtime. Live vulnerability evidence remains
        # usable without that optional enrichment.
        graph = providers.get("semantic_graph", optional=True)
        result = (
            graph.get_risk_context(subject)
            if graph is not None
            else {
                "subject": {
                    "name": subject,
                    "business_service": subject,
                },
                "risk": {},
                "sections": {},
            }
        )
        if graph is None:
            result["source_status"] = {"semantic-graph": "unavailable"}
            result["warnings"] = [
                (
                    "Service risk evidence is unavailable; "
                    "no service-specific risk facts are asserted."
                )
            ]
            return result
        try:
            vulnerability = hybrid_vulnerability(subscription_ids)
            live_summary = vulnerability.summary() if vulnerability is not None else {}
        except (RuntimeError, ValueError, TypeError, AttributeError):
            live_summary = {}
        result["source_status"] = {
            "semantic-graph": "ok",
            "live-vulnerability": "ok" if live_summary else "unavailable",
        }
        result["live_vulnerability_summary"] = live_summary
        if not live_summary:
            result["warnings"] = [
                "Live vulnerability observations are unavailable; risk is graph-only."
            ]
        return result

    def hybrid_network(subscription_ids: list[str]) -> NetworkIntelligenceService:
        # Cached per (root, subscription set, complete connection identity):
        # every scoped network route hits this path, and each miss is a live
        # ARG round trip. Credential rotation or connection replacement must
        # never reuse an observation fetched through a different SPN.
        #
        # Thread-safe (WR-05): reachable from the background remediation-
        # verification-coordinator thread too, transitively via
        # `hybrid_vulnerability` (itself called from
        # `_target_evidence_refresher`), not only from request threads.
        # Double-checked locking on a miss, matching `hybrid_vulnerability`
        # immediately below -- never a single cache-wide lock.
        cache_key = (
            str(aiops_home()),
            tuple(sorted(subscription_ids)),
            live_connection_cache_key(subscription_ids),
        )
        def load_network_rows() -> tuple[list[dict], str, int]:
            # Private Link candidates are fetched alongside the network plane
            # so private-endpoint coverage can be judged per resource rather
            # than per service kind.
            paas_types = ", ".join(
                f"'{name}'" for name in sorted(PRIVATE_LINK_RESOURCE_TYPES)
            )
            started = time.perf_counter()
            observation = live_resources.query(
                QuerySpec(
                    name="live_network_resources",
                    table="Resources",
                    query=(
                        "Resources "
                        "| where type startswith 'microsoft.network/' "
                        f"or tolower(type) in ({paas_types}) "
                        "| project id, name, type, tenantId, subscriptionId, "
                        "resourceGroup, location, tags, properties, observed_at=now()"
                    ),
                    incremental=False,
                ),
                subscription_ids=subscription_ids,
            )
            if observation.completeness not in {"complete", "healthy-empty"}:
                raise RuntimeError(
                    "Live network observations are incomplete for the requested "
                    "subscription connections"
                )
            return (
                list(observation.rows),
                observation.observed_at,
                round(max(0.0, time.perf_counter() - started) * 1_000),
            )

        rows, observed_at, topology_build_duration_ms = _ttl_cached_value(
            _hybrid_network_cache,
            cache_key,
            ttl_seconds=_HYBRID_NETWORK_CACHE_TTL_SECONDS,
            now=time.time(),
            build=load_network_rows,
            completion_clock=time.time,
        )
        policy, _revision = _network_policy_store().read_with_revision_or_raise()
        managed_network = providers.get("network", optional=True)
        flow_observations = (
            managed_network.flow_observations
            if isinstance(managed_network, NetworkIntelligenceService)
            else None
        )
        return NetworkIntelligenceService.from_arg_rows(
            rows,
            observed_at=observed_at,
            policy=policy,
            flow_observations=flow_observations,
            topology_build_duration_ms=topology_build_duration_ms,
            connection_context=live_connection_business_context(),
        )

    def hybrid_vulnerability(
        subscription_ids: list[str],
    ) -> VulnerabilityIntelligenceService | None:
        # Cached per (root, subscription set, complete connection identity): a
        # single remediation workflow request resolves this several times over
        # (plan list, scoped plan lookup, preview snapshot, patch target
        # lookup), and each miss is two live ARG round trips.
        #
        # Thread-safe (WR-05): the background remediation-verification-
        # coordinator thread (Plan 03.4-03) now also reads/writes this same
        # module-level cache via `_target_evidence_refresher`, on every
        # due-record reconciliation pass, independently of any request
        # thread -- a check-then-act race this cache was not originally
        # built to expect. Mirrors `hybrid_remediation`'s own use of
        # `_ttl_cached_value`/`_ttl_cache_lock` immediately below: a
        # lock-free read serves the common warm-cache case, and only a miss
        # serializes on a lock scoped to this specific `(cache, key)` pair,
        # never a single cache-wide lock.
        cache_key = (
            str(aiops_home()),
            tuple(sorted(subscription_ids)),
            live_connection_cache_key(subscription_ids),
        )

        def live_software_rows() -> list[dict[str, Any]]:
            workspace_observation = live_resources.query(
                QuerySpec(
                    name="live_patch_law_workspaces",
                    table="Resources",
                    query=(
                        "Resources "
                        "| where type =~ 'microsoft.operationalinsights/workspaces' "
                        "| project id, subscriptionId, "
                        "workspaceId=tostring(properties.customerId)"
                    ),
                    incremental=False,
                    source_family="log_analytics_workspace_discovery",
                ),
                subscription_ids=subscription_ids,
            )
            if workspace_observation.completeness not in {
                "complete",
                "healthy-empty",
            }:
                raise RuntimeError(
                    "Live Log Analytics workspace discovery is incomplete"
                )
            connections = {
                str(connection.subscription_id).casefold(): connection
                for connection in onboarding.registry.list(
                    include_disabled=False
                )
                if str(connection.subscription_id) in subscription_ids
            }
            rows: list[dict[str, Any]] = []
            for workspace in workspace_observation.rows:
                subscription_id = str(
                    workspace.get("subscriptionId")
                    or workspace.get("subscription_id")
                    or ""
                ).casefold()
                workspace_id = str(
                    workspace.get("workspaceId")
                    or workspace.get("workspace_id")
                    or ""
                ).strip()
                connection = connections.get(subscription_id)
                if connection is None or not workspace_id:
                    continue
                reader = build_connection_logs_client(
                    arg_config,
                    connection,
                    onboarding.resolver,
                )
                rows.extend(
                    _optional_configuration_data_rows(reader, workspace_id)
                )
            return rows

        def durable_live_snapshot() -> Mapping[str, Any]:
            cache = _enrichment_cache("live_patch_priorities")
            durable_key = hashlib.sha256(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "subscriptions": sorted(subscription_ids),
                        "connections": cache_key[2],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            found, stale, age = cache.get_entry(durable_key)
            if (
                found
                and isinstance(stale, Mapping)
                and age < _DURABLE_LIVE_PATCH_CACHE_TTL_SECONDS
            ):
                return stale
            try:
                snapshot = collect_live_patch_snapshot(
                    live_resources,
                    subscription_ids=subscription_ids,
                    software_rows=live_software_rows(),
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                if found and isinstance(stale, Mapping):
                    _LOGGER.warning(
                        "live_patch_refresh_failed_serving_lkg",
                        exc_info=True,
                    )
                    return stale
                raise
            cache.set(durable_key, snapshot)
            return snapshot

        def build() -> VulnerabilityIntelligenceService | None:
            graph = providers.get("semantic_graph", optional=True)
            try:
                network = hybrid_network(subscription_ids)
            except (RuntimeError, ValueError):
                network = None
            service = live_vulnerability_service(
                live_resources,
                subscription_ids=subscription_ids,
                semantic=graph,
                network=network,
                snapshot=durable_live_snapshot(),
                build_service=lambda tables, freshness, **kwargs: _build_vulnerability_service(
                    tables,
                    freshness,
                    **kwargs,
                    connection_context=live_connection_business_context(),
                ),
            )
            return service

        return _ttl_cached_value(
            _hybrid_vulnerability_cache,
            cache_key,
            ttl_seconds=_HYBRID_VULNERABILITY_CACHE_TTL_SECONDS,
            now=time.time(),
            build=build,
            completion_clock=time.time,
        )

    def hybrid_incidents(subscription_ids: list[str]) -> Any:
        return live_incident_engine(live_resources, subscription_ids=subscription_ids)

    def hybrid_remediation(subscription_ids: list[str]) -> LiveRemediationPlanner:
        # Cached per (root, subscription set) exactly like hybrid_vulnerability
        # above (same TTL): resolves one LiveRemediationPlanner/PlanRepository
        # per request window so scope validation (operations.py::_require's
        # remediation branch) and execution construction
        # (_execution_service_for_scope -> _planner_for_scope) observe the
        # same generation instead of each building a fresh repository (D-03).
        cache_key = (
            str(aiops_home()),
            tuple(sorted(subscription_ids)),
            live_connection_cache_key(subscription_ids),
        )

        def _build_planner() -> LiveRemediationPlanner:
            vulnerability_service = hybrid_vulnerability(subscription_ids)
            planner = LiveRemediationPlanner(
                vulnerability_service,
                repository=PlanRepository(decision_store=_remediation_decision_store()),
            )
            return _attach_live_defender_correlator(planner, vulnerability_service)

        return _ttl_cached_value(
            _hybrid_remediation_cache,
            cache_key,
            ttl_seconds=_HYBRID_VULNERABILITY_CACHE_TTL_SECONDS,
            now=time.time(),
            build=_build_planner,
            completion_clock=time.time,
        )

    def hybrid_patching(subscription_ids: list[str]) -> PatchingService | None:
        service = hybrid_vulnerability(subscription_ids)
        if service is None:
            return None
        return PatchingService(
            service,
            store=_patch_run_store,
            adapter=_patch_execution_adapter(
                onboarding,
                Scope.from_mapping({"subscription": subscription_ids}),
            ),
            require_human_approval=_require_human_approval,
            allow_self_approval=_allow_self_approval,
        )

    def exposure_read_port() -> ExposureReadPort | None:
        return providers.get("exposure_read_port", optional=True)

    def exposure_ontology(scope: Scope) -> Any:
        read_port = exposure_read_port()
        if read_port is None:
            return None
        return ExposureOntologyMapper(read_port).project(scope)

    def exposure_remediation() -> DefenderRemediationCorrelator | None:
        read_port = exposure_read_port()
        if read_port is None:
            return None
        return DefenderRemediationCorrelator.from_exposure_read_port(read_port)

    def _planner_for_scope(scope: Scope) -> Any:
        subscription_ids = subscription_ids_for_scope(
            scope,
            onboarding.registry.list(include_disabled=False),
            default_all=scope.is_unrestricted(),
        )
        if subscription_ids:
            return hybrid_remediation(subscription_ids)
        return _attach_remediation_decisions(providers.get("remediation", optional=True))

    def _patching_for_scope(scope: Scope) -> Any:
        subscription_ids = subscription_ids_for_scope(
            scope,
            onboarding.registry.list(include_disabled=False),
            default_all=scope.is_unrestricted(),
        )
        if subscription_ids:
            return hybrid_patching(subscription_ids)
        return providers.get("patching", optional=True)

    def _target_evidence_refresher(subscription_id: str, target_id: str) -> dict[str, Any] | None:
        """Narrowest available live target-evidence refresh for reconciliation.

        Reuses the existing per-request TTL-cached ``hybrid_vulnerability``
        live ARG path -- the codebase's narrowest available evidence refresh
        (WR-06/CR-03: do not wait for a full Fabric publication). Returns
        ``None`` only when the vulnerability service itself is unavailable
        for this subscription (a deployment with no live provider
        configured); an empty exposure list for the target is itself
        evidence that nothing is missing, not an unavailable signal.

        CR-02: an empty/unresolvable ``subscription_id`` or ``target_id``
        must fail closed as *unavailable* rather than being queried at all.
        A record with no derivable scope (a real category: legacy
        pre-Phase-03.2 execution records predate ``scope_attributes``
        entirely) must never have its unresolvable scope silently coerced
        into ``hybrid_vulnerability([""])``, whose only empty-list guard
        does not fire for a non-empty list containing an empty string --
        the call would otherwise reach Azure Resource Graph with a
        malformed subscription id, and *any* resulting empty row set would
        be indistinguishable downstream from "this asset has no exposures",
        producing a false ``reconciled_clean`` or a false promotion of a
        submission-ambiguous failure to ``succeeded`` without ever having
        queried the correct (or any) subscription.

        WR-06: CR-02 closes the *empty*-scope case, but a non-empty,
        syntactically valid, *wrong* subscription id (e.g. a resource
        migrated across subscriptions, or a stale ``scope_attributes``
        value) still reaches ``asset_exposures()`` unchanged, and an
        absent/wrong-subscription target produces the identical empty
        ``missing_kbs`` result as a genuinely fully-patched target. The
        returned ``target_observed`` flag makes that distinction explicit:
        ``True`` only when the target was actually seen in this snapshot's
        source data (an active exposure row, or a raw Update-Manager
        assessment/installation record even with zero remaining KBs);
        ``False`` when the target was not observed at all, so a caller can
        require confirmed observation before trusting an empty
        ``missing_kbs`` as "clean" (see ``RemediationExecutionService.
        reconcile_evidence``/``reconcile_ambiguous_submission``).
        """
        subscription_id = str(subscription_id or "").strip()
        target_id = str(target_id or "").strip()
        if not subscription_id or not target_id:
            return None  # unresolvable scope: unavailable, not "nothing missing"
        service = hybrid_vulnerability([subscription_id])
        if service is None:
            return None
        rows = service.asset_exposures()
        target_row = next(
            (
                row
                for row in rows
                if str(row.get("asset_id") or "").casefold() == target_id.casefold()
            ),
            None,
        )
        missing_kbs = list(target_row.get("missing_kbs") or []) if target_row else []
        target_observed = target_row is not None or service.is_asset_observed(target_id)
        return {
            "missing_kbs": missing_kbs,
            "assessed_at": service.freshness,
            "target_observed": target_observed,
        }

    def _execution_service_for_scope(scope: Scope) -> RemediationExecutionService:
        planner = _planner_for_scope(scope)
        if planner is not None and hasattr(planner, "generate_plans"):
            planner.generate_plans()
        deadline_seconds = float(
            os.environ.get(ENV_REMEDIATION_VERIFICATION_DEADLINE_SECONDS, "").strip()
            or VERIFICATION_DEADLINE_SECONDS
        )
        return RemediationExecutionService(
            plan_repository=getattr(planner, "repository", None),
            patching_service=_patching_for_scope(scope),
            defender_configuration_adapter=_defender_configuration_adapter(
                onboarding, scope
            ),
            execution_store=_remediation_execution_store(),
            execution_verifier=_execution_verifier(onboarding, scope),
            target_evidence_refresher=_target_evidence_refresher,
            verification_deadline_seconds=deadline_seconds,
            # CR-03 fix: both PatchingService production factories in this
            # same file (_load_patching_service, hybrid_patching) already
            # pass this identical `_allow_self_approval` closure -- this
            # constructor was the one isolated omission, silently defaulting
            # the shared gate's own self-approval policy to False forever
            # regardless of the administrator's real
            # agent_policy.allow_self_approval setting, even though the
            # shared gate (Plan 03.5-05) now runs and raises before
            # PatchingService's own correctly-wired check is ever reached.
            allow_self_approval=_allow_self_approval,
            # WR-02 fix: thread this request's live planner's
            # ApprovalEngine.policy_version into the execution gate the same
            # way `policy_version_for(planner)` projects it at the read-side
            # routes, rather than the gate's previous self-referential reuse
            # of the very decision being evaluated's own recorded value.
            # Resolved lazily (a closure, not a captured value) so a planner
            # rebuilt mid-request-window is still reflected.
            policy_version_resolver=lambda: policy_version_for(planner),
        )

    def _verification_coordinator() -> RemediationVerificationCoordinator:
        # A closure (not truly module-level) because it depends on
        # `_target_evidence_refresher` above, which itself needs
        # `hybrid_vulnerability`'s per-request TTL cache defined in this
        # same `build_context()` closure. The coordinator-owned service
        # below is constructed with `plan_repository=None,
        # patching_service=None`: it only ever calls
        # `poll_verification`/`reconcile_evidence`/
        # `reconcile_ambiguous_submission`, none of which touch
        # `self._plans`/`self._patching` (Plan 03.4-02), so it structurally
        # cannot execute, retry, or supersede a plan -- it can only
        # observe/reconcile already-durable records (mirrors CR-06's
        # fail-closed handling, not a workaround of it).
        deadline_seconds = float(
            os.environ.get(ENV_REMEDIATION_VERIFICATION_DEADLINE_SECONDS, "").strip()
            or VERIFICATION_DEADLINE_SECONDS
        )
        return RemediationVerificationCoordinator(
            execution_store=_remediation_execution_store(),
            execution_service=RemediationExecutionService(
                plan_repository=None,
                patching_service=None,
                execution_store=_remediation_execution_store(),
                execution_verifier=_execution_verifier(onboarding),
                target_evidence_refresher=_target_evidence_refresher,
                verification_deadline_seconds=deadline_seconds,
            ),
        )

    def hybrid_resource_health(subscription_ids: list[str]) -> ResourceHealthService:
        # Live per-connection utilization: each request re-lists in-scope
        # compute resources via ARG and fetches fresh Monitor Metrics, so no
        # cache is used here (unlike hybrid_network) since a stale CPU
        # reading would actively mislead an operator.
        def resource_lister(connection: Any) -> list[dict[str, Any]]:
            observation = live_resources.query(
                QuerySpec(
                    name="live_compute_resources",
                    table="Resources",
                    query=(
                        "Resources "
                        "| where type in ("
                        "'microsoft.compute/virtualmachines', "
                        "'microsoft.hybridcompute/machines', "
                        "'microsoft.app/containerapps') "
                        "| project id, name, type, subscriptionId, resourceGroup"
                    ),
                    incremental=False,
                ),
                subscription_ids=[str(connection.subscription_id)],
            )
            return list(observation.rows)

        def law_lister(connection: Any) -> list[dict[str, Any]]:
            observation = live_resources.query(
                QuerySpec(
                    name="live_law_workspaces",
                    table="Resources",
                    query=(
                        "Resources "
                        "| where type =~ 'microsoft.operationalinsights/workspaces' "
                        "| project id, name, subscriptionId, resourceGroup, "
                        "workspaceId=tostring(properties.customerId)"
                    ),
                    incremental=False,
                ),
                subscription_ids=[str(connection.subscription_id)],
            )
            return list(observation.rows)

        def amw_lister(connection: Any) -> list[dict[str, Any]]:
            # Azure Monitor Workspaces (the OTel/managed-Prometheus counterpart
            # to a Log Analytics workspace). Each row is turned into a
            # PrometheusEndpoint: workspace-scoped when ARG already exposes
            # the resource's own query endpoint, otherwise resource-scoped
            # against the shared regional endpoint using this connection's
            # subscription as the scoping id (broadest scope available without
            # per-resource lookups, and consistent with how the classic path
            # merges across every workspace in scope rather than one per VM).
            observation = live_resources.query(
                QuerySpec(
                    name="live_amw_workspaces",
                    table="Resources",
                    query=(
                        "Resources "
                        "| where type =~ 'microsoft.monitor/accounts' "
                        "| project id, name, subscriptionId, resourceGroup, location, "
                        "prometheusQueryEndpoint=tostring(properties.metrics.prometheusQueryEndpoint)"
                    ),
                    incremental=False,
                ),
                subscription_ids=[str(connection.subscription_id)],
            )
            rows: list[dict[str, Any]] = []
            for row in observation.rows:
                query_endpoint = str(row.get("prometheusQueryEndpoint") or "").strip()
                region = str(row.get("location") or "").strip()
                try:
                    if query_endpoint:
                        endpoint = workspace_scoped_endpoint(query_endpoint)
                    elif region:
                        endpoint = resource_scoped_endpoint(
                            region, str(connection.subscription_id)
                        )
                    else:
                        continue
                except ValueError:
                    continue
                rows.append({**row, "endpoint": endpoint})
            return rows

        return ResourceHealthService(
            lambda: [
                connection
                for connection in onboarding.registry.list(include_disabled=False)
                if str(connection.subscription_id) in subscription_ids
            ],
            resource_lister,
            lambda connection: build_connection_monitor_metrics_client(
                arg_config, connection, onboarding.resolver
            ),
            law_lister=law_lister,
            guest_performance_reader_factory=lambda connection: build_connection_logs_client(
                arg_config, connection, onboarding.resolver
            ),
            amw_lister=amw_lister,
            otel_performance_reader_factory=lambda connection: build_connection_prometheus_client(
                arg_config, connection, onboarding.resolver
            ),
        )

    return ApiContext(
        onboarding=onboarding,
        authenticator=build_authenticator(),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        # Rebuilt on every call (not baked in once here) so a freshly synced
        # connection is picked up on the next request without restarting the
        # API, per the provider contracts in `dependencies.py`.
        semantic_provider=lambda: providers.get("semantic", optional=True),
        hybrid_resource_provider=hybrid_resource,
        hybrid_search_provider=hybrid_search,
        hybrid_business_service_provider=hybrid_business_service,
        hybrid_impact_provider=hybrid_impact,
        hybrid_risk_provider=hybrid_risk,
        hybrid_network_provider=hybrid_network,
        hybrid_vulnerability_provider=hybrid_vulnerability,
        hybrid_incident_provider=hybrid_incidents,
        hybrid_remediation_provider=hybrid_remediation,
        hybrid_patching_provider=hybrid_patching,
        hybrid_resource_health_provider=hybrid_resource_health,
        incident_provider=lambda: providers.get("incidents", optional=True),
        remediation_provider=lambda: _attach_remediation_decisions(
            providers.get("remediation", optional=True)
        ),
        execution_provider=_execution_service_for_scope,
        network_provider=lambda: providers.get("network", optional=True),
        vulnerability_provider=lambda: providers.get("vulnerability", optional=True),
        patching_provider=lambda: providers.get("patching", optional=True),
        change_provider=lambda: providers.get("change", optional=True),
        governance_provider=lambda: providers.get("governance", optional=True),
        governance_generation_provider=_load_governance_generation_snapshot,
        settings_store=_settings_store(),
        network_policy_store=_network_policy_store(),
        risk_exception_list=list_risk_exceptions,
        risk_exception_add=add_risk_exception,
        risk_exception_revoke=revoke_risk_exception,
        foundry_agent_provider=_load_foundry_agent,
        provider_runtime=providers,
        situation_provider=_load_situation_provider,
        inventory_provider=lambda: providers.get("inventory", optional=True),
        inventory_read_port_provider=lambda: providers.get(
            "inventory_read_port", optional=True
        ),
        exposure_query_provider=lambda: providers.get(
            "exposure_query", optional=True
        ),
        exposure_patch_refresh_provider=lambda: exposure_patch_refresh,
        exposure_read_port_provider=exposure_read_port,
        exposure_ontology_provider=exposure_ontology,
        exposure_remediation_provider=exposure_remediation,
        fabric_iq_provider=lambda: providers.get("fabric_iq", optional=True),
        verification_coordinator_provider=_verification_coordinator,
        ontology_discovery_provider=lambda: _load_ontology_discovery_api(
            onboarding, ontology_roots
        ),
    )
