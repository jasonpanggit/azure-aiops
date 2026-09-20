---
quick_task: 260920-cvi
phase: quick-260920-cvi
plan: "01"
type: execute
wave: 1
depends_on: []
scope: "Render scoped resource-health cards before their live metrics arrive, then hydrate each card independently with bounded client concurrency"
autonomous: true
requirements:
  - QUICK-260920-CVI
files_modified:
  - src/api/routers/resource_health.py
  - src/intelligence/health/service.py
  - tests/test_api_resource_health.py
  - tests/test_resource_health_service.py
  - web/src/app/resource-health/page.tsx
  - web/src/app/resource-health/page.test.tsx
  - web/src/lib/services.ts
  - web/src/lib/types.ts
  - web/package.json
estimate:
  tokens: 38000
  raw_tokens: 38000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - "An authorized operator sees cards for supported in-scope compute resources as soon as the inventory request finishes, without waiting for any live metric request."
    - "Each visible card fetches its own live health detail, while one page-level scheduler keeps no more than six card-health requests globally in flight across scope changes, refreshes, retries, and unmount cleanup."
    - "A slow or failed health request leaves sibling cards visible and able to finish; the affected card alone shows an accessible loading or error state and can be retried."
    - "Changing scope cannot display or apply late health results from the previous scope, and a crafted resource ID cannot retrieve health outside the effective read scope."
    - "Refresh re-fetches card health with cache bypass semantics while retaining the resource-card identities."
  artifacts:
    - path: "src/api/routers/resource_health.py"
      provides: "Scope-authorized, per-resource health endpoint and per-resource cache isolation"
      contains: "resource_id"
    - path: "src/intelligence/health/service.py"
      provides: "Single-resource utilization path that consumes an inventory identity row without listing resources through Azure Resource Graph"
      contains: "ResourceHealthService"
    - path: "web/src/app/resource-health/page.tsx"
      provides: "Inventory-first cards, bounded health hydration, refresh, and per-card states"
      contains: "ResourceCard"
    - path: "web/src/app/resource-health/page.test.tsx"
      provides: "Deterministic coverage of early rendering, concurrency, isolation, scope changes, retry, and refresh"
    - path: "tests/test_api_resource_health.py"
      provides: "HTTP-level authorization, cache, and per-resource response coverage"
  key_links:
    - from: "web/src/app/resource-health/page.tsx"
      to: "web/src/lib/services.ts"
      via: "inventoryApi.resources supplies card identities before resourceHealthApi.resource hydrates each card"
      pattern: "inventoryApi\\.resources|resourceHealthApi\\.resource"
    - from: "src/api/routers/resource_health.py"
      to: "src/intelligence/inventory/read_port.py"
      via: "InventoryReadPort.get_resource authorizes and resolves the requested identity against ReadScope before provider or cache access"
      pattern: "inventory_read_port\\(\\).*get_resource|get_resource"
    - from: "src/api/routers/resource_health.py"
      to: "src/intelligence/health/service.py"
      via: "The authorized inventory row is passed to the single-resource snapshot method"
      pattern: "snapshot_resource"
    - from: "web/src/app/resource-health/page.tsx"
      to: "web/src/app/resource-health/page.test.tsx"
      via: "Deferred abort-aware request tests prove the global worker limit across generation transitions and independent card state transitions"
      pattern: "ResourceHealthPage"
---

<objective>
Make the resource-health page useful before live Azure Monitor calls complete: load scoped resource identities from the established inventory read contract, render those cards immediately, and hydrate each card independently through a new scope-safe per-resource health API.

Purpose: The current page waits for one aggregate request that discovers every resource and fetches all metrics serially, so one slow or failed resource delays or obscures the whole page. This plan separates fast identity rendering from live metric hydration without weakening authorization or adding another resource-discovery path.

Output: A tested per-resource backend contract, inventory-first React page, six-request client worker bound, isolated card states, and executable lint/test validation.
</objective>

