variable "enable_inventory_publication_job" {
  description = "Create the dedicated registered-connection inventory acquisition and Fabric publication job."
  type        = bool
  default     = false
}

variable "inventory_publication_schedule" {
  description = "UTC cron for inventory publication; empty keeps the job manual until initial publication is verified."
  type        = string
  default     = ""
}

variable "inventory_publication_image_digest" {
  description = "Optional immutable API image digest for this producer only; empty preserves the discovery image selection."
  type        = string
  default     = ""
  nullable    = false

  validation {
    condition     = var.inventory_publication_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.inventory_publication_image_digest))
    error_message = "inventory_publication_image_digest must be empty or a sha256 digest."
  }
}

variable "inventory_publication_native_registry_mapping" {
  description = "Publish the qualified native registry pair table without enabling legacy Ontology definition writes."
  type        = bool
  default     = false
  nullable    = false
}

variable "inventory_publication_graph_refresh_target" {
  description = "Optional reviewed workspace and GraphModel UUIDs for the bounded post-publication refresh chain; null disables it."
  type = object({
    workspace_id   = string
    graph_model_id = string
  })
  default = null

  validation {
    condition = var.inventory_publication_graph_refresh_target == null ? true : alltrue([
      for id in [var.inventory_publication_graph_refresh_target.workspace_id, var.inventory_publication_graph_refresh_target.graph_model_id] :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", id))
    ])
    error_message = "inventory_publication_graph_refresh_target requires both workspace_id and graph_model_id UUIDs."
  }
}

locals {
  inventory_publication_image = var.inventory_publication_image_digest != "" ? "${local.registry_server}/${var.api_image_repository}@${var.inventory_publication_image_digest}" : local.ontology_discovery_image
  inventory_publication_runtime_config = var.enable_fabric ? merge(local.fabric_publisher_runtime_config, {
    table_schema = var.inventory_publication_native_registry_mapping ? "" : local.fabric_publisher_runtime_config.table_schema
    ontology = merge(local.fabric_publisher_runtime_config.ontology, {
      enabled                 = var.inventory_publication_native_registry_mapping ? false : local.fabric_publisher_runtime_config.ontology.enabled
      ontology_id             = var.inventory_publication_native_registry_mapping ? "" : local.fabric_publisher_runtime_config.ontology.ontology_id
      native_registry_mapping = var.inventory_publication_native_registry_mapping
    })
  }) : null
  inventory_publication_graph_refresh_env = var.inventory_publication_graph_refresh_target == null ? {} : {
    AIOPS_GRAPH_REFRESH_WORKSPACE_ID   = var.inventory_publication_graph_refresh_target.workspace_id
    AIOPS_GRAPH_REFRESH_GRAPH_MODEL_ID = var.inventory_publication_graph_refresh_target.graph_model_id
  }
}

resource "azurerm_role_assignment" "inventory_publisher_key_vault" {
  count = var.enable_fabric && var.enable_inventory_publication_job ? 1 : 0

  scope                            = azurerm_key_vault.main.id
  role_definition_name             = "Key Vault Secrets User"
  principal_id                     = azurerm_user_assigned_identity.ontology_publisher.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_container_app_job" "inventory_publication" {
  count = var.enable_fabric && var.enable_inventory_publication_job ? 1 : 0

  name                         = "${local.base}-inventory-publication"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 3600
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ontology_publisher.id]
  }

  dynamic "secret" {
    for_each = var.enable_role_assignments ? [] : [1]
    content {
      name  = "acr-password"
      value = azurerm_container_registry.main.admin_password
    }
  }

  registry {
    server               = local.registry_server
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.ontology_publisher.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
  }

  dynamic "manual_trigger_config" {
    for_each = var.inventory_publication_schedule == "" ? [1] : []
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }

  dynamic "schedule_trigger_config" {
    for_each = var.inventory_publication_schedule != "" ? [1] : []
    content {
      cron_expression          = var.inventory_publication_schedule
      parallelism              = 1
      replica_completion_count = 1
    }
  }

  template {
    container {
      name    = "inventory-publication"
      image   = local.inventory_publication_image
      cpu     = 2
      memory  = "4Gi"
      command = ["python", "-m", "intelligence.inventory.publication_cli"]

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.client_id
      }
      env {
        name  = "AIOPS_HOME"
        value = local.onelake_aiops_home
      }
      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = local.ontology_connection_home
      }
      env {
        name  = "AIOPS_CONNECTOR_OUTPUT_DIR"
        value = local.onelake_aiops_home
      }
      env {
        name  = "AIOPS_CONFIG_PATH"
        value = "/app/config.yaml"
      }
      env {
        name  = "AIOPS_FABRIC_CONFIG"
        value = "/app/fabric.config.yaml"
      }
      env {
        name  = "AIOPS_FABRIC_CONFIG_JSON"
        value = jsonencode({ fabric = local.inventory_publication_runtime_config })
      }
      env {
        name  = "AIOPS_IDENTITY_CLASS"
        value = "publisher"
      }
      dynamic "env" {
        for_each = local.inventory_publication_graph_refresh_env
        content {
          name  = env.key
          value = env.value
        }
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.inventory_publisher_key_vault,
    fabric_workspace_role_assignment.ontology_publisher_tables,
  ]
  tags = local.tags
}
