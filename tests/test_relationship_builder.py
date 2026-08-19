from __future__ import annotations

from test_entity_builder import resource

from ontology.entity_builder import EntityBuilder
from ontology.relationship_builder import RelationshipBuilder


def test_relationship_builder_discovers_structural_and_tag_relationships():
    entities = EntityBuilder().build([resource()], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    triples = {
        (row["subject_type"], row["predicate"], row["object_type"])
        for row in relationships
    }

    assert ("Tenant", "owns", "Subscription") in triples
    assert ("Subscription", "contains", "ResourceGroup") in triples
    assert ("ResourceGroup", "contains", "VirtualMachine") in triples
    assert ("VirtualMachine", "member_of", "Application") in triples
    assert ("Application", "hosted_on", "VirtualMachine") in triples
    assert ("SupportTeam", "supports", "Application") in triples
    assert ("Owner", "owns", "Service") in triples
    assert ("BusinessService", "contains", "Application") in triples


def test_relationships_are_stable_and_deduplicated():
    entities = EntityBuilder().build([resource(), resource()], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    ids = [row["resource_id"] for row in relationships]

    assert len(ids) == len(set(ids))
    assert RelationshipBuilder().build(entities, "run-3")[0]["resource_id"] == relationships[0]["resource_id"]


def test_application_dependencies_are_discovered_from_dependency_tags():
    row = resource()
    row["payload_json"] = row["payload_json"].replace(
        '"AppName": "Payments API",',
        '"AppName": "Payments API", "DependsOn": "Identity API, Ledger API",',
    )
    entities = EntityBuilder().build([row], "run-2")

    relationships = RelationshipBuilder().build(entities, "run-2")
    dependencies = [row for row in relationships if row["predicate"] == "depends_on"]

    assert {
        next(e["name"] for e in entities if e["resource_id"] == rel["object_id"])
        for rel in dependencies
    } == {"Identity API", "Ledger API"}


def test_management_group_hierarchy_is_discovered():
    management_group = resource(
        resource_id="/providers/microsoft.management/managementgroups/mg-root",
        entity_type="ManagementGroup",
        resource_type="microsoft.management/managementgroups",
        name="mg-root",
        payload_json=(
            '{"id":"/providers/microsoft.management/managementgroups/mg-root",'
            '"name":"mg-root","tenantId":"tenant-1"}'
        ),
    )
    subscription = resource(
        resource_id="/subscriptions/sub-1",
        entity_type="Subscription",
        resource_type="microsoft.resources/subscriptions",
        name="sub-1",
        payload_json=(
            '{"id":"/subscriptions/sub-1","name":"sub-1","tenantId":"tenant-1",'
            '"subscriptionId":"sub-1","managementGroupAncestorsChain":[{"name":"mg-root"}]}'
        ),
    )
    entities = EntityBuilder().build([management_group, subscription], "run-2")

    relationships = RelationshipBuilder().build(entities, "run-2")

    assert any(
        row["subject_type"] == "ManagementGroup"
        and row["predicate"] == "contains"
        and row["object_type"] == "Subscription"
        for row in relationships
    )
