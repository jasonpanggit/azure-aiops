# Phase 03-03 Summary

## Outcome

Closed the loop 03-02 left open: after a patch execution is submitted to Azure, HOG now polls the real upstream source of truth (the ARM long-running-operation URL Update Manager/AKS hand back at submission) to learn the actual outcome, rather than trusting the initial 2xx "accepted" response as success. Submission acceptance (`"running"`) and verified outcome (`"succeeded"`/`"failed"`) are now distinct, durably recorded states. Every execution carries manual rollback guidance from the moment it is created (`rollback_plan.rollback_actions`, never auto-triggered). Retries are bounded (`MAX_EXECUTION_ATTEMPTS = 3`), idempotent against an already-succeeded execution, and revalidate the plan's current approval/target state — sharing the identical four-check approval gate `execute()` already enforced — before ever resubmitting to Azure.

## Completed

- **Task 1 (tracer):** Created `src/intelligence/remediation/execution_verifier.py` with `ExecutionVerifier`, importing `TokenCredential`/`ARM_SCOPE` from `operations.patching.azure_adapter` rather than redefining the protocol. `verify(execution_record)` reads `provider_job_id` (the operation URL) from the record, returns `{"verifiable": False, "reason": "no provider job id"}` if absent, else GETs the URL and maps the raw ARM `status` field to `{"outcome": "succeeded"|"failed"|"running", "verified_state": <raw status>, "failure_details": <error body if failed>, "verifiable": True}`. A new `ExecutionVerificationUnavailable(RuntimeError)` (mirroring `PatchExecutionUnavailable`'s `capability` attribute) is raised only for network/HTTP failures during the poll — never for a legitimately-returned failed/in-progress ARM status, since those are valid answers, not errors. 6 tests cover succeeded, failed (with extracted error message), in-progress (twice, proving repeatability), a `"Running"` status alias, network failure, and the no-`provider_job_id` case.
- **Task 2:** Wired the verifier into `RemediationExecutionService`. `execute()` now stores `rollback_guidance` (from `plan["rollback_plan"]["rollback_actions"]`) on the execution record at creation time, regardless of eventual outcome. After `patching_service.trigger()` succeeds, the record transitions to `"running"` (not `"succeeded"`) whenever an `execution_verifier` is configured — the pre-existing 03-02 behavior of recording `"succeeded"` immediately is preserved only when no verifier is wired, so existing callers/tests are unaffected. Added `poll_verification(execution_id)`: fetches the record, calls `verifier.verify()`, and updates the store — a terminal outcome updates `status`/`verified_state`/`failure_details`; a still-running outcome is a no-op (record stays `"running"`, `verified_state` refreshed); a not-verifiable or verification-unavailable result leaves `status` unchanged but appends a note to `message` so the degraded state is visible without falsely claiming success or failure. Extended `RemediationExecutionStore`'s created-record shape with `rollback_guidance`, `verified_state`, and `failure_details` fields (defaulted to `""`) so every record — not just ones that have transitioned — carries them. 5 tests cover the running-not-succeeded transition, poll-to-succeeded, poll-no-op-while-running, rollback guidance persisted at creation, and a grep-based proof that `execution_verifier.py` contains no `.submit(`/`.trigger(` call (read-only, T-03-13).
- **Task 3:** Extracted the four approval-gate checks (action_id allowlist, approval status, action_version currency, expiry) from `execute()` into a shared `_check_approval_gate(plan)` private method, called by both `execute()` and the new `retry(execution_id)` — so the checks cannot drift apart (T-03-10). `retry()` rejects (never resubmits) an already-`"succeeded"` execution (`reason="already_succeeded"`, idempotency) and rejects once `attempt_count >= MAX_EXECUTION_ATTEMPTS` (`reason="max_attempts_exceeded"`, bounded, T-03-11). Otherwise it re-runs `_check_approval_gate` against the plan's *current* state (revalidation — a plan whose approval has gone stale since the original attempt is rejected even though the execution was itself once approved), transitions the record to `"retrying"` then `"running"`, increments `attempt_count`, and follows the identical submit/verify flow as `execute()` via a shared `_submit_and_record()` helper. Added `GET /plans/{plan_id}/executions` (list) and `POST /executions/{execution_id}/retry` to `src/api/routers/remediation.py`, following the same `OperatePrincipal`/scope-narrowing pattern as `execute_plan` (retry looks up the execution's plan and narrows to the caller's operate scope before invoking `service.retry()`, so an out-of-scope execution 404s the same way an out-of-scope plan does). `RemediationExecutionError` from `retry()` maps to `409 conflict`, matching `execute`'s existing translation. `GET /executions/{id}` already returns the full stored record (unchanged code path), which now includes `rollback_guidance`, `verified_state`, `failure_details`, and `attempt_count` because the store record itself carries them. 5 service-level tests cover stale-approval rejection on retry, idempotent no-op on an already-succeeded execution, attempt-count increment through a real submit/verify cycle, the max-attempts ceiling, and a source-inspection proof that both `execute` and `retry` call `_check_approval_gate`. 4 additional HTTP tests cover the new route mounts, the enriched `GET /executions/{id}` field set, and a 409 on retrying an already-succeeded execution via the API.

## Files

- `src/intelligence/remediation/execution_verifier.py` (new) — `ExecutionVerifier`, `ExecutionVerificationUnavailable`
- `src/intelligence/remediation/execution_service.py` (modified) — `MAX_EXECUTION_ATTEMPTS`, `_check_approval_gate()`, `_submit_and_record()`, `poll_verification()`, `retry()`, `execution_verifier` constructor param
- `src/intelligence/remediation/execution_store.py` (modified) — `rollback_guidance`/`verified_state`/`failure_details` added to the created-record default shape
- `src/api/routers/remediation.py` (modified) — `GET /plans/{plan_id}/executions`, `POST /executions/{execution_id}/retry`
- `tests/test_remediation_execution_verifier.py` (new) — 15 tests (Task 1 verifier + Task 2 lifecycle wiring)
- `tests/test_remediation_execution_retry.py` (new) — 5 tests
- `tests/test_api_remediation_execution.py` (modified) — 4 new tests appended (route mounts, enriched GET fields, retry-409)

## Verification

```
uv run pytest tests/test_remediation_execution_verifier.py tests/test_remediation_execution_retry.py tests/test_remediation_execution_service.py tests/test_api_remediation_execution.py -q
```
Result: **38 passed**, 0 failed.

Manually confirmed via the test suite (the TestClient/service-level tests exercise the same code paths a manual pass would):
- A submitted execution stays `"running"` until `poll_verification()` reports a terminal ARM outcome (`test_execute_leaves_status_running_not_succeeded_until_verified`, `test_poll_verification_is_noop_while_still_running`).
- A retry against a plan whose `action_version` changed since the original attempt is rejected with `reason="stale_approval"` (`test_retry_rejects_when_plan_approval_changed_since_original_attempt`).
- Retrying an already-succeeded execution is a no-op, rejected with `reason="already_succeeded"` (`test_retry_is_noop_for_already_succeeded_execution`, and at the API level `test_retry_already_succeeded_execution_is_409`).
- `GET /executions/{id}` includes `rollback_guidance`, `verified_state`, `failure_details`, and `attempt_count` (`test_get_execution_response_includes_verification_and_history_fields`).

Also re-ran the broader remediation regression surface for safety: `uv run pytest tests/ -k remediation -q` — 2 pre-existing failures found (`test_remediation_hardening.py::test_ontology_projection_is_referentially_complete`, `test_remediation_dependencies.py::test_dependency_analysis_includes_business_and_technical_context`). Confirmed via a throwaway worktree checked out at the 03-02 completion commit (`af45aad6`, before any 03-03 change) that both fail identically there — pre-existing, out of scope for this plan, not introduced by this work. Logged to `deferred-items.md` per the scope-boundary rule rather than fixed.

## Deviations from Plan

None — all three tasks implemented exactly as specified. The plan's own read_first steps (reuse `TokenCredential`/`ARM_SCOPE` from `azure_adapter.py`, reuse the existing `_error_message`-style ARM error extraction pattern, extract `_check_approval_gate` for `execute()`/`retry()` to share) were followed as written, not deviated from.

## Known Stubs

None. Every field in the execution record and API response is sourced from either the stored plan (`rollback_plan.rollback_actions`), the real `ExecutionVerifier`'s ARM poll response, or the existing `PatchingService`/`AzureArmPatchExecutionAdapter` stack's own return values — no placeholder or fabricated data.

## Threat Flags

None beyond what the plan's `<threat_model>` already registered and mitigated:
- T-03-09 (verifier trusting submission response as success) — mitigated: `"running"` is the post-submission state; only a terminal ARM poll result moves the record to `succeeded`/`failed`.
- T-03-10 (retry bypassing the approval gate on stale context) — mitigated: `retry()` re-runs the identical `_check_approval_gate` against the plan's current state, sharing code with `execute()`.
- T-03-11 (unbounded retry DoS) — mitigated: `MAX_EXECUTION_ATTEMPTS = 3` enforced and tested.
- T-03-12 (missing audit trail) — mitigated: `attempt_count`, `rollback_guidance`, `failure_details`, `verified_state` all persisted and exposed via `GET /executions/{id}` and `GET /plans/{plan_id}/executions`.
- T-03-13 (automated rollback accidentally triggered) — mitigated: no task calls or wires any automatic reversal action; verified by a grep-based test proving `execution_verifier.py` contains no `.submit(`/`.trigger(` call.

## Boundary

This closes the EXEC-05/EXEC-06 scope Phase 3 committed to: verified outcomes, recorded rollback guidance (never automated), and bounded/idempotent/revalidated retries. Not in scope (per the plan's own exclusion and the phase's locked boundary): an automated rollback trigger, and a background poller that calls `poll_verification()` on a schedule — `poll_verification()` is callable on demand (e.g. by an operator hitting a future poll endpoint or a scheduled job outside this phase), but no such scheduler was wired here, matching the plan's task scope exactly.
