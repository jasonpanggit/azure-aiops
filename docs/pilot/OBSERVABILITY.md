# Platform Observability

## What is already instrumented

| Signal | Mechanism | Where |
| --- | --- | --- |
| API request count/latency/status class | OpenTelemetry counter + histogram, low-cardinality (`route`, `method`, `status_class`) | `src/api/telemetry.py::ApiTelemetry`, wired in `src/api/app.py` request middleware |
| Authorization denials | OpenTelemetry counter (`route`, `reason`) | `ApiTelemetry.record_denied`, called from the auth/RBAC dependency path |
| Provider health (per capability: semantic, network, vulnerability, incident, onboarding, Fabric ontology) | `ProviderRuntime.health()` — state machine (`ready`/`stale`/`partial`/`degraded`/`unavailable`/`disabled`/`loading`), retry counters, freshness/ontology version | `src/api/providers.py`, surfaced at `GET /health` and `GET /ready` |
| Fabric ontology publication status | `runtime.service.ontology_health()` timestamp reconciliation (`timestamp`/`synchronized_at`/`published_at`) | `src/api/runtime.py` |
| Container Apps platform metrics (replica count, CPU/memory, HTTP status) | Azure Monitor / Log Analytics via `logs_destination = "log-analytics"` on the Container App Environment | `infra/terraform/container_apps.tf`, `infra/terraform/main.tf` (`azurerm_log_analytics_workspace.main`, `azurerm_application_insights.main`) |
| Foundry (Copilot) call latency and failure mode | Circuit breaker failure/success counters (in-process); retry attempts logged | `src/operations/foundry_agent.py::_CircuitBreaker` |

## Availability endpoints

- `GET /health` — liveness. Never fails the process; reports `readiness`,
  provider states, ontology version, and freshness without blocking on a
  slow/rate-limited loader (`refresh=False`).
- `GET /ready` — readiness. Triggers a best-effort non-blocking refresh
  (`blocking=False`) and returns `503` unless every **required** provider is
  at least `partial`/`stale`. Container Apps uses this for the readiness
  probe so a genuinely broken deployment is taken out of rotation instead of
  serving 500s.
- Per-connection health: `GET /api/v1/connections/{id}/health` (discovery
  freshness and last successful sync per `SubscriptionConnection`).

## Alerting (new in this phase)

`infra/terraform/alerting.tf` adds an opt-in (`alert_email_addresses`)
Azure Monitor action group plus:

- **API/web availability** — metric alert firing when the API or web
  Container App's average replica count drops below 1 for 15 minutes
  (`azurerm_monitor_metric_alert.api_availability` / `.web_availability`).
- **Provider health / discovery freshness** — scheduled log query
  (`azurerm_monitor_scheduled_query_rules_alert_v2.provider_health`) against
  the Container App Environment's Log Analytics workspace, matching the
  `api_unhandled_error` structured log line the API already emits
  (`src/api/app.py`'s unhandled-exception handler) and readiness-probe
  failures.

Set `alert_email_addresses` in the environment's `.tfvars` before pilot
go-live; it defaults to `[]` (alerts evaluated, nobody notified) so lower
environments aren't forced to have an on-call address.

## Gaps intentionally deferred past this pilot phase

- **Foundry tool latency histogram** is tracked only via the circuit
  breaker's failure counter today, not exported as an OTel histogram. A
  dedicated `aiops.foundry.request.duration` histogram is the natural next
  increment (same shape as `ApiTelemetry`) — tracked as a follow-up, not
  blocking pilot go-live because Foundry failures already degrade safely
  (see `RELIABILITY.md`).
- **Frontend Real User Monitoring** (page load, client error rate) is not
  wired to Application Insights yet. The Application Insights resource
  (`azurerm_application_insights.main`) already exists for this; enabling the
  web app's `@microsoft/applicationinsights-web` SDK is the next increment.
