from __future__ import annotations

import json
import math

import pytest

from ontology.entity_builder import EntityBuilder
from ontology.graph_queries import OntologyQueryService
from ontology.ontology_publisher import OntologyPublisher
from ontology.ontology_sync import OntologyGraphSynchronizer
from ontology.relationship_builder import RelationshipBuilder
from ontology.sync_validator import SyncValidator


def entity(entity_id: str, entity_type: str = "Resource", name: str = "entity") -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": entity_id,
        "timestamp": "2026-08-19T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": entity_type,
        "name": name,
        "resource_type": "microsoft.test/resources",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-19T00:00:00Z",
        "retired_at": "",
        "ontology_version": "1",
    }


def relationship(
    relationship_id: str,
    subject_id: str,
    object_id: str,
    *,
    confidence=1.0,
) -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": relationship_id,
        "timestamp": "2026-08-19T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "subject_id": subject_id,
        "subject_type": "Resource",
        "predicate": "depends_on",
        "object_id": object_id,
        "object_type": "Resource",
        "confidence": confidence,
        "source": "test",
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-19T00:00:00Z",
        "retired_at": "",
        "ontology_version": "1",
    }


def test_sync_validator_rejects_canonical_duplicates_and_malformed_rows():
    validator = SyncValidator()
    assert not validator.validate([entity("A"), entity("a")], []).passed
    assert not validator.validate(
        [entity("a"), entity("b")],
        [relationship("EDGE", "a", "b"), relationship("edge", "a", "b")],
    ).passed
    for confidence in (True, math.nan, math.inf, -0.1, 1.1):
        assert not validator.validate(
            [entity("a"), entity("b")],
            [relationship("edge", "a", "b", confidence=confidence)],
        ).passed
    malformed = entity("a")
    malformed["entity_type"] = False
    assert not validator.validate([malformed], []).passed


def test_incremental_sync_is_case_canonical_and_retires_missing_records():
    previous_a = entity("A", name="old")
    previous_a["valid_from"] = "2026-01-01T00:00:00Z"
    previous_b = entity("B", name="removed")
    current_a = entity("a", name="new")

    result = OntologyGraphSynchronizer(SyncValidator()).synchronize(
        [current_a],
        [],
        previous_entities=[previous_a, previous_b],
        ontology_version="2",
        timestamp="2026-08-19T01:00:00Z",
    )

    assert len([row for row in result.entities if row["resource_id"] == "a"]) == 1
    active = next(row for row in result.entities if row["resource_id"] == "a")
    retired = next(row for row in result.entities if row["resource_id"] == "b")
    assert active["valid_from"] == "2026-01-01T00:00:00Z"
    assert retired["lifecycle_status"] == "retired"
    assert retired["retired_at"] == "2026-08-19T01:00:00Z"


def test_retired_relationship_with_reclassified_endpoint_type_passes_validation():
    """A resource's entity_type can change between syncs (e.g. Resource ->
    ManagedIdentity as ARM enriches the record). A relationship captured
    against the *old* type that later gets retired (because it's no longer
    reported) must not be treated as a data-quality defect purely because its
    stale subject_type/object_type no longer matches the entity's *current*
    type -- only active relationships must agree with the live entity_type.
    """
    previous_a = entity("a", entity_type="Resource")
    previous_b = entity("b", entity_type="Resource")
    stale_edge = relationship("edge", "a", "b")

    reclassified_b = entity("b", entity_type="ManagedIdentity")
    current_a = entity("a", entity_type="Resource")

    result = OntologyGraphSynchronizer(SyncValidator()).synchronize(
        [current_a, reclassified_b],
        [],
        previous_entities=[previous_a, previous_b],
        previous_relationships=[stale_edge],
        ontology_version="2",
        timestamp="2026-08-19T01:00:00Z",
    )

    retired_edge = next(
        row for row in result.relationships if row["resource_id"] == "edge"
    )
    assert retired_edge["lifecycle_status"] == "retired"
    assert retired_edge["object_type"] == "Resource"  # stale, unchanged


