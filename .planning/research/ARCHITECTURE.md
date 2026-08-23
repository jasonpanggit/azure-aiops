# Architecture Patterns

**Domain:** Azure AI/SRE operations workbench with evidence-backed investigation and governed remediation  
**Project:** Azure AI Operations Platform  
**Researched:** 2026-08-23

## Recommended Architecture

Extend the existing layered platform into two explicit planes:

```text
Authoritative sources
  ARG | Azure Monitor/Log Analytics/App Insights/OTel | Defender/Sentinel
  Update Manager | Entra | enterprise ticketing/runbooks
        │ scoped adapters; source IDs, timestamps, deep links
        ▼
Evidence + projection plane
  ingestion → normalization → evidence registry → semantic graph snapshot
        │                                         │
        │                                         └→ Fabric IQ Ontology / graph projection
        ▼
Investigation plane
  situation → evidence bundle → graph/context traversal → explanation
        │
        ▼
Decision plane
  recommendation + risk/policy evaluation → approval record
        │ (only approved, unexpired, immutable plan)
        ▼
Execution plane
  bounded idempotent action adapter → verification → audit/result evidence
```

The graph is an operational twin, not a replacement CMDB, monitoring store, or ticket system. OneLake/Delta remains the durable boundary for versioned canonical entities, relationship assertions, evidence references, workflow state, and audit records. Fabric IQ Ontology is a semantic projection and query surface; retain an exportable canonical representation because the ontology capability is preview. This aligns with the repository’s existing ARG → normalization → Fabric/OneLake → ontology → semantic-engine flow.

Every meaningful answer and recommendation should be reproducible from an immutable `evidence_bundle`: source system and query/version, scope, observation window, freshness, quality warnings, entity/relationship IDs, and deep links. Store pointers and compact summaries rather than raw logs, traces, ticket histories, or secrets. Treat AI output as a proposal with model/version and policy metadata, never as evidence.

Investigation and remediation must be durable workflows rather than request-bound threads. The API should create a job and return its ID; workers persist checkpoints and state transitions. Approval is a state transition over a specific recommendation and evidence hash, not a boolean attached to a user session. Execution re-evaluates authorization, scope, expiry, policy, and current resource state immediately before acting, then records the provider operation ID and verification result.

## Component Boundaries

| Component | Responsibility | Repository integration | Communicates with |
|-----------|----------------|------------------------|-------------------|
| Source adapters | Read scoped, authoritative observations; preserve source IDs and links | Extend `src/hermes_arg_connector/`, `src/semantic/live_provider.py`, and new adapters under `src/integrations/` | ARG, Monitor/Logs, Defender, Sentinel, Update Manager, Entra, ticketing |
| Evidence registry | Normalize observations into provenance-bearing evidence records; enforce retention/redaction | New `src/evidence/`; use `src/api/evidence.py` contracts and `src/storage/` | Adapters, graph projection, investigations, audit |
| Canonical twin/ontology projection | Maintain entities, assertion history, effective views, quality, and publication versions | Extend `src/ontology/`, `src/fabric/`, `src/storage/`; preserve `ONTOLOGY_SCHEMA.md` | OneLake/Delta, Fabric IQ, semantic engine |
| Situation service | Create/refresh a situation from an alert, incident, finding, or operator query; freeze the initial scope/evidence snapshot | New `src/investigation/` service; expose through `src/api/routers/` | Evidence, semantic engine, live providers |
| Investigation orchestrator | Execute bounded evidence gathering and analysis with checkpoints, budgets, cancellation, and partial-result states | Replace/encapsulate `src/operations/autonomous_investigation.py`; wire through `src/api/runtime.py` | Situation service, semantic/intelligence engines, Foundry |
| Explanation/recommendation service | Produce cited findings, impact paths, candidate runbooks/actions, risk, confidence, and unresolved conflicts | Compose existing `src/agents/operations/` and `src/intelligence/`; keep Foundry narration downstream | Evidence, graph, policy, Foundry |
| Policy/approval service | Evaluate action allowlists, scope, separation of duties, risk, expiry, and approval requirements | New `src/governance/`; integrate `src/api/rbac.py`, `src/api/scope.py` | Recommendation, identity, audit, execution |
| Execution adapters | Perform only typed, allowlisted, idempotent Azure actions; never accept arbitrary commands from a model | New `src/remediation/`; use Azure SDK/management APIs and managed identity | Azure control plane, policy, verification |
| Audit ledger | Append-only decision and action history, including denials, approvals, retries, provider IDs, and verification | New durable tables through `src/storage/`; correlate with existing API telemetry | Approval, execution, Azure Activity Log |
| Observability boundary | Propagate trace/correlation IDs and emit low-cardinality workflow metrics, freshness, lag, and policy outcomes | Extend `src/api/telemetry.py`, `src/fabric/telemetry.py`, and Container Apps/App Insights | OpenTelemetry, Application Insights, Azure Monitor |

