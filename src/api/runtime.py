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

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from fabric.auth import FabricAuthConfig
from fabric.config import FabricRuntimeConfig, OntologyRuntimeConfig
from fabric.dataset_mapper import InventoryDatasetMapper
from fabric.runtime import FabricRuntime, build_runtime
from intelligence.governance import EnterpriseSettingsStore
from intelligence.health.service import ResourceHealthService
from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.incidents.incident_engine import IncidentEngine
from intelligence.vulnerability.connector import (
    EpssScoreConnector,
    KevCatalogConnector,
    MsrcKbLookupConnector,
    NvdCveEnrichmentConnector,
)
from intelligence.vulnerability.enrichment_cache import EnrichmentCache
from intelligence.vulnerability.models import RiskException
from intelligence.vulnerability.service import (
    VulnerabilityIntelligenceService,
    _defender_payload,
)
from onboarding.config import ConnectorConfig
from onboarding.query_contract import QuerySpec

_LOGGER = logging.getLogger(__name__)

from intelligence.remediation.approval_decisions import RemediationDecisionStore
from intelligence.remediation.defender_correlation import DefenderRemediationCorrelator
from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.execution_verifier import ExecutionVerifier
from intelligence.remediation.plan_repository import PlanRepository
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
    build_connection_logs_client,
    build_connection_monitor_metrics_client,
    build_connection_prometheus_client,
    build_onboarding_service,
)
from onboarding.service import SubscriptionOnboardingService
from onboarding.sync import _slug
from operations.autonomous_investigation import configure_ledger_store
from operations.foundry_agent import (
    SPECIALIST_IDS,
    FoundryPromptAgent,
    MicrosoftAgentFrameworkFoundryAgent,
)
from operations.maf_orchestrator import maf_mode_enabled
from operations.patching import (
    InMemoryPatchRunStore,
    PatchingService,
    UnconfiguredPatchExecutionAdapter,
)
from operations.tools import FabricIQToolAdapter
from semantic.hybrid_query import HybridQueryService
from semantic.live_operations import (
    LiveRemediationPlanner,
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
from .scope import Scope
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
ENV_GATEWAY_ASSERTION = "AIOPS_GATEWAY_ASSERTION"

AUTH_GATEWAY = "gateway"
AUTH_ENTRA = "entra"
AUTH_TOKEN = "token"

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


def _onboarding_service() -> SubscriptionOnboardingService:
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
        else ConnectorConfig(output_dir=aiops_home())
    )
    vault = os.environ.get(ENV_CONNECTION_KEY_VAULT, "").strip()
    return build_onboarding_service(
        config,
        secret_writer=KeyVaultSecretWriter(vault) if vault else None,
        config_path=config_path,
        fabric_config_path=os.environ.get(ENV_FABRIC_CONFIG, "").strip(),
    )


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

# Scoped network requests bypass the persisted snapshot and query ARG live, so
# without a cache every page load costs a round trip. Keyed by root *and*
# subscription set, since rows fetched for one scope must never serve another.
_HYBRID_NETWORK_CACHE_TTL_SECONDS = 30
_hybrid_network_cache: dict[tuple[str, tuple[str, ...]], tuple[float, list[dict]]] = {}


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
        snapshot_dir = store.current_generation()
        if snapshot_dir is None:
            continue  # connection registered but never synced
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
            tables = mapper.load(snapshot_dir, run_id, fs=store.fs if store.is_remote else None)
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


