/*
 * APIM /mcp-proxy API Configuration
 * 
 * Creates the `/mcp-proxy` API endpoint that Foundry agents call.
 * Routes requests to centralized MCP server in ACA with per-subscription SPN management.
 */

# APIM API for MCP proxy
resource "azurerm_api_management_api" "mcp_proxy" {
  name                = "mcp-proxy-api"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main[0].name
  revision            = "1"
  display_name        = "MCP Proxy API"
  path                = "mcp-proxy"
  protocols           = ["https"]
  service_url         = "https://${azurerm_container_app.mcp_server.ingress[0].fqdn}"

  description = "Centralized MCP server proxy for specialist agents with per-subscription SPN credential management"

  subscription_key_parameter_names {
    header = "Ocp-Apim-Subscription-Key"
    query  = "subscription-key"
  }
}

# APIM Operation: POST /mcp-proxy/tool
resource "azurerm_api_management_api_operation" "mcp_proxy_tool" {
  operation_id        = "execute-tool"
  api_name            = azurerm_api_management_api.mcp_proxy.name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Execute MCP Tool"
  method              = "POST"
  url_template        = "/tool"

  description = "Execute an MCP tool for a subscription with resolved SPN credentials"

  request {
    representation {
      content_type = "application/json"
    }
  }

  response {
    status_code = 200
    description = "Tool executed successfully"

    representation {
      content_type = "application/json"
    }
  }

  response {
    status_code = 400
    description = "Bad request (e.g., subscription not onboarded)"
  }

  response {
    status_code = 401
    description = "Unauthorized (invalid or missing token)"
  }

  response {
    status_code = 500
    description = "Internal server error"
  }
}

# APIM Operation: GET /mcp-proxy/health
resource "azurerm_api_management_api_operation" "mcp_proxy_health" {
  operation_id        = "health-check"
  api_name            = azurerm_api_management_api.mcp_proxy.name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "Health Check"
  method              = "GET"
  url_template        = "/health"

  description = "Check MCP server health and connection status"

  response {
    status_code = 200
    description = "MCP server is healthy"

    representation {
      content_type = "application/json"
    }
  }

  response {
    status_code = 503
    description = "Service unavailable"
  }
}

# APIM Operation: GET /mcp-proxy/subscriptions
resource "azurerm_api_management_api_operation" "mcp_proxy_subscriptions" {
  operation_id        = "list-subscriptions"
  api_name            = azurerm_api_management_api.mcp_proxy.name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
  display_name        = "List Onboarded Subscriptions"
  method              = "GET"
  url_template        = "/subscriptions"

  description = "List all onboarded subscriptions and their connection status (credentials redacted)"

  response {
    status_code = 200
    description = "List of onboarded subscriptions"

    representation {
      content_type = "application/json"
    }
  }
}

# Apply MCP proxy inbound policy
resource "azurerm_api_management_api_policy" "mcp_proxy_inbound" {
  api_name            = azurerm_api_management_api.mcp_proxy.name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name

  xml_content = templatefile(
    "${path.module}/apim-policies/mcp-proxy-inbound.xml",
    {
      mcp_server_fqdn = azurerm_container_app.mcp_server.ingress[0].fqdn
    }
  )

  depends_on = [
    azurerm_api_management_api.mcp_proxy,
  ]
}

output "mcp_proxy_endpoint" {
  value       = "${azurerm_api_management.main[0].gateway_url}/mcp-proxy"
  description = "APIM endpoint for specialist agents to call MCP tools"
}
