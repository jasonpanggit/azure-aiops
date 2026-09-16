---
status: resolved
trigger: "SRE Agent action-free Complete was misclassified as provider patch success after live trigger/skill schema drift prevented submission."
created: 2026-09-16T23:32:00+08:00
updated: 2026-09-17T01:02:00+08:00
---

## Symptoms

- expected: One canonical payload schema/operation is shared by API, trigger, and both skills; provider success requires typed exact write submission evidence; reconciliation evidence must postdate submission/terminal completion.
- actual: API sent schema 1.1/install_patches, trigger required 1.0, read skill required 1.4/applicability_check; thread returned failed_without_action but action-free Complete became succeeded, followed by reconciliation using evidence older than execution.
- errors: Live thread 7305a739-707a-4972-bd47-c56da2836fed returned failed_without_action; remediation execution RME-0AD1A242DAE59DE9 projected succeeded then reconciled_incomplete.
- timeline: Reproduced during Playwright E2E on 2026-09-16 after PRs 184/187/188 deployment.
- reproduction: Submit the canonical 1.1 VM2 single-patch payload to the stale live Review trigger, then poll its composite action-free completed thread.

## Current Focus

- hypothesis: Confirmed and fixed; canonical schema 1.1/install_patches is retained and all permitted focused offline acceptance signals pass.
- test: Complete.
- expecting: Complete.
- next_action: None; resolved and archived.
- bug_class: bohrbug
- technique: deterministic reproduction plus working backwards from succeeded/reconciled_incomplete; SBFL skipped because no failing automated test exists yet.
- reasoning_checkpoint:
    hypothesis: "The reported incident requires three defects: duplicated SRE schema/operation text can drift without semantic skill validation; the verifier treats Complete as success without exact write-submission evidence; and reconciliation accepts SRE evidence that predates submission/terminal completion."
    confirming_evidence:
      - "Verifier source and tests map scalar Complete and action-free composite isComplete=true directly to succeeded."
      - "reconcile_evidence and reconcile_ambiguous_submission use target_observed and KB intersection but never compare assessed_at to execution transitions."
      - "Rehashed read/write skill input drift passes canonical_skill_builder_artifact; 19 new focused regressions fail on the exact unsafe branches."
    falsification_test: "The hypothesis would be false if unchanged source rejected action-free/mismatched Complete, kept stale SRE evidence pending/ambiguous, or rejected rehashed schema/operation skill drift; the focused red run observed the opposite for every branch."
    fix_rationale: "Validate one exact structured lastMessage.content result against the immutable execution snapshot before success, route typed ambiguity into existing submission_ambiguous safeguards, derive a stable causal timestamp from immutable attempt transitions for SRE-only reconciliation, and derive semantic skill input checks from runtime constants."
    blind_spots: "The live service may serialize structured skill output as text rather than an object; this fix intentionally fails closed in that case, so operator compatibility needs later authorized live verification. No cloud or portal operation is permitted in this session."
    candidate_causes:
      - "code: status-only completion mapping and absent timestamp/semantic contract guards"
      - "config: independently deployed Review trigger and skill versions drifted from the checked-in 1.1/install_patches contract"
      - "data: the thread ended action-free and the available assessment timestamp preceded execution"
    and_gate: "yes — drift/action-free data triggers the unsafe verifier branch, and stale evidence becomes terminal only because the independent reconciliation-order guard is absent; all three contribute to the full observed sequence."
- tdd_checkpoint:

## Evidence

- timestamp: 2026-09-16T23:36:00+08:00
  checked: .planning/STATE.md active scope
  found: Phase 4 planning is active; prior Phase 03.1/03.6 work explicitly supports review-only VM remediation and retains exact container evidence gates with no container execution capability.
  implication: A narrow SRE VM patch safety fix and directly related docs/tests are in scope, while .planning/STATE.md, Phase 4 gates, and container execution semantics must remain untouched.

- timestamp: 2026-09-16T23:36:00+08:00
  checked: git status
  found: The worktree is on jasonpanggit-feat-generic-sre-patch-skills, ahead of its configured upstream by 13 commits, with only this debug session untracked.
  implication: The exact relationship between HEAD and local origin/main must be checked before source edits because the request explicitly names current origin/main.

