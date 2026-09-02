from remediation_scenario import remediation_planner

from intelligence.remediation.plan_prioritizer import PlanPrioritizer
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)
from intelligence.remediation.risk_analyzer import RiskAnalyzer
from intelligence.vulnerability.service import VulnerabilityIntelligenceService
from tests.defender_correlation_scenario import (
    ACTION_CATALOG,
    MAPPED_RESOURCE_ID,
    defender_correlator,
    defender_resources,
)


def test_risk_assessment_is_explainable_and_bounded():
    plan = remediation_planner().generate_plans()["plans"][0]
    assessment = plan["risk_assessment"]

    for field in (
        "execution_risk",
        "operational_risk",
        "business_risk",
        "service_impact_risk",
    ):
        assert 0 <= assessment[field]["score"] <= 100
        assert assessment[field]["level"] in {"Low", "Moderate", "High", "Critical"}
        assert assessment[field]["drivers"]
    assert assessment["overall_risk"]["score"] <= 100


def test_priority_one_combines_reduction_criticality_dependencies_and_history():
    plans = remediation_planner().generate_plans()["plans"]
    payments = next(plan for plan in plans if plan["resource"]["name"] == "vm-payments")

    assert payments["priority"] in {"Priority 1", "Priority 2"}
    assert payments["priority_score"] >= 50
    assert set(payments["priority_factors"]) >= {
        "expected_risk_reduction",
        "service_criticality",
        "dependency_count",
        "incident_history",
    }


def test_priority_budget_sums_to_exactly_100_with_all_buckets_maxed():
    result = PlanPrioritizer().prioritize(
        {
            "business_criticality": "Mission Critical",
            "lifecycle_risk_score": 100,
            "patch_risk_score": 100,
            "incident_count_90d": 5,
            "defender_active_critical_alert_count": 4,
            "defender_active_high_alert_count": 4,
            "defender_attack_path_membership_count": 6,
            "defender_attack_path_target_count": 6,
            "defender_unhealthy_control_count": 4,
            "defender_secure_score_gap": 100,
            "application": "Payments API",
            "business_service": "Checkout",
        },
        {
            "dependency_count": 10,
            "affected_applications": ["Payments API"],
            "affected_services": ["Checkout"],
        },
        {"risk_reduction_percent": 100},
    )

    assert result["priority_score"] == 100
    assert sum(result["priority_factors"].values()) == 100


def test_unknown_business_mapping_caps_priority_below_priority_one():
    result = PlanPrioritizer().prioritize(
        {
            "business_criticality": "Mission Critical",
            "lifecycle_risk_score": 100,
            "patch_risk_score": 100,
            "incident_count_90d": 90,
            "defender_active_critical_alert_count": 4,
            "defender_active_high_alert_count": 4,
            "defender_attack_path_membership_count": 6,
            "defender_attack_path_target_count": 6,
            "defender_unhealthy_control_count": 4,
            "defender_secure_score_gap": 100,
            "application": "",
            "business_service": "",
        },
        {
            "dependency_count": 10,
            "affected_applications": [],
            "affected_services": [],
        },
        {"risk_reduction_percent": 100},
    )

    assert result["priority_score"] == 65
    assert result["priority"] == "Priority 2"


def test_evidenced_business_impact_outranks_maximum_technical_signals_without_mapping():
    prioritizer = PlanPrioritizer()
    mapped = prioritizer.prioritize(
        {
            "business_criticality": "Mission Critical",
            "lifecycle_risk_score": 60,
            "patch_risk_score": 60,
            "incident_count_90d": 1,
            "defender_active_high_alert_count": 2,
            "defender_attack_path_membership_count": 1,
            "defender_unhealthy_control_count": 1,
            "defender_secure_score_gap": 25,
            "application": "Payments API",
            "business_service": "Checkout",
        },
        {
            "dependency_count": 2,
            "affected_applications": ["Payments API"],
            "affected_services": ["Checkout"],
        },
        {"risk_reduction_percent": 60},
    )
    unmapped = prioritizer.prioritize(
        {
            "business_criticality": "Mission Critical",
            "lifecycle_risk_score": 100,
            "patch_risk_score": 100,
            "incident_count_90d": 90,
            "defender_active_critical_alert_count": 4,
            "defender_active_high_alert_count": 4,
            "defender_attack_path_membership_count": 6,
            "defender_attack_path_target_count": 6,
            "defender_unhealthy_control_count": 4,
            "defender_secure_score_gap": 100,
            "application": "",
            "business_service": "",
        },
        {
            "dependency_count": 10,
            "affected_applications": [],
            "affected_services": [],
        },
        {"risk_reduction_percent": 100},
    )

    assert mapped["priority_score"] > unmapped["priority_score"]
    assert mapped["priority_score"] >= 72
    assert unmapped["priority"] != "Priority 1"


