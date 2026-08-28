# AIOps Operations Graph — Data Sources

## 1. Source strategy

AIOps Operations Graph (HOG) federates authoritative observations with a
durable semantic graph; it does not replace or snapshot the listed systems.

| Information | Authority | What HOG retains |
|---|---|---|
| Azure resource existence/configuration | Azure Resource Graph (ARG) | Semantic identity/relationship evidence; current values are queried live. |
| Logs/metrics/traces | Azure Monitor, LAW, App Insights, OpenTelemetry destination | Relationship evidence and references; raw/current telemetry stays in the source. |
| Security operations incidents | Microsoft Sentinel / approved ITSM process | Incident projection and links. |
| Cloud security findings | Defender for Cloud | Finding identity/status and affected-resource link. |
| Patch assessment/install state | Azure Update Manager | Patch identity and compact machine relationship/status. |
| Directory identity | Microsoft Entra ID / Microsoft Graph | Tenant-scoped object IDs and approved team/application aliases. |
| CMDB/service portfolio/ITSM | ServiceNow, where designated | Approved service/team/incident/runbook references; no CMDB mirror. |
| Engineering/delivery | Azure DevOps | Team/repository/pipeline/work-item/runbook references. |

Every adapter uses allowlisted fields, native stable IDs, scoped live reads or
targeted relationship evidence, a source observation timestamp, and a deep
link/API locator. Raw payload retention is prohibited unless separately
approved. Full reconciliation may publish the durable semantic graph, but it
must not become the UI's source of current operational values.

## 2. Azure Resource Graph (ARG)

**Contribution**

- Authoritative Azure control-plane resource projection across scopes visible to the caller.
- Resource entity spine: ARM ID, type, tenant/subscription/resource group, location, tags, SKU, identity, and provider-specific properties.
- Deterministic topology from resource properties and ARG extension tables.
- Resource-change records for configuration history where supported.[1][2]

**Access**

- ARG REST API/SDK/Azure CLI/PowerShell and Resource Graph Explorer.
- Versioned KQL-dialect queries at management-group/subscription/tenant scope.
- Use the native ARG path for Resource Discovery Engine; current Azure MCP tooling is not a general arbitrary ARG query surface.

**Stable identifiers**

- ARM resource `id` as primary key, tenant-scoped and compared case-insensitively.
- `subscriptionId`, `resourceGroup`, `type`, provider-specific IDs.
- Resource-change identifiers/timestamps for temporal evidence.

**Freshness**

ARG is optimized for current control-plane discovery and is updated as Resource Providers publish changes; it is not a transaction stream. Use periodic reconciliation plus supported resource-change queries, and record query completion time.[1][2]

**Constraints**

- Results are limited to caller RBAC and query scope.
- ARG has throttling and paging; queries can return partial pages.
- Resource-provider schemas vary and properties can be absent.
- Tags are evidence, not automatically authoritative business mappings.
- One failed/partial scan cannot imply deletion.

**Graph mappings**

Resource entities; deterministic `hosts`, `dependsOn`, `supports`, and candidate `ownedBy` from approved mappings.

## 3. Azure Monitor and Log Analytics Workspace (LAW)

**Contribution**

- Alerts, activity, health, diagnostics, operational events, and retained queryable telemetry.
- Cross-resource KQL summaries used as evidence for dependencies, impacts, and incident context.
- Platform telemetry for HOG itself.

**Access**

- Azure Monitor Logs Query API/SDK, KQL, resource-centric or workspace queries.[3]
- Azure MCP Server can list LAW workspaces/tables and execute bounded workspace/resource log queries.
- Azure Monitor Metrics APIs/tools for live aggregate metric context.

**Stable identifiers**

- LAW resource/tenant/workspace IDs.
- `_ResourceId`/ARM IDs when present.
- `OperationId`, `CorrelationId`, alert IDs, table-specific record IDs, `TimeGenerated`.

**Freshness**

Near-real-time after collection, buffering, transformation, and indexing. Ingestion latency varies by data type and pipeline; record both event time and ingestion/query time.[4]

**Constraints**

- LAW remains the log store. HOG must not copy raw tables.
- Retention, table plan, archive, ingestion, query, and export costs vary.
- API concurrency, query time, result size, and throttling limits apply.[5]
- A missing row can mean latency, sampling, retention, scope, or collection failure—not absence of a relationship.
- Avoid querying the same Sentinel/Defender data through multiple paths and counting it as corroboration.

**Graph mappings**

Aggregate evidence for `dependsOn`, `impacts`, and last-observed status. Not a canonical Resource identity source when an ARM ID is available from ARG.

## 4. Application Insights

**Contribution**

