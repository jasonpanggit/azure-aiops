---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 03
subsystem: ontology-discovery
tags: [incremental-reconciliation, evidence-batching, durable-state, cas, scope-isolation]

requires:
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 02
    provides: fenced restart-safe run ledger and browser-independent coordinator
provides:
  - five-way incremental classification with authoritative full-reconciliation semantics
  - exact 50/200/40 scope-isolated EvidenceBatch contracts and deterministic splitting
  - restart-durable pending relationships and idempotent pre-dispatch batch records
  - typed rejection checkpoints that prevent malformed or over-limit curator calls
affects: [13-04, 13-05, 13-09, 13-10, 13-12, 13-15]

actuals:
  tokens: 17954
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - canonical order-independent content hashes excluding ingestion wall clocks
    - scope-first connected-component batching with immutable hard caps
    - deterministic durable identities with per-record revision CAS
    - persist-before-dispatch curator coordination with idempotent replay

key-files:
  created:
    - src/ontology_discovery/incremental.py
    - tests/test_ontology_discovery_incremental.py
  modified:
    - src/ontology_discovery/contracts.py
    - src/ontology_discovery/store.py
    - src/ontology_discovery/coordinator.py
    - src/onboarding/graph_normalize.py
    - src/ontology/pending_relationships.py
    - tests/test_pending_relationships.py

key-decisions:
  - "Treat only complete, non-degraded observations as authoritative for retirement; partial, degraded, and unknown-freshness scans preserve missing rows as unresolved."
  - "Derive evidence batch identity from source generation, authorized scope, connected component, chunk index, and ordered record IDs so replay cannot duplicate durable work."
  - "Persist each bounded batch before invoking the curator and CAS its dispatched result afterward; retries reuse the same batch ID."
  - "Preserve root STATE.md Phase 03.1 ownership during this approved concurrent Phase 13 subset and record completion only in this plan summary and commits."

patterns-established:
  - "Incremental truth: NormalizedGraph.row_hashes feed an explicit five-class delta carrying source generation, observation, freshness, and coverage."
  - "Bounded context: records are grouped by scope and connected component, ranked by endpoint match, authority, freshness, corroboration, and stable identity, then split without truncation."
  - "Durable unresolved work: pending relationship and evidence batch records use deterministic IDs, deep-copy reads, atomic file replacement, and revision CAS."

