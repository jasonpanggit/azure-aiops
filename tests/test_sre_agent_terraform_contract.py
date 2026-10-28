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
    assert (
        "value = jsonencode(merge(jsondecode(var.entra_grants_json), "
        "local.foundry_mcp_gateway_grants, "
        "local.foundry_specialist_identity_grants, "
        "local.ontology_evidence_gateway_grants))"
    ) in container_apps
    assert "sre_agent_api_gateway_grants" not in container_apps
    foundry = _read(REPO_ROOT / "infra" / "terraform" / "foundry.tf")
    gateway_grants = foundry.split("foundry_mcp_gateway_grants =", 1)[1].split(
        "foundry_azure_mcp_connection_name", 1
    )[0]
    assert "azurerm_cognitive_account_project.ops.identity[0].principal_id" in gateway_grants
    assert 'role  = "reader"' in gateway_grants
    assert "sre_agent" not in gateway_grants


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
    assert (
        "AIOPS_SRE_AGENT_TRIGGER_ORIGIN  = var.sre_agent_trigger_origin"
        in container_apps
    )
    assert "AIOPS_SRE_AGENT_TRIGGER_ID      = var.sre_agent_trigger_id" in container_apps
    assert "AIOPS_SRE_AGENT_ENDPOINT     = var.sre_agent_endpoint" in container_apps
    assert "for_each = var.sre_agent_endpoint != \"\"" in container_apps


def test_disabled_sre_execution_preserves_runtime_refusing_default() -> None:
    terraform = _read(CONTAINER_APPS_TERRAFORM)
    output = _read(SRE_TERRAFORM)

    assert (
        'value = var.enable_sre_agent_patch_execution ? "sre-agent" : "azure"'
        not in terraform
    )
    assert (
        "AIOPS_PATCH_EXECUTION               = "
        'var.enable_sre_agent_patch_execution ? "sre-agent" : null'
    ) in output


