import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from predictive_scenario import predictive_engine

from intelligence.predictive.predictive_intelligence import PredictiveIntelligence


def test_forecasts_cover_30_60_90_days_and_degrading_trends():
    prediction = predictive_engine().analyze()["predictions"][0]

    assert prediction["forecast_30_day"]["horizon_days"] == 30
    assert prediction["forecast_60_day"]["horizon_days"] == 60
    assert prediction["forecast_90_day"]["horizon_days"] == 90
    assert prediction["forecast_30_day"]["score"] <= prediction["forecast_60_day"]["score"] <= prediction["forecast_90_day"]["score"]
    assert prediction["trend"]["direction"] == "Degrading"
    assert prediction["trend"]["patch_debt_growth"] > 0
    assert prediction["trend"]["drift_growth"] > 0


def test_history_duplicates_future_and_missing_identity_fail_closed():
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    scenario["history"].append(dict(scenario["history"][0]))
    with pytest.raises(ValueError, match="Duplicate predictive history"):
        PredictiveIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )
