---
phase: 10-fabric-medallion-capability-expansion
plan: 03
subsystem: fabric
tags: [ontology, fabric, onelake, opentelemetry, durability, telemetry, tdd]

# Dependency graph
requires:
  - phase: 10-01
    provides: "OntologyPublisher.build_definition() preflight validation (ValueError before any Fabric network call), verified via test_publish_never_resolves_when_build_definition_fails"
provides:
  - "ontology.publication_state.PublicationStateStore: durable, per-ontology terminal-state record of publish attempts (rejected/failed/succeeded), backed by OneLakeDocumentStore"
  - "ConnectionSyncCoordinator wiring that records every publish attempt's terminal state in addition to logger.exception()"
  - "FabricMetrics.publish_preflight_rejected / publish_retry OpenTelemetry counters"
affects: [10-fabric-medallion-capability-expansion, fabric-health-api, ontology]

# Actuals (#2632) — pairs with the plan's `estimate` to calibrate future estimates.
# Same estimateTokens scale (chars/4 over the realized diff), never a harness token count.
actuals:
  tokens: 6825
  tasks: 3
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Small control-plane documents (single-record durable state, not a bulk dataset) persist via storage.onelake_documents.OneLakeDocumentStore.put() (last-writer-wins), the same tier already used by onboarding.store (connection registry) and intelligence.vulnerability.enrichment_cache (CVE cache) -- no new storage backend."
    - "Optional constructor-injected `metrics`/`*_store` params (mirrors fabric.sync_service.OntologySyncService's `metrics or FabricMetrics()`), so production code defaults sensibly while tests substitute fakes without touching real OpenTelemetry instruments."

key-files:
  created:
    - src/ontology/publication_state.py
    - tests/test_ontology_publish_durability.py
  modified:
    - src/onboarding/sync.py
    - src/fabric/telemetry.py

key-decisions:
  - "PublicationStateStore persists the *latest* attempt per ontology_name as a single revisioned JSON document via OneLakeDocumentStore.put() (last-writer-wins), not the strict-CAS registry pattern -- losing a race only costs one stale terminal-state read, an acceptable trade-off for an operator-visibility surface (unlike the connection registry, which guards user-facing mutations)."
  - "retryable is derived from fabric.fabric_client.FabricClient.TRANSIENT_STATUS (429/500/502/503/504) plus httpx.TransportError -- the exact same class of error fabric_client.py's own bounded backoff loop already gives up on -- rather than inventing a new retry taxonomy."
  - "onology_name defaults to 'Operational_Context_Graph' (fabric.config.FabricConfig.ontology.ontology_name's default) as a local literal in publication_state.py rather than importing fabric.config, preserving onboarding.sync's existing 'must not depend on fabric config' boundary (see tests/test_relationship_vocabulary_consistency.py's docstring)."
  - "Telemetry call-sites (record_publish_preflight_rejected/record_publish_retry) were wired into ConnectionSyncCoordinator alongside the durability wiring (Task 1's GREEN commit) rather than only in Task 2, since FabricMetrics is only imported/constructed there and Task 2's own <files> list restricts it to telemetry.py only. The calls are inert (silently caught AttributeError, logged, durability unaffected) until Task 2's commit defines the counters -- verified by running Task 1's tests against telemetry.py at its pre-Task-2 state before committing."

requirements-completed: [MED-01]

coverage:
  - id: D1
    description: "Every ontology publish outcome (preflight-rejected, retryable-failed, succeeded) produces a durable, queryable PublicationAttemptRecord that survives a fresh PublicationStateStore instance"
    requirement: "MED-01"
    verification:
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_preflight_rejection_records_durable_state"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_transient_failure_records_durable_state"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_successful_publish_records_durable_state"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_publication_state_persists_across_fresh_store_instance"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_publication_attempt_count_increments_across_repeated_attempts"
        status: pass
    human_judgment: false
  - id: D2
    description: "Preflight rejections and retryable Fabric failures emit OpenTelemetry counters (FabricMetrics.publish_preflight_rejected / publish_retry) with no PII/payload attributes, and never fire on success or non-retryable failures"
    requirement: "MED-01"
    verification:
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_preflight_rejection_increments_telemetry_counter"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_transient_failure_increments_telemetry_counter"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_successful_publish_does_not_increment_telemetry_counters"
        status: pass
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_non_transient_failure_does_not_increment_retry_telemetry_counter"
        status: pass
    human_judgment: false
  - id: D3
    description: "manager.resolve() is never invoked when build_definition() raises, exercised end-to-end through ConnectionSyncCoordinator (not just a direct OntologyPublisher.publish() call)"
    verification:
      - kind: unit
        ref: "tests/test_ontology_publish_durability.py#test_manager_resolve_never_invoked_when_build_definition_raises"
        status: pass
    human_judgment: false

# Metrics
duration: 21min
completed: 2026-09-01
status: complete
---

# Phase 10 Plan 03: Durable Ontology Publication Terminal State & Telemetry Summary

