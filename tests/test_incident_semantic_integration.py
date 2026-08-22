from __future__ import annotations

from datetime import UTC, datetime

import pytest
from semantic_scenario import semantic_scenario

from intelligence.incident.incident_context_builder import IncidentContextBuilder
from intelligence.incident.incident_intelligence import IncidentIntelligence
from semantic.semantic_engine import SemanticEngine


def test_incident_context_is_built_only_through_public_semantic_apis():
    scenario = semantic_scenario()
    semantic = SemanticEngine.from_rows(**scenario)
    resource = {
        **scenario["inventory"][0],
        "connection_id": "prod-core",
    }
    resource_key = resource["resource_id"]

    engine = IncidentIntelligence.from_semantic_engine(
        semantic,
        inventory=[resource],
        incidents=[
            {
                "incident_id": "INC-1",
                "title": "Payments unavailable",
                "status": "Active",
                "severity": "Critical",
                "started_at": "2026-08-17T00:00:00Z",
                "resource_key": resource_key,
            }
        ],
        alerts=[],
        resource_changes=[],
        patch_findings=[],
        lifecycle_findings=[],
        history=[],
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )

    finding = engine.analyze()["findings"][0]

    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail"
    assert finding["owner"] == "ops@example.com"
    assert finding["support_team"] == "SRE"
    assert finding["subscription_id"] == "sub-1"
    assert finding["subscription_connection"] == "prod-core"
    assert finding["impacted_applications"] == ["Payments"]
    assert finding["freshness"] == semantic.freshness


def test_resource_identity_normalizes_trailing_slash_and_rejects_aliases():
    arm_id = "/subscriptions/sub-1/resourcegroups/rg/providers/x/type/name"

    with pytest.raises(ValueError, match="Duplicate incident resource identity"):
        IncidentContextBuilder(
            [
                {"resource_key": arm_id, "name": "one"},
                {"resource_key": arm_id.upper() + "/", "name": "two"},
            ]
        )


def test_nested_impact_collections_are_bounded_and_disclose_truncation():
    context = IncidentContextBuilder(
        [
            {
                "resource_key": "resource-1",
                "name": "server",
                "impacted_applications": [f"app-{index}" for index in range(1200)],
            }
        ],
        max_collection_items=50,
    ).get("resource-1")

    assert len(context["impacted_applications"]) == 50
    assert context["context_truncated"] is True


def test_public_strings_and_serialized_outputs_are_bounded():
    huge = "x" * 1_000_000
    engine = IncidentIntelligence(
        resources=[
            {
                "resource_key": "resource-1",
                "name": huge,
                "impacted_applications": [huge for _ in range(50)],
            }
        ],
        incidents=[
            {
                "incident_id": "INC-1",
                "title": huge,
                "status": "Active",
                "severity": "Critical",
                "started_at": "2026-08-18T12:00:00Z",
                "resource_key": "resource-1",
            }
        ],
        alerts=[],
        resource_changes=[],
        patch_findings=[],
        lifecycle_findings=[],
        history=[],
        freshness="2026-08-18T13:00:00Z",
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        max_serialized_bytes=1_000_000,
    )

    analysis = engine.analyze()
    report = engine.report("Executive Incident Brief")

    assert len(__import__("json").dumps(analysis).encode()) < 1_000_000
    assert len(__import__("json").dumps(report).encode()) < 1_000_000
    assert analysis["findings"][0]["context_truncated"] is True
