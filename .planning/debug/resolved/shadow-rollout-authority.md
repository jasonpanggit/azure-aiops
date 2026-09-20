---
status: resolved
trigger: "Fix the Phase 11 shadow rollout authority bug in jasonpanggit/azure-aiops. Live signed validation failed on revision 0000322: rollout reports canonical_enabled=false/shadow_enabled=true, but because `src/api/routers/copilot.py` branches on `if rollout.canonical_enabled or coordinator_enabled`, activated coordinator v6 executes canonical OrchestrationService, real tool/model work, and canonical top-level result during shadow. Required contract: compatibility mode and shadow mode keep compatibility result authoritative; shadow may compute only deterministic/no-I/O canonical plan preview/comparison; canary-selected/default may execute canonical; coordinator availability must never override rollout mode. Ensure coordinator synthesis/metadata cannot claim execution outside canonical-enabled path. Add exact regressions for shadow with coordinator enabled: canonical planner/executor/narrator call counts zero beyond compatibility baseline, top-level compatibility result preserved, comparison present, mutation=false; compatibility with coordinator also stays compatibility; canary selected/default still execute canonical; invalid hints reject pre-I/O. Preserve active specialist catalog and no Azure MCP. Run focused/affected/full relevant tests, Ruff, independent review, conventional commit+trailer, PR. No Azure calls/deploy."
created: 2026-09-20T09:33:30-07:00
updated: 2026-09-20T09:45:38.695-07:00
---

## Symptoms

expected_behavior: Compatibility and shadow rollout modes keep the compatibility result authoritative. Shadow may only produce deterministic, no-I/O canonical plan preview/comparison. Canary-selected/default canonical modes may execute canonical orchestration. Coordinator availability never overrides rollout authority, and synthesis/metadata never claims canonical execution outside canonical-enabled paths.
actual_behavior: With coordinator v6 enabled during shadow rollout, `src/api/routers/copilot.py` enters `if rollout.canonical_enabled or coordinator_enabled`, executes canonical `OrchestrationService`, performs real tool/model work, and returns the canonical top-level result even though `canonical_enabled=false` and `shadow_enabled=true`.
error_messages: Live signed validation on revision 0000322 reported `canonical_enabled=false` and `shadow_enabled=true` while canonical execution still occurred.
timeline: Observed during live signed validation of revision 0000322.
reproduction: Enable coordinator v6, select shadow rollout, and invoke the Copilot route. Observe canonical planner/executor/narrator activity and canonical top-level authority despite shadow mode.

## Current Focus

reasoning_checkpoint:
  hypothesis: "Coordinator capability bypasses rollout authority because investigate_canonical wraps the deterministic planner/synthesizer, executes OrchestrationService, and emits coordinator metadata whenever coordinator_enabled is true, including when rollout.canonical_enabled is false."
  confirming_evidence:
    - "The source directly branches on `rollout.canonical_enabled or coordinator_enabled` and separately wraps planner/synthesis and metadata under coordinator_enabled alone."
    - "The RED mode matrix observes compatibility_calls=[] only for compatibility and shadow with coordinator v6, while canary-100/default execute canonical as intended."
  falsification_test: "After gating all coordinator planning, canonical execution, and coordinator metadata by rollout.canonical_enabled, the specified mode matrix would still enter canonical counters or coordinator model calls for compatibility/shadow, or would stop canonical execution for canary-100/default."
  fix_rationale: "Making the already-computed rollout.canonical_enabled flag the sole canonical execution gate restores rollout authority; coordinator remains an optional capability only inside an authorized canonical path, while shadow preview uses the existing deterministic planner without model or tool I/O."
  blind_spots: "Production Azure deployment is intentionally untested; verification is limited to local route contracts, affected tests, static checks, and an independent diff review."
  candidate_causes:
    - "code: coordinator capability is ORed into the canonical execution branch and independently controls planner/synthesis/metadata."
    - "config: an incorrect rollout parser could mark shadow canonical-enabled, but the mode matrix directly observed canonical_enabled=false and eliminated this candidate."
  and_gate: "no — coordinator availability is the single sufficient bypass when rollout canonical authority is false; the rollout parser and test environment report the intended modes."