- Application/service identity and observed request/dependency topology.
- Trace correlations, dependency target/type/success/duration, exceptions, availability tests, and application-map context.
- Strong evidence for Application entities and runtime `dependsOn` relationships.[6]

**Access**

- Application Insights workspace-based tables through Azure Monitor KQL/Logs APIs.
- Azure Portal Application Map for operator validation.
- Azure MCP’s App Insights-specific native tool is currently narrow (code-optimization recommendations); general dependency data should use KQL/API.

**Stable identifiers**

- App Insights component ARM ID.
- `cloud_RoleName`/service identity, operation/trace/span IDs, dependency target/name/type.
- Prefer OpenTelemetry resource attributes and explicit application catalog keys over display names.

**Freshness**

Near-real-time after SDK/exporter processing, sampling, ingestion, and indexing.

**Constraints**

- Sampling and missing instrumentation reduce completeness.
- Auto-collected dependencies can be noisy or target transient endpoints.
- Role instance is not an Application identity; instance churn must not create new applications.
- Application Map is observed topology, not declared business dependency truth.

**Graph mappings**

Application entities; Resource `hosts` Application; Application `dependsOn` Application/Resource; provisional incident `impacts` Application.

## 5. OpenTelemetry on Azure

**Contribution**

- Vendor-neutral traces, metrics, logs, and semantic resource attributes.
- Parent/child spans and client/server relationships for runtime dependencies.
- `service.name`, `service.namespace`, `service.instance.id`, deployment, cloud, Kubernetes, and Azure resource context.[7]

**Access**

- Instrument applications with supported OpenTelemetry SDKs or Azure Monitor OpenTelemetry Distro and export to Application Insights/Azure Monitor.[7]
- Query the resulting App Insights/LAW tables; HOG does not introduce another collector/export pipeline.

**Stable identifiers**

- Trace ID/span ID for evidence only.
- Governed service namespace/name plus environment/deployment identity for Application resolution.
- Azure/OTel cloud resource attributes when correctly configured.

**Freshness**

Near-real-time subject to batching, sampling, exporter retries, and Azure Monitor ingestion.

**Constraints**

- Semantic-convention quality depends on instrumentation governance.
- `service.instance.id` is ephemeral and not a canonical Application key.
- Do not count OpenTelemetry, App Insights, and LAW as three independent sources when they are one telemetry path.
- Store aggregate endpoint evidence, never raw spans.

**Graph mappings**

Observed Application `dependsOn` Application/Resource and Resource `hosts` Application evidence.

## 6. Microsoft Sentinel

**Contribution**

- Security incident identity, severity, status, classification, owner, entities, alerts, and investigation context.
- Incident-to-resource/application/business-service impact evidence.

**Access**

- Sentinel incident management REST APIs and portal.[8]
- Authorized LAW tables such as `SecurityIncident` and related alert/entity tables where configured.
- Data connectors and analytics rules remain Sentinel-managed.[9]

**Stable identifiers**

- Sentinel incident resource/name/incident number within workspace.
- Workspace ARM ID, alert/system IDs, mapped entity identifiers including ARM IDs when available.

**Freshness**

Incidents are derived after source ingestion, analytics-rule execution, grouping, and incident creation. Incident lifecycle changes are asynchronous.

**Constraints**

- Sentinel may use the same LAW data already queried by HOG; do not duplicate/count twice.
- Entity mapping quality varies by analytics rule and connector.
- Incident numbers/names are workspace-scoped.
- Security content can be sensitive; project allowlisted fields and deep links.
- Sentinel security incident and ServiceNow operational incident may refer to one event but remain separate source identities until explicitly correlated.

**Graph mappings**

Incident entities and provisional/accepted Incident `impacts` Resource/Application/BusinessService; Incident `mitigatedBy` Runbook/Patch after evidence.

## 7. Defender for Cloud

**Contribution**

- Security assessments, recommendations, regulatory-compliance context, alerts, and affected Azure/Azure Arc resources.
- Finding entities and resource impact/risk context.

**Access**

- Defender for Cloud REST APIs and supported ARG security-resource tables.[10]
- Continuous export to Event Hubs/LAW when already configured and justified.[11]
- Sentinel integration can provide security-operations context, but Defender remains finding authority.

**Stable identifiers**

- Assessment/recommendation key and assessment resource ID.
- Affected ARM resource ID and subscription.
- Alert identifiers for alert scenarios.

**Freshness**

Assessment refresh and export are asynchronous and service-dependent. Record status-change/event time and observation time.

**Constraints**

- Recommendations, assessments, alerts, and Sentinel incidents are different concepts.
- Continuous export is not required solely to build HOG; prefer ARG/API for compact current context.
- Avoid double ingestion through Defender export and Sentinel/LAW.
- Plan/licensing and cloud coverage vary.