def _load_network_service() -> NetworkIntelligenceService | None:
    entities, relationships, _freshness = _load_ontology_rows()
    if not entities:
        return None
    return NetworkIntelligenceService.from_rows(
        entities,
        policy=_network_policy_store().read(),
        semantic_relationships=relationships,
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
) -> VulnerabilityIntelligenceService | None:
    """Build vulnerability intelligence from one authoritative snapshot."""
    if not freshness:
        return None
    pending: list[dict[str, Any]] = []
    defender_findings: list[dict[str, Any]] = []
    defender_assessments: list[dict[str, Any]] = []
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
    for table in tables:
        for row in table.get("silver_patch_findings") or []:
            kb_id = str(row.get("kb_id") or "").strip()
            target = str(row.get("target_resource_id") or "")
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
    # Combine both ARG tables: a KB reported as still "missing" by the latest
    # assessment but already recorded as "installed" for that same target is
    # remediated (e.g. the install ran after the assessment snapshot) and
    # should not surface as an open exposure.
    findings = [
        item for item in pending if (item["server_id"], item["missing_kb"]) not in installed_kbs
    ]

    # Resolve real CVE ids for each pending KB via the public MSRC Security
    # Update Guide feed. Some KBs (e.g. Servicing Stack Updates) genuinely
    # have no CVE association in MSRC's data; those keep the `KB-<kbId>`
    # proxy identifier used before this connector was wired in, which is
    # factually correct rather than a bug.
    kb_metadata = _resolve_kb_metadata(tuple({item["missing_kb"] for item in findings}))
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

    all_cve_ids = tuple(
        sorted({item["cve_id"] for item in findings if item["cve_id"].upper().startswith("CVE-")})
    )
    cve_rows = _resolve_cve_details(all_cve_ids)

    # Layer in real-world exploitation evidence (P1): EPSS gives a continuous
    # exploitation-probability score, CISA KEV confirms active exploitation.
    # Both are best-effort — CVEs simply keep their default (unexploited)
    # values if either feed is unreachable.
    epss_scores = _resolve_epss_scores(all_cve_ids)
    kev_catalog = _resolve_kev_catalog()

    _attach_business_context(findings, semantic)
    _attach_business_context(defender_assessments, semantic)
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
        defender_assessments=defender_assessments,
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
            for item in findings
            if item.get("missing_kb")
        ],
        cves=cve_rows,
        freshness=freshness,
        metadata_connector=None,
        epss_scores=epss_scores,
        kev_catalog=kev_catalog,
    )

    resolver = _network_reachability_resolver(network)
    if resolver is not None:
        service = service.correlate_network(resolver)
    risk_exceptions = list_risk_exceptions()
    if risk_exceptions:
        service = service.apply_risk_exceptions(risk_exceptions)
    return service


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
    return _build_vulnerability_service(tables, freshness)


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
        item["application"] = public.get("application", "")
        item["business_service"] = public.get("business_service", "")
        item["owner"] = public.get("owner", "")
        item["environment"] = public.get("environment", "")
        item["criticality"] = public.get("criticality", "")
        item["subscription_id"] = public.get("subscription_id", "")
        item["subscription_connection"] = public.get("subscription_connection", "")
        item["region"] = public.get("region", "")


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


def _lookup_live_cve(cve_id: str) -> dict[str, Any] | None:
    """Fetch a single CVE directly from NVD when it isn't already part of the
    current snapshot's projection (e.g. a CVE search/drilldown for an id the
    environment hasn't observed a finding for). Memoized via the same TTL
    cache as `_resolve_cve_details`; returns None on any failure or unknown id
    so the caller can fall back to a 404 rather than surfacing a partial CVE.
    """
    cve_id = cve_id.strip().upper()
    if not cve_id.startswith("CVE-"):
        return None
    rows = _resolve_cve_details((cve_id,))
    return rows[0] if rows else None


