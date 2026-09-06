# ---------------------------------------------------------------------------
# Autonomous ontology discovery coordinator
#
# This is a finite, schedule-triggered worker.  It deliberately uses its own
# managed identity rather than the API identity or the ontology publisher
# identity, and it owns no authoritative stage or active-pointer role.
# ---------------------------------------------------------------------------

variable "ontology_discovery_schedule" {
  description = "Five-field UTC cron expression for the finite ontology discovery coordinator."
  type        = string
  default     = "*/15 * * * *"

  validation {
    condition     = length(split(" ", trimspace(var.ontology_discovery_schedule))) == 5
    error_message = "ontology_discovery_schedule must be a five-field UTC cron expression."
  }
}

locals {
  ontology_discovery_image = var.ontology_discovery_image_tag != "" ? "${local.registry_server}/${var.api_image_repository}:${var.ontology_discovery_image_tag}" : local.api_image
}

resource "azurerm_user_assigned_identity" "ontology_coordinator" {
  name                = "${local.base}-ontology-coordinator-id"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "ontology_coordinator_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.ontology_coordinator.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_container_app_job" "ontology_discovery" {
  name                         = "${local.base}-ontology-discovery"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"

  # One bounded pass must terminate before the next ordinary cadence.  The
  # retry budget is intentionally finite so a poisoned run cannot produce an
  # unbounded job storm.
  replica_timeout_in_seconds = 900
  replica_retry_limit        = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ontology_coordinator.id]
  }

  registry {
    server   = local.registry_server
    identity = azurerm_user_assigned_identity.ontology_coordinator.id
  }

  schedule_trigger_config {
    cron_expression          = var.ontology_discovery_schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "ontology-discovery"
      image  = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu    = var.api_cpu
      memory = var.api_memory

      command = [
        "python",
        "-m",
        "ontology_discovery.cli",
      ]
      args = [
        "run-once",
        "--limit",
        "10",
      ]

      env {
        name  = "AIOPS_HOME"
        value = var.enable_fabric ? "abfss://${fabric_workspace.ontology_discovery_state[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_discovery_state[0].id}/Files/aiops" : "/tmp/aiops"
      }

      env {
        name  = "AIOPS_ONTOLOGY_IDENTITY_CLASS"
        value = "coordinator"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_coordinator.client_id
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_coordinator_state,
  ]
}

# ---------------------------------------------------------------------------
# Manual-only live authorization validator
#
# ManagedIdentityCredential can select a user-assigned identity only when that
# identity is attached to the executing Azure resource. This bounded Job is
# therefore the validation runtime for the API, coordinator, and publisher
# identities. It has no schedule, ingress, AIOps runtime mode, or publisher
# credential environment variable. The curator remains deliberately
# unattached: its denial is proven by live workspace-role absence plus its
# deployed four-tool read-only Foundry definition.
# ---------------------------------------------------------------------------

resource "azurerm_container_app_job" "ontology_rbac_validation" {
  count = var.enable_fabric ? 1 : 0

  name                         = "${local.base}-ontology-rbac-check"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0

  identity {
    type = "UserAssigned"
    identity_ids = [
      azurerm_user_assigned_identity.apps.id,
      azurerm_user_assigned_identity.ontology_coordinator.id,
      azurerm_user_assigned_identity.ontology_publisher.id,
    ]
  }

  registry {
    server   = local.registry_server
    identity = azurerm_user_assigned_identity.ontology_coordinator.id
  }

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "ontology-rbac-validation"
      image  = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu    = var.api_cpu
      memory = var.api_memory

      command = [
        "python",
        "/app/scripts/validate_ontology_publisher_rbac.py",
      ]
      args = [
        "--non-production",
        "--fail-on-missing-evidence",
      ]

      env {
        name  = "AIOPS_ONTOLOGY_API_CLIENT_ID"
        value = azurerm_user_assigned_identity.apps.client_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_API_OBJECT_ID"
        value = azurerm_user_assigned_identity.apps.principal_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_COORDINATOR_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_coordinator.client_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_COORDINATOR_OBJECT_ID"
        value = azurerm_user_assigned_identity.ontology_coordinator.principal_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.client_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_PUBLISHER_OBJECT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.principal_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_CURATOR_OBJECT_ID"
        value = azurerm_cognitive_account_project.ops.identity[0].principal_id
      }

      env {
        name  = "AIOPS_ONTOLOGY_WORKSPACE_ID"
        value = fabric_workspace.ontology_rbac_validation[0].id
      }

      env {
        name  = "AIOPS_ONTOLOGY_NON_PRODUCTION"
        value = "true"
      }

      env {
        name  = "AIOPS_ONTOLOGY_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_rbac_validation[0].id
      }

      env {
        name  = "FOUNDRY_PROJECT_ENDPOINT"
        value = local.foundry_project_endpoint
      }

      env {
        name  = "FOUNDRY_ONTOLOGY_CURATOR_AGENT_NAME"
        value = local.ontology_curator_agent_name
      }

      env {
        name  = "FOUNDRY_ONTOLOGY_CURATOR_PROMPT_SHA256"
        value = sha256(local.ontology_curator_prompt)
      }

      env {
        name  = "FOUNDRY_ONTOLOGY_CURATOR_MODEL"
        value = var.foundry_model_name
      }
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_publisher,
    terraform_data.foundry_ontology_curator_agent,
  ]
}
