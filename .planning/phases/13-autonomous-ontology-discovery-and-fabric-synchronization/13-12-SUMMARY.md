---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 12
subsystem: api
tags: [fastapi, rbac, cas, evaluation-snapshot, generation-resolver, durable-lifecycle]

requires:
  - phase: 13-05
    provides: durable proposal review lifecycle and hard-shadow release policy
  - phase: 13-09
    provides: immutable generation publication, ETag CAS, fencing, and rollback
  - phase: 13-10
    provides: durable coordinator-to-publisher delegation and restart-safe run projections
  - phase: 13-11
    provides: content-addressed EvaluationSnapshot store and freshness reconstruction
provides:
  - scope-first lifecycle, proposal, generation, publication, rollback, and evaluation routes
  - server-authoritative mutation eligibility, disabled reasons, revision conflicts, and pointer ETag checks
  - restart-safe EvaluationSnapshot projection with fresh, stale, missing, and invalid states
  - request-scoped governance export reads pinned to one immutable generation
affects: [13-13, ontology-automation-ui, governance-exports, operational-api]

actuals:
  tokens: 19687
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - API facade exposes durable service projections without holding publisher credentials
    - effective connection scope is authorized before object lookup or mutation
    - mutation bodies carry revision or ETag preconditions and server eligibility remains authoritative
    - evaluation responses are rebuilt from durable storage for every provider instance

key-files:
  created:
    - src/api/routers/ontology_discovery.py
    - tests/test_api_ontology_discovery.py
    - tests/test_api_ontology_evaluation.py
  modified:
    - src/api/models.py
    - src/api/dependencies.py
    - src/api/runtime.py
    - src/api/app.py
    - src/api/routers/governance.py
    - src/ontology_discovery/store.py
    - src/ontology_discovery/generation_resolver.py

key-decisions:
  - "Keep the API runtime free of scheduler threads, publisher identity, generation staging, and pointer mutation; rollback is available only through an injected narrow publisher action."
  - "Return 404 after connection-scope authorization for out-of-scope run and proposal IDs, including exact-token collision protection."
  - "Whitelist durable run, checkpoint, proposal, review, generation, and evaluation fields instead of serializing persistence records directly."
  - "Use an opaque hash of canonical connection and subscription identity to locate durable EvaluationSnapshots."
  - "Resolve selected-connection governance exports from one captured GenerationResolver selection while retaining existing unscoped behavior."

patterns-established:
  - "Mutation flow: derive action-specific effective scope -> authorize selected connection -> scope-before-lookup -> service CAS -> bounded envelope."
  - "Degradation: generation and evaluation sections fail independently while durable run and proposal history remain readable."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-04, AUTO-ONT-05, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Durable ontology runs, proposals, generations, publication attempts, rollback, and pending state are exposed through bounded connection-scoped APIs."
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: "tests/test_api_ontology_discovery.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Approve and operate authority are separate, out-of-scope identifiers return 404, and stale revisions or ETags return 409."
    requirement: AUTO-ONT-04
    verification:
      - kind: integration
        ref: "tests/test_api_ontology_discovery.py#test_proposal_review_requires_approve_and_enforces_revision"
        status: pass
      - kind: integration
        ref: "tests/test_api_ontology_discovery.py#test_generation_rollback_requires_operate_and_delegates_etag"
        status: pass
    human_judgment: false
  - id: D3
    description: "EvaluationSnapshot projection reconstructs complete fresh, stale, missing, and invalid evidence from durable storage after restart."
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "tests/test_api_ontology_evaluation.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Runtime registers the ontology API without starting a scheduler or acquiring publisher authority, and governance exports pin one generation per selected-connection request."
    requirement: AUTO-ONT-05
    verification:
      - kind: integration
        ref: "tests/test_api_ontology_discovery.py#test_default_runtime_registers_read_action_facade_without_publisher_authority"
        status: pass
      - kind: integration
        ref: "tests/test_api_ontology_discovery.py#test_governance_export_resolves_one_request_scoped_snapshot"
        status: pass
    human_judgment: false