def test_sre_trigger_caller_role_is_agent_scoped_and_flag_guarded() -> None:
    terraform = _read(SRE_TERRAFORM)

    assert 'resource "azurerm_role_definition" "sre_agent_trigger_invoker"' in terraform
    assert 'resource "azurerm_role_definition" "sre_agent_thread_reader"' in terraform
    assert 'resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker"' in terraform
    assert 'resource "azurerm_role_assignment" "apps_sre_agent_thread_reader"' in terraform
    assert "count = var.enable_sre_agent_patch_rbac ? 1 : 0" in terraform
    assert re.search(r"scope\s+= local\.sre_agent_resource_id", terraform)
    assert '"Microsoft.App/agents/threads/read"' in terraform
    assert '"Microsoft.App/agents/threads/write"' in terraform
    permissions = terraform[
        terraform.index('resource "azurerm_role_definition" "sre_agent_trigger_invoker"') :
        terraform.index(
            'resource "azurerm_role_definition" "sre_agent_thread_reader"'
        )
    ]
    assert re.search(r"^\s*actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*not_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*data_actions\s+= \[$", permissions, re.MULTILINE)
    assert re.search(r"^\s*not_data_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert '"Microsoft.App/agents/threads/read"' not in permissions
    assert '"Microsoft.App/agents/threads/approve/action"' in permissions
    assert '"Microsoft.App/agents/threads/write"' in permissions
    assert (
        'assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]'
        in terraform
    )

    reader_start = terraform.index(
        'resource "azurerm_role_definition" "sre_agent_thread_reader"'
    )
    reader_end = terraform.index(
        'resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker"'
    )
    reader = terraform[reader_start:reader_end]
    assert '"Microsoft.App/agents/threads/read"' in reader
    assert '"Microsoft.App/agents/threads/approve/action"' not in reader
    assert '"Microsoft.App/agents/threads/write"' not in reader
    assert (
        "var.enable_sre_agent_patch_rbac || "
        "var.retain_sre_agent_thread_verification"
    ) in reader


def test_sre_patch_role_is_exact_target_scoped_and_flag_guarded() -> None:
    terraform = _read(SRE_TERRAFORM)
    start = terraform.index(
        'resource "azurerm_role_definition" "sre_agent_patch_executor"'
    )
    end = terraform.index(
        'resource "azurerm_role_assignment" "sre_agent_patch_executor"'
    )
    permissions = terraform[start:end]

    assert "count = var.enable_sre_agent_patch_rbac ? 1 : 0" in permissions
    assert "actions          = local.sre_agent_patch_actions" in permissions
    assert re.search(r"^\s*not_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*data_actions\s+= \[\]$", permissions, re.MULTILINE)
    assert re.search(r"^\s*not_data_actions\s+= \[\]$", permissions, re.MULTILINE)
    for action in (
        "Microsoft.Compute/virtualMachines/read",
        "Microsoft.Compute/virtualMachines/installPatches/action",
        "Microsoft.HybridCompute/machines/read",
        "Microsoft.HybridCompute/machines/installPatches/action",
    ):
        assert f'"{action}"' in terraform
    assert "assessPatches" not in terraform
    assert "Contributor" not in permissions

    assignment = terraform[end:]
    assert (
        "scope                            = var.sre_agent_patch_target_prefix"
        in assignment
    )
    assert (
        "principal_id                     = local.sre_agent_user_principal_id"
        in assignment
    )


def test_sre_patch_scope_must_be_managed_and_resource_group_or_narrower() -> None:
    terraform = _read(SRE_TERRAFORM)
    check_start = terraform.index(
        'check "sre_agent_patch_execution_configuration"'
    )
    check_end = terraform.index(
        'resource "azurerm_role_definition" "sre_agent_trigger_invoker"'
    )
    check = terraform[check_start:check_end]

    assert "resourcegroups/[a-z0-9._()-]+" in terraform
    assert "local.sre_agent_managed_resource_scopes" in terraform
    assert (
        'startswith(local.sre_agent_patch_target_scope, "${managed_scope}/")'
        in terraform
    )
    assert "local.sre_agent_patch_target_scope_valid" in check


def test_sre_origins_reject_localhost_and_ip_literals_before_runtime() -> None:
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")

    assert 'lower(var.sre_agent_trigger_origin) != "https://localhost"' in variables
    assert '"^https://[0-9]+(?:\\\\.[0-9]+){3}$"' in variables
    assert '"^https://localhost/?$"' in variables


def test_sre_trigger_id_is_required_and_exported_as_non_secret_config() -> None:
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")
    terraform = _read(SRE_TERRAFORM)

    assert 'variable "sre_agent_trigger_id"' in variables
    assert '"^[A-Za-z0-9._~-]+$"' in variables
    assert "var.sre_agent_trigger_id != \"\"" in terraform
    assert "AIOPS_SRE_AGENT_TRIGGER_ID          = var.sre_agent_trigger_id" in terraform


def test_sre_trigger_secret_uri_is_exact_name_and_version_pinned() -> None:
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")

    assert (
        "secrets/sre-agent-http-trigger-url/[A-Za-z0-9]+$"
        in variables
    )
    assert "versioned Azure Key Vault URI" in variables


def test_thread_read_authorization_can_survive_dispatch_rollback() -> None:
    terraform = _read(SRE_TERRAFORM)
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")

    assert 'variable "retain_sre_agent_thread_verification"' in variables
    assert (
        "count = var.enable_sre_agent_patch_rbac || "
        "var.retain_sre_agent_thread_verification ? 1 : 0"
    ) in terraform
    patch_start = terraform.index(
        'resource "azurerm_role_definition" "sre_agent_patch_executor"'
    )
    patch_end = terraform.index('resource "azapi_resource" "sre_agent"')
    assert (
        "retain_sre_agent_thread_verification"
        not in terraform[patch_start:patch_end]
    )
    assert re.search(
        r'sre_agent_reviewed_endpoint\s*=\s*"https://sre-agent-sredemo--8b71343d\.ba56c019\.australiaeast\.azuresre\.ai"',
        terraform,
    )
    assert (
        "trimsuffix(lower(var.sre_agent_endpoint), \"/\") == "
        "lower(local.sre_agent_reviewed_endpoint)"
    ) in terraform
    assert (
        "lower(local.sre_agent_resource_id) == "
        "lower(local.sre_agent_reviewed_resource_id)"
    ) in terraform
    assert (
        "var.sre_agent_thread_scope == local.sre_agent_reviewed_thread_scope"
        in terraform
    )


def test_rbac_bootstrap_is_distinct_from_dispatch_enablement() -> None:
    terraform = _read(SRE_TERRAFORM)
    variables = _read(REPO_ROOT / "infra" / "terraform" / "variables.tf")

    assert 'variable "enable_sre_agent_patch_rbac"' in variables
    assert "default     = false" in variables[
        variables.index('variable "enable_sre_agent_patch_rbac"') :
        variables.index('variable "retain_sre_agent_thread_verification"')
    ]
    assert "var.enable_sre_agent_patch_rbac &&" in terraform
    assert terraform.count("count = var.enable_sre_agent_patch_rbac ? 1 : 0") == 4
    scope_start = terraform.index('check "sre_agent_patch_target_scope"')
    scope_end = terraform.index('check "sre_agent_thread_verification_retention"')
    scope_check = terraform[scope_start:scope_end]
    assert (
        "var.enable_sre_agent_patch_rbac || var.enable_sre_agent_patch_execution"
        in scope_check
    )
    assert "local.sre_agent_patch_target_scope_valid" in scope_check
    assert "local.sre_agent_managed_resource_scopes" in terraform
    assert terraform.count(
        "condition     = local.sre_agent_patch_target_scope_valid"
    ) == 6
    assert terraform.count(
        'error_message = "SRE Agent RBAC requires a canonical managed target scope."'
    ) == 6
    assert terraform.count(
        'error_message = "Retained SRE Agent thread read requires the exact agent scope and endpoint."'
    ) == 2


def test_api_enablement_has_plan_blocking_full_configuration_precondition() -> None:
    container_apps = _read(CONTAINER_APPS_TERRAFORM)

    api_start = container_apps.index('resource "azurerm_container_app" "api"')
    api_end = container_apps.index(
        'resource "azurerm_container_app_job" "exposure_enrichment"'
    )
    api = container_apps[api_start:api_end]
    assert "lifecycle {" in api
    assert (
        "condition     = !var.enable_sre_agent_patch_execution || "
        "local.sre_agent_patch_execution_config_valid"
    ) in api
    assert (
        "var.sre_agent_trigger_scope == local.sre_agent_reviewed_trigger_scope"
        in _read(SRE_TERRAFORM)
    )
    assert (
        "var.sre_agent_thread_scope == local.sre_agent_reviewed_thread_scope"
        in _read(SRE_TERRAFORM)
    )
