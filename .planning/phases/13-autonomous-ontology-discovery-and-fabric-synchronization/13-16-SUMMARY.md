---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
plan: 16
subsystem: ontology-coordinator
tags: [onelake, foundry, etag-cas, reconciliation, fair-scheduling]

requires:
  - phase: 13-07
    provides: Scheduled finite ontology Job, proposal-only curator, and separated identities
  - phase: 13-15
    provides: Exact alert coverage and credentialed shadow validation
provides:
  - Production CLI composition from explicit OneLake connection, command, state, and dispatch roots
  - Reauthorized typed command intake and content-addressed publisher dispatch
  - Restart-safe eligible-set epochs with bounded fair retry rotation
  - Durable full/incremental reconciliation cadence, watermarks, parity, and drift repair evidence
  - Bearer-authenticated, version-bound Foundry transport regression coverage
affects: [13-17, 13-18, 13-19, publisher-worker, ontology-api]

actuals:
  tokens: 28971
  tasks: 3
  commits: 8

tech-stack:
  added: []
  patterns:
    - Explicit process capability roots with pairwise anti-alias validation
    - Service-ETag CAS for shared coordinator documents
    - Immutable eligible-set snapshots with durable round-robin cursor
    - Canonical full/replay graph parity with full rebuild as repair authority

key-files:
  created:
    - src/ontology_discovery/runtime.py
    - src/ontology_discovery/command_intake.py
    - src/ontology_discovery/dispatch_store.py
    - tests/test_ontology_discovery_runtime.py
  modified:
    - src/ontology_discovery/cli.py
    - src/ontology_discovery/store.py
    - src/ontology_discovery/incremental.py
    - tests/test_ontology_discovery_incremental.py
    - tests/test_ontology_curator_agent.py

key-decisions:
  - "Coordinator authority is rooted only in explicit connection-read, command-claim/status, state-read/write, and dispatch-create/read homes; publication authority is rejected."
  - "An active eligible-set epoch is immutable across registry churn; every inspected member advances the durable cursor and reaches success, duplicate, exhausted failure, or closed exclusion."
  - "Watermarks advance only after immutable publisher dispatch creation, and canonical full rebuild output is the repair authority when replay parity detects drift."
  - "Production Foundry calls require a credential-free HTTPS endpoint and exact non-empty agent version; bearer credentials remain on the request and are redacted only at observation boundaries."

patterns-established:
  - "Typed intake: caller intent is immutable and untrusted until current registry scope, action, eligibility, environment, and expiry are reauthorized."
  - "Fair coordinator pass: one process invocation may scan skipped members but claims and processes at most one eligible connection."
  - "Reconciliation commit: dispatch durability precedes parity result persistence and watermark CAS."

requirements-completed: [AUTO-ONT-01, AUTO-ONT-02, AUTO-ONT-03, AUTO-ONT-04, AUTO-ONT-06, AUTO-ONT-07]

coverage:
  - id: D1
    description: Exact CLI production composition persists a successful run, bounded evidence, advisory proposal, and hard-shadow publisher dispatch.
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: tests/test_ontology_discovery_runtime.py#test_cli_main_real_composition_persists_evidence_proposal_and_dispatch
        status: pass
    human_judgment: false
  - id: D2
    description: Manual command intake reauthorizes current scope before creating coordinator state.
    requirement: AUTO-ONT-06
    verification:
      - kind: integration
        ref: tests/test_ontology_discovery_runtime.py#test_manual_intake_reauthorizes_current_scope_before_creating_run
        status: pass
    human_judgment: false
  - id: D3
    description: Eligible-set epochs drain without starvation across retries and process replacement.
    requirement: AUTO-ONT-01
    verification:
      - kind: integration
        ref: tests/test_ontology_discovery_runtime.py#test_eligible_epoch_rotates_retrying_head_and_survives_every_restart
        status: pass
    human_judgment: false
  - id: D4
    description: Full and incremental reconciliation persist cadence, watermarks, parity, and drift repair evidence.
    requirement: AUTO-ONT-02
    verification:
      - kind: integration
        ref: tests/test_ontology_discovery_runtime.py#test_reconciliation_cadence_watermark_and_drift_survive_restart
        status: pass
      - kind: unit
        ref: tests/test_ontology_discovery_incremental.py#test_deterministic_trials_survive_duplicates_reordering_and_restart[0..99]
        status: pass
    human_judgment: false
  - id: D5
    description: Default Foundry transport sends the bearer credential, preserves exact agent version, redacts failures, and closes token resources.
    requirement: AUTO-ONT-03
    verification:
      - kind: integration
        ref: tests/test_ontology_curator_agent.py#test_default_transport_sends_bearer_and_redacts_http_failure
        status: pass
      - kind: integration
        ref: tests/test_ontology_curator_agent.py#test_default_transport_success_preserves_versioned_payload
        status: pass
    human_judgment: false
  - id: D6
    description: Coordinator roots are explicit, pairwise distinct, and structurally exclude publication authority.
    requirement: AUTO-ONT-07
    verification:
      - kind: unit
        ref: tests/test_ontology_discovery_runtime.py#test_capability_roots_are_explicit_distinct_and_dispatch_only
        status: pass
      - kind: unit
        ref: tests/test_ontology_discovery_runtime.py#test_production_config_requires_all_roots_and_agent_version
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-09-07
status: complete
---

