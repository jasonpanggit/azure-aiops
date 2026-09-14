"""Wiring that binds onboarding to connector config and ingestion.

Keeps the service transport-agnostic: the CLI (and later an API) build the
same object graph through :func:`build_onboarding_service`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from onboarding.config import ConnectorConfig
from ontology.subscription_connection import SubscriptionConnection
from storage.fs import join_root

from .azure_clients import (
    AzureCostManagementClient,
    AzureMonitorMetricsClient,
    AzureResourceGraphClient,
)
from .credentials import (
    CredentialResolver,
    SecretNotFoundError,
    SecretWriter,
    default_secret_provider,
)
from .discovery_source import AzureResourceGraphSource, CostActualsSource
from .ingestion_service import IngestionService
from .metadata import BusinessMetadata
from .monitor_logs import AzureMonitorLogsClient, LogsQueryLimits
from .monitor_prometheus import AzureMonitorPrometheusClient
from .registry import ConnectionRegistry
from .service import SubscriptionOnboardingService
from .sync import ConnectionSyncCoordinator
from .validation import ArgConnectionProbe, ConnectionValidator


def build_onboarding_service(
    config: ConnectorConfig,
    *,
    resolver: CredentialResolver | None = None,
    secret_writer: SecretWriter | None = None,
    arg_client: Any = None,
    config_path: str = "",
    fabric_config_path: str = "",
) -> SubscriptionOnboardingService:
    """Build the onboarding service, wired for connection-scoped sync.

    ``config_path`` and ``fabric_config_path`` remain accepted for call-site
    compatibility, but this runtime no longer constructs an API-owned Fabric
    publisher. Manual ontology refresh is durable intake only; the scheduled
    coordinator dispatches through the separately authorized publisher.
    Connection ingestion remains available through ``sync``/``sync_async``.
    """
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    arg_factory = (
        (lambda _connection: arg_client)
        if arg_client is not None
        else lambda connection: build_connection_arg_client(
            config, connection, credential_resolver
        )
    )
    coordinator = ConnectionSyncCoordinator(
        config.output_dir,
        ingestion_factory=lambda connection: build_connection_ingestion(
            config, connection, credential_resolver
        ),
        publish_timeout_seconds=config.publish_timeout_seconds,
    )
    service = SubscriptionOnboardingService(
        config.output_dir,
        registry=ConnectionRegistry(config.output_dir),
        validator=ConnectionValidator(
            probe=ArgConnectionProbe(
                resolver=credential_resolver,
                arg_client_factory=arg_factory,
            )
        ),
        sync_coordinator=coordinator,
        resolver=credential_resolver,
        secret_writer=secret_writer,
    )
    return service


def build_connection_ingestion(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> IngestionService:
    """Ingestion scoped to exactly one connection's subscription and dataset root."""
    scoped = dataclasses.replace(
        config,
        output_dir=join_root(str(config.output_dir), "connections", _slug(connection.connection_id)),
        subscriptions=(connection.subscription_id,),
        management_groups=(),
        tenant_id=connection.tenant_id,
        connection_context=connection_context(connection),
    )
    source = AzureResourceGraphSource(
        mcp=None,
        arg=build_connection_arg_client(scoped, connection, resolver),
        tenant_id=connection.tenant_id,
        connection_id=connection.connection_id,
        max_workers=scoped.max_query_workers,
        management_group_ids=(),
    )
    # The connection-scoped factory is the sole Logs authority. It supplies
    # the credential and hard query limits; IngestionService supplies only
    # server-discovered workspaces to the fixed Container Insights methods.
    logs_client = build_connection_logs_client(scoped, connection, resolver)
    cost_source = (
        CostActualsSource(cost=build_connection_cost_client(scoped, connection, resolver))
        if scoped.cost_management_enabled
        else None
    )
    return IngestionService(
        scoped,
        source=source,
        cost_source=cost_source,
        logs_client=logs_client,
    )


