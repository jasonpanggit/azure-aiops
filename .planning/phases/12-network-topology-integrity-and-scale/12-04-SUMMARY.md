---
phase: 12-network-topology-integrity-and-scale
plan: 04
subsystem: network-policy
tags: [policy-revision, cache-invalidation, declarative-rules, react-hooks, debounce]

requires:
  - phase: 12-network-topology-integrity-and-scale
    plan: 01
    provides: scope-safe network provider and policy-preview boundary
  - phase: 12-network-topology-integrity-and-scale
    plan: 03
    provides: current network analysis and downstream security regression baseline
provides:
  - revision-keyed invalidation of cached network analysis after policy writes
  - optimistic policy concurrency in persistent and in-memory stores
  - additive engine-supported target and operator fields on policy responses
  - stable, 400 ms debounced useApi refetch with retained in-flight data
affects: [12-08, network-policy-editor, network-analysis, shared-web-fetching]

actuals:
  tokens: 11730
  tasks: 3
  commits: 7

tech-stack:
  added: []
  patterns:
    - provider cache identity derived from mutable control-plane revision
    - server-published declarative rule vocabulary
    - stable trailing-edge invalidation callback in a shared React hook

key-files:
  created:
    - web/src/hooks/useApi.test.ts
    - .planning/phases/12-network-topology-integrity-and-scale/12-04-SUMMARY.md
  modified:
    - src/network/design.py
    - src/api/providers.py
    - src/api/runtime.py
    - src/network/rule_engine.py
    - src/api/routers/network.py
    - tests/test_api_network.py
    - web/src/hooks/useApi.ts

key-decisions:
  - "The managed network provider cache key is exactly ('network-policy', revision); interval caching remains active when the revision is unchanged."
  - "The complete public target vocabulary is SUPPORTED_TARGET_NAMES, derived from snapshot-backed and derived engine targets."
  - "The policy API fields are exactly supported_targets and supported_operators, both additive lists sourced from the engine."
  - "useApi refetch is a stable trailing-edge callback that coalesces calls for 400 ms and retains existing data while loading."

patterns-established:
  - "Mutable policy writes increment a monotonic revision in both storage modes and stale expected revisions fail closed."
  - "A provider whose mutable cache key changes refreshes only that provider before serving a request."
  - "Shared client invalidation belongs in useApi rather than in individual consumers."

requirements-completed: [TOPO-04]

coverage:
  - id: D1
    description: A policy write advances the revision and the next gaps request uses newly derived analysis without disabling interval caching.
    requirement: TOPO-04
    verification:
      - kind: integration
        ref: tests/test_api_network.py::TestPolicy::test_write_invalidates_cached_derived_analysis
        status: pass
      - kind: unit
        ref: tests/test_api_network.py::TestPolicy::test_store_revision_increments_and_rejects_stale_writes
        status: pass
    human_judgment: false
  - id: D2
    description: Policy responses additively publish the engine target and operator vocabulary while malformed rules remain unpersisted and valid rules preview and save.
    requirement: TOPO-04
    verification:
      - kind: integration
        ref: tests/test_api_network.py::TestPolicy
        status: pass
      - kind: unit
        ref: tests/test_network_rule_engine.py
        status: pass
    human_judgment: false
  - id: D3
    description: useApi exposes a stable refetch that coalesces rapid calls and preserves loaded data during refresh without changing existing consumers.
    requirement: TOPO-04
    verification:
      - kind: unit
        ref: web/src/hooks/useApi.test.ts
        status: pass
      - kind: other
        ref: cd web && npx vitest run
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-09-05
status: complete
---

# Phase 12 Plan 04: Policy Round-Trip and Shared Refetch Summary

**Revision-keyed network analysis, an engine-authored policy contract, and a stable debounced `useApi` refetch now make saved design policy visible without a reload.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-05T16:13:56Z
- **Completed:** 2026-09-05T16:26:27Z
- **Tasks:** 3
- **Files modified:** 9, including this summary
- **Commits:** 7, including this summary commit

## Accomplishments

