---
phase: 03-safe-remediation-execution
reviewed: 2026-09-03T14:46:49Z
depth: deep
scope: cross-phase (Phase 1 evidence → Phase 2 recommendation/approval → Phase 3 execution → Phase 6-10 inventory/identity/Fabric)
files_reviewed: 27
files_reviewed_list:
  - src/api/routers/remediation.py
  - src/api/routers/operations.py
  - src/api/routers/patching.py
  - src/api/runtime.py
  - src/api/providers.py
  - src/api/rbac.py
  - src/api/dependencies.py
  - src/intelligence/remediation/remediation_planner.py
  - src/intelligence/remediation/remediation_opportunity_engine.py
  - src/intelligence/remediation/remediation_generator.py
  - src/intelligence/remediation/defender_correlation.py
  - src/intelligence/remediation/action_catalog.py
  - src/intelligence/remediation/approval_decisions.py
  - src/intelligence/remediation/approval_engine.py
  - src/intelligence/remediation/plan_repository.py
  - src/intelligence/remediation/execution_service.py
  - src/intelligence/remediation/execution_store.py
  - src/intelligence/remediation/execution_verifier.py
  - src/intelligence/patch/patch_intelligence.py
  - src/operations/patching/service.py
  - src/operations/patching/azure_adapter.py
  - src/operations/patching/store.py
  - src/semantic/live_operations.py
  - src/onboarding/sync.py
  - src/onboarding/discovery_source.py
  - web/src/app/remediation/page.tsx
  - web/src/lib/services.ts
findings:
  critical: 7
  warning: 11
  info: 3
  total: 21
status: issues_found
---

# Phase 03: Safe Remediation Execution — Deep Cross-Phase Code Review

**Reviewed:** 2026-09-03T14:46:49Z
**Depth:** deep (upstream + downstream call-chain tracing)
**Files Reviewed:** 27 (plus tests under `tests/test_remediation_*`, `tests/test_api_remediation_*`, `tests/test_patch_*`, `web/src/app/remediation/page.test.tsx`)
**Status:** issues_found

## Summary

The remediation stack is unusually disciplined at the *boundary* level: the provider adapter is the only mutating Azure call site, snapshots are server-owned and hash-bound, the execution store is durable with compare-and-set claims, and the verifier refuses to infer success from a 2xx. Those invariants hold under inspection.

The defects are not at the boundary — they are in **identity and lifecycle**. The system treats a remediation plan as an ephemeral *view* recomputed from live Azure Resource Graph on every read, while approvals, execution claims, retry budgets, and the audit trail are durable *objects keyed on that view's identity*. In the live (production) path that identity is a hash of the current missing-KB set. The consequences compound: a successful patch changes the plan's identity, which makes its own execution record unreachable and its verification unrunnable; a blocked patch leaves the identity frozen, which permanently exhausts the retry budget with no operator recovery. Both failure modes are visible in `.planning/debug/remediation-e2e.md` (execution `RME-28E8C12074CE04D4`, attempt 3, `retryable=false`, `remaining_attempts=0`, `provider_job_id` empty after three failures that never reached the provider).

Governance has a second, independent gap: the approval *requirements* the operator is shown are never reconciled against the decisions actually recorded, separation of duties exists only as a string comparison inside the patch adapter path (the Defender-configuration family has none), and approving and executing require the identical `operate` permission — so separation of duties is structurally unenforceable, not merely disabled for demo.

Live evidence from this session (403 → RBAC granted → 409 Arc agent Disconnected) is not an environment anecdote; it is the class of failure the design does not model. Nothing in the preview, snapshot, or eligibility projection asserts *target readiness*, and every provider rejection — permission, precondition, transient — collapses into one `PatchExecutionUnavailable` that burns a scarce attempt.

---

## Current End-to-End Architecture and State Transitions

**Upstream (Phases 1, 6–10).** `AzureResourceGraphSource.fetch` runs ARG queries in a bounded pool (120 s batch cap, `discovery_source.py:44-68`), converting failures into `{"status":"failed","provider_status":"failed"}` sentinel rows. `SubscriptionSyncService._run_publish_with_timeout` (`sync.py:331-386`) bounds Fabric publish at 120 s and raises `TimeoutError` rather than hanging. `PatchIntelligence.from_semantic_sources` (`patch_intelligence.py:375-412`) now drops evidence whose target is absent from inventory and logs a `_LOGGER.warning` coverage-gap count instead of hard-failing the provider. `ProviderRuntime` (`providers.py:93-265`) keeps a working provider on refresh failure and marks it `degraded` with a reason.

**Recommendation.** Two divergent generators exist. The Fabric/snapshot path (`RemediationPlanner.generate_plans` → `RemediationOpportunityEngine.identify` → `RemediationGenerator.generate`) derives `plan_id = RMP-sha256(resource_key|action_id)` and an evidence-sensitive `action_version`. The live path (`LiveRemediationPlanner._plan`, `live_operations.py:599-664`) — the one actually serving deployed `/remediation` — derives `plan_id = live-patch-sha256({target, sorted(missing_kbs)})` and an evidence-*insensitive* `action_version`. `PlanRepository` is in-memory only (`plan_repository.py:31,36-42`); every read route calls `generate_plans()` again.

**Governance.** `GET /plans/{id}/preview` builds a server-owned snapshot (`approval_decisions.build_execution_snapshot`) hashed over `target_id|patch_ids|target_kind|operation|action_version`. `POST /remediation-plans/{id}/decisions` re-derives the snapshot, `hmac.compare_digest`s it against the client's `preview_snapshot_hash`, and appends an immutable decision to a durable, revisioned store. `GET /plans/{id}/workflow` projects five steps plus `approval.current` (snapshot-hash equality only).

