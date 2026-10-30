mock_provider "azurerm" {}

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

run "default_disabled" {
  command = plan

  variables {
    settings = null
  }

  assert {
    condition     = output.publication_backend_v1 == null && length(local.candidates) == 0 && length(local.private_services) == 0
    error_message = "Disabled must expose no backend or resource instances."
  }
}

run "disabled_with_proposed_settings" {
  command = plan

  assert {
    condition     = output.publication_backend_v1 == null && length(azurerm_resource_group.backend) == 0 && length(azurerm_role_assignment.registry_pull) == 0
    error_message = "Providing draft settings alone must not provision resources or roles."
  }
}

run "enabled_needs_complete_inputs" {
  command = plan

  variables {
    enable   = true
    settings = null
  }
  expect_failures = [var.enable]
}

run "enabled_needs_separate_fingerprint" {
  command = plan

  variables {
    enable = true
  }
  expect_failures = [var.enable]
}

run "wrong_fingerprint" {
  command = plan

  variables {
    enable                 = true
    reviewed_config_sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  expect_failures = [var.reviewed_config_sha256]
}

run "enabled_is_still_nonoperable" {
  command = plan

  variables {
    enable                 = true
    reviewed_config_sha256 = sha256(jsonencode(var.settings))
  }

  assert {
    condition     = !output.publication_backend_v1.execution_enabled && !output.publication_backend_v1.qualified && output.publication_backend_v1.bootstrap_required && output.publication_backend_v1.broker.endpoint == null
    error_message = "Provisioning cannot qualify the backend or create a service endpoint."
  }
  assert {
    condition     = !azurerm_mssql_server.control["candidate"].public_network_access_enabled && azurerm_mssql_server.control["candidate"].azuread_administrator[0].azuread_authentication_only
    error_message = "SQL must be private and Entra-only."
  }
  assert {
    condition = alltrue([
      !azurerm_storage_account.artifacts["candidate"].shared_access_key_enabled,
      !azurerm_storage_account.artifacts["candidate"].public_network_access_enabled,
      !azurerm_storage_account.artifacts["candidate"].local_user_enabled,
      !azurerm_storage_account.artifacts["candidate"].allow_nested_items_to_be_public,
      !azurerm_storage_account.artifacts["candidate"].blob_properties[0].versioning_enabled,
      !azurerm_storage_container_immutability_policy.draft["candidate"].locked,
      !azurerm_storage_container_immutability_policy.draft["candidate"].protected_append_writes_enabled,
      !azurerm_storage_container_immutability_policy.draft["candidate"].protected_append_writes_all_enabled,
      !output.publication_backend_v1.artifacts.write_role_assigned,
    ])
    error_message = "Storage must remain private, keyless, nonversioned, nonappendable and unqualified."
  }
  assert {
    condition = (
      length(azurerm_container_app_job.nonoperable_scaffold["candidate"].manual_trigger_config) == 1 &&
      length(azurerm_container_app_job.nonoperable_scaffold["candidate"].schedule_trigger_config) == 0 &&
      length(azurerm_container_app_job.nonoperable_scaffold["candidate"].event_trigger_config) == 0 &&
      azurerm_container_app_job.nonoperable_scaffold["candidate"].template[0].container[0].args[0] == "echo 'NONOPERABLE: publication backend is unqualified' >&2; exit 78" &&
      azurerm_container_app_job.nonoperable_scaffold["candidate"].replica_retry_limit == 0
    )
    error_message = "Hosting must remain Manual, finite and fixed exit-78, not a broker implementation."
  }
  assert {
    condition = (
      length(azurerm_private_endpoint.backend) == 2 &&
      azurerm_subnet.hosting["candidate"].address_prefixes == tolist(["10.80.0.0/23"]) &&
      azurerm_subnet.endpoints["candidate"].address_prefixes == tolist(["10.80.2.0/24"]) &&
      azurerm_container_app_environment.scaffold["candidate"].internal_load_balancer_enabled &&
      azurerm_container_app_environment.scaffold["candidate"].public_network_access == "Disabled"
    )
    error_message = "Require separate private subnets, endpoints and internal hosting declarations."
  }
  assert {
    condition = (
      length(azurerm_role_assignment.registry_pull) == 1 &&
      azurerm_role_assignment.registry_pull["candidate"].scope == var.settings.registry_id &&
      azurerm_role_assignment.registry_pull["candidate"].role_definition_name == "AcrPull" &&
      azurerm_role_definition.artifact_broker_candidate["candidate"].permissions[0].data_actions == toset([
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
      ])
    )
    error_message = "Only exact-registry AcrPull is assigned; candidate data role must not acquire delete or wildcard rights."
  }
}

run "reject_retention_lock" {
  command = plan
  variables {
    settings = merge(var.settings, { policy_state = "Locked" })
  }
  expect_failures = [var.settings]
}

run "reject_unqualified_policy_label" {
  command = plan
  variables {
    settings = merge(var.settings, { policy_state = "Qualified" })
  }
  expect_failures = [var.settings]
}

run "reject_missing_horizon" {
  command = plan
  variables {
    settings = merge(var.settings, { retention_days = null })
  }
  expect_failures = [var.settings]
}

run "reject_zero_retention" {
  command = plan
  variables {
    settings = merge(var.settings, { retention_days = 0 })
  }
  expect_failures = [var.settings]
}

run "reject_fractional_retention" {
  command = plan
  variables {
    settings = merge(var.settings, { retention_days = 1.5 })
  }
  expect_failures = [var.settings]
}

run "reject_out_of_range_retention" {
  command = plan
  variables {
    settings = merge(var.settings, { retention_days = 146001 })
  }
  expect_failures = [var.settings]
}

run "reject_unknown_sql_sku" {
  command = plan
  variables {
    settings = merge(var.settings, { sql_sku = "unreviewed" })
  }
  expect_failures = [var.settings]
}

run "reject_geo_replication" {
  command = plan
  variables {
    settings = merge(var.settings, { storage_replication = "GRS" })
  }
  expect_failures = [var.settings]
}

run "reject_public_connectivity" {
  command = plan
  variables {
    settings = merge(var.settings, { private_connectivity = "public" })
  }
  expect_failures = [var.settings]
}

run "reject_noncanonical_network" {
  command = plan
  variables {
    settings = merge(var.settings, { virtual_network_cidr = "10.80.1.0/16" })
  }
  expect_failures = [var.settings]
}

run "reject_public_network_range" {
  command = plan
  variables {
    settings = merge(var.settings, { virtual_network_cidr = "8.8.0.0/16" })
  }
  expect_failures = [var.settings]
}

run "reject_floating_image" {
  command = plan
  variables {
    settings = merge(var.settings, { scaffold_image = "testregistry.azurecr.io/scaffold:latest" })
  }
  expect_failures = [var.settings]
}

run "reject_substituted_registry" {
  command = plan
  variables {
    settings = merge(var.settings, { registry_server = "productionregistry.azurecr.io" })
  }
  expect_failures = [var.settings]
}

run "reject_blank_region" {
  command = plan
  variables {
    settings = merge(var.settings, { location = "" })
  }
  expect_failures = [var.settings]
}

run "reject_missing_admin" {
  command = plan
  variables {
    settings = merge(var.settings, { sql_admin_group_object_id = null })
  }
  expect_failures = [var.settings]
}
