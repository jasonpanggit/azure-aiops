# Phase 6: Software and OS Inventory Visibility - Research

**Researched:** 2026-08-25
**Domain:** Azure Resource Graph, Azure Monitor Logs ConfigurationData, FastAPI provider projections, and Next.js inventory UI
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. AI-assisted EOL resolution, AI risk narrative, AI software normalization, and dashboard visualizations were explicitly pulled into this phase's decisions (D-14/D-15/D-16, D-11) rather than deferred.
</user_constraints>

## Summary

The phase can reuse the existing ARG ingestion and API safety patterns for native VM and Arc OS inventory, but installed software has an important source-boundary correction. Microsoft documents Arc Change Tracking and Inventory software records in the Azure Monitor Logs `ConfigurationData` table in a connected Log Analytics workspace, not as an Azure Resource Graph table. The plan should add a separate, optional Log Analytics query source and keep the existing `AzureResourceGraphSource` for OS queries. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-change-tracking-inventory/overview-monitoring-agent] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources]

Native VM ARG data provides a trustworthy OS type (`properties.storageProfile.osDisk.osType`) and image metadata, but the official ARG discovery example does not establish an installed OS release version. Arc machine ARG data explicitly exposes `properties.osName`, `properties.osVersion`, and `properties.osSku`. The normalized provider must therefore distinguish native image metadata from Arc-reported guest OS data and mark native OS version/EOL matching as unknown or review-required unless the tenant's observed payload supplies a defensible version. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/virtual-machines/resource-graph-samples] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/explore-resources] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-arc/servers/resource-graph-samples]

The recommended implementation is a read-only `InventoryService` projection over normalized OS and software observations. It should apply the effective `ReadScope` before grouping, preserve raw and canonical software identities, return a common evidence/scope/pagination envelope, and expose provider/source degradation rather than converting a failed source to an empty inventory. Reuse the existing `EOLCatalog` schema and lifecycle date validation, but add a governed persistence path for operator-confirmed catalog updates; the current catalog API is in-memory/read-oriented and does not itself persist a review selection. [VERIFIED: src/api/dependencies.py:205-218, quote: "`ReadScope = Annotated[Scope, Depends(read_scope)]`"] [VERIFIED: src/api/evidence.py:156-179, quote: "`def envelope(` ... `return Envelope(...).to_dict()`"] [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:116-196, quote: "`class EOLCatalog:` ... `def update(self, rows: list[dict[str, Any]]) -> EOLCatalog:`"]

**Primary recommendation:** Use two bounded data adapters—existing ARG for native/Arc OS and a new Log Analytics Logs Query API adapter for `ConfigurationData` software—then publish both through one scope-aware inventory provider and one two-tab UI page.

## Project Constraints (from copilot-instructions.md)

The repository has no root `copilot-instructions.md`; the configured project instruction file is `.github/copilot-instructions.md`. Its actionable directives are GSD workflow directives, not feature architecture constraints: use the GSD core skill for GSD commands, load the matching `.github/skills/gsd-*` file, prefer matching custom agents when a command asks for a subagent, do not apply GSD workflows unless explicitly requested, and offer the next step after a GSD deliverable. [VERIFIED: .github/copilot-instructions.md:4-8, quote: "`- Use the gsd-core skill when the user asks for GSD or uses a `gsd-*` command.`", "`- Treat `/gsd-...` or `gsd-...` as command invocations and load the matching file from `.github/skills/gsd-*`.`", "`- When a command says to spawn a subagent, prefer a matching custom agent from `.github/agents`.`", "`- Do not apply GSD workflows unless the user explicitly asks for them.`", "`- After completing any `gsd-*` command ... ALWAYS ... offer the user the next step`"]

The project skill `skills/operational-context-graph/SKILL.md` is read-only and requires graph-backed results, explicit scope, and no mutation from query tools. It is not the right mechanism for inventory extraction; Phase 6 should implement the inventory provider behind the same API scope/evidence boundary instead of adding inventory behavior to the operational-context skill. [VERIFIED: skills/operational-context-graph/SKILL.md:8-16, quote: "`Use the read-only `operations_analysis` tool`", "`Report only graph-backed results returned by the tool.`", "`For stale or missing context, recommend correcting Azure tags/source inventory ...`"]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Native Azure VM OS observation | API / Backend | Database / Storage | ARG query construction, normalization, and source failure handling belong in the connector/provider; the immutable dataset is the durable read source. [VERIFIED: src/hermes_arg_connector/service.py:70-99, quote: "`specs = QueryCatalog(...).build(...)` ... `self.store.publish(...)`"] |
| Arc-enabled server OS observation | API / Backend | Database / Storage | Arc rows use the same ARG `Resources` path but require a typed `ArcServer` normalization boundary. [VERIFIED: src/hermes_arg_connector/normalize.py:718-724, quote: "`if resource_type == \"microsoft.hybridcompute/machines\": return \"ArcServer\"`"] |
| Installed software observation | API / Backend | Database / Storage | `ConfigurationData` is workspace log data and needs a separate Logs Query API adapter before normalization and persistence. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview] |
| OS/software grouping and filtering | API / Backend | Browser / Client | The provider must aggregate only authorized rows; the browser owns presentation filters and drill-down state but must not be the authorization boundary. [VERIFIED: src/api/dependencies.py:210-218, quote: "`Returns the requested scope narrowed to what the principal may see`"] |
| EOL classification and review queue | API / Backend | Database / Storage | Static catalog lookup, candidate persistence, date classification, and auditability must be server-owned; the UI only submits a bounded confirmation. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:183-216, quote: "`def lookup(...)` ... `classify_product(...)` ... `LifecycleStatus.UNKNOWN`"] |
| AI EOL candidates and risk narrative | API / Backend | External AI/search boundary | Retrieval/candidate provenance must be assembled server-side; Foundry may narrate already retrieved facts but must not receive raw out-of-scope inventory. [VERIFIED: src/operations/foundry_agent.py:3-18, quote: "`Retrieval is done by the Semantic Knowledge Layer`", "`Narration is done by a Foundry prompt agent`", "`The model therefore never invents inventory.`"] |
| Tabs, charts, filters, drill-down, and CSV | Browser / Client | API / Backend | Existing pages are client components using `useApi`; the API remains the source of truth for scoped rows and evidence. [VERIFIED: web/src/app/exposure/page.tsx:1-26, quote: "`\"use client\";` ... `const { scope } = useScope();` ... `useApi(...)`"] |

## Standard Stack

### Core