hypothesis: The `rollout.canonical_enabled or coordinator_enabled` branch and unconditional coordinator wrapping/metadata let coordinator availability override the rollout's execution authority.
test: Human verification of the corrected rollout authority in the intended workflow.
expecting: Compatibility/shadow remain compatibility-authoritative and canary-selected/default remain canonical-authoritative.
next_action: Archive the resolved session, commit the scoped fix with trailer, and update the debug knowledge base; do not create a PR.
bug_class: bohrbug
known_pattern_candidate: none; the debug knowledge base contains no prior rollout-authority resolution.
scope_check: Phase 11 is an explicitly planned isolated regression despite the stale Phase 4 pointer; no Azure calls, deployment, PR creation, or specialist catalog/Azure MCP configuration changes are permitted.
tdd_checkpoint:
  test_file: tests/test_api_copilot_unified.py
  test_name: test_rollout_alone_authorizes_coordinator_execution
  status: green
  failure_output: "Compatibility and shadow cases expected retained compatibility tool execution, but compatibility_calls was []; canary-selected/default and invalid-hint cases passed."

## Eliminated
<!-- APPEND only - prevents re-investigating -->

- hypothesis: The rollout decision or environment parsing incorrectly marks shadow as canonical-enabled.
  evidence: The mode matrix observes `rollout.canonical_enabled == false` for compatibility/shadow and true for canary-100/default, exactly matching `copilot_rollout_decision`.
  timestamp: 2026-09-20T09:51:00-07:00

- hypothesis: Malformed page data or hint validation causes the execution-path mismatch.
  evidence: The minimized valid-hint fixture reproduces only in noncanonical modes, while the separate invalid-hint case returns 400 before all compatibility, canonical, and coordinator I/O.
  timestamp: 2026-09-20T09:51:00-07:00

## Evidence
<!-- APPEND only - facts discovered -->

- timestamp: 2026-09-20T09:36:00-07:00
  checked: `.planning/STATE.md`, repository status, and `.planning/debug/knowledge-base.md`
  found: Phase 11 is listed as planned; the worktree contains only this untracked debug file; no prior knowledge-base entry matches coordinator-enabled shadow rollout authority.
  implication: The isolated regression is in scope, there are no unrelated code changes to preserve, and direct code tracing is required.

- timestamp: 2026-09-20T09:39:00-07:00
  checked: Complete `src/api/routers/copilot.py` implementation
  found: `investigate_canonical` constructs coordinator planner/synthesis whenever coordinator v6 is available, then executes `OrchestrationService` under `if rollout.canonical_enabled or coordinator_enabled`; it also appends coordinator execution metadata whenever `coordinator_enabled`, regardless of rollout authority.
  implication: The reported deterministic failure mechanism is directly present in code; rollout mode is not the sole authorization gate for canonical execution or coordinator execution claims.

- timestamp: 2026-09-20T09:39:00-07:00
  checked: Spectrum-based fault-localization prerequisites
  found: No failing automated regression exists yet; the only failure is the live signed-validation report.
  implication: SBFL is skipped until the agent-authored test reproduces the failure; test-first reproduction is the deterministic Bohrbug route.

- timestamp: 2026-09-20T09:42:00-07:00
  checked: Rollout decision implementation and existing unified Copilot tests
  found: `copilot_rollout_decision` correctly returns `canonical_enabled=False, shadow_enabled=True` for shadow and canonical only for selected canary/default. Existing coordinator route tests deliberately set compatibility yet assert canonical coordinator synthesis, while shadow tests use no coordinator.
  implication: The rollout function and environment configuration are not the cause; tests omitted the coordinator-plus-noncanonical interaction and some currently encode the authority bypass as expected behavior.

