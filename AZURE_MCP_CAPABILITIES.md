# Hermes Operations Graph — Azure MCP Server Capabilities

## 1. Executive position

Azure MCP Server is a preferred **agent tool surface** for supported Azure operations. It is not the ingestion backbone, not a universal Azure API, and not a substitute for Azure Resource Graph (ARG), Microsoft Graph, Defender/Sentinel APIs, Update Manager APIs, or enterprise connectors.

As verified for this architecture on 2026-08-17, Azure MCP Server 2.0 is generally available and provides useful native read operations for Azure Monitor/Log Analytics, resource groups/resources, Azure resource insights, Application Insights code-optimization recommendations, Resource Health, Azure RBAC, Azure Policy, and many other Azure services.[1][2] The current documented tool list does **not** expose:

- a general-purpose arbitrary ARG query tool;
- Microsoft Entra directory object/query tools;
- native Microsoft Sentinel incident tools;
- native Defender for Cloud finding/recommendation tools;
- native Azure Update Manager assessment/history tools;
- native ServiceNow or Azure DevOps operational-data tools.

Generic Log Analytics querying can reach Sentinel/Defender/Update data only when that data already exists in an authorized workspace/table. That is a KQL access path, not a service-specific MCP capability.

## 2. Architectural use

Use Azure MCP for:

- live, bounded agent queries against documented tools;
- Azure Monitor/Log Analytics context;
- resource listing/insights and resource-health context;
- RBAC/policy context where needed;
- Foundry agent access to approved Azure operations.

Use native supported services for platform discovery:

- ARG SDK/REST/CLI for arbitrary resource graph queries;
- Azure Monitor Query SDK/Logs API for production KQL query jobs;
- Microsoft Graph for Entra;
- Sentinel/Defender/Update Manager APIs, ARG tables, or Log Analytics as documented;
- ServiceNow and Azure DevOps supported APIs/connectors.

This separation prevents an MCP version or agent prompt from becoming the data-plane contract.

## 3. Capability matrix

| Required area | Native Azure MCP capability useful to HOG | Status | Gaps / required alternative |
|---|---|---|---|
| Azure resources / ARG | Resource-group tools list resource groups and resources. Azure Insights derives subscription/tenant infrastructure insights using ARG-backed patterns. Some other tools use ARG internally.[2][3] | Partial | No documented arbitrary ARG/KQL query tool. Resource Discovery Engine uses ARG REST/SDK/CLI directly. Do not treat natural-language Insights output as canonical inventory. |
| Azure Monitor activity | Get Azure activity-log records.[4] | Native | Use source-native APIs/queries for deterministic scheduled discovery and full retention semantics. |
| Log Analytics | List workspaces/tables/table types; query workspace logs; query logs for a resource.[4] | Native and important | Queries require explicit scope/table and are constrained for safety/size. This does not configure collection, retention, or diagnostic settings. |
| Azure Monitor metrics | Query supported metrics and related Monitor context according to the current Monitor tool reference.[4] | Native | Capability must be runtime-enumerated and tested per resource/provider; HOG should use summaries, not copy metric series. |
| Azure Monitor health models | List/get documented Azure Monitor Health Models.[2][4] | Native where service is available | Health models are additional context, not the HOG ontology or source of resource identity. |
| Azure Workbooks | List/show/create/update/soft-delete workbooks.[4] | Native, includes writes | Discovery/agent profile should allow only approved read operations. Workbooks may host quality views but are not graph storage. |
| Application Insights | List code-optimization recommendations across Application Insights components.[5] | Narrow native support | No general App Insights traces/dependencies/application-map-specific tool documented. Query App Insights/LAW through Azure Monitor KQL or supported SDK/API. |
| OpenTelemetry | Monitor instrumentation tools provide onboarding learning/orchestration for local applications.[1][2] | Operational onboarding support | Not a telemetry query or topology API. Runtime dependency evidence comes from the configured Application Insights/LAW destination. |
| Resource Health / Service Health | Get resource availability status and list service-health events.[2] | Native | Use as live operational context; do not persist full event payloads. |
| Azure RBAC | List Azure RBAC role assignments.[6] | Native read capability | Azure RBAC is not Entra directory ownership/membership. Microsoft Graph is still required for directory entities. |
| Azure Policy | List policy assignments.[7] | Native read capability | Policy compliance/findings may require ARG or Policy APIs; assignments alone do not supply all Finding entities. |
| Microsoft Sentinel | No service-specific tool in current documented list.[1][2] | Gap | Use Sentinel management APIs and/or authorized LAW `SecurityIncident`/related tables. Generic KQL does not imply full incident CRUD/lifecycle support. |
| Defender for Cloud | No service-specific tool in current documented list.[1][2] | Gap | Use Defender for Cloud APIs, ARG security-resource tables, or configured continuous export/LAW path. |
| Azure Update Manager | No service-specific tool in current documented list.[1][2] | Gap | Use Update Manager APIs and ARG `patchassessmentresources` / `patchinstallationresources` extension tables, with LAW only where configured. |
| Microsoft Entra ID | No native users/groups/service-principals/owners/delta tools.[1][2] | Gap | Use Microsoft Graph with least-privilege app permissions and tenant-scoped IDs. Azure MCP RBAC tools do not replace this. |
| ServiceNow | No native ServiceNow source tool.[1][2] | Gap | Use supported ServiceNow REST/Logic Apps/Power Platform connectors or approved integration. |
| Azure DevOps | No native Azure DevOps operational-data tool in Azure MCP Server.[1][2] | Separate MCP/API | Use Azure DevOps REST/service hooks/Analytics, or evaluate the separate Azure DevOps MCP Server under its own preview/security decision. |
| Microsoft Foundry | Azure MCP includes documented Foundry model/agent/index operations and can be deployed/connected for Foundry scenarios.[1][2] | Native, broader than HOG need | Keep HOG agent configuration and data permissions separate. Do not expose create/deploy operations to the read-only operations agent. |
| Azure SRE Agent | Tools exist for SRE Agent resources, connectors, investigations, incidents, workflows, schedules, and memories.[1][2] | Native, optional future integration | Potential overlap with HOG/Foundry; assess separately. Do not make it an unreviewed second incident-learning store. |