**Execution.** `POST /plans/{id}/execute` narrows scope → resolves the plan → `_check_approval_gate` (action allowlist, approved decision, `action_version` currency, expiry, business eligibility, snapshot integrity) → `ExecutionStore.create_or_get` claims a durable identity `plan_id|snapshot_hash|action_version` → `queued → running` → `_resolve_target` revalidates target/patch allowlist → `PatchingService.trigger` → `AzureArmPatchExecutionAdapter.submit` (single ARM POST) → status stays `running` with `provider_job_id` = the async-operation URL.

**Downstream.** `poll_verification` is invoked only from two HTTP read paths (`remediation.py:265`, `remediation.py:475`), maps ARM envelope `status` to terminal outcomes, and writes back via CAS. The browser polls the workflow every 1.5 s while non-terminal (`page.tsx:232-237`).

**State machine:** `queued → running → {succeeded | failed | cancelled}`, with `failed|cancelled → retrying → running` bounded at `MAX_EXECUTION_ATTEMPTS = 3`. `cancelled` is only reachable pre-submission; a submitted operation is explicitly `provider_not_cancellable`.

---

## Narrative Findings (AI reviewer)

### Critical

#### CR-01: Live plan identity is a hash of mutable evidence, so a successful run erases its own verification and audit path

**File:** `src/semantic/live_operations.py:587`, `src/api/routers/remediation.py:473`, `src/intelligence/remediation/execution_service.py:559`

**Issue:** `opportunity_id = f"live-patch-{_hash({'target': target_id, 'patches': sorted(missing_kbs)})[:16]}"` becomes the plan's durable-looking `plan_id` (`live_operations.py:614`). The missing-KB set is exactly what a successful patch install changes. Trace the chain:

1. `GET /api/v1/remediation/executions/{id}` resolves the record, then calls `_get_scoped_plan(context, scope, record["plan_id"])` (`remediation.py:473`), which regenerates plans and 404s when the old `plan_id` is gone.
2. `poll_verification` is reachable *only* from that route and from `plan_workflow` (`remediation.py:265`), which is fetched by `plan_id`.
3. Therefore, the moment a patch actually succeeds and evidence refreshes, the execution record for that run becomes unreachable, is never polled, and is never transitioned out of `running`. Its true outcome is never persisted.
4. The UI compounds it: `page.tsx:186-194` re-selects `planRows[0]` when the selected `plan_id` disappears, and the new plan has no executions, so Verify renders "Not run yet" for the run that just succeeded.
5. Durable decisions (`approval_decisions.py:262`) and executions (`execution_store.py:180`) are both filtered by `plan_id`, so the audit trail fragments across KB-set states.

This is the direct answer to "does post-execution verification close the loop": on the live path it structurally cannot, and the failure is invisible because it only manifests on *success*.

**Fix:** Derive live plan identity from stable facts only — target ARM id + action family (+ subscription) — and carry the mutable evidence (KB set, finding ids) in the snapshot/version fields where change detection belongs:
```python
# live_operations.py
"opportunity_id": f"live-patch-{_hash({'target': target_id, 'action': 'controlled-patch-recovery'})[:16]}",
```
and make execution reads plan-independent:
```python
# remediation.py::get_execution — authorize on the record's own scope attributes,
# not on the continued existence of a regenerated plan.
record = _execution_or_404(service, execution_id)
_authorize_execution_record(record, scope)   # subscription/connection from the record
```

---

#### CR-02: The bounded retry budget is consumed by failures that provably never reached the provider, and the execution identity is then permanently poisoned

**File:** `src/intelligence/remediation/execution_service.py:38,246-268,286-306,477-489`; `src/intelligence/remediation/execution_store.py:200-201,479-486`

**Issue:** `MAX_EXECUTION_ATTEMPTS = 3` is documented as protection against repeatedly hitting Azure (T-03-11). But `_submit_and_record` marks the attempt `failed` for three categorically different events with no discrimination:

- target/allowlist revalidation refusal, before any adapter call (`:246-268`)
- `PatchValidationError` from the self-approval gate, before any adapter call (`:286-306`)
- a genuine ARM rejection (403/409/429) — also before any state change on the host

The live session burned all three attempts on failures with `provider_job_id` empty: two on the stale self-approval guard and one on a 403. Then `execution_view` (`:477-489`) computed `retryable=False`, `remaining_attempts=0`, `ineligibility_reason="max_attempts_exceeded"`.

Recovery is then impossible by design, not by policy. `_execution_identity` is `plan_id|snapshot_hash|action_version` (`execution_store.py:479-486`); `create_or_get` returns the exhausted record for any identical triple (`:101-114`), and `execute()` returns it verbatim when `claimed` is false (`execution_service.py:160-161`). On the live path `action_version` does not change when evidence changes (see CR-05), so re-approving after the RBAC fix reproduces the same identity and the same dead record. The debug log's own next action — "create a fresh approved snapshot/execution" — has no code path that produces one.

**Fix:** Count only attempts that were actually submitted, and make supersession explicit:
```python
# only a submitted attempt consumes the budget
submitted = bool(run.provider_job_id) or provider_call_was_made
self._store.transition(..., status="failed", provider_submitted=submitted, ...)

# execution_view
attempts = int(view.get("submitted_attempt_count") or 0)
```
and add an audited `POST /executions/{id}/supersede` that closes the exhausted record and mints a new identity from a fresh approval (recording the superseded id), instead of relying on incidental hash churn.

---