| Library / component | Version | Purpose | Why Standard |
|---|---|---|---|
| Azure Resource Graph through existing `QuerySpec`/`QueryCatalog` | Internal `QuerySpec` fields are `name`, `table`, `query`, `incremental`, and `scope` | Native VM and Arc OS discovery | The repository already versions ARG queries as immutable specs and executes them through both Azure CLI and REST clients. [VERIFIED: src/hermes_arg_connector/queries.py:7-14, quote: "`class QuerySpec:` ... `name: str` ... `table: str` ... `query: str` ... `incremental: bool` ... `scope: str = \"subscriptions\"`"] [VERIFIED: src/hermes_arg_connector/azure.py:77-134, quote: "`class AzureCliArgClient:` ... `az graph query` ... `--skip-token`"] |
| Azure Monitor Logs Query API | API version `v1` in the official endpoint format | `ConfigurationData` software reads | Microsoft documents `POST https://api.loganalytics.azure.com/v1/workspaces/{workspaceId}/query` with a KQL body and Entra bearer token. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview] |
| Existing `httpx` transport | Repository constraint `httpx>=0.27,<1` | Logs API request transport and optional web-source adapters | It is already a project dependency and already underpins Azure REST clients; do not add a second HTTP package. [VERIFIED: pyproject.toml:6-18, quote: "`\"httpx>=0.27,<1\",`"] |
| Existing `EOLCatalog` / `LifecycleCatalogEntry` | Internal schema version `1.0.0` in the packaged catalog | Curated OS lifecycle lookup and date classification | It validates HTTPS source URLs, vendor domains, date ordering, supported/unknown statuses, and deterministic normalized product/version keys. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:23-34, 62-94, 139-169, quote: "`class LifecycleCatalogEntry:` ... `source_url: str` ... `class LifecycleStatus(StrEnum):` ... `SUPPORTED`, `APPROACHING_EOL`, `NEAR_EOL`, `CRITICAL`, `EOL`, `UNKNOWN` ... `EOLCatalog.default(...)`"] |
| FastAPI `ApiContext` + `ReadScope` + `Evidence` + `envelope` | Existing API contract | Inventory router and provider composition | All successful routes return `data`, `evidence`, `scope`, and optional pagination/warnings; `ReadScope` performs principal authentication and effective-scope narrowing. [VERIFIED: src/api/evidence.py:125-179, quote: "`Every API read is evaluated against a scope`" and `Envelope.to_dict` returns `data`, `evidence`, and `scope`] [VERIFIED: src/api/dependencies.py:151-218, quote: "`def read_scope(...)` ... `effective_scope(principal, \"read\", requested)`"] |
| Next.js App Router + React client component | `next` `14.2.35`; `react` `^18` | Single `/software-inventory` page with tab/filter state | These are the versions pinned in the repository; preserve them rather than upgrading the app during this phase. [VERIFIED: web/package.json:16-26, quote: "`\"next\": \"14.2.35\"`", "`\"react\": \"^18\"`"] [CITED: https://nextjs.org/docs/app/building-your-application/rendering/client-components] |

### Supporting

| Library / component | Version | Purpose | When to Use |
|---|---|---|---|
| `useApi` | Internal hook | Loading/error/cancellation state for each inventory envelope | Use for page-level OS/software calls; it explicitly distinguishes loading, API errors, and unavailable states. [VERIFIED: web/src/hooks/useApi.ts:12-46, quote: "`renders honest empty/unavailable states instead of blank UI`"] |
| `MetricCard`, `StatusBadge`, `EvidenceBar`, `StatePanel` | Internal UI components | Dashboard cards, EOL badges, evidence, loading/error/empty states | Reuse the existing visual language; `StatusBadge.statusTone` already maps `critical`, `warning`, `success`, and `unknown`. [VERIFIED: web/src/components/ui/StatusBadge.tsx:1-29, quote: "`StatusTone = \"critical\" | \"high\" | \"warning\" | \"success\" | \"neutral\" | \"info\" | \"unknown\"`"] [VERIFIED: web/src/components/ui/MetricCard.tsx:1-19, quote: "`Compact KPI card`"] |
| Vitest + Testing Library + jsdom | `vitest` `^2.1.9`, `@testing-library/react` `^16.3.2`, `jsdom` `^25.0.1` | Co-located page and service tests | The web test config already uses React, jsdom, the `@` alias, and shared setup. [VERIFIED: web/package.json:28-41, quote: "`\"@testing-library/react\": \"^16.3.2\"`", "`\"jsdom\": \"^25.0.1\"`", "`\"vitest\": \"^2.1.9\"`"] [VERIFIED: web/vitest.config.ts:5-22, quote: "`environment: \"jsdom\"`", "`setupFiles: [\"./src/test/setup.ts\"]`"] [CITED: https://vitest.dev/guide/] [CITED: https://testing-library.com/docs/react-testing-library/intro/] |
| Existing CSV generation in the browser | No new package | Export the already-rendered, authorized software drill-down | Use a small RFC-4180-compatible serializer with formula-prefix protection; do not add a CSV dependency for a bounded table export. [ASSUMED] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| Separate Logs Query API adapter for `ConfigurationData` | Treat `ConfigurationData` as an ARG `QuerySpec` | Do not use this alternative: Microsoft documents `ConfigurationData` as a Log Analytics workspace table, while the ARG table reference lists `GuestConfigurationResources` but not `ConfigurationData`. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources] |
| Existing immutable snapshot + provider projection | Browser-only direct Azure queries | Do not use this alternative: it would bypass the API's Entra/RBAC scope, evidence envelope, source status, and server-side pagination controls. [VERIFIED: docs/OPERATIONS_API.md:3-10, quote: "`The API owns no business logic` ... `No handler reads Fabric, ontology tables, or Azure Resource Graph directly.`"] |
| Existing `EOLCatalog` | A second Phase 6-only EOL schema | Do not create parallel lifecycle semantics; the current catalog already validates vendor domains and classifies `Unknown`. Extend persistence/review around it. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:76-94, 198-216, quote: "`Lifecycle catalog source_url must use HTTPS`" and "`No authoritative lifecycle entry matches`"] |
| Deterministic normalization plus AI suggestions | LLM-only canonicalization | Do not allow an opaque model to merge names/versions without retaining raw values and a reviewable mapping; this is a safety recommendation based on the phase's evidence requirements. [ASSUMED] |

**Installation:** No new external packages are recommended for Phase 6. Keep the existing Python/Node lockfiles and use the project commands already defined in the repository. [VERIFIED: pyproject.toml:6-22, quote: "`[project.optional-dependencies]` ... `api = [...]` ... `test = [...]`"] [VERIFIED: web/package.json:5-14, quote: "`\"test\": \"vitest run\"`"]

## Architecture Patterns

### System Architecture Diagram

```mermaid
flowchart LR
  Scope[Authenticated request + requested scope]
  ARG[Azure Resource Graph\nnative VM + Arc machine rows]
  Logs[Azure Monitor Logs Query API\nConfigurationData in workspace]
  Normalize[Inventory normalization\nsource type, identity, OS/software canonical fields]
  Snapshot[Immutable generation / optional normalized inventory dataset]
  Provider[Scope-aware InventoryService\naggregate, filter, paginate, evidence]
  Catalog[Curated EOL catalog\nread at request time]
  Resolve[Candidate resolution adapters\nendoflife.date + allowlisted vendor + optional web/LLM]
  Review[Operator review and governed catalog update]
  Narrative[Grounded risk narrative over aggregate facts]
  API[FastAPI inventory router\ncommon envelope]
  UI[Software Inventory page\nOS tab | Installed Software tab]
  Drill[Machine drill-down + CSV export]

  Scope --> API
  ARG --> Normalize
  Logs --> Normalize
  Normalize --> Snapshot
  Snapshot --> Provider
  Catalog --> Provider
  Provider --> API
  API --> UI
  UI --> Drill
  Provider --> Narrative
  Narrative --> UI
  Provider --> Resolve
  Resolve --> Review
  Review --> Catalog
```

The primary path is `ARG/Logs -> normalization -> immutable/current snapshot -> provider -> scoped envelope -> UI`; the browser must not call Azure directly. [VERIFIED: src/api/runtime.py:225-249, quote: "`InventoryDatasetMapper` already knows how to read that layout ... both `SemanticEngine.from_rows` and ... services require"] [VERIFIED: src/api/runtime.py:1215-1320, quote: "`ConnectionScopedLiveResourceProvider`" and "`return ApiContext(...)`"]

