variable "enable_foundry_specialist_identity_candidate" {
  description = "Stage a separate agent-identity MCP connection and scoped specialist grants for a later candidate publication. Does not activate versions or change the existing project-identity connection."
  type        = bool
  default     = false
}

variable "foundry_specialist_identity_principal_ids" {
  description = "Reviewed specialist ID to Foundry instance_identity.principal_id mapping. Use actual provider instance principals, never blueprint IDs or the shared project principal. Metadata alone does not qualify runtime subjects."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for principal in values(var.foundry_specialist_identity_principal_ids) :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", principal)) &&
      lower(principal) != "00000000-0000-0000-0000-000000000000"
    ])
    error_message = "Specialist instance principals must be nonzero object UUIDs."
  }

  validation {
    condition = length(distinct([
      for principal in values(var.foundry_specialist_identity_principal_ids) : lower(principal)
    ])) == length(var.foundry_specialist_identity_principal_ids)
    error_message = "Each specialist must have a distinct instance principal."
  }
}

locals {
  foundry_specialist_identity_ids = {
    for id, principal in var.foundry_specialist_identity_principal_ids : id => lower(principal)
  }
  foundry_specialist_identity_mapping_complete = (
    toset(keys(local.foundry_specialist_identity_ids)) == toset(keys(local.specialists_by_id))
  )
  foundry_specialist_identity_subjects_unassigned = alltrue([
    for principal in values(local.foundry_specialist_identity_ids) :
    principal != lower(azurerm_cognitive_account_project.ops.identity[0].principal_id) &&
    !contains([for subject in keys(jsondecode(var.entra_grants_json)) : lower(subject)], principal)
  ])
  foundry_specialist_identity_grants = var.enable_foundry_specialist_identity_candidate ? {
    for id, principal in local.foundry_specialist_identity_ids : principal => [{
      role              = "reader"
      scope             = { subscription = sort(tolist(local.azure_mcp_subscriptions)) }
      mcp_specialist_id = id
    }]
  } : {}
  foundry_candidate_mcp_connection_id = var.enable_apim ? (
    var.enable_foundry_specialist_identity_candidate
    ? azapi_resource.foundry_specialist_identity_mcp_connection[0].id
    : azapi_resource.foundry_mcp_connection[0].id
  ) : ""
}

# Keep the existing shared connection intact: only later candidate definitions
# select this connection, and their immutable versions still require promotion.
resource "azapi_resource" "foundry_specialist_identity_mcp_connection" {
  count                     = var.enable_foundry_specialist_identity_candidate ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-10-01-preview"
  name                      = "${local.base}-ops-agent"
  schema_validation_enabled = false
  parent_id                 = azurerm_cognitive_account_project.ops.id
  body = {
    properties = {
      authType      = "AgenticIdentityToken"
      category      = "RemoteTool"
      target        = local.foundry_mcp_server_url
      isSharedToAll = false
      audience      = local.apim_audience
      metadata      = { ApiType = "Azure" }
    }
  }

  lifecycle {
    precondition {
      condition     = var.enable_apim && length(local.azure_mcp_subscriptions) > 0
      error_message = "Specialist identity staging requires APIM and a nonempty reviewed subscription scope."
    }
    precondition {
      condition     = local.foundry_specialist_identity_mapping_complete
      error_message = "Specialist identity staging requires exactly the manifest's specialist IDs."
    }
    precondition {
      condition     = local.foundry_specialist_identity_subjects_unassigned
      error_message = "Specialist identities must not reuse the project principal or overwrite existing subject grants."
    }
  }
}
