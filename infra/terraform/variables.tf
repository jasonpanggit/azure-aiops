# ---------------------------------------------------------------------------
# Identity and subscription
#
# All four are supplied by the deploy script from web/.env.local (the service
# principal used for local development), so they are never written to a file
# that could be committed.
# ---------------------------------------------------------------------------

variable "subscription_id" {
  description = "Azure subscription the workbench is deployed into."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "tenant_id" {
  description = "Entra tenant of the deploying service principal."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}

variable "client_id" {
  description = "Application (client) ID of the deploying service principal."
  type        = string
}

variable "client_secret" {
  description = "Client secret of the deploying service principal."
  type        = string
  sensitive   = true
}

variable "deployer_object_id" {
  description = <<-EOT
    Object ID (not application ID) of the deploying service principal.

    Used for Fabric capacity administration and Key Vault data-plane access.
    Fabric capacity admin members must be object IDs for service principals,
    and the application ID is silently accepted but does not grant access.
  EOT
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Naming and placement
# ---------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for all resource names. Keep short: several Azure resource types cap at 24 characters."
  type        = string
  default     = "aiops"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,11}$", var.name_prefix))
    error_message = "name_prefix must be 3-12 lowercase alphanumeric characters starting with a letter."
  }
}

variable "environment" {
  description = "Environment discriminator, included in resource names and tags."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{2,8}$", var.environment))
    error_message = "environment must be 2-8 lowercase alphanumeric characters."
  }
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "australiaeast"
}

variable "resource_group_name" {
  description = "Resource group name. Defaults to <name_prefix>-<environment>-rg when empty."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Container images
# ---------------------------------------------------------------------------

variable "image_tag" {
  description = <<-EOT
    Tag of the API and web images in the registry.

    Deliberately not defaulted to `latest`: a mutable tag makes the deployed
    revision unidentifiable and defeats Container Apps' revision model.
  EOT
  type        = string
  default     = "v1"
}

variable "api_image_digest" {
  description = "Optional immutable sha256 digest for the API image and API-based workers. When set, it takes precedence over image_tag."
  type        = string
  default     = ""

  validation {
    condition     = var.api_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "api_image_digest must be empty or an exact lowercase sha256 digest."
  }
}

variable "web_image_digest" {
  description = "Optional immutable sha256 digest for the web image. When set, it takes precedence over image_tag."
  type        = string
  default     = ""

  validation {
    condition     = var.web_image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.web_image_digest))
    error_message = "web_image_digest must be empty or an exact lowercase sha256 digest."
  }
}

variable "ontology_discovery_image_tag" {
  description = "Optional immutable API image tag used only by the Phase 13 ontology coordinator and RBAC-validation Jobs. Empty inherits image_tag."
  type        = string
  default     = ""

  validation {
    condition = (
      var.ontology_discovery_image_tag == "" ||
      can(regex("^[0-9A-Za-z_][0-9A-Za-z_.-]{0,127}$", var.ontology_discovery_image_tag))
    )
    error_message = "ontology_discovery_image_tag must be empty or a valid 1-128 character OCI/Docker tag."
  }
}

variable "ontology_discovery_image_digest" {
  description = "Optional immutable aiops-api digest used only by Phase 13 Jobs; leaves the shared API/web/MCP images unchanged."
  type        = string
  default     = ""

  validation {
    condition = (
      var.ontology_discovery_image_digest == ""
      || can(regex("^sha256:[0-9a-f]{64}$", var.ontology_discovery_image_digest))
    )
    error_message = "ontology_discovery_image_digest must be empty or an immutable sha256 digest."
  }
}

variable "ontology_discovery_job_cpu" {
  description = "CPU allocated to each finite Phase 13 ontology Job, independent of the shared API sizing."
  type        = number
  default     = 2

  validation {
    condition     = contains([0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4], var.ontology_discovery_job_cpu)
    error_message = "ontology_discovery_job_cpu must be a supported Container Apps consumption CPU value."
  }
}

variable "ontology_discovery_job_memory" {
  description = "Memory allocated to each finite Phase 13 ontology Job, independent of the shared API sizing."
  type        = string
  default     = "4Gi"

  validation {
    condition     = can(regex("^[1-8](?:\\.0)?Gi$", var.ontology_discovery_job_memory))
    error_message = "ontology_discovery_job_memory must be expressed as 1Gi through 8Gi."
  }
}

variable "ontology_discovery_environment" {
  description = "Exact ontology coordinator data classification. Validation selects only the isolated validation connection registry and fixture Jobs; it does not rename the shared deployment."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "validation"], var.ontology_discovery_environment)
    error_message = "ontology_discovery_environment must be exactly production or validation."
  }
}

variable "api_image_repository" {
  description = "Repository name for the Operations API image."
  type        = string
  default     = "aiops-api"
}

variable "web_image_repository" {
  description = "Repository name for the Operations Workbench image."
  type        = string
  default     = "aiops-web"
}

