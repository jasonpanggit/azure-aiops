---
status: investigating
trigger: "Urgent live remediation root-cause fix. PR #273 is merged/deployed. Fresh Playwright execution RME-6B2363AC2CA1E3FF invoked autonomous SRE thread 9842e930-d5e3-4a9d-9f4f-f42afe300881 for Arc vm1 KB 5122874. SRE performed exact applicability query then exactly one command: az connectedmachine install-patches ... --no-wait true --subscription ... . Tool status Completed, output empty, error null. SRE ended `submission_ambiguous` because no typed provider_operation. Azure Activity Log proves operation was created: operation Microsoft.HybridCompute/machines/installPatches/action, operationId/correlationId dd6f0ffe-a009-489d-8e46-b07045dfef46, Started 15:02:02Z, Accepted 15:02:03Z, exact vm1 resource. Diagnose root cause in latest main and implement the smallest robust fix so successful empty-output `--no-wait` submissions are recovered from authoritative bounded Activity Log evidence without ever retrying the write command. Preserve fail-closed behavior: exact target, operation type, attempt time window, unambiguous single correlation ID, accepted/succeeded status; multiple/missing matches remain submission_ambiguous. Update canonical SRE skill/trigger contracts, hashes/fixtures/runtime parser or verifier as needed. Add focused tests. Run focused pytest + Ruff. Create a feature branch if needed, commit conventional commit with Co-authored-by trailer, push, and create a PR. Report PR number/head and exact deployment/live synchronization requirements. Do not deploy. Stop after PR creation and validated handoff."
created: 2026-09-21T08:06:29.985-07:00
updated: 2026-09-21T08:34:00.000-07:00
---

## Current Focus
<!-- OVERWRITE on each update - reflects NOW -->

reasoning_checkpoint:
  hypothesis: "SreAgentExecutionVerifier treats SRE terminal success without typed provider_operation as submission_ambiguous because it has no read-only Azure Activity Log recovery path for successful empty-output --no-wait install-patches commands."
  confirming_evidence:
    - "sre_agent_verifier.py returns _completion_without_submission when composite outcome is succeeded and submitted_operation is None."
    - "The scalar Complete/success/succeeded path also returns _completion_without_submission when submitted_operation is None."
    - "No Activity Log query path exists in sre_agent_verifier.py; repository search found only generic ARM operation polling, not event query recovery."
    - "The SRE skill contract currently says completed thread proves submission only with exact typed provider_operation, matching the failing behavior."
  falsification_test: "A focused test where terminal SRE thread has no provider_operation but mocked Activity Log returns exactly one Accepted installPatches event for the exact target/window should currently fail as submission_ambiguous and pass only after recovery."
  fix_rationale: "Add a read-only ARM Activity Log recovery hook at the missing-provider-operation terminal boundary, constrained by exact subscription, target resource ID, installPatches operation name, attempt timestamp window, single correlation/operation ID, and accepted/succeeded status; do not retry the write command."
  blind_spots: "Live SRE thread payload may expose the CLI execution completedTimestamp; the durable remediation record may only expose attempt transition timestamps. The fallback therefore fails closed if no bounded timestamp can be derived."
  candidate_causes:
    - "code: verifier lacks bounded Activity Log reconciliation before classifying terminal success without provider_operation as ambiguous"
    - "contract: canonical SRE write skill/trigger contract forbids Activity Log recovery and says only typed provider_operation proves submission"
    - "data: Azure CLI --no-wait can return empty stdout/stderr while the provider still creates an Activity Log operation"
  and_gate: "yes - data shape (empty CLI output) plus code/contract gap are both required; a typed provider_operation would already succeed, and missing Activity Log recovery only manifests for empty-output no-wait submissions."
next_action: Commit, push, and open PR for the verified fix.

## Symptoms
<!-- Written during gathering, then IMMUTABLE -->

