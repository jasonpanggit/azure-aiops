"""Shared inventory refresh runner.

Extracted from the ``inventory-refresh`` CLI command so the exact same
refresh logic can be invoked either from the command line or from an
authenticated HTTP trigger (used by a Fabric Data Pipeline Web activity).
Inventory remains the sole owner of acquisition/publication; this module
only provides two entry points onto the same `InventoryPipeline` run.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .config import ConnectorConfig


def run_inventory_refresh(
    config_path: str,
    *,
    fabric_config_path: str = "",
    connection_id: str = "",
) -> dict[str, Any]:
    """Run one inventory refresh and return the publication manifest.

    Mirrors the ``hermes-arg-connector inventory-refresh`` CLI command so
    both entry points execute identical acquisition/publication logic.
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

    from .azure import AzureCliArgClient, AzureMcpClient
    from .logs import AzureMonitorLogsClient
    from .source import AzureResourceGraphSource

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
    logs_client = None
    if config.logs_workspaces:
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
