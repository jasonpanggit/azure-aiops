# Phase 11: Cross-Page Operations Copilot Orchestration and Specialist Parity - Pattern Map

**Mapped:** 2026-09-03  
**Requirements:** COP-01 through COP-05  
**Files analyzed:** 31 implementation, infrastructure, and test files  
**Scope check:** `.planning/STATE.md` currently names Phase 03.2 as active, but also records Phase 11 in the roadmap evolution. This document is the explicitly requested Phase 11 planning input; no source files were changed.

The phase context locks concerns rather than exact target paths. Paths marked **likely new** below are planner-facing placement recommendations based on the current package layout.

## File Classification

| New/Modified File or Concern | Role | Data Flow | Closest Existing Analog | Match |
|---|---|---|---|---|
| `src/operations/orchestration_contract.py` (**likely new**) | model | request-response / transform | `src/operations/page_context.py` (`SnapshotModel`, `PageSnapshot`) | exact role |
| `src/operations/orchestration_policy.py` (**likely new**) | service / policy | transform | `src/operations/mcp_server.py` (`MCPServer.handle`) | exact flow |
| `src/operations/orchestration_service.py` (**likely new**) | service | request-response / event-driven | `src/operations/autonomous_investigation.py` (`run_context_investigation`) | exact flow |
| `src/api/routers/copilot.py` | router | request-response | its existing `investigate`, `investigate_context`, `history` routes | exact |
| `src/api/routers/multi_agent.py` | compatibility router | request-response / CRUD | its existing ledger routes | exact |
| `src/operations/page_context.py` | model / utility | transform | current snapshot v1 and deterministic findings | exact |
| `src/operations/specialist_manifest.py` plus a versioned manifest data file (**likely new**) | config / model | transform | `AgentDefinition`, `AGENTS`, and Terraform specialist locals | partial |
| `src/operations/foundry_agent.py` | provider / service | request-response | `SPECIALIST_IDS`, `_agent_contract`, `specialist_catalog` | exact |
| `src/operations/autonomous_investigation.py` | service / ledger | event-driven / batch | `AgentDefinition`, bounded delegation, reconciliation | exact |
| `src/operations/tools.py`, `src/operations/mcp_server.py` | registry / middleware | request-response | `TOOL_REGISTRY`, `REVIEWED_TOOLS`, `call_tool` | exact |
| `infra/terraform/foundry.tf`, `infra/terraform/variables.tf` | config | transform / deployment | generated `foundry_specialists_json` | exact |
| `web/src/lib/types.ts`, `web/src/lib/services.ts` | model / API client | request-response / transform | current Copilot types and snapshot builder | exact |
| `web/src/lib/copilot/page-adapters.ts` (**likely new**) | registry / utility | transform | `buildCopilotSnapshot` plus route-local builders | partial |
| `web/src/components/ui/CopilotDrawer.tsx` | component | request-response / event-driven | current drawer | exact |
| Eligible `web/src/app/**/page.tsx` routes | component | request-response / transform | `/`, `/network`, `/exposure`, `/compliance`, `/situations` | exact |
| `src/operations/investigation_thread_store.py` (**likely new**) | store | CRUD / file-I/O | `InvestigationLedgerStore`; `ConversationStore` | exact |
| Continuity API routes in `src/api/routers/copilot.py` | router | CRUD / request-response | multi-agent ledger GET/action routes | exact |
| `tests/test_orchestration_*.py`, `tests/test_page_context.py` | test | request-response / transform | Copilot snapshot, routing, and MCP suites | exact |
| `web/src/lib/copilot/page-adapters.test.ts`, route integration tests (**likely new**) | test | transform / request-response | `CopilotPageIntegrations.test.tsx`, `CopilotDrawer.test.tsx` | exact |
| `scripts/evaluate_agents.py`, versioned evaluation dataset (**dataset likely new**) | evaluation / batch | batch / request-response | inline `Case` corpus and baseline comparison | exact script, partial dataset |
| Snapshot/endpoint compatibility adapters | migration | transform | `RemediationExecutionStore._with_defaults`; existing rollback adapter tests | role match |

## Pattern Assignments

### COP-01 — Unified request/result contract and governed orchestration