def _load_foundry_agent() -> FoundryPromptAgent | None:
    """Resolve the Copilot's Foundry prompt agent from the environment.

    Built once and memoized: unlike the snapshot providers, the agent is a
    stateless HTTP client whose configuration cannot change without a restart,
    and rebuilding it per request would discard its cached access token.
    """
    global _foundry_agent
    if _foundry_agent is _UNSET:
        # Operations Copilot is the shared narrator/orchestrator. Specialist
        # agents are resolved separately through `_load_foundry_specialist_agent`;
        # using the Network specialist here would make MAF mode page-biased
        # before it ever delegates.
        agent_class = (
            MicrosoftAgentFrameworkFoundryAgent
            if maf_mode_enabled()
            else FoundryPromptAgent
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
    if specialist_id not in _foundry_specialist_agents:
        agent_class = (
            MicrosoftAgentFrameworkFoundryAgent
            if maf_mode_enabled()
            else FoundryPromptAgent
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


def _fabric_is_configured() -> bool:
    return bool(os.environ.get(ENV_FABRIC_CONFIG, "").strip()) or (
        _truthy("AIOPS_ENABLE_FABRIC")
        and bool(os.environ.get("FABRIC_WORKSPACE_ID", "").strip())
        and bool(os.environ.get("FABRIC_LAKEHOUSE_ID", "").strip())
    )


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

    def query(kind: str, args: dict[str, Any], scope: Any) -> dict[str, Any]:
        subject = str(args.get("subject") or "").strip()
        if not subject:
            raise ValueError("Ontology enrichment subject is required")
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

    return FabricIQToolAdapter(query=query, source=_ONTOLOGY_PROJECTION_PROVENANCE)


def _fabric_network_service(runtime: FabricRuntime) -> NetworkIntelligenceService:
    snapshot = runtime.service.semantic_snapshot()
    return NetworkIntelligenceService.from_rows(
        snapshot["entities"], policy=_network_policy_store().read()
    )


def _fabric_vulnerability_service(
    runtime: FabricRuntime,
) -> VulnerabilityIntelligenceService | None:
    semantic_snapshot = runtime.service.semantic_snapshot()
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
    semantic = runtime.semantic_engine()
    network = _fabric_network_service(runtime)
    return _build_vulnerability_service(
        [
            {
                "silver_patch_findings": findings,
                "silver_defender_findings": defender_findings,
                "silver_defender_assessments": defender_assessments,
                **{
                    f"silver_defender_{name}": rows
                    for name, rows in defender.items()
                },
            }
        ],
        str(semantic_snapshot.get("freshness") or ""),
        semantic=semantic,
        network=network,
    )


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
    return planner


def _fabric_remediation_planner(runtime: FabricRuntime) -> Any:
    planner = _attach_remediation_decisions(
        getattr(runtime.operations_agent(), "remediation_planner", None)
    )
    return _attach_defender_correlator(planner, runtime)


def _fabric_change_intelligence(runtime: FabricRuntime) -> Any:
    """Resolve the compliance/change-intelligence engine for this snapshot.

    Reuses the instance already built by ``operations_agent()`` (gated by
    ``change_intelligence.enabled``) rather than reconstructing it, so
    compliance reads share the exact snapshot the operations narration path
    reasons over.
    """
    return getattr(runtime.operations_agent(), "change_intelligence", None)


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
) -> dict[str, Any]:
    runtime = fabric_supplier()
    last_discovery = _latest_discovery(onboarding)
    if runtime is None:
        semantic = _load_semantic_snapshot()
        return {
            "ontology_version": getattr(semantic, "knowledge_version", ""),
            "freshness": getattr(semantic, "freshness", ""),
            "last_discovery_run": last_discovery,
            "last_ontology_publication": getattr(semantic, "freshness", ""),
        }
    health = runtime.service.ontology_health()
    semantic = runtime.semantic_engine()
    return {
        "ontology_version": semantic.knowledge_version,
        "freshness": semantic.freshness,
        "last_discovery_run": last_discovery,
        "last_ontology_publication": str(
            health.get("timestamp")
            or health.get("synchronized_at")
            or health.get("published_at")
            or ""
        ),
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
        snapshot = runtime.service.semantic_snapshot()
        freshness = str(snapshot.get("freshness") or "")
        if not freshness:
            if _truthy("AIOPS_ALLOW_EMPTY_FABRIC_SNAPSHOT"):
                # A newly created validation lakehouse is intentionally empty
                # until the first activation sync completes.
                return None
            raise RuntimeError(
                "Fabric semantic snapshot has no freshness; publish the ontology "
                "and ingestion state before activating providers"
            )
        try:
            instance = loader(runtime)
        except Exception:
            _LOGGER.exception("with_fabric_loader_failed loader=%r", loader)
            raise
        return ProviderValue(
            instance,
            freshness=freshness,
            ontology_version=str(snapshot.get("knowledge_version") or ""),
        )

    if use_fabric:
        loaders: dict[str, Callable[[], Any]] = {
            "semantic": lambda: with_fabric(lambda item: item.semantic_engine()),
            "semantic_graph": lambda: with_fabric(
                lambda item: item.semantic_graph_engine()
            ),
            "network": lambda: with_fabric(_fabric_network_service),
            "vulnerability": lambda: with_fabric(_fabric_vulnerability_service),
            "incidents": lambda: with_fabric(_fabric_incident_engine),
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
    bootstrap = _truthy("AIOPS_ALLOW_EMPTY_FABRIC_SNAPSHOT")
    core_readiness_providers = {"semantic", "semantic_graph"}
    specs = {
        name: ProviderSpec(
            loader=loader,
            configured=True,
            required=(name in core_readiness_providers and not bootstrap),
        )
        for name, loader in loaders.items()
    }
    specs["copilot"] = ProviderSpec(
        loader=_load_foundry_agent,
        configured=foundry_configured,
        required=False,
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
    )
    specs["inventory_read_port"] = ProviderSpec(
        loader=lambda: _load_inventory_read_port(),
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
        )
    return ProviderRuntime(
        specs,
        metadata_loader=lambda: _runtime_metadata(onboarding, fabric),
        refresh_interval_seconds=int(
            os.environ.get(ENV_PROVIDER_REFRESH_SECONDS, "30")
        ),
        stale_after_hours=int(os.environ.get(ENV_PROVIDER_STALE_HOURS, "24")),
    )


# Patch runs are operator-submitted mutations, not snapshot projections, so
# they use a process-level store handle like risk exceptions. The store is
# shared across provider rebuilds so a rebuild never loses run history.
_patch_run_store = InMemoryPatchRunStore()
_PATCH_EXECUTION_CREDENTIAL: Any = _UNSET


def _azure_patch_credential() -> Any | None:
    """Return one process credential shared by patch submit and verification."""
    global _PATCH_EXECUTION_CREDENTIAL
    mode = (os.environ.get(ENV_PATCH_EXECUTION) or "").strip().casefold()
    if mode not in {"azure", "arm", "azure-arm"}:
        return None
    if _PATCH_EXECUTION_CREDENTIAL is _UNSET:
        try:
            from azure.identity import DefaultAzureCredential

            _PATCH_EXECUTION_CREDENTIAL = DefaultAzureCredential()
        except Exception:  # noqa: BLE001 - callers safely refuse without identity
            _PATCH_EXECUTION_CREDENTIAL = None
    return _PATCH_EXECUTION_CREDENTIAL


def _patch_execution_adapter() -> Any:
    """Resolve the configured execution backend.

    Defaults to the refusing adapter: triggering real Azure writes must be an
    explicit deployment decision, never an accident of configuration. Setting
    ``AIOPS_PATCH_EXECUTION=azure`` opts a deployment in to live ARM calls,
    and even then a missing or unusable credential falls back to refusing
    rather than failing at import time.
    """
    credential = _azure_patch_credential()
    if credential is None:
        return UnconfiguredPatchExecutionAdapter()
    try:
        from operations.patching.azure_adapter import AzureArmPatchExecutionAdapter

        return AzureArmPatchExecutionAdapter(credential)
    except Exception:  # noqa: BLE001 - refusing is the safe outcome here
        _LOGGER.warning(
            "%s requested Azure patch execution but no usable credential was "
            "available; patch runs will refuse.",
            ENV_PATCH_EXECUTION,
        )
        return UnconfiguredPatchExecutionAdapter()


def _execution_verifier() -> ExecutionVerifier | None:
    """Build the read-only verifier at the same ARM credential boundary."""
    credential = _azure_patch_credential()
    return ExecutionVerifier(credential=credential) if credential is not None else None


def _load_patching_service(vulnerability_loader: Callable[[], Any]) -> Any | None:
    """Project the current vulnerability snapshot into patchable inventory."""
    raw = vulnerability_loader()
    service = raw.instance if isinstance(raw, ProviderValue) else raw
    if service is None:
        return None
    return PatchingService(
        service,
        store=_patch_run_store,
        adapter=_patch_execution_adapter(),
        require_human_approval=_require_human_approval,
    )


def _load_governance_snapshot() -> GovernanceSnapshot | None:
    """Build the scoped governance view from synced ontology rows.

    Returns None when nothing has been synced, so the governance routes report
    the capability as unavailable rather than returning empty results a UI
    would render as "no cost waste and no privileged access".
    """
    entities, _relationships, freshness = _load_ontology_rows()
    if not entities:
        return None
    return GovernanceSnapshot(
        entities,
        observed_at=freshness,
        connections=_governance_connections(),
    )


def _governance_connections() -> list[dict[str, Any]]:
    """Connection registry rows for SPN governance.

    Reads the registry directly rather than resolving credentials: governance
    reports on credential *metadata* (owner, scope, expiry, use) and must never
    need the secret itself, so a Key Vault outage cannot break this view.
    """
    try:
        onboarding = _onboarding_service()
        connections = onboarding.registry.list(include_disabled=True)
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
        path = None if documents is not None else root / "state" / "remediation_decisions.json"
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
        path = None if documents is not None else root / "state" / "remediation_executions.json"
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


def _load_inventory_read_port() -> Any:
    """Build the internal identity contract over the active inventory."""
    from intelligence.inventory.read_port import InventoryReadPort

    service = _load_inventory_service()
    return InventoryReadPort(service) if service is not None else None


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
    onboarding = _onboarding_service()
    providers = _build_provider_runtime(onboarding)
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

    def hybrid_resource(resource_id: str, subscription_ids: list[str]) -> dict[str, Any]:
        return HybridQueryService(
            providers.get("semantic_graph"),
            live_resources,
        ).resource_context(resource_id, subscription_ids=subscription_ids)

    def hybrid_search(query: str, subscription_ids: list[str]) -> dict[str, Any]:
        return HybridQueryService(
            providers.get("semantic_graph"),
            live_resources,
        ).search(query, subscription_ids=subscription_ids)

    def hybrid_business_service(
        service: str, subscription_ids: list[str]
    ) -> dict[str, Any]:
        return HybridQueryService(
            providers.get("semantic_graph"),
            live_resources,
        ).service_context(
            service,
            subject_type="BusinessService",
            subscription_ids=subscription_ids,
        )

    def hybrid_impact(subject: str, subscription_ids: list[str]) -> dict[str, Any]:
        graph = providers.get("semantic_graph")
        result = graph.get_impact_context(subject)
        result["source_status"] = {"semantic-graph": "ok"}
        return result

    def hybrid_risk(subject: str, subscription_ids: list[str]) -> dict[str, Any]:
        graph = providers.get("semantic_graph")
        result = graph.get_risk_context(subject)
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
        # Cached per (root, subscription set): every scoped network route hits
        # this path, and each miss is a live ARG round trip. The TTL matches
        # the snapshot-table cache so freshness behaviour is consistent.
        cache_key = (str(aiops_home()), tuple(sorted(subscription_ids)))
        now = time.time()
        cached = _hybrid_network_cache.get(cache_key)
        if cached is not None and now - cached[0] < _HYBRID_NETWORK_CACHE_TTL_SECONDS:
            rows = cached[1]
            observed_at = max(
                (str(row.get("observed_at") or "") for row in rows),
                default="",
            )
        else:
            # Private Link candidates are fetched alongside the network plane
            # so private-endpoint coverage can be judged per resource rather
            # than per service kind.
            paas_types = ", ".join(
                f"'{name}'" for name in sorted(PRIVATE_LINK_RESOURCE_TYPES)
            )
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
            rows = list(observation.rows)
            observed_at = observation.observed_at
            _hybrid_network_cache[cache_key] = (now, rows)
        return NetworkIntelligenceService.from_arg_rows(
            rows,
            observed_at=observed_at,
            policy=_network_policy_store().read(),
        )

    def hybrid_vulnerability(
        subscription_ids: list[str],
    ) -> VulnerabilityIntelligenceService | None:
        graph = providers.get("semantic_graph")
        try:
            network = hybrid_network(subscription_ids)
        except (RuntimeError, ValueError):
            network = None
        return live_vulnerability_service(
            live_resources,
            subscription_ids=subscription_ids,
            semantic=graph,
            network=network,
            build_service=_build_vulnerability_service,
        )

    def hybrid_incidents(subscription_ids: list[str]) -> Any:
        return live_incident_engine(live_resources, subscription_ids=subscription_ids)

    def hybrid_remediation(subscription_ids: list[str]) -> LiveRemediationPlanner:
        return LiveRemediationPlanner(
            hybrid_vulnerability(subscription_ids),
            repository=PlanRepository(decision_store=_remediation_decision_store()),
        )

    def hybrid_patching(subscription_ids: list[str]) -> PatchingService | None:
        service = hybrid_vulnerability(subscription_ids)
        if service is None:
            return None
        return PatchingService(
            service,
            store=_patch_run_store,
            adapter=_patch_execution_adapter(),
            require_human_approval=_require_human_approval,
        )

    def _planner_for_scope(scope: Scope) -> Any:
        subscription_ids = list(scope.values("subscription"))
        if subscription_ids:
            return hybrid_remediation(subscription_ids)
        return _attach_remediation_decisions(providers.get("remediation", optional=True))

    def _patching_for_scope(scope: Scope) -> Any:
        subscription_ids = list(scope.values("subscription"))
        if subscription_ids:
            return hybrid_patching(subscription_ids)
        return providers.get("patching", optional=True)

    def _execution_service_for_scope(scope: Scope) -> RemediationExecutionService:
        planner = _planner_for_scope(scope)
        if planner is not None and hasattr(planner, "generate_plans"):
            planner.generate_plans()
        return RemediationExecutionService(
            plan_repository=getattr(planner, "repository", None),
            patching_service=_patching_for_scope(scope),
            execution_store=_remediation_execution_store(),
            execution_verifier=_execution_verifier(),
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
                        "'microsoft.hybridcompute/machines') "
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
        governance_provider=_load_governance_snapshot,
        settings_store=_settings_store(),
        network_policy_store=_network_policy_store(),
        vulnerability_live_lookup=_lookup_live_cve,
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
        fabric_iq_provider=lambda: providers.get("fabric_iq", optional=True),
    )
