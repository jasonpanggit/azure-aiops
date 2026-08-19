from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence


def lifecycle_engine(**kwargs) -> LifecycleIntelligence:
    scenario = json.loads(Path("tests/fixtures/sample_lifecycle_dataset.json").read_text())
    return LifecycleIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        **kwargs,
    )
