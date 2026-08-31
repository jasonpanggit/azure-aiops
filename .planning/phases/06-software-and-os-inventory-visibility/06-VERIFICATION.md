---
phase: 06-software-and-os-inventory-visibility
verified: 2026-08-25T17:06:33Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 6/6
  gaps_closed:

    - "Phase 6 implementation passes the required backend lint gate."
  gaps_remaining: []
  regressions: []
human_verification:

  - test: "With approved Azure credentials, subscriptions, workspace mappings, and Entra Logs Query permission, open /software-inventory and inspect both tabs."
    expected: "Authorized OS and software rows show live freshness, evidence, exact joins, environment values, and visible partial/unavailable state during a provider outage."
    why_human: "Fixtures and automated tests cannot prove tenant permissions, real workspace configuration, live freshness, or browser presentation."

  - test: "Trigger an unmapped OS lifecycle review, inspect all candidates, explicitly select a candidate or enter a manual date, refresh, and attempt a stale-revision confirmation."
    expected: "Citations and retrieval metadata are appropriate, only the explicit choice persists, and stale revisions are rejected without overwriting newer catalog state."
    why_human: "The automated contract tests cover this behavior, but citation appropriateness and the authenticated operator workflow require human review."

  - test: "If external lifecycle search is required, configure an approved HTTPS endpoint and secret, then exercise the review."
    expected: "The configured provider is used with bounded cited results; without configuration, provider_not_configured remains visible and no unapproved call occurs."
    why_human: "Deployment configuration, secret wiring, and the external provider are unavailable in this repository-only verification."

  - test: "With approved Foundry configuration, exercise the narrative on the authenticated inventory page, then repeat with Foundry absent or failing."
    expected: "Model narration remains separate from authorized fact summaries and citations; failure visibly falls back to deterministic fact-only output."
    why_human: "External service integration and runtime degradation cannot be fully proven by local tests alone."

  - test: "Review /software-inventory at desktop, tablet, and mobile widths using keyboard navigation, drill-down, review controls, source warnings, and CSV download."
    expected: "The two tabs, controls, badges, tables, warnings, and exact-detail export remain usable, accessible, and visually legible."
    why_human: "Visual layout, focus behavior, contrast, and an actual browser download are not established by jsdom tests."
---

# Phase 6: Software and OS Inventory Visibility Verification Report

**Phase Goal:** Operators can inspect authorized, evidence-backed OS and installed-software inventory across Azure VMs and Arc-enabled servers, understand lifecycle risk, and export exact software/version matches for follow-up.

**Verified:** 2026-08-25T17:06:33Z  
**Verdict:** **AUTOMATED GATES PASS — the prior Phase 6 Ruff blocker is closed; overall status remains human-needed for the explicit residual walkthrough/configuration checks.**  
**Re-verification:** Yes — after closure of the prior lint gap in commit `12dd33e`.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Native Azure VM and Arc OS observations and Log Analytics ConfigurationData software observations are acquired, normalized, and published through the existing immutable generation. | VERIFIED | `QueryCatalog._inventory_specs()` defines separate versioned native/Arc ARG queries; `Normalizer._normalize_inventory()` creates source-specific observations/status; `IngestionService._run_locked()` calls the fixed Logs client and `DatasetStore.publish()` persists OS/software datasets. Focused backend suite passed. |
| 2 | OS and software identity is grouped canonically while raw values, exact resource joins, environment, source identity, timestamps, evidence, and pagination remain available. | VERIFIED | `inventory_normalize.py`, `MachineObservation`/`SoftwareObservation`, and `InventoryService` implement exact resource-ID joins, canonical current-state selection, tag precedence, raw identity retention, and scope-first grouping/detail. Tests cover case changes, version changes, hostname collisions, and unlinked rows. |
| 3 | Lifecycle risk uses the server-owned curated catalog, visibly flags misses, presents cited candidates, and persists only explicit revision-checked confirmation. | VERIFIED | `EOLCatalog.default()`, `LocalEOLCatalogRepository`, `EOLReviewService`, lifecycle routes, and page review controls are wired. Tests cover catalog hits/misses, candidate citations, manual dates, provenance, duplicate confirmation, and stale revisions. |
| 4 | Risk narration is grounded in authorized aggregate facts and falls back to deterministic cited facts when Foundry is absent, malformed, timed out, or ungrounded. | VERIFIED | `InventoryService.narrative_aggregates()` applies scope and bounds before `build_inventory_narrative()`; `narrative.py` excludes machine rows and unsupported citations and retains fact-only output on failure. API tests cover scope isolation, bounds, timeout, malformed output, and fallback. |
| 5 | Collection, detail, review, mapping, narrative, and export paths enforce effective scope and expose source/evidence/freshness/partial or unavailable state. | VERIFIED | `ReadScope` narrows requested scope before router calls; detail keys are server-validated; source status and warnings survive generation/runtime projection; mapping and lifecycle mutations require operate scope. API tests cover subscription isolation, forged machine-list input, source failure versus empty success, stale data, mapping scope, and revision conflicts. |
| 6 | A discoverable single Software Inventory page provides two tabs, dashboard summaries/charts, filters, lifecycle/source badges, drill-down, review controls, and safe exact-detail CSV export. | VERIFIED | `AppShell.tsx` has one `/software-inventory` entry; `page.tsx` has exactly two ARIA tabs, cards/charts, search/source/subscription/lifecycle filters, drill-down tables, EOL/mapping actions, and detail-only export through `csv.ts`. Focused UI/CSV tests passed (6 page tests, 3 CSV tests). |

