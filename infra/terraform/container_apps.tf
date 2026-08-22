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

  secret {
    name  = "hermes-database-url"
    value = "postgresql://${azurerm_postgresql_flexible_server.hermes.administrator_login}:${random_password.postgres.result}@${azurerm_postgresql_flexible_server.hermes.fqdn}:5432/${azurerm_postgresql_flexible_server_database.hermes.name}?sslmode=require"
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

      env {
        name  = "HERMES_HOME"
        value = "abfss://${azurerm_storage_container.hermes_data.name}@${azurerm_storage_account.hermes_data.name}.dfs.core.windows.net/"
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
        value = "Operational_Context_Graph"
      }

      env {
        name  = "HERMES_PROVIDER_REFRESH_SECONDS"
        value = "30"
      }

      env {
        name  = "HERMES_PROVIDER_STALE_HOURS"
        value = "24"
      }

      env {
        name        = "HERMES_DATABASE_URL"
        secret_name = "hermes-database-url"
      }

      env {
        name  = "AZURE_STORAGE_ACCOUNT"
        value = azurerm_storage_account.hermes_data.name
      }

      # Lets the onboarding API store submitted client secrets in Key Vault
      # instead of the PostgreSQL registry; requires Key Vault Secrets Officer
      # (write) on azurerm_role_assignment.kv_apps below.
      env {
        name  = "HERMES_CONNECTION_KEY_VAULT"
        value = local.key_vault_name
      }

      env {
        name  = "HERMES_AKV_BOOTSTRAP_ENABLED"
        value = "true"
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

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/health"
        # The knowledge snapshot is built at startup; probing too early would
        # restart the container mid-load.
        initial_delay = 20
        # /health can trigger a real ADLS read (see _load_snapshot_tables);
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
    azurerm_role_assignment.hermes_data,
    azurerm_role_assignment.kv_apps,
    azurerm_postgresql_flexible_server_firewall_rule.azure_services,
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
