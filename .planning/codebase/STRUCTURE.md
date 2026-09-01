# Codebase Structure

**Analysis Date:** 2026-09-01

## Directory Layout

```
azure-aiops/
├── src/                        # Python backend (API, agents, ontology, ingestion)
│   ├── api/                    # FastAPI app + per-domain routers
│   │   └── routers/
│   ├── agents/operations/      # Specialist analyzer implementations
│   ├── operations/             # Copilot orchestration, Foundry client, patching
│   │   ├── foundry_prompts/    # Per-specialist prompt templates
│   │   └── patching/           # Patch/exposure domain service
│   ├── mcp_server/             # Standalone Azure MCP sidecar app (separately deployed)
│   ├── onboarding/             # Connection registry, credentials, discovery/ingestion
│   ├── ontology/               # Entity/relationship building, confidence, publish/sync
│   ├── semantic/               # Semantic Knowledge Layer (governed read layer)
│   ├── fabric/                 # Fabric workspace/lakehouse/data-agent management
│   ├── fabric_pipelines/       # Per-domain batch pipelines (patch, vuln, governance...)
│   ├── storage/                # Delta/Parquet/OneLake writers, partitioning, locking
│   ├── network/                # Network topology/flow/rule-engine domain logic
│   ├── situations/             # Durable situation (incident-like) materialization
│   └── intelligence/           # Domain sub-packages (change, governance, health,
│                                #   incident(s), inventory, lifecycle, patch,
│                                #   predeploy, predictive, remediation, vulnerability)
├── web/                        # Next.js frontend
│   ├── src/app/                # App Router pages, one directory per drawer/domain
│   ├── src/components/         # Shared UI components (ui/, network/, exposure/, predeploy/)
│   ├── src/hooks/               # useApi, useTelemetry
│   ├── src/lib/                # api-client, auth, scope, permissions, format, csv, types
│   └── src/test/                # Vitest setup + fixtures
├── infra/                      # Infrastructure as code + operational scripts
│   ├── terraform/              # APIM, Container Apps, Foundry, Fabric, MCP server, alerting
│   ├── scripts/                # deploy.sh, build-and-push.sh, create-foundry-agent.sh, etc.
│   └── knowledge/               # Design-standard reference docs consulted during infra work
├── tests/                      # Python test suite (pytest), mirrors src/ package layout
├── scripts/                    # Repo-level utility/dev scripts
├── docs/                       # Supplementary documentation (ADRs, ops notes, diagrams)
├── mock-fabric-lakehouse/      # Local mock of Fabric lakehouse for offline dev
├── graphify-out/               # Generated knowledge-graph artifacts (cache)
├── .planning/                  # GSD planning state (phases, plans, codebase docs)
├── Dockerfile                  # Operations API container image
├── Dockerfile.azure-mcp        # Azure MCP sidecar container image
├── Dockerfile.mcp              # Legacy/alt MCP container image
├── config.yaml / config.example.yaml       # App runtime config
├── fabric.*.yaml                # Fabric environment configs (local, deploy, service-principal)
├── pyproject.toml / uv.lock    # Python project + locked dependencies
└── ARCHITECTURE.md, ONTOLOGY_SCHEMA.md, DATA_SOURCES.md, ...  # Root design docs (authoritative
                                 #   for domain intent; see .planning/codebase/ARCHITECTURE.md
                                 #   for as-built implementation architecture)
```

## Directory Purposes

**`src/api/`:**
- Purpose: HTTP surface for the Operations Workbench — auth, RBAC, routing, error translation
- Contains: App factory (`app.py`), cross-cutting concerns (`auth.py`, `rbac.py`, `scope.py`, `errors.py`, `telemetry.py`, `models.py`), and `routers/` (one file per domain)
- Key files: `src/api/app.py`, `src/api/routers/copilot.py`, `src/api/routers/multi_agent.py`

**`src/operations/`:**
- Purpose: Operations Copilot orchestration and Foundry agent integration
- Contains: `maf_orchestrator.py` (routing), `autonomous_investigation.py` (specialist selection), `foundry_agent.py` (Foundry Responses API client), per-domain analyzer modules, `patching/` subpackage, `foundry_prompts/` (text templates)
- Key files: `src/operations/maf_orchestrator.py`, `src/operations/foundry_agent.py`, `src/operations/tools.py`

**`src/agents/operations/`:**
- Purpose: Specialist analyzer implementations invoked by the Copilot
- Contains: `context_router.py`, `health_analyzer.py`, `impact_analyzer.py`, `incident_analyzer.py`, `ownership_analyzer.py`, `recommendation_engine.py`, `compliance_analyzer.py`, `operational_reasoner.py`, `operational_summary.py`

**`src/mcp_server/`:**
- Purpose: Standalone Azure MCP server (deployed independently in ACA, behind APIM)
- Contains: `app.py` — per-subscription SPN/managed-identity tool relay
- Deployed via: `Dockerfile.azure-mcp`, `infra/terraform/azure_mcp_server.tf`

