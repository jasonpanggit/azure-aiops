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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fabric.auth import FabricAuthConfig
from fabric.config import FabricRuntimeConfig, OntologyRuntimeConfig
from fabric.dataset_mapper import InventoryDatasetMapper
from fabric.runtime import FabricRuntime, build_runtime
from hermes_arg_connector.config import ConnectorConfig
from intelligence.incident.incident_intelligence import IncidentIntelligence
from intelligence.incidents.incident_engine import IncidentEngine
from intelligence.vulnerability.connector import (
    EpssScoreConnector,
    KevCatalogConnector,
    MsrcKbLookupConnector,
    NvdCveEnrichmentConnector,
)
from intelligence.vulnerability.models import RiskException
from intelligence.vulnerability.service import VulnerabilityIntelligenceService

_LOGGER = logging.getLogger(__name__)

# KB->CVE (MSRC) and CVE->detail (NVD) lookups are best-effort external
# enrichment. `_load_vulnerability_service()` is rebuilt on every request (see
# `build_context()` below), so results are memoized with a TTL to avoid an
# external API call storm and to respect NVD's rate limits. A single process
# cache is deliberately simple; failures never break the endpoint, they just
# fall back to the `KB-<kbId>` proxy identifier used before this connector
# existed.
_KB_CVE_CACHE_TTL_SECONDS = 6 * 60 * 60
_kb_cve_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
_cve_detail_cache: dict[str, tuple[float, dict[str, Any]]] = {}
from network.flow import FlowQuery
from network.service import NetworkIntelligenceService
from onboarding.credentials import KeyVaultSecretWriter
from onboarding.registry import ConnectionRegistry
from onboarding.runtime import build_onboarding_service
from onboarding.service import SubscriptionOnboardingService
from onboarding.sync import _slug
from operations.foundry_agent import FoundryPromptAgent
from semantic.semantic_engine import SemanticEngine

from .auth import (
    EntraJwtAuthenticator,
    HeaderPrincipalAuthenticator,
    StaticTokenAuthenticator,
)
from .dependencies import ApiContext
from .providers import ProviderRuntime, ProviderSpec, ProviderValue
from .rbac import Authorizer, Grant, Principal
from .telemetry import ApiTelemetry

ENV_HOME = "HERMES_HOME"
ENV_AUTH_MODE = "HERMES_API_AUTH"
ENV_TOKENS = "HERMES_API_TOKENS"
ENV_GATEWAY_GRANTS = "HERMES_API_GATEWAY_GRANTS"
ENV_ENTRA_TENANT_ID = "HERMES_ENTRA_TENANT_ID"
ENV_ENTRA_AUDIENCE = "HERMES_ENTRA_AUDIENCE"
# Optional path to a hermes_arg_connector YAML config (see config.example.yaml)
# used only to source ingestion defaults (page size, timeouts, MCP command,
# ...). Per-connection subscription/tenant scoping always comes from the
# connection itself, so this file need not list any subscriptions.
ENV_ARG_CONFIG = "HERMES_ARG_CONFIG"
ENV_CONNECTION_KEY_VAULT = "HERMES_CONNECTION_KEY_VAULT"
ENV_FABRIC_CONFIG = "HERMES_FABRIC_CONFIG"
ENV_RUNTIME_MODE = "HERMES_RUNTIME_MODE"
ENV_PROVIDER_REFRESH_SECONDS = "HERMES_PROVIDER_REFRESH_SECONDS"
ENV_PROVIDER_STALE_HOURS = "HERMES_PROVIDER_STALE_HOURS"

AUTH_GATEWAY = "gateway"
AUTH_ENTRA = "entra"
AUTH_TOKEN = "token"

# Sentinel distinguishing "not yet resolved" from a resolved-but-absent agent,
# so an unconfigured deployment is probed once rather than on every request.
_UNSET: Any = object()
_foundry_agent: Any = _UNSET


def hermes_home() -> Path | str:
    """Root for all persisted state: connection dataset snapshots.

    Plain paths use the local disk (the default for development). Set to an
    ``abfss://<container>@<account>.dfs.core.windows.net/<path>`` URI to
    persist synced dataset snapshots in Azure Data Lake Storage Gen2 instead
    -- the same `DatasetStore`/`InventoryDatasetMapper` code path handles
    both transparently (see `hermes_arg_connector.fs`).
    """
    from hermes_arg_connector.fs import resolve_root

    return resolve_root(os.environ.get(ENV_HOME) or str(Path.home() / ".hermes"))


