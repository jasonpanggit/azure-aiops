# Phase 11: Cross-Page Operations Copilot Orchestration and Specialist Parity - Research

**Researched:** 2026-09-03  
**Domain:** Governed multi-agent orchestration, typed page context, evidence provenance, and evaluation  
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Hybrid orchestration, not unconstrained autonomy.** The Operations Copilot coordinator may produce a structured intent and delegation plan, but deterministic policy validates specialist IDs, tool grants, scope, budgets, dependencies, and mutation boundaries before execution. Existing keyword routing remains the safe fallback.
2. **One request/result contract.** Standalone chat, contextual drawer, investigation workspace, and multi-agent ledger converge on one orchestration service instead of maintaining separate planners.
3. **Typed page adapters.** Route components do not hand-build arbitrary snapshots. A registry defines page kinds, evidence mapping, selected entities, freshness, coverage, starter questions, and default specialist hints.
4. **Evidence snapshot v2.** Preserve stable Azure and non-Azure entity identities, evidence priority/deduplication, visible/total coverage, freshness, conflict, uncertainty, and citations.
5. **One specialist manifest.** Runtime definitions, prompts, Operations MCP grants, Azure MCP grants, Foundry deployment settings, API catalog, and UI metadata must be generated from or validated against one versioned contract.
6. **Specialist portfolio.** Retain the existing eight specialists; close their parity gaps; add Inventory & Data Health, Identity & Access, FinOps, and Resource Health & Observability specialists. Do not create one agent per page.
7. **Executive synthesis is conditional.** Invoke it for cross-domain or explicitly executive questions, using cited specialist outputs; do not spend its latency/cost on every single-domain turn.
8. **Cross-page continuity is bounded and authorized.** Preserve a principal-scoped investigation thread across navigation without widening scope or carrying stale evidence as current fact.
9. **Safe degradation.** Foundry, Fabric IQ, Azure AI Search, Azure MCP, and Gold Data Agent are optional enrichments. Missing providers yield explicit uncertainty and deterministic evidence/results, not fabricated answers or blank pages.
10. **No autonomous production mutation.** Copilot may prepare governed handoffs, but approval and execution remain existing server-side workflows.

### Implementation Priorities

1. End-to-end tracer: one currently unsupported evidence-heavy page uses the unified contract, adapter registry, coordinator plan, specialist execution, citations, and continuity.
2. Consolidate orchestration paths and add compatibility adapters for existing clients.
3. Introduce snapshot v2 and migrate current drawer pages.
4. Establish specialist manifest/parity validation and add the four missing domain specialists.
5. Expand page adapters, executive synthesis, continuity, telemetry, and evaluation gates.

### Page Coverage Policy

- **Must integrate:** evidence-heavy operational pages and detail/action pages: overview, network, compliance, exposure, CVE, Defender posture, KB, patch priorities, situations list/detail, changes, predeploy, inventory, connections/Fabric, governance, identity, FinOps, remediation, resource health, services list/detail, twin.
- **Dedicated surfaces:** `/copilot`, `/investigate`, and `/agents` must use the unified contract while keeping their distinct presentation.
- **Explicit exclusion allowed:** redirect-only `/vulnerabilities` and pure navigation/search surfaces when no stable evidence snapshot exists. Exclusions require a tested registry disposition.

### the agent's Discretion

No section present in CONTEXT.md.

### Deferred Ideas (OUT OF SCOPE)

No section present in CONTEXT.md.

[VERIFIED: .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-CONTEXT.md:7-32]
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| COP-01 | Operations Copilot uses one scope-enforced orchestration contract for standalone, contextual drawer, investigation workspace, and multi-agent requests, with model-planned specialist delegation validated against deterministic allowlists and a safe deterministic fallback. | Canonical request/result models, one service, compatibility routers, candidate-plan validator, and fallback sequencing below. |
| COP-02 | Every operator-facing page with actionable domain evidence exposes a consistent contextual Copilot entry point through a typed page-adapter registry that binds page kind, filters, selected entities, starter questions, freshness, pagination coverage, and evidence. | Typed registry, route disposition gate, `/inventory` tracer, and page migration matrix below. |
| COP-03 | Specialist definitions, prompts, tool grants, page mappings, deployment metadata, and UI catalog are generated or validated from one versioned contract; existing agent gaps are closed and inventory/data-health, identity, FinOps, and resource-health domains have bounded specialists. | Versioned JSON manifest, exact-set parity validation, Terraform projection, and four-specialist rollout below. |
| COP-04 | Context snapshot v2 deduplicates and prioritizes evidence, preserves canonical Azure and non-Azure entity identities, represents visible-versus-total result coverage, propagates freshness and uncertainty, and fails closed when evidence is insufficient. | Snapshot v2 identity, dedup, priority, conflict, coverage, freshness, and citation algorithms below. |
| COP-05 | Operations Copilot preserves an authorized investigation thread across page transitions, invokes executive synthesis over cited specialist outputs, exposes delegation/evidence/latency telemetry, and passes representative per-page and cross-domain evaluation cases. | Principal-bound durable thread, deterministic synthesis predicate, low-cardinality telemetry, and Nyquist/evaluation map below. |

Requirements quoted verbatim from the source of truth. [VERIFIED: .planning/REQUIREMENTS.md:81-87]
</phase_requirements>

## Project Constraints (from copilot-instructions.md)

- Load the matching GSD skill for explicit GSD commands and prefer matching custom agents when a workflow delegates.
- Do not apply GSD workflows unless explicitly requested.
- After a GSD deliverable, offer the next workflow step; this research run is intentionally research-only and must not create plans.

[VERIFIED: .github/copilot-instructions.md:2-8]

## Summary

