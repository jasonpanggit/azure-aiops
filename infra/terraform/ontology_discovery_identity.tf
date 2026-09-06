# ---------------------------------------------------------------------------
# Ontology publication identity
#
# Publication is deliberately not performed by the API, coordinator Job, or
# Foundry project identity.  This user-assigned identity receives only the
# data-plane primitives required to create immutable stage objects, compare
# and replace the active pointer, publish ontology material, and remove a
# failed/canary stage during rollback.
#
# The live non-production authorization matrix remains a deployment gate:
# Terraform declares the candidate grant here, while
# scripts/validate_ontology_publisher_rbac.py must prove its effective
# behavior before an authoritative publisher can be enabled.
# ---------------------------------------------------------------------------

locals {
  ontology_publisher_data_actions = [
    # Read an explicitly addressed predecessor/manifest.  Deliberately omit
    # container enumeration and all management-plane generalization.
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    # Immutable create and conditional pointer/ontology writes.
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
    # Canary cleanup and rollback never require container/account deletion.
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
  ]
}

resource "azurerm_user_assigned_identity" "ontology_publisher" {
  name                = "${local.base}-ontology-publisher-id"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_role_definition" "ontology_publisher" {
  name        = "${local.base}-ontology-publisher"
  scope       = azurerm_resource_group.main.id
  description = "Candidate least-privilege ontology stage, pointer CAS, publish, and rollback data actions."

  permissions {
    actions          = []
    not_actions      = []
    data_actions     = local.ontology_publisher_data_actions
    not_data_actions = []
  }

  assignable_scopes = [
    azurerm_resource_group.main.id,
  ]
}

resource "azurerm_role_assignment" "ontology_publisher" {
  scope                            = azurerm_resource_group.main.id
  role_definition_id               = azurerm_role_definition.ontology_publisher.role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.ontology_publisher.principal_id
  skip_service_principal_aad_check = true
}
