# ---------------------------------------------------------------------------
# Existing Azure SRE Agent
#
# This resource is intentionally disabled by default. Set the exact observed
# managedResources list, enable management, and import the existing ARM resource
# before running any plan. Enabling it and planning before import would propose
# a create, so the import-first sequence in .azure/deployment-plan.md is a hard
# operational requirement.
# ---------------------------------------------------------------------------

variable "enable_sre_agent_management" {
  description = "Manage the existing Azure SRE Agent after it has been imported into azapi_resource.sre_agent[0]. Never enable before the reviewed import step."
  type        = bool
  default     = false
}

variable "sre_agent_managed_resources" {
  description = "Exact currently observed knowledgeGraphConfiguration.managedResources list. Populate from sanitized read-only evidence before enabling SRE Agent management."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for resource_id in var.sre_agent_managed_resources :
      resource_id == trimspace(resource_id) &&
      !endswith(resource_id, "/") &&
      can(regex(
        "^/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourcegroups/[a-z0-9._()-]+(?:/providers/[a-z0-9.-]+/[a-z0-9._()-]+/[^/?#]+(?:/[a-z0-9._()-]+/[^/?#]+)*)?$",
        lower(resource_id),
      ))
    ])
    error_message = "Every SRE Agent managed resource must be a canonical resource-group or resource ID inside subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1."
  }
}

locals {
  sre_agent_subscription_id        = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
  sre_agent_resource_group         = "rg-sredemo-dev"
  sre_agent_name                   = "sre-agent-sredemo"
  sre_agent_parent_id              = "/subscriptions/${local.sre_agent_subscription_id}/resourceGroups/${local.sre_agent_resource_group}"
  sre_agent_resource_id            = "${local.sre_agent_parent_id}/providers/Microsoft.App/agents/${local.sre_agent_name}"
  sre_agent_reviewed_resource_id   = "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/sre-agent-sredemo"
  sre_agent_reviewed_endpoint      = "https://sre-agent-sredemo--8b71343d.ba56c019.australiaeast.azuresre.ai"
  sre_agent_reviewed_trigger_scope = "59f0a04a-b322-4310-adc9-39ac41e9631e/.default"
  sre_agent_reviewed_thread_scope  = "https://azuresre.dev/.default"

  sre_agent_user_assigned_identity_id = "/subscriptions/${local.sre_agent_subscription_id}/resourcegroups/${local.sre_agent_resource_group}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/sre-agent-sredemo-amncvvib6atbg"
  sre_agent_system_principal_id       = "003cb2df-6d1f-4555-ba0b-60766e616f2d"
  sre_agent_user_principal_id         = "5b3b9ec4-16fb-4c0f-96fb-16887062f976"
  sre_agent_application_insights_id   = "55f20823-66c8-4f3a-b987-6cfc3ab096a5"
  sre_agent_patch_actions = [
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Compute/virtualMachines/installPatches/action",
    "Microsoft.HybridCompute/machines/read",
    "Microsoft.HybridCompute/machines/installPatches/action",
  ]
  sre_agent_patch_target_scope = lower(
    var.sre_agent_patch_target_prefix
  )
  sre_agent_managed_resource_scopes = [
    for resource_id in var.sre_agent_managed_resources :
    lower(resource_id)
  ]
  sre_agent_patch_target_scope_valid = (
    var.sre_agent_patch_target_prefix == trimspace(var.sre_agent_patch_target_prefix) &&
    !endswith(var.sre_agent_patch_target_prefix, "/") &&
    can(regex(
      "^/subscriptions/${lower(local.sre_agent_subscription_id)}/resourcegroups/[a-z0-9._()-]+(?:/providers/[a-z0-9.-]+/[a-z0-9._()-]+/[^/?#]+(?:/[a-z0-9._()-]+/[^/?#]+)*)?$",
      local.sre_agent_patch_target_scope,
    )) &&
    anytrue([
      for managed_scope in local.sre_agent_managed_resource_scopes :
      local.sre_agent_patch_target_scope == managed_scope ||
      startswith(local.sre_agent_patch_target_scope, "${managed_scope}/")
    ])
  )
  sre_agent_patch_execution_config_valid = (
    var.enable_sre_agent_patch_rbac &&
    var.sre_agent_http_trigger_secret_id != "" &&
    startswith(
      var.sre_agent_http_trigger_secret_id,
      "${azurerm_key_vault.main.vault_uri}secrets/sre-agent-http-trigger-url/"
    ) &&
    var.sre_agent_trigger_id != "" &&
    var.sre_agent_trigger_origin != "" &&
    var.sre_agent_endpoint != "" &&
    var.sre_agent_trigger_scope == local.sre_agent_reviewed_trigger_scope &&
    var.sre_agent_thread_scope == local.sre_agent_reviewed_thread_scope &&
    local.sre_agent_patch_target_scope_valid
  )
  sre_agent_thread_retention_config_valid = (
    trimsuffix(lower(var.sre_agent_endpoint), "/") == lower(local.sre_agent_reviewed_endpoint) &&
    var.sre_agent_thread_scope == local.sre_agent_reviewed_thread_scope &&
    lower(local.sre_agent_resource_id) == lower(local.sre_agent_reviewed_resource_id)
  )

  sre_agent_mcp_server_urls = [
    "https://aiops-dev-apim.azure-api.net/operations-mcp",
    "https://aiops-dev-apim.azure-api.net/azure-mcp",
  ]

  # Microsoft.App/agents@2026-01-01 does not declare mcpServers on the agent
  # resource. Remote MCP endpoints are separate connectors. Keep this
  # non-secret contract visible without creating connectors: the current APIM
  # policies require Entra bearer tokens, while SRE Agent supports managed
  # identity only for stdio MCP connectors. Connector creation remains blocked
  # until a supported OAuth or token-broker design is approved.
  sre_agent_pending_mcp_connectors = {
    operations = {
      resource_type         = "Microsoft.App/agents/connectors@2026-01-01"
      data_connector_type   = "Mcp"
      transport             = "http"
      endpoint              = local.sre_agent_mcp_server_urls[0]
      supported_auth        = ["BearerToken", "CustomHeaders", "OAuth"]
      authentication_status = "blocked"
    }
    azure = {
      resource_type         = "Microsoft.App/agents/connectors@2026-01-01"
      data_connector_type   = "Mcp"
      transport             = "http"
      endpoint              = local.sre_agent_mcp_server_urls[1]
      supported_auth        = ["BearerToken", "CustomHeaders", "OAuth"]
      authentication_status = "blocked"
    }
  }
}

