"""Exercise opt-in identity staging without providers, state, or live tokens."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import HeaderPrincipalAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer
from api.runtime import _gateway_grants
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.specialist_manifest import load_specialist_manifest

ROOT = Path(__file__).resolve().parents[1]
TF = ROOT / "infra/terraform"
PROJECT = "11111111-2222-3333-4444-555555555555"
SUB = "11111111-1111-1111-1111-111111111111"
IDS = {
    specialist.id: f"abcdef00-0000-0000-0000-{index:012d}"
    for index, specialist in enumerate(load_specialist_manifest().specialists, 1)
}


def _render(tmp_path, **values):
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("Terraform CLI is required for executable HCL regression")
    source = (TF / "foundry_specialist_identity.tf").read_text()
    preconditions = re.findall(
        r"precondition\s*{\s*condition\s*=\s*(.*?)\s*error_message\s*=",
        source,
        re.DOTALL,
    )
    assert len(preconditions) == 3
    source = source.split('\nresource "azapi_resource"', 1)[0]
    for original, value in {
        "azurerm_cognitive_account_project.ops.identity[0].principal_id": PROJECT,
        "azapi_resource.foundry_specialist_identity_mcp_connection[0].id": "candidate-connection",
        "azapi_resource.foundry_mcp_connection[0].id": "shared-connection",
    }.items():
        assert original in source
        source = source.replace(original, json.dumps(value))
    (tmp_path / "main.tf").write_text(source)
    manifest_path = ROOT / "src/operations/specialists.v1.json"
    (tmp_path / "context.tf").write_text(
        'variable "enable_apim" { default = true }\n'
        'variable "entra_grants_json" { default = "{}" }\n'
        f'variable "subscriptions" {{ default = ["{SUB}"] }}\n'
        "locals {\n"
        "  azure_mcp_subscriptions = toset(var.subscriptions)\n"
        "  specialists_by_id = { for s in "
        f"jsondecode(file({json.dumps(str(manifest_path))})).specialists : s.id => s }}\n"
        "}\n"
    )
    (tmp_path / "inputs.tfvars.json").write_text(json.dumps(values))
    expression = (
        "jsonencode({ grants = local.foundry_specialist_identity_grants, "
        "connection = local.foundry_candidate_mcp_connection_id, "
        f"guards = [{', '.join(preconditions)}] }})"
    )
    result = subprocess.run(
        [terraform, "console", "-no-color", "-var-file=inputs.tfvars.json"],
        cwd=tmp_path, input=expression + "\n", capture_output=True, text=True,
        timeout=30, check=False,
    )
    return result


def _rendered(tmp_path, **values):
    result = _render(tmp_path, **values)
    assert result.returncode == 0, result.stderr
    return json.loads(json.loads(result.stdout))


def test_default_preserves_shared_connection_and_adds_no_grants(tmp_path):
    result = _rendered(tmp_path)
    assert result["grants"] == {}
    assert result["connection"] == "shared-connection"


def test_opt_in_renders_twelve_distinct_scope_bound_reader_grants(tmp_path):
    result = _rendered(
        tmp_path, enable_foundry_specialist_identity_candidate=True,
        foundry_specialist_identity_principal_ids=IDS,
    )
    assert result["guards"] == [True, True, True]
    assert result["connection"] == "candidate-connection"
    assert result["grants"] == {
        principal: [{
            "role": "reader", "scope": {"subscription": [SUB]},
            "mcp_specialist_id": specialist,
        }]
        for specialist, principal in IDS.items()
    }


@pytest.mark.parametrize(
    ("overrides", "guard"),
    [
        ({"foundry_specialist_identity_principal_ids": {}}, 1),
        ({"foundry_specialist_identity_principal_ids": {k: v for k, v in IDS.items() if k != "finops"}}, 1),
        ({"foundry_specialist_identity_principal_ids": {**IDS, "unknown": "abcdef00-0000-0000-0000-000000000099"}}, 1),
        ({"foundry_specialist_identity_principal_ids": {**IDS, "network": PROJECT}}, 2),
        ({"entra_grants_json": json.dumps({IDS["network"].upper(): [{"role": "admin"}]})}, 2),
        ({"subscriptions": []}, 0),
        ({"enable_apim": False}, 0),
    ],
)
def test_staging_rejects_unscoped_incomplete_or_colliding_mapping(tmp_path, overrides, guard):
    values = {
        "enable_foundry_specialist_identity_candidate": True,
        "foundry_specialist_identity_principal_ids": IDS,
        **overrides,
    }
    assert _rendered(tmp_path, **values)["guards"][guard] is False


@pytest.mark.parametrize("principal", ["not-an-id", "00000000-0000-0000-0000-000000000000"])
def test_invalid_principal_uuid_fails_variable_validation(tmp_path, principal):
    result = _render(
        tmp_path, foundry_specialist_identity_principal_ids={**IDS, "network": principal},
    )
    assert result.returncode != 0
    assert "Specialist instance principals must be nonzero object UUIDs" in result.stderr


def test_case_variant_duplicate_subject_fails_variable_validation(tmp_path):
    result = _render(
        tmp_path,
        foundry_specialist_identity_principal_ids={**IDS, "finops": IDS["network"].upper()},
    )
    assert result.returncode != 0
    assert "Each specialist must have a distinct instance principal" in result.stderr


def test_candidate_connection_is_wired_without_switching_curator_or_shared_connection():
    source = (TF / "foundry.tf").read_text()
    specialists = source.split("foundry_specialists_json = jsonencode(", 1)[1].split(
        "\n  # Ontology", 1
    )[0]
    assert "project_connection_id = local.foundry_candidate_mcp_connection_id" in specialists
    assert re.search(
        r"FOUNDRY_OPERATIONS_MCP_CONNECTION_ID\s*=\s*\(\s*local.foundry_candidate_mcp_connection_id\s*\)",
        source,
    )
    assert re.search(
        r"FOUNDRY_OPERATIONS_MCP_CONNECTION_ID\s*=\s*local.foundry_candidate_mcp_connection_id",
        (TF / "outputs.tf").read_text(),
    )
    assert "project_connection_id = azapi_resource.foundry_mcp_connection[0].id" in source
    curator = source.split("ontology_curator_tool_config =", 1)[1].split("\n  ]", 1)[0]
    assert "merge(local.foundry_mcp_tool_config" in curator
    assert "foundry_candidate_mcp_connection_id" not in curator
    identity = (TF / "foundry_specialist_identity.tf").read_text()
    assert 'authType      = "AgenticIdentityToken"' in identity
    assert 'name                      = "${local.base}-ops-agent"' in identity
    assert "local.foundry_specialist_identity_grants" in (TF / "container_apps.tf").read_text()


def test_rendered_grants_resolve_trusted_subject_catalogs_and_deny_foreign_tools(
    tmp_path, monkeypatch,
):
    from operations import tools

    grants = _rendered(
        tmp_path, enable_foundry_specialist_identity_candidate=True,
        foundry_specialist_identity_principal_ids=IDS,
    )["grants"]
    grants[PROJECT] = [{"role": "reader", "scope": {"subscription": [SUB]}}]
    monkeypatch.setenv("AIOPS_API_GATEWAY_GRANTS", json.dumps(grants))
    authenticator = HeaderPrincipalAuthenticator(
        assertion_value="test-gateway-assertion",
        grants_resolver=_gateway_grants(),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "registry"),
        authenticator=authenticator, authorizer=Authorizer(), telemetry=ApiTelemetry(),
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    dispatched = []

    def dispatch(name, arguments, **kwargs):
        dispatched.append((name, kwargs["principal"].mcp_specialist_id()))
        return tools.ToolResult(status="empty")

    monkeypatch.setattr(tools, "call_tool", dispatch)
    manifest = load_specialist_manifest()
    for specialist in manifest.specialists:
        headers = {
            "x-aiops-gateway-assertion": "test-gateway-assertion",
            "x-ms-client-principal-name": IDS[specialist.id],
        }
        listed = client.post(
            "/api/v1/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert listed.status_code == 200
        assert [t["name"] for t in listed.json()["result"]["tools"]] == list(specialist.operations_mcp_tools)
        foreign = next(t for t in tools.TOOL_REGISTRY if t not in specialist.operations_mcp_tools)
        denied = client.post(
            "/api/v1/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": foreign, "specialist_id": "network", "arguments": {}}},
        )
        assert denied.json()["result"]["isError"] is True
        assert dispatched == []

    for specialist_id, tool in (
        ("governance", "governance_summary"),
        ("identity_access", "identity_summary"),
        ("finops", "finops_summary"),
    ):
        for subject in (PROJECT, IDS["network"], IDS[specialist_id]):
            response = client.post(
                "/api/v1/mcp",
                headers={"x-aiops-gateway-assertion": "test-gateway-assertion",
                         "x-ms-client-principal-name": subject},
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": tool, "specialist_id": specialist_id, "arguments": {}}},
            )
            matching = subject == IDS[specialist_id]
            assert response.json()["result"]["isError"] is not matching
            assert dispatched == ([(tool, specialist_id)] if matching else [])
            dispatched.clear()