### Recommended Project Structure

```text
src/
├── hermes_arg_connector/
│   ├── queries.py                 # native VM and Arc OS QuerySpec entries
│   ├── source.py                  # existing ARG source; keep ARG paging here
│   ├── logs.py                    # new bounded Log Analytics query client/source
│   ├── inventory_normalize.py     # OS/software canonical rows and identity joins
│   └── service.py                 # orchestrate both source families in one run
├── intelligence/
│   └── inventory/                 # grouping, EOL review, normalization, narrative
├── api/
│   ├── routers/inventory.py       # scoped collection/detail/review routes
│   └── models.py                  # strict request/response DTOs as needed
└── tests/
web/src/
├── app/software-inventory/
│   ├── page.tsx
│   └── page.test.tsx
├── lib/services.ts                # typed inventoryApi methods
└── lib/types.ts                   # envelope payload types
```

The exact filenames are planning guidance, not existing paths. The existing mapper currently emits `silver_vm_inventory` and `silver_server_inventory`, while no software inventory dataset exists; the new implementation should add a named inventory projection without introducing a second publication mechanism. [VERIFIED: src/fabric/dataset_mapper.py:347-353, quote: "`\"silver_vm_inventory\"`" and "`\"silver_server_inventory\"`"] [VERIFIED: .planning/phases/06-software-and-os-inventory-visibility/06-CONTEXT.md:89-92, quote: "`No existing \"software inventory\" or \"OS inventory\" concept exists`"]

### Pattern 1: Split ARG queries by source family and preserve failure as data

**What:** Add independent `QuerySpec` entries for native VM OS and Arc server OS instead of one broad query. Run them through the existing parallel `AzureResourceGraphSource.fetch`; each result remains separately attributable when a query is throttled or unavailable. [VERIFIED: src/hermes_arg_connector/source.py:23-52, quote: "`with ThreadPoolExecutor(...)`" and "`results[name] = [{\"status\": \"failed\", ...}]`"]

**When to use:** Always for this phase's two ARG families. Independent queries avoid one schema or provider failure blanking both Azure VM and Arc views. [VERIFIED: src/hermes_arg_connector/queries.py:212-231, quote: "`Split by family rather than issued as a single broad query so that a failure or throttle on one resource type does not blank the entire topology`"]

**Recommended KQL skeletons:**

```kusto
Resources
| where type =~ 'Microsoft.Compute/virtualMachines'
| summarize count() by tostring(properties.storageProfile.osDisk.osType)
```

The query above is verbatim from Microsoft's native VM ARG sample and proves the native OS type path. For the implementation, replace the aggregate with a deterministic `project` containing `id`, `name`, `type`, `subscriptionId`, `resourceGroup`, `location`, `tags`, `properties.storageProfile.osDisk.osType`, and image-reference fields, then `order by id asc`. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/virtual-machines/resource-graph-samples, quote: "`Resources | where type =~ 'Microsoft.Compute/virtualMachines' | summarize count() by tostring(properties.storageProfile.osDisk.osType)`"] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/work-with-data, quote: "`When using first, it's recommended to order the results by at least one column ... Without sorting, the results returned are random and not repeatable.`"]

```kusto
Resources
| where type == 'microsoft.hybridcompute/machines'
| project id, JoinID = toupper(id), ComputerName = tostring(properties.osProfile.computerName), OSName = tostring(properties.osName)
```

The Arc sample above is verbatim for the machine identity and OS name. Microsoft's Arc examples also use the exact field expression `| extend osSku = properties.osSku, osName = properties.osName, osVersion = properties.osVersion`; project those fields directly and preserve `properties.status` and `properties.osProfile.computerName` for machine drill-down. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-arc/servers/resource-graph-samples, quote: "`Resources | where type == 'microsoft.hybridcompute/machines' | project id, JoinID = toupper(id), ComputerName = tostring(properties.osProfile.computerName), OSName = tostring(properties.osName)`", "`| extend osSku = properties.osSku, osName = properties.osName, osVersion = properties.osVersion`"]

### Pattern 2: Normalize OS observations without fabricating native versions

**What:** Emit one normalized machine row per exact ARM resource ID with `source_type` of `azure_vm` or `arc`, `os_name`, `os_version`, `os_type`, optional `image_offer/image_sku/image_version`, `subscription_id`, `resource_group`, `location`, tags, observation timestamp, and source evidence. For native VMs, use `os_type` and image metadata as separate fields; do not convert an image SKU or `"latest"` into a claimed installed OS version. For Arc, use `osSku` when present and `osName` otherwise, with `osVersion` as the version. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/explore-resources, quote: "`imageReference` ... `offer`, `publisher`, `sku`, `version`" and "`osDisk` ... `osType`"] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-arc/servers/resource-graph-samples, quote: "`osSku = properties.osSku` ... `osName = properties.osName` ... `osVersion = properties.osVersion`"]

**When to use:** Before EOL matching and before grouping. The grouping key must be a canonical `(os_name, os_version)` pair plus a visible `source_type` count, while the detail list retains the exact machine resource ID. Native rows with no trustworthy version should group under an explicit `Unknown version`/review state rather than silently disappear. [ASSUMED]

The current normalizer already demonstrates the asymmetry that the phase must preserve: native VM normalization reads only `osType`, while Arc normalization reads `osName` and `osVersion`. [VERIFIED: src/hermes_arg_connector/normalize.py:492-510, quote: "`if entity_type == \"VirtualMachine\":` ... `entity[\"osType\"] = ...` ... `elif entity_type == \"ArcServer\":` ... `entity[\"osName\"] = ...` ... `entity[\"osVersion\"] = ...`"]

### Pattern 3: Query `ConfigurationData` as latest software state per machine/software

**What:** Query the Log Analytics workspace, filter `ConfigDataType == "Software"`, and select the latest observation for each machine/software identity. Preserve `SoftwareName`, `CurrentVersion`, `Computer`, `SourceComputerId`, `_ResourceId`, `_SubscriptionId`, `Publisher`, `SoftwareType`, and `TimeGenerated` before canonicalization. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata, quote: "`ConfigDataType` ... `Files Software WindowsServices Registry Daemons`", "`CurrentVersion` ... `Current software version`", "`SoftwareName` ... `Name of the software`", "`TimeGenerated` ... `Date and time the record was created.`"]

**Recommended KQL shape:**

```kusto
ConfigurationData
| where ConfigDataType == "Software"
| summarize arg_max(TimeGenerated, *) by Computer, SourceComputerId, _ResourceId, SoftwareName
| project TimeGenerated, Computer, SourceComputerId, _ResourceId, _SubscriptionId,
          SoftwareName, CurrentVersion, Publisher, SoftwareType, SoftwareDescription
| order by _ResourceId asc, SoftwareName asc, CurrentVersion asc
```

The exact `ConfigDataType`, `SoftwareName`, and `CurrentVersion` values above are from the official table schema; the `arg_max` approach follows Microsoft's ConfigurationData query example, which groups by machine and software name rather than version so a later version observation replaces an older version for that machine. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/queries/configurationdata, quote: "`ConfigurationData | where ConfigDataType == \"WindowsServices\" ... | summarize arg_max(TimeGenerated, *) by SoftwareName, Computer`"] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata]