#### Request/result models

**Copy from:** `src/operations/page_context.py`

Strict base model and bounded fields (`SnapshotModel`, lines 55-56; `PageSnapshot`, lines 99-124):

```python
class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class PageSnapshot(SnapshotModel):
    version: Literal["1"] = "1"
    evidence: list[EvidenceRow] = Field(default_factory=list, max_length=MAX_EVIDENCE_ROWS)
    question: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_snapshot(self) -> PageSnapshot:
        if len(self.model_dump_json()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("page snapshot exceeds size limit")
        return self
```

Use this style for one canonical `InvestigationRequest` and `InvestigationResult`: strict extras, explicit versions, bounded strings/lists, and validation at model construction. Do not return an untyped union of the current standalone result, contextual ledger, and autonomous ledger.

**Result shape anchor:** `src/operations/autonomous_investigation.py:935-971`. Preserve:

- server-generated `ledger_id`;
- principal and effective `scope`;
- orchestration decision;
- selected agents and tool calls;
- findings and citations;
- explicit synthesis mode/warnings;
- evaluation counters without hidden reasoning.

#### Router boundary and compatibility endpoints

**Copy from:** `src/api/routers/copilot.py:235-307` and `310-359`.

```python
def investigate(
    payload: InvestigationRequest,
    context: Context,
    scope: ReadScope,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    investigation = run_investigation(
        payload.question.strip(), context=context, scope=scope, ...
    )
    conversation_store().record(payload.session_id, principal.subject, investigation)
    return envelope(
        investigation.to_dict(),
        evidence=evidence,
        scope=scope.to_dict(),
        warnings=list(investigation.warnings),
    )
```

Keep `Context`, `ReadScope`, and `CurrentPrincipal` dependency injection. Legacy `/copilot/investigate`, `/copilot/investigate-context`, and `/agents/investigations` should become thin request/result adapters into the same service, not retain separate planning loops.

**Error pattern:** `src/api/routers/copilot.py:321-329` converts boundary validation failures to `ApiError(ErrorCode.INVALID_REQUEST, ..., details={"field": ...})`. `src/api/routers/multi_agent.py:76-105` returns `NOT_FOUND` for a principal-scoped miss, avoiding existence disclosure.

#### Deterministic plan validation

**Copy from:** `src/operations/mcp_server.py:144-226` and `src/operations/tools.py:1061-1076`.

```python
if name not in REVIEWED_TOOLS:
    return _tool_error("Unknown or unauthorized tool")
if not isinstance(arguments, Mapping) or not _safe_size(arguments, MAX_ARGUMENT_BYTES):
    return _tool_error("Invalid or oversized tool arguments")
validated = ToolArguments.model_validate(cleaned_arguments)
missing = [field for field in _REQUIRED.get(name, ()) if field not in args]
```

The orchestration policy should similarly validate, in deterministic code:

1. every specialist ID exists in the manifest;
2. every requested tool is granted to that specialist and exists in its server registry;
3. requested scope is no wider than `ReadScope`;
4. specialist count, tool count, wall clock, and dependency depth stay within budgets;
5. dependencies exist and are acyclic;
6. production mutation tools/actions are rejected;
7. evidence and entity references belong to the request;
8. executive synthesis is admitted only for explicit executive or cross-domain intent.

Unknown entries should be denied, not “corrected” by the model. Missing optional provider evidence should be represented as `empty`, `unavailable`, or `denied`, not converted to a transport failure.

#### Safe deterministic fallback

**Copy from:** `src/operations/maf_orchestrator.py:23-38,60-109`.

`OrchestrationDecision` already provides a serializable decision boundary, and `select_specialists_for_turn` is the safe keyword fallback. Keep it as fallback only. A coordinator-produced candidate plan must pass the same policy and produce the same result type.

**Tests to copy/extend:**

- `tests/test_api_copilot_investigation.py::test_investigation_rejects_unknown_tool_hint`
- `tests/test_api_copilot_investigation.py::test_investigation_degrades_when_agent_fails`
- `tests/test_api_copilot_investigation.py::test_history_is_isolated_per_principal`
- `tests/test_context_specialist_routing.py::test_selection_never_exceeds_the_specialist_budget`
- `tests/test_context_specialist_routing.py::test_every_selected_id_is_a_real_agent`
- `tests/test_api_copilot_snapshot.py::test_context_route_maf_mode_delegates_by_question_not_page`

