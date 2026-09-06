---
phase: 12-network-topology-integrity-and-scale
reviewed: 2026-09-06T15:42:29+08:00
status: changes_requested
baseline: 12-UI-SPEC.md
repository_head: b80b780a8a1f5a8d2e7f1d3e69023a0be5fb71cc
verified_source_head: 811883f3cca26470568fbd138c3883c5afb6a8c9
source_matches_verified_head: true
screenshots: existing_a39_inspected_no_new_capture
score: 16/24
weighted_score: 62.5/100
blockers: 0
warnings: 8
---

# Phase 12 — UI Review

**Audited:** 2026-09-06  
**Baseline:** approved `12-UI-SPEC.md` design contract  
**Verdict:** **CHANGES REQUESTED — no blocker, eight contract warnings**  
**Source audited:** current Network UI is byte-identical to source HEAD `811883f3` even though repository HEAD is the later documentation-only `b80b780a`  
**Screenshots:** no new capture because no server answered on ports 3000, 5173, or 8080; existing `12-11-A39-360px.png` inspected

The implementation is functionally substantial: honest totals, summary/full detail, bounded badge loading, five drawer findings states, policy authoring, provenance-rich exports, and the primary keyboard paths are all present and tested. It does not fully satisfy the visual contract, however. The tablet collapse point is wrong, private-link legend copy has drifted, and explicit focus/reduced-motion requirements are missing.

---

## Pillar Scores

| Pillar | Weight | Score | Weighted | Key finding |
|---|---:|---:|---:|---|
| 1. Copywriting | 10% | 3/4 | 7.5 | Operational copy is generally exact, but the policy empty state omits its next step and preview truncation is silent. |
| 2. Visuals | 20% | 2/4 | 10.0 | The hierarchy is strong, but the tablet composition violates the ≤900px contract and the current legend no longer identifies private-link candidates. |
| 3. Color | 15% | 3/4 | 11.25 | The approved palette is preserved, but the low-contrast private-link treatment has lost its required legend reinforcement and status vocabulary is incomplete. |
| 4. Typography | 10% | 3/4 | 7.5 | Sizes remain coherent, but new policy-form labels inherit a disallowed 600 weight. |
| 5. Spacing | 15% | 3/4 | 11.25 | Phase-added spacing uses the declared scale and 360px wraps, but the drawer/canvas stack activates at 560px rather than 900px. |
| 6. Experience Design | 30% | 2/4 | 15.0 | State coverage is excellent, but drawer focus is not restored, canvas animation ignores reduced-motion, and the policy form can expose two assertive alerts. |

**Overall: 16/24**  
**Weighted overall: 62.5/100**

Weighting emphasizes the primary visual workspace and interaction/accessibility behavior: Copy 10%, Visuals 20%, Color 15%, Typography 10%, Spacing 15%, Experience Design 30%.

---

## Flags and Blockers

### Blockers

None. The tested task flows remain completable, and no reviewed defect prevents loading, inspecting, filtering, drilling into, editing, or exporting network topology.

### Warnings

| ID | Pillar | Finding |
|---|---|---|
| W-UI-01 | Visuals / Spacing | The contracted column layout at ≤900px is implemented only at ≤560px. |
| W-UI-02 | Visuals / Color | The current legend says `Resource`, not the required `Private link candidate`; the retained A39 image shows different copy than current source. |
| W-UI-03 | Experience | Closing the drawer does not return focus to the topology canvas. |
| W-UI-04 | Experience | The Cytoscape `Fit` action always animates for 200ms and does not honor reduced-motion. |
| W-UI-05 | Experience | Policy validation can render `addError` and `semanticError` as simultaneous assertive regions. |
| W-UI-06 | Copywriting | The policy empty state omits “Add a rule to start checking for gaps.” |
| W-UI-07 | Copywriting | Preview renders only the first five gaps without the contracted “and N more” disclosure. |
| W-UI-08 | Typography / Color consistency | New form labels inherit 600 weight, and `statusTone()` lacks the Phase-12 additive state mappings. |

---

## Top 3 Priority Fixes

1. **Restore the responsive contract at 900px** — at tablet widths the 340px drawer remains beside the canvas, compressing the primary graph instead of becoming the specified full-width, internally scrolling drawer. Move the `.topology-stage`, `.topology-canvas-wrap`, and `.topology-drawer` rules currently under `@media (max-width: 560px)` to the existing ≤900px responsive path, then capture 768×1024 evidence.
2. **Complete the accessibility lifecycle** — retain a reference to the canvas, return focus there after drawer close or selection clearing, and replace the unconditional Cytoscape `animate(... duration: 200)` path with an immediate `fit()` when `prefers-reduced-motion: reduce` matches. Add browser-level focus and motion tests.
3. **Reconcile labels, state vocabulary, and evidence** — restore the exact `Private link candidate` legend entry, implement the declared `statusTone()` keyword mappings, complete the two missing policy-copy strings, and regenerate A39 evidence from the actual route so screenshot text cannot diverge from source.

