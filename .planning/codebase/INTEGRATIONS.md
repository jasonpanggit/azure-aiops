# External Integrations

**Analysis Date:** 2026-09-01

## APIs & External Services

**Azure Resource Discovery:**
- Azure Resource Graph (via `az graph query`) - resource/container/change/assessment/installation/Advisor recommendation queries
  - Client: shells out to Azure CLI (`az`), noted in `Dockerfile` and config comments
  - Config: `config.yaml` `azure.max_query_workers`, `page_size`, `max_pages`
- Azure MCP (`azmcp` executable) - subscription discovery
  - Invoked via `config.yaml` `azure.mcp_command: ["azmcp"]`
  - Declared as a pinned external dependency in `plugin.yaml`
- Azure Cost Management (`Microsoft.CostManagement` ActualCost API) - billed spend during discovery
  - Config: `config.yaml` `azure.cost_management` (enabled, `lookback_days`)

**Microsoft Fabric:**
- Fabric REST API (`https://api.fabric.microsoft.com/v1`) - workspace, lakehouse, data agent management
  - Client: `src/fabric/fabric_client.py` (base URL + scope `https://api.fabric.microsoft.com/.default`)
  - Related: `src/fabric/workspace_manager.py`, `src/fabric/lakehouse_manager.py`, `src/fabric/data_agent_manager.py`, `src/fabric/sql_endpoint.py`
  - Auth: `src/fabric/auth.py` (`FabricAuthConfig`)
  - Config profiles: `fabric.config.yaml`, `fabric.config.deploy.yaml`, `fabric.local.yaml`, `fabric.service-principal.example.yaml`

**Vulnerability Intelligence (public feeds):**
- NVD (National Vulnerability Database) CVE enrichment - `NvdCveEnrichmentConnector`, `src/intelligence/vulnerability/connector.py`
  - Auth: optional `NVD_API_KEY` env var
- EPSS scores - `EpssScoreConnector`, same file
- CISA KEV catalog - `KevCatalogConnector`, same file
- MSRC KB lookup - `MsrcKbLookupConnector`, same file
- Client: `httpx.get` (injectable for testing)
- Caching: `src/intelligence/vulnerability/enrichment_cache.py` (`EnrichmentCache`)

**Azure AI Foundry (Agent Orchestration):**
- Azure AI Foundry project agents - `src/operations/foundry_agent.py`
  - SDK: `azure-ai-projects`, `agent-framework`
  - Endpoint: `ENV_PROJECT_ENDPOINT` env var
  - Per-specialist agent names/versions: `FOUNDRY_<SPECIALIST>_AGENT_NAME`, `FOUNDRY_AGENT_VERSION`
  - Resilience: configurable timeout, max retries, and circuit breaker threshold/reset via env vars
  - Orchestration mode toggle: `ENV_AGENT_ORCHESTRATION_MODE` (`src/operations/maf_orchestrator.py`)
  - Infra: `infra/terraform/foundry.tf`

## Data Storage

**Databases:**
- No traditional relational/NoSQL database detected. Data persistence is file/table based via Delta Lake.

**File Storage / Lakehouse:**
- Microsoft OneLake (ADLS Gen2-compatible) - Delta Lake tables for ontology/semantic datasets
  - Client stack: `azure-storage-file-datalake`, `adlfs`, `fsspec`, `deltalake`, `pyarrow`
  - Local dev fallback: `local_onelake_root` in `src/fabric/config.py` (filesystem-backed OneLake substitute)
  - Document store: `src/storage/onelake_documents.py` (`OneLakeDocumentStore`)
  - Local output dir fallback: `storage.output_dir` in `config.yaml` (`./data`)

**Caching:**
- Local enrichment cache for vulnerability data - `src/intelligence/vulnerability/enrichment_cache.py`
- Graph output cache directories present in workspace: `graphify-out/cache`, `src/graphify-out/cache`

## Authentication & Identity

