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
 * identity. Public ingress additionally requires APIM's high-entropy gateway
 * assertion so callers cannot bypass the authenticated gateway.
 */

resource "azurerm_container_app" "azure_mcp" {
  name                         = "${local.base}-azure-mcp"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.azure_mcp.id]
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
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.azure_mcp.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
  }

  template {
    container {
      name   = "azure-mcp"
      image  = var.deploy_images ? "${azurerm_container_registry.main.login_server}/azure-mcp:${var.image_tag}" : local.placeholder_image
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

      # Overrides the Dockerfile's baked-in default at runtime. --mode all
      # (the prior default) starts azmcp with 200+ individually-registered
      # tools; Microsoft's own docs call this slower and "not recommended"
      # for regular use, and empirically here azmcp never even completed the
      # initial MCP `initialize` handshake under --mode all (hung >4
      # minutes against a direct container request) -- exactly matching
      # Foundry's "Initialization timed out while enumerating tools" error
      # for this agent. --mode namespace (the documented default) groups
      # each Azure service behind one routing tool instead, initializes
      # promptly, and still dispatches to the same underlying operations the
      # network-agent's allowed_tools list already names.
      env {
        name  = "AZMCP_ARGS"
        value = "--read-only --mode namespace --dangerously-disable-elicitation --outgoing-auth-strategy UseHostingEnvironmentIdentity"
      }

      env {
        name  = "AIOPS_GATEWAY_ASSERTION"
        value = local.gateway_assertion
      }

      # The stdio bridge is intentionally single-flight because every HTTP
      # request shares one Azure MCP child process. Bound queueing and active
      # execution below Foundry/APIM deadlines so callers receive a retryable
      # response instead of an opaque upstream timeout.
      env {
        name  = "AZMCP_REQUEST_TIMEOUT_MS"
        value = "25000"
      }

      env {
        name  = "AZMCP_QUEUE_TIMEOUT_MS"
        value = "5000"
      }

      env {
        name  = "AZMCP_MAX_QUEUE_DEPTH"
        value = "32"
      }

      env {
        name  = "AZMCP_MAX_REQUEST_BYTES"
        value = "1048576"
      }

      env {
        name  = "AZMCP_MAX_RESPONSE_BYTES"
        value = "1048576"
      }
    }

    min_replicas = 1
    # MCP initialization and all subsequent requests share process-local
    # stdio state. Multiple replicas would let ingress route one logical
    # client across different child processes and break protocol ordering.
    max_replicas = 1
  }

  ingress {
    # Public ingress so APIM (deployed without VNet injection) can reach this
    # service, matching the pattern already used for the Operations relay.
    # APIM has no VNet injection, so ingress remains public. The bridge rejects
    # direct callers without APIM's high-entropy gateway assertion before any
    # request reaches the managed-identity-backed Azure MCP child.
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
  for_each = var.enable_role_assignments ? local.azure_mcp_subscriptions : toset([])

  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.azure_mcp.principal_id
}

# Monitoring Reader additionally covers metrics/log-query tools (Azure
# Monitor, Log Analytics) that plain Reader does not grant data-plane access
# to.
resource "azurerm_role_assignment" "azure_mcp_monitoring_reader" {
  for_each = var.enable_role_assignments ? local.azure_mcp_subscriptions : toset([])

  scope                = "/subscriptions/${each.value}"
  role_definition_name = "Monitoring Reader"
  principal_id         = azurerm_user_assigned_identity.azure_mcp.principal_id
}

resource "azurerm_role_assignment" "azure_mcp_acr_pull" {
  count                = var.enable_role_assignments ? 1 : 0
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
