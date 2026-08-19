from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from patch_scenario import patch_engine
from semantic_scenario import semantic_scenario

from intelligence.patch import PatchIntelligence
from semantic.semantic_engine import SemanticEngine


def test_patch_analysis_enriches_failures_with_business_context_and_explainability():
    analysis = patch_engine().analyze()

    payroll = next(
        item for item in analysis["findings"] if item["resource"]["name"] == "vm-payroll-01"
    )
    assert payroll["application"] == "Payroll"
    assert payroll["business_service"] == "HR Services"
    assert payroll["owner"] == "hr-platform@example.com"
    assert payroll["support_team"] == "HR Operations"
    assert payroll["compliance_score"] < 50
    assert payroll["risk_score"] >= 75
    assert payroll["business_impact"] == "Critical"
    assert payroll["recommended_action"]
    assert payroll["evidence"]
    assert payroll["affected_resources"] == ["vm-payroll-01"]
    assert payroll["blast_radius"] == {
        "resource_count": 1,
        "application_count": 1,
        "business_service_count": 1,
        "service_count": 0,
    }
    assert payroll["risk_justification"]
    assert payroll["priority_reasoning"]
    assert 0 <= payroll["confidence_score"] <= 1
    assert analysis["read_only"] is True
    assert analysis["freshness"] == "2026-08-18T00:00:00Z"


def test_patch_intelligence_builds_context_through_the_semantic_engine():
    scenario = semantic_scenario()
    semantic = SemanticEngine.from_rows(**scenario)
    vm = scenario["inventory"][0]
    engine = PatchIntelligence.from_semantic_engine(
        semantic,
        inventory=[vm],
        assessments=[
            {
                "assessed_resource_id": vm["resource_id"],
                "status": "noncompliant",
                "last_modified": "2026-08-17T00:00:00Z",
                "missing_critical_updates": 1,
                "missing_security_updates": 1,
            }
        ],
        installations=[],
        history=[],
        policies=[],
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )

    finding = engine.analyze()["findings"][0]
    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail"
    assert finding["owner"] == "ops@example.com"
    assert finding["support_team"] == "SRE"
    assert finding["environment"] == "Production"
    assert finding["business_criticality"] == "Critical"


def test_duplicate_resource_names_remain_distinct_and_require_canonical_evidence_identity():
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    duplicate = dict(scenario["resources"][0])
    duplicate.update(subscription="sub-other", application="Other Payroll")
    scenario["resources"].append(duplicate)

    with pytest.raises(ValueError, match="ambiguous resource name"):
        PatchIntelligence.from_semantic_snapshot(
            **scenario,
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        ).analyze()


def test_patch_snapshot_bounds_every_evidence_collection():
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    scenario["history"] = scenario["history"] * 3

    with pytest.raises(ValueError, match="history"):
        PatchIntelligence.from_semantic_snapshot(
            **scenario,
            max_evidence_rows=10,
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )


def test_invalid_freshness_fails_closed_and_naive_patch_dates_are_normalized():
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    scenario["freshness"] = "not-a-timestamp"
    with pytest.raises(ValueError, match="freshness timestamp is invalid"):
        PatchIntelligence.from_semantic_snapshot(**scenario)

    scenario["freshness"] = "2026-08-18T00:00:00"
    scenario["installations"][0]["published_at"] = "2026-06-01T00:00:00"
    result = PatchIntelligence.from_semantic_snapshot(
        **scenario,
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    ).analyze()
    assert result["freshness"] == "2026-08-18T00:00:00Z"


def test_future_freshness_and_malformed_evidence_timestamps_fail_closed():
    scenario = json.loads(Path("tests/fixtures/mock_patch_intelligence.json").read_text())
    scenario["freshness"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="freshness timestamp is in the future"):
        PatchIntelligence.from_semantic_snapshot(
            **scenario,
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )

    scenario["freshness"] = "2026-08-18T00:00:00Z"
    scenario["assessments"][0]["assessed_at"] = "not-a-time"
    with pytest.raises(ValueError, match="assessments.assessed_at timestamp is invalid"):
        PatchIntelligence.from_semantic_snapshot(
            **scenario,
            now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
        )
