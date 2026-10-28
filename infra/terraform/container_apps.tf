# ---------------------------------------------------------------------------
# Container Apps: the API and the web workbench.
# ---------------------------------------------------------------------------

locals {
  registry_server = azurerm_container_registry.main.login_server
  gateway_assertion = coalesce(
    nonsensitive(var.apim_gateway_assertion),
    random_password.apim_gateway_assertion.result,
  )

  api_image = var.api_image_digest != "" ? "${local.registry_server}/${var.api_image_repository}@${var.api_image_digest}" : "${local.registry_server}/${var.api_image_repository}:${var.image_tag}"
  web_image = var.web_image_digest != "" ? "${local.registry_server}/${var.web_image_repository}@${var.web_image_digest}" : "${local.registry_server}/${var.web_image_repository}:${var.image_tag}"

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

  # Staged rollout of the canonical OrchestrationService (Plan 11-12 Task 2).
  #
  #   compatibility -> serve legacy projections, record canonical decisions
  #   shadow        -> compare canonical vs fallback without double-running
  #                    external tools/models or exposing any mutation
  #   canary        -> canonical default for a bounded traffic share, with an
  #                    automatic hold on any predetermined threshold failure
  #   default       -> canonical default for all traffic
  #
  # Canary traffic is bounded only in canary mode; every other permitted mode
  # is 0%. Rollback restores the prior revision/mode without rewriting threads
  # or ledgers, so the fallback mode is retained alongside the active mode.
  copilot_canary_percentage = (
    var.copilot_rollout_mode == "canary" ? var.copilot_canary_percentage :
    var.copilot_rollout_mode == "default" ? 100 : 0
  )
  # Deterministic rollback target: the governed page-anchored fallback that
  # remains selectable throughout Phase 11. Never a big-bang cutover.
  copilot_rollback_mode = "compatibility"
}

variable "copilot_rollout_mode" {
  description = "Staged rollout mode for the canonical Operations Copilot orchestrator: compatibility, shadow, canary, or default. Introduces the canonical service without a big-bang break and is reversible to the prior mode/revision."
  type        = string
  default     = "compatibility"

  validation {
    condition     = contains(["compatibility", "shadow", "canary", "default"], var.copilot_rollout_mode)
    error_message = "copilot_rollout_mode must be one of compatibility, shadow, canary, default."
  }
}

