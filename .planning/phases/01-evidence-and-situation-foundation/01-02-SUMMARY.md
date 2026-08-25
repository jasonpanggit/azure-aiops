---
phase: 01-evidence-and-situation-foundation
plan: 02
subsystem: api
tags: [fastapi, delta, azure-resource-graph, nextjs, authorization, audit]

requires:
  - phase: 01-evidence-and-situation-foundation
    provides: Durable situation models, immutable generation storage, scoped API primitives, and the operator UI foundation
provides:
  - Production six-family evidence normalization with persisted source statuses
  - Qualified operational links, append-only audit events, and stable Delta append identity
  - Recursive nested authorization and durable queue/detail/dashboard workbench wiring
affects: [phase-2-investigation-and-approval, phase-4-domain-coverage]

actuals:
  tokens: 31658
  tasks: 3
  commits: 5

tech-stack:
  added: []
  patterns:
    - Canonical source-family normalization with provider failures retained as data
    - Stable event-key append deduplication with mutation rejection
    - Provider-bound recursive scope filtering before API serialization

key-files:
  created:
    - web/src/app/situations/page.test.tsx
  modified:
    - src/hermes_arg_connector/normalize.py
    - src/situations/materializer.py
    - src/situations/store.py
    - src/storage/delta_writer.py
    - web/src/app/situations/[id]/page.tsx
    - web/src/app/page.tsx

key-decisions:
  - "Keep all six source families on the existing NormalizedGraph and immutable generation path; do not add a parallel ingestion store."
  - "Persist unresolved operational links with explicit quality instead of dropping targets that are absent from the authorized entity index."
  - "Treat physical ingestion run identifiers as write metadata when comparing repeated audit appends, while keeping event_id as the immutable audit identity."

patterns-established:
  - "Source trust: every canonical family has a status row, including empty, failed, and unavailable providers."
  - "Read authorization: authorize the parent situation first, then filter every nested resource, evidence, link, source-status, locator, and audit reference."

requirements-completed: [FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, DETECT-01, DETECT-02]

coverage:
  - id: D1
    description: "Six canonical evidence families flow through production normalization and retain source trust metadata."
    requirement: DETECT-01
    verification:
      - kind: integration
        ref: "tests/test_situations_tracer.py::test_normalizer_production_graph_contains_all_six_signal_families"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_situations_tracer.py tests/test_service.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Required operational links, unresolved quality, lifecycle audit events, and stable append protection are persisted."
    requirement: FOUND-04
    verification:
      - kind: unit
        ref: "tests/test_situations_ontology.py::test_required_operational_link_families_are_retained_when_unresolved"
        status: pass
      - kind: unit
        ref: "tests/test_situations_audit.py::test_delta_audit_append_uses_stable_event_id_and_rejects_mutation"
        status: pass
    human_judgment: false
  - id: D3
    description: "Nested situation reads remove out-of-scope evidence, links, source statuses, and audit references before serialization."
    requirement: FOUND-05
    verification:
      - kind: unit
        ref: "tests/test_situations_authorization.py::test_nested_scope_filters_evidence_links_source_status_and_audit_references"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_situations_api.py tests/test_situations_authorization.py tests/test_api_primitives.py -q"
        status: pass
    human_judgment: false
  - id: D4
    description: "Durable queue, dashboard, trust details, evidence drawer, linked entities, and service-recorded audit timeline are wired to situationsApi."
    requirement: FOUND-03
    verification:
      - kind: automated_ui
        ref: "cd web && npm test -- --run src/lib/situations.test.ts src/components/SituationTable.test.tsx src/app/situations/page.test.tsx 'src/app/situations/[id]/page.test.tsx'"
        status: pass
      - kind: other
        ref: "cd web && npm run build"
        status: pass
    human_judgment: true
    rationale: "Responsive visual hierarchy, real local API startup, keyboard/focus behavior at multiple viewport sizes, and the nine-step operator walkthrough require human verification."
  - id: D5
    description: "Phase 1 has a single-line validator-approved MVP user-story goal."
    verification:
      - kind: other
        ref: "gsd-tools query user-story.validate --story <Phase 1 goal> --pick valid"
        status: pass
    human_judgment: false

duration: 22 min
completed: 2026-08-25
status: complete
---

# Phase 01 Plan 02: Production Evidence and Durable Workbench Summary

**Six-family production evidence now reaches durable situations with qualified trust, scoped nested reads, immutable audit history, and a durable operator queue/detail experience.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-08-25T13:44:01Z
- **Completed:** 2026-08-25T14:04:40Z
- **Tasks:** 3
- **Files modified:** 28

## Accomplishments

- Wired ARG activity, Monitor, Service Health, Defender, Policy, and vulnerability observations through the production normalizer, immutable generation, curated mapping, and source-status reads.
- Added typed operational links with unresolved quality, contradiction/unknown qualification, evidence-ingested and lifecycle audit events, and stable Delta append deduplication with mutation rejection.
- Enforced recursive nested authorization and connected the queue, command center, durable detail, trust summary, evidence drawer, linked entities, and service audit timeline to persisted situation records.
- Added queue/detail/API regression coverage and validated the Phase 1 MVP goal with the centralized user-story validator.

