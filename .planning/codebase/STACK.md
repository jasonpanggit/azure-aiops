# Technology Stack

**Analysis Date:** 2026-09-01

## Languages

**Primary:**
- Python 3.11+ (`pyproject.toml` requires `>=3.11`; Docker builds on `python:3.12-slim`) - core plugin, API, connectors, ontology/semantic pipeline under `src/`
- TypeScript / React - `web/` Next.js frontend

**Secondary:**
- Terraform (HCL) - `infra/terraform/` for Azure infrastructure provisioning
- YAML - configuration (`config.yaml`, `fabric.config.yaml`, `plugin.yaml`, `arg.config.deploy.yaml`)
- Bash - deployment/ops scripts in `scripts/` and `infra/scripts/`

## Runtime

**Environment:**
- Python >=3.11 (dev), Python 3.12 (container runtime, `Dockerfile`)
- Node.js (version per `web/package.json`, Next.js 14.2.35 requires Node 18.17+)

**Package Manager:**
- Python: `uv` (see `Dockerfile` — `uv venv`, `uv sync --frozen`), lockfile `uv.lock` present
- Build backend: `hatchling` (`pyproject.toml` `[build-system]`)
- JS: npm, lockfile `web/package-lock.json` present

## Frameworks

**Core:**
- FastAPI (`fastapi>=0.115,<1`) - Operations API, `src/api/` (optional extra `api`)
- Uvicorn (`uvicorn>=0.32,<1`) - ASGI server, entry `uvicorn --factory api.app:create_app`
- Next.js 14.2.35 + React 18 - `web/` frontend
- Fluent UI React Components (`@fluentui/react-components`) - web UI component library
- agent-framework (`agent-framework>=1.0,<2`) + `azure-ai-projects>=2.0,<3` - Azure AI Foundry agent orchestration, `src/operations/foundry_agent.py`, `src/operations/maf_orchestrator.py`

**Testing:**
- pytest (`pytest>=9.0.3,<10`) - Python tests in `tests/`
- ruff (`ruff>=0.16,<0.17`) - Python lint
- Vitest (`^2.1.9`) - `web/vitest.config.ts`, frontend unit tests
- @testing-library/react, jsdom - web component testing

**Build/Dev:**
- hatchling - Python wheel build, packages listed under `[tool.hatch.build.targets.wheel]` (`src/fabric`, `src/fabric_pipelines`, `src/storage`, `src/ontology`, `src/semantic`, `src/agents`, `src/operations`, `src/intelligence`, `src/onboarding`, `src/api`)
- Docker multi-stage builds: `Dockerfile` (Operations API), `Dockerfile.azure-mcp`, `Dockerfile.mcp`
- ESLint (`eslint-config-next`) - web lint

## Key Dependencies

**Critical:**
- `azure-identity>=1.19,<2` - Azure AD authentication (DefaultAzureCredential, managed identity) across connectors and API
- `azure-keyvault-secrets>=4.9,<5` - secret retrieval, `src/api/akv_bootstrap.py`
- `azure-storage-file-datalake>=12.18,<13` + `adlfs>=2024.7,<2025` + `fsspec>=2024.6,<2025` - OneLake/ADLS Gen2 access for Delta Lake datasets
- `deltalake>=1.0,<2` + `pyarrow>=23.0.1,<24` - Delta Lake table read/write for ontology datasets
- `httpx>=0.27,<1` - HTTP client for Fabric REST API, MCP calls, and vulnerability intel connectors
- `PyJWT[crypto]>=2.10,<3` - JWT validation for gateway/Entra auth mode, `src/api/runtime.py`
- `opentelemetry-api>=1.29,<2` - tracing/telemetry, `src/fabric/telemetry.py`
- `@azure/msal-browser`, `@azure/msal-react` (web) - Entra ID login in the Next.js frontend
- `cytoscape` + `cytoscape-fcose` (web) - graph/topology visualization
- `zod` (web) - schema validation

