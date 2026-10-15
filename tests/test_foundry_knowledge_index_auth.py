from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra/scripts/create-foundry-knowledge-index.sh"


@pytest.fixture
def auth_env(tmp_path: Path) -> dict[str, str]:
    tools = tmp_path / "bin"
    tools.mkdir()
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, body in {
        "az": (
            '#!/bin/sh\nprintf "az %s\\n" "$*" >> "$AUTH_CALLS"\n'
            'if [ "${FAIL_AUTH:-}" = 1 ]; then exit 17; fi\n'
            'if [ "${EMPTY_AUTH:-}" != 1 ]; then printf "example-token\\n"; fi\n'
        ),
        "curl": (
            '#!/bin/sh\nprintf "curl %s" "$*" | tr "\\n" " " >> "$AUTH_CALLS"\n'
            'printf "\\n" >> "$AUTH_CALLS"\n'
            'printf \'{"access_token":"example-token"}\\n\'\n'
        ),
    }.items():
        executable = tools / name
        executable.write_text(body)
        executable.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
        "AUTH_CALLS": str(tmp_path / "calls"),
        "SEARCH_SERVICE_NAME": "example-search",
        "SEARCH_INDEX_NAME": "example-index",
        "KNOWLEDGE_DOCS_DIR": str(docs),
        "FOUNDRY_OPENAI_ENDPOINT": "https://example.openai.azure.com",
        "FOUNDRY_EMBEDDING_MODEL": "text-embedding-3-small",
        "FOUNDRY_AUTH_MODE": "azure_cli",
        "AZURE_TENANT_ID": "",
        "AZURE_CLIENT_ID": "",
        "AZURE_CLIENT_SECRET": "",
    }


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def test_cli_auth_uses_distinct_audiences_without_client_credentials(auth_env):
    result = _run(auth_env)
    assert result.returncode == 0, result.stderr
    calls = Path(auth_env["AUTH_CALLS"]).read_text().splitlines()
    assert calls[0] == (
        "az account get-access-token --resource https://search.azure.com "
        "--query accessToken --output tsv"
    )
    assert calls[1] == (
        "az account get-access-token --resource https://cognitiveservices.azure.com "
        "--query accessToken --output tsv"
    )
    assert len(calls) == 3
    assert calls[2].startswith("curl -sS --fail-with-body -X PUT ")


@pytest.mark.parametrize("setting", ["FAIL_AUTH", "EMPTY_AUTH"])
def test_cli_auth_failure_never_calls_search(auth_env, setting):
    auth_env[setting] = "1"
    result = _run(auth_env)
    assert result.returncode != 0
    assert "curl " not in Path(auth_env["AUTH_CALLS"]).read_text()


@pytest.mark.parametrize("mode", ["client_credentials", "unknown"])
def test_invalid_auth_fails_before_provider_io(auth_env, mode):
    auth_env["FOUNDRY_AUTH_MODE"] = mode
    result = _run(auth_env)
    assert result.returncode != 0
    assert not Path(auth_env["AUTH_CALLS"]).exists()


def test_client_credentials_remain_supported(auth_env):
    auth_env.update(
        FOUNDRY_AUTH_MODE="client_credentials",
        AZURE_TENANT_ID="example-tenant",
        AZURE_CLIENT_ID="example-client",
        AZURE_CLIENT_SECRET="example-secret",
    )
    result = _run(auth_env)
    assert result.returncode == 0, result.stderr
    calls = Path(auth_env["AUTH_CALLS"]).read_text()
    assert "az account" not in calls
    assert "scope=https://search.azure.com/.default" in calls
    assert "scope=https://cognitiveservices.azure.com/.default" in calls


def test_terraform_wires_auth_mode_to_every_foundry_provisioner():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    assert 'var.client_id == "" ? "azure_cli" : "client_credentials"' in terraform
    assert len(
        re.findall(
            r"FOUNDRY_AUTH_MODE\s*=\s*local\.foundry_deployment_auth_mode", terraform
        )
    ) == 4
