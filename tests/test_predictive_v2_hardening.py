from __future__ import annotations

from datetime import UTC, datetime

import pytest
from predictive_scenario import predictive_engine

from hermes_arg_connector.plugin import OPERATIONS_AGENT_SCHEMA
from intelligence.predictive.incident_probability_engine import (
    IncidentProbabilityEngine,
)
from intelligence.predictive.predictive_engine import PredictiveEngine
from intelligence.predictive.predictive_intelligence import PredictiveIntelligence
from intelligence.predictive.predictive_trend_engine import PredictiveTrendEngine
from ontology.ontology_validator import OntologyValidator

REQUESTED_COMMANDS = {
    "Predict Operational Risk",
    "Show High Risk Applications",
    "Service Stability Forecast",
    "Show Compliance Trends",
    "Show Operational Debt",
    "Show High Risk Resources",
    "Show Risk Drivers",
    "Predictive Risk Report",
    "Executive Forecast",
    "Is Application At Risk?",
}


def test_plugin_schema_registers_every_requested_predictive_command():
    registered = set(
        OPERATIONS_AGENT_SCHEMA["parameters"]["properties"]["command"]["enum"]
    )

    assert REQUESTED_COMMANDS <= registered


def test_semantic_advisor_findings_contribute_named_predictive_evidence():
    key = "/subscriptions/sub/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm"

    class Semantic:
        freshness = "2026-08-18T13:00:00Z"

        def get_resource_context(self, resource_key, *, subject_type):
            assert resource_key == key
            assert subject_type == "VirtualMachine"
            return {
                "sections": {
                    "advisor_findings": [{"name": "Reliability recommendation"}],
                    "operational_classification": {},
                }
            }

    engine = PredictiveIntelligence.from_semantic_engine(
        Semantic(),
        inventory=[
            {"resource_id": key, "name": "vm", "entity_type": "VirtualMachine"}
        ],
        resource_signals={key: {}},
        history=[],
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    prediction = engine.analyze()["predictions"][0]

    assert prediction["contributors"]["advisor_exposure"] == 2
    assert "advisor_exposure" in prediction["risk_drivers"]


def test_sparse_history_does_not_invent_cross_metric_growth():
    trend = PredictiveTrendEngine().calculate(
        "resource",
        [
            {
                "resource_key": "resource",
                "observed_at": "2026-06-01T00:00:00+00:00",
                "patch_debt": 10,
                "_evidence_present": True,
            },
            {
                "resource_key": "resource",
                "observed_at": "2026-08-01T00:00:00+00:00",
                "lifecycle_risk_score": 50,
                "_evidence_present": True,
            },
        ],
    )

    assert trend["patch_debt_growth"] is None
    assert trend["lifecycle_exposure_growth"] is None
    assert trend["growth_index"] == 0
    assert trend["direction"] == "Stable"


def test_unknown_probability_and_debt_remain_unknown_in_aggregates():
    estimate = IncidentProbabilityEngine().estimate(
        {"_known_signals": set()}, {"observation_count": 0, "growth_index": 0}
    )
    assert estimate["estimated_probability_percent"] is None
    assert estimate["evidence_status"] == "Unknown"

    engine = PredictiveIntelligence.from_snapshot(
        resources=[
            {
                "resource_key": "/subscriptions/sub/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm",
                "name": "vm",
                "entity_type": "VirtualMachine",
                "application": "Sparse App",
            }
        ],
        history=[],
        freshness="2026-08-18T13:00:00Z",
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    analysis = engine.analyze()

    assert analysis["predictions"][0]["operational_debt"]["score"] is None
    assert analysis["applications"][0]["operational_debt_score"] is None
    assert analysis["operational_debt"]["portfolio_score"] is None
    assert engine.query("Show services accumulating debt")["result"] == []
    assert engine.internal_planning_posture()[
        "/subscriptions/sub/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm"
    ]["operational_debt_score"] is None


def test_missing_semantic_sections_remain_unknown_not_confirmed_zero_or_gap():
    key = "/subscriptions/sub/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm"

    class Semantic:
        freshness = "2026-08-18T13:00:00Z"

        def get_resource_context(self, resource_key, *, subject_type):
            return {"sections": {}}

    engine = PredictiveIntelligence.from_semantic_engine(
        Semantic(),
        inventory=[{"resource_id": key, "name": "vm", "entity_type": "VirtualMachine"}],
        resource_signals={key: {}},
        history=[],
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    prediction = engine.analyze()["predictions"][0]

    assert prediction["operational_debt"]["categories"]["ownership_debt"] is None
    assert prediction["operational_debt"]["categories"]["security_debt"] is None
    assert prediction["contributors"]["ownership_gap"] == 0
    assert prediction["contributors"]["advisor_exposure"] == 0


def test_zero_or_one_observation_keeps_optional_trends_unknown():
    engine = PredictiveTrendEngine()
    for rows in (
        [],
        [
            {
                "resource_key": "resource",
                "observed_at": "2026-08-01T00:00:00+00:00",
                "patch_debt": 5,
                "_evidence_present": True,
            }
        ],
    ):
        trend = engine.calculate("resource", rows)
        assert trend["patch_debt_growth"] is None
        assert trend["ownership_coverage_growth"] is None
        assert trend["security_debt_growth"] is None
        assert trend["growth_index"] is None
        assert trend["direction"] == "Unknown"


@pytest.mark.parametrize("value", [True, 1.9, "7"])
def test_malformed_governed_signal_types_fail_closed(value):
    with pytest.raises(TypeError, match="patch_debt must be an integer"):
        PredictiveIntelligence.from_snapshot(
            resources=[
                {
                    "resource_key": "/subscriptions/sub/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm",
                    "name": "vm",
                    "patch_debt": value,
                }
            ],
            history=[],
            freshness="2026-08-18T13:00:00Z",
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )


def test_knowledge_projection_is_unique_valid_and_bounded():
    engine = predictive_engine()
    context = engine.context_builder.all()[0]
    duplicate_name = dict(context)
    duplicate_name["_resource_key"] = (
        "/subscriptions/other/resourcegroups/other/providers/microsoft.compute/virtualmachines/vm"
    )
    duplicate_name["resource"] = dict(context["resource"])
    engine.context_builder._resources[duplicate_name["_resource_key"]] = duplicate_name
    projection = PredictiveEngine.from_intelligence(engine).knowledge_projection()

    report = OntologyValidator().validate(
        projection["entities"], projection["relationships"]
    )
    ids = [row["resource_id"] for row in projection["entities"]]
    assert report.passed is True
    assert len(ids) == len(set(ids))
    assert all("change_version" in row for row in projection["entities"])

    bounded = PredictiveEngine.from_intelligence(
        predictive_engine(max_output_items=1)
    ).knowledge_projection()
    assert len(bounded["entities"]) <= 1
    assert len(bounded["relationships"]) <= 1
    assert bounded["collection_metadata"]["entities"]["truncated"] is True

    counts = []
    for limit in (1, 2, 100):
        candidate = PredictiveEngine.from_intelligence(
            predictive_engine(max_output_items=limit)
        ).knowledge_projection()
        counts.append(candidate["collection_metadata"]["entities"]["count"])
    assert len(set(counts)) == 1
