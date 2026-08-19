from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.predictive.predictive_intelligence import PredictiveIntelligence


def predictive_engine(**kwargs) -> PredictiveIntelligence:
    scenario = json.loads(
        Path("tests/fixtures/sample_predictive_operations.json").read_text()
    )
    return PredictiveIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        **kwargs,
    )
