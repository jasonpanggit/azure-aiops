# Phase 3 — UI Review

**Audited:** 2026-09-02  
**Baseline:** Phase 1 UI design contract (`.planning/phases/01-evidence-and-situation-foundation/01-UI-SPEC.md`) plus Phase 3 plans, summaries, UAT, and verification  
**Screenshots:** not captured — no local dev server at ports 3000, 5173, or 8080

Live validation at the deployed URL showed that the `/remediation` page shell loads (HTTP 200). Remediation, patching, and vulnerability API calls were observed returning `503 provider_unavailable`/loading, while network endpoints returned HTTP 200. This is distinguished below from UI design defects: provider availability prevents populated live validation, but it does not by itself reduce visual-contract scores.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|---|---:|---|
| 1. Copywriting | 2/4 | Strong governed-execution language, but stale Phase 2 “execution unavailable” copy remains user-visible. |
| 2. Visuals | 2/4 | Clear two-column review/preview structure, but the page is an unusually dense, long mixed backlog rather than a focused execution workspace. |
| 3. Color | 3/4 | Uses the contract’s tokens and semantic tones; some status/eligibility emphasis is visually repetitive. |
| 4. Typography | 2/4 | Global heading sizes/weights and local risk typography exceed the declared Phase 1 type contract. |
| 5. Spacing | 2/4 | Page-level CSS uses many off-scale values (18, 17/19, 14, 12, 10, 6px). |
| 6. Experience Design | 2/4 | Excellent tested lifecycle mechanics, but degraded provider states are not sufficiently differentiated and the live flow cannot reach data. |

**Overall: 13/24**

---

## Top 3 Priority Fixes

1. **Remove stale Phase 2 boundary messaging** — users can be told execution is unavailable after being shown an execution workspace — replace `page.tsx:617` and `:921` with current Phase 3 language and explicit provider-unavailable wording.
2. **Make provider degradation panel-specific and actionable** — live 503s currently leave users with generic loading/unavailable states — render a distinct `provider_unavailable` state per source with retry, last-known timestamp, and preserved network results.
3. **Normalize page geometry and type to the contract** — dense off-scale spacing and non-contract typography reduce scanability — refactor remediation CSS to the 4px scale and 14/12/18/28px, 400/600 type roles.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)

- **WARNING:** `web/src/app/remediation/page.tsx:617` sets the Copilot/evidence snapshot boundary to “Phase 2 records approval decisions only; Azure execution, rollback, and realized-outcome capture remain unavailable.” This contradicts the Phase 3 implementation and UAT contract, which explicitly adds execution, verification, rollback guidance, and outcome capture.
- **WARNING:** `page.tsx:921` repeats that Azure execution and realized-outcome validation remain unavailable for Defender cases. The page is now a Phase 3 surface; this copy should say the case is recommendation-only because it is not a supported executable action, not that the capability is globally unavailable.
- **WARNING:** `page.tsx:867` uses the generic empty state “No remediation backlog / No governed remediation candidates exist in this scope.” It does not distinguish no candidates from unavailable providers, contrary to the Phase 1 requirement to never make missing data look like an all-clear.
- **POSITIVE:** `page.tsx:677`, `:1015`, `:1094-1095`, and `:1128-1144` use specific approval-bound, verified-state, and no-automatic-rollback language. CTA labels are descriptive (“Review and execute”, “Confirm execution”, “Retry execution”).

### Pillar 2: Visuals (2/4)

- **WARNING:** `page.tsx:672-1183` combines six-source backlog aggregation, a patch inventory, filters, a long selected-detail column, approval form, preview, and execution history into one very long surface. The focal task—review one exact operation, approve it, execute, observe—is visually diluted by seeded lifecycle/identity/incident rows and unrelated source categories.
- **WARNING:** `page.tsx:846-865` makes every backlog item an `article` with a separate “Review” button, but the selected row itself is not a keyboard-selectable control. This adds interaction friction and weakens the selected-state relationship for keyboard users.
- **WARNING:** `page.tsx:1145-1159` renders immutable history as nested paragraphs/lists without a compact timeline/table treatment. Long provider IDs, timestamps, and failure details can dominate the execution panel and make audit comparison difficult.
- **POSITIVE:** The page has an explicit focal hierarchy after selection: “Business-impact evidence” then “Exact approved operation”, followed by confirmation and durable outcome (`page.tsx:1062-1135`).

### Pillar 3: Color (3/4)

- **POSITIVE:** `globals.css:1-23` defines the Phase 1 canvas/surface/brand and semantic tokens, and remediation uses semantic component tones (`page.tsx:798-812`, `:1050-1053`, `:1123-1126`) rather than introducing hardcoded page colors.
- **WARNING:** `globals.css:3625-3627` uses a blue inset selection bar plus `--color-brand-subtle`; combined with blue links, info badges, and action buttons, selection/action emphasis is frequent. Keep the accent reserved for the selected row, primary CTA, links, and focus as the contract specifies.
- **WARNING:** `page.tsx:928-931` presents projected risk reduction in success green even when it is a simulation estimate. Pairing a projected metric with success treatment can imply an achieved outcome; use a neutral/projected treatment and reserve success for verified provider state.
- **WARNING:** Status semantics are partly text-based, which is good, but `page.tsx:1123-1126` gives all non-success/non-terminal states the same warning tone. Distinguish queued/running/retrying visually while retaining text.

