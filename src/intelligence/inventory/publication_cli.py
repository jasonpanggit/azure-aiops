"""Finite registered-connection inventory publication for Container Apps Jobs."""

from __future__ import annotations

import json
import os
from dataclasses import replace

import httpx

from api.inventory_orchestration import run_inventory_refresh_all_connections
from fabric.graph_refresh import (
    GraphRefreshAmbiguousError,
    GraphRefresher,
    GraphRefreshError,
)
from onboarding.config import ConnectorConfig
from onboarding.runtime import build_onboarding_service
from storage.locking import RunLock
from storage.onelake_documents import OneLakeDocumentStore
from storage.renewing_run import renewing_run_lock


def _graph_refresher(state_root: str, guard=lambda: None) -> GraphRefresher | None:
    workspace = os.environ.get("AIOPS_GRAPH_REFRESH_WORKSPACE_ID", "").strip()
    graph = os.environ.get("AIOPS_GRAPH_REFRESH_GRAPH_MODEL_ID", "").strip()
    if not workspace and not graph:
        return None
    if not workspace or not graph:
        raise ValueError("Graph refresh requires both workspace and graph model ids")
    from azure.identity import DefaultAzureCredential

    return GraphRefresher(
        DefaultAzureCredential(),
        workspace_id=workspace,
        graph_model_id=graph,
        state_store=OneLakeDocumentStore(state_root),
        guard=guard,
        http_client=httpx.Client(),
    )


def main() -> int:
    """Acquire registered inventory and publish it using the job identity."""
    names = ("AIOPS_CONFIG_PATH", "AIOPS_FABRIC_CONFIG", "AIOPS_CONNECTION_HOME")
    config = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError("Missing inventory publication configuration: " + ", ".join(missing))
    source_config = ConnectorConfig.load(config["AIOPS_CONFIG_PATH"])
    connector = replace(
        source_config,
        output_dir=config["AIOPS_CONNECTION_HOME"],
    )
    with renewing_run_lock(RunLock(source_config.output_dir)) as lock:
        refresher = _graph_refresher(config["AIOPS_CONNECTION_HOME"], lock.assert_held)
        if refresher is not None:
            try:
                refresher.assert_ready()
            except GraphRefreshAmbiguousError as exc:
                print(json.dumps({
                    "status": "blocked",
                    "connections": {},
                    "source_generation": None,
                    "publication_status": "not_started",
                    "tables": [],
                    "graph_refresh": {
                        "status": "ambiguous",
                        "operator_review_required": True,
                        "reason": str(exc),
                    },
                }, sort_keys=True))
                return 1
        onboarding = build_onboarding_service(connector)
        connections = onboarding.registry.list(include_disabled=False)
        if not connections:
            raise RuntimeError("No active subscription connections are registered")
        discovery_roots = {}
        for connection in connections:
            lock.assert_held()
            result = onboarding.sync(connection.connection_id, mode="scheduled")
            if result.get("status") != "succeeded":
                raise RuntimeError("Registered-connection discovery failed before publication")
            discovery_roots[connection.connection_id] = (
                onboarding.sync_coordinator.connection_output_dir(connection)
            )
        lock.assert_held()
        result = run_inventory_refresh_all_connections(
            config["AIOPS_CONFIG_PATH"],
            fabric_config_path=config["AIOPS_FABRIC_CONFIG"],
            registry_root=config["AIOPS_CONNECTION_HOME"],
            discovery_output_dirs=discovery_roots,
            require_all_connections=True,
            assert_lock_held=lock.assert_held,
        )
        publication = result.get("fabric_publication") or {}
        published = (
            result["status"] == "completed"
            and publication.get("status") == "completed"
        )
        graph_refresh: dict[str, object] | None = None
        if published and refresher is not None:
            lock.assert_held()
            try:
                if not publication.get("sourceRunId"):
                    raise GraphRefreshError("graph_refresh_missing_source_run")
                graph_refresh = refresher.refresh(source_run_id=publication["sourceRunId"])
                lock.assert_held()
            except GraphRefreshError as exc:
                ambiguous = isinstance(exc, GraphRefreshAmbiguousError)
                graph_refresh = {
                    "status": "ambiguous" if ambiguous else "failed",
                    "operator_review_required": ambiguous,
                    "reason": str(exc),
                }
    summary = {
        "status": result["status"],
        "connections": {
            key: value["status"]
            for key, value in result["connections"].items()
        },
        "source_generation": publication.get("sourceRunId"),
        "publication_status": publication.get("status"),
        "tables": publication.get("fabricTables") or [],
        "graph_refresh": graph_refresh,
    }
    print(json.dumps(summary, sort_keys=True))
    refresh_ok = graph_refresh is None or graph_refresh.get("status") == "Completed"
    return 0 if published and refresh_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
