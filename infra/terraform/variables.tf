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
  default     = 1.0
}

variable "api_memory" {
  description = "Memory allocated to the API container. Must pair with api_cpu per the Container Apps ratio (2Gi per vCPU)."
  type        = string
  default     = "2Gi"
}

variable "api_min_replicas" {
  description = "Minimum API replicas. Keep at 1 or higher: the API caches an in-memory knowledge snapshot that is expensive to rebuild on a cold start."
  type        = number
  default     = 1
}

variable "api_max_replicas" {
  description = "Maximum API replicas."
  type        = number
  default     = 3
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
  description = "Non-secret deployment marker overwritten by APIM and required by gateway-only API mode."
  type        = string
  default     = "aiops-apim-v1"
  validation {
    condition     = can(regex("^[a-z0-9-]{8,64}$", var.apim_gateway_assertion))
    error_message = "apim_gateway_assertion must be a bounded lowercase deployment marker."
  }
}

# ---------------------------------------------------------------------------
# Azure AI Foundry
# ---------------------------------------------------------------------------

variable "foundry_model_name" {
  description = "Model backing the Operations Copilot prompt agent."
  type        = string
  default     = "gpt-5-mini"
}

variable "foundry_model_version" {
  description = "Model version. Verify availability with: az cognitiveservices model list -l <location>."
  type        = string
  default     = "2025-08-07"
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

variable "foundry_specialists" {
  description = "Independently named/versioned Foundry prompt specialists. Phase 09-09 expansion: all 8 agents deployed."
  type = map(object({
    name    = string
    version = string
  }))
  default = {
    network = { name = "aiops-network-agent", version = "2026.08.1" }
    vulnerability = { name = "aiops-vulnerability-agent", version = "2026.08.1" }
    patch = { name = "aiops-patch-agent", version = "2026.08.1" }
    incident = { name = "aiops-incident-agent", version = "2026.08.1" }
    change = { name = "aiops-change-agent", version = "2026.08.1" }
    governance = { name = "aiops-governance-agent", version = "2026.08.1" }
    remediation = { name = "aiops-remediation-agent", version = "2026.08.1" }
    executive_summary = { name = "aiops-executive-summary-agent", version = "2026.08.1" }
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

variable "alert_provider_stale_threshold_hours" {
  description = "Hours a required provider may stay stale before the freshness alert fires."
  type        = number
  default     = 6
}
