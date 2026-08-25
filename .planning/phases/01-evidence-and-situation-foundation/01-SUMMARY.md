---
phase: 01-evidence-and-situation-foundation
plan: 01
subsystem: situations
tags: [fastapi, pydantic, delta, provenance, rbac, nextjs, fluent-ui]
requires:
  - phase: existing-foundations
    provides: FastAPI, immutable DatasetStore, Delta sync, RBAC scope, and Next.js workbench
provides:
  - validated durable situation, evidence, link, source-status, and audit contracts
  - immutable-generation publication and scope-aware situation read provider
  - normalized multi-source evidence envelopes with failure, watermark, dedupe, and contradiction states
  - scoped situation, evidence, and append-only audit API routes plus durable UI adapter
affects: [investigation, recommendation, approval, remediation, pilot-readiness]
actuals:
  tokens: 17000
  tasks: 3
  commits: 8
tech-stack:
  added: []
  patterns:
    - "Pydantic immutable records with deterministic content-addressed IDs"
    - "ReadScope filtering before serialization and indistinguishable not-found responses"
    - "Existing immutable generation and Delta schema path remains the persistence boundary"
key-files:
  created:
    - src/situations/models.py
    - src/situations/materializer.py
    - src/situations/store.py
    - src/api/routers/situations.py
    - tests/test_situations_tracer.py
  modified:
    - src/hermes_arg_connector/normalize.py
    - src/hermes_arg_connector/storage.py
    - src/fabric/schema_registry.py
    - src/fabric/dataset_mapper.py
    - src/fabric/sync_service.py
    - src/api/dependencies.py
    - src/api/runtime.py
    - src/api/app.py
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/lib/situations.ts
    - web/src/app/situations/page.tsx
key-decisions:
  - "Use compact Pydantic situation/evidence records and keep raw provider payloads outside API responses."
  - "Use path-safe encoded IDs at the API boundary while retaining deterministic situation:// and evidence:// identities."
  - "Preserve pre-existing user edits in overlapping files; task commits contain only newly owned files."
patterns-established:
  - "Every source observation carries source identity, timestamps, watermark, provenance, quality, availability, and confidence."
  - "Audit event mutation is rejected by stable event ID before append-only persistence."
requirements-completed: [FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, DETECT-01, DETECT-02]
coverage:
  - id: D1
    description: "Durable situations are materialized from normalized resource changes and published through the immutable generation path."
    requirement: FOUND-01
    verification:
      - kind: integration
        ref: "tests/test_situations_tracer.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Representative source families share a provenance-bearing evidence envelope with dedupe, failure, watermark, and contradiction semantics."
    requirement: DETECT-01
    verification:
      - kind: unit
        ref: "tests/test_situations_ingestion.py"
        status: pass
      - kind: unit
        ref: "tests/test_situations_audit.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "Situation, evidence, and audit reads enforce effective scope and return the standard envelope without existence leakage."
    requirement: FOUND-05
    verification:
      - kind: integration
        ref: "tests/test_situations_api.py"
        status: pass
      - kind: integration
        ref: "tests/test_situations_authorization.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "The durable situation queue consumes typed durable records and qualifies contradictory trust state."
    verification:
      - kind: automated_ui
        ref: "web/src/lib/durable-situations.test.ts"
        status: pass
      - kind: other
        ref: "cd web && npm run build"
        status: pass
    human_judgment: true
    rationale: "Visual hierarchy, keyboard interaction, mobile scope visibility, and source-trust presentation require the planned human UI walkthrough."
duration: 14 min
completed: 2026-08-25
status: complete
---

# Phase 1 Plan 01: Evidence and Situation Foundation Summary

**Deterministic, provenance-bearing situations now flow from normalized observations through immutable publication into scope-authorized API and workbench contracts.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-08-25T21:17:05+08:00
- **Completed:** 2026-08-25T21:31:00+08:00
- **Tasks:** 3
- **Files modified:** 26 owned/overlapping files (including 12 files with preserved pre-existing edits)

## Accomplishments

