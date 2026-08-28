"""API-owned inventory orchestration.

This module contains the multi-connection refresh used by API-triggered sync.
The legacy Hermes connector remains as a compatibility surface while callers
move to this neutral API module.
"""

from __future__ import annotations

import dataclasses
from typing import Any


def run_inventory_refresh_all_connections(
    config_path: str,
    *,
    fabric_config_path: str = "",
    registry_root: str = "",
    connection_id: str = "",
) -> dict[str, Any]:
    """Refresh, merge, and optionally publish registered connections."""
    from onboarding.config import ConnectorConfig
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
        return {"status": "failed", "connections": connection_results}

    from fabric.config import FabricRuntimeConfig
    from fabric.runtime import build_runtime
    from intelligence.inventory.combine import (
        publish_combined_inventory_snapshot,
        republish_combined_snapshot_to_fabric,
    )

    combined_manifest = publish_combined_inventory_snapshot(
        connection_output_dirs,
        config.output_dir,
        connection_ids=succeeded,
    )
    inventory_publication: dict[str, Any] | None = None
    fabric_publication: dict[str, Any] | None = None
    if fabric_config_path:
        # Two distinct table families are produced from the same combined
        # snapshot and both are required for a complete lakehouse:
        # the `inventory_*` contract tables (written directly from the
        # merged datasets) and the bronze/silver/ontology/metadata tables
        # produced by the full Fabric sync. Publishing only one leaves the
        # other family missing.
        inventory_publication = republish_combined_snapshot_to_fabric(
            config.output_dir,
            fabric_config_path,
        )
        fabric_config = FabricRuntimeConfig.load(fabric_config_path)
        runtime = build_runtime(
            dataclasses.replace(
                fabric_config,
                source_data_root=config.output_dir,
            )
        )
        publication = runtime.service.sync()
        fabric_publication = {
            "runId": publication.run_id,
            "sourceRunId": publication.source_run_id,
            "status": publication.status,
            "fabricTables": list(publication.tables),
        }

    return {
        "status": "completed" if len(succeeded) == len(connections) else "partial",
        "connections": connection_results,
        "combined_manifest": combined_manifest,
        "inventory_publication": inventory_publication,
        "fabric_publication": fabric_publication,
    }
