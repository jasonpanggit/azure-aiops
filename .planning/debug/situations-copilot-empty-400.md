---
status: awaiting_human_verify
trigger: "Situations live reliability audit: the advertised question 'Which situations are highest priority?' must answer the valid empty/degraded live truth directly, with citations, freshness/uncertainty, mismatch 400 pre-I/O, mutation=false, and zero errors."
created: 2026-09-16T03:34:03Z
updated: 2026-09-16T04:12:00Z
---

## Current Focus

reasoning_checkpoint:
  hypothesis: "The valid-empty failure requires two code defects: the Situations adapter converts an available envelope with unknown evidence freshness into false fresh, and canonical execution leaks its planning-only incomplete coverage into the response while providing no deterministic empty-Situations claim."
  confirming_evidence:
    - "The exact browser-shaped API regression fails because returned complete is false even though the submitted page snapshot is complete 0/0."
    - "The exact adapter regression fails because unknown live evidence is emitted as fresh."
    - "The deployed HTTP 200 response contains zero claims/citations and renders only 0 of 0, Partial coverage, and uncertainty when the incidents provider is deferred."
  falsification_test: "The hypothesis would be false if the focused regressions passed unchanged, or if preserving selection coverage plus adding a coverage-cited empty claim still failed to render the direct empty/degraded truth."
  fix_rationale: "Keep planning downgraded for policy safety, but project the separately validated selection snapshot's coverage/citation into the result; synthesize a read-only page-qualified empty Situations claim from complete 0/0 coverage; derive fallback freshness from actual envelope evidence instead of envelope presence."
  blind_spots: "The deployed API remains on PR167 until Unified deployment merges this fix; post-deploy Playwright is required. No claim is made about Changes or Predeploy because the queue stops at first RED."
  candidate_causes:
    - "code: planning-only coverage escapes into the result and no valid-empty deterministic claim exists"
    - "environment: the optional incidents provider is deferred in the deployed revision"
    - "data: the valid live queue is empty and its source evidence has unknown freshness"
  and_gate: "yes — the empty dataset plus deferred tool exposes the missing deterministic path, while the adapter and planning/result conflation independently distort freshness and completeness."
next_action: Commit and open the narrow PR for Unified deployment, then rerun the same sanitized live Playwright audit against the deployed revision before advancing to Changes.

## Symptoms

expected: The live empty Situations queue advertises "Which situations are highest priority?" and Copilot answers directly that no active situations are visible, while stating unknown/degraded source freshness and citing the bounded page evidence.
actual: The page itself shows "No active situations in this scope". The advertised Copilot POST succeeds with HTTP 200 but returns zero synthesis claims, so the drawer renders only "0 of 0", partial coverage, uncertainty, and an unavailable incidents tool instead of a direct empty-state answer.
errors: No application request error. The initial harness incorrectly attributed the intentional mismatch probe's HTTP 400 and browser console error to the advertised request.
reproduction: Start the local Next.js app in dev-token mode against the stable live API revision, open /situations, open Operations Copilot, and select "Which situations are highest priority?" while GET /api/v1/situations returns 200 with data=[], pagination total=0, evidence freshness=unknown, and an empty timestamp.
started: Observed on origin/main commit 2a92253e against deployed API revision aiops-dev-api--pr167-c1f3b7e8 on 2026-09-16.

## Eliminated

- hypothesis: The advertised Situations request itself violates the canonical request contract and returns HTTP 400.
  evidence: The sanitized artifact contains the original HTTP 200 accepted response with incident/incidents routing; the request/response listener was overwritten by the later intentional mismatch request, which alone returned 400.
  timestamp: 2026-09-16T03:43:00Z

## Evidence

- timestamp: 2026-09-16T03:38:00Z
  checked: Same-run direct live Situations API
  found: GET /api/v1/situations returned 200, zero rows, pagination total 0, no warnings, and one aiops.situations/silver_situations evidence item with empty timestamp and unknown freshness/confidence.
  implication: This is a valid empty/degraded evidence case, not proof of a healthy all-clear.
- timestamp: 2026-09-16T03:38:00Z
  checked: Clean local dev-token Playwright flow against the stable live API
  found: The advertised Copilot POST returned 200 with policy_status=accepted, selected incident/incidents, unavailable tool status because the provider is deferred, zero citations, zero synthesis claims, and mutation_authorized=false. The separate incident/remediation-tool mismatch probe returned the expected 400.
  implication: Situations is the first RED because valid empty/degraded evidence produces generic metadata only; later pages must not run until this is fixed and deployed.
- timestamp: 2026-09-16T03:43:00Z
  checked: Captured request snapshot
  found: Coverage is complete 0/0 and the API evidence item is unavailable/unknown, but the adapter separately labels the synthetic situations freshness record fresh despite observed_at=unknown.
  implication: The response must state both the concrete empty truth and the lack of source-health/freshness confirmation; the adapter freshness derivation is a coupled correctness defect.