variable "copilot_canary_percentage" {
  description = "Bounded share of traffic the canonical orchestrator serves as default while copilot_rollout_mode is 'canary'. Ignored in other modes."
  type        = number
  default     = 10

  validation {
    condition     = var.copilot_canary_percentage >= 1 && var.copilot_canary_percentage <= 10
    error_message = "copilot_canary_percentage must be between 1 and 10."
  }
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

  workload_profile {
    name                  = "api-d4"
    workload_profile_type = "D4"
    minimum_count         = 0
    maximum_count         = 2
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
  revision_mode                = "Multiple"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  workload_profile_name = "api-d4"

  dynamic "secret" {
    for_each = var.enable_role_assignments ? [] : [1]
    content {
      name  = "acr-password"
      value = azurerm_container_registry.main.admin_password
    }
  }

  registry {
    server               = local.registry_server
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
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

  secret {
    name                = "cursor-active"
    value               = var.enable_role_assignments ? null : random_password.exposure_cursor["active"].result
    identity            = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    key_vault_secret_id = var.enable_role_assignments ? "${azurerm_key_vault.main.vault_uri}secrets/exposure-cursor-active" : null
  }

  secret {
    name                = "cursor-previous"
    value               = var.enable_role_assignments ? null : random_password.exposure_cursor["previous"].result
    identity            = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    key_vault_secret_id = var.enable_role_assignments ? "${azurerm_key_vault.main.vault_uri}secrets/exposure-cursor-previous" : null
  }

  dynamic "secret" {
    for_each = var.enable_sre_agent_patch_execution ? [var.sre_agent_http_trigger_secret_id] : []
    content {
      name                = "sre-agent-http-trigger-url"
      identity            = azurerm_user_assigned_identity.apps.id
      key_vault_secret_id = secret.value
    }
  }

  ingress {
    external_enabled = var.api_external_ingress
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      latest_revision = var.api_traffic_revision == ""
      revision_suffix = var.api_traffic_revision == "" ? null : trimprefix(var.api_traffic_revision, "${local.base}-api--")
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

      # APIM fronts only the governed MCP route, so "gateway" here does not
      # mean "every caller arrives via APIM". It selects an authenticator that
      # accepts a validated gateway assertion *or* a direct Entra token, since
      # the browser calls all non-MCP routes directly and the APIM inbound
      # policy strips the caller's Authorization header.
      env {
        name  = "AIOPS_API_AUTH"
        value = var.enable_apim ? "gateway" : "entra"
      }

      env {
        name  = "AIOPS_ENTRA_TENANT_ID"
        value = var.tenant_id
      }

      env {
        name  = "AIOPS_ENTRA_AUDIENCE"
        value = var.entra_api_audience
      }

      env {
        name  = "AIOPS_API_GATEWAY_GRANTS"
        value = jsonencode(merge(jsondecode(var.entra_grants_json), local.foundry_mcp_gateway_grants, local.foundry_specialist_identity_grants, local.ontology_evidence_gateway_grants))
      }

      # The browser calls the API cross-origin from the web app's own domain.
      env {
        name  = "AIOPS_API_CORS_ORIGINS"
        value = local.web_base_url
      }

      # All durable state lives in OneLake, so AIOPS_HOME points at the
      # Fabric lakehouse. Fabric is therefore required in production; with
      # var.enable_fabric = false the API falls back to container-local disk,
      # which does not survive a revision.
      env {
        name  = "AIOPS_HOME"
        value = local.onelake_aiops_home
      }

      env {
        name  = "AIOPS_CONNECTOR_OUTPUT_DIR"
        value = local.onelake_aiops_home
      }

      dynamic "env" {
        for_each = var.enable_fabric ? [1] : []
        content {
          name  = "AIOPS_FABRIC_CONFIG_JSON"
          value = jsonencode({ fabric = local.fabric_runtime_config })
        }
      }

      # The API receives exactly four ontology roots. It may read connection,
      # state, and publication data and create immutable command intake, but
      # it receives neither dispatch nor publisher credentials.
      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = local.ontology_connection_home
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
        name  = "AIOPS_ONTOLOGY_PUBLICATION_HOME"
        value = local.ontology_publication_home
      }

      dynamic "env" {
        for_each = var.fabric_native_ontology_target == null ? {} : {
          AIOPS_ONTOLOGY_NATIVE_WORKSPACE_ID = var.fabric_native_ontology_target.workspace_id
          AIOPS_ONTOLOGY_NATIVE_ITEM_ID      = var.fabric_native_ontology_target.item_id
        }
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "AIOPS_RUNTIME_MODE"
        value = var.enable_fabric ? "production" : "demo"
      }

      env {
        name  = "AIOPS_GATEWAY_ASSERTION"
        value = local.gateway_assertion
      }

      env {
        name  = "AIOPS_LOCAL_SEED"
        value = "0"
      }

      # Omit the write-mode variable unless SRE Agent execution is explicitly
      # enabled. The application then retains its fail-closed refusing default.
      dynamic "env" {
        for_each = var.enable_sre_agent_patch_execution ? [1] : []
        content {
          name  = "AIOPS_PATCH_EXECUTION"
          value = "sre-agent"
        }
      }

      dynamic "env" {
        for_each = var.enable_sre_agent_patch_execution ? [1] : []
        content {
          name        = "AIOPS_SRE_AGENT_TRIGGER_URL"
          secret_name = "sre-agent-http-trigger-url"
        }
      }

      dynamic "env" {
        for_each = var.enable_sre_agent_patch_execution ? {
          AIOPS_SRE_AGENT_SUBSCRIPTION_ID = local.sre_agent_subscription_id
          AIOPS_SRE_AGENT_TARGET_PREFIX   = var.sre_agent_patch_target_prefix
          AIOPS_SRE_AGENT_TRIGGER_ID      = var.sre_agent_trigger_id
          AIOPS_SRE_AGENT_TRIGGER_ORIGIN  = var.sre_agent_trigger_origin
          AIOPS_SRE_AGENT_TRIGGER_SCOPE   = var.sre_agent_trigger_scope
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.sre_agent_endpoint != "" ? {
          AIOPS_SRE_AGENT_ENDPOINT     = var.sre_agent_endpoint
          AIOPS_SRE_AGENT_THREAD_SCOPE = var.sre_agent_thread_scope
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      # Direct Defender writes remain a separate opt-in capability backed by
      # an explicit code-authored action catalog and approval snapshot.
      env {
        name  = "AIOPS_DEFENDER_CONFIGURATION_EXECUTION"
        value = var.enable_defender_configuration_execution ? "azure" : "disabled"
      }

      env {
        name  = "AIOPS_ENABLE_FABRIC"
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
        name  = "AIOPS_ENABLE_FABRIC_IQ"
        value = tostring(var.enable_fabric_iq)
      }

      # Canonical specialist metadata: one env pair per ACTIVATED specialist,
      # generated from local.foundry_specialist_activation (foundry.tf).
      #
      # This is deliberately NOT the candidate projection this plan would
      # publish: the activation map is either the previously validated,
      # promoted provider-ID mapping (gated by
      # terraform_data.foundry_specialist_promotion_gate, which this revision
      # depends on) or the deterministic legacy eight-agent rollback mapping.
      # A synthetic "<release>.<contract version>" candidate stamp can never
      # reach the running revision. for_each over a map yields a
      # deterministic, key-sorted ordering.
      dynamic "env" {
        for_each = local.foundry_specialist_activation
        content {
          name  = "FOUNDRY_${upper(env.key)}_AGENT_NAME"
          value = env.value.name
        }
      }

      dynamic "env" {
        for_each = {
          for id, agent in local.foundry_specialist_activation : id => agent
          if agent.version != ""
        }
        content {
          name  = "FOUNDRY_${upper(env.key)}_AGENT_VERSION"
          value = env.value.version
        }
      }

      # Which side of the promotion boundary this revision is running on.
      env {
        name  = "AIOPS_SPECIALIST_ACTIVATION_SOURCE"
        value = local.foundry_specialist_activation_source
      }

      env {
        name  = "AIOPS_FOUNDRY_VERSION_PINNING_REQUIRED"
        value = tostring(local.foundry_version_pinning_required)
      }

      env {
        name  = "AIOPS_PROVIDER_REFRESH_SECONDS"
        value = "30"
      }

      env {
        name  = "AIOPS_PROVIDER_STALE_HOURS"
        value = "24"
      }

      # Lets the onboarding API store submitted client secrets in Key Vault
      # instead of the OneLake connection registry; requires Key Vault Secrets
      # Officer (write) on azurerm_role_assignment.kv_apps below.
      env {
        name  = "AIOPS_CONNECTION_KEY_VAULT"
        value = local.key_vault_name
      }

      # Only enable the bootstrap sync when there is actually something to
      # sync -- akv_bootstrap.py raises at startup if enabled with an empty
      # secret map, which would crash the API. Since the persistence pivot to
      # OneLake there is no longer a default secret (previously the Postgres
      # connection string), so this is opt-in per environment.
      env {
        name  = "AIOPS_AKV_BOOTSTRAP_ENABLED"
        value = var.akv_bootstrap_secrets_json == "{}" ? "false" : "true"
      }

      env {
        name  = "AIOPS_AKV_BOOTSTRAP_SECRETS"
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
        value = local.foundry_coordinator_activation.name
      }

      dynamic "env" {
        for_each = var.foundry_use_agent_endpoints ? [1] : []
        content {
          name  = "FOUNDRY_USE_AGENT_ENDPOINTS"
          value = "true"
        }
      }

      dynamic "env" {
        for_each = local.foundry_coordinator_activation.version == "" ? [] : [local.foundry_coordinator_activation.version]
        content {
          name  = "FOUNDRY_AGENT_VERSION"
          value = env.value
        }
      }

      env {
        name  = "FOUNDRY_SPECIALISTS_JSON"
        value = jsonencode(local.foundry_specialist_activation)
      }

      # Identity of the contract this revision was built from. The parity
      # validator compares it to the manifest it loads, so a revision running
      # a different contract than the one that was reviewed is detectable
      # without shipping the manifest body through the environment.
      env {
        name  = "AIOPS_SPECIALIST_MANIFEST_PATH"
        value = "operations/specialists.v1.json"
      }

      env {
        name  = "AIOPS_SPECIALIST_MANIFEST_DIGEST"
        value = local.specialist_manifest_digest
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT"
          value = local.foundry_candidate_catalog_artifact_json
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_CANDIDATE_ARTIFACT_DIGEST"
          value = var.foundry_specialist_candidate_catalog_artifact_sha256
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_CANDIDATE_BINDING_DIGEST"
          value = var.foundry_specialist_candidate_binding_sha256
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_CANDIDATE_EXPECTED_NAMES"
          value = jsonencode(local.foundry_specialist_agent_names)
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_CANDIDATE_PROMPT_DIGESTS"
          value = jsonencode(var.foundry_specialist_candidate_prompt_digests)
        }
      }

      env {
        name  = "AIOPS_SOURCE_REVISION"
        value = var.deployment_source_revision
      }

      env {
        name  = "AIOPS_FOUNDRY_PROJECT_RESOURCE_ID"
        value = azurerm_cognitive_account_project.ops.id
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_MODEL_DEPLOYMENT"
          value = local.foundry_model_deployment_name
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_AI_SEARCH_CONNECTION_ID"
          value = var.enable_foundry_knowledge_search ? azapi_resource.foundry_ai_search_connection[0].id : ""
        }
      }

      dynamic "env" {
        for_each = local.foundry_candidate_catalog_artifact_present ? [1] : []
        content {
          name  = "AIOPS_FOUNDRY_AI_SEARCH_INDEX_NAME"
          value = var.foundry_knowledge_index_name
        }
      }

      # Compatibility window: the pre-manifest eight name/version pairs stay
      # visible so a rollback to the previously deployed specialist set does
      # not require a Terraform edit. Nothing reads this as authority.
      env {
        name  = "FOUNDRY_SPECIALISTS_LEGACY_JSON"
        value = jsonencode(var.foundry_specialists)
      }

      env {
        name  = "AIOPS_AGENT_ORCHESTRATION_MODE"
        value = lower(var.agent_orchestration_mode)
      }

      # Staged rollout controls for the canonical orchestrator (Plan 11-12).
      # The application reads the mode to serve compatibility/shadow/canary/
      # default behaviour at the request boundary -- shadow compares decisions
      # without double-running tools/models, canary defaults canonical for a
      # bounded traffic share and holds automatically on any predetermined
      # threshold failure, and rollback flips back to the retained fallback
      # mode without rewriting threads or ledgers.
      env {
        name  = "AIOPS_COPILOT_ROLLOUT_MODE"
        value = var.copilot_rollout_mode
      }

      env {
        name  = "AIOPS_COPILOT_CANARY_PERCENTAGE"
        value = tostring(local.copilot_canary_percentage)
      }

      env {
        name  = "AIOPS_COPILOT_ROLLBACK_MODE"
        value = local.copilot_rollback_mode
      }

      env {
        name  = "AIOPS_API_IMAGE_DIGEST"
        value = var.api_image_digest
      }

      env {
        name  = "AIOPS_DEPLOYMENT_TENANT_ID"
        value = var.tenant_id
      }

      env {
        name  = "AIOPS_DEPLOYMENT_SUBSCRIPTION_ID"
        value = var.subscription_id
      }

      env {
        name  = "AIOPS_DEPLOYMENT_RESOURCE_GROUP"
        value = azurerm_resource_group.main.name
      }

      env {
        name  = "AIOPS_DEPLOYMENT_APP"
        value = "${local.base}-api"
      }

      env {
        name  = "AIOPS_DEPLOYMENT_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "AIOPS_DEPLOYMENT_REGION"
        value = azurerm_resource_group.main.location
      }

      env {
        name  = "AIOPS_FOUNDRY_PROJECT_NAME"
        value = local.foundry_project_name
      }

      env {
        name  = "AIOPS_FOUNDRY_ACCOUNT_ENDPOINT"
        value = "https://${local.foundry_subdomain}.services.ai.azure.com"
      }

      env {
        name  = "AIOPS_COPILOT_CANDIDATE_RELEASE"
        value = var.foundry_specialist_release
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
          name        = "AIOPS_REFRESH_TRIGGER_SECRET"
          secret_name = "refresh-trigger-secret"
        }
      }

      env {
        name        = "EXPOSURE_CURSOR_ACTIVE_KEY"
        secret_name = "cursor-active"
      }

      env {
        name        = "EXPOSURE_CURSOR_PREVIOUS_KEY"
        secret_name = "cursor-previous"
      }

      # Staged Exposure v2 controls are non-secret deployment metadata.
      # Every lane defaults off and runtime validation refuses a non-off
      # stage unless the deployment authorization and immutable generation
      # pointers are explicit. Rollback changes only the selected pointer.
      env {
        name  = "AIOPS_EXPOSURE_ROLLOUT_AUTHORIZED"
        value = tostring(var.exposure_rollout_authorized)
      }

      env {
        name  = "AIOPS_EXPOSURE_WRITE_STAGE"
        value = lower(var.exposure_write_stage)
      }

      env {
        name  = "AIOPS_EXPOSURE_READ_STAGE"
        value = lower(var.exposure_read_stage)
      }

      env {
        name  = "AIOPS_EXPOSURE_WEB_STAGE"
        value = lower(var.exposure_web_stage)
      }

      env {
        name  = "AIOPS_EXPOSURE_HANDOFF_STAGE"
        value = lower(var.exposure_handoff_stage)
      }

      env {
        name  = "AIOPS_EXPOSURE_WRITE_GENERATION_ID"
        value = var.exposure_write_generation_id
      }

      env {
        name  = "AIOPS_EXPOSURE_READ_GENERATION_ID"
        value = var.exposure_read_generation_id
      }

      env {
        name  = "AIOPS_EXPOSURE_ROLLBACK_GENERATION_ID"
        value = var.exposure_rollback_generation_id
      }

      # Key identifiers are routing metadata, not key material. The rotation
      # script updates these values when it creates a new revision.
      env {
        name  = "EXPOSURE_CURSOR_ACTIVE_KID"
        value = var.exposure_cursor_active_kid
      }

      env {
        name  = "EXPOSURE_CURSOR_PREVIOUS_KID"
        value = var.exposure_cursor_previous_kid
      }

      env {
        name  = "AIOPS_ARG_CONFIG"
        value = "/app/config.yaml"
      }

      env {
        name  = "AIOPS_FABRIC_CONFIG"
        value = var.enable_fabric ? "/app/fabric.config.yaml" : ""
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8080
        path      = "/health"
        # The knowledge snapshot is built at startup; probing too early would
        # restart the container mid-load.
        initial_delay = 60
        # /health can trigger a real OneLake read (see _load_snapshot_tables);
        # the default 1s timeout was too tight under real network latency and
        # caused CrashLoopBackOff even on a healthy container. Widen the
        # timeout and tolerate more consecutive failures before restarting.
        timeout                 = 10
        interval_seconds        = 30
        failure_count_threshold = 30
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
    # The active revision may only come up behind a satisfied parity gate:
    # its specialist activation mapping is either a previously validated,
    # promoted provider-ID mapping or the legacy eight-agent rollback set.
    terraform_data.foundry_specialist_promotion_gate,
  ]

  lifecycle {
    precondition {
      condition     = var.api_traffic_revision == "" || startswith(var.api_traffic_revision, "${local.base}-api--")
      error_message = "api_traffic_revision must belong to this API container app."
    }

    precondition {
      condition     = !var.enable_sre_agent_patch_execution || local.sre_agent_patch_execution_config_valid
      error_message = "API SRE Agent execution requires bootstrapped RBAC and the complete canonical trigger, secret, endpoint, and managed target configuration."
    }

  }
}

# ---------------------------------------------------------------------------
# Durable Exposure enrichment
#
# This job uses the exact API image and managed identity selected above, but
# replaces the web process with the bounded worker CLI. A schedule-triggered
# Container Apps Job remains manually startable through Azure for recovery;
# no request path or always-running API replica schedules provider work.
# ---------------------------------------------------------------------------

resource "azurerm_container_app_job" "exposure_enrichment" {
  name                         = "${local.base}-exposure-enrichment"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 900
  replica_retry_limit          = 2

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
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
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
  }

  dynamic "secret" {
    for_each = var.nvd_api_key != "" ? [var.nvd_api_key] : []
    content {
      name  = "nvd-api-key"
      value = secret.value
    }
  }

  schedule_trigger_config {
    cron_expression          = var.exposure_enrichment_schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "exposure-enrichment"
      image  = var.deploy_images ? local.api_image : local.placeholder_image
      cpu    = var.ontology_discovery_job_cpu
      memory = var.ontology_discovery_job_memory
      command = [
        "python",
      ]
      args = [
        "/app/scripts/refresh_exposure_enrichment.py",
        "--all-due",
        "--max-items",
        tostring(var.exposure_enrichment_max_items),
      ]

      env {
        name  = "AIOPS_HOME"
        value = var.enable_fabric ? "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops" : "/tmp/aiops"
      }

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
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.acr_pull,
    fabric_workspace_role_assignment.apps,
  ]
}

# Prefetch active-generation CVE and KB metadata independently of the six-hour
# refresh of already registered due items. The shared CLI is the only writer
# and limits persistence to the durable Exposure enrichment document.
resource "azurerm_container_app_job" "exposure_prefetch" {
  name                         = "${local.base}-exposure-prefetch"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
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
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
  }

  dynamic "secret" {
    for_each = var.nvd_api_key != "" ? [var.nvd_api_key] : []
    content {
      name  = "nvd-api-key"
      value = secret.value
    }
  }

  schedule_trigger_config {
    cron_expression          = var.exposure_prefetch_schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "exposure-prefetch"
      image  = var.deploy_images ? local.api_image : local.placeholder_image
      cpu    = var.ontology_discovery_job_cpu
      memory = var.ontology_discovery_job_memory
      command = [
        "python",
      ]
      args = [
        "/app/scripts/refresh_exposure_enrichment.py",
        "--prefetch-generation",
        "--max-items",
        tostring(var.exposure_enrichment_max_items),
      ]

      env {
        name  = "AIOPS_HOME"
        value = var.enable_fabric ? "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops" : "/tmp/aiops"
      }

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
    }
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.acr_pull,
    fabric_workspace_role_assignment.apps,
  ]
}

