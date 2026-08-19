# Azure MCP Capabilities — Live Discovery

## 1. Discovery scope and current state

This inventory was generated from the live environment on 2026-08-17. It is the current runtime-discovery artifact for this task; the pre-existing uppercase `AZURE_MCP_CAPABILITIES.md` documents an earlier stable/documentation baseline and must not override the live beta tool enumeration below.

- Hermes Agent: `v0.20.2 (2026.8.16)`.
- Configured Hermes MCP servers: **none** (`hermes mcp list`).
- Ephemeral Azure MCP discovery command: `npx -y @azure/mcp@latest`.
- Resolved Azure MCP version: **3.0.0-beta.35** (`8c7fcd...`).
- Azure authentication was not required to enumerate tool schemas; no Azure data operation was executed.
- Azure MCP exposed 64 top-level namespaces in namespace mode and 45 individual tools in the operationally relevant namespaces inventoried below.

Production must pin and test an approved Azure MCP version. Do not use `latest`, and do not confuse a discovered beta schema with a configured/authorized production server.

## 2. Architecture conclusion

Reuse Azure MCP for live, bounded agent/operator queries where a native tool exists. Do not make it the deterministic ingestion contract.

Current important gaps:

| Area | Finding | Required strategy |
|---|---|---|
| Azure Resource Graph | No general-purpose arbitrary ARG query tool. `insights get`, Advisor metadata, and Workbooks may use ARG internally. | Direct ARG REST/SDK/CLI for versioned discovery queries. |
| Azure Arc | No Arc/Connected Machine namespace. | ARG `Microsoft.HybridCompute/machines` and Arc APIs. |
| Defender | No Defender namespace. | Defender for Cloud APIs, ARG security tables, or existing export/LAW. |
| Sentinel | No Sentinel namespace. | Sentinel management APIs and authorized LAW KQL. |
| Update Manager | No Update Manager namespace. | Update Manager APIs and ARG patch extension tables. |
| Cost Management | No Cost Management/billing query namespace. `pricing get` is retail price lookup only. | Cost Management Exports/Query API for actual cost; pricing only for SKU reference. |
| Entra directory | Tenant parameter/authentication and Azure RBAC tools do not expose directory users/groups/owners. | Microsoft Graph. |

## 3. Reuse rules

- Enable only exact read-only namespaces/tools required by the Foundry/Hermes profile.
- Keep write/destructive tools disabled for discovery, stewardship, and incident learning.
- Store underlying Azure source/query provenance, not merely `azure-mcp`.
- Use Azure MCP Monitor KQL for interactive/targeted use; scheduled production queries remain versioned Azure Monitor Query SDK/API assets.
- `insights get` is sampled/summarized infrastructure analysis, not canonical inventory.
- `group resource list` is resource-group scoped and is not a replacement for cross-subscription ARG.
- `applicationinsights recommendation list` does not query traces/dependencies/Application Map.
- `pricing get` does not return organization usage, invoices, budgets, amortized cost, or cost-centre allocation.

## 4. Tool matrix — subscription and resource discovery

Inputs listed as `required; optional`. Outputs summarize the documented response.

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `subscription_list` | List accessible subscriptions and default context. | none; `tenant` | subscription ID, display name, state, tenant ID, default flag | Reuse for operator context/bootstrap; ARG remains resource authority. |
| `group_list` | List resource groups in a subscription. | none; `subscription`, `tenant` | resource-group names and IDs | Reuse for targeted navigation/reconciliation. |
| `group_resource_list` | List resources in one resource group. | `resource-group`; `subscription`, `tenant` | resource names, IDs, types, locations | Reuse for a bounded inspection; not estate inventory. |
| `insights_get` | Analyze subscription/tenant infrastructure with ARG-backed aggregation and MCP sampling. | none; `query`, `nocache`, `scope`, `subscription`, `tenant` | summarized composition, patterns, trends, scenario insights | Reuse for human planning and anomaly hypotheses only; never emit authoritative entities directly. |