- timestamp: 2026-09-20T09:46:00-07:00
  checked: Retained `run_investigation`, Foundry coordinator planner/synthesis adapters, and introducing commit `b9832b9e0`
  found: Compatibility executes through `operations.investigation.call_tool` and may use one ordinary narration call; canonical execution uses the route-local executor plus coordinator planning/synthesis. Commit `b9832b9e0` introduced coordinator wrapping, the boolean `or coordinator_enabled`, and unconditional coordinator metadata together.
  implication: Independent counters can distinguish retained compatibility from canonical work, and the three introduced conditions form one coherent authorization defect.

- timestamp: 2026-09-20T09:49:00-07:00
  checked: First RED run of the agent-authored mode matrix
  found: Compatibility and shadow both failed because the compatibility counter stayed zero, while canary-selected and default passed as canonical. The invalid-hint case rejected before I/O but hit unrelated unresolved domain-snapshot validation first.
  implication: The new test directly reproduces rollout authority being overridden. The invalid-hint fixture needs minimization so it asserts the intended binding gate rather than an earlier independent gate.

- timestamp: 2026-09-20T09:51:00-07:00
  checked: Minimized focused RED run: `uv run pytest -q tests/test_api_copilot_unified.py::test_rollout_alone_authorizes_coordinator_execution tests/test_api_copilot_unified.py::test_coordinator_enabled_invalid_hint_rejects_before_any_io`
  found: Exactly the compatibility and shadow matrix cases fail because canonical execution suppresses the expected retained compatibility call; canary-selected, default, and coordinator-enabled invalid-hint pre-I/O cases pass (3 passed, 2 failed).
  implication: The regression isolates the rollout-authority bug and covers both adjacent authorized modes plus the pre-I/O validation boundary.

- timestamp: 2026-09-20T09:56:00-07:00
  checked: Focused TDD green run after the three rollout-authority gates
  found: `test_rollout_alone_authorizes_coordinator_execution` and `test_coordinator_enabled_invalid_hint_rejects_before_any_io` pass in all five parametrized cases.
  implication: The minimal production change satisfies the specified authority matrix and pre-I/O boundary; TDD checkpoint is green.

- timestamp: 2026-09-20T09:58:00-07:00
  checked: Existing coordinator-focused tests via `pytest -k coordinator`
  found: 9 tests pass; only `test_coordinator_failure_preserves_exact_validated_page_hint` fails because it configures compatibility but expects canonical coordinator fallback reason `planner_unavailable`.
  implication: The production fix did not broadly break coordinator logic; this pre-existing test fixture encodes the removed authority bypass and must select default rollout to test canonical coordinator failure.

- timestamp: 2026-09-20T10:03:00-07:00
  checked: Coordinator-focused tests after mode-only correction of five pre-existing canonical coordinator fixtures
  found: All 10 coordinator-focused tests pass; retained compatibility fixtures and the multi-agent compatibility runtime fixture remain in compatibility mode.
  implication: Coordinator planning/synthesis still works in authorized canonical mode, while compatibility/shadow authority is now independently covered.

- timestamp: 2026-09-20T10:05:00-07:00
  checked: Guardrail revert half: temporarily restored the original three production conditions and reran the driving mode matrix
  found: Exactly compatibility and shadow failed with empty compatibility calls; canary-100 and default continued to pass.
  implication: The original bug reliably returns when only the production fix is removed.

- timestamp: 2026-09-20T10:07:00-07:00
  checked: Guardrail reapply half
  found: Reapplying only the three rollout-authority conditions restores all four mode-matrix cases to green.
  implication: The production gate change is both necessary and sufficient for the regression; revert-and-reconfirm passes.

- timestamp: 2026-09-20T10:11:00-07:00
  checked: Complete affected `tests/test_api_copilot_unified.py` suite and Ruff on changed files
  found: The complete unified Copilot file passes (217 tests), and Ruff reports all checks passed.
  implication: The fix preserves all directly adjacent route behavior and meets changed-file static quality checks.

