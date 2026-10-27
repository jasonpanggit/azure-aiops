"""Offline contract tests for the Bash platform setup entry point."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path):
    root = tmp_path / "checkout with spaces"
    scripts = root / "infra/scripts"
    scripts.mkdir(parents=True)
    script = scripts / "setup-platform.sh"
    shutil.copyfile(ROOT / "infra/scripts/setup-platform.sh", script)
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.touch(mode=0o700)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n"
        "sys.exit(int(os.environ.get('TEST_UV_EXIT', '0')))\n"
    )
    uv.chmod(0o700)
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return root, script, environment


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--help"],
        ["--apply", "--env-file", "/secure/a file.env", "--stage", "fabric"],
    ],
)
def test_launcher_preserves_arguments_and_uses_checkout(launcher, tmp_path, arguments):
    root, script, environment = launcher
    result = subprocess.run(
        ["bash", str(script), *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["cwd"] == str(root)
    assert payload["args"] == [
        "run",
        "--no-sync",
        "python",
        str(root / "infra/scripts/setup-platform.py"),
        *arguments,
    ]


def test_launcher_preserves_failure_status(launcher):
    _, script, environment = launcher
    result = subprocess.run(
        ["bash", str(script)],
        env={**environment, "TEST_UV_EXIT": "23"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 23


def test_launcher_missing_dependencies_is_actionable(launcher):
    root, script, environment = launcher
    (root / ".venv/bin/python").unlink()
    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "uv sync --locked --extra api --extra test" in result.stderr
    assert not result.stdout


def test_launcher_missing_uv_is_actionable(launcher, tmp_path):
    _, script, environment = launcher
    bin_dir = tmp_path / "without-uv"
    bin_dir.mkdir()
    (bin_dir / "dirname").symlink_to(shutil.which("dirname"))
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env={**environment, "PATH": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 127
    assert "uv is required" in result.stderr
