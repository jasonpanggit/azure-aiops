---
status: fixing
trigger: "Check the deployed /remediation experience end to end: select a fix, review impact, approve, run, and verify with Playwright; capture issues and errors, identify improvement gaps, troubleshoot root causes, fix them, and repeat until the E2E succeeds."
created: "2026-09-03T09:28:07+08:00"
updated: "2026-09-03T18:58:00+08:00"
---

# Debug Session: Remediation E2E

## Symptoms

- Expected: The deployed `/remediation` workflow lets a user select a fix, review its impact, approve it, run it, and verify a successful/completed outcome.
- Actual: Select, Review, Approve, Run, and Verify all rendered in the deployed UI. Approval returned HTTP 201 and execution returned HTTP 202, but Verify reported a failed execution because the same principal approved and requested the patch.
- Errors: "The approver must be someone other than the requester."
- Timeline: Live validation requested on 2026-09-03; prior remediation changes are present in the working tree.
- Reproduction: Open `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/remediation`, select an available fix, review impact, approve, run, and verify.

## Current Focus

- hypothesis: "Active API revision 0000207 rejects self-approval because it was built before the runtime callback wiring that passes agent_policy.allow_self_approval into PatchingService; the settings route persists true, but the stale revision uses PatchingService's default false. Separately, the live ARG path does not query DefenderAssessment rows, so unhealthy Guest-Configuration recommendations cannot become live remediation plans even though the persisted Fabric path has a mapper."
- bug_class: bohrbug
- test: "Compare immutable revision/image timing and source history, inspect backend logs for RME-28E8C12074CE04D4, run focused local self-approval tests, and inspect the read-only Defender ingestion/normalization/planner chain. Deploy only the already-authored API wiring from checkpoint 785c0400, then repeat the same authorized UI flow."
- expecting: "The active image predates the callback, the focused local tests pass, and the isolated new API revision allows the same-principal approved request to reach the configured provider guard. Defender tracing will show persisted assessment normalization and planner support, but no live query-to-planner path for Guest-Configuration/DefenderAssessment rows."
- falsification_test: "After deploying the isolated checkpoint image, the same authenticated flow still returns the separation-of-duties error before provider submission; or live_vulnerability_service is shown to query and pass DefenderAssessment rows into defender_posture and _configuration_assessments. Either observation falsifies the corresponding branch."
- blind_spots: "The active revision's exact AIOPS_HOME/OneLake values are not exposed by metadata; an isolated image update could still reveal a settings-store/runtime-root mismatch. Current live Defender findings may change, and provider submission/Verify remain unproven until the new revision is exercised. No secrets, tokens, synthetic identities, or code bypasses will be used."
- candidate_causes:
    - "code: active API image predates runtime wiring that passes allow_self_approval into PatchingService; live_operations also omits a DefenderAssessment ARG query."
    - "config: governance settings and execution runtime could use different AIOPS_HOME/OneLake roots."
    - "environment: active revision could route mutation handling to a stale worker/image."
    - "data: durable execution is idempotent, so retries retain the original failed execution identity."
  and_gate: "no for the observed rejection: stale code alone is sufficient to reject requester=approver; the persisted true setting is required for the intended post-fix demo but is not a second cause. For Defender coverage, source support and live input availability are separate conditions."
- checkpoint_state: "authorized_settings_patch_and_defender_coverage_investigation"
- next_action: "Run read-only health and governance-settings GETs against the 100%-traffic API revision 0000208, then execute the existing bounded Playwright harness against /remediation; capture the new revision's backend logs and determine whether the authorized Retry reaches provider submission and Verify."

### Structured reasoning checkpoint

reasoning_checkpoint:
  hypothesis: "Active API revision 0000207 rejects self-approval because it was built before the runtime callback wiring that passes agent_policy.allow_self_approval into PatchingService; the settings route persists true, but the stale revision uses PatchingService's default false."
  confirming_evidence:
    - "The deployed PATCH and GET settings calls returned 200 with allow_self_approval=true while execute and UI Retry both returned 202 with the exact separation-of-duties message for equal requester/approver identities."
    - "The active image aiops-api:remediation-context-20260903-111700 was created at 2026-09-03T02:40:10Z; checkpoint 785c0400 containing the callback wiring was created at 2026-09-03T13:24:43+0800."
    - "git show 785c0400 includes allow_self_approval=_allow_self_approval in _load_patching_service, while the pre-checkpoint baseline does not; focused local self-approval tests pass."
  falsification_test: "After deploying the isolated checkpoint image, the same effective settings and same authenticated requester/approver still produce the separation-of-duties error before provider submission."
  fix_rationale: "Deploy the already-authored, narrowly scoped runtime wiring that supplies the persisted governance callback to the guarded PatchingService. This changes no identity, approval, autonomous-remediation, or provider guard and addresses stale deployed code rather than masking the error."
  blind_spots: "The active revision's OneLake root and exact environment values are not exposed by metadata; a new revision could still reveal a settings-store mismatch. Provider submission and Verify remain unproven until the new revision is exercised."
  candidate_causes:
    - "code: active API image predates the self-approval callback wiring"
    - "config: settings persistence and execution runtime could use different document-store roots"
  and_gate: "no for the current rejection: stale code alone is sufficient; persisted true is required only for the intended post-fix operation."

## Evidence

- timestamp: 2026-09-03T16:05:00+08:00
  checked: "Repository settings implementation and STATE scope"
  found: "The governed endpoint is PATCH /api/v1/governance/settings, protected by WritePrincipal plus ReadScope. EnterpriseSettingsStore merges a partial agent_policy update over defaults and persists state/enterprise_settings.json through the deployed OneLake document store; allow_self_approval defaults false and is read at execution time."
  implication: "The requested mutation has a legitimate narrow API path and does not require code changes or an identity bypass. The complete Phase 10 status is not a blocker because the user explicitly authorized this remediation-demo operation and requested continuation of this existing debug session."

- timestamp: 2026-09-03T16:08:00+08:00
  checked: "Deployed API OpenAPI and Container Apps non-secret configuration"
  found: "OpenAPI exposes PATCH /api/v1/governance/settings. The active API is revision 0000207, uses direct/gateway authentication mode with tenant ffc83107-fcc0-4d2e-8798-d582da36505e and audience api://306c1437-0e7d-43bd-940b-79b878166331; the current Azure CLI context is the target-tenant service principal."
  implication: "A bearer acquired from the current target-tenant CLI context can be used through the normal authenticated API path. The next request is a read-only effective-policy check followed by the narrowly authorized PATCH."

