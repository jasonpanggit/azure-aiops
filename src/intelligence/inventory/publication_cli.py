"""Finite registered-connection inventory publication for Container Apps Jobs."""

from __future__ import annotations

import json
import os
from dataclasses import replace

from api.inventory_orchestration import run_inventory_refresh_all_connections
from onboarding.config import ConnectorConfig
from onboarding.runtime import build_onboarding_service


def main() -> int:
    """Acquire registered inventory and publish it using the job identity."""
    names = ("AIOPS_CONFIG_PATH", "AIOPS_FABRIC_CONFIG", "AIOPS_CONNECTION_HOME")
    config = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise ValueError("Missing inventory publication configuration: " + ", ".join(missing))
    connector = replace(
        ConnectorConfig.load(config["AIOPS_CONFIG_PATH"]),
        output_dir=config["AIOPS_CONNECTION_HOME"],
    )
    onboarding = build_onboarding_service(connector)
    connections = onboarding.registry.list(include_disabled=False)
    if not connections:
        raise RuntimeError("No active subscription connections are registered")
    discovery_roots = {}
    for connection in connections:
        result = onboarding.sync(connection.connection_id, mode="scheduled")
        if result.get("status") != "succeeded":
            raise RuntimeError("Registered-connection discovery failed before publication")
        discovery_roots[connection.connection_id] = (
            onboarding.sync_coordinator.connection_output_dir(connection)
        )
    result = run_inventory_refresh_all_connections(
        config["AIOPS_CONFIG_PATH"],
        fabric_config_path=config["AIOPS_FABRIC_CONFIG"],
        registry_root=config["AIOPS_CONNECTION_HOME"],
        discovery_output_dirs=discovery_roots,
        require_all_connections=True,
    )
    publication = result.get("fabric_publication") or {}
    summary = {
        "status": result["status"],
        "connections": {
            key: value["status"]
            for key, value in result["connections"].items()
        },
        "source_generation": publication.get("sourceRunId"),
        "publication_status": publication.get("status"),
        "tables": publication.get("fabricTables") or [],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if (
        result["status"] == "completed"
        and publication.get("status") == "completed"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
