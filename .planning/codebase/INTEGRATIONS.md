# External Integrations

**Analysis Date:** 2026-08-23

## APIs & External Services

**Azure Resource Graph:**
- Azure Resource Graph - discovers and queries subscriptions/resources, changes, patch assessments, resource containers, and Advisor recommendations.
  - SDK/Client: Azure CLI `az graph query` via `AzureCliArgClient` (`src/hermes_arg_connector/azure.py`); direct REST fallback `AzureResourceGraphClient` uses `httpx`.
  - Auth: Azure identity token for `https://management.azure.com/.default` (`src/hermes_arg_connector/azure.py`).

**Azure MCP:**
- Azure MCP CLI - subscription discovery only.
  - SDK/Client: `azmcp subscription list` process adapter (`src/hermes_arg_connector/azure.py`).
  - Auth: the locally/deployment-authenticated Azure identity; command is configured by `azure.mcp_command` in `config.example.yaml`.

**Microsoft Fabric:**
- Fabric REST API - workspace/lakehouse/ontology metadata and synchronization operations.
  - SDK/Client: `FabricClient` over `httpx` (`src/fabric/fabric_client.py`).
  - Auth: `azure-identity` credential with Fabric scope `https://api.fabric.microsoft.com/.default` (`src/fabric/auth.py`).
- OneLake - durable connection registry, semantic snapshots, Delta/Parquet datasets, and document state.
  - SDK/Client: `azure-storage-file-datalake`, `adlfs`, `fsspec`, `deltalake`, and `pyarrow` (`src/storage/`, `src/hermes_arg_connector/onelake_fs.py`).
  - Auth: storage token scope `https://storage.azure.com/.default`; ABFSS roots use `onelake.dfs.fabric.microsoft.com` (`src/fabric/auth.py`, `src/storage/onelake_writer.py`).
- Fabric SQL endpoint - optional SQL reads for lakehouse-backed operations.
  - SDK/Client: SQL reader in `src/fabric/sql_endpoint.py`.
  - Auth: Azure token scope `https://database.windows.net/.default` (`src/fabric/sql_endpoint.py`).

**Azure AI:**
- Azure AI Foundry project/prompt agent - narrates already-retrieved, scope-filtered Copilot facts.
  - SDK/Client: small data-plane REST client using `urllib` (`src/operations/foundry_agent.py`); agent provisioning uses `infra/scripts/create-foundry-agent.sh`.
  - Auth: `DefaultAzureCredential` with `https://ai.azure.com/.default` (`src/operations/foundry_agent.py`); Terraform disables local key auth (`infra/terraform/foundry.tf`).
- Entra ID - API bearer-token validation and browser sign-in.
  - SDK/Client: `PyJWT[crypto]` JWKS validation (`src/api/auth.py`) and MSAL browser packages (`web/package.json`).
  - Auth: tenant-specific issuer/JWKS at `login.microsoftonline.com`; tenant and API audience are `HERMES_ENTRA_TENANT_ID` and `HERMES_ENTRA_AUDIENCE` (`src/api/runtime.py`).

**Security intelligence feeds:**
- Microsoft Security Update Guide affected-product OData feed - maps KBs to CVEs (`src/intelligence/vulnerability/connector.py`).
- NVD REST API - CVE descriptions, CVSS, severity, and curated exploit references (`src/intelligence/vulnerability/connector.py`).
  - SDK/Client: `httpx`.
  - Auth: optional `NVD_API_KEY` header; anonymous public access is supported.
- FIRST.org EPSS API - exploitation probability (`src/intelligence/vulnerability/connector.py`).
  - SDK/Client: `httpx`.
  - Auth: none detected.
- CISA Known Exploited Vulnerabilities catalog - confirmed exploitation status (`src/intelligence/vulnerability/connector.py`).
  - SDK/Client: `httpx`.
  - Auth: none detected.

## Data Storage

**Databases:**
- No separate relational or NoSQL database detected. The application uses Fabric OneLake Delta/Parquet datasets and JSON manifests as its durable system of record (`src/storage/`, `src/fabric/sync_service.py`).
- Local filesystem storage is used for development/default `HERMES_HOME` and generated datasets (`src/api/runtime.py`, `config.example.yaml`).