duration: 11min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 12: Scope-Enforced Ontology Operations API Summary

**FastAPI now exposes restart-safe ontology lifecycle and EvaluationSnapshot state through scope-first envelopes, server-owned eligibility, CAS-safe mutations, and publisher-separated rollback delegation.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-09-07T02:11:14Z
- **Completed:** 2026-09-07T02:22:06Z
- **Tasks:** 2
- **Files modified:** 10 implementation/test files

## Accomplishments

- Added bounded status, run history/detail/run-now/retry/cancel, proposal list/detail/review, generation/publication, rollback, latest evaluation, and evaluation-history endpoints under `/api/v1/ontology-discovery`.
- Enforced read, approve, and operate scopes before object lookup; out-of-scope IDs return non-disclosing 404 responses and stale revisions or pointer ETags return 409.
- Projected exact server-owned `can_cancel`, `can_retry`, `can_rollback`, release eligibility, and disabled reasons while omitting principals, raw metadata, trace payloads, and unapproved evidence bodies.
- Rebuilt EvaluationSnapshot state from the durable store after provider recreation and preserved stale evidence for audit without treating it as release-eligible.
- Registered a read/action facade without an API scheduler thread, publisher credential, stage primitive, or pointer mutation capability.
- Migrated selected-connection governance exports to one captured immutable generation while preserving existing response contracts and unscoped behavior.

## Task Commits

Each TDD task has a RED contract commit followed by its GREEN implementation:

1. **Task 1 RED: lifecycle, scope, CAS, and evaluation API contracts** - `26fecb38`
2. **Task 1 GREEN: scoped durable ontology API surface** - `8169994d`
3. **Task 2 RED: runtime ownership and restart reconstruction contracts** - `ae529ba2`
4. **Task 2 GREEN: provider registration and immutable governance reads** - `1472c55d`

## Files Created/Modified

- `src/api/routers/ontology_discovery.py` - Scope-first lifecycle, proposal, generation/publication, rollback, and EvaluationSnapshot API facade and routes.
- `src/api/models.py` - Strict bounded run, review, and rollback mutation bodies.
- `src/api/dependencies.py` - Optional ontology and request-scoped governance provider seams.
- `src/api/runtime.py` - Restart-safe durable provider construction without scheduler or publisher authority.
- `src/api/app.py` - Ontology router registration only; no ontology worker lifecycle.
- `src/api/routers/governance.py` - Selected-connection generation provider consumption without changing export envelopes.
- `src/ontology_discovery/store.py` - Public newest-first run/proposal reads and CAS retry transition.
- `src/ontology_discovery/generation_resolver.py` - Safe allowlisted metadata reads against a captured immutable generation.
- `tests/test_api_ontology_discovery.py` - Scope isolation, collision, authority split, CAS, generation, degradation, runtime ownership, and governance tests.
- `tests/test_api_ontology_evaluation.py` - Durable fresh/stale/missing/invalid projection, history bounds, scope, and restart tests.

## Decisions Made

- The API receives only a narrow rollback callback. Default runtime wiring intentionally supplies no publisher action because the API identity must never acquire publisher credentials or direct stage/pointer methods.
- Object lookup always follows effective connection authorization. Proposal scope matching uses exact delimited tokens rather than substring matching to prevent cross-scope identifier collisions.
- Durable records are projected through explicit allowlists. Run requesters, lease owners, arbitrary metadata, raw checkpoint payloads, review actors, and raw evidence are not serialized.
- Missing generation and evaluation capabilities produce independent typed sections with release and rollback disabled; they do not hide durable run history.
- Governance uses a captured resolver selection when exactly one connection is selected and retains the existing aggregate provider for legacy unscoped requests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added durable store read and retry service methods**
- **Found during:** Task 1
- **Issue:** The existing store exposed only due runs and single proposal lookups, so an API implementation would otherwise have needed private state access and could not delegate retry to a service-owned CAS transition.
- **Fix:** Added bounded public run/proposal reads and a revision-protected retry transition with existing lock, history, and persistence semantics.
- **Files modified:** `src/ontology_discovery/store.py`
- **Verification:** API tests and ontology store/proposal/coordinator regressions passed.
- **Committed in:** `8169994d`