Keep routers, CLI, and UI thin. Add services under owning packages and compose them in `src/api/runtime.py` or `src/fabric/runtime.py`; do not duplicate workflow logic in `src/api/routers/` or `web/`.

## Data Contracts and State

Use separate records for:

1. **Observation/evidence:** immutable source fact or compact source-derived summary with `source`, `source_locator`, `observed_at`, `scope`, `freshness`, and quality.
2. **Assertion:** a graph relationship with confidence, provenance, observation timestamps, lifecycle state, and evidence references. Preserve conflicting source assertions; derive an effective edge under versioned policy.
3. **Situation:** subject/scope, trigger, status, evidence-bundle version, investigator run, and operator-visible freshness/warnings.
4. **Recommendation:** proposed action, target set, preconditions, risk class, expected effect, evidence hash, policy decision, expiry, and runbook/version reference.
5. **Approval:** approver identity, role/separation-of-duties result, decision, timestamp, reason, recommendation/evidence hash, and expiry.
6. **Execution/audit:** action ID, provider operation ID, before/after references, adapter version, result, verification evidence, rollback/compensation status, and correlation ID.

Recommended workflow states are explicit and monotonic: `created → investigating → explained → recommended → awaiting_approval → approved → executing → verifying → succeeded|failed|partially_succeeded|expired|cancelled`. Persist rejection, timeout, supersession, and policy-denial events; do not overwrite the recommendation that was approved.

## Data Flow

### Detection to explanation

1. A scheduled sync, alert/incident import, or operator request creates a scoped situation.
2. Source adapters retrieve only the minimum authorized data. Each call emits a trace span and an evidence reference.
3. Evidence is normalized and reconciled with the versioned semantic snapshot. Live data is explicitly marked with its observation time and does not silently replace snapshot data.
4. Investigation traverses bounded graph paths (depth and query budget), joins domain intelligence, and records the exact evidence bundle used.
5. Deterministic rules and source precedence establish impact and confidence. Foundry may summarize or suggest hypotheses, but citations and unresolved conflicts remain in the structured result.

### Recommendation to approved remediation

1. A typed recommendation references target IDs, preconditions, runbook/action type, risk, evidence hash, and expected verification.
2. Policy evaluates target scope, caller role, environment, action allowlist, current resource state, and separation of duties.
3. UI/API presents the recommendation and evidence; approval records the exact version/hash and expires on freshness or time limits.
4. The worker re-checks policy and evidence freshness, acquires a durable idempotency key, and invokes one execution adapter.
5. The adapter records the Azure operation ID; a verifier reads resulting state and Activity Log evidence.
6. The audit ledger links situation → evidence → recommendation → approval → execution → verification, while the UI reports partial failure and retry/rollback state.

### Ingestion/publication

Retain the existing immutable generation and Fabric synchronization path. Add evidence and workflow tables as governed projections, publish graph versions atomically, and expose source, curated, and ontology watermarks separately. A graph refresh failure must not destroy the last known-good canonical snapshot.

## Integration Points with This Repository