#### CR-03: Verification is browser-driven, unbounded, and reads only the ARM envelope

**File:** `src/intelligence/remediation/execution_verifier.py:108-137`; `src/intelligence/remediation/execution_service.py:559-672`; `src/api/routers/remediation.py:265,474-475`

**Issue:** Three defects in one loop.

1. **Pull-only.** `poll_verification` has no caller other than the two HTTP GETs. `grep -rn "poll_verification" src/` returns exactly three hits (definition + two routes). If the operator closes the tab, the execution stays `running` forever: `retry` rejects non-terminal states (`execution_service.py:371-376`) and `cancel` returns `provider_not_cancellable` (`:534-553`). The record is unreachable and unresolvable.
2. **No deadline.** Any unrecognized ARM status falls through to `_OUTCOME_RUNNING` (`execution_verifier.py:131-137`), and the Defender-configuration branch returns `running` indefinitely until desired properties match (`:98-106`). There is no max-age after which an execution becomes `unknown`/`timed_out`.
3. **Envelope-only parsing.** `raw_status = str(payload.get("status"))` reads the long-running-operation envelope. For `Microsoft.Compute|HybridCompute/.../installPatches`, the per-machine result lives in `properties.status` (`Succeeded` / `CompletedWithWarnings` / `Failed`) with `installedPatchCount` / `failedPatchCount` / `errorDetails`. An operation that completes with every patch failing is recorded as `succeeded`. No post-run assessment refresh reconciles the claim against Update Manager, so "verified" never means "the KB is gone".

**Fix:** Add a server-side verification worker over `status in {queued, running, retrying}` records with a per-execution deadline, and parse the result body:
```python
properties = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
detail = str(properties.get("status") or raw_status).casefold()
if detail in {"completedwithwarnings"} or int(properties.get("failedPatchCount") or 0) > 0:
    return {"verifiable": True, "outcome": _OUTCOME_FAILED, "verified_state": ...,
            "failure_details": _error_message(payload, response)}
```
plus a terminal `unknown` outcome when `now - created_at > verification_deadline`.

---

#### CR-04: Approval requirements are decorative, the Defender family has no separation of duties at all, and approving requires the same permission as executing

**File:** `src/intelligence/remediation/approval_engine.py:99-112`; `src/intelligence/remediation/execution_service.py:178-220,270-273`; `src/operations/patching/service.py:269-315`; `src/api/routers/operations.py:363,480-490`; `src/api/dependencies.py:310,319`

**Issue:** Three independent gaps in one governance surface.

1. `ApprovalEngine.requirements` emits rows with `"status": "Required - Not Approved"` and `"approval_recorded": False` and **nothing ever reconciles them against the decision store**. `_check_approval_gate` only requires *one* latest `approved` decision (`execution_service.py:194-201`). A plan displaying three required roles plus stage gates executes on a single decision from any operate-scoped principal. The UI renders the same decorative list (`page.tsx:568`).
2. Separation of duties lives exclusively in `PatchingService._authorize_approval`, reached only via `trigger()`. The Defender-configuration branch calls `self._defender_configuration.submit(snapshot)` (`execution_service.py:270-273`) with **no requester, no approver, and no `require_human_approval` consultation** — that family has no SoD and no human-approval enforcement whatsoever.
3. `record_remediation_decision` and `execute_plan` both require action `"operate"` (`operations.py:363`, `dependencies.py:319`). There is no distinct approve permission, so any principal that can approve can also execute. SoD can only ever be a `casefold()` string comparison between two fields supplied by the same authority — which is precisely why the demo toggle `allow_self_approval` disables it completely rather than degrading it.

The demo-vs-production distinction is therefore weaker than STATE.md claims: production is fail-closed on *one* comparison, on *one* action family, with *zero* enforcement of the policy set the operator is shown.

**Fix:** Evaluate approval policy server-side inside `_check_approval_gate`, for all families, against recorded decisions:
```python
satisfied = {(d["approver"], _role_of(d)) for d in decisions if d["decision"] == "approved"}
missing = [r for r in plan["approval_requirements"] if not _satisfied_by(r, satisfied)]
if missing:
    raise RemediationExecutionError("Required approvals are incomplete",
        reason="approval_requirements_unmet", details={"missing": missing})
```
record `approval_policy_version` on the decision, and split RBAC into `approve` and `operate` actions so the guard is structural rather than nominal.

---

#### CR-05: On the live path `action_version` excludes evidence, so the Phase 02-08 approval-freshness guarantee does not hold in production

**File:** `src/semantic/live_operations.py:607-612` vs `src/intelligence/remediation/remediation_generator.py:96-101`

**Issue:** `02-08-SUMMARY.md` records: *"Implement action_version hash with evidence digest … enabling detection of approval staleness when Defender evidence changes."* `RemediationGenerator` honours that (`action_id|title|execution_steps|rollback_actions|evidence_digest`). The live planner does not:
```python
action_version = _hash({"action": opportunity["recommended_action"],
                        "rollback": ["Uninstall patch if rollback is required"]})[:16]
```
No evidence, no citations, no `observed_at`, no target. It changes only if the recommendation string changes. Consequences on the only path that reaches Azure: an approval survives a Defender re-assessment, a severity change, a finding being resolved by another team, and an inventory drift — `_check_approval_gate`'s `stale_approval` check (`execution_service.py:202-211`) is inert. The `defender_evidence_fresh` revalidation check appended at `operations.py:402` is recorded as passed without being evaluated at all.

Conversely, the two generators produce structurally incompatible `action_version` semantics for the same governance gate, so a plan's freshness behaviour silently depends on whether Fabric publish succeeded — which, per the live evidence, currently times out.

