terraform {
  required_version = ">= 1.9, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 5.2.0"
    }
  }
}

provider "azurerm" {
  subscription_id                 = var.subscription_id
  tenant_id                       = var.tenant_id
  resource_provider_registrations = "none"
  features {}
}

variable "subscription_id" {
  type        = string
  description = "Approved DEV subscription."
  default     = "890c9bfc-d09c-4143-9ce5-465e75e3eecc"
}

variable "tenant_id" {
  type        = string
  description = "Approved DEV tenant."
  default     = "262a3a77-7d74-4684-8937-897d98d2a17a"
}

locals {
  resource_group = "aiops-dev-rg"
  base           = "/subscriptions/${var.subscription_id}/resourceGroups/${local.resource_group}"
  registry_id    = "${local.base}/providers/Microsoft.ContainerRegistry/registries/aiopsdevacr7h0ih3"
  image          = "aiopsdevacr7h0ih3.azurecr.io/aiops-publication-broker@sha256:6d9478ab8877efb97c92e7c39d40dce92e589f61416a91b7a9b4aa61795195bd"
}

resource "azurerm_user_assigned_identity" "setup" {
  name                = "aiops-dev-setup-id"
  location            = "australiaeast"
  resource_group_name = local.resource_group
}

# Pull permission is the only standing grant; setup permissions are task-specific.
resource "azurerm_role_assignment" "registry_pull" {
  scope                = local.registry_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.setup.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_container_app_job" "setup" {
  name                         = "aiops-dev-setup"
  location                     = "australiaeast"
  resource_group_name          = local.resource_group
  container_app_environment_id = "${local.base}/providers/Microsoft.App/managedEnvironments/aiops-dev-cae"
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 300
  replica_retry_limit          = 0

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.setup.id]
  }
  registry {
    server   = "aiopsdevacr7h0ih3.azurecr.io"
    identity = azurerm_user_assigned_identity.setup.id
  }
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }
  template {
    container {
      name    = "setup"
      image   = local.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python"]
      args    = ["-c", file("${path.module}/readiness.py")]
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.setup.client_id
      }
    }
  }

  depends_on = [azurerm_role_assignment.registry_pull]
}

output "job_id" {
  description = "Manual setup runner resource ID."
  value       = azurerm_container_app_job.setup.id
}

output "identity_client_id" {
  description = "Explicit client ID for managed-identity SDK selection."
  value       = azurerm_user_assigned_identity.setup.client_id
}

output "identity_principal_id" {
  description = "Principal for separately reviewed task-specific permission assignments."
  value       = azurerm_user_assigned_identity.setup.principal_id
}
