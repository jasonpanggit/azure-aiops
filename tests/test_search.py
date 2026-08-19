from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine


def engine() -> SemanticEngine:
    return SemanticEngine.from_rows(**semantic_scenario())


def test_searches_production_owner_patch_and_business_context():
    semantic = engine()

    production = semantic.search_operational_context("Find all production applications")
    owned = semantic.search_operational_context("Find all applications owned by SRE")
    failed = semantic.search_operational_context("Find all servers with failed patches")
    related = semantic.search_operational_context(
        "Find resources related to Business Service Retail"
    )

    assert {row["name"] for row in production["items"]} == {"Identity", "Payments"}
    assert [row["name"] for row in owned["items"]] == ["Payments"]
    assert [row["name"] for row in failed["items"]] == ["vm-payments"]
    assert [row["name"] for row in related["items"]] == ["vm-payments"]


def test_searches_ownership_gaps_and_critical_infrastructure():
    scenario = semantic_scenario()
    scenario["relationships"] = [
        row
        for row in scenario["relationships"]
        if not (
            row["predicate"] == "owned_by"
            and row["subject_id"].endswith("vm-identity")
        )
    ]
    semantic = SemanticEngine.from_rows(**scenario)

    gaps = semantic.search_operational_context("Find applications missing ownership")
    critical = semantic.search_operational_context("Find critical infrastructure")

    assert [row["name"] for row in gaps["items"]] == ["Identity"]
    assert [row["name"] for row in critical["items"]] == ["vm-payments"]