Add adversarial candidate plans covering unknown specialist, cross-specialist tool theft, widened scope, cyclic dependencies, excess budgets, mutation requests, and invalid citations.

---

### COP-02 — Typed page-adapter registry and route integration

#### Frontend contract and adapter output

**Copy from:** `web/src/lib/types.ts:2451-2475` and `web/src/lib/services.ts:405-460`.

The current split is the right layering:

- shared wire types in `types.ts`;
- a pure builder in `services.ts`;
- route components supply visible records and provider envelopes;
- the drawer submits the completed snapshot.

Move route-specific construction into a typed adapter registry. Each registry entry should define:

- route/page-kind match and explicit eligibility/exclusion;
- selected entity mapping;
- evidence sections and priority;
- filters and visible/total coverage;
- freshness/source availability mapping;
- starter questions as orchestration hints;
- default specialist hints.

The builder must stay pure and bounded. Preserve `copilotEvidenceRows`’ status propagation, but replace index-only identities where a stable source identity exists.

#### Page component integration

**Closest examples:**

- `web/src/app/page.tsx:163-183` — cross-domain overview evidence.
- `web/src/app/network/page.tsx:181-214` — selected ARM entities, active-tab filter, domain evidence, and starter hints.
- `web/src/app/exposure/cves/[id]/page.tsx` — detail-page contextual drawer.

Route components should call one adapter with already-loaded page data, then render `CopilotDrawer`. They should not duplicate page-kind literals, evidence IDs, truncation, freshness rules, or starter specialist mapping.

Current integrated routes confirmed by imports are only:

`/`, `/network`, `/compliance`, `/exposure`, `/exposure/cves/[id]`, `/situations`.

The registry coverage test must account for all 28 route files and encode tested dispositions for `/vulnerabilities` redirect and any approved utility/search exclusions.

#### Drawer request flow

**Copy from:** `web/src/components/ui/CopilotDrawer.tsx:118-178`.

Preserve immutable per-turn snapshot capture, warning deduplication, explicit deterministic/partial/error stages, and direct evidence display when narration is unavailable.

Change the current branch at lines 130-132: contextual turns call `investigateContext(submittedSnapshot)`, so starter `tool` and `toolArguments` are ignored whenever a snapshot exists. In the unified contract they must be typed **hints** passed through policy, never a direct bypass.

#### Page and drawer tests

**Copy from:**

- `web/src/components/ui/CopilotPageIntegrations.test.tsx:4-60`
- `web/src/components/ui/CopilotDrawer.test.tsx:25-135`
- `web/src/app/compliance/page.test.tsx:136`

Keep assertions for exact submitted snapshot, cited deterministic fallback, duplicate warning suppression, and no duplicated narration/finding cards. Expand the integration test from six hard-coded examples to the registry itself:

- every eligible route has one adapter;
- every route has exactly one disposition;
- route aliases/redirects cannot create duplicate adapters;
- each adapter emits stable page/entity/evidence identity;
- partial pages report visible versus total counts;
- stale/unavailable evidence cannot become actionable;
- starter hints reach the unified request.

---

### COP-03 — Versioned specialist manifest and Foundry/tool parity

#### Runtime specialist definition

**Copy from:** `src/operations/autonomous_investigation.py:47-89`.

```python
@dataclass(frozen=True)
class AgentDefinition:
    id: str
    name: str
    role: str
    tools: tuple[str, ...]
    keywords: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    contract_version: str = SPECIALIST_CONTRACT_VERSION
```

Extend the manifest schema rather than adding more parallel constants. It must contain purpose, intent examples, dependencies, Operations MCP grants, Azure MCP grants, knowledge policy, page mappings, output schema, UI metadata, Foundry name/model/version, and contract version.

#### Current generation pattern

**Copy from:** `infra/terraform/foundry.tf:176-221,272-290`.

`foundry_specialist_tool_guide` and `foundry_specialists_json` demonstrate the desired derivation pattern: prompts and actual `allowed_tools` come from the same maps. Preserve generation; change the source to the versioned manifest or validate Terraform projections against it.