**`src/onboarding/`:**
- Purpose: Connection lifecycle, credential storage, discovery source adapters, scheduled ingestion
- Contains: `registry.py`, `credentials.py`, `discovery_source.py`, `ingestion_service.py`, `azure_clients.py`, `cli.py`

**`src/ontology/`:**
- Purpose: Graph entity/relationship construction, confidence scoring, Fabric publish/reconcile
- Contains: `entity_builder.py`, `relationship_builder.py`, `confidence.py`, `ontology_publisher.py`, `ontology_sync.py`, `ontology_validator.py`

**`src/semantic/`:**
- Purpose: Governed read layer over the published ontology snapshot, blended with live data
- Contains: `semantic_engine.py`, `hybrid_query.py`, `live_provider.py`, `live_operations.py`, `query_cache.py`, `semantic_validator.py`

**`src/fabric/` and `src/fabric_pipelines/`:**
- Purpose: Fabric platform integration (`fabric/`) and per-domain batch pipelines that populate curated tables (`fabric_pipelines/`)
- Contains: `fabric/fabric_client.py`, `fabric/workspace_manager.py`; `fabric_pipelines/patch_pipeline.py`, `vulnerability_pipeline.py`, `governance_pipeline.py`, `topology_pipeline.py`, `predeploy_pipeline.py`, `change_pipeline.py`, `lifecycle_pipeline.py`

**`src/storage/`:**
- Purpose: Physical persistence primitives — Delta/Parquet writers, OneLake filesystem, partitioning, locking
- Key files: `delta_writer.py`, `onelake_fs.py`, `onelake_writer.py`, `parquet_writer.py`

**`src/network/`:**
- Purpose: Network domain logic feeding the network specialist and network drawer
- Key files: `topology.py`, `flow.py`, `rule_engine.py`, `gaps.py`, `tightening.py`

**`src/situations/`:**
- Purpose: Durable "situation" (incident-like investigation) materialization and storage
- Key files: `materializer.py`, `models.py`, `store.py`

**`web/src/app/`:**
- Purpose: Next.js App Router pages, one directory per operational drawer
- Contains: `agents/`, `changes/`, `compliance/`, `connections/`, `copilot/`, `exposure/`, `finops/`, `governance/`, `identity/`, `inventory/`, `investigate/`, `network/`, `remediation/`, `resource-health/`, `search/`, `services/`, `situations/`, `twin/`, `vulnerabilities/`
- Each page directory typically has `page.tsx` and a co-located `page.test.tsx`

**`web/src/components/`:**
- Purpose: Shared UI building blocks
- Contains: `ui/` (generic components — cards, charts, drawers, tables), `network/` (topology graph/drawer), `exposure/` (patch inventory), `predeploy/` (blast-radius graph)

**`web/src/lib/`:**
- Purpose: Frontend cross-cutting logic — API client, auth, scope/permissions, formatting
- Key files: `api-client.ts`, `auth.ts`, `scope.ts`, `scope-options.ts`, `permissions.ts`, `situations.ts`, `network-graph.ts`

**`infra/terraform/`:**
- Purpose: All provisioned Azure infrastructure as code
- Key files: `main.tf`, `apim.tf`, `apim-mcp-proxy.tf`, `container_apps.tf`, `foundry.tf`, `fabric.tf`, `azure_mcp_server.tf`, `mcp_server.tf`, `persistence.tf`, `alerting.tf`
- Contains: `apim-policies/` (XML policy fragments, e.g. `mcp-inbound.xml`)

**`infra/scripts/`:**
- Purpose: Operational automation invoked by Terraform `local-exec` or manually
- Key files: `deploy.sh` (drives full deploy), `create-foundry-agent.sh`, `validate-runtime-e2e.sh`, `rollback-apim-mcp.sh`, `build-and-push.sh`

**`tests/`:**
- Purpose: Python test suite, mirrors `src/` package structure by subpackage
- Contains: `tests/fixtures/` for shared test data

**`docs/`:**
- Purpose: Supplementary/ancillary documentation not part of the root design-doc set

**`mock-fabric-lakehouse/`:**
- Purpose: Local mock of a Fabric lakehouse for offline development without live Fabric capacity

## Key File Locations

**Entry Points:**
- `src/api/app.py`: Operations API FastAPI app factory
- `src/mcp_server/app.py`: Azure MCP sidecar FastAPI app
- `web/src/app/layout.tsx`: Next.js root layout
- `src/onboarding/cli.py`: Onboarding/ingestion CLI entry
- `infra/scripts/deploy.sh`: Full-stack deploy entry point

**Configuration:**
- `config.yaml` / `config.example.yaml`: App runtime config
- `fabric.config.yaml`, `fabric.local.yaml`, `fabric.service-principal.example.yaml`: Fabric environment configs
- `infra/terraform/terraform.tfvars`, `variables.tf`: Terraform inputs
- `web/.env.local` / `web/.env.local.example`: Frontend env config
- `pyproject.toml`: Python project/dependency config

**Core Logic:**
- `src/api/routers/*.py`: Domain endpoint handlers
- `src/semantic/semantic_engine.py`, `hybrid_query.py`: Read-side ontology query logic
- `src/operations/maf_orchestrator.py`, `autonomous_investigation.py`: Copilot orchestration
- `src/ontology/ontology_publisher.py`, `entity_builder.py`, `relationship_builder.py`: Graph construction/publish

