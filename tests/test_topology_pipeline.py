from __future__ import annotations

import hashlib

from deltalake import DeltaTable

from fabric_pipelines.topology_pipeline import (
    TopologyOneLakePublisher,
    derive_edges,
    to_topology_edge_row,
)
from hermes_arg_connector.normalize import _add_edge as hermes_add_edge
from storage.onelake_writer import OneLakeWriter
from topology_comparison_scenario import (
    NSG_ID,
    OBSERVED_AT,
    SUBNET_ID,
    VNET_ID,
    topology_comparison_scenario,
)


def test_derive_edges_produces_expected_entities_and_predicates():
    entities, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)

    entity_ids = {row["entity_id"] for row in entities}
    assert VNET_ID in entity_ids
    assert SUBNET_ID in entity_ids
    assert NSG_ID in entity_ids

    edge_rows = [to_topology_edge_row(edge) for edge in edges]
    predicates_by_pair = {
        (row["subject_id"], row["predicate"], row["object_id"]) for row in edge_rows
    }
    assert (VNET_ID, "contains", SUBNET_ID) in predicates_by_pair
    assert (SUBNET_ID, "protectedBy", NSG_ID) in predicates_by_pair


def test_protects_by_edge_relationship_id_matches_hermes_add_edge_scheme():
    """Proves the tracer's `<done>` criterion: same subject/predicate/object/
    source input produces the exact same content-addressed relationshipId
    Hermes's own `Normalizer._add_edge` would produce.
    """
    _, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)
    pipeline_edge = to_topology_edge_row(
        next(edge for edge in edges if edge["predicate"] == "protectedBy")
    )

    hermes_index: dict[str, dict] = {}
    hermes_add_edge(
        hermes_index,
        pipeline_edge["subject_id"],
        pipeline_edge["predicate"],
        pipeline_edge["object_id"],
        pipeline_edge["source"],
        OBSERVED_AT,
        0.99,
    )
    hermes_edge = next(iter(hermes_index.values()))

    assert hermes_edge["relationshipId"] == pipeline_edge["relationship_id"]
    # Independently recompute the hash to prove the scheme itself, not just
    # cross-agreement between the two ports of the same function.
    expected_digest = hashlib.sha256(
        f"{pipeline_edge['subject_id']}|{pipeline_edge['predicate']}|"
        f"{pipeline_edge['object_id']}|{pipeline_edge['source']}".encode()
    ).hexdigest()[:24]
    assert expected_digest == pipeline_edge["relationship_id"]


def test_edge_rows_preserve_confidence_source_and_assertion_state():
    """T-08-06: unknown/stale/conflicting edges must remain explicit --
    confidence/source/assertionState must survive to the Delta row unchanged.
    """
    _, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)
    rows = [to_topology_edge_row(edge) for edge in edges]

    protected_by = next(row for row in rows if row["predicate"] == "protectedBy")
    assert protected_by["confidence"] == 0.99
    assert protected_by["source"] == "fabric_pipeline:topology"
    assert protected_by["assertion_state"] == "accepted"


def test_pipeline_writes_topology_entities_and_edges_to_delta_tables(tmp_path):
    """Proves the tracer's other `<done>` criterion: rows are actually written
    to a Delta table via the reused writer machinery (not a new writer).
    """
    entities, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)
    edge_rows = [to_topology_edge_row(edge) for edge in edges]

    lakehouse_root = tmp_path / "lakehouse"
    publisher = TopologyOneLakePublisher(
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=lakehouse_root)
    )

    entities_write = publisher.publish_entities(entities)
    edges_write = publisher.publish_edges(edge_rows)

    assert entities_write.result.rows_processed == len(entities)
    assert edges_write.result.rows_processed == len(edge_rows)

    entities_table = DeltaTable(str(lakehouse_root / "Tables" / "topology_entities"))
    edges_table = DeltaTable(str(lakehouse_root / "Tables" / "topology_edges"))
    assert entities_table.to_pyarrow_table().num_rows == len(entities)
    assert edges_table.to_pyarrow_table().num_rows == len(edge_rows)
