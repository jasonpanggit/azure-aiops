from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.remediation.remediation_planner import RemediationPlanner


def remediation_planner(**overrides):
    fixture = json.loads(
        Path("tests/fixtures/sample_remediation_planning.json").read_text()
    )
    fixture.update(overrides)
    return RemediationPlanner.from_snapshot(
        **fixture,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