**Fix:** Compute `action_version` in one shared helper used by both planners, including a stable evidence digest (`source_type:source_id` sorted, and a *content* timestamp such as `last_assessed_at` — never the query clock):
```python
from intelligence.remediation.versioning import action_version_for
action_version = action_version_for(action_id=..., target_id=target_id,
                                    patches=sorted(missing_kbs), citations=citations)
```

---

#### CR-06: `RemediationExecutionService` can be constructed with `plan_repository=None`, producing an unhandled `AttributeError` (HTTP 500) on every eligibility read

**File:** `src/api/runtime.py:2821-2831`; `src/intelligence/remediation/execution_service.py:117,135,457`

**Issue:**
```python
return RemediationExecutionService(
    plan_repository=getattr(planner, "repository", None), ...)
```
When `_planner_for_scope` returns `None` — no onboarded subscriptions for a restricted scope, `hybrid_remediation` unavailable, or `providers.get("remediation", optional=True)` returning `None` because Fabric publish failed (a live, current condition) — `self._plans` is `None`. `plan_eligibility` then executes `self._plans.get(plan_id)` (`:457`) and raises `AttributeError`, which no route handler translates. This is the exact live 500 recorded at `remediation-e2e.md:184-186`; the session fixed the *unrestricted* provider selection but left the `None` guard absent, so the crash remains reachable for restricted scopes and for a degraded-provider deployment. `execute()` (`:135`) and `retry()` (`:379`) crash identically.

**Fix:** Fail closed with the typed contract the router already understands:
```python
def plan_eligibility(self, plan_id: str) -> dict[str, Any]:
    if self._plans is None:
        return {"executable": False, "ineligibility_reason": "plan_repository_unavailable"}
```
and raise `RemediationExecutionError(reason="plan_repository_unavailable")` from `execute`/`retry` rather than constructing a service that cannot function.

---

#### CR-07: Deselecting the last patch silently re-selects every patch, widening the approved blast radius

**File:** `web/src/app/remediation/page.tsx:489-508`

**Issue:**
```tsx
const checked = selectedPatchIds.length === 0 || selectedPatchIds.includes(patch.patch_id);
...
setSelectedPatchIds(next.length === all.length ? [] : next);
```
`[]` is overloaded: it means both "operator has expressed no narrowing" and "operator deselected everything". With `all = [A, B]`: unchecking A yields `[B]`; unchecking B yields `next = []`, which is stored as `[]` — and `checked` immediately re-evaluates to `true` for **both** patches. The workflow effect refetches with no `patch_id` query params (`page.tsx:205`, `services.ts:773`), the preview rebuilds over *all* available patches (`approval_decisions.py:117,124`), and the operator's `preview_snapshot_hash` now binds an approval to the full patch set they were trying to clear. On a production host this is an unintended full patch install plus reboot.

`page.test.tsx:261-277` only unchecks one of two boxes, so the case is untested.

**Fix:** Model selection explicitly and refuse the empty state in the UI (the server already refuses it at `approval_decisions.py:137-142`):
```tsx
const [selection, setSelection] = useState<string[] | null>(null); // null = all
const current = selection ?? all;
const next = event.target.checked ? [...current, id] : current.filter((x) => x !== id);
if (next.length === 0) { setActionError("Select at least one patch, or leave all selected."); return; }
setSelection(next.length === all.length ? null : next);
```

---

### Warnings

#### WR-01: The workflow reports Run and Verify "complete" for a failed execution and never routes the operator forward

**File:** `src/api/routers/remediation.py:287-347`

**Issue:** `terminal` includes `"failed"` and `"cancelled"` (`:287-291`), so Verify projects `"complete"`; Run projects `"complete"` merely because `latest_execution is not None` (`:329`); and `recommended_step` short-circuits to `"verify"` for any existing execution (`:296-297`) regardless of outcome or retryability. The live session recorded exactly this: *"Workflow reports Select, Review, Approve, Run, and Verify complete; execution … is failed at attempt 3, retryable=false"* (`remediation-e2e.md:154-155`). A five-step governed journey that renders as fully complete after a failed change is an operator-safety misstatement, not a cosmetic issue.

**Fix:** Project step status from the execution outcome, and add a terminal-failure recommendation:
```python
verify_status = "complete" if status == "succeeded" else "blocked" if status in {"failed","cancelled"} else ...
recommended_step = ("verify" if status in {"running","queued","retrying"}
                    else "retry" if latest_execution.get("retryable")
                    else "approve" if status in {"failed","cancelled"} else "verify")
```

#### WR-02: The UI never renders `ineligibility_reason`, `remaining_attempts`, or `cancellable`, contradicting the recorded Phase 03-06 decision

**File:** `web/src/app/remediation/page.tsx` (no occurrences); `web/src/lib/services.ts:710-713`; `.planning/phases/03-safe-remediation-execution/03-06-SUMMARY.md`

**Issue:** `03-06-SUMMARY.md` states: *"The browser treats executable, retryable, cancellable, remaining_attempts, and ineligibility_reason as authoritative server projections."* The types exist, but `grep -n "ineligibility_reason\|remaining_attempts\|cancellable" web/src/app/remediation/page.tsx` returns nothing. `canRun` (`:321-327`) silently hides the Run control when `workflow.plan.executable` is false without displaying the server's reason (`stale_approval`, `target_not_found`, `business_impact_unknown`, `execution_snapshot_drift`). There is also no cancel control anywhere, so `POST /executions/{id}/cancel` is unreachable from the product. The operator is left to infer a fail-closed refusal from an absent button.

