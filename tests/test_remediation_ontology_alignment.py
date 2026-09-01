from pathlib import Path

from remediation_scenario import remediation_planner
from fabric.dataset_mapper import ONTOLOGY_RELATIONSHIP_TYPES, remediation_decision_ontology_rows, remediation_plan_ontology_rows
from tests.defender_correlation_scenario import defender_correlator


def test_approval_decisions_are_projected_into_remediation_ontology():
    planner = remediation_planner()
    plan = next(
        item for item in planner.generate_plans()["plans"] if item["evidence_citations"]
    )

    decision = planner.repository.decisions.append(
        plan=plan,
        decision="rejected",
        approver="operator@example.com",
        reason="Evidence needs owner clarification",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
    )
    projection = planner.repository.ontology_projection()

    assert any(
        row["entity_id"] == decision["decision_id"]
        and row["entity_type"] == "ApprovalDecision"
        and row["lifecycle_status"] == "rejected"
        for row in projection["entities"]
    )
    assert any(
        row["subject_id"] == plan["plan_id"]
        and row["relationship_type"] == "hasApprovalDecision"
        and row["object_id"] == decision["decision_id"]
        for row in projection["relationships"]
    )
    assert projection["read_only"] is True


def test_durable_approval_decisions_publish_to_ontology_rows():
    planner = remediation_planner()
    plan = planner.generate_plans()["plans"][0]
    decision = planner.repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="operator@example.com",
        reason="Approved for planning handoff",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
        expires_at="2026-09-01T00:00:00Z",
    )

    entities, relationships = remediation_decision_ontology_rows(
        [decision],
        "run-1",
        "2026-08-31T00:00:00Z",
    )

    assert any(
        row["resource_id"] == decision["decision_id"]
        and row["entity_type"] == "ApprovalDecision"
        for row in entities
    )
    assert any(
        row["subject_id"] == plan["plan_id"]
        and row["predicate"] == "hasApprovalDecision"
        and row["object_id"] == decision["decision_id"]
        for row in relationships
    )


def test_plan_defender_evidence_relationships_are_registered_and_projected():
    planner = remediation_planner(defender_correlator=defender_correlator())
    plan = planner.generate_plans()["plans"][0]

    projection = planner.repository.ontology_projection()
    relationship_types = {row["relationship_type"] for row in projection["relationships"]}

    assert {
        ("RemediationPlan", "addressesFinding", "DefenderAssessment"),
        ("RemediationPlan", "addressesAlert", "SecurityAlert"),
        ("RemediationPlan", "breaksAttackPath", "AttackPath"),
        ("RemediationPlan", "improvesControl", "SecureScoreControl"),
    } <= set(ONTOLOGY_RELATIONSHIP_TYPES)
    assert {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    } <= relationship_types
    assert any(
        row["relationship_type"] == "addressesFinding"
        and row["object_id"] == "assess-001"
        for row in projection["relationships"]
    )
    distinct = {
        row["relationship_type"]
        for row in projection["relationships"]
        if row["relationship_type"]
        in {"addressesFinding", "addressesAlert", "breaksAttackPath", "improvesControl"}
    }
    assert distinct == {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    }
    forbidden = ("resolve", "fix", "remediate", "close", "clear")
    assert all(
        all(term not in row["relationship_type"].casefold() for term in forbidden)
        for row in projection["relationships"]
    )
    rel = next(
        row for row in projection["relationships"] if row["relationship_type"] == "addressesFinding"
    )
    assert rel["confidence"] == 1.0
    assert rel["source"] == "remediation-plan-citation"


def test_plan_projection_records_unresolved_citations_without_synthesized_ids():
    planner = remediation_planner(defender_correlator=defender_correlator())
    plans = planner.generate_plans()["plans"]
    broken = dict(next(item for item in plans if item["evidence_citations"]))
    broken["resource"] = {"name": "vm-payments"}
    broken["resource_key"] = ""
    broken["evidence_citations"] = [
        {key: value for key, value in citation.items() if key != "resource_id"}
        for citation in broken["evidence_citations"]
    ]
    planner.repository.replace_generation([broken])

    projection = planner.repository.ontology_projection()

    assert not any(
        row["relationship_type"] in {"addressesFinding", "addressesAlert", "breaksAttackPath", "improvesControl"}
        for row in projection["relationships"]
    )
    assert projection["pending_relationships"]
    assert all("reason" in row for row in projection["pending_relationships"])


def test_plan_projection_still_keeps_existing_plan_relationships():
    planner = remediation_planner(defender_correlator=defender_correlator())
    plan = next(
        item for item in planner.generate_plans()["plans"] if item["evidence_citations"]
    )
    planner.repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="operator@example.com",
        reason="Approved for planning handoff",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
    )
    projection = planner.repository.ontology_projection()
    rels = {row["relationship_type"] for row in projection["relationships"]}
    assert {
        "requiresApproval",
        "hasStep",
        "hasRollbackPlan",
        "hasSimulation",
        "mitigatesRisk",
        "protectsService",
        "requiresPlan",
        "hasApprovalDecision",
    } <= rels


def test_plan_relationship_rows_publish_through_sync_path():
    planner = remediation_planner(defender_correlator=defender_correlator())
    planner.generate_plans()
    projection = planner.repository.ontology_projection()
    entities, relationships = remediation_plan_ontology_rows(
        projection,
        "run-1",
        "2026-08-31T00:00:00Z",
    )
    published = {row["predicate"] for row in relationships}
    assert {
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    } <= published


def test_docs_and_schema_remain_aligned_with_registry_predicates():
    docs = Path("docs/ontology-model.md").read_text()
    schema = Path("ontology-schema.md").read_text()
    for predicate in (
        "addressesFinding",
        "addressesAlert",
        "breaksAttackPath",
        "improvesControl",
    ):
        assert predicate in docs
        assert predicate in schema
    for phrase in (
        "record intent to address",
        "not resolved until post-change evidence confirms it",
        "canonical resource ID",
        "separate meanings",
    ):
        assert phrase in docs
        assert phrase in schema