<execution_context>
@.github/gsd-core/workflows/execute-plan.md
@.github/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.github/copilot-instructions.md
@AGENTS.md
@src/api/routers/resource_health.py
@src/intelligence/health/service.py
@src/intelligence/inventory/read_port.py
@src/api/dependencies.py
@src/api/runtime.py
@tests/test_api_resource_health.py
@tests/test_resource_health_service.py
@tests/test_inventory_read_port.py
@web/src/app/resource-health/page.tsx
@web/src/app/inventory/page.test.tsx
@web/src/app/exposure/__tests__/independent-states.test.tsx
@web/src/hooks/useApi.test.ts
@web/src/lib/services.ts
@web/src/lib/types.ts
</context>

<dependency_graph>

1. Task 1 creates the authenticated single-resource API that accepts an inventory-authorized identity row and returns one live utilization result without invoking `resource_lister`.
2. Task 2 consumes both existing `inventoryApi.resources` and Task 1's new `resourceHealthApi.resource`, then proves inventory-first rendering, bounded scheduling, stale-result rejection, and local card recovery.
3. The tasks share only the API contract: backend tests lock the envelope and authorization semantics before the frontend binds to them.

</dependency_graph>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Trace one authorized inventory resource to one live health response</name>
  <files>src/intelligence/health/service.py, src/api/routers/resource_health.py, tests/test_resource_health_service.py, tests/test_api_resource_health.py</files>
  <behavior>
    - An in-scope VM or Container App identity resolved by `InventoryReadPort.get_resource()` produces a one-resource `ResourceHealthSnapshot` with the existing utilization fields, evidence, warnings, unavailable-metric semantics, and cache metadata.
    - The snake_case inventory contract (`resource_id`, `resource_name`, `resource_type`, `subscription_id`, `resource_group`) is normalized into the ARG-style internal health row (`id`, `name`, `type`, `subscriptionId`, `resourceGroup`) before supported-type validation or metrics access, with the canonical inventory resource ID propagated unchanged to the response and provider call.
    - The single-resource service path uses the supplied inventory row and matching active subscription connection; its `resource_lister` is never invoked.
    - A missing, unsupported, or out-of-scope resource returns the same not-found response before metrics-provider construction or cache lookup, preventing resource-existence disclosure.
    - Per-resource cache entries are separated by effective subscription scope and canonical case-insensitive resource ID; cache hits and `force_refresh=true` match the aggregate endpoint's TTL behavior.
    - A metrics failure returns the existing `unknown` utilization row with its safe per-resource error rather than failing another resource request.
  </behavior>
  <action>
    Start with failing service and HTTP tests, then add a documented `ResourceHealthService.snapshot_resource(...)` public method that accepts the already-authorized inventory identity mapping plus the allowed subscription IDs. At this boundary, explicitly normalize `resource_id` to `id`, `resource_name` to `name`, `resource_type` to `type`, `subscription_id` to `subscriptionId`, and `resource_group` to `resourceGroup`; perform supported-type validation, subscription/provider selection, cache identity construction, and metrics access only against that normalized internal row. Preserve the inventory row's canonical `resource_id` value as the internal `id` and response/provider resource ID while casefolding only comparison and cache-key material. Validate that the normalized resource type is in `SUPPORTED_RESOURCE_TYPES`, that the row has a subscription represented by the effective request/provider scope, and that an active matching connection exists. Reuse `_fetch_resource_utilization`, the existing metrics-client factory, and existing classic/OTel guest-performance merge so field/status semantics stay identical to `snapshot()`. Build a one-row `ResourceHealthSnapshot`; do not call `resource_lister` or issue a new resource-identity ARG query on this path.

    Add `GET /api/v1/resource-health/resource` with required `resource_id` and existing `force_refresh` query semantics. Resolve the identity through `context.inventory_read_port().get_resource(scope, resource_id)` before touching the resource-health cache or live provider. Return `NOT_FOUND` for absent, unsupported, and unauthorized identities with one non-disclosing message. Resolve the health provider for the identity's subscription, call `snapshot_resource`, and return the standard envelope with the existing source evidence and effective scope. Keep the aggregate `GET /api/v1/resource-health` contract intact. Add a dedicated resource cache keyed by sorted effective subscription scope plus casefolded canonical resource ID, authorize before every cache read, and clear it in the existing test fixture.

    Extend the API fixture with a fake inventory read-port provider and instrumented lister/metrics factories. Include a contract-realistic snake_case inventory row with a mixed-case canonical resource ID and assert that normalization supplies the expected ARG-style fields to health internals and propagates that exact canonical ID through the metrics call and response. Cover success, no `resource_lister` call, out-of-scope indistinguishability, unsupported type rejection, provider absence, metric-error isolation, same-resource cache hits, distinct-resource cache separation, and force-refresh bypass. Preserve current unrestricted-admin behavior for the aggregate endpoint and all `ReadScope` authorization semantics.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py</automated>
  </verify>
  <done>
    An authenticated caller can request exactly one authorized inventory resource's health without resource discovery, and tests prove the snake_case inventory contract is normalized with canonical ID propagation and scope checks occur before isolated cache/provider access while the aggregate endpoint remains compatible.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Render inventory cards first and hydrate them with a bounded independent queue</name>
  <files>web/src/lib/types.ts, web/src/lib/services.ts, web/src/app/resource-health/page.tsx, web/src/app/resource-health/page.test.tsx, web/package.json</files>
  <behavior>
    - Resolving the inventory request renders supported VM and Container App cards immediately even when every live-health promise is still pending.
    - With more than six cards, exactly six health requests start; one scheduler and active-count shared across all generations opens a worker slot only after an active request settles or aborts, so a scope change, refresh, retry, or unmount never creates a seventh globally pending request.
    - Resolving one card updates only that card, rejecting one card shows an accessible local error and retry control, and pending siblings remain visible with local loading states.
    - Changing scope discards old cards immediately through the existing scope-sensitive inventory load, removes obsolete queued work, aborts obsolete active requests, and prevents late old-scope health promises from mutating the new card set.
    - `Refresh now` keeps identities visible, cancels queued work and aborts active work from the prior generation, resets card health to loading, and requeues every card with `force_refresh=true`; a local retry requeues only its card through the same bounded scheduler.
  </behavior>
  <action>
    Add a strict `ResourceHealthDetail` response shape only if the backend one-resource envelope differs from `ResourceHealthSnapshot`; otherwise reuse `ResourceHealthSnapshot`. Add a documented `resourceHealthApi.resource(resourceId, scope, forceRefresh, options: { signal?: AbortSignal } = {})` method that sends `resource_id`, the unchanged `ScopeSelection`, optional `force_refresh`, and `options.signal` through the existing API client to the new route. Keep `snapshot()` for compatibility and correct its stale comment about requiring explicit subscription scope.

    Refactor `ResourceHealthPage` into an inventory-first flow. Use `inventoryApi.resources(scope, 0, 500)` as the lightweight identity source and filter its returned rows to the backend-supported VM and Container App types. Render each identity as a stable card immediately. Maintain per-resource `{loading, data, error}` state keyed by canonical resource ID and route initial loads, retries, refreshes, and scope replacements through one page-lifetime scheduler with one queue, one global active counter, and one `AbortController` per active request. On scope change, refresh, or unmount, remove obsolete queued jobs and abort every obsolete active controller, but do not decrement or reset the active counter at cancellation time: release each slot only in that request's settlement/finally path, then allow current-generation queued work to start. This ensures new-generation work waits while obsolete requests are still pending and the global in-flight total remains at most six. Starting or retrying work must never use an unbounded `Promise.all`. Pass each controller's signal to `resourceHealthApi.resource`, and retain generation plus abort guards on every completion so stale promises cannot repopulate a changed scope even if a transport mock ignores cancellation. Keep inventory loading/error/empty states page-level, but render metric loading, failures, and retry controls inside the affected card with `role="status"`/`role="alert"` and resource-specific accessible names.

    Derive observed/critical/warning/healthy counts, chart rows, warnings, unavailable metrics, and Copilot resource context from successful card details while using the inventory-card count as the total. Keep missing metrics as em dashes, never healthy zeroes. Keep cards present during global refresh, requeue through the same six-worker scheduler with cache bypass, and permit local retry without disturbing siblings. Pass the exact current scope to both inventory and health requests.

    Create `page.test.tsx` using the repository's Vitest/Testing Library hoisted-service mocks and deferred-promise pattern. Make the health mock capture each `AbortSignal` and track current plus peak unsettled requests. Prove early card rendering, the six-request ceiling and slot release, independent success/error/loading UI, local retry, refresh cache bypass, scope propagation, and rejection of late previous-scope results. Add transition tests that hold six old-generation requests pending, trigger both a scope change and a refresh, assert old queued jobs are removed and old active signals are aborted, assert no new-generation request starts until an aborted old request actually settles, and assert the measured global peak remains six throughout; also assert unmount aborts remaining active work. Add the missing `lint:fix` package script as `next lint --fix` so the required repository validation command is runnable; do not add or update dependencies.
  </action>
  <verify>
    <automated>cd web &amp;&amp; npm test -- src/app/resource-health/page.test.tsx &amp;&amp; npx tsc --noEmit &amp;&amp; npm run lint:fix &amp;&amp; npm test</automated>
  </verify>
  <done>
    `/resource-health` shows authorized inventory cards before live metrics, uses AbortSignal-backed cancellation, never exceeds six globally unsettled detail requests during ordinary loads or generation transitions, isolates slow/failing cards, safely resets across scope changes, and passes targeted plus full frontend validation.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Browser → inventory/resource-health APIs | Untrusted query scope and resource IDs cross into authenticated, scope-enforced read routes. |