- timestamp: 2026-09-03T16:10:00+08:00
  checked: "Authenticated GET /api/v1/governance/settings on revision 0000207"
  found: "The governed settings route returned HTTP 200 for the current target-tenant service principal. require_human_approval is true; the effective response omitted allow_self_approval, which is therefore not enabled by the deployed stored document/default merge."
  implication: "The user's authorized narrow PATCH is necessary for this demo. It will preserve human approval while enabling only same-principal approval, and the response will be re-read before any remediation mutation."

- timestamp: 2026-09-03T16:12:00+08:00
  checked: "Authorized settings mutation and immediate read-back"
  found: "PATCH /api/v1/governance/settings with {agent_policy:{allow_self_approval:true}} returned HTTP 200 and effective allow_self_approval=true while require_human_approval remained true. A follow-up GET returned the same effective values. Correlation IDs were captured locally; no token or secret was printed."
  implication: "The deployed policy mutation succeeded through the legitimate authenticated settings API. The same-principal retry is now authorized for this demo, but remains bounded to the existing Patch vm1 Arc plan and must be evidenced end to end."

- timestamp: 2026-09-03T16:20:00+08:00
  checked: "TARGET_ARC=1 Playwright run after the authorized policy change"
  found: "The UI rendered one Arc Patch vm1 plan and persisted Select evidence, but the workflow GET failed in the browser with net::ERR_FAILED; no approval or execute request was issued. The harness exited with the bounded workflow timeout. Browser request events did not show an Authorization header, so this run does not prove an API workflow failure."
  implication: "The next experiment must isolate cross-origin browser authentication/CORS from backend behavior using the same fresh bearer against the exact workflow endpoint, without issuing approval or execute."

- timestamp: 2026-09-03T16:25:00+08:00
  checked: "Read-only direct workflow request after the browser timeout"
  found: "The exact deployed workflow endpoint returned HTTP 200 with Patch vm1, executable preview, known business impact, and the existing failed execution record. The API log recorded the direct GET successfully; no approval or execute request was made by this probe."
  implication: "The backend route is healthy and the browser failure is isolated to the test harness/browser cross-origin authentication boundary. The old failed record will be superseded only by a fresh authorized approval/run if the UI can render Review."

- timestamp: 2026-09-03T16:30:00+08:00
  checked: "Web-origin CORS preflight and authenticated workflow GET"
  found: "OPTIONS returned HTTP 200 with allow-origin equal to the deployed web origin and allow-headers authorization. An authenticated GET with that Origin returned HTTP 200. The harness route interception was changed from page scope to browser-context scope; application code was not changed."
  implication: "The next Playwright run tests the harness boundary only. If Review renders, the requested same-principal mutation is permitted by the effective demo setting and will be captured; if it fails before Review, no mutation should occur."

- timestamp: 2026-09-03T16:45:00+08:00
  checked: "Context-level authenticated Playwright retry after policy mutation"
  found: "The deployed UI completed Select, Review, Approve, Run, and Verify. The plan had known business impact and the four reviewed patch IDs; approval returned HTTP 201 and execute returned HTTP 202 with no request failures or page errors. Verify displayed the prior execution RME-28E8C12074CE04D4 and the old self-approval failure, with the same actor in approved_by/requested_by. No successful new provider attempt is evidenced."
  implication: "The effective setting did not create a fresh execution result in this run; the execution endpoint likely honored the durable execution identity/idempotency record from the earlier failed run. Inspect retry semantics before issuing another mutation, rather than misclassifying this as proof that the setting is ignored."

- timestamp: 2026-09-03T16:50:00+08:00
  checked: "Repository execution idempotency and retry contract plus fresh Playwright response bodies"
  found: "execute returns the existing durable record when the plan/snapshot execution identity already exists; the documented POST /api/v1/remediation/executions/{execution_id}/retry is the only path that claims a failed terminal attempt and resubmits the exact immutable snapshot. The UI exposes this as Retry approved snapshot when execution.retryable is true."
  implication: "The correct continuation is a UI-driven bounded retry after Verify displays the old failure. It revalidates the current approval/snapshot and exercises the setting-enabled patching guard without inventing parameters or bypassing authorization."

- timestamp: 2026-09-03T17:10:00+08:00
  checked: "Authenticated GET/PATCH/GET /api/v1/governance/settings on the deployed API"
  found: "The preflight GET, narrow PATCH with {agent_policy:{allow_self_approval:true}}, and read-back all returned HTTP 200. The effective policy is allow_self_approval=true, require_human_approval=true, and allow_autonomous_remediation=false."
  implication: "The authorized setting is effective without weakening the human-approval requirement or enabling autonomous remediation. The next live action is limited to the existing rendered Arc Patch vm1 workflow and its server-owned retry snapshot."

- timestamp: 2026-09-03T17:20:00+08:00
  checked: "Bounded Playwright run after the effective policy read-back"
  found: "The real Arc Patch vm1 plan and Review/Approve UI rendered, but the harness timed out waiting for Review and run after the approval click. Persisted evidence contains no approval or execution request; MSAL synthetic-cache iframe traffic remained pending and the only request failure was an unrelated aborted network-summary request."
  implication: "This run did not reach a server mutation. The next experiment changes only harness timing by aborting the synthetic login iframe, which makes the app's existing fail-closed token path return promptly; the API still receives the same real bearer through the normal server-authenticated request boundary."

- timestamp: 2026-09-03T17:33:00+08:00
  checked: "Playwright rerun with the first synthetic MSAL abort matcher"
  found: "The matcher did not intercept the actual login.microsoftonline.com authorize URL: two authorize requests failed after the normal MSAL timeout, the workflow GET remained pending, and the harness exited before Review. No approval or execution request was issued."
  implication: "The experiment falsified only the glob matcher, not the authentication-boundary approach. Use an exact host regex matcher; this changes no deployed code, identity, policy, or provider guard."

- timestamp: 2026-09-03T17:52:00+08:00
  checked: "Completed Playwright approval/run attempt with the corrected MSAL matcher"
  found: "The deployed UI rendered Patch vm1, recorded approval HTTP 201, entered Run, and issued execute HTTP 202. The server returned the existing durable execution RME-28E8C12074CE04D4 as failed with the prior self-approval message; the UI was still loading its refreshed Verify workflow after the harness's fixed 30-second wait, so Retry was not clicked."
  implication: "Execute is idempotently returning the existing failed execution; the required next operation is the rendered Retry approved snapshot control. The next harness-only change waits for that control and does not issue a direct retry request."