- timestamp: 2026-09-16T03:48:00Z
  checked: Canonical execution and deterministic synthesis source
  found: The endpoint creates a planning-only snapshot with complete=false and unavailable freshness; OrchestrationService returns that planning coverage and seeds citations from it even when the original selection snapshot is complete 0/0. `_deterministic_page_claims` also returns immediately when no retained scalar evidence exists and has no valid-empty Situations path.
  implication: The planning safety downgrade leaks into the user-visible contract, and no cited claim can replace the resulting generic coverage-only UI.
- timestamp: 2026-09-16T03:52:00Z
  checked: Focused test-first reproductions
  found: The Python API regression fails on complete=false versus submitted complete=true; the TypeScript adapter regression fails on fresh versus expected unavailable.
  implication: Both coupled code defects reproduce deterministically without the live environment.
- timestamp: 2026-09-16T03:56:00Z
  checked: First minimal fix against focused regressions
  found: Adapter freshness passes; API now preserves complete 0/0 coverage and emits the direct empty/degraded claim, but the response still omits its snapshot:coverage citation.
  implication: One response-projection seam is filtering coverage citations; the fix is not acceptable until the claim is citation-closed.
- timestamp: 2026-09-16T04:00:00Z
  checked: Canonical citation response projection
  found: The route discarded every citation not prefixed tool: or retained:, including the server-generated snapshot:coverage citation used by deterministic coverage claims.
  implication: The exact server-owned coverage citation must be allowlisted without widening arbitrary browser citation projection.
- timestamp: 2026-09-16T04:07:00Z
  checked: Full adjacent backend suite after first fix
  found: Broadly projecting the selection snapshot's coverage/citations broke the untrusted-browser-observation downgrade and overflowed the 256-citation bound for a 300-row inventory case.
  implication: Coverage preservation must be limited to the complete 0/0 Situations case, and only the single coverage citation may come from the selection snapshot; arbitrary browser rows must remain excluded.
- timestamp: 2026-09-16T04:12:00Z
  checked: End-to-end source map
  found: /situations loads GET /api/v1/situations into buildSituationsCopilotContext; the advertised question binds incident/incidents; specialists.v1.json grants incidents to the read-only incident specialist and maps situations; /api/v1/copilot/investigations validates the hint before I/O, executes the optional provider, then OrchestrationService performs deterministic/Foundry synthesis; route.incident.correlate is the nearest evaluation case but no existing case covered the exact empty/deferred advertised question.
  implication: The fix belongs at the shared adapter/response/synthesis seams, not in page copy or a provider-specific workaround.
- timestamp: 2026-09-16T04:12:00Z
  checked: Fix-acceptance guardrail
  found: Target regressions pass; reverting only the implementation makes both regressions fail and reapplying makes both pass; boundary neighbors reject partial-empty, singleton, and another page kind; full adjacent backend suite, full web suite, web lint/typecheck, Ruff, and all nine offline specialist parity checks pass.
  implication: The patch addresses the mechanism without widening untrusted browser authority or altering non-Situations empty behavior.

## Resolution

root_cause: The Situations empty-state path conflated envelope availability with freshness, leaked planning-only partial coverage into the response, had no deterministic coverage-cited claim when the optional incident tool produced no cited findings, and filtered the exact server-generated coverage citation from the API response.
fix: Derive Situations freshness from actual evidence; retain the validated selection snapshot's coverage/citation in canonical results while keeping the planner downgrade internal; emit a page-qualified direct empty/degraded claim citing snapshot:coverage; allowlist only that exact server-generated coverage citation in the response projection.
verification:
  target_test: { result: pass }
  mutation_check: { result: skipped, reason_if_skipped: "No Stryker configuration or dependency exists in this repository; exact revert-and-reconfirm and boundary tests were used.", mutant_killed: null }
  no_op_deletion: { result: pass, deletion_justified_by_rca: false }
  adjacent_tests:
    result: pass
    suites_run:
      - "tests/test_api_copilot_unified.py tests/test_orchestration_policy.py tests/test_page_context.py"
      - "full web npm test"
      - "Situations page and adapter tests"
      - "web lint and TypeScript noEmit"
      - "Ruff on changed Python"
      - "validate_specialist_parity.py --offline (9/9)"
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true, fixed_on_reapply: true }
  guardrail_verdict: accepted
  live_deployed_verification: pending_unified_deployment
oracle_type: specified
files_changed:
  - src/api/routers/copilot.py
  - src/operations/orchestration_service.py
  - tests/test_api_copilot_unified.py
  - web/src/lib/copilot/page-adapters.ts
  - web/src/lib/copilot/page-adapters.test.ts
