from remediation_scenario import remediation_planner
from fabric.dataset_mapper import remediation_decision_ontology_rows


def test_approval_decisions_are_projected_into_remediation_ontology():
    planner = remediation_planner()
    plan = planner.generate_plans()["plans"][0]

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
