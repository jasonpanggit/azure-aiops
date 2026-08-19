from __future__ import annotations

import json
from pathlib import Path

import pytest
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import OperationsAgent
from semantic.semantic_engine import SemanticEngine


def agent() -> OperationsAgent:
    return OperationsAgent(SemanticEngine.from_rows(**semantic_scenario()))


def test_analyze_vm_returns_evidence_backed_read_only_reasoning():
    result = agent().analyze("Analyze VM", "vm-payments")

    assert result["command"] == "Analyze VM"
    assert result["subject"]["name"] == "vm-payments"
    assert set(result["operational_domains"]) >= {
        "Infrastructure Health",
        "Patch Compliance",
        "Security Exposure",
        "Ownership Coverage",
        "Operational Risk",
    }
    assert result["risk"]["level"] == "Critical"
    assert result["health"]["category"] in {
        "Healthy",
        "Warning",
        "Degraded",
        "Critical",
    }
    assert result["conclusions"]
    assert all(
        conclusion["evidence"]
        and conclusion["data_sources"]
        and conclusion["reasoning"]
        and "risk_factors" in conclusion
        for conclusion in result["conclusions"]
    )
    assert result["recommendations"]
    assert result["read_only"] is True
    assert "action_result" not in result


def test_unknown_agent_command_fails_closed():
    with pytest.raises(ValueError, match="Unsupported Operations Agent command"):
        agent().analyze("Restart VM", "vm-payments")


def test_patch_failure_workflow_correlates_severity_impact_and_escalation():
    result = agent().analyze("Analyze Patch Compliance", "vm-payments")

    assert result["severity"] == "Critical"
    assert [row["name"] for row in result["impact"]["impacted_applications"]] == [
        "Payments"
    ]
    assert [
        row["name"] for row in result["impact"]["impacted_business_services"]
    ] == ["Retail"]
    assert result["ownership"]["owners"][0]["name"] == "ops@example.com"
    assert result["ownership"]["support_groups"][0]["name"] == "SRE"
    assert any(
        "schedule remediation" in item["suggested_action"]
        for item in result["recommendations"]
    )


def test_dependency_workflow_exposes_direction_radius_and_criticality():
    result = agent().analyze(
        "Show Impact Summary", "vm-payments", subject_type="VirtualMachine"
    )
    impact = result["impact"]

    assert [row["name"] for row in impact["upstream_dependencies"]] == [
        "Identity"
    ]
    assert impact["downstream_dependencies"] == []
    assert impact["blast_radius"]["application_count"] == 1
    assert impact["criticality"] == {
        "risk_level": "Critical",
        "criticality_points": 10,
    }
    assert result["freshness"] == "2026-08-17T00:00:00Z"
    assert result["knowledge_version"].startswith("semantic-")


def test_operational_risk_analysis_recommends_advisory_review():
    result = agent().analyze("Analyze Operational Risk", "vm-payments")

    assert result["risk"]["level"] == "Critical"
    assert any(
        item["priority"] == "Critical" and item["advisory_only"]
        for item in result["recommendations"]
    )


def test_operations_agent_records_required_latency_metrics():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.analysis_duration = Instrument()
            self.recommendation_latency = Instrument()
            self.knowledge_retrieval_latency = Instrument()
            self.summary_generation_latency = Instrument()
            self.impact_duration = Instrument()
            self.context_generation_latency = Instrument()

    telemetry = Telemetry()
    operations = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario()), telemetry=telemetry
    )

    operations.analyze("Analyze VM", "vm-payments")
    operations.analyze(
        "Show Impact Summary", "vm-payments", subject_type="VirtualMachine"
    )
    operations.analyze(
        "Generate Incident Context",
        "vm-payments",
        subject_type="VirtualMachine",
    )

    assert telemetry.analysis_duration.records
    assert telemetry.recommendation_latency.records
    assert telemetry.knowledge_retrieval_latency.records
    assert telemetry.summary_generation_latency.records
    assert telemetry.impact_duration.records
    assert telemetry.context_generation_latency.records


def test_sample_operational_scenarios_run_end_to_end():
    scenarios = json.loads(
        Path("tests/fixtures/sample_operations_scenarios.json").read_text()
    )
    operations = agent()

    for scenario in scenarios:
        result = operations.analyze(
            scenario["command"],
            scenario["subject"],
            subject_type=scenario["subject_type"],
        )
        assert result["subject"]["name"] == scenario["expected_subject"]
        assert result["risk"]["level"] == scenario["expected_risk"]
        assert result["read_only"] is True


def test_analyze_vm_uses_vm_domain_when_name_collides_with_arc_server():
    scenario = semantic_scenario()
    scenario["entities"].append(
        {
            "resource_id": "arc-collision",
            "entity_type": "ArcServer",
            "name": "vm-payments",
            "lifecycle_status": "active",
        }
    )
    scenario["inventory"].append(
        {
            "resource_id": "arc-collision",
            "name": "vm-payments",
            "entity_type": "ArcServer",
            "status": "available",
        }
    )

    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Analyze VM", "vm-payments"
    )

    assert result["subject"]["entity_type"] == "VirtualMachine"