# Phase 13 Plan 16: Production Coordinator Foundation Summary

**A real OneLake-backed coordinator now drains eligible connections fairly through inventory, versioned Foundry curation, hard-shadow policy, validation, reconciliation, and immutable publisher dispatch.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-09-07T06:30:00Z
- **Completed:** 2026-09-07T06:44:52Z
- **Tasks:** 3
- **Files modified:** 9 implementation/test files

## Accomplishments

- Replaced `_RecordOnlyProcessor` with a fail-closed production runtime using four explicit, distinct capability roots and no coordinator publication authority.
- Added typed create-only command intake, current-registry reauthorization, OneLake-backed lifecycle state, immutable publish dispatches, and restart-safe CAS behavior.
- Added starvation-free immutable eligible-set epochs whose cursor rotates past retries, duplicates, and exclusions while processing no more than one connection per pass.
- Added durable cadence-driven full/incremental selection, canonical parity and drift evidence, post-dispatch watermark commits, and 100 seeded recovery trials.
- Locked the real bearer-authenticated Foundry request boundary with `httpx.MockTransport`, exact deployed agent version checks, sanitized failures, and close coverage.

## Task Commits

1. **Task 1: Production scheduler composition and durable dispatch**
   - `7664db4f` — RED production coordinator contracts
   - `6bf11c36` — OneLake command/state/dispatch composition and fair scheduler
2. **Task 2: Durable full/incremental reconciliation**
   - `efd7fbb6` — RED cadence, watermark, drift, and 100-seed contracts
   - `e90958f7` — durable reconciliation controls and canonical parity
3. **Task 3: Secure versioned Foundry transport**
   - `df506cb8` — RED outbound request and fail-closed configuration contracts
   - `9ee45458` — HTTPS and exact version production enforcement

Additional verification/fix commits:

- `bfcc032b` — fenced scheduled-run lifecycle correction
- `6bbe6217` — exact `cli.main` production-composition integration proof

## Files Created/Modified

- `src/ontology_discovery/runtime.py` — production config, reauthorizing intake, fair scheduler, real evidence/curator/policy/validator/dispatch pipeline.
- `src/ontology_discovery/command_intake.py` — typed immutable manual, maintenance, and rollback command envelopes with narrow coordinator claims.
- `src/ontology_discovery/dispatch_store.py` — content-addressed publish dispatches and separated coordinator/publisher capability views.
- `src/ontology_discovery/store.py` — OneLake document backend, eligible epochs, reconciliation controls/results/audits, and ETag-backed CAS.
- `src/ontology_discovery/incremental.py` — canonical graph normalization, hashing, and full/replay parity.
- `src/ontology_discovery/cli.py` — exact production runtime entry point with a hard one-connection pass bound.
- `tests/test_ontology_discovery_runtime.py` — capability, intake, restart fairness, reconciliation, config, and exact CLI integration tests.
- `tests/test_ontology_discovery_incremental.py` — 100 deterministic duplicate/retry/reorder/restart parity trials.
- `tests/test_ontology_curator_agent.py` — real outbound bearer, versioned payload, redaction, and close tests.

## Decisions Made