| Resource-health API → inventory read port | The API must resolve identity and visibility from the authoritative scoped read contract before any health cache or provider use. |
| Resource-health service → Azure Monitor/Logs | A bounded browser queue triggers live external reads whose latency and failures are independent per resource. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-260920-CVI-01 | Elevation of Privilege | `GET /resource-health/resource` | high | mitigate | Resolve `resource_id` through `InventoryReadPort.get_resource(ReadScope, ...)`, use one not-found response for absent/out-of-scope IDs, and call metrics only after authorization. |
| T-260920-CVI-02 | Information Disclosure | Per-resource TTL cache | high | mitigate | Perform authorization before cache reads and key entries by effective subscription scope plus canonical resource ID; test cross-scope and cross-resource isolation. |
| T-260920-CVI-03 | Tampering | Scope changes and late browser promises | medium | mitigate | Pass the current scope and AbortSignal to every request, cancel obsolete queued work, abort obsolete active work, and reject completions from stale scope/load generations. |
| T-260920-CVI-04 | Denial of Service | Client live-metrics fan-out | medium | mitigate | Use one scheduler and active counter across generations, cap globally unsettled requests at six, release slots only after settlement/abort completion, retain the server TTL/force-refresh contract, and test transitions deterministically. |
| T-260920-CVI-05 | Information Disclosure | Per-card error rendering | medium | mitigate | Preserve safe API error messages, use React text rendering, and avoid exposing provider credentials or raw transport payloads. |
</threat_model>