- timestamp: 2026-09-16T23:38:00+08:00
  checked: HEAD, origin/main, and merge-base identities
  found: HEAD, local origin/main, and their merge-base are all 7801871aba734a312f39f17546a62da1a6b2671d; the branch-name/upstream status is misleading but content is exactly current local origin/main.
  implication: The baseline constraint is satisfied without checkout, reset, network access, or modification.

- timestamp: 2026-09-16T23:38:00+08:00
  checked: configured gsd-debugger agent skills and project skill indexes
  found: No debugger-specific agent skill was configured; gsd-debug applies the standard persistent scientific workflow, while archify is unrelated to this source bug.
  implication: No additional project rule file applies to the investigation/fix.

- timestamp: 2026-09-16T23:38:00+08:00
  checked: .planning/debug/knowledge-base.md semantic/keyword fallback
  found: No prior resolution matches SRE action-free completion, provider submission proof, or stale reconciliation evidence.
  implication: Continue open-ended investigation; no known-pattern candidate is promoted.

- timestamp: 2026-09-16T23:38:00+08:00
  checked: SBFL prerequisites
  found: The repository has tests, but the prefilled incident has no currently identified failing local test or per-test coverage spectrum.
  implication: Spectrum-based fault localization is skipped; deterministic source tracing and a focused regression repro are the correct route.

- timestamp: 2026-09-16T23:40:00+08:00
  checked: broad source/test/artifact search for incident vocabulary
  found: install_patches and provider_submitted occur extensively in remediation execution tests; no matching SRE-named artifact was found under the top-level skills directory.
  implication: The provider integration is likely represented as a generic remediation adapter rather than a file named after SRE; narrow by exact symbols and package ownership.

- timestamp: 2026-09-16T23:42:00+08:00
  checked: exact-term file localization
  found: SRE provider behavior is isolated in src/operations/patching/sre_agent_adapter.py with tests/test_patching_sre_agent_adapter.py and a sanitized trigger fixture; evidence reconciliation is owned by src/intelligence/remediation/execution_service.py and tests/test_remediation_evidence_reconciliation.py.
  implication: Working backwards can now test the two reported divergence points directly instead of searching generic remediation code.

- timestamp: 2026-09-16T23:45:00+08:00
  checked: SRE submission adapter, focused tests, patch models/service, and sanitized trigger fixture
  found: The API adapter locks envelope schema 1.1 and top-level operation install_patches, while its declared bound read/write skill contracts both use output schema 1.0 with operations read_patch_applicability/install_selected_patches; the fixture prompt independently repeats these values instead of deriving one canonical contract.
  implication: The reported deployed trigger/read-skill drift is structurally possible because constants are duplicated across source and external artifacts; source has no equality check against the live/deployed trigger or skill definitions.

- timestamp: 2026-09-16T23:45:00+08:00
  checked: SRE adapter submission result semantics
  found: A 202 response with success true and a bounded threadId records only trigger acceptance and returns state submitted; it does not claim provider patch success.
  implication: The action-free succeeded projection occurs downstream in thread verification, not in the submission adapter itself.

- timestamp: 2026-09-16T23:48:00+08:00
  checked: src/intelligence/remediation/sre_agent_verifier.py and poll_verification success transition
  found: _composite_outcome returns succeeded whenever lastMessage.isComplete is true and no warning/critical actions exist, and the legacy string status Complete also returns succeeded; neither path requires a typed write-skill result, exact command/submission evidence, operation identity, selected KBs, or provider submission timestamp.
  implication: An action-free or refusal completion deterministically becomes execution status succeeded, exactly matching the incident.

- timestamp: 2026-09-16T23:48:00+08:00
  checked: reconcile_evidence and existing reconciliation tests
  found: A target_observed result is immediately classified clean/incomplete from selected KB intersection; assessed_at is copied as display data but never parsed or compared to execution timing. Existing tests explicitly accept 12:05 evidence for a 12:00 execution but have no stale/pre-submission negative.
  implication: Evidence older than submission or terminal provider completion can produce terminal reconciliation, confirming the reported ordering defect.

- timestamp: 2026-09-16T23:52:00+08:00
  checked: SRE verifier tests
  found: Existing regressions explicitly require legacy string Complete and a composite with isComplete true, no actions, empty incident status, and even content "failed" to map to succeeded.
  implication: The regression suite codifies the unsafe assumption and must be updated to require typed structured submission evidence while retaining Pending Review/provider-active behavior.

