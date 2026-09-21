---
status: awaiting_human_verify
trigger: "Continue the active remediation debug in /tmp/aiops-sre-snapshot-fix. Live execution RME-212F84FAF079F15F persisted execution_snapshot correctly contains subscription_id, approver, patch_ids [5122874], operation install_patches, but Azure SRE Agent accepted thread 54f65f04-ae29-4c1a-82bc-c6f78291da9d and produced no provider_operation/approval. Confirm and fix the manual filtering/schema omission so outbound approval.execution_snapshot includes subscription_id and approver, validates equality against top-level subscription_id/approved_by, and preserves existing snapshot_hash identity semantics."
created: 2026-09-21T04:22:44-07:00
updated: 2026-09-21T04:56:00-07:00
---

## Current Focus

hypothesis: Confirmed and fixed — the outbound nested approval snapshot now preserves subscription_id and approver, enforces top-level equality, and retains the original five-field hash identity.
test: Automated verification complete; live Azure SRE Agent submission intentionally not performed.
expecting: A future authorized live execution emits approval.execution_snapshot with all eight fields and downstream SRE can bind provider_operation/approval.
next_action: If operationally desired, validate the next authorized live SRE execution without deploying from this session.
known_pattern_candidate: "Data Shape / API Contract — missing required fields caused by legacy payload allowlists"
bug_class: Bohrbug
candidate_causes:
  - "code: manual allowlists omit subscription_id and approver"
  - "data: persisted execution_snapshot might omit or misname one of the fields"
and_gate: "likely no — code omission alone explains loss, but persisted live data will be checked against producer expectations"

reasoning_checkpoint:
  hypothesis: "Two legacy exact-field filters cause the live failure: execution_service.py drops subscription_id/approver before adapter handoff, and sre_agent_adapter.py rejects any nested snapshot containing them."
  confirming_evidence:
    - "The hardened service handoff regression fails with exactly two missing keys: subscription_id and approver."
    - "The hardened direct adapter payload regression fails in _validate_approval before token/HTTP because the complete persisted snapshot exceeds the six-field exact set."
    - "Persistence code deliberately adds subscription_id and approver outside the canonical hash fields."
  falsification_test: "The hypothesis would be false if the hardened tests observed both fields in the outbound request without changing the producer/adapter, or if the live persisted shape lacked either field; the former directly failed and the supplied live evidence plus persistence implementation establish the latter."
  fix_rationale: "Extending only the outbound projection/schema and adding cross-level equality repairs the lost provider contract; separating hash identity fields preserves all existing approval snapshot hashes."
  blind_spots: "No live SRE submission will be run per instruction; exact downstream acceptance is inferred from the stated SRE contract and validated locally at the HTTP boundary."
  candidate_causes:
    - "code: legacy producer and adapter exact-field allowlists omit the two newer projection fields"
    - "data: live persisted approval might lack the projection fields, contradicted by supplied execution evidence and current persistence implementation"
  and_gate: "no — the producer omission alone strips the fields, while the adapter allowlist independently blocks forwarding a complete snapshot; both must be corrected for a complete end-to-end fix, but either one is sufficient to prevent the desired outbound payload."

## Symptoms

expected: Outbound Azure SRE Agent approval.execution_snapshot includes subscription_id and approver, with values equal to top-level subscription_id and approved_by, while snapshot_hash identity remains unchanged.
actual: Live execution RME-212F84FAF079F15F persisted both fields, but accepted SRE thread 54f65f04-ae29-4c1a-82bc-c6f78291da9d produced no provider_operation/approval because outbound nested approval snapshot omitted them.
errors: No explicit error supplied; provider_operation/approval is absent after the SRE Agent accepted the thread.
reproduction: Submit the persisted execution snapshot for RME-212F84FAF079F15F through the Azure SRE Agent adapter and inspect the outbound approval payload/validation.
started: Observed in the referenced live execution/thread; exact introduction date not supplied.

## Eliminated

## Evidence

