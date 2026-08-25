---
phase: 01-evidence-and-situation-foundation
plan: 03
subsystem: api-and-ui
tags: [fastapi, freshness, authorization, audit, nextjs, vitest, responsive]

requires:
  - phase: 01-evidence-and-situation-foundation
    provides: Durable source-status, evidence, audit, scope, and situation queue contracts from plan 01-02.
provides:
  - Nested audit scope-snapshot authorization with no metadata leakage.
  - UTC timestamp-derived evidence freshness and boundary regression coverage.
  - Durable source-status/evidence trust rendering and distinct audit failure state.
  - Complete durable queue regression coverage for filters, pagination, scope reload, errors, and keyboard row actions.
affects: [phase-2-investigation-and-approval, phase-4-domain-coverage]

actuals:
  tokens: 5705
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - Enforce each nested audit event scope_snapshot before reference filtering or serialization.
    - Derive freshness from timezone-aware persisted timestamps while preserving explicit provider bands.
    - Keep service audit failure distinct from successful empty history in the read-only workbench.

key-files:
  created: []
  modified:
    - src/situations/store.py
    - src/situations/materializer.py
    - tests/test_situations_authorization.py
    - tests/test_situations_ingestion.py
    - web/src/components/ui/EvidenceBar.tsx
    - web/src/app/situations/[id]/page.tsx
    - web/src/app/situations/[id]/page.test.tsx
    - web/src/app/situations/page.tsx
    - web/src/app/situations/page.test.tsx

key-decisions:
  - "Treat an audit event scope_snapshot as an independent authorization predicate; an out-of-scope event is removed in full."
  - "Use UTC age bands of one hour and twenty-four hours for fallback freshness, with future observations treated as fresh."
  - "Keep local Save view locally state separate from service-recorded audit history and expose rejected audit reads as unavailable."

patterns-established:
  - "Nested authorization occurs before copying audit fields or filtering references."
  - "Every durable trust row renders provider status, availability, quality, freshness, timestamps, watermark, query version, requested scope, and provider error where present."

requirements-completed: [FOUND-03, FOUND-04, FOUND-05, DETECT-02]

coverage:
  - id: D1
    description: "Scoped audit reads omit out-of-scope scope snapshots and metadata, while persisted evidence freshness derives deterministic age bands."
    requirement: FOUND-05
    verification:
      - kind: integration
        ref: "uv run pytest tests/test_situations_authorization.py tests/test_situations_ingestion.py tests/test_situations_api.py -q"
        status: pass
      - kind: other
        ref: "uv run ruff check src/situations/store.py src/hermes_arg_connector/normalize.py tests/test_situations_authorization.py tests/test_situations_ingestion.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "Durable detail renders source-status trust facts and distinguishes rejected audit service reads from successful empty audit history."
    requirement: FOUND-03
    verification:
      - kind: automated_ui
        ref: "cd web && npm test -- --run 'src/app/situations/[id]/page.test.tsx'"
        status: pass
      - kind: other
        ref: "cd web && npm run build"
        status: pass
    human_judgment: false
  - id: D3
    description: "The durable situation queue has regression coverage for loading, rows, search, P1/P2/P3 filters, pagination, both empty states, provider errors, scope reload, and keyboard row actions."
    requirement: DETECT-02
    verification:
      - kind: automated_ui
        ref: "cd web && npm test -- --run src/app/situations/page.test.tsx"
        status: pass
      - kind: other
        ref: "cd web && npm run lint"
        status: pass
    human_judgment: false
  - id: D4
    description: "The local API and responsive/keyboard operator walkthrough evidence is recorded where the environment permits."
    verification:
      - kind: other
        ref: "curl -fsS -H 'Authorization: Bearer <configured local token>' http://127.0.0.1:8080/api/v1/situations"
        status: pass
      - kind: manual_procedural
        ref: "Local API detail/audit and desktop/tablet/mobile visual walkthrough"
        status: unknown
    human_judgment: true
    rationale: "The authenticated collection returned a successful empty envelope, so no durable detail ID was available; this runtime also lacks an interactive browser for visual viewport and focus-return inspection."

duration: 16 min
completed: 2026-08-25
status: complete
---

# Phase 1 Plan 3: Evidence and Situation Foundation Summary

**Nested audit scope enforcement, timestamp-derived freshness, durable source trust, explicit audit failure states, and the complete situation queue regression matrix are now implemented.**

## Performance

- **Duration:** 16 min
- **Started:** 2026-08-25T14:20:40Z
- **Completed:** 2026-08-25T14:35:47Z
- **Tasks:** 3
- **Files modified:** 9 owned files

## Accomplishments

- Enforced each audit row’s own `scope_snapshot` before serialization, removing the complete event when it falls outside the caller’s effective scope while preserving unrestricted reads and authorized reference filtering.
- Replaced lexical timestamp comparison with timezone-aware UTC parsing and named one-hour/twenty-four-hour freshness thresholds; valid provider bands remain authoritative and invalid/missing timestamps remain `unknown`.
- Added durable source-status rows to the EvidenceBar, included evidence confidence, and separated service audit failure from successful empty audit history.
- Expanded queue tests to cover loading, durable rows, search, each priority, pagination navigation and offsets, active-scope empty, filtered empty, provider errors, scope reload, and keyboard-reachable row activation.

