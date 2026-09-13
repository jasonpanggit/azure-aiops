from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "show-publication-progress.sh"

_FAKE_AZ = r"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
malformed = os.environ.get("FAKE_MALFORMED", "")

if args[:3] == ["containerapp", "job", "show"]:
    if malformed == "job":
        print("{not-json")
    else:
        print(json.dumps({
            "id": "",
            "properties": {
                "configuration": {"replicaTimeout": 3600},
                "environmentId": "",
                "workloadProfileName": "Consumption",
            },
        }))
elif args[:4] == ["containerapp", "job", "execution", "show"]:
    if malformed == "execution":
        print("{not-json")
    else:
        print(json.dumps({
            "properties": {
                "startTime": "2026-09-13T00:00:00Z",
                "status": "Running",
                "template": {
                    "containers": [{
                        "image": "example.invalid/publication:test",
                        "resources": {"cpu": 1, "memory": "2Gi"},
                    }],
                },
            },
        }))
elif args[:4] == ["containerapp", "job", "replica", "list"]:
    print(json.dumps([{
        "name": "replica-1",
        "properties": {
            "containers": [{
                "name": "publisher",
                "ready": True,
                "restartCount": 0,
                "runningState": "Running",
            }],
            "createdTime": "2026-09-13T00:00:01Z",
        },
    }]))
elif args[:4] == ["containerapp", "job", "logs", "show"]:
    event = {
        "checkpoint_bytes_written": 456,
        "checkpoint_id": "a" * 64,
        "checkpoint_rows_written": 123,
        "checkpoint_state": "persisted",
        "completed": 4,
        "elapsed_seconds": 12.5,
        "event": "activation_progress",
        "remaining_tables": 5,
        "stage": "table_publication",
        "status": "completed",
        "table_name": "bronze_resources",
        "total": 9,
    }
    message = "publication-event " + json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
    ) + " complete"
    print(json.dumps(
        {"TimeStamp": "2026-09-13T00:00:12Z", "Log": message},
        separators=(",", ":"),
    ))
else:
    print(json.dumps({}))
"""


def _run_monitor(tmp_path: Path, *, malformed: str = "") -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    az = fake_bin / "az"
    az.write_text(_FAKE_AZ, encoding="utf-8")
    az.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_MALFORMED": malformed,
        "TERM": "",
    }
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--once",
            "--execution",
            "execution-1",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=15,
    )


def test_monitor_parses_sorted_compact_embedded_progress_event(
    tmp_path: Path,
) -> None:
    result = _run_monitor(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Latest structured progress" in result.stdout
    assert "completed            4" in result.stdout
    assert f"checkpoint_id        {'a' * 64}" in result.stdout
    assert "checkpoint_rows_written 123" in result.stdout
    assert "checkpoint_bytes_written 456" in result.stdout


@pytest.mark.parametrize("malformed", ["job", "execution"])
def test_monitor_exits_nonzero_for_malformed_required_json(
    tmp_path: Path,
    malformed: str,
) -> None:
    result = _run_monitor(tmp_path, malformed=malformed)

    assert result.returncode != 0
    assert "Error: malformed job" in result.stderr
