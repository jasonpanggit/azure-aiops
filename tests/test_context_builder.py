from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine


def engine() -> SemanticEngine:
    return SemanticEngine.from_rows(**semantic_scenario())


def test_builds_compact_vm_context_from_semantic_knowledge():
    payload = engine().get_resource_context("vm-payments")

    assert payload["context_type"] == "resource"
    assert payload["subject"]["name"] == "vm-payments"
    assert payload["sections"]["applications"][0]["name"] == "Payments"
    assert payload["sections"]["ownership"][0]["name"] == "ops@example.com"
    assert payload["sections"]["compliance"]["status"] == "failed"
    assert payload["sections"]["patching"]["failed_patch_count"] == 2
    assert payload["sections"]["advisor_findings"][0]["name"] == "advisor-payments"
    assert payload["sections"]["resource_health"]["status"] == "degraded"
    assert payload["sections"]["cost_context"][0]["name"] == "CC-42"
    assert payload["sections"]["security_findings"][0]["severity"] == "high"
    assert payload["risk"]["level"] == "Critical"
    assert "payload_json" not in str(payload)


def test_builds_application_service_and_subscription_views():
    semantic = engine()

    application = semantic.get_application_context("Payments")
    service = semantic.get_service_context("Retail")
    subscription = semantic.get_subscription_context("sub-1")

    assert {row["name"] for row in application["sections"]["infrastructure"]} == {
        "vm-payments"
    }
    assert application["sections"]["support_teams"][0]["name"] == "SRE"
    assert service["sections"]["applications"][0]["name"] == "Payments"
    assert subscription["sections"]["resource_count"] == 2


def test_latest_compliance_fact_wins_regardless_of_input_order():
    scenario = semantic_scenario()
    target = scenario["compliance"][0]["assessed_resource_id"]
    old = {
        "assessed_resource_id": target,
        "status": "failed",
        "timestamp": "2026-08-16T00:00:00Z",
    }
    new = {
        "assessed_resource_id": target,
        "status": "compliant",
        "timestamp": "2026-08-18T00:00:00Z",
    }

    first = SemanticEngine.from_rows(**{**scenario, "compliance": [old, new]})
    second = SemanticEngine.from_rows(**{**scenario, "compliance": [new, old]})

    assert first.get_resource_context("vm-payments")["sections"]["compliance"]["status"] == "compliant"
    assert second.get_resource_context("vm-payments")["sections"]["compliance"]["status"] == "compliant"


def test_malformed_or_missing_compliance_is_unknown_without_patch_penalty():
    scenario = semantic_scenario()
    target = scenario["compliance"][0]["assessed_resource_id"]
    scenario["compliance"] = [
        {
            "assessed_resource_id": target,
            "payload_json": "[]",
            "timestamp": "2026-08-18T00:00:00Z",
        }
    ]
    semantic = SemanticEngine.from_rows(**scenario)

    context = semantic.get_resource_context("vm-payments")

    assert context["sections"]["compliance"]["status"] == "unknown"
    assert context["risk"]["factors"]["patch_noncompliance"] == 0


def test_context_list_sections_report_total_and_truncation():
    entities = [
        {
            "resource_id": "application",
            "entity_type": "Application",
            "name": "Large App",
            "lifecycle_status": "active",
        },
        *[
            {
                "resource_id": f"resource-{index}",
                "entity_type": "Resource",
                "name": f"Resource {index}",
                "lifecycle_status": "active",
            }
            for index in range(60)
        ],
    ]
    relationships = [
        {
            "resource_id": f"hosts-{index}",
            "subject_id": "application",
            "subject_type": "Application",
            "predicate": "hosted_on",
            "object_id": f"resource-{index}",
            "object_type": "Resource",
            "lifecycle_status": "active",
        }
        for index in range(60)
    ]
    semantic = SemanticEngine.from_rows(
        entities=entities,
        relationships=relationships,
        inventory=[
            {"resource_id": f"resource-{index}", "name": f"Resource {index}"}
            for index in range(60)
        ],
    )

    context = semantic.get_application_context("Large App")

    assert len(context["sections"]["infrastructure"]) == 50
    assert context["section_metadata"]["infrastructure"] == {
        "count": 60,
        "returned": 50,
        "truncated": True,
    }
