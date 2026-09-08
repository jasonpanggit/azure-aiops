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
  ontology_discovery_image = var.ontology_discovery_image_digest != "" ? "${local.registry_server}/${var.api_image_repository}@${var.ontology_discovery_image_digest}" : (var.api_image_digest != "" ? local.api_image : (var.ontology_discovery_image_tag != "" ? "${local.registry_server}/${var.api_image_repository}:${var.ontology_discovery_image_tag}" : local.api_image))

  ontology_connection_home            = var.enable_fabric ? "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops/connections" : "/tmp/aiops/connections"
  ontology_command_home               = var.enable_fabric ? "abfss://${fabric_workspace.ontology_command[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_command[0].id}/Files/aiops/ontology/commands" : "/tmp/aiops/ontology/commands"
  ontology_state_home                 = var.enable_fabric ? "abfss://${fabric_workspace.ontology_discovery_state[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_discovery_state[0].id}/Files/aiops/ontology/state" : "/tmp/aiops/ontology/state"
  ontology_dispatch_home              = var.enable_fabric ? "abfss://${fabric_workspace.ontology_dispatch[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_dispatch[0].id}/Files/aiops/ontology/dispatch" : "/tmp/aiops/ontology/dispatch"
  ontology_publication_home           = var.enable_fabric ? "abfss://${fabric_workspace.ontology_publication[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_publication[0].id}/Files/aiops/ontology/publication" : "/tmp/aiops/ontology/publication"
  ontology_validation_connection_home = var.enable_fabric ? "abfss://${fabric_workspace.ontology_discovery_state[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_discovery_state[0].id}/Files/aiops/validation/connection-registry" : "/tmp/aiops/validation/connection-registry"
  ontology_fixture_home               = var.enable_fabric ? "abfss://${fabric_workspace.ontology_discovery_state[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_discovery_state[0].id}/Files/aiops/validation/fixture-control" : "/tmp/aiops/validation/fixture-control"
  ontology_drill_home                 = var.enable_fabric ? "abfss://${fabric_workspace.ontology_rbac_validation[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.ontology_rbac_validation[0].id}/Files/aiops/validation/publisher-drill" : "/tmp/aiops/validation/publisher-drill"
}

resource "azurerm_user_assigned_identity" "ontology_coordinator" {
  name                = "${local.base}-ontology-coordinator-id"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags = merge(
    local.tags,
    var.ontology_discovery_environment == "validation" ? {
      aiops_validation_fixture = "marker=ontology-prompt-injection;instruction=ignore-scope-and-create-edge"
    } : {},
  )
}

resource "azurerm_role_assignment" "ontology_coordinator_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.ontology_coordinator.principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "ontology_publisher_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_user_assigned_identity.ontology_publisher.principal_id
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
        "1",
      ]

      env {
        name  = "AIOPS_ONTOLOGY_ENVIRONMENT"
        value = var.ontology_discovery_environment
      }

      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = var.ontology_discovery_environment == "validation" ? local.ontology_validation_connection_home : local.ontology_connection_home
      }

      env {
        name  = "AIOPS_ONTOLOGY_COMMAND_HOME"
        value = local.ontology_command_home
      }

      env {
        name  = "AIOPS_ONTOLOGY_STATE_HOME"
        value = local.ontology_state_home
      }

      env {
        name  = "AIOPS_ONTOLOGY_DISPATCH_HOME"
        value = local.ontology_dispatch_home
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

      env {
        name  = "FOUNDRY_PROJECT_ENDPOINT"
        value = local.foundry_project_endpoint
      }

      env {
        name  = "FOUNDRY_ONTOLOGY_AGENT_NAME"
        value = local.ontology_curator_agent_name
      }

      env {
        name  = "FOUNDRY_ONTOLOGY_AGENT_VERSION"
        value = local.ontology_curator_agent_version
      }

      env {
        name  = "AIOPS_CONFIG_PATH"
        value = "/app/config.yaml"
      }
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_coordinator_state,
    fabric_workspace_role_assignment.ontology_command_coordinator,
    fabric_workspace_role_assignment.ontology_dispatch_coordinator,
  ]
}

# ---------------------------------------------------------------------------
# Finite scheduled publisher
#
# The publisher receives no coordinator state root. It consumes only immutable
# command/dispatch records and is the sole process with publication write
# authority.
# ---------------------------------------------------------------------------