check "sre_agent_patch_execution_configuration" {
  assert {
    condition     = !var.enable_sre_agent_patch_execution || local.sre_agent_patch_execution_config_valid
    error_message = "SRE Agent patch execution requires bootstrapped RBAC, separate trigger and agent origins, an exact trigger ID, and the canonical versioned trigger secret URI."
  }
}

check "sre_agent_patch_target_scope" {
  assert {
    condition = !(var.enable_sre_agent_patch_rbac || var.enable_sre_agent_patch_execution) || (
      local.sre_agent_patch_target_scope_valid
    )
    error_message = "SRE Agent patch RBAC and execution require a canonical resource-group-or-narrower target scope covered by sre_agent_managed_resources in the selected subscription."
  }
}

check "sre_agent_thread_verification_retention" {
  assert {
    condition     = !var.retain_sre_agent_thread_verification || local.sre_agent_thread_retention_config_valid
    error_message = "Retaining SRE Agent thread verification requires the exact agent endpoint."
  }
}

resource "azurerm_role_definition" "sre_agent_trigger_invoker" {
  count = var.enable_sre_agent_patch_rbac ? 1 : 0

  name  = "${local.base}-sre-agent-trigger-invoker"
  scope = "/subscriptions/${local.sre_agent_subscription_id}"

  permissions {
    actions     = []
    not_actions = []
    data_actions = [
      "Microsoft.App/agents/threads/approve/action",
      "Microsoft.App/agents/threads/write",
    ]
    not_data_actions = []
  }

  assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }

  }
}

resource "azurerm_role_definition" "sre_agent_thread_reader" {
  count = var.enable_sre_agent_patch_rbac || var.retain_sre_agent_thread_verification ? 1 : 0

  name  = "${local.base}-sre-agent-thread-reader"
  scope = "/subscriptions/${local.sre_agent_subscription_id}"

  permissions {
    actions     = []
    not_actions = []
    data_actions = [
      "Microsoft.App/agents/threads/read",
    ]
    not_data_actions = []
  }

  assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }

    precondition {
      condition     = !var.retain_sre_agent_thread_verification || local.sre_agent_thread_retention_config_valid
      error_message = "Retained SRE Agent thread read requires the exact agent scope and endpoint."
    }
  }
}

resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker" {
  count = var.enable_sre_agent_patch_rbac ? 1 : 0

  scope                            = local.sre_agent_resource_id
  role_definition_id               = azurerm_role_definition.sre_agent_trigger_invoker[0].role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }

  }
}

resource "azurerm_role_assignment" "apps_sre_agent_thread_reader" {
  count = var.enable_sre_agent_patch_rbac || var.retain_sre_agent_thread_verification ? 1 : 0

  scope                            = local.sre_agent_resource_id
  role_definition_id               = azurerm_role_definition.sre_agent_thread_reader[0].role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }

    precondition {
      condition     = !var.retain_sre_agent_thread_verification || local.sre_agent_thread_retention_config_valid
      error_message = "Retained SRE Agent thread read requires the exact agent scope and endpoint."
    }
  }
}

resource "azurerm_role_definition" "sre_agent_patch_executor" {
  count = var.enable_sre_agent_patch_rbac ? 1 : 0

  name  = "${local.base}-sre-agent-patch-executor"
  scope = "/subscriptions/${local.sre_agent_subscription_id}"

  permissions {
    actions          = local.sre_agent_patch_actions
    not_actions      = []
    data_actions     = []
    not_data_actions = []
  }

  assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }
  }
}

