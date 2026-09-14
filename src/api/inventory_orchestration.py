"""API-owned inventory orchestration.

This module contains the multi-connection refresh used by API-triggered sync.
It is the single entry point for inventory refresh; the standalone connector
package it replaced has been removed.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger(__name__)


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
    from onboarding.runtime import (
        build_connection_ingestion,
        build_connection_inventory_pipeline,
    )
    from onboarding.service import SubscriptionOnboardingService
    from onboarding.sync import ConnectionSyncCoordinator

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
    # ``registry`` (this module's ``root``) and the connection dataset
    # storage root (``config.output_dir``, used by
    # ``build_connection_inventory_pipeline``/``build_connection_ingestion``)
    # may legitimately differ, so ``sync_coordinator`` must be rooted at
    # ``config.output_dir`` -- matching where ingestion actually writes --
    # while ``registry`` stays pointed at this module's real registry.
    onboarding_service = SubscriptionOnboardingService(
        config.output_dir,
        registry=registry,
        resolver=resolver,
        sync_coordinator=ConnectionSyncCoordinator(
            config.output_dir,
            ingestion_factory=lambda connection: build_connection_ingestion(
                config, connection, resolver
            ),
        ),
    )
    connection_output_dirs: dict[str, str] = {}
    connection_results: dict[str, Any] = {}
    max_workers = max(1, min(config.max_query_workers, len(connections)))
    started = time.monotonic()

    def refresh_connection(connection) -> tuple[str, str, dict[str, Any]]:
        connection_started = time.monotonic()
        try:
            pipeline = build_connection_inventory_pipeline(config, connection, resolver)
            result = pipeline.refresh()
            # The narrow inventory pipeline above only acquires OS/software/
            # PaaS-resource observations (feeds the `inventory_*` contract
            # tables). It never writes `entities/*.jsonl`, which is what
            # `InventoryDatasetMapper` (below) reads to build every
            # bronze_*/silver_* table (bronze_resources, bronze_advisor,
            # bronze_cost_actuals, etc.). Without this second, full ARG
            # discovery run, those tables silently end up with 0 rows even
            # though the sync reports "succeeded". Reuses the same
            # per-connection ingestion the interactive "Sync" button runs.
            onboarding_service.sync(connection.connection_id, mode="manual")
        except Exception as exc:  # noqa: BLE001 - isolate one connection's failure
            outcome = {"status": "failed", "error": str(exc)}
            output_dir = ""
        else:
            outcome = {"status": "completed", "manifest": result.manifest}
            # DatasetStore.root is fsspec's scheme-less internal path for
            # remote stores. Preserve the configured URI so the merge opens
            # OneLake rather than treating that path as a local directory.
            output_dir = str(getattr(pipeline.store, "uri_root", pipeline.store.root))
        return (
            connection.connection_id,
            output_dir,
            {
                **outcome,
                "_duration_seconds": round(time.monotonic() - connection_started, 3),
            },
        )

    # Acquisition is independently scoped per connection, so it can run in
    # parallel. Merge and Fabric publication below remain single-writer steps.
    with ThreadPoolExecutor(
        max_workers=max_workers, thread_name_prefix="inventory-connection"
    ) as executor:
        futures = [
            executor.submit(refresh_connection, connection)
            for connection in connections
        ]
        for future in as_completed(futures):
            connection_id, output_dir, outcome = future.result()
            connection_output_dirs[connection_id] = output_dir
            connection_results[connection_id] = outcome

    for outcome in connection_results.values():
        duration = outcome.pop("_duration_seconds", None)
        if duration is not None:
            logger.info("inventory_connection_refresh duration_seconds=%s", duration)
    logger.info(
        "inventory_connections_refresh duration_seconds=%s connections=%s workers=%s",
        round(time.monotonic() - started, 3),
        len(connections),
        max_workers,
    )

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
    from onboarding.activation import publish_combined_snapshot

    combined_manifest = publish_combined_inventory_snapshot(
        connection_output_dirs,
        config.output_dir,
        connection_ids=succeeded,
    )
    inventory_publication: dict[str, Any] | None = None
    fabric_publication: dict[str, Any] | None = None
    entities_manifest: dict[str, Any] | None = None
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
            source_run_id=str(combined_manifest["runId"]),
        )
        fabric_config = FabricRuntimeConfig.load(fabric_config_path)

        # The bronze/silver/gold family is built from `entities/*.jsonl`
        # (written per-connection above by ``onboarding_service.sync``), not
        # from ``combined_manifest`` (which only carries the narrow
        # inventory/os/software datasets). Merge a separate,
        # entities-aware combined snapshot -- mirroring
        # ``onboarding.activation.activate_runtime`` -- and replay *that*
        # generation into the Fabric sync instead.
        entities_manifest = publish_combined_snapshot(
            onboarding_service,
            succeeded,
            config.output_dir,
        )
        runtime = build_runtime(
            dataclasses.replace(
                fabric_config,
                source_data_root=config.output_dir,
            )
        )
        requested_subscriptions = sorted(
            {
                str(connection.subscription_id)
                for connection in connections
                if connection.connection_id in succeeded and connection.subscription_id
            }
        )
        from storage.onelake_documents import OneLakeDocumentStore

        publication = runtime.service.sync(
            replay_source_run_id=str(entities_manifest["runId"]),
            requested_scope={"subscription": requested_subscriptions},
            # Gold curation (exposure facts/facets/summaries) is only staged
            # and activated when a pointer store is supplied. Without it,
            # this connection-triggered sync path silently skips Gold-layer
            # publication even though bronze/silver tables complete normally.
            exposure_pointer_store=OneLakeDocumentStore(root),
        )
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
        "entities_manifest": entities_manifest,
        "inventory_publication": inventory_publication,
        "fabric_publication": fabric_publication,
    }
