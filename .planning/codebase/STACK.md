# Technology Stack

**Analysis Date:** 2026-08-24

## Languages

**Primary:**
- Python (project requires `>=3.11`) - core backend, connector, API, ontology, semantic, and intelligence modules (`pyproject.toml`, `src/`).
- TypeScript/JavaScript - Next.js operator web app (`web/package.json`, `web/src/`).

**Secondary:**
- HCL/Terraform - Azure/Fabric infrastructure and deployment topology (`infra/terraform/`).
- Bash - deployment and runtime helper scripts (`infra/scripts/deploy.sh`, `scripts/start-api.sh`).
- YAML - connector, Fabric, and plugin/runtime config (`config.example.yaml`, `fabric.config.example.yaml`, `plugin.yaml`).

## Runtime

**Environment:**
- API container runtime is Python `3.12-slim` (`Dockerfile`).
- Web container runtime is Node `22-alpine` (`web/Dockerfile`).
- API and web are deployed to Azure Container Apps (`infra/terraform/container_apps.tf`).

**Package Manager:**
- Python packages are resolved and installed with `uv` (`Dockerfile`, `uv.lock`).
- Web dependencies are managed with npm (`web/package.json`, `web/package-lock.json`).
- Lockfile: `uv.lock` present; `web/package-lock.json` present.

## Frameworks

**Core:**
- FastAPI (`>=0.115,<1`) + Uvicorn (`>=0.32,<1`) for the backend API (`pyproject.toml`, `src/api/app.py`).
- Next.js `14.2.35` + React 18 for the web workbench (`web/package.json`).
- Fluent UI v9 for frontend component system (`web/package.json`).

**Testing:**
- pytest (`>=9.0.3,<10`) for backend tests (`pyproject.toml`, `tests/`).
- Vitest + Testing Library + jsdom for frontend tests (`web/package.json`, `web/src/**/*.test.ts*`).

**Build/Dev:**
- Hatchling for Python build backend (`pyproject.toml`).
- Terraform for infra provisioning (`infra/terraform/*.tf`).
- Azure CLI + Resource Graph extension required in API runtime (`Dockerfile`, `src/hermes_arg_connector/azure.py`).

## Key Dependencies

**Critical:**
- `azure-identity` - managed identity/service principal and token acquisition across Azure services (`pyproject.toml`, `src/fabric/auth.py`, `src/operations/foundry_agent.py`).
- `azure-keyvault-secrets` - Key Vault secret read/write for onboarding/bootstrap (`pyproject.toml`, `src/onboarding/credentials.py`, `src/api/akv_bootstrap.py`).
- `azure-storage-file-datalake`, `adlfs`, `deltalake`, `pyarrow`, `fsspec` - OneLake/Delta/Parquet persistence (`pyproject.toml`, `src/storage/`, `src/hermes_arg_connector/fs.py`).
- `httpx` - outbound HTTP for Fabric, ARG REST path, and vulnerability feeds (`pyproject.toml`, `src/fabric/fabric_client.py`, `src/hermes_arg_connector/azure.py`, `src/intelligence/vulnerability/connector.py`).
- `PyJWT[crypto]` - Entra JWT validation in API auth path (`pyproject.toml`, `src/api/auth.py`).
- `opentelemetry-api` - API telemetry instrumentation (`pyproject.toml`, `src/api/telemetry.py`).
- `@azure/msal-browser` + `@azure/msal-react` - browser Entra auth (`web/package.json`, `web/src/lib/auth.ts`).

**Infrastructure:**
- Terraform providers: `hashicorp/azurerm`, `microsoft/fabric`, `azure/azapi`, and `hashicorp/random` (`infra/terraform/providers.tf`).

## Configuration

**Environment:**
- Connector behavior is configured by YAML (`config.example.yaml`) and loaded by `ConnectorConfig` (`src/hermes_arg_connector/config.py`).
- API runtime wiring is environment-driven via `HERMES_*`, `FABRIC_*`, and `AZURE_*` variables (`src/api/runtime.py`, `infra/terraform/container_apps.tf`).
- Web auth/API addressing uses `NEXT_PUBLIC_*` variables plus runtime `/api/config` lookup (`web/src/lib/auth.ts`, `web/src/lib/api-client.ts`, `web/Dockerfile`).

**Build:**
- Backend build files: `pyproject.toml`, `uv.lock`, `Dockerfile`.
- Frontend build files: `web/package.json`, `web/package-lock.json`, `web/Dockerfile`.
- Infrastructure/deploy files: `infra/terraform/*.tf`, `infra/scripts/deploy.sh`.

## Platform Requirements

**Development:**
- Python 3.11+, Node.js, npm, and Azure CLI with Resource Graph extension (`README.md`, `Dockerfile`).
- Local/dev runs use `uv sync --extra test` and npm scripts from `web/package.json` (`README.md`).

**Production:**
- Azure Container Apps + Azure Container Registry + user-assigned managed identity (`infra/terraform/container_apps.tf`).
- Azure Key Vault private endpoint path for onboarding secrets (`infra/terraform/persistence.tf`).
- Optional/expected Fabric OneLake-backed durable state via `abfss://...onelake.dfs.fabric.microsoft.com/...` (`infra/terraform/container_apps.tf`, `src/hermes_arg_connector/fs.py`).

---

*Stack analysis: 2026-08-24*