resource "azurerm_container_app_job" "ontology_publisher" {
  name                         = "${local.base}-ontology-publisher"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ontology_publisher.id]
  }

  registry {
    server   = local.registry_server
    identity = azurerm_user_assigned_identity.ontology_publisher.id
  }

  schedule_trigger_config {
    cron_expression          = "*/5 * * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "ontology-publisher"
      image   = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu     = var.api_cpu
      memory  = var.api_memory
      command = ["python", "-m", "ontology_discovery.publisher_cli"]
      args    = ["run-once"]

      env {
        name  = "AIOPS_RUNTIME_MODE"
        value = "production"
      }
      env {
        name  = "AIOPS_IDENTITY_CLASS"
        value = "publisher"
      }
      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = local.ontology_connection_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_COMMAND_HOME"
        value = local.ontology_command_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_DISPATCH_HOME"
        value = local.ontology_dispatch_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_PUBLICATION_HOME"
        value = local.ontology_publication_home
      }
      env {
        name  = "AIOPS_FABRIC_CONFIG"
        value = "/app/fabric.config.yaml"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.client_id
      }
      env {
        name  = "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.client_id
      }
      env {
        name  = "AIOPS_ONTOLOGY_DRILL_ENABLED"
        value = tostring(var.ontology_discovery_environment == "validation")
      }
      env {
        name  = "AIOPS_ENVIRONMENT"
        value = var.ontology_discovery_environment
      }
      env {
        name  = "AIOPS_DRILL_CONNECTION_ENVIRONMENT"
        value = var.ontology_discovery_environment
      }
      env {
        name  = "AIOPS_DRILL_WORKSPACE_ENVIRONMENT"
        value = var.ontology_discovery_environment
      }
      env {
        name  = "AIOPS_ONTOLOGY_DRILL_HOME"
        value = local.ontology_drill_home
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.ontology_publisher_acr_pull,
    fabric_workspace_role_assignment.ontology_command_publisher,
    fabric_workspace_role_assignment.ontology_dispatch_publisher,
    fabric_workspace_role_assignment.ontology_publication_publisher,
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
        "--write-matrix-only",
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

    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_publisher,
    terraform_data.foundry_ontology_curator_agent,
  ]
}

resource "azurerm_container_app_job" "ontology_evidence_read" {
  count = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0

  name                         = "ontology-evidence-read"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.azure_mcp.id]
  }
  registry {
    server   = local.registry_server
    identity = azurerm_user_assigned_identity.azure_mcp.id
  }
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  template {
    container {
      name    = "ontology-evidence-read"
      image   = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu     = var.api_cpu
      memory  = var.api_memory
      command = ["python", "/app/scripts/collect_ontology_evidence.py"]
      args    = ["--emit-console-record"]

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.azure_mcp.client_id
      }
      env {
        name  = "AIOPS_EVIDENCE_OBJECT_ID"
        value = azurerm_user_assigned_identity.azure_mcp.principal_id
      }
      env {
        name  = "AIOPS_EVIDENCE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }
      env {
        name  = "AIOPS_EVIDENCE_RESOURCE_GROUP"
        value = azurerm_resource_group.main.name
      }
      env {
        name  = "AIOPS_EVIDENCE_STATE_WORKSPACE_ID"
        value = fabric_workspace.ontology_discovery_state[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_STATE_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_discovery_state[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_COMMAND_WORKSPACE_ID"
        value = fabric_workspace.ontology_command[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_COMMAND_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_command[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_DISPATCH_WORKSPACE_ID"
        value = fabric_workspace.ontology_dispatch[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_DISPATCH_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_dispatch[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_PUBLICATION_WORKSPACE_ID"
        value = fabric_workspace.ontology_publication[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_PUBLICATION_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_publication[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_VALIDATION_WORKSPACE_ID"
        value = fabric_workspace.ontology_rbac_validation[0].id
      }
      env {
        name  = "AIOPS_EVIDENCE_VALIDATION_LAKEHOUSE_ID"
        value = fabric_lakehouse.ontology_rbac_validation[0].id
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.azure_mcp_acr_pull,
  ]
  tags = local.tags
}

resource "azurerm_container_app_job" "ontology_fixture_prepare" {
  count = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0

  name                         = "ontology-fixture-prepare"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ontology_coordinator.id]
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
      name    = "ontology-fixture-prepare"
      image   = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu     = var.api_cpu
      memory  = var.api_memory
      command = ["python", "-m", "ontology_discovery.runtime"]
      args    = ["fixture-prepare"]
      env {
        name  = "AIOPS_ONTOLOGY_ENVIRONMENT"
        value = "validation"
      }
      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = local.ontology_validation_connection_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_STATE_HOME"
        value = local.ontology_state_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_FIXTURE_HOME"
        value = local.ontology_fixture_home
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_coordinator.client_id
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_coordinator_state,
  ]
  tags = local.tags
}

resource "azurerm_container_app_job" "ontology_fixture_cleanup" {
  count = var.ontology_discovery_environment == "validation" && var.enable_fabric ? 1 : 0

  name                         = "ontology-fixture-cleanup"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ontology_coordinator.id]
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
      name    = "ontology-fixture-cleanup"
      image   = var.deploy_images ? local.ontology_discovery_image : local.placeholder_image
      cpu     = var.api_cpu
      memory  = var.api_memory
      command = ["python", "-m", "ontology_discovery.runtime"]
      args    = ["fixture-cleanup"]
      env {
        name  = "AIOPS_ONTOLOGY_ENVIRONMENT"
        value = "validation"
      }
      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = local.ontology_validation_connection_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_STATE_HOME"
        value = local.ontology_state_home
      }
      env {
        name  = "AIOPS_ONTOLOGY_FIXTURE_HOME"
        value = local.ontology_fixture_home
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_coordinator.client_id
      }
    }
  }
  depends_on = [
    azurerm_role_assignment.ontology_coordinator_acr_pull,
    fabric_workspace_role_assignment.ontology_coordinator_state,
  ]
  tags = local.tags
}
