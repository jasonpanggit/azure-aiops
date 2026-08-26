---
phase: 1
slug: evidence-and-situation-foundation
status: draft
shadcn_initialized: false
preset: none
created: 2026-08-25
---

# Phase 1 — UI Design Contract

> Visual and interaction contract for the Evidence and Situation Foundation.
> The interface must make trust inspectable: a situation is not an all-clear,
> explanation, or action until its scope, source evidence, freshness, quality,
> and audit history are visible.

## Phase intent

Phase 1 is a read-and-foundation slice. It delivers durable situations,
normalized evidence, scoped reads, provenance, quality/freshness signals,
contradiction states, and append-only audit visibility. Do not imply
recommendation approval or remediation execution in this phase; those belong to
Phases 2–3.

The page-level design principle is **message before medium**. Every page must
lead with the operational statement it can prove, then choose the visual form
that makes that proof fastest to scan:

| Message | Intentional visual form |
|---|---|
| What needs attention now? | Posture scorecard + ranked situation table |
| Which durable situations are in scope? | Filterable queue/table |
| Why does this situation exist, and can I trust it? | Situation brief + evidence chain + timeline + bounded relationship view |
| Is source coverage trustworthy? | Source-health scorecards + freshness table |
| What was observed and by whom? | Append-only audit timeline/table |
| Where are the linked operational entities? | Bounded graph/context list, never an unbounded “spiderweb” |
| Can I find an authorized record? | Intent search with result cards and explicit scope |

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | Fluent UI v9 (`@fluentui/react-components`) plus existing project primitives |
| Icon library | Fluent UI System Icons (`@fluentui/react-icons`); use icons only when they improve recognition, with accessible labels |
| Font | Existing Segoe UI system stack; use Segoe UI for UI and a monospace fallback only for IDs, timestamps, and source references. A Geist migration is deferred until the font assets are actually present. |

Existing Fluent UI and CSS primitives are the source of truth; do not introduce
shadcn, Tailwind, a second icon set, or a competing token system.

## Existing UI surface and implementation mapping

Reuse `AppShell`, `ScopeSelector`, `PageHeader`, `EvidenceBar`, `MetricCard`,
`StatusBadge`, `StatePanel`, `DataCard`, `SituationTable`, `StructuredData`,
`TopologyWorkspace`, and existing `CopilotDrawer` patterns. Extend the
existing `web/src/app/globals.css` tokens rather than replacing them.