resource "azurerm_role_assignment" "sre_agent_patch_executor" {
  count = var.enable_sre_agent_patch_rbac ? 1 : 0

  scope                            = var.sre_agent_patch_target_prefix
  role_definition_id               = azurerm_role_definition.sre_agent_patch_executor[0].role_definition_resource_id
  principal_id                     = local.sre_agent_user_principal_id
  skip_service_principal_aad_check = true

  lifecycle {
    precondition {
      condition     = local.sre_agent_patch_target_scope_valid
      error_message = "SRE Agent RBAC requires a canonical managed target scope."
    }
  }
}

resource "azapi_resource" "sre_agent" {
  count = var.enable_sre_agent_management ? 1 : 0

  type                      = "Microsoft.App/agents@2026-01-01"
  name                      = local.sre_agent_name
  parent_id                 = local.sre_agent_parent_id
  location                  = "australiaeast"
  schema_validation_enabled = false

  identity {
    type         = "SystemAssigned, UserAssigned"
    identity_ids = [local.sre_agent_user_assigned_identity_id]
  }

  body = {
    properties = {
      actionConfiguration = {
        accessLevel = "Low"
        identity    = local.sre_agent_user_assigned_identity_id
        mode        = "Review"
      }
      aoaiDeploymentSku = "GlobalStandard"
      experimentalSettings = {
        EnableWorkspaceTools = true
      }
      knowledgeGraphConfiguration = {
        identity         = local.sre_agent_user_assigned_identity_id
        managedResources = var.sre_agent_managed_resources
      }
      incidentManagementConfiguration = {
        connectionName = "azmonitor"
        oboUser        = ""
        type           = "AzMonitor"
      }
      defaultModel = {
        name     = "Automatic"
        provider = "MicrosoftFoundry"
      }
      logConfiguration = {
        applicationInsightsConfiguration = {
          appId = local.sre_agent_application_insights_id
        }
      }
      monthlyAgentUnitLimit = 10000
      sandboxConfiguration = {
        egress = {
          mode = "Unrestricted"
        }
      }
      upgradeChannel = "Stable"
    }
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [tags]

    precondition {
      condition     = var.subscription_id == local.sre_agent_subscription_id
      error_message = "The imported SRE Agent must be managed only through its existing subscription."
    }

    precondition {
      condition     = length(var.sre_agent_managed_resources) > 0
      error_message = "Populate sre_agent_managed_resources with the exact current list before import or planning."
    }

  }
}

output "sre_agent_resource_id" {
  description = "Exact existing Azure SRE Agent ARM resource ID; management remains disabled until import."
  value       = local.sre_agent_resource_id
}

output "sre_agent_import_address" {
  description = "Terraform address used by the reviewed import-first workflow."
  value       = "azapi_resource.sre_agent[0]"
}

output "sre_agent_pending_mcp_server_urls" {
  description = "Non-secret native APIM MCP URLs awaiting a separately approved authenticated connector design."
  value       = local.sre_agent_mcp_server_urls
}

output "sre_agent_pending_mcp_connectors" {
  description = "Non-secret child-connector contract; every entry remains blocked and no connector resource or gateway grant is created."
  value       = local.sre_agent_pending_mcp_connectors
}

output "sre_agent_identity_principal_ids" {
  description = "Observed SRE Agent principal IDs retained for later caller-identity verification; neither receives a gateway grant in this draft."
  value = {
    system_assigned = local.sre_agent_system_principal_id
    user_assigned   = local.sre_agent_user_principal_id
  }
}

output "sre_agent_patch_execution_environment" {
  description = "Non-secret, default-off runtime contract for the pre-created SRE Agent patch trigger. The trigger URL remains a Key Vault-backed Container Apps secret."
  value = {
    enabled                             = var.enable_sre_agent_patch_execution
    rbac_bootstrapped                   = var.enable_sre_agent_patch_rbac
    thread_verification_retained        = var.retain_sre_agent_thread_verification
    AIOPS_PATCH_EXECUTION               = var.enable_sre_agent_patch_execution ? "sre-agent" : null
    AIOPS_SRE_AGENT_ENDPOINT            = var.sre_agent_endpoint
    AIOPS_SRE_AGENT_SUBSCRIPTION_ID     = local.sre_agent_subscription_id
    AIOPS_SRE_AGENT_TARGET_PREFIX       = var.sre_agent_patch_target_prefix
    AIOPS_SRE_AGENT_TRIGGER_ID          = var.sre_agent_trigger_id
    AIOPS_SRE_AGENT_TRIGGER_ORIGIN      = var.sre_agent_trigger_origin
    AIOPS_SRE_AGENT_TRIGGER_SCOPE       = var.sre_agent_trigger_scope
    AIOPS_SRE_AGENT_THREAD_SCOPE        = var.sre_agent_thread_scope
    trigger_url_is_key_vault_referenced = var.sre_agent_http_trigger_secret_id != ""
  }
}
