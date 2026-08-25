---
phase: 06-software-and-os-inventory-visibility
plan: 05
subsystem: inventory
tags: [python, fastapi, pytest, nextjs, vitest, eol, lifecycle, provenance]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: scope-aware immutable OS inventory provider and Software Inventory page
provides:
  - request-time curated EOL catalog lookup with versioned atomic local persistence
  - multi-source lifecycle candidates with bounded HTTPS vendor citations
  - scoped operator confirmation, review provenance, and optimistic revision protection
affects: [06-06, 06-07, 06-08, 06-09, inventory, software-inventory]

# Actuals (#2632)
actuals:
  tokens: 18564
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - server-owned lifecycle review DTOs retain candidate claims, citations, retrieval timestamps, confidence, and support channel
    - catalog overrides, pending candidates, and review provenance are persisted as separate state sections with atomic replace
    - candidate confirmation compares the current catalog revision before validating and writing the selected date

key-files:
  created:
    - src/intelligence/inventory/eol_repository.py
    - src/intelligence/inventory/eol_review.py
    - tests/test_inventory_eol.py
  modified:
    - src/intelligence/inventory/models.py
    - src/intelligence/inventory/service.py
    - src/api/models.py
    - src/api/routers/inventory.py
    - src/api/runtime.py
    - tests/test_api_inventory_router.py
    - web/src/app/software-inventory/page.tsx
    - web/src/app/software-inventory/page.test.tsx
    - web/src/lib/services.ts
    - web/src/lib/types.ts

key-decisions:
  - "Curated packaged catalog data is consulted first on every lifecycle read; unresolved keys remain review_required and never receive an automatic winner."
  - "Known-product catalog rows retain authoritative vendor citations even when an operator selects an endoflife.date or web-search candidate; the selected source citation remains in review provenance."
  - "Lifecycle mutations use the existing operate permission, effective scope, exact normalized OS key, and an atomic expected revision check."

patterns-established:
  - "CandidateResolver runs endoflife.date, bounded allowlisted official-vendor scraping, and an injectable web/search source independently, preserving every valid candidate."
  - "LifecycleClassification support channel and evidence are projected into OS machine/group DTOs instead of being discarded at the API boundary."

requirements-completed: [INV-03]

coverage:
  - id: D1
    description: "A catalog miss returns all valid multi-source EOL candidates with bounded citation and extraction provenance."
    requirement: INV-03
    verification:
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_catalog_miss_returns_all_sources_and_confirmation_persists_provenance"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_candidate_citations_are_https_and_bounded_to_approved_sources"
        status: pass
    human_judgment: false
  - id: D2
    description: "Only an authenticated, operated, scoped, exact-key, revision-checked candidate/manual confirmation persists lifecycle data."
    requirement: INV-03
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_lifecycle_route_returns_cited_candidates_and_confirms_explicitly"
        status: pass
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_lifecycle_reads_require_auth_and_mutations_require_operate_scope"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_confirmation_rejects_stale_revision_without_overwriting_newer_catalog"
        status: pass
    human_judgment: false
  - id: D3
    description: "The OS page exposes review-required state, every candidate field/citation, explicit candidate/manual confirmation, and refresh behavior."
    requirement: INV-03
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx"
        status: pass
    human_judgment: false
  - id: D4
    description: "Authenticated browser walkthrough confirms candidate inspection, persistence after refresh, and stale-revision feedback."
    requirement: INV-03
    verification: []
    human_judgment: true
    rationale: "This executor cannot perform the authenticated visual browser walkthrough; backend and jsdom tests cover the contract."

duration: 13min
completed: 2026-08-25
status: complete
---

# Phase 06 Plan 05: EOL Review and Confirmation Summary

**Curated request-time EOL lookup now resolves catalog misses into cited multi-source candidates and persists only explicitly scoped, revision-checked operator confirmations.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-25T16:01:54Z
- **Completed:** 2026-08-25T16:14:07Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- Added `LocalEOLCatalogRepository` with request-time packaged-catalog reads, atomic local replacement, candidate caching, separate review provenance, and optimistic revision conflicts.
- Added `CandidateResolver` for endoflife.date, bounded HTTPS official-vendor extraction, and injectable web/search candidates; all valid candidates remain available without automatic selection.
- Added lifecycle review and confirmation routes with effective scope, operate authorization, exact normalized keys, strict DTOs, candidate/manual-date validation, durable reviewer/source evidence, and conflict-safe writes.
- Wired support channel and lifecycle evidence through OS inventory DTOs, and added a page action that displays candidate date, source, citation, retrieval time, claim, and confidence before explicit confirmation.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace one catalog miss through candidate review and persisted confirmation** - `56f1845` (feat)
2. **Task 2: Harden lifecycle DTOs, authorization, and review provenance** - `0e80486` (fix)

## Files Created/Modified