requirements-completed: [AUTO-ONT-02, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: "Added, changed, retired, unresolved, and stale evidence classifications converge to a clean rebuild without false retirement during partial or degraded scans."
    requirement: AUTO-ONT-02
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_incremental.py#test_incremental_classifier_records_all_delta_classes_and_provenance"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_discovery_incremental.py#test_complete_reconciliation_converges_to_clean_rebuild"
        status: pass
    human_judgment: false
  - id: D2
    description: "EvidenceBatch enforces exact 50/200/40 caps and deterministic scope-first splitting without record loss or cross-scope context."
    requirement: AUTO-ONT-07
    verification:
      - kind: integration
        ref: "tests/test_ontology_discovery_incremental.py#test_evidence_batch_rejects_values_above_exact_caps"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_discovery_incremental.py#test_split_is_scope_first_deterministic_bounded_and_lossless"
        status: pass
    human_judgment: false
  - id: D3
    description: "Pending relationships and persist-before-dispatch evidence batches survive restart and replay with deterministic identity and revision CAS."
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: "tests/test_pending_relationships.py#test_durable_pending_edge_retains_replay_state_across_restart"
        status: pass
      - kind: integration
        ref: "tests/test_ontology_discovery_incremental.py#test_coordinator_persists_every_bounded_batch_before_curator_dispatch"
        status: pass
    human_judgment: false

duration: 7min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 03: Incremental Discovery and Durable Evidence Batching Summary

**Five-way reconciliation now feeds exact scope-isolated 50/200/40 evidence batches, with pending edges and curator-bound work persisted durably before dispatch.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-06T11:04:33Z
- **Completed:** 2026-09-06T11:11:39Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- Extended the established normalized row-hash boundary with order-independent, wall-clock-independent hashing and explicit added, changed, retired, unresolved, and stale classifications.
- Added shared EvidenceBatch caps, scope-first connected-component splitting, deterministic quality ordering, typed malformed/indivisible rejection, and full-reconciliation parity.
- Moved pending relationships into the atomic run ledger with deterministic identities, complete retry/provenance fields, restart reconstruction, terminal history, and record revision CAS.
- Added persist-before-dispatch coordinator processing so no over-limit or unpersisted batch reaches the curator, while replay, cancellation, generation changes, and typed failures remain safe.

## Task Commits

Each TDD task was committed with a RED test before its GREEN implementation:

1. **Task 1 RED: incremental and bounded-batch contracts** - `fd15b672`
2. **Task 1 GREEN: five-way reconciliation and deterministic splitting** - `671c568e`
3. **Task 2 RED: restart-durable pending and coordinator contracts** - `e23f4409`
4. **Task 2 GREEN: persistent pending edges and evidence batches** - `56ffa50d`

## Files Created/Modified

- `src/ontology_discovery/incremental.py` - Five-way delta classifier, typed batch rejection, deterministic scope/component splitting, and stable batch identity.
- `src/ontology_discovery/contracts.py` - Shared 50/200/40 caps, validated EvidenceBatch serialization, and safe processor failure contract.
- `src/ontology_discovery/store.py` - Atomic pending relationship and evidence batch records with deterministic IDs, replay deduplication, and revision CAS.
- `src/ontology_discovery/coordinator.py` - Persist-before-dispatch bounded evidence processor and durable typed-failure checkpoints.
- `src/onboarding/graph_normalize.py` - Stable row hashing independent of mapping/list order and ingestion wall clocks.
- `src/ontology/pending_relationships.py` - Durable-store adapter while preserving the existing in-memory compatibility path.
- `tests/test_ontology_discovery_incremental.py` - Delta, caps, splitting, reconciliation, persistence, dispatch, replay, and rejection coverage.
- `tests/test_pending_relationships.py` - Restart reconstruction, terminal-state retention, deterministic identity, and CAS coverage.

## Decisions Made

- Missing rows become retired only from a complete observation with usable freshness; all bounded or degraded observations fail closed as unresolved.
- Authorized scope is the first batching partition, so colliding endpoint names or IDs in different scopes can never share curator context.
- Connected components may be split into whole records when a component exceeds a hard cap; an individual record whose embedded references exceed a cap is rejected rather than truncated.
- Durable batch status changes from `persisted` to `dispatched` only after the curator returns, allowing process replacement to retry without losing or duplicating the batch record.
- Root `.planning/STATE.md`, roadmap, and requirements remain untouched because Phase 03.1 owns the active root planning state during this safe concurrent subset.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- RED tests failed on the expected missing incremental, pending-CAS, and bounded-processor contracts.
- Ruff identified import-order and formatting issues during implementation; these were corrected before the task commit.

## Verification

- `uv run python .planning/scripts/preflight_phase_13.py` — passed.
- `uv run pytest -q tests/test_ontology_discovery_incremental.py -x` — 10 passed after Task 1.
- `uv run pytest -q tests/test_pending_relationships.py tests/test_ontology_discovery_incremental.py -x` — 19 passed.
- `uv run ruff check src/ontology_discovery src/onboarding/graph_normalize.py src/ontology/pending_relationships.py` — passed.
- Relevant ontology discovery, store, coordinator, incremental, and pending regressions — 48 passed.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 13-04 may consume only the persisted, bounded EvidenceBatch records through its strict proposal adapter.
- Pending relationships, batch rejection outcomes, and curator dispatch results are restart-safe and available for later policy, review, and publication plans.
- No Plan 13-04 work or later MCP, shared operations tool, Foundry Terraform, deployment, API runtime, or web UI surface was started or modified.
- Phase 03.1 remains the active root planning workstream.

## Self-Check: PASSED

- All eight implementation/test artifacts and this summary exist.
- All four Task 1/Task 2 RED and GREEN commits are present in repository history.
- Summary frontmatter is valid and marks all three plan requirements complete.
- Root `.planning/STATE.md` remains unchanged with Phase 03.1 active.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
