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

output "postgres_server_fqdn" {
  description = "PostgreSQL Flexible Server hostname used by the API."
  value       = azurerm_postgresql_flexible_server.hermes.fqdn
}

output "adls_account_name" {
  description = "ADLS Gen2 storage account holding dataset snapshots."
  value       = azurerm_storage_account.hermes_data.name
}

output "fabric_workspace_id" {
  description = "Fabric workspace ID, or null when Fabric is disabled."
  value       = var.enable_fabric ? fabric_workspace.ops[0].id : null
}

output "fabric_lakehouse_id" {
  description = "Fabric lakehouse ID, or null when Fabric is disabled."
  value       = var.enable_fabric ? fabric_lakehouse.context_graph[0].id : null
}