- `src/intelligence/inventory/eol_repository.py` - Versioned catalog repository and atomic local state persistence.
- `src/intelligence/inventory/eol_review.py` - Candidate sources, HTTPS/citation validation, classification, and confirmation workflow.
- `src/intelligence/inventory/models.py`, `src/intelligence/inventory/service.py` - Lifecycle support channel/evidence projection and scoped review lookup.
- `src/api/models.py`, `src/api/routers/inventory.py`, `src/api/runtime.py` - Typed confirmation DTO, protected lifecycle routes, and runtime repository wiring.
- `tests/test_inventory_eol.py`, `tests/test_api_inventory_router.py` - Candidate, provenance, authorization, duplicate, malformed-input, and stale-revision coverage.
- `web/src/app/software-inventory/page.tsx`, `web/src/app/software-inventory/page.test.tsx`, `web/src/lib/services.ts`, `web/src/lib/types.ts` - Review action, candidate evidence presentation, confirmation refresh, and typed client contracts.

## Decisions Made

- Kept the packaged `EOLCatalog` as the authoritative first lookup and extended it with review state rather than creating parallel lifecycle semantics.
- Kept advisory source citations in provenance while ensuring known-product lifecycle catalog entries satisfy the existing authoritative vendor-domain validation.
- Used server-side candidate identity and re-resolution rather than trusting browser-submitted dates or citations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking import] Corrected the protocol import for Python 3.11.**
- **Found during:** Task 1 verification
- **Issue:** `Protocol` is provided by `typing`, not `collections.abc`, preventing inventory test collection.
- **Fix:** Moved the import to `typing`.
- **Files modified:** `src/intelligence/inventory/eol_repository.py`
- **Verification:** Focused pytest and Ruff checks passed.
- **Committed in:** `56f1845`

**2. [Rule 1 - Catalog validation bug] Preserved authoritative vendor URLs for non-vendor candidate selections.**
- **Found during:** Task 1 verification
- **Issue:** Existing lifecycle validation correctly rejects endoflife.date as a catalog citation for known products, so selecting that valid candidate initially could not persist.
- **Fix:** Persist the approved vendor URL in the catalog row while retaining the selected endoflife.date/search citation and claim in review provenance.
- **Files modified:** `src/intelligence/inventory/eol_review.py`
- **Verification:** Candidate confirmation and stale-revision tests passed.
- **Committed in:** `56f1845`

**3. [Rule 1 - UI/type wiring] Fixed a nested review handler and aligned API validation expectations.**
- **Found during:** Task 1 verification
- **Issue:** The first page edit nested review handlers inside the software-detail handler, and the existing API translates Pydantic request errors to HTTP 400 rather than 422.
- **Fix:** Restored top-level handlers, corrected the UI test, and asserted the repository's stable 400 validation contract.
- **Files modified:** `web/src/app/software-inventory/page.tsx`, `web/src/app/software-inventory/page.test.tsx`, `tests/test_api_inventory_router.py`
- **Verification:** TypeScript, Vitest, focused pytest, and Ruff checks passed.
- **Committed in:** `56f1845`

---

**Total deviations:** 3 auto-fixed (1 Rule 3, 2 Rule 1)
**Impact on plan:** All fixes were directly required for importability, lifecycle correctness, and the existing API/UI contracts; no parallel inventory store or auth architecture was introduced.

## Issues Encountered

- The repository contained extensive unrelated staged/unstaged working-tree changes before execution. Only the 13 plan-owned files were committed; unrelated edits remain preserved.
- The existing FastAPI/Starlette HTTPX deprecation warning remains outside this plan's scope.

## Auth Gates

None.

## Known Stubs

None in files created or modified by this plan.

The required authenticated browser walkthrough was not run in this non-interactive execution and was recorded in `.planning/WINDOWS.md` as an open `unrun-verify` entry.

## Verification

- `uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py -q` - passed (12 tests).
- `cd web && npm run test -- src/app/software-inventory/page.test.tsx` - passed (3 tests; Vitest emitted existing React act warnings).
- `cd web && npx tsc --noEmit` - passed.
- Targeted Ruff checks for all plan-owned Python files - passed.
- `uv run pytest -q` - passed (all backend tests).
- Tracer feedback gate rerun before Task 2 - passed (focused backend and UI commands).
- Human browser walkthrough - not run; tracked in `.planning/WINDOWS.md`.

## Next Phase Readiness

- 06-06 can add or refine source adapters without changing the candidate/review API boundary.
- Future plans can supply a real web/LLM search callback through `CandidateResolver` while retaining the same bounded candidate DTO and operator confirmation guard.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-25*

## Self-Check: PASSED

- Summary exists on disk.
- Task commits `56f1845` and `0e80486` exist in git history.
- No task commit deleted tracked files.
- Unrelated working-tree changes remain preserved.