def _token_principals() -> dict[str, Principal]:
    """Parse ``HERMES_API_TOKENS`` as JSON: ``{token: {subject, grants: [...]}}``."""
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
        asserted = set(roles)
        return tuple(grant for grant in principal.grants if grant.role in asserted)

    return resolve


def build_authenticator():
    mode = (os.environ.get(ENV_AUTH_MODE) or AUTH_TOKEN).strip().casefold()
    if mode == AUTH_GATEWAY:
        return HeaderPrincipalAuthenticator(grants_resolver=_gateway_grants())
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
    so an unconfigured HERMES_ARG_CONFIG defaults safely to base ingestion
    settings.
    """
    config_path = os.environ.get(ENV_ARG_CONFIG, "").strip()
    config = (
        ConnectorConfig.load(config_path)
        if config_path
        else ConnectorConfig(output_dir=hermes_home())
    )
    vault = os.environ.get(ENV_CONNECTION_KEY_VAULT, "").strip()
    return build_onboarding_service(
        config,
        secret_writer=KeyVaultSecretWriter(vault) if vault else None,
    )


def _connection_dataset_dir(root: str, connection_id: str) -> str:
    """Mirror `ConnectionSyncCoordinator.connection_output_dir()` without
    constructing a full sync coordinator just to resolve a path."""
    from hermes_arg_connector.fs import join_root

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
# It performs a real ADLS read (list connections, open each manifest, map each
# dataset) which can easily exceed the Container Apps probe's 1s timeout under
# real network latency, causing repeated probe failures and a
# CrashLoopBackOff that silently reverts traffic to an older revision. Cache
# the result with a short TTL so the probe never triggers a fresh remote read.
# The cache is keyed by the resolved `HERMES_HOME` root, because that root is
# resolved from the environment on every call and a value loaded for one root
# must never be served for another.
_SNAPSHOT_TABLES_CACHE_TTL_SECONDS = 30
_snapshot_tables_cache: dict[str, tuple[float, tuple[list[dict[str, list[dict]]], str]]] = {}


def _load_snapshot_tables() -> tuple[list[dict[str, list[dict]]], str]:
    """Load the mapped datasets for every registered synced connection.

    Cached per `HERMES_HOME` root with a short TTL (see module docstring above)
    so repeated calls (notably the health probe, hit every ~10s) don't each
    perform a fresh remote ADLS read.
    """
    from hermes_arg_connector.storage import DatasetStore

    root = hermes_home()
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
    for connection in connections:
        connection_root = _connection_dataset_dir(root, connection.connection_id)
        store = DatasetStore(connection_root)
        snapshot_dir = store.current_generation()
        if snapshot_dir is None:
            continue  # connection registered but never synced
        manifest_path = f"{snapshot_dir}/manifest.json"
        if store.is_remote:
            if not store.fs.exists(manifest_path):
                continue
            try:
                with store.fs.open(manifest_path, "rt") as handle:
                    manifest = json.loads(handle.read())
            except (OSError, json.JSONDecodeError):
                continue
        else:
            manifest_file = Path(manifest_path)
            if not manifest_file.exists():
                continue
            try:
                manifest = json.loads(manifest_file.read_text())
            except (OSError, json.JSONDecodeError):
                continue
        run_id = str(manifest.get("runId") or connection.connection_id)
        try:
            tables = mapper.load(snapshot_dir, run_id, fs=store.fs if store.is_remote else None)
        except Exception:  # noqa: BLE001, S112 - a malformed connection shouldn't take the API down
            continue
        tables_by_connection.append(tables)
        started_at = str(manifest.get("startedAt") or "")
        freshness = max(freshness, started_at)
    result = (tables_by_connection, freshness)
    _snapshot_tables_cache[cache_key] = (now, result)
    return result


def _load_semantic_snapshot() -> SemanticEngine | None:
    root = hermes_home()
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
    entities, _relationships, _freshness = _load_ontology_rows()
    if not entities:
        return None
    return NetworkIntelligenceService.from_rows(entities)


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


def _resolve_kb_to_cves(kb_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Resolve KB ids to real CVE ids via the public MSRC Security Update
    Guide feed, memoized with a TTL so repeated requests don't re-query MSRC
    for the same KBs. Returns an empty tuple for KBs MSRC has no CVE for
    (e.g. Servicing Stack Updates, which are commonly advisory-only) and an
    empty dict entirely on any network failure, so callers can safely fall
    back to the `KB-<kbId>` proxy identifier.
    """
    now = time.monotonic()
    resolved: dict[str, tuple[str, ...]] = {}
    to_fetch: list[str] = []
    for kb_id in kb_ids:
        cached = _kb_cve_cache.get(kb_id)
        if cached and now - cached[0] < _KB_CVE_CACHE_TTL_SECONDS:
            resolved[kb_id] = cached[1]
        else:
            to_fetch.append(kb_id)
    if to_fetch:
        try:
            updates = MsrcKbLookupConnector().fetch(tuple(to_fetch))
        except Exception:
            _LOGGER.warning("MSRC KB-to-CVE lookup failed; falling back to KB proxy ids", exc_info=True)
            updates = ()
        fetched_kbs = {update.kb_id for update in updates}
        for update in updates:
            _kb_cve_cache[update.kb_id] = (now, update.cve_ids)
            resolved[update.kb_id] = update.cve_ids
        for kb_id in to_fetch:
            if kb_id not in fetched_kbs:
                _kb_cve_cache[kb_id] = (now, ())
                resolved[kb_id] = ()
    return resolved