Phase 11 should be implemented as a compatibility migration around one new Python orchestration service, not as a rewrite of every UI. Today the three public paths invoke three different loops: `/copilot/investigate` calls the heuristic `run_investigation`, `/copilot/investigate-context` calls `run_context_investigation`, and `/agents/investigations` calls `run_autonomous_investigation`. The contextual path additionally maintains its own page-to-specialist table and only uses keyword selection under its “MAF” adapter. [VERIFIED: src/api/routers/copilot.py:235-352] [VERIFIED: src/api/routers/multi_agent.py:53-73] [VERIFIED: src/operations/autonomous_investigation.py:621-704,707-986] [VERIFIED: src/operations/maf_orchestrator.py:60-109]

The safest tracer is `/inventory`: it is a required evidence-heavy route, currently has no drawer integration, and the governed Python registry already exposes the exact tool `"inventory_resources"` while Operations MCP does not expose it and no Inventory & Data Health specialist exists. This tracer therefore proves the canonical contract, model-candidate/deterministic-policy split, manifest parity, page adapter, snapshot v2, citations, and continuity without first inventing a new provider. [VERIFIED: .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-REVIEW.md:18-37] The current tool is quoted verbatim as `"inventory_resources"` with handler `_tool_inventory_resources`. [VERIFIED: src/operations/tools.py:1024-1032]

Do not add another orchestration dependency. The repository already resolves `agent-framework` 1.15.0, Pydantic 2.13.4, FastAPI 0.138.0, OpenTelemetry API 1.43.0, Next.js 14.2.35, React 18.3.1, TypeScript 5.9.3, Vitest 2.1.9, and Zod 4.4.3. The focused Copilot backend suite passed 65 tests, the drawer suite passed 4 tests, and `terraform validate` succeeded during this research session. [VERIFIED: uv.lock:63-73] [VERIFIED: pyproject.toml:20-27] [VERIFIED: web/package.json:16-41] [VERIFIED: local test execution 2026-09-03]

**Primary recommendation:** Build a canonical v2 orchestration service and manifest first, prove it end-to-end on `/inventory`, then convert all legacy endpoints and routes through adapters before removing any old planner.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Candidate intent/delegation planning | API / Backend | External Foundry | The model proposes a typed plan; server policy remains authoritative. |
| Scope, grants, budgets, dependencies, mutation policy | API / Backend | — | Existing `ReadScope` and `call_tool` enforcement already live here. |
| Page context extraction | Browser / Client | API / Backend | The page reports what it rendered; the API treats it as untrusted and revalidates it. |
| Specialist manifest | API / Backend source artifact | Infrastructure / UI | Python loads it, Terraform projects it, and the API catalog supplies UI metadata. |
| Evidence identity, dedup, conflict, citations | API / Backend | Browser / Client | Client adapters create typed observations; server canonicalization and authorization decide what is usable. |
| Cross-page thread UI continuity | Browser / Client | API / Storage | A root client provider carries only an opaque thread ID; server storage binds content to principal and scope. |
| Investigation/ledger persistence | Database / Storage | API / Backend | Existing OneLake document storage is already wired at API startup. |
| Executive synthesis | API / Backend | External Foundry | A deterministic predicate admits a cited aggregation call only after specialist results exist. |
| Telemetry and evaluations | API / Backend | Infrastructure | Runtime records low-cardinality metrics; offline/live harnesses enforce release gates. |

The current authorization boundary obtains `CurrentPrincipal`, computes `ReadScope`, and narrows requested scope through `effective_scope`. [VERIFIED: src/api/dependencies.py:210-277] The current scope vocabulary is quoted verbatim as `"business_service"`, `"application"`, `"environment"`, `"subscription"`, `"subscription_connection"`, `"owner"`, `"support_team"`, `"region"`, and `"criticality"`. [VERIFIED: src/api/scope.py:15-31]

## Standard Stack

### Core

| Library | Version in project | Published | Purpose | Why Standard Here |
|---|---:|---|---|---|
| `agent-framework` | 1.15.0 | 2026-08-21 | Existing Foundry agent adapter and optional structured planning | Already installed and selected by `AIOPS_AGENT_ORCHESTRATION_MODE`; no second agent framework is needed. |
| `pydantic` | 2.13.4 | 2026-05-06 | Strict request, snapshot, manifest, plan, and result validation | Existing `SnapshotModel` already uses `ConfigDict(extra="forbid")`. |
| `fastapi` | 0.138.0 | 2026-06-20 | Compatibility routes, canonical endpoint, dependency-injected auth/scope | Existing API boundary and error/envelope conventions. |
| `opentelemetry-api` | 1.43.0 | 2026-06-24 | Counters and histograms for orchestration behavior | Existing `ApiTelemetry` records request counts, duration, and denials without payloads. |
| Next.js / React / TypeScript | 14.2.35 / 18.3.1 / 5.9.3 | 2025-12-11 / 2024-04-26 / 2025-09-30 | Typed page adapters, root continuity provider, dedicated surfaces | Existing web application stack. |

Exact dependency constraints are quoted as `"agent-framework>=1.0,<2"`, `"fastapi>=0.115,<1"`, and `"opentelemetry-api>=1.29,<2"`. [VERIFIED: pyproject.toml:6-27] Exact web declarations are quoted as `"next": "14.2.35"`, `"react": "^18"`, `"typescript": "^5"`, `"vitest": "^2.1.9"`, and `"zod": "^4.4.3"`. [VERIFIED: web/package.json:16-41] Registry dates were checked against PyPI and npm during this session. [VERIFIED: PyPI JSON API and npm registry]

### Supporting

| Component | Version/contract | Purpose | When to Use |
|---|---|---|---|
| Existing `OneLakeDocumentStore` | Project code | Durable principal-scoped threads and ledgers | Production/distributed continuity; memory remains a local fallback. |
| Existing governed `TOOL_REGISTRY` / `call_tool` | Project code | Scope-filtered deterministic execution | Every specialist call, regardless of planner source. |
| Existing Vitest + Testing Library | Vitest 2.1.9 | Adapter, provider, drawer, and route-disposition tests | Every frontend migration wave. |
| Existing pytest | pytest 9.x constraint | Contract, policy, parity, persistence, API, and evaluation tests | Every backend task. |

