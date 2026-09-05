# Phase 10 — Exposure UI Review

**Audited:** 2026-09-03  
**Scope:** Exposure web page/component layer only; backend/API implementation excluded  
**Baseline:** Abstract six-pillar standards  
**Screenshots:** Not captured — no local server responded on ports 3000, 5173, or 8080. The supplied live URL reaches the organizational sign-in gate under unauthenticated automation.  
**Human review rule:** Authenticated-data visual claims are explicitly marked `needs_human_review: true`.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|---|---:|---|
| 1. Copywriting | 3/4 | Strong decision-oriented headings and remediation labels, but generic errors, unexplained terminology, and ambiguous empty-state copy remain. |
| 2. Visuals | 2/4 | The overview and drilldowns establish hierarchy, but the Defender page is a long undifferentiated stack and detail routes lose active navigation context. |
| 3. Color | 2/4 | Status tokens are coherent, but undefined CSS variables can make the destructive action illegible and muted text fails normal-text contrast. |
| 4. Typography | 2/4 | Headings are clear, but operational tables rely heavily on 10–11px text and too many one-off sizes/weights. |
| 5. Spacing | 2/4 | Card/grid spacing is generally consistent, but narrow controls, dense tables, and one-off inline styles weaken responsive usability. |
| 6. Experience Design | 1/4 | Decision metrics are misformatted, one source failure blanks whole pages, destructive actions lack safe feedback, and tables are client-only at scale. |

**Overall: 12/24**

---

## Top 3 UI-Only Priority Fixes

1. **Restore trustworthy decision support and independent source states** — Multiply ratio-based secure-score values by 100, aggregate or label subscription scope, derive SLA cards from named fields, and render each Defender/patch section with its own loading/error/empty/degraded state instead of gating the whole page.
2. **Make Defender-scale tables operable and responsive** — Use paginated envelope data where available, add search/sort and persistent filter context, set deliberate table minimum widths or mobile row layouts, and expose remediation/deep-link actions from alerts, attack paths, controls, and recommendations.
3. **Make risk-exception actions safe and accessible** — Replace undefined color variables with design tokens, label all search/checkbox controls, add explicit confirmation, announce success/failure, retain failed selections, and prevent bulk processing from silently continuing after an error.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

- **WARNING — Strong task framing is not consistent across pages.** The overview asks the operator a decision question and uses specific actions (`web/src/app/exposure/page.tsx:72-76`, `web/src/app/exposure/page.tsx:180-205`), while the patch and Defender pages fall back to generic “Loading”, “Error”, and “Failed to load … data” messages with no failed-source identity or recovery guidance (`web/src/app/exposure/patch-priorities/page.tsx:118-119`, `web/src/app/exposure/defender-posture/page.tsx:112-113`).
- **WARNING — “AUM” is unexplained operator jargon.** The queue description says “AUM patch” without expansion or contextual help (`web/src/app/exposure/patch-priorities/page.tsx:141-146`).
- **WARNING — Empty copy conflates different causes.** “No patches match the current filters” is used when the upstream collection itself is empty or when search/filters remove all rows (`web/src/app/exposure/patch-priorities/page.tsx:163-166`). This does not distinguish healthy-empty, filtered-empty, unavailable, or degraded.
- **WARNING — Table vocabulary contains a duplicate label.** Two adjacent columns are both titled “Priority”, although the first is a rank and the second is the priority identity/details (`web/src/app/exposure/patch-priorities/page.tsx:177-185`).
- **Positive evidence.** CVE/KB drilldowns explain loading and failure context and provide a return action (`web/src/app/exposure/cves/[id]/page.tsx:64-79`, `web/src/app/exposure/kbs/[id]/page.tsx:37-52`). Patch inventory also explains the governed handoff rather than implying direct execution (`web/src/components/exposure/PatchInventory.tsx:97-117`).

### Pillar 2: Visuals (2/4)

