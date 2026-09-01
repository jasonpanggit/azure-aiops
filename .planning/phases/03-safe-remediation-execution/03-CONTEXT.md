# Phase 3: Safe Remediation Execution - Context

**Gathered:** 2026-09-01
**Status:** Ready for planning

<domain>
## Phase Boundary

An approved recommendation can safely run as a bounded, observable Azure job and produce a verified, auditable outcome. This phase also closes a discovered prerequisite gap: Phase 2 built the full remediation intelligence layer (plans, approvals, business decisions) but never exposed it via HTTP — `src/api/app.py` mounts no `remediation` router, so `/api/remediation/*` returns 404 and the deployed web UI's remediation page shows no data. Phase 3 must both (a) wire the missing read/approval API surface and (b) add the new bounded execution capability on top of it.

</domain>

<decisions>
## Implementation Decisions

### Action Selection (EXEC-01)
- Only `controlled-patch-recovery` from the governed action catalog (`tests/fixtures/governed_remediation_catalog.json`) becomes executable in Phase 3.
- The other 5 catalog actions (critical-alert-containment, attack-path-segmentation-review, secure-score-control-remediation, exploitable-finding-remediation, configuration-baseline-recovery) remain recommendation/approval-only — no execution path for them yet.
- Rationale: patch recovery already has a tested, safety-constrained Azure adapter (`azure_adapter.py`) to build on; lowest-risk starting point.

### Execution Mechanism & API Wiring (EXEC-01, EXEC-02, EXEC-03)
- Create `src/api/routers/remediation.py` and mount it in `src/api/app.py`. This closes the pre-existing Phase 2 gap: expose plans, approvals, and business-decision reads over HTTP (fixing the 404s the deployed web UI currently hits).
- Add `POST /api/remediation/plans/{id}/execute` that triggers execution only for plans whose action type is `controlled-patch-recovery` and whose approval status is already approved.
- Execution logic generalizes `src/operations/patching/azure_adapter.py` rather than introducing a parallel/duplicate implementation. Preserve its existing safety constraints:
  - No fan-out — one execution run targets one resource only.
  - The target/resource selection is passed through verbatim from the already-approved plan (no widening).
  - Submission is not success — record `submitted` + `provider_job_id`; defer to the upstream Azure service as the source of truth.
  - Pinned ARM API versions per resource kind (Compute 2024-07-01, HybridCompute 2024-07-10, ContainerService 2024-05-01).
- `GET /api/remediation/plans/{id}/preview` (or equivalent) surfaces target set, ARM operation, preconditions, expected effect, and collateral impact before approval (EXEC-02).

### Job Durability (EXEC-04)
- Reuse the existing async job pattern from `src/api/routers/connections.py` (`sync_async` + `sync_state` polling) rather than building a new job-store abstraction.
- Persist an execution record with status enum: `queued` → `running` → `succeeded` / `failed` / `retrying` / `cancelled`.
- Expose `GET /api/remediation/executions/{id}` for polling, mirroring `GET /{connection_id}/health`.

### Verification & Rollback (EXEC-05, EXEC-06)
- Post-action verification polls the real upstream source of truth (Azure Update Manager / Arc-enabled server patch status, or AKS node pool upgrade status) rather than trusting the initial submission response.
- Verification records: actual state, outcome, failure details.
- Rollback/compensation for patch actions is inherently limited (patches generally cannot be cleanly "undone"). Phase 3 records rollback **guidance** (manual remediation steps / known safe next actions) rather than an automated rollback trigger. No auto-rollback in this phase.
- Retries (EXEC-06) are bounded, visible, and idempotent; a retry must re-validate the plan's approval context and target state haven't changed before resubmitting (guards against stale approvals).

### the agent's Discretion
- Exact schema/field names for the execution job record.
- Whether preview/approval reads live in the new `remediation.py` router directly or partially delegate to existing `src/intelligence/remediation/*` modules (prefer delegation — router should stay thin).
- Test depth/structure, as long as it follows existing `tests/` conventions for routers and adapters.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/operations/patching/azure_adapter.py` — the only existing state-mutating Azure adapter in the codebase; documents the safety constraints Phase 3 must preserve (no fan-out, verbatim allowlisted selection, "accepted not succeeded" semantics, pinned ARM API versions). Supports 3 target kinds already: Azure VM, Arc-enabled server, AKS node pool — directly matches `controlled-patch-recovery`'s scope.
- `src/api/routers/connections.py` (`sync_connection`, `connection_health`) — the established durable/async job pattern: queue → return immediately with `status: running` → client polls a `/health`-style endpoint for stage/progress until terminal state. Phase 3's execution job tracking should mirror this shape.
- `src/intelligence/remediation/*.py` (remediation_generator, approval_engine, business_decision, execution_simulator, rollback_planner, plan_repository, defender_correlation, dependency_analyzer, impact_estimator, plan_prioritizer, risk_analyzer, remediation_opportunity_engine, approval_decisions) — full Phase 2 business logic layer, currently only reachable by importing Python directly (no HTTP surface). The new router should call into these rather than duplicate logic.
- `tests/fixtures/governed_remediation_catalog.json` — governed action catalog (6 actions + 4 approval policies) built in Phase 2 (02-03). Needs re-inspection during planning to confirm exact field names for `action_id`/category/risk fields (prior inspection script reported `None` for some fields — likely a nested-path issue, not a data problem).

### Established Patterns
- FastAPI router-per-domain, mounted in `src/api/app.py` (see existing imports for compliance, connections, graph, inventory, multi_agent, network, operations, patching, planned, twin, vulnerability, context, copilot, governance, mcp, resource_health).
- Async/durable job state via a `sync_state`-like status object with `queued`/`running`/`succeeded`/`failed` (+ Phase 3 adds `retrying`/`cancelled`).
- Adapters that mutate Azure resources treat the ARM 2xx response as "accepted," never "succeeded" — success is always confirmed via a follow-up read from the owning Azure service.

### Integration Points
- New `src/api/routers/remediation.py` mounted alongside existing routers in `src/api/app.py`.
- Web UI at `web/src/app/remediation/page.tsx` (already built, 40KB, fully wired to expect these endpoints) — once the router exists, the existing frontend should light up largely unmodified; no major UI rework expected as part of Phase 3, just confirming the API contract matches what the page already calls.
- Execution endpoint delegates to a generalized `azure_adapter.py`-style function scoped to `controlled-patch-recovery` only.

</code_context>

<specifics>
## Specific Ideas

- The API-wiring gap (missing `remediation.py` router entirely) is treated as an in-scope prerequisite fix for Phase 3, not a separate quick patch — because Phase 3's execution UI cannot work at all without the underlying read/approval endpoints existing first.
- Keep the "no remediation for its own sake" principle established in Phase 2 intact: execution must only be reachable from an already-approved plan; no direct "run this action" bypass of the approval workflow.

</specifics>

<deferred>
## Deferred Ideas

- Execution for the other 5 governed action categories (critical-alert-containment, attack-path-segmentation-review, secure-score-control-remediation, exploitable-finding-remediation, configuration-baseline-recovery) — future phase, once patch-recovery execution is proven safe in practice.
- Automated rollback/compensation triggers — deferred; Phase 3 only records rollback guidance, not automated reversal.
- Domain coverage across VM/Arc/AKS beyond what `azure_adapter.py` already supports, and any cross-domain operational twin replay — belongs to Phase 4 (Domain Coverage and Operational Twin).

</deferred>