The governed tool result statuses are quoted verbatim as `"ok"`, `"empty"`, `"unavailable"`, and `"denied"`; preserve their distinct meanings. [VERIFIED: src/operations/tools.py:40-46]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| Extend existing service + MAF adapter | Native Magentic/group-chat workflow for every turn | Adds state and nondeterminism before the deterministic policy contract is proven; conflicts with the locked bounded-hybrid posture. |
| Existing OneLake document store | Add Cosmos checkpoint package | Better native Agent Framework checkpointing, but adds package and infrastructure work when this repository already has durable principal-scoped document patterns. |
| API-served UI catalog | Duplicate manifest into a web build artifact | Faster static rendering, but reintroduces the exact cross-layer drift COP-03 forbids. |

Official Agent Framework documentation lists sequential, concurrent, handoff, group-chat, and Magentic orchestration and supports human-in-the-loop workflows and checkpoints. [CITED: https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/] [CITED: https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints]

**Installation:** No new package installation is recommended.

## Package Legitimacy Audit

Not applicable: the prescribed implementation uses already-declared and locked dependencies. If planning introduces any new package, the planner must run the package-legitimacy gate before installation.

## Architecture Patterns

### System Architecture Diagram

```text
Page / dedicated surface
  -> typed page adapter (or explicit no-snapshot disposition)
  -> canonical InvestigationRequestV2 + opaque thread_id
  -> FastAPI auth + effective ReadScope
  -> snapshot v1 compatibility converter (only for legacy callers)
  -> snapshot v2 validation / canonicalization / evidence retention
  -> coordinator candidate plan
       -> model JSON candidate available? --no--> deterministic keyword fallback
       -> yes
  -> deterministic policy validator
       -> invalid / unavailable? ----------> deterministic keyword fallback
       -> valid
  -> bounded specialist DAG
       -> governed local call_tool
       -> optional Foundry / Operations MCP / Azure MCP / Fabric / Search enrichments
       -> explicit empty / unavailable / denied / partial states
  -> cited specialist findings + reconciliation
       -> cross-domain or executive intent? --yes--> cited executive synthesis
       -> no ---------------------------------------> direct domain result
  -> canonical InvestigationResultV2
  -> principal-scoped thread + optional ledger persistence
  -> compatibility response projection
  -> UI evidence/citation rendering + low-cardinality telemetry
```

### Recommended Project Structure

```text
src/operations/
├── orchestration_contract.py      # canonical request/result and candidate-plan models
├── orchestration_policy.py        # deterministic validation and reason codes
├── orchestration_service.py       # the only planning/execution/reconciliation loop
├── specialist_manifest.py         # strict loader and projections
├── specialists.v1.json            # single versioned specialist source
├── investigation_thread_store.py  # principal/scope-bound durable continuity
├── page_context.py                # snapshot v1 converter plus snapshot v2 models
├── maf_orchestrator.py            # deterministic fallback retained
└── autonomous_investigation.py    # ledger projection, not a second planner
web/src/lib/copilot/
├── page-adapters.ts               # typed adapter/disposition registry
├── thread-context.tsx             # opaque cross-navigation thread continuity
└── orchestration.ts               # canonical web request/result helpers
tests/
├── test_orchestration_contract.py
├── test_orchestration_policy.py
├── test_orchestration_parity.py
├── test_investigation_thread_store.py
└── test_page_context_v2.py
web/src/lib/copilot/
├── page-adapters.test.ts
└── thread-context.test.tsx
```

These are recommended new paths, not current repository facts. [ASSUMED]

### Pattern 1: Model Proposes, Policy Disposes

The coordinator returns only a typed candidate: structured intent, specialist IDs, tool calls, dependency edges, and whether executive synthesis is requested. It does not return hidden reasoning. Deterministic code validates exact manifest membership, exact specialist grants, tool argument schema, scope, per-stage budgets, acyclic dependencies, evidence ownership, and read-only mutation policy. Any planner timeout, parse failure, unknown ID, illegal edge, or optional-provider outage produces a reason code and runs the existing keyword fallback through the same validator. The model never authorizes execution. [VERIFIED: src/operations/mcp_server.py:55-130] [VERIFIED: src/operations/tools.py:1061-1084]

Agent Framework structured outputs accept a Pydantic model or JSON schema through `response_format` when the underlying client supports it; strict local validation is still required. [CITED: https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs]

### Pattern 2: Thin Compatibility Routers

Keep all three endpoints until web callers migrate, but make each do only: authenticate, translate legacy request to `InvestigationRequestV2`, call `OperationsCopilotOrchestrator.run`, and project the canonical result if the old response shape is still required. Add a canonical route for new clients or make `/copilot/investigate` accept the versioned union; do not leave endpoint-specific selection logic. Existing unknown-tool validation and principal-scoped not-found semantics remain at the router boundary. [VERIFIED: src/api/routers/copilot.py:235-363] [VERIFIED: src/api/routers/multi_agent.py:58-105]

### Pattern 3: Single Manifest, Many Projections

Use one committed JSON manifest loaded by strict Pydantic models. Terraform must `jsondecode(file(...))` that same artifact to derive Foundry agents, prompts, Operations MCP and Azure MCP grants, deployment names/versions, and Container Apps metadata. Python derives runtime definitions, dependency rules, output validators, and API catalog. The UI renders the API catalog and never carries a second specialist list. Add exact-set tests for every projection and a wheel-content test for the JSON file. [VERIFIED: infra/terraform/foundry.tf:11-55,72-111,182-221,272-290] [VERIFIED: src/operations/autonomous_investigation.py:47-89] [VERIFIED: src/operations/foundry_agent.py:815-835]

Current specialist IDs are quoted verbatim:

> `"network", "vulnerability", "patch", "incident", "change", "governance", "remediation", "executive_summary"`

