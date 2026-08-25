---
phase: 06-software-and-os-inventory-visibility
plan: 06
subsystem: inventory
tags: [python, fastapi, lifecycle, provenance, onelake, httpx]

# Dependency graph
requires:
  - phase: 06-software-and-os-inventory-visibility
    provides: request-time lifecycle review route and curated catalog contract
provides:
  - bounded endoflife.date and official-vendor lifecycle candidate adapters
  - explicit unavailable fallback for unconfigured external web/LLM resolution
  - concurrent citation-bearing source resolution with typed failures
  - revisioned local/OneLake catalog persistence with provenance and audit events
affects: [inventory, lifecycle-review, operator-confirmation, OneLake]

# Actuals (#2632)
actuals:
  tokens: 9841
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Candidate sources execute behind an adapter boundary and never auto-select a winner."
    - "Small catalog control-plane documents use revision-checked atomic local or OneLake persistence."
    - "External provider requests contain only normalized OS identity and a fixed lifecycle operation."

key-files:
  created:
    - src/storage/onelake_documents.py
    - tests/test_onelake_documents.py
  modified:
    - src/intelligence/inventory/eol_review.py
    - src/intelligence/inventory/eol_repository.py
    - src/api/runtime.py
    - tests/test_inventory_eol.py
    - tests/test_api_inventory_router.py

key-decisions:
  - "D-06: Keep the curated lifecycle catalog server-owned, revisioned, and authoritative at request time."
  - "D-07: Preserve endoflife.date, official-vendor, and web/LLM candidates independently with citations and source failures."
  - "D-08: Require explicit operator confirmation with an expected catalog revision; never auto-select a candidate."
  - "D-14: Keep external web/LLM resolution disabled until an approved provider endpoint and credential contract is configured."

patterns-established:
  - "UnconfiguredLifecycleSearchProvider reports provider_not_configured as an unavailable source failure instead of attempting an unapproved call."
  - "Catalog confirmation records reviewer, selected source claim, citation, revision, and an immutable lifecycle.confirmed audit event."

requirements-completed: [INV-03]

coverage:
  - id: D1
    description: "Bounded official-vendor retrieval extracts date claims with HTTPS allowlisting, citations, and typed failures."
    requirement: INV-03
    verification:
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_official_vendor_adapter_extracts_bounded_citation"
        status: pass
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_bounded_official_vendor_failures_are_typed"
        status: pass
    human_judgment: false
  - id: D2
    description: "All configured source candidates are returned concurrently without an automatic winner, with explicit unavailable external-provider state."
    requirement: INV-03
    verification:
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_unconfigured_external_search_is_explicitly_unavailable"
        status: pass
      - kind: integration
        ref: "uv run pytest tests/test_inventory_eol.py tests/test_api_inventory_router.py -q"
        status: pass
    human_judgment: false
  - id: D3
    description: "Operator confirmation persists the seeded catalog, provenance, audit event, and revision-safe selection across restart."
    requirement: INV-03
    verification:
      - kind: unit
        ref: "tests/test_inventory_eol.py::test_document_backed_catalog_persists_seed_provenance_and_audit"
        status: pass
      - kind: unit
        ref: "tests/test_onelake_documents.py"
        status: pass
    human_judgment: true
    rationale: "The final operator review of candidate citations and rejection behavior is a human workflow check."

duration: 8min
completed: 2026-08-26
status: complete
---

# Phase 06 Plan 06: Lifecycle provider and catalog persistence summary

**Bounded lifecycle candidates now retain source citations and failures, while operator-confirmed EOL data persists atomically with revision and audit provenance.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-08-25T16:18:24Z
- **Completed:** 2026-08-25T16:26:45Z
- **Tasks:** 3
- **Files modified:** 8 including this summary

## Accomplishments

- Added bounded endoflife.date and official-vendor retrieval with HTTPS origin controls, redirect limits, timeouts, response-size limits, bounded claim extraction, citations, and typed per-source failures.
- Added a server-side lifecycle provider interface and approved HTTPS adapter; absent `APPROVED_SEARCH_API_ENDPOINT`, the provider explicitly reports external web/LLM resolution unavailable and does not call Foundry or an unapproved service.
- Resolved source families concurrently and preserved every valid candidate, including duplicate dates and disagreements, without selecting a winner.
- Added revisioned local/OneLake JSON document persistence, packaged catalog seeding, confirmation provenance, immutable lifecycle audit events, and restart-safe catalog overrides.

