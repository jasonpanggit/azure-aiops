<!-- refreshed: 2026-08-24 -->
# Architecture

**Analysis Date:** 2026-08-24

## System Overview

```text
┌──────────────────────────────────────────────────────────────┐
│                         Entry Points                         │
│ `src/api/app.py`  `src/hermes_arg_connector/cli.py`          │
│ `__init__.py` / `hermes_plugin.py`  `scripts/`              │
└──────────────┬───────────────────────┬───────────────────────┘
               │                       │
               ▼                       ▼
┌─────────────────────────┐  ┌────────────────────────────────┐
│ API / Agent Surface      │  │ Ingestion & Onboarding          │
│ `src/api/routers/`       │  │ `src/hermes_arg_connector/`     │
│ `src/agents/operations/` │  │ `src/onboarding/`               │
└──────────────┬──────────┘  └───────────────┬────────────────┘
               │                            │
               ▼                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Semantic and Intelligence Services                            │
│ `src/semantic/` `src/intelligence/` `src/network/`             │
│ `src/operations/`                                              │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────┐
│ Persistence and Ontology Projection                            │
│ `src/fabric/` `src/storage/` `src/ontology/`                    │
│ OneLake/Delta tables and Fabric Ontology                        │
└──────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| API application | Builds FastAPI middleware, routers, envelopes, telemetry, and lifecycle hooks | `src/api/app.py` |
| API runtime | Wires authentication, providers, Fabric runtime, live sources, and cached snapshots | `src/api/runtime.py` |
| ARG connector | Discovers subscriptions, executes approved queries, normalizes records, and publishes immutable local/OneLake generations | `src/hermes_arg_connector/service.py` |
| Fabric sync | Maps source generations to bronze/silver/ontology datasets, validates quality, writes Delta, and refreshes ontology state | `src/fabric/sync_service.py` |
| Semantic layer | Provides bounded graph, hybrid, live, search, and evidence-backed query services | `src/semantic/semantic_engine.py`, `src/semantic/hybrid_query.py` |
| Intelligence modules | Analyze change, incident, lifecycle, patch, predictive, remediation, and vulnerability domains | `src/intelligence/` |
| Operations agent | Composes semantic and intelligence engines into read-oriented operational analysis | `src/agents/operations/operations_agent.py` |
| Ontology layer | Builds, validates, synchronizes, retires, and publishes graph entities and relationships | `src/ontology/` |

## Pattern Overview

**Overall:** Layered, service-oriented Python application with an ingestion/publishing plane and a read/query plane.

**Key Characteristics:**
- Application factories and runtime builders perform dependency composition; routers and CLI commands delegate to services.
- Azure and enterprise sources remain authoritative. The system materializes normalized identity, relationships, provenance, quality, and curated projections rather than raw operational stores.
- OneLake/Delta is the durable persistence boundary; Fabric Ontology is the semantic graph projection.
- Domain intelligence is split into independently constructible engines, commonly created from a `SemanticEngine` snapshot.
- Writes are guarded by locks, bounded by configuration, validated before commit, and exposed through immutable/versioned snapshots.

## Layers

**Entry and delivery layer:**
- Purpose: Expose HTTP, CLI, Hermes plugin, scheduled, and local-development interfaces.
- Location: `src/api/`, `src/hermes_arg_connector/cli.py`, `__init__.py`, `hermes_plugin.py`, `scripts/`
- Contains: FastAPI routers, CLI subcommands, plugin registration, startup wrappers.
- Depends on: Runtime builders and application services.
- Used by: Web clients, Hermes, operators, and deployment scripts.

**Source and onboarding layer:**
- Purpose: Discover Azure subscriptions, connect credentials, scope ingestion, and retrieve live source data.
- Location: `src/hermes_arg_connector/`, `src/onboarding/`, `src/semantic/live_provider.py`
- Contains: Azure MCP/CLI adapters, query catalog, connection registry, onboarding services, live resource providers.
- Depends on: Azure CLI/MCP, Key Vault abstractions, configured filesystem or OneLake roots.
- Used by: Ingestion services, API providers, and CLI activation flows.

**Normalization and ontology layer:**
- Purpose: Convert source-shaped records into canonical entity/relationship records and govern their lifecycle.
- Location: `src/hermes_arg_connector/normalize.py`, `src/hermes_arg_connector/ontology.py`, `src/ontology/`
- Contains: Entity/relationship builders, validators, graph synchronizer, ontology manager/publisher.
- Depends on: Source payloads and schema/validation rules.
- Used by: Dataset publication, Fabric mapping, and semantic query construction.

**Persistence and Fabric projection layer:**
- Purpose: Publish source generations and project governed datasets into Fabric-compatible storage.
- Location: `src/hermes_arg_connector/storage.py`, `src/fabric/`, `src/storage/`
- Contains: Atomic generation store, Delta writer, OneLake writer, dataset mapper, schema registry, quality checks, sync service.
- Depends on: Filesystem/OneLake, Fabric REST/authentication, Delta/Parquet tooling.
- Used by: Semantic snapshots, API runtime, Fabric Ontology, and replay operations.

**Semantic and domain intelligence layer:**
- Purpose: Answer bounded graph/context questions and produce domain-specific operational analysis.
- Location: `src/semantic/`, `src/intelligence/`, `src/network/`, `src/agents/operations/`
- Contains: Graph indexes, query services, live composition, domain engines, context builders, summaries, and agent orchestration.
- Depends on: Curated snapshots, live providers, and configured external enrichment connectors.
- Used by: API routers, CLI operations, and the Hermes read-only tool.

## Data Flow

### Primary Ingestion and Publication Path

1. `src/hermes_arg_connector/cli.py:160` dispatches the `sync` action to ingestion.
2. `src/hermes_arg_connector/service.py:48` acquires `RunLock`, then builds query specs with `QueryCatalog` (`src/hermes_arg_connector/service.py:70`).
3. `src/hermes_arg_connector/service.py:82` normalizes merged source payloads via `Normalizer`, including historical change merge before watermark advancement.
4. `src/hermes_arg_connector/service.py:86` publishes an immutable generation and `src/hermes_arg_connector/service.py:97` persists new state/watermarks.
5. `src/fabric/sync_service.py` maps and writes curated datasets through `src/storage/delta_writer.py` into OneLake/Delta and updates ontology publication state.
6. `src/semantic/semantic_engine.py` and domain engines consume the governed snapshot through runtime providers.

### API Request Path

1. `src/api/app.py:192` creates the API and includes router modules at `src/api/app.py:227` through `src/api/app.py:238`.
2. `src/api/runtime.py:1113` builds `ApiContext` providers, including semantic/live/hybrid paths, and is attached to app state in `src/api/app.py`.
3. Router handlers in `src/api/routers/` resolve providers through dependencies (`src/api/dependencies.py`) and enforce auth/RBAC (`src/api/auth.py`, `src/api/rbac.py`).
4. API responses are wrapped with evidence/scope envelopes (`src/api/evidence.py`, `src/api/models.py`), and failures are translated through `src/api/errors.py`.
5. Health/readiness probes enter via `src/api/app.py:317` and `src/api/app.py:345`, which rely on runtime provider state.

**State Management:**
- Connection, watermark, hash, and run state live under the configured Hermes root through `src/hermes_arg_connector/state.py`.
- Source generations are immutable and selected via `current`; Fabric sync state and quality reports are written as Delta/OneLake metadata.
- Runtime engines are cached/rebuilt by semantic version in `src/fabric/runtime.py`; API snapshot reads are TTL-cached in `src/api/runtime.py`.
- Background provider refresh uses a daemon thread started by `src/api/app.py`.

## Key Abstractions

**Runtime composition:**
- Purpose: Construct a coherent dependency graph for API, Fabric, and agent execution.
- Examples: `src/api/runtime.py`, `src/fabric/runtime.py`, `src/onboarding/runtime.py`
- Pattern: Explicit builder functions return configured service/runtime objects; optional providers are enabled from typed configuration.

**Canonical graph snapshot:**
- Purpose: Provide stable entities, relationships, views, health, and quality data across persistence and query layers.
- Examples: `src/ontology/ontology_sync.py`, `src/semantic/semantic_engine.py`
- Pattern: Validate and canonicalize IDs, preserve `valid_from`/lifecycle history, then expose bounded graph indexes and query methods.

**Source adapter:**
- Purpose: Isolate external command/API behavior from ingestion logic.
- Examples: `src/hermes_arg_connector/azure.py`, `src/hermes_arg_connector/source.py`, `src/semantic/live_provider.py`
- Pattern: Inject clients/source objects into services so fixtures and alternate providers can be used without changing orchestration.

**Dataset mapping and writer:**
- Purpose: Translate source-shaped snapshots to typed Fabric table names and durable storage.
- Examples: `src/fabric/dataset_mapper.py`, `src/storage/delta_writer.py`, `src/storage/onelake_writer.py`
- Pattern: Schema and partition policies are centralized; merge is used for histories and overwrite for reconciled projections.

## Entry Points

**FastAPI factory:**
- Location: `src/api/app.py:create_app`
- Triggers: `uvicorn --factory api.app:create_app` or embedding code.
- Responsibilities: Build/accept `ApiContext`, register routers, middleware, OpenAPI, background refresh, and lifecycle handling.

**Project CLI:**
- Location: `src/hermes_arg_connector/cli.py:register_cli` and `cli_command`
- Triggers: `hermes-arg` / `uv run hermes-arg`.
- Responsibilities: Dispatch ingestion, queries, scheduling, local seeding, Fabric, semantic, operations, activation, and subscription commands.

**Hermes plugin:**
- Location: `__init__.py`, `hermes_plugin.py`, `src/hermes_arg_connector/plugin.py`
- Triggers: Hermes directory-plugin discovery.
- Responsibilities: Add `src` to import resolution and register the read-only operational tool and CLI integration.

## Architectural Constraints

- **Threading:** Request handling is asynchronous through FastAPI; blocking provider refresh runs on a dedicated daemon thread, and bounded thread pools parallelize selected ingestion/Fabric writes.
- **Global state:** Runtime caches exist in `src/api/runtime.py` and `FabricRuntime` caches constructed engines; invalidate or key caches by semantic version/configured root.
- **Circular imports:** No confirmed circular dependency chain detected; preserve lazy imports in `src/fabric/runtime.py` and `src/api/runtime.py` when optional/domain services are loaded.
- **Consistency:** Never expose a partially written generation; publish complete owner-only generations before switching `current`.
- **Security boundary:** API authentication/authorization, trusted roots, connection scoping, and read-only agent behavior are enforced at the delivery/runtime boundaries.

## Anti-Patterns

### Business logic in delivery adapters

**What happens:** API and CLI are entry/delivery surfaces that delegate to runtime services rather than implementing domain workflows.
**Why it's wrong:** Duplicating workflows in `src/api/routers/` or `src/hermes_arg_connector/cli.py` would bypass shared locking, validation, evidence, and state behavior.
**Do this instead:** Add orchestration to a service under `src/`, wire it through `src/api/runtime.py` or `src/fabric/runtime.py`, and keep the adapter thin.

### Treating snapshots as mutable source systems

**What happens:** Curated projections and semantic snapshots are derived from Azure and enterprise systems.
**Why it's wrong:** They can become stale and cannot replace source detail or authoritative lifecycle state.
**Do this instead:** Use source adapters in `src/hermes_arg_connector/` or `src/semantic/live_operations.py` for current detail, and attach evidence/freshness to derived answers.

## Error Handling

**Strategy:** Typed/configuration errors are raised at boundaries, service failures are translated to stable API errors, and failed runs write explicit failed state without advancing success watermarks.

**Patterns:**
- API exceptions use `ApiError` and translation in `src/api/errors.py`; responses follow `EnvelopeModel`/`ErrorModel` from `src/api/models.py`.
- Ingestion and Fabric services validate before publication and use lock/rollback/state mechanisms in `src/hermes_arg_connector/locking.py`, `src/hermes_arg_connector/state.py`, and `src/fabric/sync_service.py`.
- External failures are isolated behind adapters and represented as unavailable/stale provider results where the API contract allows.

## Cross-Cutting Concerns

**Logging:** Module loggers and structured event names are used in `src/api/app.py`, `src/api/runtime.py`, and Fabric services.
**Validation:** Typed config, Pydantic API models, ontology validators, schema registry checks, and Fabric data-quality reports validate at boundaries.
**Authentication:** API modes are implemented in `src/api/auth.py`; RBAC and scope checks are in `src/api/rbac.py` and `src/api/scope.py`; Azure/Fabric credentials are built in `src/fabric/auth.py` and onboarding credential abstractions.

---

*Architecture analysis: 2026-08-24*
