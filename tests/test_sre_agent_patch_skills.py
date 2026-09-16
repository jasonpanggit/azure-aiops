"""Offline contracts for the two reviewed SRE Agent patch skills."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import scripts.preflight_sre_agent_patch_execution as preflight
from src.operations.patching.sre_agent_adapter import (
    SRE_PATCH_READ_SKILL_SHA256,
    SRE_PATCH_WRITE_SKILL_SHA256,
    sre_agent_patch_envelope_contract,
)

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "infra/sre-agent/skills"
READ_SKILL = SKILLS / "aiops-read-patch-applicability-v1/SKILL.md"
WRITE_SKILL = SKILLS / "aiops-install-selected-patches-v1/SKILL.md"
TRIGGER = ROOT / "infra/sre-agent/patch-trigger.v1.json"


def test_exactly_two_versioned_skill_builder_files_are_bound_by_raw_hash() -> None:
    assert sorted(SKILLS.glob("*/SKILL.md")) == sorted([READ_SKILL, WRITE_SKILL])
    assert hashlib.sha256(READ_SKILL.read_bytes()).hexdigest() == (
        SRE_PATCH_READ_SKILL_SHA256
    )
    assert hashlib.sha256(WRITE_SKILL.read_bytes()).hexdigest() == (
        SRE_PATCH_WRITE_SKILL_SHA256
    )

    definition = json.loads(TRIGGER.read_text(encoding="utf-8"))
    assert definition["skills"] == definition["payloadSchema"]["properties"][
        "skill_chain"
    ]["const"]
    assert definition["skills"]["sequence"] == ["read", "write"]
    assert definition["skills"]["read"]["tools"] == ["RunAzCliReadCommands"]
    assert definition["skills"]["write"]["tools"] == ["RunAzCliWriteCommands"]


def test_read_skill_is_one_fixed_bounded_arg_query() -> None:
    text = READ_SKILL.read_text(encoding="utf-8")
    assert text.count("az graph query --graph-query") == 1
    assert "--first 257" in text
    assert "patchassessmentresources" in text
    assert "where tolower(id) endswith '/patchassessmentresults/latest'" in text
    assert "where name =~ 'latest'" not in text
    assert "maximum_age_seconds = 86400" in text
    assert "child_activity_id != assessment_activity_id" in text
    assert "child_last_modified_at != assessment_last_modified_at" in text
    assert "approved_patch_id in~ ({{approved_patch_ids_kql}})" in text
    assert "{{target_resource_type}}" in text
    assert "\nlet " not in text
    assert "materialize(" not in text
    assert "\nprint " not in text
    assert "$left" not in text
    assert "$right" not in text
    assert "target_join_id = tolower" in text
    assert "child_activity_count > 1 or isnotempty(child_activity_id)" in text
    assert "`skip_token` to be null or empty" in text
    assert "zero count" in text
    assert "`blocked_patch_not_applicable`" in text
    assert "properties.extended.instanceView.powerState.code" in text
    assert "blocked_target_not_running" in text
    assert "reboot_pending = tobool(properties.rebootPending)" in text
    assert "blocked_reboot_pending" in text
    assert "blocked_patch_not_applicable" in text
    assert "RunAzCliWriteCommands" in text
    assert "Do not use `RunAzCliWriteCommands`" in text


def test_write_skill_routes_exact_vm_and_arc_commands() -> None:
    text = WRITE_SKILL.read_text(encoding="utf-8")
    vm = (
        "az vm install-patches --ids <target_id> --kb-numbers-to-include "
        "<exact IDs> --maximum-duration PT2H --reboot-setting IfRequired --no-wait"
    )
    arc = (
        "az connectedmachine install-patches --ids <target_id> "
        "--windows-parameters "
        """'{"kbNumbersToInclude":[...]}' """
        "--maximum-duration PT2H --reboot-setting IfRequired --no-wait true"
    )
    assert text.count(vm) == 1
    assert text.count(arc) == 1
    assert "Present exactly one command in Review mode" in text
    assert "no more than 300 seconds" in text
    assert "`vm_power_state=PowerState/running` immediately before Review" in text
    assert "`reboot_pending=false`" in text
    assert "never auto-started" in text
    assert "classification filter" in text
    assert "fallback" in text
    assert "retry" in text


def test_executable_artifacts_are_generic_and_have_no_demo_target_literals() -> None:
    paths = [READ_SKILL, WRITE_SKILL, TRIGGER]
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        assert "vm1" not in text
        assert "aiops-demo-rg" not in text


def test_envelope_accepts_both_exact_target_kinds_and_binds_review_contract() -> None:
    contract = sre_agent_patch_envelope_contract()
    properties = contract["properties"]
    assert properties["target_kind"] == {
        "enum": ["Azure VM", "Arc-enabled server"]
    }
    assert properties["reboot_setting"] == {"const": "IfRequired"}
    chain = properties["skill_chain"]["const"]
    assert chain["read"]["maximum_rows"] == 257
    assert chain["read"]["maximum_age"] == "PT24H"
    assert chain["write"]["required_read_evidence_maximum_age"] == "PT5M"
    assert chain["write"]["review_command_count"] == 1

    definition = json.loads(TRIGGER.read_text(encoding="utf-8"))
    assert definition["runMode"] == "Review"
    assert definition["payloadSchema"] == contract


@pytest.mark.parametrize(
    ("artifact", "old", "new", "hash_attribute"),
    [
        (
            READ_SKILL,
            "Require schema version `1.1`, operation `install_patches`",
            "Require schema version `1.4`, operation `applicability_check`",
            "PATCH_READ_SKILL_SHA256",
        ),
        (
            WRITE_SKILL,
            "Require schema version `1.1`, operation `install_patches`",
            "Require schema version `1.0`, operation `install_selected_patches`",
            "PATCH_WRITE_SKILL_SHA256",
        ),
    ],
)
def test_skill_input_contract_drift_fails_even_when_artifact_is_rehashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: Path,
    old: str,
    new: str,
    hash_attribute: str,
) -> None:
    drifted_dir = tmp_path / artifact.parent.name
    drifted_dir.mkdir()
    drifted = drifted_dir / "SKILL.md"
    drifted.write_text(
        artifact.read_text(encoding="utf-8").replace(old, new, 1),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        preflight,
        hash_attribute,
        hashlib.sha256(drifted.read_bytes()).hexdigest(),
    )

    with pytest.raises(preflight.ReadinessError, match="input contract"):
        preflight.canonical_skill_builder_artifact(drifted)


@pytest.mark.parametrize(
    ("artifact", "old", "new"),
    [
        (READ_SKILL, "--first 257", "--first 1000"),
        (READ_SKILL, "PT24H", "PT48H"),
        (WRITE_SKILL, "PT2H", "PT4H"),
        (WRITE_SKILL, "RunAzCliWriteCommands", "RunAzCliReadCommands"),
    ],
)
def test_skill_hash_or_instruction_drift_fails_closed(
    tmp_path: Path,
    artifact: Path,
    old: str,
    new: str,
) -> None:
    drifted_dir = tmp_path / artifact.parent.name
    drifted_dir.mkdir()
    drifted = drifted_dir / "SKILL.md"
    drifted.write_text(
        artifact.read_text(encoding="utf-8").replace(old, new, 1),
        encoding="utf-8",
    )

    with pytest.raises(preflight.ReadinessError, match="hash drift"):
        preflight.canonical_skill_builder_artifact(drifted)


def test_canonical_trigger_skill_drift_fails_before_offline_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = json.loads(TRIGGER.read_text(encoding="utf-8"))
    drifted = copy.deepcopy(definition)
    drifted["skills"]["write"]["tools"] = ["RunAzCliReadCommands"]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline validation must not spawn subprocesses")
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_http_requester",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline validation must not use the network")
        ),
    )

    with pytest.raises(preflight.ReadinessError, match="skills"):
        preflight.canonical_trigger_body(drifted)
