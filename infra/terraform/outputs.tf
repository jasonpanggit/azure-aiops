output "resource_group_name" {
  description = "Resource group holding every resource in this deployment."
  value       = azurerm_resource_group.main.name
}

output "web_url" {
  description = "Operations Workbench URL."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "api_url" {
  description = "Operations API base URL."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "container_registry" {
  description = "Registry login server, used by infra/scripts/build-and-push.sh."
  value       = azurerm_container_registry.main.login_server
}

output "api_image" {
  description = "Fully qualified API image reference expected by the API container app."
  value       = local.api_image
}

output "web_image" {
  description = "Fully qualified web image reference expected by the web container app."
  value       = local.web_image
}

output "foundry_project_endpoint" {
  description = "Foundry project data-plane endpoint (FOUNDRY_PROJECT_ENDPOINT)."
  value       = local.foundry_project_endpoint
}

output "copilot_provider_environment" {
  description = "Non-secret sourceable Operations Copilot provider and rollout environment. Empty provider values mean the corresponding live gate remains BLOCKED."
  value = {
    FOUNDRY_PROJECT_ENDPOINT             = local.foundry_project_endpoint
    OPERATIONS_MCP_SERVER_URL            = var.enable_apim ? local.foundry_mcp_server_url : ""
    AZURE_MCP_SERVER_URL                 = var.enable_apim ? local.foundry_azure_mcp_server_url : ""
    MCP_APIM_AUDIENCE                    = var.enable_apim ? local.apim_audience : ""
    FOUNDRY_CANDIDATE_MAPPING            = local.foundry_candidate_artifact_path
    FOUNDRY_OPERATIONS_MCP_CONNECTION_ID = var.enable_apim ? azapi_resource.foundry_mcp_connection[0].id : ""
    FOUNDRY_AZURE_MCP_CONNECTION_ID      = var.enable_apim ? azapi_resource.foundry_azure_mcp_connection[0].id : ""
    AIOPS_COPILOT_ROLLOUT_MODE           = var.copilot_rollout_mode
    AIOPS_COPILOT_CANARY_PERCENTAGE      = tostring(local.copilot_canary_percentage)
    AIOPS_COPILOT_ROLLBACK_MODE          = local.copilot_rollback_mode
  }
}

output "foundry_agent_name" {
  description = "Prompt agent backing the Operations Copilot (FOUNDRY_AGENT_NAME)."
  value       = var.foundry_agent_name
}

output "foundry_model_deployment" {
  description = "Model deployment the prompt agent runs on."
  value       = azurerm_cognitive_deployment.chat.name
}

output "key_vault_name" {
  description = "Key Vault holding the API bearer token."
  value       = azurerm_key_vault.main.name
}

output "entra_web_client_id" {
  description = "Entra SPA application client ID compiled into the web image."
  value       = var.entra_web_client_id
}

output "apim_gateway_url" {
  description = "Non-secret APIM MCP gateway URL, or null when APIM is disabled."
  value       = var.enable_apim ? "${azurerm_api_management.main[0].gateway_url}/mcp" : null
}

output "apim_azure_mcp_gateway_url" {
  description = "Non-secret APIM gateway URL for the standalone Azure MCP server (azure-mcp path), or null when APIM is disabled."
  value       = var.enable_apim ? "${azurerm_api_management.main[0].gateway_url}/azure-mcp" : null
}

output "apim_resource_id" {
  description = "APIM resource identifier; no credentials or policy values are exposed."
  value       = var.enable_apim ? azurerm_api_management.main[0].id : null
}

output "apim_name" {
  description = "APIM service name, or null when APIM is disabled."
  value       = var.enable_apim ? azurerm_api_management.main[0].name : null
}

output "foundry_project_principal_id" {
  description = <<-EOT
    Object ID of the Foundry project's system-assigned identity. Add this as a
    key in entra_grants_json (AIOPS_ENTRA_GRANTS_JSON) with the grants
    specialist agents should be able to exercise over MCP, e.g.
    {"<this value>": [{"role": "reader"}]}, then re-apply -- Foundry's MCP
    connection authenticates as this identity when calling APIM.
  EOT
  value       = azurerm_cognitive_account_project.ops.identity[0].principal_id
}

output "apim_api_name" {
  description = "APIM MCP API name, or null when APIM is disabled."
  value       = var.enable_apim ? azurerm_api_management_api.mcp[0].name : null
}


output "fabric_workspace_id" {
  description = "Fabric workspace ID, or null when Fabric is disabled."
  value       = var.enable_fabric ? fabric_workspace.ops[0].id : null
}

output "fabric_lakehouse_id" {
  description = "Fabric lakehouse ID, or null when Fabric is disabled."
  value       = var.enable_fabric ? fabric_lakehouse.context_graph[0].id : null
}

output "ontology_evidence_role_contract" {
  description = "Exact five-item contract consumed by the external OneLake ManagedIdentity Read reconciler."
  value = var.enable_fabric && var.ontology_discovery_environment == "validation" ? {
    principal_object_id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    principal_resource_id = azurerm_user_assigned_identity.azure_mcp.id
    tenant_id             = var.tenant_id
    targets = {
      ontology_discovery_state = {
        workspace_id = fabric_workspace.ontology_discovery_state[0].id
        item_id      = fabric_lakehouse.ontology_discovery_state[0].id
      }

      ontology_command = {
        workspace_id = fabric_workspace.ontology_command[0].id
        item_id      = fabric_lakehouse.ontology_command[0].id
      }
      ontology_dispatch = {
        workspace_id = fabric_workspace.ontology_dispatch[0].id
        item_id      = fabric_lakehouse.ontology_dispatch[0].id
      }
      ontology_publication = {
        workspace_id = fabric_workspace.ontology_publication[0].id
        item_id      = fabric_lakehouse.ontology_publication[0].id
      }
      ontology_rbac_validation = {
        workspace_id = fabric_workspace.ontology_rbac_validation[0].id
        item_id      = fabric_lakehouse.ontology_rbac_validation[0].id
      }
    }
  } : null
}

output "ontology_coordinator_source_role_contract" {
  description = "Exact production connection-registry read contract for the ontology coordinator."
  value = var.enable_fabric ? {
    principal_object_id   = azurerm_user_assigned_identity.ontology_coordinator.principal_id
    principal_resource_id = azurerm_user_assigned_identity.ontology_coordinator.id
    tenant_id             = var.tenant_id
    workspace_id          = fabric_workspace.ops[0].id
    item_id               = fabric_lakehouse.context_graph[0].id
    path                  = "/Files/aiops/connections"
  } : null
}