- timestamp: 2026-09-16T23:52:00+08:00
  checked: patch-skill/readiness contract tests
  found: Offline tests compare trigger payloadSchema to the runtime adapter and bind skills by raw hashes, but the canonical values are still repeated in adapter source, preflight script, trigger JSON, and skill prose; readiness only proves each repeated copy matches its expected local hash/body.
  implication: Hash locking detects mutation of one checked artifact but not intentional coordinated drift or mismatch against an independently versioned live skill contract; one shared semantic contract assertion is needed.

- timestamp: 2026-09-16T23:58:00+08:00
  checked: execution submission and transition persistence
  found: Successful trigger acceptance is durably recorded as a running transition with provider_job_id/provider_submitted; verifier completion is a later first succeeded transition. Each current attempt retains immutable ordered transition timestamps even after pending reconciliation updates.
  implication: A stable lower bound can be derived without schema migration as the latest of the submission-handle transition and the first terminal transition; repeated reconciliation attempts will not move that boundary.

- timestamp: 2026-09-16T23:58:00+08:00
  checked: canonical trigger, read skill, write skill, and operator documentation
  found: Checked-in artifacts currently state input schema 1.1/install_patches consistently, but the preflight semantic skill validator does not require those input markers and the write skill leaves its structured outcome fields unspecified. Documentation explicitly says Complete alone is provider completion.
  implication: The narrow source fix should make canonical input markers code-owned/semantically validated, define an exact typed write-submission result, and revise verifier/docs so Complete alone cannot advance.

- timestamp: 2026-09-17T00:02:00+08:00
  checked: focused pre-change test baseline
  found: 216 focused SRE adapter/verifier/skill/readiness/reconciliation tests passed.
  implication: The repository is internally green while encoding the unsafe assumptions; new root-cause regressions are required to reproduce the incident locally.

- timestamp: 2026-09-17T00:08:00+08:00
  checked: agent-authored regression design
  found: Added specified-oracle tests for action-free Complete, exact typed submission equality across every immutable field, submitted/refused/ambiguous outcomes, stale/fresh SRE evidence ordering, ambiguous SRE promotion, non-SRE compatibility, and rehashed skill input drift. Timestamp neighbors are terminal-minus-1s and terminal-plus-1s.
  implication: The tests exercise the root predicates rather than only the incident message and include the boundary neighbors needed to detect off-by-one/order mistakes.

- timestamp: 2026-09-17T00:12:00+08:00
  checked: focused pre-fix regression run
  found: 19 tests failed exactly as predicted. Action-free, mismatched, failed_without_action, and submission_ambiguous completed threads all returned succeeded; stale SRE evidence reconciled clean or promoted ambiguity; both rehashed skill contract drifts passed validation.
  implication: Each root-cause branch is directly and deterministically reproduced before production changes; valid/fresh and non-SRE held-out cases did not appear in the failure list.

- timestamp: 2026-09-17T00:23:00+08:00
  checked: focused post-source-fix regression run
  found: All 65 verifier, reconciliation, and semantic skill-contract tests passed.
  implication: The narrow code guards satisfy the driving regressions before artifact/docs synchronization.

- timestamp: 2026-09-17T00:33:00+08:00
  checked: first full focused verification and Ruff
  found: 3 pre-existing unavailable-thread deadline tests failed because an unrelated hunk changed verification_timed_out to submission_ambiguous; Ruff found two unused E402 noqa comments and one extraneous-parentheses issue in that hunk.
  implication: The fix is not yet accepted; narrow the diff to preserve established unavailable-thread semantics rather than updating unrelated tests.

- timestamp: 2026-09-17T00:37:00+08:00
  checked: narrowed focused test and Ruff rerun
  found: All 259 focused tests passed and Ruff reported "All checks passed".
  implication: Driving regressions, adjacent Pending Review/unavailable-thread lifecycle tests, readiness/hash tests, and Python static checks are green after preserving prior deadline behavior.

- timestamp: 2026-09-17T00:41:00+08:00
  checked: canonical render, changed paths, diff check, and mutation tooling
  found: Canonical render is deterministic at 6bf0298022e720915be3d0f18702ca9a6b7a3bc3d8f4c4af6ae57c9d9c6c32ce with liveMutationPerformed false; git diff --check passed; no STATE/Phase 4 path changed; the diff adds validation and regressions rather than deleting behavior; no Stryker or Python mutation runner is configured.
  implication: Static/no-op/scope guardrails pass; mutation signal is formally skipped, while targeted revert-and-reconfirm will provide causal evidence.