---

## Contract Coverage

| Requested behavior | Result | Evidence |
|---|---|---|
| Loading, empty, populated, partial, and unavailable page states | **PASS** | `page.tsx:239-330`, `page.tsx:846-902`; isolated Retry tests in `page.test.tsx` and honest-total tests at `page.test.tsx:195-293`. |
| Summary / Full detail control | **PASS** | Explicit `detail=summary` default in `page.tsx:51-59`; pressed-button group and 1,500-node guard in `TopologyWorkspace.tsx:651-670, 733-759`; tests at `TopologyWorkspace.test.tsx:110-186`. |
| Coverage disclosures | **PASS** | Page disclosure in `page.tsx:268-285`; badge disclosure and complete footnote in `TopologyWorkspace.tsx:761-867`; server-pagination and badge-budget tests pass. |
| Five drawer findings states | **PASS** | Findings present, confirmed clean, incomplete, unavailable, and loading are explicit in `TopologyDetailDrawer.tsx:281-384`; tests at `TopologyDetailDrawer.test.tsx:84-157`. |
| Policy form and mutation refresh | **PASS WITH COPY/A11Y WARNINGS** | Free-form rule ID, server vocabulary, JSON assertion, preview, save, two-step delete, and refetch are present in `page.tsx:913-1349`; relevant tests pass at `page.test.tsx:580-897`. |
| Control and affected-resource badges | **PASS** | Case-folded fan-out and role-aware titles in `TopologyWorkspace.tsx:64-148`; tests at `TopologyWorkspace.test.tsx:226-295`. |
| JSON / PNG exports | **PASS** | Ten-key provenance envelope and timestamped filenames in `TopologyGraph.tsx:300-412`; tests at `TopologyGraph.test.tsx:178-303`. |
| Keyboard semantics | **PARTIAL** | New controls, pagers, Retry actions, two-step delete, and drawer-first Escape are tested. Drawer-close focus restoration and direct keyboard operation of the canvas remain absent. The latter was explicitly accepted as a pre-existing non-actionable limitation in `12-REVIEW-FIX.md`; the former is an unmet UI-SPEC requirement. |
| 360px no-overflow | **PASS, evidence-limited** | A39 is 360×1462 and shows wrapped toolbar, callout, drawer, ARM ID, and footnote. `12-11-SUMMARY.md` records 360/360 document and 322/322 drawer geometry. No current live server was available for independent recapture. |
| Unknown and provenance copy | **PASS** | Unconditional `Graph Unknown` guard in `EvidenceBar.tsx:15-20, 50`; three-state flow copy in `page.tsx:904-912`; long-form freshness and peer-resolution copy are tested. |

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**What works**

- Page-level failure copy clearly distinguishes unavailable data from clean data and supplies uniquely named Retry actions.
- The three flow-log provenance strings match the contract exactly (`page.tsx:904-912`).
- Freshness unknowns, incomplete coverage, drawer uncertainty, private-link scope, and peer provenance use direct operator-facing language.
- Destructive policy deletion changes both visible and accessible labels before the second activation.

**WARNING — policy empty state loses the prescribed next action.**  
`web/src/app/network/page.tsx:1298-1301` renders only “No design rules are configured for this estate.” The contract also requires “Add a rule to start checking for gaps.” Without that sentence, the empty state explains the condition but not the recovery.

**WARNING — preview truncation is silent.**  
`web/src/app/network/page.tsx:1285-1294` renders `preview.gaps.slice(0, 5)` but never appends the contracted “and {n−5} more.” For six or more preview gaps, the list is bounded with no disclosure.

**Remediation**

- Change the policy empty message to the exact two-sentence contract copy.
- When `preview.gaps.length > 5`, append a visible count such as `and ${preview.gaps.length - 5} more`.

### Pillar 2: Visuals (2/4)

**What works**

- The page retains the intended hierarchy: header/evidence, four metrics, qualification callouts, five tabs, then the topology as the primary visual anchor.
- Summary/full, filter toggles, exports, graph, drawer, and honesty footnote are visually grouped in a consistent workspace.
- The existing A39 artifact shows readable wrapping at 360px and no visible horizontal clipping.

