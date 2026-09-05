---
phase: 13
slug: autonomous-ontology-discovery-and-fabric-synchronization
status: approved
shadcn_initialized: false
preset: none
created: 2026-09-04
reviewed_at: 2026-09-04T22:27:36.420+08:00
---

# Phase 13 — UI Design Contract

> Visual and interaction contract for the autonomous ontology operating surface.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none — reuse the repository's bespoke CSS system |
| Preset | not applicable |
| Component library | existing `web/src/components/ui/*` primitives |
| Icon library | none — preserve existing text glyph and status-dot conventions |
| Font | `"Segoe UI Variable", "Segoe UI", Arial, sans-serif` |

Phase 13 extends the existing `/connections` Data & Integrations experience. It
must not initialize shadcn, add a route/nav product, or introduce parallel
buttons, badges, tables, dialogs, or visual tokens.

---

## Information Architecture

Add an **Ontology automation** tab (`ontology-automation-tab`, controlling
`ontology-automation-panel`) to the existing tab list alongside Subscriptions
and Fabric Medallion. The tab state becomes
`"subscriptions" | "fabric-medallion" | "ontology-automation"`.

Keep one `PageHeader`. While this tab is active, render title **Ontology
automation** and description **"Monitor scheduled discovery, review proposed
relationships, and manage validated Fabric ontology generations for one
onboarded connection."** Its action slot contains:

1. a required **Connection** selector populated from the already scope-filtered
   connection list; and
2. **Run discovery now**, disabled until a connection is selected and the
   server says a run-now action is eligible.

Default to the first active in-scope connection only when no selection exists,
matching the Fabric Medallion selector behavior. Never retain a selected
connection after it leaves effective scope. Every ontology query/mutation carries
the selected `connection_id`; the server remains authoritative for subscription
scope and eligibility. With no onboarded connections, show **No subscriptions
onboarded**. With connections but no valid selection, show **Select a connection
to view ontology automation** and disable all mutations with that reason.

The panel order is:

1. An evidence/warning bar with knowledge version and scoped warnings.
2. Four compact metric cards: scheduler state, last valid generation, proposals
   awaiting review, and current validation status.
3. Scheduler card: enabled state, cadence, next due run, last trigger, and a
   quiet **Run discovery now** action.
4. Current-run card: trigger, stage, progress, checkpoint, attempt, deadline,
   lease owner/fence/expiry, cancellation state, and server-projected **Cancel
   run** / **Retry discovery run** eligibility with exact disabled reasons.
5. Incremental-discovery card: added, changed, retired, unresolved, and stale
   counts plus the last full-reconciliation time/result. A bounded pending-edge
   table shows subject, predicate, object, missing endpoint, first/last observed,
   attempts, and status.
6. Proposal-review table: subject, predicate, object, confidence, evidence
   freshness, decision state, and review action. Pagination and filters are
   mandatory; raw model output is never the primary view.
7. Generation/publication card: active generation, source generation, validation
   summary, fence/version, prior generation, rollback eligibility, and attempt
   history. **Roll back generation** is shown only for server-projected eligible
   prior generations and always carries an exact disabled reason otherwise.
8. Paginated run/publication-attempt history: trigger, start/end, terminal state,
   last checkpoint, proposal/accepted/published counts, source/target generation,
   attempt, and failure class. Eligible rows expose **Retry discovery run**.
9. Evaluation/agent card: curator version, shadow/allowlisted mode, last
   evaluation gate, precision/recall, injection test, latency, and degraded-agent
   status. Agent degradation must not imply deterministic refresh failure.

When a run is active, the current-run card is the primary visual anchor and
appears above metrics. When idle, metrics remain first and the most recent
terminal run appears in normal sequence.

No action may depend on browser polling to complete. The page reads durable run
state and may be closed/reopened without changing the lifecycle.

---

## Component Inventory

