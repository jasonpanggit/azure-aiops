from __future__ import annotations

from patch_scenario import patch_engine


def test_trends_cover_required_windows_and_detect_degradation_and_chronic_failures():
    trends = patch_engine().query("Show patch trends")["result"]

    assert set(trends) == {"7_day", "30_day", "90_day"}
    assert trends["7_day"]["compliance_trend"] == "degrading compliance"
    assert trends["30_day"]["recurring_failures"] == ["vm-payroll-01"]
    assert trends["90_day"]["chronic_offenders"] == ["vm-payroll-01"]
    for window in trends.values():
        assert "patch_success_trend" in window
        assert "patch_failure_trend" in window
        assert "risk_trend" in window
