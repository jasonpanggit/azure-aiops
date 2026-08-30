from __future__ import annotations

from typing import Any

from storage.datasets import DatasetStore as _DatasetStore

from .graph_normalize import NormalizedGraph
from .ontology_metadata import generate_ontology_metadata


class DatasetStore(_DatasetStore):
    """Compatibility shim for AIOps graph-shaped publication."""

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
        return super().publish(
            datasets,
            query_results,
            run_metadata,
            ontology=generate_ontology_metadata(graph.entities),
        )


__all__ = ["DatasetStore"]
