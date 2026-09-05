# Phase 13: Autonomous Ontology Discovery and Fabric Synchronization - Research

**Researched:** 2026-09-04  
**Domain:** Durable ontology discovery, governed AI relationship proposals, and fenced Fabric publication  
**Confidence:** HIGH for repository behavior; MEDIUM for current Microsoft service guidance

## Summary

Phase 13 should replace the process-local background thread behind the existing Sync button with one durable, run-once coordinator shared by scheduled and manual triggers. The current path is UI `connectionsApi.sync(..., "manual")` → `POST /subscription-connections/{id}/sync` → `SubscriptionOnboardingService.sync_async()` → `ConnectionSyncCoordinator.run()` → `_InventoryRefreshRunner` → combined snapshot → `FabricSyncService.sync()`. The browser polls every 1.5 seconds for up to 20 minutes, while the server uses a process-local `ThreadPoolExecutor`; restart reconciliation converts inherited `"running"` state to `"failed"`. [VERIFIED: web/src/app/connections/page.tsx:18-32,70-94,131-151] [VERIFIED: src/api/routers/connections.py:239-275] [VERIFIED: src/onboarding/service.py:498-652] [VERIFIED: src/onboarding/runtime.py:282-347]

The tracer must preserve the current deterministic graph builders and make the model advisory only. Use a versioned Foundry **prompt agent** with narrowly allowlisted, read-only MCP evidence tools; locally validate every response and persist content-addressed proposals. Microsoft describes prompt agents as the managed choice for production agents without custom orchestration and hosted agents as the custom-code choice. Keep a decision checkpoint to switch only if agent-side custom protocols are proven necessary; scheduling, admission policy, publication, and rollback remain deterministic in either case. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview#agent-types] [VERIFIED: infra/terraform/foundry.tf:11-295] [VERIFIED: src/operations/foundry_agent.py:340-533]

The main correctness boundary is publication. Current OneLake JSON “CAS” is a read/check followed by unconditional overwrite, the existing Fabric lock can immediately break another infinite lease, and the current multi-table rollback is not an atomic reader-visible transaction. Build immutable generation-scoped outputs, validate them completely, then conditionally swap one active-generation pointer under a renewable lease plus monotonically increasing fencing token and source/current-generation preconditions. Rollback is another fenced pointer transition to a retained valid generation. [VERIFIED: src/storage/onelake_documents.py:134-177] [VERIFIED: src/storage/onelake_writer.py:131-186] [VERIFIED: src/fabric/sync_service.py:365-524] [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]

**Primary recommendation:** Begin with a fail-fast Phase 10/12 dependency preflight and a non-authoritative Wave 0 contract harness that exercises the eventual evidence, policy, publisher, active-pointer, consumer, and rollback interfaces without writing production state. The first authoritative tracer runs only after consumer compatibility and publisher-authorization checkpoints, and then covers durable due work → bounded evidence delta → deterministic graph plus advisory proposal → hard shadow admission → immutable staged generation → service-enforced fenced pointer promotion → consumer resolution → fenced rollback.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Schedule and run-now intake | API / Backend | ACA Job | The API authorizes and records run-now intent; an ACA Job invokes the same finite coordinator independently of a browser. [VERIFIED: src/api/routers/connections.py:239-275] [CITED: https://learn.microsoft.com/en-us/azure/container-apps/jobs] |
| Due-work selection and checkpoints | API / Backend | Database / Storage | Work eligibility must derive from durable records, following the existing run-once remediation coordinator/store pattern. [VERIFIED: src/intelligence/remediation/verification_coordinator.py:34-119] [VERIFIED: src/intelligence/remediation/execution_store.py:330-456] |
| Inventory and deterministic graph build | API / Backend | Database / Storage | Existing normalization/build/validation code remains authoritative; no graph semantics belong in the agent. [VERIFIED: src/fabric_pipelines/ontology_pipeline.py:48-87] |
| Curator relationship proposals | Foundry Agent Service | API / Backend | Foundry proposes from bounded evidence; the backend validates, deduplicates, and governs proposals. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview] [VERIFIED: src/operations/foundry_agent.py:739-812] |
| Proposal review and admission | API / Backend | Browser / Client | Server-side policy/CAS owns state transitions; the web only displays and submits authorized review decisions. [VERIFIED: src/fabric_pipelines/relationship_suggestions_contract.py:33-96] |
| Staging, validation, promotion, rollback | Database / Storage | API / Backend | Immutable generation data and one fenced active pointer define visibility; a dedicated publisher performs transitions. [VERIFIED: src/storage/datasets.py:217-325] |
| Status and observability | API / Backend | Browser / Client | Durable run/proposal/publication records are the source; UI polling is only a projection. [VERIFIED: web/src/app/connections/page.tsx:70-94] |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| AUTO-ONT-01 | A durable, browser-independent scheduler discovers due connection work, prevents concurrent publication for the same scope, resumes safely after restart, and exposes bounded retry, timeout, cancellation, and run-now controls. [VERIFIED: .planning/REQUIREMENTS.md:99] | Reuse the durable due-query/run-once coordinator pattern, add ACA Job invocation, and route manual Sync into the same ledger. |
| AUTO-ONT-02 | Incremental discovery identifies added, changed, retired, unresolved, and stale ontology inputs from authoritative inventory and operational evidence, while scheduled full reconciliation detects drift. [VERIFIED: .planning/REQUIREMENTS.md:100] | Extend existing row hashes, retirement synchronization, and pending-edge seam with durable observations and periodic full reconciliation. |
| AUTO-ONT-03 | A versioned Microsoft Foundry ontology agent receives only scope-filtered read-only evidence and the approved ontology contract, and returns structured, cited relationship proposals without direct authoritative Fabric write access. [VERIFIED: .planning/REQUIREMENTS.md:101] | Extend current prompt-agent provisioning, Responses client, managed identity, MCP registry, and tool allowlists. |
| AUTO-ONT-04 | Relationship proposals have deterministic identity, provenance, confidence, evidence, lifecycle, and review state; promotion enforces known endpoints, approved predicates and type pairs, scope, contradiction checks, and explicit human-review or allowlisted auto-accept policy. [VERIFIED: .planning/REQUIREMENTS.md:102] | Replace free-form parsing/random IDs and confidence-only promotion with strict contracts and deterministic policy. |
| AUTO-ONT-05 | The ontology publisher uses a dedicated least-privilege identity, fenced single-writer/version preconditions, fail-closed validation, immutable generation lineage, and atomic promotion with rollback to a prior valid generation. [VERIFIED: .planning/REQUIREMENTS.md:103] | Combine renewable lease, fencing token, conditional pointer CAS, immutable generations, and a separate publisher identity. |
| AUTO-ONT-06 | Pending edges, run checkpoints, leases, proposal decisions, publication attempts, failures, and ontology quality metrics persist across restarts and remain visible through scope-enforced operational APIs and UI. [VERIFIED: .planning/REQUIREMENTS.md:104] | Persist immutable run/proposal/attempt documents and scope-filtered projections; do not rely on in-memory pending or live-run collections. |
| AUTO-ONT-07 | Offline and deployed evaluations enforce tenant isolation, prompt-injection resistance, relationship precision and recall, citation and freshness requirements, idempotency, bounded cost and latency, failure recovery, and audit completeness. [VERIFIED: .planning/REQUIREMENTS.md:105] | Add deterministic replay fixtures, adversarial cases, coordinator fault injection, and a deployed shadow-mode gate. |

The descriptions above are verbatim from the requirements source. [VERIFIED: .planning/REQUIREMENTS.md:97-105]
</phase_requirements>

## Standard Stack

### Core

