from intelligence.change.change_risk_engine import ChangeRiskEngine


def test_change_risk_is_bounded_and_factor_attributed():
    result = ChangeRiskEngine().calculate(
        change={"category": "Network", "severity": "Critical", "changed_fields": ["publicNetworkAccess"]},
        context={"environment": "Production", "business_criticality": "Critical"},
        drift={"drifted": True, "severity": "Critical"},
        deviations={"policy": 1, "security": 1},
        incident_correlation={"contribution_score": 80},
    )

    assert 0 <= result["score"] <= 100
    assert result["level"] == "Critical"
    assert set(result["factors"]) == {
        "change_severity", "sensitive_scope", "production_environment",
        "business_criticality", "configuration_drift", "policy_deviation",
        "security_deviation", "incident_proximity"
    }
    assert result["justification"]
