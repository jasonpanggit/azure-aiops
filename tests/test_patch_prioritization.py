from __future__ import annotations

from patch_scenario import patch_engine


def test_priority_queue_is_ranked_and_contains_business_aware_rationale():
    queue = patch_engine().query("Show patch priority list")["result"]

    assert queue[0]["resource"]["name"] == "vm-payroll-01"
    assert queue[0]["priority"] == "Priority 1"
    assert "critical business workload" in queue[0]["priority_reasoning"]
    assert "missing critical update" in queue[0]["priority_reasoning"]
    assert queue[-1]["priority"] == "Priority 4"
    assert all(item["advisory_only"] is True for item in queue)
    assert all("no action is executed" in item["recommended_action"] for item in queue)
