---
status: awaiting_human_verify
trigger: "Investigate and fix the reported bug in the current repository: clicking the `Open governed remediation` link in `web/src/components/exposure/PatchInventory.tsx` appears to only reload `/remediation` instead of opening the selected governed remediation context. Follow the scientific method: inspect the link/handoff, query-param consumption in `web/src/app/remediation/page.tsx`, Next.js routing behavior, and existing tests. Preserve scope safety and existing user changes. Implement the smallest correct fix, add/update focused tests, and run the relevant frontend test/lint commands. Do not commit. Report root cause and files changed."
created: 2026-09-02T22:26:04+08:00
updated: 2026-09-02T22:55:00+08:00
---

## Current Focus

hypothesis: The remediation context query parameter reaches the page, but the page never uses it to initialize selectedId, so the UI falls back to the first plan/backlog item and appears to reload without opening the target context.
test: Add a focused page test with multiple plans where the handoff resource matches the second plan, then implement only query-driven initial selection and rerun the focused tests/lint.
expecting: Before the fix the second plan is not selected; after the fix the matching plan detail is selected while manual Review selection remains available.
next_action: Have the user click the PatchInventory governed remediation link in the real workflow and confirm the matching resource context opens.

## Symptoms

expected: Clicking "Open governed remediation" opens `/remediation` with the selected governed remediation context.
actual: Clicking the link appears to only reload `/remediation` without opening the selected context.
errors: None reported.
reproduction: In the exposure PatchInventory UI, click "Open governed remediation" for a selected inventory item.
started: Not specified.

## Eliminated

## Evidence

- timestamp: 2026-09-02T22:34:00+08:00
  checked: PatchInventory.tsx, remediation/page.tsx, focused tests, git diff
  found: PatchInventory builds `/remediation?resource_key=<target>&kb=<patch>&business_service=<service>` correctly. Remediation reads `resource_key` via useSearchParams and passes it to remediationPlans, but `selectedId` starts empty and `selected` falls back to the first plan/backlog item; no query-derived selection is initialized.
  implication: Next.js Link/query handoff is present. The likely defect is page-side context selection, not a missing URL or hard navigation.

- timestamp: 2026-09-02T22:34:00+08:00
  checked: working tree
  found: Existing user changes include web/src/app/remediation/page.tsx and unrelated backend/infrastructure files; PatchInventory is unmodified. A new debug file is untracked.
  implication: Fix must avoid reverting or rewriting existing remediation changes and must only touch the focused frontend files/tests.

- timestamp: 2026-09-02T22:40:00+08:00
  checked: focused PatchInventory and remediation Vitest suites
  found: Existing 4 PatchInventory tests and remediation suite pass, but no test covers a resource handoff selecting among multiple backlog plans. The page's only selection update is the manual Review button; selected defaults to first plan/item.
  implication: Existing tests validate URL generation and rendering, not end-to-end query-context consumption.

reasoning_checkpoint:
  hypothesis: "RemediationContent ignores the resource_key handoff when choosing the selected backlog item, causing selectedId to remain empty and the detail pane to fall back to the first plan."
  confirming_evidence:
    - "PatchInventory generates the expected resource_key/kb/business_service URL."
    - "RemediationContent reads resource_key and filters the plans request, but selectedId is initialized to an empty string and is never set from the query."
    - "The existing focused tests pass without asserting that a non-first matching plan is selected."
  falsification_test: "A regression test with two plans, where resource_key matches only the second plan, would still select the second plan without any code change; or runtime tracing would show selectedId initialized from the query elsewhere."
  fix_rationale: "Initialize selectedId from the first backlog item whose source resource matches resource_key, while retaining the existing first-item fallback and manual Review behavior."
  blind_spots: "The live API's exact resource filtering and Next.js client navigation cannot be exercised by the jsdom unit test; the test will verify page-side consumption and matching."
  candidate_causes:
    - "code: selectedId has no query-derived initialization"
    - "data/API: remediation plan resource identity may be nested and differs from the display-only BacklogItem resource string"
  and_gate: "no — the observed behavior is explained by the missing page selection initialization; API filtering and query handoff are supporting conditions, not a second required defect."

- timestamp: 2026-09-02T22:55:00+08:00
  checked: focused frontend tests and lint after fix
  found: PatchInventory suite passed 4/4; remediation suite passed 29/29 including the new multi-plan handoff regression; next lint passed with no warnings or errors; git diff --check passed.
  implication: The fix is stable under the focused automated checks. Real browser/production routing still needs user confirmation.

## Resolution

root_cause: RemediationContent read resource_key but never used it to initialize selectedId; selected therefore fell back to the first plan/backlog item instead of opening the handed-off resource context.
fix: Select the first backlog item whose source resource identity matches resource_key, while preserving the existing fallback and manual Review selection.
verification:
  oracle_type: specified
  guardrail_verdict: pending
  signals: pending
files_changed:
  - web/src/app/remediation/page.tsx
  - web/src/app/remediation/page.test.tsx
