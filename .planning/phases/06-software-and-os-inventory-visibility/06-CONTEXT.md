# Phase 6: Software and OS Inventory Visibility - Context

**Gathered:** 2026-08-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a "Software Inventory" UI page with two tabbed views:

1. **OS Inventory** — extracted from Azure Resource Graph, covering both native Azure VMs and Arc-enabled servers, grouped by OS name/version, with EOL date and EOL risk status per OS.
2. **Installed Software Inventory** — extracted from ARG data collected by Arc Change Tracking & Inventory (guest configuration / software inventory extension), grouped by software name + version, letting an operator quickly find how many/which servers have a specific software+version installed.

Both views include dashboard-style summary cards/charts above their tables (EOL risk distribution, top OS versions, top software by install count), plus search/filter and drill-down to the affected machine list. OS EOL dates are resolved via a curated static table with AI-assisted candidate resolution (multi-source lookup + citations) for operator confirmation when unmapped.

</domain>

<decisions>
## Implementation Decisions

### Data Scope & Grouping
- **D-01:** OS Inventory groups machines by OS name/version first (e.g., "Windows Server 2019 — 42 machines"), with drill-down to the underlying machine list. Not a flat one-row-per-machine table.
- **D-02:** OS Inventory covers both native Azure VMs and Arc-enabled servers in one grouped view, each row/machine clearly labeled by source type (Azure VM vs Arc).
- **D-03:** Installed Software Inventory groups by software name + version first, with drill-down to the affected machine list — consistent grouping pattern with OS Inventory.
- **D-04:** Software+version lookup is a general-purpose capability (answers "how many/which servers have X version Y installed"), not a dedicated incident-response feature. It is useful for incident response (e.g., a SolarWinds-style supply-chain event) but should not be built or labeled as an incident workflow — no incident ticketing/casework in this phase.
- **D-05:** Software lookup results (drill-down machine list) are exportable as CSV.

### OS EOL Data Source & Matching
- **D-06:** EOL dates are resolved via a **curated static table** (OS name/version → EOL date) that is the primary source of truth read at request time. — **Reversibility:** costly — later migrating storage of this table (e.g., from static file/table to a different schema) means re-pointing all EOL lookups and any UI review-queue state keyed on it.
- **D-07:** When an OS version has no entry in the static table, the platform runs a **multi-source resolution** (endoflife.date API, official vendor website scraping, and web/LLM search) and presents **all candidate answers with their source/citation** to the operator for review — it does not auto-pick a single answer.
- **D-08:** The operator selects the correct EOL date from the presented candidates (or enters one manually); that selection is written back into the static table so future lookups for that OS version resolve immediately without re-running resolution.
- **D-09:** Until an OS version's EOL date is confirmed, the UI must not silently omit or blank the field — it must visibly flag the row (e.g., "EOL date needs review") so the operator can trigger/confirm resolution from the UI.

### UI Layout & Views
- **D-10:** Single "Software Inventory" page with two tabs: **OS Inventory** and **Installed Software**. Not two separate top-level nav pages, not stacked sections.
- **D-11:** Each tab shows dashboard-style summary cards + charts above its table (e.g., EOL risk distribution donut/bar, top OS versions, top software by install count) — this is not a table-only page.
- **D-12:** EOL risk is shown as a **color-coded badge**: red = expired, yellow = expiring within 90 days, green = supported/OK, gray = unknown/needs review.
- **D-13:** Minimum filtering: search + filter by OS/software name, source type (Azure VM vs Arc), subscription, and EOL status.

### AI-Assisted Features (in scope for this phase)
- **D-14:** AI-assisted EOL resolution — LLM/web-search-backed candidate lookup with citations, feeding the operator review queue described in D-07/D-08.
- **D-15:** AI-generated risk narrative — a short summary highlighting notable risk concentrations (e.g., "12 servers running EOL Windows Server 2012 in prod — prioritize X") surfaced alongside the dashboard summary.
- **D-16:** AI-assisted software normalization — dedupe/canonicalize messy software name/version strings from raw inventory data (e.g., "7-Zip 19.00" vs "7-Zip v19.00") before grouping, so the grouped view doesn't fragment identical software into near-duplicate rows.