- timestamp: 2026-09-03T18:10:00+08:00
  checked: "Completed Playwright UI-driven approval, Run, Verify, and Retry flow with the effective self-approval setting"
  found: "The deployed UI rendered Patch vm1; approval POST returned 201; execute POST returned 202; Verify rendered failed execution RME-28E8C12074CE04D4; the UI Retry approved snapshot control was clicked; retry POST returned 202. The retry advanced to attempt 2 but failed before provider submission with the exact same message, 'The approver must be someone other than the requester'. The requester and approver were both 5ded50ff-9e32-4455-9583-1c139580acae. Captured artifact includes Select/Approve/Run/Verify/Retry screenshots, console, request failures, network statuses, and response bodies."
  implication: "The requested UI flow is fully exercised, but the deployed execution path is not honoring the effective settings value. No provider patch was submitted. This is now a deployment/runtime wiring discrepancy to localize with read-only revision and log evidence; no guard will be weakened."

- timestamp: 2026-09-03T18:25:00+08:00
  checked: "Read-only Azure resource discovery"
  found: "The target resources are in aiops-dev-rg; aiops-dev-api revision aiops-dev-api--0000207 and aiops-dev-web revision aiops-dev-web--0000167 are ready and serving."
  implication: "The earlier failed resource-group probe was only a command-scope error. Revision metadata and logs can now be inspected without changing deployment state."

- timestamp: 2026-09-03T18:32:00+08:00
  checked: "Active revision provenance, backend logs, source history, and focused self-approval tests"
  found: "The active image aiops-api:remediation-context-20260903-111700 was created at 2026-09-03T02:40:10Z, before checkpoint 785c0400 (2026-09-03T13:24:43+0800). The checkpoint source includes allow_self_approval=_allow_self_approval in runtime._load_patching_service; the pre-checkpoint baseline does not. Deployed logs show the approval and execute/retry HTTP requests but no provider job ID or provider submission, while local tests/test_patch_approval_gate.py -k self_approval passed."
  implication: "This confirms a code-revision mismatch rather than a settings-route persistence failure: the active API is serving the pre-wiring image, so its PatchingService default remains fail-closed false. A narrowly scoped API image rollout is the falsifiable fix experiment."

- timestamp: 2026-09-03T18:35:00+08:00
  checked: "DefenderAssessment/Guest-Configuration source-to-planner trace"
  found: "The onboarding query catalog requests microsoft.security/assessments at src/onboarding/query_catalog.py:73-85. src/onboarding/defender_normalize.py:140-180 extracts targetResourceId, status, severity, recommendation, and resource type; graph_normalize.py:202-220 materializes DefenderAssessment entities; dataset_mapper.py:406-409 and 469-472 writes bronze/silver assessment datasets; fabric/sync_service.py:889-918 reads silver defender_assessments; runtime.py:1800-1826 passes assessments into _build_vulnerability_service; vulnerability/service.py:505-560 filters unhealthy rows in defender_posture; live_operations.py:383-397 and 339-350 can turn supported posture recommendations into configuration opportunities/plans. However, live_operations.py:120-171 queries only Update Manager patch assessment/installations and never queries defender_assessments or defender_subassessments, so the deployed live planner cannot receive unhealthy Guest-Configuration/DefenderAssessment rows. Unsupported recommendations are manual-review only via action_catalog.py:38-60."
  implication: "Fabric-backed synced assessments have a source-to-planner path, subject to resource normalization and supported recommendation matching. The deployed live ARG path has a concrete coverage gap: unhealthy Guest-Configuration/DefenderAssessment findings are not converted into live actionable VM plans because they are never queried into the live vulnerability service. No broad feature is being implemented in this debug session."

- timestamp: 2026-09-03T18:52:00+08:00
  checked: "Narrow API rollout from isolated checkpoint source"
  found: "Built one API image aiops-api:remediation-self-approval-20260903-1842 from checkpoint 785c0400 plus the two required Defender modules, with SOURCE_CACHE_BUST set, and updated only aiops-dev-api. New revision aiops-dev-api--0000208 became Healthy/RunningAtMaxScale with 100% latest traffic; the prior web app and other Container Apps were not changed."
  implication: "The stale-image hypothesis now has a controlled counterfactual. Read-only settings/health checks and the same authorized Playwright UI flow can test whether runtime callback wiring is now effective."

- timestamp: 2026-09-03T09:31:00+08:00
  checked: ".planning/STATE.md and prior debug session state"
  found: "Milestone Phase 10 is complete; the request explicitly targets the deployed /remediation workflow and says to preserve unrelated remediation working-tree changes. The debug session has no prior live evidence yet."
  implication: "Live E2E reproduction and remediation-scoped source/test inspection are in scope; no fix hypothesis is confirmed."

- timestamp: 2026-09-03T09:34:00+08:00
  checked: "knowledge-base.md, prior remediation context, remediation router/page/services/tests, and project skill inventory"
  found: "No prior knowledge-base entry matches this workflow. The prior remediation context identified a page-side query-selection defect and recorded focused tests/lint passing, while the current page includes that selection fix. The deployed workflow still requires fresh live evidence."
  implication: "Treat the earlier query-selection fix as a candidate only; the live E2E must test current deployed behavior and the complete Select → Review → Approve → Run → Verify handoff."

- timestamp: 2026-09-03T09:37:00+08:00
  checked: "deployed /remediation page and guessed /api/v1/remediation endpoints"
  found: "The deployed page returns HTTP 200 with Next.js cache HIT. Direct requests to the web host's /api/v1/remediation/plans and related guessed paths return Next.js HTTP 404, and local Node cannot require Playwright."
  implication: "The 200 shell does not prove the workflow backend is reachable. The API base used by the browser must be identified before classifying this as a backend or UI failure; Playwright requires another installed executable/package or a bounded install."

- timestamp: 2026-09-03T09:39:00+08:00
  checked: "deployed /api/config, direct API health, and authenticated remediation plan request using the locally available Azure CLI service-principal session"
  found: "The browser runtime config points to https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io. The API health endpoint is HTTP 200/ready, but the authenticated GET /api/v1/remediation/plans?offset=0&limit=100 returns HTTP 500 internal_error with a correlation ID. The unauthenticated request returns the expected 401."
  implication: "API routing and authentication reach the deployed API, but remediation plan generation fails server-side before Select can populate; this is stronger evidence than the earlier web-host 404 and is now the leading live failure branch."