def test_dependency_analysis_is_bounded_and_discloses_truncation():
    scenario = semantic_scenario()
    payments_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["entity_type"] == "Application" and row["name"] == "Payments"
    )
    scenario["entities"].extend(
        {
            "resource_id": f"upstream-{index}",
            "entity_type": "Application",
            "name": f"Upstream {index}",
            "lifecycle_status": "active",
        }
        for index in range(60)
    )
    scenario["relationships"].extend(
        {
            "resource_id": f"depends-{index}",
            "subject_id": payments_id,
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": f"upstream-{index}",
            "object_type": "Application",
            "lifecycle_status": "active",
        }
        for index in range(60)
    )

    operations = OperationsAgent(SemanticEngine.from_rows(**scenario))
    result = operations.analyze(
        "Show Impact Summary", "vm-payments", subject_type="VirtualMachine"
    )
    analysis = operations.analyze("Analyze VM", "vm-payments")

    assert len(result["impact"]["upstream_dependencies"]) == 50
    assert result["impact"]["truncated"] is True
    assert analysis["evidence_metadata"]["sections"]["upstream_dependencies"] == {
        "count": 61,
        "returned": 50,
        "truncated": True,
    }
    assert analysis["evidence_metadata"]["truncated"] is True


def test_analyze_business_service_uses_business_service_domain_on_collision():
    scenario = semantic_scenario()
    scenario["entities"].append(
        {
            "resource_id": "service-collision",
            "entity_type": "Service",
            "name": "Retail",
            "lifecycle_status": "active",
        }
    )

    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Analyze Business Service", "Retail"
    )

    assert result["subject"]["entity_type"] == "BusinessService"


def test_operational_risk_subject_type_resolves_cross_domain_collision():
    scenario = semantic_scenario()
    scenario["entities"].append(
        {
            "resource_id": "service-payments-collision",
            "entity_type": "Service",
            "name": "Payments",
            "lifecycle_status": "active",
        }
    )

    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Analyze Operational Risk", "Payments", subject_type="Application"
    )

    assert result["subject"]["entity_type"] == "Application"


def test_application_analysis_returns_substantive_ten_domain_conclusions():
    result = agent().analyze("Analyze Application", "Payments")
    conclusions = {item["domain"]: item for item in result["conclusions"]}

    assert set(conclusions) == {
        "Infrastructure Health",
        "Patch Compliance",
        "Security Exposure",
        "Ownership Coverage",
        "Application Dependencies",
        "Business Impact",
        "Operational Risk",
        "Cost Optimization",
        "Lifecycle Management",
        "Governance",
    }
    assert "Identity" in str(conclusions["Application Dependencies"]["evidence"])
    assert "Retail" in str(conclusions["Business Impact"]["evidence"])
    assert "CC-42" in str(conclusions["Cost Optimization"]["evidence"])
    assert "active" in str(conclusions["Lifecycle Management"]["evidence"])
    assert all(item["evidence"] and item["reasoning"] for item in conclusions.values())
    assert any(
        "cost allocation" in item["suggested_action"].casefold()
        for item in result["recommendations"]
    )


def test_obsolete_sku_advisor_workflow_is_usable_end_to_end():
    scenario = semantic_scenario()
    vm_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["entity_type"] == "VirtualMachine" and row["name"] == "vm-payments"
    )
    scenario["entities"].append(
        {
            "resource_id": "obsolete-sku-advisor",
            "entity_type": "AdvisorRecommendation",
            "name": "Modernize obsolete SKU",
            "lifecycle_status": "active",
        }
    )
    scenario["relationships"].append(
        {
            "resource_id": "obsolete-sku-affects-vm",
            "subject_id": "obsolete-sku-advisor",
            "subject_type": "AdvisorRecommendation",
            "predicate": "affects",
            "object_id": vm_id,
            "object_type": "VirtualMachine",
            "lifecycle_status": "active",
        }
    )

    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Analyze VM", "vm-payments"
    )

    lifecycle = next(
        item for item in result["conclusions"] if item["domain"] == "Lifecycle Management"
    )
    assert "Modernize obsolete SKU" in str(lifecycle["evidence"])
    assert any(
        "modernization" in item["suggested_action"].casefold()
        for item in result["recommendations"]
    )


def test_related_semantic_context_is_correlated_across_vm_subscription_and_service():
    operations = agent()

    vm = operations.analyze("Analyze VM", "vm-payments")
    subscription = operations.analyze("Analyze Subscription", "sub-1")
    service = operations.analyze("Analyze Business Service", "Retail")

    vm_domains = {item["domain"]: item for item in vm["conclusions"]}
    subscription_domains = {
        item["domain"]: item for item in subscription["conclusions"]
    }
    service_domains = {item["domain"]: item for item in service["conclusions"]}

    assert "Identity" in str(vm_domains["Application Dependencies"]["evidence"])
    assert "Payments" in str(subscription_domains["Business Impact"]["evidence"])
    assert "Retail" in str(subscription_domains["Business Impact"]["evidence"])
    assert "failed" in str(service_domains["Patch Compliance"]["evidence"])
    assert "active" in str(service_domains["Lifecycle Management"]["evidence"])
