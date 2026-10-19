from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from storage.datasets import DatasetStore

from .fabric_contracts import INVENTORY_FABRIC_CONTRACTS, validate_inventory_dataset
from .onelake_publication import InventoryOneLakePublisher


@dataclass
class InventoryFabricPublisher:
    """Publish inventory logical datasets through Fabric contracts.

    The local ``DatasetStore`` remains the compatibility/staging writer for
    existing readers.  ``fabric_tables`` records the Fabric-native table payloads
    that a real OneLake/Delta writer can persist without changing read shapes.
    """

    store: DatasetStore
    onelake: InventoryOneLakePublisher | None = None
    fabric_tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    table_writes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def publish(
        self,
        datasets: Mapping[str, list[dict[str, Any]]],
        *,
        query_results: Mapping[str, list[dict[str, Any]]] | None = None,
        run_metadata: Mapping[str, Any] | None = None,
        persist_compatibility: bool = True,
        assert_lock_held: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Publish validated inventory tables and optionally update the store."""
        if assert_lock_held is not None:
            assert_lock_held()
        logical_datasets = {name: list(rows) for name, rows in datasets.items()}
        published_datasets: dict[str, list[dict[str, Any]]] = {}
        for logical_name, rows in logical_datasets.items():
            report = validate_inventory_dataset(logical_name, rows)
            if not report.passed:
                raise ValueError(f"Inventory quality validation failed: {report.to_dict()}")
            contract = INVENTORY_FABRIC_CONTRACTS[logical_name]
            self.fabric_tables[contract.table_name] = list(rows)
            if self.onelake is not None:
                if assert_lock_held is not None:
                    assert_lock_held()
                write = self.onelake.publish_table(contract, rows)
                self.table_writes[contract.table_name] = {
                    "tableUri": write.table_uri,
                    "rowsProcessed": write.result.rows_processed,
                    "rowsAdded": write.result.rows_added,
                    "rowsRemoved": write.result.rows_removed,
                    "skipped": write.result.skipped,
                    "version": write.result.version,
                }
            # Every dataset is written under both its logical ("inventory/x")
            # and Fabric table ("inventory_x") name. Readers -- the connection
            # merge in combine.py and the republish path -- address datasets by
            # logical name, so omitting it here makes the rows unreadable and
            # the next republish silently writes the dataset back as empty.
            published_datasets[logical_name] = list(rows)
            published_datasets[contract.table_name] = list(rows)

        metadata = {
            "runId": "inventory-refresh",
            "status": "completed",
            "queryVersion": "1.0.0",
            **dict(run_metadata or {}),
            "fabricTables": {
                logical_name: INVENTORY_FABRIC_CONTRACTS[logical_name].table_name
                for logical_name in logical_datasets
            },
            "fabricTableWrites": dict(self.table_writes),
        }
        if not persist_compatibility:
            return {
                **metadata,
                "datasets": {
                    name: {"rowCount": len(rows)}
                    for name, rows in sorted(published_datasets.items())
                },
            }
        return self.store.publish(
            published_datasets,
            dict(query_results or {}),
            metadata,
            ontology={},
            **({"assert_lock_held": assert_lock_held} if assert_lock_held is not None else {}),
        )


__all__ = ["InventoryFabricPublisher"]