[VERIFIED: src/operations/foundry_agent.py:48-57]

The manifest must add the locked portfolio labels “Inventory & Data Health”, “Identity & Access”, “FinOps”, and “Resource Health & Observability” while keeping domain specialists independent of route count. [VERIFIED: .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-CONTEXT.md:13-16]

### Pattern 4: Typed Page Adapter and Disposition Registry

Each Next.js route has exactly one registry disposition: `integrated`, `dedicated`, `redirect`, or `excluded-with-reason` (proposed values). An integrated adapter is a pure function over already-loaded page data and API envelopes; it emits page identity, typed entities, filters, coverage, freshness, evidence, starter hints, and default specialist hints. Route components render a shared contextual entry component and never construct evidence IDs or page-kind strings directly. [ASSUMED]

The current browser contract is limited to the exact page kinds `"network" | "vulnerability" | "patch" | "incident" | "governance" | "remediation" | "resource"` and snapshot version `"1"`. [VERIFIED: web/src/lib/types.ts:2451-2462] The registry must replace that closed route-local union with v2 page kinds derived from the coverage policy.

### Pattern 5: Snapshot v2 Canonical Evidence Pipeline

Apply this deterministic order:

1. Validate strict shape and byte/list bounds before processing.
2. Canonicalize each `EntityRef` as either an Azure resource identity or a typed domain identity with namespace, kind, and stable source key.
3. Re-authorize Azure entities from canonical ARM IDs and authorize domain entities through server-side resolver metadata; never trust browser attributes.
4. Compute stable evidence identity from source system, source record key, canonical entity key, and claim type—not visible-row index or freshness timestamp.
5. Merge exact duplicates, preserving all source citations and the strongest freshness/quality warning.
6. Represent conflicting values for the same entity/claim as a conflict set; never choose silently.
7. Rank retained evidence deterministically: selected entity, direct/actionable evidence, severity, freshness, confidence/quality, then stable ID.
8. Record result coverage with visible count, total count, offset/limit, filter/sort fingerprint, and completeness state.
9. Reject any narrated material claim whose citation is not in the retained authorized evidence set.
10. Return `insufficient_evidence` when no usable evidence remains, all relevant providers are unavailable/denied, or a full-estate conclusion is requested from partial visible coverage.

The existing v1 limits are quoted as `MAX_SNAPSHOT_BYTES = 128 * 1024`, `MAX_SELECTED_RESOURCES = 50`, `MAX_EVIDENCE_ROWS = 200`, and `MAX_EVIDENCE_ROW_BYTES = 8 * 1024`; retain or deliberately revise them in one policy module, not in browser code. [VERIFIED: src/operations/page_context.py:18-21] Existing network findings already downgrade stale data, merge duplicate citation IDs, and keep actionability deterministic. [VERIFIED: src/operations/page_context.py:160-233]

### Pattern 6: Principal-Bound Continuity, Evidence Aging

Place a client provider under `ScopeProvider` in the root layout. It keeps only the opaque server-issued thread ID in browser session storage and survives navigation. The server thread store uses one document per thread, records owner principal, effective-scope fingerprint, revision, bounded turns, snapshot hash/version, evidence references, observation times, and current/historical classification. On every turn, reload, verify identity and principal, intersect with current effective scope, and mark prior evidence historical until rechecked. Never use a client-supplied principal or `authorized` boolean as authority. [VERIFIED: web/src/app/layout.tsx:12-23] [VERIFIED: src/operations/investigation.py:383-454] [VERIFIED: src/operations/autonomous_investigation.py:1014-1154]

The existing conversation defaults are quoted as `MAX_TURNS_PER_SESSION = 12`, `MAX_SESSIONS = 2_000`, and `SESSION_TTL_SECONDS = 60 * 60`. [VERIFIED: src/operations/investigation.py:52-61] Use them as initial compatibility defaults, but make product retention configurable.

### Pattern 7: Conditional, Citation-Closed Executive Synthesis

Admit executive synthesis only when the validated intent is explicitly executive or when at least two distinct domain specialists produced material cited findings. Its input is normalized specialist findings plus retained evidence, not prompts, tool dumps, or hidden reasoning. Validate every executive claim’s evidence references against the union of cited specialist outputs; on failure, return direct specialist results and a synthesis warning. The current autonomous flow invokes executive synthesis unconditionally, so it must be converted to a result projection. [VERIFIED: src/operations/autonomous_investigation.py:662-704]

### Anti-Patterns to Avoid

- **Three planners behind three routes:** compatibility endpoints must call one service.
- **Calling the current keyword matcher “LLM planning”:** `select_specialists_for_turn` iterates catalog keywords and is only the fallback. [VERIFIED: src/operations/maf_orchestrator.py:76-108]
- **Starter tool bypass:** today contextual requests ignore starter `tool` and `toolArguments`; v2 starter values are policy-validated hints. [VERIFIED: web/src/components/ui/CopilotDrawer.tsx:118-166]
- **Browser authorization:** browser snapshots are observations, never authorization.
- **Index-based evidence IDs:** page order changes break citations and dedup.
- **Subset parity checks:** grants must match exactly and forbidden mutation tools must remain absent.
- **Unconditional executive calls:** wastes budget and obscures domain answers.
- **Thread ID as authorization:** possession of an ID does not establish ownership.
- **Historical evidence presented as fresh:** navigation continuity is not evidence refresh.
- **Question, principal, resource, or thread IDs as metric labels:** creates secret/high-cardinality telemetry.
- **Bulk rewrite of old ledgers:** versioned read compatibility is safer than mutating audit history.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Request/plan/manifest validation | Ad hoc dictionary checks | Existing Pydantic v2 strict models and JSON Schema | Predictable errors, bounds, schema generation, and testability. |
| Tool authorization | Prompt-only restrictions | Existing `TOOL_REGISTRY`, MCP argument models, `ReadScope`, and exact manifest grants | Models cannot enforce authorization. |
| Agent framework | A second custom workflow engine | Existing Agent Framework adapter plus plain deterministic service | The project already resolves and tests it. |
| Durable thread storage | Browser transcript or unbounded process dictionary | Existing OneLake document-store pattern with bounded read-through cache | Principal checks and replica durability already have an analog. |
| Telemetry | Custom metrics transport | Existing OpenTelemetry API | Existing privacy and low-cardinality conventions. |
| UI agent catalog | Hard-coded cards | API projection of the manifest | Prevents silent drift. |
| Evidence citations | Free-form model footnotes | Stable retained evidence IDs and strict reference validation | Prevents fabricated or truncated citations. |
| Crypto/authentication | Custom tokens or encryption | Existing Entra/JWT authentication and server-generated opaque IDs | Avoids new credential and key-management risk. |

