---
status: resolved
trigger: "Compliance page to remediation page handoff is not working; no fix appears for the private endpoint cosmos-pe resource URL."
created: "2026-09-08T22:01:39+08:00"
updated: "2026-09-08T22:58:00+08:00"
---

## Symptoms

- expected: Selecting a compliance violation and opening remediation preserves the finding and shows its remediation candidate in a governed, truthful destination state.
- actual: `/remediation?resource_key=.../microsoft.network/privateendpoints/cosmos-pe` shows no fix.
- errors: No explicit browser error was reported.
- timeline: Reproduced after the earlier `fix(remediation): repair empty remediation page from compliance` release.
- reproduction: Open the supplied resource-scoped remediation URL for `cosmos-pe`, or select its compliance violation and click Open remediation.

## Current Focus

hypothesis: Confirmed — the selected client-derived compliance finding was dropped at the link boundary and could not be reconstructed from server-generated remediation plans.
bug_class: Bohrbug — deterministic data-contract loss at the cross-page boundary.
test: Exact six-field parsing, extra/duplicate rejection, canonical resource enforcement, unrelated-plan isolation, mutation-control absence, full web tests, typecheck, lint, and production build.
expecting: The selected `cosmos-pe` finding appears as a bounded "Compliance finding review" with "Manual review only" and no executable network action controls.
next_action: None; the local fix is complete and cloud mutation remains frozen.
tdd_checkpoint:
  test_file: "web/src/app/compliance/page.test.tsx; web/src/app/remediation/page.test.tsx"
  test_name: "hands a canonical network finding to remediation as bounded review context; renders a bounded compliance finding as manual review when no generated plan matches"
  status: "green"
  failure_output: "2 failed, 58 passed. Source received review_source=null; destination could not find heading 'Compliance finding review'."

## Evidence

- timestamp: 2026-09-08T22:18:00+08:00
  checked: compliance link builder, remediation query consumption, operations remediation filter, live planner action families
  found: Compliance passes only `resource_key`; remediation filters server plans by exact resource ID; the live planner emits only patch and supported Defender configuration plans. Network compliance violations are computed client-side and are not an input to the remediation provider.
  implication: Resource canonicalization is working as designed. The missing contract between the client-derived compliance finding and remediation review is the root cause.

- timestamp: 2026-09-08T22:19:00+08:00
  checked: commit 8b5eab79b
  found: The prior fix repaired the old `business_service` link, split empty states, and added catalog trigger producers, but did not serialize the selected network compliance finding or generate a network action.
  implication: Extending resource filtering again cannot fix this case. The destination needs a bounded review handoff, and unsupported network mutation must remain fail closed.

- timestamp: 2026-09-08T22:24:00+08:00
  checked: active STATE.md phase and complete scoped page/test implementations
  found: Phase 03.1 is active with remediation and network behavior explicitly preserved. `remediationHref` emits only `resource_key`; `RemediationContent` reads no compliance finding fields and its zero-plan branch renders only "No fix for this resource". Existing tests have isolated `useSearchParams`, API, and link seams suitable for a local deterministic regression.
  implication: The fix remains in the allowed local frontend scope and can be proven without any cloud operation. It must add a narrow query contract and a non-executable fallback rather than alter plan generation or execution.

- timestamp: 2026-09-08T22:24:30+08:00
  checked: spectrum-based fault localization eligibility
  found: No pre-existing failing frontend test represented this bug before the TDD red phase, so there is no failing/passing per-test coverage spectrum to rank.
  implication: SBFL is skipped with a logged reason; deterministic working-backwards and contract-boundary testing are the appropriate route.

- timestamp: 2026-09-08T22:26:00+08:00
  checked: .planning/debug/knowledge-base.md
  found: No prior resolution matches the client-derived compliance-to-remediation handoff loss. Existing remediation entries concern action-version stability and server workflow behavior, not missing cross-page finding context.
  implication: No known-pattern candidate supersedes the confirmed local data-contract hypothesis.

- timestamp: 2026-09-08T22:29:30+08:00
  checked: first TDD command invocation
  found: The root-level `npm test` command did not reach Vitest because this repository's package.json is under web/.
  implication: This is a test-runner working-directory error, not evidence about the hypothesis; rerun through `npm --prefix web`.