- **WARNING — Hierarchy is strongest only on overview and CVE detail.** The overview supplies headline metrics, a single best-action card, and summary links (`web/src/app/exposure/page.tsx:129-205`, `web/src/app/exposure/page.tsx:208-280`); CVE detail combines a risk gauge, impact metrics, evidence, and investigation sections (`web/src/app/exposure/cves/[id]/page.tsx:121-189`). This is a credible decision hierarchy.
- **WARNING — Defender posture becomes an unranked vertical inventory.** Alerts, attack paths, controls, recommendations, and images are rendered as consecutive peer sections without in-page navigation, prioritization, or a “next action” focal point (`web/src/app/exposure/defender-posture/page.tsx:160-423`). `needs_human_review: true` for density and scan-path validation with authenticated production data.
- **WARNING — The overview contradicts its own “lean summary” model.** The component comment says detail pages own full tables (`web/src/app/exposure/page.tsx:17-22`), but the full `PatchInventory` is appended to the overview (`web/src/app/exposure/page.tsx:282`). This duplicates patch workflow content and weakens the landing-page focal point.
- **WARNING — Detail navigation has no selected parent view.** Only `/exposure`, `/defender-posture`, and `/patch-priorities` can become active (`web/src/app/exposure/layout.tsx:6-10`, `web/src/app/exposure/layout.tsx:20-27`); `/cves/[id]` and `/kbs/[id]` therefore show no active tab. Their breadcrumbs return only to Exposure, not the originating Patch priorities context (`web/src/app/exposure/cves/[id]/page.tsx:115-120`, `web/src/app/exposure/kbs/[id]/page.tsx:60-65`).
- **WARNING — Every card receives hover lift, including noninteractive content.** The global card hover treatment changes border, shadow, and position (`web/src/app/globals.css:882-895`), which can imply clickability on static metric/detail cards. `needs_human_review: true` for perceived affordance.

### Pillar 3: Color (2/4)

- **BLOCKER — The bulk revoke action references an undefined color token.** The button uses `var(--danger-color)` and white text (`web/src/app/exposure/patch-priorities/page.tsx:371-385`), but the defined critical token is `--color-critical` (`web/src/app/globals.css:14-15`). Because `--danger-color` has no fallback or definition, the background declaration is invalid and white text can become illegible on the white card.
- **WARNING — Several borders also reference an undefined token.** Search, recommendation rows, image rows, and risk-exception rows use `var(--border-color)` (`web/src/app/exposure/patch-priorities/page.tsx:154-160`, `web/src/app/exposure/patch-priorities/page.tsx:389-412`, `web/src/app/exposure/defender-posture/page.tsx:313-321`, `web/src/app/exposure/defender-posture/page.tsx:367-376`), while the design token is `--color-border` (`web/src/app/globals.css:9-10`). The intended separators therefore do not render.
- **WARNING — Muted operational text fails WCAG AA normal-text contrast.** `--color-text-muted` is `#778290` (`web/src/app/globals.css:8`), measuring approximately **3.90:1** on white and **3.74:1** on the subtle surface. It is used at 10–12px in table headers, secondary rows, pagination, and breadcrumbs (`web/src/app/globals.css:1571-1580`, `web/src/app/globals.css:1609-1619`, `web/src/app/globals.css:1781-1813`, `web/src/app/globals.css:1845-1855`), below the 4.5:1 threshold.
- **WARNING — Semantic colors are sometimes optimistic rather than evidentiary.** Any available “Highest-value patch” is assigned success green (`web/src/app/exposure/page.tsx:148-157`), and every risk-reduction bar is green regardless of score (`web/src/app/globals.css:3413-3426`). Availability and magnitude should not automatically communicate successful posture.
- **Positive evidence.** Core brand/status tokens are centralized (`web/src/app/globals.css:1-23`), and status pills pair color with text labels and dots (`web/src/components/ui/StatusBadge.tsx:9-16`).

