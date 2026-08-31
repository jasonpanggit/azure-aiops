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


def test_live_flow_logs_from_rows_maps_traffic_analytics_shape():
    """NTANetAnalytics (VNet flow logs) uses unsuffixed column names and
    single-letter protocol/status codes -- both must be normalized to the
    ARM NSG rule vocabulary before the join can match anything."""
    from fabric_pipelines.flowlog_ingest import FlowLogRecord, live_flow_logs_from_rows

    rows = [
        {
            "TimeGenerated": OBSERVED_AT,
            "SrcIp": "10.10.0.5",
            "DestIp": "10.10.1.4",
            "L4Protocol": "T",
            "DestPort": 443.0,
            "FlowStatus": "A",
        },
        {
            "TimeGenerated": OBSERVED_AT,
            "SrcIp": "203.0.113.9",
            "DestIp": "10.10.1.4",
            "L4Protocol": "U",
            "DestPort": 53,
            "FlowStatus": "D",
        },
        # dropped: missing destination port -- incomplete observation, not evidence
        {
            "TimeGenerated": OBSERVED_AT,
            "SrcIp": "10.0.0.1",
            "DestIp": "10.0.0.2",
            "L4Protocol": "T",
            "DestPort": None,
            "FlowStatus": "A",
        },
        # dropped: unrecognised protocol code -- never guessed at (D-05)
        {
            "TimeGenerated": OBSERVED_AT,
            "SrcIp": "10.0.0.3",
            "DestIp": "10.0.0.4",
            "L4Protocol": "X",
            "DestPort": 443,
            "FlowStatus": "A",
        },
    ]

    records = live_flow_logs_from_rows(rows)

    assert records == [
        FlowLogRecord(
            source_address="10.10.0.5",
            destination_address="10.10.1.4",
            destination_port="443",
            protocol="Tcp",
            decision="Allow",
            observed_at=OBSERVED_AT,
        ),
        FlowLogRecord(
            source_address="203.0.113.9",
            destination_address="10.10.1.4",
            destination_port="53",
            protocol="Udp",
            decision="Deny",
            observed_at=OBSERVED_AT,
        ),
    ]


def test_live_flow_log_query_targets_vnet_schema_not_retired_nsg_schema():
    """Guard against regressing to the retired AzureNetworkAnalytics_CL
    column names, which do not resolve against NTANetAnalytics and would
    fail the query with a KQL semantic error at runtime."""
    from onboarding.monitor_logs import NSG_FLOW_LOG_QUERY

    assert "NTANetAnalytics" in NSG_FLOW_LOG_QUERY
    assert 'SubType == "FlowLog"' in NSG_FLOW_LOG_QUERY
    for retired_column in ("SrcIP_s", "DestIP_s", "L4Protocol_s", "DestPort_d", "FlowStatus_s"):
        assert retired_column not in NSG_FLOW_LOG_QUERY


def test_live_flow_log_join_uses_cidr_containment_and_live_provenance():
    """A live flow log whose source falls *inside* a rule's declared CIDR
    (but isn't an exact string match) must still match -- and the resulting
    edge must carry live-mode provenance, not the fixture markers."""
    from fabric_pipelines.flowlog_ingest import (
        FlowLogRecord,
        join_flow_logs_with_nsg_rules,
    )

    rules = [
        {
            "id": "rule-allow-https",
            "protocol": "Tcp",
            "sourceAddress": "10.10.0.0/16",
            "destinationAddress": "10.10.1.0/24",
            "destinationPort": "443",
            "access": "Allow",
            "isDefault": False,
        }
    ]
    flows = [
        FlowLogRecord(
            source_address="10.10.5.7",  # contained by 10.10.0.0/16, not an exact match
            destination_address="10.10.1.20",
            destination_port="443",
            protocol="Tcp",
            decision="Allow",
            observed_at=OBSERVED_AT,
        )
    ]

    edges = join_flow_logs_with_nsg_rules(rules, flows, observed=OBSERVED_AT, live=True)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["source"] == "fabric_pipeline:flowlog_live"
    assert edge["confidence"] == 0.95
    assert edge["assertionState"] == "accepted"
    assert edge["attributes"]["dataSource"] == "traffic_analytics"
    assert edge["attributes"]["allowedVsObserved"] == "allowed_and_observed"


def test_live_flow_log_join_matches_port_ranges():
    from fabric_pipelines.flowlog_ingest import (
        FlowLogRecord,
        join_flow_logs_with_nsg_rules,
    )

    rules = [
        {
            "id": "rule-allow-web-range",
            "protocol": "Tcp",
            "sourceAddress": "*",
            "destinationAddress": "10.10.1.0/24",
            "destinationPort": "8000-8100",
            "access": "Allow",
            "isDefault": False,
        }
    ]
    flows = [
        FlowLogRecord(
            source_address="203.0.113.1",
            destination_address="10.10.1.5",
            destination_port="8050",
            protocol="Tcp",
            decision="Allow",
            observed_at=OBSERVED_AT,
        )
    ]

    edges = join_flow_logs_with_nsg_rules(rules, flows, observed=OBSERVED_AT, live=True)

    assert len(edges) == 1
    assert edges[0]["objectId"] == "rule-allow-web-range"


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


