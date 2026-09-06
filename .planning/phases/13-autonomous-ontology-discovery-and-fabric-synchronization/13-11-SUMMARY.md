---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 11
subsystem: evaluation-storage
tags: [pydantic, content-addressing, onelake, cas, freshness, release-safety]

requires:
  - phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
    plan: 01
    provides: dependency preflight, shadow-safe contract foundation, and adversarial Wave 0 corpus
provides:
  - strict content-addressed EvaluationSnapshot contract with complete evaluation lineage
  - immutable durable snapshot history with a revision/ETag CAS latest pointer
  - restart-safe fresh, stale, missing, and invalid evidence classification
  - fail-closed release-evidence lookup that retains stale and prior valid audit history
affects: [13-12, 13-13, 13-14, release-policy, evaluation-api]

actuals:
  tokens: 9748
  tasks: 2
  commits: 4

tech-stack:
  added: []
  patterns:
    - frozen strict Pydantic evaluation contracts with content-derived identity
    - immutable snapshot documents plus independent history index and small CAS pointer
    - earliest source-specific expiry controls freshness and release eligibility

key-files:
  created:
    - src/ontology_discovery/evaluation.py
    - src/ontology_discovery/evaluation_store.py
    - tests/test_ontology_evaluation_snapshot.py
  modified: []

key-decisions:
  - "Persist only opaque scope-<hash> keys and sanitized artifact references; raw prompts, evidence, paths, URLs, and tenant identifiers are excluded from the snapshot contract."
  - "Treat the earliest global or source-specific expiry as authoritative, with the exact boundary classified stale."
  - "Write and index immutable evidence before attempting the latest-pointer CAS, so a lost race retains audit history but cannot change release evidence."
  - "Keep pointer reconstruction independent from history reconstruction, allowing invalid latest state to degrade visibly without discarding prior valid snapshots."

patterns-established:
  - "Evaluation identity: canonical serialized contract content determines an immutable EVS-<SHA256> identity."
  - "Release evidence: only a valid, fresh, explicitly eligible latest snapshot may authorize policy; all other states return no evidence."

