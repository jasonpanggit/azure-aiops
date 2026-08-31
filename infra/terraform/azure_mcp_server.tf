/*
 * Azure MCP Server Container App (native @azure/mcp tool catalog)
 *
 * This is a distinct MCP surface from azurerm_container_app.mcp_server
 * (the Python relay in mcp_server.tf). That relay only forwards to the
 * governed Operations executor and exposes its curated tool set. This
 * container runs Microsoft's official Azure MCP Server (Dockerfile.azure-mcp)
 * so specialist agents can also query/list Azure resources directly across
 * the full generic tool catalog (compute, storage, network, monitor, cost,
 * etc.), read-only, authorized purely via this container's own managed
 * identity -- no shared secret, no dependency on the Operations executor.
 */

resource "azurerm_container_app" "azure_mcp" {
  name                         = "${local.base}-azure-mcp"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.azure_mcp.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.azure_mcp.id
  }

  template {
    container {
      name   = "azure-mcp"
      image  = "${azurerm_container_registry.main.login_server}/azure-mcp:${var.image_tag}"
      cpu    = "0.5"
      memory = "1Gi"

      env {
        name  = "PORT"
        value = "8000"
      }

      # Tells the Azure SDK credential chain inside @azure/mcp which user
      # assigned identity to use -- required whenever more than one identity
      # could otherwise be ambiguous to DefaultAzureCredential.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.azure_mcp.client_id
      }

      # @azure/mcp 3.0.0-beta's default credential chain does not attempt
      # ManagedIdentityCredential even when IDENTITY_ENDPOINT/IDENTITY_HEADER
      # are correctly injected by Container Apps -- confirmed via live
      # testing and a matching upstream report
      # (https://github.com/microsoft/mcp/issues/1030). Setting this forces
      # DefaultAzureCredential to use only ManagedIdentityCredential, which
      # is what actually authorizes every Azure Resource Manager/Monitor
      # call this container makes.
      env {
        name  = "AZURE_TOKEN_CREDENTIALS"
        value = "ManagedIdentityCredential"
      }
    }

    min_replicas = 1
    max_replicas = 3
  }

  ingress {
    # Public ingress so APIM (deployed without VNet injection) can reach this
    # service, matching the pattern already used for the Operations relay.
    # There is no shared-secret gate here: every tool this server exposes is
    # read-only and authorized solely by this container's managed identity
    # roles below, so the blast radius of a direct call is bounded to the
    # same read-only access an authenticated caller already gets via APIM's
    # Azure AD JWT + product subscription requirement.
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
    azurerm_role_assignment.azure_mcp_reader,
    azurerm_role_assignment.azure_mcp_monitoring_reader,
    azurerm_role_assignment.azure_mcp_acr_pull,
  ]
}

resource "azurerm_user_assigned_identity" "azure_mcp" {
  name                = "${local.base}-azure-mcp-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  tags = local.tags
}

# Reader scoped to the deploying/onboarded subscriptions -- enough for the
# vast majority of @azure/mcp's read/list tools (resource inventory, configs,
# topology, etc.) without granting any write/control-plane access.
resource "azurerm_role_assignment" "azure_mcp_reader" {
  for_each = local.azure_mcp_subscriptions

  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.azure_mcp.principal_id
}

# Monitoring Reader additionally covers metrics/log-query tools (Azure
# Monitor, Log Analytics) that plain Reader does not grant data-plane access
# to.
resource "azurerm_role_assignment" "azure_mcp_monitoring_reader" {
  for_each = local.azure_mcp_subscriptions

  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Monitoring Reader"
  principal_id         = azurerm_user_assigned_identity.azure_mcp.principal_id
}

resource "azurerm_role_assignment" "azure_mcp_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.azure_mcp.principal_id
}

locals {
  # Falls back to the deploying subscription when onboarded_subscriptions is
  # empty so the new server has at least read access to something to query,
  # without requiring a separate variable just for this server.
  azure_mcp_subscriptions = toset(
    length(var.onboarded_subscriptions) > 0
    ? var.onboarded_subscriptions
    : [data.azurerm_client_config.current.subscription_id]
  )
}

output "azure_mcp_fqdn" {
  value       = azurerm_container_app.azure_mcp.ingress[0].fqdn
  description = "FQDN of the standalone Azure MCP server (Microsoft @azure/mcp) for APIM routing"
}

output "azure_mcp_identity_principal_id" {
  value       = azurerm_user_assigned_identity.azure_mcp.principal_id
  description = "Principal ID of the Azure MCP server's managed identity"
}
