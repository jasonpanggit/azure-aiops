/*
 * Azure MCP Server Container App
 * 
 * Deploys the centralized MCP server that all specialist agents route through.
 * Server loads subscription connections from registry and resolves SPNs from AKV.
 */

variable "operations_mcp_api_revision_suffix" {
  description = "Optional same-app API revision for protected Operations MCP acceptance before API traffic cutover. Empty keeps the main API endpoint."
  type        = string
  default     = ""

  validation {
    condition = (
      var.operations_mcp_api_revision_suffix == "" ||
      can(regex("^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$", var.operations_mcp_api_revision_suffix))
    )
    error_message = "The Operations MCP API revision must be an empty value or a lowercase alphanumeric/hyphen revision suffix, not a URL or hostname."
  }
}

locals {
  operations_mcp_api_host = var.operations_mcp_api_revision_suffix == "" ? local.api_fqdn : "${local.base}-api--${var.operations_mcp_api_revision_suffix}.${azurerm_container_app_environment.main.default_domain}"
}

resource "azurerm_container_app" "mcp_server" {
  name                         = "${local.base}-mcp-server"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.mcp_server.id]
  }

  dynamic "secret" {
    for_each = var.enable_role_assignments ? [] : [1]
    content {
      name  = "acr-password"
      value = azurerm_container_registry.main.admin_password
    }
  }

  registry {
    server               = azurerm_container_registry.main.login_server
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.mcp_server.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
  }

  template {
    container {
      name   = "mcp-server"
      image  = var.deploy_images ? "${azurerm_container_registry.main.login_server}/mcp-server:${var.image_tag}" : local.placeholder_image
      cpu    = "0.5"
      memory = "1Gi"

      env {
        name  = "AIOPS_HOME"
        value = "/app/data"
      }

      env {
        name  = "AIOPS_AKV_NAME"
        value = azurerm_key_vault.main.name
      }

      env {
        name  = "AIOPS_SUBSCRIPTION_IDS"
        value = join(",", var.onboarded_subscriptions)
      }

      env {
        name  = "PORT"
        value = "8000"
      }

      # The ACA service owns the public MCP protocol hop. Tool execution stays
      # in the existing governed API so its authorization and audit controls
      # remain the single source of truth.
      env {
        name  = "AIOPS_OPERATIONS_MCP_URL"
        value = "https://${local.operations_mcp_api_host}/api/v1/mcp"
      }

      env {
        name  = "AIOPS_GATEWAY_ASSERTION"
        value = local.gateway_assertion
      }

      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        initial_delay           = 5
        timeout                 = 3
        failure_count_threshold = 3
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        timeout                 = 3
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        timeout                 = 3
        failure_count_threshold = 3
      }
    }

    min_replicas = 1
    max_replicas = 3
  }

  ingress {
    # Public ingress so APIM (deployed without VNet injection) can reach this
    # service. The relay rejects any request without APIM's high-entropy
    # gateway assertion before it reaches the governed tool executor.
    external_enabled = true
    target_port      = 8000
    transport        = "http"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.mcp_server_reader,
    azurerm_role_assignment.mcp_server_akv_secrets_user,
    azurerm_role_assignment.mcp_server_acr_pull,
  ]
}

# Managed identity for MCP server
resource "azurerm_user_assigned_identity" "mcp_server" {
  name                = "${local.base}-mcp-server-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = local.tags
}

# Role: Reader on each onboarded subscription (allows tool calls with resolved SPN)
resource "azurerm_role_assignment" "mcp_server_reader" {
  for_each = var.enable_role_assignments || var.enable_mcp_role_assignments ? toset(var.onboarded_subscriptions) : toset([])

  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.mcp_server.principal_id
}

# Role: Key Vault Secrets User (allows reading SPN credentials from AKV)
resource "azurerm_role_assignment" "mcp_server_akv_secrets_user" {
  count                = var.enable_role_assignments || var.enable_mcp_role_assignments ? 1 : 0
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.mcp_server.principal_id
}

# Role: AcrPull (allows pulling mcp-server image from registry)
resource "azurerm_role_assignment" "mcp_server_acr_pull" {
  count                = var.enable_role_assignments ? 1 : 0
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.mcp_server.principal_id
}

output "mcp_server_fqdn" {
  value       = azurerm_container_app.mcp_server.ingress[0].fqdn
  description = "FQDN of the MCP server for APIM routing"
}

output "mcp_server_identity_principal_id" {
  value       = azurerm_user_assigned_identity.mcp_server.principal_id
  description = "Principal ID of MCP server managed identity"
}
