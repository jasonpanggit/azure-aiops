from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404
from pathlib import Path


def build_aiops_cron_command(schedule: str, script_name: str, workdir: str) -> list[str]:
    return [
        "aiops",
        "cron",
        "create",
        schedule,
        "",
        "--name",
        "azure-resource-graph-sync",
        "--script",
        script_name,
        "--no-agent",
        "--workdir",
        workdir,
        "--deliver",
        "local",
    ]


def install_schedule(schedule: str, config_path: Path, workdir: Path) -> list[str]:
    aiops_home = Path(os.environ.get("AIOPS_HOME") or Path.home() / ".aiops")
    scripts = aiops_home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script_name = "azure-resource-graph-sync.sh"
    script_path = scripts / script_name
    content = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"cd {shlex.quote(str(workdir))}\n"
        f"uv run aiops-inventory sync --config {shlex.quote(str(config_path))}\n"
    )
    temporary = script_path.with_suffix(".tmp")
    temporary.write_text(content)
    temporary.chmod(0o700)
    temporary.replace(script_path)
    command = build_aiops_cron_command(schedule, script_name, str(workdir))
    # Safe: command is an internal argv list, never shell text.
    completed = subprocess.run(command, check=False)  # nosec B603
    if completed.returncode:
        raise RuntimeError(f"aiops cron create failed with exit code {completed.returncode}")
    return command