**Testing:**
- `tests/`: pytest suite mirroring `src/`
- `web/src/**/*.test.tsx`, `web/src/**/*.test.ts`: Vitest co-located component/lib tests
- `web/vitest.config.ts`: Frontend test runner config

## Naming Conventions

**Files (Python):**
- `snake_case.py`, one primary responsibility per module (e.g. `foundry_agent.py`, `maf_orchestrator.py`, `ontology_publisher.py`)
- Domain-specific analyzers suffixed `_analyzer.py` (e.g. `health_analyzer.py`, `impact_analyzer.py`, `ownership_analyzer.py`)
- Pipeline modules suffixed `_pipeline.py` under `src/fabric_pipelines/`

**Files (TypeScript/Next.js):**
- Page components: `PascalCase`-free, always `page.tsx` inside a route-segment directory named for the feature (`web/src/app/<feature>/page.tsx`)
- Co-located tests: `<file>.test.tsx` / `<file>.test.ts` next to the source file, not in a separate `__tests__` tree
- Shared components: `PascalCase.tsx` (e.g. `DataCard.tsx`, `ScopeSelector.tsx`, `TopologyGraph.tsx`)
- Library modules: `kebab-case.ts` or `camelCase.ts` under `web/src/lib/` (e.g. `api-client.ts`, `network-graph.ts`, `scope-options.ts`)

**Directories:**
- Python subpackages under `src/` are singular domain nouns (`network`, `ontology`, `semantic`, `storage`) except plural where the concept is inherently plural (`situations`, `intelligence` sub-areas like `incidents`)
- Next.js route segments under `web/src/app/` are kebab-case matching the URL path (`resource-health/`, `changes/predeploy/`)
- Terraform files are named by the Azure resource group/concern they provision (`apim.tf`, `foundry.tf`, `fabric.tf`)

## Where to Add New Code

**New API endpoint / domain surface:**
- Add a router module: `src/api/routers/<domain>.py`
- Register it in `src/api/app.py` (import + `app.include_router(...)`)
- Add request/response models to `src/api/models.py` if shared, or co-locate simple models in the router
- Tests: `tests/api/routers/test_<domain>.py` (mirror path)

**New Copilot specialist:**
- Analyzer logic: `src/agents/operations/<name>_analyzer.py` or `src/operations/<name>_analyzer.py` (follow existing sibling naming)
- Prompt template: `src/operations/foundry_prompts/<name>_prompt.txt`
- Wire into `page_specialists` mapping in `src/operations/autonomous_investigation.py`
- Provision the Foundry agent via `infra/scripts/create-foundry-agent.sh` + Terraform `foundry_tool_registry` entry

**New Fabric pipeline:**
- Implementation: `src/fabric_pipelines/<domain>_pipeline.py`
- Curated table writer usage: reuse `src/storage/*` writers, don't hand-roll persistence

**New frontend page/drawer:**
- Route: `web/src/app/<feature>/page.tsx` (+ co-located `page.test.tsx`)
- Shared components: `web/src/components/<feature>/` if feature-specific, else `web/src/components/ui/`
- API access: extend `web/src/lib/api-client.ts`, add a typed hook in `web/src/hooks/` if reused across pages

**New Terraform resource:**
- Add to the most concern-aligned existing `.tf` file under `infra/terraform/` (e.g. new APIM policy → `apim.tf` or `apim-policies/`); create a new file only for a genuinely new subsystem
- Add any new role/identity grants consistently with existing `local.*_subscriptions` for-each patterns

**Utilities:**
- Shared Python helpers: closest-matching existing subpackage (`src/storage/`, `src/onboarding/`) rather than a new top-level utils module
- Shared frontend helpers: `web/src/lib/`

## Special Directories

**`.planning/`:**
- Purpose: GSD workflow state — phases, plans, requirements, codebase maps
- Generated: Partially (STATE.md and codebase docs are generated/refreshed by GSD commands)
- Committed: Yes

**`graphify-out/` (root and `web/graphify-out/`, `src/graphify-out/`):**
- Purpose: Generated knowledge-graph artifacts/cache
- Generated: Yes
- Committed: Check `.gitignore` before committing changes here — treat as build output

**`mock-fabric-lakehouse/`:**
- Purpose: Local offline substitute for a real Fabric lakehouse during development
- Generated: No (hand-maintained fixtures)
- Committed: Yes

**`web/.next/`:**
- Purpose: Next.js build output
- Generated: Yes
- Committed: No (build artifact)

**`infra/terraform/.terraform/`, `terraform.tfstate*`:**
- Purpose: Terraform provider cache and state
- Generated: Yes
- Committed: State files should not be treated as source of truth for review — verify `.gitignore` coverage before assuming they're tracked

**`__pycache__/` (throughout `src/`, `tests/`):**
- Purpose: Python bytecode cache
- Generated: Yes
- Committed: No

---

*Structure analysis: 2026-09-01*