- **Semantic graph:** extend `src/semantic/semantic_engine.py` and `src/semantic/hybrid_query.py` with evidence-aware path results rather than creating a second graph database.
- **Ontology:** retain `src/ontology/ontology_sync.py` validators and assertion lifecycle; add effective/evidence/incident-time/agent-safe views and publication health.
- **Persistence:** use `src/storage/delta_writer.py`, `src/storage/onelake_writer.py`, and document storage for immutable versions, job state, evidence pointers, and audit events. First consolidate duplicated local/OneLake storage behavior behind conformance-tested ports.
- **Runtime:** add durable worker/job dependencies to `src/api/runtime.py` and `src/fabric/runtime.py`; remove reliance on process-local provider refresh and long-lived request futures.
- **API:** add situation, investigation, recommendation, approval, execution, and audit routers with stable envelope/error contracts. Continue applying authorization immediately after provider retrieval, including nested evidence.
- **Operations/Foundry:** keep `src/operations/foundry_agent.py` read-oriented and scope-filtered. Pass structured evidence bundles to the model; do not expose execution tools in the same capability set as discovery.
- **Infrastructure:** keep Container Apps for API/UI; use Container Apps Jobs or Durable Functions for scheduled and long-running workers. Use managed identities and Key Vault, with separate read/discovery and write/execution permissions.
- **Frontend:** add a workflow timeline and evidence panel to the existing Next.js workbench; render approval/action state from server records, not optimistic client state.
- **Observability:** extend existing OpenTelemetry metrics to traces across API → worker → source/provider → execution adapter; alert on freshness, stuck jobs, failed verification, denied actions, and publication lag.

## Patterns to Follow

### Pattern 1: Evidence bundle with snapshot pinning
**What:** A query/investigation consumes a named snapshot plus explicitly timestamped live observations and returns source links, confidence, warnings, and scope.  
**When:** Every explanation, recommendation, and approval.  
**Why:** Prevents an answer from changing invisibly between recommendation and execution.

### Pattern 2: Durable orchestrator with idempotent activities
**What:** Orchestrator owns state and waits; activities perform bounded reads, policy checks, actions, and verification. Each activity has a stable idempotency key and retry classification.  
**When:** Investigations, syncs, approvals, and remediation that can exceed an HTTP request.  
**Why:** Durable Functions documents checkpoints, retries, recovery, and monitoring as runtime responsibilities. A repository-native equivalent is acceptable initially, but the state contract should remain compatible with a durable worker.

### Pattern 3: Separate decision and execution capabilities
**What:** Reasoning can propose; only a policy-controlled execution service can mutate Azure.  
**When:** Any action with production effect.  
**Why:** Approval must be evaluated outside the model/client and immediately before execution, with least-privilege managed identity.

### Pattern 4: Append-only audit correlation
**What:** Carry one correlation/run ID through API, evidence retrieval, workflow, approval, adapter, and Azure operation; append events rather than updating history in place.  
**When:** All state transitions and external mutations.  
**Why:** Azure Activity Log covers control-plane operations but has finite default retention and differs from data-plane logs; the platform needs durable links and retention of its own decision history.

### Pattern 5: Graph projection, not graph ownership
**What:** OneLake canonical tables are versioned and exportable; Fabric IQ supplies entity/relationship semantics and graph navigation.  
**When:** Operational twin publication and agent grounding.  
**Why:** Fabric IQ provides ontology concepts, relationships, constraints, bindings, and graph representation, but is currently preview; an adapter and rollback boundary contain change risk.

## Anti-Patterns to Avoid

### AI-controlled mutation
**What:** Giving an agent arbitrary ARM/CLI access or allowing model text to become a command.  
**Why bad:** Bypasses scope, approval, idempotency, and audit controls.  
**Instead:** Typed action catalog, server-side policy, immutable approval, dedicated execution identity, and post-action verification.

### Request-bound investigation
**What:** Running parallel agent work in API threads and continuing after timeout.  
**Why bad:** Existing code already identifies this as a production risk; work can outlive the request and lose reliable cancellation/reconciliation.  
**Instead:** Persisted jobs, cooperative cancellation, bounded budgets, checkpoints, and explicit partial results.

