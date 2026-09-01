from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from deltalake import DeltaTable

from fabric.schema_registry import schema_for
from intelligence.remediation.approval_engine import ApprovalEngine
from intelligence.remediation.remediation_opportunity_engine import (
    RemediationOpportunityEngine,
)
from storage.delta_writer import DeltaWriteMode, DeltaWriter

FIXTURE_PATH = Path("tests/fixtures/governed_remediation_catalog.json")
SEEDER_PATH = Path("scripts/seed_remediation_catalog.py")

_COMMAND_PATTERN = re.compile(
    r"(^|\s)(sudo|rm\s|az\s|kubectl\s|curl\s|bash\s|sh\s|python[0-9.]*\s|\./|\$\(|`|\|\||;\s*\w+|>\s*/|2>&1)",
    re.IGNORECASE,
)


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


# ---------------------------------------------------------------------------
# Task 1: governed catalog content
# ---------------------------------------------------------------------------


def test_every_catalog_action_is_accepted_by_the_opportunity_engine() -> None:
    fixture = _load_fixture()
    engine = RemediationOpportunityEngine(fixture["action_catalog"])
    assert len(engine.catalog) == len(fixture["action_catalog"])


def test_catalog_covers_all_four_defender_signal_families() -> None:
    fixture = _load_fixture()
    required_fields = {
        "defender_active_critical_alert_count",
        "defender_attack_path_membership_count",
        "defender_unhealthy_control_count",
        "defender_exploitable_finding_count",
    }
    seen_fields: set[str] = set()
    for action in fixture["action_catalog"]:
        for clause in action["trigger"]["any"]:
            seen_fields.add(clause["field"])
    assert required_fields <= seen_fields


def test_defender_evidence_reaches_catalog_matching_via_identify() -> None:
    fixture = _load_fixture()
    engine = RemediationOpportunityEngine(fixture["action_catalog"])
    resource = {
        "resource_key": "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
        "name": "vm-1",
        "defender_active_critical_alert_count": 2,
    }
    opportunities = engine.identify([resource])
    assert opportunities
    matched = [
        opportunity
        for opportunity in opportunities
        if opportunity["action_id"] == "critical-alert-containment"
    ]
    assert matched
    assert any(
        "defender active critical alert count" in evidence
        for evidence in matched[0]["evidence"]
    )


def test_every_action_has_unique_id_and_required_labels() -> None:
    fixture = _load_fixture()
    action_ids = [action["action_id"] for action in fixture["action_catalog"]]
    assert len(action_ids) == len(set(action_ids))
    for action in fixture["action_catalog"]:
        assert str(action["title"]).strip()
        assert str(action["opportunity_type"]).strip()


def test_no_catalog_string_looks_like_a_runnable_command() -> None:
    fixture = _load_fixture()
    offenders = [
        value
        for value in _iter_strings(fixture["action_catalog"])
        if _COMMAND_PATTERN.search(value)
    ]
    assert offenders == []


def test_every_approval_policy_resolves_a_required_role_for_targeted_resource_classes() -> None:
    fixture = _load_fixture()
    engine = ApprovalEngine(fixture["approval_policies"])
    action = fixture["action_catalog"][0]
    resource = {
        "environment": "Production",
        "business_criticality": "Mission Critical",
    }
    risk = {"execution_risk": {"score": 60}}
    requirements = engine.requirements(resource, action, risk)
    assert requirements
    assert all(str(row["role"]).strip() for row in requirements)


# ---------------------------------------------------------------------------
# Task 2: seeder behaviors
# ---------------------------------------------------------------------------


def _read_json_column(table: Path, table_name: str, column: str) -> list:
    rows = DeltaTable(str(table / table_name)).to_pyarrow_table().to_pylist()
    return [json.loads(row[column]) for row in rows]