**Fix:** Render `plan.ineligibility_reason` and `execution.ineligibility_reason` as explicit blocker copy on the Run and Verify steps, show `remaining_attempts`, and expose a cancel control gated on `execution.cancellable`.

#### WR-03: Upstream degradation is logged, not surfaced — the workflow envelope carries no warnings

**File:** `src/intelligence/patch/patch_intelligence.py:407-411`; `src/api/routers/remediation.py:349-379`; `src/api/providers.py:58,75,348`; `src/intelligence/remediation/defender_correlation.py:327-347,504`

**Issue:** `envelope(...)` supports a `warnings` argument and `defender_remediation_cases` uses it (`operations.py:289-311`), but `plan_workflow`, `preview_plan`, `list_plans`, and `get_plan` pass none. Meanwhile the platform *has* the signals: `PatchIntelligence` counts skipped coverage gaps and emits only `_LOGGER.warning`; `ProviderState.degraded_reason` and staleness exist on every provider; `DefenderRemediationCorrelator` computes per-family `availability`. An operator approving a real host change cannot see that N evidence rows were dropped, that Fabric publish timed out, or that a Defender source family is `unknown`. This is the direct answer to "does the operator UI accurately communicate partial/stale/unavailable inputs": it does not.

**Fix:** Thread a `degradation` list (source, availability, reason, dropped-row counts) into the workflow envelope's `warnings` and render it above the approve/run controls.

#### WR-04: Live evidence citations hard-code `"freshness": "current"`

**File:** `src/semantic/live_operations.py:543,698`

**Issue:** `"observed_at": self.freshness, "freshness": "current"` asserts currency rather than computing it, unlike `DefenderRemediationCorrelator._citation_freshness`, which calls `classify_freshness(observed_at)` (`defender_correlation.py:512-523`). Because `self.freshness` is the ARG query wall-clock (`live_operations.py:130-165`, `observed_at=now()` in the KQL projection), a finding assessed weeks ago is labelled "current" in the operator's evidence list (`page.tsx:74-75`). Evidence age — the input to the urgency argument — is systematically overstated.

**Fix:** Populate `observed_at` from the row's own assessment timestamp and derive `freshness` via `classify_freshness`.

#### WR-05: No target-readiness precondition, and every ARM rejection collapses into one failure class

**File:** `src/operations/patching/azure_adapter.py:168-173`; `src/intelligence/remediation/execution_service.py:286-306`; `src/operations/patching/service.py:163-205`

**Issue:** `PatchTarget` records `reachable`, `patchable`, and `blocked_reason` derived purely from whether patches were observed — nothing checks the Arc agent's `status`/`lastStatusChange`, VM power state, or assessment age. The live 409 ("agent reported Disconnected") was therefore unforeseeable from a preview that reported `executable=true`. And `if response.status_code >= 400: raise PatchExecutionUnavailable(...)` treats 403 (permanent authorization), 409 (transient precondition), and 429 (throttling) identically, so a transient precondition consumes an attempt from the budget in CR-02 and produces no operator-actionable classification.

**Fix:** Add a readiness precondition to snapshot construction (Arc `properties.status == "Connected"`, assessment not older than a bound) surfaced as `preview.preconditions`, and classify adapter failures:
```python
if response.status_code in {401, 403}: reason = "provider_authorization"
elif response.status_code in {409, 412}: reason = "target_precondition"
elif response.status_code == 429 or response.status_code >= 500: reason = "provider_transient"
```

#### WR-06: Patch-run history is process-local in a multi-replica deployment

**File:** `src/api/runtime.py:2178`; `src/operations/patching/store.py:1-6,26-28`

**Issue:** `_patch_run_store = InMemoryPatchRunStore()` is a module global shared by `_load_patching_service` (`:2312`) and `hybrid_patching` (`:2776`). The module docstring states the opposite requirement: *"Patch runs are user-submitted mutations that must survive a provider rebuild."* `GET /api/v1/patching/runs` therefore returns only the runs submitted by the replica that happens to serve the request, and loses them on restart or scale-in. The reboot setting, resource group, HTTP status, and `run_id` for real mutations are not durably recorded anywhere (the execution store keeps `provider_job_id` and `message` only).

**Fix:** Back `PatchRunStore` with the same revisioned document store used by `RemediationExecutionStore` (`runtime.py:2433-2443`).

#### WR-07: Plans are regenerated several times per request, and `execute` validates a different generation than it executes

**File:** `src/api/routers/remediation.py:57,90,101,239-245,351,444-448`; `src/api/runtime.py:2822-2827`

**Issue:** `plan_workflow` triggers `generate_plans()` at least five times (its own `_get_scoped_plan`, the nested `preview_plan`, and each `_plan_eligibility` → `execution_provider` → `_planner_for_scope`). `execute_plan` scope-checks a plan from planner instance A (`_planner` via `_require`) and then executes against planner instance B's repository (`_execution_service_for_scope`, which builds a *new* `LiveRemediationPlanner`). The 30 s vulnerability cache (`runtime.py:344,2736-2738`) usually masks the divergence, but a cache expiry between the two calls means the plan authorized for scope is not the plan object executed.

**Fix:** Resolve one planner/repository per request (dependency-scoped memoization) and pass the already-resolved plan into the execution service rather than re-fetching it.

#### WR-08: Approval expiry is collected as a date, so a same-day approval is rejected and granularity is one day

**File:** `web/src/app/remediation/page.tsx:583-588`; `src/api/routers/operations.py:106-130`