**Important source correction:** Microsoft describes CTI inventory as being stored in a connected Log Analytics workspace's `ConfigurationData` table, and the Logs Query API returns a `tables` array with `columns` and `rows`. It does not describe this table as an ARG table. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-change-tracking-inventory/overview-monitoring-agent, quote: "`Ingests inventory metadata into the ConfigurationData table in the connected Log Analytics workspace.`"] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview, quote: "`POST https://api.loganalytics.azure.com/v1/workspaces/{workspaceId}/query`" and "`The API returns a JSON response containing a tables array`"]

**When to use:** Use a separate `LogAnalyticsConfigurationDataSource` with explicit workspace IDs. The current connection model carries subscription/tenant/credential information but no workspace ID; planning must add a workspace-to-connection configuration mapping or a governed workspace registry. [VERIFIED: src/api/models.py:107-114, quote: "`ConnectionCreateRequest` ... `tenant_id`, `subscription_id`, `credential`, `metadata`"] [ASSUMED]

### Pattern 4: Join software to machines only by authoritative identity

**What:** Prefer exact case-insensitive `_ResourceId` to the normalized ARG machine resource ID. If `_ResourceId` is absent or does not match an Azure VM/Arc resource, retain the software row as `unlinked` with `Computer` and `SourceComputerId`; do not fuzzy-match hostnames across subscriptions. The ConfigurationData schema documents `_ResourceId` as the associated resource identifier and separately exposes `Computer` and `SourceComputerId`. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata, quote: "`_ResourceId` ... `A unique identifier for the resource that the record is associated with`", "`Computer`", "`SourceComputerId`"]

**When to use:** During normalization and again before machine drill-down. A joined row inherits source type only from the exact matched machine resource; `SourceSystem` values such as `Linux` or `Azure` are collection-agent values, not an authorization-safe substitute for Azure VM versus Arc classification. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata, quote: "`SourceSystem` ... `Linux` ... `Azure`"]

### Pattern 5: Server-side aggregation, client-side presentation filters

**What:** The provider accepts a validated query/filter DTO, narrows rows to the effective `Scope`, computes summary counts and grouped rows from only those rows, and paginates machine details. The UI may apply display search to already authorized data, but server endpoints must support exact software+version lookup and scoped drill-down. [VERIFIED: src/api/routers/patching.py:58-68, quote: "`rows = [target.to_dict() for target in service.targets(scope)]`" and "`pagination=page.to_dict(len(rows))`"] [VERIFIED: src/api/scope.py:94-130, quote: "`effective scope can never be broader than what the principal may see`"]

**When to use:** Always. For a grouped row, the detail endpoint must re-check the group key and scope rather than accepting a client-provided list of machine IDs. [ASSUMED]

### Pattern 6: Treat EOL resolution as candidate retrieval plus an explicit mutation

**What:** On a cache/catalog miss, run the three D-07 source families in parallel behind interfaces: endoflife.date, an allowlisted official vendor URL/domain, and an optional web/LLM search provider. Return every candidate with `candidate_id`, normalized OS identity, proposed date, source kind, URL/citation, retrieved timestamp, extraction text/claim, and confidence. Do not select a winner in the resolver. [ASSUMED]

The existing lifecycle catalog already requires HTTPS source URLs and restricts known product families to vendor domains such as `learn.microsoft.com`, `ubuntu.com`, `access.redhat.com`, `debian.org`, and `kubernetes.io`; reuse that validation boundary for scraped candidates. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:76-94, quote: "`parsed_url.scheme != \"https\"`" and "`allowed_domains = { ... }`"]

The operator confirmation route should accept only a candidate ID or a manually entered ISO date plus the exact normalized OS key, perform optimistic concurrency against the catalog revision, validate the resulting catalog entry, write atomically to the governed static store, and return the updated catalog evidence. The current `EOLCatalog.update` returns a new object but has no file/database write; this is a concrete planning task, not an assumption that D-08 already works. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:186-196, quote: "`def update(self, rows: list[dict[str, Any]]) -> EOLCatalog:`" and "`return EOLCatalog(...)`"]

### Pattern 7: Ground AI only on bounded facts and citations

**What:** Feed the risk narrative model the already scoped dashboard aggregates, notable groups, EOL classifications, and evidence references. Mark the response as narration, keep the underlying facts visible, and fall back to fact-only output when Foundry is missing or unavailable. The existing Copilot route appends narration evidence at medium confidence and explicitly returns retrieved context when the agent cannot be reached. [VERIFIED: src/api/routers/copilot.py:160-217, quote: "`Filter the entire payload before anything is shown or sent to the model`" and "`showing retrieved context only.`"] [VERIFIED: src/operations/foundry_agent.py:49-71, quote: "`FOUNDRY_SCOPE = \"https://ai.azure.com/.default\"`" and "`_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}`"]

**When to use:** For D-15 narrative and any AI-assisted D-16 mapping suggestion. The LLM is not the source of OS EOL truth and must not receive a request to directly mutate the catalog or silently merge software identities. [ASSUMED]

### Anti-Patterns to Avoid

- **Treating `ConfigurationData` as ARG:** It will produce an implementation that cannot execute against the documented source. Use the Logs Query API and workspace credentials/configuration. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview]
- **Claiming native VM image SKU is installed OS version:** Image reference data and guest OS state are different observations; expose the distinction and flag unresolved EOL matching. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/explore-resources]
- **Joining software to the nearest hostname:** This can cross subscriptions or merge duplicate names. Require exact `_ResourceId`, otherwise show an unlinked/unknown machine relationship. [ASSUMED]
- **Aggregating before RBAC filtering:** A count can leak the existence of out-of-scope software or machines even if the detail rows are later filtered. Apply `ReadScope` before every count, chart, export, and narrative input. [VERIFIED: src/api/dependencies.py:205-218, quote: "`handler physically cannot return out-of-scope rows`"]
- **Using `ConfigurationData` latest rows without a deterministic key:** `arg_max` must group by machine identity plus software name, not by version; grouping by version preserves obsolete versions as if they were currently installed. [ASSUMED]
- **Using LLM output as an automatic EOL winner:** D-07/D-08 require all candidates and operator confirmation. [VERIFIED: .planning/phases/06-software-and-os-inventory-visibility/06-CONTEXT.md:28-32, quote: "`it does not auto-pick a single answer`"]
- **Adding a second direct-Azure UI path:** Browser requests must continue through `apiRequest`, which attaches bearer/correlation headers and unwraps the common envelope. [VERIFIED: web/src/lib/api-client.ts:86-108, quote: "`Every call attaches a bearer token ... and an `X-Correlation-ID``"]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| ARG pagination and scope transport | A new paging loop in the inventory provider | Existing `AzureCliArgClient` / `AzureResourceGraphClient` through `QuerySpec` | Both clients already implement bounded page loops and continuation tokens. [VERIFIED: src/hermes_arg_connector/azure.py:92-134, 158-203, quote: "`for _ in range(self.max_pages):`" and "`if not continuation_token: return rows`"] |
| Common API trust contract | Per-route response dictionaries | `Evidence`, `ReadScope`, `Page`, and `envelope` | The UI and audit model expect source, timestamp, confidence, freshness, effective scope, warnings, and pagination in one contract. [VERIFIED: src/api/evidence.py:125-179, quote: "`A response body: the data, its evidence, and the scope it was read under.`"] |
| Lifecycle date validation | Ad hoc date parsing and status strings | Existing `LifecycleCatalogEntry` and `EOLCatalog.classify_product` | Existing code enforces ISO dates, date ordering, HTTPS citations, supported/unknown statuses, and calendar-month thresholds. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:40-94, 218-258, quote: "`Lifecycle dates must order release <= mainstream <= extended support`" and "`LifecycleStatus.UNKNOWN`"] |
| Software current-state selection | Keeping every historical ConfigurationData row in the UI | KQL `arg_max(TimeGenerated, *)` plus server-side canonicalization | CTI emits observations over collection cycles; the official query pattern uses `arg_max` for latest state. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/queries/configurationdata] |
| AI web discovery trust | A bespoke unbounded scraper or raw LLM answer | Interface-based adapters with HTTPS/vendor-domain allowlists and citation-bearing candidates | Static lifecycle code already establishes an authoritative-domain validation pattern; candidate retrieval must preserve citations for human review. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:76-94, quote: "`allowed_domains`" and "`source_url must use HTTPS`"] |
| CSV escaping | Naive `join(",")` export | A tested serializer that quotes cells and prefixes formula-leading values | Spreadsheet formula injection and commas/newlines are edge cases a minimal export must handle. [ASSUMED] |

