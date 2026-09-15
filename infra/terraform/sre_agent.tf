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
      startswith(lower(resource_id), "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/")
    ])
    error_message = "Every SRE Agent managed resource must remain inside subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1."
  }
}

locals {
  sre_agent_subscription_id = "a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
  sre_agent_resource_group  = "rg-sredemo-dev"
  sre_agent_name            = "sre-agent-sredemo"
  sre_agent_parent_id       = "/subscriptions/${local.sre_agent_subscription_id}/resourceGroups/${local.sre_agent_resource_group}"
  sre_agent_resource_id     = "${local.sre_agent_parent_id}/providers/Microsoft.App/agents/${local.sre_agent_name}"

  sre_agent_user_assigned_identity_id = "/subscriptions/${local.sre_agent_subscription_id}/resourcegroups/${local.sre_agent_resource_group}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/sre-agent-sredemo-amncvvib6atbg"
  sre_agent_system_principal_id       = "003cb2df-6d1f-4555-ba0b-60766e616f2d"
  sre_agent_user_principal_id         = "5b3b9ec4-16fb-4c0f-96fb-16887062f976"
  sre_agent_application_insights_id   = "55f20823-66c8-4f3a-b987-6cfc3ab096a5"

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
    condition = !var.enable_sre_agent_patch_execution || (
      var.sre_agent_http_trigger_secret_id != "" &&
      var.sre_agent_endpoint != "" &&
      startswith(
        lower(var.sre_agent_patch_target_prefix),
        "/subscriptions/${lower(local.sre_agent_subscription_id)}/"
      ) &&
      strcontains(lower(var.sre_agent_patch_target_prefix), "/resourcegroups/")
    )
    error_message = "SRE Agent patch execution requires an expected agent endpoint, an existing trigger secret URI, and a target prefix inside the configured SRE Agent subscription."
  }
}

resource "azurerm_role_definition" "sre_agent_trigger_invoker" {
  count = var.enable_sre_agent_patch_execution ? 1 : 0

  name  = "${local.base}-sre-agent-trigger-invoker"
  scope = "/subscriptions/${local.sre_agent_subscription_id}"

  permissions {
    actions     = []
    not_actions = []
    data_actions = [
      "Microsoft.App/agents/threads/read",
      "Microsoft.App/agents/threads/write",
    ]
    not_data_actions = []
  }

  assignable_scopes = ["/subscriptions/${local.sre_agent_subscription_id}"]
}

resource "azurerm_role_assignment" "apps_sre_agent_trigger_invoker" {
  count = var.enable_sre_agent_patch_execution ? 1 : 0

  scope                            = local.sre_agent_resource_id
  role_definition_id               = azurerm_role_definition.sre_agent_trigger_invoker[0].role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true
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
    AIOPS_PATCH_EXECUTION               = var.enable_sre_agent_patch_execution ? "sre-agent" : "azure"
    AIOPS_SRE_AGENT_ENDPOINT            = var.sre_agent_endpoint
    AIOPS_SRE_AGENT_SUBSCRIPTION_ID     = local.sre_agent_subscription_id
    AIOPS_SRE_AGENT_TARGET_PREFIX       = var.sre_agent_patch_target_prefix
    AIOPS_SRE_AGENT_TRIGGER_SCOPE       = var.sre_agent_trigger_scope
    AIOPS_SRE_AGENT_THREAD_SCOPE        = var.sre_agent_thread_scope
    trigger_url_is_key_vault_referenced = var.sre_agent_http_trigger_secret_id != ""
  }
}