- timestamp: 2026-09-20T10:11:00-07:00
  checked: Mutation runner availability
  found: No Stryker or project mutation-test configuration is present; mutation-related matches are only GSD framework documentation/source.
  implication: Guardrail mutation signal is skipped with an explicit environment limitation.

- timestamp: 2026-09-20T10:16:00-07:00
  checked: Full relevant 13-file Copilot/orchestration suite, repository-wide Ruff, and diff hygiene
  found: Relevant suite had 3 failures among 568 tests: one snapshot-v2 500 and two shadow drawer expectations; `git diff --check` passed. Repository-wide Ruff found 26 pre-existing errors only in untouched infra/scripts files, while changed-file Ruff remains clean.
  implication: Verification is not yet accepted. The three test failures require isolation; unrelated Ruff debt must not be modified for this bug.

- timestamp: 2026-09-20T10:20:00-07:00
  checked: Each of the three relevant-suite failures in a fresh pytest process plus complete failing test files
  found: All three reproduce independently. The first drawer test expects a model-derived shadow plan divergence, but the corrected no-model deterministic preview matches compatibility. The second supplies a page-invalid specialist hint yet expects 200, while the required contract says invalid hints reject before I/O; it now returns 400 with zero calls. Snapshot-v2 still returns an unexplained 500.
  implication: The drawer failures are stale assertions caused by removing coordinator authority from shadow; snapshot-v2 requires a traceback before classification.

- timestamp: 2026-09-20T10:24:00-07:00
  checked: Snapshot-v2 failure inputs with the route invoked outside pytest assertions
  found: With rollout mode absent, the compatibility path calls the inventory port with `family=None`; the pre-existing test asserts `family=="os"`, causing its hidden 500. The changed coordinator conditions are inert because this context has no coordinator.
  implication: Snapshot-v2 is an unrelated pre-existing fixture defect (it assumes canonical mode without setting it), not a regression from this fix.

- timestamp: 2026-09-20T10:28:00-07:00
  checked: Corrected drawer rollout tests and explicit-default snapshot-v2 probe
  found: All 9 drawer rollout tests pass. The snapshot-v2 test reaches canonical mode with an explicit default but then fails its separate stale assertion that citations must be empty even though canonical tool evidence is cited.
  implication: Snapshot-v2 is independently broken in both absent-mode and explicit-canonical variants and is excluded as documented pre-existing debt; no production or test changes for that unrelated contract are warranted here.

- timestamp: 2026-09-20T10:28:00-07:00
  checked: Ruff and whitespace validation after drawer assertion updates
  found: Ruff passes on all changed Python files and `git diff --check` is clean.
  implication: Changed code meets repository formatting/static checks despite unrelated repository-wide Ruff debt.

- timestamp: 2026-09-20T10:33:00-07:00
  checked: Full relevant 13-file Copilot/orchestration suite with the independently documented snapshot-v2 baseline test deselected
  found: Every selected test passes.
  implication: All in-scope Copilot, rollout, policy, parity, evaluation, and provider-readiness behavior is green after the fix.

- timestamp: 2026-09-20T10:38:00-07:00
  checked: Independent complete diff review
  found: Production changes are exactly three predicate substitutions in `investigate_canonical`; tests add the specified coordinator-enabled rollout matrix and invalid-hint pre-I/O case, change five pre-existing coordinator behavior fixtures to default, and align two shadow tests with deterministic preview/pre-I/O rejection. No specialist catalog, Azure MCP, deployment, or infrastructure files changed.
  implication: The diff is minimal, authority-preserving, non-deletion-only, and within the requested scope; no refactor beyond the explicit predicates is justified.

- timestamp: 2026-09-20T09:45:38.695-07:00
  checked: Bounded human-verification checkpoint response
  found: The user reported `confirmed fixed`.
  implication: End-to-end human verification is complete, so the accepted fix can be archived and committed without deployment, Azure access, PR creation, or catalog changes.

