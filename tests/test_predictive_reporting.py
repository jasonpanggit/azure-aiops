from predictive_scenario import predictive_engine


def test_predictive_queries_and_reports_are_bounded_read_only():
    engine = predictive_engine()
    for query in (
        "What is likely to fail next", "Show unstable applications",
        "Show services accumulating debt", "Forecast incidents",
        "Show workloads requiring intervention", "Show predictive trends"
    ):
        result = engine.query(query)
        assert result["read_only"] is True
        assert result["result"]

    for report_type in (
        "Predictive Operations Summary", "Failure Risk Forecast",
        "Application Stability Report", "Business Service Risk Forecast",
        "Operational Debt Forecast", "Executive Predictive Brief"
    ):
        report = engine.report(report_type)
        assert report["headline"]
        assert report["focus"]
        assert report["read_only"] is True


def test_telemetry_records_prediction_feature_trend_and_report_latency():
    class I:
        def __init__(self): self.records=[]
        def record(self, value, attributes=None): self.records.append((value, attributes))
    class T:
        def __init__(self):
            self.analysis_duration=I(); self.feature_duration=I(); self.forecast_duration=I()
            self.trend_duration=I(); self.aggregation_duration=I(); self.report_duration=I(); self.freshness=I()
    telemetry=T(); engine=predictive_engine(telemetry=telemetry)
    engine.analyze(); engine.report("Executive Predictive Brief")
    assert all(item.records for item in (telemetry.analysis_duration, telemetry.feature_duration, telemetry.forecast_duration, telemetry.trend_duration, telemetry.aggregation_duration, telemetry.report_duration, telemetry.freshness))