### the agent's Discretion
- Exact API/backend endpoint shapes, ARG query design for OS/software extraction, caching/refresh cadence, and the concrete mechanism for triggering AI-assisted EOL resolution (on-demand vs background job) are left to research/planning.
- Exact chart types and dashboard card set beyond the three named (EOL risk distribution, top OS versions, top software by install count) are left to planning/design discretion.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Requirements
- `.planning/ROADMAP.md` — Phase 6 entry (Software and OS Inventory Visibility)
- `.planning/REQUIREMENTS.md` — v1 requirement set; this phase is additive to the existing roadmap (no existing REQ IDs map directly — confirm during planning whether new REQ IDs should be added)

### Existing ARG/Ingestion Patterns
- `src/hermes_arg_connector/queries.py` — `QueryCatalog` defines existing ARG KQL query specs (resources, resource_containers, resource_changes, patch_assessments, patch_assessment_details, patch_installations). New OS/software inventory queries should follow this pattern.
- `src/hermes_arg_connector/service.py` — `IngestionService` orchestrates query execution, normalization, and dataset storage; shows how a new inventory dataset would be wired into the ingestion run.
- `src/hermes_arg_connector/source.py`, `azure.py` — ARG/MCP client abstractions used by the ingestion service.

### Existing API/Router Patterns
- `src/api/routers/patching.py` — closest existing analog: exposes a provider-resolved inventory (`/api/v1/patching/targets`) with scope-aware envelope, evidence, and pagination. New OS/software inventory endpoints should follow this router shape (scope, evidence, envelope, pagination).
- `src/api/evidence.py`, `src/api/scope.py`, `src/api/dependencies.py` — shared evidence/scope/pagination primitives used across routers.

### Existing UI Page Patterns
- `web/src/app/vulnerabilities/page.tsx` — existing single-page inventory-style view with tables; useful layout reference.
- `web/src/app/compliance/page.tsx` and `page.test.tsx` — existing page + test pairing convention.

No external specs beyond the above — requirements fully captured in decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `IngestionService` / `QueryCatalog` in `src/hermes_arg_connector/` — extend with new `QuerySpec` entries for OS inventory (VM/Arc machine OS properties) and installed software (Change Tracking & Inventory / guest configuration data) rather than building a parallel ingestion path.
- Patching router's scope/evidence/envelope/pagination pattern in `src/api/routers/patching.py` is the closest precedent for the new inventory endpoints.

### Established Patterns
- ARG queries are versioned `QuerySpec` objects with `name`, `table`, `query` (KQL), `incremental`, and `scope`; normalization happens centrally in `IngestionService._run_locked`.
- API routers resolve a provider service via `context.resolve_provider(...)` or a hybrid live provider keyed by scope's subscription IDs, then wrap results in `envelope(...)` with `Evidence` and `Page`.
- Web app pages live under `web/src/app/<feature>/page.tsx` with a co-located `page.test.tsx`.

### Integration Points
- No existing "software inventory" or "OS inventory" concept exists in the codebase today (confirmed via search — only `patch_assessments`/`patch_installations` queries touch software-adjacent data). This phase introduces new ARG queries, a new provider/service, new router endpoints, and a new web page — it does not extend an existing inventory feature.
- Arc Change Tracking & Inventory data in ARG is exposed via `configurationdata` / guest configuration resource types (specific ARG table/schema to be confirmed by research — not yet present in `queries.py`).

</code_context>

<specifics>
## Specific Ideas

- Motivating use case explicitly named by the user: quickly answer "how many servers have software X version Y installed" — framed by the user as general inventory capability that happens to be valuable during a supply-chain-style incident (the user referenced the SolarWinds incident as the kind of scenario this should make easier to handle), not as a dedicated incident-response feature.
- EOL resolution workflow: when static table lacks a version, resolve via multiple sources in parallel (endoflife.date API, official vendor site scraping, web/LLM search), show all candidates with citations, let the operator pick/confirm, then persist the choice back to the static table so it's a one-time resolution per OS version.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. AI-assisted EOL resolution, AI risk narrative, AI software normalization, and dashboard visualizations were explicitly pulled into this phase's decisions (D-14/D-15/D-16, D-11) rather than deferred.

</deferred>

---

*Phase: 6-software-and-os-inventory-visibility*
*Context gathered: 2026-08-25*
