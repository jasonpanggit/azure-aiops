from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine


def engine() -> SemanticEngine:
    return SemanticEngine.from_rows(**semantic_scenario())


def test_vm_failure_impact_tree_is_directional():
    impact = engine().get_impact_context("vm-identity")

    assert impact["root"]["name"] == "vm-identity"
    assert {row["name"] for row in impact["impacted_applications"]} == {
        "Identity",
        "Payments",
    }
    assert {row["name"] for row in impact["impacted_business_services"]} == {
        "Retail",
        "Shared Platform",
    }
    assert impact["blast_radius"]["application_count"] == 2


def test_patch_failure_impact_reaches_business_service():
    impact = engine().get_impact_context("patch-payments")

    assert impact["cause_type"] == "PatchAssessment"
    assert [row["name"] for row in impact["impacted_business_services"]] == [
        "Retail"
    ]


def test_upstream_and_downstream_dependency_chains_are_distinct():
    semantic = engine()

    upstream = semantic.query("Show upstream dependencies", subject="Payments")
    downstream = semantic.query("Show downstream impact", subject="Identity")

    assert [row["name"] for row in upstream["items"]] == ["Identity"]
    assert [row["name"] for row in downstream["items"]] == ["Payments"]


def test_application_name_collision_resolves_impact_to_application_domain():
    impact = engine().get_impact_context("Identity")

    assert impact["cause_type"] == "Application"
    assert impact["root"]["entity_type"] == "Application"


def test_impact_tree_preserves_downstream_dependency_path():
    impact = engine().get_impact_context("vm-identity")
    identity = next(
        child for child in impact["tree"]["children"] if child["node"]["name"] == "Identity"
    )

    assert any(
        child["relation"] == "downstream_dependency"
        and child["node"]["name"] == "Payments"
        for child in identity["children"]
    )


def test_impact_tree_obeys_global_traversal_budget():
    scenario = semantic_scenario()
    applications = [
        {
            "resource_id": f"app-{index}",
            "entity_type": "Application",
            "name": f"App {index}",
            "lifecycle_status": "active",
        }
        for index in range(30)
    ]
    dependencies = [
        {
            "resource_id": f"dependency-{index}",
            "subject_id": f"app-{index + 1}",
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": f"app-{index}",
            "object_type": "Application",
            "lifecycle_status": "active",
        }
        for index in range(29)
    ]
    scenario["entities"].extend(applications)
    scenario["relationships"].extend(dependencies)
    semantic = SemanticEngine.from_rows(**scenario, max_traversal_nodes=10)

    impact = semantic.get_impact_context("App 0")

    def application_nodes(node):
        return int(node["node"]["entity_type"] == "Application") + sum(
            application_nodes(child) for child in node.get("children", [])
        )

    assert application_nodes(impact["tree"]) == 10
    assert impact["truncated"]


def test_impact_metadata_marks_service_truncation():
    scenario = semantic_scenario()
    payments_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["entity_type"] == "Application" and row["name"] == "Payments"
    )
    services = [
        {
            "resource_id": f"service-{index}",
            "entity_type": "Service",
            "name": f"Service {index}",
            "lifecycle_status": "active",
        }
        for index in range(60)
    ]
    relationships = [
        {
            "resource_id": f"implements-{index}",
            "subject_id": payments_id,
            "subject_type": "Application",
            "predicate": "implements",
            "object_id": f"service-{index}",
            "object_type": "Service",
            "lifecycle_status": "active",
        }
        for index in range(60)
    ]
    scenario["entities"].extend(services)
    scenario["relationships"].extend(relationships)

    impact = SemanticEngine.from_rows(**scenario).get_impact_context("Payments")

    assert len(impact["impacted_services"]) == 50
    assert impact["collection_metadata"]["impacted_services"] == {
        "count": 61,
        "returned": 50,
        "truncated": True,
    }
    assert impact["truncated"]


def test_impact_tree_budget_includes_service_and_business_nodes():
    scenario = semantic_scenario()
    payments_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["entity_type"] == "Application" and row["name"] == "Payments"
    )
    scenario["entities"].extend(
        {
            "resource_id": f"budget-service-{index}",
            "entity_type": "Service",
            "name": f"Budget Service {index}",
            "lifecycle_status": "active",
        }
        for index in range(20)
    )
    scenario["relationships"].extend(
        {
            "resource_id": f"budget-implements-{index}",
            "subject_id": payments_id,
            "subject_type": "Application",
            "predicate": "implements",
            "object_id": f"budget-service-{index}",
            "object_type": "Service",
            "lifecycle_status": "active",
        }
        for index in range(20)
    )
    semantic = SemanticEngine.from_rows(**scenario, max_traversal_nodes=10)

    impact = semantic.get_impact_context("Payments")

    def node_count(node):
        return 1 + sum(node_count(child) for child in node.get("children", []))

    assert node_count(impact["tree"]) <= 10
    assert impact["truncated"]


def test_cycle_markers_consume_the_global_tree_budget():
    entities = [
        {
            "resource_id": f"app-{index}",
            "entity_type": "Application",
            "name": f"App {index}",
            "lifecycle_status": "active",
        }
        for index in range(4)
    ]
    edges = ((1, 0), (2, 0), (0, 1), (3, 1))
    relationships = [
        {
            "resource_id": f"edge-{subject}-{object_}",
            "subject_id": f"app-{subject}",
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": f"app-{object_}",
            "object_type": "Application",
            "lifecycle_status": "active",
        }
        for subject, object_ in edges
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        max_traversal_nodes=4,
    )

    impact = semantic.get_impact_context("App 0")

    def node_count(node):
        return 1 + sum(node_count(child) for child in node.get("children", []))

    assert node_count(impact["tree"]) <= 4
    assert impact["truncated"]


def test_aggregate_tree_child_slicing_sets_truncated():
    entities = [
        {
            "resource_id": "application",
            "entity_type": "Application",
            "name": "Application",
            "lifecycle_status": "active",
        },
        *[
            {
                "resource_id": f"business-{index}",
                "entity_type": "BusinessService",
                "name": f"Business {index}",
                "lifecycle_status": "active",
            }
            for index in range(30)
        ],
        *[
            {
                "resource_id": f"service-{index}",
                "entity_type": "Service",
                "name": f"Service {index}",
                "lifecycle_status": "active",
            }
            for index in range(30)
        ],
    ]
    relationships = [
        *[
            {
                "resource_id": f"contains-{index}",
                "subject_id": f"business-{index}",
                "subject_type": "BusinessService",
                "predicate": "contains",
                "object_id": "application",
                "object_type": "Application",
                "lifecycle_status": "active",
            }
            for index in range(30)
        ],
        *[
            {
                "resource_id": f"implements-{index}",
                "subject_id": "application",
                "subject_type": "Application",
                "predicate": "implements",
                "object_id": f"service-{index}",
                "object_type": "Service",
                "lifecycle_status": "active",
            }
            for index in range(30)
        ],
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        max_results=50,
    )

    impact = semantic.get_impact_context("Application")

    assert len(impact["tree"]["children"]) == 50
    assert not impact["collection_metadata"]["impacted_business_services"][
        "truncated"
    ]
    assert not impact["collection_metadata"]["impacted_services"]["truncated"]
    assert impact["truncated"]