## 5. Tool matrix — Compute and AKS

### Read-only tools suitable for discovery

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `compute_vm_get` | List VMs or get one VM; optional instance view. | none; `vm-name`, `instance-view`, `resource-group`, `subscription`, `tenant` | name, location, size, provisioning/OS/network details; optional power/runtime status | Reuse for targeted VM detail/status after ARG identity. |
| `compute_vmss_get` | List/get VM scale sets and optional instance. | none; `vmss-name`, `instance-id`, `resource-group`, `subscription`, `tenant` | VMSS location, SKU, capacity, policy, instances | Reuse for targeted topology/status. |
| `compute_disk_get` | List/get managed disks, supports wildcard name. | none; `disk-name`, `resource-group`, `subscription`, `tenant` | size, SKU, provisioning state, OS type, attachment-relevant details | Reuse for disk context; ARG can provide deterministic bulk view. |
| `aks_cluster_get` | List/get AKS clusters. | none; `tenant`, `subscription`, `resource-group`, `cluster` | cluster resource/configuration including IDs, endpoint/identity/provisioning metadata | Reuse for targeted AKS control-plane details. |
| `aks_nodepool_get` | List/get node pools for a cluster. | `resource-group`, `cluster`; `tenant`, `subscription`, `nodepool` | node-pool configuration and provisioning metadata | Reuse for cluster topology; it does not inspect pods/services/workloads. |

### Write/destructive Compute tools — exclude from HOG profiles

| Tool | Capability | Required inputs | Output | Strategy |
|---|---|---|---|---|
| `compute_vm_create` | Create VM and supporting networking. | `vm-name`, `location`, `image`, `admin-username`, `resource-group` | created VM/deployment details | Disable. |
| `compute_vm_delete` | Permanently delete VM. | `vm-name`, `resource-group` | deletion result | Disable. |
| `compute_vm_power-state` | Start/stop/deallocate/restart VM. | `vm-name`, `power-action`, `resource-group` | operation/status, optional async status URI | Disable. |
| `compute_vm_update` | Resize/tag/configure VM. | `vm-name`, `resource-group` | updated VM | Disable. |
| `compute_vmss_create` | Create VMSS. | `vmss-name`, `location`, `image`, `admin-username`, `resource-group` | created VMSS | Disable. |
| `compute_vmss_delete` | Delete VMSS and instances. | `vmss-name`, `resource-group` | deletion result | Disable. |
| `compute_vmss_update` | Update capacity/size/policy/tags. | `vmss-name`, `resource-group` | updated VMSS | Disable. |
| `compute_disk_create` | Create managed disk. | `disk-name`, `resource-group` | created disk | Disable. |
| `compute_disk_delete` | Delete managed disk. | `disk-name`, `resource-group` | deletion flag | Disable. |
| `compute_disk_update` | Resize/reconfigure/tag disk. | `disk-name` | updated disk | Disable. |

## 6. Tool matrix — Azure Monitor and Log Analytics