**Graph mappings**

Finding entities; Finding `impacts` Resource/Application/BusinessService; Finding `mitigatedBy` Patch/Runbook when approved.

## 8. Azure Update Manager

**Contribution**

- Machine patch assessments, missing updates, classifications, installation runs/results, maintenance context, and reboot information.
- Patch entities and applicability/impact relationships.[12]

**Access**

- Azure Update Manager APIs/portal.
- ARG extension tables such as `patchassessmentresources` and `patchinstallationresources` for queryable assessment/install records.[12]
- LAW only where a documented/configured path supplies required history.

**Stable identifiers**

- Machine ARM/Azure Arc ID.
- Assessment/installation run resource IDs.
- Update/KB/package identifiers namespaced by operating system/product/source.

**Freshness**

Assessment data changes after scheduled/on-demand assessment; installation records change after deployment runs. It is not continuously current without assessment.

**Constraints**

- Update Manager remains patch orchestration and status authority.
- Assessment recency must accompany compliance claims.
- The same KB/package identifier can have OS/product context differences.
- Do not infer successful mitigation from applicability or deployment request alone.

**Graph mappings**

Patch entities; Patch `impacts` Resource/Application; Incident/Finding `mitigatedBy` Patch only with resolution/install evidence.

## 9. Microsoft Entra ID

**Contribution**

- Tenant-scoped users, groups, service principals, applications, owners, and group membership.
- Identity aliases for Team and Application ownership context.

**Access**

- Microsoft Graph REST/SDK with least-privilege delegated/application permissions.
- Delta query for supported incremental object collections.[13]
- Sign-in/audit APIs only for explicitly approved scenarios.

**Stable identifiers**

- Entra object `id` plus tenant ID.
- Application `appId` and service-principal object ID have distinct meanings.
- Group object ID for Team resolution.
- Opaque delta links/tokens for incremental synchronization.

**Freshness**

On-demand reads; supported collections can use delta synchronization. Audit/sign-in events arrive asynchronously and have license/retention constraints.

**Constraints**

- Azure RBAC role assignments are not Entra group membership or application ownership.
- Guests and multitenant apps must not be merged by display name/email.
- Personal data minimization applies; publish Team entities rather than member rosters by default.
- Delta support/property behavior varies and requires token recovery handling.

**Graph mappings**

Team and Application aliases; candidate/approved `ownedBy` edges. Entra technical “owner” does not automatically mean operational ownership.

## 10. ServiceNow

**Contribution**

- Approved CMDB/application/business-service identities and relationships when designated authoritative.
- Assignment/support groups, incidents, changes, knowledge articles, and runbook references.
- Business ownership and service mapping usually unavailable from Azure alone.

**Access**

- ServiceNow REST APIs with ACL-aware integration account.
- Microsoft ServiceNow connector for Logic Apps/Power Automate for supported actions/triggers.[14]
- Existing Azure Monitor ITSM integration may route alerts/tickets but is not a graph-query API.[15]

**Stable identifiers**

- `sys_id` as native stable object identity.
- Table/class plus instance URL and domain/tenant context.
- Incident/change numbers are human-friendly aliases, not the primary key.
- Correlation IDs for idempotent cross-system references.

**Freshness**

Use API incremental reads (`sys_updated_on` plus stable paging/tie-breaker) or supported events/triggers. Ticket/CMDB changes are subject to workflows and ACLs.

**Constraints**

- Instance schema, CMDB classes, relationship types, plugins, domains, and ACLs are organization-specific.
- Do not mirror the CMDB; project approved IDs/properties/relations and deep links.
- Generic connector actions are not a bulk graph federation service.
- Full descriptions/comments/attachments can contain secrets or personal data.
- Determine whether ServiceNow is authoritative for each service/ownership property before scoring it highly.

**Graph mappings**

Application, BusinessService, Team, Incident, Runbook; `ownedBy`, `supports`, `dependsOn`, `impacts`, `mitigatedBy` where the source relation explicitly means that predicate.

## 11. Azure DevOps

**Contribution**

- Projects/teams, repositories, commits, pull requests, builds, pipelines, deployments/environments, work items, tests, and operational runbook artifacts.
- Delivery traceability from incident/change to application and deployment.

**Access**

- Azure DevOps REST APIs.[16]
- Service Hooks for event-driven changes.[17]
- Analytics/OData for supported reporting scenarios; choose based on use case, not convenience.
- A separate Azure DevOps MCP Server may be evaluated independently; it is not a native Azure MCP Server namespace.

**Stable identifiers**

- Organization plus project ID.
- Team ID, repository ID, pipeline/build/release/run ID, work-item ID, commit SHA.
- URLs are aliases/references and can change.

