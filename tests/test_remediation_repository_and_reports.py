from remediation_scenario import remediation_planner


def test_repository_projects_required_ontology_entities_and_relationships():
    planner = remediation_planner()
    result = planner.generate_plans()
    initial_projection = planner.repository.ontology_projection()
    entity_types = {row["entity_type"] for row in initial_projection["entities"]}

    assert {
        "RemediationPlan",
        "ApprovalRequirement",
        "RollbackPlan",
        "ExecutionStep",
        "RiskAssessment",
        "SimulationResult",
    } <= entity_types
    planner.repository.decisions.append(
        plan=result["plans"][0],
        decision="approved",
        approver="operator@example.com",
        reason="Approved for planning handoff",
        scope={},
        action_version=result["plans"][0]["action_version"],
    )
    projection = planner.repository.ontology_projection()
    entity_types = {row["entity_type"] for row in projection["entities"]}
    relationship_types = {row["relationship_type"] for row in projection["relationships"]}
    assert "ApprovalDecision" in entity_types
    assert {"requiresPlan", "mitigatesRisk", "protectsService", "hasApprovalDecision"} <= relationship_types
    assert len(planner.repository.list()) == len(result["plans"])
    assert projection["read_only"] is True


def test_reports_cover_required_executive_planning_views():
    planner = remediation_planner(max_output_items=2)
    for report in (
        "Modernization Roadmap",
        "Patch Remediation Plan",
        "Compliance Recovery Plan",
        "High-Risk Service Remediation Plan",
        "Technology Debt Reduction Plan",
        "Executive Risk Reduction Strategy",
    ):
        result = planner.report(report)
        assert result["report_type"]
        assert result["read_only"] is True
        assert result["approval_required"] is True
        assert len(result["plans"]) <= 2
        assert result["collection_metadata"]["plans"]["count"] >= len(result["plans"])
