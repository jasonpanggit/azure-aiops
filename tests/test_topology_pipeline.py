from __future__ import annotations

import hashlib
import json

from deltalake import DeltaTable
from topology_comparison_scenario import (
    NSG_ID,
    OBSERVED_AT,
    SUBNET_ID,
    VNET_ID,
    topology_comparison_scenario,
)

from fabric_pipelines.topology_pipeline import (
    TopologyOneLakePublisher,
    derive_edges,
    to_topology_edge_row,
)
from onboarding.graph_normalize import _add_edge as aiops_add_edge
from storage.onelake_writer import OneLakeWriter


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


def test_protects_by_edge_relationship_id_matches_aiops_add_edge_scheme():
    """Proves the tracer's `<done>` criterion: same subject/predicate/object/
    source input produces the exact same content-addressed relationshipId
    AIOps's own `Normalizer._add_edge` would produce.
    """
    _, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)
    pipeline_edge = to_topology_edge_row(
        next(edge for edge in edges if edge["predicate"] == "protectedBy")
    )

    aiops_index: dict[str, dict] = {}
    aiops_add_edge(
        aiops_index,
        pipeline_edge["subject_id"],
        pipeline_edge["predicate"],
        pipeline_edge["object_id"],
        pipeline_edge["source"],
        OBSERVED_AT,
        0.99,
    )
    aiops_edge = next(iter(aiops_index.values()))

    assert aiops_edge["relationshipId"] == pipeline_edge["relationship_id"]
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


def test_derive_edges_covers_default_deny_rule_and_hasrule_predicate():
    """Full predicate vocabulary (Task 2): hasRule must be emitted for both
    the explicit allow rule and Azure's retained default deny rule -- the
    default rule is not dropped (network_normalize.py docstring guarantee).
    """
    _, edges = derive_edges(topology_comparison_scenario(), observed=OBSERVED_AT)
    rows = [to_topology_edge_row(edge) for edge in edges]

    has_rule_objects = {row["object_id"] for row in rows if row["predicate"] == "hasRule"}
    assert any("allow-https" in obj for obj in has_rule_objects)
    assert any("denyallinbound" in obj for obj in has_rule_objects)


def test_flowlog_ingest_join_is_fixture_only_and_classifies_allowed_vs_observed():
    from topology_comparison_scenario import nsg_rule_rows

    from fabric_pipelines.flowlog_ingest import (
        curated_flow_log_fixture,
        join_flow_logs_with_nsg_rules,
    )

    rules = nsg_rule_rows()
    flows = curated_flow_log_fixture(OBSERVED_AT)
    edges = join_flow_logs_with_nsg_rules(rules, flows, observed=OBSERVED_AT)

    assert edges, "fixture flow logs must match at least one NSG rule"
    classifications = {edge["attributes"]["allowedVsObserved"] for edge in edges}
    assert "allowed_and_observed" in classifications
    for edge in edges:
        assert edge["source"] == "fabric_pipeline:flowlog_fixture"
        assert edge["attributes"]["dataSource"] == "fixture"
        assert edge["assertionState"] == "fixture_only"


def test_ontology_binding_registers_topology_tables_without_inferring_relationships():
    """Pitfall 2 / D-10 guard: ontology_binding must only register
    already-derived tables, never claim to detect/infer relationships."""
    from fabric_pipelines.ontology_binding import TopologyOntologyBinder

    class _StubManager:
        def __init__(self):
            self.calls = []

        def resolve(self, **kwargs):
            self.calls.append(("resolve", kwargs))

        def create(self, display_name, definition):
            self.calls.append(("create", display_name, definition))
            return {"id": "ontology-topology-1", "displayName": display_name}

    manager = _StubManager()
    binder = TopologyOntologyBinder(
        manager, workspace_id="workspace-1", lakehouse_id="lakehouse-1"
    )

    result = binder.bind(
        ontology_id="",
        ontology_name="Topology_Comparison_Ontology",
        entity_types={
            "VNet": "topology_entities",
            "Subnet": "topology_entities",
            "NetworkSecurityGroup": "topology_entities",
        },
        relationships={
            ("VNet", "contains", "Subnet"): "topology_edges",
            ("Subnet", "protectedBy", "NetworkSecurityGroup"): "topology_edges",
        },
    )

    assert result["action"] == "created"
    create_call = next(call for call in manager.calls if call[0] == "create")
    definition = create_call[2]
    part_paths = {part["path"] for part in definition["parts"]}
    assert any(path.startswith("EntityTypes/") for path in part_paths)
    assert any(path.startswith("RelationshipTypes/") for path in part_paths)
    # Registration only points at already-materialized Delta tables; it must
    # never configure Fabric IQ to "detect"/"infer" anything (Pitfall 2).
    assert "detect" not in json.dumps(definition).lower()
    assert "infer" not in json.dumps(definition).lower()
