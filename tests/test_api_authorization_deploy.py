"""Executable tests for the guarded API authorization deployment workflow."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIGEST = f"sha256:{'a' * 64}"
API_IMAGE = f"registry.example/aiops-api@{API_DIGEST}"
SUBSCRIPTION_ID = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _deploy_workspace(tmp_path: Path, *, mode: str = "default") -> tuple[Path, dict[str, str]]:
    root = tmp_path / "deploy-workspace"
    scripts = root / "infra" / "scripts"
    terraform_dir = root / "infra" / "terraform"
    operations = root / "src" / "operations"
    fake_bin = root / "fake-bin"
    for directory in (scripts, terraform_dir / ".terraform", operations, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(REPO_ROOT / "infra" / "scripts" / "deploy.sh", scripts / "deploy.sh")
    for name in (
        "copilot_canary_authorization.v1.json",
        "copilot_default_authorization.v1.json",
    ):
        shutil.copy2(REPO_ROOT / "src" / "operations" / name, operations / name)
    (terraform_dir / "terraform.tfvars").write_text(
        "\n".join(
            (
                f'copilot_rollout_mode = "{mode}"',
                f'api_image_digest = "{API_DIGEST}"',
                "",
            )
        ),
        encoding="utf-8",
    )
    env_file = root / "deploy.env"
    env_file.write_text(
        "\n".join(
            (
                f"AZURE_SUBSCRIPTION_ID={SUBSCRIPTION_ID}",
                "AZURE_TENANT_ID=tenant",
                "AZURE_CLIENT_ID=client",
                "AZURE_CLIENT_SECRET=secret",
                "NEXT_PUBLIC_ENTRA_CLIENT_ID=web-client",
                "AIOPS_ENTRA_API_AUDIENCE=audience",
                'AIOPS_ENTRA_GRANTS_JSON={"principal":[]}',
                "",
            )
        ),
        encoding="utf-8",
    )
    state_file = root / "fake-state"
    apply_count_file = root / "fake-apply-count"
    log_file = root / "fake-terraform.log"
    state_file.write_text("compatibility", encoding="utf-8")
    apply_count_file.write_text("0", encoding="utf-8")

    _write_executable(
        fake_bin / "terraform",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        echo "$*" >>"${{FAKE_TERRAFORM_LOG}}"
        command="${{1:-}}"
        shift || true
        case "${{command}}" in
          apply)
            count="$(cat "${{FAKE_APPLY_COUNT}}")"
            count=$((count + 1))
            printf '%s' "${{count}}" >"${{FAKE_APPLY_COUNT}}"
            mode="$(
              awk -F'=' '/^[ \t]*copilot_rollout_mode[ \t]*=/ {{
                gsub(/[ \t"]/,"",$2); value=$2
              }} END {{ print value }}' terraform.tfvars
            )"
            for argument in "$@"; do
              case "${{argument}}" in
                -var=copilot_rollout_mode=*)
                  mode="${{argument#-var=copilot_rollout_mode=}}"
                  ;;
              esac
            done
            if [[ "${{FAKE_ROLLBACK_FAIL:-0}}" == "1" ]] &&
              [[ "${{count}}" -ge 3 ]] &&
              [[ "${{mode}}" == "compatibility" ]]; then
              exit 1
            fi
            printf '%s' "${{mode}}" >"${{FAKE_STATE}}"
            echo "state=${{mode}}" >>"${{FAKE_TERRAFORM_LOG}}"
            ;;
          output)
            if [[ "${{1:-}}" == "-raw" ]]; then
              case "${{2:-}}" in
                api_image) printf '%s\\n' "{API_IMAGE}" ;;
                resource_group_name) printf '%s\\n' "aiops-dev-rg" ;;
                api_app_name) printf '%s\\n' "aiops-dev-api" ;;
                container_registry) printf '%s\\n' "registry.example" ;;
              esac
            elif [[ "${{1:-}}" == "-json" ]] &&
              [[ "${{2:-}}" == "copilot_provider_environment" ]]; then
              mode="$(cat "${{FAKE_STATE}}")"
              output_mode="${{FAKE_OUTPUT_MODE:-${{mode}}}}"
              case "${{output_mode}}" in
                canary) percentage=10 ;;
                default) percentage=100 ;;
                *) percentage=0 ;;
              esac
              echo "output=${{output_mode}}/${{percentage}}" >>"${{FAKE_TERRAFORM_LOG}}"
              printf '{{"AIOPS_COPILOT_ROLLOUT_MODE":"%s","AIOPS_COPILOT_CANARY_PERCENTAGE":"%s","AIOPS_API_IMAGE_DIGEST":"{API_DIGEST}"}}\\n' \
                "${{output_mode}}" "${{percentage}}"
            fi
            ;;
          init) ;;
          *) exit 2 ;;
        esac
        """,
    )
    _write_executable(
        fake_bin / "az",
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        if [[ "$*" == *"containerapp show"* ]]; then
          printf '%s\\n' "/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/aiops-dev-rg/providers/Microsoft.App/containerApps/aiops-dev-api"
          exit 0
        fi
        if [[ "$*" == *"containerapp revision list"* ]]; then
          mode="$(cat "${{FAKE_STATE}}")"
          case "${{mode}}" in
            canary) percentage=10 ;;
            default) percentage=100 ;;
            *) percentage=0 ;;
          esac
          printf '[{{"name":"api--%s-r1","properties":{{"active":true,"healthState":"Healthy","template":{{"containers":[{{"image":"{API_IMAGE}","env":[{{"name":"AIOPS_COPILOT_ROLLOUT_MODE","value":"%s"}},{{"name":"AIOPS_COPILOT_CANARY_PERCENTAGE","value":"%s"}}]}}]}}}}}}]\\n' \
            "${{mode}}" "${{mode}}" "${{percentage}}"
          exit 0
        fi
        exit 2
        """,
    )
    _write_executable(
        fake_bin / "sleep",
        """
        #!/usr/bin/env bash
        exit 0
        """,
    )

    environment = os.environ.copy()
    for name in (
        "AIOPS_API_AUTHORIZATION_RELEASE",
        "TF_CLI_ARGS",
        "TF_CLI_ARGS_apply",
        "TF_CLI_ARGS_plan",
        "TF_CLI_ARGS_output",
        "TF_CLI_ARGS_init",
        "TF_VAR_copilot_rollout_mode",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "AIOPS_DEPLOYER_OBJECT_ID": "deployer",
            "AIOPS_ENV_FILE": str(env_file),
            "FAKE_STATE": str(state_file),
            "FAKE_APPLY_COUNT": str(apply_count_file),
            "FAKE_TERRAFORM_LOG": str(log_file),
        }
    )
    return scripts / "deploy.sh", environment


def _run_deploy(
    script: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), "apply", *arguments],
        cwd=script.parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_rollout_uses_staged_workflow_and_confirms_active_revision(
    tmp_path: Path,
) -> None:
    script, environment = _deploy_workspace(tmp_path)

    result = _run_deploy(
        script,
        environment,
        "-target=azurerm_container_app.api",
        "-auto-approve",
    )

    assert result.returncode == 0, "\n".join(
        (
            result.stderr,
            result.stdout,
            Path(environment["FAKE_TERRAFORM_LOG"]).read_text(encoding="utf-8"),
        )
    )
    assert "staging immutable API digest in compatibility mode" in result.stdout
    assert "active immutable API revision api--default-r1" in result.stdout


def test_canary_rollout_keeps_bounded_staged_semantics(tmp_path: Path) -> None:
    script, environment = _deploy_workspace(tmp_path, mode="canary")

    result = _run_deploy(
        script,
        environment,
        "-target=azurerm_container_app.api",
        "-auto-approve",
    )

    assert result.returncode == 0, "\n".join(
        (
            result.stderr,
            result.stdout,
            Path(environment["FAKE_TERRAFORM_LOG"]).read_text(encoding="utf-8"),
        )
    )
    assert "active immutable API revision api--canary-r1" in result.stdout
    assert "mode canary, percentage 10" in result.stdout


def test_default_rollout_cannot_bypass_staging_when_release_flag_is_omitted(
    tmp_path: Path,
) -> None:
    script, environment = _deploy_workspace(tmp_path, mode="compatibility")

    result = _run_deploy(
        script,
        environment,
        "-var=copilot_rollout_mode=default",
        "-auto-approve",
    )

    assert result.returncode != 0
    assert (
        "API authorization release requires exactly one Terraform target"
        in result.stderr
    )
    assert not Path(environment["FAKE_TERRAFORM_LOG"]).exists()


def test_authorized_rollout_fails_when_rollback_cannot_be_confirmed(
    tmp_path: Path,
) -> None:
    script, environment = _deploy_workspace(tmp_path)
    environment["FAKE_OUTPUT_MODE"] = "canary"
    environment["FAKE_ROLLBACK_FAIL"] = "1"

    result = _run_deploy(
        script,
        environment,
        "-target=azurerm_container_app.api",
        "-auto-approve",
    )

    assert result.returncode != 0
    assert "authorized rollout validation failed" in result.stderr
    assert "automatic compatibility hold could not be verified" in result.stderr
