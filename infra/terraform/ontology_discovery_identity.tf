# ---------------------------------------------------------------------------
# Ontology publication identity
#
# Publication is deliberately not performed by the API, coordinator Job, or
# Foundry project identity.
#
# Platform limitation: Fabric workspace roles are currently the authorization
# boundary for OneLake Lakehouse write/delete operations. Fabric does not
# expose path-level custom roles for these operations; Contributor is the least
# broad role that can write/delete Lakehouse data. Plan 13-07 therefore creates
# two isolated non-production workspaces on the existing capacity rather than
# changing the production workspace or granting Admin/Member.
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

# Durable coordinator state is isolated from both production and RBAC canaries.
resource "fabric_workspace" "ontology_discovery_state" {
  count = var.enable_fabric ? 1 : 0

  display_name = "${local.base}-ontology-state"
  description  = "Non-production workspace for Phase 13 ontology discovery run state and evidence batches."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "ontology_discovery_state" {
  count = var.enable_fabric ? 1 : 0

  display_name = "ontology_discovery_state"
  description  = "Non-production Lakehouse for durable ontology coordinator state; never authoritative ontology output."
  workspace_id = fabric_workspace.ontology_discovery_state[0].id
}

resource "fabric_workspace_role_assignment" "ontology_coordinator_state" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ontology_discovery_state[0].id
  role         = "Contributor"

  principal = {
    id   = azurerm_user_assigned_identity.ontology_coordinator.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_state_api" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ontology_discovery_state[0].id
  role         = "Viewer"

  principal = {
    id   = azurerm_user_assigned_identity.apps.principal_id
    type = "ServicePrincipal"
  }
}

# Authorization canaries run in a second disposable non-production boundary.
resource "fabric_workspace" "ontology_rbac_validation" {
  count = var.enable_fabric ? 1 : 0

  display_name = "${local.base}-ontology-rbac-validation"
  description  = "Non-production workspace reserved for Phase 13 authorization canaries."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "ontology_rbac_validation" {
  count = var.enable_fabric ? 1 : 0

  display_name = "ontology_rbac_validation"
  description  = "Non-production Lakehouse for create, pointer CAS, rollback, and cleanup authorization evidence."
  workspace_id = fabric_workspace.ontology_rbac_validation[0].id
}

resource "fabric_workspace_role_assignment" "ontology_publisher" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ontology_rbac_validation[0].id
  role         = "Contributor"

  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}

# Production command, dispatch, and publication roots are isolated from one
# another so process composition cannot accidentally widen authority by
# aliasing paths in the shared operational lakehouse.
resource "fabric_workspace" "ontology_command" {
  count = var.enable_fabric ? 1 : 0

  display_name = "${local.base}-ontology-command"
  description  = "Immutable ontology command intake for API, coordinator, and publisher reauthorization."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "ontology_command" {
  count = var.enable_fabric ? 1 : 0

  display_name = "ontology_command"
  description  = "Create-only command envelopes and worker-owned status transitions."
  workspace_id = fabric_workspace.ontology_command[0].id
}

resource "fabric_workspace" "ontology_dispatch" {
  count = var.enable_fabric ? 1 : 0

  display_name = "${local.base}-ontology-dispatch"
  description  = "Publisher dispatch boundary shared only by coordinator and publisher."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "ontology_dispatch" {
  count = var.enable_fabric ? 1 : 0

  display_name = "ontology_dispatch"
  description  = "Immutable publish and rollback dispatches with fenced worker receipts."
  workspace_id = fabric_workspace.ontology_dispatch[0].id
}

resource "fabric_workspace" "ontology_publication" {
  count = var.enable_fabric ? 1 : 0

  display_name = "${local.base}-ontology-publication"
  description  = "Authoritative staged ontology generations and active pointer."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "ontology_publication" {
  count = var.enable_fabric ? 1 : 0

  display_name = "ontology_publication"
  description  = "Publisher-owned immutable generations and fenced active pointer."
  workspace_id = fabric_workspace.ontology_publication[0].id
}

resource "fabric_workspace_role_assignment" "ontology_command_api" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_command[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.apps.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_command_coordinator" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_command[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.ontology_coordinator.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_command_publisher" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_command[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_dispatch_coordinator" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_dispatch[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.ontology_coordinator.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_dispatch_publisher" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_dispatch[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_publication_api" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_publication[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.apps.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_publication_publisher" {
  count        = var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_publication[0].id
  role         = "Contributor"
  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}

# ---------------------------------------------------------------------------
# Plan 20 read-only deployed evidence identity
#
# The pre-existing Azure MCP UAI already has subscription Reader, Monitoring
# Reader, and ACR pull. It is reused here only because those are the exact
# read capabilities the fixed evidence collector requires. These assignments
# add Viewer metadata access and OneLake Data Access Security Read to the five
# isolated Phase 13 Lakehouse items. They deliberately do not touch the
# production ops workspace, replace any existing data-access role, or grant
# Contributor/Member/Admin.
# ---------------------------------------------------------------------------

resource "fabric_workspace_role_assignment" "ontology_evidence_ontology_discovery_state" {
  count        = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_discovery_state[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_evidence_ontology_command" {
  count        = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_command[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_evidence_ontology_dispatch" {
  count        = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_dispatch[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_evidence_ontology_publication" {
  count        = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_publication[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    type = "ServicePrincipal"
  }
}

resource "fabric_workspace_role_assignment" "ontology_evidence_ontology_rbac_validation" {
  count        = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0
  workspace_id = fabric_workspace.ontology_rbac_validation[0].id
  role         = "Viewer"
  principal = {
    id   = azurerm_user_assigned_identity.azure_mcp.principal_id
    type = "ServicePrincipal"
  }
}

# ---------------------------------------------------------------------------
# OneLake data-access roles (Phase13EvidenceRead)
#
# These five roles were previously declared as fabric_onelake_data_access_security
# resources, but the Fabric provider 1.13 ManagedIdentity round-tripping bug
# prevents Terraform from managing them reliably.
#
# They are now managed by scripts/reconcile_onelake_data_access_roles.py via
# the official Fabric REST API (PUT /v1/workspaces/{wid}/items/{iid}/dataAccessRoles).
#
# If these resources already exist in Terraform state from a prior apply, they
# must be removed with `terraform state rm` AFTER live REST verification
# confirms the roles are correct. See docs/onelake-data-access-role-migration.md.
# ---------------------------------------------------------------------------
