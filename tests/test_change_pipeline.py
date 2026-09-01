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


def test_change_pipeline_forwards_knowledge_projection_entities():
    scenario = json.loads(Path("tests/fixtures/sample_change_intelligence.json").read_text())
    now = lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    result = run(**scenario, now=now)
    aiops = ChangeIntelligence.from_snapshot(**scenario, now=now).knowledge_projection()

    assert result.entities == aiops["entities"]
    assert result.entities != []


def test_change_pipeline_forwards_knowledge_projection_relationships():
    scenario = json.loads(Path("tests/fixtures/sample_change_intelligence.json").read_text())
    now = lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    result = run(**scenario, now=now)
    aiops = ChangeIntelligence.from_snapshot(**scenario, now=now).knowledge_projection()

    assert result.relationships == aiops["relationships"]


def test_change_pipeline_empty_snapshot_yields_empty_entities_and_relationships():
    now = lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    result = run(
        resources=[],
        resource_changes=[],
        policy_deviations=[],
        security_deviations=[],
        network_changes=[],
        identity_changes=[],
        iac_changes=[],
        incidents=[],
        history=[],
        freshness="2026-08-18T13:00:00Z",
        now=now,
    )

    assert result.entities == []
    assert result.relationships == []
