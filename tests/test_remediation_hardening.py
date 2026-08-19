from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pytest
from remediation_scenario import remediation_planner

from intelligence.remediation.remediation_planner import RemediationPlanner
from intelligence.remediation.risk_analyzer import RiskAnalyzer


def fixture():
    return json.loads(
        Path("tests/fixtures/sample_remediation_planning.json").read_text()
    )


def build(snapshot, **kwargs):
    return RemediationPlanner.from_snapshot(
        **snapshot,
        **kwargs,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )


def test_no_governed_action_catalog_means_no_invented_workflow():
    result = remediation_planner(action_catalog=[]).generate_plans()

    assert result["plans"] == []
    assert result["summary"]["plan_count"] == 0


def test_nested_internal_identifiers_are_redacted_from_every_public_plan_field():
    scenario = fixture()
    arm = scenario["resources"][0]["resource_key"]
    encoded = arm
    for _ in range(25):
        encoded = quote(encoded)
    scenario["resources"][0]["name"] = encoded
    scenario["resources"][0]["owner"] = encoded
    scenario["action_catalog"][0]["execution_steps"][0] = encoded

    serialized = json.dumps(build(scenario).generate_plans()).casefold()

    assert "/subscriptions/" not in serialized
    assert "%2fsubscriptions" not in serialized


def test_catalog_requires_valid_triggers_and_complete_rollback_contract():
    scenario = fixture()
    scenario["action_catalog"][0]["trigger"] = {
        "any": [{"field": "patch_risk_score", "gte": "75"}]
    }
    with pytest.raises(ValueError, match="trigger threshold"):
        build(scenario)

    scenario = fixture()
    scenario["action_catalog"][0]["rollback_actions"] = []
    with pytest.raises(ValueError, match="rollback_actions"):
        build(scenario)


def test_approval_policy_thresholds_fail_closed():
    scenario = fixture()
    scenario["approval_policies"][0]["conditions"]["minimum_execution_risk"] = True

    with pytest.raises(ValueError, match="minimum_execution_risk"):
        build(scenario)


def test_unknown_evidence_does_not_create_an_opportunity():
    scenario = fixture()
    scenario["resources"] = [
        {
            "resource_key": scenario["resources"][0]["resource_key"],
            "name": "unknown-posture",
        }
    ]

    assert build(scenario).generate_plans()["plans"] == []


def test_unknown_business_and_service_evidence_remains_unknown():
    action = fixture()["action_catalog"][0]
    assessment = RiskAnalyzer().analyze(
        {"patch_risk_score": 80},
        {"dependency_count": 0},
        action,
    )

    assert assessment["business_risk"] == {
        "score": None,
        "level": "Unknown",
        "drivers": ["Business criticality evidence unavailable"],
        "evidence_status": "Unknown",
    }
    assert assessment["service_impact_risk"]["score"] is None
    assert assessment["service_impact_risk"]["level"] == "Unknown"


def test_ontology_projection_is_referentially_complete():
    planner = remediation_planner()
    planner.generate_plans()
    projection = planner.repository.ontology_projection()
    entity_ids = {row["entity_id"] for row in projection["entities"]}

    assert all(
        row["subject_id"] in entity_ids and row["object_id"] in entity_ids
        for row in projection["relationships"]
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_resources", True),
        ("max_plans", 1.5),
        ("max_output_items", "10"),
        ("max_dependencies", False),
        ("max_serialized_bytes", 1024.5),
    ],
)
def test_direct_planning_bounds_require_exact_integers(name, value):
    with pytest.raises(TypeError, match=rf"{name} must be an integer"):
        remediation_planner(**{name: value})


def test_serialized_response_bound_fails_closed():
    planner = remediation_planner(max_serialized_bytes=1024)

    with pytest.raises(ValueError, match="output exceeds"):
        planner.generate_plans()
