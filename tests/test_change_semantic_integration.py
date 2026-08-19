from datetime import UTC, datetime

from semantic_scenario import semantic_scenario

from intelligence.change.change_intelligence import ChangeIntelligence
from semantic.semantic_engine import SemanticEngine


def test_change_context_uses_public_semantic_apis():
    scenario = semantic_scenario()
    semantic = SemanticEngine.from_rows(**scenario)
    resource = scenario["inventory"][0]
    key = resource["resource_id"]
    engine = ChangeIntelligence.from_semantic_engine(
        semantic,
        inventory=[resource],
        resource_changes=[{
            "change_id": "CHG-1", "resource_key": key,
            "changed_at": "2026-08-17T00:00:00Z", "change_type": "Update",
            "category": "Configuration", "changed_by": "Unknown", "source": "ARG",
            "changed_fields": [], "summary": "Resource updated"
        }],
        policy_deviations=[], security_deviations=[], network_changes=[],
        identity_changes=[], iac_changes=[], incidents=[], history=[],
        expected_configurations={}, observed_configurations={},
        now=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )
    finding = engine.analyze()["findings"][0]
    assert finding["application"] == "Payments"
    assert finding["business_service"] == "Retail"
    assert finding["owner"] == "ops@example.com"
    assert finding["support_team"] == "SRE"