- timestamp: 2026-09-08T22:31:00+08:00
  checked: TDD red run `npm --prefix web test -- src/app/compliance/page.test.tsx src/app/remediation/page.test.tsx`
  found: Both new contract tests failed for the predicted reasons while 58 adjacent tests passed. The compliance URL returned `review_source=null`; the remediation page could not find the "Compliance finding review" heading and retained the generic empty-resource state.
  implication: The regression tests reproduce both sides of the dropped handoff contract without any production change. The hypothesis is directly confirmed and the red phase is valid.

- timestamp: 2026-09-08T22:34:00+08:00
  checked: active STATE.md metadata, project/debugger skills, and scoped git status
  found: Phase 03.1 explicitly requires remediation and network behavior to remain preserved; no configured debugger agent skill adds requirements; only the two red test files and debug checkpoint are dirty, while both production pages are clean.
  implication: A local frontend-only additive review handoff is in phase scope, and production edits can be isolated from unrelated dirty changes without cloud mutation or commits.

- timestamp: 2026-09-08T22:35:00+08:00
  checked: complete compliance implementation and remediation query/filter/zero-plan render seams
  found: `remediationHref` is the sole source link builder; remediation reads query state once at `RemediationContent`; the zero-plan resource branch is isolated from generated-plan workflow rendering and actions.
  implication: The fix can be additive and local: serialize a six-field allowlist, validate it into a typed bounded review value, and render only that value in the existing no-plan branch.

- timestamp: 2026-09-08T22:36:00+08:00
  checked: first GREEN production patch application
  found: The compliance page hunk applied, but the remediation page update was not applied because one query-context line differed from the patch expectation.
  implication: Preserve the successful source hunk, inspect exact destination contexts, and retry only the destination change rather than making a confounded rewrite.

- timestamp: 2026-09-08T22:37:00+08:00
  checked: retried remediation-only production patch
  found: The destination now validates source, canonical resource identity, finding/severity enums, and explicit length bounds before rendering the review-only state; generated plans and workflow action branches are unchanged.
  implication: The production GREEN implementation is complete; the destination test mock must preserve the newly used existing canonical-resource utility before running Vitest.

- timestamp: 2026-09-08T22:39:00+08:00
  checked: GREEN run `npm --prefix web test -- src/app/compliance/page.test.tsx src/app/remediation/page.test.tsx`
  found: Both scoped test files passed: 60 tests total, including the two formerly RED handoff tests.
  implication: The bounded source-to-destination contract fixes the reproduced bug; proceed to REFACTOR hardening with boundary neighbors before broader lint/build verification.

- timestamp: 2026-09-08T22:41:00+08:00
  checked: REFACTOR boundary run after adding source overflow and destination exact-limit/N+1/incomplete neighbors
  found: Both scoped files passed with 65 tests total. Exact 200/1000-character context renders; 201/1001-character or incomplete context fails closed; source overflow emits resource identity only.
  implication: The bounded contract is now regression-protected on both sides, including adjacent equivalence-class boundaries.

- timestamp: 2026-09-08T22:42:00+08:00
  checked: scoped production/test diff and frontend mutation-test configuration
  found: The diff is additive apart from replacing the old one-line resource link builder and making the service mock preserve an existing utility; no plan/workflow action branch is deleted or bypassed. Web has no Stryker dependency or configuration.
  implication: The no-op/deletion guard is satisfied; mutation testing will be explicitly skipped as unavailable, and lint/build remain required verification signals.

- timestamp: 2026-09-08T22:43:00+08:00
  checked: targeted Next lint for the four scoped frontend files
  found: ESLint completed with no warnings or errors.
  implication: The implementation and regression tests satisfy the repository's scoped React/TypeScript lint rules.

- timestamp: 2026-09-08T22:44:00+08:00
  checked: local production frontend build
  found: Next.js compiled, typechecked, generated all 28 static pages, and exited successfully. Existing MSAL `window is not defined` diagnostics were logged during static generation but did not fail the build.
  implication: The changed compliance and remediation routes compile in the full frontend; proceed to revert-and-reconfirm before accepting the fix.

- timestamp: 2026-09-08T22:46:00+08:00
  checked: revert-and-reconfirm test run with only the two production page changes path-stashed
  found: Vitest exited 1 with 3 handoff/review failures and 62 adjacent passes: the source context test and both valid destination review tests failed.
  implication: The bug deterministically returns when the production fix is absent; restore the exact scoped stash before re-confirming GREEN.