### Pillar 4: Typography (2/4)

- **WARNING — Dense tables depend on undersized text.** Table headers are 10px, secondary text is 11px, compact status badges are 10px, and pagination is 11px (`web/src/app/globals.css:1571-1619`, `web/src/app/globals.css:1176-1180`, `web/src/app/globals.css:1781-1826`). This is especially risky when combined with the muted-color contrast failure.
- **WARNING — The scale is fragmented.** Exposure-relevant styles use 10, 11, 12, 13, 14, 15, 17, 18, 20, 30, and responsive/clamped heading sizes, plus weights 500, 600, 650, and 700 (`web/src/app/globals.css:252-267`, `web/src/app/globals.css:823-855`, `web/src/app/globals.css:1127-1180`, `web/src/app/exposure/defender-posture/page.tsx:313-321`). This exceeds a restrained operational type scale and makes inline-styled sections visibly less consistent.
- **WARNING — Raw identifiers can dominate or collapse unpredictably.** Metric values use 30px with `overflow-wrap:anywhere` (`web/src/app/globals.css:1133-1139`), while long CVSS strings and table values are forced to break (`web/src/app/globals.css:3537-3543`, `web/src/app/globals.css:1582-1588`). `needs_human_review: true` for real KB/CVE/resource-ID wrapping at desktop, tablet, and mobile widths.
- **Positive evidence.** The Segoe UI stack, 14px body, and 1.45 line height are appropriate for the Azure context (`web/src/app/globals.css:218-223`), and heading levels are consistently structured through shared `PageHeader` and cards (`web/src/components/ui/PageHeader.tsx:11-26`).

### Pillar 5: Spacing (2/4)

- **WARNING — Core page and card spacing is coherent.** The page uses a bounded 1440px canvas and responsive padding (`web/src/app/globals.css:29-32`, `web/src/app/globals.css:592-599`, `web/src/app/globals.css:5222-5228`); cards, metrics, and grids consistently use roughly 12–22px rhythm (`web/src/app/globals.css:897-921`, `web/src/app/globals.css:1066-1079`).
- **WARNING — High-column tables have no deliberate responsive width.** `.operations-table` is only `width:100%` and has no `min-width` (`web/src/app/globals.css:1559-1588`). Six- to eight-column Exposure tables (`web/src/components/exposure/PatchInventory.tsx:131-140`, `web/src/app/exposure/cves/[id]/page.tsx:372-384`) can therefore compress into narrow wrapped columns instead of producing a predictable horizontal workspace. `needs_human_review: true` at 375×812 and 768×1024 with authenticated data.
- **WARNING — Important controls are visually cramped.** Open-row links are 28×28px and pagination controls are 26px high (`web/src/app/globals.css:1629-1638`, `web/src/app/globals.css:1805-1831`), substantially below the preferred 44px touch target for mobile operational use.
- **WARNING — One-off inline spacing bypasses the shared rhythm.** Patch search, remediation link, bulk action/table, and Defender detail rows hardcode `0.5rem`, `0.75rem`, `1rem`, and 4px radii (`web/src/app/exposure/patch-priorities/page.tsx:149-160`, `web/src/app/exposure/patch-priorities/page.tsx:250-255`, `web/src/app/exposure/patch-priorities/page.tsx:371-431`, `web/src/app/exposure/defender-posture/page.tsx:313-321`).
- **Positive evidence.** Mobile rules collapse page headers, metrics, CVE summary grids, and the best-action card (`web/src/app/globals.css:5067-5088`, `web/src/app/globals.css:5226-5236`, `web/src/app/globals.css:5381-5396`).

### Pillar 6: Experience Design (1/4)