# Failed enrichment lookups (e.g. NVD 429 rate-limiting) are cached for a
# much shorter TTL than successes: long enough that the background refresh
# thread doesn't hammer a throttled upstream every cycle, short enough that
# real recovery is picked up well within a work day. `_cve_detail_cache`
# stores `{}` as the cached row for a negatively-cached id so callers keep
# their existing "no detail available" behavior for free.
_NEGATIVE_CACHE_TTL_SECONDS = 15 * 60


def _resolve_cve_details(cve_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    """Enrich real CVE ids with full detail (description, CVSS) from NVD,
    memoized with a TTL. Requires the `NVD_API_KEY` environment variable;
    returns no rows (and never raises) if it is unset or the request fails,
    so enrichment is always optional.
    """
    now = time.monotonic()
    rows: list[dict[str, Any]] = []
    to_fetch: list[str] = []
    for cve_id in cve_ids:
        cached = _cve_detail_cache.get(cve_id)
        if cached is None:
            to_fetch.append(cve_id)
            continue
        cached_at, cached_row = cached
        ttl = _KB_CVE_CACHE_TTL_SECONDS if cached_row else _NEGATIVE_CACHE_TTL_SECONDS
        if now - cached_at < ttl:
            if cached_row:
                rows.append(cached_row)
        else:
            to_fetch.append(cve_id)
    if to_fetch:
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
                _cve_detail_cache[cve_id] = (now, {})
            cves = ()
        for cve in cves:
            row = cve.to_dict()
            _cve_detail_cache[cve.cve_id] = (now, row)
            rows.append(row)
    return rows


# EPSS scores drift slowly (FIRST.org publishes new scores roughly daily) and
# the KEV catalog changes even less often, so both share the same long TTL
# used for the other public-feed enrichments above.
_epss_cache: dict[str, tuple[float, dict[str, float]]] = {}
_kev_cache: tuple[float, dict[str, dict[str, str]]] | None = None


def _resolve_epss_scores(cve_ids: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """Fetch EPSS exploitation-probability scores for `cve_ids` from
    FIRST.org, memoized with a TTL. Returns an empty dict (never raises) on
    any network failure so EPSS enrichment is always optional.
    """
    now = time.monotonic()
    scores: dict[str, dict[str, float]] = {}
    to_fetch: list[str] = []
    for cve_id in cve_ids:
        cached = _epss_cache.get(cve_id)
        if cached and now - cached[0] < _KB_CVE_CACHE_TTL_SECONDS:
            scores[cve_id] = cached[1]
        else:
            to_fetch.append(cve_id)
    if to_fetch:
        try:
            fetched = EpssScoreConnector().fetch_scores(tuple(to_fetch))
        except Exception:
            _LOGGER.warning("EPSS score lookup failed; CVEs will be surfaced without EPSS", exc_info=True)
            fetched = {}
        for cve_id in to_fetch:
            row = fetched.get(cve_id, {"epss_score": 0.0, "epss_percentile": 0.0})
            _epss_cache[cve_id] = (now, row)
            scores[cve_id] = row
    return scores


def _resolve_kev_catalog() -> dict[str, dict[str, str]]:
    """Fetch the full CISA KEV catalog, memoized with a TTL. Returns an empty
    dict (never raises) on any network failure so KEV enrichment is always
    optional; every CVE is simply treated as not-known-exploited.
    """
    global _kev_cache
    now = time.monotonic()
    if _kev_cache is not None and now - _kev_cache[0] < _KB_CVE_CACHE_TTL_SECONDS:
        return _kev_cache[1]
    try:
        catalog = KevCatalogConnector().fetch_catalog()
    except Exception:
        _LOGGER.warning("CISA KEV catalog lookup failed; KEV status will be unavailable", exc_info=True)
        catalog = _kev_cache[1] if _kev_cache is not None else {}
    _kev_cache = (now, catalog)
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
                }
            )
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
    kb_to_cves = _resolve_kb_to_cves(tuple({item["missing_kb"] for item in findings}))
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
    findings = expanded_findings

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

    service = VulnerabilityIntelligenceService.from_rows(
        findings=findings,
        security_updates=[
            {"kb_id": item["missing_kb"], "cve_ids": [item["cve_id"]]} for item in findings
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


def _load_vulnerability_service() -> VulnerabilityIntelligenceService | None:
    tables, freshness = _load_snapshot_tables()
    return _build_vulnerability_service(tables, freshness)


# Local development keeps exceptions in memory. Production configures
# HERMES_DATABASE_URL, which switches these helpers to a shared PostgreSQL table
# so exceptions survive restarts and remain consistent across replicas.
_risk_exception_store: dict[str, RiskException] = {}
_RISK_EXCEPTION_DDL = """
CREATE TABLE IF NOT EXISTS risk_exceptions (
    exception_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL
)
"""


def _risk_exception_dsn() -> str:
    return os.environ.get("HERMES_DATABASE_URL", "").strip()


def _risk_exception_connection():
    import psycopg

    return psycopg.connect(_risk_exception_dsn())


def _ensure_risk_exception_table(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(_RISK_EXCEPTION_DDL)


def list_risk_exceptions() -> list[RiskException]:
    if _risk_exception_dsn():
        with _risk_exception_connection() as connection:
            _ensure_risk_exception_table(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT payload FROM risk_exceptions ORDER BY exception_id"
                )
                rows = cursor.fetchall()
        return [
            RiskException(**(json.loads(payload) if isinstance(payload, str) else payload))
            for (payload,) in rows
        ]
    return list(_risk_exception_store.values())


def add_risk_exception(exception: RiskException) -> None:
    if _risk_exception_dsn():
        with _risk_exception_connection() as connection:
            _ensure_risk_exception_table(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO risk_exceptions (exception_id, payload) "
                    "VALUES (%s, %s::jsonb) "
                    "ON CONFLICT (exception_id) DO UPDATE SET payload = EXCLUDED.payload",
                    (exception.exception_id, json.dumps(exception.to_dict())),
                )
        return
    _risk_exception_store[exception.exception_id] = exception


def revoke_risk_exception(exception_id: str) -> bool:
    if _risk_exception_dsn():
        with _risk_exception_connection() as connection:
            _ensure_risk_exception_table(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM risk_exceptions WHERE exception_id = %s",
                    (exception_id,),
                )
                removed = cursor.rowcount > 0
        return removed
    return _risk_exception_store.pop(exception_id, None) is not None



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
        candidate = FoundryPromptAgent.from_env()
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


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().casefold() in {"1", "true", "yes", "on"}


def _fabric_is_configured() -> bool:
    return bool(os.environ.get(ENV_FABRIC_CONFIG, "").strip()) or (
        _truthy("HERMES_ENABLE_FABRIC")
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
            os.environ.get("HERMES_FABRIC_SOURCE_DATA_ROOT", "/data/fabric-source")
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


def _fabric_network_service(runtime: FabricRuntime) -> NetworkIntelligenceService:
    snapshot = runtime.service.semantic_snapshot()
    return NetworkIntelligenceService.from_rows(snapshot["entities"])


def _fabric_vulnerability_service(
    runtime: FabricRuntime,
) -> VulnerabilityIntelligenceService | None:
    semantic_snapshot = runtime.service.semantic_snapshot()
    patch = runtime.service.patch_intelligence_snapshot()
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
    semantic = runtime.semantic_engine()
    network = _fabric_network_service(runtime)
    return _build_vulnerability_service(
        [{"silver_patch_findings": findings}],
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


def _fabric_remediation_planner(runtime: FabricRuntime) -> Any:
    return getattr(runtime.operations_agent(), "remediation_planner", None)


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


def _load_inventory_service() -> Any:
    """Load inventory only from an active generation (or explicit fixture)."""
    from hermes_arg_connector.storage import DatasetStore
    from intelligence.inventory.service import InventoryService
    from intelligence.inventory.eol_repository import LocalEOLCatalogRepository
    from intelligence.inventory.eol_review import EOLReviewService

    eol_review = EOLReviewService(
        repository=LocalEOLCatalogRepository(Path(hermes_home()) / "state" / "eol_catalog.json")
    )
    fixture = os.environ.get("HERMES_INVENTORY_FIXTURE", "").strip()
    if fixture:
        return InventoryService.from_fixture(fixture, eol_review=eol_review)
    return InventoryService.from_store(DatasetStore(hermes_home()), eol_review=eol_review)


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
            # Downstream intelligence requires a real snapshot timestamp. Surface
            # this as an explicit degraded provider rather than letting the
            # constructor raise an opaque timestamp error.
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
            "network": lambda: with_fabric(_fabric_network_service),
            "vulnerability": lambda: with_fabric(_fabric_vulnerability_service),
            "incidents": lambda: with_fabric(_fabric_incident_engine),
            "remediation": lambda: with_fabric(_fabric_remediation_planner),
        }
    elif mode == "demo":
        loaders = {
            "semantic": _load_semantic_snapshot,
            "network": _load_network_service,
            "vulnerability": _load_vulnerability_service,
            "incidents": _load_incident_engine,
            "remediation": lambda: None,
        }
    else:
        loaders = {name: (lambda: None) for name in (
            "semantic",
            "network",
            "vulnerability",
            "incidents",
            "remediation",
        )}

    foundry_configured = bool(
        os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
        and os.environ.get("FOUNDRY_AGENT_NAME", "").strip()
    )
    specs = {
        name: ProviderSpec(loader=loader, configured=True, required=True)
        for name, loader in loaders.items()
    }
    specs["inventory"] = ProviderSpec(
        loader=_load_inventory_service,
        configured=True,
        required=False,
    )
    specs["copilot"] = ProviderSpec(
        loader=_load_foundry_agent,
        configured=foundry_configured,
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


def build_context() -> ApiContext:
    """Assemble the default context from the environment."""
    onboarding = _onboarding_service()
    providers = _build_provider_runtime(onboarding)
    return ApiContext(
        onboarding=onboarding,
        authenticator=build_authenticator(),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        # Rebuilt on every call (not baked in once here) so a freshly synced
        # connection is picked up on the next request without restarting the
        # API, per the provider contracts in `dependencies.py`.
        semantic_provider=lambda: providers.get("semantic", optional=True),
        incident_provider=lambda: providers.get("incidents", optional=True),
        remediation_provider=lambda: providers.get("remediation", optional=True),
        network_provider=lambda: providers.get("network", optional=True),
        vulnerability_provider=lambda: providers.get("vulnerability", optional=True),
        vulnerability_live_lookup=_lookup_live_cve,
        risk_exception_list=list_risk_exceptions,
        risk_exception_add=add_risk_exception,
        risk_exception_revoke=revoke_risk_exception,
        foundry_agent_provider=_load_foundry_agent,
        inventory_provider=lambda: providers.get("inventory", optional=True),
        provider_runtime=providers,
    )
