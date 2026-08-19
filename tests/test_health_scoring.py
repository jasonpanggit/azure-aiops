from __future__ import annotations

from agents.operations.health_analyzer import HealthAnalyzer


def test_health_categories_cover_full_zero_to_one_hundred_scale():
    analyzer = HealthAnalyzer()

    assert analyzer.category_for(100) == "Healthy"
    assert analyzer.category_for(80) == "Healthy"
    assert analyzer.category_for(79) == "Warning"
    assert analyzer.category_for(60) == "Warning"
    assert analyzer.category_for(59) == "Degraded"
    assert analyzer.category_for(40) == "Degraded"
    assert analyzer.category_for(39) == "Critical"
    assert analyzer.category_for(0) == "Critical"


def test_health_score_is_explainable_and_bounded():
    result = HealthAnalyzer().analyze(
        {
            "risk": {"score": 100},
            "sections": {
                "resource_health": {"status": "degraded"},
                "compliance": {"status": "failed"},
                "security_findings": [{"title": "one"}, {"title": "two"}],
                "ownership": [],
            },
        }
    )

    assert result["score"] == 0
    assert result["category"] == "Critical"
    assert result["deductions"] == {
        "operational_risk": 40,
        "unhealthy_state": 25,
        "patch_noncompliance": 15,
        "security_exposure": 20,
        "missing_ownership": 10,
    }
    assert result["data_sources"]


def test_health_reports_evidence_coverage_and_unknown_domains():
    result = HealthAnalyzer().analyze(
        {"risk": {"score": 0, "factors": {}}, "sections": {}}
    )

    assert result["score"] == 60
    assert result["category"] == "Warning"
    assert result["deductions"]["evidence_uncertainty"] == 40
    assert result["evidence_coverage"] == "Limited"
    assert set(result["unknowns"]) == {
        "resource_health",
        "patch_compliance",
        "security_exposure",
        "ownership",
    }
    assert "not proof" in result["reasoning"]