**Score:** 6/6 contract truths verified. The prior lint gate is closed; the score does not waive the residual manual checks.

## Decision Coverage (D-01 through D-16)

| Decision | Status | Evidence |
|---|---|---|
| D-01 | VERIFIED | OS groups use server-owned `OS name|version` keys and exact detail lookup. |
| D-02 | VERIFIED | Native VM and Arc source types remain distinct in one grouped view and detail rows. |
| D-03 | VERIFIED | Software groups use canonical name/version with exact machine drill-down. |
| D-04 | VERIFIED | Routes and UI are general inventory lookup; no incident/casework semantics were introduced. |
| D-05 | VERIFIED | CSV exports the returned exact software/version detail rows only. |
| D-06 | VERIFIED | Packaged curated catalog is consulted at request time through the repository. |
| D-07 | VERIFIED* | endoflife.date, bounded official-vendor HTML extraction, and approved web/search adapters preserve candidates/failures independently; `*` the external provider is intentionally unavailable until configured. |
| D-08 | VERIFIED | Candidate/manual confirmation requires explicit selection, exact normalized key, operate scope, and expected catalog revision. |
| D-09 | VERIFIED | Unknown lifecycle groups render “EOL date needs review” and remain visible. |
| D-10 | VERIFIED | One route and one navigation entry contain exactly OS Inventory and Installed Software tabs. |
| D-11 | VERIFIED | Both tabs render metric cards and dashboard bar visualizations above tables. |
| D-12 | WARNING | Code maps expired/expiring/supported/unknown to critical/warning/success/unknown badge tones; actual color contrast and rendered appearance require browser review. |
| D-13 | VERIFIED | Search, source, subscription, and OS lifecycle filters are implemented; subscription narrowing is sent through API scope. |
| D-14 | VERIFIED | Unconfigured web/LLM resolution returns an explicit `provider_not_configured` failure and makes no unapproved call. |
| D-15 | VERIFIED | Narrative separates facts/model text/confidence/citations/status and keeps deterministic facts on model failure. |
| D-16 | VERIFIED | Server-owned versioned mapping repository, scoped approve/reject routes, optimistic revisions, audit provenance, and unapproved-count exclusion are implemented and tested. |

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/intelligence/inventory/models.py` | Immutable OS/software/evidence/source/lifecycle DTOs | VERIFIED | 467 lines; typed frozen contracts and API projections. |
| `src/intelligence/inventory/service.py` | Scope-first grouping/detail/narrative projection | VERIFIED | 807 lines; active-generation reads, exact detail, status/warning projection. |
| `src/api/routers/inventory.py` | Scoped collection/detail/review/mapping/narrative routes | VERIFIED | 400 lines; routes call `InventoryService` and enforce `ReadScope`/operate scope. |
| `src/hermes_arg_connector/queries.py` | Independent native VM and Arc ARG QuerySpecs | VERIFIED | Fixed, versioned, ordered queries at `_inventory_specs()`. |
| `src/hermes_arg_connector/inventory_normalize.py` | Canonical software normalization and exact joins | VERIFIED | Fixed ConfigurationData boundary and current-state guards. |
| `src/hermes_arg_connector/logs.py` | Bounded Azure Monitor Logs client/parser | VERIFIED | Fixed KQL, token scope, response/row/schema bounds. |
| `src/hermes_arg_connector/service.py` / `storage.py` | ARG + Logs ingestion into one immutable generation | VERIFIED | Software fetch/normalization and `inventory/*` dataset publication are wired. |
| `src/intelligence/inventory/eol_repository.py` / `eol_review.py` | Revisioned lifecycle review/persistence | VERIFIED | Atomic local/OneLake document path, candidate provenance, audit event. |
| `src/intelligence/inventory/mapping_repository.py` / `software_normalization.py` | Governed D-16 mapping state | VERIFIED | Substantive implementation and tests exist; the targeted Ruff check now passes after `12dd33e`. |
| `src/intelligence/inventory/narrative.py` | Aggregate-only narrative/fallback | VERIFIED | Bounded facts and visible fallback warning. |
| `web/src/app/software-inventory/page.tsx` | Two-tab inventory dashboard | VERIFIED | Real API-backed UI; prior Installed Software placeholder is gone. |
| `web/src/lib/csv.ts` | Safe CSV serializer/download | VERIFIED | RFC-4180 quoting and formula-leading value protection. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `queries.py` | `service.py` | QueryCatalog specs passed to existing source fetch | WIRED | `_run_locked()` builds specs and fetches by each spec name. |
| `normalize.py` | `models.py` | `MachineObservation.from_mapping()` | WIRED | Native/Arc normalized rows become immutable DTOs. |
| `service.py` | `storage.py` | `graph.inventory_*` then `DatasetStore.publish()` | WIRED | OS/software rows and source status are published in the active generation. |
| `logs.py` | `inventory_normalize.py` | fixed `tables/columns/rows` result to normalizer | WIRED | `_fetch_software_inventory()` supplies parsed rows to `normalize_configuration_data()`. |
| `api/routers/inventory.py` | `InventoryService` | scoped collection/detail/review calls | WIRED | All inventory routes resolve the service and pass effective scope. |
| `InventoryService` | `eol_review.py` / `mapping_repository.py` | review and approved mapping projection | WIRED | Classification, confirmation, suggestion persistence, and decision routes are connected. |
| `InventoryService` | `narrative.py` | scoped aggregate facts | WIRED | Narrative route invokes builder with service and scope; no independent retrieval path. |
| `page.tsx` | API clients / `csv.ts` | typed calls and exact detail serialization | WIRED | Page calls `inventoryApi` methods and exports only `softwareDetail` rows. |
| `AppShell.tsx` | `page.tsx` | `/software-inventory` navigation entry | WIRED | One discoverable Software Inventory link exists. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| OS dashboard | `InventorySnapshot.observations` | Native/Arc ARG rows → normalizer → `DatasetStore` active generation | Yes | FLOWING |
| Installed Software dashboard | `software_observations` | Azure Monitor Logs `ConfigurationData` → exact join/normalization → active generation | Yes | FLOWING |
| Lifecycle review | `EOLReviewResult` | Request-time curated catalog or independently resolved cited candidates | Yes | FLOWING |
| Mapping review | `SoftwareMappingRepository` | Server-persisted suggestions and operator decisions | Yes | FLOWING |
| Risk narrative | `narrative_aggregates` | Scope-filtered OS/software groups; optional Foundry only narrates supplied facts | Yes | FLOWING |
| CSV export | `softwareDetail` | Exact authorized detail response held in page state | Yes | FLOWING |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Phase 6 backend source, scope, EOL, mapping, narrative, runtime, and document behavior | `uv run pytest tests/test_inventory_provider.py tests/test_inventory_eol.py tests/test_inventory_mapping.py tests/test_logs_client.py tests/test_api_inventory_router.py tests/test_api_runtime.py tests/test_onelake_documents.py -q` | 100% passing; no failures | PASS |
| Full backend regression | `uv run pytest -q` | Exit 0; full suite passed | PASS |
| Two tabs, summaries, filters, review actions, drill-down, and export context | `cd web && npm run test -- src/app/software-inventory/page.test.tsx src/lib/csv.test.ts` | 2 files, 9 tests passed; existing React `act(...)` warnings only | PASS |
| Full frontend regression | `cd web && npm test` | 131 passed, 1 failed (132 total); failure is in unrelated `src/app/compliance/page.test.tsx` at line 120, expecting a missing firewall-bypass Copilot link | PARTIAL / unrelated failure |
| Frontend production readiness | `cd web && npm run lint && npm run build` | Lint passed; build passed; existing MSAL `window is not defined` generation logs only | PASS |
| Backend lint | `uv run ruff check src tests` | Exit 1; 11 findings remain in unrelated `multi_agent.py`, `twin.py`, `governance/finops.py`, `operational_twin.py`, and unrelated tests; no Phase 6 mapping findings | PARTIAL / unrelated findings |
| Targeted Phase 6 lint | `uv run ruff check` on all Phase 6-owned Python modules/tests | Exit 0, `All checks passed!`; prior I001/F401 mapping errors are gone | PASS |

## Probe Execution

| Probe | Command | Result | Status |
|---|---|---|---|
| Phase 6 probe scripts | No Phase 6 `probe-*.sh` is declared or present | Not applicable | SKIP |

## Requirements Coverage

| Requirement | Source Plan(s) | Status | Evidence |
|---|---|---|---|
| INV-01 | 06-01, 06-02, 06-03, 06-04 | SATISFIED in code/tests; live Azure walkthrough pending | ARG native/Arc and Logs ConfigurationData paths, generation publication, provenance/status tests. |
| INV-02 | 06-01, 06-02, 06-03, 06-04, 06-07 | SATISFIED in code/tests | Canonical identity, raw values, exact joins, current-state dedup, governed mapping tests. |
| INV-03 | 06-05, 06-06 | SATISFIED with configured-provider caveat | Curated catalog, all-source candidate boundary, bounded vendor adapter, persistence, explicit confirmation, and disabled-provider semantics are tested. |
| INV-04 | 06-08 | SATISFIED | Aggregate-only grounded narrative and deterministic fallback tests. |
| INV-05 | 06-01 through 06-09 | SATISFIED in code/tests; residual manual walkthrough remains | Scope, evidence, pagination, source lifecycle, stale/partial/unavailable states, audit, API/UI coverage, and passing targeted lint. |
| INV-06 | 06-01, 06-09 | SATISFIED in code/tests; visual walkthrough pending | Single two-tab page, cards/charts, filters, badges, drill-down, and safe CSV tests/build. |

No Phase 6 requirement IDs are orphaned in `REQUIREMENTS.md`; all INV-01 through INV-06 are claimed by plans and mapped to implementation evidence.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `src/intelligence/inventory/mapping_repository.py` | 10-19 | Prior import-order/unused-import findings inspected after `12dd33e` | INFO | Imports are now ordered and the unused `TYPE_CHECKING`/`Scope` import is removed; targeted Ruff passes. |
| `tests/test_inventory_mapping.py` | 3-9 | Prior import-order finding inspected after `12dd33e` | INFO | `software_normalization` follows the service import; targeted Ruff passes. |

No unreferenced `TBD`, `FIXME`, or `XXX` markers were found in the Phase 6 implementation/test files. Defensive `return {}`/`return []` paths are missing/corrupt-source handling, not rendered static-data stubs. The initial 06-01 Installed Software placeholder was replaced by the Logs-backed implementation.

## Residual Manual Walkthrough / Configuration Items

These remain explicit human checks; they are not automated Phase 6 blockers:

1. **Authenticated Azure walkthrough:** Configure approved connection subscriptions, ARG permissions, server-owned Log Analytics workspace mappings, and Entra Logs Query permission. Open both tabs and verify real source freshness, evidence, exact joins, environment values, and a provider outage/partial state.
2. **EOL citation review:** Trigger an unmapped OS, inspect every endoflife.date/official-vendor candidate and retrieval timestamp, confirm the intended official URL, select one or enter a manual date, refresh, and verify only the explicit choice persists. Test the stale-revision response.
3. **External-provider configuration:** If the third EOL source is required operationally, an administrator must configure an approved HTTPS endpoint and secret via `APPROVED_SEARCH_API_ENDPOINT` / `APPROVED_SEARCH_API_KEY`. Until then, `provider_not_configured` must remain visible and no unapproved call may occur. `FOUNDRY_PROJECT_ENDPOINT` alone is intentionally insufficient.
4. **Foundry narrative walkthrough:** With approved Foundry configuration, confirm model narration remains separate from facts and citations; with it absent or failing, confirm the fact-only warning.
5. **Browser UX/accessibility:** Review desktop/tablet/mobile layout, keyboard tab/drill-down/review flow, badge colors/contrast, source warnings, and actual CSV download.

## Gaps Summary

The Phase 6 product path is present, connected, data-flowing, and covered by focused tests. The requested targeted Phase 6 Ruff command now exits 0 after `12dd33e`; the full backend suite, focused backend suite, focused Software Inventory UI/CSV suite, frontend lint, and production build also pass. The full frontend suite remains `131 passed, 1 failed` because the unrelated `src/app/compliance/page.test.tsx` expects a firewall-bypass Copilot link that the current compliance page does not render; this failure is outside Phase 6 and is preserved explicitly. Repository-wide Ruff still reports 11 unrelated findings, with no Phase 6-owned findings.

No automated Phase 6 gap remains. Under the verification gate, the overall status is `human_needed` rather than `passed` because the authenticated Azure/provider, citation, Foundry, and browser walkthrough/configuration checks remain open.

---

_Verified: 2026-08-25T17:06:33Z_  
_Verifier: the agent (gsd-verifier)_