**Key insight:** The difficult part is not rendering two tables; it is maintaining a truthful identity chain from two different Azure data planes to one authorized machine view. Reusing the existing source, evidence, lifecycle, and test primitives prevents a Phase 6-only parallel trust model.

## Common Pitfalls

### Pitfall 1: Source-plane mismatch

**What goes wrong:** The planner adds `ConfigurationData` to `QueryCatalog` and the ARG client attempts to run a Log Analytics table name against Resource Graph. [ASSUMED]

**Why it happens:** The phase description says “ARG data collected by Arc Change Tracking & Inventory,” while Microsoft documents the resulting inventory in a Log Analytics workspace `ConfigurationData` table. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-change-tracking-inventory/overview-monitoring-agent, quote: "`Ingests inventory metadata into the ConfigurationData table in the connected Log Analytics workspace.`"]

**How to avoid:** Make the data-plane boundary explicit in the design, configure workspace IDs, and return a distinct source status for Logs versus ARG. [ASSUMED]

**Warning signs:** No workspace ID in configuration, no Logs API token scope, or tests that only mock `AzureCliArgClient`.

### Pitfall 2: Native VM EOL false precision

**What goes wrong:** A marketplace image SKU or image version is presented as the installed OS release and matched to an EOL date with high confidence. [ASSUMED]

**Why it happens:** The native VM ARG example includes image-reference `offer`, `publisher`, `sku`, and `version`, but the same official material only demonstrates `osDisk.osType` for OS grouping. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/explore-resources, quote: "`imageReference` ... `sku` ... `version`" and "`osDisk` ... `osType`"]

**How to avoid:** Keep `image_*` metadata separate from `os_name/os_version`; require review for unresolved native versions and show the unknown badge. [ASSUMED]

**Warning signs:** A native VM's EOL mapping is marked supported solely from `imageReference.version == "latest"` or a custom image with no OS version.

### Pitfall 3: Arc/software identity cannot be joined

**What goes wrong:** Software rows have a `Computer` value but no exact Azure resource ID, so a fuzzy hostname join assigns software to the wrong duplicate host. [ASSUMED]

**Why it happens:** `ConfigurationData` exposes `_ResourceId`, `Computer`, and `SourceComputerId` as separate fields, and the documented table resource-type metadata does not list Arc machines in the same way as the Arc ARG resource table. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata, quote: "`_ResourceId`", "`Computer`", "`SourceComputerId`"]

**How to avoid:** Exact `_ResourceId` first; otherwise retain an unlinked row and warning, with no inferred source type. [ASSUMED]

**Warning signs:** Join code uses only lowercased `Computer`, software counts exceed known machine counts, or an Arc row changes subscription after a hostname collision.

### Pitfall 4: Stale or partial data looks empty

**What goes wrong:** A workspace outage, missing CTI onboarding, malformed Logs response, or throttled ARG query is rendered as “0 installed software.” [ASSUMED]

**Why it happens:** The UI naturally defaults to `data ?? []`, while providers can be unavailable or partial. The existing provider runtime explicitly distinguishes `ready`, `stale`, `partial`, `degraded`, and `unavailable`. [VERIFIED: src/api/providers.py:15-22, quote: "`READY = \"ready\"` ... `PARTIAL = \"partial\"` ... `UNAVAILABLE = \"unavailable\"`"]

**How to avoid:** Include per-source status and warnings in the envelope; reserve an empty result for a successful query with zero rows; show `StatePanel`/warning when a source is unavailable. [VERIFIED: src/api/evidence.py:136-153, quote: "`warnings` ... `Results are truncated; narrow the scope ...`"]

**Warning signs:** A failed source returns HTTP 200 with an empty array and no warning, or summary cards show zero while the evidence bar has no source timestamp.

### Pitfall 5: Aggregation leaks scope

**What goes wrong:** The API filters machine details but computes counts/charts from the unfiltered estate. [ASSUMED]

**Why it happens:** Grouping is often implemented before the router applies a scope, but existing `ReadScope` is the second RBAC enforcement point and must constrain the handler's service call. [VERIFIED: src/api/dependencies.py:205-218, quote: "`The second RBAC enforcement point for read routes.`"]

**How to avoid:** Pass `Scope` into every provider method and test both grouped counts and drill-down rows for subscription/business-service isolation. [VERIFIED: src/api/routers/vulnerability.py:36-55, quote: "`rows = service.exposures(scope)`" and "`scope=scope.to_dict()`"]

**Warning signs:** Out-of-scope software appears in “top software,” export row count differs from the displayed count, or a group-detail route accepts arbitrary machine IDs.

### Pitfall 6: Review persistence is mistaken for local UI state

**What goes wrong:** An operator selects an EOL candidate and the browser displays it, but the next request or API process restart loses it. [ASSUMED]

**Why it happens:** The current catalog is loaded from a file/default resource and `EOLCatalog.update` returns an object; no existing API mutation persists the selected entry. [VERIFIED: src/api/runtime.py:512-527, quote: "`EOLCatalog.from_file(...)` ... `EOLCatalog.default(...)`"] [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:186-196, quote: "`return EOLCatalog(...)`"]

**How to avoid:** Add a server-side versioned store and optimistic concurrency; retain candidate citations and operator identity in an audit/review record while updating the curated catalog. [ASSUMED]

**Warning signs:** `localStorage` is used for EOL decisions, the UI has no revision/conflict error, or the static file is written directly from a request without atomic replacement.

### Pitfall 7: AI normalization fragments or over-merges

**What goes wrong:** “7-Zip 19.00” and “7-Zip v19.00” remain separate, or unrelated products with similar names are silently merged. [ASSUMED]

**Why it happens:** Software publishers report inconsistent strings and LLM similarity is not an identity proof. [ASSUMED]

**How to avoid:** Store raw fields, deterministic normalized fields, normalization method, and confidence; apply exact deterministic rules first and route ambiguous AI mappings through a reviewable mapping table. [ASSUMED]

**Warning signs:** There is no raw value in the API response/evidence, canonical mappings are not versioned, or a model response directly changes group counts without a reproducible mapping record.

## Runtime State Inventory