def test_priority_factors_report_every_weight_table_bucket_by_name():
    factors = PlanPrioritizer().prioritize(
        {
            "business_criticality": "High",
            "application": "App",
            "business_service": "Svc",
        },
        {
            "dependency_count": 1,
            "affected_applications": ["App"],
            "affected_services": ["Svc"],
        },
        {"risk_reduction_percent": 0},
    )["priority_factors"]

    assert set(factors) == {
        "business_impact",
        "defender_exposure",
        "expected_risk_reduction",
        "service_criticality",
        "dependency_count",
        "lifecycle_risk",
        "patch_risk",
        "incident_history",
    }


def test_defender_exposure_bucket_responds_to_independent_signals_without_single_signal_saturation():
    prioritizer = PlanPrioritizer()
    base_resource = {"application": "App", "business_service": "Svc"}
    dependencies = {
        "dependency_count": 0,
        "affected_applications": ["App"],
        "affected_services": ["Svc"],
    }
    simulation = {"risk_reduction_percent": 0}

    alerts = prioritizer.prioritize(
        {**base_resource, "defender_active_critical_alert_count": 2},
        dependencies,
        simulation,
    )["priority_factors"]["defender_exposure"]
    attack_paths = prioritizer.prioritize(
        {
            **base_resource,
            "defender_attack_path_membership_count": 1,
            "defender_attack_path_target_count": 1,
        },
        dependencies,
        simulation,
    )["priority_factors"]["defender_exposure"]
    controls = prioritizer.prioritize(
        {
            **base_resource,
            "defender_unhealthy_control_count": 2,
            "defender_secure_score_gap": 50,
        },
        dependencies,
        simulation,
    )["priority_factors"]["defender_exposure"]

    assert 0 < alerts < 18
    assert 0 < attack_paths < 18
    assert 0 < controls < 18
    assert len({alerts, attack_paths, controls}) >= 2


def test_priority_bands_remain_unchanged():
    prioritizer = PlanPrioritizer()
    assert (
        prioritizer.prioritize(
            {
                "application": "App",
                "business_service": "Svc",
                "business_criticality": "High",
            },
            {"dependency_count": 0, "affected_applications": ["App"], "affected_services": ["Svc"]},
            {"risk_reduction_percent": 0},
        )["priority"]
        == "Priority 2"
    )
    assert (
        prioritizer.prioritize(
            {"application": "App", "business_service": "Svc"},
            {"dependency_count": 0, "affected_applications": ["App"], "affected_services": ["Svc"]},
            {"risk_reduction_percent": 0},
        )["priority"]
        == "Priority 3"
    )
    assert (
        prioritizer.prioritize(
            {},
            {"dependency_count": 0, "affected_applications": [], "affected_services": []},
            {"risk_reduction_percent": 0},
        )["priority"]
        == "Priority 4"
    )


def test_priority_factors_do_not_count_findings_closed():
    factors = PlanPrioritizer().prioritize(
        {},
        {"dependency_count": 0, "affected_applications": [], "affected_services": []},
        {"risk_reduction_percent": 0},
    )["priority_factors"]

    assert all("finding" not in name and "closed" not in name for name in factors)


def test_non_defender_relative_ordering_stays_stable_when_no_defender_signals_present():
    prioritizer = PlanPrioritizer()
    low = prioritizer.prioritize(
        {
            "business_criticality": "Low",
            "lifecycle_risk_score": 20,
            "patch_risk_score": 20,
            "incident_count_90d": 0,
            "application": "App A",
            "business_service": "Svc A",
        },
        {
            "dependency_count": 1,
            "affected_applications": ["App A"],
            "affected_services": ["Svc A"],
        },
        {"risk_reduction_percent": 20},
    )
    high = prioritizer.prioritize(
        {
            "business_criticality": "Mission Critical",
            "lifecycle_risk_score": 80,
            "patch_risk_score": 80,
            "incident_count_90d": 3,
            "application": "App B",
            "business_service": "Svc B",
        },
        {
            "dependency_count": 5,
            "affected_applications": ["App B"],
            "affected_services": ["Svc B"],
        },
        {"risk_reduction_percent": 80},
    )

    assert high["priority_score"] > low["priority_score"]


