from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fabric_pipelines.change_pipeline import OUTPUT_TABLE, run
from intelligence.change.change_intelligence import ChangeIntelligence


def test_change_pipeline_matches_aiops_snapshot():
    scenario = json.loads(Path("tests/fixtures/sample_change_intelligence.json").read_text())
    now = lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    result = run(**scenario, now=now)
    aiops = ChangeIntelligence.from_snapshot(**scenario, now=now).analyze()

    assert result.table_name == OUTPUT_TABLE
    assert len(result.findings) == len(aiops["findings"])
    chg = next(item for item in result.findings if item["change_id"] == "CHG-100")
    assert chg["configuration_drifted"] is True
    assert chg["compliance_score"] == 40
    assert chg["incident_id"] == "INC-100"
    assert chg["confirmed_cause"] is False