### Shadow CMDB or telemetry lake
**What:** Copying all resources, logs, traces, tickets, or raw security events into the platform.  
**Why bad:** Stale/conflicting authority, cost, privacy exposure, and unclear retention.  
**Instead:** Compact governed projections, provenance/deep links, aggregate telemetry evidence, and live reads for detail.

### Mutable “current truth” graph
**What:** Overwriting edges or deleting contradictory assertions.  
**Why bad:** Destroys incident-time reconstruction and makes recommendations unauditable.  
**Instead:** Assertion history, effective views, temporal expiry, conflict/quarantine states, and versioned policies.

## Scalability Considerations

| Concern | At 100 users | At 10K users | At 1M users |
|---------|--------------|--------------|-------------|
| Workflow jobs | One durable worker pool; persisted job table | Queue-backed workers, leases, per-tenant quotas | Partitioned queues, dedicated execution pools, backpressure |
| Graph/query | Cached immutable snapshot and bounded traversal | Push filtering/aggregates into SQL/Delta; shared snapshot cache | Precomputed effective/path indexes and tenant partitions |
| Evidence | Compact references and summaries in OneLake | Retention tiers, source-side queries, bundle size limits | Externalized evidence index with strict tenant/retention partitioning |
| Remediation | Serial per target group with dry-run/verification | Per-scope concurrency limits and circuit breakers | Provider-specific schedulers, blast-radius budgets, staged rollout |
| Audit/telemetry | Correlation IDs and structured events | Central dashboards and alerts for lag/stuck/denied work | Partitioned retention, sampling only for technical traces, never for audit events |

## Build Order

1. **Contract and safety foundation:** define evidence, assertion, situation, recommendation, approval, execution, and audit schemas; add correlation IDs, state transitions, idempotency, and scope tests.
2. **Durable investigation slice:** implement one vertical detect → evidence → graph context → explanation flow using existing incident/resource intelligence; persist jobs and evidence bundles.
3. **Recommendation and approval:** add typed runbook/action catalog, policy evaluation, expiry, separation-of-duties, and UI/API approval timeline. No mutation yet.
4. **One bounded remediation:** implement a low-risk Azure action with managed identity, preconditions, dry-run, idempotent operation tracking, verification, and Activity Log correlation.
5. **Operational twin hardening:** add effective/evidence/incident-time graph views, ontology refresh health, rollback, and source/curated/graph watermarks.
6. **Scale and integrations:** move sync/refresh/investigation off process-local threads, add more source adapters and action types, then load/failure-test Container Apps Jobs or Durable Functions.

## Sources

- Microsoft, *What Is Ontology (Preview)?* — entities, properties, relationships, bindings, graph, and preview status. https://learn.microsoft.com/en-us/fabric/iq/ontology/overview (MEDIUM confidence; official documentation checked 2026-08-23)
- Microsoft, *Data binding in ontology (preview).* https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-bind-data (MEDIUM; official)
- Microsoft, *Durable Functions overview.* https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-overview (MEDIUM; official)
- Microsoft, *Pipeline deployment approvals.* https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals (MEDIUM; official)
- Microsoft, *Enable OpenTelemetry in Application Insights.* https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-enable (MEDIUM; official)
- Microsoft, *Activity Log in Azure Monitor.* https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log (MEDIUM; official)
- Microsoft, *What is Microsoft Foundry Agent Service?* https://learn.microsoft.com/en-us/azure/ai-foundry/agents/overview (MEDIUM; official)
- Microsoft, *Operational excellence quick links.* https://learn.microsoft.com/en-us/azure/well-architected/operational-excellence/ (LOW; provider fetch was unavailable, architecture principle cross-checked against repository constraints)
- Repository codebase map: `.planning/codebase/ARCHITECTURE.md`, `INTEGRATIONS.md`, `CONCERNS.md`, `STACK.md`; project contract: `.planning/PROJECT.md` (HIGH for repository-specific findings)
