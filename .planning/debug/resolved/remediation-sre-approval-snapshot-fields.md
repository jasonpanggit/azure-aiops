---
status: resolved
trigger: "After clicking Start a new run on live /remediation, SRE Agent received the request but returned blocked_no_action -- immutable approval snapshot lacks required subscription and approver fields for equality validation. No Azure command was run."
created: "2026-09-21T03:11:00-07:00"
updated: "2026-09-21T03:32:00-07:00"
related: ".planning/debug/remediation-sre-trigger-missing.md (resolved -- distinct prior root causes: AUM assessment freshness, verifier liveness classification, browser patch-selection restore drift. This session is scoped narrowly to the approval snapshot's own field contract.)"
---

# Debug Session: Remediation SRE Approval Snapshot Missing Subscription/Approver Fields

## Symptoms

- Expected: After selecting patch KB5122874, approving, and choosing Run, the SRE Agent accepts the submitted approval snapshot, validates it against what it independently observes, and issues the install command.
- Actual: SRE Agent responded `blocked_no_action -- immutable approval snapshot lacks required subscription and approver fields for equality validation. No Azure command was run.`
- Timeline: Screenshot 2026-09-21T03:09:23 local, against live production lineage PR #265 (051342521e9ff0827df422032f0840cf5806271b), API revision `aiops-dev-api--pr265-05134252-r1`, web #264. Prior successful Playwright cycles submitted exact KB 5122874 before this regression surfaced.

## Current Focus

reasoning_checkpoint:
  hypothesis: "The Azure SRE Agent's own read/action skill performs an equality validation on the immutable approval snapshot it receives, and that snapshot -- built by build_execution_snapshot() and persisted by RemediationDecisionStore.append() -- has never carried subscription_id or approver, even though both values are already known at the points those functions run (PatchTarget.subscription_id, and the decision's approver parameter)."
  confirming_evidence:
    - "src/intelligence/remediation/approval_decisions.py: _SNAPSHOT_FIELDS = (target_id, patch_ids, target_kind, operation, action_version) -- the hashed identity fields, none of which is subscription_id or approver."
    - "build_execution_snapshot()'s returned dict (patch branch) is exactly {target_id, patch_ids, target_kind, operation, action_version, available_patches, snapshot_hash} -- no subscription_id despite `target.subscription_id` (operations/patching/models.py PatchTarget) being populated at that exact call site."
    - "RemediationDecisionStore.append() stores `copy.deepcopy(execution_snapshot)` verbatim under `execution_snapshot` for an approved decision; `approver` is recorded only as a sibling top-level field on the decision record, never merged into the nested snapshot object itself."
    - "execution_service.py's `_validated_execution_snapshot()` returns `decision.get('execution_snapshot')` unchanged (after hash/version checks) and that exact object is what gets persisted onto the execution record dispatched to the provider (`execution_store.create_or_get(execution_snapshot=snapshot, ...)`) -- i.e. this is the one object that reaches the provider boundary and would be read by an external validator."
    - "No SRE-specific adapter/dispatch code exists anywhere in this repository (confirmed via exhaustive grep across src/, api/, tests/, infra/, .planning/ for 'sre-agent', 'SreAgent', 'infra/sre-agent'); the only patch execution adapter in-repo is `operations/patching/azure_adapter.AzureArmPatchExecutionAdapter` (name='azure-arm'). The Azure SRE Agent is a separate, externally configured Azure resource whose skill independently reads/validates this application's approval/execution state -- consistent with the prior debug session's finding that the SRE read skill lives outside this repo."
  falsification_test: "This would be false if build_execution_snapshot() or RemediationDecisionStore.append() already projected subscription_id/approver onto the persisted snapshot object (they do not, per direct source read), or if some other in-repo code path merged them in before the snapshot reached the execution record (no such code path exists in execution_service.py/execution_store.py)."
  fix_rationale: "Add subscription_id (from the already-resolved PatchTarget) to build_execution_snapshot()'s output, and merge approver into the persisted snapshot at RemediationDecisionStore.append() time (the earliest point both the snapshot and a real approver identity coexist). Keep both fields out of _SNAPSHOT_FIELDS/execution_snapshot_hash: target_id already pins the subscription (it's an ARM resource id), so this is additive metadata for the external validator, not a new tamper surface, and it leaves every already-recorded pending approval's snapshot_hash and execute-time hmac revalidation unaffected -- no risk to already-approved live requests."
  blind_spots: "The SRE Agent's skill/read-model itself is not in this repository, so the exact shape/consumption path it uses to read the snapshot (direct API read vs. some other channel) could not be directly inspected here; the fix is scoped to guarantee this application's own persisted/exposed approval snapshot is self-contained and carries both fields, which is the only thing this repo can control and the only thing the reported error text implicates. No Azure command was run or deployed as part of this investigation."
  candidate_causes:
    - "code (confirmed): build_execution_snapshot()/RemediationDecisionStore.append() never projected subscription_id/approver onto the persisted snapshot object."
    - "data: none -- the target and approver values were always present upstream (PatchTarget.subscription_id, decision approver), just never carried into the snapshot."
    - "environment/provider: the SRE Agent's own equality validation is external and out of scope to change; it is presumed correct given it explicitly names the two missing fields it expects."
  and_gate: "No -- a single missing-field code defect (the snapshot never carrying subscription_id/approver) is sufficient on its own to produce this exact blocked_no_action message; no second condition is required."

