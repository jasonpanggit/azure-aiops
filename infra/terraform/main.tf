# ---------------------------------------------------------------------------
# Core platform: naming, resource group, registry, observability, secrets.
# ---------------------------------------------------------------------------

locals {
  # A short suffix keeps globally-unique names (registry, Key Vault, Foundry
  # subdomain) collision-free across repeated deployments without forcing the
  # operator to invent one.
  suffix = random_string.suffix.result
  base   = "${var.name_prefix}-${var.environment}"

  # Registry names are alphanumeric-only and capped at 50 characters.
  registry_name = substr(replace("${var.name_prefix}${var.environment}acr${local.suffix}", "-", ""), 0, 50)
  # Key Vault names are capped at 24 characters.
  key_vault_name = substr("${var.name_prefix}-${var.environment}-kv-${local.suffix}", 0, 24)

  resource_group_name = coalesce(var.resource_group_name, "${local.base}-rg")

  tags = merge(
    {
      application = "azure-aiops"
      component   = "operations-workbench"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.tags,
  )

  # The deploying principal's object ID, resolved from Entra when not supplied.
  deployer_object_id = coalesce(var.deployer_object_id, data.azurerm_client_config.current.object_id)
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

# APIM validates the Foundry-issued token, then supplies this high-entropy
# assertion to downstream services. Keeping it Terraform-sensitive prevents
# public API callers from forging the gateway-authenticated identity headers.
resource "random_password" "apim_gateway_assertion" {
  length  = 48
  special = false
}

resource "random_password" "exposure_cursor" {
  for_each = var.enable_role_assignments ? toset([]) : toset(["active", "previous"])
  length   = 64
  special  = false

  # Imported bootstrap keys have different generation metadata. Rotation must
  # be explicit (-replace), not a side effect of adopting existing secrets.
  lifecycle {
    ignore_changes = [length, special]
  }
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------

resource "azurerm_container_registry" "main" {
  name                = local.registry_name
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"

  # Contributor-only bootstrap explicitly opts out of role assignments.
  admin_enabled = !var.enable_role_assignments

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Identity used by both container apps
#
# A user-assigned identity (rather than system-assigned) because the AcrPull
# grant must exist *before* the app's first pull. A system-assigned principal
# does not exist until the app is created, which makes that ordering
# impossible to express.
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "apps" {
  name                = "${local.base}-apps-id"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  count                = var.enable_role_assignments ? 1 : 0
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id

  # The identity is created moments earlier in the same apply; without this the
  # assignment can fail while Entra still reports the principal as unknown.
  skip_service_principal_aad_check = true
}

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.base}-law"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "${local.base}-appi"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# Key Vault
#
# Reserved for deployment secrets. RBAC authorization (not access policies) so
# the grants below are the single source of truth for data-plane access.
# ---------------------------------------------------------------------------

resource "azurerm_key_vault" "main" {
  name                       = local.key_vault_name
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  # The subscription policy requires private access. Add a private endpoint
  # before using this vault for runtime secrets.
  public_network_access_enabled = false
  network_acls {
    bypass         = "AzureServices"
    default_action = "Deny"
  }

  # Soft delete is not optional on Key Vault; purge protection is left off so a
  # non-production environment can be torn down and rebuilt under the same name.
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  tags = local.tags
}

resource "azurerm_role_assignment" "kv_deployer" {
  count = var.enable_role_assignments ? 1 : 0
  # The deploying principal needs data-plane access to write the secret below;
  # subscription Owner alone does not grant it under RBAC authorization.
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = local.deployer_object_id
}

resource "azurerm_role_assignment" "kv_apps" {
  count = var.enable_role_assignments || var.enable_connection_secret_role_assignment ? 1 : 0
  scope = azurerm_key_vault.main.id
  # Needs write (Secrets Officer) not just read (Secrets User): the API
  # stores submitted onboarding client secrets in Key Vault at request time,
  # in addition to resolving keyvault:// references at sync time.
  role_definition_name             = "Key Vault Secrets Officer"
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true
}

# Update Manager installPatches is an ARM action on the target VM. Keep this
# grant at the application resource-group boundary so the governed execution
# identity can patch the managed VM estate it serves.
resource "azurerm_role_assignment" "apps_virtual_machine_contributor" {
  count                            = var.enable_role_assignments ? 1 : 0
  scope                            = azurerm_resource_group.main.id
  role_definition_name             = "Virtual Machine Contributor"
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true
}

# The execution identity may only read and update Defender pricing resources.
# It cannot issue arbitrary ARM writes or mutate protected workloads.
resource "azurerm_role_definition" "apps_defender_configuration" {
  count = var.enable_defender_configuration_execution && var.enable_role_assignments ? 1 : 0

  name  = "${local.base}-defender-configuration-operator"
  scope = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"

  permissions {
    actions = [
      "Microsoft.Security/pricings/read",
      "Microsoft.Security/pricings/write",
    ]
    not_actions = []
  }

  assignable_scopes = [
    "/subscriptions/${data.azurerm_client_config.current.subscription_id}",
  ]
}

resource "azurerm_role_assignment" "apps_defender_configuration" {
  count = var.enable_defender_configuration_execution && var.enable_role_assignments ? 1 : 0

  scope                            = "/subscriptions/${data.azurerm_client_config.current.subscription_id}"
  role_definition_id               = azurerm_role_definition.apps_defender_configuration[0].role_definition_resource_id
  principal_id                     = azurerm_user_assigned_identity.apps.principal_id
  skip_service_principal_aad_check = true
}
