from __future__ import annotations

from fabric_pipelines.impact_context_builder import OUTPUT_TABLE, build_graph, traverse


def test_impact_context_builder_aggregates_assessments_and_enforces_traversal_scope():
    resources = [
        {"resource_id": "vm-1", "name": "vm-1", "entity_type": "VirtualMachine"},
        {"resource_id": "sql-1", "name": "sql-1", "entity_type": "SqlServer"},
        {"resource_id": "secret-1", "name": "secret", "entity_type": "KeyVault"},
    ]
    graph = build_graph(
        resources=resources,
        topology_edges=[
            {"subject_id": "vm-1", "predicate": "dependsOn", "object_id": "sql-1"},
            {"subject_id": "sql-1", "predicate": "dependsOn", "object_id": "secret-1"},
        ],
        vulnerability_findings=[{"resource_id": "vm-1", "risk_score": 88}],
        lifecycle_findings=[{"resource_id": "vm-1", "lifecycle_status": "EOL", "risk_score": 84}],
        patch_findings=[{"resource_id": "vm-1", "status": "noncompliant", "compliance_score": 0}],
        change_findings=[{"resource_id": "sql-1", "risk_score": 60}],
    )

    assert graph.table_name == OUTPUT_TABLE
    vm = next(node for node in graph.nodes if node["node_id"] == "vm-1")
    assert vm["risk_score"] == 88
    assert vm["lifecycle_status"] == "EOL"
    assert vm["patch_status"] == "noncompliant"

    scoped = traverse(graph, "vm-1", allowed_resource_ids={"vm-1", "sql-1"})
    assert {node["node_id"] for node in scoped["nodes"]} == {"vm-1", "sql-1"}
    assert all(edge["object_id"] != "secret-1" for edge in scoped["edges"])
