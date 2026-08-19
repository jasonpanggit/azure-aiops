# Dependency Discovery Design

## 1. Objective

Infer and maintain these operational relationships with evidence and confidence:

- Application → SQL/Database
- Application → StorageAccount
- Application → KeyVault
- Application → ServiceBus
- Application → AKSCluster

Raw telemetry remains in Azure Monitor, Log Analytics, Application Insights, and OpenTelemetry. Hermes stores only normalized endpoint-pair evidence windows and accepted/proposed relationships.

## 2. Source capability assessment

| Source | Existing dependency capability | Use |
|---|---|---|
| Application Insights | `AppDependencies`, `AppRequests`, operation/trace correlation, Application Map | Primary observed application-call dependency source.[1] |
| OpenTelemetry | client/server spans, resource and semantic-convention attributes | Primary vendor-neutral identity and dependency semantics; queried from Azure Monitor destination.[2] |
| Log Analytics | KQL across App Insights and diagnostic tables | Query/aggregation plane; not an independent corroborating source when it stores the same telemetry. |
| Azure Resource Graph | Declared resource properties, private endpoints, identities, parent/child and service configuration | Deterministic structural/configuration evidence. |
| Defender for Cloud | Security assessments, attack-path/security context, affected resource IDs | Risk/attack-path enrichment; not a general runtime application-dependency authority. |
| Azure Monitor metrics | Service/resource health and activity | Corroborating activity/freshness, not endpoint identity. |

## 3. Reuse from Hermes

- Azure MCP Monitor KQL tools for bounded interactive investigations and source validation.
- Native MCP client dynamic discovery and tool allowlisting.
- Cron scheduler scripts for deterministic aggregate queries and watermarks.
- Webhooks for incident/event-triggered targeted refresh.
- Delegation for parallel investigation of ambiguous endpoint mappings.
- Tool registry plugin model for a service-gated HOG adapter; no new core tools.
- Built-in memory for operator preferences only, not dependency facts.
- Session store for investigation audit; OneLake/Fabric for operational context facts.

## 4. Evidence normalization pipeline

1. Query an approved time window from App Insights/LAW.
2. Select source application identity, target/dependency type, target host/address, success, duration, result, operation count, cloud/OTel resource attributes, and time bounds.
3. Aggregate by normalized source and target. Do not persist raw spans/requests.
4. Resolve source to canonical Application.
5. Resolve target to canonical Azure entity through exact ARM ID, resource attributes, known Azure DNS suffix, private endpoint mapping, or steward-approved alias.
6. Emit a per-source relationship assertion with evidence reference, observation count, time window, and confidence.
7. Ontology Steward validates, reconciles, decays, accepts, or queues review.

## 5. Application identity

Preferred order:

1. Governed `applicationKey` supplied through configuration/service catalog.
2. Explicit ARM/App Insights resource mapping.
3. OpenTelemetry `service.namespace` + `service.name` + environment.
4. App Insights `cloud_RoleName` plus environment/workspace.
5. Similarity only as a low-confidence proposal.

`service.instance.id` and `cloud_RoleInstance` identify instances, not Applications.

## 6. Target-specific discovery

### Application → SQL/Database

Evidence:

- `AppDependencies` dependency type/target/data/name for SQL calls.
- OpenTelemetry database client spans (`db.system`, server address/port, database namespace/name under the applicable semantic-convention version).
- Azure SQL/PostgreSQL/MySQL resource FQDN and private endpoint configuration from ARG.

Normalization:

- Parse server FQDN and port; never store credentials or connection strings.
- Resolve server/resource first, then database name where instrumented and approved.
- Emit `calls` for observed database operations and derive/accept `dependsOn` when evidence is persistent and operationally required.

Caveats:

- Connection pooling and sampling affect counts.
- Generic TCP/HTTP spans may not reveal database name.
- Customer-managed DNS/private endpoints require mapping through Azure networking metadata.

### Application → StorageAccount

Evidence:

- Azure SDK HTTP dependencies in App Insights.
- OTel HTTP/Azure SDK spans with server address and storage operation attributes.
- Target FQDN suffixes for Blob, Queue, Table, File, or DFS endpoints.
- Storage account endpoints/private endpoints from ARG.

Normalization:

- Map endpoint hostname to StorageAccount ARM ID.
- Keep service kind (blob/queue/table/file/dfs) as relationship evidence/property.
- Do not infer account from a container/blob path if tenant/account identity is ambiguous.

### Application → KeyVault

Evidence:

- App Insights HTTP/Azure SDK dependency targeting `*.vault.azure.net` or sovereign-cloud equivalent.
- OTel client spans/server address.
- Key Vault URI and private endpoint/DNS mapping from ARG.
- Managed-identity/RBAC assignment can corroborate access potential but does not prove runtime use.

Normalization:

- Store Key Vault resource identity only; never secret/key/certificate name or value unless a separately approved use case requires a non-sensitive identifier.
- Observed calls create `calls`; repeated successful use may create accepted `dependsOn`.

### Application → ServiceBus

Evidence:

- App Insights dependency telemetry from Azure Service Bus SDK.
- OTel messaging spans and semantic attributes such as messaging system, destination, operation, and server address.
- Namespace, queue/topic/subscription metadata from ARG/service API.

Normalization:

- Resolve namespace FQDN to Service Bus namespace ARM ID.
- Optionally represent queue/topic as a Resource when operationally important; otherwise keep destination as evidence metadata.
- Producer and consumer directions differ: producer `calls`/`connectsTo` namespace; asynchronous business dependency requires explicit policy.

### Application → AKSCluster

Two meanings must be separated:

1. **Hosted by AKS:** OTel Kubernetes resource attributes, cluster/resource ID, namespace, workload identity, and deployment metadata support `AKSCluster hosts Application`.
2. **Calls an application hosted in AKS:** trace propagation and service identity support `Application calls Application`; cluster is contextual hosting, not necessarily the direct dependency target.

Evidence:

- OTel `k8s.*` and `cloud.resource_id` attributes.
- App Insights role/operation correlation.
- AKS resource and node resource group from ARG/Azure MCP AKS get.
- Kubernetes control-plane/in-cluster metadata only through an approved source; Azure MCP AKS tools do not inspect pods/services.

Do not infer “Application depends on AKSCluster” merely because one trace passed through an ingress endpoint. Prefer the more precise Application-to-Application edge plus hosting context.

## 7. Declared versus observed graph

Maintain separate assertions:

- **Declared:** ServiceNow/architecture metadata, Azure resource properties, Azure DevOps deployment definitions.
- **Observed:** App Insights/OTel aggregate runtime calls.
- **Permitted:** RBAC/network rules/private endpoint configuration.
- **Inferred:** multi-signal or model proposal.

A permitted path is not an observed call. An observed call is not automatically a business-critical dependency. The effective graph can combine them without erasing their semantics.

## 8. Confidence model

Confidence is a calibrated policy score, not a probability claim.

### Base score by evidence

| Evidence | Base |
|---|---:|
| Exact declared native resource reference | 0.98 |
| Approved service-catalog dependency | 0.95 |
| OTel/App Insights target with exact ARM/resource resolution, repeated windows | 0.82 |
| Exact Azure FQDN plus governed source Application | 0.75 |
| Network connection with exact endpoints but weak service semantics | 0.60 |
| Temporal/co-occurrence correlation | 0.45 |
| LLM/name similarity only | 0.30 |

### Adjustments

- `+0.05` independent authoritative corroboration, capped at 0.98 unless steward-approved.
- `+0.03` repeated in at least three independent time windows.
- `-0.10` sampled/partial telemetry without item-count-aware aggregation.
- `-0.15` ambiguous endpoint maps to multiple resources.
- `-0.20` contradiction with an authoritative declaration.
- recency decay after predicate-specific stale threshold.

Do not count OpenTelemetry, App Insights, and LAW as three sources when OTel exported into App Insights/LAW. They form one provenance chain.

### Suggested states

- `>=0.80`: auto-accept technical observed edge if endpoint validation passes.
- `0.60–0.79`: accept into technical view after repeated windows; review for business blast-radius use.
- `0.40–0.59`: proposed/review.
- `<0.40`: evidence only, excluded from default traversal.

Business-service and ownership relationships require stronger source/steward policy than runtime technical edges.

## 9. Staleness and decay

- Runtime `calls`: short half-life, e.g. 7–14 days after last observation, calibrated per application traffic.
- `dependsOn`: longer half-life, e.g. 30–90 days, and may remain accepted if declared evidence is current.
- `hosts`: derive from current deployment/configuration and expire on confirmed deployment change.
- Source outage freezes decay.
- Zero traffic is not evidence of removal for dormant/batch applications.

## 10. Query design

Production queries are versioned deterministic KQL/ARG assets. Azure MCP is useful for discovery and interactive validation but should not be the only scheduled execution contract.

Queries must:

- bound time and scope;
- select allowlisted columns;
- aggregate in source;
- account for sampling where possible;
- cap cardinality and reject high-cardinality payloads;
- record query version, workspace/resource ID, window, and completion watermark;
- never extract raw request/trace bodies, connection strings, or secret names/values.

## 11. Defender role

Defender may add:

- Finding `impacts` Resource/Application;
- security attack-path/context relationships;
- public exposure, vulnerability, and recommendation evidence.

It does not replace App Insights/OTel for general runtime dependencies. Treat attack paths as security-analysis assertions with their own source and confidence.

## 12. Validation

Build a labeled pilot set covering SQL, Storage, Key Vault, Service Bus, and AKS. Measure:

- source Application resolution accuracy;
- target resource resolution accuracy;
- edge direction accuracy;
- precision/recall by target type;
- stale-edge rate;
- ambiguous endpoint rate;
- false corroboration from duplicated telemetry paths.

No auto-accept threshold is production-ready until the pilot meets approved precision targets.

## References

[1] Microsoft, “Application Map in Application Insights.” https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-map

[2] Microsoft, “Application Insights OpenTelemetry observability overview.” https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview

[3] OpenTelemetry, “Semantic conventions.” https://opentelemetry.io/docs/specs/semconv/
