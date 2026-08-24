# Codebase Structure

**Analysis Date:** 2026-08-24

## Directory Layout

```text
azure-aiops/
├── src/
│   ├── agents/                 # Operations agent orchestration
│   ├── api/                    # FastAPI application, auth, routers, providers
│   ├── fabric/                 # Fabric runtime, sync, mapping, quality, clients
│   ├── hermes_arg_connector/   # Azure ARG ingestion plugin and dataset store
│   ├── intelligence/           # Domain analysis engines
│   ├── network/                # Network topology and flow intelligence
│   ├── onboarding/             # Subscription connections, credentials, activation
│   ├── ontology/               # Entity/relationship building, validation, publishing
│   ├── operations/             # Foundry/operational agent integration
│   ├── semantic/               # Graph, hybrid, live, and semantic query services
│   └── storage/                # Delta, OneLake, partitioning, and document writers
├── tests/                      # Pytest unit, integration, scenario, and API tests
├── web/                        # Separate frontend application
├── infra/terraform/            # Azure deployment and infrastructure definitions
├── infra/scripts/              # Build, deploy, provisioning, and validation scripts
├── scripts/                    # Local startup and semantic graph helpers
├── docs/                       # Architecture, production, and pilot documentation
├── skills/                     # Packaged Hermes/GSD or domain skill assets
├── config*.yaml                # Project-local and example runtime configurations
├── pyproject.toml              # Python package, dependencies, CLI, test config
├── plugin.yaml                 # Hermes plugin manifest
└── Dockerfile                  # Container build entry
```

## Directory Purposes

**`src/api/`:**
- Purpose: HTTP application boundary for the Operations Workbench.
- Contains: `app.py`, `runtime.py`, auth/RBAC/dependencies, response models, telemetry, providers, and `routers/`.
- Key files: `src/api/app.py`, `src/api/runtime.py`, `src/api/dependencies.py`, `src/api/routers/operations.py`, `src/api/routers/context.py`.

**`src/hermes_arg_connector/`:**
- Purpose: Azure Resource Graph connector and Hermes plugin command implementation.
- Contains: Azure MCP/CLI adapters, query catalog, normalization, lock/state, local mode, scheduling, and generation storage.
- Key files: `src/hermes_arg_connector/cli.py`, `src/hermes_arg_connector/service.py`, `src/hermes_arg_connector/source.py`, `src/hermes_arg_connector/storage.py`.

**`src/fabric/` and `src/storage/`:**
- Purpose: Persist and project curated data into OneLake/Delta and Fabric Ontology.
- Contains: Runtime composition, Fabric clients, schema registry, dataset mapping, quality validation, Delta/OneLake writers, and document storage.
- Key files: `src/fabric/runtime.py`, `src/fabric/sync_service.py`, `src/fabric/dataset_mapper.py`, `src/storage/delta_writer.py`, `src/storage/onelake_writer.py`.

**`src/ontology/`:**
- Purpose: Govern graph identity, relationship shape, lifecycle, and publication.
- Contains: Builders, validators, graph synchronization, manager, publisher, and metadata synchronization.
- Key files: `src/ontology/entity_builder.py`, `src/ontology/relationship_builder.py`, `src/ontology/ontology_sync.py`, `src/ontology/ontology_validator.py`.

**`src/semantic/`:**
- Purpose: Query canonical graph snapshots and combine durable context with request-time operational data.
- Contains: semantic models/indexes, query services, caches, assertion reconciliation, hybrid query, and live operations/provider code.
- Key files: `src/semantic/semantic_engine.py`, `src/semantic/hybrid_query.py`, `src/semantic/live_operations.py`, `src/semantic/live_provider.py`.

**`src/intelligence/`:**
- Purpose: Domain-specific analysis over semantic context and evidence.
- Contains: `change/`, `incident/`, `incidents/`, `lifecycle/`, `patch/`, `predictive/`, `remediation/`, and `vulnerability/` packages.
- Key files: Each domain has an engine/service/context-builder pattern, for example `src/intelligence/patch/patch_intelligence.py` and `src/intelligence/incident/incident_intelligence.py`.

**`src/agents/operations/` and `src/operations/`:**
- Purpose: Compose domain engines into user-facing operational reasoning and Foundry integration.
- Contains: `operations_agent.py`, analyzers, context routing, summaries, prompt/tool integration.
- Key files: `src/agents/operations/operations_agent.py`, `src/agents/operations/operational_reasoner.py`, `src/operations/foundry_agent.py`.

**`src/onboarding/`:**
- Purpose: Register, validate, scope, sync, and activate subscription connections.
- Contains: registry, credentials, onboarding service/runtime, activation, sync coordination, and connection health.
- Key files: `src/onboarding/registry.py`, `src/onboarding/service.py`, `src/onboarding/runtime.py`, `src/onboarding/activation.py`.

**`src/network/`:**
- Purpose: Network topology, addressing, flow, and network-specific query/analysis behavior.
- Contains: models, topology, flow, design, addressing, query, and service modules.
- Key files: `src/network/service.py`, `src/network/flow.py`, `src/network/topology.py`.

**`tests/`:**
- Purpose: Verify domain engines, persistence, API contracts, integrations, and end-to-end fixture scenarios.
- Contains: `test_*.py` suites plus `*_scenario.py` fixtures/scenario helpers.
- Key files: `tests/test_api_http.py`, `tests/test_service.py`, `tests/test_fabric_client.py`, `tests/test_semantic_queries.py`, `tests/test_incremental_sync.py`.

**`web/`:**
- Purpose: Independent frontend client.
- Contains: Next.js/TypeScript configuration, package lock, Vitest setup, and UI source directories below the inspected depth.
- Key files: `web/package.json`, `web/next.config.mjs`, `web/vitest.config.ts`, `web/src/app/layout.tsx`, `web/src/lib/api-client.ts`.