| Component | Status | Usage |
|-----------|--------|-------|
| `PageHeader` | reused | tab-specific description and Run discovery now action |
| `StatePanel` | reused | loading, unavailable, empty, partial, and failed section states |
| `StatusBadge` / `statusTone()` | reused/extended | run, proposal, generation, agent, and validation statuses |
| `MetricCard` | reused | scheduler, generation, review, and validation summary |
| `EvidenceBar` | reused | scope, warnings, and knowledge-version evidence |
| `TableColumnFilters` | reused | trigger/stage/status/predicate/decision filters |
| `TablePagination` | reused | run, proposal, and generation history |
| `StructuredData` | reused | secondary evidence and validation details inside `<details>` |
| Existing `callout` classes | reused | degraded, stale, failed, and recovery guidance |
| Existing `.form-control` select | reused | selected connection in `PageHeader` actions |
| `operations-table` / `table-scroll` | reused | pending edges, proposals, runs, and publication attempts |
| New visual primitive | forbidden | compose existing primitives only |

---

## Spacing Scale

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | status and inline evidence gaps |
| sm | 8px | compact control spacing |
| md | 16px | cards, table controls, metric grid |
| lg | 24px | section spacing |
| xl | 32px | page/panel spacing |
| 2xl | 48px | not introduced by this phase |
| 3xl | 64px | not introduced by this phase |

Exceptions: reused components keep their existing padding exactly; Phase 13 does
not refactor global spacing.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.45 |
| Label/table header | 12px | 600 | 1.4 |
| Section heading | inherit shared card heading | inherit | inherit |
| Display/metric | inherit `MetricCard` | inherit | inherit |

No new font, display scale, or arbitrary weight is introduced.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `var(--color-canvas)`, `var(--color-surface)` | page, cards, tables |
| Secondary (30%) | `var(--color-surface-muted)`, `var(--color-border)` | card headers, tab track, dividers |
| Accent (10%) | `var(--color-brand)` | selected tab, primary run-now action, focus ring |
| Destructive | `var(--color-critical)` | cancel or rollback only |

Accent is reserved for selection, Run discovery now, links, and focus. It is
never used as a success/failure semantic color.

---

## Status Vocabulary

| Domain | Labels |
|--------|--------|
| Scheduler/run | `Due`, `Queued`, `Discovering`, `Proposing`, `Review pending`, `Validating`, `Publishing`, `Succeeded`, `Failed`, `Cancelled`, `Timed out` |
| Proposal | `Pending review`, `Accepted`, `Rejected`, `Superseded`, `Auto-accepted by policy`, `Blocked` |
| Generation | `Staged`, `Valid`, `Active`, `Rejected`, `Rolled back`, `Superseded` |
| Agent | `Available`, `Degraded`, `Unavailable`, `Shadow mode`, `Allowlisted auto-accept` |

Never collapse these distinctions:

- Agent unavailable is not deterministic discovery failed.
- No proposals is not no ontology change; explain whether the run found no
  changes, produced no supported proposals, or could not invoke the agent.
- A successful run is not a successful publication until the active-generation
  pointer changed.
- Cancel requested is not cancelled until the server records a terminal state.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA | **Run discovery now** |
| CTA supporting text | "Uses the same durable coordinator as scheduled discovery. Closing this page does not stop the run." |
| No connection heading | "No subscriptions onboarded" |
| No connection body | "Onboard an Azure subscription connection before configuring or running ontology discovery." |
| No selection heading | "Select a connection to view ontology automation" |
| No selection body | "Choose an in-scope connection above. Discovery, proposal review, and generation actions are connection-specific." |
| Empty proposal heading | "No relationship proposals need review" |
| Empty proposal body | "The latest completed run produced no proposals requiring a decision for this scope." |
| Filtered proposal empty | "No proposals match these filters" + **Clear filters** |
| No-run heading | "Ontology discovery has not run for this connection" |
| No-run body | "Wait for the scheduled run or run discovery now. Existing Fabric ontology data is unchanged." |
| Empty run history | "No discovery run history is available for this connection." |
| Empty publication history | "No ontology publication attempts are available. Existing Fabric data is unchanged." |
| Empty pending edges | "No relationships are waiting for unresolved endpoints." |
| Agent degraded | "Relationship proposal agent is unavailable. Deterministic discovery can continue; no model proposals will be promoted." |
| Failed run | "Ontology discovery failed at {stage}. {safe_reason} Review the attempt, then retry from the recorded checkpoint." |
| Scheduler error | "Ontology schedule is unavailable. Existing run and generation history remains visible. Refresh status or run discovery manually if eligible." |
| Proposal error | "Relationship proposals are unavailable. No review decision was changed. Refresh proposals before acting." |
| Incremental/pending-edge error | "Incremental discovery details are unavailable. No pending relationship was removed or promoted. Refresh discovery details." |
| Generation error | "Ontology generation status is unavailable. Do not assume publication completed. Refresh generation status." |
| Evaluation error | "Agent evaluation status is unavailable. Auto-accept remains disabled until evaluation evidence is restored." |
| Run-history error | "Discovery run history is unavailable. Current run state was not changed. Refresh run history." |
| Publication-history error | "Publication attempt history is unavailable. The active generation was not changed. Refresh publication history." |
| Run-now failure | "Discovery was not started for connection {connection_id}. {safe_reason} Refresh connection status before trying again." |
| Cancel failure | "Cancellation was not requested for run {run_id}. {safe_reason} Refresh run status before trying again." |
| Retry failure | "Retry was not started for run {run_id}. {safe_reason} Refresh run eligibility before trying again." |
| Proposal-decision failure | "Proposal {proposal_id} was not {accepted/rejected}. {safe_reason} Refresh the proposal before deciding again." |
| Rollback failure | "Generation {generation_id} was not activated. {safe_reason} Refresh generation history and rollback eligibility before trying again." |
| Stale data | "The active ontology generation is older than its freshness objective. Last valid generation remains available." |
| Cancel action | **Cancel run** |
| Retry action | **Retry discovery run** |
| Rollback action | **Roll back generation** |
| Cancel confirmation | "Cancel run {run_id}? Work stops at the next safe checkpoint. The active ontology generation will not change." |
| Rollback confirmation | "Roll back to generation {generation_id}? This changes the active pointer and preserves both generations and the audit history." |
| Review accept | **Accept proposal** |
| Review reject | **Reject proposal** |