- **BLOCKER — Defender secure-score values are materially misrepresented.** The fixture establishes ratio values such as `0.5`, `0.75`, and `0.25` (`web/src/app/exposure/page.test.tsx:136-149`, `web/src/app/exposure/page.test.tsx:188-198`), but the UI appends `%` without multiplying by 100 and only displays the first subscription (`web/src/app/exposure/defender-posture/page.tsx:123-130`). Controls likewise render `0.25` as `0%` after `toFixed(0)` (`web/src/app/exposure/defender-posture/page.tsx:274-281`). Operators can make prioritization decisions from values off by 100×.
- **BLOCKER — A single slow or failed source suppresses otherwise usable page content.** Patch priorities waits for all four sources and shows one generic error if any fails (`web/src/app/exposure/patch-priorities/page.tsx:31-47`, `web/src/app/exposure/patch-priorities/page.tsx:118-121`). Defender does the same across six sources (`web/src/app/exposure/defender-posture/page.tsx:37-57`, `web/src/app/exposure/defender-posture/page.tsx:112-115`). This violates partial-degradation expectations and makes a nonessential source failure block task completion.
- **BLOCKER — Risk-exception revocation is unsafe and failures are invisible.** Individual failures are only logged to the console (`web/src/app/exposure/patch-priorities/page.tsx:86-99`); bulk revoke proceeds sequentially with no confirmation, success state, visible failure, or aggregate result (`web/src/app/exposure/patch-priorities/page.tsx:103-109`, `web/src/app/exposure/patch-priorities/page.tsx:363-387`). The select-all and row checkboxes also have no accessible names (`web/src/app/exposure/patch-priorities/page.tsx:393-428`).
- **WARNING — Search is inaccessible by name.** The patch search relies on placeholder text and has no `<label>` or `aria-label` (`web/src/app/exposure/patch-priorities/page.tsx:148-161`).
- **WARNING — The tab pattern is incomplete.** Links are assigned `role="tab"` and inactive links are removed from sequential focus (`web/src/app/exposure/layout.tsx:18-30`), but there are no associated tabpanels, IDs, `aria-controls`, or arrow-key behavior. Use ordinary navigation semantics or implement the complete ARIA Tabs pattern.
- **WARNING — Empty and degraded states disappear silently.** Defender sections render only when row counts exceed zero, so healthy-empty categories have no explanatory state (`web/src/app/exposure/defender-posture/page.tsx:160-161`, `web/src/app/exposure/defender-posture/page.tsx:217-218`, `web/src/app/exposure/defender-posture/page.tsx:258-259`, `web/src/app/exposure/defender-posture/page.tsx:298-299`, `web/src/app/exposure/defender-posture/page.tsx:352-353`). CVE attack-path loading/errors are also ignored once the main detail loads (`web/src/app/exposure/cves/[id]/page.tsx:43-46`, `web/src/app/exposure/cves/[id]/page.tsx:335-357`).
- **WARNING — Defender findings stop short of remediation.** Alert remediation steps and attack-path manual remediation steps exist in the data shape but are not surfaced in the tables; Defender sections provide no governed-remediation or resource deep links (`web/src/app/exposure/defender-posture/page.tsx:160-255`). Recommendations show prose only (`web/src/app/exposure/defender-posture/page.tsx:298-349`). Patch and CVE/KB pages, by contrast, expose remediation actions (`web/src/app/exposure/patch-priorities/page.tsx:250-264`, `web/src/app/exposure/cves/[id]/page.tsx:125-138`, `web/src/app/exposure/kbs/[id]/page.tsx:66-79`).
- **WARNING — Pagination is client-side after full collection fetch.** Defender calls request whole collections (`web/src/app/exposure/defender-posture/page.tsx:30-35`), filters scan all rows, and pagination slices arrays already in memory (`web/src/lib/table-column-filters.ts:44-78`, `web/src/lib/use-table-pagination.ts:28-46`). This does not provide Defender-scale loading, sorting, or stable server-side navigation.
- **WARNING — Secondary-source failure is hidden in PatchInventory.** Runs are loaded alongside targets, but only target loading/error is handled; a failed run request silently removes historical runs (`web/src/components/exposure/PatchInventory.tsx:48-50`, `web/src/components/exposure/PatchInventory.tsx:88-95`, `web/src/components/exposure/PatchInventory.tsx:238-258`).
- **WARNING — Motion reduction is incomplete.** Global cards and critical metrics animate (`web/src/app/globals.css:882-895`, `web/src/app/globals.css:1093-1117`), while the reduced-motion rule only targets `.inventory-page` descendants (`web/src/app/globals.css:6125-6134`).
- **Positive evidence.** Shared focus-visible outlines are present (`web/src/app/globals.css:270-277`), status badges use text as well as color (`web/src/components/ui/StatusBadge.tsx:9-16`), table filters are labeled (`web/src/components/ui/TableColumnFilters.tsx:33-50`), pagination exposes range and disabled states (`web/src/components/ui/TablePagination.tsx:71-140`), and CVE risk acceptance requires a reason with visible in-form errors (`web/src/app/exposure/cves/[id]/page.tsx:86-109`, `web/src/app/exposure/cves/[id]/page.tsx:208-236`).