def _acl_rules():
    """Two NSGs deliberately reusing one rule name, plus a distinct name.

    Rule names are only unique within an NSG, so this shape is what makes
    ``AclGroup`` disambiguation necessary rather than decorative.
    """
    return [
        {
            "id": "rule-a-allow-web",
            "name": "allow-web",
            "nsgId": "/subscriptions/s/resourceGroups/rg/providers/"
            "Microsoft.Network/networkSecurityGroups/nsg-a",
            "protocol": "Tcp",
            "sourceAddress": "10.0.0.0/8",
            "destinationAddress": "10.0.1.0/24",
            "destinationPort": "443",
            "access": "Allow",
            "isDefault": False,
        },
        {
            "id": "rule-b-allow-web",
            "name": "allow-web",
            "nsgId": "/subscriptions/s/resourceGroups/rg/providers/"
            "Microsoft.Network/networkSecurityGroups/nsg-b",
            "protocol": "Tcp",
            "sourceAddress": "10.0.0.0/8",
            "destinationAddress": "10.0.1.0/24",
            "destinationPort": "443",
            "access": "Deny",
            "isDefault": False,
        },
    ]


def _acl_flow(**overrides):
    from fabric_pipelines.flowlog_ingest import FlowLogRecord

    defaults = {
        "source_address": "10.0.0.5",
        "destination_address": "10.0.1.9",
        "destination_port": "443",
        "protocol": "Tcp",
        "decision": "Allow",
        "observed_at": OBSERVED_AT,
    }
    defaults.update(overrides)
    return FlowLogRecord(**defaults)


def test_acl_rule_attribution_beats_cidr_inference():
    """Azure naming the rule that fired outranks us re-deriving it.

    Both fixture rules match this flow by CIDR, so inference alone would
    silently pick the first. AclRule + AclGroup identify the real one.
    """
    from fabric_pipelines.flowlog_ingest import join_flow_logs_with_nsg_rules

    flows = [_acl_flow(acl_rule="allow-web", acl_group="nsg-b")]
    edges = join_flow_logs_with_nsg_rules(
        _acl_rules(), flows, observed=OBSERVED_AT, live=True
    )

    assert len(edges) == 1
    assert edges[0]["objectId"] == "rule-b-allow-web"
    assert edges[0]["attributes"]["attribution"] == "acl_rule"
    # nsg-b denies, but the flow was allowed -- a contradiction only visible
    # because attribution picked the right rule.
    assert edges[0]["attributes"]["allowedVsObserved"] == "denied_but_traffic_observed"


def test_cidr_inference_is_used_when_azure_did_not_attribute():
    """Flows without AclRule still match, but are marked as inferred."""
    from fabric_pipelines.flowlog_ingest import join_flow_logs_with_nsg_rules

    edges = join_flow_logs_with_nsg_rules(
        _acl_rules(), [_acl_flow()], observed=OBSERVED_AT, live=True
    )

    assert len(edges) == 1
    assert edges[0]["attributes"]["attribution"] == "cidr_match"


def test_an_unknown_acl_rule_is_not_attributed_by_cidr_fallback():
    """Naming a rule we do not hold must not fall back to guessing.

    If Azure says rule X fired and X is outside the ingested scope, matching
    on CIDR would confidently attribute the flow to the *wrong* rule. Better
    to emit nothing than a plausible falsehood.
    """
    from fabric_pipelines.flowlog_ingest import join_flow_logs_with_nsg_rules

    flows = [_acl_flow(acl_rule="rule-from-another-subscription")]
    edges = join_flow_logs_with_nsg_rules(
        _acl_rules(), flows, observed=OBSERVED_AT, live=True
    )

    assert edges == []


def test_ambiguous_acl_rule_name_without_group_is_not_attributed():
    """A name matching two NSGs, with no group to disambiguate, is unresolvable."""
    from fabric_pipelines.flowlog_ingest import join_flow_logs_with_nsg_rules

    flows = [_acl_flow(acl_rule="allow-web")]  # no acl_group
    edges = join_flow_logs_with_nsg_rules(
        _acl_rules(), flows, observed=OBSERVED_AT, live=True
    )

    assert edges == []


def test_live_rows_carry_acl_attribution_fields():
    from fabric_pipelines.flowlog_ingest import live_flow_logs_from_rows

    rows = [
        {
            "SrcIp": "10.0.0.5",
            "DestIp": "10.0.1.9",
            "DestPort": 443,
            "L4Protocol": "T",
            "FlowStatus": "A",
            "AclRule": "allow-web",
            "AclGroup": "nsg-b",
            "TimeGenerated": OBSERVED_AT,
        }
    ]
    records = live_flow_logs_from_rows(rows)

    assert len(records) == 1
    assert records[0].acl_rule == "allow-web"
    assert records[0].acl_group == "nsg-b"