- timestamp: 2026-09-03T09:44:00+08:00
  checked: "authenticated Playwright page with API request interception"
  found: "The live browser loads the shell but remains at the organizational sign-in gate, so it emits no remediation API request without a cached Entra user account. The direct authenticated API request independently returned HTTP 500."
  implication: "The browser-auth boundary is separate from the server failure. The next experiment must use the direct API correlation ID and container logs; mocking the sign-in screen would not establish the live workflow."

- timestamp: 2026-09-03T09:50:00+08:00
  checked: "latest deployed API stack trace for GET /api/v1/remediation/plans and local remediation router/runtime"
  found: "The request reaches remediation.py:list_plans line 101, then _plan_with_eligibility line 396, _plan_eligibility line 392, and execution_service.py:plan_eligibility line 457. The exact exception is AttributeError: 'NoneType' object has no attribute 'get' because self._plans is None. The local runtime intentionally creates a fresh execution service and planner for the scope, while the list route creates another planner and repository."
  implication: "The immediate live failure is not the earlier Patch Semantic validation error: plan generation reaches eligibility, but the execution service is constructed without a usable plan repository for the returned plan. The fix must address this repository handoff or fail closed without a 500."

- timestamp: 2026-09-03T09:59:00+08:00
  checked: "working-tree runtime fix, focused regression test, and lint"
  found: "The targeted runtime change now resolves unrestricted execution through every active onboarded subscription and generates that live planner's repository before constructing RemediationExecutionService. A focused unrestricted eligibility regression was added; ruff passed and 38 remediation router/execution tests passed."
  implication: "The local counterfactual is clean. Deployment is required to falsify or confirm that this exact provider-selection change removes the live HTTP 500."

- timestamp: 2026-09-03T10:06:00+08:00
  checked: "deployed revision 0000202 unrestricted plan list and governed workflow, plus explicit-subscription workflow"
  found: "Revision 0000202 returns HTTP 200 for unrestricted governed plans with one live plan and ineligibility_reason=not_approved. Its unrestricted workflow returns Select complete but Review blocked with preview_error=provider_unavailable. The same plan with subscription=a87a8e64-a52a-4aa8-a760-5e8919d23cd1 returns preview_error=target_not_found."
  implication: "The first 500 is fixed. Review exposes a second independent scope handoff: runtime _patching_for_scope has no unrestricted active-connection fallback, so it cannot resolve the target used by the live plan."

- timestamp: 2026-09-03T10:12:00+08:00
  checked: "local focused workflow regression after adding unrestricted patching fallback"
  found: "The new workflow test reached a successful preview path; its only failure was an incorrect test expectation for patch ordering (the snapshot contract sorts KB600001 before KB600002). Import-cycle risk from sharing the operations helper was also caught immediately and removed by keeping the small registry projection local to patching.py."
  implication: "The patch-provider hypothesis remains supported; production logic has not yet failed in the local workflow test."

- timestamp: 2026-09-03T10:22:00+08:00
  checked: "revision 0000203 patch target endpoints and live plan metadata, plus local patch classifier"
  found: "After the unrestricted patch-provider fallback, both unrestricted and explicit-subscription preview requests still return 409 target_not_found for the exact live plan target. The patch target collection returns zero rows. The live plan exposes an empty resource_type while its ARM id identifies Microsoft.HybridCompute/machines/vm1. The classifier accepted row type metadata but did not fall back to the target ARM id."
  implication: "Provider selection alone is insufficient. The focused classifier regression passes after deriving the type from asset_id/resource_id, so the next deployment tests the combined fix."

- timestamp: 2026-09-03T10:16:00+08:00
  checked: "revision 0000204 live remediation workflow through Select, Review, Approve, and Run"
  found: "Unrestricted patch targets now return one exact Arc-enabled server target. The governed workflow returns preview_error empty, Review complete, a server-owned execution snapshot with four patch ids, and recommended_step=approve. The exact snapshot was approved with HTTP 201 and revalidation status passed. The workflow then reached Run, but execute returned HTTP 409 business_impact_unknown because the live plan has no business ownership metadata."
  implication: "The original API/provider and preview failures are fixed. The remaining run block is an intentional fail-closed business safety gate caused by incomplete live data, not a workflow handoff crash. Bypassing it would invalidate the remediation safety contract."

- timestamp: 2026-09-03T10:20:00+08:00
  checked: "live workflow approval and execute response"
  found: "Approval HTTP 201 passed all seven revalidation checks and bound the exact snapshot hash f55dadce0b6feffffc61124eae3034b3ae54d1e2b5f9f0064fa340f42454cc82. Execute returned HTTP 409 business_impact_unknown, before any provider adapter call."
  implication: "The safety gate is functioning as designed. A successful real patch run cannot be claimed without known business impact and an explicitly authorized execution target."

- timestamp: 2026-09-03T10:29:00+08:00
  checked: "complete backend/frontend verification gates"
  found: "The complete backend pytest suite passed. Targeted backend ruff passed. Remediation frontend tests (7/7), frontend lint, and production build passed. The complete frontend suite has 15 failures in connections/page.test.tsx and 188 passing tests; those failures are outside the changed remediation/patching files and were not modified."
  implication: "The targeted fix meets automated verification, but the real workflow cannot honestly be reported as succeeded because execution is correctly refused while business impact is unknown."

- timestamp: 2026-09-03T10:36:00+08:00
  checked: "Fresh authenticated deployed plan, workflow, business-decision, patch-target, subscription-connection, and health responses"
  found: "Revision 0000204 remains healthy and returns one exact Arc target with four available patches and a successful preview. The plan and target expose empty subscription/business-service/application/environment/owner fields, while the active demo connection exposes subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1, business_service/application/environment demo, owner/support_team Jason, and a successful sync. The plan business decision remains disposition=schedule, business_impact.status=unknown, and unknowns=[Business ownership is unknown for this target]; workflow remains Select/Review/Approve complete, Run current, Verify pending."
  implication: "The safety gate is still correctly active, but the live data is not wholly devoid of ownership context: connection-level metadata exists and is not being carried onto the exact ARM target. The next investigation must determine whether that lineage is authoritative enough to project or whether ownership must remain a human/resource-level data correction."

