"""Static safety contract for the existing Azure SRE Agent import configuration."""

from __future__ import annotations

import re
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
    assert 'aoaiDeploymentSku = "GlobalStandard"' in body
    assert "EnableWorkspaceTools = true" in body
    assert 'connectionName = "azmonitor"' in body
    assert 'oboUser        = ""' in body
    assert 'type           = "AzMonitor"' in body
    assert 'name     = "Automatic"' in body
    assert 'provider = "MicrosoftFoundry"' in body
    assert '"55f20823-66c8-4f3a-b987-6cfc3ab096a5"' in terraform
    assert "applicationInsightsConfiguration" in body
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
        "connectionKey",
        "connectionString",
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


def test_sre_patch_execution_is_default_off_and_trigger_url_is_secret_safe() -> None:
    container_apps = _read(CONTAINER_APPS_TERRAFORM)
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")

    assert 'variable "enable_sre_agent_patch_execution"' in variables
    start = variables.index('variable "enable_sre_agent_patch_execution"')
    assert "default     = false" in variables[start : start + 300]
    assert 'name                = "sre-agent-http-trigger-url"' in container_apps
    assert "key_vault_secret_id = secret.value" in container_apps
    assert 'name        = "AIOPS_SRE_AGENT_TRIGGER_URL"' in container_apps
    assert 'secret_name = "sre-agent-http-trigger-url"' in container_apps
    assert "value = var.sre_agent_http_trigger_secret_id" not in container_apps
    assert "AIOPS_SRE_AGENT_ENDPOINT     = var.sre_agent_endpoint" in container_apps
    assert "for_each = var.sre_agent_endpoint != \"\"" in container_apps


def test_sre_trigger_caller_role_is_agent_scoped_and_flag_guarded() -> None:
    terraform = _read(SRE_TERRAFORM)

    assert 'resource "azurerm_role_definition" "sre_agent_trigger_invoker"' in terraform
    assert 'resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker"' in terraform
    assert "count = var.enable_sre_agent_patch_execution ? 1 : 0" in terraform
    assert re.search(r"scope\s+= local\.sre_agent_resource_id", terraform)
    assert '"Microsoft.App/agents/threads/read"' in terraform
    assert '"Microsoft.App/agents/threads/write"' in terraform
    permissions = terraform[
        terraform.index('resource "azurerm_role_definition" "sre_agent_trigger_invoker"') :
        terraform.index(
            'resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker"'
        )
    ]
    assert re.search(r"^\s*actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*not_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*data_actions\s+= \[$", permissions, re.MULTILINE)
    assert re.search(r"^\s*not_data_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert (
        'assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]'
        in terraform
    )
