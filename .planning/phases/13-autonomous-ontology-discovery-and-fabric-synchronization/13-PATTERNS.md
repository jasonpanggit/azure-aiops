# Phase 13: Autonomous Ontology Discovery and Fabric Synchronization - Pattern Map

**Mapped:** 2026-09-04  
**Files classified:** 46 proposed new/modified files or fixture groups  
**Analogs found:** 45 / 46  
**Scope note:** `.planning/STATE.md:21-24,80-83` says execution is currently at Phase 03.5/03.6. This document is planning analysis only. Phase 13 implementation remains gated on its Phase 10 and Phase 12 dependencies.

## File Classification

The source documents prescribe package-level responsibilities more often than final filenames. The table below turns those responsibilities into the file inventory the planner should use. If planning consolidates a listed file, retain its assigned analog and invariants.

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/ontology_discovery/contracts.py` | model | transform | `src/operations/mcp_server.py` | exact role |
| `src/ontology_discovery/store.py` | store | CRUD/CAS | `src/intelligence/remediation/execution_store.py` | exact role; storage CAS must be strengthened |
| `src/ontology_discovery/coordinator.py` | service/coordinator | batch/event-driven | `src/intelligence/remediation/verification_coordinator.py` | exact |
| `src/ontology_discovery/incremental.py` | service | transform/batch | `src/ontology/ontology_sync.py` | role-match |
| `src/ontology_discovery/curator.py` | service | request-response | `src/operations/foundry_agent.py` | exact role |
| `src/ontology_discovery/policy.py` | service | transform/CAS | `src/fabric_pipelines/ontology_pipeline.py` | role-match |
| `src/ontology_discovery/publisher.py` | service | file-I/O/CAS | `src/storage/datasets.py` | strong partial |
| `src/ontology_discovery/prompts/ontology_curator.md` | config | transform | `infra/terraform/foundry.tf` specialist prompts | role-match |
| `src/ontology_discovery/telemetry.py` | utility | event-driven | `src/fabric/telemetry.py` | exact role |
| `src/storage/onelake_documents.py` | store | file-I/O/CAS | same file, lines 96-177 | migration seam, not a safe distributed-CAS implementation yet |
| `src/storage/datasets.py` | store | file-I/O/CAS | same file, lines 183-325 | migration seam; remote pointer is unconditional today |
| `src/storage/locking.py` | utility | event-driven/CAS | same file, lines 20-150 | role-match; add fencing rather than treating lease as fence |
| `src/ontology/ontology_validator.py` | service | transform | same file, lines 36-221 | exact extension |
| `src/ontology/pending_relationships.py` | store | CRUD | same file, lines 44-103 | exact behavior; persistence belongs in durable store |
| `src/fabric/dataset_mapper.py` | config/model | transform | `ONTOLOGY_RELATIONSHIP_TYPES`, lines 181-260 | exact authoritative vocabulary |
| `src/operations/mcp_server.py` | middleware/service | request-response | same file, lines 55-130,144-294 | exact extension |
| `src/operations/tools.py` | service registry | request-response | same file, lines 902-1010 | exact extension |
| `src/operations/foundry_agent.py` | service | request-response | same file, lines 298-337,340-533 | exact extension |
| `src/api/models.py` | model | request-response | same file, lines 149-171 | exact extension |
| `src/api/routers/ontology_discovery.py` | route/controller | request-response | `src/api/routers/connections.py` | exact role |
| `src/api/dependencies.py` | provider/config | request-response | same file, lines 110-139 | exact extension |
| `src/api/runtime.py` | provider/config | request-response | same file, lines 3076-3095,3235-3251 | exact extension |
| `src/api/app.py` | config | event-driven/request-response | same file, lines 201-255,285-320 | router registration only; do not add an API-owned scheduler |
| `src/api/routers/connections.py` | route/controller | request-response | same file, lines 239-275 | compatibility endpoint migration |
| `infra/terraform/foundry.tf` | config | provisioning | same file, lines 11-55,180-295,415-486,684-827 | exact extension |
| `infra/scripts/create-foundry-agent.sh` | utility/config | provisioning | same file, lines 33-59,75-179 | exact extension |
| `infra/terraform/ontology_discovery.tf` | config | scheduled batch | `infra/terraform/container_apps.tf` | role-match; no existing ACA Job |
| `infra/terraform/variables.tf` | config | provisioning | same file, lines 430-489 | exact style |
| `web/src/lib/types.ts` | model | request-response | same file, lines 1-66 | exact extension |
| `web/src/lib/services.ts` | service | request-response | same file, lines 96-210 | exact extension |
| `web/src/components/ontology/OntologyAutomationPanel.tsx` | component | request-response | `web/src/components/fabric/medallion.tsx` | exact role |
| `web/src/app/connections/page.tsx` | component/controller | request-response | same file, lines 41-68,153-319 | exact extension |
| `web/src/app/connections/page.test.tsx` | test | request-response | same file, lines 1-54,160-335 | exact extension |
| `scripts/evaluate_ontology_discovery.py` | utility/evaluator | batch | `scripts/evaluate_agents.py` | exact role |
| `evals/ontology-discovery/promptfooconfig.yaml` | config/eval | batch | none | no repository analog |
| `evals/ontology-discovery/reference.jsonl` | test fixture | batch | `tests/fixtures/*.json` conventions | partial |
| `tests/fixtures/ontology_discovery/*.json` | test fixture | batch | `tests/fixtures/mock_arg_responses.json` | partial |
| `tests/test_ontology_discovery_contracts.py` | test | transform | `tests/test_operations_mcp_foundry.py` | exact role |
| `tests/test_ontology_discovery_store.py` | test | CRUD/CAS | `tests/test_onelake_documents.py` | exact role |
| `tests/test_ontology_discovery_coordinator.py` | test | batch/event-driven | `tests/test_remediation_verification_coordinator.py` | exact role |
| `tests/test_ontology_discovery_incremental.py` | test | transform/batch | `tests/test_incremental_discovery.py` | exact role |
| `tests/test_ontology_curator_agent.py` | test | request-response | `tests/test_operations_mcp_foundry.py` | exact role |
| `tests/test_ontology_proposal_policy.py` | test | transform/CAS | `tests/test_relationship_vocabulary_consistency.py` | role-match |
| `tests/test_ontology_generation_publication.py` | test | file-I/O/CAS | `tests/test_run_lock.py` + `tests/test_ontology_publish_durability.py` | strong composite |
| `tests/test_api_ontology_discovery.py` | test | request-response | `web-independent API tests` in `tests/test_api_remediation_router.py` | role-match |
| `tests/test_ontology_discovery_evals.py` | test/evaluator | batch | `scripts/evaluate_agents.py` + existing deterministic tests | role-match |

## Pattern Assignments

### `src/ontology_discovery/contracts.py`

**Copy from:** `src/operations/mcp_server.py:55-80` for strict Pydantic input and `src/operations/foundry_agent.py:223-295` for fail-closed whole-document validation.

```python
class MCPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
```

```python
try:
    payload = json.loads(text)
except (TypeError, json.JSONDecodeError) as exc:
    raise FoundryAgentError(...) from exc
if not isinstance(payload, dict) or set(payload) != {"findings"}:
    raise FoundryAgentError(...)
```

Use `ConfigDict(extra="forbid")`, bounded fields/lists, explicit status literals, timezone-aware timestamps, and canonical IDs. Model output must not supply trusted tenant, subscription, policy, lifecycle, or publication fields.

### `src/ontology_discovery/store.py`

**Copy from:** `src/intelligence/remediation/execution_store.py:100-173,330-456,558-656`.

```python
identity = _execution_identity(plan_id, execution_snapshot)
with self._claim_lock():
    state = self._read_state()
    existing = next(
        (row for row in state["executions"]
         if str(row.get("execution_identity") or "") == identity),
        None,
    )
    if existing is not None:
        return copy.deepcopy(existing), False
```

```python
if (
    int(record.get("revision") or 0) != expected_revision
    or record.get("status") not in expected
):
    raise ExecutionClaimConflict("execution_claim_conflict", record)
```

Follow the deterministic get-or-create identity, append-only history, deep-copy read boundary, status-plus-revision transition, safe legacy defaults, and atomic local temp-file replacement patterns. Store immutable runs, batches, proposals, decisions, generations, and attempts separately from small mutable due/active pointers.

**Do not copy as distributed CAS:** `src/storage/onelake_documents.py:134-158` currently checks a JSON revision and then performs `upload_data(..., overwrite=True)` without an ETag condition. Phase 13 must make the service enforce `If-Match`/create-only conditions and return the observed ETag.

### `src/ontology_discovery/coordinator.py`

**Copy from:** `src/intelligence/remediation/verification_coordinator.py:34-119`.

```python
def run_once(self, now: datetime | None = None) -> dict[str, int]:
    moment = now or self._now()
    due = self._store.list_due_for_verification(now=moment)
    processed = errored = skipped_contended = 0
    for record in due:
        try:
            # Dispatch entirely from durable record state.
            ...
            processed += 1
        except ExecutionLockContended:
            skipped_contended += 1
        except Exception:
            errored += 1
            _LOGGER.exception(...)
    return {...}
```

Keep `run_once(now, limit)` free of FastAPI, HTTP, browser, and thread ownership. Query due records from storage, CAS-claim before work, dispatch from durable status/checkpoint, isolate failures per record, and return bounded counters. Manual and scheduled triggers create/claim the same run contract.

### `src/ontology_discovery/incremental.py`

**Copy from:** `src/ontology/ontology_sync.py:60-188`, `src/ontology/pending_relationships.py:44-103`, and `tests/test_incremental_discovery.py:16-79`.

```python
for previous in previous_entity_index.values():
    if previous["resource_id"] not in entities:
        entities[previous["resource_id"]] = _retire(
            previous, ontology_version, timestamp
        )
...
resolved_edges, pending_rows = pending_store.resolve(set(entities.keys()))
```

Retain deterministic normalization and row hashes. Extend the existing added/changed comparison with explicit retired, unresolved, and stale observations plus a durable full-reconciliation watermark. Persist pending rows through `store.py`; do not leave `PendingRelationshipStore._pending` as process memory.

### `src/ontology_discovery/curator.py`

**Copy from:** `src/operations/foundry_agent.py:298-337,340-533,739-812`.

```python
acquired = self._get_credential().get_token("https://ai.azure.com/.default")
...
payload = {
    "agent_reference": {"type": "agent_reference", "name": self.agent_name},
    "input": [{"role": "user", "content": prompt}],
    "max_output_tokens": 2_000,
}
response = self._post("/openai/v1/responses", payload, versioned=False)
```

Reuse managed identity, 60-second timeout, retryable-status allowlist, bounded exponential retry, circuit breaker, and response-text extraction. Context belongs in the user turn as bounded JSON; untrusted metadata never enters system instructions. Unlike the current synchronous adapter, the job path should be async end-to-end as required by `13-AI-SPEC.md`.

### `src/ontology_discovery/policy.py`

**Copy from:** `src/fabric_pipelines/ontology_pipeline.py:157-222`, `src/fabric/dataset_mapper.py:181-260`, and `src/ontology/ontology_validator.py:75-221`.

```python
existing = by_relationship_id.get(relationship_id)
if existing is not None:
    conflicts.append({
        "relationship_id": relationship_id,
        "resolution": "deterministic_kept",
    })
    continue
```

The exact `(subject_type, predicate, object_type)` allowlist must derive from `ONTOLOGY_RELATIONSHIP_TYPES`. Canonical endpoints, scope, citations, freshness, contradiction, corroboration, and policy version are server-derived. Preserve the deterministic-wins collision rule.

**Anti-pattern:** do not copy `src/fabric_pipelines/relationship_suggestion_promoter.py:98-133` as the acceptance boundary. It gates only on confidence and endpoint existence. Phase 13 starts in shadow mode.

### `src/ontology_discovery/publisher.py`

**Copy from:** `src/storage/datasets.py:217-325` for immutable staging and `src/ontology/ontology_validator.py:75-221` for fail-closed validation.

```python
stage = self.generations / f".{final.name}.staging-{uuid.uuid4().hex}"
try:
    ...
    stage.replace(final)
except Exception:
    shutil.rmtree(stage, ignore_errors=True)
    raise
```

Publish a complete immutable generation, manifest, validation report, source/proposal/decision lineage, and fencing token before visibility changes. Promotion and rollback are both conditional active-pointer transitions.

**Do not copy:** `DatasetStore._activate_generation()` at `src/storage/datasets.py:306-310` writes remote `current.json` unconditionally. Also do not copy the in-place multi-table rollback behavior in `src/fabric/sync_service.py:365-524` as the atomicity boundary.

### `src/storage/onelake_documents.py`, `src/storage/datasets.py`, `src/storage/locking.py`

These are infrastructure seams, not already-complete solutions.

- Preserve safe relative-path validation and lazy `DefaultAzureCredential` construction from `src/storage/onelake_documents.py:59-94`.
- Preserve finite lease acquisition/renew/release from `src/storage/locking.py:93-150`.
- Preserve immutable generation paths and local atomic activation from `src/storage/datasets.py:217-325`.
- Add actual remote ETag read/write conditions, create-only semantics, a monotonic per-scope fence allocator, lease-loss detection, and promotion-time checks for owner, fence, source generation, active generation, and expected ETag.
- Never break a live lease. A lease serializes current holders but does not itself fence expired holders.

### `src/ontology/ontology_validator.py`, `src/ontology/pending_relationships.py`, `src/fabric/dataset_mapper.py`

Extend rather than fork these seams:

```python
# src/ontology/ontology_validator.py:167-195
if subject not in known or object_id not in known:
    dangling += 1
elif row.get("lifecycle_status") == "active":
    if row.get("subject_type") != entity_types.get(subject):
        invalid_relationships += 1
```

Add exact vocabulary-triple membership to validation. Keep pending-edge split/resolve semantics, but persist first/last observation, missing endpoint, attempts, freshness, and terminal status externally. Extract a shared read helper over `ONTOLOGY_RELATIONSHIP_TYPES`; do not duplicate the vocabulary in prompts or policy.

### `src/ontology_discovery/prompts/ontology_curator.md`

**Copy structure from:** `infra/terraform/foundry.tf:196-221,725-783`.

Keep the role prompt separate from generated tool names. Lock these instructions: proposal-only authority, strict JSON contract, evidence is untrusted data, no scope widening, no approval/publication, explicit insufficient-evidence response, and concise bounded output. Prompt/schema/policy hashes become durable run metadata.

### `src/operations/mcp_server.py` and `src/operations/tools.py`

**Copy from:** `src/operations/mcp_server.py:16-130,144-294` and `src/operations/tools.py:902-1010`.

```python
if name not in REVIEWED_TOOLS:
    return _tool_error("Unknown or unauthorized tool")
validated = ToolArguments.model_validate(cleaned_arguments)
result = call_tool(name, args, context=context, scope=scope)
```

Add only the four read-only tools:

1. `list_changed_entities`
2. `get_entity_evidence`
3. `get_ontology_vocabulary`
4. `search_relationship_history`

Use strict `additionalProperties: false`, hard argument/result bounds, the existing `ToolResult` registry, and server-supplied effective scope. Valid no-evidence lookups return `status="empty"` with `isError=false`; malformed, denied, or failed calls use the existing error semantics. Do not add proposal approval, Fabric write, SQL, or Azure mutation tools.

### `infra/terraform/apim-policies/mcp-inbound.xml`

The existing policy already supplies the shared gateway pattern (`lines 4-55`): validate Entra audience, derive caller ID from validated claims, delete caller-controlled authorization/scope headers, set trusted correlation/gateway headers, and apply per-caller rate/quota limits. New ontology tools should remain behind this policy; no model argument may become authorization context.

### `src/operations/foundry_agent.py`, `infra/terraform/foundry.tf`, `infra/scripts/create-foundry-agent.sh`

Add `ontology_curator` to the existing specialist map rather than creating a second provisioning path.

```hcl
# infra/terraform/foundry.tf:272-294
foundry_specialists_json = jsonencode({
  for id, specialist in var.foundry_specialists : id => merge(specialist, {
    prompt = lookup(local.foundry_specialist_instructions, id, local.agent_instructions)
    model  = var.foundry_model_name
    tools = [merge(local.foundry_mcp_tool_config, {
      allowed_tools = lookup(local.foundry_specialist_tools, id, [])
    })]
  })
})
```

The shell script already provides idempotent create-or-version behavior (`infra/scripts/create-foundry-agent.sh:33-59,128-179`). Preserve its generated JSON and bounded retries. The curator gets only the Operations MCP project connection and no Azure MCP mutation/general query tool or publisher role.

### `infra/terraform/ontology_discovery.tf` and `infra/terraform/variables.tf`

**Closest pattern:** `infra/terraform/container_apps.tf:31-74,330-359` for environment, image, managed identity, ACR, and Application Insights settings.

Create one finite `azurerm_container_app_job` using the existing image and ACA environment, a UTC cron, `parallelism = 1`, completion count 1, bounded replica timeout/retry, and a command that invokes coordinator `run_once`. Create a distinct publisher user-assigned identity and grant only demonstrated OneLake/Fabric stage/promote operations. This category has no exact repository analog; verify provider syntax against the installed provider before planning.

### `src/api/models.py`

**Copy from:** `src/api/models.py:149-171`.

```python
class SoftwareMappingDecisionRequest(ApiModel):
    mapping_id: str = Field(min_length=1, max_length=160)
    expected_revision: int = Field(ge=0)
    reason: str = Field("", max_length=1024)
```

All review, cancel, retry, run-now, and rollback mutation bodies need bounded IDs/reasons plus `expected_revision` or ETag and an idempotency key where a new operation may be created.

### `src/api/routers/ontology_discovery.py`

**Copy from:** `src/api/routers/connections.py:45-72,79-93` for scope filtering and `src/api/routers/inventory.py:382-419` for review CAS.

```python
operate_scope = context.authorizer.effective_scope(principal, "operate", scope)
if service.detail(item_id, operate_scope) is None:
    raise ApiError(ErrorCode.NOT_FOUND, "No item matches this scope")
try:
    result = service.decide(..., expected_revision=payload.expected_revision)
except RevisionConflict as exc:
    raise ApiError(ErrorCode.CONFLICT, "The item changed; refresh before deciding", ...)
```

Return normal `envelope(...)` responses with evidence, effective scope, knowledge version, and pagination. Authorize the selected connection before every read or mutation and return not-found for out-of-scope records to avoid existence disclosure. Use separate review and operate permissions if the RBAC vocabulary provides them; never trust a client-projected eligibility flag.

### `src/api/routers/connections.py`

Preserve `POST /subscription-connections/{id}/sync`, its `OperatePrincipal`, `_authorize_action`, and response envelope (`lines 239-259`), but replace `context.onboarding.sync_async(...)` with durable run get-or-create/enqueue and return the durable run reference. Do not retain a separate process-local publication path.

### `src/api/dependencies.py`, `src/api/runtime.py`, `src/api/app.py`

Follow the optional provider wiring at `src/api/dependencies.py:127-139`, closure construction at `src/api/runtime.py:3076-3095`, and router registration at `src/api/app.py:285-320`.

Do **not** copy `_start_verification_coordinator()` (`src/api/app.py:201-255`) as Phase 13's production scheduler. It is useful only as a lifecycle/error-isolation example. The browser-independent trigger is the ACA Job; the API may expose run-now and status.

### `web/src/lib/types.ts` and `web/src/lib/services.ts`

Mirror Pydantic contracts closely and preserve the common envelope (`web/src/lib/types.ts:1-66`). Build scope-aware methods as in `web/src/lib/services.ts:120-210`:

```typescript
return apiRequest<Result>("/ontology-discovery/...", {
  method: "POST",
  query: scopeToSearchParams(scope),
  body: payload,
});
```

Every query and mutation carries `connection_id`; mutation requests carry expected revision/ETag and idempotency data.

### `web/src/components/ontology/OntologyAutomationPanel.tsx`

**Copy from:** `web/src/components/fabric/medallion.tsx:1-110,130-203,272-365,370-413`.

```tsx
const status = useApi(
  () => ontologyAutomationApi.status(connectionScope),
  [refreshKey, scopeKey],
);

{status.error ? (
  <StatePanel title="..." message="..." tone="error" />
) : status.loading ? (
  <StatePanel title="Loading ..." message="..." tone="loading" />
) : rows.length === 0 ? (
  <StatePanel title="..." message="..." />
) : (
  // Existing cards, badges, filters, pagination, and table classes.
)}
```

Fetch sections independently so one unavailable source does not blank durable generation/history data. Reuse `EvidenceBar`, `MetricCard`, `StatePanel`, `StatusBadge/statusTone`, `TableColumnFilters`, `TablePagination`, `StructuredData`, `operations-table`, `table-scroll`, and existing callout/button/form classes. Add no visual primitive or parallel design token.

### `web/src/app/connections/page.tsx`

**Copy from:** the existing tab/selector behavior at `web/src/app/connections/page.tsx:41-68,153-215,305-319`.

Extend the tab union with `"ontology-automation"`, add the required IDs from the UI spec, reuse one `PageHeader`, and key selection by `connection_id` rather than subscription ID. Default only to the first active in-scope connection, clear a selection that leaves scope, and render the ontology panel in the existing page.

Remove the browser-lifecycle assumption for ontology automation: `pollSyncState()` at lines 70-116 is not the lifecycle owner. Refreshing/polling may project durable status, but closing the page cannot alter or lose work.

### `web/src/app/connections/page.test.tsx`

**Copy from:** `web/src/app/connections/page.test.tsx:1-54,160-335`.

Use hoisted API mocks, `ScopeProvider`, role/tabpanel assertions, `within(panel)`, and explicit checks that every API call receives the selected effective scope. Add tests for selection invalidation, independent section failures, exact empty/degraded copy, server-projected disabled reasons, confirmation text, pagination/filtering, and active-run ordering.

### `src/ontology_discovery/telemetry.py`

**Copy from:** `src/fabric/telemetry.py:6-76`, `src/operations/gold_grounding_metrics.py:8-40`, and `src/api/telemetry.py:17-47`.

```python
meter = meter or metrics.get_meter("aiops.ontology_discovery", "0.1.0")
self.run_duration = meter.create_histogram(
    "ontology.discovery.run.duration", unit="s"
)
self.stale_writer_blocked = meter.create_counter(
    "ontology.discovery.publication.stale_writer_blocked"
)
```

Use low-cardinality enums/counts only. Never attach prompts, evidence/tool bodies, resource IDs, principal IDs, raw errors, or scope values. Correlation IDs in traces should be opaque/hashes. Keep Foundry server-side tracing for agent internals and add application spans around due selection, claim, evidence, batch, policy, validation, stage, promotion, and rollback.

### `scripts/evaluate_ontology_discovery.py`

**Copy from:** `scripts/evaluate_agents.py:1-98,291-362,365-465,503-588`.

Follow the dataclass-per-case/result pattern, bounded retry handling, deterministic aggregation, baseline-before-output ordering, `argparse`, optional artifact write, and non-zero exit on a release-gate failure. Unlike `evaluate_agents.py`, support both recorded/offline fixtures and an explicitly credentialed deployed mode. Compute exact precision/recall and slice results by predicate, type pair, resource family, and source status.

### `evals/ontology-discovery/promptfooconfig.yaml`, `evals/ontology-discovery/reference.jsonl`, and `tests/fixtures/ontology_discovery/*.json`

No Promptfoo configuration exists in the repository. Use the AI spec as the primary contract. Keep fixtures versioned, synthetic/redacted, deterministic, and complete enough to replay scope, evidence IDs/times, source generation, vocabulary, expected/forbidden edges, disposition, allowed tools, normalized hash, and publication outcome. Start with at least the 32 scenario bundles and 100 candidate pairs specified by `13-AI-SPEC.md:601-629`.

## Test Pattern Assignments

| New Test | Copy Structure From | Required Emphasis |
|---|---|---|
| `tests/test_ontology_discovery_contracts.py` | `tests/test_operations_mcp_foundry.py:32-65` | Valid whole JSON; reject prose, extra fields, unknown citations, out-of-scope IDs, mutation instructions |
| `tests/test_ontology_discovery_store.py` | `tests/test_onelake_documents.py:23-43,94-123,126-192` | Local/remote parity, two independent clients, create-only and stale ETag conflicts, no partial reads |
| `tests/test_ontology_discovery_coordinator.py` | `tests/test_remediation_verification_coordinator.py:34-114` | Durable-state dispatch, restart with zero memory, duplicate trigger, per-record isolation, cancellation/deadline |
| `tests/test_ontology_discovery_incremental.py` | `tests/test_incremental_discovery.py:16-79` | Stable hashes, add/change/retire/unresolved/stale, full-reconcile parity |
| `tests/test_ontology_curator_agent.py` | `tests/test_operations_mcp_foundry.py:32-65` | Four-tool allowlist, scope isolation, bounded calls/output, empty-vs-error, schema-repair limit |
| `tests/test_ontology_proposal_policy.py` | `tests/test_relationship_vocabulary_consistency.py:22-45` | Exhaustive exact triple checks, deterministic IDs, deterministic-wins conflicts, review CAS, shadow default |
| `tests/test_ontology_generation_publication.py` | `tests/test_run_lock.py:88-155`; `tests/test_ontology_publish_durability.py:207-260` | Lease renewal/loss, monotonic fence, stale writer rejection, pointer CAS, partial stage, rollback failure |
| `tests/test_api_ontology_discovery.py` | `src/api/routers/inventory.py:382-419` behavior | Scope-filter list/detail, not-found non-disclosure, review/retry/cancel/rollback conflicts and envelopes |
| `tests/test_ontology_discovery_evals.py` | `scripts/evaluate_agents.py:440-488,503-588` | Deterministic replay, isolation/injection, precision/recall slices, cost/latency caps, audit completeness |

## Shared Patterns

### Durable State and CAS

**Sources:** `src/intelligence/remediation/execution_store.py:100-173,342-456,558-656`; `src/storage/onelake_documents.py:134-177`.

- Deterministic identity before side effects.
- Immutable transition/attempt history.
- Status plus revision/ETag CAS.
- Explicit conflict exceptions translated to HTTP 409.
- Atomic local replacement and service-enforced remote `If-Match`.
- Never use `put()`/last-writer-wins for runs, decisions, fences, or active generation.

### Run Locks and Fencing

**Source:** `src/storage/locking.py:20-150`.

- Finite lease, renewal, explicit loss, and natural expiry.
- Add a monotonic fencing token and verify it immediately before promotion.
- Check cancellation, source generation, and active-pointer ETag at every consequential boundary.
- Never assume timeout stopped work and never break a non-expired peer lease.

### Authentication and Scope

**Sources:** `src/api/routers/connections.py:45-72`; `infra/terraform/apim-policies/mcp-inbound.xml:4-55`.

- Derive effective scope from authenticated identity.
- Filter before model access and before mutation.
- Return not-found for out-of-scope object IDs.
- Delete caller-controlled identity/scope headers at APIM.
- Separate curator, reviewer/operator, and publisher authority.

### Errors and Degradation

**Sources:** `src/operations/foundry_agent.py:439-496`; `src/intelligence/remediation/verification_coordinator.py:80-119`.

- Retry only transient transport/status failures with bounded backoff.
- Isolate one record/batch failure from the rest of a run.
- Agent failure records a degraded advisory batch but does not fail deterministic refresh.
- Validation, audit, lease, fence, or pointer-precondition failures block publication.
- Persist safe machine-readable failure class; bound/redact human-readable error text.

### Ontology Authority

**Sources:** `src/fabric_pipelines/ontology_pipeline.py:48-87,157-222`; `src/ontology/ontology_sync.py:60-188`; `src/fabric/dataset_mapper.py:181-260`.

- Existing `EntityBuilder` and `RelationshipBuilder` remain authoritative.
- Deterministic edges win collisions.
- Proposed edges remain advisory until deterministic policy/review admits them.
- Full graph validation happens after merging and before staging/promotion.

### UI State

**Sources:** `web/src/components/fabric/medallion.tsx:40-110,130-203,272-365`; `web/src/app/connections/page.tsx:153-319`.

- One page header and an accessible tab/tabpanel pair.
- Scope-filtered connection selector.
- Independent section loading/error/empty states.
- Existing status vocabulary, cards, filters, pagination, tables, callouts, and buttons.
- Server eligibility and disabled reasons are authoritative.

## No Exact Analog Found

| File/Capability | Reason | Planner Direction |
|---|---|---|
| True OneLake ETag CAS in `src/storage/onelake_documents.py` / `src/storage/datasets.py` | Existing remote writes are unconditional after client-side revision checks | Add an Azure Data Lake SDK conditional-write adapter and concurrency tests using independent clients |
| Monotonic fencing token allocation | `RunLock` has a renewable lease but no fence counter | Allocate under CAS in the durable per-scope pointer; stamp and recheck every publication |
| `infra/terraform/ontology_discovery.tf` ACA Job | Repository has long-lived Container Apps only | Adapt image/environment/identity/env conventions from `container_apps.tf`; validate job resource syntax |
| `evals/ontology-discovery/promptfooconfig.yaml` | No Promptfoo integration exists | Follow `13-AI-SPEC.md`; keep it CI/offline and avoid third-party production data export |

## Anti-Patterns the Planner Must Name Explicitly

1. Do not keep API `ThreadPoolExecutor` Sync as a second scheduler.
2. Do not claim `OneLakeDocumentStore.write()` is distributed CAS until the storage service receives an ETag condition.
3. Do not equate a renewable lease with fencing.
4. Do not publish in-place tables and call compensating rollback atomic.
5. Do not use free-form suggestion parsing or confidence-only promotion.
6. Do not let the agent, MCP tools, browser, or broad API identity publish Fabric.
7. Do not duplicate the relationship vocabulary.
8. Do not log prompts, tool bodies, evidence payloads, raw resource IDs, or scope values.

## Metadata

**Analog search scope:** `src/storage`, `src/intelligence/remediation`, `src/ontology`, `src/fabric`, `src/fabric_pipelines`, `src/operations`, `src/api`, `infra`, `web/src`, `scripts`, `tests`  
**Primary analogs read:** 27 source/config/test files  
**Pattern extraction date:** 2026-09-04
