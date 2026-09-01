# Phase 03-02 Summary

## Outcome

Added the single bounded execution capability this phase authorizes: `POST /api/v1/remediation/plans/{id}/execute`, reachable only for an already-approved `controlled-patch-recovery` plan. The execution path is a thin adapter over the existing `operations.patching` stack (`PatchingService.trigger` / `AzureArmPatchExecutionAdapter`) — no parallel/duplicate ARM-calling code was introduced. Execution is tracked as a durable job (`queued` → `running` → `succeeded`/`failed`), persisted at each transition so status survives a process restart and is pollable via `GET /api/v1/remediation/executions/{id}`.

## Completed

- **Task 1 (tracer):** Created `src/intelligence/remediation/execution_service.py` with `RemediationExecutionService.execute(plan_id, *, requested_by)`. The public method signature takes no target/patch/operation parameter at all — everything comes from the stored plan. Internally: (1) look up the plan, 404-equivalent via typed `RemediationExecutionError` if absent; (2) reject anything whose `action_id` isn't the literal `"controlled-patch-recovery"`; (3) find the latest decision, reject if none/not-approved, if `action_version` is stale, or if `expires_at` has passed; (4) resolve the plan's own `PatchTarget` and call `PatchingService.trigger` with patch selection read verbatim from the target's own available-patch allowlist (never from a caller parameter); (5) catch `PatchValidationError`/`PatchExecutionUnavailable` and surface them as a failed execution result rather than letting them propagate. 7 tests cover every rejection path plus the successful end-to-end trigger and the caught-adapter-failure case.
- **Task 2:** Created `src/intelligence/remediation/execution_store.py` with `RemediationExecutionStore`, mirroring `RemediationDecisionStore`'s exact persistence shape (path/document_store mutual exclusivity, revisioned write-with-retry, threading lock, schema version). `create()` rejects a second non-terminal (`queued`/`running`/`retrying`) execution for the same `plan_id`, returning the existing record's id instead of starting a second one — the EXEC-03 no-concurrent-execution guard. `update()` validates `status` against the known enum. Wired `RemediationExecutionService` to persist `queued` → `running` → terminal at each transition when constructed with an `execution_store`. 6 additional tests cover round-trip persistence, the concurrency guard (and that a new attempt is allowed after a terminal state), the full lifecycle through `execute()`, and `attempt_count` incrementing only on distinct resubmission.
- **Task 3:** Added `POST /plans/{plan_id}/execute` and `GET /executions/{execution_id}` to `src/api/routers/remediation.py`. `execute` narrows to the caller's operate scope and resolves the plan via the shared `_get_scoped_plan` helper from 03-01 before ever touching the execution gate, so an out-of-scope plan 404s rather than 409s. `RemediationExecutionError` → `409 conflict` (an unapproved/mismatched/wrong-action-type plan is a conflict with current state); `PatchValidationError`/`PatchExecutionUnavailable` → the same `ApiError` codes `patching.py`'s `create_patch_run` already uses. Added `execution_provider: Callable[[], Any] | None = None` to `ApiContext` (per-request resolution, matching the other intelligence-engine providers) and a `_remediation_execution_store()` OneLake-or-file singleton in `runtime.py` (`state/remediation_executions.json`), wired into the `ApiContext(...)` construction right after the existing `remediation_provider=` line. 6 HTTP-level tests cover the 409 paths, the successful execute-then-poll round trip, the out-of-scope 404, unknown-execution 404, and route-mount regression.

## Files

- `src/intelligence/remediation/execution_service.py` (new) — `RemediationExecutionService`, `RemediationExecutionError`
- `src/intelligence/remediation/execution_store.py` (new) — `RemediationExecutionStore`
- `src/intelligence/remediation/remediation_generator.py` (modified) — one additive field: generated plans now carry `action_id` (previously only `opportunity_type` was present; no existing field carried the catalog action's identity, so this was the minimal additive change called out as acceptable in the plan's read_first)
- `src/api/routers/remediation.py` (modified) — `POST /plans/{plan_id}/execute`, `GET /executions/{execution_id}`
- `src/api/models.py` — unchanged; confirmed no request body model was needed (`execute` takes no body beyond what `OperatePrincipal` already supplies)
- `src/api/dependencies.py` (modified) — `ApiContext.execution_provider` field
- `src/api/runtime.py` (modified) — `_remediation_execution_store()` singleton, `execution_provider=` wired into `ApiContext(...)`
- `tests/test_remediation_execution_service.py` (new) — 13 tests
- `tests/test_api_remediation_execution.py` (new) — 6 tests

## Verification

```
uv run pytest tests/test_remediation_execution_service.py tests/test_api_remediation_execution.py tests/test_patching_azure_adapter.py -q
```
Result: **30 passed**, 0 failed.

Also re-ran the broader remediation/patching HTTP surface for regression:
```
uv run pytest tests/test_remediation_execution_service.py tests/test_api_remediation_execution.py tests/test_patching_azure_adapter.py tests/test_api_remediation_router.py tests/test_api_remediation_approvals.py tests/test_api_patching_router.py -q
```
Result: **76 passed**, 0 failed.

`grep` confirms no `subprocess`/shell-execution import in any new file (EXEC-01).

Manually confirmed via the test suite (not a separate manual pass, since the TestClient exercises the same HTTP path):
- Executing a plan of any `action_id` other than `controlled-patch-recovery` → `409 conflict`
- Executing an unapproved `controlled-patch-recovery` plan → `409 conflict` with `details.reason == "not_approved"`
- Executing a valid, approved plan → `202`, `status: "succeeded"`, immediately pollable via `GET /executions/{id}` through terminal state

## Deviations from Plan

- **[Rule 2 - minimal additive field]** The plan's read_first anticipated that `action_id` might not be directly recoverable from the plan dict and authorized adding it as a one-line additive field if so. Confirmed during Task 1 that `RemediationGenerator.generate()`'s output carried `opportunity_type` (a human title, not unique per catalog entry — e.g. multiple actions could theoretically share an `opportunity_type` string) but not `action_id`. Added `"action_id": str(opportunity.get("action_id") or action.get("action_id") or "")` to the generator's output dict, sourced from the opportunity dict the generator already receives (which already carried `action_id` from `RemediationOpportunityEngine.identify()`). This is the exact minimal change the plan pre-authorized, not a schema expansion.
- No other deviations. All three tasks implemented as specified; the tracer feedback gate (Task 1's full test suite passing before Task 2 began) was satisfied before proceeding.

## Known Stubs

None. Every field in the execution record and API response is sourced from either the stored plan, the recorded approval decision, or the real `PatchingService`/`AzureArmPatchExecutionAdapter` stack's own return values — no placeholder or fabricated data.

## Threat Flags

None beyond what the plan's `<threat_model>` already registered (T-03-04 elevation of privilege, T-03-05 tampering, T-03-06 repudiation, T-03-07 DoS via concurrent execute — all mitigated and asserted by dedicated tests per the threat register's own disposition column).

## Boundary

This plan adds the one execution path Phase 3 authorizes, but it is not yet independently verified end-to-end against a real Azure environment or covered by outcome-verification (did the patch actually apply?) — that is 03-03's scope per the phase goal's own split (`Approved recommendation runs as bounded observable job with verified outcome`).
