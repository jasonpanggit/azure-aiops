# ---------------------------------------------------------------------------
# Ontology publication identity
#
# Publication is deliberately not performed by the API, coordinator Job, or
# Foundry project identity.
#
# Platform limitation: Fabric workspace roles are currently the authorization
# boundary for OneLake Lakehouse write/delete operations. Fabric does not
# expose path-level custom roles for these operations; Contributor is the least
# broad role that can write/delete Lakehouse data. Admin and Member are never
# granted. Application fencing, create-only writes, conditional ETags, and
# canary-only validation provide the narrower operation boundary above this
# platform grant.
#
# The live non-production authorization matrix remains a deployment gate:
# Terraform declares the candidate grant here, while
# scripts/validate_ontology_publisher_rbac.py must prove its effective
# behavior before an authoritative publisher can be enabled.
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "ontology_publisher" {
  name                = "${local.base}-ontology-publisher-id"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "fabric_workspace_role_assignment" "ontology_publisher" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ops[0].id
  role         = "Contributor"

  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}