requirements-completed: [AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Strict versioned EvaluationSnapshot captures reproducible lineage, metrics, thresholds, failures, expiry, eligibility, and sanitized artifacts.
    requirement: AUTO-ONT-07
    verification:
      - kind: unit
        ref: "tests/test_ontology_evaluation_snapshot.py#test_contract_is_strict_frozen_bounded_and_content_addressed"
        status: pass
    human_judgment: false
  - id: D2
    description: Immutable snapshots are durable before a conflict-safe latest pointer can expose them to release consumers.
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: "uv run pytest -q tests/test_ontology_evaluation_snapshot.py -k 'contract or write or cas' -x"
        status: pass
    human_judgment: false
  - id: D3
    description: Fresh processes reconstruct bounded history and classify fresh, stale, missing, invalid, corrupt, and legacy evidence without authorizing stale or invalid release.
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: "uv run pytest -q tests/test_ontology_evaluation_snapshot.py -x"
        status: pass
    human_judgment: false

duration: 7min
completed: 2026-09-06
status: complete
---

# Phase 13 Plan 11: Durable Evaluation Snapshot Summary

**Strict content-addressed evaluation snapshots now survive restart, preserve immutable audit history, classify source-aware freshness deterministically, and fail closed before release-policy consumption.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-09-06T10:56:03Z
- **Completed:** 2026-09-06T11:02:35Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added a frozen, strict `EvaluationSnapshot` contract containing opaque scope identity, UTC observation/evaluation/expiry times, dataset/prompt/schema/model/agent/policy versions and hashes, bounded slice metrics and thresholds, critical failures, release eligibility, source expiries, and sanitized artifact references.
- Persisted content-addressed snapshots as immutable documents before updating an independent bounded history index and revision/ETag-protected latest pointer; stale CAS writers cannot replace current evidence.
- Added process-cache-free `latest()`, `history()`, and `release_evidence()` reads with exact fresh/stale/missing/invalid states, source-specific stale boundaries, corruption handling, safe legacy degradation, and retained valid history.

## Task Commits

Each TDD task was committed through RED then GREEN:

1. **Task 1 RED: EvaluationSnapshot contract and durable-write tests** - `5a7e66fb`
2. **Task 1 GREEN: Immutable snapshots and CAS latest pointer** - `c0a10435`
3. **Task 2 RED: Restart, freshness, corruption, and legacy tests** - `d0ea0a34`
4. **Task 2 GREEN: Reconstruction and fail-closed release lookup** - `1e437e1c`

## Files Created/Modified

- `src/ontology_discovery/evaluation.py` - Strict evaluation lineage, metric, threshold, expiry, artifact, status, and content-addressed snapshot contracts.
- `src/ontology_discovery/evaluation_store.py` - Immutable snapshot persistence, independent history indexing, CAS latest pointer, restart reconstruction, and release-evidence lookup.
- `tests/test_ontology_evaluation_snapshot.py` - Contract, write ordering, CAS, restart, freshness boundary, corruption, history-retention, missing-snapshot, and legacy regressions.

## Decisions Made

- Scope identity is represented only by an opaque `scope-<hash>` key and matching hash; the contract cannot accept a raw subscription or tenant path.
- Snapshot identity covers every governed field except the identity itself, using canonical JSON and SHA-256.
- Freshness expires at the earliest global or source-specific deadline. Equality with the deadline is stale, not fresh.
- Pointer corruption and missing immutable content are `invalid`; an absent pointer is `missing`; an expired valid snapshot is `stale` and remains auditable.
- A failed pointer CAS may leave a new immutable snapshot in history, but cannot make it latest or release-eligible.
- Root `.planning/STATE.md` remains owned by active Phase 03.1 and was not changed for this approved concurrent Phase 13 plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Canonicalized nested Pydantic values during content hashing**
- **Found during:** Task 1 GREEN
- **Issue:** The first identity serializer handled datetimes but not nested frozen contract models, so snapshot construction failed before persistence.
- **Fix:** Serialize nested `BaseModel` values through their JSON-mode model dump before hashing.
- **Files modified:** `src/ontology_discovery/evaluation.py`
- **Verification:** Task 1 contract/write/CAS suite passes.
- **Committed in:** `c0a10435`

**2. [Rule 1 - Bug] Kept generated metric numerator consistent with its test value**
- **Found during:** Task 1 GREEN
- **Issue:** The test factory varied precision while retaining a hardcoded numerator, correctly tripping the contract's ratio-integrity validator.
- **Fix:** Derive the test numerator from the requested precision.
- **Files modified:** `tests/test_ontology_evaluation_snapshot.py`
- **Verification:** Task 1 and complete Plan 13-11 suites pass.
- **Committed in:** `c0a10435`

---

**Total deviations:** 2 auto-fixed bugs.
**Impact on plan:** Both fixes were required for deterministic contract correctness; no feature or architectural scope was added.

## Issues Encountered

- Context7 CLI was unavailable in the environment. The implementation was validated against the repository-locked Pydantic 2.13.4 runtime and existing local strict-contract patterns without adding or changing dependencies.

## Verification

- `uv run python .planning/scripts/preflight_phase_13.py` — passed; Phase 10 and Phase 12 evidence complete.
- `uv run pytest -q tests/test_ontology_evaluation_snapshot.py -k 'contract or write or cas' -x` — 4 passed.
- `uv run pytest -q tests/test_ontology_evaluation_snapshot.py -x` — 10 passed.
- `uv run pytest -q tests/test_onelake_documents.py tests/test_ontology_discovery_store.py tests/test_ontology_discovery_coordinator.py tests/test_ontology_discovery_contracts.py -x` — 36 passed.
- `uv run ruff check src/ontology_discovery/evaluation.py src/ontology_discovery/evaluation_store.py` — passed.

## Known Stubs

None.

## Threat Model

- **T13-E1 (latest-pointer tampering):** Content-addressed immutable records, scope/path consistency checks, revision/ETag CAS, and corruption/restart tests fail closed.
- **T13-E2 (metric-lineage repudiation):** Every snapshot binds all required version/hash/time/threshold facts into its content identity.
- No unplanned security-relevant endpoint, authentication, schema, or file-access surface was introduced beyond the plan's declared evaluation-store boundary.

## User Setup Required

None - local filesystem and OneLake document-store modes share the same contract, with no new environment variables or deployment steps.

## Next Phase Readiness

- Plan 13-12 can project deterministic latest/history/status and release-evidence APIs without relying on process memory.
- Plan 13-14 can persist evaluator output before any release-gate consumer observes it.
- Plan 13-03 and all other later plans remain unstarted in this execution.

## Self-Check: PASSED

- All three Plan 13-11 source/test artifacts exist.
- All four RED/GREEN task commits exist and contain the required Copilot co-author trailer.
- Required preflight, task verification, relevant storage/ontology regressions, and source lint all passed.
- Root `.planning/STATE.md` still identifies Phase 03.1 as the active workstream and is unchanged from the plan start.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-06*
