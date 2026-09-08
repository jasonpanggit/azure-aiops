"""Shared inventory refresh runner.

Extracted from the ``inventory-refresh`` CLI command so the exact same
refresh logic can be invoked either from the command line or from an
authenticated HTTP trigger (used by a Fabric Data Pipeline Web activity).
Inventory remains the sole owner of acquisition/publication; this module
provides both a single-config entry point (for local/dev use, or when only
one Azure AD app/subscription is configured) and a multi-connection
orchestrator that fans out across every registered ``SubscriptionConnection``
so production rollouts spanning many subscriptions each get their own
acquisition run, merged into one Fabric-facing snapshot.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from api.inventory_orchestration import run_inventory_refresh_all_connections
from onboarding.config import ConnectorConfig


def _legacy_run_inventory_refresh_all_connections(
    config_path: str,
    *,
    fabric_config_path: str = "",
    registry_root: str = "",
    connection_id: str = "",
) -> dict[str, Any]:
    """Refresh inventory for registered subscription connections.

    Runs one ``InventoryPipeline`` per active :class:`SubscriptionConnection`,
    scoped to that connection's subscription and isolated dataset root (the
    same ``connections/<slug>/`` convention used by onboarding's ARG/cost
    ingestion), then merges all connections' inventory datasets into one
    deduplicated snapshot and -- if a Fabric config is supplied -- publishes
    that merged snapshot to Fabric exactly once. A failure acquiring one
    connection's inventory does not block the others. When ``connection_id`` is
    supplied, only that active connection is refreshed and published.
    """
    from onboarding.credentials import CredentialResolver, default_secret_provider
    from onboarding.registry import ConnectionRegistry
    from onboarding.runtime import build_connection_inventory_pipeline

    config = ConnectorConfig.load(config_path)
    root = registry_root or str(config.output_dir)
    registry = ConnectionRegistry(root)
    if connection_id:
        connections = [registry.get(connection_id)]
        if not connections[0].is_active:
            raise RuntimeError(f"Connection '{connection_id}' is disabled")
    else:
        connections = registry.list(include_disabled=False)
    if not connections:
        raise RuntimeError("No active subscription connections are registered")

    resolver = CredentialResolver(provider=default_secret_provider())
    connection_output_dirs: dict[str, str] = {}
    connection_results: dict[str, Any] = {}
    for connection in connections:
        pipeline = build_connection_inventory_pipeline(config, connection, resolver)
        connection_output_dirs[connection.connection_id] = str(pipeline.store.root)
        try:
            result = pipeline.refresh()
        except Exception as exc:  # noqa: BLE001 - isolate one connection's failure
            connection_results[connection.connection_id] = {
                "status": "failed",
                "error": str(exc),
            }
            continue
        connection_results[connection.connection_id] = {
            "status": "completed",
            "manifest": result.manifest,
        }

    succeeded = [
        connection_id
        for connection_id, outcome in connection_results.items()
        if outcome["status"] == "completed"
    ]
    if not succeeded:
        return {
            "status": "failed",
            "connections": connection_results,
        }

    from intelligence.inventory.combine import (
        publish_combined_inventory_snapshot,
        republish_combined_snapshot_to_fabric,
    )

    combined_manifest = publish_combined_inventory_snapshot(
        connection_output_dirs,
        config.output_dir,
        connection_ids=succeeded,
    )

    fabric_publication: dict[str, Any] | None = None
    if fabric_config_path:
        fabric_publication = republish_combined_snapshot_to_fabric(
            config.output_dir,
            fabric_config_path,
            retain_raw_queries=config.retain_raw_queries,
            source_run_id=str(combined_manifest["runId"]),
        )

    return {
        "status": "completed" if len(succeeded) == len(connections) else "partial",
        "connections": connection_results,
        "combined_manifest": combined_manifest,
        "fabric_publication": fabric_publication,
    }


def run_inventory_refresh(
    config_path: str,
    *,
    fabric_config_path: str = "",
    connection_id: str = "",
) -> dict[str, Any]:
    """Run one single-config inventory refresh and return the manifest.

    Mirrors the ``aiops-inventory inventory-refresh`` CLI command so
    both entry points execute identical acquisition/publication logic. This
    entry point targets exactly the subscriptions listed in ``config_path``
    (or all subscriptions visible to the configured credential, if none are
    listed) -- it does not fan out across the onboarding connection
    registry. Use :func:`run_inventory_refresh_all_connections` for
    production rollouts spanning multiple registered subscriptions.
    """
    from fabric.auth import build_credential, build_delta_storage_options
    from fabric.config import FabricRuntimeConfig
    from fabric.fabric_client import FabricClient
    from fabric.lakehouse_manager import LakehouseManager
    from fabric.workspace_manager import WorkspaceManager
    from intelligence.inventory.fabric_publication import InventoryFabricPublisher
    from intelligence.inventory.onelake_publication import InventoryOneLakePublisher
    from intelligence.inventory.pipeline import InventoryPipeline
    from storage.datasets import DatasetStore
    from storage.delta_writer import DeltaWriter
    from storage.onelake_writer import OneLakeWriter

    from .azure_clients import AzureCliArgClient, AzureMcpClient
    from .discovery_source import AzureResourceGraphSource
    from .monitor_logs import AzureMonitorLogsClient

    config = ConnectorConfig.load(config_path)
    if connection_id:
        config = replace(
            config,
            connection_context={
                **dict(config.connection_context),
                "connection_id": connection_id,
            },
        )
    source = AzureResourceGraphSource(
        mcp=AzureMcpClient(
            command_prefix=config.azure_mcp_command,
            timeout=config.command_timeout_seconds,
        ),
        arg=AzureCliArgClient(
            page_size=config.page_size,
            max_pages=config.max_pages,
            timeout=config.command_timeout_seconds,
        ),
        tenant_id=config.tenant_id,
        max_workers=config.max_query_workers,
        management_group_ids=config.management_groups,
    )
    from azure.identity import DefaultAzureCredential

    logs_client = AzureMonitorLogsClient(DefaultAzureCredential())
    publisher = None
    if fabric_config_path:
        fabric_config = FabricRuntimeConfig.load(fabric_config_path)
        if fabric_config.local_onelake_root is not None:
            onelake = OneLakeWriter(
                fabric_config.workspace_id or fabric_config.workspace_name,
                fabric_config.lakehouse_id or fabric_config.lakehouse_name,
                table_schema=fabric_config.table_schema,
                local_root=fabric_config.local_onelake_root,
            )
            delta_writer = DeltaWriter()
        else:
            credential = build_credential(fabric_config.auth)
            client = FabricClient(credential)
            workspace = WorkspaceManager(client).resolve(
                workspace_id=fabric_config.workspace_id,
                workspace_name=fabric_config.workspace_name,
            )
            lakehouse = LakehouseManager(client, str(workspace["id"])).resolve(
                lakehouse_id=fabric_config.lakehouse_id,
                lakehouse_name=fabric_config.lakehouse_name,
                create_if_missing=fabric_config.create_lakehouse_if_missing,
                enable_schemas=bool(fabric_config.table_schema),
            )
            storage_options = build_delta_storage_options(credential)
            onelake = OneLakeWriter(
                str(workspace["id"]),
                str(lakehouse["id"]),
                workspace_name=str(workspace.get("displayName") or ""),
                lakehouse_name=str(lakehouse.get("displayName") or ""),
                table_schema=fabric_config.table_schema,
                credential=credential,
                storage_options=storage_options,
            )
            delta_writer = DeltaWriter(
                storage_options=storage_options,
                storage_options_provider=lambda: build_delta_storage_options(credential),
            )
        publisher = InventoryFabricPublisher(
            DatasetStore(config.output_dir, retain_raw_queries=config.retain_raw_queries),
            onelake=InventoryOneLakePublisher(onelake, delta_writer=delta_writer),
        )
    result = InventoryPipeline(
        config,
        source=source,
        logs_client=logs_client,
        publisher=publisher,
    ).refresh()
    return result.manifest


__all__ = ["run_inventory_refresh", "run_inventory_refresh_all_connections"]