Copy must describe the exact server state and recovery path. Never use "AI
updated the ontology" before deterministic validation and publication succeed.

---

## UI Considerations

Applicable state considerations resolved: 12 covered, 1 backstop, 0 unresolved.

| Category | Element(s) | Status | Resolution / Reason |
|----------|------------|--------|---------------------|
| empty | run history | ✅ covered | Render documented no-run copy and preserve last active generation if one exists. |
| empty | proposal review table | ✅ covered | Render documented no-proposals copy, not a blank table. |
| empty | filtered proposal results | ✅ covered | Render "No proposals match these filters" with Clear filters; do not reuse the no-proposals-for-review state. |
| empty | pending edges and history | ✅ covered | Pending edges, run history, and publication history each use their distinct documented zero-state copy. |
| loading | each panel section | ✅ covered | Sections load independently with `StatePanel tone="loading"`; one slow source never blanks the page. |
| error | scheduler/run API | ✅ covered | Section-local error preserves generation and proposal data already loaded. |
| partial | unavailable curator agent | ✅ covered | Degraded callout explicitly states deterministic discovery may continue and no proposals are promoted. |
| partial | publication failure after discovery | ✅ covered | Run card shows publication failure while active generation card remains on the prior valid generation. |
| partial | lease lost or expired | ✅ covered | Current-run card shows lease/fence/expiry and disables mutation according to server eligibility; it never reports the run as active owner after lease loss. |
| populated | one current run | ✅ covered | Compact stage/progress card; no table required for the single current run. |
| zero-one-many | proposal and run history | ✅ covered | Zero-state copy, single rows, and paginated/filterable tables all use existing patterns. |
| overflow | proposal evidence and rationale | ✅ covered | Clamp table cells; expose bounded details in `<details>` using `StructuredData`. |
| long-text | resource IDs, errors, citations | ✅ covered | Wrap/break canonical IDs and bound visible error/rationale text; no horizontal page overflow. |
| stale | old generation or overdue scheduler | ✅ covered | Warning callout includes observed time, freshness objective, and safe run-now action. |
| destructive | cancel and rollback | ✅ covered | Server eligibility controls disabled state; explicit confirmation uses exact run/generation IDs. |
| scope | selected connection | ✅ covered | Selector is populated only from effective-scope connections; every read/mutation binds selected connection ID and clears selection if scope changes. |
| accessibility | tabs, tables, progress, callouts | 🧪 backstop | Verify keyboard tab behavior, focus return after review, `aria-live` run updates, accessible status text, and non-color-only distinctions. |

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not applicable |
| third-party registries | none | prohibited for this phase |

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved 2026-09-04