| Surface | Current route/file | Phase 1 contract |
|---|---|---|
| Global context | `web/src/components/AppShell.tsx`, `web/src/app/layout.tsx` | Persistent operating scope, advisory mode, runtime/knowledge health, and signed-in operator remain visible. Scope changes reload all data and show the selected scope in the page proof. |
| Command center | `web/src/app/page.tsx` | Lead with “What needs attention now”; scorecard is a qualified posture summary, not a definitive health claim. Keep ranked situations and data-coverage risk above secondary domains. |
| Situation queue | `web/src/app/situations/page.tsx` | Primary Phase 1 route. Use table for comparison, search and P1/P2/P3 filters, explicit current-scope count, freshness/evidence bar, and no-results distinction. |
| Situation detail | `web/src/app/situations/[id]/page.tsx` | Primary Phase 1 route. Reframe as “What happened / what is affected / what supports this / what remains unknown”. Use summary scorecards, evidence drawer, linked entities, timeline, contradictions, and audit history. |
| Investigation context | `web/src/app/investigate/page.tsx` | Existing cross-domain context remains a read-only bridge to Phase 2. Surface source/freshness qualification before any synthesis; do not present a recommendation as executable. |
| Search | `web/src/app/search/page.tsx` | Keep governed intent search. The current `StructuredData` output is an interim read-only representation; the target is typed result cards identifying entity type, scope, source/freshness, key attributes, and navigation target rather than dumping raw JSON as the primary view. |
| Correlated changes | `web/src/app/changes/page.tsx` | Timeline is the right form. Label correlation as temporal proximity, not causation; every event gets source/time and links back to a situation when an authorized match exists, plus an evidence/source link or an explicit unavailable marker. |
| Services | `web/src/app/services/page.tsx`, `services/[name]/page.tsx` | Table for service inventory; detail hierarchy for ownership, situations, evidence coverage, and dependencies. “Not mapped” is a visible data-quality state. |
| Data coverage | `web/src/app/connections/page.tsx` | Treat as source trust/coverage view: scorecards plus table for freshness, sync status, credential/availability state, business context, and record counts. |
| Topology | `web/src/app/network/page.tsx` | Graph only for bounded path questions; pair it with a textual deciding-path list and evidence. Never make canvas geometry the sole proof. |
| Twin | `web/src/app/twin/page.tsx` | Graph/relationship and temporal views are intentional. Qualify revision, confidence, freshness, and partial data; raw export is secondary. |
| Compliance | `web/src/app/compliance/page.tsx` | Scorecard + violation table + selected finding context. Accepted exceptions remain visible and carry owner/reason/expiry. |
| Exposure | `web/src/app/exposure/page.tsx`, `exposure/cves/[id]`, `exposure/kbs/[id]` | Tables for prioritization; risk gauge/radar and attack-path graph only as supporting proof. Preserve source, publication, affected assets, and unknowns. |
| Changes predeploy | `web/src/app/changes/predeploy/page.tsx` | Existing assessment form and evidence/table hierarchy; this phase only supplies evidence foundations, not approval or execution. |
| Remediation | `web/src/app/remediation/page.tsx` | Preserve as future-phase/read-only candidate surface. Existing “Create action plan” and “Open remediation candidate” controls are read-only handoffs in Phase 1 and must be labeled “View future-phase candidate”; no executable CTA or approval implication is allowed. |
| Agents/Copilot | `web/src/app/agents/page.tsx`, `copilot/page.tsx` | Evidence reconciliation and trust boundary stay visible. Do not use chat as the primary route for durable situations. |
| Governance/Identity/Admin | `governance/page.tsx`, `identity/page.tsx`, `admin/page.tsx` | Tables and review packs remain audit/access surfaces. Empty data must say “not observed” or “unavailable”, never imply zero risk. |
| FinOps | `finops/page.tsx` | Existing scorecards/tables remain outside Phase 1’s primary acceptance path; use the same evidence bar and qualified unavailable states. |
| Vulnerabilities | `vulnerabilities/page.tsx` | Portfolio entry point: lead with severity/reachability posture, then use a ranked CVE table with a clear path into Exposure detail. |

## Page contracts

### `/` — Operational command center

**Operator message:** “Within my authorized scope, this is the current
operational posture, these situations deserve attention, and this is how much
the evidence coverage can be trusted.”

Hierarchy:
1. `PageHeader`: “What needs attention now” and scope-aware description.
2. Posture scorecard: numeric posture is accompanied by label, calculation
   caveat, selected scope, and last evidence update.
3. Four compact scorecards: critical situations, reachable exposure, control
   gaps, and data coverage risk.
4. Ranked situation table (six rows maximum, “View all”).
5. Service risk concentration and operational data coverage.

The posture treatment may use a visually strong hero, but it must retain the
qualification, evidence bar, and ranked queue immediately below it. The score is
a summary; the table and evidence bar are the proof. Decorative treatment must
never imply a definitive health guarantee.

### `/situations` — Durable situation queue

**Operator message:** “These are the authorized situations currently requiring
triage, ranked by impact and evidence confidence.”

Use a comparison-first table with columns: priority, situation/title and state,
business impact, likely cause (qualified), owner/support team, latest related
change, and open action. Priority and lifecycle use text plus status color.
Search matches title, ID, owner, service, application, and cause. Priority
filter is an explicit segmented control. Preserve pagination and show
`Showing X–Y of Z`.

