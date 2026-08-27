from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from fabric_pipelines.patch_pipeline import OUTPUT_TABLE, run
from intelligence.patch.patch_intelligence import PatchIntelligence


def test_patch_pipeline_matches_hermes_snapshot():
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    now = lambda: datetime(2026, 8, 18, tzinfo=UTC)
    result = run(**scenario, now=now)
    hermes = PatchIntelligence.from_semantic_snapshot(**scenario, now=now).analyze()

    assert result.table_name == OUTPUT_TABLE
    assert len(result.findings) == len(hermes["findings"])
    payroll = next(item for item in result.findings if item["resource_name"] == "vm-payroll-01")
    assert payroll["compliance_score"] == 0
    assert payroll["patch_policy"] == "Production baseline"
    assert payroll["policy_compliant"] is False
    assert payroll["risk_score"] == 93
