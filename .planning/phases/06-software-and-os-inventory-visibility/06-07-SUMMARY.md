---
phase: 06-software-and-os-inventory-visibility
plan: 07
subsystem: inventory
tags: [python, fastapi, nextjs, software-normalization, rbac, audit]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: canonical software inventory projection and server-owned lifecycle review patterns
provides:
  - server-owned versioned software mapping repository with local/OneLake persistence
  - scoped approval and rejection routes with optimistic concurrency and immutable audit provenance
  - mapping-aware software aggregation and browser review controls
affects: [inventory, software-review, authorization, audit, OneLake]

# Actuals (#2632)
actuals:
  tokens: 24792
  tasks: 2
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Software mappings are advisory until an authenticated operator approves them."
    - "Mapping decisions use per-record revisions plus atomic server-owned persistence."
    - "Scope predicates are checked before mapping serialization, mutation, and aggregation."

key-files:
  created:
    - src/intelligence/inventory/mapping_repository.py
    - src/intelligence/inventory/software_normalization.py
    - tests/test_inventory_mapping.py
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
  - "Only approved mappings can change grouped software counts; suggested and rejected identities remain review state."
  - "Mapping decisions require an effective operate scope and expected per-mapping revision."
  - "External web/LLM search remains unavailable unless an explicitly approved provider configuration exists."

patterns-established:
  - "Raw name, version, publisher, canonical identity, method, confidence, source timestamp, and provenance are retained together."
  - "Audit events record actor, action, revision, scope snapshot, before/after provenance, and mapping provenance."

requirements-completed: [INV-02, INV-05]

coverage:
  - id: D1
    description: "Deterministic normalization preserves raw software identity while approved mappings canonicalize aggregate grouping."
    requirement: INV-02
    verification:
      - kind: unit
        ref: "tests/test_inventory_mapping.py::test_suggestions_are_server_owned_and_approved_mapping_changes_grouping"
        status: pass
    human_judgment: false
  - id: D2
    description: "Authenticated, scoped mapping list, approval, and rejection routes enforce optimistic revisions and audit provenance."
    requirement: INV-05
    verification:
      - kind: integration
        ref: "tests/test_api_inventory_router.py::test_mapping_list_decision_is_scoped_audited_and_revision_checked"
        status: pass
    human_judgment: false
  - id: D3
    description: "Malformed model output remains a non-authoritative, provenance-bearing suggestion."
    requirement: INV-02
    verification:
      - kind: unit
        ref: "tests/test_inventory_mapping.py::test_malformed_model_output_is_visible_but_non_authoritative"
        status: pass
    human_judgment: false
  - id: D4
    description: "The Software Inventory page exposes server-owned mapping review actions and sends the current revision."
    requirement: INV-05
    verification:
      - kind: automated_ui
        ref: "web/src/app/software-inventory/page.test.tsx::renders server-owned mapping review controls and sends its revision"
        status: pass
    human_judgment: true
    rationale: "Automated rendering verifies the action contract; an operator should still visually review the approval/rejection workflow."

duration: 9min
completed: 2026-08-26
status: complete
---

# Phase 06 Plan 07: Software normalization mapping review summary

**Server-owned software normalization review now preserves raw identities, isolates unapproved counts, and records scoped optimistic approval/rejection decisions with audit provenance.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-08-25T16:26:28Z
- **Completed:** 2026-08-25T16:35:02Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- Added a revisioned mapping repository with idempotent AI suggestions, publisher-aware raw identity keys, local/OneLake persistence, and immutable decision audit events.
- Integrated mapping state into software projections so suggested/rejected records cannot affect aggregates, while approved mappings canonicalize groups and preserve raw/detail provenance.
- Added authenticated read, approve, and reject routes with effective scope enforcement, conflict handling, path aliases, typed DTOs, and Software Inventory page controls.
- Kept external web/LLM lookup disabled unless the approved provider endpoint and credential contract from D-14 are configured.

## Task Commits

Each implementation task was committed atomically:

1. **Task 1: Trace one ambiguous software suggestion through scoped review and approval** - `29d07bb` (feat)
2. **Task 2: Harden mapping rejection, optimistic concurrency, scope, and count isolation** - `3a66215` (fix)

**Plan follow-up fix:** `bcac81c` (fix: require server mapping review data)

All commits include the Copilot co-author trailer.

## Files Created/Modified

- `src/intelligence/inventory/mapping_repository.py` - server-owned mapping records, revision checks, persistence, and audit trail.
- `src/intelligence/inventory/software_normalization.py` - deterministic identity handling, validated AI suggestions, and approved mapping projection.
- `src/intelligence/inventory/service.py` - mapping suggestion ingestion, scope filtering, count isolation, and mapping collection/detail projections.
- `src/api/routers/inventory.py` - scoped mapping list/detail and approve/reject endpoints.
- `src/api/runtime.py` - runtime composition using the server-owned mapping document.
- `web/src/app/software-inventory/page.tsx` - normalization review display and approval/rejection actions.
- `tests/test_inventory_mapping.py` - approval, rejection, revision, provenance, malformed output, and count coverage.
- `tests/test_api_inventory_router.py` - authenticated route, scope, audit, and conflict coverage.
- `web/src/app/software-inventory/page.test.tsx` - mapping review UI action coverage.

## Decisions Made

- Mapping repository state is authoritative for review decisions; browser state is never treated as audit history.
- Publisher remains part of the exact raw identity key, so conflicting publishers do not collapse without explicit approval.
- Scope is applied before mapping records are serialized or allowed to influence group counts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved provider-rebuilt mapping state across requests in API tests**
- **Found during:** Task 2 (mapping route hardening)
- **Issue:** The test context rebuilt `InventoryService` for each request with a fresh in-memory repository, making an approval appear not to persist.
- **Fix:** Wired a durable temporary mapping repository into the test context, matching the production server-owned persistence contract.
- **Files modified:** `tests/test_api_inventory_router.py`
- **Verification:** Scoped approval and stale revision integration test passes.
- **Committed in:** `3a66215`

**2. [Rule 2 - Missing Critical] Removed the empty mapping-data UI fallback**
- **Found during:** final stub scan
- **Issue:** An empty fallback could make the review panel appear to have no records when the mapping API client was unavailable.
- **Fix:** Require the authenticated mapping API response as the page data source.
- **Files modified:** `web/src/app/software-inventory/page.tsx`
- **Verification:** Software Inventory UI test passes.
- **Committed in:** `bcac81c`

---

**Total deviations:** 2 auto-fixed (1 Rule 1, 1 Rule 2)
**Impact on plan:** Both fixes protect server-owned persistence and prevent misleading empty review state; no scope creep.

## Issues Encountered

- The targeted UI suite emits existing React `act(...)` warnings while still passing all tests; no tests were skipped.
- Unrelated pre-existing working-tree changes were preserved and excluded from all task commits.

## User Setup Required

None for mapping review. External web/LLM search remains intentionally unavailable until an administrator configures the approved provider endpoint and credential contract.

## Next Phase Readiness

- Software normalization review is ready for operator UAT against an ambiguous mapping, including approval, rejection, refresh persistence, scope isolation, and stale-revision feedback.
- The next plan can consume approved canonical mappings without adding another ingestion store.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-26*

## Self-Check: PASSED

- Summary file exists.
- Task commits `29d07bb`, `3a66215`, and follow-up fix `bcac81c` exist.
