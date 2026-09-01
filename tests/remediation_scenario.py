from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from intelligence.remediation.remediation_planner import RemediationPlanner
from tests.defender_correlation_scenario import defender_correlator


def remediation_planner(**overrides):
    fixture = json.loads(
        Path("tests/fixtures/sample_remediation_planning.json").read_text()
    )
    correlator = overrides.pop("defender_correlator", defender_correlator())
    if "resources" not in overrides:
        resource_by_key = {
            str(key).casefold(): row
            for key, row in correlator.resources_by_key.items()
        }
        merged_resources = []
        for row in fixture["resources"]:
            resource_key = str(row.get("resource_key") or "").casefold()
            merged = {**row, **resource_by_key.get(resource_key, {})}
            merged["resource"] = {
                "id": merged.get("resource_key", ""),
                "name": merged.get("name", ""),
                "entity_type": merged.get("entity_type", "Resource"),
            }
            merged_resources.append(merged)
        fixture["resources"] = merged_resources
    fixture.update(overrides)
    planner = RemediationPlanner.from_snapshot(
        **fixture,
        now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    planner.generator.defender_correlator = correlator
    return planner
