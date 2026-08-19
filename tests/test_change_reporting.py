from change_scenario import change_engine


def test_change_queries_reports_trends_and_telemetry():
    engine = change_engine()
    assert engine.query("Show high risk changes")["result"]
    assert engine.query("Show configuration drift")["result"]
    assert engine.query("Show incident contributing changes")["result"]
    trends = engine.query("Show change trends")["result"]
    assert set(trends) == {"30_day", "90_day", "180_day"}

    for report_type in (
        "Change Intelligence Summary", "Configuration Compliance Report",
        "Change Risk Report", "Incident Contribution Report", "Executive Change Brief"
    ):
        report = engine.report(report_type)
        assert report["headline"]
        assert report["focus"]
        assert report["read_only"] is True