variable "deploy_images" {
  description = <<-EOT
    Whether the container images already exist in the registry.

    On a first apply the registry is created empty, so the container apps
    cannot pull anything. Leave this false to provision the platform, push the
    images with infra/scripts/build-and-push.sh, then apply again with it true.
  EOT
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Container app sizing
# ---------------------------------------------------------------------------

variable "api_cpu" {
  description = "vCPU allocated to the API container."
  type        = number
  default     = 4.0
}

variable "api_memory" {
  description = <<-EOT
    Memory allocated to the API container on the dedicated D4 workload profile.
    4Gi (2 vCPU) was observed
    OOM-killing (exit 137) the API in a crash loop once real (non-empty)
    inventory data was loaded into the in-memory provider cache. Projected
    temporal reads keep cold-start memory bounded so 8Gi provides headroom
    for the production provider set at 4 vCPU.
  EOT
  type        = string
  default     = "8Gi"
}

variable "api_min_replicas" {
  description = "Minimum API replicas. Keep at 1 or higher: the API caches an in-memory knowledge snapshot that is expensive to rebuild on a cold start."
  type        = number
  default     = 1
}

variable "api_max_replicas" {
  description = "Maximum API replicas. Keep at 1 while connection sync jobs run in-process so autoscaling cannot orphan a live sync on another replica."
  type        = number
  default     = 1
}

variable "enable_defender_configuration_execution" {
  description = "Opt in to approval-gated direct Microsoft Defender for Cloud configuration actions and their narrow pricing-resource RBAC grant."
  type        = bool
  default     = false
}

variable "enable_sre_agent_patch_execution" {
  description = "Opt in to approval-gated patch dispatch through one separately approved Azure SRE Agent HTTP trigger. The trigger is never created or updated by Terraform."
  type        = bool
  default     = false
}

variable "enable_sre_agent_patch_rbac" {
  description = "Bootstrap the three reviewed SRE patch execution roles before the separately approved dispatch enablement plan."
  type        = bool
  default     = false
}

variable "retain_sre_agent_thread_verification" {
  description = "Retain only agent-scoped thread read authorization while previously submitted SRE executions finish reconciliation after dispatch is disabled."
  type        = bool
  default     = false
}

variable "sre_agent_http_trigger_secret_id" {
  description = "Existing Key Vault secret URI containing the Azure SRE Agent HTTP trigger URL. The URL value must never be supplied directly to Terraform."
  type        = string
  default     = ""

  validation {
    condition = (
      var.sre_agent_http_trigger_secret_id == "" ||
      can(regex("^https://[a-z0-9-]+\\.vault\\.azure\\.net/secrets/sre-agent-http-trigger-url/[A-Za-z0-9]+$", var.sre_agent_http_trigger_secret_id))
    )
    error_message = "sre_agent_http_trigger_secret_id must be empty or a versioned Azure Key Vault URI for the exact sre-agent-http-trigger-url secret."
  }
}

variable "sre_agent_trigger_origin" {
  description = "Expected non-secret HTTPS origin copied from the reviewed SRE Agent trigger URL. It is validated independently from the agent data-plane endpoint."
  type        = string
  default     = ""

  validation {
    condition = (
      var.sre_agent_trigger_origin == "" ||
      (
        can(regex("^https://[^/:]+$", var.sre_agent_trigger_origin)) &&
        lower(var.sre_agent_trigger_origin) != "https://localhost" &&
        !can(regex("^https://[0-9]+(?:\\.[0-9]+){3}$", var.sre_agent_trigger_origin))
      )
    )
    error_message = "sre_agent_trigger_origin must be empty or an HTTPS DNS origin without credentials, a port, path, query, or fragment."
  }
}

variable "sre_agent_trigger_id" {
  description = "Exact non-secret HTTP trigger ID reviewed with the canonical definition and copied from the trigger URL."
  type        = string
  default     = ""

  validation {
    condition = (
      var.sre_agent_trigger_id == "" ||
      (
        length(var.sre_agent_trigger_id) <= 256 &&
        can(regex("^[A-Za-z0-9._~-]+$", var.sre_agent_trigger_id))
      )
    )
    error_message = "sre_agent_trigger_id must be empty or an exact URL-safe trigger identifier of at most 256 characters."
  }
}

variable "sre_agent_endpoint" {
  description = "Expected non-secret Azure SRE Agent data-plane endpoint used only to poll persisted threads."
  type        = string
  default     = ""

  validation {
    condition = (
      var.sre_agent_endpoint == "" ||
      (
        can(regex("^https://[^/:]+/?$", var.sre_agent_endpoint)) &&
        !can(regex("^https://localhost/?$", lower(var.sre_agent_endpoint))) &&
        !can(regex("^https://[0-9]+(?:\\.[0-9]+){3}/?$", var.sre_agent_endpoint))
      )
    )
    error_message = "sre_agent_endpoint must be empty or an HTTPS DNS endpoint without userinfo, an explicit port, query parameters, or fragments."
  }
}

variable "sre_agent_patch_target_prefix" {
  description = "Exact ARM resource prefix within the configured SRE Agent subscription that the adapter may target."
  type        = string
  default     = ""
}

variable "sre_agent_trigger_scope" {
  description = "Managed-identity token scope for invoking the SRE Agent HTTP trigger."
  type        = string
  default     = "59f0a04a-b322-4310-adc9-39ac41e9631e/.default"

  validation {
    condition     = endswith(var.sre_agent_trigger_scope, "/.default")
    error_message = "sre_agent_trigger_scope must be an Azure Identity .default scope."
  }
}

variable "sre_agent_thread_scope" {
  description = "Managed-identity token scope for polling the SRE Agent data-plane thread endpoint."
  type        = string
  default     = "https://azuresre.dev/.default"

  validation {
    condition     = endswith(var.sre_agent_thread_scope, "/.default")
    error_message = "sre_agent_thread_scope must be an Azure Identity .default scope."
  }
}

variable "web_cpu" {
  description = "vCPU allocated to the web container."
  type        = number
  default     = 0.5
}

variable "web_memory" {
  description = "Memory allocated to the web container."
  type        = string
  default     = "1Gi"
}

variable "web_min_replicas" {
  description = "Minimum web replicas."
  type        = number
  default     = 1
}

variable "web_max_replicas" {
  description = "Maximum web replicas."
  type        = number
  default     = 3
}

# ---------------------------------------------------------------------------
# API authentication
# ---------------------------------------------------------------------------

variable "entra_web_client_id" {
  description = <<-EOT
    Entra SPA application identifier used by the web workbench.

    Entra SPA application client ID compiled into the production web image.
  EOT
  type        = string
}

variable "entra_api_audience" {
  description = "Expected aud claim for Operations API access tokens."
  type        = string
}

variable "entra_grants_json" {
  description = "JSON subject-to-AIOps-grants map; Entra app roles must assert each configured role."
  type        = string
  sensitive   = true

  validation {
    condition     = can(jsondecode(var.entra_grants_json))
    error_message = "entra_grants_json must be valid JSON."
  }
}

variable "akv_bootstrap_secrets_json" {
  description = "JSON map of Key Vault secret names to secret-backed environment variable names."
  type        = string
  default     = "{}"

  validation {
    condition     = can(jsondecode(var.akv_bootstrap_secrets_json))
    error_message = "akv_bootstrap_secrets_json must be valid JSON."
  }
}

variable "nvd_api_key" {
  description = <<-EOT
    NVD API key used to enrich CVE detail (description, CVSS) from the
    National Vulnerability Database. Without it, NVD's anonymous rate limit
    (5 requests/30s) throttles CVE detail lookups, causing them to fail with
    "CVE not found" in the UI. Leave empty to disable enrichment.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "exposure_enrichment_schedule" {
  description = "Five-field UTC cron schedule for the durable Exposure enrichment Container Apps Job."
  type        = string
  default     = "0 */6 * * *"

  validation {
    condition     = length(split(" ", trimspace(var.exposure_enrichment_schedule))) == 5
    error_message = "exposure_enrichment_schedule must be a five-field cron expression."
  }
}

variable "exposure_prefetch_schedule" {
  description = "Five-field UTC cron schedule for the durable Exposure metadata prefetch Container Apps Job."
  type        = string
  default     = "*/10 * * * *"

  validation {
    condition     = can(regex("^\\*/([5-9]|1[0-5]) \\* \\* \\* \\*$", trimspace(var.exposure_prefetch_schedule)))
    error_message = "exposure_prefetch_schedule must run every 5 to 15 minutes (for example, */10 * * * *)."
  }
}

variable "exposure_enrichment_max_items" {
  description = "Maximum durable enrichment items attempted by one scheduled job execution."
  type        = number
  default     = 100

  validation {
    condition = (
      var.exposure_enrichment_max_items >= 1
      && var.exposure_enrichment_max_items <= 1000
      && floor(var.exposure_enrichment_max_items) == var.exposure_enrichment_max_items
    )
    error_message = "exposure_enrichment_max_items must be an integer from 1 through 1000."
  }
}

variable "patch_publication_schedule" {
  description = "Five-field UTC cron schedule for the bounded patch-only Fabric publication job."
  type        = string
  default     = "*/5 * * * *"

  validation {
    condition     = length(split(" ", trimspace(var.patch_publication_schedule))) == 5
    error_message = "patch_publication_schedule must be a five-field cron expression."
  }
}

variable "refresh_trigger_secret" {
  description = <<-EOT
    Shared secret checked against the x-aiops-trigger-secret header on
    POST /api/v1/inventory/refresh. This endpoint is called by the Fabric
    Data Pipeline's Web activity on a schedule to run inventory
    acquisition + normalization + OneLake publication. Leave empty to
    disable the endpoint (it returns 503 until configured).
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "api_external_ingress" {
  description = <<-EOT
    Whether the API accepts traffic from outside the Container Apps environment.

    Required because the Entra-authenticated browser calls the API directly.
  EOT
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Azure API Management MCP gateway
# ---------------------------------------------------------------------------

variable "enable_apim" {
  description = "Whether to provision the approved Operations MCP APIM facade."
  type        = bool
  default     = false
}

variable "apim_name" {
  description = "Existing or approved APIM service name. Empty derives one from the deployment name."
  type        = string
  default     = ""
}

variable "apim_sku" {
  description = "APIM SKU; must be confirmed for MCP support before apply."
  type        = string
  default     = "Developer"
  validation {
    condition     = contains(["Basic", "Basic_v2", "Developer", "Standard", "Standard_v2", "Premium", "Premium_v2"], var.apim_sku)
    error_message = "apim_sku must be an APIM tier that supports the approved MCP gateway."
  }
}

variable "apim_virtual_network_type" {
  description = "APIM network mode. Internal requires an approved private backend/DNS design."
  type        = string
  default     = "None"
  validation {
    condition     = contains(["None", "External", "Internal"], var.apim_virtual_network_type)
    error_message = "apim_virtual_network_type must be None, External, or Internal."
  }
}

variable "apim_publisher_name" {
  description = "APIM publisher display name."
  type        = string
  default     = "Azure AI Operations"
}

variable "apim_publisher_email" {
  description = "APIM publisher contact email; use an approved operational address."
  type        = string
  default     = ""
}

variable "apim_audience" {
  description = "Optional Entra audience accepted by the APIM MCP policy; defaults to the API audience and never uses a client-declared audience."
  type        = string
  default     = ""
}

variable "apim_revision" {
  description = "MCP API revision kept for reversible gateway rollout."
  type        = string
  default     = "1"
}

variable "apim_subscription_limit" {
  description = "Maximum approved product subscriptions; subscription keys are consumer controls, not grants."
  type        = number
  default     = 10
}

variable "apim_gateway_assertion" {
  description = "Shared secret asserted by APIM (and the ACA MCP relay) to prove a request was validated by the gateway. Leave empty to auto-generate a strong secret."
  type        = string
  default     = ""
  sensitive   = true
  validation {
    condition     = var.apim_gateway_assertion == "" || can(regex("^[A-Za-z0-9]{32,128}$", var.apim_gateway_assertion))
    error_message = "apim_gateway_assertion must be empty (to auto-generate) or a 32-128 character alphanumeric secret."
  }
}

# ---------------------------------------------------------------------------
# Azure AI Foundry
# ---------------------------------------------------------------------------

variable "foundry_model_name" {
  description = "Model backing the Operations Copilot prompt agent."
  type        = string
  default     = "gpt-5.4-mini"
}

variable "foundry_model_version" {
  description = "Model version. Verify availability with: az cognitiveservices model list -l <location>."
  type        = string
  default     = "2026-03-17"
}

variable "foundry_model_sku" {
  description = "Deployment SKU for the model."
  type        = string
  default     = "GlobalStandard"
}

variable "foundry_model_capacity" {
  description = "Deployment capacity in thousands of tokens per minute. The provider default of 1 (1K TPM) is too low for interactive use."
  type        = number
  default     = 50
}

variable "foundry_agent_name" {
  description = "Name of the Foundry prompt agent that narrates Copilot answers."
  type        = string
  default     = "operations-copilot"
}

variable "foundry_agent_name_prefix" {
  description = <<-EOT
    Prefix applied to every manifest-derived Foundry specialist agent name.

    Deployed agent names are projected from the committed specialist manifest
    (src/operations/specialists.v1.json) as
    "<prefix><manifest foundry.name><suffix>". The defaults reproduce the
    eight already-deployed names exactly (manifest `network` ->
    `aiops-network-agent`), so adopting the manifest adds the four new
    specialists instead of orphaning the existing eight.
  EOT
  type        = string
  default     = "aiops-"
}

variable "foundry_agent_name_suffix" {
  description = "Suffix applied to every manifest-derived Foundry specialist agent name."
  type        = string
  default     = "-agent"
}

variable "foundry_specialist_release" {
  description = <<-EOT
    Immutable release stamp for the manifest-derived specialist version set.

    The deployed version of each specialist is
    "<release>.<manifest foundry.version>". Foundry agent versions are
    additive and immutable, so a contract change must publish a new version
    string rather than redefine a published one. Pin this back to a prior
    release (e.g. "2026.08") to re-select the previously published version
    set for rollback without editing the manifest.
  EOT
  type        = string
  default     = "2026.09"

  validation {
    condition     = can(regex("^[0-9A-Za-z][0-9A-Za-z.-]*$", var.foundry_specialist_release))
    error_message = "foundry_specialist_release must be an alphanumeric/dot/hyphen release stamp."
  }
}

variable "foundry_specialists" {
  description = <<-EOT
    DEPRECATED compatibility input: the pre-manifest eight named/versioned
    Foundry prompt specialists.

    The committed specialist manifest is now the primary source for agent
    names, versions, prompts, and grants (see local.foundry_specialist_deployment
    in foundry.tf). This variable is retained for one migration window so
    existing tfvars keep planning and so the previously deployed name/version
    pairs stay visible to the running app (FOUNDRY_SPECIALISTS_LEGACY_JSON)
    as a rollback target. It no longer drives the deployed agent definitions.
  EOT
  type = map(object({
    name    = string
    version = string
  }))
  default = {
    network           = { name = "aiops-network-agent", version = "2026.08.1" }
    vulnerability     = { name = "aiops-vulnerability-agent", version = "2026.08.1" }
    patch             = { name = "aiops-patch-agent", version = "2026.08.1" }
    incident          = { name = "aiops-incident-agent", version = "2026.08.1" }
    change            = { name = "aiops-change-agent", version = "2026.08.1" }
    governance        = { name = "aiops-governance-agent", version = "2026.08.1" }
    remediation       = { name = "aiops-remediation-agent", version = "2026.08.1" }
    executive_summary = { name = "aiops-executive-summary-agent", version = "2026.08.1" }
  }
}

variable "foundry_specialist_promotion_artifact" {
  description = <<-EOT
    Path to the reviewed, persisted validated-promotion artifact that decides
    which specialist versions the running revision activates.

    Terraform cannot consume apply-time local-exec output during the same
    plan, so promotion is a two-stage boundary:

      Stage 1 (apply N)   create-foundry-agent.sh publishes new immutable
                          agent versions, captures the ACTUAL immutable
                          provider version ID returned for each one, runs the
                          live parity gate against those exact IDs, and -- only
                          if the gate passes -- writes this artifact with
                          status "validated", the manifest digest it was
                          validated against, and the previously promoted
                          mapping as `rollback_target`.
      Stage 2 (apply N+1) Terraform reads this artifact at PLAN time and, if
                          terraform_data.foundry_specialist_promotion_gate's
                          preconditions hold, activates exactly that mapping on
                          the Container Apps revision.

    Because the artifact is read at plan time, a candidate version created by
    the current apply can never activate in that same unvalidated step.

    Leave empty (the default) to keep the deterministic legacy eight-agent
    migration mapping active without sending synthetic release labels as
    provider IDs. Select active or rollback explicitly only after supplying a
    matching validated artifact. The file is a deployment input, not
    repository state -- keep it outside the build context and reviewed
    alongside the manifest it pins.
  EOT
  type        = string
  default     = ""
}

variable "foundry_specialist_candidate_catalog_artifact" {
  description = <<-EOT
    Path to the separately reviewed foundry-specialist-candidates.v1 artifact
    exposed to the API catalog. This input is metadata-only: it never supplies
    FOUNDRY_<ID>_AGENT_VERSION and cannot change the activation target.
  EOT
  type        = string
  default     = ""
}

variable "foundry_specialist_candidate_catalog_artifact_sha256" {
  description = "Raw SHA-256 of the candidate catalog bytes, used only for transport/file integrity. Required with foundry_specialist_candidate_catalog_artifact."
  type        = string
  default     = ""

  validation {
    condition     = var.foundry_specialist_candidate_catalog_artifact_sha256 == "" || can(regex("^[0-9a-f]{64}$", var.foundry_specialist_candidate_catalog_artifact_sha256))
    error_message = "foundry_specialist_candidate_catalog_artifact_sha256 must be empty or an exact lowercase SHA-256 digest."
  }
}

variable "foundry_specialist_candidate_binding_sha256" {
  description = "Reviewed sha256-canonical-json-candidate-v1 semantic digest of the strict candidate catalog, excluding only source_revision, generated_at, and validation timestamps."
  type        = string
  default     = ""

  validation {
    condition     = var.foundry_specialist_candidate_binding_sha256 == "" || can(regex("^[0-9a-f]{64}$", var.foundry_specialist_candidate_binding_sha256))
    error_message = "foundry_specialist_candidate_binding_sha256 must be empty or an exact lowercase SHA-256 digest."
  }
}

variable "foundry_specialist_candidate_prompt_digests" {
  description = "Separately reviewed specialist ID to prompt SHA-256 mapping used to reject stale or mismatched candidate rows."
  type        = map(string)
  default     = {}

  validation {
    condition = alltrue([
      for digest in values(var.foundry_specialist_candidate_prompt_digests) :
      can(regex("^[0-9a-f]{64}$", digest))
    ])
    error_message = "Every foundry_specialist_candidate_prompt_digests value must be an exact lowercase SHA-256 digest."
  }
}

variable "deployment_source_revision" {
  description = "Exact lowercase Git source revision of the API image. Required when candidate catalog metadata is supplied so stale artifacts fail closed."
  type        = string
  default     = ""

  validation {
    condition     = var.deployment_source_revision == "" || can(regex("^(?:[0-9a-f]{40}|[0-9a-f]{64})$", var.deployment_source_revision))
    error_message = "deployment_source_revision must be empty or an exact 40- or 64-character lowercase hexadecimal revision."
  }
}

variable "foundry_specialist_activation_target" {
  description = "Specialist provider-ID mapping to activate: legacy, active, or rollback."
  type        = string
  default     = "legacy"

  validation {
    condition     = contains(["legacy", "active", "rollback"], lower(var.foundry_specialist_activation_target))
    error_message = "foundry_specialist_activation_target must be legacy, active, or rollback."
  }
}

variable "enable_foundry_specialist_candidate_publish" {
  description = "Explicit stage-B switch for additive specialist candidate publication after the version-pinning runtime is verified."
  type        = bool
  default     = false
}

variable "foundry_version_pinning_runtime_verified" {
  description = "Reviewed assertion that the deployed API runtime pins outbound Foundry requests to configured provider version IDs."
  type        = bool
  default     = false
}

variable "foundry_coordinator_activation_artifact" {
  description = "Path to the validated Operations Copilot coordinator activation artifact. A publish apply writes it; a later reviewed apply activates it."
  type        = string
  default     = ""
}

variable "enable_foundry_coordinator_candidate_publish" {
  description = "Publish and live-validate one additive Operations Copilot coordinator version without publishing specialist agents."
  type        = bool
  default     = false
}

variable "foundry_specialist_rollback_rotation" {
  description = "Optional operator-chosen rotation epoch. A new non-empty value advances the immutable rollback target once during the next successful promotion; reusing the value leaves it stable."
  type        = string
  default     = ""
}

variable "foundry_model_deployment_name_override" {
  description = <<-EOT
    Optional explicit Azure model deployment name handed to the live parity
    gate so it can verify the deployed agents actually point at the model
    DEPLOYMENT (var.foundry_model_name), which is deliberately distinct from
    the manifest's declared contract model (`foundry.model`). Empty means the
    chat deployment's own name is used.
  EOT
  type        = string
  default     = ""
}

variable "agent_orchestration_mode" {
  description = "Operations Copilot orchestration mode. Defaults to 'maf' for Microsoft Agent Framework question-first delegation; set to 'deterministic' for the legacy page-anchored rollback path or 'canonical' to route every surface through the governed OrchestrationService."
  type        = string
  default     = "maf"

  validation {
    condition     = contains(["maf", "deterministic", "canonical"], lower(var.agent_orchestration_mode))
    error_message = "agent_orchestration_mode must be 'maf', 'deterministic', or 'canonical'."
  }
}

variable "enable_fabric_iq" {
  description = "Enable optional governed Fabric IQ enrichment. Identity remains owned by InventoryReadPort."
  type        = bool
  default     = false
}

variable "create_foundry_agent" {
  description = <<-EOT
    Whether to create the prompt agent after apply.

    Foundry prompt agents have no ARM resource type, so they are created
    through the data-plane REST API by a local-exec provisioner. This requires
    the Azure CLI on the machine running Terraform.
  EOT
  type        = bool
  default     = true
}

variable "enable_ontology_curator_agent" {
  description = <<-EOT
    Independently publish the Phase 13 ontology curator prompt agent.

    This switch is intentionally separate from
    enable_foundry_specialist_candidate_publish: enabling the ontology curator
    must not publish or promote the complete interactive specialist portfolio.
  EOT
  type        = bool
  default     = false
}

variable "enable_foundry_knowledge_search" {
  description = <<-EOT
    Whether to provision an Azure AI Search service and wire it into every
    Foundry specialist's Knowledge tools (azure_ai_search tool type).

    This is a new billed resource (default SKU below supports semantic
    ranking), distinct from the MCP tool-callers: it is a general-purpose,
    citable document corpus (not limited to any one framework) that
    specialists query directly for grounding, independent of operations-mcp
    and azure-mcp.
  EOT
  type        = bool
  default     = false
}

variable "foundry_knowledge_search_sku" {
  description = "SKU for the Azure AI Search service backing the Foundry knowledge base. 'standard' is the minimum tier that supports semantic ranking (used by the default vector_semantic_hybrid query type)."
  type        = string
  default     = "standard"
}

variable "foundry_knowledge_index_name" {
  description = "Name of the Azure AI Search index specialists query for grounded knowledge."
  type        = string
  default     = "aiops-knowledge"
}

variable "foundry_embedding_model_name" {
  description = "Embedding model deployment used to vectorize knowledge documents at index time and queries at retrieval time."
  type        = string
  default     = "text-embedding-3-small"
}

variable "foundry_embedding_model_capacity" {
  description = "Embedding model deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 30
}

# ---------------------------------------------------------------------------
# Microsoft Fabric
# ---------------------------------------------------------------------------

variable "enable_fabric" {
  description = <<-EOT
    Whether to provision Microsoft Fabric (capacity, workspace, lakehouse).

    Defaults to false because a Fabric capacity bills continuously from the
    moment it is created, independent of use. The rest of the platform deploys
    and runs without it.
  EOT
  type        = bool
  default     = false
}

variable "fabric_capacity_sku" {
  description = "Fabric capacity SKU. F2 is the smallest that supports a real workspace."
  type        = string
  default     = "F2"

  validation {
    condition     = can(regex("^F(2|4|8|16|32|64|128|256|512|1024|2048)$", var.fabric_capacity_sku))
    error_message = "fabric_capacity_sku must be an F-series SKU, e.g. F2 or F64."
  }
}

variable "fabric_capacity_admins" {
  description = <<-EOT
    Additional capacity administrators: user principal names for users, object
    IDs for service principals. The deploying principal is always included.
  EOT
  type        = list(string)
  default     = []
}

variable "fabric_workspace_name" {
  description = "Fabric workspace display name. Defaults to <name_prefix>-<environment>-ops when empty."
  type        = string
  default     = ""
}

variable "fabric_lakehouse_name" {
  description = "Lakehouse holding the operational context graph datasets."
  type        = string
  default     = "operational_context_graph_v2"
}

variable "fabric_ontology_name" {
  description = "Fabric ontology item backing the operational context graph."
  type        = string
  default     = "Operational_Context_Ontology_v2"
}

variable "alert_email_addresses" {
  description = <<-EOT
    Email addresses notified by Azure Monitor when platform observability
    alert rules fire (API/UI availability, provider health, discovery
    freshness). Empty by default so this is opt-in per environment; the pilot
    deployment must set at least one address before go-live.
  EOT
  type        = list(string)
  default     = []
}

variable "existing_alert_action_group_id" {
  description = "Optional existing Azure Monitor action-group resource ID. When set, alerts reuse it and Terraform does not create an email-backed action group."
  type        = string
  default     = ""

  validation {
    condition = (
      var.existing_alert_action_group_id == "" ||
      can(regex(
        "(?i)^/subscriptions/[0-9a-f-]{36}/resourcegroups/[^/]+/providers/microsoft\\.insights/actiongroups/[^/]+$",
        var.existing_alert_action_group_id,
      ))
    )
    error_message = "existing_alert_action_group_id must be empty or a complete Microsoft.Insights/actionGroups resource ID."
  }
}

variable "alert_provider_stale_threshold_hours" {
  description = "Hours a required provider may stay stale before the freshness alert fires."
  type        = number
  default     = 6
}

variable "exposure_ingestion_cadence_minutes" {
  description = "Configured duration of one Exposure ingestion cycle; every Exposure alert window uses exactly this duration."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [5, 10, 15, 30],
      var.exposure_ingestion_cadence_minutes,
    )
    error_message = "exposure_ingestion_cadence_minutes must be one of 5, 10, 15, or 30."
  }
}

variable "exposure_alert_evaluation_minutes" {
  description = "Azure Monitor evaluation frequency for Exposure alerts; must not exceed the ingestion cadence."
  type        = number
  default     = 5

  validation {
    condition = contains(
      [5, 10, 15, 30],
      var.exposure_alert_evaluation_minutes,
    )
    error_message = "exposure_alert_evaluation_minutes must be one of 5, 10, 15, or 30."
  }

  validation {
    condition = (
      var.exposure_alert_evaluation_minutes <=
      var.exposure_ingestion_cadence_minutes
    )
    error_message = "Exposure alerts must evaluate at least as fast as the configured ingestion cadence."
  }
}

variable "exposure_alert_min_effective_rows" {
  description = "Minimum effective Exposure rows expected after a non-empty ingestion cycle."
  type        = number
  default     = 1

  validation {
    condition     = var.exposure_alert_min_effective_rows >= 0
    error_message = "exposure_alert_min_effective_rows must be non-negative."
  }
}

variable "exposure_alert_max_drop_ratio" {
  description = "Maximum allowed effective-row drop from last known good before alerting."
  type        = number
  default     = 0.2

  validation {
    condition     = var.exposure_alert_max_drop_ratio >= 0 && var.exposure_alert_max_drop_ratio <= 1
    error_message = "exposure_alert_max_drop_ratio must be between zero and one."
  }
}

variable "exposure_alert_source_max_age_seconds" {
  description = "Maximum allowed age of effective Exposure source-family data."
  type        = number
  default     = 21600

  validation {
    condition     = var.exposure_alert_source_max_age_seconds > 0
    error_message = "exposure_alert_source_max_age_seconds must be positive."
  }
}

variable "exposure_alert_min_enrichment_quality" {
  description = "Minimum successful durable-enrichment ratio for one Exposure cycle."
  type        = number
  default     = 0.9

  validation {
    condition     = var.exposure_alert_min_enrichment_quality >= 0 && var.exposure_alert_min_enrichment_quality <= 1
    error_message = "exposure_alert_min_enrichment_quality must be between zero and one."
  }
}

variable "exposure_alert_min_represented_ratio" {
  description = "Minimum represented-to-total Exposure coverage ratio."
  type        = number
  default     = 0.95

  validation {
    condition     = var.exposure_alert_min_represented_ratio >= 0 && var.exposure_alert_min_represented_ratio <= 1
    error_message = "exposure_alert_min_represented_ratio must be between zero and one."
  }
}

variable "exposure_alert_max_reconciliation_mismatches" {
  description = "Maximum unexpected old/new semantic mismatches allowed in one cycle."
  type        = number
  default     = 0

  validation {
    condition     = var.exposure_alert_max_reconciliation_mismatches >= 0
    error_message = "exposure_alert_max_reconciliation_mismatches must be non-negative."
  }
}

variable "exposure_alert_max_reconciliation_ratio" {
  description = "Maximum unexpected old/new semantic drift ratio allowed in one cycle."
  type        = number
  default     = 0

  validation {
    condition     = var.exposure_alert_max_reconciliation_ratio >= 0 && var.exposure_alert_max_reconciliation_ratio <= 1
    error_message = "exposure_alert_max_reconciliation_ratio must be between zero and one."
  }
}

variable "exposure_alert_query_p95_ms" {
  description = "Maximum scoped Exposure query p95 latency in milliseconds."
  type        = number
  default     = 1000

  validation {
    condition     = var.exposure_alert_query_p95_ms > 0
    error_message = "exposure_alert_query_p95_ms must be positive."
  }
}

variable "exposure_alert_max_query_errors" {
  description = "Maximum Exposure query errors allowed in one ingestion-cycle window."
  type        = number
  default     = 0

  validation {
    condition     = var.exposure_alert_max_query_errors >= 0
    error_message = "exposure_alert_max_query_errors must be non-negative."
  }
}

variable "exposure_rollout_authorized" {
  description = "Explicit deployment authorization for any non-off Exposure rollout stage."
  type        = bool
  default     = false
}

variable "exposure_write_stage" {
  description = "Exposure v2 projection writer stage: off, shadow, canary, or on."
  type        = string
  default     = "off"

  validation {
    condition     = contains(["off", "shadow", "canary", "on"], lower(var.exposure_write_stage))
    error_message = "exposure_write_stage must be off, shadow, canary, or on."
  }
}

variable "exposure_read_stage" {
  description = "Exposure v2 API reader stage: off, shadow, canary, or on."
  type        = string
  default     = "off"

  validation {
    condition     = contains(["off", "shadow", "canary", "on"], lower(var.exposure_read_stage))
    error_message = "exposure_read_stage must be off, shadow, canary, or on."
  }
}

variable "exposure_web_stage" {
  description = "Exposure v2 web surface stage: off, shadow, canary, or on."
  type        = string
  default     = "off"

  validation {
    condition     = contains(["off", "shadow", "canary", "on"], lower(var.exposure_web_stage))
    error_message = "exposure_web_stage must be off, shadow, canary, or on."
  }
}

variable "exposure_handoff_stage" {
  description = "Exposure governed handoff stage: off, shadow, canary, or on."
  type        = string
  default     = "off"

  validation {
    condition     = contains(["off", "shadow", "canary", "on"], lower(var.exposure_handoff_stage))
    error_message = "exposure_handoff_stage must be off, shadow, canary, or on."
  }
}

variable "exposure_write_generation_id" {
  description = "Candidate generation receiving additive Exposure v2 writes."
  type        = string
  default     = ""
}

variable "exposure_read_generation_id" {
  description = "Candidate generation selected by the Exposure v2 reader."
  type        = string
  default     = ""
}

variable "exposure_rollback_generation_id" {
  description = "Retained prior generation selected by non-destructive rollback."
  type        = string
  default     = ""
}

variable "exposure_cursor_active_kid" {
  description = "Non-secret identifier for the active Exposure cursor signing-key version."
  type        = string
  default     = ""

  validation {
    condition = (
      var.exposure_cursor_active_kid == "" ||
      can(regex("^[0-9A-Za-z][0-9A-Za-z._-]{2,127}$", var.exposure_cursor_active_kid))
    )
    error_message = "exposure_cursor_active_kid must be empty or a 3-128 character non-secret identifier."
  }
}

variable "exposure_cursor_previous_kid" {
  description = "Non-secret identifier for the previous Exposure cursor signing-key version retained during overlap."
  type        = string
  default     = ""

  validation {
    condition = (
      var.exposure_cursor_previous_kid == "" ||
      can(regex("^[0-9A-Za-z][0-9A-Za-z._-]{2,127}$", var.exposure_cursor_previous_kid))
    )
    error_message = "exposure_cursor_previous_kid must be empty or a 3-128 character non-secret identifier."
  }
}

check "exposure_cursor_kids_distinct" {
  assert {
    condition = (
      var.exposure_cursor_active_kid == "" ||
      var.exposure_cursor_previous_kid == "" ||
      var.exposure_cursor_active_kid != var.exposure_cursor_previous_kid
    )
    error_message = "Active and previous Exposure cursor kid values must be distinct."
  }
}

variable "onboarded_subscriptions" {
  description = "List of Azure subscription IDs that have onboarded SPN credentials in AKV"
  type        = list(string)
  default     = []
}
