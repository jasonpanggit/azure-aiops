"""Static safety contract for the existing Azure SRE Agent import configuration."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRE_TERRAFORM = REPO_ROOT / "infra" / "terraform" / "sre_agent.tf"
CONTAINER_APPS_TERRAFORM = REPO_ROOT / "infra" / "terraform" / "container_apps.tf"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resource_body(terraform: str) -> str:
    start = terraform.index('resource "azapi_resource" "sre_agent"')
    body_start = terraform.index("  body = {", start)
    body_end = terraform.index("\n  lifecycle {", body_start)
    return terraform[body_start:body_end]


def test_sre_agent_is_import_gated_and_destroy_protected() -> None:
    terraform = _read(SRE_TERRAFORM)

    assert 'variable "enable_sre_agent_management"' in terraform
    assert "default     = false" in terraform
    assert "count = var.enable_sre_agent_management ? 1 : 0" in terraform
    assert 'type                      = "Microsoft.App/agents@2026-01-01"' in terraform
    assert "schema_validation_enabled = false" in terraform
    assert "prevent_destroy = true" in terraform
    assert "ignore_changes  = [tags]" in terraform
    assert "length(var.sre_agent_managed_resources) > 0" in terraform


def test_sre_agent_preserves_observed_identity_and_writable_settings() -> None:
    terraform = _read(SRE_TERRAFORM)
    body = _resource_body(terraform)

    assert 'type         = "SystemAssigned, UserAssigned"' in terraform
    assert '"003cb2df-6d1f-4555-ba0b-60766e616f2d"' in terraform
    assert '"5b3b9ec4-16fb-4c0f-96fb-16887062f976"' in terraform
    assert 'accessLevel = "Low"' in body
    assert 'mode        = "Review"' in body
    assert 'type = "AzMonitor"' in body
    assert 'name     = "Automatic"' in body
    assert 'provider = "MicrosoftFoundry"' in body
    assert "monthlyAgentUnitLimit = 10000" in body
    assert 'mode = "Unrestricted"' in body
    assert 'upgradeChannel = "Stable"' in body


def test_sre_agent_body_excludes_read_only_service_properties() -> None:
    body = _resource_body(_read(SRE_TERRAFORM))

    for read_only_property in (
        "agentEndpoint",
        "outboundIpAddresses",
        "powerState",
        "provisioningState",
        "runningState",
    ):
        assert read_only_property not in body


def test_sre_agent_keeps_mcp_urls_in_a_blocked_connector_contract() -> None:
    terraform = _read(SRE_TERRAFORM)
    body = _resource_body(terraform)

    assert (
        '"https://aiops-dev-apim.azure-api.net/operations-mcp"' in terraform
    )
    assert '"https://aiops-dev-apim.azure-api.net/azure-mcp"' in terraform
    assert '"Microsoft.App/agents/connectors@2026-01-01"' in terraform
    assert 'data_connector_type   = "Mcp"' in terraform
    assert 'authentication_status = "blocked"' in terraform
    assert "mcpServers" not in body
    assert 'resource "azapi_resource" "sre_agent_mcp_connector"' not in terraform


def test_sre_principals_receive_no_premature_gateway_grants() -> None:
    sre_terraform = _read(SRE_TERRAFORM)
    container_apps = _read(CONTAINER_APPS_TERRAFORM)

    assert "effective_api_gateway_grants_json" not in sre_terraform
    assert "sre_agent_api_gateway_grants" not in sre_terraform
    assert "value = var.entra_grants_json" in container_apps