def _run_seeder(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SEEDER_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_seeder_help_documents_required_target_argument() -> None:
    result = _run_seeder("--help")
    assert result.returncode == 0
    assert "--target" in result.stdout


def test_seeder_requires_explicit_target(tmp_path: Path) -> None:
    result = _run_seeder()
    assert result.returncode != 0
    assert "target" in (result.stdout + result.stderr).lower()


def test_seeder_dry_run_reports_and_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "lakehouse"
    result = _run_seeder("--target", str(target), "--dry-run")
    assert result.returncode == 0
    assert "would" in result.stdout.lower()
    assert not target.exists()


def test_seeder_writes_both_tables_with_round_tripping_json_columns(
    tmp_path: Path,
) -> None:
    target = tmp_path / "lakehouse"
    result = _run_seeder("--target", str(target))
    assert result.returncode == 0

    fixture = _load_fixture()

    catalog_rows = DeltaTable(
        str(target / "Tables" / "silver_remediation_action_catalog")
    ).to_pyarrow_table().to_pylist()
    assert len(catalog_rows) == len(fixture["action_catalog"])
    seeded_by_id = {row["action_id"]: row for row in catalog_rows}
    for action in fixture["action_catalog"]:
        row = seeded_by_id[action["action_id"]]
        assert json.loads(row["trigger_json"]) == action["trigger"]
        assert json.loads(row["execution_steps_json"]) == action["execution_steps"]
        assert json.loads(row["preconditions_json"]) == action["preconditions"]
        assert json.loads(row["rollback_actions_json"]) == action["rollback_actions"]
        assert json.loads(row["success_criteria_json"]) == action["success_criteria"]
        assert json.loads(row["failure_criteria_json"]) == action["failure_criteria"]
        assert json.loads(row["deployment_stages_json"]) == action["deployment_stages"]
        assert json.loads(row["effectiveness_json"]) == action["effectiveness"]

    policy_rows = DeltaTable(
        str(target / "Tables" / "silver_remediation_approval_policies")
    ).to_pyarrow_table().to_pylist()
    assert len(policy_rows) == len(fixture["approval_policies"])
    seeded_policies_by_id = {row["policy_id"]: row for row in policy_rows}
    for policy in fixture["approval_policies"]:
        row = seeded_policies_by_id[policy["policy_id"]]
        assert json.loads(row["conditions_json"]) == policy["conditions"]
        assert json.loads(row["roles_json"]) == policy["roles"]

    schema = schema_for("silver_remediation_action_catalog")
    for field in schema:
        assert field.name in catalog_rows[0]


def test_seeder_is_idempotent_across_repeated_runs(tmp_path: Path) -> None:
    target = tmp_path / "lakehouse"
    first = _run_seeder("--target", str(target))
    assert first.returncode == 0
    first_catalog = DeltaTable(
        str(target / "Tables" / "silver_remediation_action_catalog")
    ).to_pyarrow_table().to_pylist()

    second = _run_seeder("--target", str(target))
    assert second.returncode == 0
    second_catalog = DeltaTable(
        str(target / "Tables" / "silver_remediation_action_catalog")
    ).to_pyarrow_table().to_pylist()

    assert len(first_catalog) == len(second_catalog)
    assert {row["action_id"] for row in first_catalog} == {
        row["action_id"] for row in second_catalog
    }


def test_seeder_validates_content_and_refuses_to_write_invalid_catalog(
    tmp_path: Path,
) -> None:
    target = tmp_path / "lakehouse"
    invalid_fixture = tmp_path / "invalid_catalog.json"
    invalid_fixture.write_text(
        json.dumps(
            {
                "action_catalog": [
                    {
                        "action_id": "bad-action",
                        "title": "Bad action",
                        "opportunity_type": "Test",
                        "trigger": {"any": []},
                        "execution_steps": [],
                        "preconditions": [],
                        "rollback_actions": [],
                        "success_criteria": [],
                        "failure_criteria": [],
                        "deployment_stages": [],
                        "effectiveness": {},
                    }
                ],
                "approval_policies": [],
            }
        )
    )

    result = _run_seeder(
        "--target", str(target), "--catalog", str(invalid_fixture)
    )

    assert result.returncode != 0
    assert not target.exists()


def test_seeder_module_reaches_no_cloud_sdk_and_spawns_no_process() -> None:
    source = SEEDER_PATH.read_text()
    assert "azure.mgmt" not in source
    assert "subprocess" not in source