**API/UI catalog pattern:** `src/operations/autonomous_investigation.py:81-89` joins runtime definitions with `specialist_catalog()` deployment status. `src/operations/foundry_agent.py:815-835` reports configured name/version/status without claiming absent agents are ready.

#### Concrete drift to eliminate

| Drift | Evidence |
|---|---|
| Patch runtime/Foundry mismatch | `AGENTS` grants patch `cve_exposure` and `remediation_plans` (`autonomous_investigation.py:72`); Terraform patch gets generic context only (`foundry.tf:40`). |
| Change mismatch | Runtime grants `incidents` and `search` (`autonomous_investigation.py:74`); Terraform change is generic-only (`foundry.tf:44`). |
| Governance mismatch | Runtime includes `risk_context` (`autonomous_investigation.py:75`), but `REVIEWED_TOOLS` omits it (`mcp_server.py:30-52`). |
| Registry/MCP mismatch | `TOOL_REGISTRY` includes `inventory_resources`, `search`, and `risk_context` (`tools.py:902-1058`), while `REVIEWED_TOOLS` does not. |
| Portfolio mismatch | `SPECIALIST_IDS`, `AGENTS`, Terraform variables, role prompts, and UI catalog contain eight agents; the four Phase 11 domains are absent. |

Add Inventory & Data Health, Identity & Access, FinOps, and Resource Health & Observability to the manifest once, then derive/validate all projections.

#### Validation tests

**Copy from:**

- `tests/test_foundry_tool_registry_matches_implementation.py:36-78`
- `tests/test_foundry_agent.py::test_specialist_catalog_has_independent_names_and_versions`
- `tests/test_foundry_agent.py::test_all_specialist_agents_have_distinct_ids_and_versions`
- `tests/test_context_specialist_routing.py::test_every_selected_id_is_a_real_agent`

The existing Terraform regex test is a useful migration guard, but the final parity gate should load structured manifest data and compare exact sets across runtime definitions, Operations MCP, Azure MCP grants, Foundry projection, API catalog, page mappings, and UI cards. A permissive subset check is insufficient for grants.

---

### COP-04 — Evidence snapshot v2

#### Backend model and authorization

**Copy from:** `src/operations/page_context.py:24-157`.

Preserve:

- browser input is untrusted;
- `extra="forbid"`;
- byte/list bounds;
- canonical identity-derived authorization;
- declared scope cannot exceed effective scope;
- evidence references must resolve;
- canonical, sorted hash over the validated model.

Snapshot v2 should add a discriminated stable `EntityRef` for ARM and non-ARM entities rather than overloading `resource_id`. The v1 workaround in `web/src/lib/services.ts:424-434` removes non-ARM selected entities and moves their IDs into arbitrary `data`; do not carry that loss into v2.

Add explicit:

- `visible_count`, `total_count`, and coverage state;
- evidence priority and deduplication key;
- source freshness/quality;
- conflicts and uncertainty;
- retained citation references;
- insufficiency rules.

#### Deterministic evidence semantics

**Copy from:** `deterministic_network_findings` in `src/operations/page_context.py:160-233`.

This is the strongest local pattern for:

- downgrading verified findings when freshness is degraded;
- retaining `source_status`;
- making actionable status deterministic;
- deduplicating by entity/check/normalized summary;
- merging citation IDs rather than dropping duplicates.

Generalize these mechanics; do not generalize network check IDs or network-only sections.

**Tests to copy/extend:**

- all tests in `tests/test_page_context.py`
- `tests/test_api_copilot_snapshot.py::test_context_route_rejects_unknown_version_and_wider_scope`
- `::test_context_route_preserves_freshness_warning_and_downgrades_finding`
- `::test_context_route_rejects_out_of_scope_evidence_identity`
- `web/src/components/ui/CopilotPageIntegrations.test.tsx::keeps non-Azure page identifiers...`

Add v2 tests for non-ARM stable IDs, priority retention at bounds, duplicate merge, visible/total mismatch, conflict retention, stale continuity evidence, and citation rejection after truncation.

---

### COP-05 — Continuity, conditional executive synthesis, telemetry, and evaluations

