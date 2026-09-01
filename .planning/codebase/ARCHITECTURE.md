<!-- refreshed: 2026-09-01 -->
# Architecture

**Analysis Date:** 2026-09-01

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     Web Frontend (Next.js)                          │
│  `web/src/app/*` (page drawers) + `web/src/components/*`            │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │ REST (envelope: data/evidence/scope)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Operations API (FastAPI)                         │
│  `src/api/app.py` (factory) + `src/api/routers/*` (per-domain)      │
│  auth/rbac/scope/errors/telemetry cross-cutting in `src/api/*`      │
└───────┬───────────────┬───────────────┬───────────────┬─────────────┘
        │               │               │               │
        ▼               ▼               ▼               ▼
┌───────────────┐ ┌────────────┐ ┌──────────────┐ ┌───────────────────┐
│ Semantic Layer│ │ Operations │ │  Onboarding/  │ │  Domain services   │
│ `src/semantic`│ │ Copilot    │ │  Ingestion    │ │ network/patching/  │
│ (ontology     │ │ `src/      │ │ `src/         │ │ situations/        │
│ snapshot read)│ │ operations`│ │ onboarding`   │ │ intelligence/*     │
└───────┬───────┘ └─────┬──────┘ └──────┬────────┘ └──────────┬─────────┘
        │               │               │                     │
        │        ┌──────┴───────┐       │                     │
        │        ▼              ▼       ▼                     ▼
        │   Foundry Agents   Azure MCP   Azure APIs (ARG/ARM/  Fabric
        │  (`foundry_agent.py`, (via APIM  Monitor/etc via     pipelines
        │   maf_orchestrator)   proxy)     `onboarding/azure_   `src/
        │                                  clients.py`)        fabric_pipelines`
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│         Fabric / OneLake curated store (durable graph state)        │
│  `src/storage/*` (writers) + `src/ontology/*` (publish/reconcile)   │
└─────────────────────────────────────────────────────────────────────┘
```

Standalone sidecar (separately deployed, not imported by the API):

```text
┌─────────────────────────────────────────────────────────────────┐
│   Azure MCP Server (Azure Container Apps, behind APIM)          │
│   `src/mcp_server/app.py` — per-subscription SPN/tool relay      │
└─────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| API app factory | Auth, routing, error translation, no business logic | `src/api/app.py` |
| Routers | One file per domain surface (inventory, network, patching, governance, copilot, twin, situations, etc.) | `src/api/routers/*.py` |
| Semantic Knowledge Layer | Reads governed ontology snapshot; assembles envelope responses; caching/index/hybrid query | `src/semantic/*.py` |
| Operations Copilot | Question-first specialist delegation, MAF vs deterministic orchestration, Foundry agent invocation | `src/operations/maf_orchestrator.py`, `src/operations/autonomous_investigation.py`, `src/operations/foundry_agent.py` |
| Specialist analyzers | Domain-specific reasoning invoked by the Copilot (network, vulnerability, incident, ownership, health, compliance, impact, recommendation) | `src/operations/*_analyzer.py`, `src/agents/operations/*.py` |
| Patching service | Patch/exposure domain logic and adapters | `src/operations/patching/*.py` |
| Onboarding/Ingestion | Connection registry, credential storage, discovery source adapters, scheduled sync into curated store | `src/onboarding/*.py` |
| Ontology engine | Entity/relationship building, confidence scoring, publish/reconcile/validate against Fabric | `src/ontology/*.py` |
| Fabric integration | Fabric workspace/lakehouse/data-agent management, sync, schema registry | `src/fabric/*.py` |
| Fabric pipelines | Per-domain batch pipelines (patch, vulnerability, governance, lifecycle, predeploy, topology, change) that build/publish curated tables | `src/fabric_pipelines/*.py` |
| Storage | Delta/Parquet/OneLake writers, partitioning, locking | `src/storage/*.py` |
| Situations | Durable "situation" (incident-like) materialization and store | `src/situations/*.py` |
| Network domain | Topology, flow, addressing, rule-engine, gap analysis for network specialist | `src/network/*.py` |
| Azure MCP Server (sidecar) | Centralized MCP tool execution with per-subscription SPN credential management, deployed standalone in ACA behind APIM | `src/mcp_server/app.py` |
| Web frontend | Next.js App Router pages per domain drawer, shared UI components, API client/hooks | `web/src/app/*`, `web/src/components/*`, `web/src/lib/api-client.ts` |
| Infra | Terraform (APIM, Container Apps, Foundry, Fabric, MCP server, alerting) + operational scripts | `infra/terraform/*.tf`, `infra/scripts/*.sh` |

## Pattern Overview

**Overall:** Layered service architecture with a governed read-side ("Semantic Knowledge Layer") separated from write-side ingestion/ontology pipelines, fronted by a FastAPI backend and a Next.js frontend. AI reasoning is delegated to Microsoft Foundry agents that call tools only through a governed MCP proxy (APIM) — the app never lets an LLM write directly to the graph.

**Key Characteristics:**
- **Source-of-record separation:** Azure ARG/Monitor/Entra/ServiceNow/DevOps remain authoritative; the app materializes only identity/assertion/evidence/confidence projections (see root `ARCHITECTURE.md` for the full principle set — still authoritative for domain intent).
- **Evidence-first envelope:** every API response following `EnvelopeModel` in `src/api/models.py` carries `data`, `evidence`, and `scope` — never raw model output as fact.
- **Dual-MCP routing:** operations-mcp (curated/Fabric-backed) vs azure-mcp (live/authoritative ARM/ARG) are explicitly routed per specialist tool in `src/operations/tools.py` / Foundry tool registry (Terraform `foundry_tool_registry`).
- **Deterministic-before-generative:** MAF orchestration mode is now default (`src/operations/maf_orchestrator.py`), with a documented rollback to deterministic page-anchored routing via `AIOPS_AGENT_ORCHESTRATION_MODE`.
- **Read-only discovery, governed writes:** discovery/onboarding identities (`src/onboarding/credentials.py`, `registry.py`) are separate from any mutation path; agent-triggered actions require explicit policy.

## Layers

**API/Presentation Layer:**
- Purpose: HTTP surface, auth, RBAC/scope enforcement, error translation, OpenAPI
- Location: `src/api/app.py`, `src/api/auth.py`, `src/api/rbac.py`, `src/api/scope.py`, `src/api/errors.py`, `src/api/dependencies.py`
- Contains: FastAPI app factory, middleware, dependency-injected `ApiContext`/`OperatePrincipal`
- Depends on: Semantic layer, Operations Copilot, Onboarding services (via routers)
- Used by: Next.js web frontend (`web/src/lib/api-client.ts`), MCP tool relay

**Router Layer:**
- Purpose: Domain-scoped endpoint definitions (one router per feature area)
- Location: `src/api/routers/*.py` (compliance, connections, context, copilot, governance, graph, inventory, mcp, multi_agent, network, operations, patching, planned, predeploy, resource_health, situations, twin, vulnerability)
- Contains: Route handlers only; delegates business logic to semantic/operations/onboarding modules
- Depends on: `src/semantic`, `src/operations`, `src/onboarding`, `src/network`, `src/situations`

**Semantic Knowledge Layer:**
- Purpose: Serve governed ontology snapshot reads, blend with live operational data
- Location: `src/semantic/*.py` (semantic_engine, hybrid_query, live_provider, live_operations, query_cache, semantic_indexes, semantic_validator)
- Depends on: `src/ontology` (published graph), `src/storage` (curated tables)
- Used by: routers, Operations Copilot (`foundry_agent.py` retrieval step)

**Operations/Agent Layer:**
- Purpose: Copilot orchestration, specialist agent invocation, Foundry integration
- Location: `src/operations/*.py`, `src/agents/operations/*.py`
- Contains: `maf_orchestrator.py` (routing decision), `autonomous_investigation.py` (page_kind → specialist mapping), `foundry_agent.py` (Foundry Responses API client), per-domain analyzers
- Depends on: Semantic layer (retrieval), Azure MCP/Fabric via tool calls (generation grounding only)
- Used by: `src/api/routers/copilot.py`, `src/api/routers/multi_agent.py`, `src/api/routers/operations.py`

**Ingestion/Onboarding Layer:**
- Purpose: Connection lifecycle, credential storage (Key Vault), scheduled discovery, curated-store writes
- Location: `src/onboarding/*.py`
- Depends on: `src/storage`, `src/ontology`, Azure SDK clients (`azure_clients.py`)
- Used by: `src/api/routers/connections.py`, `src/api/routers/inventory.py`, scheduled jobs

**Ontology Layer:**
- Purpose: Entity/relationship construction, confidence scoring, publish/reconcile against Fabric IQ Ontology
- Location: `src/ontology/*.py`
- Depends on: `src/storage` (OneLake writers), `src/fabric` (Fabric client/data-agent manager)
- Used by: `src/fabric_pipelines/*`, `src/semantic/*`

**Fabric/Pipeline Layer:**
- Purpose: Batch/scheduled pipelines building curated per-domain tables (patch, vulnerability, governance, lifecycle, predeploy, topology, change) and publishing to OneLake
- Location: `src/fabric_pipelines/*.py`, `src/fabric/*.py`
- Depends on: `src/storage`, `src/ontology`

**Storage Layer:**
- Purpose: Physical persistence (Delta/Parquet/OneLake), partitioning, locking
- Location: `src/storage/*.py`
- Used by: ontology, fabric_pipelines, onboarding

**Frontend Layer:**
- Purpose: Page drawers per operational domain, shared UI kit, API client
- Location: `web/src/app/*` (Next.js App Router pages), `web/src/components/*`, `web/src/lib/*`
- Depends on: Operations API via `web/src/lib/api-client.ts`

**MCP Sidecar (independently deployed):**
- Purpose: Centralized Azure tool execution with per-subscription managed-identity/SPN credential scoping, fronted by APIM
- Location: `src/mcp_server/app.py`
- Depends on: `src/onboarding/credentials.py`, `src/onboarding/registry.py`
- Deployed via: `infra/terraform/azure_mcp_server.tf`, `Dockerfile.azure-mcp`

## Data Flow

### Primary Request Path (page drawer → answer)

1. User opens a page drawer in the web app; page fetches domain data via `web/src/lib/api-client.ts` → Operations API router (`src/api/routers/*.py`)
2. Router resolves scope/RBAC via `src/api/scope.py` / `src/api/rbac.py`, then calls into `src/semantic/hybrid_query.py` or `live_provider.py` for envelope data
3. Semantic layer reads the curated Fabric/OneLake snapshot (`src/storage/*`) and, where configured, blends live Azure calls (`src/semantic/live_operations.py`)
4. Response returned as an `EnvelopeModel` (`data`/`evidence`/`scope`) — `src/api/models.py`

### Copilot / Specialist Investigation Flow

1. User asks a question in the Copilot drawer (`web/src/app/copilot/page.tsx`) → `src/api/routers/copilot.py` / `multi_agent.py`
2. `src/operations/maf_orchestrator.py` decides orchestration strategy (MAF vs deterministic) and selects specialist(s) via `src/operations/autonomous_investigation.py` (`page_specialists` mapping)
3. Selected specialist (`src/operations/*_analyzer.py`) retrieves grounding context from the Semantic layer, then invokes a Foundry agent (`src/operations/foundry_agent.py`) using the Responses API
4. Foundry agent calls governed tools through APIM's MCP proxy — routed to either `operations-mcp` (curated/Fabric) or `azure-mcp` (live ARM/ARG via the standalone `src/mcp_server/app.py` sidecar)
5. Narration is generated strictly from retrieved context; Copilot returns evidence-cited findings to the drawer

**State Management:**
- No client-side global state store observed beyond React context (`web/src/lib/scope-context.tsx` for subscription/scope selection) and per-hook fetch state (`web/src/hooks/useApi.ts`)
- Server-side state is the curated OneLake/Fabric snapshot plus onboarding connection registry (`src/onboarding/registry.py`); no in-process session state beyond request-scoped `ApiContext`

## Key Abstractions

**Envelope Response:**
- Purpose: Every API response wraps `data` with `evidence` (source/confidence/freshness) and `scope`
- Examples: `src/api/models.py` (`EnvelopeModel`, `ErrorModel`)
- Pattern: Enforced at router boundary; consumed uniformly by `web/src/lib/api-client.ts`

**Orchestration Decision:**
- Purpose: Immutable record of which specialists were selected and why, for a Copilot turn
- Examples: `src/operations/maf_orchestrator.py` (`OrchestrationDecision` dataclass)
- Pattern: `frozen=True` dataclass with `to_dict()` serialization

**Connection Registry:**
- Purpose: Tracks onboarded Azure subscriptions/connections and their credential references
- Examples: `src/onboarding/registry.py`, `src/onboarding/credentials.py` (Key Vault-backed secret provider)
- Pattern: Registry pattern with typed exceptions (`ConnectionNotFoundError`, `SecretNotFoundError`)

**Assertion / Evidence:**
- Purpose: Graph edges carry `confidence`, `source`, `createdTimestamp`, `lastObservedTimestamp` rather than being asserted as fact
- Examples: `src/ontology/confidence.py`, `src/semantic/semantic_assertions.py`, `src/ontology/relationship_builder.py`

**Foundry Prompt Agent:**
- Purpose: Two-stage answer pattern — deterministic retrieval, then constrained narration
- Examples: `src/operations/foundry_agent.py`, prompt templates in `src/operations/foundry_prompts/*.txt`
- Pattern: Client only invokes a pre-provisioned agent (created via `infra/scripts/create-foundry-agent.sh`); missing agent degrades to retrieval-only, never fails hard

## Entry Points

**Operations API:**
- Location: `src/api/app.py` (factory function building the FastAPI app)
- Triggers: HTTP requests from web frontend and any external API consumer
- Responsibilities: Auth, routing, error translation, OpenAPI schema generation

**Azure MCP Sidecar:**
- Location: `src/mcp_server/app.py`
- Triggers: MCP tool-call requests relayed from APIM's `/mcp-server` surface
- Responsibilities: Per-subscription credential resolution and Azure tool execution

**Web Frontend:**
- Location: `web/src/app/layout.tsx` (root layout), `web/src/app/page.tsx` (home)
- Triggers: Browser navigation via Next.js App Router
- Responsibilities: Render page drawers, call Operations API, handle auth (`web/src/components/AuthGate.tsx`)

**Onboarding CLI:**
- Location: `src/onboarding/cli.py`
- Triggers: Operator-invoked ingestion/onboarding commands
- Responsibilities: Manual/scheduled connection setup and discovery sync

**Terraform Deploy:**
- Location: `infra/terraform/main.tf`, invoked via `infra/scripts/deploy.sh`
- Triggers: Manual `terraform apply` / deploy script run
- Responsibilities: Provision APIM, Container Apps (API, MCP sidecar, web), Foundry agents, Fabric resources

## Architectural Constraints

- **Threading:** FastAPI async app; `src/operations/foundry_agent.py` uses both `asyncio` and a `threading` lock for agent-name resolution caching — mixed async/thread patterns exist in this module, be careful when modifying.
- **Global state:** Module-level caches/singletons observed in `src/operations/foundry_agent.py` (agent-id resolution cache) and `src/semantic/query_cache.py` / `semantic_cache.py` (query result caching) — these are process-local, so multiple container replicas do not share cache state.
- **Rate limits (known operational gotcha):** APIM enforces a rate-limit policy in front of the MCP proxy (currently 300 calls/60s per `.planning/STATE.md` history) and the MCP dispatcher previously had a lifetime-not-per-request call cap (`MAX_CALLS`) — any change to `src/mcp_server/app.py` or its Terraform policy must preserve per-request (not per-process) limiting.
- **Dual MCP routing is explicit, not automatic:** specialists must be wired to the correct MCP (`operations-mcp` vs `azure-mcp`) per tool; there is no automatic fallback logic beyond the documented `arm_execute_query` fallback for network.
- **Credential separation:** discovery identities (read-only, per-subscription via `azure_mcp` managed identity + role assignments) are distinct from any future write/publish identity — do not collapse these in code or Terraform.

## Anti-Patterns

### Treating model output as authoritative

**What happens:** A common mistake in earlier iterations was to let a Foundry/LLM response stand in for graph fact.
**Why it's wrong:** Violates the evidence-first principle; breaks the UI's "will not invent unsupported answers" guarantee.
**Do this instead:** Retrieval must come from the Semantic Knowledge Layer (`src/semantic/*`) and be passed into the Foundry agent as constrained context (`src/operations/foundry_agent.py` docstring pattern); absence of context means the Copilot says "not found," not a guess.

### Per-process singleton limits masquerading as per-request limits

**What happens:** `MAX_CALLS` in the MCP dispatcher was a lifetime, per-process cap rather than a per-caller quota, silently breaking containers permanently after 25 total tool calls.
**Why it's wrong:** Causes production outages that look unrelated to actual usage; masks real throttling needs behind an accidental global ceiling.
**Do this instead:** Enforce per-caller throttling at the APIM layer (`rate-limit-by-key`/`quota-by-key` policies in `infra/terraform/apim-policies`), keep any in-process constant as a coarse safety net only, and document it as such wherever redefined.

## Error Handling

**Strategy:** Centralized translation of internal exceptions into a stable `ErrorModel` envelope at the API boundary.

**Patterns:**
- Domain-specific exceptions (`SecretNotFoundError`, `SecretStorageError`, `OnboardingError`, `ConnectionNotFoundError`) raised deep in `src/onboarding/*` and `src/api/routers/*`
- `src/api/errors.py` (`ApiError`, `ErrorCode`, `translate()`) converts these into consistent HTTP responses
- FastAPI-level handlers in `src/api/app.py` catch `RequestValidationError` and unhandled exceptions, returning `JSONResponse` with the `ErrorModel` shape

## Cross-Cutting Concerns

**Logging:** Standard `logging` module per-file loggers (`logger = logging.getLogger(__name__)` pattern seen in `src/mcp_server/app.py`, `src/operations/foundry_agent.py`); no centralized structured-logging wrapper observed beyond `src/api/telemetry.py` (`Timer`).

**Validation:** Pydantic models throughout (`src/api/models.py`, `src/mcp_server/app.py` `MCPToolRequest`, `src/network/models.py`); blank-string optional-field stripping applied before validation per known fix in MCP tool argument handling.

**Authentication:** `src/api/auth.py` + `src/api/dependencies.py` (`OperatePrincipal`) for the Operations API; managed identity + APIM policies (`infra/terraform/apim-policies`, `mcp-inbound.xml`) for service-to-service MCP calls; Key Vault-backed secret provider (`src/onboarding/credentials.py`) for per-subscription discovery credentials.

---

*Architecture analysis: 2026-09-01*
