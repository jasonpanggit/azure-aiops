from __future__ import annotations

from fabric_pipelines.predeploy_pipeline import OUTPUT_TABLE, run
from intelligence.predeploy import PreDeploymentImpactService
from test_predeploy import _discovered, _terraform_plan


def test_predeploy_pipeline_matches_hermes_service_for_cab_and_risk():
    proposed = [{"source": "terraform_plan", "payload": _terraform_plan(), "change_id": "chg-1"}]
    result = run(proposed_changes=proposed, discovered=_discovered())
    hermes = PreDeploymentImpactService().assess(
        source="terraform_plan",
        payload=_terraform_plan(),
        discovered=_discovered(),
        change_id="chg-1",
    )

    assert result.table_name == OUTPUT_TABLE
    row = result.evaluations[0]
    assert row["risk_score"] == hermes["risk"]["score"]
    assert row["cab_verdict"] == hermes["cab_recommendation"]["verdict"]
    assert row["total_impacted_count"] == hermes["blast_radius"]["total_impacted_count"]
    assert row["confirmed_cause"] is False