#### Principal-scoped continuity store

**Volatile state analog:** `src/operations/investigation.py:383-454` (`ConversationStore`).

It demonstrates principal checks, per-thread turn bounds, global LRU bounds, TTL, and locking. Do not copy its process-only durability or session-ID-only map key: another principal reusing a session ID replaces the prior state even though it cannot read it.

**Durable audit analog:** `src/operations/autonomous_investigation.py:1014-1154` (`InvestigationLedgerStore`).

Copy:

- a structural `LedgerDocumentStore` protocol;
- one document per server-generated ledger/thread;
- write-through persistence and bounded read-through cache;
- identity revalidation after document load;
- principal check after rehydration;
- local-memory fallback with explicit durability state.

`tests/test_investigation_ledger_store.py` is the template suite. Especially copy:

- `test_ledger_survives_process_restart`
- `test_principal_scoping_survives_rehydration`
- `test_corrupt_document_is_not_served_as_a_ledger`
- `test_storage_outage_does_not_fail_the_investigation`
- `test_each_ledger_is_its_own_document`

Continuity must additionally bind each carried evidence item to original scope, observed time, snapshot hash/version, and stale/current status. Navigation may retain context but must not silently treat old evidence as current or widen scope.

**Wiring anchor:** `src/api/runtime.py:2588-2595` attaches OneLake storage once during context construction.

#### Conditional executive synthesis

**Aggregation analog:** `src/operations/autonomous_investigation.py:662-703` reconciles specialist runs and passes one computed synthesis into the executive ledger record.

Do **not** copy its unconditional line 664-665 executive invocation. Phase 11 requires an explicit deterministic predicate based on cross-domain selection or executive intent. Synthesis input must be cited specialist outputs, not raw hidden reasoning, and the output must be validated against retained citations.

#### Telemetry and privacy

**Copy from:** `src/api/routers/copilot.py:278-288`.

Audit low-cardinality orchestration facts—principal subject, selected specialist/tool IDs, statuses, fallback reason, duration, budget exhaustion, contract versions—without logging question text, tool arguments, raw evidence, tokens, or chain-of-thought.

#### Evaluation script and dataset

**Copy from:** `scripts/evaluate_agents.py`.

- `Case` (`75-98`) is the typed case pattern.
- `_run_case` (`365-437`) distinguishes transient harness failures, routing misses, and wall-clock timeouts.
- `_aggregate` (`440-465`) keeps routing, narration, groundedness, tool correctness, latency, and runtime counts separate.
- `main` (`503-584`) supports filtered runs, immutable result artifacts, baseline comparison, and a nonzero routing-regression exit.

Move/extend the inline `CASES` corpus into a versioned dataset so page kind, route, scope, expected specialists/tools, provider state, continuity steps, expected citations, latency/cost limits, and release thresholds are reviewable as data.

**Unit evaluation anchors:**

- `tests/test_copilot_evaluation.py` — groundedness, scope isolation, tool selection, citations, latency, prompt injection, unknown tools.
- `tests/test_context_evaluation_metrics.py` — comparable contextual metrics and `None` for unmeasured, not false zero.
- `.planning/eval/gold-grounding-baseline.json` — preserve degraded real baseline rather than fabricating a pass.

Add route-to-adapter coverage, exact tool-grant parity, stale/partial/unavailable behavior, two-navigation continuity, scope narrowing, conditional executive usage, per-stage latency, token/cost budget, and release-threshold assertions.

## Compatibility Migration Pattern

1. Define the canonical v2 request/result and orchestration service first.
2. Convert every old request at the router boundary.
3. Execute only the canonical service.
4. Project the canonical result back only where an old client requires its legacy shape.
5. Include contract/snapshot versions in persisted records and telemetry.
6. Test old and new endpoints for equivalent policy decisions and evidence.

**Copy from:** `src/intelligence/remediation/execution_store.py:149-167,430-476,561-575`.

- `create()` is a thin backward-compatible adapter into `create_or_get()`.
- `_with_defaults()` upgrades older persisted records on read.
- writes stamp `_SCHEMA_VERSION`.
- file writes are atomic (`mkstemp`, `fsync`, `os.replace`).

