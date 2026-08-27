from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from storage.datasets import DatasetStore
from storage.locking import RunLock

from .fabric_publication import InventoryFabricPublisher
from .models import SoftwareObservation
from .normalization import normalize_os_inventory, normalize_paas_resources
from .software_normalization import normalize_configuration_data
from .sources.arg import (
    inventory_log_analytics_workspace_specs,
    inventory_os_specs,
    inventory_resource_specs,
)
from .sources.logs import fetch_software_inventory


@dataclass(frozen=True)
class InventoryRefreshResult:
    manifest: dict[str, Any]
    fabric_tables: dict[str, list[dict[str, Any]]]


class InventoryPipeline:
    """Inventory-owned refresh pipeline for OS/software compatibility datasets."""

    def __init__(
        self,
        config: Any,
        *,
        source: Any,
        logs_client: Any = None,
        store: DatasetStore | None = None,
        publisher: InventoryFabricPublisher | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.logs_client = logs_client
        self.clock = clock or (lambda: datetime.now(UTC))
        self.store = store or DatasetStore(
            config.output_dir,
            retain_raw_queries=getattr(config, "retain_raw_queries", False),
        )
        self.publisher = publisher or InventoryFabricPublisher(self.store)

    def refresh(self) -> InventoryRefreshResult:
        with RunLock(self.config.output_dir):
            return self._refresh_locked()

    def _refresh_locked(self) -> InventoryRefreshResult:
        started = self.clock().astimezone(UTC).replace(microsecond=0)
        subscriptions = list(getattr(self.config, "subscriptions", ()))
        if not subscriptions:
            discovered = self.source.list_subscriptions()
            subscriptions = [
                str(item.get("subscriptionId") or item.get("id") or "")
                for item in discovered
                if item.get("subscriptionId") or item.get("id")
            ]
        if not subscriptions:
            raise RuntimeError("No Azure subscriptions were returned by Azure inventory source")

        law_specs = inventory_log_analytics_workspace_specs()
        specs = [*inventory_os_specs(), *inventory_resource_specs(), *law_specs]
        query_results = self.source.fetch(specs, subscriptions)
        requested_scope = {"subscription": sorted(subscriptions)}
        for spec in specs:
            for row in query_results.get(spec.name, []):
                row.setdefault("query_version", spec.version)
                row.setdefault("requested_scope", requested_scope)
                row.setdefault("provider_status", "ok")

        run_id = str(uuid.uuid4())
        observed = _iso(started)
        os_rows, os_status = normalize_os_inventory(
            query_results,
            observed,
            run_id=run_id,
            requested_scope=requested_scope,
        )
        discovered_law_workspaces = [
            row
            for row in query_results.get("inventory_log_analytics_workspaces", [])
            if row.get("workspaceId")
        ]
        software_rows, software_status = fetch_software_inventory(
            self.logs_client,
            subscriptions,
            started,
            discovered_workspaces=discovered_law_workspaces,
        )
        software_observations = normalize_configuration_data(
            software_rows,
            os_rows,
            observed_at=observed,
        )
        if not software_observations and software_status["state"] != "ready":
            software_observations = [
                SoftwareObservation.from_mapping(row)
                for row in self.store.read_dataset("inventory/software_observations")
            ]
        software_dataset = [row.to_dict() for row in software_observations]
        software_status["row_count"] = len(software_dataset)
        resource_rows = normalize_paas_resources(
            query_results.get("inventory_resources", []),
            observed,
            run_id=run_id,
        )

        manifest = self.publisher.publish(
            {
                "inventory/os_observations": os_rows,
                "inventory/source_status": os_status,
                "inventory/software_observations": software_dataset,
                "inventory/software_source_status": [software_status],
                "inventory/resource_observations": resource_rows,
            },
            query_results=query_results,
            run_metadata={
                "runId": run_id,
                "startedAt": observed,
                "subscriptions": sorted(subscriptions),
                "queryVersion": "1.0.0",
                "status": "completed",
            },
        )
        return InventoryRefreshResult(manifest=manifest, fabric_tables=self.publisher.fabric_tables)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


__all__ = ["InventoryPipeline", "InventoryRefreshResult"]