def test_sync_fails_closed_before_returning_an_invalid_graph():
    with pytest.raises(ValueError, match="ontology graph"):
        OntologyGraphSynchronizer(SyncValidator()).synchronize(
            [entity("a")],
            [relationship("edge", "a", "missing")],
        )


def test_entity_builder_enforces_source_tag_and_string_bounds():
    with pytest.raises(ValueError):
        EntityBuilder(max_source_rows=1).build(
            [entity("a"), entity("b")], "run"
        )
    malformed = entity("a")
    malformed["payload_json"] = '{"tags": ["bad"]}'
    with pytest.raises(TypeError, match="tags"):
        EntityBuilder().build([malformed], "run")
    oversized = entity("a")
    oversized["payload_json"] = '{"tags": {"AppName": "' + "x" * 33 + '"}}'
    with pytest.raises(ValueError, match="tag value"):
        EntityBuilder(max_tag_value_chars=32).build([oversized], "run")
    with pytest.raises(ValueError, match="entity bound"):
        EntityBuilder(max_entities=1).build([entity("a")], "run")
    malformed_json = entity("a")
    malformed_json["payload_json"] = "{bad"
    with pytest.raises(ValueError, match="payload_json"):
        EntityBuilder().build([malformed_json], "run")
    for field_name in ("lineage_json", "semantic_metadata_json"):
        malformed_metadata = entity("a")
        malformed_metadata[field_name] = "{bad"
        with pytest.raises(ValueError, match=field_name):
            EntityBuilder().build([malformed_metadata], "run")

    upper = entity("A", name="UPPER")
    lower = entity("a", name="lower")
    with pytest.raises(ValueError, match="canonical duplicate"):
        EntityBuilder().build([upper, lower], "run")
    alias_upper = entity("A", name="same")
    alias_lower = entity("a", name="same")
    aliases = EntityBuilder().build([alias_upper, alias_lower], "run")
    assert len([row for row in aliases if row["resource_id"] == "a"]) == 1


def test_relationship_and_synchronization_source_bounds_fail_closed():
    with pytest.raises(ValueError, match="entity source"):
        RelationshipBuilder(max_entities=1).build(
            [entity("a"), entity("b")], "run"
        )
    with pytest.raises(ValueError, match="entity source"):
        OntologyGraphSynchronizer(SyncValidator(), max_entities=1).synchronize(
            [entity("a"), entity("b")], []
        )


def test_graph_queries_bound_source_results_and_cyclic_traversal():
    with pytest.raises(ValueError):
        OntologyQueryService([entity("a"), entity("b")], [], max_source_entities=1)

    applications = [
        entity(f"app-{index}", "Application", f"App {index}")
        for index in range(10)
    ]
    edges = [
        {
            **relationship(f"edge-{index}", f"app-{index}", f"app-{(index + 1) % 10}"),
            "subject_type": "Application",
            "object_type": "Application",
        }
        for index in range(10)
    ]
    result = OntologyQueryService(
        applications,
        edges,
        max_results=2,
        max_traversal_nodes=3,
    ).answer("What is impacted if this server fails?", entity="App 0")
    assert result["returned"] <= 2
    assert result["truncated"] is True

    duplicate_edges = [
        relationship("EDGE", "app-0", "app-1"),
        relationship("edge", "app-0", "app-1"),
    ]
    with pytest.raises(ValueError):
        OntologyQueryService(applications, duplicate_edges)


def test_health_ignores_retired_relationships_and_query_revalidates_graph():
    resource = entity("r")
    owner = entity("owner", "Owner", "owner@example.com")
    retired = relationship("owned", "r", "owner")
    retired.update(
        {
            "predicate": "owned_by",
            "object_type": "Owner",
            "lifecycle_status": "retired",
            "retired_at": "2026-08-19T01:00:00Z",
        }
    )
    graph = OntologyGraphSynchronizer(SyncValidator()).synchronize(
        [resource, owner], [retired]
    )
    assert graph.health["relationship_count"] == 0
    assert graph.health["missing_ownership"] == 1
    assert graph.health["orphan_resources"] == 1

    malformed_lifecycle = entity("r")
    malformed_lifecycle["lifecycle_status"] = "bogus"
    with pytest.raises(ValueError, match="validation"):
        OntologyQueryService([malformed_lifecycle], [])

    bad_edge = relationship("edge", "r", "owner", confidence=math.nan)
    bad_edge["subject_type"] = "Application"
    with pytest.raises(ValueError, match="validation"):
        OntologyQueryService([resource, owner], [bad_edge])

    missing_source = relationship("edge", "r", "owner")
    missing_source.pop("source")
    with pytest.raises(ValueError, match="validation"):
        OntologyQueryService([resource, owner], [missing_source])


