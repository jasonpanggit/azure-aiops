---
status: blocked
phase: 09-consumer-pivot
source:
  - 09-01-SUMMARY.md
  - 09-02-SUMMARY.md
  - 09-03-SUMMARY.md
  - 09-04-SUMMARY.md
  - 09-05-SUMMARY.md
  - 09-06-SUMMARY.md
started: 2026-08-28T16:30:00+08:00
updated: 2026-08-28T16:45:00+08:00
---

## Current Test

number: 2
name: Submit a question using the visible Network context
expected: |
  In the open contextual Copilot panel, submit a question about the visible Network topology or evidence. The response should be tied to the current page snapshot, include citations, source freshness, uncertainty, and a clear synthesis mode.
awaiting: redeployment of the web image containing the contextual synthesis fix

## Tests

### 1. Open the contextual Copilot on a live operations page
expected: The Network page shows a compact accessible launcher; activating it opens a contextual side panel while keeping the page visible.
result: passed

### 2. Submit a question using the visible Network context
expected: The panel submits the current page snapshot and returns findings tied to the visible topology/evidence, with citations, source freshness, uncertainty, and a clear synthesis mode.
result: blocked — the fix is local and the live Azure Container App still needs a new web image before retesting.

### 3. Verify staged and fallback states
expected: Loading/progress, partial or stale evidence, unavailable Foundry narration, retry, and request failure are distinct and honest; deterministic results are not labeled as LLM output.
result: pending

### 4. Verify accessibility and responsive behavior
expected: Keyboard focus enters the panel, Escape closes it, screen readers receive the panel name and live progress, and the launcher/panel remain usable at narrow and wide viewport sizes.
result: pending

### 5. Verify the full investigation workspace remains available
expected: `/agents` still presents agent activity, reconciliation, evaluation, ledger, and human controls independently of the contextual side panel.
result: pending

### 6. Verify tenant-dependent Foundry and Fabric IQ enrichment
expected: When configured in the target tenant, named specialist and Fabric IQ enrichment metadata are visible in the resulting ledger/evidence; when unavailable, the system clearly falls back to governed deterministic/API results without blocking identity or scope.
result: pending

## Summary

total: 6
passed: 1
issues: 1
pending: 5
skipped: 0
blocked: 0

## Gaps

- **Test 2 initial attempt:** The contextual endpoint returns `synthesis.narration` as a string, while the drawer treated the entire synthesis object as a `CopilotAnswer`, causing `MarkdownLite` to call `.replace` on `undefined`. Fixed in `web/src/components/ui/CopilotDrawer.tsx` by normalizing contextual narration before rendering.
- **Deployment required:** The live UAT URL will not include the local fix until the web image is built and deployed to the Azure Container App.
