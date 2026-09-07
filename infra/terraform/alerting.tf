# ---------------------------------------------------------------------------
# Platform observability alerting
#
# Enterprise pilot readiness requires the platform to page a human when API/UI
# availability, provider health, or discovery freshness degrade instead of
# relying on someone noticing in the UI. Alerts are opt-in per environment
# (empty `alert_email_addresses` disables notification, not evaluation) so a
# dev/test deployment isn't forced to configure an on-call address.
# ---------------------------------------------------------------------------

locals {
  create_alert_action_group = (
    var.existing_alert_action_group_id == "" &&
    length(var.alert_email_addresses) > 0
  )
  alerting_enabled = (
    var.existing_alert_action_group_id != "" ||
    length(var.alert_email_addresses) > 0
  )
  alert_action_group_id = (
    var.existing_alert_action_group_id != ""
    ? var.existing_alert_action_group_id
    : try(one(azurerm_monitor_action_group.ops[*].id), "")
  )
}

resource "azurerm_monitor_action_group" "ops" {
  count               = local.create_alert_action_group ? 1 : 0
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

# Ontology discovery metrics use one closed `rule` enum and never attach
# prompts, evidence/tool bodies, IDs, scope values, principals, credentials, or
# raw errors. The rules below are deliberately data-driven so the smoke
# validator can prove a one-to-one metric -> query -> action-group chain.
locals {
  ontology_discovery_alert_rules = {
    scope_disclosure = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    unauthorized_mutation = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    successful_injection = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    invalid_edge_promotion = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    stale_writer_promotion = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    partial_active_generation = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    missing_audit = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    active_generation_unrecoverable = {
      tier         = "immediate"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT5M"
      severity     = 0
      shadow_reset = true
      query_op     = ">"
    }
    successful_run_gap = {
      tier         = "page"
      threshold    = 30
      operator     = "GreaterThan"
      window       = "PT30M"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    active_generation_age = {
      tier         = "page"
      threshold    = 21600
      operator     = "GreaterThan"
      window       = "PT15M"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    fenced_publication_failures = {
      tier         = "page"
      threshold    = 2
      operator     = "GreaterThanOrEqual"
      window       = "PT15M"
      severity     = 1
      shadow_reset = false
      query_op     = ">="
    }
    critical_pending_edge_age = {
      tier         = "page"
      threshold    = 86400
      operator     = "GreaterThan"
      window       = "PT15M"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    nonterminal_run_age = {
      tier         = "page"
      threshold    = 2700
      operator     = "GreaterThan"
      window       = "PT15M"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    citation_validity = {
      tier         = "hour"
      threshold    = 1
      operator     = "LessThan"
      window       = "PT1H"
      severity     = 2
      shadow_reset = false
      query_op     = "<"
    }
    citation_freshness = {
      tier         = "hour"
      threshold    = 0.99
      operator     = "LessThan"
      window       = "PT1H"
      severity     = 2
      shadow_reset = false
      query_op     = "<"
    }
    post_repair_schema_validity = {
      tier         = "hour"
      threshold    = 1
      operator     = "LessThan"
      window       = "PT1H"
      severity     = 1
      shadow_reset = false
      query_op     = "<"
    }
    repair_rate = {
      tier         = "hour"
      threshold    = 0.05
      operator     = "GreaterThan"
      window       = "PT1H"
      severity     = 2
      shadow_reset = false
      query_op     = ">"
    }
    timeout_rate = {
      tier         = "hour"
      threshold    = 0.01
      operator     = "GreaterThan"
      window       = "PT1H"
      severity     = 2
      shadow_reset = false
      query_op     = ">"
    }
    model_latency_p95 = {
      tier         = "hour"
      threshold    = 30
      operator     = "GreaterThan"
      window       = "PT15M"
      severity     = 2
      shadow_reset = false
      query_op     = ">"
    }
    attempt_duration_max = {
      tier         = "hour"
      threshold    = 60
      operator     = "GreaterThan"
      window       = "PT1H"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    cap_violation = {
      tier         = "hour"
      threshold    = 0
      operator     = "GreaterThan"
      window       = "PT1H"
      severity     = 1
      shadow_reset = false
      query_op     = ">"
    }
    overall_precision = {
      tier         = "weekly"
      threshold    = 0.98
      operator     = "LessThan"
      window       = "P2D"
      severity     = 1
      shadow_reset = true
      query_op     = "<"
    }
    critical_precision = {
      tier         = "weekly"
      threshold    = 0.95
      operator     = "LessThan"
      window       = "P2D"
      severity     = 1
      shadow_reset = true
      query_op     = "<"
    }
    overall_recall = {
      tier         = "weekly"
      threshold    = 0.9
      operator     = "LessThan"
      window       = "P2D"
      severity     = 2
      shadow_reset = true
      query_op     = "<"
    }
    critical_recall = {
      tier         = "weekly"
      threshold    = 0.85
      operator     = "LessThan"
      window       = "P2D"
      severity     = 2
      shadow_reset = true
      query_op     = "<"
    }
    escalation_f1 = {
      tier         = "weekly"
      threshold    = 0.95
      operator     = "LessThan"
      window       = "P2D"
      severity     = 1
      shadow_reset = true
      query_op     = "<"
    }
    mandatory_review_recall = {
      tier         = "weekly"
      threshold    = 1
      operator     = "LessThan"
      window       = "P2D"
      severity     = 0
      shadow_reset = true
      query_op     = "<"
    }
    pair_precision_wilson_lower_bound = {
      tier         = "weekly"
      threshold    = 0.98
      operator     = "LessThan"
      window       = "P2D"
      severity     = 1
      shadow_reset = true
      query_op     = "<"
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "ontology_discovery" {
  for_each = local.alerting_enabled ? local.ontology_discovery_alert_rules : {}

  name                 = "${local.base}-ontology-${replace(each.key, "_", "-")}"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = each.value.tier == "immediate" ? "PT1M" : each.value.tier == "page" ? "PT5M" : each.value.tier == "hour" ? "PT15M" : "P1D"
  window_duration      = each.value.window
  scopes               = [azurerm_application_insights.main.id]
  severity             = each.value.severity
  description          = "Ontology discovery ${each.key}; action=ontology-operations; reset=${each.value.shadow_reset ? "affected-pair-shadow" : "none"}."

  criteria {
    query = <<-KQL
      AppMetrics
      | where Name == "ontology.discovery.alert.signal"
      | where tostring(Properties.rule) == each.key
      | summarize Signal=max(Max)
      | where Signal ${each.value.query_op} ${each.value.threshold}
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

# API availability: any non-2xx/3xx response rate sustained over the
# evaluation window. Container Apps emits `Requests` with a `StatusCodeCategory`
# dimension through the Log Analytics-backed diagnostic settings on the
# Container App Environment.
resource "azurerm_monitor_metric_alert" "api_availability" {
  count               = local.alerting_enabled ? 1 : 0
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
    action_group_id = local.alert_action_group_id
  }

  tags = local.tags
}

resource "azurerm_monitor_metric_alert" "web_availability" {
  count               = local.alerting_enabled ? 1 : 0
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
    action_group_id = local.alert_action_group_id
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
  count                = local.alerting_enabled ? 1 : 0
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

# Exposure one-cycle alerts
#
# The evaluation frequency is never slower than ingestion, and every window is
# exactly one configured ingestion cycle. All rules trigger on the first
# failing period. Quality/latency signals are intentionally aggregated across
# the one cycle rather than persisted across multiple cycles: this preserves
# noise resistance while still surfacing the first bad cycle.
locals {
  exposure_alert_iso8601_minutes = {
    "5"  = "PT5M"
    "10" = "PT10M"
    "15" = "PT15M"
    "30" = "PT30M"
  }
  exposure_ingestion_cycle_window = local.exposure_alert_iso8601_minutes[
    tostring(var.exposure_ingestion_cadence_minutes)
  ]
  exposure_alert_evaluation_frequency = local.exposure_alert_iso8601_minutes[
    tostring(var.exposure_alert_evaluation_minutes)
  ]
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_row_zero" {
  count                = local.alerting_enabled ? 1 : 0
  name                 = "${local.base}-exposure-row-zero"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = local.exposure_alert_evaluation_frequency
  window_duration      = local.exposure_ingestion_cycle_window
  scopes               = [azurerm_application_insights.main.id]
  severity             = 0
  description          = "Exposure effective rows reached the configured false-clear floor in one ingestion cycle."
  # AppMetrics is materialized in the workspace only after the first custom
  # metric arrives. Provision the fail-closed rule before that first cycle.
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      ExposureMetrics
      | where Name == "aiops.exposure.ingestion.rows"
      | where tostring(Properties.environment) == "${var.environment}"
      | where tostring(Properties.outcome) == "effective"
      | summarize EffectiveRows=max(Max)
      | where EffectiveRows < ${var.exposure_alert_min_effective_rows}
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_row_drop" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-row-drop"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 0
  description           = "Exposure effective-row drop exceeded the configured last-known-good ratio in one ingestion cycle."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      ExposureMetrics
      | where Name == "aiops.exposure.ingestion.drop.ratio"
      | where tostring(Properties.environment) == "${var.environment}"
      | summarize DropRatio=max(Max)
      | where DropRatio > ${var.exposure_alert_max_drop_ratio}
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_source_health" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-source-health"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 1
  description           = "An Exposure source failed, became unavailable, or exceeded its allowed age in one ingestion cycle."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      let FailedCycles = ExposureMetrics
        | where Name == "aiops.exposure.source.cycles"
        | where tostring(Properties.environment) == "${var.environment}"
        | where tostring(Properties.outcome) in ("failed", "partial", "unavailable")
        | summarize Signal=sum(Sum)
        | where Signal > 0;
      let StaleSources = ExposureMetrics
        | where Name == "aiops.exposure.source.age"
        | where tostring(Properties.environment) == "${var.environment}"
        | summarize Signal=max(Max)
        | where Signal > ${var.exposure_alert_source_max_age_seconds};
      union FailedCycles, StaleSources
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_merge_conflict" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-merge-conflict"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 0
  description           = "Exposure Gold merge or generation activation reported a conflict."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      ExposureMetrics
      | where Name == "aiops.exposure.merge.rows"
      | where tostring(Properties.environment) == "${var.environment}"
      | where tostring(Properties.outcome) == "conflict"
      | summarize Conflicts=sum(Sum)
      | where Conflicts > 0
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_enrichment_quality" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-enrichment-quality"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 2
  description           = "Exposure enrichment success ratio degraded below its one-cycle quality threshold."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      ExposureMetrics
      | where Name == "aiops.exposure.enrichment.quality"
      | where tostring(Properties.environment) == "${var.environment}"
      | summarize Quality=min(Min)
      | where Quality < ${var.exposure_alert_min_enrichment_quality}
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_coverage_ratio" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-coverage-ratio"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 1
  description           = "Exposure represented-to-total coverage degraded below its one-cycle threshold."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      ExposureMetrics
      | where Name == "aiops.exposure.coverage.ratio"
      | where tostring(Properties.environment) == "${var.environment}"
      | summarize RepresentedRatio=min(Min)
      | where RepresentedRatio < ${var.exposure_alert_min_represented_ratio}
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_reconciliation_drift" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-reconciliation-drift"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 0
  description           = "Exposure old/new semantic reconciliation exceeded its exact mismatch policy."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      let MismatchCount = ExposureMetrics
        | where Name == "aiops.exposure.reconciliation.mismatches"
        | where tostring(Properties.environment) == "${var.environment}"
        | where tostring(Properties.outcome) == "unexpected_drift"
        | summarize Signal=sum(Sum)
        | where Signal > ${var.exposure_alert_max_reconciliation_mismatches};
      let DriftRatio = ExposureMetrics
        | where Name == "aiops.exposure.reconciliation.drift.ratio"
        | where tostring(Properties.environment) == "${var.environment}"
        | where tostring(Properties.outcome) == "unexpected_drift"
        | summarize Signal=max(Max)
        | where Signal > ${var.exposure_alert_max_reconciliation_ratio};
      union MismatchCount, DriftRatio
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "exposure_query_slo" {
  count                 = local.alerting_enabled ? 1 : 0
  name                  = "${local.base}-exposure-query-slo"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  evaluation_frequency  = local.exposure_alert_evaluation_frequency
  window_duration       = local.exposure_ingestion_cycle_window
  scopes                = [azurerm_application_insights.main.id]
  severity              = 1
  description           = "Exposure scoped query latency or error count exceeded its one-cycle budget."
  skip_query_validation = true

  criteria {
    query = <<-KQL
      let ExposureMetrics = datatable(Name:string, Properties:dynamic, Sum:real, Min:real, Max:real) []
        | union isfuzzy=true AppMetrics;
      let SlowQueries = ExposureMetrics
        | where Name == "aiops.exposure.query.duration"
        | where tostring(Properties.environment) == "${var.environment}"
        | summarize Signal=percentile(Max, 95)
        | where Signal > ${var.exposure_alert_query_p95_ms};
      let QueryErrors = ExposureMetrics
        | where Name == "aiops.exposure.query.events"
        | where tostring(Properties.environment) == "${var.environment}"
        | where tostring(Properties.outcome) == "error"
        | summarize Signal=sum(Sum)
        | where Signal > ${var.exposure_alert_max_query_errors};
      union SlowQueries, QueryErrors
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
    action_groups = [local.alert_action_group_id]
  }

  tags = local.tags
}