### Pillar 4: Typography (2/4)

- **WARNING:** The contract declares body 14/400, label 12/600, heading 18/600, display 28/600. `globals.css:252-260` uses 28px/650 and 18px/650, and `globals.css:3672-3675` adds a 24px risk number. These are close but not contract-compliant new-surface roles.
- **WARNING:** The CSS contains broad legacy typography beyond the four declared sizes (for example `globals.css:37`, `:118`, `:189`, and `:3588` use 18/15/13/11px). While much is shared legacy styling, the remediation surface inherits it without a scoped type reset.
- **POSITIVE:** The body stack is the required Segoe UI system stack (`globals.css:218-223`), and IDs/provider references use `<code>` in key execution locations (`page.tsx:1075`, `:1129`).

### Pillar 5: Spacing (2/4)

- **WARNING:** New remediation layout values do not follow the declared 4px scale: `globals.css:3594` (18px), `:3600` (18px), `:3611`/`:3739` (16px is valid), `:3621` (17px/19px), `:3638` (20px), `:3643`/`:3715` (4/10px), `:3650` (6px), `:3704`/`:3744` (12px), and `:3725` (12px). Replace 18 with 16/20, 17/19 with 16/20, 10/6 with 8/4, and use 24/32px for major section separation.
- **WARNING:** `page.tsx:735` uses inline layout styling (`justifyContent: "space-between"`, `alignItems: "center"`), which makes the page-level geometry harder to audit and maintain in the shared CSS/token system.
- **POSITIVE:** The major grids use coherent columns and collapse at `globals.css:5115-5123`, and controls have 38px minimum height, close to the contract’s pointer-target intent.

### Pillar 6: Experience Design (2/4)

- **POSITIVE:** The Phase 3 interaction logic is substantially covered: server-owned eligibility, preview-before-execute, confirmation, bounded polling/cleanup, retry/cancel gating, verified terminal states, failure details, rollback guidance, and immutable attempts are implemented at `page.tsx:428-527` and `:1081-1174`. The focused UI suite passed, and the Phase 3 summary reports 32 focused tests passing.
- **WARNING:** `page.tsx:620-628` converts API failures into a generic source warning and only promotes an error to `pageError` when the backlog is empty. With live remediation/patching/vulnerability providers returning `503 provider_unavailable`, the user can see persistent loading or a mixed partial page without a clear per-provider recovery action. This is a provider-availability/observability gap, not proof that the CSS or interaction model is broken.
- **WARNING:** `page.tsx:831-832` uses one generic loading panel for the fan-out. The Phase 1 contract requires retaining the heading/scope and identifying partial provider failures; provider-specific loading and degraded states should replace the single undifferentiated message.
- **WARNING:** `page.tsx:867` presents “No remediation backlog” when the composed backlog is empty, despite seeded rows normally masking emptiness. If all providers are unavailable or a legitimate scoped empty result occurs, the copy and next action do not distinguish those states.
- **WARNING:** `page.tsx:1030` uses `input type="date"` for expiry, with no visible timezone/absolute-time guidance. Approval expiry is a safety boundary; use an explicit date-time control or clearly state the timezone and server interpretation.
- **BLOCKER (live task completion):** Live UAT could load the deployed shell but could not populate remediation/patching/vulnerability data because those APIs returned `503 provider_unavailable/loading`; network endpoints returned 200. This blocks validation and execution at that deployment/provider state. It is not a UI design defect: resolve provider readiness/configuration separately, then re-run the authenticated preview → approval → execute → observe flow. The Phase 3 UAT also intentionally deferred mutating execution.

---

## Files Audited

- `.github/agents/gsd-ui-auditor.agent.md`
- `.planning/STATE.md`
- `.planning/phases/01-evidence-and-situation-foundation/01-UI-SPEC.md`
- `.planning/phases/03-safe-remediation-execution/03-CONTEXT.md`
- `.planning/phases/03-safe-remediation-execution/03-UAT.md`
- `.planning/phases/03-safe-remediation-execution/03-VERIFICATION.md`
- `.planning/phases/03-safe-remediation-execution/03-01-PLAN.md`, `03-01-SUMMARY.md`
- `.planning/phases/03-safe-remediation-execution/03-02-PLAN.md`, `03-02-SUMMARY.md`
- `.planning/phases/03-safe-remediation-execution/03-03-PLAN.md`, `03-03-SUMMARY.md`
- `.planning/phases/03-safe-remediation-execution/03-04-PLAN.md`, `03-04-SUMMARY.md`
- `.planning/phases/03-safe-remediation-execution/03-05-PLAN.md`, `03-05-SUMMARY.md`
- `.planning/phases/03-safe-remediation-execution/03-06-PLAN.md`, `03-06-SUMMARY.md`
- `web/src/app/remediation/page.tsx`
- `web/src/app/remediation/page.test.tsx`
- `web/src/app/globals.css`

