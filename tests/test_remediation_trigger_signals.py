"""Contract tests for the signals that governed catalog triggers match against.

``RemediationPlanner`` flattens ``resource_signals`` onto its resources when it
is constructed, but the Defender correlator is attached afterwards and
correlation runs at plan-generation time -- strictly later than opportunity
identification. Any trigger field that no producer writes onto the resource
rows is therefore permanently dead, and the catalog action keyed on it can
never fire. These tests pin that contract so a dead field fails loudly here
rather than silently returning an empty remediation page.
"""

from __future__ import annotations

import json
from pathlib import Path

from api.runtime import _merge_trigger_signals
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "fabric"
    / "catalogs"
    / "governed_remediation_catalog.v1.json"
)


def _catalog() -> list[dict]:
    return json.loads(CATALOG_PATH.read_text())["action_catalog"]


def _trigger_fields(catalog: list[dict]) -> set[str]:
    fields: set[str] = set()
    for action in catalog:
        for clause in action["trigger"].get("any") or ():
            fields.add(str(clause["field"]))
    return fields


class _Planner:
    def __init__(self, resources: list[dict]) -> None:
        self.resources = resources


class _Correlator:
    def __init__(self, posture: dict[str, dict]) -> None:
        self._posture = posture

    def posture_by_resource(self) -> dict[str, dict]:
        return self._posture


class _VulnerabilityService:
    def __init__(self, exposures: list[dict]) -> None:
        self._exposures = exposures

    def asset_exposures(self) -> list[dict]:
        return self._exposures


def test_merge_trigger_signals_flattens_defender_and_vulnerability_signals() -> None:
    planner = _Planner(
        [
            {"resource_key": "/subscriptions/s/rg/a"},
            {"resource_key": "/subscriptions/s/rg/b"},
        ]
    )
    _merge_trigger_signals(
        planner,
        _Correlator({"/subscriptions/s/rg/a": {"defender_exploitable_finding_count": 3}}),
        _VulnerabilityService(
            [{"asset_id": "/subscriptions/s/rg/b", "critical_count": 4}]
        ),
    )

    assert planner.resources[0]["defender_exploitable_finding_count"] == 3
    assert planner.resources[1]["critical_vulnerability_count"] == 4


def test_merge_trigger_signals_survives_partial_snapshots() -> None:
    """A missing Defender table must degrade to an absent signal, not a crash."""

    class _Broken:
        def posture_by_resource(self):
            raise RuntimeError("defender tables unavailable")

    planner = _Planner([{"resource_key": "/subscriptions/s/rg/a"}])
    _merge_trigger_signals(planner, _Broken(), _VulnerabilityService([]))

    assert "defender_exploitable_finding_count" not in planner.resources[0]


def test_merge_trigger_signals_is_a_no_op_without_inputs() -> None:
    planner = _Planner([{"resource_key": "/subscriptions/s/rg/a"}])
    _merge_trigger_signals(planner, None, None)

    assert planner.resources[0] == {"resource_key": "/subscriptions/s/rg/a"}


def test_every_governed_catalog_action_can_fire() -> None:
    """No catalog action may depend on a trigger field no producer emits."""
    catalog = _catalog()
    resources = [
        # Defender-sourced signals, merged by _merge_trigger_signals.
        {"resource_key": "/subscriptions/s/rg/a", "defender_active_critical_alert_count": 1},
        {"resource_key": "/subscriptions/s/rg/b", "defender_attack_path_membership_count": 1},
        {"resource_key": "/subscriptions/s/rg/c", "defender_unhealthy_control_count": 1},
        {"resource_key": "/subscriptions/s/rg/d", "defender_secure_score_gap": 10},
        {"resource_key": "/subscriptions/s/rg/e", "defender_exploitable_finding_count": 1},
        # Vulnerability-sourced signal, merged by _merge_trigger_signals.
        {"resource_key": "/subscriptions/s/rg/f", "critical_vulnerability_count": 1},
        # Patch intelligence posture, merged in fabric.runtime.
        {"resource_key": "/subscriptions/s/rg/g", "failed_update": True},
        {"resource_key": "/subscriptions/s/rg/h", "patch_risk_score": 75},
        # Change intelligence posture, merged in fabric.runtime.
        {"resource_key": "/subscriptions/s/rg/i", "configuration_drift_count": 1},
        {"resource_key": "/subscriptions/s/rg/j", "policy_violation_count": 1},
    ]

    fired = {
        row["action_id"]
        for row in RemediationOpportunityEngine(catalog).identify(resources)
    }

    assert fired == {action["action_id"] for action in catalog}


def test_every_trigger_field_is_exercised_by_a_producer() -> None:
    """Guards the reverse direction: a new trigger field needs a producer."""
    produced = {
        # api.runtime._merge_trigger_signals (Defender correlator posture)
        "defender_active_critical_alert_count",
        "defender_attack_path_membership_count",
        "defender_unhealthy_control_count",
        "defender_secure_score_gap",
        "defender_exploitable_finding_count",
        # api.runtime._merge_trigger_signals (vulnerability asset exposures)
        "critical_vulnerability_count",
        # fabric.runtime merge_posture (patch intelligence)
        "failed_update",
        "patch_risk_score",
        # fabric.runtime merge_posture (change intelligence)
        "configuration_drift_count",
        "policy_violation_count",
    }

    assert _trigger_fields(_catalog()) <= produced