**WARNING — tablet composition violates the design contract.**  
The UI-SPEC requires the canvas and drawer to stack at ≤900px. The actual stack rules appear under `@media (max-width: 560px)` (`globals.css:5270,5382-5397`). Between 561px and 900px the 340px fixed drawer (`globals.css:2964-2973`) remains beside the canvas, leaving an unnecessarily narrow graph.

**WARNING — the private-link legend entry is missing.**  
The current toolbar renders `Resource` at `TopologyWorkspace.tsx:693-699`, while C-3 requires `Private link candidate`. This matters because private-link workloads otherwise rely on a subtle dashed treatment. The A39 image itself shows `Private link candidate`, so the retained visual evidence does not match current source and cannot prove the current legend.

**Remediation**

- Apply the stage-column and full-width drawer rules at ≤900px, preserving the 420px canvas and 340px drawer cap.
- Replace or supplement the generic `Resource` legend item with the exact private-link candidate label and style.
- Re-capture desktop, tablet, and mobile screenshots from the real `/network` route.

### Pillar 3: Color (3/4)

**What works**

- Phase 12 adds no color literal to the CSS or Cytoscape stylesheet; the phase CSS diff contains only layout/wrapping declarations.
- The existing canvas palette and seven `StatusTone` values remain intact.
- Severity is reinforced with text in badges and the drawer rather than relying only on color.

**WARNING — the low-contrast private-link treatment lost its required reinforcement.**  
The contract records the dashed `#8a97a6` border on `#eef2f7` as approximately 2.4:1 and therefore relies on a legend and drawer text. Drawer text exists, but the current legend labels the swatch `Resource`, not `Private link candidate` (`TopologyWorkspace.tsx:696`; `globals.css:2751-2753`).

**WARNING — declared state keywords are not mapped.**  
`web/src/components/ui/StatusBadge.tsx:20-29` does not add the Phase-12 mappings for `complete`, `partial`, `not-analyzed`, `private-link-candidate`, `public-access-enabled`, `peer-not-ingested`, or `peer-out-of-scope`. Current call sites often pass explicit tones, so this is not presently task-breaking, but the shared status contract is incomplete.

**Remediation**

- Restore the explicit private-link legend label.
- Add the contract’s state keywords to `statusTone()` without changing existing mappings or adding an eighth tone.

### Pillar 4: Typography (3/4)

**What works**

- The page maintains the Segoe UI system stack and the established 10/11/12/13px dense-workbench scale.
- No inline `fontSize` or `fontWeight` declarations appear in the Network page/components.
- Drawer labels, headings, badges, controls, and the audit footnote preserve clear role differentiation.

**WARNING — newly introduced policy labels render at a non-contracted weight.**  
`globals.css:3303-3310` applies `font-weight: 600` to `.policy-add-form label`, so Phase-12 strings such as “Rule assertion (JSON)” inherit 600. The UI-SPEC allows inherited 600 only for the existing status badge and segmented-control active option; new form strings were required to use 400 or 700.

**Remediation**

- Override Phase-12 policy form labels to 700 if emphasis is needed, or 400 for normal labels. Do not introduce another weight.

### Pillar 5: Spacing (3/4)

**What works**

- The only Phase-12 CSS addition uses the declared 8px token (`.topology-coverage`) and the two responsive overflow fixes add no off-scale spacing.
- Existing 6/9/10/14px exceptions remain inherited rather than duplicated.
- A39 demonstrates successful wrapping at the 360px floor, including a long ARM ID and dense 14-item footnote.

**WARNING — responsive spacing behavior begins too late.**  
The contract assigns the compact stacked drawer/canvas composition to ≤900px, but current CSS defers it to ≤560px (`globals.css:5270,5382-5397`). This is a layout-density defect at common 768px tablet widths even though the 360px floor passes.

**Remediation**

- Move only the topology stage/canvas/drawer responsive declarations to the existing ≤900px media block; retain all declared dimensions and spacing values.

### Pillar 6: Experience Design (2/4)

**What works**

- All five drawer states are explicit and mutually distinguishable.
- Retry controls have stable, unique accessible names and refetch only their owner.
- Summary/full detail, the >1,500-node confirmation, on-demand detail, pagination, badge budget, and partial exports all disclose their consequences.
- Policy authoring keeps semantic validation server-owned and preserves form input after failures.
- Unknown freshness and peer provenance never default to false certainty.

