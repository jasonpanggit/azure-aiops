from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from incident_scenario import incident_engine

from intelligence.incident.incident_intelligence import IncidentIntelligence


def test_incident_correlation_explains_probable_causes_and_business_impact():
    finding = incident_engine().analyze()["findings"][0]

    assert finding["incident"]["incident_id"] == "INC-100"
    assert finding["resource"] == {
        "name": "vm-payments",
        "entity_type": "VirtualMachine",
    }
    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail Checkout"
    assert finding["owner"] == "ops@example.com"
    assert finding["support_team"] == "Payments SRE"
    assert finding["probable_causes"]
    assert finding["probable_causes"][0]["causal_score"] >= 60
    assert finding["probable_causes"][0]["evidence"]
    assert finding["impacted_applications"]
    assert finding["impacted_business_services"] == ["Retail Checkout"]
    assert finding["blast_radius"]["application_count"] == 2
    assert finding["read_only"] is True


def test_analysis_never_claims_certain_causation_or_execution():
    analysis = incident_engine().analyze()

    assert analysis["read_only"] is True
    for finding in analysis["findings"]:
        assert all(cause["conclusion"] != "Confirmed root cause" for cause in finding["probable_causes"])
        assert all(cause["confidence"] <= 0.95 for cause in finding["probable_causes"])
        assert finding["recommended_action"]["advisory_only"] is True
        assert "action_result" not in finding


def test_post_incident_alert_and_lifecycle_posture_are_not_probable_causes():
    engine = incident_engine()
    engine.evidence.append(
        {
            "evidence_id": "ALT-AFTER",
            "evidence_type": "Alert",
            "observed_at": "2026-08-18T12:30:00Z",
            "resource_key": engine.incidents[0]["resource_key"],
            "severity": "Critical",
            "summary": "Alert after incident start",
            "causal_eligible": True,
        }
    )

    finding = engine.analyze()["findings"][0]

    assert "ALT-AFTER" not in {
        cause["evidence_id"] for cause in finding["probable_causes"]
    }
    assert all(
        cause["evidence_type"] != "Lifecycle Risk"
        for cause in finding["probable_causes"]
    )


def test_duplicate_evidence_identity_fails_closed():
    scenario = json.loads(
        Path("tests/fixtures/sample_incident_causality.json").read_text()
    )
    scenario["alerts"].append(dict(scenario["alerts"][0]))

    with pytest.raises(ValueError, match="Duplicate incident evidence identity"):
        IncidentIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )


def test_history_is_validated_and_contributes_distinct_historical_incidents():
    scenario = json.loads(
        Path("tests/fixtures/sample_incident_causality.json").read_text()
    )
    scenario["history"] = [
        {
            "incident_id": "INC-080",
            "observed_at": "2026-08-01T12:00:00Z",
            "status": "Resolved",
            "severity": "High",
            "resource_key": scenario["resources"][0]["resource_key"],
        }
    ]

    engine = IncidentIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )

    assert {row["incident_id"] for row in engine.incidents} == {
        "INC-080",
        "INC-090",
        "INC-100",
    }


@pytest.mark.parametrize(
    "history",
    [
        [
            {
                "incident_id": "INC-X",
                "observed_at": "not-a-date",
                "resource_key": "resource-1",
            }
        ],
        [
            {
                "incident_id": "INC-X",
                "observed_at": "2999-01-01T00:00:00Z",
                "resource_key": "resource-1",
            }
        ],
        [
            {
                "incident_id": "INC-X",
                "observed_at": "2026-08-01T00:00:00Z",
                "resource_key": "resource-1",
            },
            {
                "incident_id": "INC-X",
                "observed_at": "2026-08-01T00:00:00Z",
                "resource_key": "resource-1",
            },
        ],
    ],
)
def test_malformed_future_or_duplicate_history_fails_closed(history):
    scenario = json.loads(
        Path("tests/fixtures/sample_incident_causality.json").read_text()
    )
    scenario["history"] = history

    with pytest.raises(ValueError):
        IncidentIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )
