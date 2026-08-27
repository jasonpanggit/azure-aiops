from __future__ import annotations

from semantic.semantic_engine import SemanticEngine


def test_graph_only_engine_does_not_require_operational_snapshots():
    engine = SemanticEngine.from_graph_rows(
        entities=[
            {
                "resource_id": "application:payments",
                "entity_type": "Application",
                "name": "Payments",
                "lifecycle_status": "active",
            },
            {
                "resource_id": "service:checkout",
                "entity_type": "Service",
                "name": "Checkout",
                "lifecycle_status": "active",
            },
        ],
        relationships=[
            {
                "subject_id": "application:payments",
                "subject_type": "Application",
                "object_id": "service:checkout",
                "object_type": "Service",
                "predicate": "depends_on",
                "resource_id": "relationship:payments-checkout",
                "lifecycle_status": "active",
            }
        ],
        knowledge_version="graph-v1",
        freshness="2026-08-23T00:00:00Z",
    )

    result = engine.get_application_context("Payments")

    assert result["knowledge_version"].startswith("semantic-")
    assert result["sections"]["downstream_dependents"] == []
    assert result["sections"]["infrastructure"] == []
    assert result["risk"]["level"] == "Unknown"