The table is the canonical queue; do not replace it with cards. On narrow
screens, horizontal scroll is allowed but the first two columns must remain
understandable, and the open action remains reachable.

### `/situations/[id]` — Evidence-backed situation brief

**Operator message:** “This durable situation is [state/severity] in [scope],
affects [resources/services], and here is exactly what supports, qualifies, or
contradicts that statement.”

Top section:
- Breadcrumb back to Situations.
- Title, situation ID, lifecycle, severity, priority, owner, scope, started and
  last-observed timestamps.
- A compact trust summary: overall evidence state, freshest source timestamp,
  source availability, quality, and authorization scope.

Main layout:
- Left/wide: “What failed?”, “What is at risk?”, and “What changed?” summary
  cards, followed by a chronological correlated timeline.
- Right: “Who owns it?”, affected-resource count, linked operational entities,
  and next read-only navigation.
- Evidence section: source-grouped rows/cards with source ID/deep link,
  observed/ingested times, watermark, ingestion status, provenance, and
  quality/freshness band.
- Contradictions and unknowns are a distinct warning panel before any
  conclusion. Use “Evidence conflicts” and “What is not known”, not hidden
  fallback copy.
- Audit section: append-only events with actor, action, timestamp, scope
  snapshot, related source/situation/evidence ID. Show newest first with a
  “Recorded event” label; never offer edit/delete controls.

Evidence rows open a drawer or detail region; selection must preserve the
operator’s scroll position and expose a close button and keyboard focus return.
Use graph view only for a bounded “linked entities” panel, with a list fallback
and explicit node/edge labels.

### `/connections` — Data coverage and source trust

**Operator message:** “Which sources make this operating picture trustworthy,
which are stale/degraded, and what scope or metadata is missing?”

Use scorecards for total, current, stale, failed, and context gaps. The table
must show source/connection, authorized business context, health, sync status,
last successful sync, freshness band, and discovered-record count. A stale or
failed row is not omitted. Onboarding and editing are separate from the
read-only trust summary.

### `/changes` — Correlated observation timeline

**Operator message:** “These source events occurred near active situations; the
interface shows correlation, not an unsupported causal conclusion.”

Use a vertical timeline with event type, source, exact timestamp, relative
time, affected situation, and evidence link. Keep “No correlated changes” as a
valid scoped result, separate from unavailable source data.

### `/search` — Governed operational discovery

**Operator message:** “This supported intent returned these authorized entities,
and here is how the result was interpreted.”

Keep the large search input and supported-intent suggestions, but render results
as typed entity cards with title/ID, entity type, scope, key operational
attributes, source/freshness, and a clear navigation link. Raw structured data
is an expandable secondary view. Empty results mean “understood, no match in
scope”; unsupported intent/error means a different state.

### Cross-route implementation gaps and read-only labels

The current codebase contains several controls from later phases. During this
contract's implementation, preserve them only as explicitly read-only
navigation:

| Current label | Phase 1 presentation |
|---|---|
| `Search` | `Find authorized records` |
| `Save command state` | `Save view locally` (local collaboration only; not audit history) |
| `Create action plan` | `View future-phase candidate` |
| `Open remediation candidate` | `View future-phase candidate` |
| `Onboard subscription` | Keep in a separate source-management area, not inside the trust summary |

Situation detail audit UI must distinguish server-recorded append-only events
from localStorage collaboration notes. If a durable situation/evidence/audit
endpoint is not available in the current API, the UI must show
“Audit history unavailable from the service” rather than presenting local notes
as immutable audit history. The target Phase 1 API contract is:

`GET /situations/{id}` — lifecycle, scope snapshot, ownership, affected
entities, normalized evidence references, freshness/quality, contradictions,
unknowns.

`GET /situations/{id}/audit` — append-only events with actor, action, timestamp,
scope snapshot, and related source/situation/evidence IDs.

`GET /evidence/{id}` — source identifier, source/deep link, observed and
ingested timestamps, watermark, ingestion status, provenance, quality, and
freshness band.

## Spacing Scale

