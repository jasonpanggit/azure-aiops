"""Behavior tests for BusinessDecisionEngine: consequence, disposition, alternatives.

The user's locked correction is that remediation is not finding closure and
that technical severity alone must never decide priority. These tests assert
that correction is executable logic, not intent: every decision states both
cost sides against named evidence, every disposition is reason-coded, and a
case lacking a known business mapping can never receive ``act_now`` no matter
how severe the underlying technical signal is.
"""

from __future__ import annotations

from intelligence.remediation.business_decision import BusinessDecisionEngine, DISPOSITIONS
from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
from intelligence.remediation.execution_simulator import ExecutionSimulator
from intelligence.remediation.risk_analyzer import RiskAnalyzer
from intelligence.remediation.rollback_planner import RollbackPlanner

from defender_correlation_scenario import (
    ACTION_CATALOG,
    MAPPED_RESOURCE_ID,
    NOT_APPLICABLE_RESOURCE_ID,
    UNMAPPED_RESOURCE_ID,
    defender_correlator,
    defender_resources,
)

def _full_action() -> dict:
    """The catalog action fixture only sets risk_reduction_percent; the
    execution simulator requires all four effectiveness percentages, so
    default the rest to 0 for tests that need a real simulation view."""
    action = dict(ACTION_CATALOG[0])
    action["effectiveness"] = {
        "risk_reduction_percent": 40,
        "compliance_improvement_percent": 0,
        "lifecycle_exposure_reduction_percent": 0,
        "operational_debt_reduction_percent": 0,
    }
    return action


ACTION = _full_action()


def _cases() -> dict[str, dict]:
    correlator = defender_correlator()
    return {case["resource_key"]: case for case in correlator.cases()}


def _resource_by_key(key: str) -> dict:
    for resource in defender_resources():
        if resource["resource_key"] == key:
            return resource
    raise AssertionError(f"no fixture resource for {key}")


def _views_for(case: dict) -> dict:
    """Build the dependency/risk/simulation/rollback views a real caller supplies."""
    resource = _resource_by_key(case["resource_key"])
    dependencies = DependencyAnalyzer().analyze(resource)
    risk = RiskAnalyzer().analyze(resource, dependencies, ACTION)
    simulation = ExecutionSimulator().simulate(resource, ACTION, risk)
    rollback = RollbackPlanner().build(ACTION)
    return {
        "dependencies": dependencies,
        "risk": risk,
        "simulation": simulation,
        "rollback": rollback,
        "action": ACTION,
    }


def _bounded_schedule_case() -> dict:
    """Hand-built case: bounded exposure, no active exploitation, known mapping."""
    return {
        "resource_key": "resource-schedule",
        "weakness_key": "text:enable disk encryption",
        "resource_name": "vm-scheduled",
        "evidence_citations": [
            {
                "source_type": "assessment",
                "source_id": "assess-schedule-1",
                "observed_at": "2026-08-18T09:00:00Z",
                "freshness": "stale",
                "summary": "Enable disk encryption",
                "severity": "medium",
            }
        ],
        "business_context": {
            "affected_applications": ["Reporting API"],
            "affected_services": ["Reporting"],
            "owners": ["Reporting Owner"],
            "dependency_count": 1,
        },
        "max_severity": "medium",
        "contradictory_evidence": False,
        "not_applicable_evidence": "",
        "source_family_status": {},
        "observed_facts": ["assessment:assess-schedule-1 reported medium severity"],
        "derived_inferences": [],
        "unknowns": [],
    }


def _defer_case() -> dict:
    """Hand-built case: change risk (via a heavy multi-stage action) exceeds current exposure."""
    return {
        "resource_key": "resource-defer",
        "weakness_key": "text:enable disk encryption",
        "resource_name": "vm-deferred",
        "evidence_citations": [
            {
                "source_type": "assessment",
                "source_id": "assess-defer-1",
                "observed_at": "2026-08-18T09:00:00Z",
                "freshness": "stale",
                "summary": "Enable disk encryption",
                "severity": "low",
            }
        ],
        "business_context": {
            "affected_applications": ["Reporting API"],
            "affected_services": ["Reporting"],
            "owners": ["Reporting Owner"],
            "dependency_count": 1,
        },
        "max_severity": "low",
        "contradictory_evidence": False,
        "not_applicable_evidence": "",
        "source_family_status": {},
        "observed_facts": ["assessment:assess-defer-1 reported low severity"],
        "derived_inferences": [],
        "unknowns": [],
    }


def _heavy_action() -> dict:
    """A catalog action with enough deployment stages to push execution risk high."""
    action = dict(ACTION)
    action["deployment_stages"] = ["staging", "canary", "region-1", "region-2", "production"]
    return action


