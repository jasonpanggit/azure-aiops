from __future__ import annotations

from agents.operations.ownership_analyzer import OwnershipAnalyzer
from agents.operations.recommendation_engine import RecommendationEngine


def test_recommendations_cover_missing_owner_patch_failure_and_high_risk():
    recommendations = RecommendationEngine().generate(
        risk={
            "score": 90,
            "level": "Critical",
            "factors": {"missing_owner": 25, "patch_noncompliance": 25},
        },
        health={"score": 20, "category": "Critical"},
        compliance={
            "status": "failed",
            "failed_patch_count": 3,
            "compliant": False,
        },
        ownership={"coverage": "Missing"},
        context={"sections": {}},
    )

    actions = {item["suggested_action"] for item in recommendations}
    assert recommendations[0]["priority"] == "Critical"
    assert "Assign and validate a workload owner and support group." in actions
    assert any("schedule remediation" in action for action in actions)
    assert any("immediate" in action for action in actions)
    assert all(
        set(item)
        >= {
            "priority",
            "impact",
            "confidence",
            "rationale",
            "suggested_action",
            "evidence",
            "advisory_only",
        }
        for item in recommendations
    )
    assert all(item["advisory_only"] for item in recommendations)


def test_unknown_patch_state_does_not_create_remediation_recommendation():
    recommendations = RecommendationEngine().generate(
        risk={"score": 0, "level": "Low", "factors": {}},
        health={"score": 100, "category": "Healthy"},
        compliance={"status": "unknown", "failed_patch_count": 0, "compliant": False},
        ownership={"coverage": "Covered"},
        context={"sections": {}},
    )

    assert recommendations == []


def test_absent_ownership_domain_is_unknown_not_a_missing_owner_conclusion():
    ownership = OwnershipAnalyzer().analyze({"sections": {"applications": []}})

    assert ownership["coverage"] == "Unknown"
    assert ownership["evidence_available"] is False


def test_cost_and_lifecycle_recommendations_require_observed_context():
    recommendations = RecommendationEngine().generate(
        risk={"score": 0, "level": "Low", "factors": {}},
        health={"score": 100, "category": "Healthy"},
        compliance={"status": "unknown", "compliant": False},
        ownership={"coverage": "Unknown"},
        context={
            "sections": {
                "cost": [{"amount": 100, "currency": "USD"}],
                "lifecycle": {"status": "obsolete"},
            }
        },
    )

    assert any("cost" in item["rationale"].casefold() for item in recommendations)
    assert any("modernization" in item["suggested_action"].casefold() for item in recommendations)


def test_obsolete_sku_advisor_evidence_generates_modernization_recommendation():
    recommendations = RecommendationEngine().generate(
        risk={"score": 0, "level": "Low", "factors": {}},
        health={"score": 100, "category": "Healthy"},
        compliance={"status": "unknown", "compliant": False},
        ownership={"coverage": "Unknown"},
        context={
            "sections": {
                "advisor_findings": [
                    {"name": "Modernize obsolete SKU", "entity_type": "AdvisorRecommendation"}
                ],
                "lifecycle": {"status": "active"},
            }
        },
    )

    assert any(
        "modernization" in item["suggested_action"].casefold()
        for item in recommendations
    )
