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
from storage.fs import is_onelake_uri, resolve_root

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
    *,
    connection_home: str | Path = "",
    source_root: str | Path = "",
) -> dict[str, Any]:
    """Publish Patch data from explicit, isolated production roots."""
    connector_config = ConnectorConfig.load(connector_config_path)
    fabric_config = FabricRuntimeConfig.load(fabric_config_path)
    connection_root, combined_root = _publication_roots(
        connector_config,
        fabric_config,
        connection_home=connection_home,
        source_root=source_root,
    )
    sources = _PatchSnapshotSources(
        registry=ConnectionRegistry(str(connection_root)),
        sync_coordinator=ConnectionSyncCoordinator(
            str(connection_root)
        ),
    )
    connections = sources.registry.list(include_disabled=False)
    if not connections:
        raise RuntimeError("No active subscription connections are registered")
    combined_manifest = publish_combined_snapshot(
        sources,
        [connection.connection_id for connection in connections],
        combined_root,
        reuse_unchanged=True,
    )
    source_run_id = str(combined_manifest.get("runId") or "")
    if not source_run_id:
        raise RuntimeError("Combined patch source generation is unavailable")
    fabric_config = replace(fabric_config, source_data_root=combined_root)
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


def _publication_roots(
    connector_config: ConnectorConfig,
    fabric_config: FabricRuntimeConfig,
    *,
    connection_home: str | Path,
    source_root: str | Path,
) -> tuple[Path | str, Path | str]:
    production = fabric_config.local_onelake_root is None
    if production and (
        not str(connection_home).strip() or not str(source_root).strip()
    ):
        raise ValueError(
            "Production patch publication requires explicit connection and source roots"
        )
    connection = _normalized_root(
        connection_home or connector_config.output_dir
    )
    source = _normalized_root(source_root or fabric_config.source_data_root)
    if production and (
        not is_onelake_uri(str(connection))
        or not is_onelake_uri(str(source))
    ):
        raise ValueError(
            "Production patch publication roots must be OneLake URIs"
        )
    if _root_identity(connection) == _root_identity(source):
        raise ValueError(
            "Patch connection and combined source roots must be distinct"
        )
    return connection, source


def _normalized_root(value: str | Path) -> Path | str:
    text = str(value).strip()
    if not text:
        raise ValueError("Patch publication root is required")
    return resolve_root(text) if is_onelake_uri(text) else Path(text).resolve()


def _root_identity(value: Path | str) -> str:
    text = str(value).rstrip("/")
    return text.casefold() if is_onelake_uri(text) else text
