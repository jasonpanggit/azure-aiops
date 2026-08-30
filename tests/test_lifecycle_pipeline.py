from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fabric_pipelines.lifecycle_pipeline import OUTPUT_TABLE, run
from intelligence.lifecycle.lifecycle_intelligence import LifecycleIntelligence


def test_lifecycle_pipeline_matches_aiops_snapshot():
    scenario = json.loads(Path("tests/fixtures/sample_lifecycle_dataset.json").read_text())
    now = lambda: datetime(2026, 8, 18, tzinfo=UTC)
    result = run(**scenario, now=now)
    aiops = LifecycleIntelligence.from_snapshot(**scenario, now=now).analyze()

    assert result.table_name == OUTPUT_TABLE
    assert len(result.findings) == len(aiops["findings"])
    payroll = next(item for item in result.findings if item["resource_name"] == "vm-payroll-legacy")
    assert payroll["lifecycle_status"] == "EOL"
    assert payroll["risk_score"] == next(
        item["risk_score"] for item in aiops["findings"] if item["resource"]["name"] == "vm-payroll-legacy"
    )
    assert payroll["recommended_action"] == "Upgrade to Windows Server 2025"
