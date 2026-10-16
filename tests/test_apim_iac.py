import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TF = ROOT / "infra" / "terraform"


def test_apim_is_opt_in_and_exposes_only_mcp_proxy():
    source = (TF / "apim.tf").read_text()
    assert "enable_apim" in source
    assert 'path' in source and '"mcp"' in source
    assert "subscription_required = true" in source
    assert "service_url" in source
    assert "mcp_policy_vars" in source
    assert 'resource "azurerm_api_management_api_operation" ' not in source


def test_apim_policy_validates_token_limits_and_replaces_identity_headers():
    policy = (TF / "apim-policies" / "mcp-inbound.xml").read_text()
    for marker in (
        "validate-azure-ad-token",
        "rate-limit-by-key",
        "quota-by-key",
        "X-AIOps-Validated-Gateway",
        "X-AIOps-Gateway-Assertion",
        "exists-action=\"delete\"",
        "StartsWith",
        "application/json",
        "Unsupported Media Type",
    ):
        assert marker in policy
    assert "OneLake" not in policy
    assert "client_secret" not in policy
    assert "remediation" not in policy


def test_apim_validated_user_identity_matches_direct_entra_subject_precedence():
    policy = (TF / "apim-policies" / "mcp-inbound.xml").read_text()
    inbound = ET.fromstring(policy).find("inbound")
    assert inbound is not None
    elements = list(inbound)
    validation = next(i for i, element in enumerate(elements) if element.tag == "validate-azure-ad-token")
    identity_index = next(
        i for i, element in enumerate(elements)
        if element.tag == "set-variable" and element.get("name") == "aiopsCallerId"
    )
    assert validation < identity_index
    expression = elements[identity_index].get("value", "")
    assert (
        expression.index("return preferredUsername[0].Trim()")
        < expression.index("return upn[0].Trim()")
        < expression.index("return oid[0]")
        < expression.index("return appid[0]")
    )
    assert "!string.IsNullOrWhiteSpace(preferredUsername[0])" in expression
    assert "!string.IsNullOrWhiteSpace(upn[0])" in expression
    direct = (ROOT / "src/api/auth.py").read_text()
    assert (
        direct.index('claims.get("preferred_username")')
        < direct.index('claims.get("upn")')
        < direct.index('claims.get("oid")')
    )


@pytest.mark.parametrize(
    ("suffix", "valid"),
    [
        ("", True), ("0000007", True), ("candidate-1", True),
        ("foreign.example.com", False), ("https://foreign.example", False),
        ("../0000007", False), ("-invalid", False), ("invalid-", False),
        ("a" * 65, False),
    ],
)
def test_operations_mcp_revision_selector_rejects_foreign_hosts(tmp_path, suffix, valid):
    terraform = shutil.which("terraform")
    if terraform is None:
        pytest.skip("Terraform CLI is required for executable HCL regression")
    source = (TF / "mcp_server.tf").read_text()
    variable = source.split("\nlocals {", 1)[0].split(
        'variable "operations_mcp_api_revision_suffix"', 1
    )[1]
    (tmp_path / "main.tf").write_text(
        'variable "operations_mcp_api_revision_suffix"' + variable
    )
    result = subprocess.run(
        [terraform, "plan", "-input=false", "-no-color", f"-var=operations_mcp_api_revision_suffix={suffix}"],
        cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert (result.returncode == 0) is valid, result.stderr
    if not valid:
        assert "not a URL or hostname" in result.stderr
    assert 'default     = ""' in variable
    assert 'https://${local.operations_mcp_api_host}/api/v1/mcp' in source
    assert '${local.base}-api--${var.operations_mcp_api_revision_suffix}.' in source
    assert '${azurerm_container_app_environment.main.default_domain}' in source

def test_outputs_are_identifiers_only_and_smoke_script_does_not_persist_token():
    outputs = (TF / "outputs.tf").read_text()
    script = (ROOT / "infra" / "scripts" / "validate-apim-mcp.sh").read_text()
    assert "apim_gateway_url" in outputs
    assert "sensitive" not in outputs
    assert "AIOPS_MCP_BEARER_TOKEN" in script
    assert "unsupported method" in script
    assert "X-AIOps-Scope: attacker" in script
    assert "tee" not in script
    assert "AIOPS_DEPLOY_ARTIFACT_DIR" not in script


def test_rollback_artifact_is_declared_and_secret_safe():
    deploy = (ROOT / "infra" / "scripts" / "deploy.sh").read_text()
    rollback = (ROOT / "infra" / "scripts" / "rollback-apim-mcp.sh").read_text()
    runbook = (ROOT / ".planning" / "phases" / "09-consumer-pivot" / "09-APIM-ROLLBACK.md").read_text()
    assert "AIOPS_DEPLOY_ARTIFACT_DIR" in deploy
    assert "capture_apim_snapshot" in deploy
    assert "terraform.tfstate" in runbook
    assert "AIOPS_APIM_ROLLBACK_SNAPSHOT" in rollback
    assert "Authorization" not in rollback