**Infrastructure:**
- `PyYAML>=6,<7` - config file parsing (`config.yaml`, `fabric.config.yaml`)
- Azure MCP (`azmcp` executable) - external pinned binary for Azure subscription/resource discovery, referenced in `plugin.yaml` `external_dependencies` and `config.yaml` (`azure.mcp_command`)
- Azure CLI (`az`) - required in runtime image for `az graph query` (Resource Graph extraction), noted in `Dockerfile` comments

## Configuration

**Environment:**
- No committed `.env` file found in root listing (`.aiops-local/` present, contents not inspected)
- Runtime environment variables read directly via `os.environ`/`os.getenv` — no dotenv loader detected
- Key env vars (non-exhaustive, see INTEGRATIONS.md for auth-specific ones):
  - `AIOPS_ARG_CONFIG`, `AIOPS_FABRIC_CONFIG` - paths to YAML config files (`src/api/routers/inventory.py`)
  - `AIOPS_REFRESH_TRIGGER_SECRET` - shared secret to trigger refresh endpoint
  - `AIOPS_HOME` (`ENV_HOME`) - local state root (`src/api/runtime.py`)
  - `NVD_API_KEY` - optional NVD vulnerability API key (`src/intelligence/vulnerability/connector.py`)
  - `AZURE_CLIENT_ID` - used by Key Vault bootstrap (`src/api/akv_bootstrap.py`)
  - Foundry agent config: `ENV_PROJECT_ENDPOINT`, `ENV_AGENT_NAME`, `FOUNDRY_<SPECIALIST>_AGENT_NAME`, `FOUNDRY_AGENT_VERSION`, `ENV_TIMEOUT`, `ENV_MAX_RETRIES`, `ENV_CIRCUIT_THRESHOLD`, `ENV_CIRCUIT_RESET_SECONDS`, `ENV_API_VERSION` (`src/operations/foundry_agent.py`)
  - Auth/gateway: `ENV_AUTH_MODE`, `ENV_GATEWAY_ASSERTION`, `ENV_GATEWAY_GRANTS`, `ENV_ENTRA_TENANT_ID`, `ENV_ENTRA_AUDIENCE`, `APPROVED_SEARCH_API_KEY` (`src/api/runtime.py`)

**Build:**
- `pyproject.toml` - Python project/deps/build config, pytest and ruff config sections
- `config.yaml` (from `config.example.yaml`) - Azure discovery settings: subscriptions, management groups, MCP command, query workers, cost management
- `fabric.config.yaml` / `fabric.config.deploy.yaml` / `fabric.local.yaml` / `fabric.service-principal.example.yaml` - Fabric workspace/lakehouse connection profiles for different environments (local, service principal, deploy)
- `arg.config.deploy.yaml` - Azure Resource Graph deployment config
- `web/next.config.mjs`, `web/tsconfig.json` - Next.js/TS build config
- `web/vitest.config.ts` - frontend test config

## Platform Requirements

**Development:**
- Python 3.11+, `uv` package manager
- Node.js for `web/` frontend
- Azure CLI (`az`) and Azure MCP (`azmcp`) executables available on PATH for discovery flows
- Local state directories: `.aiops-local/`, `.azure/` (present in workspace, not committed contents)

**Production:**
- Container-based deployment (Docker images built via `Dockerfile`, `Dockerfile.azure-mcp`, `Dockerfile.mcp`)
- Azure Container Apps (`infra/terraform/container_apps.tf`)
- Azure API Management fronting the MCP/API surface (`infra/terraform/apim.tf`, `apim-mcp-proxy.tf`, `apim-policies/`)
- Azure AI Foundry project for agent orchestration (`infra/terraform/foundry.tf`)
- Microsoft Fabric workspace + OneLake for ontology/semantic data storage
- Terraform-managed Azure infra: alerting, persistence, networking (see `infra/terraform/*.tf`)

---

*Stack analysis: 2026-09-01*
