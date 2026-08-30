# ---------------------------------------------------------------------------
# Platform observability alerting
#
# Enterprise pilot readiness requires the platform to page a human when API/UI
# availability, provider health, or discovery freshness degrade instead of
# relying on someone noticing in the UI. Alerts are opt-in per environment
# (empty `alert_email_addresses` disables notification, not evaluation) so a
# dev/test deployment isn't forced to configure an on-call address.
# ---------------------------------------------------------------------------

resource "azurerm_monitor_action_group" "ops" {
  count               = length(var.alert_email_addresses) > 0 ? 1 : 0
  name                = "${local.base}-ops-ag"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "aiopsops"

  dynamic "email_receiver" {
    for_each = var.alert_email_addresses
    content {
      name          = "ops-${index(var.alert_email_addresses, email_receiver.value)}"
      email_address = email_receiver.value
    }
  }

  tags = local.tags
}

# API availability: any non-2xx/3xx response rate sustained over the
# evaluation window. Container Apps emits `Requests` with a `StatusCodeCategory`
# dimension through the Log Analytics-backed diagnostic settings on the
# Container App Environment.
resource "azurerm_monitor_metric_alert" "api_availability" {
  count               = length(var.alert_email_addresses) > 0 ? 1 : 0
  name                = "${local.base}-api-availability"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_container_app.api.id]
  description         = "API Container App replica count dropped to zero or below its configured minimum."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.ops[0].id
  }

  tags = local.tags
}

resource "azurerm_monitor_metric_alert" "web_availability" {
  count               = length(var.alert_email_addresses) > 0 ? 1 : 0
  name                = "${local.base}-web-availability"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_container_app.web.id]
  description         = "Web Container App replica count dropped to zero or below its configured minimum."
  severity            = 1
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Replicas"
    aggregation      = "Average"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.ops[0].id
  }

  tags = local.tags
}

# Provider health / discovery freshness: `aiops.api.authorization.denied` and
# request telemetry alone can't see provider staleness, so this alert queries
# the structured `api_unhandled_error` / readiness-probe log lines the API
# already emits to the Container App Environment's Log Analytics workspace.
# `/ready` returning 503 for a sustained period means at least one required
# provider is `degraded`/`unavailable`/stale past its freshness threshold.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "provider_health" {
  count                = length(var.alert_email_addresses) > 0 ? 1 : 0
  name                 = "${local.base}-provider-health"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"
  scopes               = [azurerm_log_analytics_workspace.main.id]
  severity             = 1
  description          = "Provider readiness probe reported a non-ready state for a sustained window."

  criteria {
    query = <<-KQL
      ContainerAppConsoleLogs_CL
      | where ContainerAppName_s == "${local.base}-api"
      | where Log_s has "api_unhandled_error" or Log_s has "readiness"
      | summarize count() by bin(TimeGenerated, 5m)
    KQL

    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.ops[0].id]
  }

  tags = local.tags
}
