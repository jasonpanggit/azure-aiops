"""Exercise the real opt-in pytest shard hooks in isolated subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def suite(tmp_path):
    (tmp_path / "conftest.py").write_text((ROOT / "tests/conftest.py").read_text())
    (tmp_path / "test_cases.py").write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('value', range(11))\n"
        "def test_case(value):\n"
        "    assert value != 7\n"
    )
    return tmp_path


def _run(suite, *args):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", *args],
        cwd=suite, capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
    )


def _cases(result):
    return [
        line for line in result.stdout.splitlines()
        if line.startswith("test_cases.py::")
    ]


def test_shards_cover_every_case_exactly_once_and_preserve_order(suite):
    baseline = _run(suite, "--collect-only")
    assert baseline.returncode == 0, baseline.stderr
    expected = _cases(baseline)
    assert len(expected) == 11
    collected = []
    for index in range(4):
        result = _run(
            suite, "--collect-only", "--ci-shard-index", str(index),
            "--ci-shard-count", "4",
        )
        assert result.returncode == 0, result.stderr
        cases = _cases(result)
        assert cases == expected[index::4]
        collected.extend(cases)
    assert sorted(collected) == sorted(expected)
    assert len(set(collected)) == len(expected)


@pytest.mark.parametrize("args", [
    ["--ci-shard-index", "0"],
    ["--ci-shard-count", "4"],
    ["--ci-shard-index", "-1", "--ci-shard-count", "4"],
    ["--ci-shard-index", "4", "--ci-shard-count", "4"],
    ["--ci-shard-index", "0", "--ci-shard-count", "0"],
])
def test_invalid_shard_settings_fail_before_tests(suite, args):
    result = _run(suite, *args)
    assert result.returncode == 4
    assert "must both be provided" in result.stderr
    assert "passed" not in result.stdout


def test_selected_failure_propagates_and_junit_is_written(suite):
    result = _run(
        suite, "--ci-shard-index", "3", "--ci-shard-count", "4",
        "--junitxml=results.xml",
    )
    assert result.returncode == 1
    assert "test_case[7]" in result.stdout
    assert (suite / "results.xml").is_file()


def test_unsharded_default_still_runs_the_whole_suite(suite):
    result = _run(suite)
    assert result.returncode == 1
    assert "1 failed, 10 passed" in result.stdout


def test_workflow_preserves_fail_closed_required_backend_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    tests = jobs["backend-tests"]
    assert tests["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    assert tests["strategy"]["fail-fast"] is False
    command = next(step["run"] for step in tests["steps"] if step.get("name") == "Run backend shard")
    assert "--ci-shard-count=4" in command
    assert "--ci-shard-index=${{ matrix.shard }}" in command
    assert "--durations=30" in command and "--junitxml=" in command
    gate = jobs["backend"]
    assert gate["if"] == "always()"
    assert gate["needs"] == "backend-tests"
    assert gate["steps"][0]["env"]["SHARD_RESULT"] == "${{ needs.backend-tests.result }}"
    assert gate["steps"][0]["run"] == 'test "$SHARD_RESULT" = success'
    assert not tests.get("continue-on-error", False)


@pytest.mark.parametrize("status", ["success", "failure", "cancelled", "skipped"])
def test_backend_gate_only_accepts_success(status):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    command = workflow["jobs"]["backend"]["steps"][0]["run"]
    result = subprocess.run(
        ["bash", "-c", command], env={**os.environ, "SHARD_RESULT": status},
        capture_output=True, check=False,
    )
    assert (result.returncode == 0) is (status == "success")
