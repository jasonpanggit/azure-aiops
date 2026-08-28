# ---------------------------------------------------------------------------
# Operations MCP gateway.  This is deliberately opt-in: APIM is expensive and
# its target, audience, and network reachability must be approved first.
# ---------------------------------------------------------------------------

locals {
  apim_name       = coalesce(var.apim_name, "${local.base}-apim")
  apim_api_name   = "${local.base}-mcp"
  mcp_backend_url = "${local.api_base_url}/api/v1/mcp"
  apim_audience   = coalesce(var.apim_audience, var.entra_api_audience)
  mcp_policy_vars = {
    tenant_id         = var.tenant_id
    audience          = local.apim_audience
    backend_url       = local.mcp_backend_url
    gateway_assertion = var.apim_gateway_assertion
  }
}

resource "azurerm_api_management" "main" {
  count                = var.enable_apim ? 1 : 0
  name                 = local.apim_name
  location             = azurerm_resource_group.main.location
  resource_group_name  = azurerm_resource_group.main.name
  publisher_name       = var.apim_publisher_name
  publisher_email      = var.apim_publisher_email
  sku_name             = "${var.apim_sku}_1"
  virtual_network_type = var.apim_virtual_network_type
  tags                 = local.tags
}

resource "azurerm_api_management_api" "mcp" {
  count                 = var.enable_apim ? 1 : 0
  name                  = local.apim_api_name
  resource_group_name   = azurerm_resource_group.main.name
  api_management_name   = azurerm_api_management.main[0].name
  revision              = var.apim_revision
  display_name          = "Governed Operations MCP"
  path                  = "mcp"
  protocols             = ["https"]
  service_url           = local.mcp_backend_url
  subscription_required = true
  import {
    content_format = "openapi+json"
    content_value = jsonencode({
      openapi = "3.0.1"
      info    = { title = "Governed Operations MCP", version = var.apim_revision }
      paths = {
        "/" = {
          post = {
            operationId = "mcp"
            responses   = { "200" = { description = "MCP response" } }
          }
        }
      }
    })
  }
}

resource "azurerm_api_management_api_policy" "mcp" {
  count               = var.enable_apim ? 1 : 0
  api_name            = azurerm_api_management_api.mcp[0].name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
  xml_content         = templatefile("${path.module}/apim-policies/mcp-inbound.xml", local.mcp_policy_vars)
}

resource "azurerm_api_management_product" "mcp" {
  count                 = var.enable_apim ? 1 : 0
  product_id            = "operations-mcp"
  api_management_name   = azurerm_api_management.main[0].name
  resource_group_name   = azurerm_resource_group.main.name
  display_name          = "Operations MCP (approved clients)"
  published             = true
  approval_required     = true
  subscription_required = true
  subscriptions_limit   = var.apim_subscription_limit
}

resource "azurerm_api_management_product_api" "mcp" {
  count               = var.enable_apim ? 1 : 0
  api_name            = azurerm_api_management_api.mcp[0].name
  product_id          = azurerm_api_management_product.mcp[0].product_id
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
}
