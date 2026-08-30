---
phase: 09-consumer-pivot
plan: 03
subsystem: web
tags: [next, react, copilot, accessibility, snapshots, inventory]
requires:
  - phase: 09-consumer-pivot
    provides: typed contextual Copilot API and governed inventory boundary
provides:
  - Typed bounded frontend PageSnapshot builder and contextual API client
  - Accessible shared Copilot launcher and staged contextual drawer
  - Page-specific snapshot wiring for home, Network, exposure, CVE, compliance, situations, and remediation
affects: [consumer-pivot, network-copilot, operations-ui]
tech-stack:
  added: []
  patterns: [typed visible-state snapshots, explicit deterministic fallback, accessible live-region drawer]
key-files:
  created:
    - web/src/components/ui/CopilotDrawer.test.tsx
    - web/src/components/ui/CopilotDrawerButton.test.tsx
    - web/src/components/ui/CopilotPageIntegrations.test.tsx
  modified:
    - web/src/lib/types.ts
    - web/src/lib/services.ts
    - web/src/components/ui/CopilotDrawer.tsx
    - web/src/components/ui/CopilotDrawerButton.tsx
    - web/src/app/network/page.tsx
    - web/src/app/page.tsx
    - web/src/app/exposure/page.tsx
    - web/src/app/exposure/cves/[id]/page.tsx
    - web/src/app/compliance/page.tsx
    - web/src/app/situations/page.tsx
    - web/src/app/remediation/page.tsx
    - web/src/app/globals.css
decisions:
  - "Page-level Copilot submits the exact named visible state through one shared drawer; /agents remains the full investigation workspace."
  - "Deterministic findings, hypotheses, source warnings, and Foundry narration are rendered as distinct states."
metrics:
  duration: 12min
  completed: 2026-08-28
  status: complete
actuals:
  tokens: 18000
  tasks: 2
  commits: 3
---

# Phase 09 Plan 03: Consumer Pivot Summary

**Accessible contextual Copilot now follows each supported operations page through a bounded typed snapshot, with cited deterministic results and honest staged degradation.**

## Accomplishments

- Added TypeScript mirrors for page kinds, selected resources, scope authorization, evidence rows, findings, and synthesis mode.
- Added a bounded snapshot builder/evidence adapter and `investigate-context` service wrapper.
- Network and the home, exposure, CVE detail, compliance, situations, and remediation pages now submit page-specific filters, visible records, selected resources, scope, and evidence through the shared drawer.
- Improved the launcher with compact icon-first responsive styling, accessible naming/tooltips/focus, dialog semantics, Escape handling, live status messaging, deterministic fallback labeling, partial findings, and retry.
- Preserved `/agents` as the independent activity, reconciliation, evaluation, ledger, and human-controls workspace.

## Task Commits

1. `1e3fb5c3` — `feat(09-03): connect Network page to accessible contextual Copilot`
2. `d041e5de` — `feat(09-03): expand contextual Copilot across operations pages`
3. `11e3be87` — `test(09-03): align page tests with contextual launcher`

## Verification

- `cd web && npm run lint` — passed.
- `cd web && npm run build` — passed; existing MSAL prerender `window is not defined` messages are emitted but do not fail the build.
- Focused Copilot, page integration, `/agents`, compliance, remediation, and situations tests — 14 passed.
- Full web suite — 140 passed; one existing connections onboarding test was flaky in the parallel run and passed when run independently.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed TypeScript evidence-row inference**
- **Found during:** Task 2 build verification
- **Issue:** Concatenating source-derived and visible-record evidence inferred incompatible object types.
- **Fix:** Added explicit `CopilotEvidenceRow` return annotations.
- **Files modified:** `web/src/lib/services.ts`
- **Commit:** `1e3fb5c3`

**2. [Rule 1 - Bug] Updated page regression mocks for new shared helper exports**
- **Found during:** Full web verification
- **Issue:** Existing compliance, remediation, and situations mocks did not expose the snapshot helper.
- **Fix:** Added lightweight helper mocks and updated the compliance assertion for the button launcher.
- **Files modified:** `web/src/app/compliance/page.test.tsx`, `web/src/app/remediation/page.test.tsx`, `web/src/app/situations/page.test.tsx`
- **Commit:** `11e3be87`

## Known Stubs

None.

## Self-Check: PASSED

- Summary exists at `.planning/phases/09-consumer-pivot/09-03-SUMMARY.md`.
- Commits `1e3fb5c3`, `d041e5de`, and `11e3be87` are present.
- Focused verification, lint, and production build completed successfully.