Declared values (must be multiples of 4):

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, status-dot gaps, inline metadata |
| sm | 8px | Compact controls, table secondary lines |
| md | 16px | Card body padding, default control gaps |
| lg | 24px | Section padding, page-header separation |
| xl | 32px | Grid gaps, major card groups |
| 2xl | 48px | Page-level section breaks |
| 3xl | 64px | Only for spacious command-center separation |

Exceptions: minimum pointer targets for icon-only/mobile controls, and the
existing top bar/sidebar shell tokens. Existing component-level geometry may
retain legacy values, but all new page-level layout values must use the
declared 4px scale.

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.45 |
| Label | 12px | 600 | 1.3 |
| Heading | 18px | 600 | 1.2 |
| Display | 28px | 600 | 1.2 |

These values document the live system rather than requiring a disruptive global
typography migration. IDs, watermarks, and source identifiers use a monospace
fallback at 12px and must remain selectable. New UI should use only the four
declared sizes and regular 400 or semibold 600. Existing legacy component
weights are not a pattern for new surfaces.

## Color

Existing `globals.css` tokens are authoritative:

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `#eef2f7` canvas / `#ffffff` surface | Page background and readable content surfaces |
| Secondary (30%) | `#fafafa` / `#f0f2f5` | Cards, table sub-surfaces, sidebar, nav, controls |
| Accent (10%) | `#0f6cbd` | Primary CTA, active nav, links, selected table row, focus ring, evidence/source navigation |
| Destructive | `#b42318` | Destructive or critical states only; never use as decorative emphasis |

Semantic colors remain `critical #b42318`, `high #d83b01`, `warning #8a6100`,
`success #107c10`, and `info #005a9e`, each paired with its existing subtle
background. Accent is reserved for primary navigation state, one primary CTA
per decision surface, actionable links, selection, and focus—not every
interactive element. Status must never be conveyed by color alone.

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | `Open situation queue` |
| Situation detail navigation CTA | `Review evidence` |
| Empty situation queue heading | `No active situations in this scope` |
| Empty situation queue body | `No durable situation records are currently available for the selected operating scope. This is not a source-health confirmation; review data coverage below.` |
| Empty filtered queue heading | `No situations match these filters` |
| Empty filtered queue body | `Adjust the priority or search criteria. This result reflects the current operating scope.` |
| Empty evidence heading | `No evidence is linked yet` |
| Empty evidence body | `The situation exists, but no normalized source records are available in this scope. Do not treat the absence as confirmation that nothing happened.` |
| Error state | `Situation intelligence is unavailable. The workbench will not present an empty queue as an all-clear state. Check source health and try again.` |
| Stale state | `Evidence is stale — verify the source before relying on this conclusion.` |
| Future-phase handoff | `View future-phase candidate` |
| Local collaboration | `Save view locally` |
| Contradiction state | `Evidence conflicts — review the source records before drawing a conclusion.` |
| Unavailable source | `Source unavailable — freshness and quality cannot be confirmed.` |
| Audit empty state | `No audit events are visible in this scope.` |
| Destructive confirmation | `Delete or suppress situation: not available in Phase 1. Durable records and audit events are not deletable from the UI.` |

Prefer “observed”, “linked”, “correlated”, “available”, “stale”, “degraded”, and
“unknown” over “proved”, “root cause”, “healthy”, or “all clear” unless the
API supplies that authoritative state.

## UI Considerations

Applicable state considerations resolved: 8 covered, 2 backstop, 0 unresolved.

