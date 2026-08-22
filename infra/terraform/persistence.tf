# ---------------------------------------------------------------------------
# Durable application state
#
# The connection registry is stored in PostgreSQL. Dataset generations are
# stored in ADLS Gen2 and accessed through the API's managed identity, avoiding
# the Azure Files SMB mount that is incompatible with the subscription policy.
# ---------------------------------------------------------------------------

resource "random_password" "postgres" {
  length      = 32
  special     = false
  min_lower   = 4
  min_upper   = 4
  min_numeric = 4
}

resource "azurerm_postgresql_flexible_server" "hermes" {
  name                = "${local.base}-pg-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  version                = "16"
  administrator_login    = "hermesadmin"
  administrator_password = random_password.postgres.result
  storage_mb             = 32768
  sku_name               = "B_Standard_B1ms"
  backup_retention_days  = 7
  zone                   = "3"

  # Container Apps reaches this dev database over TLS. Production deployments
  # should move the server behind a delegated subnet/private DNS zone.
  public_network_access_enabled = true

  tags = local.tags
}

resource "azurerm_postgresql_flexible_server_database" "hermes" {
  name      = "hermes"
  server_id = azurerm_postgresql_flexible_server.hermes.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.hermes.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_storage_account" "hermes_data" {
  name                = substr(replace("${var.name_prefix}${var.environment}lake${local.suffix}", "-", ""), 0, 24)
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  is_hns_enabled           = true
  min_tls_version          = "TLS1_2"

  # ADLS access uses Entra ID/RBAC, not an SMB account key.
  shared_access_key_enabled     = false
  public_network_access_enabled = false

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  tags = local.tags
}

resource "azurerm_storage_container" "hermes_data" {
  name                  = "hermes-data"
  storage_account_id    = azurerm_storage_account.hermes_data.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "hermes_data" {
  scope                = azurerm_storage_account.hermes_data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id

  skip_service_principal_aad_check = true
}

resource "azurerm_virtual_network" "apps" {
  name                = "${local.base}-vnet"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.50.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "container_apps" {
  name                 = "container-apps"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.apps.name
  address_prefixes     = ["10.50.0.0/21"]

  delegation {
    name = "container-apps"

    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = "private-endpoints"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.apps.name
  address_prefixes     = ["10.50.8.0/24"]
}

resource "azurerm_private_dns_zone" "dfs" {
  name                = "privatelink.dfs.core.windows.net"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "dfs" {
  name                = "${local.base}-dfs-dns-link"
  private_dns_zone_id = azurerm_private_dns_zone.dfs.id
  virtual_network_id  = azurerm_virtual_network.apps.id
}

resource "azurerm_private_dns_zone" "blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob" {
  name                = "${local.base}-blob-dns-link"
  private_dns_zone_id = azurerm_private_dns_zone.blob.id
  virtual_network_id  = azurerm_virtual_network.apps.id
}

resource "azurerm_private_endpoint" "hermes_data" {
  name                = "${local.base}-adls-pe"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.base}-adls-connection"
    private_connection_resource_id = azurerm_storage_account.hermes_data.id
    subresource_names              = ["dfs"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.dfs.id]
  }

  tags = local.tags
}

resource "azurerm_private_endpoint" "hermes_data_blob" {
  name                = "${local.base}-adls-blob-pe"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.base}-adls-blob-connection"
    private_connection_resource_id = azurerm_storage_account.hermes_data.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.blob.id]
  }

  tags = local.tags
}

# The subscription's ASC Default policy also disables public network access
# on Key Vault, so the API (submitting onboarding client secrets) needs the
# same private-link path as ADLS above.
resource "azurerm_private_dns_zone" "vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "vault" {
  name                = "${local.base}-vault-dns-link"
  private_dns_zone_id = azurerm_private_dns_zone.vault.id
  virtual_network_id  = azurerm_virtual_network.apps.id
}

resource "azurerm_private_endpoint" "key_vault" {
  name                = "${local.base}-kv-pe"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.base}-kv-connection"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.vault.id]
  }

  tags = local.tags
}