**Issue:** `<input type="date">` yields `"2026-09-04"`, which `_future_expiry` parses as midnight UTC. Selecting today always fails with "expires_at must be in the future"; selecting tomorrow grants an approval window that varies from minutes to 24 hours depending on submission time. For a control whose purpose is bounding the authorization window, the granularity is not fit for purpose.

**Fix:** Use `datetime-local`, default to a policy-driven offset (e.g. now + 4 h), and validate the maximum window server-side.

#### WR-09: Error messages distinguish "execution does not exist" from "execution exists but is out of scope"

**File:** `src/api/routers/remediation.py:504-513,542-548`

**Issue:** `retry_execution`/`cancel_execution` first resolve the record with `Scope.unrestricted()`. A non-existent id yields `"Remediation execution not found"`; an existing-but-out-of-scope id falls through to `_get_scoped_plan`, yielding `"Remediation plan not found"`. Both are 404, but the differing messages form a cross-tenant existence oracle for execution identifiers. It also means every retry/cancel builds an unrestricted planner over all onboarded subscriptions.

**Fix:** Resolve with the narrowed `write_scope` and return one identical `NOT_FOUND` body for both cases.

#### WR-10: `create_or_get` matches any legacy record for the plan regardless of its snapshot

**File:** `src/intelligence/remediation/execution_store.py:101-112`

**Issue:** The existence check is `execution_identity == identity` **or** `(not row["execution_identity"] and row["plan_id"] == plan_id)`. Any record persisted without an identity (e.g. via the `create()` compatibility path at `:149-167`, or a v1 document) is returned as "the existing execution" for a completely different approved snapshot — and `execute()` then returns it to the caller as their result (`execution_service.py:160-161`), reporting another action's outcome as theirs.

**Fix:** Drop the fallback and migrate legacy rows by backfilling `execution_identity` from their stored snapshot at read time.

#### WR-11: Unbounded 1.5 s client polling with no cap or backoff

**File:** `web/src/app/remediation/page.tsx:232-237`

**Issue:** While status is `queued|running|retrying` the page re-fetches the whole workflow every 1.5 s indefinitely. Each fetch regenerates plans (WR-07), issues live ARG queries on cache miss, and polls ARM. Given CR-03 (no server-side deadline), a stuck `running` execution produces an unbounded request loop for as long as the tab is open — and, paradoxically, the only mechanism that can terminalize the record.

**Fix:** Exponential backoff to a ceiling with a maximum polling duration, plus a manual refresh control once the ceiling is hit.

### Info

#### IN-01: The execution snapshot is validated three times per gate call

**File:** `src/intelligence/remediation/execution_service.py:144,219,247,747`
`_check_approval_gate` calls `_validated_execution_snapshot`, `execute` calls it again, and `_resolve_target` calls it a third time. Harmless but obscures which validation actually gates a given path.

#### IN-02: `_latest_decision` resolves ties to the earliest-appended decision

**File:** `src/intelligence/remediation/execution_service.py:674-678`
`max(decisions, key=lambda row: str(row["decided_at"]))` returns the first maximum. Two decisions sharing a timestamp string (approve then reject) resolve to the approval. Prefer `(decided_at, sequence)` as the sort key.

#### IN-03: `EXECUTABLE_ACTION_IDS` is re-exported from a module that only imports it

**File:** `src/intelligence/remediation/execution_service.py:17,815`
Listed in `__all__` though it is owned by `action_catalog`, giving two import paths for one allowlist.

---

## Explicit Assessments Requested

**Does automatic plan generation currently make sense?** Not in its present form. Generation itself is sound and cheap to reason about, but it is wired as an *on-read view* (`generate_plans()` on every list/get/preview/workflow/decision/eligibility call, in-memory `PlanRepository`, `plan_id` computed from live evidence) while approvals, execution claims, retry budgets, and audit history are *durable objects keyed on that view's identity*. That mismatch is the root of CR-01, CR-02, CR-06, and WR-07. Automatic generation should continue; automatic **identity** should not.

**Are freshness/approval semantics coherent?** No — they are incoherent along three axes. (a) Two generators compute `action_version` by incompatible rules, and the production one omits evidence entirely (CR-05), so `defender_evidence_fresh` is recorded as passed without evaluation. (b) The UI's `approval.current` compares only `snapshot_hash` (`remediation.py:280-286`) while `execute` additionally enforces `action_version` currency and expiry — a plan can display "approval current" and still be refused `stale_approval`, with the reason never rendered (WR-02). (c) Citation freshness is asserted as `"current"` rather than classified (WR-04).

**Does post-execution verification close the loop?** No. It closes the *submission* loop and nothing further. Verification runs only when a browser requests it (CR-03), has no deadline, reads only the ARM envelope rather than the patch result, and there is no reconciliation step that re-assesses the target to confirm the KB is gone. Worse, on the live path a genuinely successful run changes the plan identity and thereby severs the only route to its own verification (CR-01).

**Does the operator UI accurately communicate partial/stale/unavailable inputs?** No. Coverage gaps are logged rather than returned (WR-03), degraded provider state never reaches the workflow envelope, evidence age is overstated (WR-04), server-computed blocker reasons are dropped on the floor (WR-02), a failed change renders as a completed workflow (WR-01), and the patch picker can widen the approved change set (CR-07).

---

## Recommendations (exactly five, ranked)

### 1. Make plan identity durable and decouple execution/audit reads from plan regeneration — *immediate reliability*

