# Technology Stack

**Project:** Azure AI Operations Platform  
**Researched:** 2026-08-23  
**Scope:** Stack decisions for the integrated pilot workflow in an existing brownfield repository. Existing foundations are retained unless the pilot exposes a verified compatibility or lifecycle issue.

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | `>=3.11`; deploy Python 3.12 | API, source adapters, evidence orchestration, approval state, and bounded remediation workers | Already the project runtime; keep the deployed 3.12-slim image and avoid a platform rewrite. |
| FastAPI | `>=0.115,<1` (existing lock/range) | Authenticated API and workflow endpoints | Existing routers, envelopes, dependency injection, and tests already provide the correct extension point. |
| Uvicorn | `>=0.32,<1` | ASGI serving | Existing production entry point; no reason to introduce another server. |
| Next.js | `14.2.35` (existing) | Operations workbench | Retain the existing standalone build for the pilot. Do not make a major Next upgrade part of workflow delivery; assess it separately because it changes App Router/runtime behavior. |
| React / Fluent UI | React 18 / Fluent UI React Components 9 (`^9.74.6`) | Consistent operator UI, approval dialogs, evidence panels | Matches the current workbench and supports accessible confirmation flows without a parallel design system. |

### Data and Evidence

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Azure Resource Graph REST/CLI adapter | REST API; existing `az graph query` adapter | Subscription/resource/change discovery and read-only evidence | Keep the current CLI adapter for the pilot, behind its existing source boundary. Add REST/SDK only when CLI limitations require it. All query packs must be scoped, paged, throttled, versioned, and auditable. |
| Azure Monitor Logs Query API + KQL | Service API | Compact incident, dependency, and operational evidence | Query source systems in bounded time windows; retain resource IDs, correlation IDs, timestamps, deep links, and freshness—not raw telemetry. |
| Application Insights / OpenTelemetry | Existing `opentelemetry-api>=1.29,<2`; source-native App Insights | Correlation and low-cardinality platform telemetry | Continue the existing telemetry boundary and never put source payloads or secrets in metrics/logs. |
| Microsoft Fabric OneLake + Lakehouse Delta/Parquet | Existing `deltalake>=1.0,<2`, `pyarrow>=23.0.1,<24`, `adlfs>=2024.7,<2025`, `fsspec>=2024.6,<2025` | Durable immutable generations, evidence projections, decisions, and audit records | This is already the persistence boundary. Versioned, atomic projections make approval history and rollback reproducible. |
| Fabric REST APIs | Existing `httpx>=0.27,<1` client | Workspace/lakehouse metadata, sync, and publication control | Preserve the current small adapter instead of adding a broad SDK whose coverage may lag Fabric APIs. |
| Fabric IQ Ontology | Current service is **Preview** | Optional graph/semantic projection | Use only after a target-tenant capability spike. OneLake/Delta remains canonical because preview lifecycle, API, refresh, relationship attributes, and rollback behavior must not become hidden availability dependencies. |

### Azure Operations and AI

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Azure Identity | `azure-identity>=1.19,<2` (existing) | Managed identity and local developer authentication | Standardize all Azure/Fabric/Key Vault credentials on `DefaultAzureCredential`; separate identities by discovery, publication, and execution plane. |
| Azure Key Vault | `azure-keyvault-secrets>=4.9,<5` (existing) | Bootstrap and secret isolation | Keep secrets out of config, browser variables, agent context, and container images. |
| Azure Resource Manager management-plane adapters | Add only the narrowly required `azure-mgmt-*` packages, pinned in the pilot lockfile | Execute explicitly approved remediation | Prefer resource-scoped, operation-specific adapters over a generic “run Azure command” tool. A capability spike must identify exact API/package versions for each runbook. |
| Azure Container Apps Jobs | Platform capability; use the existing Container Apps deployment model | Scheduled ingestion and asynchronous execution of approved commands | Scheduled/manual jobs are production-supported and fit one bounded execution per run. Keep approval and status APIs in FastAPI; dispatch execution to a job with an idempotency key. |
| Microsoft Foundry Agent Service | Current managed service; retain existing REST client until SDK contract is validated | Optional read-only narration over retrieved evidence | Foundry supports managed prompt/hosted agents and MCP/custom tools, but the pilot must expose only scoped read tools and evidence references. Do not enable mutation through the agent. |
| Microsoft Sentinel, Defender for Cloud, Azure Update Manager | Source-native service APIs | Incidents, findings/recommendations, and patch assessment/install evidence | Project compact records and links keyed by authoritative resource/incident/patch IDs. Verify tenant permissions, retention, paging, and API shape before committing connectors. |