**Auth Provider:**
- Microsoft Entra ID (Azure AD)
  - Azure resource/Fabric auth: `azure-identity` (DefaultAzureCredential / managed identity), `src/fabric/auth.py`
  - Web frontend login: MSAL (`@azure/msal-browser`, `@azure/msal-react`) in `web/`
  - API auth modes (`src/api/runtime.py`):
    - Token mode (`AUTH_TOKEN`, default) - static bearer tokens via `ENV_TOKENS`
    - Gateway mode (`AUTH_GATEWAY`) - JWT assertion validated against `ENV_ENTRA_TENANT_ID` + `ENV_ENTRA_AUDIENCE` using `PyJWT`
    - Gateway grants configured via `ENV_GATEWAY_GRANTS`
  - Key Vault-backed client ID resolution: `src/api/akv_bootstrap.py` (`AZURE_CLIENT_ID`)

## Monitoring & Observability

**Error Tracking:**
- No dedicated error-tracking SaaS (e.g., Sentry) detected.

**Telemetry/Tracing:**
- OpenTelemetry API (`opentelemetry-api`) - `src/fabric/telemetry.py`
- Azure alerting configured via Terraform - `infra/terraform/alerting.tf`

**Logs:**
- Standard Python `logging` module usage observed (e.g., `src/api/runtime.py` imports `logging`)

## CI/CD & Deployment

**Hosting:**
- Azure Container Apps - `infra/terraform/container_apps.tf`
- Azure API Management (APIM) front door for API/MCP proxy - `infra/terraform/apim.tf`, `apim-mcp-proxy.tf`, `apim-policies/`
- Container images built via `Dockerfile` (Operations API), `Dockerfile.azure-mcp`, `Dockerfile.mcp`

**CI Pipeline:**
- Not confirmed from files inspected (no `.github/workflows` reviewed in this pass) — check root for GitHub Actions config if present.

**Infrastructure as Code:**
- Terraform - `infra/terraform/*.tf` (main, providers, variables, outputs, mcp_server, azure_mcp_server, fabric, foundry, persistence, alerting, apim)
- Deployment scripts: `infra/scripts/configure-entra-app-roles.sh`, `infra/scripts/rollback-apim-mcp.sh`, `scripts/`

## Environment Configuration

**Required env vars (non-secret names only):**
- `AIOPS_ARG_CONFIG`, `AIOPS_FABRIC_CONFIG` - config file paths
- `AIOPS_REFRESH_TRIGGER_SECRET` - refresh endpoint trigger secret (value not read)
- `AIOPS_HOME` - local state root override
- `AIOPS_ENTRA_TENANT_ID`, `AIOPS_ENTRA_AUDIENCE` (gateway auth mode)
- `AZURE_CLIENT_ID` - managed identity / Key Vault client
- `NVD_API_KEY` - optional vulnerability feed API key
- `APPROVED_SEARCH_API_KEY` - approved search API key gate
- Foundry: `ENV_PROJECT_ENDPOINT`, `ENV_AGENT_NAME`, `FOUNDRY_AGENT_VERSION`, `FOUNDRY_<SPECIALIST>_AGENT_NAME/VERSION`, timeout/retry/circuit-breaker vars

**Secrets location:**
- Azure Key Vault (`azure-keyvault-secrets` SDK, `src/api/akv_bootstrap.py`) for production secret retrieval
- Local `.aiops-local/` directory present in workspace (connections, state) — not inspected for contents (forbidden/sensitive)
- No `.env` file detected in repo root listing

## Webhooks & Callbacks

**Incoming:**
- Refresh trigger endpoint gated by `AIOPS_REFRESH_TRIGGER_SECRET` - `src/api/routers/inventory.py` (acts as a manually-triggered webhook-style endpoint)

**Outgoing:**
- None detected (no outbound webhook dispatch code found in this pass)

---

*Integration audit: 2026-09-01*
