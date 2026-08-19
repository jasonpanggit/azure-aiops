from __future__ import annotations

from semantic_scenario import semantic_scenario

from semantic.semantic_engine import SemanticEngine
from semantic.semantic_models import RiskInputs, RiskScorer
from semantic.semantic_registry import SemanticRegistry

MODULES = (
    "semantic_engine",
    "semantic_registry",
    "semantic_models",
    "query_cache",
    "indexes",
    "validator",
)

MODELS = {
    "Application",
    "Service",
    "Infrastructure",
    "Compliance",
    "Patching",
    "Ownership",
    "BusinessImpact",
    "ResourceHealth",
    "OperationalRisk",
    "Dependencies",
    "Lifecycle",
    "Cost",
    "Security",
}


def _engine(**kwargs) -> SemanticEngine:
    return SemanticEngine.from_rows(**semantic_scenario(), **kwargs)


def test_exact_semantic_framework_modules_and_models_exist():
    for module in MODULES:
        __import__(f"semantic.{module}")
    assert set(SemanticRegistry.default().names()) == MODELS


def test_reusable_views_and_agent_api_contract():
    semantic = _engine()
    application = semantic.application_context("Payments")
    business_service = semantic.service_context(
        "Retail", subject_type="BusinessService"
    )
    subscription = semantic.subscription_context("sub-1")
    resource = semantic.resource_context(
        "vm-payments", subject_type="VirtualMachine"
    )

    assert application["context_type"] == "application"
    assert business_service["subject"]["entity_type"] == "BusinessService"
    assert subscription["context_type"] == "subscription"
    assert resource["context_type"] == "resource"
    assert semantic.risk_context("vm-payments")["risk"]["level"] == "Critical"
    assert semantic.impact_context(
        "vm-identity", subject_type="VirtualMachine"
    )["blast_radius"]["application_count"] == 2
    assert semantic.search_operational_context(
        "Find all production applications"
    )["items"]


def test_required_semantic_queries_and_searches():
    semantic = _engine()
    assert semantic.query("Show application context", subject="Payments")[
        "context_type"
    ] == "application"
    assert semantic.query("Show service context", subject="Retail")[
        "context_type"
    ] == "service"
    assert semantic.query("Show VM context", subject="vm-payments")[
        "context_type"
    ] == "resource"
    assert semantic.query("Show server context", subject="vm-payments")[
        "context_type"
    ] == "resource"
    assert semantic.query("Show subscription context", subject="sub-1")[
        "context_type"
    ] == "subscription"
    assert semantic.query("Find orphan resources")["intent"] == "orphan_resources"
    assert semantic.query("Find ownership gaps")["intent"] == "ownership_gaps"
    assert semantic.query("Show dependency chain", subject="Payments")["upstream"]
    assert semantic.query("Show downstream impact", subject="Identity")["items"]
    assert semantic.query("Show upstream dependencies", subject="Payments")["items"]
    assert semantic.query("Show operational risk", subject="vm-payments")["risk"]

    assert semantic.search_operational_context(
        "Find all applications owned by SRE"
    )["items"]
    assert semantic.search_operational_context(
        "Find servers with failed patches"
    )["items"]
    assert semantic.search_operational_context(
        "Find applications missing ownership"
    )["count"] == 0
    assert semantic.search_operational_context(
        "Find critical infrastructure by business service Retail"
    )["items"]


def test_impact_analysis_contract_covers_required_failure_modes():
    semantic = _engine()
    vm = semantic.impact_context("vm-identity", subject_type="VirtualMachine")
    application = semantic.impact_context("Identity", subject_type="Application")
    patch = semantic.impact_context(
        "patch-payments", subject_type="PatchAssessment"
    )
    subscription = semantic.impact_context("sub-1", subject_type="Subscription")

    for result in (vm, application, patch, subscription):
        assert result["root"]
        assert result["blast_radius"]
        assert result["tree"]
        assert "truncated" in result
    assert vm["impacted_applications"]
    assert application["impacted_business_services"]
    assert patch["impacted_business_services"]
    assert subscription["blast_radius"]["resource_count"] == 2


def test_operational_risk_methodology_is_deterministic_and_bounded():
    assessment = RiskScorer().score(
        RiskInputs(
            missing_owner=True,
            patch_compliant=False,
            advisor_recommendation_count=1,
            security_finding_count=1,
            criticality="Critical",
            environment="Production",
        )
    )
    assert assessment.score == 100
    assert assessment.level == "Critical"
    assert assessment.score == sum(assessment.factors.values())
    assert RiskScorer.level_for(24) == "Low"
    assert RiskScorer.level_for(25) == "Moderate"
    assert RiskScorer.level_for(50) == "High"
    assert RiskScorer.level_for(75) == "Critical"


def test_semantic_telemetry_records_all_required_metrics():
    class Instrument:
        def __init__(self):
            self.records = []

        def record(self, value, attributes=None):
            self.records.append((value, attributes))

    class Telemetry:
        def __init__(self):
            self.query_latency = Instrument()
            self.traversal_latency = Instrument()
            self.context_latency = Instrument()
            self.cache_hit_ratio = Instrument()
            self.knowledge_freshness = Instrument()
            self.ontology_lag = Instrument()
            self.cache_results = []

        def record_cache(self, hit, ratio):
            self.cache_results.append((hit, ratio))
            self.cache_hit_ratio.record(ratio)

    telemetry = Telemetry()
    semantic = _engine(telemetry=telemetry)
    semantic.application_context("Payments")
    semantic.application_context("Payments")
    semantic.risk_context("vm-payments", subject_type="VirtualMachine")
    semantic.impact_context("vm-identity", subject_type="VirtualMachine")
    semantic.search_operational_context("Find all production applications")

    assert telemetry.query_latency.records
    assert telemetry.traversal_latency.records
    assert telemetry.context_latency.records
    assert telemetry.cache_hit_ratio.records
    assert telemetry.knowledge_freshness.records
    assert telemetry.ontology_lag.records
    assert any(hit for hit, _ratio in telemetry.cache_results)