| Category | Element(s) | Status | Resolution / Reason |
|----------|------------|--------|---------------------|
| empty | situation queue, evidence, audit, linked entities | ✅ covered | Use the documented empty copy and distinguish no data from unavailable data and from zero findings. |
| loading | all API-backed route surfaces | ✅ covered | Use `StatePanel` status with a specific activity message; retain page heading and scope while loading. |
| error | situations, evidence, source coverage, search | ✅ covered | Use alert state with problem plus next step; never render an empty table as success. |
| populated | queue, detail, evidence, timeline, audit | ✅ covered | Use tables/timelines for comparison and chronological proof; expose IDs, timestamps, and links. |
| partial | dashboard fan-out, situation detail, source coverage | ✅ covered | Keep available sections, show per-source warning in `EvidenceBar`, and label missing providers. |
| overflow | long IDs, source links, table columns, timeline text | ✅ covered | Wrap human text, use horizontal table scroll, preserve selectable monospace IDs, and provide full value via title/accessible name. |
| zero-one-many | metrics, linked resources, evidence, audit events | ✅ covered | Copy uses singular/plural correctly; one item remains fully attributed, many remain scannable. |
| long-text | causes, provenance, warnings, descriptions | 🧪 backstop | Visual/UI test must verify wrapping, no clipped proof, and usable drawer content at representative long values. |
| authorization | scope selector and all nested records | ✅ covered | Display current scope and scope-limited counts; forbidden records render as absent/not-found per API contract, never as leaked placeholders. |
| stale/contradictory | evidence bar, detail warnings, source rows | 🧪 backstop | Held-out UI-state test must verify stale/degraded/contradictory records cannot display an unqualified definitive conclusion. |

## Accessibility and interaction

- Maintain semantic landmarks: one `h1`, descriptive `h2`s, `nav`,
  `main`, table captions/labels where needed, and `aria-live`/`role="status"`
  for loading. `StatePanel` errors use `role="alert"`.
- All status badges include text. Pair severity/health color with label, icon
  shape, or text; meet WCAG AA contrast for text and controls.
- Keyboard order follows page proof: scope → primary action → filters →
  evidence/trust → content → secondary navigation. Every row action has an
  accessible name such as `Investigate <title>`.
- Focus is visible with the existing brand focus ring. Drawers, dialogs, and
  mobile navigation trap focus while open, close on Escape, and return focus to
  the trigger.
- Do not expose hidden chain-of-thought, secrets, credentials, or unauthorized
  fields. Source IDs/deep links may be shown only when returned within scope.
- Graphs require a text/list equivalent, labelled nodes/edges, keyboard
  navigation where interactive, and a visible statement of graph bounds.
- Dates use machine-readable `<time>` with exact absolute value available;
  relative labels (“5m ago”) are supplementary, not the only timestamp.

## Responsive behavior

- Desktop (≥1101px): retain 244px sidebar, 56px top bar, max content width
  1440px, and two-column detail/dashboard grids.
- Tablet (769–1100px): collapse multi-column grids to one readable main column;
  keep trust bar and filters wrapped; topology/detail side panels stack.
- Mobile (≤768px): sidebar becomes the existing menu drawer; cards stack;
  page actions wrap; table containers scroll horizontally; evidence chains wrap
  into rows; drawers become full-width/bottom sheets with an obvious close.
- Never hide scope, freshness, authorization, severity, or error state on small
  screens. Secondary metadata can collapse behind a labelled disclosure.
- Minimum interactive target is 44×44px. Avoid hover-only affordances and do not
  require graph dragging to discover a fact.

## Data and state contract

Every material situation/evidence claim must be renderable from the API envelope:
`data`, `evidence`, `scope`, optional `warnings`, and pagination. The UI must
surface:

- situation identity, lifecycle, type, severity, priority, scope, owner,
  timestamps, affected resources, and linked entity IDs;
- evidence source family/object ID, observed and ingested timestamps, watermark,
  ingestion status, provenance/deep-link input, freshness band, availability,
  quality, and confidence;
- contradiction/incompleteness warnings as first-class state;
- audit event ID, actor, action, scope snapshot, timestamp, and source
  references, in append-only presentation order.

Scope changes invalidate visible data and show loading before replacement.
Partial fan-out responses retain successful panels and attach warnings to the
specific source/panel. A `404`/forbidden result must not reveal whether an
out-of-scope situation exists.

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| none | none | not applicable |

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