## Task Commits

Each task was committed atomically:

1. **Task 1: Tracer — enforce nested audit scope and derive durable evidence freshness** — `42fc877` (fix)
2. **Task 2: Render persisted source trust and separate audit service failure from empty history** — `6f2098d` (feat)
3. **Task 3: Complete queue regression matrix and capture local walkthrough evidence** — `265ae7c` (test)

**Plan metadata:** final docs commit recorded in git history.

## Files Created/Modified

- `src/situations/store.py` — checks nested audit scope snapshots before exposing events.
- `src/situations/materializer.py` — derives fallback freshness from persisted UTC timestamps.
- `tests/test_situations_authorization.py` and `tests/test_situations_ingestion.py` — cover audit metadata absence and freshness boundaries.
- `web/src/components/ui/EvidenceBar.tsx` — renders durable source-status and evidence confidence facts.
- `web/src/app/situations/[id]/page.tsx` and its test — renders durable trust and explicit audit-unavailable state.
- `web/src/app/situations/page.tsx` and its test — distinguishes empty queue states and covers the durable queue matrix.

## Decisions Made

- Audit event snapshots are authorization predicates, not display-only metadata.
- Freshness fallback uses deterministic UTC age bands and never overrides an explicit valid provider band.
- Local collaboration remains local storage and is not represented as immutable service audit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Applied freshness repair at the actual implementation boundary**
- **Found during:** Task 1
- **Issue:** The plan identified `_freshness` under `src/hermes_arg_connector/normalize.py`, but the current implementation defines and calls it in `src/situations/materializer.py`.
- **Fix:** Updated the actual helper used by `normalize_signal_families` and covered it through the public normalization boundary without changing the normalized storage contract.
- **Files modified:** `src/situations/materializer.py`, `tests/test_situations_ingestion.py`
- **Verification:** Targeted backend tests and Ruff pass.
- **Committed in:** `42fc877`

**2. [Rule 1 - Bug] Removed jsdom navigation noise from keyboard activation regression**
- **Found during:** Task 3
- **Issue:** Simulated anchor activation caused jsdom’s expected “navigation not implemented” diagnostic even though the test passed.
- **Fix:** Prevented the test-only default navigation after proving focus and activation, while retaining the accessible link href assertion.
- **Files modified:** `web/src/app/situations/page.test.tsx`
- **Verification:** Queue test passes without navigation diagnostics.
- **Committed in:** `265ae7c`

---

**Total deviations:** 2 auto-fixed (Rule 1: 1, Rule 3: 1). **Impact:** Both changes were directly required to verify the planned backend and queue behavior; no product scope expansion or new dependency was introduced.

## Issues Encountered

- `uv sync --extra test` removed the already-locked API extra from the local virtual environment, so the documented `start:api` command initially could not find `.venv/bin/uvicorn`. Running `uv sync --extra api --extra test` restored the existing locked runtime package without changing project dependencies.
- The first API startup attempted an Azure-backed local SPN sync and logged a pre-existing Cost Management 429 before the process failed on the missing API extra. A retry then found port 8080 already occupied by an existing local uvicorn process.
- The authenticated collection smoke call to `http://127.0.0.1:8080/api/v1/situations` returned HTTP 200 with a valid envelope, zero rows, pagination `{offset: 0, limit: 100, total: 0, next_offset: null}`, and selected scope `{}`. Therefore no encoded durable detail or audit endpoint call could be made.
- The local Next.js app responded with HTTP 200 at `/situations`. Automated tests proved state transitions, keyboard focus, Escape drawer behavior, and read-only labels; interactive desktop/tablet/mobile visual inspection was unavailable.
- The production build passed with the pre-existing `@azure/msal-browser` `window is not defined` static-generation diagnostics.

## Authentication Gates

None. The configured local token was used without exposing its value.

## Known Stubs

None. Empty, unavailable, degraded, contradictory, incomplete, and unknown values are explicit trust states rather than placeholder data.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The durable Phase 1 backend and UI contracts are ready for Phase 2 investigation and recommendation work: nested audit metadata is scope-safe, persisted trust is visible, and queue/detail failure states are explicit. Before milestone shipping, rerun the local API against a fixture-backed data set with a non-empty durable situation, call its detail and audit endpoints, and perform the responsive/keyboard visual walkthrough; open items are recorded in `.planning/WINDOWS.md`.

## Self-Check: PASSED

- `01-03-SUMMARY.md` exists after this write.
- Task commits `42fc877`, `6f2098d`, and `265ae7c` exist in git history.
- Targeted backend tests, backend lint, frontend queue/detail tests, frontend lint, and production build passed.
- Local API collection and web smoke responses were captured; unavailable detail/audit and visual walkthrough steps are explicitly recorded as open broken windows rather than claimed as complete.

---
*Phase: 01-evidence-and-situation-foundation*
*Completed: 2026-08-25*
