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
from .credentials import CredentialResolver, SecretWriter, default_secret_provider
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

    ``fabric_config_path``, when set, attaches a ``publish_factory`` to the
    sync coordinator so that a successful connection sync is immediately
    followed by the same merge + ontology + Fabric-publish step
    ``aiops-inventory inventory-refresh`` runs from the CLI/cron path -- i.e. an
    interactive "Sync" click on one connection produces Fabric tables for
    that connection only.
    Leaving it empty keeps this call ingestion-only (used by the CLI, and by
    tests that don't want a Fabric publish attempted). ``config_path`` is the
    on-disk connector config path used to re-load a fresh
    :class:`ConnectorConfig` inside the refresh run (mirrors how the CLI and
    `/inventory/refresh` invoke `run_inventory_refresh_all_connections`); it
    is only required alongside `fabric_config_path`.
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
    if fabric_config_path:
        coordinator.publish_factory = lambda connection: _InventoryRefreshRunner(
            config_path, fabric_config_path, service, connection.connection_id
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
        max_workers=scoped.max_query_workers,
        management_group_ids=(),
    )
    logs_client = AzureMonitorLogsClient(
        (resolver or CredentialResolver(provider=default_secret_provider())).build(
            connection.credential
        ),
        limits=LogsQueryLimits(timeout_seconds=scoped.command_timeout_seconds),
    )
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
        max_workers=scoped.max_query_workers,
        management_group_ids=(),
    )
    logs_client = AzureMonitorLogsClient(
        (resolver or CredentialResolver(provider=default_secret_provider())).build(
            connection.credential
        ),
        limits=LogsQueryLimits(timeout_seconds=scoped.command_timeout_seconds),
    )
    return InventoryPipeline(scoped, source=source, logs_client=logs_client)


def build_connection_arg_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureResourceGraphClient:
    """Build an ARG client authenticated with one connection's service principal."""
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    return AzureResourceGraphClient(
        credential_resolver.build(connection.credential),
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
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    return AzureCostManagementClient(
        credential_resolver.build(connection.credential),
        timeout=config.command_timeout_seconds,
        max_workers=config.max_query_workers,
    )


def build_connection_monitor_metrics_client(
    config: ConnectorConfig,
    connection: SubscriptionConnection,
    resolver: CredentialResolver | None = None,
) -> AzureMonitorMetricsClient:
    """Build a Monitor Metrics client authenticated with one connection SPN."""
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    return AzureMonitorMetricsClient(
        credential_resolver.build(connection.credential),
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
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    return AzureMonitorLogsClient(
        credential_resolver.build(connection.credential),
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
    credential_resolver = resolver or CredentialResolver(provider=default_secret_provider())
    return AzureMonitorPrometheusClient(
        credential_resolver.build(connection.credential),
        timeout=config.command_timeout_seconds,
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


class _InventoryRefreshRunner:
    """Adapts `run_inventory_refresh_all_connections` to the coordinator's
    `publish_factory` contract (an object with a no-arg ``run()``).

    A small class rather than a bare closure so the config paths are
    captured once at service-build time; the underlying function re-reads
    the connector config and registry itself on every call.
    """

    def __init__(
        self,
        config_path: str,
        fabric_config_path: str,
        service: SubscriptionOnboardingService,
        connection_id: str,
    ) -> None:
        self._config_path = config_path
        self._fabric_config_path = fabric_config_path
        self._service = service
        self._connection_id = connection_id

    def run(self) -> dict[str, Any]:
        from api.inventory_orchestration import (
            run_inventory_refresh_all_connections,
        )

        inventory = run_inventory_refresh_all_connections(
            self._config_path,
            # Publish only after the ontology merge below has completed.
            fabric_config_path="",
            connection_id=self._connection_id,
        )
        if inventory.get("status") == "failed":
            raise RuntimeError(
                f"Inventory refresh failed for connection '{self._connection_id}'"
            )

        from fabric.config import FabricRuntimeConfig
        from fabric.runtime import build_runtime
        from onboarding.activation import publish_combined_snapshot

        fabric_config = FabricRuntimeConfig.load(self._fabric_config_path)
        combined = publish_combined_snapshot(
            self._service,
            [self._connection_id],
            fabric_config.source_data_root,
        )
        publication = build_runtime(fabric_config).service.sync()
        return {
            "inventory": inventory,
            "combined_snapshot": combined,
            "fabric_publication": {
                "run_id": publication.run_id,
                "source_run_id": publication.source_run_id,
                "status": publication.status,
                "tables": list(publication.tables),
            },
        }


__all__ = [
    "build_connection_arg_client",
    "build_connection_cost_client",
    "build_connection_ingestion",
    "build_connection_inventory_pipeline",
    "build_connection_logs_client",
    "build_connection_monitor_metrics_client",
    "build_connection_prometheus_client",
    "build_onboarding_service",
    "connection_context",
]
