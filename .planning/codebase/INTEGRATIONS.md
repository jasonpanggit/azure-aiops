# External Integrations

**Analysis Date:** 2026-08-24

## APIs & External Services

**Azure control plane and discovery:**
- Azure MCP CLI (`azmcp`) for subscription discovery.
  - SDK/Client: `AzureMcpClient` command adapter (`src/hermes_arg_connector/azure.py`).
  - Auth: authenticated Azure identity on host/container; command configured via `azure.mcp_command` (`config.example.yaml`, `src/hermes_arg_connector/config.py`).
- Azure Resource Graph for inventory/change/assessment reads.
  - SDK/Client: Azure CLI `az graph query` (`AzureCliArgClient`) and direct REST (`AzureResourceGraphClient`) (`src/hermes_arg_connector/azure.py`).
  - Auth: token scope `https://management.azure.com/.default` (`src/hermes_arg_connector/azure.py`).
- Azure Cost Management for actual-cost feed.
  - SDK/Client: `AzureCostManagementClient` (`src/hermes_arg_connector/azure.py`, `src/hermes_arg_connector/source.py`).
  - Auth: token scope `https://management.azure.com/.default` (`src/hermes_arg_connector/azure.py`).

**Fabric and OneLake:**
- Microsoft Fabric REST API for workspace/lakehouse/ontology operations.
  - SDK/Client: `FabricClient` over `httpx` (`src/fabric/fabric_client.py`).
  - Auth: token scope `https://api.fabric.microsoft.com/.default` (`src/fabric/fabric_client.py`).
- OneLake/ABFSS storage for durable datasets/state.
  - SDK/Client: `azure-storage-file-datalake`, `adlfs`, `deltalake`, `fsspec`, `pyarrow` (`pyproject.toml`, `src/storage/`, `src/hermes_arg_connector/fs.py`).
  - Auth: token scope `https://storage.azure.com/.default` (`src/fabric/auth.py`).

**Identity and AI services:**
- Microsoft Entra ID for API and frontend identity flows.
  - SDK/Client: `PyJWT` JWKS validation (`src/api/auth.py`) and MSAL browser (`web/src/lib/auth.ts`, `web/package.json`).
  - Auth config: `HERMES_ENTRA_TENANT_ID`, `HERMES_ENTRA_AUDIENCE`, `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`, `NEXT_PUBLIC_ENTRA_API_SCOPE` (`src/api/runtime.py`, `web/src/lib/auth.ts`).
- Azure AI Foundry prompt agent for Copilot narration.
  - SDK/Client: Foundry data-plane REST wrapper (`src/operations/foundry_agent.py`).
  - Auth: token scope `https://ai.azure.com/.default`; runtime config via `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_AGENT_NAME` (`src/operations/foundry_agent.py`, `infra/terraform/container_apps.tf`).

**Security intelligence feeds:**
- Microsoft Security Update Guide OData (`https://api.msrc.microsoft.com/sug/v2.0/en-US/affectedProduct`) (`src/intelligence/vulnerability/connector.py`).
- NVD CVE API (`https://services.nvd.nist.gov/rest/json/cves/2.0`) (`src/intelligence/vulnerability/connector.py`).
- FIRST.org EPSS API (`https://api.first.org/data/v1/epss`) (`src/intelligence/vulnerability/connector.py`).
- CISA KEV JSON feed (`https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json`) (`src/intelligence/vulnerability/connector.py`).

## Data Storage

**Databases:**
- Not detected as a dedicated relational/NoSQL service. Durable operational data is persisted as OneLake-backed files/tables via Delta/Parquet (`src/storage/delta_writer.py`, `src/storage/parquet_writer.py`, `src/storage/onelake_writer.py`).

**File Storage:**
- OneLake ABFSS path is the production durable root (`infra/terraform/container_apps.tf`, `src/hermes_arg_connector/fs.py`).
- Local filesystem fallback for development or non-Fabric mode (`src/api/runtime.py`, `config.example.yaml`).
- Azure Key Vault for submitted onboarding secrets and bootstrap secret write-through (`src/onboarding/credentials.py`, `src/api/akv_bootstrap.py`).

**Caching:**
- In-process TTL caches for semantic snapshot tables and external enrichment connectors (`src/api/runtime.py`, `src/intelligence/vulnerability/enrichment_cache.py`).