def _high_execution_risk() -> dict:
    resource = _resource_by_key(MAPPED_RESOURCE_ID)
    resource = dict(resource, business_criticality="", environment="")
    dependencies = DependencyAnalyzer().analyze(resource)
    dependencies = dict(dependencies, dependency_count=10)
    action = _heavy_action()
    risk = RiskAnalyzer().analyze(resource, dependencies, action)
    return risk


# ---------------------------------------------------------------------------
# Task 1: disposition, urgency reason codes, cost sections, confidence
# ---------------------------------------------------------------------------


def test_act_now_disposition_names_active_business_impact_path():
    cases = _cases()
    case = dict(cases[MAPPED_RESOURCE_ID.casefold()])
    case["contradictory_evidence"] = False
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    assert decision["disposition"] == "act_now"
    assert decision["urgency_rationale"]["reason_code"] == "ACTIVE_BUSINESS_IMPACT_PATH"
    assert decision["urgency_rationale"]["evidence_citations"]


def test_schedule_disposition_names_bounded_exposure_and_maintenance_window():
    case = _bounded_schedule_case()
    decision = BusinessDecisionEngine().decide(case)
    assert decision["disposition"] == "schedule"
    assert decision["urgency_rationale"]["reason_code"] == "BOUNDED_EXPOSURE_MAINTENANCE_WINDOW"
    assert "maintenance window" in decision["urgency_rationale"]["message"]


def test_defer_disposition_names_both_sides_of_the_risk_comparison():
    case = _defer_case()
    risk = _high_execution_risk()
    decision = BusinessDecisionEngine().decide(case, risk=risk)
    assert decision["disposition"] == "defer"
    assert decision["urgency_rationale"]["reason_code"] == "CHANGE_RISK_EXCEEDS_EXPOSURE"
    message = decision["urgency_rationale"]["message"]
    assert "Change risk" in message
    assert "exposure" in message.casefold()


