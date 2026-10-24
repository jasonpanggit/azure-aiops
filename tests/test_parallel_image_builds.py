"""Exercise the release script with offline tools and real child processes."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {"aiops-api", "aiops-web", "mcp-server", "azure-mcp"}
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def release(tmp_path):
    repo = tmp_path / "repo"
    scripts = repo / "infra/scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "infra/scripts/build-and-push.sh", scripts)
    (repo / "infra/terraform").mkdir()
    tfvars = repo / "infra/terraform/terraform.tfvars"
    tfvars.write_text('image_tag = "old"\n')
    (repo / "web").mkdir()
    for filename in (
        "Dockerfile",
        "web/Dockerfile",
        "Dockerfile.mcp",
        "Dockerfile.azure-mcp",
    ):
        (repo / filename).write_text("FROM scratch\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    tools = tmp_path / "bin"
    tools.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    terraform = tools / "terraform"
    terraform.write_text("#!/bin/sh\nprintf 'test.azurecr.io\\n'\n")
    terraform.chmod(0o755)
    az = tools / "az"
    az.write_text(
        f"#!{sys.executable}\n"
        r"""
import json
import os
from pathlib import Path
import sys
import time

state = Path(os.environ["BUILD_TEST_STATE"])
args = sys.argv[1:]
def event(kind, image):
    with (state / "events").open("a") as stream:
        stream.write(json.dumps([kind, image]) + "\n")
if args[:3] == ["acr", "repository", "show"]:
    image = args[args.index("--image") + 1].split(":")[0]
    if os.environ.get("BUILD_TEST_EXISTING") == image:
        sys.exit(0)
    if not (state / (image + ".done")).exists():
        sys.exit(1)
    if os.environ.get("BUILD_TEST_MISSING") == image:
        sys.exit(1)
    event("verify", image)
    if "--output" in args:
        print(json.dumps({"name": "release-test", "digest": "sha256:" + "a" * 64}))
elif args[:2] == ["acr", "build"]:
    assert Path(args[args.index("--file") + 1]).is_file()
    image = args[args.index("--image") + 1].split(":")[0]
    event("start", image)
    # The first batch must actually overlap, not merely claim parallelism.
    expected = int(os.environ.get("BUILD_TEST_EXPECT_OVERLAP", "1"))
    if image in {"aiops-api", "aiops-web"}:
        deadline = time.monotonic() + 5
        while True:
            rows = [json.loads(line) for line in (state / "events").read_text().splitlines()]
            if sum(row[0] == "start" for row in rows) >= expected:
                break
            if time.monotonic() > deadline:
                event("timeout", image)
                sys.exit(8)
            time.sleep(.01)
    time.sleep(.05)
    assert Path(args[args.index("--file") + 1]).is_file()
    if os.environ.get("BUILD_TEST_FAIL") == image:
        event("fail", image)
        sys.exit(7)
    (state / (image + ".done")).touch()
    event("finish", image)
else:
    sys.exit("Unexpected az command: " + repr(args))
"""
    )
    az.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "BUILD_TEST_STATE": str(state),
        "AIOPS_ENV_FILE": str(tmp_path / "absent"),
        "AIOPS_BUILD_MODE": "acr",
        "AIOPS_BUILD_PARALLELISM": "2",
        "NEXT_PUBLIC_ENTRA_CLIENT_ID": "test-client",
        "NEXT_PUBLIC_ENTRA_TENANT_ID": "test-tenant",
        "NEXT_PUBLIC_ENTRA_API_SCOPE": "api://test/access",
    }

    def run(extra_env=None, flags=()):
        result = subprocess.run(
            ["bash", str(scripts / "build-and-push.sh"), "release-test", *flags],
            cwd=repo,
            env={**env, **(extra_env or {})},
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        events = state / "events"
        rows = (
            [json.loads(line) for line in events.read_text().splitlines()]
            if events.exists()
            else []
        )
        assert not list(repo.glob(".acr-build-context.*"))
        return result, rows, tfvars.read_text()

    return run


@pytest.mark.parametrize("parallelism", [1, 2, 3, 4])
def test_builds_overlap_within_bound_before_recording_release(release, parallelism):
    result, events, tfvars = release(
        {
            "AIOPS_BUILD_PARALLELISM": str(parallelism),
            "BUILD_TEST_EXPECT_OVERLAP": str(parallelism),
        }
    )
    assert result.returncode == 0, result.stderr
    active, peak = set(), 0
    for kind, image in events:
        if kind == "start":
            active.add(image)
            peak = max(peak, len(active))
        elif kind == "finish":
            active.remove(image)
    assert not active
    assert peak == parallelism
    assert {image for kind, image in events if kind == "finish"} == IMAGES
    assert {image for kind, image in events if kind == "verify"} == IMAGES
    assert events.index(["verify", "aiops-api"]) > max(
        i for i, row in enumerate(events) if row[0] == "finish"
    )
    assert 'image_tag     = "release-test"' in tfvars
    assert DIGEST in tfvars


def test_failed_batch_joins_siblings_without_recording_or_next_batch(release):
    result, events, tfvars = release(
        {
            "BUILD_TEST_FAIL": "aiops-api",
            "BUILD_TEST_EXPECT_OVERLAP": "2",
        },
        flags=("--deploy",),
    )
    assert result.returncode != 0
    assert ["finish", "aiops-web"] in events
    assert {image for kind, image in events if kind == "start"} == {
        "aiops-api",
        "aiops-web",
    }
    assert not any(kind == "verify" for kind, _ in events)
    assert tfvars == 'image_tag = "old"\n'
    assert "NOT recording or deploying" in result.stderr


def test_missing_manifest_does_not_record_release(release):
    result, _, tfvars = release({"BUILD_TEST_MISSING": "azure-mcp"})
    assert result.returncode != 0
    assert tfvars == 'image_tag = "old"\n'
    assert "tag is incomplete" in result.stderr


def test_authorization_release_stays_api_only(release):
    result, events, tfvars = release(flags=("--api-authorization-release",))
    assert result.returncode == 0, result.stderr
    assert {image for _, image in events} == {"aiops-api"}
    assert 'image_tag = "old"' in tfvars
    assert DIGEST in tfvars


def test_existing_api_tag_is_not_overwritten(release):
    result, events, tfvars = release({"BUILD_TEST_EXISTING": "aiops-api"})
    assert result.returncode != 0
    assert ["start", "aiops-api"] not in events
    assert tfvars == 'image_tag = "old"\n'
    assert "refusing to reuse existing API tag" in result.stderr


@pytest.mark.parametrize("value", ["0", "5", "-1", "two", "2;exit 0"])
def test_invalid_parallelism_is_rejected(release, value):
    result, events, tfvars = release({"AIOPS_BUILD_PARALLELISM": value})
    assert result.returncode == 2
    assert not events
    assert tfvars == 'image_tag = "old"\n'
