terraform {
  # The Fabric provider requires >= 1.8; 1.9 is the floor for the `templatefile`
  # and provider-function behaviour used here.
  required_version = ">= 1.9, < 2.0"

  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
      # 5.x is the current major line. `azurerm_ai_services` was removed in
      # 5.0 in favour of `azurerm_cognitive_account`, and
      # `azurerm_cognitive_account_project` (the modern, non-hub Foundry
      # project) is only available from this line onward.
      version = "~> 5.1"
    }
    fabric = {
      source = "microsoft/fabric"
      # Workspace, lakehouse, and workspace role assignment all support
      # service principal authentication in this line.
      version = "~> 1.13"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.6"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  client_id       = var.client_id
  client_secret   = var.client_secret

  features {
    key_vault {
      # Deliberately do not purge on destroy: soft-delete is the last line of
      # defence for key material, and purging makes an accidental destroy
      # unrecoverable.
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    cognitive_account {
      # Cognitive accounts hold no durable state here (models are re-deployable
      # declaratively), and a soft-deleted account blocks recreating one with
      # the same custom subdomain — which would break redeploys.
      purge_soft_delete_on_destroy = true
    }
    resource_group {
      # Refuse to silently delete resources this configuration does not own.
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "azapi" {
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  client_id       = var.client_id
  client_secret   = var.client_secret
}

provider "fabric" {
  tenant_id     = var.tenant_id
  client_id     = var.client_id
  client_secret = var.client_secret
  # OneLake data-access roles are still a provider preview surface. This is
  # enabled only so the five explicit Phase 13 read roles below can be
  # managed; it does not opt any existing resource into broader access.
  preview = true
}