**Key insight:** the hard part is not selecting agents; it is ensuring that every model-selected action, carried observation, citation, and persisted turn remains inside the caller’s current authorization and the versioned manifest.

## Runtime State Inventory

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | Durable investigation ledgers use the exact path template `"ledgers/{ledger_id}.json"` and can contain snapshot version `"1"`; standalone conversation state is in-process only. [VERIFIED: src/operations/autonomous_investigation.py:1026-1036] [VERIFIED: src/operations/investigation.py:378-464] | Add record contract versions and legacy readers. Do not rewrite old ledgers. Create a separate principal-scoped thread document namespace and migrate only active v1 conversations opportunistically. |
| Live service config | Foundry prompt agents and their versions live on the Foundry data plane; the deployment script creates a new version when an agent already exists. [VERIFIED: infra/scripts/create-foundry-agent.sh:1-8,104-136] | Deploy new manifest-derived versions and verify live MCP `tools/list` grants after Terraform apply. Source edits alone do not update live agents. |
| OS-registered state | None specific to Copilot/Foundry/specialist naming found in `infra/`, `scripts/`, `src/`, or `web/`; targeted search found no launchd/systemd/pm2/task-scheduler registrations. [VERIFIED: targeted repository audit 2026-09-03] | None. Existing ingestion scheduling is unrelated to this contract migration. |
| Secrets/env vars | Container Apps currently injects eight pairs of `FOUNDRY_<SPECIALIST>_AGENT_NAME`/`VERSION`, `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_SPECIALISTS_JSON`, and `AIOPS_AGENT_ORCHESTRATION_MODE`. [VERIFIED: infra/terraform/container_apps.tf:213-347] | Keep legacy env compatibility for one rollout, add four specialist projections, and never place credentials in the manifest. Local research shell has no Foundry/Gold agent env configured. |
| Build artifacts / installed packages | `.venv`, `dist/`, Python caches, `web/.next`, and container images can retain old manifest/code. [VERIFIED: build-artifact audit 2026-09-03] | Rebuild wheel/web/container artifacts, validate packaged manifest inclusion, deploy a new revision, and run parity/live evaluation against that revision. |

## Migration Sequencing

1. **Wave 0 — Characterization and contracts:** add canonical models, manifest schema, exact parity tests, route-disposition test, and snapshot v1/v2 fixtures before moving execution.
2. **Tracer — `/inventory`:** add Inventory & Data Health manifest entry, expose its existing governed tool through Operations MCP, implement the inventory page adapter, submit snapshot v2, persist a principal thread, and render cited fallback behavior.
3. **Canonical service:** implement candidate planning, deterministic policy, fallback, specialist DAG, reconciliation, conditional synthesis, and one result type.
4. **Compatibility convergence:** translate `/copilot/investigate`, `/copilot/investigate-context`, and `/agents/investigations` into the service; retain response projection and ledger actions.
5. **Snapshot migration:** convert the six currently integrated drawer routes first, then reject new v1 clients only after route/API compatibility tests prove parity.
6. **Manifest parity rollout:** close patch/change/governance/tool-registry mismatches, add the remaining three specialists, generate Terraform/Foundry/API/UI projections, and deploy new agent versions.
7. **Page expansion:** integrate all locked eligible routes; mark `/vulnerabilities` as redirect and `/search` as excluded unless a stable evidence adapter is defined.
8. **Continuity/synthesis/telemetry:** move drawer state to the root provider, add durable thread endpoints, enable conditional executive synthesis, and instrument stage-level outcomes.
9. **Evaluation and live gate:** run deterministic suites, Terraform validation, route matrix, provider-failure cases, cross-page sequences, and live baseline comparison before deleting old planner code.

This ordering follows the locked tracer-first priorities. [VERIFIED: .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-CONTEXT.md:20-26]

## Common Pitfalls

### Pitfall 1: Policy Validation After Tool Execution
**What goes wrong:** An invalid candidate has already caused data access or cost before it is rejected.  
**How to avoid:** Fully parse and validate the whole candidate plan—including DAG, grants, arguments, scope, and budgets—before the first call.  
**Warning signs:** Audit shows denied tool calls produced by model plans rather than pre-execution policy decisions.

### Pitfall 2: “Unavailable” Collapses to “Empty”
**What goes wrong:** Provider failure is narrated as a true negative.  
**How to avoid:** Preserve exact tool states and make insufficiency deterministic. Existing tests already require a failed provider to return `"unavailable"`, never `"empty"`. [VERIFIED: tests/test_copilot_evaluation.py:310-328]  
**Warning signs:** Empty findings paired with provider exceptions or missing freshness.

### Pitfall 3: Manifest Exists but Projections Still Drift
**What goes wrong:** Engineers continue editing Terraform or Python lists directly.  
**How to avoid:** Remove or generate parallel lists and compare exact sets in CI. Current patch runtime grants are `"cve_exposure"` and `"remediation_plans"` while Terraform patch receives only generic context. [VERIFIED: src/operations/autonomous_investigation.py:69-78] [VERIFIED: infra/terraform/foundry.tf:25-55]  
**Warning signs:** New manifest specialist is absent from API catalog, env, UI, or live MCP grants.

