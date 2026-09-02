# ---------------------------------------------------------------------------
# Microsoft Fabric
#
# Gated behind var.enable_fabric (default false) because a Fabric capacity
# bills from creation regardless of use. Everything else in this configuration
# deploys and runs without it.
#
# Fabric spans two providers: the capacity is an Azure resource (azurerm),
# while workspaces and lakehouses live in the Fabric control plane (fabric).
# ---------------------------------------------------------------------------

locals {
  fabric_workspace_name = coalesce(var.fabric_workspace_name, "${local.base}-ops")

  # Service principals must be identified by object ID here; an application ID
  # is accepted by the API but grants nothing.
  fabric_admins = distinct(concat([local.deployer_object_id], var.fabric_capacity_admins))
}

resource "azurerm_fabric_capacity" "main" {
  count = var.enable_fabric ? 1 : 0

  # Capacity names are alphanumeric-only and lowercase.
  name                = substr(replace("${var.name_prefix}${var.environment}cap${local.suffix}", "-", ""), 0, 63)
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  administration_members = local.fabric_admins

  sku {
    name = var.fabric_capacity_sku
    tier = "Fabric"
  }

  tags = local.tags
}

resource "azurerm_role_assignment" "fabric_capacity_reader_apps" {
  count = var.enable_fabric ? 1 : 0

  scope                            = azurerm_fabric_capacity.main[0].id
  role_definition_name             = "Reader"
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true
}

data "fabric_capacity" "main" {
  count        = var.enable_fabric ? 1 : 0
  display_name = azurerm_fabric_capacity.main[0].name

  depends_on = [azurerm_fabric_capacity.main]
}

# ---------------------------------------------------------------------------
# Workspace and lakehouse
#
# Requires the tenant setting "Service principals can use Fabric APIs" to be
# enabled for the deploying principal. If it is not, these resources fail with
# a PrincipalTypeNotSupported error and the capacity above must be assigned to
# a workspace by hand.
# ---------------------------------------------------------------------------

resource "fabric_workspace" "ops" {
  count = var.enable_fabric ? 1 : 0

  display_name = local.fabric_workspace_name
  description  = "Operational context graph for the AIOps workbench."
  capacity_id  = data.fabric_capacity.main[0].id
}

resource "fabric_lakehouse" "context_graph" {
  count = var.enable_fabric ? 1 : 0

  display_name = var.fabric_lakehouse_name
  description  = "Landing and curated zones for topology, incident, change, and vulnerability datasets."
  workspace_id = fabric_workspace.ops[0].id

  # Schema support is set at creation and cannot be changed afterwards. It is
  # left disabled: the AIOps sync client's table-listing/registration calls
  # (LakehouseManager.list_tables) use the flat `/tables` endpoint, which
  # Fabric rejects with UnsupportedOperationForSchemasEnabledLakehouse when
  # schemas are enabled. Curated datasets are organised by table name prefix
  # instead (bronze_/silver_/ontology_).
}

# The container apps read from the lakehouse with the same identity they use
# elsewhere. Contributor rather than Member: they must not administer the
# workspace or manage its access.
resource "fabric_workspace_role_assignment" "apps" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ops[0].id
  role         = "Contributor"

  principal = {
    id   = azurerm_user_assigned_identity.apps.principal_id
    type = "ServicePrincipal"
  }
}
