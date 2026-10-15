# ---------------------------------------------------------------------------
# Operations MCP gateway.  This is deliberately opt-in: APIM is expensive and
# its target, audience, and network reachability must be approved first.
# ---------------------------------------------------------------------------

locals {
  apim_name     = coalesce(var.apim_name, "${local.base}-apim-${local.suffix}")
  apim_api_name = "${local.base}-mcp"
  # Foundry agents reach APIM's native MCP API, which now terminates on the
  # private ACA MCP relay before reaching the governed Operations executor.
  mcp_backend_url  = "https://${azurerm_container_app.mcp_server.ingress[0].fqdn}"
  apim_audience    = coalesce(var.apim_audience, var.entra_api_audience)
  apim_audience_id = replace(local.apim_audience, "api://", "")
  mcp_policy_vars = {
    tenant_id         = var.tenant_id
    audience          = local.apim_audience
    audience_id       = local.apim_audience_id
    backend_url       = local.mcp_backend_url
    gateway_assertion = local.gateway_assertion
  }

  # Distinct native MCP surface for the standalone Azure MCP server
  # (Microsoft's @azure/mcp), separate from the Operations executor relay
  # above -- see azure_mcp_server.tf.
  azure_mcp_backend_url = "https://${azurerm_container_app.azure_mcp.ingress[0].fqdn}"
  azure_mcp_policy_vars = {
    tenant_id         = var.tenant_id
    audience          = local.apim_audience
    audience_id       = local.apim_audience_id
    backend_url       = local.azure_mcp_backend_url
    gateway_assertion = local.gateway_assertion
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
  subscription_required = false
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

# Backend pointing at the existing (already MCP-protocol-speaking) Operations
# tool server. The native MCP API references this backend + endpoint template
# instead of a bare serviceUrl so APIM proxies real JSON-RPC MCP traffic and
# surfaces the backend's tools/resources through the MCP server blade.
resource "azapi_resource" "mcp_backend" {
  count     = var.enable_apim ? 1 : 0
  type      = "Microsoft.ApiManagement/service/backends@2024-06-01-preview"
  name      = "${local.base}-mcp-backend"
  parent_id = azurerm_api_management.main[0].id
  body = {
    properties = {
      protocol = "http"
      url      = local.mcp_backend_url
    }
  }
}

# APIM's native MCP inventory is identified by apiType=``mcp``. The azurerm
# provider can proxy an HTTP API but cannot emit this preview-only API type.
resource "azapi_resource" "mcp_server" {
  count                     = var.enable_apim ? 1 : 0
  type                      = "Microsoft.ApiManagement/service/apis@2024-06-01-preview"
  name                      = "${local.base}-operations-mcp"
  parent_id                 = azurerm_api_management.main[0].id
  schema_validation_enabled = false
  body = {
    properties = {
      type                 = "mcp"
      displayName          = "Operations MCP Server"
      description          = "Governed read-only MCP server for the Operations executor (CVE/vulnerability, workbench, and remediation queries), relayed via the private ACA MCP relay"
      path                 = "operations-mcp"
      protocols            = ["https"]
      subscriptionRequired = false
      backendId            = azapi_resource.mcp_backend[0].name
      mcpProperties = {
        endpoints = {
          mcp = {
            uriTemplate = "/"
          }
        }
      }
    }
  }
}

resource "azurerm_api_management_api_policy" "mcp" {
  count               = var.enable_apim ? 1 : 0
  api_name            = azurerm_api_management_api.mcp[0].name
  api_management_name = azurerm_api_management.main[0].name
  resource_group_name = azurerm_resource_group.main.name
  xml_content         = templatefile("${path.module}/apim-policies/mcp-inbound.xml", local.mcp_policy_vars)
}

# The native MCP surface (azapi_resource.mcp_server) is a separate API from
# the plain HTTP-proxy one above and needs its own policy attachment -- the
# azurerm resource type doesn't know about `apis` created via azapi, so this
# is itself an azapi child resource under the same api.
resource "azapi_resource" "mcp_server_policy" {
  count     = var.enable_apim ? 1 : 0
  type      = "Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview"
  name      = "policy"
  parent_id = azapi_resource.mcp_server[0].id
  body = {
    properties = {
      format = "xml"
      value  = templatefile("${path.module}/apim-policies/mcp-inbound.xml", local.mcp_policy_vars)
    }
  }
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

# ---------------------------------------------------------------------------
# Azure MCP gateway (Microsoft's @azure/mcp).  A second, independent native
# MCP surface, distinct from the Operations relay above: this fronts the
# standalone azure_mcp container app (azure_mcp_server.tf), whose generic
# Azure resource tool catalog is authorized purely by that container's own
# managed identity roles rather than the Operations executor.
# ---------------------------------------------------------------------------

resource "azapi_resource" "azure_mcp_backend" {
  count     = var.enable_apim ? 1 : 0
  type      = "Microsoft.ApiManagement/service/backends@2024-06-01-preview"
  name      = "${local.base}-azure-mcp-backend"
  parent_id = azurerm_api_management.main[0].id
  body = {
    properties = {
      protocol = "http"
      url      = local.azure_mcp_backend_url
    }
  }
}

resource "azapi_resource" "azure_mcp_server" {
  count                     = var.enable_apim ? 1 : 0
  type                      = "Microsoft.ApiManagement/service/apis@2024-06-01-preview"
  name                      = "${local.base}-azure-mcp"
  parent_id                 = azurerm_api_management.main[0].id
  schema_validation_enabled = false
  body = {
    properties = {
      type                 = "mcp"
      displayName          = "Azure MCP Server"
      description          = "Microsoft's official Azure MCP Server (@azure/mcp) -- generic, read-only tools for compute, storage, network, monitor, and cost across onboarded subscriptions"
      path                 = "azure-mcp"
      protocols            = ["https"]
      subscriptionRequired = false
      backendId            = azapi_resource.azure_mcp_backend[0].name
      mcpProperties = {
        endpoints = {
          mcp = {
            uriTemplate = "/"
          }
        }
      }
    }
  }
}

resource "azapi_resource" "azure_mcp_server_policy" {
  count     = var.enable_apim ? 1 : 0
  type      = "Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview"
  name      = "policy"
  parent_id = azapi_resource.azure_mcp_server[0].id
  body = {
    properties = {
      format = "xml"
      value  = templatefile("${path.module}/apim-policies/azure-mcp-inbound.xml", local.azure_mcp_policy_vars)
    }
  }
}

resource "azurerm_api_management_product" "azure_mcp" {
  count                 = var.enable_apim ? 1 : 0
  product_id            = "azure-mcp"
  api_management_name   = azurerm_api_management.main[0].name
  resource_group_name   = azurerm_resource_group.main.name
  display_name          = "Azure MCP (approved clients)"
  published             = true
  approval_required     = true
  subscription_required = true
  subscriptions_limit   = var.apim_subscription_limit
}
