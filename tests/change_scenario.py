from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.change.change_intelligence import ChangeIntelligence


def change_engine(**kwargs) -> ChangeIntelligence:
    scenario = json.loads(
        Path("tests/fixtures/sample_change_intelligence.json").read_text()
    )
    return ChangeIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        **kwargs,
    )