Also retain the explicit rollback seam tested by `tests/test_api_multi_agent.py::test_deterministic_rollback_uses_rest_foundry_adapter`, but do not let rollback mode create a second contract or bypass policy.

## Shared Patterns

### Authentication and scope

**Sources:** `src/api/routers/copilot.py:235-240,314-335`; `src/api/routers/multi_agent.py:58-70,76-85`.

All reads and writes receive `CurrentPrincipal` and effective `ReadScope`. Principal identity scopes persistence; effective scope validates every entity/tool call. A browser-provided `authorized: true` flag is never authority by itself.

### Safe provider degradation

**Sources:** `src/api/routers/copilot.py:174-193`; `src/operations/autonomous_investigation.py:923-934`.

Optional narration/provider failure adds a warning while deterministic evidence remains visible. Preserve distinct `empty`, `unavailable`, `denied`, `partial`, and `stale` states.

### Response envelopes and evidence

**Sources:** `src/api/routers/copilot.py:290-307`; `src/api/routers/multi_agent.py:35-50`.

Return `envelope(data, evidence=..., scope=..., warnings=...)`. Narration confidence cannot exceed its grounding evidence.

### Bounded execution

**Sources:** `src/operations/mcp_server.py:161-174`; `src/operations/autonomous_investigation.py:35-40,788-800`.

Enforce byte, call, specialist, step, dependency, and wall-clock limits before execution. Return explicit partial/budget status; do not simply leave an HTTP request hanging.

## Anti-Patterns to Avoid

1. **Three planners behind three endpoints.** All surfaces must call one orchestration service.
2. **Model output as authorization.** Coordinator plans are proposals; deterministic policy decides.
3. **Starter tools as bypasses.** Treat them as validated hints.
4. **Route-local snapshot construction.** Use the adapter registry.
5. **`resource_id` for every identity.** Non-ARM entities need typed stable references.
6. **“200 rows means complete.”** Always expose visible/total coverage.
7. **Parallel specialist truth sources.** Do not separately edit `SPECIALIST_IDS`, `AGENTS`, Terraform, prompts, API cards, and UI metadata.
8. **Subset-only parity tests.** Exact grants and forbidden mutation tools must be checked.
9. **Unconditional executive calls.** Invoke only for cross-domain or explicit executive intent.
10. **Session ID as sole persistence key.** Bind ownership to principal and re-check after rehydration.
11. **Carrying stale evidence as current.** Preserve observation time and force uncertainty/recheck.
12. **Logging prompts, raw tool arguments, evidence, or hidden reasoning.**
13. **Blank UI on Foundry/Fabric/Search/Azure MCP failure.** Return deterministic evidence with explicit uncertainty.
14. **Autonomous mutation or approval inference.** Handoffs may be prepared; existing server-side approval/execution remains authoritative.
15. **LLM-as-judge as the only release gate.** Prefer deterministic routing, grants, citation, scope, latency, and cost checks.

## No Exact Analog Found

| Concern | Why |
|---|---|
| Typed route-to-page-adapter registry with tested exclusion dispositions | Current routes construct snapshots ad hoc. |
| One manifest generating/validating Python, Terraform, Foundry, API, and UI projections | Current sources are parallel and already drift. |
| Stable non-ARM entity references in snapshots | Snapshot v1 intentionally drops them from selected resources. |
| Durable cross-page thread with evidence aging and scope narrowing | Conversation state is volatile; durable ledgers are per investigation, not navigation continuity. |
| External versioned full page/question evaluation dataset with release thresholds | Current cases are inline and the script only fails completed routing misses. |

Use the concrete analogs above for structure, but derive these new contracts from `11-CONTEXT.md` and `11-REVIEW.md`; do not preserve the limitations merely because they are current behavior.

## Metadata

**Search scope:** `src/api`, `src/operations`, `src/intelligence/remediation`, `web/src`, `tests`, `scripts`, `infra/terraform`, `.planning/eval`  
**Strong analog families:** strict Pydantic contracts, governed MCP dispatcher, contextual ledger, durable principal-scoped ledger, typed frontend client, drawer integration tests, Terraform projection, live evaluation harness  
**Pattern extraction date:** 2026-09-03