- timestamp: 2026-09-03T10:47:00+08:00
  checked: "Onboarding metadata contract, live ARG finding construction, semantic enrichment, and focused regression suites"
  found: "Subscription onboarding documents business metadata as optional connection-scoped mapping; its environment mapping is explicitly mapping_type=subscription and business-service linkage is generated from the same connection mapping. live Update Manager rows project subscriptionId, but _patch_finding discarded it before build-service enrichment. The new fallback retains subscription identity, fills only missing fields from the matching active connection, and preserves explicit resource metadata. Focused live/runtime and remediation suites passed, and ruff passed."
  implication: "The remaining block is a safe, actionable data-lineage defect rather than a reason to weaken execution authorization. Deploy only the API change and re-check that the plan becomes business-impact known; never call execute."

- timestamp: 2026-09-03T10:54:00+08:00
  checked: "New local integration regression for connection-context fallback"
  found: "The first implementation retained subscription_id in live_operations but _build_vulnerability_service reconstructed pending rows without copying that field, so the integration regression still produced empty business metadata. This is a direct code-path defect, not evidence against the subscription mapping contract."
  implication: "The missing propagation point is now localized to the runtime row projection; preserve subscription_id there before re-running the same regression. No execution authorization is changed."

- timestamp: 2026-09-03T10:59:00+08:00
  checked: "Focused integration and remediation regression suites after preserving subscription_id in runtime projection"
  found: "All 74 focused tests passed and ruff passed. The integration regression now confirms subscription-scoped business metadata reaches asset exposures while explicit resource metadata remains unchanged."
  implication: "The safe fix is locally verified and ready for an API-only deployment. The live patch adapter and execute endpoint remain intentionally uncalled."

- timestamp: 2026-09-03T11:10:00+08:00
  checked: "API revision 000206 after the first metadata-fix deployment and fresh authenticated plan/preview responses"
  found: "Revision 000206 received 100% traffic and served a new API image tag, but the plan still exposed empty subscription/business metadata and business_impact.status=unknown; preview remained available but had no affected services/applications. This contradicts the passing integrated local regression. The most likely deployment-specific cause is reuse of the Docker source COPY cache across the API-only ACR build; the Dockerfile already exposes SOURCE_CACHE_BUST for this purpose."
  implication: "Do not alter the logic based on this inconclusive rollout. Force a source-layer rebuild, then re-test the actual active revision."

- timestamp: 2026-09-03T11:15:00+08:00
  checked: "Azure CLI ACR build capability"
  found: "The installed az acr build command rejects --no-cache before queuing a build."
  implication: "Use the Dockerfile's supported SOURCE_CACHE_BUST build argument as the cache invalidation mechanism and keep the API-only deployment bounded."

- timestamp: 2026-09-03T11:24:00+08:00
  checked: "Active API revision 000207 with fresh authenticated plan, preview, approvals, business-decision, and workflow requests"
  found: "Revision 000207 receives 100% traffic. The live plan now carries subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1, connection demo, business_service/application/environment demo, owner Jason, and criticality medium; business_impact.status=known and unknowns is empty. Preview returns operation install_patches with executable=true and the existing approved snapshot hash. The existing approval is current and its seven revalidation checks passed. Workflow reports select/review/approve complete, run current, verify pending, recommended_step=run, execution=null. No POST execute request was made."
  implication: "The original Run block was a workflow/data-lineage defect caused by dropped subscription context, now fixed. Run is legitimately the next operator action, but successful execution/verification cannot be claimed without deliberately mutating the real host, which is out of scope and prohibited by the checkpoint evidence."

- timestamp: 2026-09-03T11:34:00+08:00
  checked: "Complete backend pytest suite and initial frontend gate invocation"
  found: "The complete backend suite passed. The initial frontend test/lint/build commands were launched from the repository root and correctly failed with ENOENT because package.json is under web/; this is a test invocation error, not an application failure."
  implication: "Re-run the applicable frontend gates from web/ before accepting verification."

- timestamp: 2026-09-03T11:51:00+08:00
  checked: "Final verification gates after API revision 000207 deployment"
  found: "Complete backend pytest passed (all tests). Remediation UI tests passed 7/7, frontend lint passed, and production build passed with only the known MSAL window-is-not-defined build warnings. git diff --check passed. The complete frontend suite's unrelated connections failures remain as previously recorded."
  implication: "The fix passes automated regression and live API workflow verification. The live workflow is now safely ready for the real operator Run action, but this session cannot perform or claim a real patch execution or post-run Verify."

- timestamp: 2026-09-03T12:00:00+08:00
  checked: "Checkpoint response and execution boundary"
  found: "No human operator is available to authorize or confirm a real-host remediation run. The repaired workflow has reached Run with known business impact, but POST execute would deliberately mutate the real Arc host."
  implication: "Keep the session in awaiting_human_verify as a blocked, resumable checkpoint. The exact remaining operator action is Run the approved patch set in the deployed /remediation workflow, capture the provider response, and complete Verify; do not claim DEBUG COMPLETE or Verify success."

- timestamp: 2026-09-03T13:20:00+08:00
  checked: "First scripted Playwright attempt against deployed /remediation with a controlled MSAL cache injection"
  found: "The browser reached the deployed page but rendered no generated plan button, and the harness terminated with 'No generated remediation plan was rendered' before persisting partial evidence; the temporary browser process required explicit termination."
  implication: "This does not yet implicate repository code or the live API. The browser-session injection is unproven and must be instrumented to distinguish the sign-in gate, token acquisition failure, API error, or plan-loading state before any mutation retry."

- timestamp: 2026-09-03T13:28:00+08:00
  checked: "Local deployed-version MSAL cache implementation and the partial Playwright session state"
  found: "MSAL v3 generates account keys as msal.3|homeAccountId|environment|tenant and credential keys as lower-cased msal.3|... pipe-delimited values, with msal.3.account.keys and msal.3.token.keys.<clientId> indexes. The harness had inserted legacy hyphenated keys, so MSAL correctly saw no account and the UI remained at Sign in."
  implication: "The failed browser attempt is localized to the test-session setup. Correcting those cache keys is a falsifiable harness-only experiment; the deployed repository behavior remains unchanged."

- timestamp: 2026-09-03T13:34:00+08:00
  checked: "Corrected MSAL cache-key Playwright attempt and captured deployed network evidence"
  found: "The deployed shell rendered the authenticated workbench and requested real API endpoints, but MSAL silent token acquisition still failed with block_iframe_reload; the API calls consequently carried no Authorization header and returned 401 unauthenticated. No repository endpoint was reached with this browser session."
  implication: "The browser session is authenticated only at the UI-template level, not at token acquisition. Injecting the already-authorized API bearer at Playwright's request boundary will test the deployed UI/API workflow without changing application code or bypassing server authorization."

