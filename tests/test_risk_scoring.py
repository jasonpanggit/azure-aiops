from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine
from semantic.semantic_models import RiskInputs, RiskScorer


def test_risk_score_uses_all_documented_inputs_and_is_explainable():
    assessment = RiskScorer().score(
        RiskInputs(
            missing_owner=True,
            patch_compliant=False,
            advisor_recommendation_count=3,
            security_finding_count=2,
            criticality="critical",
            environment="Production",
        )
    )

    assert assessment.score == 100
    assert assessment.level == "Critical"
    assert set(assessment.factors) == {
        "missing_owner",
        "patch_noncompliance",
        "advisor_recommendations",
        "security_findings",
        "resource_criticality",
        "environment_classification",
    }


def test_risk_score_is_bounded_and_maps_levels():
    scorer = RiskScorer()

    assert scorer.score(RiskInputs()).score == 0
    assert scorer.score(RiskInputs()).level == "Low"
    assert scorer.level_for(25) == "Moderate"
    assert scorer.level_for(50) == "High"
    assert scorer.level_for(75) == "Critical"


def test_aggregate_risk_factors_explain_the_selected_score():
    semantic = SemanticEngine.from_rows(**semantic_scenario())

    risk = semantic.get_service_context("Retail")["risk"]

    assert risk["score"] == sum(risk["factors"].values())


def test_subscription_risk_api_matches_subscription_context():
    semantic = SemanticEngine.from_rows(**semantic_scenario())

    direct = semantic.get_risk_context("sub-1")["risk"]
    context = semantic.get_subscription_context("sub-1")["risk"]

    assert direct == context
    assert direct["level"] == "Critical"