## Task Commits

1. **Task 1: Tracer — carry one production source family through durable publication and read** — `a67f0ab`
2. **Task 2: Expand six-family trust, operational links, and immutable audit persistence** — `f36696a`
3. **Task 3: Complete recursive authorization, durable workbench wiring, queue coverage, and MVP planning gate** — `3e1f6af`
4. **Rule 1 fix: keep projected situation links ontology-valid** — `cf6a059`

## Files Created/Modified

- `src/hermes_arg_connector/queries.py` — canonical six-family provider query specifications.
- `src/hermes_arg_connector/normalize.py` and `src/situations/materializer.py` — source normalization, qualification, links, and audit emission.
- `src/hermes_arg_connector/storage.py`, `src/fabric/dataset_mapper.py`, `src/fabric/schema_registry.py`, `src/fabric/sync_service.py` — immutable generation and curated Delta publication.
- `src/storage/delta_writer.py` — caller-supplied append keys, duplicate comparison, and mutation rejection.
- `src/situations/store.py` — recursive authorization projection.
- `web/src/app/page.tsx`, `web/src/app/situations/page.tsx`, `web/src/app/situations/[id]/page.tsx`, and trust/API helpers — durable workbench wiring.
- `tests/test_situations_tracer.py`, `tests/test_situations_ontology.py`, `tests/test_situations_audit.py`, `tests/test_situations_authorization.py`, and `web/src/app/situations/page.test.tsx` — regression coverage.

## Decisions Made

- Kept Delta/OneLake authoritative and ontology read-oriented; no second situation store was introduced.
- Used service-recorded audit events only for audit history; local “Save view locally” state is not represented as server audit.
- Retained the manual UI walkthrough as human judgment rather than treating passing component tests and a production build as visual proof.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected ontology relationship type consistency**
- **Found during:** Overall verification
- **Issue:** Resolved Resource links could be projected with the generic link type instead of the canonical ontology entity type, causing the validator to reject the relationship.
- **Fix:** Projected the resolved target’s actual ontology type while retaining the curated link type in link payloads.
- **Files modified:** `src/fabric/dataset_mapper.py`
- **Verification:** `uv run pytest tests/test_situations_ontology.py tests/test_incremental_sync.py -q`
- **Committed in:** `cf6a059`

**2. [Rule 1 - Bug] Preserved stable evidence-ingestion event content across replay runs**
- **Found during:** Task 2 verification
- **Issue:** Replaying the same source record changed its ingestion timestamp and caused the stable audit event to be treated as a mutation.
- **Fix:** Preserved the prior evidence ingestion timestamp and excluded only physical ingestion-run metadata from duplicate content comparison.
- **Files modified:** `src/hermes_arg_connector/service.py`, `src/storage/delta_writer.py`
- **Verification:** `uv run pytest tests/test_service.py tests/test_incremental_sync.py tests/test_situations_audit.py -q`
- **Committed in:** `f36696a`

**3. [Rule 1 - Bug] Denied direct reads of nested evidence removed by scope projection**
- **Found during:** Task 3 authorization verification
- **Issue:** The provider filtered nested evidence for situation detail but the direct evidence endpoint returned a hidden row after only checking the parent.
- **Fix:** Required the evidence ID to remain in the filtered visible evidence collection before returning it.
- **Files modified:** `src/situations/store.py`
- **Verification:** `uv run pytest tests/test_situations_authorization.py tests/test_situations_api.py -q`
- **Committed in:** `3e1f6af`

---

**Total deviations:** 3 auto-fixed (Rule 1: 3).
**Impact on plan:** All fixes closed correctness or authorization defects directly exposed by the planned verification; no later-phase product behavior was added.

## Issues Encountered

- The repository contained extensive unrelated dirty worktree changes. Owned files with overlapping edits were selectively staged; unrelated changes remain in the working tree untouched.
- Next.js build passes but continues to print pre-existing `@azure/msal-browser` `window is not defined` messages during static generation.
- The required nine-step human walkthrough was not run in this execution environment; it remains the only verification blocker.

## User Setup Required

None - no external service configuration was added.

## Next Phase Readiness

The Phase 1 durable foundation is ready for Phase 2 investigation/recommendation planning: six-family evidence, qualified links, scoped reads, and service audit history are available as stable contracts. Before claiming full Phase 1 UAT completion, run the nine-step local API/web walkthrough from `01-02-PLAN.md`, including responsive and keyboard checks.

## Self-Check: PASSED

- `01-02-SUMMARY.md` exists.
- Commits `a67f0ab`, `f36696a`, `3e1f6af`, and `cf6a059` exist in git history.
- Full backend suite, phase lint, frontend suite, frontend build, and MVP goal validator passed.

---
*Phase: 01-evidence-and-situation-foundation*
*Completed: 2026-08-25*