bug_class: "Bohrbug: deterministic missing-field contract gap between this repo's persisted approval snapshot and the external SRE Agent's equality validation."
hypothesis: "Confirmed: build_execution_snapshot()/RemediationDecisionStore.append() never projected subscription_id or approver onto the immutable approval snapshot that flows to the execution record and the external SRE Agent."
test: "Completed against current origin/main (051342521e9ff0827df422032f0840cf5806271b) source, on an isolated worktree/branch (fix/sre-approval-snapshot-fields). Added red regression tests confirming the two fields were absent, implemented the additive fix, confirmed green, ran the full remediation/patching-focused pytest suite (all pass) plus a full-repo run (only pre-existing, unrelated failures in test_copilot_evaluation_v2.py/test_network_*/test_copilot_drawer_rollout.py etc., confirmed present on unmodified origin/main via git stash), and ruff check on touched files."
expecting: "Satisfied: root cause traced to exact source lines, minimal additive fix implemented without touching the security-relevant hash/identity fields, and validated via focused red/green tests plus regression sweep."
next_action: "Ready to plan/execute the live recovery: deploy this fix (new API image/revision), then re-run vm1 / KB5122874 through preview -> approve -> Run and confirm the SRE Agent thread no longer returns blocked_no_action on this ground. No deployment was performed in this debug session per scope."

## Evidence

- timestamp: "2026-09-21T03:15:00-07:00"
  checked: "Exhaustive grep across src/, api/, tests/, infra/, .planning/ for 'sre-agent', 'SreAgent', 'AzureAIAgent', 'thread_id' in the patching/remediation modules"
  found: "No SRE-specific adapter or dispatch code exists in this repository; the only real patch execution adapter is AzureArmPatchExecutionAdapter (name='azure-arm'). infra/sre-agent does not exist in this checkout."
  implication: "The Azure SRE Agent is an externally configured Azure product that independently reads/validates this app's persisted approval/execution state; the fix must be scoped entirely to what this repo controls -- the shape of the persisted approval snapshot -- not to any adapter/dispatch code."

- timestamp: "2026-09-21T03:18:00-07:00"
  checked: "src/intelligence/remediation/approval_decisions.py build_execution_snapshot() and _SNAPSHOT_FIELDS"
  found: "Snapshot dict = {target_id, patch_ids, target_kind, operation, action_version, available_patches, snapshot_hash}. target.subscription_id (PatchTarget field, already resolved at this call site) is never included."
  implication: "subscription_id is a one-line additive projection from data already in scope; safe to add without touching the hash."

- timestamp: "2026-09-21T03:20:00-07:00"
  checked: "src/intelligence/remediation/approval_decisions.py RemediationDecisionStore.append()"
  found: "`approver` is stored only as a top-level decision-record field; the nested `execution_snapshot` copy stored for an approved decision never receives it."
  implication: "approver must be merged into the persisted snapshot at append() time -- the earliest point a real approver identity exists alongside the snapshot -- so the object that eventually reaches the execution record/provider boundary carries it."

