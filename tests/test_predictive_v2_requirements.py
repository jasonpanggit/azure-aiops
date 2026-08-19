from __future__ import annotations

import json

from predictive_scenario import predictive_engine
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from intelligence.predictive.failure_prediction import FailurePredictionEngine
from intelligence.predictive.incident_probability_engine import (
    IncidentProbabilityEngine,
)
from intelligence.predictive.operational_debt_engine import OperationalDebtEngine
from intelligence.predictive.prediction_context_builder import PredictionContextBuilder
from intelligence.predictive.prediction_summary import PredictionSummary
from intelligence.predictive.predictive_engine import PredictiveEngine
from intelligence.predictive.risk_forecasting import RiskForecaster
from intelligence.predictive.service_health_forecaster import ServiceHealthForecaster
from intelligence.predictive.trend_detector import TrendDetector
from semantic.semantic_engine import SemanticEngine


def test_requested_predictive_modules_and_expanded_models_are_available():
    assert all(
        component is not None
        for component in (
            PredictiveEngine,
            RiskForecaster,
            FailurePredictionEngine,
            ServiceHealthForecaster,
            IncidentProbabilityEngine,
            TrendDetector,
            OperationalDebtEngine,
            PredictionContextBuilder,
            PredictionSummary,
        )
    )

    analysis = PredictiveEngine.from_intelligence(predictive_engine()).analyze()
    prediction = analysis["predictions"][0]

    assert prediction["failure_prediction"]["risk_score"] >= 0
    assert 0 <= prediction["failure_prediction"]["estimated_probability_percent"] <= 95
    assert prediction["failure_prediction"]["evidence"]
    assert prediction["failure_prediction"]["preventive_action"]["advisory_only"] is True
    assert prediction["operational_debt"]["categories"] == {
        "patch_debt": 70,
        "lifecycle_debt": 68,
        "ownership_debt": 0,
        "configuration_debt": 100,
        "security_debt": 60,
    }
    assert prediction["observed_patterns"]
    assert prediction["contributors"]
    assert prediction["potential_consequences"]
    assert prediction["risk_models"]["vm_failure_risk"] is not None
    assert prediction["risk_models"]["arc_server_degradation_risk"] is None

    assert analysis["subscriptions"]
    assert analysis["resource_groups"]
    assert analysis["environments"]
    assert analysis["service_health_forecasts"]
    assert analysis["operational_debt"]["portfolio_score"] >= 0
    assert analysis["proactive_recommendations"]


def test_predictive_knowledge_projection_models_required_entities_and_relationships():
    engine = PredictiveEngine.from_intelligence(predictive_engine())
    engine.analyze()
    projection = engine.knowledge_projection()
    entity_types = {row["entity_type"] for row in projection["entities"]}
    relationship_types = {row["relationship_type"] for row in projection["relationships"]}

    assert {"Prediction", "Forecast", "Trend", "OperationalDebt", "RiskDriver"} <= entity_types
    assert {"hasForecast", "hasTrend", "accumulatesDebt", "drivenBy"} <= relationship_types
    assert projection["read_only"] is True


def test_ten_requested_predictive_agent_commands_are_read_only_and_explainable():
    semantic = SemanticEngine.from_rows(**semantic_scenario())
    agent = OperationsAgent(semantic, predictive_intelligence=predictive_engine())
    portfolio_commands = (
        "Predict Operational Risk",
        "Show High Risk Applications",
        "Service Stability Forecast",
        "Show Compliance Trends",
        "Show Operational Debt",
        "Show High Risk Resources",
        "Show Risk Drivers",
        "Predictive Risk Report",
        "Executive Forecast",
    )
    for command in portfolio_commands:
        result = agent.analyze(command, "Enterprise", subject_type="PredictivePortfolio")
        serialized = json.dumps(result).casefold()
        assert result["read_only"] is True
        assert result["subject"]["entity_type"] == "PredictivePortfolio"
        assert "remediation_result" not in serialized
        assert "/subscriptions/" not in serialized

    application = agent.analyze(
        "Is Application At Risk?", "Payments", subject_type="Application"
    )
    assert application["predictive_intelligence"]["application"]["name"] == "Payments"
    assert application["predictive_intelligence"]["read_only"] is True


def test_required_predictive_telemetry_and_accuracy_contract_exist():
    telemetry = predictive_engine().telemetry

    assert telemetry.prediction_latency is not None
    assert telemetry.risk_scoring_duration is not None
    assert telemetry.forecast_accuracy is not None
    assert telemetry.trend_generation_duration is not None
    assert telemetry.context_assembly_duration is not None
    assert telemetry.recommendation_generation_duration is not None
    accuracy = telemetry.record_forecast_accuracy(predicted=80, observed=1)
    assert accuracy == 0.8