<edge_cases>
- Inventory succeeds with no supported compute rows: show the existing honest empty state and issue no health requests.
- Inventory includes unsupported types: omit them from this metrics page without trying the health endpoint.
- More than 500 matching resources: retain the existing inventory endpoint's bounded pagination semantics and hydrate every card returned for the active page; do not fall back to request-time ARG discovery.
- One request never settles: at most that worker slot remains occupied; the other five workers and already-settled cards continue independently.
- A card fails while others load or succeed: retain its identity, show only its local error/retry, and keep successful metrics/chart data.
- Scope changes during outstanding work: old identities clear under existing `useApi` scope semantics, obsolete queued work is removed, active work is aborted, slots remain occupied until those requests settle, and late completions are ignored.
- Refresh during partially loaded state: use one new generation, retain identities, cancel obsolete queued/active work, wait for globally shared slots to release on settlement, and prevent prior requests from overwriting refreshed results.
- Duplicate resource IDs differing only by case: canonicalize state/cache keys so only one card/request identity exists.
- Missing guest metrics: retain the existing unavailable-metric disclosure and em-dash rendering.
- Inventory read port or live provider unavailable: inventory failure is page-level; a health-provider failure after identities load is isolated to affected cards.
</edge_cases>

<source_audit>

| Source | ID | Feature / Requirement | Plan | Status | Notes |
|--------|----|-----------------------|------|--------|-------|
| GOAL | — | Load the resource-health page before live metrics | 01 | COVERED | Task 2 renders inventory identities before health promises settle. |
| REQ | Q-01 | Fetch each resource card's health independently | 01 | COVERED | Tasks 1-2 establish and consume a one-resource contract. |
| REQ | Q-02 | Bound client concurrency | 01 | COVERED | Task 2 fixes and tests one six-request global ceiling across scope, refresh, retry, abort, and unmount transitions. |
| REQ | Q-03 | Isolate slow/failing card states | 01 | COVERED | Task 2 provides local loading, error, retry, and stale-result handling. |
| REQ | Q-04 | Preserve authorization and scope semantics | 01 | COVERED | Task 1 authorizes via `ReadScope` plus inventory read-port lookup before cache/provider use. |
| REQ | Q-05 | Reuse inventory/read-port identity rather than add ARG discovery | 01 | COVERED | Existing `/inventory/resources` supplies cards and `snapshot_resource` consumes its row without `resource_lister`. |
| REQ | Q-06 | Add targeted tests, strict TypeScript, JSDoc, and required validation | 01 | COVERED | Both tasks are test-first; Task 2 documents the public client API and enables/runs `npm run lint:fix &amp;&amp; npm test`. |
| RESEARCH | — | No separate research artifact; existing repository contracts were sufficient | 01 | COVERED | Level 0 discovery confirmed the inventory read port, route, service, and deferred-promise test patterns. |
| CONTEXT | — | No separate CONTEXT.md or D-XX decisions; all inline constraints are represented above | 01 | COVERED | No deferred ideas were introduced. |