## Task Commits

Each implementation task was committed atomically:

1. **Task 1: Trace bounded endoflife and official-vendor retrieval into the review route** - `3cc215d` (`feat`)
2. **Task 2: Select the approved web/LLM provider** - blocking checkpoint resolved by retaining external search disabled until configuration; no source commit
3. **Task 3: Add the selected web/LLM adapter and durable catalog document persistence** - `8c787ea` (`feat`)

## Files Created/Modified

- `src/intelligence/inventory/eol_review.py` - source adapter protocol, unavailable fallback, approved search adapter, concurrent resolution, and bounded vendor handling.
- `src/intelligence/inventory/eol_repository.py` - document-backed catalog state, seed metadata, revisions, provenance, and audit events.
- `src/api/runtime.py` - server-owned catalog/provider composition and safe provider configuration boundary.
- `src/storage/onelake_documents.py` - atomic revisioned local/OneLake document store.
- `tests/test_inventory_eol.py` - source failure, provider boundary, citation, concurrency-compatible, restart, and audit coverage.
- `tests/test_api_inventory_router.py` - operator-visible unavailable provider warning coverage.
- `tests/test_onelake_documents.py` - local round-trip, conflict, corruption, path safety, and DFS upload coverage.
- `.planning/phases/06-software-and-os-inventory-visibility/06-06-SUMMARY.md` - execution record.

## Decisions Made

- The checkpoint decision is preserved: external web/LLM search stays disabled until an approved provider endpoint and credential contract are supplied. `FOUNDRY_PROJECT_ENDPOINT` alone is not interpreted as a search implementation.
- The catalog remains authoritative only after explicit operator confirmation; candidates and source failures are review state, not catalog truth.
- Local development and OneLake use the same revisioned document contract, with no inventory rows sent to the external provider.

## Deviations from Plan

### Checkpoint resolution

**1. Provider configuration unavailable - retained safe fallback**
- **Found during:** Task 2 blocking provider decision
- **Issue:** No `FOUNDRY_PROJECT_ENDPOINT` or `APPROVED_SEARCH_API_ENDPOINT` was available, so selecting and calling an external web/LLM provider would require fabricated credentials or an unapproved service.
- **Fix:** Implemented the provider interface, approved HTTPS adapter, and `UnavailableLifecycleSearchProvider`; runtime composition reports `provider_not_configured` and keeps external search disabled.
- **Files modified:** `src/intelligence/inventory/eol_review.py`, `src/api/runtime.py`, `tests/test_inventory_eol.py`
- **Verification:** Provider boundary and API source-warning tests pass; no external provider call is made when unconfigured.
- **Committed in:** `8c787ea`

**Total deviations:** 1 checkpoint resolution
**Impact on plan:** D-07 remains complete as an explicit source contract and review state; only the unconfigured third source remains unavailable until approved administration supplies configuration.

## Issues Encountered

- The working tree contained unrelated pre-existing changes, including a runtime file with partial work. Runtime lifecycle changes were staged from a clean HEAD baseline so those changes remain uncommitted and preserved.
- `git diff --check` reports a pre-existing blank line at EOF in `infra/terraform/variables.tf`; it is outside this plan and was not changed.

## User Setup Required

External web/LLM lifecycle resolution remains intentionally disabled. To enable it, an administrator must provide an approved HTTPS search endpoint through `APPROVED_SEARCH_API_ENDPOINT` and its credential through the deployment secret mechanism as `APPROVED_SEARCH_API_KEY`. No credentials were fabricated or committed. `FOUNDRY_PROJECT_ENDPOINT` is not sufficient without an explicitly approved web-search tool and citation contract.

## Next Phase Readiness

- The lifecycle review API is ready to show endoflife.date, official-vendor, and explicit web/LLM-unavailable source state.
- The durable catalog survives process restart and rejects stale confirmation revisions.
- Final human verification should review an unmapped OS, candidate citations, and vendor redirect/oversize rejection before shipping.

---
*Phase: 06-software-and-os-inventory-visibility*
*Completed: 2026-08-26*

## Self-Check: PASSED

- Summary file exists.
- Task commits `3cc215d` and `8c787ea` exist.