- Added validated situation, evidence, links, source-status, and immutable audit models with deterministic IDs.
- Extended the existing normalized graph, immutable generation, schema registry, mapper, and Delta sync path with situation projections and audit append semantics.
- Added multi-source normalization for representative families, explicit failed/unavailable status, watermark preservation, deduplication, contradiction signaling, and ontology Situation links.
- Added scope-aware situation/evidence/audit endpoints and typed frontend service/queue adapters without adding an authentication mode or executable action.

## Task Commits

1. **Task 1: Tracer — persist and open one authorized situation end to end** — `0ed80fd`
2. **Task 2: Expand representative evidence, deduplication, trust states, audit, and ontology links** — `1d31e57`
3. **Task 3: Complete scoped read APIs and the approved operator-trust workbench surfaces** — `0f7653e`, `dccfecb`

Task 3 uses two commits because its API authorization tests and UI contract test were kept as separate owned file sets.

## Verification

- `uv run pytest tests/test_situations_model.py tests/test_situations_tracer.py tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_api.py tests/test_situations_authorization.py tests/test_situations_audit.py -q` — PASS (8 tests).
- `uv run pytest tests/test_situations_ingestion.py tests/test_situations_ontology.py tests/test_situations_audit.py tests/test_normalize.py tests/test_service.py tests/test_incremental_sync.py -q` — PASS (33 tests).
- `uv run pytest tests/test_situations_api.py tests/test_situations_authorization.py tests/test_api_primitives.py -q` — PASS (44 tests).
- Planned frontend Vitest command — PASS (6 tests).
- `cd web && npm run build` — PASS.
- New situation implementation/test lint — PASS.
- Plan-wide ruff command — BLOCKED only by pre-existing warnings in `src/api/routers/multi_agent.py`, `src/api/routers/twin.py`, and `src/hermes_arg_connector/service.py`; these were not modified for this plan and were recorded in `.planning/WINDOWS.md`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Made encoded durable IDs routable**
- **Found during:** Task 1
- **Issue:** Content-addressed `://` IDs contain slashes and initially returned Starlette 404 responses.
- **Fix:** Added path converters and ordered audit routes before detail routes; clients continue to URL-encode IDs.
- **Files modified:** `src/api/routers/situations.py`, `tests/test_situations_tracer.py`
- **Verification:** Tracer and API tests pass.
- **Committed in:** `0ed80fd`

**2. [Rule 1 - Bug] Stabilized repeated-ingestion generation hashes**
- **Found during:** Task 2
- **Issue:** Ingestion-time fields and volatile change timestamps caused duplicate observations to appear as changed datasets on repeat runs.
- **Fix:** Excluded ingestion volatility from semantic generation hashes and canonicalized observation fingerprints.
- **Files modified:** `src/hermes_arg_connector/storage.py`, `src/situations/materializer.py`
- **Verification:** Existing service and incremental-sync suites pass.
- **Committed in:** `1d31e57` (implementation remains in the overlapping worktree change set).

---

**Total deviations:** 2 auto-fixed (Rule 1: 2). **Impact:** Required for correct routing and idempotent ingestion; no new architecture or dependency was introduced.

## Issues Encountered

- The repository contained extensive pre-existing uncommitted edits, including several files named by this plan. Those edits were preserved and not staged or committed as unrelated work. The owned new files were committed atomically; overlapping implementation edits remain in the working tree for the owner to review/commit with their existing changes.
- The plan-wide ruff command still reports three pre-existing warnings. They are explicitly tracked in `WINDOWS.md` rather than fixed outside the phase scope.
- The required manual UI walkthrough with a running fixture-backed API/web server was not run in this non-interactive execution.

## Known Stubs

None. “Cause not yet determined” is an intentional qualified unknown state, not placeholder data.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The next phase can consume durable situation IDs, normalized evidence envelopes, scoped reads, trust states, and append-only audit records. Review the open broken-windows entries and perform the manual UI walkthrough before shipping the milestone.

## Self-Check: PASSED

- Summary file exists.
- Task commits `0ed80fd`, `1d31e57`, and `0f7653e` exist.
- All owned Python and frontend automated verification commands pass.
- Open out-of-scope lint/manual-verification entries are recorded in `.planning/WINDOWS.md`.

---
*Phase: 01-evidence-and-situation-foundation*
*Completed: 2026-08-25*
