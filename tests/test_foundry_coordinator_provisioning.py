"""Coordinator provisioning remains safe in both restored and existing projects."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_foundry_coordinator", ROOT / "scripts/validate_foundry_coordinator.py"
)
assert SPEC is not None and SPEC.loader is not None
coordinator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coordinator)


def test_prompt_runtime_role_grants_only_project_reads_and_response_execution():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    role = terraform.split(
        'resource "azurerm_role_definition" "apps_foundry_prompt_runtime" {', 1
    )[1].split('\nresource ', 1)[0]
    permissions = re.search(r"data_actions\s*=\s*\[(.*?)\]", role, re.DOTALL)
    assert permissions is not None
    assert re.findall(r'"([^"]+)"', permissions[1]) == [
        "Microsoft.CognitiveServices/accounts/AIServices/agents/read",
        "Microsoft.CognitiveServices/accounts/AIServices/deployments/read",
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/read",
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/write",
    ]
    actions = re.search(r"(?<!data_)actions\s*=\s*\[(.*?)\]", role, re.DOTALL)
    assert actions is not None
    assert re.findall(r'"([^"]+)"', actions[1]) == [
        "Microsoft.CognitiveServices/accounts/projects/read",
    ]
    assert re.search(r"\n\s+not_actions\s*=\s*\[\]", role)
    assert re.search(r"\n\s+not_data_actions\s*=\s*\[\]", role)
    assert "assignable_scopes = [azurerm_resource_group.main.id]" in role
    assert "var.enable_role_assignments || var.enable_foundry_role_assignments" in role


def test_prompt_runtime_assignment_is_limited_to_project_and_api_identity():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    assignment = terraform.split(
        'resource "azurerm_role_assignment" "apps_foundry_prompt_runtime" {', 1
    )[1].split('\nresource ', 1)[0]
    assert re.search(
        r"scope\s*=\s*azurerm_cognitive_account_project\.ops\.id", assignment
    )
    assert re.search(
        r"principal_id\s*=\s*azurerm_user_assigned_identity\.apps\.principal_id",
        assignment,
    )
    assert (
        "azurerm_role_definition.apps_foundry_prompt_runtime[0].role_definition_resource_id"
        in assignment
    )
    assert "var.enable_role_assignments || var.enable_foundry_role_assignments" in assignment


def test_response_runtime_role_grants_only_account_read_and_response_execution():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    role = terraform.split(
        'resource "azurerm_role_definition" "apps_foundry_response_runtime" {', 1
    )[1].split('\nresource ', 1)[0]
    permissions = re.search(r"data_actions\s*=\s*\[(.*?)\]", role, re.DOTALL)
    assert permissions is not None
    assert re.findall(r'"([^"]+)"', permissions[1]) == [
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/read",
        "Microsoft.CognitiveServices/accounts/OpenAI/responses/write",
    ]
    actions = re.search(r"(?<!data_)actions\s*=\s*\[(.*?)\]", role, re.DOTALL)
    assert actions is not None
    assert re.findall(r'"([^"]+)"', actions[1]) == [
        "Microsoft.CognitiveServices/accounts/read",
    ]
    assert re.search(r"\n\s+not_actions\s*=\s*\[\]", role)
    assert re.search(r"\n\s+not_data_actions\s*=\s*\[\]", role)
    assert "assignable_scopes = [azurerm_resource_group.main.id]" in role
    assert "var.enable_role_assignments || var.enable_foundry_role_assignments" in role


def test_response_runtime_assignment_is_limited_to_account_and_api_identity():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    assignment = terraform.split(
        'resource "azurerm_role_assignment" "apps_foundry_response_runtime" {', 1
    )[1].split('\nresource ', 1)[0]
    assert re.search(
        r"scope\s*=\s*azurerm_cognitive_account\.foundry\.id", assignment
    )
    assert re.search(
        r"principal_id\s*=\s*azurerm_user_assigned_identity\.apps\.principal_id",
        assignment,
    )
    assert (
        "azurerm_role_definition.apps_foundry_response_runtime[0].role_definition_resource_id"
        in assignment
    )
    assert "var.enable_role_assignments || var.enable_foundry_role_assignments" in assignment


def test_cli_auth_does_not_require_or_use_client_secret(monkeypatch):
    monkeypatch.setenv("FOUNDRY_AUTH_MODE", "azure_cli")
    monkeypatch.delenv("AZURE_CLIENT_SECRET", raising=False)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "token\n", ""))
    monkeypatch.setattr(coordinator.subprocess, "run", run)
    assert coordinator._token() == "token"
    assert run.call_args.args[0] == [
        "az", "account", "get-access-token",
        "--scope", "https://ai.azure.com/.default",
        "--query", "accessToken", "--output", "tsv",
    ]


@pytest.mark.parametrize("status,stdout", [(1, "token"), (0, ""), (0, " \n")])
def test_cli_auth_failures_fail_closed(monkeypatch, status, stdout):
    monkeypatch.setenv("FOUNDRY_AUTH_MODE", "azure_cli")
    monkeypatch.setattr(
        coordinator.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], status, stdout, "private error")),
    )
    with pytest.raises(RuntimeError, match="Azure CLI Foundry token acquisition failed"):
        coordinator._token()


def test_unknown_auth_mode_fails_before_io(monkeypatch):
    monkeypatch.setenv("FOUNDRY_AUTH_MODE", "unknown")
    with pytest.raises(ValueError, match="Unsupported Foundry authentication mode"):
        coordinator._token()


def test_client_credentials_are_still_supported(monkeypatch):
    monkeypatch.delenv("FOUNDRY_AUTH_MODE", raising=False)
    monkeypatch.setenv("AZURE_CLIENT_ID", "client")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"access_token":"token"}'
    request = Mock(return_value=response)
    monkeypatch.setattr(coordinator.urllib.request, "urlopen", request)
    assert coordinator._token() == "token"
    assert b"scope=https%3A%2F%2Fai.azure.com%2F.default" in request.call_args.args[0].data


def _arguments(tmp_path, version, rejected=None):
    args = [
        "validate_foundry_coordinator.py",
        "--endpoint", "https://example.services.ai.azure.com/api/projects/restored",
        "--agent-name", "coordinator",
        "--provider-version-id", version,
        "--expected-model", "model",
        "--manifest-digest", "manifest",
        "--out", str(tmp_path / "activation.json"),
    ]
    if rejected is not None:
        args += ["--rejected-versions-json", json.dumps(rejected)]
    return args


@pytest.mark.parametrize(
    "version,rejected",
    [("1", None), ("5", ["5"]), ("coordinator:2", None), ("", [])],
)
def test_rejected_version_never_reaches_foundry(monkeypatch, tmp_path, version, rejected):
    monkeypatch.setattr(sys, "argv", _arguments(tmp_path, version, rejected))
    token = Mock()
    monkeypatch.setattr(coordinator, "_token", token)
    with pytest.raises(ValueError, match="empty or explicitly rejected"):
        coordinator.main()
    token.assert_not_called()
    assert not (tmp_path / "activation.json").exists()


@pytest.mark.parametrize("rejected", ["1", [1], [""], ["1", "1"], [False], {}])
def test_invalid_version_history_fails_before_io(monkeypatch, tmp_path, rejected):
    monkeypatch.setattr(sys, "argv", _arguments(tmp_path, "5", rejected))
    token = Mock()
    monkeypatch.setattr(coordinator, "_token", token)
    with pytest.raises(ValueError, match="distinct nonempty strings"):
        coordinator.main()
    token.assert_not_called()


@pytest.mark.parametrize("version,rejected", [("1", []), ("5", None)])
def test_live_probes_bind_actual_version_and_reviewed_history(
    monkeypatch, tmp_path, version, rejected
):
    monkeypatch.setattr(sys, "argv", _arguments(tmp_path, version, rejected))
    monkeypatch.setattr(coordinator, "_token", lambda: "token")
    plan = {
        "steps": [{
            "specialist_id": "network",
            "tool_calls": [{
                "tool": "firewall_nsg_gaps",
                "arguments": {"category": "firewall_bypass"},
                "citation_ids": ["snapshot:coverage"],
                "mutation": False,
            }],
            "depends_on": [],
        }],
        "estimated_tokens": 0,
        "max_wall_seconds": 30,
        "mutation_intent": False,
    }
    request = Mock(side_effect=[
        {
            "status": "active", "name": "coordinator", "version": version,
            "definition": {"model": "model"},
        },
        {"output_text": json.dumps(plan)},
        {"output_text": "synthesis"},
    ])
    monkeypatch.setattr(coordinator, "_request_json", request)
    monkeypatch.setattr(
        coordinator, "validate_executive_synthesis",
        lambda *args, **kwargs: [{
            "evidence_refs": ["tool:coordinator-validation:0"],
            "summary": "The payments subnet bypasses inspection.",
        }],
    )
    assert coordinator.main() == 0
    artifact = json.loads((tmp_path / "activation.json").read_text())
    assert artifact["provider_version_id"] == version
    assert artifact["supersedes_unusable_versions"] == (
        ["1", "2", "3", "4"] if rejected is None else rejected
    )
    digest = artifact.pop("validation_digest")
    assert digest == coordinator._validation_digest(artifact)
    for call in request.call_args_list[1:]:
        assert call.kwargs["payload"]["agent_reference"]["version"] == version


def test_terraform_binds_configured_rejections_to_publish_and_activation():
    terraform = (ROOT / "infra/terraform/foundry.tf").read_text()
    assert "FOUNDRY_COORDINATOR_REJECTED_VERSIONS_JSON" in terraform
    assert "!contains(var.foundry_coordinator_rejected_versions," in terraform
    assert (
        "try(tolist(local.foundry_coordinator_artifact.supersedes_unusable_versions), null)"
        " == var.foundry_coordinator_rejected_versions"
    ) in terraform