**`infra/`:**
- Purpose: Deployment and Azure infrastructure.
- Contains: Terraform resources in `infra/terraform/` and operational scripts in `infra/scripts/`.
- Key files: `infra/terraform/main.tf`, `infra/terraform/container_apps.tf`, `infra/terraform/fabric.tf`, `infra/scripts/deploy.sh`.

## Key File Locations

**Entry Points:**
- `src/api/app.py`: FastAPI `create_app` factory.
- `src/hermes_arg_connector/cli.py`: `hermes-arg` command registration and dispatch.
- `__init__.py`: Hermes directory-plugin bootstrap.
- `hermes_plugin.py`: import-friendly Hermes facade.
- `scripts/start-api.sh`, `scripts/start-local.sh`: local process launchers.

**Configuration:**
- `pyproject.toml`: Python package metadata, dependencies, wheel packages, CLI entry point, and pytest defaults.
- `config.example.yaml`: ARG connector defaults and storage settings.
- `fabric.config.example.yaml`: Fabric runtime example.
- `plugin.yaml`: Hermes manifest and tool registration metadata.
- `infra/terraform/variables.tf`: infrastructure inputs.

**Core Logic:**
- `src/hermes_arg_connector/service.py`: source ingestion orchestration.
- `src/fabric/sync_service.py`: Fabric synchronization orchestration.
- `src/semantic/semantic_engine.py`: bounded semantic graph query engine.
- `src/fabric/runtime.py`: Fabric and intelligence runtime assembly.
- `src/api/runtime.py`: API context assembly.

**Testing:**
- `tests/`: all pytest suites; test names mirror the subsystem (`test_normalize.py`, `test_delta_tables.py`, `test_api_runtime.py`).
- `tests/fixtures/`: deterministic source payloads and test data.
- `tests/*_scenario.py`: reusable domain scenario inputs.

## Naming Conventions

**Files:**
- Python modules use lowercase `snake_case`, such as `src/hermes_arg_connector/service.py`, `src/hermes_arg_connector/queries.py`, and `src/api/runtime.py`.
- Test modules use `test_<feature>.py`; scenario helpers use `<feature>_scenario.py`.
- Infrastructure uses descriptive lowercase Terraform filenames such as `container_apps.tf` and `persistence.tf`.
- Documentation uses uppercase project artifacts at the root and title-case/uppercase Markdown names under planning.

**Directories:**
- Python packages are lowercase nouns or domain names: `src/intelligence/patch/`, `src/onboarding/`, `src/ontology/`.
- Intelligence domains use one directory per bounded capability, with some specialized plural/singular packages retained as distinct current boundaries (`incident/` and `incidents/`).
- API endpoints are grouped under `src/api/routers/` by resource or workflow (`operations.py`, `network.py`, `vulnerability.py`).

**Symbols:**
- Classes use `PascalCase` (`IngestionService`, `FabricSyncService`); functions and variables use `snake_case`; constants use uppercase.
- Builders/factories are named `build_*` or `create_*`; services are named `*Service`; engines are named `*Engine`; connectors/writers/managers follow their integration role.

## Where to Add New Code

**New Feature:**
- Put source-specific ingestion in `src/hermes_arg_connector/` or a source/domain package, orchestration in the relevant `*service.py`, and API exposure in `src/api/routers/`.
- Add tests in `tests/test_<feature>.py`, using `tests/fixtures/` for deterministic external payloads.
- Add runtime wiring in `src/api/runtime.py` or `src/fabric/runtime.py`, not inside a router.

**New Component/Module:**
- Add a Python module under the owning bounded package: graph lifecycle in `src/ontology/`, semantic querying in `src/semantic/`, Fabric persistence in `src/fabric/` or `src/storage/`, and domain analysis in the matching `src/intelligence/<domain>/`.
- Add package exports only when the package's existing `__init__.py` boundary requires them; otherwise import the concrete module.

**Utilities:**
- Put shared persistence/filesystem behavior in `src/storage/` or `src/hermes_arg_connector/fs.py`; shared semantic query behavior belongs in `src/semantic/`.
- Avoid placing reusable domain logic in `scripts/`; reserve scripts for process/deployment wrappers.

**New API route:**
- Add a router module under `src/api/routers/`, define models/dependencies with the existing API boundary, then include the router in `src/api/app.py`.

**New intelligence domain:**
- Add a subpackage under `src/intelligence/` with a service/engine and context builder following adjacent domains; compose it from `src/fabric/runtime.py` and expose through `src/agents/operations/` or a router.

## Special Directories

**`.planning/`:**
- Purpose: GSD planning and codebase analysis artifacts.
- Generated: Yes, by workflow tooling.
- Committed: Intended for project planning; `ARCHITECTURE.md` and `STRUCTURE.md` are generated analysis outputs.

**`live-data/`:**
- Purpose: Local/OneLake-shaped runtime data, connection snapshots, generations, and state.
- Generated: Yes.
- Committed: Present in the repository workspace; treat contents as runtime data rather than source modules.

**`mock-fabric-lakehouse/`:**
- Purpose: Local mock of Fabric Files/Tables for offline integration and validation.
- Generated: Fixture/runtime data.
- Committed: Present as repository support data; do not add application logic here.

**`dist/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `graphify-out/`:**
- Purpose: Build, Python bytecode, test/lint caches, and graph analysis output.
- Generated: Yes.
- Committed: These are generated artifacts; source changes belong under `src/`, `tests/`, `web/`, or `infra/`.

---

*Structure analysis: 2026-08-24*
