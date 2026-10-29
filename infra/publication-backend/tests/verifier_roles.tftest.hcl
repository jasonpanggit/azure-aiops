mock_provider "azurerm" {
  override_during = plan

  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-pub-rg/providers/Microsoft.Storage/storageAccounts/testpublicationartifacts"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-pub-rg/providers/Microsoft.Storage/storageAccounts/testpublicationartifacts/blobServices/default/containers/attempts"
    }
  }
}

variables {
  subscription_id = "11111111-1111-1111-1111-111111111111"
  tenant_id       = "22222222-2222-2222-2222-222222222222"
  settings = {
    name_prefix               = "test-pub"
    location                  = "australiaeast"
    sql_server_name           = "test-publication-control"
    sql_database_name         = "publication_control"
    sql_sku                   = "S0"
    sql_max_size_gb           = 2
    sql_backup_retention_days = 7
    sql_admin_group_name      = "test-operators"
    sql_admin_group_object_id = "33333333-3333-3333-3333-333333333333"
    storage_account_name      = "testpublicationartifacts"
    storage_replication       = "LRS"
    artifact_container_name   = "attempts"
    retention_days            = 2
    policy_state              = "Unlocked"
    private_connectivity      = "isolated-vnet-private-endpoints"
    virtual_network_cidr      = "10.80.0.0/16"
    registry_id               = "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-registry/providers/Microsoft.ContainerRegistry/registries/testregistry"
    registry_server           = "testregistry.azurecr.io"
    scaffold_image            = "testregistry.azurecr.io/scaffold@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
}

run "verifier_disabled_null_settings" {
  command = plan
  variables {
    settings = null
  }
  assert {
    condition     = output.publication_backend_verifier_roles_v1 == null && length(azurerm_role_definition.artifact_verifier_candidate) == 0 && length(local.verifier_candidates) == 0
    error_message = "Default-disabled must not define verifier roles or proposed bindings."
  }
}

run "verifier_disabled_with_settings" {
  command = plan
  assert {
    condition     = output.publication_backend_verifier_roles_v1 == null && length(azurerm_role_definition.artifact_verifier_candidate) == 0 && length(azurerm_role_assignment.registry_pull) == 0
    error_message = "Draft settings cannot enable roles or assignments."
  }
}

run "verifier_enabled_is_unassigned_and_read_only" {
  command = plan
  variables {
    enable                 = true
    reviewed_config_sha256 = sha256(jsonencode(var.settings))
  }
  assert {
    condition = (
      length(azurerm_role_definition.artifact_verifier_candidate) == 3 &&
      alltrue([for role in azurerm_role_definition.artifact_verifier_candidate :
        length(role.permissions[0].actions) == 1 &&
        length(role.permissions[0].data_actions) == 0 &&
        length(role.permissions[0].not_actions) == 0 &&
        length(role.permissions[0].not_data_actions) == 0
      ])
    )
    error_message = "Verifier definitions must contain only one ARM read each, no data actions or exclusions."
  }
  assert {
    condition = (
      output.publication_backend_verifier_roles_v1.proposed_bindings.account.actions == ["Microsoft.Storage/storageAccounts/read"] &&
      output.publication_backend_verifier_roles_v1.proposed_bindings.blob_service.actions == ["Microsoft.Storage/storageAccounts/blobServices/read"] &&
      output.publication_backend_verifier_roles_v1.proposed_bindings.container_policy.actions == ["Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read"]
    )
    error_message = "Exact closed read allowlists must not broaden to wildcard, write, SQL, key or SAS actions."
  }
  assert {
    condition = (
      output.publication_backend_verifier_roles_v1.proposed_bindings.account.scope == "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-pub-rg/providers/Microsoft.Storage/storageAccounts/testpublicationartifacts" &&
      output.publication_backend_verifier_roles_v1.proposed_bindings.blob_service.scope == "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-pub-rg/providers/Microsoft.Storage/storageAccounts/testpublicationartifacts/blobServices/default" &&
      output.publication_backend_verifier_roles_v1.proposed_bindings.container_policy.scope == "/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/test-pub-rg/providers/Microsoft.Storage/storageAccounts/testpublicationartifacts/blobServices/default/containers/attempts"
    )
    error_message = "Proposed read bindings cannot use a subscription, RG, parent or protected-container scope."
  }
  assert {
    condition = (
      !output.publication_backend_verifier_roles_v1.assigned &&
      !output.publication_backend_verifier_roles_v1.execution_enabled &&
      !output.publication_backend_verifier_roles_v1.qualified &&
      alltrue([for binding in output.publication_backend_verifier_roles_v1.proposed_bindings : !binding.assigned && length(binding.data_actions) == 0]) &&
      length(azurerm_role_assignment.registry_pull) == 1 &&
      azurerm_role_assignment.registry_pull["candidate"].role_definition_name == "AcrPull" &&
      !output.publication_backend_v1.execution_enabled &&
      !output.publication_backend_v1.qualified &&
      output.publication_backend_v1.broker.endpoint == null &&
      !azurerm_storage_container_immutability_policy.draft["candidate"].locked
    )
    error_message = "No assignment or execution/locking/qualification may be introduced."
  }
}