- timestamp: 2026-09-08T22:49:00+08:00
  checked: revert-and-reconfirm after restoring the exact production path stash
  found: Both targeted test files returned to GREEN with 65 of 65 tests passing.
  implication: The production changes, rather than an environmental change or weakened test, are necessary and sufficient for the automated reproduction.

- timestamp: 2026-09-08T22:50:00+08:00
  checked: final scoped diff check, full working-tree status, and stash list
  found: `git diff --check` is clean; the temporary compliance handoff stash was dropped; task changes are confined to the four allowed frontend files and this checkpoint. Pre-existing `.azure/deployment-plan.md` and `.azure/validate-status.json` changes remain untouched, as do older unrelated stashes.
  implication: The fix is ready for human workflow verification with cloud freeze and commit prohibition honored.

- timestamp: 2026-09-08T22:58:00+08:00
  checked: independent two-pass code review and full frontend validation after hardening
  found: The first review identified legacy/extra/duplicate query acceptance and visible disabled Approve/Run step controls; the second identified unrelated resource plans bypassing manual review. All findings were fixed. A final review reported no significant issues. Full web validation passed 59 test files and 675 tests, TypeScript `--noEmit`, Next ESLint, and the production build; `git diff --check` remained clean.
  implication: The six-field contract is exact, unsupported compliance findings always remain manual-review-only even when another plan exists for the resource, and no mutation workflow controls render.

reasoning_checkpoint:
  hypothesis: "The handoff loses the selected network compliance finding because it sends only a resource identifier, while the destination can query only server-generated plans that do not include client-derived network findings."
  confirming_evidence:
    - "fromGap/fromTopology create Violation rows in web/src/app/compliance/page.tsx."
    - "remediationHref serializes only violation.resource."
    - "GET /api/v1/remediation-plans filters plans already generated by the remediation provider."
    - "LiveRemediationPlanner plan families are patch and Defender configuration; no private-endpoint network executor is allowlisted."
  falsification_test: "Find a server-side plan or handoff provider that accepts the selected compliance violation identity and recommendation for this resource."
  fix_rationale: "Carry a strict, bounded compliance review context to the existing remediation page and render it as manual review when no executable plan exists. This restores handoff continuity without claiming unsupported execution."
  blind_spots: "The deployed compliance violation selected by the user is not queried because the global cloud freeze prohibits live mutations and the bug is reproducible from the source contract."
  candidate_causes:
    - "code: selected violation context is dropped at the link boundary"
    - "data: the selected network finding exists only in the compliance page's derived Violation row and is absent from server plan data"
  and_gate: "yes: the violation is client-derived, and the URL carries only resource identity."

## Eliminated

- hypothesis: Resource ID casing causes the exact filter to miss.
  evidence: Both API and web comparisons casefold resource IDs; the supplied URL is canonical and intentionally filters to zero because no plan exists.

## Resolution

root_cause: "Two conditions co-occur: the compliance link drops the selected client-derived network finding context, and the remediation plan source has no corresponding network finding/action data to reconstruct it from `resource_key`."
fix: "Serialize exactly six allowlisted, single-occurrence compliance review fields for canonical resources; reject aliases, extras, duplicates, incomplete values, and values over their bounds. Valid compliance context takes precedence over unrelated resource plans and renders in a standalone manual-review-only state with no approval, run, or execution controls. Unsupported network execution remains unavailable."
verification:
  target_test: { result: pass, detail: "68 scoped tests pass after strict-key and unrelated-plan hardening" }
  mutation_check: { result: skipped, reason_if_skipped: "Web has no Stryker dependency or configuration", mutant_killed: false }
  no_op_deletion: { result: pass, deletion_justified_by_rca: false }
  adjacent_tests: { result: pass, suites_run: ["full web: 59 files / 675 tests passed", "TypeScript --noEmit: passed", "Next ESLint: clean", "Next production build: passed", "final independent code review: no significant issues"] }
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true, fixed_on_reapply: true }
  guardrail_verdict: accepted
files_changed:
  - web/src/app/compliance/page.tsx
  - web/src/app/compliance/page.test.tsx
  - web/src/app/remediation/page.tsx
  - web/src/app/remediation/page.test.tsx
oracle_type: specified
