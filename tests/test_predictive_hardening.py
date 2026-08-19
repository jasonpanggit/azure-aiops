from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pytest
from predictive_scenario import predictive_engine

from intelligence.predictive.predictive_context_builder import PredictiveContextBuilder
from intelligence.predictive.predictive_intelligence import PredictiveIntelligence


def test_nested_encoded_identifiers_are_redacted_from_public_outputs():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    arm = scenario["resources"][0]["resource_key"]
    encoded = arm
    for _ in range(11):
        encoded = quote(encoded)
    scenario["resources"][0]["name"] = encoded
    scenario["resources"][0]["owner"] = encoded

    engine = PredictiveIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )
    serialized = json.dumps(engine.analyze()).casefold()

    assert "/subscriptions/" not in serialized
    assert "%2fsubscriptions" not in serialized


def test_unknown_ownership_does_not_create_confirmed_gap_evidence():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    resource = dict(scenario["resources"][1])
    resource.pop("ownership_coverage")
    scenario["resources"] = [resource]
    scenario["history"] = []

    prediction = PredictiveIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    ).analyze()["predictions"][0]

    assert "ownership_gap" not in prediction["risk_drivers"]
    assert prediction["feature_contributions"]["ownership_gap"] == 0


def test_same_timestamp_observations_fail_closed_even_with_different_ids():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    row = dict(scenario["history"][0])
    row["observation_id"] = "different"
    scenario["history"].append(row)

    with pytest.raises(ValueError, match="Duplicate predictive history"):
        PredictiveIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )


def test_encoded_trailing_space_cannot_create_a_distinct_history_identity():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    row = dict(scenario["history"][0])
    row["resource_key"] += "%20"
    row["observation_id"] = "different"
    scenario["history"].append(row)

    with pytest.raises(ValueError, match="Duplicate predictive history"):
        PredictiveIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )


def test_encoded_whitespace_before_trailing_slash_is_same_canonical_identity():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    alias = dict(scenario["resources"][0])
    alias["resource_key"] += "%20/"

    with pytest.raises(ValueError, match="Duplicate predictive resource identity"):
        PredictiveIntelligence.from_snapshot(
            **{**scenario, "resources": [scenario["resources"][0], alias]},
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )

    history_alias = dict(scenario["history"][0])
    history_alias["resource_key"] += "%20/"
    history_alias["observation_id"] = "different"
    with pytest.raises(ValueError, match="Duplicate predictive history"):
        PredictiveIntelligence.from_snapshot(
            **{**scenario, "history": [scenario["history"][0], history_alias]},
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("max_history_rows", True),
        ("max_history_rows", 1.5),
        ("max_output_items", True),
        ("max_output_items", 1.5),
        ("max_serialized_bytes", True),
        ("max_serialized_bytes", 1024.5),
    ],
)
def test_direct_predictive_api_bounds_require_exact_integers(name, value):
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )

    with pytest.raises(TypeError, match=rf"{name} must be an integer"):
        PredictiveIntelligence.from_snapshot(
            **scenario,
            **{name: value},
            now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        )


@pytest.mark.parametrize("value", [True, 1.5])
def test_predictive_context_resource_bound_requires_exact_integer(value):
    with pytest.raises(TypeError, match="max_resources must be an integer"):
        PredictiveContextBuilder([], max_resources=value)


def test_truncated_portfolio_reports_preserve_total_and_disclose_truncation():
    engine = predictive_engine(max_output_items=1)
    analysis = engine.analyze()
    report = engine.report("Predictive Operations Summary")

    assert analysis["collection_metadata"]["predictions"] == {
        "count": 3,
        "returned": 1,
        "truncated": True,
    }
    assert analysis["collection_metadata"]["applications"]["truncated"] is True
    assert analysis["collection_metadata"]["business_services"]["truncated"] is True
    assert report["portfolio_summary"]["resource_count"] == 3
    assert report["collection_metadata"]["predictions"]["truncated"] is True
    assert "3 workloads" in report["headline"]


def test_query_metadata_counts_candidates_before_truncation():
    result = predictive_engine(max_output_items=1).query("What is likely to fail next")

    assert result["collection_metadata"]["result"] == {
        "count": 3,
        "returned": 1,
        "truncated": True,
    }


def test_empty_history_rows_do_not_inflate_evidence_confidence():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    resource = {
        "resource_key": scenario["resources"][0]["resource_key"],
        "name": "unknown-evidence",
    }
    scenario["resources"] = [resource]
    scenario["history"] = [
        {
            "resource_key": resource["resource_key"],
            "observed_at": timestamp,
            "observation_id": f"empty-{index}",
        }
        for index, timestamp in enumerate(
            ("2026-05-20T13:00:00Z", "2026-07-01T13:00:00Z", "2026-08-18T13:00:00Z")
        )
    ]

    prediction = PredictiveIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    ).analyze()["predictions"][0]

    assert prediction["confidence"] == 0
    assert prediction["trend"]["observation_count"] == 0


def test_horizon_forecasts_project_incident_and_debt_domains_explicitly():
    prediction = predictive_engine().analyze()["predictions"][0]
    for horizon in (30, 60, 90):
        forecast = prediction[f"forecast_{horizon}_day"]
        assert 0 <= forecast["incident_likelihood_score"] <= 100
        assert forecast["estimated_incident_band"] in {"0", "1", "2-3", "4+"}
        assert 0 <= forecast["patch_debt_risk_score"] <= 100
        assert 0 <= forecast["lifecycle_exposure_score"] <= 100
        assert 0 <= forecast["configuration_drift_score"] <= 100
        assert 0 <= forecast["compliance_degradation_score"] <= 100
        assert forecast["forecast_type"] == "Scenario risk projection"
    assert prediction["confidence_kind"] == "Evidence sufficiency, not calibrated probability"
