variable "subscription_id" {
  description = "Explicit reviewed subscription; no environment-derived target."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be an explicit UUID."
  }
}

variable "tenant_id" {
  description = "Explicit reviewed Entra tenant."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be an explicit UUID."
  }
}

variable "enable" {
  description = "Provision preparatory resources only; never enables publication or qualifies the backend."
  type        = bool
  default     = false
  nullable    = false

  validation {
    condition     = !var.enable || (var.settings != null && var.reviewed_config_sha256 != null)
    error_message = "Enabling requires complete settings and a separately declared reviewed_config_sha256."
  }
}

variable "reviewed_config_sha256" {
  description = "Separately declared SHA256 of jsonencode(settings), not an authenticated approval or execution grant."
  type        = string
  default     = null

  validation {
    condition = var.reviewed_config_sha256 == null ? true : try(
      can(regex("^[0-9a-f]{64}$", var.reviewed_config_sha256)) &&
      var.reviewed_config_sha256 == sha256(jsonencode(var.settings)), false
    )
    error_message = "reviewed_config_sha256 must match the complete typed settings, without observation fallback."
  }
}

variable "settings" {
  description = "Operator-reviewed isolated names, placement, capacity, retention and private network. No production resource IDs."
  type = object({
    name_prefix               = string
    location                  = string
    sql_server_name           = string
    sql_database_name         = string
    sql_sku                   = string
    sql_max_size_gb           = number
    sql_backup_retention_days = number
    sql_admin_group_name      = string
    sql_admin_group_object_id = string
    storage_account_name      = string
    storage_replication       = string
    artifact_container_name   = string
    retention_days            = number
    policy_state              = string
    private_connectivity      = string
    virtual_network_cidr      = string
    registry_id               = string
    registry_server           = string
    scaffold_image            = string
  })
  default = null

  validation {
    condition = var.settings == null ? true : try(alltrue([
      can(regex("^[a-z][a-z0-9-]{1,12}[a-z0-9]$", var.settings.name_prefix)),
      can(regex("^[a-z][a-z0-9]+$", var.settings.location)),
      can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.settings.sql_server_name)),
      can(regex("^[a-zA-Z][a-zA-Z0-9_-]{0,62}$", var.settings.sql_database_name)),
      can(regex("^[a-z0-9]{3,24}$", var.settings.storage_account_name)),
      can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.settings.artifact_container_name)),
      !strcontains(var.settings.artifact_container_name, "--"),
      trimspace(var.settings.sql_admin_group_name) != "",
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.settings.sql_admin_group_object_id)),
    ]), false)
    error_message = "Provide explicit valid isolated names, Azure region code and a separate operator Entra admin group."
  }

  validation {
    condition = var.settings == null ? true : try(alltrue([
      contains(["S0", "S1", "S2", "GP_Gen5_2", "GP_Gen5_4"], var.settings.sql_sku),
      var.settings.sql_max_size_gb >= 1,
      var.settings.sql_max_size_gb == floor(var.settings.sql_max_size_gb),
      contains([7, 14, 21, 28, 35], var.settings.sql_backup_retention_days),
      contains(["LRS", "ZRS"], var.settings.storage_replication),
      var.settings.retention_days >= 1,
      var.settings.retention_days <= 146000,
      var.settings.retention_days == floor(var.settings.retention_days),
      var.settings.policy_state == "Unlocked",
    ]), false)
    error_message = "Explicit supported SQL/storage capacity and integer retention are required; this preparatory root supports only an Unlocked draft policy."
  }

  validation {
    condition = var.settings == null ? true : try(alltrue([
      var.settings.private_connectivity == "isolated-vnet-private-endpoints",
      can(regex("^(10\\.[0-9]+|172\\.(1[6-9]|2[0-9]|3[01])|192\\.168)\\.0\\.0/16$", var.settings.virtual_network_cidr)),
      cidrhost(var.settings.virtual_network_cidr, 0) == split("/", var.settings.virtual_network_cidr)[0],
      can(regex("^/subscriptions/${var.subscription_id}/resourceGroups/[^/]+/providers/Microsoft.ContainerRegistry/registries/[A-Za-z0-9]+$", var.settings.registry_id)),
      can(regex("^[a-z0-9]+\\.azurecr\\.io$", var.settings.registry_server)),
      lower(split("/", var.settings.registry_id)[8]) == split(".", var.settings.registry_server)[0],
      can(regex("^${replace(var.settings.registry_server, ".", "\\.")}/[a-z0-9/_-]+@sha256:[0-9a-f]{64}$", var.settings.scaffold_image)),
    ]), false)
    error_message = "Require an explicit canonical private /16, isolated private-endpoint mode and matching same-subscription ACR ID/server/digest-pinned scaffold image."
  }
}
