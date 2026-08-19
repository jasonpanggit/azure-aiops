from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
from change_scenario import change_engine

from fabric.config import FabricRuntimeConfig
from intelligence.change.change_context_builder import ChangeContextBuilder
from intelligence.change.change_intelligence import ChangeIntelligence


def test_encoded_and_standalone_identifiers_are_redacted():
    engine = change_engine()
    arm = "/subscriptions/5ef7423a-80d9-4c44-ae0f-058600202e4a/resourceGroups/rg/providers/x/a"
    engine.changes[0]["summary"] = " ".join(
        [
            base64.b64encode(arm.encode()).decode(),
            "\n".join(
                base64.b64encode(arm.encode()).decode()[index : index + 16]
                for index in range(0, len(base64.b64encode(arm.encode()).decode()), 16)
            ).rstrip("="),
            arm.encode().hex(),
            "5ef7423a-80d9-4c44-ae0f-058600202e4a",
            "%2525252Fsubscriptions%2525252F5ef7423a-80d9-4c44-ae0f-058600202e4a",
        ]
    )

    serialized = json.dumps(engine.analyze()).casefold()

    assert "5ef7423a-80d9-4c44-ae0f-058600202e4a" not in serialized
    assert base64.b64encode(arm.encode()).decode().casefold() not in serialized
    assert arm.encode().hex() not in serialized


def test_change_config_boolean_false_disables_and_malformed_types_fail(tmp_path):
    base = """
fabric:
  auth: {mode: managed_identity}
  workspace_name: Operations
  lakehouse_name: Inventory
  source_data_root: ./source
  change_intelligence: VALUE
"""
    path = tmp_path / "fabric.yaml"
    path.write_text(base.replace("VALUE", "false"))
    assert FabricRuntimeConfig.load(path).change_intelligence.enabled is False

    for value in ('"false"', "[]"):
        path.write_text(base.replace("VALUE", value))
        with pytest.raises((TypeError, ValueError), match="change_intelligence"):
            FabricRuntimeConfig.load(path)

    for field in ("max_changes", "max_output_items"):
        path.write_text(
            base.replace("VALUE", f"{{enabled: true, {field}: 0}}")
        )
        with pytest.raises(ValueError, match="bounds"):
            FabricRuntimeConfig.load(path)


def test_duplicate_or_resolved_deviations_do_not_inflate_posture():
    scenario = json.loads(
        __import__("pathlib").Path(
            "tests/fixtures/sample_change_intelligence.json"
        ).read_text()
    )
    duplicate = dict(scenario["policy_deviations"][0])
    scenario["security_deviations"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate deviation identity"):
        ChangeIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )

    scenario["security_deviations"].pop()
    scenario["policy_deviations"][0]["status"] = "Resolved"
    engine = ChangeIntelligence.from_snapshot(
        **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
    )
    compliance = engine.analyze()["compliance"][0]
    assert compliance["policy_deviation_count"] == 0
    assert compliance["compliance_score"] == 55


def test_unrelated_change_and_missing_incident_identity_are_not_probable():
    engine = change_engine()
    engine.changes[0].update(category="Configuration", changed_fields=["tags"])
    finding = next(
        row
        for row in engine.analyze()["findings"]
        if row["change"]["change_id"] == "CHG-100"
    )
    assert finding["incident_correlation"]["classification"] != "Probable contributor"

    scenario = json.loads(
        __import__("pathlib").Path(
            "tests/fixtures/sample_change_intelligence.json"
        ).read_text()
    )
    del scenario["incidents"][0]["incident_id"]
    with pytest.raises(ValueError, match="incident_id"):
        ChangeIntelligence.from_snapshot(
            **scenario, now=lambda: datetime(2026, 8, 18, 13, tzinfo=UTC)
        )


def test_trends_and_recent_changes_are_deterministic_and_recency_ordered():
    engine = change_engine(max_output_items=1)
    reversed_engine = change_engine()
    reversed_engine.history.reverse()
    assert engine.analyze()["trends"] == reversed_engine.analyze()["trends"]

    engine.changes.append(
        {
            **engine.changes[0],
            "change_id": "CHG-NEW",
            "changed_at": "2026-08-18T12:20:00Z",
            "severity": "Low",
            "changed_fields": [],
        }
    )
    recent = engine.query("Show recent changes")["result"]
    assert recent[0]["change"]["change_id"] == "CHG-NEW"


def test_nested_deviation_collections_respect_output_bound():
    engine = change_engine(max_output_items=2)
    base = dict(engine.policy[0])
    engine.policy = [
        {**base, "deviation_id": f"POL-{index}"} for index in range(20)
    ]
    finding = engine.analyze()["findings"][0]
    assert len(finding["policy_deviations"]) <= 2
    context = engine.context_builder._resources[next(iter(engine.context_builder._resources))]
    context["expected_configuration"] = {f"field-{index}": 0 for index in range(20)}
    context["observed_configuration"] = {f"field-{index}": 1 for index in range(20)}
    analysis = engine.analyze()
    assert len(analysis["findings"][0]["configuration_drift"]["fields"]) <= 2
    assert len(analysis["compliance"][0]["drift_fields"]) <= 2


def test_whitespace_actor_is_unknown_and_deviation_order_is_deterministic():
    engine = change_engine(max_output_items=1)
    engine.changes[0]["changed_by"] = "   "
    finding = next(
        row
        for row in engine.analyze()["findings"]
        if row["change"]["change_id"] == "CHG-100"
    )
    assert finding["actor_evidence_status"] == "Unknown"
    assert all(not item.startswith("Actor:") for item in finding["evidence"])

    base = dict(engine.policy[0])
    engine.policy = [
        {**base, "deviation_id": "POL-Z"},
        {**base, "deviation_id": "POL-A"},
    ]
    forward = engine.query("Show policy deviations")["result"]
    engine.policy.reverse()
    reverse = engine.query("Show policy deviations")["result"]
    assert forward == reverse


def test_encoded_canonical_resource_aliases_match():
    key = "/subscriptions/sub-1/resourceGroups/rg/providers/x/a"
    builder = ChangeContextBuilder([{"resource_key": key, "name": "server"}])
    encoded = key.replace("/", "%2525252F")
    assert builder.get(encoded)["resource"]["name"] == "server"