## 4. Azure Monitor tool safety constraints

The current Azure Monitor tool reference documents safety and shape constraints including explicit workspace/resource/table inputs, query/result limits, and rejected management/destructive KQL patterns.[4] Architecture consequences:

- maintain reviewed query templates for repeatable graph discovery;
- scope time range and projected columns;
- query aggregate relationship evidence, not raw events;
- validate row truncation/limits and page where supported;
- do not use agent-generated KQL as the only production discovery mechanism;
- record query version and source watermark in evidence metadata.

Azure MCP queries data already collected by Azure Monitor. It does not justify a new telemetry pipeline and does not guarantee that a required table exists.

## 5. Authentication, authorization, and hosting

Azure MCP brokers operations using Azure credentials/tokens and the permissions available to the caller/workload identity.[8] Recommended HOG profile:

- managed identity or approved workload identity for hosted use;
- a dedicated read-only discovery/agent identity;
- minimum subscription/workspace/resource scopes;
- server read-only mode;
- enabled-service/namespace filters;
- pinned/tested version rather than unreviewed `latest` in production;
- remote hosting protected by Entra authentication and an approved gateway/network design;
- audit of tool invocation, target scope, result status, and correlation ID;
- no secrets or full source payloads in MCP/agent logs.

Read-only server mode is an important guardrail, not a substitute for least-privilege RBAC. A client or tool description can still be malicious or overbroad; apply Microsoft’s MCP security guidance for authentication, token handling, network isolation, tool poisoning, and prompt injection.[8]

## 6. Proposed MCP profiles

### Discovery profile

Purpose: architecture validation and operator-assisted investigation.

Enable only validated read namespaces such as:

- Monitor/Log Analytics;
- Resource Group/resource listing;
- Resource Health/Service Health;
- Azure Insights, with clear non-authoritative labeling;
- RBAC and Policy if required.

Do not enable write-capable Workbook, resource, Foundry, or SRE Agent operations by default.

### Foundry operations agent profile

Purpose: read-only operational reasoning.

- Same narrow namespaces.
- Fabric IQ handles ontology traversal.
- Separate governed tools handle arbitrary ARG and required-source gaps.
- Response contract requires source, confidence, and observation time.
- Tool invocation budget and scope are enforced.

### Administrative profile

If ever needed, this is a separate identity and configuration, not a mode switch available to the production reasoning agent. It requires explicit approval and auditing.

## 7. Capability registry

Because Azure MCP evolves quickly, maintain a versioned capability registry containing:

- server/package version and release date;
- runtime-enumerated tool/namespace name;
- read/write/destructive classification;
- required Azure roles/scopes;
- input/output contract and limits;
- source system actually queried;
- allowed agent/profile;
- last test date and evidence;
- fallback native API/connector.

Re-run compatibility tests before upgrades. The official command reference and runtime tool enumeration outrank marketing examples or assumptions.[2]

## 8. Key decisions

1. Azure MCP is preferred for supported live agent tools, not for batch ingestion.
2. ARG remains the Resource Discovery Engine’s authoritative query surface.
3. Azure Monitor MCP tools may query KQL but raw logs remain in LAW/App Insights.
4. Unsupported sources use their supported APIs/connectors; no fake “generic MCP” abstraction is claimed.
5. Agent access is read-only by default and is separate from publication identities.
6. Every MCP-derived assertion records the underlying Azure source/table/query reference, not merely `azure-mcp`.

## 9. Acceptance tests for implementation

- Runtime tool enumeration matches the approved registry.
- Disabled/write tools cannot be called from the read-only agent profile.
- Arbitrary ARG scenarios route to the explicit ARG tool, not Azure Insights.
- LAW queries enforce workspace, table, time, and result budgets.
- Sentinel/Defender/Update/Entra requests do not silently route to nonexistent native tools.
- RBAC negative tests fail for out-of-scope subscriptions/workspaces.
- Output provenance identifies underlying service and timestamp.
- Upgrade tests detect renamed/removed tools or changed output schemas.

## References

[1] Microsoft, “Azure MCP Server.” https://github.com/microsoft/mcp/tree/main/servers/Azure.Mcp.Server

[2] Microsoft, “Azure MCP CLI command reference.” https://github.com/microsoft/mcp/blob/main/servers/Azure.Mcp.Server/docs/azmcp-commands.md

[3] Microsoft, “Azure MCP Server tools for Azure Insights.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/azure-insights

[4] Microsoft, “Azure MCP Server tools for Azure Monitor and Workbooks.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/azure-monitor

[5] Microsoft, “Azure MCP Server tools for Application Insights.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/application-insights

[6] Microsoft, “Azure MCP Server tools for Azure RBAC.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/azure-rbac

[7] Microsoft, “Azure MCP Server tools for Azure Policy.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/azure-policy

[8] Microsoft, “Secure your Azure MCP Server deployment.” https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/security
