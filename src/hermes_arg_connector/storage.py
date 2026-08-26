from __future__ import annotations

from typing import Any

from storage.datasets import DatasetStore as _DatasetStore

from .normalize import NormalizedGraph
from .ontology import generate_ontology_metadata


class DatasetStore(_DatasetStore):
    """Compatibility shim for Hermes graph-shaped publication."""

    def publish(
        self,
        graph: NormalizedGraph,
        query_results: dict[str, list[dict]],
        run_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        datasets: dict[str, list[dict]] = {
            **{f"entities/{entity_type}": rows for entity_type, rows in graph.entities.items()},
            "relationships/relationships": graph.relationships,
            "changes/resource_changes": graph.changes,
        }
        for collection in ("situations", "evidence", "links", "audit_events", "source_status"):
            rows = getattr(graph, collection, None)
            if rows is not None:
                datasets[f"situations/{collection}"] = list(rows)
        if getattr(graph, "inventory_observations", None) is not None:
            datasets["inventory/os_observations"] = list(graph.inventory_observations)
        if getattr(graph, "inventory_source_status", None) is not None:
            datasets["inventory/source_status"] = list(graph.inventory_source_status)
        if getattr(graph, "inventory_software_observations", None) is not None:
            datasets["inventory/software_observations"] = list(graph.inventory_software_observations)
        if getattr(graph, "inventory_software_source_status", None) is not None:
            datasets["inventory/software_source_status"] = list(graph.inventory_software_source_status)
        return super().publish(
            datasets,
            query_results,
            run_metadata,
            ontology=generate_ontology_metadata(graph.entities),
        )


__all__ = ["DatasetStore"]