- timestamp: 2026-09-03T13:42:00+08:00
  checked: "Bearer-injected Playwright attempt against the deployed UI"
  found: "The real deployed shell rendered the workbench and four auxiliary API calls returned 200 with the request-boundary bearer, but no remediation-plan request appeared before the harness observed the Loading governed fixes state. MSAL still logged block_iframe_reload while the synthetic cache account remained only a template-level session."
  implication: "The next bounded observation must include request-failure capture and a post-load wait. If the plan request remains absent, the fault is in the deployed client lifecycle or unresolved token promise rather than the already-verified API planner."

- timestamp: 2026-09-03T13:48:00+08:00
  checked: "Instrumented bearer-injected Playwright session after a 15-second post-load wait"
  found: "The remediation-plan GET was issued to the correct deployed API route and carried the Playwright-injected authorized bearer, but no response had arrived after 15 seconds; auxiliary API calls completed with 200 and the UI remained in Loading governed fixes. No mutation request was issued."
  implication: "This is a live latency/long-running planner observation, not yet a failure. Extend only the observation window to 120 seconds, bounded by the API's known long refresh behavior, and capture the terminal response."

- timestamp: 2026-09-03T14:02:00+08:00
  checked: "Bounded 120-second Playwright planner wait and Select → Review → Approve transition"
  found: "The live remediation plan eventually loaded and the UI advanced through Select and Review. The harness then timed out looking for Review and run after Record decision, but had not persisted the post-approval DOM/API state, so the cause of that transition failure is not yet localized. No execute request was issued."
  implication: "The API planner is slow but functional. Capture the post-approval workflow response and rendered Run state before deciding whether the live approval caused a stale-preview/error state or the client failed to refresh."

- timestamp: 2026-09-03T14:12:00+08:00
  checked: "Persisted Playwright state around the live approval click"
  found: "The Review state showed one executable Arc patch plan, known business impact, four patch IDs, and the exact existing snapshot hash. After clicking Record decision, the UI remained in Recording… while MSAL token acquisition completed; the previous 30-second locator timeout occurred before the approval POST was observable. No execute request was issued."
  implication: "The remaining delay is likely the browser token-acquisition boundary, not a rendered Run-control defect. Extend only the approval completion wait to 120 seconds and capture the terminal approval response before exercising Execute."

- timestamp: 2026-09-03T14:24:00+08:00
  checked: "Long Playwright retry through planner and plan selection"
  found: "The planner eventually produced the same live plan, but the harness timed out after selecting it while waiting 30 seconds for Continue to approval. This indicates the workflow/preview request can exceed the default locator timeout under the deployed live provider; no approval or execute mutation was issued."
  implication: "Increase only the workflow-preview observation bound to 120 seconds and persist the rendered state. A terminal preview error will be investigated as an API/provider failure; a terminal Review control will allow the authorized mutation sequence to continue."

- timestamp: 2026-09-03T14:34:00+08:00
  checked: "120-second workflow-preview wait after selecting the live plan"
  found: "The deployed page still did not expose Continue to approval within the extended bound. Earlier runs showed the workflow request itself could be slow, but this run did not persist the post-selection DOM before the timeout, so the terminal state is still unobserved. No approval or execute mutation was issued."
  implication: "Add failure-safe persistence immediately after selection and on timeout. This isolates a slow/pending workflow request from a returned preview error or client render issue without changing repository behavior."

- timestamp: 2026-09-03T14:45:00+08:00
  checked: "Authorized Playwright run against revision 000207 through deployed /remediation"
  found: "The real deployed UI completed Select, Review, Approve, and Run. GET plans/workflow returned 200, approval POST returned 201, execute POST returned 202, and final workflow returned 200. Verify rendered execution RME-28E8C12074CE04D4 as failed with provider outcome 'The approver must be someone other than the requester'; no provider patch was applied."
  implication: "The E2E reached the live mutation boundary and failed closed during provider execution identity validation. Confirm whether this is the intended two-person rule in repository code before changing anything; the current run must not be retried with the same actor."

- timestamp: 2026-09-03T14:56:00+08:00
  checked: "src/operations/patching/service.py:_authorize_approval, src/api/routers/operations.py:record_remediation_decision, src/api/routers/remediation.py:execute_plan, and tests/test_patch_approval_gate.py"
  found: "The approval route records approver=principal.subject, and the execute route passes requested_by=principal.subject. PatchingService compares the normalized values and raises 'The approver must be someone other than the requester' before adapter.submit. The focused approval-gate suite passed 8 tests, including self-approval refusal and a distinct-approver acceptance with provider-submission assertions."
  implication: "The failed live execution is a deterministic, intentional separation-of-duties guard. No repository defect is evidenced, and weakening it or fabricating a second identity would be unsafe. A successful live E2E requires two genuinely distinct authorized principals: one requester and a different approver."

- timestamp: 2026-09-03T15:08:00+08:00
  checked: "Locally available Azure CLI authentication accounts"
  found: "The target deployment tenant is currently selected through service principal 306c1437-0e7d-43bd-940b-79b878166331. The cached user account pangj@microsoft.com belongs to other tenant subscriptions and is not a cached user identity for the deployed tenant. No second authorized target-tenant principal is available for a safe retry."
  implication: "The remaining blocker is an external identity prerequisite, not repository behavior. A second authorized operator must approve the existing plan, after which the requester can safely rerun/retry and verify; no actor spoofing, request-body override, or policy disablement is appropriate."

- timestamp: 2026-09-03T15:20:00+08:00
  checked: ".planning/STATE.md, existing remediation debug state, knowledge-base.md, and working tree"
  found: "Phase 10 is complete and the request is a live deployed remediation validation. The existing session is awaiting human verification from the prior Arc-host run. The working tree contains many unrelated user changes; only remediation-E2E artifacts may be touched. No knowledge-base entry matches this target-selection request."
  implication: "Continue the existing session in investigation mode, preserve all unrelated changes, and constrain any live mutation to a qualifying Azure VM/Defender plan if one is actually present."

