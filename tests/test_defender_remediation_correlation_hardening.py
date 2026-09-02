from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intelligence.remediation.plan_prioritizer import PlanPrioritizer
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)
from intelligence.vulnerability.service import VulnerabilityIntelligenceService
from tests.defender_correlation_scenario import (
    ACTION_CATALOG,
    UNMAPPED_RESOURCE_ID,
    defender_alerts,
    defender_assessments,
    defender_attack_path_nodes,
    defender_attack_paths,
    defender_correlator,
    defender_resources,
    defender_secure_score_controls,
)


def test_large_attack_path_is_bounded_and_reports_truncation():
    path = defender_attack_paths()[0]
    path["resourceIds"] = [
        f"/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-{i}"
        for i in range(150)
    ]
    nodes = [
        {
            "id": f"node-{i}",
            "name": f"vm-{i}",
            "attackPathId": "path-001",
            "nodeType": "VirtualMachine",
            "resourceId": resource_id,
            "resolved": True,
        }
        for i, resource_id in enumerate(path["resourceIds"])
    ]
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=[],
        defender_alerts=[],
        defender_attack_paths=[path],
        defender_attack_path_nodes=nodes,
        defender_secure_score_controls=[],
        freshness="2026-08-18T13:00:00Z",
    )

    cases = defender_correlator(vulnerability_service=service, max_cases=20).cases()

    assert len(cases) <= 20
    assert any("truncation" in " ".join(case["unknowns"]) for case in cases)


def test_large_cve_blast_radius_is_bounded_and_reports_truncation():
    assessments = []
    for i in range(120):
        row = defender_assessments()[0].copy()
        row["assessment_id"] = f"assess-{i:03d}"
        row["target_resource_id"] = (
            f"/subscriptions/sub-1/resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-{i}"
        )
        row["cve_id"] = "CVE-2026-9999"
        assessments.append(row)
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=assessments,
        defender_alerts=[],
        defender_attack_paths=[],
        defender_attack_path_nodes=[],
        defender_secure_score_controls=[],
        freshness="2026-08-18T13:00:00Z",
    )

    cases = defender_correlator(vulnerability_service=service, max_cases=25).cases()

    assert len(cases) <= 25
    assert any("truncation" in " ".join(case["unknowns"]) for case in cases)


def test_missing_or_unparseable_timestamp_is_unknown_and_lowers_confidence():
    assessments = defender_assessments()
    assessments = assessments[:1]
    assessments[0]["last_assessed_at"] = "not-a-timestamp"
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=assessments,
        defender_alerts=defender_alerts(),
        defender_attack_paths=defender_attack_paths(),
        defender_attack_path_nodes=defender_attack_path_nodes(),
        defender_secure_score_controls=defender_secure_score_controls(),
        freshness="2026-08-18T13:00:00Z",
    )

    case = defender_correlator(vulnerability_service=service).cases()[0]

    assert any(citation["freshness"] == "unknown" for citation in case["evidence_citations"])
    assert case["confidence"] < 0.95


def test_stale_source_family_marks_cases_stale_and_lowers_confidence():
    stale_at = (datetime(2026, 8, 18, 13, tzinfo=UTC) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    controls = defender_secure_score_controls()
    controls[0]["observedAt"] = stale_at
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=defender_assessments(),
        defender_alerts=defender_alerts(),
        defender_attack_paths=defender_attack_paths(),
        defender_attack_path_nodes=defender_attack_path_nodes(),
        defender_secure_score_controls=controls,
        freshness="2026-08-18T13:00:00Z",
    )

    case = defender_correlator(vulnerability_service=service).cases()[0]

    assert any(citation["freshness"] == "stale" for citation in case["evidence_citations"])
    assert case["confidence"] < 0.95


def test_contradictory_source_families_record_disagreement_and_reduce_confidence():
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

    case = defender_correlator(vulnerability_service=service).cases()[0]

    assert case["contradictory_evidence"] is True
    assert case["confidence"] < 0.8


def test_unknown_inventory_resource_escalates_without_fabricating_resource():
    assessments = defender_assessments()
    assessments = assessments[:1]
    assessments[0]["target_resource_id"] = (
        "/subscriptions/sub-1/resourceGroups/rg-missing/providers/Microsoft.Compute/virtualMachines/vm-missing"
    )
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=assessments,
        defender_alerts=[],
        defender_attack_paths=[],
        defender_attack_path_nodes=[],
        defender_secure_score_controls=[],
        freshness="2026-08-18T13:00:00Z",
    )

    case = defender_correlator(vulnerability_service=service).cases()[0]

    assert case["resource_name"] == "vm-missing"
    assert case["disposition"] == "escalate"
    assert "resource" in " ".join(case["unknowns"])


def test_malformed_resource_identifier_is_skipped_with_recorded_reason():
    assessments = defender_assessments()
    assessments = assessments[:1]
    assessments[0]["target_resource_id"] = ""
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=assessments,
        defender_alerts=[],
        defender_attack_paths=[],
        defender_attack_path_nodes=[],
        defender_secure_score_controls=[],
        freshness="2026-08-18T13:00:00Z",
    )

    cases = defender_correlator(vulnerability_service=service).cases()

    assert cases == []


def test_unmapped_business_context_never_reaches_priority_one_end_to_end():
    correlator = defender_correlator()
    case = next(item for item in correlator.cases() if item["resource_key"] == UNMAPPED_RESOURCE_ID.casefold())
    resource = {
        **next(row for row in defender_resources() if row["resource_key"] == UNMAPPED_RESOURCE_ID),
        **correlator.posture_by_resource()[UNMAPPED_RESOURCE_ID.casefold()],
        "defender_recommendation": "Enable disk encryption",
        "evidence_citations": case["evidence_citations"],
    }
    opportunity = RemediationOpportunityEngine(ACTION_CATALOG).identify([resource])[0]
    priority = PlanPrioritizer().prioritize(
        resource,
        case["business_context"],
        {"risk_reduction_percent": 100},
    )

    assert case["disposition"] != "act_now"
    assert opportunity["action_id"] == "enable-disk-encryption"
    assert priority["priority"] != "Priority 1"
