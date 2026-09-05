"""Contract tests for the detached pre-Phase-12 compatibility recording."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.network_baseline import (
    BASELINE_PATH,
    BaselineArtifactMissingError,
    capture_default_responses,
    load_baseline,
    record_baseline,
)
from tests.network_scale_fixtures import g4_baseline_estate


def test_baseline_is_recorded_and_self_consistent(tmp_path: Path) -> None:
    baseline = load_baseline()
    replay = capture_default_responses(g4_baseline_estate())

    assert set(baseline["endpoints"]) == {"topology", "gaps", "rule_findings"}
    for endpoint, current in replay.items():
        recorded = baseline["endpoints"][endpoint]
        assert current["body"] == recorded["body"]
        assert current["byte_length"] == recorded["byte_length"]
        assert current["top_level_keys"] == recorded["top_level_keys"]
        assert current["representative_item_keys"] == recorded["representative_item_keys"]

    assert baseline["topology"]["node_count"] == len(
        json.loads(baseline["endpoints"]["topology"]["body"])["data"]["topology"]["resources"]
    )
    assert baseline["topology"]["edge_count"] == len(
        json.loads(baseline["endpoints"]["topology"]["body"])["data"]["topology"]["relationships"]
    )
    assert baseline["topology"]["collection_counts"]
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["phase_base_commit"])
    assert baseline["recording_environment"]["git_mode"] == "detached_worktree"
    assert (
        baseline["recording_environment"]["head_commit"]
        == baseline["phase_base_commit"]
    )
    assert isinstance(baseline["suite_pass_counts"]["backend"], int)
    assert isinstance(baseline["suite_pass_counts"]["web"], int)
    assert baseline["allowed_additive_nodes"] == []
    assert baseline["allowed_additive_keys"] == []

    copied = tmp_path / "baseline.json"
    reproduced = record_baseline(
        copied,
        phase_base_commit=baseline["phase_base_commit"],
        backend_pass_count=baseline["suite_pass_counts"]["backend"],
        web_pass_count=baseline["suite_pass_counts"]["web"],
        canvas_interactivity=baseline["canvas_interactivity"],
    )
    assert reproduced["endpoints"] == baseline["endpoints"]
    assert json.loads(copied.read_text()) == reproduced


def test_missing_baseline_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "not-recorded.json"

    with pytest.raises(BaselineArtifactMissingError, match="Pre-phase baseline artifact is missing"):
        load_baseline(missing)


def test_canvas_interactivity_ceiling_is_measured() -> None:
    measurement = load_baseline()["canvas_interactivity"]

    assert 0 < measurement["measured_ceiling_nodes"] <= 1_500
    assert measurement["threshold_ms"] > 0
    assert measurement["samples"]
    assert "vitest" in measurement["method"].casefold()
    assert "jsdom" in measurement["method"].casefold()
    assert measurement["machine"]
    assert measurement["enterprise_fixture_total_nodes"] == 34_600
    assert measurement["measured_sample_max_nodes"] == 1_500


def test_default_baseline_path_is_the_phase_artifact() -> None:
    assert BASELINE_PATH.as_posix().endswith(
        ".planning/phases/12-network-topology-integrity-and-scale/12-PRE-PHASE-BASELINE.json"
    )