### Read-only tools to reuse

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `monitor_activitylog_list` | Activity logs for a named resource. | `resource-name`; `resource-type`, `hours`, `event-level`, `top`, `tenant`, `subscription`, `resource-group` | event timestamp, operation, status, caller and activity context | Reuse as change/incident evidence; not final state. |
| `monitor_workspace_list` | List LAW workspaces. | none; `tenant`, `subscription`, `resource-group` | workspace names, IDs and properties | Reuse for workspace discovery. |
| `monitor_table_type_list` | List available table types. | `workspace`, `resource-group`; `tenant`, `subscription` | table type names | Reuse during query capability validation. |
| `monitor_table_list` | List tables/schemas for a type. | `workspace`, `table-type`, `resource-group`; `tenant`, `subscription` | table names and schemas | Reuse for schema discovery/drift checks. |
| `monitor_workspace_log_query` | Read-only KQL over a workspace/table. | `workspace`, `query`, `table`; `hours`, `limit`, `tenant`, `subscription` | bounded KQL result rows | Reuse for targeted/interactive evidence; aggregate in source. |
| `monitor_resource_log_query` | Read-only KQL for a specific resource/table. | `query`, `table`, `resource-id`; `hours`, `limit`, `tenant`, `subscription` | resource-filtered bounded KQL rows | Reuse for incident/dependency drill-down. |
| `monitor_metrics_definitions` | List metric definitions. | `resource`; `search-string`, `limit`, `metric-namespace`, `resource-type`, `tenant`, `subscription`, `resource-group` | metric names/namespaces/aggregations/descriptions | Reuse to construct a targeted metrics query. |
| `monitor_metrics_query` | Query resource metric time series. | `metric-names`, `metric-namespace`, `resource`; `start-time`, `end-time`, `interval`, `aggregation`, `filter`, `max-buckets`, `resource-type`, scope | bounded metric time series | Reuse for live context; do not materialize metric history. |
| `monitor_healthmodels_list` | List Azure Monitor Health Models. | none; `tenant`, `subscription`, `resource-group` | model name, resource group, location | Optional context; not the Fabric ontology. |
| `monitor_healthmodels_get` | Get a named Health Model. | `health-model`, `resource-group`; `tenant`, `subscription` | metadata and possible health state | Optional context. |
| `monitor_webtests_get` | List/get Azure Monitor web tests. | none; `webtest-resource`, `tenant`, `subscription`, `resource-group` | web-test configuration/details | Reuse as availability-test/Runbook context if needed. |
| `monitor_instrumentation_get-learning-resource` | List/get instrumentation guidance. | none; `path` | resource paths or guidance content | Reuse during instrumentation onboarding, not discovery. |

### Monitor write/workspace mutation tools — exclude

| Tool | Capability | Inputs | Output | Strategy |
|---|---|---|---|---|
| `monitor_webtests_createorupdate` | Create/update availability web test. | `webtest-resource`, `resource-group`; many web-test settings | created/updated test | Disable. |
| `monitor_instrumentation_orchestrator-start` | Analyze local workspace and begin instrumentation changes. | `workspace-path` | first action/session | Disable in production HOG. |
| `monitor_instrumentation_orchestrator-next` | Continue instrumentation workflow. | `session-id`, `completion-note` | next action/completion | Disable. |
| `monitor_instrumentation_send-brownfield-analysis` | Submit code-analysis findings to workflow. | `session-id`, `findings-json` | workflow state | Disable. |
| `monitor_instrumentation_send-enhancement-select` | Select instrumentation enhancements. | `session-id`, `enhancement-keys` | workflow state | Disable. |

## 7. Application Insights

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `applicationinsights_recommendation_list` | List code-optimization recommendations from profiler data. | none; `tenant`, `subscription`, `resource-group` | recommendation records across App Insights components | Reuse as optional Finding source. It does not expose requests, dependencies, traces, Application Map, or live metrics. Use Monitor KQL/API for those. |

## 8. Resource Health and Service Health

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `resourcehealth_availability-status_get` | Get availability for one or all accessible resources. | none; `resourceId`, `resource-group`, `subscription`, `tenant` | Available/Unavailable/Degraded/Unknown plus reason/details | Reuse for live operational status and incident corroboration. |
| `resourcehealth_health-events_list` | List planned maintenance, incidents, advisories, security events. | none; `event-type`, `status`, `tracking-id`, `filter`, time range, scope | tracking ID, title, summary, type/status, times, impacted services | Reuse for Incident/impact context; retain links/compact projection only. |