resource "fabric_workspace_role_assignment" "patch_publisher" {
  count = var.enable_fabric ? 1 : 0

  workspace_id = fabric_workspace.ops[0].id
  role         = "Contributor"

  principal = {
    id   = azurerm_user_assigned_identity.ontology_publisher.principal_id
    type = "ServicePrincipal"
  }
}

resource "azurerm_container_app_job" "patch_publication" {
  count = var.enable_fabric ? 1 : 0

  name                         = "${local.base}-patch-publication"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
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

  schedule_trigger_config {
    cron_expression          = var.patch_publication_schedule
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name   = "patch-publication"
      image  = var.deploy_images ? local.api_image : local.placeholder_image
      cpu    = var.ontology_discovery_job_cpu
      memory = var.ontology_discovery_job_memory
      command = [
        "python",
        "-m",
        "onboarding.cli",
      ]
      args = [
        "patch-publish",
        "--config",
        "/app/arg.config.deploy.yaml",
        "--fabric-config",
        "/app/fabric.config.deploy.yaml",
        "--connection-home",
        "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops/connections",
        "--source-root",
        "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops/patch-publication-source",
        "--managed-identity-client-id",
        azurerm_user_assigned_identity.ontology_publisher.client_id,
      ]

      env {
        name  = "AIOPS_HOME"
        value = "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.ontology_publisher.client_id
      }

      env {
        name  = "AIOPS_CONNECTION_HOME"
        value = "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops/connections"
      }

      env {
        name  = "AIOPS_PATCH_SOURCE_ROOT"
        value = "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops/patch-publication-source"
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
    fabric_workspace_role_assignment.patch_publisher,
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

  dynamic "secret" {
    for_each = var.enable_role_assignments ? [] : [1]
    content {
      name  = "acr-password"
      value = azurerm_container_registry.main.admin_password
    }
  }

  registry {
    server               = local.registry_server
    identity             = var.enable_role_assignments ? azurerm_user_assigned_identity.apps.id : null
    username             = var.enable_role_assignments ? null : azurerm_container_registry.main.admin_username
    password_secret_name = var.enable_role_assignments ? null : "acr-password"
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
        name  = "AIOPS_API_BASE_URL"
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