- Added monotonic policy revisions and optimistic stale-write rejection to both the durable document-backed store and the local in-memory fallback.
- Made the managed network provider detect a changed policy revision and rebuild before serving the next analysis while leaving the 30-second read cache intact for unchanged policy.
- Published the full declarative rule engine vocabulary through additive `supported_targets` and `supported_operators` policy fields.
- Added a stable `useApi.refetch()` callback with a 400 ms coalescing window and retained-data loading behavior, verified against every web consumer.

## Cache-Key Contract

- **Managed provider key shape:** `("network-policy", revision)`.
- `revision` starts at `0` and increments after every successful write, including in-memory writes.
- An unchanged key continues to use the provider refresh interval; repeated gaps reads do not rebuild the network service.
- A changed key refreshes only the network provider before `ProviderRuntime.get("network")` returns.
- If the revision changes during a refresh, the key is not published as current and the request path retries rather than labelling stale analysis with the new revision.
- The hybrid network path continues caching only live ARG rows under `(AIOPS_HOME, sorted subscription IDs)` and reconstructs its analysis service with `NetworkDesignPolicyStore.read()` on each request.

## Rule Engine Contract

The policy payload preserves every previous field and adds exactly:

- `supported_targets`
- `supported_operators`

`supported_targets`, sourced from `SUPPORTED_TARGET_NAMES`, is:

`firewalls`, `gateways`, `load_balancers`, `nics`, `nsg_rules`, `nsgs`, `peerings`, `private_dns_zones`, `private_endpoints`, `private_link_resources`, `route_tables`, `routes`, `subnets`, `vnets`.

`supported_operators`, sourced from `SUPPORTED_OPERATORS`, is:

`equals`, `not_equals`, `in`, `not_in`, `contains`, `not_contains`, `matches`, `not_matches`, `exists`, `gt`, `gte`, `lt`, `lte`, `in_cidr`, `not_in_cidr`.

Malformed declarative assertions continue through the existing server validator, return its operator-facing reason, and do not advance the policy revision or persist the rule. A valid assertion previews without persistence and saves through the existing endpoint.

## Task Commits

Each TDD task was committed as a failing test followed by its implementation:

1. **Task 1 RED: Policy freshness and revision regressions** — `a32c6db7`
2. **Task 1 GREEN: Revision-keyed network analysis** — `22d71173`
3. **Task 2 RED: Additive engine contract regressions** — `444e432c`
4. **Task 2 GREEN: Published rule engine contract** — `99d43855`
5. **Task 3 RED: Stable debounced refetch regressions** — `7a9f9cf1`
6. **Task 3 GREEN: Shared `useApi` refetch** — `6b91bd25`

## Files Created/Modified

- `src/network/design.py` — policy revision accessor, in-memory revision parity, locking, and expected-revision guard.
- `src/api/providers.py` — optional provider cache keys and targeted refresh on key change.
- `src/api/runtime.py` — binds the network provider to `("network-policy", revision)`.
- `src/network/rule_engine.py` — exports the complete accepted target-name vocabulary.
- `src/api/routers/network.py` — adds `supported_targets` and `supported_operators` to policy payloads.
- `tests/test_api_network.py` — policy freshness, revision, additive response, and declarative-rule integration coverage.
- `web/src/hooks/useApi.ts` — stable 400 ms debounced `refetch` with retained data during refresh.
- `web/src/hooks/useApi.test.ts` — hook identity, coalescing, latest-loader, and retained-data tests.

## Verification

- `.venv/bin/python -m pytest -o addopts='' tests/test_api_network.py tests/test_network_rule_engine.py -q` — **81 passed**.
- `.venv/bin/python -m pytest -o addopts='' tests/test_network_downstream_scope.py -q` — **4 passed**; Plan 12-01 security gate remains green.
- `.venv/bin/python -m pytest -o addopts='' -q` — **2,656 passed, 35 skipped**; complete backend suite.
- `cd web && npx vitest run` — **39 files passed, 249 tests passed, 15 existing todos**; complete shared-hook regression suite.
- `cd web && npx tsc --noEmit` — **passed**.
- Ruff on all changed Python source and tests — **passed**.

## Decisions Made