### Identity, Safety, and Delivery

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Microsoft Entra ID + MSAL Browser | `@azure/msal-browser ^5.18.0`, `@azure/msal-react ^5.5.5` (existing) | Operator sign-in and API audience validation | Preserve the existing tenant/audience/JWKS model and explicit RBAC/scope checks. |
| Azure RBAC + managed identities | Azure platform | Least-privilege source reads and remediation writes | Grant the smallest resource/action scope to separate identities; approval is enforced by the API and worker, not by the UI. |
| Terraform | `>=1.9,<2`; existing AzureRM `~>5.1`, Fabric `~>1.13`, AzAPI `~>2.6` | Reproducible ACA, identity, Key Vault, monitoring, and Fabric infrastructure | Extend existing modules. Use AzAPI only where AzureRM/Fabric providers do not yet expose a required capability. |
| Azure Monitor / Log Analytics / Application Insights | Existing provisioned platform | Run telemetry, audit correlation, alerts, and freshness monitoring | Aligns with Container Apps diagnostics and prevents a new observability stack during the pilot. |
| uv + `uv.lock`; npm lockfile | Existing | Reproducible Python and web builds | Keep lockfiles authoritative; no scheduled production download of Azure MCP/npm packages. |

## Version and Upgrade Policy

1. **Do not re-platform established foundations.** FastAPI, Next.js 14, Fluent UI, OneLake/Delta, Terraform, and the current identity/storage libraries are already integrated and validated.
2. **Pin every new remediation/source dependency.** Select versions during the phase capability spike, record the API version and package version in the lockfile, and test against the target Azure tenant. Do not use floating `latest`.
3. **Treat Fabric IQ Ontology as an optional preview projection.** A failed ontology refresh must not make canonical evidence, approval state, or audit history unavailable.
4. **Keep the Foundry client thin.** The existing REST boundary is preferable until the current official SDK/data-plane contract, authentication flow, tool support, and version are verified. Upgrade only as a scoped decision.
5. **Separate control plane from data plane.** FastAPI records recommendation, approval, execution intent, and result; a Container Apps Job performs the bounded action; Azure Activity Log and application audit provide independent evidence.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Resource discovery | Existing `az graph query` adapter, with REST fallback | Generic Azure MCP arbitrary-query tool | Current repository documents that installed Azure MCP does not provide general ARG querying; do not assume tool coverage. |
| Durable store | OneLake Delta/Parquet | PostgreSQL, Cosmos DB, or Redis as a new system of record | Duplicates the governed Fabric projection and creates consistency/retention work. Use an external cache only if measured workload requires it. |
| Semantic graph | Fabric IQ Ontology as optional projection | Make Ontology the canonical operational database | Official documentation labels Ontology/Fabric IQ Preview; lifecycle and rollback risk is unacceptable for pilot authority. |
| Async execution | Azure Container Apps Jobs | In-process FastAPI background tasks | Jobs survive request completion and isolate credentials/action permissions; in-process tasks are fragile for retries, restarts, and audit. |
| Agent integration | Foundry Agent Service over scoped read tools | Give an LLM direct Azure write permissions | Violates the explicit human-approval and bounded-remediation constraint. |
| Azure SDK surface | Narrow, operation-specific `azure-mgmt-*` adapters or REST | One generic ARM executor | Generic execution is difficult to authorize, validate, make idempotent, and review safely. |
| Secrets | Managed identity + Key Vault | Service-principal secrets in YAML/container settings | Increases credential exposure and conflicts with existing Key Vault/bootstrap design. |
| Observability | Azure Monitor/Application Insights + OpenTelemetry | New third-party telemetry platform | Existing infrastructure is provisioned and already supports correlation, alerts, and low-cardinality metrics. |

## Installation

Existing foundations remain the baseline:

```bash
# Python
uv sync --extra test

# Web
cd web
npm ci
```

Add dependencies only when a specific pilot runbook needs them, for example:

```bash
# Example shape; choose and record the exact package/version during the capability spike.
uv add "azure-mgmt-<service>==<verified-version>"
uv lock
```

Do not add a package merely to wrap a service already isolated behind `httpx` or the Azure CLI.

## Sources

Official documentation checked on 2026-08-23:

- [Azure Resource Graph REST API](https://learn.microsoft.com/rest/api/azure-resourcegraph/)
- [Azure Monitor Logs Query API overview](https://learn.microsoft.com/azure/azure-monitor/logs/api/overview)
- [Azure Monitor API access and authentication](https://learn.microsoft.com/azure/azure-monitor/logs/api/access-api)
- [Application Insights OpenTelemetry overview](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-overview)
- [OneLake overview](https://learn.microsoft.com/fabric/onelake/onelake-overview)
- [Fabric lakehouse overview](https://learn.microsoft.com/fabric/data-engineering/lakehouse-overview)
- [Fabric Ontology (Preview)](https://learn.microsoft.com/fabric/iq/ontology/overview)
- [Microsoft Foundry Agent Service overview](https://learn.microsoft.com/azure/ai-foundry/agents/overview)
- [Azure Container Apps Jobs](https://learn.microsoft.com/azure/container-apps/jobs)
- [Managed identities for Azure resources](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview)
- [Azure Resource Manager overview](https://learn.microsoft.com/azure/azure-resource-manager/management/overview)
- [Azure Update Manager overview](https://learn.microsoft.com/azure/update-manager/overview)
- [Microsoft Defender for Cloud overview](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-cloud-introduction)
- [Microsoft Sentinel overview](https://learn.microsoft.com/azure/sentinel/overview)

**Confidence:** MEDIUM for retained stack and Azure storage/identity/runtime recommendations (existing code plus official documentation); LOW for exact current Sentinel/Defender/Update Manager/Foundry API versions and Fabric Ontology production readiness, which require target-tenant capability spikes.
