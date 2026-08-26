from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from storage.datasets import DatasetStore

from .fabric_contracts import INVENTORY_FABRIC_CONTRACTS, validate_inventory_dataset


@dataclass
class InventoryFabricPublisher:
    """Publish inventory logical datasets through Fabric contracts.

    The local ``DatasetStore`` remains the compatibility/staging writer for
    existing readers.  ``fabric_tables`` records the Fabric-native table payloads
    that a real OneLake/Delta writer can persist without changing read shapes.
    """

    store: DatasetStore
    fabric_tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def publish(
        self,
        datasets: Mapping[str, list[dict[str, Any]]],
        *,
        query_results: Mapping[str, list[dict[str, Any]]] | None = None,
        run_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        logical_datasets = {name: list(rows) for name, rows in datasets.items()}
        for logical_name, rows in logical_datasets.items():
            report = validate_inventory_dataset(logical_name, rows)
            if not report.passed:
                raise ValueError(f"Inventory quality validation failed: {report.to_dict()}")
            contract = INVENTORY_FABRIC_CONTRACTS[logical_name]
            self.fabric_tables[contract.table_name] = list(rows)

        metadata = {
            "runId": "inventory-refresh",
            "status": "completed",
            "queryVersion": "1.0.0",
            **dict(run_metadata or {}),
            "fabricTables": {
                logical_name: INVENTORY_FABRIC_CONTRACTS[logical_name].table_name
                for logical_name in logical_datasets
            },
        }
        return self.store.publish(
            logical_datasets,
            dict(query_results or {}),
            metadata,
            ontology={},
        )


__all__ = ["InventoryFabricPublisher"]