**WARNING — focus is not restored after drawer close.**  
The drawer moves focus to its close button on selection (`TopologyDetailDrawer.tsx:86-98`), but `onClose` only clears selection (`TopologyWorkspace.tsx:370`) and the canvas is a non-focusable `role="application"` element (`TopologyGraph.tsx:637-642`). The explicit requirement to return focus to the canvas is therefore not implemented.

**WARNING — reduced-motion is not honored by the graph controls.**  
`TopologyGraph.tsx:616-618` always runs a 200ms Cytoscape animation for Fit. The only `prefers-reduced-motion` block in `globals.css:6147-6165` targets Inventory-page CSS and cannot disable this JavaScript animation.

**WARNING — more than one assertive validation region can coexist.**  
The policy form renders `addError` and `semanticError` in separate `role="alert"` elements (`page.tsx:1171-1175,1252-1256`). Some validation branches set one without clearing the other (`page.tsx:1013-1022`), so the contract’s “exactly one assertive region may be active at a time” rule is not guaranteed.

**Accepted limitation, not a new remediation item:** direct keyboard navigation and selection of Cytoscape nodes is still absent. `12-REVIEW-FIX.md` explicitly adjudicated the full canvas keyboard model as pre-existing/out of Phase-12 scope. All controls added by Phase 12 are keyboard-reachable, and every canvas-only status has a DOM-text equivalent.

**Remediation**

- Make the canvas programmatically focusable, retain its element ref, and focus it after close/selection clearing.
- Query `matchMedia("(prefers-reduced-motion: reduce)")` before Fit; use immediate `cy.fit()` when reduction is requested.
- Consolidate policy validation into one alert state, or clear the other alert before setting a new validation error.

---

## Evidence and Test Results

| Check | Result |
|---|---|
| Targeted Phase-12 frontend suite | **PASS — 9 files, 181 tests** |
| Complete web Vitest suite | **PASS — 43 files, 347 passed, 15 todo** |
| TypeScript `npx --no-install tsc --noEmit` | **PASS — zero diagnostics** |
| Next.js ESLint `npm run lint` | **PASS — zero warnings/errors** |
| `git diff --check` | **PASS** |
| Current UI vs. source HEAD `811883f3` | **PASS — no diff** |
| Dev-server probe | No server on 3000, 5173, or 8080 |
| A39 evidence | **Inspected — 360×1462**; recorded geometry passes, but legend copy differs from current source |
| Registry audit | Skipped: no `components.json`; UI-SPEC declares no third-party registries |

The test run emitted existing non-failing Vite CJS, Cytoscape sparse-data mapping, Keyborg disposal, and React `act(...)` diagnostics. No test failed.

---

## Files Audited

### Design, planning, and closure evidence

- `.planning/STATE.md`
- `.github/gsd-core/workflows/ui-review.md`
- `.github/gsd-core/references/ui-brand.md`
- `.planning/phases/12-network-topology-integrity-and-scale/12-UI-SPEC.md`
- `.planning/phases/12-network-topology-integrity-and-scale/12-CONTEXT.md`
- All `12-01-SUMMARY.md` through `12-11-SUMMARY.md`
- `12-REVIEW-PRE-PHASE.md`
- `12-REVIEW.md`
- `12-REVIEW-FIX.md`
- `12-VALIDATION.md`
- `12-VERIFICATION.md`
- `12-SECURITY.md`
- `12-FABRIC-PRIVATE-LINK-DECISION.md`
- `12-11-A39-360px.png`

### Current frontend source and tests

- `web/src/app/network/page.tsx`
- `web/src/app/network/page.test.tsx`
- `web/src/app/globals.css`
- `web/src/components/network/TopologyWorkspace.tsx`
- `web/src/components/network/TopologyWorkspace.test.tsx`
- `web/src/components/network/TopologyGraph.tsx`
- `web/src/components/network/TopologyGraph.test.tsx`
- `web/src/components/network/TopologyDetailDrawer.tsx`
- `web/src/components/network/TopologyDetailDrawer.test.tsx`
- `web/src/components/ui/EvidenceBar.tsx`
- `web/src/components/ui/EvidenceBar.test.tsx`
- `web/src/components/ui/StatusBadge.tsx`
- `web/src/components/ui/StatusBadge.test.tsx`
- `web/src/components/ui/StatePanel.tsx`
- `web/src/hooks/useApi.ts`
- `web/src/hooks/useApi.test.ts`
- `web/src/lib/network-graph.ts`
- `web/src/lib/network-graph.test.ts`
- `web/src/lib/network-services.test.ts`
- `web/src/lib/services.ts`
- `web/src/lib/types.ts`
- `web/src/lib/format.ts`
- `web/src/test/network-fixtures.ts`