This is a new inventory capability, not a rename/refactor/migration phase. No rename-state inventory is required. The relevant existing state is the lifecycle catalog and current immutable dataset path, which must be extended rather than replaced. [VERIFIED: src/hermes_arg_connector/storage.py:38-47, quote: "`Publishes complete immutable generations and atomically switches `current`.`"]

## State of the Art

| Old approach | Current approach | When changed | Impact |
|---|---|---|---|
| Treat all Azure operational data as `Resources`/ARG | Use the correct data plane per source: ARG for ARM/Arc resources and Logs Query API for workspace tables | Current Microsoft documentation distinguishes Resource Graph tables from Log Analytics tables. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources] | Phase 6 needs two source adapters and separate freshness/status evidence. |
| Return only a table of software strings | CTI `ConfigurationData` latest-state query keyed by machine/software, then canonical grouped projection | Current ConfigurationData query/schema docs. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/reference/queries/configurationdata] | Use `arg_max(TimeGenerated, *)`; preserve collection timestamps and raw identity. |
| Let an AI answer determine EOL | Curated catalog first, cited multi-source candidates second, explicit operator confirmation third | Locked D-06 through D-09 and D-14. [VERIFIED: .planning/phases/06-software-and-os-inventory-visibility/06-CONTEXT.md:28-32, quote: "`static table ... primary source of truth`", "`does not auto-pick a single answer`", "`written back into the static table`"] | AI is advisory/retrieval, never the lifecycle system of record. |

**Deprecated/outdated:**

- Do not use the legacy `api.loganalytics.io` hostname for new code; Microsoft says it is being replaced by `api.loganalytics.azure.com`, although the legacy endpoint remains supported for the foreseeable future. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api, quote: "`The `api.loganalytics.io` endpoint is being replaced by `api.loganalytics.azure.com`.`"]
- Do not add a browser-side Azure credential or arbitrary KQL endpoint; the existing API boundary and scoped provider pattern are the project standard. [VERIFIED: docs/OPERATIONS_API.md:3-10, quote: "`No handler reads Fabric, ontology tables, or Azure Resource Graph directly.`"]

## Validation Architecture

Nyquist validation is enabled because `.planning/config.json` has `"nyquist_validation": true`. [VERIFIED: .planning/config.json:20-22, quote: "`\"workflow\": { ... \"nyquist_validation\": true`"]

### Test Framework

| Property | Value |
|---|---|
| Python framework | `pytest` from the repository test configuration; project requires Python `>=3.11`. [VERIFIED: pyproject.toml:5, 37-39, quote: "`requires-python = \">=3.11\"`" and "`testpaths = [\"tests\"]`"] |
| Web framework | Vitest with jsdom, React Testing Library, and the existing setup file. [VERIFIED: web/vitest.config.ts:12-20, quote: "`environment: \"jsdom\"`" and "`setupFiles: [\"./src/test/setup.ts\"]`"] |
| Quick Python run | `pytest tests/test_queries.py tests/test_inventory_provider.py tests/test_api_inventory_router.py -q` |
| Full Python run | `pytest -q` |
| Quick web run | `cd web && npm run test -- src/app/software-inventory/page.test.tsx` |
| Full web run | `cd web && npm test` |

### Phase Decisions → Test Map

There are no Phase 6 requirement IDs in `REQUIREMENTS.md`; the roadmap marks Phase 6 requirements as TBD. The locked decision IDs are therefore the implementation acceptance map. [VERIFIED: .planning/ROADMAP.md:115-124, quote: "`### Phase 6: Software and OS Inventory Visibility`" ... "`**Requirements**: TBD`"]

| Decision | Behavior | Test type | Automated command | File exists? |
|---|---|---|---|---|
| D-01/D-02 | OS groups native VM and Arc machines by canonical OS identity and drills to exact machine rows with source type | unit + API | `pytest tests/test_inventory_provider.py -q` | ❌ Wave 0 |
| D-03/D-04 | Software groups by canonical name/version and supports exact general-purpose lookup | unit + API | `pytest tests/test_inventory_provider.py::test_software_grouping_and_exact_lookup -q` | ❌ Wave 0 |
| D-05 | CSV includes only scoped drill-down rows and safely quotes formula/comma/newline values | unit + UI | `cd web && npm run test -- src/app/software-inventory/page.test.tsx` | ❌ Wave 0 |
| D-06/D-09 | Catalog hit classifies EOL; catalog miss visibly returns review-required state | unit + UI | `pytest tests/test_inventory_provider.py::test_unmapped_os_requires_review -q` | ❌ Wave 0 |
| D-07/D-08/D-14 | Candidate resolver returns all cited candidates and confirmation persists with revision/concurrency validation | API integration | `pytest tests/test_api_inventory_router.py::test_eol_candidates_and_confirmation -q` | ❌ Wave 0 |
| D-10/D-11/D-12/D-13 | One page has two accessible tabs, cards/charts, required filters, and color-coded status | UI | `cd web && npm run test -- src/app/software-inventory/page.test.tsx` | ❌ Wave 0 |
| D-15 | Narrative is grounded in scoped aggregate facts and degrades visibly when Foundry is unavailable | API + UI | `pytest tests/test_api_inventory_router.py::test_narrative_degrades_without_foundry -q` | ❌ Wave 0 |
| D-16 | Raw software strings remain available while canonical grouping uses deterministic/approved mappings | unit + UI | `pytest tests/test_inventory_provider.py::test_software_normalization_preserves_raw_values -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** Run the affected Python test file or the co-located inventory page test.
- **Per wave merge:** Run `pytest -q` and `cd web && npm test`.
- **Phase gate:** Full Python and web suites green before `/gsd-verify-work`, plus a manual check that scope, stale/partial states, EOL review, drill-down, and CSV behavior are visible.

### Wave 0 Gaps

- [ ] `tests/test_inventory_provider.py` — source normalization, exact identity joins, grouping, EOL classification, software normalization, limits.
- [ ] `tests/test_api_inventory_router.py` — scope narrowing, envelope/evidence/pagination, provider outage, candidate review persistence, narrative fallback.
- [ ] `tests/fixtures/mock_arg_responses.json` extension or a dedicated inventory fixture — native VM image fields, Arc OS fields, and duplicate host names.
- [ ] `tests/fixtures/mock_configurationdata.json` — `ConfigDataType="Software"` rows, version changes, `_ResourceId` present/absent, `TimeGenerated` ordering.
- [ ] `web/src/app/software-inventory/page.test.tsx` — tabs, filters, chart/card summaries, EOL badges, drill-down, CSV, loading/error/unknown review states.
- [ ] `web/src/lib/services.test.ts` or equivalent — URL/query serialization for repeated scope and exact software/version filters.
- [ ] `tests/test_logs_client.py` — Logs API response `tables/columns/rows`, HTTP errors, malformed schema, bounds, and workspace scope.

## Security Domain

Security enforcement is enabled and the configured ASVS level is 1. [VERIFIED: .planning/config.json:35-37, quote: "`\"security_enforcement\": true`" and "`\"security_asvs_level\": 1`"]

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---|---|---|
| V2 Authentication | Yes | Reuse the existing `CurrentPrincipal`/authenticator path; every inventory route is protected by the API application security policy. [VERIFIED: src/api/dependencies.py:151-156, quote: "`def get_principal(...)` ... `authenticate(dict(request.headers))`"] |
| V3 Session Management | Limited | No new session store is needed; use the existing bearer-token and correlation-ID behavior and do not put Azure credentials in the browser. [VERIFIED: web/src/lib/api-client.ts:86-115, quote: "`Every call attaches a bearer token`" and "`const token = await getAccessToken()`"] |
| V4 Access Control | Yes | Require `ReadScope`; apply it before OS/software grouping, EOL candidate context, AI narrative input, detail rows, and CSV export. [VERIFIED: src/api/dependencies.py:205-218, quote: "`effective_scope(principal, \"read\", requested)`"] |
| V5 Input Validation | Yes | Use strict Pydantic request models (`extra="forbid"`), bounds on search/version strings, safe KQL escaping, allowlisted vendor URLs, and safe CSV cell escaping. [VERIFIED: src/api/models.py:17-20, quote: "`model_config = ConfigDict(extra=\"forbid\")`"] [ASSUMED: CSV formula-injection mitigation is needed for spreadsheet consumers] |
| V6 Cryptography | No new primitive | Do not hand-roll token or cryptographic code; reuse Entra/credential clients and existing bearer transport. [VERIFIED: src/hermes_arg_connector/azure.py:162-165, quote: "`get_token(\"https://management.azure.com/.default\")`"] |