- **Observed evidence:** `live_operations.py:587` (`opportunity_id` = hash of target + `sorted(missing_kbs)`) → `live_operations.py:614` (`plan_id`); `remediation.py:473` (`get_execution` → `_get_scoped_plan`); `remediation.py:265` (only other `poll_verification` caller); `execution_store.py:180` and `approval_decisions.py:262` (both keyed on `plan_id`); `runtime.py:2825-2826` (`plan_repository=getattr(planner, "repository", None)`).
- **Failure/risk addressed:** CR-01 and CR-06. A successful patch mutates the plan key, which 404s the execution read, prevents verification from ever running, orphans the decision/execution audit chain, and makes the UI report "Not run yet" for a run that just changed a production host. A missing repository crashes eligibility with a 500.
- **Proposed change:** Derive live plan identity from stable facts only (target ARM id + action family + subscription); move the mutable KB set into the snapshot and `action_version`. Authorize execution reads from the execution record's own scope attributes instead of requiring the plan to still exist. Resolve exactly one planner/repository per request and inject it, and make `RemediationExecutionService` fail closed (`plan_repository_unavailable`) instead of dereferencing `None`.
- **Upstream/downstream impact:** Upstream — `live_operations` opportunity/plan builders and the shared version helper (see #4). Downstream — `remediation.py` execution routes, `plan_workflow` step projection, `page.tsx` selection persistence across refreshes; existing durable decision/execution documents need a one-time `plan_id` migration map. Requires no change to the adapter or snapshot contract.
- **Acceptance criteria / measurement:** (a) An integration test that executes a plan, mutates `missing_kbs`, regenerates, and asserts `GET /executions/{id}` still returns 200 with the same `execution_id` and that `poll_verification` reaches a terminal state. (b) `plan_id` is byte-identical across ≥10 consecutive `generate_plans()` calls spanning a cache expiry, for both live and Fabric planners. (c) No `AttributeError` reachable from any remediation route with all providers unavailable — assert typed 503/409 instead. (d) Zero orphaned decisions/executions (`plan_id` with no matching plan) reported by a new health check.

### 2. Split the execution attempt budget by proof of submission and give operators an audited supersede path — *immediate reliability*

- **Observed evidence:** `execution_service.py:38` (`MAX_EXECUTION_ATTEMPTS = 3`), `:246-268` and `:286-306` (pre-submission refusals recorded as failed attempts), `:477-489` (`retryable`/`remaining_attempts`), `execution_store.py:200-201,479-486` (`max_attempts_exceeded`, permanent identity); live evidence `remediation-e2e.md:120,145,155` (attempts 1–2 self-approval guard, attempt 3 provider 403, all with `provider_job_id` empty).
- **Failure/risk addressed:** CR-02 and WR-05. The safety mechanism designed to prevent repeated Azure submissions is consumed entirely by failures that never reached Azure, then permanently blocks the remediation once the external cause (RBAC, agent connectivity) is fixed. Today's only recovery is incidental hash churn — which CR-05 has removed on the live path.
- **Proposed change:** Record `provider_submitted` on each attempt; count only submitted attempts against the ceiling. Classify adapter failures (`provider_authorization` / `target_precondition` / `provider_transient` / `provider_rejected`) and surface the class in `ineligibility_reason`. Add `POST /executions/{id}/supersede` that closes an exhausted record with an explicit reason and mints a new identity from a fresh approval, recording `superseded_by` / `supersedes` in the immutable history.
- **Upstream/downstream impact:** Upstream — `azure_adapter.submit` must return the classification rather than one `PatchExecutionUnavailable`; `PatchingService.trigger` propagates it. Downstream — `execution_view` projection, `remediation.py` route surface, `page.tsx` Verify step controls, `RemediationExecutionStore` schema bump (v2.1) with defaults for existing rows.
- **Acceptance criteria / measurement:** (a) A test asserting three consecutive pre-submission refusals leave `remaining_attempts` unchanged while one submitted failure decrements it. (b) A test reproducing the live sequence (403 → RBAC granted → supersede → submit) reaching `succeeded` without editing stored state. (c) `ineligibility_reason` is non-empty and class-specific for every terminal failure in `tests/test_remediation_execution_retry.py`. (d) Operational metric: zero executions in `failed` with `remaining_attempts == 0` and `provider_job_id == ""`.

### 3. Move verification server-side with a deadline, deep result parsing, and post-run evidence reconciliation — *immediate reliability + strategic*

- **Observed evidence:** `execution_verifier.py:108-137` (envelope `status` only), `:98-106` (Defender branch can return `running` forever); `execution_service.py:559-672` (`poll_verification` has no non-HTTP caller); `remediation.py:265,474-475` (the only two callers); `page.tsx:232-237` (1.5 s browser loop is the de-facto scheduler).
- **Failure/risk addressed:** CR-03, WR-11, and the strategic half of "closing the loop". Today an execution's terminal state depends on someone keeping a browser tab open; a partially-failed Azure patch run is recorded as `succeeded`; and nothing confirms the KB actually disappeared from assessment.
- **Proposed change:** Add a bounded server-side verification worker over non-terminal records (reusing the existing CAS transitions, so no new concurrency model), with a per-execution deadline producing a terminal `unknown` outcome plus operator guidance. Parse `properties.status` / `installedPatchCount` / `failedPatchCount` / `errorDetails` and treat `CompletedWithWarnings` or `failedPatchCount > 0` as `failed`. On a verified success, trigger a targeted patch-assessment refresh for that resource and record the reconciliation result (`kbs_cleared` / `kbs_remaining`) on the execution.
- **Upstream/downstream impact:** Upstream — needs the Phase 6–10 inventory/ARG refresh entry point for a single resource, and must tolerate the current Fabric publish timeout by refreshing the live ARG path only. Downstream — Verify step copy, `verified_state` vocabulary, the `succeeded` definition used by any reporting, and client polling becomes a convenience rather than a correctness dependency.
- **Acceptance criteria / measurement:** (a) With no browser open, an execution submitted to a stub ARM reaches a terminal status within the worker interval. (b) A fixture returning envelope `Succeeded` with `properties.status = CompletedWithWarnings`, `failedPatchCount = 2` records `failed` with the error detail. (c) Every execution reaches a terminal status within the configured deadline — measured as p100 age of non-terminal records. (d) A verified success stores a reconciliation result; a success whose KBs remain is flagged rather than reported clean.

### 4. Enforce one server-side approval policy for all action families, with a distinct approve permission and a single shared `action_version` — *strategic (governance correctness)*

- **Observed evidence:** `approval_engine.py:99-112` (`approval_recorded: False`, never reconciled); `execution_service.py:194-201` (one decision suffices), `:270-273` (Defender submit takes no requester/approver); `patching/service.py:269-315` (SoD only here); `operations.py:363` and `dependencies.py:319` (approve and execute both require `operate`); `operations.py:402` (`defender_evidence_fresh` recorded unevaluated); `live_operations.py:607-611` vs `remediation_generator.py:96-101` (divergent `action_version`).
- **Failure/risk addressed:** CR-04 and CR-05. The governance surface shown to operators and auditors overstates what is enforced: multi-role requirements are decorative, one action family has no separation of duties or human-approval check at all, approving and executing are the same permission, and the production `action_version` cannot detect evidence change. This is the difference between "demo self-approval is an explicit opt-out" and "separation of duties is structurally unenforceable".
- **Proposed change:** Evaluate `approval_requirements` against recorded decisions inside `_check_approval_gate` for every family, returning `approval_requirements_unmet` with the missing rows. Move the requester≠approver check out of `PatchingService` into that gate so it covers Defender configuration too, and keep `allow_self_approval` as the single audited demo escape hatch recorded on the decision. Split RBAC into `approve` and `operate` actions. Extract one `action_version_for(...)` helper — including a stable evidence digest keyed on content timestamps, never the query clock — used by both planners.
- **Upstream/downstream impact:** Upstream — `ApprovalEngine` must emit machine-checkable role/policy identifiers, and principals need role claims; `rbac.py` gains an action. Downstream — `record_remediation_decision` records `approval_policy_version`; `page.tsx` renders requirement satisfaction rather than a static list; existing approvals recorded under the old `action_version` rule will read as stale once (a deliberate, auditable one-time invalidation).
- **Acceptance criteria / measurement:** (a) A plan carrying two required roles cannot execute on one decision; the refusal names the missing role. (b) A Defender-configuration execution is refused when requester == approver and `allow_self_approval` is false. (c) A principal holding `approve` but not `operate` can approve and cannot execute, and vice versa. (d) Mutating a citation's content timestamp changes `action_version` on both planners and produces `stale_approval` on execute.

### 5. Make the workflow contract explain itself: server-computed blockers and degradation, honest step projection, and a safe patch picker — *immediate operator safety*

- **Observed evidence:** `remediation.py:287-347` (Run/Verify `complete` on failure; `recommended_step` pinned to `verify`), `:349-379` (envelope passes no `warnings`); `page.tsx:321-327,603-606` (blocked with no reason), `:489-508` (deselect-all → all selected), `:232-237` (unbounded polling); `services.ts:710-713` (fields typed but unrendered); `patch_intelligence.py:407-411` (coverage gaps only logged); `providers.py:58,348` (`degraded_reason` never surfaced); `live_operations.py:543,698` (`"freshness": "current"` asserted).
- **Failure/risk addressed:** CR-07, WR-01, WR-02, WR-03, WR-04, WR-11. The operator currently cannot distinguish "safely refused", "input degraded", and "already done", is shown a completed workflow after a failed production change, and can widen the approved blast radius with a deselect gesture.
- **Proposed change:** Add two server-computed arrays to the workflow payload — `blockers[]` (code, human sentence, the concrete next operator action) derived from the same `ineligibility_reason` values the gate already produces, and `degradation[]` (source, availability, reason, dropped-row counts) assembled from `ProviderState`, `PatchIntelligence` coverage counts, and `source_family_status`. Project step status from execution outcome rather than existence. Render blockers, degradation, `remaining_attempts`, and a cancel control in the UI. Replace the overloaded `[]` patch selection with an explicit `null = all` model that refuses an empty set. Add backoff and a polling ceiling. Compute citation freshness instead of asserting it.
- **Upstream/downstream impact:** Upstream — `patch_intelligence` and `providers` must return coverage/degradation counts rather than logging them; `defender_correlation.source_family_status` gets a second consumer. Downstream — `RemediationWorkflow` type gains two fields (additive), `page.tsx` gains one blocker panel, and `page.test.tsx` gains cases for terminal failure, exhausted attempts, degraded sources, and deselect-all.
- **Acceptance criteria / measurement:** (a) Every `ineligibility_reason` emitted by `execution_service` has a rendered sentence and a named next action; asserted by a test enumerating the reason vocabulary. (b) A failed execution renders Verify as blocked with a retry or supersede action, never "complete". (c) A UI test proves deselecting every patch refuses rather than selecting all, and that the approved `snapshot_hash` matches the operator's visible selection. (d) With a degraded patch provider, the workflow response carries a non-empty `degradation[]` and the UI shows it above the approve control. (e) Client requests per minute for a stuck execution stay bounded under the backoff ceiling.

---

_Reviewed: 2026-09-03T14:46:49Z_
_Reviewer: gsd-code-reviewer (adversarial deep review)_
_Depth: deep — no source files were modified; no commit was made._
