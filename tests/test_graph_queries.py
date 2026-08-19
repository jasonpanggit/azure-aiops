from __future__ import annotations

from test_entity_builder import resource

from ontology.entity_builder import EntityBuilder
from ontology.graph_queries import OntologyQueryService
from ontology.relationship_builder import RelationshipBuilder


def service():
    entities = EntityBuilder().build([resource()], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    return OntologyQueryService(entities, relationships)


def test_graph_queries_answer_required_operational_questions():
    query = service()

    owner = query.answer("Who owns this VM?", entity="vm1")
    applications = query.answer("What does this VM belong to?", entity="vm1")
    resources = query.answer("What resources belong to Service X?", entity="Retail")
    impact = query.answer("What is impacted if this server fails?", entity="vm1")
    business_service = query.answer("What business service owns this?", entity="vm1")

    assert owner["items"][0]["name"] == "ops@example.com"
    assert any(item["entity_type"] == "Application" for item in applications["items"])
    assert any(item["entity_type"] == "VirtualMachine" for item in resources["items"])
    assert {item["entity_type"] for item in impact["items"]} >= {
        "Application",
        "BusinessService",
    }
    assert business_service["items"][0]["name"] == "Retail"


def test_query_reports_missing_ownership_and_orphans():
    row = resource()
    row["payload_json"] = row["payload_json"].replace('"Owner": "ops@example.com",', "")
    entities = EntityBuilder().build([row], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")
    query = OntologyQueryService(entities, relationships)

    assert query.answer("Find resources with missing ownership")["count"] == 1
    assert isinstance(query.answer("Show orphan infrastructure")["items"], list)


def test_query_finds_applications_affected_by_patch_failures():
    vm = resource()
    assessment = resource(
        resource_id="assessment-1",
        entity_type="PatchAssessment",
        name="assessment-1",
        resource_type="microsoft.compute/patchassessmentresults",
        payload_json=(
            '{"id":"assessment-1","name":"assessment-1","tenantId":"tenant-1",'
            '"subscriptionId":"sub-1","targetResourceId":"'
            + vm["resource_id"]
            + '","status":"failed"}'
        ),
    )
    entities = EntityBuilder().build([vm, assessment], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    result = OntologyQueryService(entities, relationships).answer(
        "What applications are affected by patch failures?"
    )

    assert [row["name"] for row in result["items"]] == ["Payments API"]


def test_query_projection_excludes_raw_inventory_and_lineage():
    result = service().answer("Who owns this VM?", entity="vm1")

    sensitive = {
        "payload_json",
        "lineage_json",
        "semantic_metadata_json",
        "tenant_id",
        "subscription_id",
        "resource_id",
    }
    assert not sensitive & set(result["items"][0])


def test_shared_owner_does_not_connect_unrelated_impact_graphs():
    first = resource()
    second = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=resource()["payload_json"]
        .replace("vm1", "vm2")
        .replace("Payments API", "Identity API")
        .replace("Retail", "Wholesale")
        .replace("Production", "Development")
        .replace("CC-42", "CC-99")
        .replace("SRE", "Platform")
        .replace("Checkout", "Identity"),
    )
    entities = EntityBuilder().build([first, second], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    result = OntologyQueryService(entities, relationships).answer(
        "Show impacted business services", entity="vm1"
    )

    assert [row["name"] for row in result["items"]] == ["Retail"]


def test_shared_service_does_not_connect_unrelated_impact_graphs():
    first = resource()
    second = resource(
        resource_id="/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm2",
        name="vm2",
        payload_json=resource()["payload_json"]
        .replace("vm1", "vm2")
        .replace("Payments API", "Identity API")
        .replace("Retail", "Wholesale")
        .replace("Production", "Development")
        .replace("CC-42", "CC-99")
        .replace("ops@example.com", "identity@example.com")
        .replace("SRE", "Platform"),
    )
    entities = EntityBuilder().build([first, second], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    result = OntologyQueryService(entities, relationships).answer(
        "Show impacted business services", entity="vm1"
    )

    assert [row["name"] for row in result["items"]] == ["Retail"]


def test_compliance_by_application_returns_aggregation():
    vm = resource()
    assessment = resource(
        resource_id="assessment-1",
        entity_type="PatchAssessment",
        name="assessment-1",
        resource_type="microsoft.compute/patchassessmentresults",
        payload_json=(
            '{"id":"assessment-1","tenantId":"tenant-1","subscriptionId":"sub-1",'
            '"targetResourceId":"' + vm["resource_id"] + '","status":"failed"}'
        ),
    )
    entities = EntityBuilder().build([vm, assessment], "run-2")
    relationships = RelationshipBuilder().build(entities, "run-2")

    result = OntologyQueryService(entities, relationships).answer(
        "Show compliance by application"
    )
    application = next(row for row in entities if row["entity_type"] == "Application")

    assert result["items"] == [
        {
            "application_id": application["resource_id"],
            "application_name": "Payments API",
            "server_count": 1,
            "assessed_server_count": 1,
            "failed_assessment_count": 1,
            "compliant": False,
        }
    ]