- timestamp: "2026-09-21T03:22:00-07:00"
  checked: "src/intelligence/remediation/execution_service.py _validated_execution_snapshot() and _submit_and_record()/execution_store.create_or_get()"
  found: "`_validated_execution_snapshot()` returns `decision['execution_snapshot']` unchanged after hash/version checks; that exact object is passed to `execution_store.create_or_get(execution_snapshot=snapshot, ...)`, becoming the execution record's own `execution_snapshot`."
  implication: "Fixing the object at RemediationDecisionStore.append() time is sufficient -- it flows unchanged through revalidation onto the execution record without any further code path to patch."

## Resolution

root_cause: "build_execution_snapshot() and RemediationDecisionStore.append() never projected subscription_id (available on the already-resolved PatchTarget) or approver (available as the append() parameter) onto the immutable approval snapshot object that is persisted, revalidated unchanged at execute time, and ultimately reaches the execution record read by the external Azure SRE Agent for its own equality validation -- causing it to reject the submission with blocked_no_action."
fix: "Added `subscription_id: target.subscription_id` to build_execution_snapshot()'s patch-snapshot dict, and merged `approver` into the persisted snapshot copy inside RemediationDecisionStore.append() for approved decisions. Both fields are excluded from `_SNAPSHOT_FIELDS`/`execution_snapshot_hash`, so every already-recorded pending approval's snapshot_hash and execute-time hmac revalidation are unaffected."
branch: "fix/sre-approval-snapshot-fields (isolated worktree at /tmp/aiops-sre-snapshot-fix, based on origin/main @ 051342521e9ff0827df422032f0840cf5806271b -- PR #265 lineage)"
commit: "77735e5062b8081010577d7d7a502b3ae04df948"
files_changed:
  - "src/intelligence/remediation/approval_decisions.py"
  - "tests/test_remediation_approval_decisions.py"
latest_tests:
  - "tests/test_remediation_approval_decisions.py::test_candidate_snapshot_is_server_derived_sorted_versioned_and_hashed (updated for the new subscription_id field + explicit hash-stability assertion)"
  - "tests/test_remediation_approval_decisions.py::test_candidate_snapshot_carries_subscription_id_for_provider_equality_checks (new, red->green)"
  - "tests/test_remediation_approval_decisions.py::test_approved_decision_snapshot_carries_the_recorded_approver (new, red->green)"
validation:
  - "Focused suite: python -m pytest tests/test_remediation_approval_decisions.py -q -> 17 passed"
  - "Broad suite: python -m pytest tests/ -k 'remediation or patching' (excluding known-unrelated pre-existing baseline failures) -> all passed (100%)"
  - "Full repo suite: only pre-existing failures unrelated to this change (test_copilot_evaluation_v2.py fixture/manifest issue, test_network_*, test_copilot_drawer_rollout.py, test_context_specialist_routing.py, test_global_namespace_placeholders.py, test_api_multi_agent.py) -- confirmed present on unmodified origin/main via `git stash` before/after comparison."
  - "ruff check src/intelligence/remediation/approval_decisions.py tests/test_remediation_approval_decisions.py -> All checks passed!"
not_deployed: "No Azure command was run and no deployment was performed. The fix exists only on the local branch/worktree above pending review and release."

## Recommended Live Recovery / E2E Steps

1. Review/merge `fix/sre-approval-snapshot-fields` (based on origin/main @ 051342521) into main via a PR.
2. Build and deploy a new API revision from the merged commit (e.g. `aiops-dev-api--pr<N>-<sha>-r1`), matching the existing PR #265 deployment pattern; no infrastructure/Terraform change is required (patch adapter selection and SRE Agent configuration are unaffected).
3. On the deployed environment, re-run the vm1 / KB5122874 flow: open `/remediation`, select the fix, review impact, approve (a *new* approval decision is required so the persisted snapshot picks up the new fields -- pre-existing approvals recorded before this fix will still lack them), choose Run.
4. Confirm in the SRE Agent's own thread/read model that the submitted approval snapshot now includes `subscription_id` and `approver`, and that it no longer returns `blocked_no_action` for the missing-fields reason (the AUM assessment-freshness and verifier-liveness findings from the prior, separately-resolved debug session remain independent blockers to watch for and are not addressed by this fix).
5. Confirm the execution record's `execution_snapshot` (as returned by `GET /executions/{id}` or the plan workflow route) shows both fields, and that `snapshot_hash`/approval-currency behavior for any *other* concurrently pending approval is unaffected (hash is unchanged by design).
