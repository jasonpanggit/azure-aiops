# ---------------------------------------------------------------------------
# Container Apps: the API and the web workbench.
# ---------------------------------------------------------------------------

locals {
  registry_server = azurerm_container_registry.main.login_server

  api_image = "${local.registry_server}/${var.api_image_repository}:${var.image_tag}"
  web_image = "${local.registry_server}/${var.web_image_repository}:${var.image_tag}"

  # Placeholder used before the real images exist in the registry. Container
  # Apps requires an image at creation time, and a first apply necessarily
  # precedes the first push.
  placeholder_image = "mcr.microsoft.com/k8se/quickstart:latest"

  # Container app FQDNs are `<app name>.<environment default domain>`. Deriving
  # them from the environment rather than from the app resources is what lets
  # each app know the other's URL: referencing the peer's computed fqdn would
  # make the two apps mutually dependent and fail with a cycle.
  api_fqdn = "${local.base}-api.${azurerm_container_app_environment.main.default_domain}"
  web_fqdn = "${local.base}-web.${azurerm_container_app_environment.main.default_domain}"

  api_base_url = "https://${local.api_fqdn}"
  web_base_url = "https://${local.web_fqdn}"
}

resource "azurerm_container_app_environment" "main" {
  name                = "${local.base}-cae"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location

  # Not computed in the 5.x provider: it must be set explicitly before
  # log_analytics_workspace_id is accepted.
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.container_apps.id

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

resource "azurerm_container_app" "api" {
  name                         = "${local.base}-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  workload_profile_name = "Consumption"

  registry {
    server = local.registry_server
    # Must be a user-assigned identity that is also on the app's identity
    # block; a system-assigned identity cannot be referenced here.
    identity = azurerm_user_assigned_identity.apps.id
  }

  dynamic "secret" {
    for_each = var.nvd_api_key != "" ? [var.nvd_api_key] : []
    content {
      name  = "nvd-api-key"
      value = secret.value
    }
  }

  dynamic "secret" {
    for_each = var.refresh_trigger_secret != "" ? [var.refresh_trigger_secret] : []
    content {
      name  = "refresh-trigger-secret"
      value = secret.value
    }
  }

  ingress {
    external_enabled = var.api_external_ingress
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.api_min_replicas
    max_replicas = var.api_max_replicas

    container {
      name   = "api"
      image  = var.deploy_images ? local.api_image : local.placeholder_image
      cpu    = var.api_cpu
      memory = var.api_memory

      env {
        name  = "HERMES_API_AUTH"
        value = "entra"
      }

      env {
        name  = "HERMES_ENTRA_TENANT_ID"
        value = var.tenant_id
      }

      env {
        name  = "HERMES_ENTRA_AUDIENCE"
        value = var.entra_api_audience
      }

      env {
        name  = "HERMES_API_GATEWAY_GRANTS"
        value = var.entra_grants_json
      }

      # The browser calls the API cross-origin from the web app's own domain.
      env {
        name  = "HERMES_API_CORS_ORIGINS"
        value = local.web_base_url
      }

      # All durable state lives in OneLake, so HERMES_HOME points at the
      # Fabric lakehouse. Fabric is therefore required in production; with
      # var.enable_fabric = false the API falls back to container-local disk,
      # which does not survive a revision.
      env {
        name  = "HERMES_HOME"
        value = var.enable_fabric ? "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/hermes" : "/tmp/hermes"
      }

      env {
        name  = "HERMES_RUNTIME_MODE"
        value = "production"
      }

      env {
        name  = "HERMES_LOCAL_SEED"
        value = "0"
      }

      env {
        name  = "HERMES_ENABLE_FABRIC"
        value = tostring(var.enable_fabric)
      }

      env {
        name  = "FABRIC_WORKSPACE_ID"
        value = var.enable_fabric ? fabric_workspace.ops[0].id : ""
      }

      env {
        name  = "FABRIC_LAKEHOUSE_ID"
        value = var.enable_fabric ? fabric_lakehouse.context_graph[0].id : ""
      }

      env {
        name  = "FABRIC_ONTOLOGY_NAME"
        value = var.fabric_ontology_name
      }

      env {
        name  = "HERMES_PROVIDER_REFRESH_SECONDS"
        value = "30"
      }

      env {
        name  = "HERMES_PROVIDER_STALE_HOURS"
        value = "24"
      }

      # Lets the onboarding API store submitted client secrets in Key Vault
      # instead of the OneLake connection registry; requires Key Vault Secrets
      # Officer (write) on azurerm_role_assignment.kv_apps below.
      env {
        name  = "HERMES_CONNECTION_KEY_VAULT"
        value = local.key_vault_name
      }

      # Only enable the bootstrap sync when there is actually something to
      # sync -- akv_bootstrap.py raises at startup if enabled with an empty
      # secret map, which would crash the API. Since the persistence pivot to
      # OneLake there is no longer a default secret (previously the Postgres
      # connection string), so this is opt-in per environment.
      env {
        name  = "HERMES_AKV_BOOTSTRAP_ENABLED"
        value = var.akv_bootstrap_secrets_json == "{}" ? "false" : "true"
      }

      env {
        name  = "HERMES_AKV_BOOTSTRAP_SECRETS"
        value = var.akv_bootstrap_secrets_json
      }

      # Wires the Foundry prompt agent in as the Copilot's narration layer.
      # Absent these the API still answers from the knowledge layer, but
      # without prose.
      env {
        name  = "FOUNDRY_PROJECT_ENDPOINT"
        value = local.foundry_project_endpoint
      }

      env {
        name  = "FOUNDRY_AGENT_NAME"
        value = var.foundry_agent_name
      }

      # Selects the user-assigned identity for DefaultAzureCredential, which
      # would otherwise be ambiguous on a multi-identity app.
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.apps.client_id
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      dynamic "env" {
        for_each = var.nvd_api_key != "" ? [1] : []
        content {
          name        = "NVD_API_KEY"
          secret_name = "nvd-api-key"
        }
      }

      dynamic "env" {
        for_each = var.refresh_trigger_secret != "" ? [1] : []
        content {
          name        = "HERMES_REFRESH_TRIGGER_SECRET"
          secret_name = "refresh-trigger-secret"
        }
      }

      env {
        name  = "HERMES_ARG_CONFIG"
        value = "/app/config.yaml"
      }

      env {
        name  = "HERMES_FABRIC_CONFIG"
        value = "/app/fabric.config.yaml"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/health"
        # The knowledge snapshot is built at startup; probing too early would
        # restart the container mid-load.
        initial_delay = 20
        # /health can trigger a real OneLake read (see _load_snapshot_tables);
        # the default 1s timeout was too tight under real network latency and
        # caused CrashLoopBackOff even on a healthy container. Widen the
        # timeout and tolerate more consecutive failures before restarting.
        timeout                 = 10
        failure_count_threshold = 6
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = 8080
        path                    = "/ready"
        timeout                 = 10
        failure_count_threshold = 6
      }
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.kv_apps,
  ]
}

# ---------------------------------------------------------------------------
# Web workbench
# ---------------------------------------------------------------------------

resource "azurerm_container_app" "web" {
  name                         = "${local.base}-web"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  workload_profile_name = "Consumption"

  registry {
    server   = local.registry_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.web_min_replicas
    max_replicas = var.web_max_replicas

    container {
      name   = "web"
      image  = var.deploy_images ? local.web_image : local.placeholder_image
      cpu    = var.web_cpu
      memory = var.web_memory

      # Served to the browser at runtime by /api/config, so one image works in
      # every environment rather than being baked at build time.
      env {
        name  = "HERMES_API_BASE_URL"
        value = local.api_base_url
      }

      env {
        name  = "NODE_ENV"
        value = "production"
      }

      liveness_probe {
        transport     = "HTTP"
        port          = 3000
        path          = "/api/config"
        initial_delay = 10
      }

      readiness_probe {
        transport = "HTTP"
        port      = 3000
        path      = "/api/config"
      }
    }
  }

  tags = local.tags

  depends_on = [azurerm_role_assignment.acr_pull]
}
