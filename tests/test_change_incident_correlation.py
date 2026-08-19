from change_scenario import change_engine


def test_change_incident_correlation_is_probabilistic_and_temporal():
    finding = change_engine().analyze()["findings"][0]
    correlation = finding["incident_correlation"]

    assert correlation["incident_id"] == "INC-100"
    assert correlation["classification"] == "Probable contributor"
    assert correlation["contribution_score"] >= 60
    assert correlation["confidence"] <= 0.95
    assert correlation["confirmed_cause"] is False
    assert correlation["evidence"]


def test_change_after_incident_is_not_a_probable_contributor():
    engine = change_engine()
    engine.changes[0]["changed_at"] = "2026-08-18T12:45:00Z"

    finding = next(
        row
        for row in engine.analyze()["findings"]
        if row["change"]["change_id"] == "CHG-100"
    )
    correlation = finding["incident_correlation"]

    assert correlation["classification"] != "Probable contributor"
    assert correlation["confirmed_cause"] is False