expected: A successful empty-output `az connectedmachine install-patches --no-wait true` submission should be recovered from authoritative bounded Azure Activity Log evidence when there is exactly one accepted/succeeded `Microsoft.HybridCompute/machines/installPatches/action` operation for the exact target and attempt window, without retrying the write command.
actual: SRE ended `submission_ambiguous` because the command completed with empty output/error and no typed `provider_operation`, even though Azure Activity Log proved a single operation/correlation ID was created for vm1.
errors: `submission_ambiguous`; tool status Completed, output empty, error null; no typed provider_operation.
reproduction: Trigger Arc vm1 KB 5122874 remediation using the autonomous SRE path where `az connectedmachine install-patches ... --no-wait true --subscription ...` returns empty stdout/stderr but Activity Log contains operationId/correlationId `dd6f0ffe-a009-489d-8e46-b07045dfef46`.
started: Observed after PR #273 deployment in Playwright execution RME-6B2363AC2CA1E3FF.

## Eliminated
<!-- APPEND only - prevents re-investigating -->

## Evidence
<!-- APPEND only - facts discovered -->

- timestamp: 2026-09-21T08:06:29.985-07:00
  checked: .planning/STATE.md scope summary
  found: Active Phase 4 is ready for planning, while recent completed session work and technical notes include remediation/SRE workflow hardening; no blocker entry prevents urgent remediation recovery fixes.
  implication: Live remediation root-cause fix is in scope as an urgent operational recovery change.
- timestamp: 2026-09-21T08:06:29.985-07:00
  checked: Common bug pattern categories
  found: Symptom maps to Data Shape/API Contract and Error Handling: successful provider write has no stdout payload but authoritative evidence exists outside the typed command-result contract.
  implication: Candidate causes include code contract gap in parser/reconciler and fixture/contract gap in SRE skill trigger expectations.
- timestamp: 2026-09-21T08:18:00.000-07:00
  checked: src/intelligence/remediation/sre_agent_verifier.py terminal handling
  found: Both composite terminal success and scalar Complete/success/succeeded return `_completion_without_submission(...)` when `_submitted_operation(...)` is absent; no Activity Log query is attempted.
  implication: The reported `submission_ambiguous` is deterministic for empty-output no-wait submissions unless the SRE thread emits typed provider_operation.
- timestamp: 2026-09-21T08:18:00.000-07:00
  checked: SRE skill/trigger contract
  found: Closed outcome currently states completed thread proves submission only with exact typed provider_operation and ambiguous submission terminates without retry.
  implication: Runtime and canonical contract must both be updated to permit bounded authoritative Activity Log recovery while preserving no-retry fail-closed behavior.
- timestamp: 2026-09-21T08:34:00.000-07:00
  checked: Focused regression tests
  found: `pytest -q tests/test_sre_agent_execution_verifier.py tests/test_patching_sre_agent_adapter.py tests/test_sre_agent_patch_skills.py` passed.
  implication: The exact Activity Log recovery succeeds for one accepted match and fail-closed variants remain ambiguous.
- timestamp: 2026-09-21T08:34:00.000-07:00
  checked: Focused Ruff
  found: `ruff check src/intelligence/remediation/sre_agent_verifier.py src/operations/patching/sre_agent_adapter.py tests/test_sre_agent_execution_verifier.py tests/test_sre_agent_patch_skills.py tests/test_patching_sre_agent_adapter.py` passed.
  implication: Touched Python files satisfy lint.

## Resolution
<!-- OVERWRITE as understanding evolves -->

root_cause: SRE terminal success verification had no bounded Azure Activity Log recovery path for successful empty-output `az connectedmachine install-patches --no-wait true` submissions that lacked typed provider_operation, so it deterministically classified them as `submission_ambiguous`.
fix: Added a read-only, fail-closed Azure Activity Log recovery path in `SreAgentExecutionVerifier` that only converts terminal/ambiguous SRE outcomes to submitted when exact target, installPatches operation type, bounded attempt window, accepted/succeeded status, and a single unambiguous correlation ID are present; updated canonical SRE skill/trigger contracts and SHA; added focused tests.
verification: Focused pytest and Ruff passed.
files_changed:
  - src/intelligence/remediation/sre_agent_verifier.py
  - src/operations/patching/sre_agent_adapter.py
  - infra/sre-agent/skills/aiops-install-selected-patches-v1/SKILL.md
  - infra/sre-agent/patch-trigger.v1.json
  - tests/test_sre_agent_execution_verifier.py
  - tests/test_sre_agent_patch_skills.py