**File Storage:**
- Microsoft Fabric OneLake via ABFSS for production (`infra/terraform/container_apps.tf`, `src/hermes_arg_connector/onelake_fs.py`).
- Local disk for development and fallback mode; output is organized into generations/current/state (`README.md`).
- Azure Key Vault stores submitted onboarding client secrets and explicitly allowlisted bootstrap secrets (`src/onboarding/credentials.py`, `src/api/akv_bootstrap.py`).

**Caching:**
- In-process TTL/memoization for snapshots and vulnerability feed enrichment (`src/api/runtime.py`); no Redis or external cache detected.

## Authentication & Identity

**Auth Provider:**
- Microsoft Entra ID - direct JWT validation is available through `EntraJwtAuthenticator` (`src/api/auth.py`), using tenant JWKS and app audience.
- Trusted gateway assertion mode - `HeaderPrincipalAuthenticator` consumes validated `x-ms-client-principal-*` headers and resolves explicit grants (`src/api/auth.py`).
- Static bearer tokens - local/test mode via `HERMES_API_TOKENS` (`src/api/runtime.py`).
- Azure managed identity/service principal - Azure SDK, Fabric, OneLake, Key Vault, Resource Graph, and Foundry access (`src/fabric/auth.py`, `src/operations/foundry_agent.py`).

## Monitoring & Observability

**Error Tracking:**
- No third-party error tracker detected. API failures are logged through Python logging and translated to stable error envelopes (`src/api/app.py`).

**Logs:**
- OpenTelemetry metrics API records request counts, latency, and authorization denials without payloads (`src/api/telemetry.py`).
- Azure Log Analytics backs Container Apps diagnostics; Application Insights is provisioned for application telemetry (`infra/terraform/main.tf`).
- Azure Monitor metric and scheduled-query alerts notify configured email action groups (`infra/terraform/alerting.tf`).

## CI/CD & Deployment

**Hosting:**
- Azure Container Apps hosts the FastAPI API and Next.js UI; Azure Container Registry stores images (`infra/terraform/container_apps.tf`, `infra/terraform/main.tf`).
- Terraform provisions the platform; shell deployment/build scripts are under `infra/scripts/`.

**CI Pipeline:**
- No hosted CI provider or workflow detected in the inspected repository. Deployment is script/Terraform-driven through `infra/scripts/deploy.sh` and `infra/scripts/build-and-push.sh`.

## Environment Configuration

**Required env vars:**
- API/auth: `HERMES_API_AUTH`, `HERMES_API_TOKENS` or `HERMES_API_GATEWAY_GRANTS`, `HERMES_ENTRA_TENANT_ID`, `HERMES_ENTRA_AUDIENCE` (`src/api/runtime.py`).
- Fabric/state: `HERMES_HOME`, `HERMES_FABRIC_CONFIG`, `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID`, `AZURE_CLIENT_ID` (`src/api/runtime.py`, `infra/terraform/container_apps.tf`).
- Foundry: `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME` (`src/operations/foundry_agent.py`).
- Optional vulnerability enrichment: `NVD_API_KEY` (`src/intelligence/vulnerability/connector.py`).
- Optional Key Vault bootstrap: `HERMES_CONNECTION_KEY_VAULT`, `HERMES_AKV_BOOTSTRAP_ENABLED`, `HERMES_AKV_BOOTSTRAP_SECRETS` (`src/api/akv_bootstrap.py`).

**Secrets location:**
- Azure Key Vault in deployed environments (`src/onboarding/credentials.py`, `infra/terraform/main.tf`); Container Apps secret-backed environment values are used for bootstrap (`src/api/akv_bootstrap.py`).
- Local development uses ignored `web/.env.local`; its existence is noted but secret contents are not part of this map.

## Webhooks & Callbacks

**Incoming:**
- No webhook endpoints detected. The API exposes request/response routes through FastAPI routers under `src/api/routers/`; asynchronous provider refresh is timer-thread based (`src/api/app.py`).

**Outgoing:**
- No webhook delivery detected. Outbound calls are synchronous HTTP/API requests to Azure Resource Graph, Fabric, Foundry, Key Vault, and public security feeds (`src/hermes_arg_connector/azure.py`, `src/fabric/fabric_client.py`, `src/operations/foundry_agent.py`, `src/intelligence/vulnerability/connector.py`).
- Foundry uses asynchronous operation polling through `Location`/`Retry-After` headers rather than a callback endpoint (`src/operations/foundry_agent.py`).

---

*Integration audit: 2026-08-23*