def test_sync_rejects_incomplete_current_and_previous_version_metadata():
    for field_name in ("change_version", "valid_from", "ontology_version"):
        current = entity("a")
        current.pop(field_name)
        with pytest.raises(ValueError, match="current snapshot"):
            OntologyGraphSynchronizer(SyncValidator()).synchronize([current], [])

        previous = entity("a")
        previous.pop(field_name)
        with pytest.raises(ValueError, match="previous snapshot"):
            OntologyGraphSynchronizer(SyncValidator()).synchronize(
                [entity("a")], [], previous_entities=[previous]
            )


def test_synthetic_hierarchy_lineage_is_complete_and_input_order_independent():
    subscription = entity("/subscriptions/sub-1", "Subscription", "sub-1")
    vm = entity(
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
        "VirtualMachine",
        "vm",
    )
    vm["payload_json"] = (
        '{"tenantId":"tenant-1","subscriptionId":"sub-1",'
        '"resourceGroup":"rg"}'
    )
    first = EntityBuilder().build([subscription, vm], "run")
    second = EntityBuilder().build([vm, subscription], "run")
    assert first == second
    tenant = next(row for row in first if row["entity_type"] == "Tenant")
    assert json.loads(tenant["lineage_json"])["source_resource_ids"] == sorted(
        [subscription["resource_id"], vm["resource_id"].casefold()]
    )


def test_active_relationship_to_retired_endpoint_fails_validation_and_sync():
    active = entity("a")
    retired = entity("b")
    retired["lifecycle_status"] = "retired"
    retired["retired_at"] = "2026-08-19T01:00:00Z"
    edge = relationship("edge", "a", "b")
    assert not SyncValidator().validate([active, retired], [edge]).passed
    with pytest.raises(ValueError, match="current snapshot"):
        OntologyGraphSynchronizer(SyncValidator()).synchronize(
            [active, retired], [edge]
        )


def test_publisher_rejects_relationships_with_unknown_endpoint_types():
    class Manager:
        pass

    publisher = OntologyPublisher(
        Manager(), workspace_id="workspace", lakehouse_id="lakehouse"
    )
    with pytest.raises(ValueError, match="endpoint"):
        publisher.build_definition(
            {"Application": "apps"},
            {("Missing", "owns", "Application"): "relationships"},
            "Operational_Context",
        )


def test_synchronize_defers_dangling_edge_instead_of_dropping_it():
    from ontology.pending_relationships import PendingRelationshipStore

    store = PendingRelationshipStore()
    a = entity("a")
    edge_to_missing_b = relationship("edge-ab", "a", "b")

    result = OntologyGraphSynchronizer(SyncValidator(), pending_relationships=store).synchronize(
        [a], [edge_to_missing_b]
    )

    assert all(row["resource_id"] != "edge-ab" for row in result.relationships)
    assert len(result.pending_relationships) == 1
    assert result.pending_relationships[0]["resource_id"] == "edge-ab"
    assert len(store) == 1


def test_synchronize_resolves_deferred_edge_once_target_entity_appears():
    from ontology.pending_relationships import PendingRelationshipStore

    store = PendingRelationshipStore()
    a = entity("a")
    edge_to_missing_b = relationship("edge-ab", "a", "b")
    synchronizer = OntologyGraphSynchronizer(SyncValidator(), pending_relationships=store)

    first = synchronizer.synchronize([a], [edge_to_missing_b])
    assert len(first.pending_relationships) == 1

    b = entity("b")
    second = synchronizer.synchronize([a, b], [])

    assert any(row["resource_id"] == "edge-ab" for row in second.relationships)
    assert second.pending_relationships == []
    assert len(store) == 0