**Durable per-ontology `PublicationAttemptRecord` (rejected/failed/succeeded) backed by `OneLakeDocumentStore`, plus `FabricMetrics.publish_preflight_rejected`/`publish_retry` OpenTelemetry counters, wired into `ConnectionSyncCoordinator`'s existing publish exception handler.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-09-01T07:54:11Z
- **Completed:** 2026-09-01T08:15:11Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `ontology.publication_state.PublicationStateStore` durably records the latest ontology-publish attempt (outcome, retryable, error, attempt_count) per `ontology_name`, surviving a fresh store instance reading the same backing root -- closing MED-01's "durable state" gap.
- `ConnectionSyncCoordinator`'s publish try/except now distinguishes a preflight `ValueError` (never retried) from any other Fabric REST failure (retryable only when it carries one of `fabric_client.FabricClient.TRANSIENT_STATUS`'s own codes, mirroring the exact class of error that client's own bounded backoff loop already gives up on).
- `FabricMetrics` gains `publish_preflight_rejected`/`publish_retry` counters (low-cardinality status-code dimension only, no payload/PII), closing MED-01's "telemetry" gap.
- Added an end-to-end preflight-ordering regression (`manager.resolve()` never invoked when `build_definition()` raises) exercised through the full `ConnectionSyncCoordinator` path, completing the assertion noted but not filed as its own test in Plan 10-01 Task 1.

## Task Commits

Task 1 followed the TDD RED/GREEN cycle (`tdd="true"`); Tasks 2 and 3 were single commits:

1. **Task 1 (RED): failing test for durable publication attempt record** - `3dd0877a` (test)
2. **Task 1 (GREEN): durable per-publication-attempt terminal-state record** - `e83f1c5b` (feat)
3. **Task 2: telemetry for publish preflight rejections and retries** - `4bf4f217` (feat)
4. **Task 3: telemetry and call-ordering regression tests** - `48fccc69` (test)

No plan-metadata commit was made — `.planning/` is tracked in this repo but the phase directory's SUMMARY/STATE/ROADMAP updates are captured in the final commit described below (see Self-Check).

_TDD Gate Compliance: RED (`3dd0877a`) precedes GREEN (`e83f1c5b`); no REFACTOR commit was needed (GREEN was already clean)._

## Files Created/Modified
- `src/ontology/publication_state.py` - New: `PublicationAttemptRecord` dataclass + `PublicationStateStore` (durable, OneLake/local-disk-backed, last-writer-wins per `ontology_name`)
- `src/onboarding/sync.py` - `ConnectionSyncCoordinator` gains `publication_state_store`/`ontology_name`/`metrics` constructor params and a `_record_publication_attempt()` helper wired into the existing publish exception handler
- `src/fabric/telemetry.py` - `FabricMetrics.publish_preflight_rejected`/`publish_retry` counters + `record_publish_preflight_rejected()`/`record_publish_retry(status_code)` methods
- `tests/test_ontology_publish_durability.py` - New: 10 tests covering durability, telemetry, and the preflight call-ordering regression

## Decisions Made
- See `key-decisions` in frontmatter above (storage-tier choice, retryable-status derivation, `ontology_name` default literal to preserve the fabric-config-agnostic boundary, and the Task-1/Task-2 telemetry-wiring split rationale).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] `_record_publication_attempt` is exception-safe end-to-end**
- **Found during:** Task 1 (wiring `sync.py`)
- **Issue:** The plan's action text didn't explicitly call out that recording (durable store write + telemetry) must never itself break the sync run it is describing.
- **Fix:** Wrapped the entire recording body in a `try/except Exception: logger.exception(...)` (mirroring the existing `noqa: BLE001, S110` discipline already used for `_report()` in the same file), and verified this by running Task 1's tests against a `telemetry.py` state that did *not yet* have the counter methods defined (i.e., before Task 2's commit) — confirming durability recording succeeds even when the telemetry call inside the same method raises `AttributeError`.
- **Files modified:** `src/onboarding/sync.py`
- **Verification:** `pytest tests/test_ontology_publish_durability.py -q` passed at the Task-1 GREEN commit, before `telemetry.py` was touched.
- **Committed in:** `e83f1c5b` (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Necessary for correctness — a durability/telemetry recording bug must never surface as a sync-run failure. No scope creep.

## Issues Encountered
- **Concurrent execution on the shared working tree:** another executor (Plan 10-02, MED-06 DataQualityValidator work) was committing to the same branch (`fix-ontology-sync-publish`) concurrently while this plan ran, interleaving commits (`a98acb94`, `b3722abf`, `adc20daa`, `d4e70e49`) between this plan's own commits. A `pytest tests/ -q` run against the live working tree at one point showed ~38 failures (mostly `tests/test_incremental_sync.py`) caused entirely by that other agent's in-flight (uncommitted at the time) `src/fabric/data_quality.py` changes — none of it caused by this plan. Verified by checking out a disposable `git worktree` at the pre-10-03 commit (`a98acb94`) and copying only this plan's final files on top: exactly the same 10 pre-existing failures appeared (8 in `test_data_quality.py` from 10-02's own in-progress TDD RED state, plus 2 unrelated pre-existing failures in `test_service.py`/`test_situations_tracer.py`), and zero new failures. This plan's changes are confirmed clean; the transient full-suite noise was a snapshot of concurrent, uncommitted work by a sibling executor, not a defect in this plan.

## Next Phase Readiness
- MED-01 is now fully closed: preflight-validation (Plan 10-01) + durable state and telemetry (this plan) are both proven.
- `PublicationStateStore` is ready to be read by the later Fabric medallion health API plan mentioned in this plan's `<objective>` — it exposes `.get(ontology_name)` and `.list()` for that purpose.
- No blockers for subsequent phase-10 plans.

---
*Phase: 10-fabric-medallion-capability-expansion*
*Completed: 2026-09-01*

## Self-Check: PASSED

All created/modified files confirmed present on disk; all 4 commit hashes (`3dd0877a`, `e83f1c5b`, `4bf4f217`, `48fccc69`) confirmed present in `git log --oneline --all`.
