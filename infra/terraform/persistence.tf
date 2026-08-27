# ---------------------------------------------------------------------------
# Networking for durable application state
#
# All durable state -- the connection registry, risk exceptions, cached CVE
# enrichment, and every dataset generation -- lives in OneLake, the Microsoft
# Fabric unified data platform (see fabric.tf). There is no separate database
# or storage account: the API reaches OneLake with its managed identity over
# the private-link path below, avoiding both the Azure Files SMB mount that is
# incompatible with the subscription policy and a second copy of the data.
# ---------------------------------------------------------------------------

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

# The subscription's ASC Default policy disables public network access on Key
# Vault, so the API (submitting onboarding client secrets) needs a
# private-link path to it.
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
