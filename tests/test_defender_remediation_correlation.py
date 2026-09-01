"""Behavior tests for Defender-correlated business-decision remediation cases."""

from __future__ import annotations

from defender_correlation_scenario import (
    MAPPED_RESOURCE_ID,
    UNMAPPED_RESOURCE_ID,
    UNMATCHED_WEAKNESS_RESOURCE_ID,
    defender_correlator,
)


def test_shared_resource_and_weakness_collapse_into_one_case():
    correlator = defender_correlator()
    cases = correlator.cases()
    mapped = [case for case in cases if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()]
    assert len(mapped) == 1
    case = mapped[0]
    citation_sources = {citation["source_id"] for citation in case["evidence_citations"]}
    # assessment + alert + attack path node + secure-score control all
    # contribute to the same resource/weakness pairing.
    assert {"assess-001", "alert-001"}.issubset(citation_sources)
    assert len(case["evidence_citations"]) >= 2


def test_citations_preserve_distinct_source_types_and_metadata():
    correlator = defender_correlator()
    case = next(
        case for case in correlator.cases() if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()
    )
    source_types = {citation["source_type"] for citation in case["evidence_citations"]}
    assert {"assessment", "alert"}.issubset(source_types)
    for citation in case["evidence_citations"]:
        assert citation["source_type"]
        assert citation["source_id"]
        assert citation["observed_at"]
        assert citation["freshness"]
        assert citation["summary"]


def test_known_business_context_is_populated_from_resource_and_dependencies():
    correlator = defender_correlator()
    case = next(
        case for case in correlator.cases() if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()
    )
    context = case["business_context"]
    assert context["affected_applications"] == ["Payments API"]
    assert context["affected_services"] == ["Checkout"]
    assert context["owners"] == ["Payments Product Owner"]
    assert context["upstream_dependencies"] == ["API Gateway"]
    assert context["downstream_dependencies"] == ["Ledger Writer"]


def test_every_case_reports_cost_of_action_and_inaction_when_business_context_known():
    correlator = defender_correlator()
    case = next(
        case for case in correlator.cases() if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()
    )
    assert case["cost_of_action"]
    assert case["cost_of_inaction"]


def test_every_case_reports_disposition_and_urgency_rationale():
    correlator = defender_correlator()
    for case in correlator.cases():
        assert case["disposition"] in {
            "act_now",
            "schedule",
            "defer",
            "not_applicable",
            "escalate",
        }
        assert case["urgency_rationale"]


def test_unmapped_business_context_lowers_confidence_and_escalates():
    correlator = defender_correlator()
    cases = {case["resource_key"]: case for case in correlator.cases()}
    mapped_case = cases[MAPPED_RESOURCE_ID.casefold()]
    unmapped_case = cases[UNMAPPED_RESOURCE_ID.casefold()]
    assert unmapped_case["confidence"] < mapped_case["confidence"]
    assert unmapped_case["disposition"] == "escalate"
    assert unmapped_case["business_mapping_review_required"] is True


def test_critical_severity_with_unknown_mapping_never_acts_now():
    correlator = defender_correlator()
    unmapped_case = next(
        case for case in correlator.cases() if case["resource_key"] == UNMAPPED_RESOURCE_ID.casefold()
    )
    assert unmapped_case["disposition"] != "act_now"


def test_facts_inferences_and_unknowns_are_separated():
    correlator = defender_correlator()
    for case in correlator.cases():
        assert isinstance(case["observed_facts"], list)
        assert isinstance(case["derived_inferences"], list)
        assert isinstance(case["unknowns"], list)


def test_unmatched_weakness_reports_no_safe_action_and_is_still_returned():
    correlator = defender_correlator()
    unmatched_case = next(
        case
        for case in correlator.cases()
        if case["resource_key"] == UNMATCHED_WEAKNESS_RESOURCE_ID.casefold()
    )
    assert unmatched_case["catalog_match"] is False
    assert unmatched_case["outcome"] == "no_safe_action"
    assert unmatched_case["outcome_reason"]


def test_cases_are_read_only_with_no_execution_state():
    correlator = defender_correlator()
    assert not hasattr(correlator, "execute")
    assert not hasattr(correlator, "apply")
    for case in correlator.cases():
        assert case["read_only"] is True
        assert "execution_performed" not in case
        assert "job_id" not in case


def test_posture_by_resource_emits_fixed_defender_signal_vocabulary():
    correlator = defender_correlator()
    posture = correlator.posture_by_resource()
    resource_posture = posture[MAPPED_RESOURCE_ID.casefold()]
    for key in (
        "defender_active_critical_alert_count",
        "defender_active_high_alert_count",
        "defender_attack_path_membership_count",
        "defender_attack_path_target_count",
        "defender_unhealthy_control_count",
        "defender_secure_score_gap",
        "defender_exploitable_finding_count",
        "defender_max_severity",
        "defender_evidence_freshness",
        "defender_business_mapping_known",
    ):
        assert key in resource_posture
