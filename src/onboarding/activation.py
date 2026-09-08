"""Production discovery aggregation and Fabric activation workflow."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from onboarding.ontology_metadata import generate_ontology_metadata
from onboarding.service import SubscriptionOnboardingService
from storage.datasets import DatasetStore
from storage.onelake_documents import OneLakeDocumentStore

from .graph_normalize import ENTITY_TYPES, NormalizedGraph

_EXPOSURE_PASSTHROUGH_KEYS = {
    "exposure/workload_observations": "observation_id",
    "exposure/workload_deployments": "deployment_id",
    "exposure/workload_source_checkpoints": "checkpoint_key",
    "situations/source_status": "partition_key",
}


def publish_combined_snapshot(
    service: SubscriptionOnboardingService,
    connection_ids: list[str],
    target_root: str | Path,
) -> dict[str, Any]:
    """Publish one isolated, deduplicated snapshot from synced connections."""
    if not connection_ids:
        raise ValueError("At least one subscription connection is required")
    entities: dict[str, dict[str, dict[str, Any]]] = {
        name: {} for name in ENTITY_TYPES
    }
    relationships: dict[str, dict[str, Any]] = {}
    changes: dict[str, dict[str, Any]] = {}
    exposure_rows: dict[str, dict[str, dict[str, Any]]] = {
        name: {} for name in _EXPOSURE_PASSTHROUGH_KEYS
    }
    source_runs: list[str] = []
    latest_started_at = ""

    for connection_id in connection_ids:
        connection = service.registry.get(connection_id)
        root = service.sync_coordinator.connection_output_dir(connection)
        store = DatasetStore(root)
        generation = store.current_generation()
        if generation is None:
            raise ValueError(
                f"Connection '{connection_id}' has no successful discovery snapshot"
            )
        manifest = _read_manifest(store, generation)
        source_runs.append(str(manifest.get("runId") or connection_id))
        latest_started_at = max(
            latest_started_at, str(manifest.get("startedAt") or "")
        )
        datasets = manifest.get("datasets") or {}
        for dataset_name in datasets:
            if dataset_name.startswith("entities/"):
                entity_type = dataset_name.split("/", 1)[1]
                if entity_type not in entities:
                    continue
                for row in store.read_dataset(dataset_name):
                    identifier = str(row.get("id") or "")
                    if identifier:
                        existing = entities[entity_type].get(identifier)
                        existing_connection = str(
                            (existing or {}).get("connection_id") or ""
                        )
                        incoming_connection = str(row.get("connection_id") or "")
                        if (
                            existing is not None
                            and existing_connection
                            and incoming_connection
                            and existing_connection != incoming_connection
                        ):
                            raise ValueError(
                                "Discovery entity identity collision across "
                                f"connections: {entity_type} '{identifier}' is "
                                f"present in both '{existing_connection}' and "
                                f"'{incoming_connection}'"
                            )
                        entities[entity_type][identifier] = row
            elif dataset_name == "relationships/relationships":
                for row in store.read_dataset(dataset_name):
                    identifier = str(row.get("relationshipId") or "")
                    if identifier:
                        relationships[identifier] = row
            elif dataset_name == "changes/resource_changes":
                for row in store.read_dataset(dataset_name):
                    identifier = "|".join(
                        str(row.get(key) or "")
                        for key in ("id", "changeId", "timestamp", "connection_id")
                    )
                    changes[identifier] = row
            elif dataset_name in exposure_rows:
                key_field = _EXPOSURE_PASSTHROUGH_KEYS[dataset_name]
                for row in store.read_dataset(dataset_name):
                    identifier = "|".join(
                        (
                            str(row.get("connection_id") or connection_id),
                            str(row.get("workspace_id") or ""),
                            str(row.get(key_field) or ""),
                        )
                    )
                    if not str(row.get(key_field) or ""):
                        identifier = hashlib.sha256(
                            json.dumps(
                                row,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()
                    exposure_rows[dataset_name][identifier] = row

    graph = NormalizedGraph(
        entities={
            name: sorted(rows.values(), key=lambda row: str(row.get("id") or ""))
            for name, rows in entities.items()
        },
        relationships=sorted(
            relationships.values(),
            key=lambda row: str(row.get("relationshipId") or ""),
        ),
        changes=sorted(
            changes.values(),
            key=lambda row: (
                str(row.get("timestamp") or ""),
                str(row.get("id") or ""),
            ),
        ),
    )
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = f"activation-{uuid.uuid4()}"
    datasets = {
        **{f"entities/{entity_type}": rows for entity_type, rows in graph.entities.items()},
        "relationships/relationships": graph.relationships,
        "changes/resource_changes": graph.changes,
        **{
            name: [
                rows[key]
                for key in sorted(rows)
            ]
            for name, rows in exposure_rows.items()
        },
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
            "sourceConnectionIds": sorted(connection_ids),
            "sourceRunIds": sorted(source_runs),
        },
        ontology=generate_ontology_metadata(graph.entities),
    )


def activate_runtime(
    service: SubscriptionOnboardingService,
    *,
    fabric_config: str | Path,
    connection_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Validate, discover, publish, and verify a production Fabric snapshot."""
    selected = connection_ids or [
        connection.connection_id
        for connection in service.registry.list(include_disabled=False)
    ]
    if not selected:
        raise ValueError("No active subscription connections are registered")

    validations: dict[str, Any] = {}
    syncs: dict[str, Any] = {}
    for connection_id in selected:
        validation = service.validate(connection_id)
        validations[connection_id] = validation
        if not validation.get("passed"):
            raise ValueError(
                f"Connection '{connection_id}' failed SPN access validation"
            )
        sync = service.sync(connection_id, mode="manual")
        syncs[connection_id] = sync
        if sync.get("status") != "succeeded":
            raise RuntimeError(f"Connection '{connection_id}' discovery failed")

    from fabric.config import FabricRuntimeConfig
    from fabric.runtime import build_runtime

    config = FabricRuntimeConfig.load(fabric_config)
    combined = publish_combined_snapshot(service, selected, config.source_data_root)
    runtime = build_runtime(config)
    publication = runtime.service.sync(
        exposure_pointer_store=OneLakeDocumentStore(service.registry.root)
    )
    semantic = runtime.semantic_engine()
    return {
        "status": "activated",
        "connections": sorted(selected),
        "validations": validations,
        "discovery_syncs": syncs,
        "combined_snapshot": combined,
        "fabric_publication": {
            "run_id": publication.run_id,
            "source_run_id": publication.source_run_id,
            "status": publication.status,
            "tables": list(publication.tables),
        },
        "ontology_version": semantic.knowledge_version,
        "freshness": semantic.freshness,
    }


def _read_manifest(store: DatasetStore, generation: str) -> dict[str, Any]:
    path = f"{generation}/manifest.json"
    try:
        if store.is_remote:
            with store.fs.open(path, "rt") as handle:
                payload = json.loads(handle.read())
        else:
            payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Discovery manifest is unreadable for {generation}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Discovery manifest is invalid for {generation}")
    return payload


__all__ = ["activate_runtime", "publish_combined_snapshot"]
