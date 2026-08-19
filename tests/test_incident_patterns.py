from __future__ import annotations

from incident_scenario import incident_engine


def test_recurring_patterns_are_evidence_backed_and_bounded():
    patterns = incident_engine().query("Show recurring incident patterns")["result"]

    assert patterns
    pattern = patterns[0]
    assert pattern["occurrence_count"] == 2
    assert pattern["resource"]["name"] == "vm-payments"
    assert pattern["pattern_type"] in {"Alert", "Resource Change"}
    assert pattern["incident_ids"] == ["INC-090", "INC-100"]
    assert pattern["confidence"] <= 0.95


def test_query_contract_rejects_unbounded_or_action_intents():
    engine = incident_engine()

    for query in ("Restart affected systems", "Remediate root cause", "Show everything"):
        try:
            engine.query(query)
        except ValueError as exc:
            assert "Unsupported incident intelligence query" in str(exc)
        else:
            raise AssertionError("unsafe or unsupported query was accepted")