- Kept coordinator publication capability structurally absent rather than relying on a runtime deny check.
- Snapshot registry membership and revision once per epoch; registry changes are deferred to the next epoch so a changing first connection cannot starve later members.
- Treat full reconstruction as authoritative repair output and persist only opaque parity counts/hashes before advancing the committed watermark.
- Preserve the already-correct bearer behavior in `curator.py`; add executable request inspection instead of changing a working transport because the earlier verifier display had redacted the source literal.
- Preserved all Phase 03.1 active STATE position fields while recording Phase 13 metrics and roadmap/requirements progress.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Rejected insecure Foundry project endpoints**
- **Found during:** Task 3 RED investigation
- **Issue:** Production required a non-empty endpoint but accepted plaintext HTTP or credential-bearing URLs.
- **Fix:** Added absolute, credential-free HTTPS validation before runtime construction.
- **Files modified:** `src/ontology_discovery/runtime.py`
- **Verification:** Production config rejection test and targeted Ruff pass.
- **Committed in:** `9ee45458`

**2. [Rule 1 - Bug] Persisted the scheduled run lifecycle around provider work**
- **Found during:** Overall verification
- **Issue:** The first scheduler implementation recorded epoch outcomes but did not claim, fence, retry, and complete the authoritative run record.
- **Fix:** Added durable run claim/failure/success transitions and a sanitized publisher-dispatch checkpoint.
- **Files modified:** `src/ontology_discovery/runtime.py`
- **Verification:** Complete 171-test plan gate passes, including exact CLI reconstruction.
- **Committed in:** `bfcc032b`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 bug)
**Impact on plan:** Both fixes enforce required production security and durability; no scope expansion beyond the plan's 10-file boundary.

## Issues Encountered

- The Task 3 bearer-header RED assertion passed unexpectedly. Bytecode inspection confirmed the transport already sent `Bearer <token>`; source display had redacted the literal. The test was retained as executable regression coverage, and the RED gate moved to the missing HTTPS endpoint validation.
- Repository-wide `pytest` reaches three pre-existing ontology graph failures in unchanged `ontology_sync.py` paths. Repository-wide Ruff also retains 27 pre-existing legacy-script findings. Both are recorded in `deferred-items.md`; all Plan 13-16 tests and changed-file Ruff checks pass.

## Verification

- `uv run pytest -q tests/test_ontology_discovery_runtime.py tests/test_ontology_discovery_store.py tests/test_ontology_discovery_incremental.py tests/test_ontology_curator_agent.py tests/test_ontology_proposal_policy.py -x` — **171 passed**
- Task 2 focused cadence/watermark/drift/seed gate — **103 passed**
- Changed-file `uv run ruff check ...` — **passed**
- `uv run python .planning/scripts/preflight_phase_13.py` — **passed**
- Full `uv run pytest -q` — **3 pre-existing out-of-scope failures**
- Full `uv run ruff check .` — **27 pre-existing out-of-scope findings**

## Known Stubs

None. Empty collections and optional values found by the stub scan are typed lifecycle defaults, test assertions, or valid empty graph inputs rather than unwired production UI/data placeholders.

## User Setup Required

Production must provide explicit, pairwise-distinct OneLake URIs in:

- `AIOPS_CONNECTION_HOME`
- `AIOPS_ONTOLOGY_COMMAND_HOME`
- `AIOPS_ONTOLOGY_STATE_HOME`
- `AIOPS_ONTOLOGY_DISPATCH_HOME`

It must also provide `AIOPS_RUNTIME_MODE=production`, `AIOPS_CONFIG_PATH`, `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_ONTOLOGY_AGENT_NAME`, and `FOUNDRY_ONTOLOGY_AGENT_VERSION`. The coordinator rejects publication roots and publisher credentials.

## Next Phase Readiness

- Plan 13-17 can consume the publisher capability view and process immutable publish dispatches without changing coordinator authority.
- Plan 13-18 can reuse `CommandIntakeService` for API create/read/status while keeping dispatch absent.
- The active Phase 03.1 position remains unchanged; Plan 17 was not started.

## Self-Check: PASSED

All created production files and all eight task/TDD/fix commits were found in
the target worktree.

---
*Phase: 13-autonomous-ontology-discovery-and-fabric-synchronization*
*Completed: 2026-09-07*