def test_not_applicable_disposition_carries_supporting_evidence():
    cases = _cases()
    case = cases[NOT_APPLICABLE_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    assert decision["disposition"] == "not_applicable"
    assert decision["urgency_rationale"]["reason_code"] == "EVIDENCE_CONFIRMS_NOT_APPLICABLE"
    assert "host level" in decision["urgency_rationale"]["message"]


def test_unknown_business_mapping_escalates_with_reduced_confidence_and_review():
    cases = _cases()
    mapped_case = cases[MAPPED_RESOURCE_ID.casefold()]
    unmapped_case = cases[UNMAPPED_RESOURCE_ID.casefold()]
    mapped_decision = BusinessDecisionEngine().decide(mapped_case, **_views_for(mapped_case))
    unmapped_decision = BusinessDecisionEngine().decide(unmapped_case, **_views_for(unmapped_case))
    assert unmapped_decision["disposition"] == "escalate"
    assert unmapped_decision["confidence"] < mapped_decision["confidence"]
    assert any("mapping" in item.casefold() for item in unmapped_decision["review_requirements"])


def test_contradictory_evidence_reduces_confidence_without_picking_a_family():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    assert case["contradictory_evidence"] is True
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    assert decision["confidence"] < 0.7
    assert any("families disagree" in item.casefold() or "conflicting" in item.casefold()
               for item in decision["review_requirements"])
    # The engine must not silently prefer one family's severity as authoritative:
    # the reason code names the contradiction rather than a specific family's value.
    assert decision["disposition"] == "escalate"
    assert decision["urgency_rationale"]["reason_code"] == "CONTRADICTORY_EVIDENCE"


def test_highest_severity_with_unknown_mapping_never_acts_now_but_moderate_mapped_can():
    cases = _cases()
    unmapped_case = dict(cases[UNMAPPED_RESOURCE_ID.casefold()])
    unmapped_case["max_severity"] = "critical"
    unmapped_decision = BusinessDecisionEngine().decide(unmapped_case, **_views_for(unmapped_case))
    assert unmapped_decision["disposition"] != "act_now"

    mapped_case = dict(cases[MAPPED_RESOURCE_ID.casefold()])
    mapped_case["contradictory_evidence"] = False
    mapped_case["max_severity"] = "high"
    mapped_decision = BusinessDecisionEngine().decide(mapped_case, **_views_for(mapped_case))
    assert mapped_decision["disposition"] == "act_now"


def test_every_decision_carries_named_cost_sections_across_all_dimensions():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    dimensions = (
        "service_risk",
        "customer_impact",
        "operational_continuity",
        "compliance_exposure",
        "change_risk",
        "downtime",
        "effort",
        "opportunity_cost",
    )
    for section_name in ("cost_of_action", "cost_of_inaction"):
        section = decision[section_name]
        assert section
        for dimension in dimensions:
            assert dimension in section
            entry = section[dimension]
            assert entry["status"] in {"known", "unknown"}
            assert entry["detail"]


def test_every_consequence_statement_names_its_evidence_citations():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    assert decision["urgency_rationale"]["evidence_citations"]
    known_entries = [
        entry
        for section in (decision["cost_of_action"], decision["cost_of_inaction"])
        for entry in section.values()
        if entry["status"] == "known"
    ]
    assert known_entries
    for entry in known_entries:
        assert entry["evidence_citations"]


def test_decision_output_has_no_finding_closure_count_term():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    forbidden_terms = ("findings_closed", "findings_closeable", "closure_count", "closed_count")
    factor_names = set(decision["cost_of_action"]) | set(decision["cost_of_inaction"])
    assert not (factor_names & set(forbidden_terms))
    for section in (decision["cost_of_action"], decision["cost_of_inaction"]):
        for entry in section.values():
            for forbidden in forbidden_terms:
                assert forbidden not in entry["detail"].casefold()


def test_dispositions_are_restricted_to_the_five_named_values():
    cases = _cases()
    for case in cases.values():
        decision = BusinessDecisionEngine().decide(case, **_views_for(case))
        assert decision["disposition"] in DISPOSITIONS
    assert set(DISPOSITIONS) == {"act_now", "schedule", "defer", "not_applicable", "escalate"}


# ---------------------------------------------------------------------------
# Task 2: alternatives comparison including doing nothing
# ---------------------------------------------------------------------------


def test_options_collection_contains_recommended_schedule_and_no_change():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    option_ids = {option["option_id"] for option in decision["options"]}
    assert {"act_now", "schedule", "no_change"}.issubset(option_ids)


def test_every_option_carries_the_full_attribute_set():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    required_attrs = (
        "pros",
        "cons",
        "residual_risk",
        "effort",
        "downtime",
        "reversibility",
        "business_impact",
    )
    for option in decision["options"]:
        for attr in required_attrs:
            assert attr in option
            value = option[attr]
            if isinstance(value, dict):
                assert value.get("status") in {"known", "unknown"}
            else:
                assert isinstance(value, list)


def test_exactly_one_option_is_recommended_and_matches_disposition():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    recommended = [option for option in decision["options"] if option["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["option_id"] == decision["disposition"]


def test_no_change_option_has_equal_depth_and_states_residual_risk_of_inaction():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    no_change = next(option for option in decision["options"] if option["option_id"] == "no_change")
    act_now = next(option for option in decision["options"] if option["option_id"] == "act_now")
    assert set(no_change) == set(act_now)
    assert no_change["residual_risk"] == decision["cost_of_inaction"]["service_risk"]
    assert no_change["residual_risk"]["status"] in {"known", "unknown"}


def test_option_with_unsupported_evidence_is_present_with_explicit_marker():
    case = _bounded_schedule_case()
    decision = BusinessDecisionEngine().decide(case)
    act_now = next(option for option in decision["options"] if option["option_id"] == "act_now")
    # No simulation/rollback view was supplied: attributes that depend on
    # them must still be present, marked unknown rather than omitted.
    assert act_now["downtime"]["status"] == "unknown"
    assert act_now["reversibility"]["status"] == "unknown"


def test_option_attributes_reuse_simulation_and_rollback_values():
    cases = _cases()
    case = cases[MAPPED_RESOURCE_ID.casefold()]
    views = _views_for(case)
    decision = BusinessDecisionEngine().decide(case, **views)
    act_now = next(option for option in decision["options"] if option["option_id"] == "act_now")
    risk_reduction = views["simulation"]["risk_reduction_percent"]
    assert str(risk_reduction) in act_now["residual_risk"]["detail"]
    reversible = views["rollback"]["reversible"]
    assert reversible is True
    assert "Reversible" in act_now["reversibility"]["detail"]


def test_escalate_decision_has_no_approvable_option():
    cases = _cases()
    case = cases[UNMAPPED_RESOURCE_ID.casefold()]
    decision = BusinessDecisionEngine().decide(case, **_views_for(case))
    assert decision["disposition"] == "escalate"
    recommended = next(option for option in decision["options"] if option["recommended"])
    assert recommended["option_id"] == "escalate"
    assert not any(option["approvable"] for option in decision["options"])


# -- Task 3: business decisions threaded into generated plans ----------------


def _generator_scenario(defender_correlator_instance=None):
    from intelligence.remediation.approval_engine import ApprovalEngine
    from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
    from intelligence.remediation.execution_simulator import ExecutionSimulator
    from intelligence.remediation.impact_estimator import ImpactEstimator
    from intelligence.remediation.plan_prioritizer import PlanPrioritizer
    from intelligence.remediation.remediation_generator import RemediationGenerator
    from intelligence.remediation.risk_analyzer import RiskAnalyzer
    from intelligence.remediation.rollback_planner import RollbackPlanner

    return RemediationGenerator(
        dependency_analyzer=DependencyAnalyzer(),
        risk_analyzer=RiskAnalyzer(),
        approval_engine=ApprovalEngine([]),
        rollback_planner=RollbackPlanner(),
        simulator=ExecutionSimulator(),
        impact_estimator=ImpactEstimator(),
        prioritizer=PlanPrioritizer(),
        defender_correlator=defender_correlator_instance,
    )


def _mapped_opportunity() -> dict:
    resource = _resource_by_key(MAPPED_RESOURCE_ID)
    return {
        "_resource_key": MAPPED_RESOURCE_ID,
        "_resource": resource,
        "_action": ACTION,
        "resource": {"name": resource["name"], "entity_type": resource.get("entity_type", "Resource")},
        "application": resource.get("application", "Unknown"),
        "business_service": resource.get("business_service", "Unknown"),
        "environment": resource.get("environment", ""),
        "owner": resource.get("owner", ""),
        "subscription_id": resource.get("subscription_id", ""),
        "subscription_connection": resource.get("subscription_connection", ""),
        "opportunity_type": ACTION["opportunity_type"],
        "action_id": ACTION["action_id"],
        "evidence": ["defender_recommendation:Enable disk encryption"],
        "read_only": True,
    }


def test_defender_sourced_plan_carries_full_business_decision_section():
    generator = _generator_scenario(defender_correlator())
    plan = generator.generate(_mapped_opportunity())
    decision = plan["business_decision"]
    assert decision["disposition"] in DISPOSITIONS
    assert decision["urgency_rationale"]["reason_code"]
    assert set(("service_risk", "customer_impact")) <= set(decision["cost_of_action"])
    assert set(("service_risk", "customer_impact")) <= set(decision["cost_of_inaction"])
    assert decision["options"]
    assert "confidence" in decision
    assert "review_requirements" in decision


def test_plan_carries_expected_secure_score_improvement_or_unknown_marker():
    generator = _generator_scenario(defender_correlator())
    plan = generator.generate(_mapped_opportunity())
    improvement = plan["expected_secure_score_improvement"]
    assert improvement["status"] in {"known", "unknown"}
    assert improvement["status"] == "known"
    assert improvement["points"] > 0

    generator_no_correlator = _generator_scenario(None)
    plan_no_case = generator_no_correlator.generate(_mapped_opportunity())
    assert plan_no_case["expected_secure_score_improvement"]["status"] == "unknown"


def test_plan_carries_uncertainty_section_from_unknowns_grouping():
    generator = _generator_scenario(defender_correlator())
    plan = generator.generate(_mapped_opportunity())
    assert isinstance(plan["uncertainty"], list)
    # Sourced from the decision's own unknowns grouping, not restated prose.
    assert plan["uncertainty"] == plan["business_decision"]["unknowns"]


def test_plan_and_opportunity_carry_evidence_citations_alongside_evidence_list():
    generator = _generator_scenario(defender_correlator())
    opportunity = _mapped_opportunity()
    plan = generator.generate(opportunity)
    assert isinstance(plan["evidence"], list)
    assert all(isinstance(item, str) for item in plan["evidence"])
    assert isinstance(plan["evidence_citations"], list)
    assert plan["evidence_citations"]
    assert all("source_type" in citation for citation in plan["evidence_citations"])


def test_non_defender_opportunity_still_generates_with_unknown_business_decision():
    generator = _generator_scenario(None)
    plan = generator.generate(_mapped_opportunity())
    decision = plan["business_decision"]
    assert decision["disposition"] in DISPOSITIONS
    assert plan["expected_secure_score_improvement"]["status"] == "unknown"
    assert isinstance(plan["uncertainty"], list)


def test_plan_still_reports_read_only_posture_with_no_execution_authorization():
    generator = _generator_scenario(defender_correlator())
    plan = generator.generate(_mapped_opportunity())
    assert plan["read_only"] is True
    assert plan["execution_authorized"] is False
    assert plan["execution_performed"] is False
    assert plan["recommended_action"]["advisory_only"] is True


def test_full_remediation_suite_still_passes_with_generator_extension():
    # Guardrail placeholder: the plan-level verification block runs the full
    # remediation suite directly; this test asserts the extension point the
    # rest of the suite depends on (an optional, defaulted constructor
    # parameter) does not require every existing caller to change.
    generator = _generator_scenario()
    plan = generator.generate(_mapped_opportunity())
    assert plan["business_decision"]["disposition"] in DISPOSITIONS