## 9. Advisor

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `advisor_metadata_get` | Get one recommendation type. | `recommendation-type-id`; `language` | name/category/impact/resource type/description/benefits/actions | Reuse to normalize Finding type. |
| `advisor_metadata_list` | Query global recommendation metadata and retirements. | none; language/resource type/impact/category/subcategory/tracking ID/retirement date | type IDs, categories, impact, actions, scope, retirement details | Reuse for type catalog and service-retirement context. |
| `advisor_recommendation_list` | List active recommendation records. | none; filters, `top`, scope | up to 100 active recommendation rows | Reuse as Finding source for details; preserve list cap. |
| `advisor_recommendation_summary` | Server-side grouped counts/total. | none; `group-by`, filters, `top`, scope | true total and grouped counts | Reuse for coverage/quality summaries, not individual findings. |
| `advisor_recommendation_apply` | Return rules for applying recommendation to IaC. | `resource` | IaC recommendation rules | Exclude from read-only discovery; optionally link as remediation guidance after review. |

## 10. Cost and pricing

| Tool | Capability | Inputs | Output | Reuse strategy |
|---|---|---|---|---|
| `pricing_get` | Query Azure Retail Prices for explicit SKU/service/region filters. | none; `currency`, `sku`, `service`, `region`, `service-family`, `price-type`, `include-savings-plan`, `filter` | retail meter/SKU price records | Reuse only as reference-price enrichment. It is not Cost Management, actual usage, budget, export, invoice, or CostCentre allocation. |

## 11. Requested areas with no native tools

### Azure Resource Graph

No arbitrary query command was discovered. `insights_get` returns sampled/summarized insights, and some tools internally use ARG. HOG must use direct ARG REST/SDK/CLI for deterministic KQL, paging, exact projections, and resource-change tables.

### Azure Arc

No Arc/Connected Machine tool was discovered. `group_resource_list` may enumerate Arc resource IDs only within one resource group; it does not supply a complete Arc operational contract. Use ARG/Arc APIs.

### Defender

No Defender for Cloud/Defender XDR tool was discovered. Use service APIs, ARG security tables, or existing LAW/export path.

### Sentinel

No Sentinel tool was discovered. Generic Monitor KQL can query Sentinel tables already in an authorized LAW, but incident lifecycle requires Sentinel APIs.

### Update Manager

No Update Manager tool was discovered. Use Update Manager APIs and ARG patch assessment/installation extension tables.

### Cost Management

No Cost Management tool was discovered. Use Cost Management Query/Exports APIs. Retail Pricing is not a substitute.

## 12. Other discovered namespaces relevant later

The current Azure MCP namespace catalog also includes `policy`, `role`, `sreagent`, `kusto`, `eventgrid`, `eventhubs`, `servicebus`, `keyvault`, `sql`, `storage`, `postgres`, `mysql`, `containerapps`, `appservice`, `functionapp`, `deviceregistry`, `resilience`, `quota`, `workbooks`, `foundryextensions`, and others.

Before using any of them:

1. enumerate the exact version-pinned sub-tools with `--learn`;
2. classify read/write/destructive/secret/local-required metadata;
3. allowlist only the specific read tools;
4. record inputs/outputs and fallback source API;
5. add compatibility tests.

## 13. Hermes integration strategy

- Add Azure MCP through `hermes mcp add` only after pinning and security review.
- Configure tool selection so only approved namespaces/sub-tools are exposed.
- Disable MCP sampling unless a concrete trusted Azure MCP workflow needs server-initiated model calls.
- Use a separate discovery identity with least-privilege Azure RBAC.
- Keep MCP tools deferrable/tier-disclosed to avoid sending a large schema on every model call.
- Cron already performs MCP discovery at job startup; pin toolsets so scheduled jobs receive only approved Azure tools.
- Maintain a versioned capability registry with runtime tool name, version, inputs, outputs, metadata, RBAC, last test, and fallback.

## References

[1] Microsoft, Azure MCP Server repository. https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server

[2] Microsoft, Azure MCP command reference. https://github.com/microsoft/mcp/blob/main/servers/Azure.Mcp.Server/docs/azmcp-commands.md

[3] Microsoft, Azure MCP Server documentation. https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/
