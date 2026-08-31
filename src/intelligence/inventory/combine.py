"""Combine per-connection inventory snapshots into one Fabric-facing snapshot.

Mirrors ``onboarding.activation.publish_combined_snapshot``'s dedupe-and-merge
pattern, but for the inventory-owned datasets. Inventory remains the sole
owner of these dataset names and of the ``InventoryFabricPublisher`` republish
step, so this module -- not ``onboarding`` or ``onboarding`` --
performs the merge and the final Fabric write.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.datasets import DatasetStore

_INVENTORY_DATASETS = (
    "inventory/os_observations",
    "inventory/source_status",
    "inventory/software_observations",
    "inventory/software_source_status",
    "inventory/resource_observations",
)


def publish_combined_inventory_snapshot(
    connection_output_dirs: dict[str, str | Path],
    target_root: str | Path,
    *,
    connection_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Merge each connection's isolated inventory snapshot into one target root.

    Each row is keyed by ``resource_id`` (os/resource rows) or by
    ``resource_id`` + ``canonical_identity`` (software rows, which are
    per-machine-per-package). A genuine identity collision across two
    different connections' subscriptions is treated as an error, matching the
    safety policy already used for discovery entities in
    ``onboarding.activation.publish_combined_snapshot`` -- this should not
    normally happen since Azure resource IDs embed the subscription ID.
    """
    selected = connection_ids or sorted(connection_output_dirs)
    if not selected:
        raise ValueError("At least one subscription connection is required")

    os_rows: dict[str, dict[str, Any]] = {}
    resource_rows: dict[str, dict[str, Any]] = {}
    software_rows: dict[str, dict[str, Any]] = {}
    os_statuses: list[dict[str, Any]] = []
    software_statuses: list[dict[str, Any]] = []
    source_runs: list[str] = []
    latest_started_at = ""

    def _merge(bucket: dict[str, dict[str, Any]], identifier: str, row: dict[str, Any]) -> None:
        if not identifier:
            return
        existing = bucket.get(identifier)
        existing_connection = str((existing or {}).get("connection_id") or "")
        incoming_connection = str(row.get("connection_id") or "")
        if (
            existing is not None
            and existing_connection
            and incoming_connection
            and existing_connection != incoming_connection
        ):
            raise ValueError(
                "Inventory row identity collision across connections: "
                f"'{identifier}' is present in both '{existing_connection}' and "
                f"'{incoming_connection}'"
            )
        if existing is not None and str(existing.get("observed_at") or "") > str(
            row.get("observed_at") or ""
        ):
            # Same identity, same connection: keep the freshest observation
            # instead of whichever connection happened to be processed last.
            # This closes the race where a stale/partial refresh from one
            # connection could silently overwrite a newer row already merged
            # from another pass over the same connection's history.
            return
        bucket[identifier] = row

    for connection_id in selected:
        root = connection_output_dirs[connection_id]
        store = DatasetStore(root)
        if store.current_generation() is None:
            continue
        manifest = _read_manifest(store)
        source_runs.append(str(manifest.get("runId") or connection_id))
        latest_started_at = max(latest_started_at, str(manifest.get("startedAt") or ""))

        for row in store.read_dataset("inventory/os_observations"):
            _merge(os_rows, str(row.get("resource_id") or ""), dict(row))
        for row in store.read_dataset("inventory/resource_observations"):
            _merge(resource_rows, str(row.get("resource_id") or ""), dict(row))
        for row in store.read_dataset("inventory/software_observations"):
            key = "|".join(
                str(row.get(field) or "") for field in ("resource_id", "canonical_identity")
            )
            _merge(software_rows, key, dict(row))
        os_statuses.extend(store.read_dataset("inventory/source_status"))
        software_statuses.extend(store.read_dataset("inventory/software_source_status"))

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = f"inventory-activation-{uuid.uuid4()}"
    datasets = {
        "inventory/os_observations": sorted(
            os_rows.values(), key=lambda row: str(row.get("resource_id") or "")
        ),
        "inventory/source_status": os_statuses,
        "inventory/software_observations": sorted(
            software_rows.values(),
            key=lambda row: (
                str(row.get("resource_id") or ""),
                str(row.get("canonical_identity") or ""),
            ),
        ),
        "inventory/software_source_status": software_statuses,
        "inventory/resource_observations": sorted(
            resource_rows.values(), key=lambda row: str(row.get("resource_id") or "")
        ),
    }
    return DatasetStore(target_root).publish(
        datasets,
        {},
        {
            "runId": run_id,
            "status": "completed",
            "startedAt": latest_started_at or now,
            "completedAt": now,
            "queryVersion": "combined-subscription-connections-v1",
            "sourceConnectionIds": sorted(selected),
            "sourceRunIds": sorted(source_runs),
        },
        ontology={},
    )


def republish_combined_snapshot_to_fabric(
    target_root: str | Path,
    fabric_config_path: str,
    *,
    retain_raw_queries: bool = False,
) -> dict[str, Any]:
    """Publish the already-merged combined inventory snapshot through Fabric.

    Reads back the just-written combined datasets from ``target_root`` and
    republishes them through :class:`InventoryFabricPublisher`, so Fabric only
    ever receives one write per refresh regardless of how many subscription
    connections were merged into it.
    """
    from fabric.auth import build_credential, build_delta_storage_options
    from fabric.config import FabricRuntimeConfig
    from fabric.fabric_client import FabricClient
    from fabric.lakehouse_manager import LakehouseManager
    from fabric.workspace_manager import WorkspaceManager
    from storage.delta_writer import DeltaWriter
    from storage.onelake_writer import OneLakeWriter

    from .fabric_publication import InventoryFabricPublisher
    from .onelake_publication import InventoryOneLakePublisher

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
    store = DatasetStore(target_root, retain_raw_queries=retain_raw_queries)
    publisher = InventoryFabricPublisher(
        store,
        onelake=InventoryOneLakePublisher(onelake, delta_writer=delta_writer),
    )
    datasets = {name: store.read_dataset(name) for name in _INVENTORY_DATASETS}
    return publisher.publish(datasets, run_metadata={"runId": "inventory-refresh"})


def _read_manifest(store: DatasetStore) -> dict[str, Any]:
    import json

    generation = store.current_generation()
    path = f"{generation}/manifest.json"
    try:
        if store.is_remote:
            with store.fs.open(path, "rt") as handle:
                payload = json.loads(handle.read())
        else:
            payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Inventory manifest is unreadable for {generation}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Inventory manifest is invalid for {generation}")
    return payload


__all__ = ["publish_combined_inventory_snapshot", "republish_combined_snapshot_to_fabric"]