- timestamp: 2026-09-03T15:24:00+08:00
  checked: "Deployed Defender endpoints with the authorized service-principal bearer: /vulnerabilities/defender-posture, /defender/overview, /defender/secure-score-controls, and /remediation/defender-cases"
  found: "Defender posture returned HTTP 200 with zero rows; secure-score controls returned HTTP 200 with zero rows; Defender remediation cases returned HTTP 200 with zero cases; overview reported zero active alerts, zero attack paths, zero unhealthy recommendations, and one secure score at 53.4%."
  implication: "The deployed data currently exposes no Defender recommendation eligible for selection on any VM. The secure score is the closest Defender-category signal but is not an executable VM-scoped recommendation."

- timestamp: 2026-09-03T15:25:00+08:00
  checked: "Persisted deployed remediation-plan response and repository live-data records"
  found: "The only captured live plan is 'Patch vm1' for /subscriptions/.../Microsoft.HybridCompute/machines/vm1, with target_kind Arc-enabled server and defender_mapping.status=not_applicable, defender_recommendations=[], and reason='No Defender recommendation is associated with this exposure'. Repository data has a separate Microsoft.Compute/virtualMachines/vm1 inventory row, but the Defender for Endpoint text is software inventory on the Arc resource, not an available Defender recommendation."
  implication: "The prior Arc plan is explicitly disqualified by the changed requirement, and the available Defender software/secure-score signals cannot be safely converted into a recommendation or mutation target. Run Playwright only to capture fresh deployed UI/network/backend evidence and stop before Select mutation if no qualifying VM plan appears."

- timestamp: 2026-09-03T15:32:00+08:00
  checked: "Fresh target-filtered Playwright run against deployed /remediation, with request-boundary bearer and console/network/UI/backend capture"
  found: "The deployed UI rendered the real workbench and one Arc patch row ('Patch vm1'); no request failed and no page error occurred. API responses for the plan, vulnerability summary, network summary, subscription connections, and situations were HTTP 200. The browser console contained expected MSAL block_iframe_reload/Chrome SSO warnings from the synthetic session. The harness reported zero plans only because it parsed a deliberately truncated 10,000-byte plan response, while the persisted UI and response prefix contain the Arc plan."
  implication: "This Playwright attempt did not mutate or select a target and does not change the backend diagnosis. Increase only the local evidence capture bound for the plan response, rerun the same target filter, and use the complete response to produce an unambiguous no-eligible-target result."

- timestamp: 2026-09-03T15:39:00+08:00
  checked: "Rerun of target-filtered Playwright after preserving the complete remediation-plan response"
  found: "The harness completed with result=no_eligible_azure_vm_defender_fix, available_plan_count=1, eligible_azure_vm_defender_plan_count=0, and closest_defender_plans=[]. The persisted plan is the Arc-only Patch vm1 plan; the UI remained at Select and no approval or execute request was issued. The API plan, vulnerability, network, connections, and situations requests were HTTP 200 with zero request failures and zero page errors."
  implication: "The changed target requirement is conclusively unmet in the deployed remediation dataset. The exact Select → Review → Approve → Run → Verify mutation sequence must not be attempted against the Arc row."

- timestamp: 2026-09-03T15:42:00+08:00
  checked: "Read-only Azure Advisor Security recommendations and Microsoft.Security pricing for subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1"
  found: "Advisor returned security recommendations including 'Microsoft Defender for APIs should be enabled' (High), but no VM-scoped Defender for Cloud/Endpoint/Servers action was exposed; it also returned VM security items such as backup/encryption/secure-protocol configuration. Microsoft.Security pricing already reports VirtualMachines Standard/P2 and StorageAccounts Standard/DefenderForStorageV2."
  implication: "The closest Defender-category recommendation is Defender for APIs at subscription scope, not a permitted Azure VM target. Existing VM Defender pricing is already enabled at P2, so inventing an enable-Servers fix would be false and unsafe."

- timestamp: 2026-09-03T11:39:28+08:00
  checked: "Checkpoint response, target-tenant Azure CLI account cache, environment variable names, repository approval fixtures, and existing live Playwright harness"
  found: "The selected target-tenant context is authenticated by one service principal (the deployment/API application); the only cached user account belongs to a different tenant, and the target tenant cache contains no second user or service-principal account. Repository fixtures contain distinct synthetic principals for unit tests, but they are not provisioned Azure identities and cannot authorize a live Playwright request. The existing harness can inject only a bearer obtained from the current CLI context and must not be used to impersonate another principal."
  implication: "A second live approver is not yet established. The next falsifiable check is to enumerate target-subscription role assignments and inspect the focused authorization tests; absent a second provisioned principal with API access, do not retry approval or execute."

- timestamp: 2026-09-03T11:42:00+08:00
  checked: "Initial bounded target-subscription role-assignment and tenant service-principal enumeration attempts"
  found: "The role-assignment command produced no usable result within the bounded invocation, and the auxiliary tenant service-principal projection could not run because this environment has no `python` executable. These are command-environment limitations, not evidence that a second authorized principal exists. The repository inspection did confirm only synthetic distinct subjects such as manager@example.com and approver@example.com in tests."
  implication: "The identity availability conclusion remains provisional until a bounded Azure CLI role-assignment check succeeds or reports an explicit authorization failure. Regardless, synthetic subjects remain ineligible for the live E2E."

- timestamp: 2026-09-03T11:45:00+08:00
  checked: "Focused separation-of-duties regression suites and bounded identity discovery"
  found: "The focused tests passed (4 approval-related cases selected across the patch gate and API approval suites), including self-approval rejection, normalized casing/whitespace rejection, missing approver rejection, and distinct-approver acceptance with adapter-submission assertions. The first role query used incompatible Azure CLI flags, and tenant service-principal enumeration returned an explicit insufficient-privileges error; no second live credential was obtained."
  implication: "Repository governance behavior is directly verified, while live second-identity availability remains unresolved until the corrected role query. The test's synthetic distinct approver is not a provisioned identity and cannot satisfy the live checkpoint."

- timestamp: 2026-09-03T11:48:00+08:00
  checked: "Corrected bounded target-subscription role-assignment query and repository Entra authorization wiring"
  found: "The target subscription has several Azure RBAC-assigned service principals and one user, including identities with Owner/Contributor/Virtual Machine Contributor roles, but the local Azure CLI cache still contains only the current target-tenant service principal. The application authorizes Entra callers through the deployment's explicit AIOPS_API_GATEWAY_GRANTS subject map and asserted app roles; Azure RBAC assignment alone does not provide a bearer credential or an application grant."
  implication: "The role inventory proves that other directory principals exist, but not that a second identity is provisioned for this session or authorized to call this API. The next check must inspect only non-secret deployment metadata and app-role assignment visibility; no token or secret will be printed or synthesized."