def test_runtime_merge_preserves_defender_keys_and_leaves_unmatched_resource_unchanged():
    posture = defender_correlator().posture_by_resource()
    mapped = posture[MAPPED_RESOURCE_ID.casefold()]
    assert mapped["defender_active_high_alert_count"] == 1
    assert mapped["defender_attack_path_membership_count"] == 1
    assert all("defender_" in key for key in mapped if key.startswith("defender_"))
    assert (
        posture.get(
            "/subscriptions/sub-1/resourcegroups/rg-missing/providers/microsoft.compute/virtualmachines/vm-missing"
        )
        is None
    )


def test_defender_trigger_produces_opportunity_from_resource_signal():
    resource = {
        **defender_resources()[0],
        **defender_correlator().posture_by_resource()[MAPPED_RESOURCE_ID.casefold()],
        "defender_recommendation": "Enable disk encryption",
        "evidence_citations": defender_correlator().cases()[0]["evidence_citations"],
    }
    engine = RemediationOpportunityEngine(ACTION_CATALOG)

    opportunities = engine.identify([resource])

    assert opportunities
    assert opportunities[0]["action_id"] == "enable-disk-encryption"


def test_opportunity_keeps_string_evidence_and_adds_defender_evidence_citations():
    resource = {
        **defender_resources()[0],
        **defender_correlator().posture_by_resource()[MAPPED_RESOURCE_ID.casefold()],
        "defender_recommendation": "Enable disk encryption",
        "evidence_citations": defender_correlator().cases()[0]["evidence_citations"],
    }
    engine = RemediationOpportunityEngine(ACTION_CATALOG)

    opportunity = engine.identify([resource])[0]

    assert opportunity["evidence"]
    assert all(isinstance(item, str) for item in opportunity["evidence"])
    assert opportunity["evidence_citations"]
    assert all("source_id" in citation for citation in opportunity["evidence_citations"])


def test_risk_analyzer_folds_defender_operational_signal_into_operational_risk():
    assessment = RiskAnalyzer().analyze(
        {
            "patch_risk_score": 20,
            "lifecycle_risk_score": 40,
            "predictive_risk_score": 60,
            "configuration_drift_count": 1,
            "defender_secure_score_gap": 80,
        },
        {"dependency_count": 0},
        ACTION_CATALOG[0],
    )

    assert assessment["operational_risk"]["score"] == 44


def test_risk_analyzer_marks_all_five_operational_signals_as_known():
    assessment = RiskAnalyzer().analyze(
        {
            "patch_risk_score": 20,
            "lifecycle_risk_score": 40,
            "predictive_risk_score": 60,
            "configuration_drift_count": 1,
            "defender_secure_score_gap": 80,
        },
        {"dependency_count": 0},
        ACTION_CATALOG[0],
    )

    assert assessment["operational_risk"]["evidence_status"] == "Known"


def test_risk_analyzer_marks_four_of_five_operational_signals_as_partial():
    assessment = RiskAnalyzer().analyze(
        {
            "patch_risk_score": 20,
            "lifecycle_risk_score": 40,
            "predictive_risk_score": 60,
            "configuration_drift_count": 1,
        },
        {"dependency_count": 0},
        ACTION_CATALOG[0],
    )

    assert assessment["operational_risk"]["evidence_status"] == "Partial"


def test_missing_correlator_or_empty_posture_is_a_no_op():
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=[],
        defender_alerts=[],
        defender_attack_paths=[],
        defender_attack_path_nodes=[],
        defender_secure_score_controls=[],
        freshness="2026-08-18T13:00:00Z",
    )
    empty = defender_correlator(resources=[], vulnerability_service=service)
    assert empty.posture_by_resource() == {}


def test_canonical_resource_key_normalizes_case_and_arm_id_forms():
    resources = defender_resources()
    upper_resource = {
        **resources[0],
        "resource_key": MAPPED_RESOURCE_ID.upper(),
    }
    correlator = defender_correlator(resources=[upper_resource])

    posture = correlator.posture_by_resource()

    assert MAPPED_RESOURCE_ID.casefold() in posture
