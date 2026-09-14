"""Dedicated patch-only Fabric publication entrypoint."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from onboarding.activation import publish_combined_snapshot
from onboarding.config import ConnectorConfig
from onboarding.registry import ConnectionRegistry
from onboarding.sync import ConnectionSyncCoordinator

from .config import FabricRuntimeConfig
from .runtime import FabricRuntimeMode, build_runtime

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PatchSnapshotSources:
    registry: ConnectionRegistry
    sync_coordinator: ConnectionSyncCoordinator


def run_patch_publication(
    connector_config_path: str | Path,
    fabric_config_path: str | Path,
) -> dict[str, Any]:
    """Merge current connection snapshots and publish one due patch generation."""
    connector_config = ConnectorConfig.load(connector_config_path)
    sources = _PatchSnapshotSources(
        registry=ConnectionRegistry(str(connector_config.output_dir)),
        sync_coordinator=ConnectionSyncCoordinator(
            str(connector_config.output_dir)
        ),
    )
    connections = sources.registry.list(include_disabled=False)
    if not connections:
        raise RuntimeError("No active subscription connections are registered")
    combined_manifest = publish_combined_snapshot(
        sources,
        [connection.connection_id for connection in connections],
        connector_config.output_dir,
        reuse_unchanged=True,
    )
    source_run_id = str(combined_manifest.get("runId") or "")
    if not source_run_id:
        raise RuntimeError("Combined patch source generation is unavailable")
    fabric_config = replace(
        FabricRuntimeConfig.load(fabric_config_path),
        source_data_root=connector_config.output_dir,
    )
    runtime = build_runtime(
        fabric_config,
        mode=FabricRuntimeMode.PUBLISH,
    )
    result = runtime.service.sync_patch_tables(
        replay_source_run_id=source_run_id,
    )
    summary = {
        "status": result.status,
        "source_generation_hash": hashlib.sha256(
            result.source_run_id.encode()
        ).hexdigest()[:24],
        "tables_published": len(result.tables),
        "rows_processed": result.rows_processed,
        "failed_records": result.failed_records,
        "duration_seconds": result.duration_seconds,
    }
    _LOGGER.info(
        "patch_publication status=%s tables=%s rows=%s failed=%s duration_seconds=%.3f",
        summary["status"],
        summary["tables_published"],
        summary["rows_processed"],
        summary["failed_records"],
        summary["duration_seconds"],
    )
    return summary