- timestamp: 2026-09-21T04:22:44-07:00
  checked: user-supplied live execution evidence
  found: Persisted execution_snapshot contains subscription_id, approver, patch_ids [5122874], and operation install_patches, while the accepted agent thread has no provider_operation/approval.
  implication: Persistence is not the loss point; inspect the outbound payload construction and adapter contract.

- timestamp: 2026-09-21T04:22:44-07:00
  checked: .planning/STATE.md scope
  found: Phase 03 remediation and live E2E work are completed and explicitly recorded; this is a focused remediation integration correction requested against current origin/main.
  implication: The requested fix is in repository scope and should remain narrowly limited to the SRE outbound approval contract.

- timestamp: 2026-09-21T04:22:44-07:00
  checked: worktree identity and cleanliness
  found: /tmp/aiops-sre-snapshot-fix is detached at b4cc911ab0e96cae06aa56fd2702fc9675ec0b81 with a clean working tree before this debug record.
  implication: Investigation can proceed without risking unrelated user changes.

- timestamp: 2026-09-21T04:34:00-07:00
  checked: execution_service.py _submit_and_record
  found: approval_context.execution_snapshot is rebuilt through an inline six-name tuple containing only target_id, patch_ids, target_kind, operation, action_version, and snapshot_hash.
  implication: subscription_id and approver are deterministically discarded after durable approval and before PatchingService/adapter submission.

- timestamp: 2026-09-21T04:34:00-07:00
  checked: sre_agent_adapter.py contract, validation, and hash implementation
  found: SRE_PATCH_APPROVED_SNAPSHOT_FIELDS contains exactly the same six names; schema and _validate_approval require exact set equality; _approved_snapshot_hash derives canonical identity by iterating that constant minus snapshot_hash.
  implication: The adapter cannot accept the complete persisted snapshot, and naively adding fields to the existing constant would incorrectly change snapshot hash semantics.

- timestamp: 2026-09-21T04:34:00-07:00
  checked: approval_decisions.py persistence and canonical hash
  found: build_execution_snapshot adds subscription_id outside _SNAPSHOT_FIELDS, RemediationDecisionStore.append adds approver outside the hash, and execution_snapshot_hash canonically hashes only the original five executable identity fields.
  implication: The persisted live shape is intentional; the complete fix must project both fields downstream while keeping a separate five-field adapter hash identity.

- timestamp: 2026-09-21T04:34:00-07:00
  checked: existing focused tests
  found: The service handoff fixture and direct adapter fixture both model only the legacy six-field nested snapshot; their two focused tests pass and therefore encode the omission instead of detecting it.
  implication: Regression tests must use the real eight-field persisted shape and assert cross-level equality failures.

- timestamp: 2026-09-21T04:34:00-07:00
  checked: knowledge-base.md
  found: sre-complete-without-submit is a related prior SRE contract-drift incident, but its root cause concerned action-free completion and semantic skill verification rather than loss of approval projection fields.
  implication: Treat it as adjacent regression context, not the root cause of this payload omission.

- timestamp: 2026-09-21T04:38:00-07:00
  checked: hardened pre-fix regression run
  found: 2 failures and 3 passes. The service assertion reports exactly subscription_id and approver missing; direct adapter submission rejects the complete eight-field snapshot in _validate_approval before HTTP. The canonical hash and mismatch refusal tests pass.
  implication: The hypothesis is confirmed at both independent loss/contract boundaries, and existing hash semantics already ignore the two projection fields at the approval layer.

- timestamp: 2026-09-21T04:41:00-07:00
  checked: first post-fix focused run
  found: Adapter payload/hash/equality cases pass (4 cases); service forwarding still reports subscription_id None because the test's _approve fixture, unlike production persistence, never populated subscription_id.
  implication: Code now forwards the key rather than omitting it; the remaining failure is an inaccurate regression fixture that must model the supplied live persisted shape.