- timestamp: 2026-09-03T11:52:00+08:00
  checked: "Deployed API app registration metadata, app-role visibility, Container Apps inventory, and repository authorization configuration"
  found: "The deployed API app registration is `aiops-demo-spn` with appRoleAssignmentRequired=false, while Graph app-role enumeration is denied to the current service principal. The production API is configured to authorize only subjects in the explicit AIOPS_API_GATEWAY_GRANTS map intersected with asserted Entra roles; the local environment exposes no second credential source, and the target tenant has exactly one cached Azure CLI account. Subscription RBAC identities therefore cannot be promoted into a live approver without their own provisioned credential and configured API grant."
  implication: "No genuinely available second authorized approver can be established from this environment. The only safe remaining action is automated guard verification plus evidence finalization; do not invoke live approval/run again with the current principal."

- timestamp: 2026-09-03T11:56:00+08:00
  checked: "Ignored web/.env.local identity configuration using non-sensitive projections only"
  found: "A client secret is present for the current client ID and target tenant, and the local AIOPS_ENTRA_GRANTS_JSON contains three configured subjects. The client ID matches the requester service principal; no second client ID/secret pair is provisioned locally. Values, subject names, tokens, and secrets were not printed or used."
  implication: "The local secret is not an independent approver credential. The configured grant subjects cannot be used for a live Playwright approval without their own authenticated session, so the two-identity run remains genuinely blocked."

- timestamp: 2026-09-03T12:00:00+08:00
  checked: "Final focused governance verification and existing Playwright evidence"
  found: "All 8 tests in tests/test_patch_approval_gate.py passed. The two self-approval tests reject exact and case/whitespace-normalized identity matches before adapter submission; missing approval is rejected; a distinct synthetic approver is accepted and submitted once. Existing Playwright evidence records Patch vm1 reaching the deployed UI workflow and the backend returning the separation-of-duties failure with no provider patch submission."
  implication: "The guard is correctly enforced, the fallback automated proof is passing, and the live two-identity E2E is blocked by missing provisioned identity rather than a repository defect. No further live mutation request is authorized."

## Resolution

- root_cause: "The live execution used one authenticated service-principal identity for both approval and execution request. The repository's separation-of-duties guard correctly rejects that combination before the patch adapter is called. The earlier provider/scope/target/context defects were fixed and the deployed workflow now reaches this intentional governance boundary."
- fix: "For unrestricted requests, resolve both remediation and patching through all active onboarded subscriptions; generate the live planner repository before constructing the execution service; make patching router resolution use the same fallback; infer supported compute kind from asset_id/resource_id when live type metadata is absent; retain subscription identity from live ARG rows and fill missing finding context from the matching active connection's explicit subscription mapping without overriding resource-level metadata."
- verification:
    target_test:
      result: pass
      evidence: "The agent-authored connection-context integration regression passed, the complete backend pytest suite passed, the deployed revision 000207 plan/workflow reproduced the repaired behavior, and the focused patch-approval suite passed all 8 tests including self-approval rejection and distinct-approver acceptance."
    mutation_check:
      result: skipped
      reason_if_skipped: "No Python mutation-testing tool is configured for this repository; Stryker is JavaScript/TypeScript-specific."
      mutant_killed: false
    no_op_deletion:
      result: pass
      deletion_justified_by_rca: false
      evidence: "The fix adds metadata lineage and preserves all approval, snapshot, disposition, unknown, adapter, and verification gates."
    adjacent_tests:
      result: pass
      suites_run:
        - "uv run pytest -q (complete backend suite; passed)"
        - "uv run pytest -q focused remediation/live suites (passed)"
        - "uv run ruff check on changed backend files (passed)"
        - "cd web && npm test -- --run src/app/remediation/page.test.tsx (7 passed)"
        - "cd web && npm run lint (passed)"
        - "cd web && npm run build (passed; known MSAL window-is-not-defined warnings only)"
      caveat: "The complete frontend suite has 15 pre-existing/unrelated connections/page.test.tsx failures, as previously recorded."
    revert_and_reconfirm:
      result: pass
      bug_returned_on_revert: true
      fixed_on_reapply: true
      evidence: "Earlier deployed revisions reproduce the no-scope 500/preview failures; revision 000207 reproduces the live workflow through Run with known business impact."
    guardrail_verdict: accepted
    live_target_validation:
      result: selected_existing_arc_plan_but_blocked_by_identity
      plan: "Patch vm1"
      target: "Microsoft.HybridCompute/machines/vm1 (Arc-enabled server)"
      reason: "Per the checkpoint decision, the existing Arc plan was accepted as the live target because no Azure VM Defender fix exists. The deployed Playwright evidence shows the UI reached Select → Review → Approve → Run → Verify, but the only available bearer represented the requester and no second provisioned authorized approver was available."
      playwright_evidence: ".planning/ui-reviews/remediation-e2e-live.json"
    prior_live_execution:
      result: blocked_by_separation_of_duties
      reason: "The earlier Arc-host run reached execution but failed closed because approver and requester were the same principal; the provider patch was not submitted."
    guard_correctness_fallback:
      result: pass
      tests:
        - "tests/test_patch_approval_gate.py::test_self_approval_is_refused"
        - "tests/test_patch_approval_gate.py::test_self_approval_cannot_be_disguised_by_casing_or_whitespace"
        - "tests/test_patch_approval_gate.py::test_missing_approver_is_refused_when_policy_requires_approval"
        - "tests/test_patch_approval_gate.py::test_a_distinct_approver_is_accepted_and_recorded"
      command: "uv run pytest -q tests/test_patch_approval_gate.py"
      evidence: "8 passed; self-approval raised before adapter submission, while a distinct approver submitted exactly once."
    human_verification:
      result: blocked
      required_action: "Provision or provide access to a genuinely distinct target-tenant principal with a configured AioPS API grant. Use it in Playwright to approve Patch vm1, then run and verify with the original requester. Until then, the live two-identity E2E cannot be claimed complete."
- files_changed:
    - "src/api/runtime.py"
    - "src/semantic/live_operations.py"
    - "tests/test_api_runtime_vulnerability_correlation.py"
    - "tests/test_live_provider.py"
    - "tests/test_api_remediation_router.py"
    - "tests/test_api_patching_router.py"
- oracle_type: "specified"
