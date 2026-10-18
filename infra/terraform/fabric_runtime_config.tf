locals {
  fabric_runtime_defaults = {
    for key, value in yamldecode(file("${path.module}/../../fabric.config.deploy.yaml")).fabric :
    key => value if key != "gold_grounding_agent"
  }
  fabric_runtime_config = var.enable_fabric ? merge(local.fabric_runtime_defaults, {
    workspace_id                = fabric_workspace.ops[0].id
    workspace_name              = fabric_workspace.ops[0].display_name
    lakehouse_id                = fabric_lakehouse.context_graph[0].id
    lakehouse_name              = fabric_lakehouse.context_graph[0].display_name
    source_data_root            = local.onelake_aiops_home
    create_lakehouse_if_missing = false
    auth = {
      mode                       = "managed_identity"
      tenant_id                  = var.tenant_id
      managed_identity_client_id = azurerm_user_assigned_identity.apps.client_id
    }
    sql_endpoint = {
      server   = fabric_lakehouse.context_graph[0].properties.sql_endpoint_properties.connection_string
      database = fabric_lakehouse.context_graph[0].properties.sql_endpoint_properties.id
      schema   = "dbo"
    }
    capacity = {
      subscription_id = var.subscription_id
      resource_group  = azurerm_resource_group.main.name
      capacity_name   = azurerm_fabric_capacity.main[0].name
    }
    ontology = merge(local.fabric_runtime_defaults.ontology, {
      enabled = var.enable_fabric_ontology_item
    })
    }, var.fabric_gold_grounding_agent_id == "" ? {} : {
    gold_grounding_agent = {
      display_name = "AI Ops Data Agent"
      item_id      = var.fabric_gold_grounding_agent_id
    }
  }) : null
  onelake_aiops_home = var.enable_fabric ? "abfss://${fabric_workspace.ops[0].id}@onelake.dfs.fabric.microsoft.com/${fabric_lakehouse.context_graph[0].id}/Files/aiops" : "/tmp/aiops"
  fabric_publisher_runtime_config = var.enable_fabric ? merge(local.fabric_runtime_config, {
    auth = {
      mode                       = "managed_identity"
      tenant_id                  = var.tenant_id
      managed_identity_client_id = azurerm_user_assigned_identity.ontology_publisher.client_id
    }
  }) : null
}
