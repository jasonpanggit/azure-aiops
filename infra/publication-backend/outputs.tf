output "publication_backend_v1" {
  description = "Preparation-only interface; never execution authority, live evidence, SQL grant or a broker endpoint."
  value = var.enable && var.settings != null ? {
    schema_version     = "publication-backend/v1"
    disposition        = "PREPARATORY-NONOPERABLE-UNQUALIFIED"
    execution_enabled  = false
    qualified          = false
    bootstrap_required = true
    config_sha256      = sha256(jsonencode(var.settings))
    sql = {
      server_id     = azurerm_mssql_server.control["candidate"].id
      server_fqdn   = azurerm_mssql_server.control["candidate"].fully_qualified_domain_name
      database_id   = azurerm_mssql_database.control["candidate"].id
      database_name = azurerm_mssql_database.control["candidate"].name
      grants        = "NONE: separate reviewed procedure bootstrap required"
    }
    artifacts = {
      account_id                 = azurerm_storage_account.artifacts["candidate"].id
      account_name               = azurerm_storage_account.artifacts["candidate"].name
      blob_endpoint              = azurerm_storage_account.artifacts["candidate"].primary_blob_endpoint
      container_id               = azurerm_storage_container.artifacts["candidate"].id
      container_name             = azurerm_storage_container.artifacts["candidate"].name
      versioning_enabled         = false
      version_id                 = null
      declared_policy_state      = var.settings.policy_state
      declared_retention_days    = var.settings.retention_days
      candidate_role_id          = azurerm_role_definition.artifact_broker_candidate["candidate"].role_definition_resource_id
      candidate_assignment_scope = azurerm_storage_container.artifacts["candidate"].id
      write_role_assigned        = false
    }
    broker = {
      identity_id  = azurerm_user_assigned_identity.broker["candidate"].id
      client_id    = azurerm_user_assigned_identity.broker["candidate"].client_id
      principal_id = azurerm_user_assigned_identity.broker["candidate"].principal_id
      hosting_id   = azurerm_container_app_job.nonoperable_scaffold["candidate"].id
      hosting_kind = "Manual exit-78 NONOPERABLE scaffold, not a broker service"
      endpoint     = null
    }
    connectivity = {
      virtual_network_id = azurerm_virtual_network.backend["candidate"].id
      endpoint_ids       = { for key, endpoint in azurerm_private_endpoint.backend : key => endpoint.id }
      qualified          = false
    }
  } : null
}
