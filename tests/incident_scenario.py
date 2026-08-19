from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.incident.incident_intelligence import IncidentIntelligence


def incident_engine(**kwargs) -> IncidentIntelligence:
    scenario = json.loads(
        Path("tests/fixtures/sample_incident_causality.json").read_text()
    )
    return IncidentIntelligence.from_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
        **kwargs,
    )