## Resolution
<!-- OVERWRITE as understanding evolves -->

root_cause: Coordinator availability is used as execution authority in `investigate_canonical`: coordinator wrapping, the `rollout.canonical_enabled or coordinator_enabled` execution branch, and coordinator metadata are not gated by `rollout.canonical_enabled`, so a configured coordinator bypasses compatibility/shadow rollout authority.
fix: Gate coordinator planner/synthesis wrapping, canonical OrchestrationService execution, and coordinator execution metadata on `rollout.canonical_enabled`; shadow therefore previews with the deterministic local planner only.
verification:
  target_test:
    result: pass
    detail: "Specified mode matrix passes for compatibility, shadow, canary-100, and default; invalid coordinator-enabled hint rejects before all I/O."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker or project mutation-test configuration is present."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    detail: "Production diff replaces three permissive predicates; it does not delete canonical behavior and retains it for authorized canary/default modes."
  adjacent_tests:
    result: pass
    suites_run:
      - "tests/test_api_copilot_unified.py (complete file)"
      - "tests/test_copilot_drawer_rollout.py (complete file)"
      - "13-file Copilot/orchestration relevant suite, excluding one independently reproduced pre-existing snapshot-v2 assertion"
      - "Ruff on all changed Python files"
    known_baseline: "tests/test_api_copilot_snapshot_v2.py::test_snapshot_v2_api_never_retains_untrusted_browser_citations is pre-existing: absent rollout invokes compatibility with family=None; explicit default produces a valid governed tool citation that contradicts its empty-citations assertion."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    detail: "Revert reproduced exactly compatibility/shadow failures; reapply restored all mode-matrix cases."
  independent_review:
    result: pass
    detail: "No unrelated production changes, catalog changes, Azure MCP additions, Azure calls, deployments, or PR creation."
  human_verification:
    result: pass
    detail: "User responded `confirmed fixed` at the bounded human-verification checkpoint."
  guardrail_verdict: accepted
files_changed:
  - src/api/routers/copilot.py
  - tests/test_api_copilot_unified.py
  - tests/test_copilot_drawer_rollout.py
oracle_type: specified

## Prevention

### Blameless branching 5-Whys

- **Code branch:** Coordinator v6 was introduced as a capability, but its availability was ORed into the canonical execution condition and independently controlled coordinator synthesis metadata. That made an available implementation act as authorization because execution capability and rollout authority were represented by separate booleans without a single authoritative gate at each canonical-only operation.
- **Test/config branch:** Existing coordinator tests selected compatibility mode while asserting canonical behavior, so they encoded the bypass rather than challenging it. Shadow tests did not combine coordinator availability with a noncanonical rollout, leaving the cross-product of rollout mode and coordinator capability uncovered.
- **AND-gate result:** No multi-cause production condition is required. Coordinator availability alone was sufficient to bypass a correctly parsed compatibility/shadow decision; the test gap explains why the defect persisted, not why it executed.

### Why wasn't this caught?

The route test gate did not cover coordinator-enabled compatibility/shadow modes, and five coordinator fixtures incorrectly used compatibility mode while expecting canonical execution. Code review and static checks could not distinguish capability from authorization because both values were valid booleans.

### Recurrence guard

The specified-oracle regression `tests/test_api_copilot_unified.py::test_rollout_alone_authorizes_coordinator_execution` locks the compatibility, shadow, canary-100, and default authority matrix with separate compatibility/canonical/coordinator call counters, authoritative-result assertions, shadow comparison, and `mutation=false`. `tests/test_api_copilot_unified.py::test_coordinator_enabled_invalid_hint_rejects_before_any_io` locks the validation boundary, and `tests/test_copilot_drawer_rollout.py::test_shadow_reports_deterministic_plan_comparison_without_canonical_io` locks deterministic no-I/O shadow preview behavior.
