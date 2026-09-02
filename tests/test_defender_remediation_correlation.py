"""Behavior tests for Defender-correlated business-decision remediation cases."""

from __future__ import annotations

from defender_correlation_scenario import (
    MAPPED_RESOURCE_ID,
    UNMAPPED_RESOURCE_ID,
    UNMATCHED_WEAKNESS_RESOURCE_ID,
    defender_correlator,
    defender_resources,
)
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from tests.test_api_http import FakeSecretWriter

OPERATOR_TOKEN = "operator-token-0123456789abcd"
SCOPED_OPERATOR_TOKEN = "scoped-operator-token-012345"


def _fake_planner(correlator):
    class _FakePlanner:
        defender_correlator = correlator
        resources = defender_resources()

        @staticmethod
        def generate_plans():
            return {"plans": [], "generated_at": "", "read_only": True, "execution_performed": False}

        @staticmethod
        def identify_opportunities():
            return {"opportunities": [], "generated_at": "", "read_only": True}

    return _FakePlanner()


def _client(tmp_path, *, correlator=None, principals=None) -> TestClient:
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(
            tmp_path / "aiops", secret_writer=FakeSecretWriter()
        ),
        authenticator=StaticTokenAuthenticator(
            principals
            or {
                OPERATOR_TOKEN: Principal(subject="operator@example.com", grants=(Grant("operator"),)),
                SCOPED_OPERATOR_TOKEN: Principal(
                    subject="scoped-operator@example.com",
                    grants=(Grant("operator", Scope({"business_service": ["Checkout"]})),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        remediation_provider=lambda: _fake_planner(correlator or defender_correlator()),
    )
    return TestClient(create_app(context), raise_server_exceptions=False)


def _auth(token: str = OPERATOR_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def test_defender_cases_route_returns_scoped_evidence_envelope(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/remediation/defender-cases", headers=_auth())
    assert response.status_code == 200, response.text
    body = response.json()
    cases = body["data"]["cases"]
    assert cases
    case = next(case for case in cases if case["resource_key"] == MAPPED_RESOURCE_ID.casefold())
    assert case["evidence_citations"]
    assert case["business_context"]
    assert case["disposition"]
    assert case["urgency_rationale"]
    assert body["evidence"][0]["source_engine"] == "intelligence.DefenderRemediationCorrelator"


def test_out_of_scope_defender_case_is_absent_for_scoped_operator(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/api/v1/remediation/defender-cases", headers=_auth(SCOPED_OPERATOR_TOKEN)
    )
    assert response.status_code == 200, response.text
    resource_keys = {case["resource_key"] for case in response.json()["data"]["cases"]}
    # The scoped operator is only authorized for business_service "Checkout"
    # (the mapped resource); the unmapped and unmatched-catalog resources
    # carry no such scope attribute and must not leak through.
    assert MAPPED_RESOURCE_ID.casefold() in resource_keys
    assert UNMAPPED_RESOURCE_ID.casefold() not in resource_keys


def test_degraded_source_family_reports_unavailable_and_still_returns_healthy_cases(
    tmp_path,
) -> None:
    from defender_correlation_scenario import (
        ACTION_CATALOG,
        defender_alerts,
        defender_assessments,
        defender_attack_path_nodes,
        defender_attack_paths,
        defender_secure_score_controls,
    )

    from intelligence.remediation.defender_correlation import (
        DefenderRemediationCorrelator,
    )
    from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=defender_assessments(),
        defender_alerts=defender_alerts(),
        defender_attack_paths=defender_attack_paths(),
        defender_attack_path_nodes=defender_attack_path_nodes(),
        defender_secure_score_controls=defender_secure_score_controls(),
        defender_source_status=[
            {
                "source_family": "defender_alerts",
                "availability": "unavailable",
                "freshness": "stale",
                "quality": "degraded",
                "error": "Defender alerts export failed",
                "observed_at": "2026-08-18T05:00:00Z",
            }
        ],
        freshness="2026-08-18T13:00:00Z",
    )
    correlator = DefenderRemediationCorrelator(
        vulnerability_service=service,
        dependency_analyzer=DependencyAnalyzer(),
        resource_lookup=defender_resources(),
        action_catalog=ACTION_CATALOG,
    )
    client = _client(tmp_path, correlator=correlator)
    response = client.get("/api/v1/remediation/defender-cases", headers=_auth())
    assert response.status_code == 200, response.text
    body = response.json()
    assert any("defender_alerts".replace("defender_", "") in warning or "alert" in warning for warning in body.get("warnings", []))
    mapped_case = next(
        case
        for case in body["data"]["cases"]
        if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()
    )
    assert mapped_case["source_family_status"]["alert"]["availability"] == "unavailable"
    unmatched_case = next(
        case
        for case in body["data"]["cases"]
        if case["resource_key"] == UNMATCHED_WEAKNESS_RESOURCE_ID.casefold()
    )
    assert unmatched_case["source_family_status"]["assessment"]["availability"] != "unavailable"


def test_contradictory_evidence_reports_disagreement_and_reduced_confidence(tmp_path) -> None:
    from defender_correlation_scenario import (
        ACTION_CATALOG,
        defender_alerts,
        defender_assessments,
        defender_attack_path_nodes,
        defender_attack_paths,
        defender_secure_score_controls,
    )

    from intelligence.remediation.defender_correlation import (
        DefenderRemediationCorrelator,
    )
    from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    assessments = defender_assessments()
    assessments[0]["severity"] = "low"
    alerts = defender_alerts()
    alerts[0]["severity"] = "critical"
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=assessments,
        defender_alerts=alerts,
        defender_attack_paths=defender_attack_paths(),
        defender_attack_path_nodes=defender_attack_path_nodes(),
        defender_secure_score_controls=defender_secure_score_controls(),
        freshness="2026-08-18T13:00:00Z",
    )
    correlator = DefenderRemediationCorrelator(
        vulnerability_service=service,
        dependency_analyzer=DependencyAnalyzer(),
        resource_lookup=defender_resources(),
        action_catalog=ACTION_CATALOG,
    )
    client = _client(tmp_path, correlator=correlator)
    response = client.get("/api/v1/remediation/defender-cases", headers=_auth())
    assert response.status_code == 200, response.text
    mapped_case = next(
        case
        for case in response.json()["data"]["cases"]
        if case["resource_key"] == MAPPED_RESOURCE_ID.casefold()
    )
    assert mapped_case["contradictory_evidence"] is True
    assert mapped_case["confidence"] < 0.7


def test_defender_cases_route_is_read_only_with_no_execution_endpoint(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/v1/remediation/defender-cases", headers=_auth())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["read_only"] is True
    for case in response.json()["data"]["cases"]:
        assert case["read_only"] is True