- timestamp: 2026-09-17T00:43:00+08:00
  checked: targeted verifier-guard revert
  found: Bypassing only the scalar Complete proof condition made the action-free regression fail with actual outcome succeeded instead of failed; the guard was immediately restored.
  implication: The exact submission-proof guard, not an unrelated change, causally prevents the reported false success.

- timestamp: 2026-09-17T00:45:00+08:00
  checked: targeted reconciliation-order revert
  found: Bypassing only the SRE timestamp comparison made all five stale/equal/naive/malformed/missing cases reconcile clean instead of pending; the guard was immediately restored.
  implication: The causal assessed_at boundary directly prevents stale terminal reconciliation and its malformed-timestamp variants.

- timestamp: 2026-09-17T00:47:00+08:00
  checked: targeted semantic-contract revert
  found: Bypassing only the runtime-derived skill input marker allowed both rehashed schema/operation drifts to validate, causing both regressions to fail; the guard was immediately restored.
  implication: The semantic check, independent of raw hash locking, causally prevents coordinated contract drift.

- timestamp: 2026-09-17T00:51:00+08:00
  checked: final fully reapplied fix-acceptance guardrail
  found: All 259 focused tests passed; focused Ruff passed; canonical offline render returned hash 6bf0298022e720915be3d0f18702ca9a6b7a3bc3d8f4c4af6ae57c9d9c6c32ce with liveMutationPerformed=false; git diff --check and forbidden-path checks passed.
  implication: The narrow source/artifact/docs fix is accepted offline; only real authorized SRE-thread verification remains unavailable under this session's constraints.

- timestamp: 2026-09-17T00:55:00+08:00
  checked: continuation scope, configured skills, baseline identity, and changed paths
  found: The user retained canonical 1.1/install_patches and authorized offline completion; no debugger agent skill override is configured; HEAD still exactly equals local origin/main at 7801871; only the 13 declared fix/test/artifact paths plus this debug record are changed, with no STATE or Phase 4 path.
  implication: The continuation remains in scope and can close after one focused offline reconfirmation without live/cloud work or unrelated edits.

- timestamp: 2026-09-17T00:58:00+08:00
  checked: continuation focused tests and static analysis
  found: All 259 tests in the six targeted SRE verifier/adapter/skill/readiness/reconciliation/lifecycle suites passed in 2.82 seconds; focused Ruff reported all checks passed.
  implication: The minimal fix still satisfies its regressions and preserves adjacent Pending Review, unavailable-thread, exact-KB, and non-SRE behavior.

- timestamp: 2026-09-17T01:00:00+08:00
  checked: canonical offline render and final scope guard
  found: The render retained artifact/schema 1.1 and operation install_patches, produced canonical hash 6bf0298022e720915be3d0f18702ca9a6b7a3bc3d8f4c4af6ae57c9d9c6c32ce, and reported liveMutationPerformed=false; git diff --check passed and no STATE or Phase 4 path changed.
  implication: All user-permitted acceptance checks pass without network, Azure, portal, CLI, cloud, commit, push, or PR activity; the session is complete.

- timestamp: 2026-09-17T01:02:00+08:00
  checked: resolved-session archival and knowledge-base recurrence record
  found: The session was moved to .planning/debug/resolved and the tested root-cause/fix/guard pattern was appended to .planning/debug/knowledge-base.md; no commit was created per the explicit constraint.
  implication: Persistent debug state and future known-pattern recall are complete.

## Eliminated

- hypothesis: The SRE submission adapter itself marks HTTP trigger acceptance as patch success.
  evidence: submit() returns state submitted only, and _submit_and_record persists running; the first succeeded transition is exclusively created by poll_verification after the unsafe verifier outcome.
  timestamp: 2026-09-17T00:12:00+08:00

- hypothesis: A race or intermittent cloud response is required for the false success.
  evidence: Pure offline MockTransport tests reproduce the false succeeded result deterministically from a fixed action-free completed payload.
  timestamp: 2026-09-17T00:12:00+08:00

## Resolution