**2. [Rule 2 - Missing Critical] Added safe immutable generation metadata reads**
- **Found during:** Task 1
- **Issue:** `GenerationResolver` could pin dataset reads but had no public allowlisted path for manifest, validation, compatibility, or publication metadata.
- **Fix:** Added `read_metadata()` with a closed filename allowlist and the same captured generation selection.
- **Files modified:** `src/ontology_discovery/generation_resolver.py`
- **Verification:** Generation consumer, publication, governance, and API regressions passed.
- **Committed in:** `8169994d`

**3. [Rule 2 - Security] Prevented scope collisions and durable payload disclosure**
- **Found during:** Task 2
- **Issue:** Substring scope matching could admit colliding identifiers, and serializing an entire checkpoint payload could expose fields not approved for the API.
- **Fix:** Switched to exact delimited scope tokens, added a collision test, scrubbed messages, and allowlisted checkpoint and proposal projection fields.
- **Files modified:** `src/api/routers/ontology_discovery.py`, `tests/test_api_ontology_discovery.py`
- **Verification:** Scope-collision, redaction, authorization, and complete API suites passed.
- **Committed in:** `1472c55d`

---

**Total deviations:** 3 auto-fixed (3 missing critical security/correctness controls).
**Impact on plan:** All changes were required to preserve durable service ownership and non-disclosing scope enforcement; no new product surface or dependency was added.

## Issues Encountered

- Provider-runtime background refresh is asynchronous, so the ontology facade uses the established optional direct-provider closure instead of depending on refresh timing. This keeps durable operational state available even when unrelated snapshot providers are unavailable.
- Existing Starlette/httpx and FastAPI `on_event` deprecation warnings remain in regression output; they predate this plan and do not affect behavior.

## Verification

- `uv run pytest -q tests/test_api_ontology_discovery.py tests/test_api_ontology_evaluation.py tests/test_api_authorization.py tests/test_api_runtime.py tests/test_api_http.py tests/test_api_inventory_router.py tests/test_governance.py -x` — 163 passed.
- `uv run pytest -q tests/test_ontology_evaluation_snapshot.py tests/test_ontology_discovery_store.py tests/test_ontology_proposal_policy.py tests/test_ontology_generation_publication.py tests/test_ontology_generation_consumers.py tests/test_ontology_discovery_coordinator.py -x` — 75 passed.
- Required Ruff check over all Plan 13-12 source and test files — passed.
- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- `git diff --check` — passed.
- All four RED/GREEN task commits contain the required Copilot trailer.

## Known Stubs

None.

## User Setup Required

None - no deployment, push, merge, credential change, or external service mutation was performed.

## Next Phase Readiness

- Plan 13-13 can consume typed durable section endpoints and rely exclusively on server-projected eligibility and disabled reasons.
- The default API runtime remains read/action-only and cannot publish or roll back without an explicitly injected publisher-service action.
- Root Phase 03.1 remains the active workstream; only Phase 13 completed-plan accounting is updated.

## Self-Check: PASSED

- All three created artifacts and all seven modified implementation artifacts exist.
- All four RED/GREEN task commits are present in repository history.
- Required API, authorization, runtime, evaluation, durable-store, publication, resolver, Ruff, and Phase 13 preflight checks passed.
- Root `STATE.md` remains assigned to Phase 03.1; only Phase 13 completed-plan count/list will be changed.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