def build_connection_inventory_pipeline(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> Any:
    """Build an ``InventoryPipeline`` scoped to exactly one connection.

    Mirrors :func:`build_connection_ingestion`: the pipeline is scoped to the
    connection's subscription and writes into that connection's isolated
    ``connections/<slug>/`` dataset root. No Fabric publisher is attached here
    -- only the merged, multi-connection snapshot should be published to
    Fabric, so each connection's raw run stays purely local/staging.
    """
    from intelligence.inventory.pipeline import InventoryPipeline

    scoped = dataclasses.replace(
        config,
        output_dir=join_root(str(config.output_dir), "connections", _slug(connection.connection_id)),
        subscriptions=(connection.subscription_id,),
        management_groups=(),
        tenant_id=connection.tenant_id,
        connection_context=connection_context(connection),
    )
    source = AzureResourceGraphSource(
        mcp=None,
        arg=build_connection_arg_client(scoped, connection, resolver),
        tenant_id=connection.tenant_id,
        connection_id=connection.connection_id,
        max_workers=scoped.max_query_workers,
        management_group_ids=(),
    )
    logs_client = build_connection_logs_client(scoped, connection, resolver)
    return InventoryPipeline(scoped, source=source, logs_client=logs_client)


def build_connection_arg_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureResourceGraphClient:
    """Build an ARG client authenticated with one connection's service principal."""
    return AzureResourceGraphClient(
        build_connection_credential(connection, resolver),
        page_size=config.page_size,
        max_pages=config.max_pages,
        timeout=config.command_timeout_seconds,
    )


def build_connection_cost_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureCostManagementClient:
    """Build a Cost Management client authenticated with one connection SPN."""
    return AzureCostManagementClient(
        build_connection_credential(connection, resolver),
        timeout=config.command_timeout_seconds,
        max_workers=config.max_query_workers,
    )


def build_connection_monitor_metrics_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureMonitorMetricsClient:
    """Build a Monitor Metrics client authenticated with one connection SPN."""
    return AzureMonitorMetricsClient(
        build_connection_credential(connection, resolver),
        timeout=config.command_timeout_seconds,
    )


def build_connection_logs_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureMonitorLogsClient:
    """Build a Logs Query client authenticated with one connection SPN.

    Mirrors :func:`build_connection_monitor_metrics_client` but targets the
    Azure Monitor Logs Query API (KQL), used for classic guest performance
    counters (memory/disk-free) that the platform Metrics API cannot supply.
    """
    return AzureMonitorLogsClient(
        build_connection_credential(connection, resolver),
        limits=LogsQueryLimits(timeout_seconds=config.command_timeout_seconds),
    )


def build_connection_prometheus_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureMonitorPrometheusClient:
    """Build an Azure Monitor Prometheus client authenticated with one connection SPN.

    Mirrors :func:`build_connection_logs_client` but targets the managed-
    Prometheus PromQL API, used for OpenTelemetry-based guest metrics
    (memory/disk-free) that land in an Azure Monitor Workspace instead of a
    Log Analytics workspace.
    """
    return AzureMonitorPrometheusClient(
        build_connection_credential(connection, resolver),
        timeout=config.command_timeout_seconds,
    )


def build_connection_credential(
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> Any:
    """Resolve one subscription connection's service-principal credential."""
    credential = connection.credential
    if credential is None or credential.kind != "service_principal":
        raise SecretNotFoundError(
            f"Subscription connection '{connection.connection_id}' requires a "
            "service_principal credential"
        )
    credential_resolver = resolver or CredentialResolver(
        provider=default_secret_provider()
    )
    return credential_resolver.build(credential)


def connection_cache_identity(connection: SubscriptionConnection) -> tuple[str, ...]:
    """Return the complete non-secret identity used to partition live-data caches."""
    credential = connection.credential
    return (
        str(connection.tenant_id).casefold(),
        str(connection.subscription_id).casefold(),
        str(connection.connection_id).casefold(),
        str(getattr(credential, "credential_id", "") or "").casefold(),
        str(getattr(credential, "kind", "") or "").casefold(),
        str(getattr(credential, "tenant_id", "") or "").casefold(),
        str(getattr(credential, "client_id", "") or "").casefold(),
        str(getattr(credential, "secret_ref", "") or ""),
    )


def connection_context(connection: SubscriptionConnection) -> dict[str, str]:
    """Connection identity and business metadata stamped onto every ingested row.

    This is what allows the ontology layer to emit ``SubscriptionConnection`` and
    ``ConnectionHealth`` entities from real ingestion, and what supplies the
    ``mapped_to``/``supports`` lineage edges to Environment and Business Service.
    """
    business = BusinessMetadata.from_mapping(connection.metadata.get("business") or {})
    context: dict[str, str] = {
        "connection_id": connection.connection_id,
        "connection_name": connection.name or connection.connection_id,
    }
    health = getattr(connection.health, "status", "") if connection.health else ""
    optional = {
        "connection_health_status": health,
        "environment_name": business.environment,
        "business_service_name": business.business_service,
        "application_name": business.application,
        "owner_name": business.project_owner,
        "support_team_name": business.support_team,
        "criticality": business.criticality,
        "cost_center": business.cost_center,
    }
    context.update({key: str(value) for key, value in optional.items() if value})
    return context


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value)).strip("-")


__all__ = [
    "build_connection_arg_client",
    "build_connection_cost_client",
    "build_connection_credential",
    "build_connection_ingestion",
    "build_connection_inventory_pipeline",
    "build_connection_logs_client",
    "build_connection_monitor_metrics_client",
    "build_connection_prometheus_client",
    "build_onboarding_service",
    "connection_cache_identity",
    "connection_context",
]