**Freshness**

Service hooks are event-driven but need replay/reconciliation; REST/Analytics reads are on-demand and may be eventually consistent.

**Constraints**

- Organization/project boundaries and permissions matter.
- Service hooks can be retried/duplicated and require idempotency.
- Analytics is reporting-oriented and not authoritative for every live operation.
- Repository naming similarity is not enough to map an Application.
- Store links and approved metadata, not source code, logs, or full work-item history.

**Graph mappings**

Application/Team/Runbook aliases; support/ownership proposals; Incident `mitigatedBy` Runbook; delivery evidence for incident learning.

## 12. Cross-source identity and deduplication

### Rules

1. Namespace every native ID by tenant/organization/instance and entity type.
2. Prefer exact ARM ID, Entra object ID, ServiceNow `sys_id`, and Azure DevOps GUID/ID.
3. Preserve aliases instead of overwriting source identities.
4. Merge only through exact cross-reference, deterministic governed mapping, or steward approval.
5. Never merge solely by display name, hostname, role name, email, repository name, or incident title.
6. Treat shared telemetry paths as one evidence source, not independent corroboration.

### Source precedence examples

- Resource existence/configuration: ARG over tags/telemetry/CMDB snapshots.
- Runtime dependency: repeated App Insights/OTel observation; declared ServiceNow/ADO dependency may coexist rather than overwrite it.
- Business service and operational owner: approved ServiceNow/service portfolio and steward policy over inferred tags/Entra technical owners.
- Security finding: Defender; security incident lifecycle: Sentinel; ITSM incident workflow: ServiceNow.
- Patch state: Update Manager.

## 13. Freshness model

For each source record/assertion store:

- source event/effective timestamp when available;
- query/observation timestamp;
- source successful-run watermark;
- curated publication watermark;
- Ontology graph refresh watermark;
- stale-after policy by source/predicate.

Do not collapse these into one “last updated” timestamp. Failed queries freeze confidence/lifecycle pending recovery; they do not prove absence.

## 14. Minimum source onboarding checklist

- Authority and owner approved.
- API/table/tool and official documentation recorded.
- Stable identifiers and tenant scope proven.
- Required fields allowlisted and classified.
- Permissions/RBAC/ACL negative-tested.
- Paging, throttling, retries, duplicate events, and deletion semantics tested.
- Freshness and retention understood.
- Mapping and starting confidence approved.
- Reconciliation query exists.
- Source deep link works.
- Raw telemetry/CMDB/ticket replication explicitly excluded.

## References

[1] Microsoft, “Overview of Azure Resource Graph.” https://learn.microsoft.com/en-us/azure/governance/resource-graph/overview

[2] Microsoft, “Get Azure resource changes.” https://learn.microsoft.com/en-us/azure/governance/resource-graph/changes/get-resource-changes

[3] Microsoft, “Azure Monitor Logs API overview.” https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview

[4] Microsoft, “Log data ingestion time in Azure Monitor.” https://learn.microsoft.com/en-us/azure/azure-monitor/logs/data-ingestion-time

[5] Microsoft, “Azure Monitor service limits — Log Analytics workspaces.” https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/service-limits#log-analytics-workspaces

[6] Microsoft, “Application Map in Application Insights.” https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-map

[7] Microsoft, “Application Insights OpenTelemetry observability overview.” https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview

[8] Microsoft, “Microsoft Sentinel incidents — REST API.” https://learn.microsoft.com/en-us/rest/api/securityinsights/incidents/list

[9] Microsoft, “Microsoft Sentinel data connectors reference.” https://learn.microsoft.com/en-us/azure/sentinel/data-connectors-reference

[10] Microsoft, “Defender for Cloud Assessments — List.” https://learn.microsoft.com/en-us/rest/api/defenderforcloud/assessments/list

[11] Microsoft, “Continuously export Microsoft Defender for Cloud data.” https://learn.microsoft.com/en-us/azure/defender-for-cloud/continuous-export

[12] Microsoft, “Query Azure Update Manager logs.” https://learn.microsoft.com/en-us/azure/update-manager/query-logs

[13] Microsoft, “Microsoft Graph delta query overview.” https://learn.microsoft.com/en-us/graph/delta-query-overview

[14] Microsoft, “ServiceNow connector.” https://learn.microsoft.com/en-us/connectors/service-now/

[15] Microsoft, “IT Service Management Connector overview.” https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/itsmc-overview

[16] Microsoft, “Azure DevOps REST API reference.” https://learn.microsoft.com/en-us/rest/api/azure/devops/

[17] Microsoft, “Azure DevOps service hooks overview.” https://learn.microsoft.com/en-us/azure/devops/service-hooks/overview
