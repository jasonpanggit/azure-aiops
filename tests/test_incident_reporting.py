from __future__ import annotations

from incident_scenario import incident_engine


def test_incident_reports_are_distinct_explainable_and_read_only():
    engine = incident_engine()
    report_types = (
        "Incident Correlation Summary",
        "Operational Causality Report",
        "Business Impact Report",
        "Recurring Pattern Report",
        "Executive Incident Brief",
    )
    focuses = []

    for report_type in report_types:
        report = engine.report(report_type)
        assert report["headline"]
        assert report["focus"]
        assert report["evidence_summary"]
        assert report["freshness"] == "2026-08-18T13:00:00Z"
        assert report["read_only"] is True
        focuses.append(str(report["focus"]))

    assert len(set(focuses)) == len(report_types)


def test_incident_telemetry_records_required_metrics():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.analysis_duration = Instrument()
            self.correlation_latency = Instrument()
            self.causality_latency = Instrument()
            self.business_impact_latency = Instrument()
            self.pattern_latency = Instrument()
            self.report_duration = Instrument()
            self.freshness = Instrument()

    telemetry = Telemetry()
    engine = incident_engine(telemetry=telemetry)
    engine.analyze()
    engine.report("Executive Incident Brief")

    assert all(
        instrument.records
        for instrument in (
            telemetry.analysis_duration,
            telemetry.correlation_latency,
            telemetry.causality_latency,
            telemetry.business_impact_latency,
            telemetry.pattern_latency,
            telemetry.report_duration,
            telemetry.freshness,
        )
    )
