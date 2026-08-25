# Phase 6: Software and OS Inventory Visibility - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-25
**Phase:** 6-software-and-os-inventory-visibility
**Areas discussed:** Data scope & grouping, OS EOL data source & matching, UI layout & views

---

## Data Scope & Grouping

| Option | Description | Selected |
|--------|-------------|----------|
| Grouped by OS first, drill down to machine list | Matches EOL-risk view | ✓ |
| Flat list, one row per machine | OS as a column | |
| Both: summary/grouped view + separate detailed machine list | | |

**User's choice:** Grouped by OS first, drill down to machine list.

| Option | Description | Selected |
|--------|-------------|----------|
| Both Azure VMs and Arc-enabled servers, clearly labeled by source type | | ✓ |
| Only Azure VMs | | |
| Only Arc-enabled servers | | |

**User's choice:** Both, clearly labeled by source type.

| Option | Description | Selected |
|--------|-------------|----------|
| Grouped by software name+version, drill down to machine list | Consistent with OS view | ✓ |
| Flat list, one row per (machine, software) pair | | |
| Grouped by machine first, expand to see installed software list | | |

**User's choice:** Grouped by software name+version, drill down to machine list.

**Notes:** User later clarified the software lookup use case is NOT an incident-response feature — it's a general capability to quickly determine how many/which servers have a specific software+version installed, which happens to help during incidents like SolarWinds but shouldn't be scoped/labeled as incident response.

---

## OS EOL Data Source & Matching

| Option | Description | Selected |
|--------|-------------|----------|
| Maintained static mapping table, periodically updated | Simple, no runtime dependency | |
| Live lookup via endoflife.date API at request/ingest time | | |
| Hybrid: static table with fallback to endoflife.date API | | |

**User's choice (free text):** Hybrid, but besides endoflife.date API, also consider official websites containing EOL dates via web scraping, or Bing search / LLM search.

| Option | Description | Selected |
|--------|-------------|----------|
| Static table → endoflife.date API → vendor scrape → web/LLM search (ordered fallback) | | |
| endoflife.date API first, static table as offline fallback | | |
| Always try official vendor site first | | |

**User's choice (free text):** Static table (curated) first; then use all three ways (API, scrape, LLM/web search) in parallel and present results with references/citations for the user to validate and select — the selected answer then goes into the static table.

| Option | Description | Selected |
|--------|-------------|----------|
| Flag "EOL date needs review" in UI, operator can trigger/confirm resolution | | ✓ |
| Auto-pick majority answer silently | | |
| Block/blank the EOL column until resolved | | |

**User's choice:** Flag it in the UI so operator can trigger/confirm resolution.

---

## UI Layout & Views

| Option | Description | Selected |
|--------|-------------|----------|
| Two tabs within one 'Software Inventory' page: OS Inventory \| Installed Software | | ✓ |
| Two separate top-level nav pages | | |
| Single page, both sections stacked vertically | | |

**User's choice:** Two tabs within one page.

| Option | Description | Selected |
|--------|-------------|----------|
| Color-coded badge: red=expired, yellow=<90 days, green=OK, gray=unknown | | ✓ |
| Simple days-remaining number only | | |
| Text label only | | |

**User's choice:** Color-coded badge.

| Option | Description | Selected |
|--------|-------------|----------|
| Search + filter by OS/software name, source type, subscription, EOL status | | ✓ |
| Just a search box | | |
| Full filter panel including resource group, region, tags | | |

**User's choice:** Search + filter by OS/software name, source type, subscription, EOL status.

**Notes:** User raised the software-lookup-for-incident-response use case here (SolarWinds-style scenario), which was refined into a general capability (see notes above) rather than a dedicated feature.

| Option | Description | Selected |
|--------|-------------|----------|
| Exact name+version search returning full affected machine list w/ subscription/RG/environment | | ✓ |
| Name-only search | | |
| Fuzzy/partial name search only | | |

**User's choice:** Exact name+version search with full context.

| Option | Description | Selected |
|--------|-------------|----------|
| Export CSV of matched machines | | ✓ |
| No export needed for v1 | | |

**User's choice:** Yes, CSV export.

**Additional discussion — AI features:**

User was asked which AI touchpoints to include:

| Option | Description | Selected |
|--------|-------------|----------|
| AI-assisted EOL resolution only | Already scoped via multi-source lookup | |
| Also AI-generated risk narrative | e.g. "12 servers running EOL Windows Server 2012 in prod — prioritize X" | |
| Also AI-assisted software normalization | Dedupe messy version strings | |
| All three | | ✓ |

**User's choice:** All three, and also include dashboards rather than just tables.

| Option | Description | Selected |
|--------|-------------|----------|
| Summary cards + charts above the tables | EOL risk distribution, top OS versions, top software by install count | ✓ |
| Separate dedicated dashboard tab | | |
| Minimal KPI cards only, no charts | | |

**User's choice:** Summary cards + charts above the tables (per tab).

---

## the agent's Discretion

- Exact ARG query/KQL design for OS and software inventory extraction.
- Exact backend endpoint shapes, caching/refresh cadence.
- Mechanism for triggering AI-assisted EOL resolution (on-demand vs background job).
- Exact chart types and any additional dashboard cards beyond the three named.

## Deferred Ideas

None — all raised ideas (AI risk narrative, AI normalization, dashboards) were pulled into phase scope rather than deferred.