- A policy revision is part of provider identity rather than a reason to remove or shorten the normal refresh interval.
- Provider refresh remains last-good for ordinary snapshot failures, but a provider is not returned under a mismatched mutable cache key.
- Derived targets (`nsg_rules`, `routes`) are included in the public target vocabulary because the existing validator accepts them; publishing only snapshot-backed targets would let the editor drift from the engine.
- Refetch uses a trailing-edge 400 ms debounce so every caller inherits one coalescing policy, and the callback reads the latest loader through the existing ref.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wired the policy revision at the provider composition root**
- **Found during:** Task 1
- **Issue:** `ProviderRuntime` can support revision-aware keys in `src/api/providers.py`, but the network provider cannot use one unless its `ProviderSpec` is configured where providers are composed.
- **Fix:** Added the network-only `("network-policy", revision)` key in `src/api/runtime.py`.
- **Files modified:** `src/api/runtime.py`
- **Verification:** Patch-then-gaps integration test passed inside a frozen refresh window; full backend suite passed.
- **Committed in:** `22d71173`

**2. [Rule 2 - Missing Critical] Published derived targets as part of the authoritative engine vocabulary**
- **Found during:** Task 2
- **Issue:** The existing `SUPPORTED_TARGETS` mapping covered snapshot attributes but omitted the engine-supported derived targets `nsg_rules` and `routes`; directly publishing only its keys would advertise an incomplete validator contract.
- **Fix:** Added exported `SUPPORTED_TARGET_NAMES`, derived from both engine target sets, and made validation and the API consume it.
- **Files modified:** `src/network/rule_engine.py`, `src/api/routers/network.py`
- **Verification:** Engine unit tests and additive policy contract tests passed.
- **Committed in:** `99d43855`

**Total deviations:** 2 auto-fixed (1 blocking issue, 1 missing critical contract).
**Impact on plan:** Both changes are the minimum wiring needed to make the planned cache key and engine-authored contract complete; no new dependency, endpoint, or architecture was introduced.

## TDD Gate Compliance

- Task 1: RED `a32c6db7` precedes GREEN `22d71173`.
- Task 2: RED `444e432c` precedes GREEN `99d43855`.
- Task 3: RED `7a9f9cf1` precedes GREEN `6b91bd25`.
- Every RED run failed on the intended missing behavior before implementation.

## Threat Model Verification

- **T-12-16:** The next network-provider read is keyed by the current policy revision and cannot return an instance under a superseded key.
- **T-12-17:** Declarative bodies still use `validate_rule_parameters`; no `eval`, executable expression path, or client semantic validator was added.
- **T-12-18:** The provider's 30-second normal cache remains in place and browser refetch calls coalesce for 400 ms.
- **T-12-19:** Both policy storage modes reject a stale expected revision and leave the current policy unchanged.
- No additional endpoint, authentication path, file-access boundary, or schema trust boundary was introduced.

## Known Stubs

None. No placeholders, TODOs, FIXMEs, skipped tests, or unwired data sources were introduced in the files changed by this plan. The 15 Vitest todos reported by the full suite pre-existed this plan.

## Issues Encountered

- The isolated worktree did not initially contain `.venv` or `web/node_modules`; both were recreated from the committed Python and npm lockfiles without changing dependency manifests.
- Existing FastAPI/Starlette deprecation warnings, Vitest Keyborg cleanup messages, npm deprecation notices, and locked-dependency audit findings remain outside this plan. They did not fail verification and were not modified.

## User Setup Required

None.

## Next Phase Readiness

- Plan 12-08 can consume `supported_targets`, `supported_operators`, and stable per-loader `refetch()` handles.
- Policy mutations now become visible to the next gaps request without waiting for the provider refresh interval.
- No blocker remains, and the Plan 12-01 scope-isolation security gate remains green.

## Self-Check: PASSED

- All six TDD task commits resolve and carry the required co-author trailer.
- All eight declared implementation/test files exist in the assigned isolated worktree.
- Backend targeted, backend full-suite, Plan 12-01 security, full web, TypeScript, and Ruff verification passed with the exact counts recorded above.
- `STATE.md` and `ROADMAP.md` were not modified, as explicitly requested.
- No generated or temporary file is untracked.

---
*Phase: 12-network-topology-integrity-and-scale*
*Completed: 2026-09-05*
