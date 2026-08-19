from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine


def engine() -> SemanticEngine:
    return SemanticEngine.from_rows(**semantic_scenario())


def test_required_semantic_query_intents_route_to_views():
    semantic = engine()

    assert semantic.query("Show application context", subject="Payments")["context_type"] == "application"
    assert semantic.query("Show service context", subject="Retail")["context_type"] == "service"
    assert semantic.query("Show VM context", subject="vm-payments")["context_type"] == "resource"
    assert semantic.query("Show server context", subject="vm-payments")["context_type"] == "resource"
    assert semantic.query("Show subscription context", subject="sub-1")["context_type"] == "subscription"
    assert semantic.query("Find orphan resources")["count"] == 0
    assert semantic.query("Find ownership gaps")["count"] == 0
    assert semantic.query("Show operational risk", subject="vm-payments")["risk"]["level"] == "Critical"


def test_agent_api_methods_are_cacheable_and_versioned():
    semantic = engine()

    first = semantic.get_application_context("Payments")
    second = semantic.get_application_context("Payments")

    assert first == second
    assert semantic.cache.stats().hits == 1
    assert first["knowledge_version"].startswith("semantic-")


def test_success_criteria_questions_use_only_semantic_interface():
    semantic = engine()

    ownership = semantic.query("What owns this VM?", subject="vm-payments")
    outage = semantic.query(
        "What applications are impacted by this outage?", subject="vm-identity"
    )
    risks = semantic.query("What services are at operational risk?")
    patching = semantic.query("Which production workloads failed patching?")
    blast = semantic.query("What is the blast radius of this failure?", subject="vm-identity")
    owned = semantic.query("Show all applications owned by SRE")

    assert ownership["sections"]["ownership"][0]["name"] == "ops@example.com"
    assert {row["name"] for row in outage["impacted_applications"]} == {
        "Identity",
        "Payments",
    }
    assert {row["name"] for row in risks["items"]} >= {"Retail"}
    assert [row["name"] for row in patching["items"]] == ["vm-payments"]
    assert blast["blast_radius"]["application_count"] == 2
    assert [row["name"] for row in owned["items"]] == ["Payments"]


def test_public_results_do_not_echo_queries_or_raw_run_versions():
    semantic = engine()
    semantic.knowledge_version = "072c7d57-e970-4b20-b159-e19510748d2f"
    result = semantic.query(
        "Find ownership gaps /subscriptions/secret-sub/resourceGroups/secret"
    )

    text = str(result)
    assert "secret-sub" not in text
    assert "072c7d57" not in text
    assert result["knowledge_version"].startswith("semantic-")


def test_list_results_are_bounded_with_total_and_truncation():
    scenario = semantic_scenario()
    template = next(
        row for row in scenario["entities"] if row["entity_type"] == "VirtualMachine"
    )
    scenario["entities"] = [
        {
            **template,
            "resource_id": f"resource-{index}",
            "name": f"resource-{index}",
        }
        for index in range(60)
    ]
    scenario["relationships"] = []
    scenario["compliance"] = []
    scenario["security"] = []
    scenario["inventory"] = [
        {"resource_id": f"resource-{index}", "name": f"resource-{index}"}
        for index in range(60)
    ]
    semantic = SemanticEngine.from_rows(**scenario)

    result = semantic.query("Find ownership gaps")

    assert result["count"] == 60
    assert len(result["items"]) == 50
    assert result["truncated"]
