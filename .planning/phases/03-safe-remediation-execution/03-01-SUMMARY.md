# Phase 03-01 Summary

## Outcome

Closed the Phase 2 API gap: `src/api/app.py` mounted no `remediation` router, so nothing under `/api/v1/remediation/plans/*` existed even though the full business logic (`RemediationPlanner`, `PlanRepository`, `ApprovalEngine`, `BusinessDecisionEngine`) has existed since Phase 2. Added a thin, read-only HTTP layer over that existing logic — list/get plans, preview (EXEC-02), approvals, and business-decision context — delegating entirely to `src/intelligence/remediation/*` with zero duplicated business logic.

## Completed

- **Task 1 (tracer):** Created `src/api/routers/remediation.py` with `GET /api/v1/remediation/plans` and `GET /api/v1/remediation/plans/{plan_id}`, mirroring `operations.py`'s existing `_require`/`_filter_scoped`/`_filter_rows` scope-filtering conventions (imported, not re-implemented). Mounted the router in `src/api/app.py` alongside the other `include_router(...)` calls.
- **Task 2:** Added `GET /plans/{plan_id}/preview` (EXEC-02: target, ARM operation, preconditions, expected effect, collateral impact — all derived from existing plan fields, no fabricated data), `GET /plans/{plan_id}/approvals` (approval_requirements + recorded decisions from `planner.repository.decisions.list`), and `GET /plans/{plan_id}/business-decision` (verbatim `business_decision` dict). Extracted a shared `_get_scoped_plan(context, scope, plan_id)` helper used by `get_plan` and all three new handlers to avoid duplicating not-found/scope logic. Preview sets `operation` from `operation_for_kind()` (reused from `operations/patching/models.py`) only for `controlled-patch-recovery` plans; all other opportunity types report `"not executable in this phase"` rather than inventing an ARM operation.
- **Task 3:** Added a mount regression test (`test_remediation_router_is_mounted_in_the_running_app`) asserting all 5 new paths appear in `app.routes` via `/openapi.json`, and that none of the web UI's pre-existing `operationsApi` routes (`/remediation-plans`, `/remediation-opportunities`, `/remediation/defender-cases`, `/remediation-plans/{plan_id}/decisions`) were renamed or removed. Confirmed via source read of `web/src/lib/services.ts` that the web UI only calls those routes, none of which collide with the new `/remediation/plans/*` prefix.

## Files

- `src/api/routers/remediation.py` (new) — 5 read endpoints
- `src/api/app.py` (modified) — import + `include_router(remediation_routes.router)`
- `tests/test_api_remediation_router.py` (new) — 11 tests

## Verification

```
uv run pytest tests/test_api_remediation_router.py tests/test_api_remediation_approvals.py tests/test_api_http.py -q
```
Result: **66 passed**, 0 failed. Also independently re-ran `tests/test_api_remediation_router.py` alone (11 passed).

`app.routes`/`/openapi.json` confirmed to include:
- `/api/v1/remediation/plans`
- `/api/v1/remediation/plans/{plan_id}`
- `/api/v1/remediation/plans/{plan_id}/preview`
- `/api/v1/remediation/plans/{plan_id}/approvals`
- `/api/v1/remediation/plans/{plan_id}/business-decision`

...alongside unchanged pre-existing `/api/v1/remediation-plans`, `/api/v1/remediation-opportunities`, `/api/v1/remediation/defender-cases`, `/api/v1/remediation-plans/{plan_id}/decisions`.

## Deviations from Plan

None — plan executed as written. Tasks 1 and 2 were implemented together in a single router file and committed as one atomic commit (rather than two separate commits) since Task 2 additions were small, tightly coupled to the Task 1 scaffolding (the `_get_scoped_plan` helper depends on Task 1's `_planner`/lookup pattern), and splitting them would have produced an intermediate commit with an incomplete/untested router. All three tasks' verification commands were run and pass; the tracer feedback gate (re-running `<verify>` end-to-end before Task 2) was satisfied by the full `tests/test_api_remediation_router.py -q` pass prior to adding Task 2 code.

## Known Stubs

None. All fields returned by preview/approvals/business-decision are sourced directly from existing `RemediationGenerator.generate()` output; no placeholder or empty-by-default values were introduced.

## Threat Flags

None beyond what the plan's `<threat_model>` already anticipated (T-03-01 information disclosure, mitigated via scope-filter + 404-not-403 pattern, asserted in `test_get_plan_outside_scope_is_404` and `test_preview_outside_scope_is_404`).

## Boundary

This plan is read-only. Nothing here executes ARM operations, records approvals, or performs any Azure change — it only surfaces Phase 2's existing draft-plan data over HTTP. Execution and verification are 03-02/03-03.
