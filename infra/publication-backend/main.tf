locals {
  candidates = var.enable && var.settings != null ? { candidate = var.settings } : {}
  tags = {
    component   = "publication-backend"
    disposition = "PREPARATORY-NONOPERABLE-UNQUALIFIED"
  }
}

resource "azurerm_resource_group" "backend" {
  for_each = local.candidates
  name     = "${each.value.name_prefix}-rg"
  location = each.value.location
  tags     = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_virtual_network" "backend" {
  for_each            = local.candidates
  name                = "${each.value.name_prefix}-vnet"
  resource_group_name = azurerm_resource_group.backend[each.key].name
  location            = each.value.location
  address_space       = [each.value.virtual_network_cidr]
  tags                = local.tags
}

resource "azurerm_subnet" "hosting" {
  for_each             = local.candidates
  name                 = "broker-hosting"
  resource_group_name  = azurerm_resource_group.backend[each.key].name
  virtual_network_name = azurerm_virtual_network.backend[each.key].name
  address_prefixes     = [cidrsubnet(each.value.virtual_network_cidr, 7, 0)]

  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "endpoints" {
  for_each             = local.candidates
  name                 = "backend-endpoints"
  resource_group_name  = azurerm_resource_group.backend[each.key].name
  virtual_network_name = azurerm_virtual_network.backend[each.key].name
  address_prefixes     = [cidrsubnet(each.value.virtual_network_cidr, 8, 2)]
}

resource "azurerm_user_assigned_identity" "broker" {
  for_each            = local.candidates
  name                = "${each.value.name_prefix}-broker-id"
  resource_group_name = azurerm_resource_group.backend[each.key].name
  location            = each.value.location
  tags                = local.tags
}

resource "azurerm_mssql_server" "control" {
  for_each                      = local.candidates
  name                          = each.value.sql_server_name
  resource_group_name           = azurerm_resource_group.backend[each.key].name
  location                      = each.value.location
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  connection_policy             = "Proxy"
  tags                          = local.tags

  azuread_administrator {
    login_username              = each.value.sql_admin_group_name
    object_id                   = each.value.sql_admin_group_object_id
    tenant_id                   = var.tenant_id
    azuread_authentication_only = true
  }

  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = lower(each.value.sql_admin_group_object_id) != lower(azurerm_user_assigned_identity.broker[each.key].principal_id)
      error_message = "The broker principal cannot be the SQL administrator."
    }
  }
}

resource "azurerm_mssql_database" "control" {
  for_each             = local.candidates
  name                 = each.value.sql_database_name
  server_id            = azurerm_mssql_server.control[each.key].id
  sku_name             = each.value.sql_sku
  max_size_gb          = each.value.sql_max_size_gb
  storage_account_type = "Local"
  tags                 = local.tags

  short_term_retention_policy {
    retention_days = each.value.sql_backup_retention_days
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_account" "artifacts" {
  for_each                          = local.candidates
  name                              = each.value.storage_account_name
  resource_group_name               = azurerm_resource_group.backend[each.key].name
  location                          = each.value.location
  account_kind                      = "StorageV2"
  account_tier                      = "Standard"
  account_replication_type          = each.value.storage_replication
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  public_network_access_enabled     = false
  cross_tenant_replication_enabled  = false
  local_user_enabled                = false
  is_hns_enabled                    = false
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = true
  tags                              = local.tags

  blob_properties {
    versioning_enabled = false
  }

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "artifacts" {
  for_each              = local.candidates
  name                  = each.value.artifact_container_name
  storage_account_id    = azurerm_storage_account.artifacts[each.key].id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container_immutability_policy" "draft" {
  for_each                              = local.candidates
  storage_container_resource_manager_id = azurerm_storage_container.artifacts[each.key].id
  immutability_period_in_days           = each.value.retention_days
  locked                                = false
  protected_append_writes_enabled       = false
  protected_append_writes_all_enabled   = false

  lifecycle {
    prevent_destroy = true
  }
}

locals {
  private_services = {
    for pair in setproduct(keys(local.candidates), ["sql", "blob"]) :
    "${pair[0]}-${pair[1]}" => { candidate = pair[0], service = pair[1] }
  }
}

resource "azurerm_private_dns_zone" "backend" {
  for_each            = local.private_services
  name                = each.value.service == "sql" ? "privatelink.database.windows.net" : "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.backend[each.value.candidate].name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "backend" {
  for_each             = local.private_services
  name                 = "${var.settings.name_prefix}-${each.value.service}-dns"
  private_dns_zone_id  = azurerm_private_dns_zone.backend[each.key].id
  virtual_network_id   = azurerm_virtual_network.backend[each.value.candidate].id
  registration_enabled = false
  tags                 = local.tags
}

resource "azurerm_private_endpoint" "backend" {
  for_each            = local.private_services
  name                = "${var.settings.name_prefix}-${each.value.service}-pe"
  resource_group_name = azurerm_resource_group.backend[each.value.candidate].name
  location            = var.settings.location
  subnet_id           = azurerm_subnet.endpoints[each.value.candidate].id
  tags                = local.tags

  private_service_connection {
    name                           = "${each.value.service}-connection"
    private_connection_resource_id = each.value.service == "sql" ? azurerm_mssql_server.control[each.value.candidate].id : azurerm_storage_account.artifacts[each.value.candidate].id
    subresource_names              = [each.value.service == "sql" ? "sqlServer" : "blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.backend[each.key].id]
  }
}

# Deliberately unassigned: write includes overwrite, so Locked retention and
# separate effective-permission qualification are required before any grant.
resource "azurerm_role_definition" "artifact_broker_candidate" {
  for_each          = local.candidates
  name              = "${each.value.name_prefix}-artifact-broker-candidate"
  scope             = azurerm_resource_group.backend[each.key].id
  assignable_scopes = [azurerm_resource_group.backend[each.key].id]
  description       = "UNASSIGNED candidate for exact artifact container only; no delete, key, SAS, policy or SQL authority."

  permissions {
    actions = [
      "Microsoft.Storage/storageAccounts/blobServices/containers/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read",
    ]
    data_actions = [
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
      "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
    ]
  }
}

resource "azurerm_role_assignment" "registry_pull" {
  for_each             = local.candidates
  scope                = each.value.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.broker[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_container_app_environment" "scaffold" {
  for_each                       = local.candidates
  name                           = "${each.value.name_prefix}-cae"
  resource_group_name            = azurerm_resource_group.backend[each.key].name
  location                       = each.value.location
  infrastructure_subnet_id       = azurerm_subnet.hosting[each.key].id
  internal_load_balancer_enabled = true
  public_network_access          = "Disabled"
  tags                           = local.tags

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }
}

resource "azurerm_container_app_job" "nonoperable_scaffold" {
  for_each                     = local.candidates
  name                         = "${each.value.name_prefix}-scaffold"
  resource_group_name          = azurerm_resource_group.backend[each.key].name
  location                     = each.value.location
  container_app_environment_id = azurerm_container_app_environment.scaffold[each.key].id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 60
  replica_retry_limit          = 0
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.broker[each.key].id]
  }

  registry {
    server   = each.value.registry_server
    identity = azurerm_user_assigned_identity.broker[each.key].id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "nonoperable-scaffold"
      image   = each.value.scaffold_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["/bin/sh", "-c"]
      args    = ["echo 'NONOPERABLE: publication backend is unqualified' >&2; exit 78"]
    }
  }

  depends_on = [azurerm_role_assignment.registry_pull]
}