- root_cause: "AND-gate: deployed SRE schema/operation copies can drift because skill validation is hash-only rather than semantically tied to runtime 1.1/install_patches; SRE thread verification treats Complete/action-free completion as succeeded without exact typed write-submission evidence; SRE evidence reconciliation has no causal assessed_at lower bound and accepts pre-submission/pre-terminal data."
- fix: "Semantically tie both skill input contracts and trigger artifactVersion to runtime 1.1/install_patches; require an exact schema-1.0 bound-write provider_operation before any Complete/success thread can advance; persist unproven completion as submission_ambiguous and explicit failed_without_action as failure; require SRE-only assessed_at to strictly postdate immutable submission and first-terminal transitions; synchronize the reviewed write skill, trigger prompt/hashes, fixtures, and operator docs."
- verification:
    target_test:
      result: pass
      details: "259 focused tests passed, including the new action-free completion, exact provider_operation, timestamp boundary, semantic contract drift, Pending Review, unavailable-thread, and non-SRE regressions."
    mutation_check:
      result: skipped
      reason_if_skipped: "No Stryker or Python mutation runner is configured."
      mutant_killed: "Manual targeted reversions of all three root guards were killed by 1 verifier test, 5 timestamp tests, and 2 semantic-contract tests."
    no_op_deletion:
      result: pass
      deletion_justified_by_rca: false
      details: "Diff adds strict validation/state handling and regression coverage; it is not deletion-only and does not weaken assertions."
    adjacent_tests:
      result: pass
      suites_run:
        - tests/test_patching_sre_agent_adapter.py
        - tests/test_sre_agent_execution_verifier.py
        - tests/test_sre_agent_patch_skills.py
        - tests/test_sre_agent_patch_readiness.py
        - tests/test_remediation_evidence_reconciliation.py
        - tests/test_remediation_verification_review_fixes.py
      static_checks:
        - "focused Ruff: pass"
        - "canonical trigger render/hash: pass"
        - "git diff --check and no STATE/Phase 4 changes: pass"
    revert_and_reconfirm:
      result: pass
      bug_returned_on_revert: true
      fixed_on_reapply: true
      details: "Targeted bypasses independently restored false Complete success, stale clean reconciliation, and rehashed schema/operation drift; restoring each guard returned the complete focused suite to green."
    environment:
      offline: pass
      authorized_live_sre: not_applicable_by_constraint
      reason: "The user explicitly prohibited network/Azure/portal/CLI/cloud operations and authorized completion from focused offline source validation."
    guardrail_verdict: accepted
- oracle_type: specified
- files_changed:
    - src/intelligence/remediation/sre_agent_verifier.py
    - src/intelligence/remediation/execution_service.py
    - src/operations/patching/sre_agent_adapter.py
    - scripts/preflight_sre_agent_patch_execution.py
    - infra/sre-agent/patch-trigger.v1.json
    - infra/sre-agent/skills/aiops-install-selected-patches-v1/SKILL.md
    - docs/SRE_AGENT_PATCH_EXECUTION.md
    - tests/test_sre_agent_execution_verifier.py
    - tests/test_remediation_evidence_reconciliation.py
    - tests/test_sre_agent_patch_skills.py
    - tests/test_sre_agent_patch_readiness.py
    - tests/fixtures/sre_agent_patch_trigger.sanitized.json
    - tests/fixtures/sre_agent_patch_secret.sanitized.json

## Prevention

- branch_code:
    why: "Completion status was treated as proof of provider submission, and reconciliation checked selected-KB membership without causal time ordering."
    actionable_condition: "Require an exact typed provider_operation bound to the immutable execution snapshot, and require SRE assessment evidence to strictly postdate immutable submission/first-terminal transitions."
- branch_config:
    why: "Trigger and skill copies could be rehashed while drifting from the runtime envelope contract."
    actionable_condition: "Derive semantic skill/trigger checks from the runtime-owned schema 1.1 and install_patches constants instead of trusting hashes alone."
- branch_data:
    why: "The incident supplied an action-free completed thread and pre-execution assessment data, both previously accepted as positive evidence."
    actionable_condition: "Fail closed on absent/mismatched provider_operation and stale, equal, naive, malformed, or missing SRE assessed_at values."
- why_not_caught: "Existing tests explicitly encoded scalar/action-free Complete as success and had no semantic skill-input or stale SRE evidence boundary gate."
- recurrence_guard: "The 259-test focused suite now includes specified-oracle regressions in tests/test_sre_agent_execution_verifier.py, tests/test_remediation_evidence_reconciliation.py, tests/test_sre_agent_patch_skills.py, and tests/test_sre_agent_patch_readiness.py; runtime guards fail closed at the verifier, semantic preflight, and SRE-only reconciliation boundaries."
