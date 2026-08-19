from datetime import UTC, datetime

from semantic_scenario import semantic_scenario

from intelligence.predictive.predictive_intelligence import PredictiveIntelligence
from semantic.semantic_engine import SemanticEngine


def test_predictive_context_uses_public_semantic_apis():
    scenario=semantic_scenario(); semantic=SemanticEngine.from_rows(**scenario); resource=scenario["inventory"][0]; key=resource["resource_id"]
    engine=PredictiveIntelligence.from_semantic_engine(
        semantic, inventory=[resource], resource_signals={key:{"patch_risk_score":70,"patch_debt":5,"lifecycle_risk_score":20,"incident_count_30d":2,"incident_count_90d":3,"change_risk_score":40,"configuration_drift_count":1,"security_finding_count":1}}, history=[], now=lambda: datetime(2026,8,18,tzinfo=UTC)
    )
    prediction=engine.analyze()["predictions"][0]
    assert prediction["application"]=="Payments"
    assert prediction["business_service"]=="Retail"
    assert prediction["owner"]=="ops@example.com"
    assert prediction["support_team"]=="SRE"