| Library / Service | Version | Purpose | Why Standard |
|---|---:|---|---|
| Python | `>=3.11` | Coordinator, contracts, stores, agent adapter, APIs | Existing project runtime requirement. [VERIFIED: pyproject.toml:1-18] |
| `pydantic` | `2.13.4` | Strict untrusted-output and API/store contracts | Already locked and used by MCP request validation. [VERIFIED: uv.lock:3779-3786] [VERIFIED: src/operations/mcp_server.py:55-130] |
| `azure-identity` | `1.25.3` | Managed-identity credentials | Already locked and used by the Foundry client. [VERIFIED: uv.lock:1108-1115] [VERIFIED: src/operations/foundry_agent.py:298-337] |
| `azure-storage-file-datalake` | `12.25.0` | OneLake leases and conditional storage operations | Already locked; use its lease and request-condition primitives rather than emulating concurrency in JSON. [VERIFIED: uv.lock:1184-1191] [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage] |
| `deltalake` | `1.6.2` | Existing Fabric Delta writes/repair | Preserve the current writer for physical tables, but move reader-visible atomicity to generation promotion. [VERIFIED: uv.lock:1621-1627] [VERIFIED: src/fabric/sync_service.py:365-524] |
| `fastapi` | `0.138.0` | Run-now, status, proposal-review, and rollback APIs | Existing API framework and authorization boundary. [VERIFIED: uv.lock:1697-1704] |
| Foundry prompt agent | Existing project data plane | Advisory relationship proposals | Managed default; no custom agent runtime is needed for the initial contract. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview#choose-how-to-build] |
| Azure Container Apps Job | Existing ACA environment | Browser-independent scheduled/run-once invocation | Jobs are finite and support manual or scheduled triggers, timeout, retry, and parallelism configuration. [CITED: https://learn.microsoft.com/en-us/azure/container-apps/jobs] |

### Supporting

| Library | Version | Purpose | When to Use |
|---|---:|---|---|
| `httpx` | `0.28.1` | Existing Foundry Responses REST transport | Reuse the current timeout/retry/circuit-breaker adapter. [VERIFIED: uv.lock:2156-2164] [VERIFIED: src/operations/foundry_agent.py:340-533] |
| `opentelemetry-api` | `1.43.0` | Coordinator/run/promotion spans | Add only around deterministic orchestration; use Foundry server-side tracing for agent internals. [VERIFIED: uv.lock:3108-3115] [CITED: https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept] |
| `pyarrow` | `23.0.1` | Existing dataset/Delta schemas | Extend existing contracts and fixtures; do not invent a second serialization stack. [VERIFIED: uv.lock:3699-3706] |
| `pytest` | `9.1.1` | Backend replay, concurrency, fault, and contract tests | Existing configured test framework. [VERIFIED: uv.lock:4061-4069] [VERIFIED: pyproject.toml:42-44] |
| Vitest | `^2.1.9` | Web status/review tests | Existing web test framework. [VERIFIED: web/package.json:28-42] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| Prompt agent | Hosted agent | Use only after a checkpoint proves custom agent-side orchestration/protocol code is necessary; it adds a custom runtime without changing deterministic scheduler or publisher ownership. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview#agent-types] |
| ACA scheduled Job | API-resident timer thread | The latter repeats the current process-lifetime failure mode and does not survive scaling/restarts as durable work. [VERIFIED: src/onboarding/service.py:68-150] |
| Conditional active pointer | In-place updates plus per-table rollback | In-place writes expose mixed generations and current rollback is table-by-table. [VERIFIED: src/fabric/sync_service.py:365-524] |

**Installation:** introduce no new production runtime package in the tracer. Evaluation tooling is isolated in the repository's existing package managers and committed lockfiles:

```bash
uv sync --all-extras
cd web && npm ci
npm ci --prefix evals/ontology-discovery
uv sync --extra eval --locked
```

The project already declares the required Azure, storage, Delta, HTTP, telemetry, validation, and test dependencies. Promptfoo is a pinned npm-only evaluation dependency under `evals/ontology-discovery`; Phoenix and `opentelemetry-sdk` are pinned Python `eval` extras. They are not production runtime dependencies. [VERIFIED: pyproject.toml:6-27] [VERIFIED: AI-SPEC.md:548-599]

## Package Legitimacy Audit

The AI-SPEC requires Promptfoo and self-hosted Arize Phoenix. Direct package identities were rechecked against their canonical registries on 2026-09-04 and must be exact-pinned in committed evaluation lockfiles. Existing lock entries resolve through the configured Microsoft package-feed proxy. [VERIFIED: npm registry metadata, 2026-09-04] [VERIFIED: PyPI JSON metadata, 2026-09-04] [VERIFIED: uv.lock:1008-1014] [VERIFIED: uv.lock:1109-1115]

| Package set | Registry | Verdict | Disposition |
|---|---|---|---|
| Existing `uv.lock` dependencies | Microsoft package-feed proxy/PyPI | `SUS` heuristic result; already repository-locked [VERIFIED: gsd-tools package-legitimacy check, 2026-09-04] | Retain lock; no Phase 13 package addition |
| `promptfoo==0.122.2` | npm (`promptfoo`) | `VERIFIED` — MIT, canonical `github.com/promptfoo/promptfoo`, executable `promptfoo`, Node >=22.22.0 [VERIFIED: npm registry metadata, 2026-09-04] | Exact dev pin in `evals/ontology-discovery/package.json` and committed package lock; synthetic/local providers only |
| `arize-phoenix==20.7.0` | PyPI (`arize-phoenix`) | `VERIFIED` — Elastic-2.0, canonical `github.com/Arize-ai/phoenix`, Python >=3.10,<3.15 [VERIFIED: PyPI JSON metadata, 2026-09-04] | Exact `eval` extra pin and committed `uv.lock`; loopback self-hosted evaluation only |
| `opentelemetry-sdk==1.44.0` | PyPI (`opentelemetry-sdk`) | `VERIFIED` — Apache-2.0, canonical OpenTelemetry repository, Python >=3.10 [VERIFIED: PyPI JSON metadata, 2026-09-04] | Exact `eval` extra pin and committed `uv.lock`; sanitized evaluator spans only |

**Packages removed due to `SLOP` verdict:** none. [VERIFIED: gsd-tools package-legitimacy check, 2026-09-04]  
**Packages flagged as suspicious `SUS`:** no new direct evaluation package. If repository dependency/license policy rejects Phoenix during locked installation, execution must halt for a blocking decision and AI-SPEC reconciliation; substituting another tracing tool is not permitted.

## Current Manual Sync Trace

1. The UI submits `"manual"` Sync, then polls health every 1.5 seconds and stops after 20 minutes. The literal values are `SYNC_POLL_INTERVAL_MS = 1_500` and `SYNC_POLL_TIMEOUT_MS = 20 * 60 * 1_000`. [VERIFIED: web/src/app/connections/page.tsx:18-32,70-94,131-151]
2. The API requires an operate-capable principal, checks connection scope, calls `context.onboarding.sync_async`, and directs clients to the health endpoint. [VERIFIED: src/api/routers/connections.py:239-275]
3. `sync_async` persists a queued/running `SyncState`, remembers the run ID in process memory, and submits `_run_sync_job` to a shared process-local executor. State writes retry registry revision conflicts three times. [VERIFIED: src/onboarding/service.py:68-150,498-631]
4. The coordinator’s allowed modes are quoted verbatim: `"initial"`, `"scheduled"`, `"manual"`. Its progress stages are quoted verbatim: `"queued"`, `"discovering"`, `"merging"`, `"publishing_ontology"`, `"writing_fabric_tables"`, `"succeeded"`. [VERIFIED: src/onboarding/sync.py:65-72,151-306]
5. Runtime construction installs `_InventoryRefreshRunner` when Fabric is configured. The runner refreshes inventory, publishes the combined snapshot, and calls `build_runtime(config).service.sync()`. [VERIFIED: src/onboarding/runtime.py:34-90,282-347]
6. Combined activation reads each connection’s active generation, rejects cross-connection identity collisions, creates `run_id = f"activation-{uuid.uuid4()}"`, and publishes merged entities, relationships, changes, and ontology metadata through `DatasetStore`. [VERIFIED: src/onboarding/activation.py:18-125]
7. `FabricSyncService.sync()` acquires `OneLakeWriter.sync_lock()`, derives/validates datasets, writes multiple Delta tables concurrently, and then publishes ontology metadata. [VERIFIED: src/fabric/sync_service.py:164-178,188-478]
8. Before `data_committed`, failure restores prior Delta versions or deletes new tables; after tables are considered committed, ontology publication failure retains graph tables for retry. This is recovery logic, not atomic generation visibility. [VERIFIED: src/fabric/sync_service.py:365-524]
9. The default publication timeout is 120 seconds, implemented by joining a daemon helper thread. On timeout the helper is not cancelled and may continue writing after the run is marked failed. [VERIFIED: src/onboarding/sync.py:331-387] Existing tests prove prompt return from a hung publisher but do not prove the abandoned writer stopped. [VERIFIED: tests/test_subscription_onboarding.py:840-875]
10. On restart, inherited process-local `"running"` work is reconciled to `"failed"` because the new process cannot own its worker. [VERIFIED: tests/test_subscription_onboarding.py:949-1025]

## Architecture Patterns

### System Architecture Diagram

```text
ACA schedule ─┐
              ├─> run-once command ─> durable due/run ledger ─> per-scope renewable lease
API run-now ──┘                               │                         │
                                              ├─duplicate? ─> return existing run/status
                                              └─claimed ─> inventory evidence checkpoint
                                                               │
                         full-reconcile due? ─yes───────────────┤
                                         no ─> bounded delta ──┘
                                                               │
                                             deterministic graph build/validate
                                                               │
                                  ┌────────────────────────────┴──────────────────┐
                                  │                                               │
                         authoritative graph                            scope-filtered evidence
                                  │                                               │
                                  │                                  Foundry prompt curator
                                  │                                               │
                                  │                                  strict local parse/validate
                                  │                                               │
                                  └──────────────> proposal ledger/review policy <─┘
                                                        │
                                              admitted proposals only
                                                        │
                                         immutable candidate generation
                                                        │
                                      complete validation + quality gates
                                                        │
                                  lease/fence/source/current-generation recheck
                                                        │
                                        conditional active-pointer promotion
                                                        │
                              status/API/UI/audit/metrics + retained prior generation
                                                        │
                                              fenced pointer rollback
```

### Recommended Project Structure

```text
src/
├── ontology_discovery/
│   ├── contracts.py       # run, checkpoint, proposal, review, generation contracts
│   ├── store.py           # immutable records + conditional pointer/CAS
│   ├── coordinator.py     # run_once; no HTTP/FastAPI/thread ownership
│   ├── incremental.py     # hashes, retirements, unresolved/stale, full reconcile
│   ├── curator.py         # Foundry adapter + strict parser
│   ├── policy.py          # deterministic proposal admission
│   └── publisher.py       # stage/validate/fence/promote/rollback
├── operations/
│   ├── mcp_server.py      # add bounded read-only ontology evidence tools
│   └── foundry_agent.py   # reuse transport/auth/retry, add curator contract adapter
├── api/
│   └── routers/           # run-now, status/history, proposals/review, rollback
infra/terraform/
├── foundry.tf             # curator specialist, allowlist, MI connection/version
└── ontology_discovery.tf  # ACA Job, publisher identity/RBAC, schedule/config
web/src/app/connections/
└── ...                    # durable run/proposal/publication status and controls
tests/
└── fixtures/ontology_discovery/  # replay, injection, collision, fencing, rollback
```

This structure extends the current packaging roots rather than introducing a service outside `src`, and preserves the existing operations, API, Terraform, and connections-page seams. [VERIFIED: pyproject.toml:36-40] [VERIFIED: tests/test_foundry_tool_registry_matches_implementation.py:22-78]

### Pattern 1: Durable Run-Once Coordinator

**What:** A transport-independent `run_once(now, limit)` queries due durable work, claims one record with status/revision CAS, processes it, persists every transition, and isolates failures per record.  
**When to use:** Both ACA schedule execution and manual run-now processing.  
**Repository pattern:** `RemediationVerificationCoordinator.run_once()` plus `RemediationExecutionStore.list_due_for_verification()` and CAS transitions. [VERIFIED: src/intelligence/remediation/verification_coordinator.py:34-119] [VERIFIED: src/intelligence/remediation/execution_store.py:330-456]

```python
# Repository-pattern pseudocode; contract names are proposed, not existing values.
def run_once(now):
    for run in store.list_due(now=now, limit=batch_limit):
        claimed = store.claim(run.run_id, expected_revision=run.revision)
        if not claimed:
            continue
        try:
            execute_claimed_run(claimed)
        except Exception as exc:
            store.record_failure(claimed.run_id, expected_revision=claimed.revision, error=exc)
```

### Pattern 2: Immutable Attempts + Small Conditional Pointers

**What:** Write each run, proposal, decision, checkpoint, generation manifest, and publication attempt under deterministic immutable identity. Keep only small mutable records for due scheduling and active generation, updated using real storage ETag/`If-Match`.  
**When to use:** Any state that must survive replica changes and support audit/replay.  
**Why:** `OneLakeDocumentStore.write()` currently performs read/revision-check/upload but its upload is unconditional, so it is not sufficient as cross-replica CAS. [VERIFIED: src/storage/onelake_documents.py:134-177] Azure documents ETag plus `If-Match` as optimistic concurrency. [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]

### Pattern 3: Lease + Monotonic Fence + Preconditions

**What:** Acquire a finite per-scope lease, increment/persist a fencing token, renew periodically, detect renewal loss, and recheck lease owner/token, source generation, and active generation immediately before promotion. Stamp publication records and candidate generations with the token.  
**When to use:** Authoritative staging/promotion/rollback.  
**Repository seam:** `RunLock` already uses a finite 60-second remote lease and exposes `renew()`. The exact lease duration is `LEASE_DURATION_SECONDS = 60`. [VERIFIED: src/storage/locking.py:20-34,93-150] Do not reuse `OneLakeWriter.sync_lock()` unchanged because it acquires `lease_duration=-1` and immediately breaks `LeaseAlreadyPresent`. [VERIFIED: src/storage/onelake_writer.py:152-184]

### Pattern 4: Immutable Generation + Conditional Promotion

**What:** Stage a complete generation at a generation-specific path, validate it, write its immutable manifest/lineage, then conditionally update one active pointer. Keep the prior active generation.  
**When to use:** Fabric ontology publication and rollback.  
**Repository seam:** `DatasetStore` already writes `generations/<name>` and makes it visible through `"current.json"` remotely or an atomic local symlink. The exact pointer name is `"_POINTER_NAME = \"current.json\""`. [VERIFIED: src/storage/datasets.py:29-45,217-325] Its remote pointer write is currently unconditional and must be upgraded to conditional ETag semantics. [VERIFIED: src/storage/datasets.py:293-310]

### Pattern 5: Advisory Agent, Deterministic Admission

**What:** Give the curator only bounded, scope-filtered evidence and an approved vocabulary; parse one strict response document; validate citations, endpoint scope, freshness, predicate/type triple, contradiction, duplicate identity, and policy state locally.  
**When to use:** Every model-proposed relationship.  
**Repository seam:** Existing specialist parsing rejects prose wrappers, uncited evidence, wrong resource IDs, wrong types, and mutation-capable summaries. [VERIFIED: tests/test_operations_mcp_foundry.py:14-65] Existing MCP argument models are strict and dispatch is scope-bound. [VERIFIED: src/operations/mcp_server.py:55-130,144-297]

### Pattern 6: Deterministic Proposal Identity

Use a canonical hash over:

```text
tenant_id | subscription_id | source_generation_id |
canonical_subject_id | approved_predicate | canonical_object_id |
evidence_set_hash | proposal_schema_version | policy_version
```

Persist `agent_name`, `agent_version`, `model/deployment`, `prompt_version`, `observed_at`, `evidence_refs`, `uncertainty`, `confidence`, lifecycle state, reviewer facts, and supersession/reversal lineage. This replaces the current random UUID suggestion ID and subject-as-`resource_id`. [VERIFIED: src/fabric_pipelines/relationship_suggestion_parser.py:33-110] [VERIFIED: src/fabric_pipelines/relationship_suggestions_contract.py:99-150]

### Pattern 7: Prompt-Agent-First Foundry Extension

Add an ontology curator entry to the existing specialist map, role prompt, generated MCP configuration, tool registry, and allowlist; let `create-foundry-agent.sh` create or version it through the Foundry data plane. [VERIFIED: infra/terraform/foundry.tf:11-295,716-827] [VERIFIED: infra/scripts/create-foundry-agent.sh:33-59,75-179] Invoke through the existing managed-identity Responses transport, which uses audience `"https://ai.azure.com/.default"`, a 60-second request timeout, retry handling, and a circuit breaker. [VERIFIED: src/operations/foundry_agent.py:298-337,340-533]

The curator should be stateless per batch and receive durable `run_id`/`batch_id` correlation; do not make a Foundry conversation the work ledger. [RECOMMENDATION]

### Anti-Patterns to Avoid

- **Parallel scheduler architecture:** Do not preserve API thread-pool Sync while adding a separate scheduled implementation; both triggers must enqueue/claim the same durable run contract. [VERIFIED: src/onboarding/service.py:498-631]
- **Agent writes Fabric:** Curator identity gets no OneLake/Fabric writer role and no mutation tool. [RECOMMENDATION]
- **Confidence-only promotion:** Current promoter checks confidence and endpoint existence only; it is not an autonomous admission policy. [VERIFIED: src/fabric_pipelines/relationship_suggestion_promoter.py:98-133]
- **Free-form repair loop:** Do not silently skip malformed model lines or feed attacker-controlled output back into repair prompts. Fail the batch contract and retain the rejected artifact safely. [VERIFIED: src/fabric_pipelines/relationship_suggestion_parser.py:33-110]
- **Lease means fencing:** A lease can expire or be broken; promotion still needs a monotonic token and conditional preconditions. [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]
- **Delta rollback means atomicity:** Restoring tables after a failure does not prevent readers from observing mixed versions. [VERIFIED: src/fabric/sync_service.py:365-524]
- **Duplicate vocabulary:** Reuse/extract the authoritative triples from `ONTOLOGY_RELATIONSHIP_TYPES`; do not create a curator-only list. [VERIFIED: src/fabric/dataset_mapper.py:181-260] [VERIFIED: tests/test_relationship_vocabulary_consistency.py:22-45]

## Tracer-First Plan and Dependency Order

1. **Contracts and replay fixture:** One scope, one deterministic edge, one valid proposal, one invalid/injected proposal, one review decision, one generation, one promotion, one rollback. Define IDs, states, transitions, redaction, and metrics before infrastructure. Supports all requirements. [RECOMMENDATION]
2. **Durable store and CAS seam:** Immutable records, small due/active pointers, true conditional writes, deterministic get-or-create, revision/status transitions, history. Extend `execution_store` and `onelake_documents` patterns. Supports AUTO-ONT-01/04/05/06. [VERIFIED: src/intelligence/remediation/execution_store.py:100-173,330-456,558-656]
3. **Run-once coordinator and manual adapter:** Move the current deterministic pipeline behind durable claim/checkpoint semantics; change manual Sync to create/return a run and poll durable status. Keep old API response fields during compatibility migration. Supports AUTO-ONT-01/06. [VERIFIED: src/api/routers/connections.py:239-275]
4. **Incremental evidence contract:** Extend row hashes to added/changed/retired/unresolved/stale, version hash semantics, and schedule full reconciliation. Supports AUTO-ONT-02. Existing `changed_resource_ids()` covers added/changed but explicitly not removal. [VERIFIED: src/onboarding/graph_normalize.py:1126-1155]
5. **Curator shadow tracer:** Add read-only tools, Foundry prompt-agent version, strict parser, deterministic IDs, and rejection/audit records; no authoritative promotion. Supports AUTO-ONT-03/04/07. [VERIFIED: infra/terraform/foundry.tf:11-295]
6. **Deterministic policy and review:** Enforce endpoint, scope, exact predicate/type triple, evidence/freshness, contradiction, lifecycle, reviewer permission, CAS, and reversible allowlisted auto-accept. Supports AUTO-ONT-04/06/07. [RECOMMENDATION]
7. **Generation publisher:** Dedicated identity, renewable lease/fence, immutable staging, complete validation, conditional pointer promotion, retained prior generation, fenced rollback. Supports AUTO-ONT-05/06. [RECOMMENDATION]
8. **ACA Job, status UI, telemetry, deployed eval:** Add schedule/run-once command, run/proposal/generation status, redacted tracing, SLO metrics, fault drills, and shadow-to-enforced gate. Supports AUTO-ONT-01/06/07. [CITED: https://learn.microsoft.com/en-us/azure/container-apps/jobs]

Do not execute Phase 13 until its declared Phase 10 and Phase 12 dependencies are complete. The roadmap says `"Depends on: Phase 10, Phase 12"`, while current state remains on Phase 03.5/03.6 preparation. [VERIFIED: .planning/ROADMAP.md:804-809] [VERIFIED: .planning/STATE.md:1-24,80-83]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Agent hosting/versioning | A new custom curator container by default | Existing Foundry prompt-agent Terraform/script path | Foundry manages prompt agents; repository already provisions versions. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview] [VERIFIED: infra/scripts/create-foundry-agent.sh:75-179] |
| Azure identity | Token files or client-secret plumbing | `DefaultAzureCredential` and managed identities | Existing client and Terraform already use MI. [VERIFIED: src/operations/foundry_agent.py:298-337] [VERIFIED: infra/terraform/foundry.tf:337-486] |
| Tool protocol | A curator-specific external tool server | Existing governed MCP registry and APIM route | Current registry enforces strict arguments, scope, limits, and audit. [VERIFIED: src/operations/mcp_server.py:55-297] |
| Ontology inference | New relationship builder inside the coordinator/agent | `EntityBuilder`, `RelationshipBuilder`, `OntologyGraphSynchronizer`, `OntologyValidator` | Current Fabric pipeline intentionally reuses these exact deterministic builders. [VERIFIED: src/fabric_pipelines/ontology_pipeline.py:1-76] |
| Predicate vocabulary | Agent prompt text as authority | `ONTOLOGY_RELATIONSHIP_TYPES` exposed through a shared helper | Existing CI already guards vocabulary consistency. [VERIFIED: tests/test_relationship_vocabulary_consistency.py:22-45] |
| Cross-process locking | PID files or in-memory mutex | Finite OneLake lease plus fencing/CAS | Existing `RunLock` supplies the lease seam; storage conditional writes supply CAS. [VERIFIED: src/storage/locking.py:20-150] [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage] |
| Scheduler | Browser polling or API daemon timer | ACA Job invoking run-once coordinator | Browser-independent finite jobs are a standard ACA primitive. [CITED: https://learn.microsoft.com/en-us/azure/container-apps/jobs] |
| Atomic publication | Multi-table “best effort” plus delete/restore | Immutable generation and one conditional active pointer | Readers need one visibility boundary. [VERIFIED: src/storage/datasets.py:217-325] |

**Key insight:** Reuse repository algorithms and adapters, but strengthen their durability/concurrency boundary; do not confuse existing local/process safety with distributed publication correctness.

## Incremental Discovery and Proposal Contract Findings

- `Normalizer` stores SHA-256 row hashes; `changed_resource_ids()` returns added/changed IDs, not removals. Retired/unresolved/stale observations and full-reconciliation drift need additional durable state. [VERIFIED: src/onboarding/graph_normalize.py:69-129,1126-1155]
- `OntologyGraphSynchronizer` can merge a previous snapshot, retire rows, and accept a pending relationship store. [VERIFIED: src/ontology/ontology_sync.py:25-189]
- `PendingRelationshipStore` is memory-resident but supports `to_list()`/`from_list()`; callers must persist it. Its test default predicate is quoted verbatim as `"depends_on"`. [VERIFIED: src/ontology/pending_relationships.py:12-20,44-103] [VERIFIED: tests/test_pending_relationships.py:6-12,57-66]
- Existing proposal status/source literals include `"pending_review"`, `"accepted"`, and `"fabric_data_agent"`; preserve compatibility through an explicit schema migration rather than silently changing stored values. [VERIFIED: src/fabric_pipelines/relationship_suggestions_contract.py:33-96]
- Existing feedback conversion is deterministic and deterministic relationships win collisions with resolution `"deterministic_kept"`. [VERIFIED: src/fabric_pipelines/ontology_pipeline.py:157-222] [VERIFIED: tests/test_relationship_suggestion_feedback_loop.py:108-181]
- The parser currently accepts line-delimited JSON embedded in prose and silently ignores malformed lines; tests explicitly expect prose and bad objects to be ignored. This behavior must not be used for production curator admission. [VERIFIED: tests/test_relationship_suggestions.py:113-145]
- The current promoter’s exact source is `"foundry_relationship_suggestion_auto_promoter"` and its threshold constant is `0.90`; its gate only checks threshold plus known endpoints. It also creates authoritative-shaped rows without trustworthy tenant/subscription/time context. [VERIFIED: src/fabric_pipelines/relationship_suggestion_promoter.py:40-95,98-133]
- `OntologyValidator` validates structural fields, lifecycle, duplicate IDs, endpoints, self-edges, endpoint type equality/lifecycle, and confidence range, but it does not enforce the approved predicate/type-triple vocabulary. Add that check before any staged generation can pass. [VERIFIED: src/ontology/ontology_validator.py:36-221]

## Safe Storage and Publication Contract

### Durable record families

Use deterministic paths/keys for these conceptual records:

- `Run`: scope, trigger, requested-by, idempotency key, source generation, full/incremental mode, status/revision, attempt/deadline/cancellation, stage checkpoints.
- `EvidenceBatch`: immutable authorized resource IDs, content hashes, observation/freshness, source provenance, schema version, redaction facts.
- `Proposal`: deterministic ID, subject/predicate/object, evidence refs/hash, confidence/uncertainty, scope, source generation, agent/prompt/model/schema/policy versions, lifecycle.
- `Decision`: immutable review/auto-policy result, actor/roles, reason, expected proposal revision/version, reverses/supersedes.
- `Generation`: immutable candidate manifest, source/proposal/decision lineage, table/content hashes, validation report, fence token.
- `PublicationAttempt`: immutable stage/promote/rollback attempt, expected and observed active generation/ETag, lease/fence, outcome/error.
- `ActivePointer`: small mutable per-scope record containing active generation, prior generation, fence token, source generation, ETag/revision.

These are recommended contracts derived from the requirement set and existing immutable-history/CAS pattern. [VERIFIED: .planning/REQUIREMENTS.md:99-105] [VERIFIED: src/intelligence/remediation/execution_store.py:100-173,330-456]

### Promotion transaction

1. Claim run using status/revision CAS.
2. Acquire finite per-scope lease; allocate monotonic fence.
3. Snapshot expected source generation and expected active pointer ETag.
4. Build generation-scoped tables/files; never overwrite active generation.
5. Validate schema, vocabulary/type triples, endpoints/scope, lifecycle, quality, lineage, and manifest completeness.
6. Re-read lease/fence/source/active pointer; abort on any mismatch.
7. Write immutable publication attempt.
8. Update active pointer with `If-Match` on the expected ETag and all logical preconditions.
9. Mark attempt/run succeeded and emit redacted audit/metrics.
10. On rollback, repeat the same fenced conditional transition to a retained valid generation.

This design extends the existing immutable generation/pointer abstraction while correcting its unconditional remote pointer write. [VERIFIED: src/storage/datasets.py:217-325] [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]

## Common Pitfalls

### Pitfall 1: Timeout returns while the writer continues
**What goes wrong:** A run is failed/retried, but its abandoned daemon helper later commits stale output.  
**Why it happens:** `join(timeout)` bounds waiting, not execution. [VERIFIED: src/onboarding/sync.py:331-387]  
**How to avoid:** Cooperative cancellation at safe boundaries plus lease-loss detection and promotion-time fencing; never rely on thread cancellation.  
**Warning signs:** A timed-out run’s table/version events appear after a newer run starts.

### Pitfall 2: Treating JSON revision checks as distributed CAS
**What goes wrong:** Two replicas read the same revision and both overwrite.  
**Why it happens:** Current remote document persistence checks in memory then performs unconditional upload. [VERIFIED: src/storage/onelake_documents.py:134-177]  
**How to avoid:** Service-enforced ETag `If-Match`; test two independent store instances, not two threads sharing one lock. [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]  
**Warning signs:** Revision history skips or two promotions report success from one predecessor.

### Pitfall 3: Breaking a live lease as “stale”
**What goes wrong:** Concurrent publishers both believe they own the critical section.  
**Why it happens:** Current Fabric lock breaks `LeaseAlreadyPresent` immediately. [VERIFIED: src/storage/onelake_writer.py:152-184]  
**How to avoid:** Finite expiry, periodic renewal, explicit lost-lease failure, and fencing token; do not break a non-expired owner.

### Pitfall 4: In-place multi-table publication
**What goes wrong:** Readers observe a mixed candidate/old generation, and rollback itself can fail.  
**Why it happens:** Tables are written independently and ontology publication follows data commit. [VERIFIED: src/fabric/sync_service.py:365-524]  
**How to avoid:** Immutable staging and one reader-visible pointer swap.

### Pitfall 5: Scope inferred from model arguments
**What goes wrong:** Prompt injection or a confused model requests another tenant/subscription.  
**Why it happens:** Treating tool arguments as authorization.  
**How to avoid:** Derive effective scope from authenticated APIM/API context and intersect every result server-side. Existing APIM removes caller-controlled scope headers and inserts trusted identity/correlation headers. [VERIFIED: infra/terraform/apim-policies/mcp-inbound.xml:1-180]

### Pitfall 6: Vocabulary validation stops at “string exists”
**What goes wrong:** A valid-looking predicate connects invalid endpoint types.  
**Why it happens:** Current validator does not compare edges to approved subject/predicate/object triples. [VERIFIED: src/ontology/ontology_validator.py:36-221]  
**How to avoid:** Exact triple membership from the shared Fabric vocabulary, plus canonical endpoint-type resolution.

### Pitfall 7: Duplicate work is handled only by a lock
**What goes wrong:** Retried triggers create duplicate runs/proposals after a crash.  
**Why it happens:** Locks serialize time but do not provide idempotent identity.  
**How to avoid:** Deterministic run/batch/proposal IDs and get-or-create semantics before lease acquisition, following the execution-store identity pattern. [VERIFIED: src/intelligence/remediation/execution_store.py:100-173]

### Pitfall 8: Traces become a cross-tenant data channel
**What goes wrong:** Prompts, tool arguments/results, or resource IDs leak into shared telemetry.  
**Why it happens:** Agent traces can capture model/tool content. [CITED: https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept]  
**How to avoid:** Redact payloads by default; emit hashes/counts/authorized scope key and separately access-controlled diagnostics.

## Code Examples

### Existing strict model-output boundary

```python
# Source: tests/test_operations_mcp_foundry.py:32-65
result = parse_specialist_findings(
    json.dumps({"findings": [finding]}),
    evidence_refs={"evidence-1"},
    resource_ids={authorized_resource_id},
)
```

The curator parser should follow this fail-closed whole-document pattern and reject prose wrappers, unknown citations, unauthorized IDs, invalid types, and mutation instructions. [VERIFIED: tests/test_operations_mcp_foundry.py:32-65]

### Existing immutable generation activation seam

```python
# Source: src/storage/datasets.py:217-325
generation = store._write_generation(datasets, ontology, manifest, run_id)
store._activate_generation(generation)
```

Do not copy private methods directly; extract a public stage/validate/promote abstraction and make remote activation conditional on ETag/fence/source preconditions. [VERIFIED: src/storage/datasets.py:217-325]

### Foundry prompt-agent invocation shape

```python
# Source: official quickstart; adapt through the repository's existing REST adapter.
response = openai_client.responses.create(
    input="Evaluate this bounded ontology evidence batch.",
    extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
)
```

Prompt-agent versions and Responses invocation are documented by Microsoft; use the repository adapter rather than introducing a second client path. [CITED: https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent] [CITED: https://learn.microsoft.com/azure/foundry/agents/quickstarts/responses-api] [VERIFIED: src/operations/foundry_agent.py:340-533]

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Backend framework | `pytest 9.1.1` [VERIFIED: uv.lock:4061-4069] |
| Backend config | `pyproject.toml`, `testpaths = ["tests"]`, `addopts = "-q"` [VERIFIED: pyproject.toml:42-44] |
| Web framework | `vitest ^2.1.9` [VERIFIED: web/package.json:28-42] |
| Quick backend command | `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_ontology_generation_publication.py` |
| Full backend command | `uv run pytest -q` |
| Quick web command | `cd web && npm test -- --run src/app/connections/page.test.tsx` |
| Full web command | `cd web && npm test` |

The inspected backend baseline passed 154 tests across onboarding, durability, Fabric sync, locks/documents, ontology, suggestions, Foundry, and MCP; the connections-page baseline passed 9 tests. [VERIFIED: test commands executed 2026-09-04]

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| AUTO-ONT-01 | due selection, duplicate trigger, restart, retry/deadline/cancel, run-now parity | unit/integration | `uv run pytest -q tests/test_ontology_discovery_coordinator.py tests/test_api_ontology_discovery.py` | ❌ Wave 0 |
| AUTO-ONT-02 | add/change/retire/unresolved/stale plus full reconcile parity | unit/replay | `uv run pytest -q tests/test_ontology_discovery_incremental.py tests/test_incremental_sync.py` | ❌/✅ |
| AUTO-ONT-03 | scope-bound tools, strict proposal parse, no writer tool/role | contract/integration | `uv run pytest -q tests/test_ontology_curator_agent.py tests/test_foundry_tool_registry_matches_implementation.py tests/test_mcp_protocol.py` | ❌/✅ |
| AUTO-ONT-04 | deterministic IDs, duplicate suppression, policy/review CAS, vocabulary triples | unit/property | `uv run pytest -q tests/test_ontology_proposal_policy.py tests/test_relationship_vocabulary_consistency.py` | ❌/✅ |
| AUTO-ONT-05 | stale writer rejected, conditional promotion, rollback, immutable prior generation | concurrency/fault | `uv run pytest -q tests/test_ontology_generation_publication.py tests/test_run_lock.py` | ❌/✅ |
| AUTO-ONT-06 | restart persistence and scope-filtered API/UI history | integration/web | `uv run pytest -q tests/test_api_ontology_discovery.py && cd web && npm test -- --run src/app/connections/page.test.tsx` | ❌/✅ |
| AUTO-ONT-07 | isolation, injection, precision/recall, citation/freshness, idempotency, cost/latency, recovery/audit | replay/deployed eval | `uv run pytest -q tests/test_ontology_discovery_evals.py` | ❌ Wave 0 |

### Existing Tests to Extend

- Manual flow/restart/timeout: `tests/test_subscription_onboarding.py`. Existing tests cover exact progress stages, failure, timeout return, async state, and orphan reconciliation. [VERIFIED: tests/test_subscription_onboarding.py:745-875,904-1067]
- Publication and storage: `tests/test_ontology_publish_durability.py`, `tests/test_fabric_sync_service.py`, `tests/test_run_lock.py`, `tests/test_onelake_documents.py`. [VERIFIED: tests/test_ontology_publish_durability.py:1-8] [VERIFIED: tests/test_fabric_sync_service.py:1-21] [VERIFIED: tests/test_run_lock.py:1-12] [VERIFIED: tests/test_onelake_documents.py:1-8]
- Graph/contracts: `tests/test_ontology_validator.py`, `tests/test_pending_relationships.py`, `tests/test_relationship_suggestions.py`, `tests/test_relationship_suggestion_feedback_loop.py`, `tests/test_relationship_suggestion_promoter.py`, `tests/test_relationship_vocabulary_consistency.py`. [VERIFIED: tests/test_ontology_validator.py:1-8] [VERIFIED: tests/test_pending_relationships.py:1-12] [VERIFIED: tests/test_relationship_suggestions.py:1-23] [VERIFIED: tests/test_relationship_suggestion_feedback_loop.py:1-31] [VERIFIED: tests/test_relationship_suggestion_promoter.py:1-10] [VERIFIED: tests/test_relationship_vocabulary_consistency.py:1-19]
- Foundry/MCP: `tests/test_foundry_agent.py`, `tests/test_foundry_tool_registry_matches_implementation.py`, `tests/test_mcp_protocol.py`, `tests/test_mcp_tools.py`, `tests/test_operations_mcp_foundry.py`. [VERIFIED: tests/test_foundry_agent.py:1-10] [VERIFIED: tests/test_foundry_tool_registry_matches_implementation.py:1-24] [VERIFIED: tests/test_mcp_protocol.py:1-8] [VERIFIED: tests/test_mcp_tools.py:1-8] [VERIFIED: tests/test_operations_mcp_foundry.py:1-11]
- Coordinator pattern: `tests/test_remediation_verification_coordinator.py`. [VERIFIED: tests/test_remediation_verification_coordinator.py:1-8]
- Web: `web/src/app/connections/page.test.tsx`, which already mocks `sync`/`health` and verifies scope propagation for Fabric views. [VERIFIED: web/src/app/connections/page.test.tsx:5-54,160-213]

### Sampling Rate

- **Per task commit:** smallest mapped test file plus `uv run ruff check <changed paths>`.
- **Per wave merge:** all Phase 13 tests, existing onboarding/Fabric/ontology/Foundry/MCP regressions, and web connections tests.
- **Phase gate:** `uv run pytest -q`, `uv run ruff check .`, `cd web && npm test`, web typecheck/build, `terraform fmt -check -recursive infra/terraform`, `terraform validate`, and deployed shadow evaluation.

### Wave 0 Gaps

- [ ] `tests/fixtures/ontology_discovery/` — tenant collision, injected metadata, duplicate proposal, stale writer, lease loss, partial stage, pointer CAS conflict, rollback failure.
- [ ] `tests/test_ontology_discovery_contracts.py`
- [ ] `tests/test_ontology_discovery_store.py`
- [ ] `tests/test_ontology_discovery_coordinator.py`
- [ ] `tests/test_ontology_discovery_incremental.py`
- [ ] `tests/test_ontology_curator_agent.py`
- [ ] `tests/test_ontology_proposal_policy.py`
- [ ] `tests/test_ontology_generation_publication.py`
- [ ] `tests/test_api_ontology_discovery.py`
- [ ] `tests/test_ontology_discovery_evals.py`

## Security Domain

Security enforcement is enabled at ASVS level 1 and blocks on high-severity findings. [VERIFIED: .planning/config.json:20-49]

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | yes | Existing Entra token validation at APIM/API and managed identity for service-to-service access. [VERIFIED: infra/terraform/apim-policies/mcp-inbound.xml:1-180] |
| V3 Session Management | no for curator batches | Use stateless batch calls correlated to durable run/batch IDs; no cross-run agent conversation. [RECOMMENDATION] |
| V4 Access Control | yes | Server-derived tenant/subscription scope, separate reviewer/operate permissions, separate curator/publisher identities, deny-by-default MCP allowlist. |
| V5 Input Validation | yes | Strict Pydantic request/output contracts, canonical Azure IDs, exact vocabulary/type triples, bounded payload/tool results. [VERIFIED: src/operations/mcp_server.py:55-137] |
| V6 Cryptography | yes | Managed identity/token platform and SHA-256 content identities; never implement tokens/signatures. [VERIFIED: src/operations/foundry_agent.py:298-337] [VERIFIED: src/onboarding/graph_normalize.py:69-129] |
| V7 Error/Logging | yes | Redacted structured failures and immutable attempt/audit records; do not log prompts/tool payloads by default. |
| V8 Data Protection | yes | Scope-filter evidence before model access; encrypt via Azure-managed storage/platform controls; minimize trace content. |
| V9 Communications | yes | Existing APIM/HTTPS boundaries and managed identity connections. [VERIFIED: infra/terraform/foundry.tf:415-486] |
| V10 Malicious Code | yes | Treat metadata, MCP descriptions/results, and model output as untrusted data; no output-driven code/tool execution. [CITED: https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol] |
| V13 API/Web Service | yes | Bounded pagination/status, idempotency keys, CAS transitions, rate limits, and scope filtering. Existing APIM provides per-caller rate limit/quota. [VERIFIED: infra/terraform/apim-policies/mcp-inbound.xml:1-180] |

### Threat Model

| Threat | STRIDE | Attack / Failure | Required Mitigation | Verification |
|---|---|---|---|---|
| Prompt injection from Azure metadata | Tampering/Elevation | Resource names/tags/descriptions instruct the agent to ignore policy or call tools | Delimit metadata as data; immutable system instruction; read-only allowlist; no writer tool; strict local schema/citation/scope/vocabulary checks; reject, do not repair with attacker text | Injection fixture cannot change tool list, scope, lifecycle, or authoritative graph |
| Cross-tenant leakage | Information disclosure | Model/tool request or trace includes another tenant’s similarly named/short ID | Scope from authenticated server context; canonical full Azure IDs; intersect tool results; authorize every citation; redact traces | Two-tenant collision fixture and API/MCP/trace assertions |
| Overprivileged writer | Elevation | Curator or general API identity can mutate authoritative Fabric | Separate publisher UAI; minimum OneLake/Fabric operations; curator has read-only MCP only; no shared credentials | Terraform assertions and negative live authorization smoke |
| Stale writer | Tampering | Timed-out/lease-lost run promotes after a newer run | Renewable lease, lost-lease abort, monotonic fence, source and active generation `If-Match` immediately before promotion | Pause old writer, promote new writer, resume old writer; old promotion must fail |
| Duplicate runs/proposals | Repudiation/Tampering | Retries or concurrent triggers create duplicate lifecycle/audit | Deterministic idempotency keys and proposal IDs; immutable get-or-create; status/revision CAS | Concurrent trigger/property tests produce one logical run/proposal |
| Malicious/invalid predicate | Tampering | Agent emits invented predicate or valid predicate for wrong endpoint types | Exact shared subject/predicate/object allowlist; canonical endpoint types; fail closed | Exhaustive vocabulary plus novel/case-confusion fixtures |
| Review bypass | Elevation | Client flips status to accepted or auto-policy silently broadens | Server state machine/CAS, separate review permission, immutable decisions, shadow default, versioned allowlist, reversible policy | Direct status mutation denied; stale review CAS rejected |
| Poisoned evidence | Tampering | Stale/untrusted source fabricates correlation | Source provenance, freshness deadline, trust ranking, corroboration for auto-accept, uncertainty, immutable evidence hash | Stale/single-source/contradictory fixtures remain review/rejected |
| Rollback failure | Availability/Tampering | Destructive rollback loses last valid graph or stale rollback wins | Retain immutable prior generation; rollback is fenced conditional pointer transition; record failed rollback; never delete active prior generation until retention allows | Inject rollback CAS/storage failure; active pointer remains valid |
| Lost audit event | Repudiation | Publication succeeds without durable attempt/decision lineage | Persist consequential audit/manifest before pointer promotion; fail closed if unavailable | Audit-store outage blocks promotion |
| Cancellation races | Tampering | Cancelled run continues into promotion | Durable cancel request checked at every safe boundary and in promotion preconditions; fence invalidation | Cancel during model call/stage; no active-pointer change |
| Trace disclosure | Information disclosure | Application Insights stores prompt/tool payload or unauthorized IDs | Server-side tracing with content capture minimized/redacted; scoped access and retention | Telemetry fixture scans emitted attributes |

## API, UI, Telemetry, and Deployment Recommendations

- Preserve `POST /subscription-connections/{id}/sync` as an authorized compatibility/run-now endpoint, but return a durable run reference and stop submitting a process-local worker. [VERIFIED: src/api/routers/connections.py:239-275]
- Add scope-filtered endpoints for run list/detail/cancel/retry, proposal list/detail/review/reverse, generation/attempt history, and rollback. Every mutation uses expected revision/ETag and idempotency key. [RECOMMENDATION]
- Extend the connections page instead of adding a parallel admin surface: current page already owns Sync and health polling. Replace the 20-minute browser-lifetime assumption with durable history/status, and show trigger, checkpoint, retry/deadline, proposal counts, validation, fence/generation, rollback, and degraded-agent state. [VERIFIED: web/src/app/connections/page.tsx:70-94,131-151]
- Add an `azurerm_container_app_job` in the existing ACA environment using the existing image and configuration pattern, with one finite command that invokes `run_once`; configure scheduled UTC cron, replica timeout/retry, `parallelism=1`, and completion count 1. Cross-scope concurrency may happen through separate claims, but same-scope publication remains serialized by storage controls. [CITED: https://learn.microsoft.com/en-us/azure/container-apps/jobs]
- Provision a distinct publisher user-assigned identity. The curator/Foundry project identity receives only the existing APIM MCP connection and allowed read tools; it receives no OneLake/Fabric publication role. [VERIFIED: infra/terraform/foundry.tf:415-486,684-714]
- Use Foundry server-side Application Insights tracing first; correlate `run_id`, `batch_id`, `proposal_id`, and `generation_id` using non-sensitive hashes. Add OpenTelemetry spans around due selection, claim, evidence, agent batch, validation, stage, promotion, and rollback. [CITED: https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept] [VERIFIED: uv.lock:3108-3115]
- Metrics: due backlog/oldest age, run duration/outcome/retries/timeouts/cancellations, lease contention/loss, CAS conflicts, incremental/full counts, agent calls/tokens/latency/failures, parse/rejection reasons, proposal precision/recall/citation/freshness, review age, generation validation, promotion/rollback outcome, stale-writer blocks, and audit completeness. [RECOMMENDATION]

## State of the Art

| Old/Current Repository Approach | Phase 13 Approach | Impact |
|---|---|---|
| Process-local `ThreadPoolExecutor` and live-run set | Durable run ledger plus ACA Job/run-once coordinator | Browser/process-independent recovery and scaling. [VERIFIED: src/onboarding/service.py:68-150,498-631] |
| Daemon-thread timeout | Cooperative boundaries plus fence-enforced inability to promote | Timed-out work cannot overwrite newer success. [VERIFIED: src/onboarding/sync.py:331-387] |
| Revision check plus unconditional upload | ETag `If-Match` CAS | Real cross-replica optimistic concurrency. [VERIFIED: src/storage/onelake_documents.py:134-177] [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage] |
| Infinite lease that can be broken immediately | Renewable finite lease plus monotonic fencing token | Prevents overlapping/stale authoritative writers. [VERIFIED: src/storage/onelake_writer.py:152-184] |
| Free-form line parser and random IDs | Whole-document strict schema and content identity | Auditability, idempotency, and fail-closed handling. [VERIFIED: src/fabric_pipelines/relationship_suggestion_parser.py:33-110] |
| Confidence + known-endpoint auto-promotion | Scope/vocabulary/type/evidence/freshness/contradiction/review policy | Safe advisory-to-authoritative boundary. [VERIFIED: src/fabric_pipelines/relationship_suggestion_promoter.py:98-133] |
| In-place multi-table writes/restore | Immutable candidate generation and conditional pointer promotion | Atomic reader-visible generation and reliable rollback. [VERIFIED: src/fabric/sync_service.py:365-524] |
| Fabric Data Agent suggestion scaffold | Existing Foundry prompt-agent/MCP governance path | Reuses deployed identity, tool, APIM, tracing, and versioning patterns. [VERIFIED: infra/terraform/foundry.tf:11-295] |

**Deprecated/outdated for this phase:**
- Treat `OneLakeDocumentStore` revision as distributed CAS. [VERIFIED: src/storage/onelake_documents.py:134-177]
- Use `OneLakeWriter.sync_lock()` as the sole single-writer guarantee. [VERIFIED: src/storage/onelake_writer.py:131-186]
- Use `parse_suggestions()` or `promote_suggestions()` as the production autonomy boundary. [VERIFIED: src/fabric_pipelines/relationship_suggestion_parser.py:33-110] [VERIFIED: src/fabric_pipelines/relationship_suggestion_promoter.py:98-133]
- Assume a timed-out Python thread has stopped. [VERIFIED: src/onboarding/sync.py:331-387]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---:|---:|---|
| `uv` | Python lock/test commands | ✓ | `0.10.9` [VERIFIED: environment probe, 2026-09-04] | — |
| Python | Backend/tests | ✓ | host `3.14.7`; project venv ran Python 3.11 packages | Project supports `>=3.11`. [VERIFIED: pyproject.toml:5-18] |
| Azure CLI | identity/deployment/live smoke | ✓ | `2.87.0` [VERIFIED: environment probe, 2026-09-04] | Terraform/data-plane scripts where applicable |
| Terraform | ACA Job/identity/Foundry provisioning | ✓ | `1.14.8` [VERIFIED: environment probe, 2026-09-04] | — |
| Docker | image/local deployment validation | ✓ | `29.7.2` [VERIFIED: environment probe, 2026-09-04] | — |
| Node | web validation | ✓ | `22.23.2` [VERIFIED: environment probe, 2026-09-04] | — |
| npm | web validation | ✓ | `10.9.8` [VERIFIED: environment probe, 2026-09-04] | — |

**Missing dependencies with no fallback:** none found. [VERIFIED: environment probe, 2026-09-04]  
**Missing dependencies with fallback:** Context7 research provider was unavailable, so current official Microsoft Learn pages were fetched directly and cited. [VERIFIED: research-plan execution, 2026-09-04]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | The exact Terraform provider/API shape chosen for conditional OneLake pointer writes can be implemented through the installed Azure storage SDK without a new dependency. [ASSUMED] | Safe Storage | May require a small adapter around the underlying Blob/Data Lake client; does not change architecture. |
| A2 | The deployed Fabric consumers can all be routed through an active-generation manifest/pointer abstraction rather than hard-coded mutable table names. [ASSUMED] | Publication | If any consumer cannot resolve generations, the planner must add a compatibility view/alias cutover before claiming atomicity. |
| A3 | The exact Foundry prompt-agent Responses path supports a sufficiently strict output-format option for the curator. [ASSUMED] | Curator | If not, whole-document local Pydantic validation still applies; malformed output becomes a rejected batch. |
| A4 | A dedicated publisher identity can be granted a narrower effective role than the current API identity for every required Fabric/OneLake operation. [ASSUMED] | Security/Deployment | Live RBAC granularity may require custom role design and a deployment checkpoint. |

## Open Questions (RESOLVED)

1. **Can every runtime consumer resolve an active generation rather than direct mutable table names? — RESOLVED**
   - What we know: `DatasetStore` already uses immutable generations and a current pointer for source snapshots. [VERIFIED: src/storage/datasets.py:36-45,183-215]
   - Decision: Inventory every API, Fabric, agent, export, and semantic consumer. Each must resolve one `GenerationResolver` active pointer or a versioned compatibility alias, and the same contract suite must pass before promotion, after promotion, and after rollback.
   - Gate: A blocking one-way-door decision checkpoint reviews the inventory and compatibility evidence before authoritative pointer promotion.

2. **What is the narrowest live Fabric/OneLake role set for the dedicated publisher? — RESOLVED**
   - What we know: Existing infrastructure uses managed identities and project/runtime roles. [VERIFIED: infra/terraform/foundry.tf:337-486,684-714]
   - Decision: Grant a distinct publisher only demonstrated stage, conditional pointer, ontology publish, and rollback actions. Remove authoritative stage/pointer grants and credentials from API, ACA Job/coordinator, and curator identities.
   - Gate: Terraform assertions and live denied-write attempts for all three non-publisher identities are mandatory, followed by a blocking publisher-RBAC evidence checkpoint. Manual Sync delegates through the publisher.

3. **Does the exact deployed Foundry agent path enforce structured output? — RESOLVED**
   - What we know: Prompt agents and Responses are supported; repository currently validates specialist text locally. [CITED: https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent] [VERIFIED: tests/test_operations_mcp_foundry.py:32-65]
   - Decision: Do not claim or depend on platform-enforced structured output. Require JSON in the versioned prompt, parse the whole response with strict local Pydantic validation, allow at most two sanitized repair attempts, and persist `invalid_agent_output` on failure.
   - Recommendation: Keep strict local Pydantic validation mandatory regardless; treat platform schema enforcement as defense in depth.

4. **When is a hosted agent justified? — RESOLVED**
   - What we know: Microsoft positions hosted agents for custom code/orchestration and prompt agents for managed production agents without it. [CITED: https://learn.microsoft.com/azure/foundry/agents/overview#agent-types]
   - Decision: The locked default remains the code-first prompt agent. A blocking checkpoint may select hosted only after executed proposal-generation evidence proves required agent-side multi-step protocol state, unavailable custom middleware, or custom runtime orchestration. Convenience and SDK ergonomics are insufficient; scheduling, admission, publication, and rollback remain deterministic in either case.

## Sources

### Primary (HIGH confidence)

- Repository source and tests cited inline, especially onboarding Sync, `DatasetStore`, OneLake documents/locks, Fabric sync, ontology contracts/validator, proposal scaffold, Foundry adapter, MCP registry, APIM policies, and Terraform.
- Executed baseline: 154 targeted backend tests and 9 connections-page tests passed on 2026-09-04. [VERIFIED: pytest/vitest commands executed 2026-09-04]

### Secondary (MEDIUM confidence)

- [Microsoft Foundry Agent Service overview](https://learn.microsoft.com/azure/foundry/agents/overview) — prompt versus hosted agents, identity, MCP, observability.
- [Prompt agent quickstart](https://learn.microsoft.com/azure/foundry/agents/quickstarts/prompt-agent) — prompt-agent creation/version and client pattern.
- [Responses API quickstart](https://learn.microsoft.com/azure/foundry/agents/quickstarts/responses-api) — Responses invocation.
- [MCP tool guidance](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol) — allowed tools, approvals, connections, and untrusted tool data.
- [Azure Container Apps Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs) — manual/scheduled/event jobs and finite execution settings.
- [Azure Storage concurrency](https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage) — ETag/`If-Match` and leases.
- [Foundry tracing](https://learn.microsoft.com/azure/foundry/observability/concepts/trace-agent-concept) — Application Insights and trace sensitivity.

### Tertiary (LOW confidence)

- Assumptions A1–A4 above require implementation or live-environment confirmation. [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — existing lock/config/source was read; no new package proposed. [VERIFIED: pyproject.toml:6-27] [VERIFIED: uv.lock:1-13]
- Architecture: HIGH — current end-to-end path and reusable repository seams were traced directly; recommended fencing follows official storage concurrency guidance. [CITED: https://learn.microsoft.com/en-us/azure/storage/blobs/concurrency-manage]
- Foundry service details: MEDIUM — current official Microsoft Learn pages were fetched directly because Context7 was unavailable. [VERIFIED: research-plan execution, 2026-09-04]
- Pitfalls: HIGH — each critical concurrency/parser/promotion issue is visible in current code and covered where noted by tests. [VERIFIED: tests/test_subscription_onboarding.py:840-875] [VERIFIED: tests/test_run_lock.py:1-12] [VERIFIED: tests/test_onelake_documents.py:1-8]

**Research date:** 2026-09-04  
**Valid until:** 2026-10-04 for repository patterns; recheck Foundry/ACA preview details immediately before infrastructure implementation.
