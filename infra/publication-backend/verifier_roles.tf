locals {
  verifier_reads = {
    account = {
      action = "Microsoft.Storage/storageAccounts/read"
      scope  = try(azurerm_storage_account.artifacts["candidate"].id, null)
    }
    blob_service = {
      action = "Microsoft.Storage/storageAccounts/blobServices/read"
      scope  = try("${azurerm_storage_account.artifacts["candidate"].id}/blobServices/default", null)
    }
    container_policy = {
      action = "Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read"
      scope  = try(azurerm_storage_container.artifacts["candidate"].id, null)
    }
  }
  verifier_candidates = {
    for pair in setproduct(keys(local.candidates), keys(local.verifier_reads)) :
    "${pair[0]}-${pair[1]}" => {
      candidate = pair[0]
      read_kind = pair[1]
    }
  }
}

# Definitions only. Each proposed grant has its own narrower resource scope.
resource "azurerm_role_definition" "artifact_verifier_candidate" {
  for_each          = local.verifier_candidates
  name              = "${var.settings.name_prefix}-verifier-${each.value.read_kind}-candidate"
  scope             = azurerm_resource_group.backend[each.value.candidate].id
  assignable_scopes = [azurerm_resource_group.backend[each.value.candidate].id]
  description       = "UNASSIGNED read-only artifact verifier candidate; no data, SQL, write, key or SAS authority."

  permissions {
    actions          = [local.verifier_reads[each.value.read_kind].action]
    not_actions      = []
    data_actions     = []
    not_data_actions = []
  }
}

output "publication_backend_verifier_roles_v1" {
  description = "Proposed exact-scope read bindings only, never assigned permissions or provider qualification."
  value = var.enable && var.settings != null ? {
    schema_version    = "publication-backend-verifier-roles/v1"
    assigned          = false
    execution_enabled = false
    qualified         = false
    proposed_bindings = {
      for key, role in azurerm_role_definition.artifact_verifier_candidate :
      local.verifier_candidates[key].read_kind => {
        role_definition_id = role.role_definition_resource_id
        principal_id       = azurerm_user_assigned_identity.broker["candidate"].principal_id
        scope              = local.verifier_reads[local.verifier_candidates[key].read_kind].scope
        actions            = [local.verifier_reads[local.verifier_candidates[key].read_kind].action]
        data_actions       = []
        assigned           = false
      }
    }
  } : null
}