### Pitfall 4: Stable ID Includes Row Index or Timestamp
**What goes wrong:** Reordering or refresh changes citations and defeats dedup.  
**How to avoid:** Use source record keys and canonical entity/claim identity; carry observation time separately. Current browser code uses exact index-based forms `` `${section}:visible:${index}` `` and `` `${section}:${item.source_table || "source"}:${index}` ``. [VERIFIED: web/src/lib/services.ts:447-460]

### Pitfall 5: Continuity Widens Scope
**What goes wrong:** A user narrows subscription scope but an old turn continues to ground answers with broader evidence.  
**How to avoid:** Store original scope per evidence item, intersect on every turn, and drop or mark unauthorized references.  
**Warning signs:** Thread results contain entities that the same request cannot retrieve directly.

### Pitfall 6: Cross-Domain Means “Always Executive”
**What goes wrong:** Every turn incurs extra model latency and citations become less direct.  
**How to avoid:** Use a deterministic predicate after specialist execution and expose the predicate outcome in telemetry.  
**Warning signs:** Single-domain route tests show two LLM calls.

### Pitfall 7: Route Coverage Test Scans Only Integrated Imports
**What goes wrong:** New pages silently ship without a disposition.  
**How to avoid:** Compare the route-file inventory to registry entries and fail for zero or multiple dispositions. The review records 28 route pages and only six current snapshot integrations. [VERIFIED: .planning/phases/11-cross-page-operations-copilot-orchestration-and-specialist-p/11-REVIEW.md:3-24]

### Pitfall 8: Telemetry Becomes a Secret Sink
**What goes wrong:** Questions, tool arguments, principal names, or resource IDs become metric dimensions.  
**How to avoid:** Keep dimensions to controlled enums/manifest IDs and reserve protected audit logs for principal attribution. Existing telemetry intentionally excludes payloads, headers, principals, and scope values. [VERIFIED: src/api/telemetry.py:1-47]

## Code Examples

The following are prescriptive design proposals rather than existing repository values. [ASSUMED]

### Candidate Plan Validation Boundary

```python
class CandidatePlan(StrictModel):
    contract_version: Literal["2"]
    intent_kind: IntentKind
    specialist_ids: list[SpecialistId]
    tool_calls: list[CandidateToolCall]
    dependency_edges: list[DependencyEdge]
    executive_requested: bool = False

def choose_plan(request, candidate, manifest, policy):
    try:
        return policy.validate(candidate, request=request, manifest=manifest)
    except (ValidationError, PolicyDenied, PlannerUnavailable):
        fallback = deterministic_fallback(request, manifest=manifest)
        return policy.validate(fallback, request=request, manifest=manifest)
```

