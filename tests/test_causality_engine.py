from __future__ import annotations

from datetime import UTC, datetime

from intelligence.incident.causality_engine import CausalityEngine


def test_causality_scoring_rewards_target_temporal_and_signal_evidence():
    engine = CausalityEngine()
    incident = {
        "incident_id": "INC-1",
        "started_at": "2026-08-18T12:00:00Z",
        "resource_key": "resource-1",
        "severity": "Critical",
    }
    signal = {
        "evidence_id": "CHG-1",
        "evidence_type": "Resource Change",
        "observed_at": "2026-08-18T11:55:00Z",
        "resource_key": "resource-1",
        "severity": "High",
        "summary": "Configuration changed",
    }

    result = engine.score(
        incident, signal, now=datetime(2026, 8, 18, 13, tzinfo=UTC)
    )

    assert 0 <= result["causal_score"] <= 100
    assert result["causal_score"] >= 70
    assert result["classification"] == "Probable cause"
    assert result["confidence"] <= 0.95
    assert set(result["factors"]) == {
        "target_match",
        "temporal_proximity",
        "signal_strength",
        "causal_relevance",
    }


def test_future_signal_is_not_treated_as_probable_cause():
    result = CausalityEngine().score(
        {
            "incident_id": "INC-1",
            "started_at": "2026-08-18T12:00:00Z",
            "resource_key": "resource-1",
        },
        {
            "evidence_id": "ALT-1",
            "evidence_type": "Alert",
            "observed_at": "2026-08-18T12:30:00Z",
            "resource_key": "resource-1",
            "severity": "Critical",
        },
        now=datetime(2026, 8, 18, 13, tzinfo=UTC),
    )

    assert result["causal_score"] < 60
    assert result["classification"] != "Probable cause"


def test_non_causal_posture_is_capped_as_contextual_evidence():
    result = CausalityEngine().score(
        {
            "incident_id": "INC-1",
            "started_at": "2026-08-18T12:00:00Z",
            "resource_key": "resource-1",
        },
        {
            "evidence_id": "EOL-1",
            "evidence_type": "Lifecycle Risk",
            "observed_at": "2026-08-18T11:55:00Z",
            "resource_key": "resource-1",
            "severity": "Critical",
            "causal_eligible": False,
        },
        now=datetime(2026, 8, 18, 13, tzinfo=UTC),
    )

    assert result["causal_score"] <= 34
    assert result["classification"] == "Contextual evidence"
