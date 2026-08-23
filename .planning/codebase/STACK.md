# Technology Stack

**Analysis Date:** 2026-08-23

## Languages

**Primary:**
- Python 3.11+ (`pyproject.toml`) - connector CLI, FastAPI API, Fabric/OneLake persistence, ontology, semantic and operational intelligence.
- TypeScript/JavaScript (`web/src/`, `web/package.json`) - Next.js operations workbench UI.

**Secondary:**
- HCL/Terraform (`infra/terraform/`) - Azure and Fabric infrastructure provisioning.
- Bash (`scripts/`, `infra/scripts/`) - local startup, image publishing, deployment, and Foundry post-apply operations.
- YAML (`config.example.yaml`, `fabric.config.example.yaml`, `plugin.yaml`) - connector, Fabric, and Hermes plugin configuration.

## Runtime

**Environment:**
- Python 3.12-slim in the production API image (`Dockerfile`); the project supports Python `>=3.11` (`pyproject.toml`).
- Node.js runtime for the Next.js web image; the web app uses Next.js standalone output (`web/next.config.mjs`).
- Azure Container Apps for deployed API and UI (`infra/terraform/container_apps.tf`).

**Package Manager:**
- `uv` for Python dependency resolution and virtual environments (`Dockerfile`, `uv.lock`).
- npm for the web application (`web/package.json`; lockfile should be kept with the web project).
- Lockfiles: `uv.lock` is present; Terraform provider lock is present at `infra/terraform/.terraform.lock.hcl`.

## Frameworks

**Core:**
- FastAPI `>=0.115,<1` and Uvicorn `>=0.32,<1` (`pyproject.toml`) - HTTP API and ASGI serving (`src/api/app.py`, `Dockerfile`).
- Next.js `14.2.35`, React 18, and React DOM (`web/package.json`) - browser workbench.
- Fluent UI React Components 9 (`web/package.json`) - UI component system.
- Cytoscape and `cytoscape-fcose` (`web/package.json`) - graph visualization and layout.

**Testing:**
- pytest `>=9.0.3,<10` (`pyproject.toml`) - Python tests under `tests/`.
- Vitest 2, Testing Library React, jsdom, and `@testing-library/user-event` (`web/package.json`) - UI tests.

**Build/Dev:**
- Hatchling (`pyproject.toml`) - Python wheel packaging.
- uv sync with frozen `uv.lock` (`Dockerfile`) - reproducible API image dependencies.
- Next standalone build (`web/next.config.mjs`) - self-contained production web bundle.
- Terraform >=1.9,<2 with AzureRM, Fabric, AzAPI, and Random providers (`infra/terraform/providers.tf`).
- Azure CLI plus the Resource Graph extension (`Dockerfile`, `src/hermes_arg_connector/azure.py`) - production ARG extraction.

## Key Dependencies

**Critical:**
- `azure-identity` (`pyproject.toml`) - managed identity, service principal, and developer Azure CLI credentials (`src/fabric/auth.py`, `src/operations/foundry_agent.py`).
- `azure-keyvault-secrets` (`pyproject.toml`, `src/api/akv_bootstrap.py`) - secret storage and retrieval.
- `azure-storage-file-datalake`, `adlfs`, `deltalake`, `pyarrow`, and `fsspec` (`pyproject.toml`) - OneLake/ADLS-backed Delta, Parquet, and filesystem access.
- `httpx` (`pyproject.toml`) - Fabric, Resource Graph, MSRC, NVD, EPSS, and other HTTP clients.
- `PyJWT[crypto]` (`pyproject.toml`, `src/api/auth.py`) - Entra JWT signature, issuer, audience, and claim validation.
- `PyYAML` (`pyproject.toml`) - YAML connector and Fabric configuration loading.
- `opentelemetry-api` (`pyproject.toml`, `src/api/telemetry.py`) - low-cardinality request and intelligence metrics.
- `@azure/msal-browser` and `@azure/msal-react` (`web/package.json`) - browser-side Entra authentication.
- `zod` (`web/package.json`) - frontend runtime validation.

**Infrastructure:**
- `azurerm` `~>5.1`, `microsoft/fabric` `~>1.13`, `Azure/azapi` `~>2.6`, and `hashicorp/random` `~>3.6` (`infra/terraform/providers.tf`) - Azure resources, Fabric workspace/lakehouse, API resources not covered by AzureRM, and unique naming.

## Configuration

**Environment:**
- Python connector defaults are YAML-driven through `config.yaml`, based on `config.example.yaml`; do not read or publish local secret-bearing config.
- Fabric runtime is selected with `HERMES_FABRIC_CONFIG` and `fabric.config.yaml`/`fabric.config.example.yaml` (`src/api/runtime.py`).
- API auth, storage root, CORS, provider refresh, Foundry, Key Vault, and Azure identity are environment-driven (`src/api/runtime.py`, `src/api/akv_bootstrap.py`).
- Browser configuration is in `web/.env.local.example`; only `NEXT_PUBLIC_*` variables are intended for browser exposure.

**Build:**
- Python packaging: `pyproject.toml` and `uv.lock`.
- API container: `Dockerfile`.
- Web build: `web/package.json`, `web/next.config.mjs`, and `web/tsconfig.json`.
- Deployment: `infra/terraform/*.tf` and `infra/scripts/deploy.sh`.

## Platform Requirements

**Development:**
- Python 3.11+, uv, Node.js/npm, Azure CLI with Resource Graph, and an authenticated Azure identity (`README.md`).
- Use `uv sync --extra test` and `npm` scripts defined in `web/package.json`.

**Production:**
- Azure Container Apps, Azure Container Registry, user-assigned managed identity, Key Vault, Log Analytics/Application Insights, and optionally Fabric capacity/workspace/lakehouse (`infra/terraform/main.tf`, `infra/terraform/container_apps.tf`, `infra/terraform/fabric.tf`).
- The API image must contain the `az` Resource Graph extension (`Dockerfile`); durable production state should use OneLake rather than container-local disk (`infra/terraform/container_apps.tf`).

---

*Stack analysis: 2026-08-23*