### Known Threat Patterns for Azure inventory

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Out-of-scope machine/software disclosure | Information disclosure | Scope-narrow before aggregation and serialize only scoped rows; test subscription and business-service grants. [VERIFIED: src/api/scope.py:94-130, quote: "`effective scope can never be broader than what the principal may see`"] |
| KQL injection through search/version filters | Tampering | Validate lengths/types and escape single quotes before constructing a query; prefer fixed query templates and parameters where the client supports them. [VERIFIED: src/semantic/live_provider.py:40-49, quote: "`escaped_id = resource_id.replace(\"'\", \"''\")`"] |
| Provider outage rendered as empty inventory | Spoofing/information disclosure | Preserve `unavailable`, `partial`, `stale`, and warning states; never claim zero when the source did not answer. [VERIFIED: src/api/providers.py:83-99, quote: "`no safe provider to serve`" and "`Failed refreshes never replace a working provider`"] |
| CSV formula injection or delimiter breaking | Tampering | Quote every cell, prefix spreadsheet-formula-leading values, and test commas, quotes, CR/LF, and values beginning with `=`, `+`, `-`, or `@`. [ASSUMED] |
| Prompt injection or unsupported AI claim | Tampering/information disclosure | Send only bounded, scoped facts to Foundry; preserve citations and show fact status/narration warnings. [VERIFIED: src/operations/tools.py:4-17, quote: "`The Foundry agent never touches Azure, Fabric, or the ontology directly`" and "`each ... applies the caller's Scope`"] |
| Catalog update race or malicious URL | Tampering | Require exact normalized OS key, optimistic revision, ISO date, HTTPS, authoritative-domain validation, and atomic server-side write. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:62-94, quote: "`source_url must use HTTPS`" and "`Duplicate lifecycle catalog product/version`"] |

## Environment Availability

Phase 6 depends on Python, Node/npm, Azure CLI Resource Graph, and (for CTI software) a Log Analytics workspace and Entra-authorized Logs Query API path. The local probe found Node `v22.23.2`, npm `10.9.8`, Azure CLI `2.87.0` with Resource Graph extension `2.1.1`, and `uv 0.10.9`; Python is `3.9.6`, below the repository's declared `>=3.11`; `azmcp` is missing. [VERIFIED: environment probe 2026-08-25, quote: "`Python 3.9.6`", "`v22.23.2`", "`10.9.8`", "`azure-cli\": \"2.87.0\"`", "`resource-graph\": \"2.1.1`", "`uv 0.10.9`", "`azmcp missing`"] [VERIFIED: pyproject.toml:5, quote: "`requires-python = \">=3.11\"`"]

| Dependency | Required by | Available | Version | Fallback |
|---|---|---:|---|---|
| Python | Connector/API tests and runtime | ✗ wrong version | 3.9.6; project requires >=3.11 | Use the project's supported Python 3.11+ interpreter; do not change project constraints. |
| Node/npm | Next.js page/tests | ✓ | Node 22.23.2 / npm 10.9.8 | — |
| Azure CLI + Resource Graph extension | Existing ARG fallback and Phase 6 ARG queries | ✓ | Azure CLI 2.87.0 / extension 2.1.1 | — |
| `azmcp` | Existing subscription discovery default | ✗ | — | Explicit configured subscriptions or an existing registered connection can avoid discovery; otherwise this remains a Phase 1/runtime blocker. [VERIFIED: src/hermes_arg_connector/azure.py:44-74, quote: "`Thin process adapter over the official Azure MCP CLI`"] |
| Log Analytics workspace | CTI software inventory | Not verified locally | Workspace-specific | Configure a workspace registry/ID and test against a real or approved fixture workspace; no local service can substitute for CTI data. [ASSUMED] |
| Entra authorization for Logs Query API | CTI software inventory | Not verified locally | — | Use the existing connection credential only if it has workspace Reader/Logs query permission; otherwise surface source unavailable. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api, quote: "`To access the API, you must authenticate through Microsoft Entra ID`" and "`grant your app access to your Log Analytics workspace`"] |
| Foundry project/agent | D-15 narrative and optional LLM lookup | Not verified locally | Environment-configured | Return scoped deterministic facts plus a visible “narrative unavailable” warning; do not block core inventory reads. [VERIFIED: src/operations/foundry_agent.py:243-253, quote: "`Returning `None` ... lets a deployment run without Foundry`"] |

**Missing dependencies with no fallback:**

- Python 3.11+ is required to run the repository's declared test/runtime environment. [VERIFIED: pyproject.toml:5, quote: "`requires-python = \">=3.11\"`"]
- A configured Log Analytics workspace and authorized Logs Query API are required for real installed-software data; fixtures can only validate code paths. [ASSUMED]

**Missing dependencies with fallback:**

- `azmcp` can be bypassed only when subscriptions/connections are already configured; this does not repair the Phase 1 blocker. [ASSUMED]
- Foundry can fall back to fact-only output for core inventory, with D-15 marked unavailable rather than fabricated. [VERIFIED: src/api/routers/copilot.py:166-185, quote: "`No Foundry prompt agent is configured; returning retrieved context without a narrated answer.`"]

## Phase 1 Blockers Carried Forward

The requested Phase 6 scope does not authorize acting on Phase 1 blockers. The current state explicitly lists: “Validate exact provider contracts, permissions, pagination, watermarks, retention, and cross-domain identity normalization.” [VERIFIED: .planning/STATE.md:90-94, quote: "`Phase 1: Validate exact provider contracts, permissions, pagination, watermarks, retention, and cross-domain identity normalization.`"] Phase 6 should add inventory-specific tests and configuration checks that expose these dependencies, but should not attempt to resolve or rewrite Phase 1 foundation behavior in this research or plan.

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | Native VM ARG image metadata is not sufficient to assert installed OS release version for all tenants. | Summary; Pattern 2 | EOL risk could be falsely classified; confirm with representative tenant payloads. |
| A2 | `ConfigurationData` software rows can be joined reliably by `_ResourceId` for the target tenant/workspaces. | Pattern 4 | Software drill-down may require a governed computer-to-resource mapping or remain partially unlinked. |
| A3 | The project will configure one or more Log Analytics workspace IDs per connection or via a workspace registry. | Pattern 3; Environment | Software inventory cannot execute without workspace configuration. |
| A4 | A small in-browser CSV serializer is acceptable and can be made safe with tests. | Supporting stack; Security | A compliance/security review may require a shared export library or server-side export. |
| A5 | AI web/LLM search can be supplied through an optional server-side adapter without changing the Foundry narration boundary. | Pattern 6/7 | D-14 may need a separate approved search integration and human checkpoint. |
| A6 | Ambiguous software normalization mappings should be reviewable rather than silently merged. | Pattern 7; Pitfall 7 | Counts may remain fragmented until a mapping is approved, but silent false merges are worse. |