</source_audit>

<verification>
1. Run backend target coverage: `uv run pytest -q tests/test_resource_health_service.py tests/test_api_resource_health.py`.
2. Run the frontend target and strict type check: `cd web && npm test -- src/app/resource-health/page.test.tsx && npx tsc --noEmit`.
3. From `web/`, run the required validation exactly: `npm run lint:fix && npm test`.
4. Run `git diff --check`.
5. Inspect `git status --short` and the scoped diff. Only the nine files in `files_modified` may be changed by execution; preserve all unrelated user-owned changes and do not commit them.
</verification>

<success_criteria>
- Inventory-backed cards appear before any live metric detail resolves.
- Every card has an independent live request and local loading/error/retry lifecycle.
- Instrumented tests prove no seventh health request starts while six are pending, including while scope changes or refreshes abort obsolete work and await its settlement.
- Scope changes and crafted IDs cannot disclose or apply data outside the effective authorized scope.
- The per-resource path performs no resource-identity ARG listing.
- Existing aggregate resource-health behavior remains covered and compatible.
- Targeted backend/frontend tests, TypeScript strict checking, `npm run lint:fix`, and the full frontend suite pass.
</success_criteria>

<output>
Create `.planning/quick/260920-cvi-load-the-resource-health-page-before-liv/260920-cvi-SUMMARY.md` when execution is complete.
</output>