Pydantic recommends discriminated unions for more predictable union validation and supports `extra="forbid"` for rejecting unknown data. [CITED: https://docs.pydantic.dev/latest/concepts/unions/] [CITED: https://docs.pydantic.dev/latest/concepts/models/]

### Typed Page Adapter Registry

```typescript
type RouteDisposition =
  | { kind: "integrated"; adapter: PageAdapter }
  | { kind: "dedicated"; surface: DedicatedSurface }
  | { kind: "redirect"; target: string }
  | { kind: "excluded"; reason: string };

export const pageAdapters = {
  "/inventory": {
    kind: "integrated",
    adapter: inventoryAdapter,
  },
} satisfies Record<KnownRoute, RouteDisposition>;
```

Keep adapters serializable and client-safe; Next.js 14 assigns interactive state/effects/browser APIs to Client Components and sensitive backend access to Server Components. [CITED: https://nextjs.org/docs/14/app/building-your-application/rendering/composition-patterns]

### Citation-Closed Executive Predicate

```python
def should_synthesize(intent, cited_findings) -> bool:
    domains = {finding.specialist_id for finding in cited_findings if finding.evidence_refs}
    return intent.explicitly_executive or len(domains) >= 2

def validate_synthesis(output, retained_evidence_ids):
    for claim in output.claims:
        if not claim.evidence_refs or not set(claim.evidence_refs) <= retained_evidence_ids:
            raise CitationPolicyDenied()
```

## State of the Art

| Old/Current Approach | Prescribed Phase 11 Approach | Evidence / Impact |
|---|---|---|
| Keyword-only “MAF” selection | Model-generated typed candidate plus deterministic validation and keyword fallback | Current selector scans `keywords`; model planning becomes real without granting autonomy. [VERIFIED: src/operations/maf_orchestrator.py:60-109] |
| Three endpoint-specific loops | One canonical service with compatibility routers | Prevents tool, specialist, freshness, and persistence drift. |
| Route-local snapshot builders | Typed adapter/disposition registry | Makes every eligible route testable. |
| Eight parallel specialist representations | One committed manifest and generated/validated projections | Exact parity replaces regex/subset checks. |
| Snapshot v1 with ARM-only selected resources and 200-row truncation | Snapshot v2 with typed identities, coverage, priority, dedup, conflict, and citation closure | Avoids treating the visible subset as the estate. |
| Local drawer state and in-memory standalone sessions | Root client provider plus durable principal/scope-bound thread | Survives navigation and replicas without widening authorization. |
| Unconditional executive run in autonomous flow | Deterministic conditional aggregation | Reduces unnecessary cost/latency and keeps single-domain answers direct. |

The current live baseline is quoted verbatim: `"routing_rate": 0.87`, `"groundedness_mean": 0.283`, `"tool_correctness_mean": 1.0`, and `"latency_ms_median": 1828.2`. [VERIFIED: .planning/eval/gold-grounding-baseline.json:4-18] Phase 11 should preserve this artifact as a degraded baseline and add explicit release-threshold configuration rather than rewriting history.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | The proposed new file placement and class names are the best fit for the current package layout. | Project Structure / Code Examples | Planner may choose equivalent paths, but must preserve boundaries and one source of truth. |
| A2 | `/inventory` is the best end-to-end tracer because its provider and governed tool already exist. | Summary / Migration | Another route could be chosen, but would likely require more provider work before proving orchestration. |
| A3 | Proposed v2 enum labels and wire-field names are design proposals, not locked public values. | Architecture / Code Examples | They must be finalized in the first contract task before clients implement them. |
| A4 | Existing 12-turn/one-hour conversation limits are acceptable initial compatibility defaults. | Continuity | Product retention expectations may require different configurable values. |
| A5 | `/search` should be explicitly excluded unless a stable evidence snapshot is defined. | Migration | User may decide search results are evidence-heavy enough to integrate. |

## Open Questions

1. **What are the release thresholds for model-dependent routing, groundedness, latency, and cost?**
   - What we know: the live baseline is 0.87 routing, 0.283 mean groundedness, 1.0 tool correctness, and 1828.2 ms median latency. [VERIFIED: .planning/eval/gold-grounding-baseline.json:4-18]
   - Recommendation: make deterministic gates 100% (scope isolation, mutation denial, route disposition, manifest parity, retained citation validity) and require explicit product approval for model-quality and cost thresholds.
2. **What is the required thread retention and cross-device behavior?**
   - What we know: existing conversation state retains 12 turns for one idle hour in process; durable ledgers are retained separately. [VERIFIED: src/operations/investigation.py:52-61] [VERIFIED: src/operations/autonomous_investigation.py:1040-1054]
   - Recommendation: implement configurable bounded retention and same-browser navigation first; do not claim indefinite chat retention.
3. **Do live Azure MCP tool names match every Terraform grant?**
   - What we know: Terraform carries a reviewed list, but the local shell lacks the project endpoint needed for a live `tools/list` parity check. [VERIFIED: infra/terraform/foundry.tf:58-111]
   - Recommendation: add a post-deploy parity check against live MCP catalogs before promoting specialist versions.
4. **Should old ledgers be projected into the canonical result on read?**
   - Recommendation: preserve immutable old documents and provide a version-aware read adapter; do not bulk rewrite audit records.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---:|---|---|
| Project Python | API/tests | ✓ | 3.11.16 in `.venv` | System Python 3.14.7 is not the project runtime. |
| `uv` | dependency/test commands | ✓ | 0.10.9 | Existing `.venv/bin/python`. |
| Node.js / npm | web build/tests | ✓ | 22.23.2 / 10.9.8 | — |
| Terraform | infrastructure validation | ✓ | 1.14.8 | — |
| Azure CLI | Foundry deployment/live eval | ✓, authenticated | 2.87.0 | Deterministic local tests only. |
| Docker daemon | image verification | ✓ | client 29.7.2 | Local Python/web runs. |
| Foundry project endpoint | model planning/live parity | ✗ in local shell | — | Required safe deterministic fallback. |
| Gold Data Agent credentials | optional enrichment | ✗ in local shell | — | Explicit unavailable result; core routing continues. |

**Missing dependencies with no fallback:** None for local implementation and deterministic tests.

**Missing dependencies with fallback:** Foundry and Gold Data Agent configuration; live model/deployment verification must run in an environment where they are configured.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Backend framework | pytest 9.x |
| Backend config | `pyproject.toml` |
| Web framework | Vitest 2.1.9 + Testing Library |
| Quick backend command | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_page_context_v2.py -q` |
| Quick web command | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts` |
| Full backend command | `.venv/bin/python -m pytest -q` |
| Full web command | `cd web && npm test` |
| Infrastructure command | `cd infra/terraform && terraform validate -no-color` |

Existing test locations and commands are declared in `pyproject.toml` and `web/package.json`. [VERIFIED: pyproject.toml:42-44] [VERIFIED: web/package.json:5-14]

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| COP-01 | All legacy routes produce the same policy decision/result semantics; invalid model plans fall back safely | unit + API integration | `.venv/bin/python -m pytest tests/test_orchestration_policy.py tests/test_api_copilot_unified.py -q` | ❌ Wave 0 |
| COP-02 | Every route has exactly one adapter/disposition and every eligible adapter emits bounded v2 context | unit + component | `cd web && npm test -- --run src/lib/copilot/page-adapters.test.ts` | ❌ Wave 0 |
| COP-03 | Manifest, runtime, Operations MCP, Azure MCP, Terraform, API, and UI sets match exactly | unit + Terraform | `.venv/bin/python -m pytest tests/test_orchestration_parity.py -q && cd infra/terraform && terraform validate -no-color` | ❌ Wave 0 |
| COP-04 | Identity, dedup, priority, conflict, coverage, freshness, insufficiency, and citation closure | unit + API | `.venv/bin/python -m pytest tests/test_page_context_v2.py tests/test_api_copilot_snapshot_v2.py -q` | ❌ Wave 0 |
| COP-05 | Principal isolation, scope narrowing, cross-navigation continuity, conditional synthesis, telemetry, and page/cross-domain cases | unit + integration + live eval | `.venv/bin/python -m pytest tests/test_investigation_thread_store.py tests/test_copilot_evaluation_v2.py -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** focused test file(s) for the touched contract or adapter.
- **Per wave merge:** focused backend Copilot suite, all web Copilot tests, and Terraform validation.
- **Phase gate:** full backend/web suites, exact parity, route matrix, and saved live evaluation artifact green before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/test_orchestration_contract.py` — canonical versioned request/result and legacy conversions.
- [ ] `tests/test_orchestration_policy.py` — adversarial candidate plans, budgets, DAGs, grants, mutation denial, fallback.
- [ ] `tests/test_orchestration_parity.py` — exact manifest projections and forbidden tools.
- [ ] `tests/test_page_context_v2.py` — canonical entity/evidence semantics.
- [ ] `tests/test_investigation_thread_store.py` — durability, principal binding, scope narrowing, aging.
- [ ] `tests/test_api_copilot_unified.py` — three compatibility endpoints converge.
- [ ] `web/src/lib/copilot/page-adapters.test.ts` — all 28 route dispositions and adapter output.
- [ ] `web/src/lib/copilot/thread-context.test.tsx` — continuity across remount/navigation.
- [ ] Versioned evaluation dataset consumed by `scripts/evaluate_agents.py`.

The current evaluation script separates routing, groundedness, tool correctness, narration, latency, runtime, transient errors, and timeouts; preserve these dimensions and add page/thread/cost fields. [VERIFIED: scripts/evaluate_agents.py:75-98,365-465,503-584]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | yes | Existing Entra/gateway `CurrentPrincipal`; no client-supplied identity. |
| V3 Session Management | yes | Server-issued opaque thread ID, principal binding, bounded TTL/turns, revalidation after storage read. |
| V4 Access Control | yes | Effective `ReadScope`, canonical entity authorization, exact specialist/tool grants, deny unknowns. |
| V5 Input Validation | yes | Strict Pydantic models, bounded strings/lists/bytes, discriminated unions, MCP argument schemas. |
| V6 Cryptography | yes | Existing JWT signature/issuer/audience validation and standard UUID/SHA-256 utilities; no custom crypto. |

Existing Entra authentication validates `"RS256"` signatures and requires `"exp"`, `"iat"`, `"iss"`, and `"aud"` claims. [VERIFIED: src/api/auth.py:139-189] Static tokens use constant-time comparison. [VERIFIED: src/api/auth.py:49-75]

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| Prompt injection proposes privileged tools | Elevation / Tampering | Treat model output as untrusted candidate data; deterministic allowlists and read-only mutation fence. |
| Confused deputy across specialists | Elevation | Validate each tool against the selected specialist’s exact manifest grants and current principal scope. |
| Cross-principal thread guessing | Information disclosure | Principal check on every read/write; return not-found semantics for mismatches. |
| Stale evidence drives current decision | Tampering | Observation timestamps, historical marker, current-scope intersection, mandatory recheck for actionable claims. |
| Citation forgery or truncation orphan | Spoofing | Validate references against retained authorized evidence after dedup/priority truncation. |
| Excessive tool/model fan-out | Denial of service | Specialist/tool/depth/wall-clock/token budgets and deterministic partial result. |
| Optional provider failure fabricated as empty | Tampering | Preserve unavailable/denied/partial states and deterministic insufficiency. |
| Telemetry leaks operator/resource data | Information disclosure | Low-cardinality controlled attributes; no prompts, arguments, principal, resource, or thread IDs in metrics. |
| Manifest tampering creates wider grants | Elevation | Code review, exact parity tests, forbidden-mutation tests, Terraform validation, post-deploy live catalog verification. |
| Chain-of-thought exposure | Information disclosure | Persist only structured intent, selected IDs, policy reason codes, findings, citations, and outcomes. |

Agent Framework security guidance explicitly describes the split where a model decides what to do while deterministic framework policy decides what is allowed. [CITED: https://learn.microsoft.com/en-us/agent-framework/agents/security]

## Sources

### Primary (HIGH confidence)

- `.planning/REQUIREMENTS.md:81-87` — COP-01 through COP-05.
- `.planning/phases/.../11-CONTEXT.md:7-32` — locked decisions, priorities, and route policy.
- `src/operations/page_context.py:18-157,160-233` — snapshot bounds, strict validation, scope, hash, freshness, dedup.
- `src/operations/investigation.py:52-186,310-464` — heuristic planner, execution, and bounded sessions.
- `src/operations/autonomous_investigation.py:47-89,621-986,1014-1154` — specialist definitions, three flows, ledger persistence.
- `src/operations/maf_orchestrator.py:18-109` — current deterministic “MAF” selection.
- `src/operations/tools.py:40-46,902-1084` and `src/operations/mcp_server.py:19-130` — governed tools and MCP contract.
- `src/api/routers/copilot.py:235-363` and `src/api/routers/multi_agent.py:53-105` — endpoint drift and compatibility boundaries.
- `infra/terraform/foundry.tf:11-221,272-290` — current grants/prompts/projection.
- `web/src/lib/types.ts:2451-2475`, `web/src/lib/services.ts:405-515`, `web/src/components/ui/CopilotDrawer.tsx:118-178` — current web contracts.
- Existing focused tests and `.planning/eval/gold-grounding-baseline.json`.

### Secondary (official documentation)

- [Agent Framework orchestrations](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/)
- [Agent Framework checkpoints](https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints)
- [Agent Framework structured outputs](https://learn.microsoft.com/en-us/agent-framework/agents/structured-outputs)
- [Agent Framework security](https://learn.microsoft.com/en-us/agent-framework/agents/security)
- [Foundry Agent Service overview](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Foundry MCP tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol)
- [Pydantic unions](https://docs.pydantic.dev/latest/concepts/unions/)
- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [OpenTelemetry Metrics API](https://opentelemetry.io/docs/specs/otel/metrics/api/)
- [Next.js 14 composition patterns](https://nextjs.org/docs/14/app/building-your-application/rendering/composition-patterns)

### Tertiary (LOW confidence)

- New target file names, proposed v2 enum labels, and exact field names are design proposals marked `[ASSUMED]`.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — exact installed versions and project declarations verified locally; no new dependency proposed.
- Architecture: HIGH — based on direct reads of all three orchestration paths, auth/scope, storage, infrastructure, web, and tests.
- Snapshot/evidence algorithm: HIGH for constraints and current gaps; MEDIUM for proposed wire naming.
- Pitfalls: HIGH — most are demonstrated by existing drift, tests, or current code paths.
- Live provider parity: MEDIUM — local environment lacks Foundry/Gold configuration, so post-deploy verification remains required.

**Research date:** 2026-09-03  
**Valid until:** 2026-09-10 for Foundry/Agent Framework details; 2026-10-03 for repository architecture.
