from pathlib import Path


ROOT = Path(__file__).parents[1]
TF = ROOT / "infra" / "terraform"


def test_apim_is_opt_in_and_exposes_only_mcp_proxy():
    source = (TF / "apim.tf").read_text()
    assert "enable_apim" in source
    assert 'path' in source and '"mcp"' in source
    assert "subscription_required = true" in source
    assert "service_url" in source
    assert "azurerm_api_management_api_operation_policy" in source
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
        "413",
    ):
        assert marker in policy
    assert "OneLake" not in policy
    assert "client_secret" not in policy
    assert "remediation" not in policy


def test_outputs_are_identifiers_only_and_smoke_script_does_not_persist_token():
    outputs = (TF / "outputs.tf").read_text()
    script = (ROOT / "infra" / "scripts" / "validate-apim-mcp.sh").read_text()
    assert "apim_gateway_url" in outputs
    assert "sensitive" not in outputs
    assert "AIOPS_MCP_BEARER_TOKEN" in script
    assert ">" not in script
    assert "tee" not in script