## Open Questions

1. **Which Log Analytics workspace(s) contain CTI `ConfigurationData` for each subscription/connection?**
   - What we know: CTI stores inventory in a connected workspace and the Logs API is workspace-ID based. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-change-tracking-inventory/overview-monitoring-agent] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview]
   - What's unclear: The current connection contract has subscription/tenant/credential but no workspace identifier. [VERIFIED: src/api/models.py:107-114, quote: "`subscription_id` ... `tenant_id` ... `credential` ... `metadata`"]
   - Recommendation: Make workspace IDs explicit configuration and fail that source as unavailable when absent; do not discover arbitrary workspaces from browser input. [ASSUMED]

2. **What native VM source will supply an EOL-matchable release version?**
   - What we know: Official ARG examples expose `osType` and image-reference fields; Arc exposes `osName/osVersion/osSku`. [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/virtual-machines/resource-graph-samples] [VERIFIED: Microsoft Learn, https://learn.microsoft.com/en-us/azure/azure-arc/servers/resource-graph-samples]
   - What's unclear: Whether the pilot tenant has guest inventory for native VMs or only image metadata.
   - Recommendation: Plan native rows with explicit unknown/review state and add fixture/tenant validation before claiming complete native EOL coverage. [ASSUMED]

3. **Should catalog review updates use the existing Fabric metadata table, a governed JSON file, or a new durable store?**
   - What we know: Existing sync persists `metadata_lifecycle_catalog`, while `EOLCatalog` loads from a file/default and validates rows. [VERIFIED: src/fabric/sync_service.py:611-660, quote: "`metadata.append({**base, **entry})`"] [VERIFIED: src/api/runtime.py:512-527, quote: "`EOLCatalog.from_file` ... `EOLCatalog.default`"]
   - What's unclear: D-06 requires a static table read at request time, while an API confirmation needs durable mutation and concurrency.
   - Recommendation: Choose one server-side authoritative store during planning, wrap it behind a catalog repository interface, and preserve the existing row schema/citations. [ASSUMED]

4. **Which web/LLM search provider is approved for D-14?**
   - What we know: The local GSD research environment had no configured search MCP/provider and the existing Foundry agent is a narration client, not a web-search implementation. [VERIFIED: environment/config probe 2026-08-25] [VERIFIED: src/operations/foundry_agent.py:205-212, quote: "`Invokes a Foundry prompt agent over the data-plane REST API`"]
   - What's unclear: Whether the deployed environment has an approved web search capability.
   - Recommendation: Keep a provider interface and an explicit unavailable state; require a human/configuration checkpoint before enabling external search. [ASSUMED]

5. **What is the desired semantics for paid support tiers?**
   - What we know: Existing lifecycle code has explicit `mainstream`/`extended` channels and does not infer paid support from dates. [VERIFIED: src/intelligence/lifecycle/eol_catalog.py:58-75, quote: "`default_support_channel` ... `mainstream` ... `extended`"]
   - What's unclear: Whether Phase 6's badge should use mainstream EOL, extended EOL, or a per-connection support entitlement.
   - Recommendation: Reuse the existing catalog support-channel field and show the channel in evidence; do not silently treat paid support as universally available. [VERIFIED: docs/LIFECYCLE_INTELLIGENCE.md:64-68, quote: "`paid Ubuntu ESM and RHEL ELS are never assumed`"]

## Sources

### Primary (HIGH confidence)

- Microsoft Learn — Azure VM Resource Graph sample queries; native `osDisk.osType` and image-reference examples: https://learn.microsoft.com/en-us/azure/virtual-machines/resource-graph-samples
- Microsoft Learn — ARG virtual machine discovery payload: https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/explore-resources
- Microsoft Learn — Arc-enabled server Resource Graph samples; `osName`, `osVersion`, `osSku`: https://learn.microsoft.com/en-us/azure/azure-arc/servers/resource-graph-samples
- Microsoft Learn — Change Tracking and Inventory overview; `ConfigurationData` destination and Arc support: https://learn.microsoft.com/en-us/azure/azure-change-tracking-inventory/overview-monitoring-agent
- Microsoft Learn — ConfigurationData table schema: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/configurationdata
- Microsoft Learn — ConfigurationData sample queries: https://learn.microsoft.com/en-us/azure/azure-monitor/reference/queries/configurationdata
- Microsoft Learn — Azure Monitor Logs Query API overview and access/authentication: https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview and https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/access-api
- Microsoft Learn — ARG query language, supported tables, scope, joins, and paging: https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/query-language, https://learn.microsoft.com/en-us/azure/governance/resource-graph/concepts/work-with-data, https://learn.microsoft.com/en-us/azure/governance/resource-graph/reference/supported-tables-resources
- Repository source of truth — ARG queries/source/normalization: `src/hermes_arg_connector/queries.py`, `source.py`, `azure.py`, `service.py`, `normalize.py`
- Repository source of truth — API scope/evidence/provider/router patterns: `src/api/dependencies.py`, `evidence.py`, `providers.py`, `routers/patching.py`
- Repository source of truth — lifecycle catalog and persistence integration: `src/intelligence/lifecycle/eol_catalog.py`, `src/fabric/sync_service.py`, `src/fabric/runtime.py`
- Repository source of truth — UI and test patterns: `web/src/app/exposure/page.tsx`, `web/src/app/compliance/page.tsx`, `web/src/app/compliance/page.test.tsx`, `web/src/hooks/useApi.ts`, `web/vitest.config.ts`

### Secondary (MEDIUM confidence)

- Next.js official client-component documentation: https://nextjs.org/docs/app/building-your-application/rendering/client-components
- Vitest official guide: https://vitest.dev/guide/
- Testing Library official React Testing Library introduction: https://testing-library.com/docs/react-testing-library/intro/
- OWASP ASVS project reference for the V2–V6 security review categories: https://owasp.org/www-project-application-security-verification-standard/ [CITED: official OWASP project]

### Tertiary (LOW confidence)

- No tertiary web-only finding is used to lock the architecture. The web-search research item was classified LOW and is retained only as a prompt for human validation of the approved web/LLM search provider. [VERIFIED: GSD classify-confidence seam, provider `websearch` -> `LOW`]

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH for repository patterns and Microsoft data-plane documentation; MEDIUM for the proposed new Logs adapter because it is not yet implemented.
- Architecture: MEDIUM; the source boundary and existing composition patterns are verified, but workspace configuration and native VM version coverage remain open.
- Pitfalls: MEDIUM; source mismatch, paging, scope, lifecycle, and provider degradation are verified patterns; CSV/AI normalization controls remain implementation recommendations.

**Research date:** 2026-08-25
**Valid until:** 2026-09-01 for Azure/AI integration details; 2026-09-24 for stable repository patterns.