## Authentication & Identity

**Auth Provider:**
- Microsoft Entra ID with JWT validation (`EntraJwtAuthenticator`) (`src/api/auth.py`).
  - Implementation: issuer and JWKS from tenant; explicit grants mapping via `HERMES_API_GATEWAY_GRANTS` (`src/api/auth.py`, `src/api/runtime.py`).
- Gateway-asserted identity mode (`HeaderPrincipalAuthenticator`) (`src/api/auth.py`).
- Static token mode for local/testing (`StaticTokenAuthenticator`) (`src/api/auth.py`, `src/api/runtime.py`).
- Azure managed identity or service principal for Fabric/KeyVault/OneLake/Foundry clients (`src/fabric/auth.py`, `src/onboarding/credentials.py`, `src/operations/foundry_agent.py`).

## Monitoring & Observability

**Error Tracking:**
- None dedicated (no Sentry/Rollbar detected). API emits structured errors and logs (`src/api/app.py`).

**Logs:**
- OpenTelemetry metric instrumentation in API (`src/api/telemetry.py`).
- Azure Container Apps probes + Application Insights/Log Analytics wiring in Terraform (`infra/terraform/container_apps.tf`).

## CI/CD & Deployment

**Hosting:**
- Azure Container Apps hosts backend and frontend containers (`infra/terraform/container_apps.tf`).
- Azure Container Registry stores images referenced by Terraform (`infra/terraform/container_apps.tf`).

**CI Pipeline:**
- GitHub Actions workflow exists at `.github/workflows/ci.yml` with backend (ruff/pytest), frontend (lint/test/build), and Trivy SARIF security scan jobs.

## Environment Configuration

**Required env vars:**
- API auth/runtime: `HERMES_API_AUTH`, `HERMES_API_TOKENS`, `HERMES_API_GATEWAY_GRANTS`, `HERMES_ENTRA_TENANT_ID`, `HERMES_ENTRA_AUDIENCE`, `HERMES_API_CORS_ORIGINS` (`src/api/runtime.py`, `src/api/app.py`).
- State/Fabric: `HERMES_HOME`, `HERMES_FABRIC_CONFIG`, `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID`, `FABRIC_ONTOLOGY_NAME`, `AZURE_CLIENT_ID` (`src/api/runtime.py`, `infra/terraform/container_apps.tf`).
- Key Vault onboarding/bootstrap: `HERMES_CONNECTION_KEY_VAULT`, `HERMES_AKV_BOOTSTRAP_ENABLED`, `HERMES_AKV_BOOTSTRAP_SECRETS` (`src/api/akv_bootstrap.py`, `src/onboarding/credentials.py`).
- Foundry Copilot: `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME`, `FOUNDRY_API_VERSION` (`src/operations/foundry_agent.py`).
- Optional vuln feed auth: `NVD_API_KEY` (`src/intelligence/vulnerability/connector.py`).
- Frontend runtime/public config: `NEXT_PUBLIC_HERMES_API_BASE_URL`, `NEXT_PUBLIC_ENTRA_CLIENT_ID`, `NEXT_PUBLIC_ENTRA_TENANT_ID`, `NEXT_PUBLIC_ENTRA_API_SCOPE` (`web/src/lib/api-client.ts`, `web/src/lib/auth.ts`).

**Secrets location:**
- Production secrets are expected in Azure Key Vault and/or secret-backed environment values (`src/onboarding/credentials.py`, `src/api/akv_bootstrap.py`, `infra/terraform/container_apps.tf`).
- Local secret material is environment-driven (for example `env://AZURE_CLIENT_SECRET`) and intentionally not persisted in plaintext (`src/hermes_arg_connector/local.py`, `src/onboarding/credentials.py`).

## Webhooks & Callbacks

**Incoming:**
- None detected. API surface is standard request/response FastAPI routes under `src/api/routers/` (inventory via `src/api/routers/*.py`).

**Outgoing:**
- None detected for webhook-style push delivery.
- Outbound integrations are pull/request-based HTTP or CLI invocations (Azure APIs, Fabric APIs, Foundry APIs, public vulnerability feeds) (`src/hermes_arg_connector/azure.py`, `src/fabric/fabric_client.py`, `src/operations/foundry_agent.py`, `src/intelligence/vulnerability/connector.py`).

---

*Integration audit: 2026-08-24*