---

## Authenticated Human Validation Queue

- `needs_human_review: true` — Verify hierarchy and scan path with real Defender alert/recommendation/image volumes.
- `needs_human_review: true` — Verify 375×812, 768×1024, and 1440×900 behavior, especially six- to eight-column tables, long ARM IDs, CVSS vectors, and header actions.
- `needs_human_review: true` — Verify keyboard focus order, link/tab semantics, horizontal-scroll discoverability, sticky context, and screen-reader announcements after organizational sign-in.
- `needs_human_review: true` — Verify color/hover affordances and compact text readability in both supported themes, if more than the audited light token set is available.

No authenticated live-data visual observation is claimed in this report.

---

## UI Concerns for the Final Five Cross-Layer Recommendations

The final cross-layer set should account for three UI-driven contract needs: **(1)** explicit units/aggregation semantics for scores and SLA metrics, **(2)** paginated, searchable, sortable collection contracts with per-source freshness/degradation metadata, and **(3)** governed remediation handoffs that preserve scope/origin context and return auditable success/failure outcomes. These are cross-layer implications from the UI audit, not a backend implementation review.

---

## Verification

- `cd web && npx tsc --noEmit` — passed.
- `cd web && npx vitest run src/app/exposure/page.test.tsx src/components/exposure/PatchInventory.test.tsx src/components/ui/TablePagination.test.tsx` — 18 tests passed.
- No focused tests exist in the audited set for Defender posture, patch priorities, CVE detail, KB detail, Exposure navigation semantics, destructive-action confirmation, responsive behavior, or accessibility.

---

## Files Audited

- `web/src/app/exposure/layout.tsx`
- `web/src/app/exposure/page.tsx`
- `web/src/app/exposure/page.test.tsx`
- `web/src/app/exposure/patch-priorities/page.tsx`
- `web/src/app/exposure/defender-posture/page.tsx`
- `web/src/app/exposure/cves/[id]/page.tsx`
- `web/src/app/exposure/kbs/[id]/page.tsx`
- `web/src/components/exposure/PatchInventory.tsx`
- `web/src/components/exposure/PatchInventory.test.tsx`
- `web/src/components/ui/TableColumnFilters.tsx`
- `web/src/components/ui/TablePagination.tsx`
- `web/src/components/ui/TablePagination.test.tsx`
- `web/src/components/ui/PageHeader.tsx`
- `web/src/components/ui/StatePanel.tsx`
- `web/src/components/ui/MetricCard.tsx`
- `web/src/components/ui/StatusBadge.tsx`
- `web/src/hooks/useApi.ts`
- `web/src/lib/table-column-filters.ts`
- `web/src/lib/use-table-pagination.ts`
- `web/src/lib/types.ts`
- `web/src/app/globals.css`

Registry audit skipped: `components.json` is not present.
