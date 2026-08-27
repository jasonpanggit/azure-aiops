"""Wiring that binds onboarding to connector config and ingestion.

Keeps the service transport-agnostic: the CLI (and later an API) build the
same object graph through :func:`build_onboarding_service`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from hermes_arg_connector.azure import (
    AzureCostManagementClient,
    AzureResourceGraphClient,
)
from hermes_arg_connector.config import ConnectorConfig
from hermes_arg_connector.logs import AzureMonitorLogsClient, LogsQueryLimits
from hermes_arg_connector.service import IngestionService
from hermes_arg_connector.source import AzureResourceGraphSource, CostActualsSource
from ontology.subscription_connection import SubscriptionConnection
from storage.fs import join_root

from .credentials import CredentialResolver, SecretWriter, default_secret_provider
from .metadata import BusinessMetadata
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
) -> SubscriptionOnboardingService:
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
    return SubscriptionOnboardingService(
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
    "build_connection_ingestion",
    "build_connection_inventory_pipeline",
    "build_onboarding_service",
    "connection_context",
]