- timestamp: 2026-09-21T04:43:00-07:00
  checked: focused post-fix regressions after fixture correction
  found: 5/5 cases pass: exact service handoff, exact outbound HTTP payload, unchanged hash identity, and subscription_id/approver mismatch refusal.
  implication: The fix addresses both confirmed boundaries and the specified validation/hash invariants.

- timestamp: 2026-09-21T04:47:00-07:00
  checked: complete SRE adapter module plus focused service handoff regression
  found: 60 cases ran with one failure. test_operator_identity_is_audit_data_and_never_used_as_bearer_token changed run.approved_by and approval.approved_by but left nested execution_snapshot.approver at the old identity, so the new required equality correctly rejected it before HTTP.
  implication: The production validation is working; this pre-existing test must update all three representations to preserve its intended valid-envelope setup.

- timestamp: 2026-09-21T04:47:00-07:00
  checked: Ruff and diff integrity
  found: Ruff passed on all four changed Python files; git diff --check passed; diff is additive and limited to two production files and two focused test files plus the debug record.
  implication: Static quality and no-op/deletion guardrail signals pass.

- timestamp: 2026-09-21T04:50:00-07:00
  checked: relevant pytest after adjacent fixture correction
  found: 60/60 cases pass across the complete SRE adapter module and focused execution-service handoff regression.
  implication: Target and adjacent-test guardrail signals pass.

- timestamp: 2026-09-21T04:50:00-07:00
  checked: mutation tooling availability
  found: No Stryker executable/configuration is available in the Python repository or web workspace.
  implication: Mutation signal is explicitly skipped; exact payload, mismatch, hash-invariance, adjacent, and revert/reconfirm tests carry verification.

- timestamp: 2026-09-21T04:53:00-07:00
  checked: revert phase of revert-and-reconfirm guardrail
  found: Path-limited stash removed only the two production changes; both root-cause regressions failed exactly as before (missing service keys and adapter exact-set rejection). The stash then restored and dropped cleanly.
  implication: The bug returns when this fix is absent; post-restore green confirmation remains.

- timestamp: 2026-09-21T04:56:00-07:00
  checked: post-restore regressions and final worktree
  found: Both root-cause regressions pass after restoration; git diff --check passes; no temporary gsd-sre-snapshot-revert-check stash remains; only the four intended Python files and this debug record are changed.
  implication: Revert-and-reconfirm passes and the worktree is ready for caller review without commit, deployment, or PR.

## Resolution

root_cause: Two legacy exact-field filters remained after subscription_id and approver were added to persisted approval snapshots: execution_service.py rebuilt the provider snapshot from six legacy keys, and sre_agent_adapter.py required/schema-validated exactly those six. The first stripped both fields and the second made a complete persisted snapshot invalid.
fix: Forward subscription_id and approver from the durable decision snapshot; extend the SRE nested approval schema/field set; validate both against top-level subscription_id/approved_by; compute snapshot_hash from a separate unchanged five-field identity tuple.
verification:
  oracle_type: specified
  target_test:
    result: pass
    details: "5/5 focused cases passed for exact service handoff, exact HTTP payload, hash invariance, and two mismatch refusals."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker executable/configuration is available for this Python codebase."
    mutant_killed: false
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: false
    details: "Production diff adds projection/schema/equality validation and separates hash identity; it does not delete or short-circuit behavior."
  adjacent_tests:
    result: pass
    suites_run:
      - "tests/test_patching_sre_agent_adapter.py"
      - "tests/test_remediation_verification_review_fixes.py::test_execution_passes_exact_durable_approval_to_patch_adapter"
    details: "60/60 pytest cases passed; Ruff passed on all four changed Python files."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  diff_check:
    result: pass
  guardrail_verdict: accepted
  residual_risk: "No live Azure SRE submission or deployment was performed; downstream acceptance must be observed on a future authorized live execution."
files_changed:
  - src/intelligence/remediation/execution_service.py
  - src/operations/patching/sre_agent_adapter.py
  - tests/test_remediation_verification_review_fixes.py
  - tests/test_patching_sre_agent_adapter.py
