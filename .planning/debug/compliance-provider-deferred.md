---
status: verifying
trigger: "https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/compliance not loading. showing error \"Compliance evaluation unavailable. The vulnerability provider is deferred\""
created: "2026-09-12T17:43:15+08:00"
updated: "2026-09-12T20:48:00+08:00"
---

## Symptoms

- expected: The deployed compliance page loads governed compliance posture and supporting vulnerability/network evidence.
- actual: The page fails to load its compliance evaluation.
- errors: `Compliance evaluation unavailable. The vulnerability provider is deferred`
- timeline: Reported against the live dev deployment on 2026-09-12; the page worked in earlier compliance releases.
- reproduction: Open `https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/compliance`.

## Current Focus

reasoning_checkpoint:
  hypothesis: "The Compliance regression requires two code defects from the hydration cutover: unscoped vulnerability reads fall through to the intentionally deferred snapshot provider, and change compliance has no bounded provider because its loader delegates to the memory-heavy all-domain operations agent."
  confirming_evidence:
    - "Authenticated live probes show all three unscoped network routes return 200 through their onboarded-subscription fallback, unscoped `/vulnerabilities/exposures` returns the exact 503, and the same exposure request with an explicit subscription returns 200."
    - "All four `/compliance/*` routes return 503 `change provider is deferred`; `_fabric_change_intelligence` currently calls `runtime.operations_agent()`, which constructs patch, lifecycle, incident, predictive, remediation, and change intelligence together."
    - "Eagerly enabling all providers caused two exit-137 terminations on an 8Gi replica, proving full hydration is not a viable fallback."
  falsification_test: "The hypothesis is false if unscoped vulnerability still fails after using active onboarded subscriptions, if direct ChangeIntelligence construction invokes operations_agent/full-domain hydration, or if the bounded canary exceeds memory/restarts."
  fix_rationale: "Retain intentional deferral for full-snapshot providers, route unscoped vulnerability through the already-bounded hybrid path exactly as network does, and schedule only a directly constructed change provider; this restores every Compliance dependency without loading incident/remediation/duplicate snapshot graphs."
  blind_spots: "Direct change construction still needs one semantic engine and must be proven under production-scale data; live canary must show no exit 137, stable readiness, and 200 responses from all eight page dependencies."
  candidate_causes:
    - "code: vulnerability `_service` lacks network's active-onboarded-subscription fallback (confirmed)"
    - "code: change provider is permanently deferred because its existing constructor is coupled to full `operations_agent` hydration (confirmed)"
    - "config/environment: Fabric mode activates the deferral policy and 8Gi is insufficient for eager all-domain hydration, but both are valid deployment constraints"
    - "data: production graph volume amplifies eager hydration, but explicit-subscription hybrid vulnerability succeeds against the same data"
  and_gate: "yes — full Compliance recovery requires both an unscoped vulnerability fallback and an independently loadable change provider; either fix alone leaves one page section unavailable"
next_action: "Build and deploy a v2 bounded canary containing the corrected optional semantic-graph lookup, then repeat stability and all eight authenticated Compliance dependency checks."
reasoning_checkpoint:
  hypothesis: "The deployed d19af3cba code causes the compliance failure because it marks Fabric vulnerability/network/change providers permanently unscheduled and skips them on every refresh."
  confirming_evidence:
    - "Live `/health` repeatedly reports the affected providers as deferred with loaded=false, blank last_attempt_at, and attempts=0."
    - "The deployed ACR digest is tagged to d19af3cba, whose provider loop explicitly continues past every `scheduled=False` spec."
    - "The compliance page's first-error chain includes vulnerability exposures, which resolves the missing vulnerability provider and emits the exact reported message."
  falsification_test: "If a current-HEAD image starts and vulnerability/network/change still remain deferred with zero attempts, or the new scheduling regression test passes against d19af3cba semantics, this hypothesis is wrong."
  fix_rationale: "Current HEAD removes the permanent opt-out and restores every configured provider to the background refresh lifecycle; regression coverage locks that startup contract, and an API-only immutable rollout replaces the affected code without changing data, RBAC, web, or infrastructure."
  blind_spots: "Resolved by failed live verification: full hydration does expose startup instability, so the original fix direction is rejected and investigation resumes."
  candidate_causes:
    - "code: d19af3cba retains 2bc5b2a81's permanent scheduled=False skip for supported Fabric providers (confirmed)"
    - "config: AIOPS_ENABLE_FABRIC=true activates the bad branch, but this is valid required production configuration rather than a defect"
    - "environment: revision 0000294 runs the affected immutable digest while current source no longer contains the policy"
    - "data: ruled out for the deferred state because no loader or cache-key attempt ever occurs"
  and_gate: "no — the permanent code-level scheduling exclusion alone fully explains the zero-attempt deferred state; Fabric configuration is the legitimate trigger condition, not a second defect"
bug_class: bohrbug
candidate_causes:
  - "code: startup/provider refresh selection excludes optional providers after readiness was narrowed to core providers"
  - "config: deployed feature flags or provider mode intentionally defer vulnerability/network/change"
  - "environment: the live revision lacks a worker/background refresh process needed to schedule deferred providers"
  - "data: active provider metadata marks only exposure_query as eligible"
and_gate: "unknown; test whether a code scheduling omission alone explains all deferred/no-attempt states or requires a deployment/config condition"

## Evidence

- timestamp: 2026-09-12T17:43:15+08:00
  checked: deployed API `/health`
  found: readiness is `ready`, but `vulnerability`, `network`, `change`, `remediation`, `remediation_catalog`, `semantic`, and `semantic_graph` all report `state=deferred`, `loaded=false`, and no attempts; only `exposure_query` is loaded.
  implication: This is a provider scheduling/defer-policy regression, not a single vulnerability loader exception.

- timestamp: 2026-09-12T17:49:00+08:00
  checked: debug knowledge base and repository history
  found: The closest prior pattern is network-topology-live-ui, whose fix made provider reads last-known-good and moved loading to startup/background refresh. HEAD is a newer commit, 39080ceba (`added health for container apps`), making startup/health changes the highest-priority differential.
  implication: Treat the prior pattern as a hypothesis candidate only; inspect whether the latest health change accidentally removed the sole scheduler for optional providers.

- timestamp: 2026-09-12T17:49:00+08:00
  checked: initial code search
  found: Provider refresh is centralized in `src/api/app.py` and `src/api/providers.py`; runtime registers `exposure_query` separately from hybrid vulnerability/network callables, and the compliance failure text is not a static frontend string found by the broad search.
  implication: Trace provider spec defer policy and compliance dependency resolution rather than changing the page.

- timestamp: 2026-09-12T17:53:00+08:00
  checked: local provider lifecycle implementation and latest commit diff
  found: Local `ProviderRuntime.refresh(force=True)` iterates every configured spec synchronously; there is no `deferred` state constant or selective scheduling branch. Commit 39080ceba only changed resource-health/container-app collection and did not touch provider startup, health, or deployment configuration.
  implication: The latest local commit cannot directly produce live `state=deferred`; the deployed image likely contains different source or deployment-time code/config not represented by local HEAD.

- timestamp: 2026-09-12T17:53:00+08:00
  checked: spectrum-based fault localization eligibility
  found: There is no currently failing local test reproducing the deployed `deferred` state, and local provider tests encode all-provider forced refresh.
  implication: SBFL is skipped because the prerequisite failing test spectrum does not exist; use differential debugging against the deployed revision.

- timestamp: 2026-09-12T17:57:00+08:00
  checked: all git refs/history for provider defer state
  found: Commit 2bc5b2a81 is explicitly titled `fix: defer full ontology hydration` and introduces `DEFERRED`, including initial deferred state and readiness handling. That code exists in origin/fix/kb-detail-silver and its descendants but not local main.
  implication: This commit is a direct, testable source candidate for the deployed state and explains the image/source mismatch.

- timestamp: 2026-09-12T17:57:00+08:00
  checked: compliance page dependency graph
  found: The primary page error selects the first failure among topology, gaps, rule findings, and vulnerability exposures. Those requests resolve network/vulnerability providers; governed compliance/change errors are rendered separately.
  implication: The reported `vulnerability provider is deferred` is produced by the page's vulnerability exposure request and will recur until deferred provider hydration is scheduled.

- timestamp: 2026-09-12T18:01:00+08:00
  checked: commit 2bc5b2a81 implementation
  found: It added `ProviderSpec.scheduled`, initialized configured-but-unscheduled providers to `deferred`, skipped every unscheduled spec on every forced and periodic refresh, and explicitly set vulnerability/network/change/semantic/remediation plus related read ports to `scheduled=False` whenever Fabric is configured.
  implication: The behavior is permanent deferral, not staggered hydration. It deterministically produces zero attempts forever and directly causes the compliance API dependency failure.

- timestamp: 2026-09-12T18:01:00+08:00
  checked: Azure Container App inventory
  found: Live API is revision `aiops-dev-api--0000294` using immutable digest `sha256:d8186200840309902795ba6101d1c58dd35f5ed60d7cf9a06e27509b055e3e51`; live web is revision 0000228.
  implication: Verification and remediation can be scoped to an API-only immutable rollout, preserving other deployed capabilities and unrelated working-tree files.

- timestamp: 2026-09-12T18:05:00+08:00
  checked: live API `/health` and `/ready`
  found: Both reproduce deterministically. `vulnerability`, `network`, `change`, `semantic`, `semantic_graph`, `governance`, inventory/remediation providers are `deferred`, `loaded=false`, `last_attempt_at=""`, attempts 0; `exposure_query` is ready. Overall readiness remains ready because deferred capabilities were marked optional.
  implication: This exactly matches 2bc5b2a81's permanent `scheduled=False` mechanism and rules out transient loader failures, retry backoff, and missing provider data as the cause of these states.

- timestamp: 2026-09-12T18:05:00+08:00
  checked: ACR metadata for deployed digest
  found: Digest `d818620...` is tagged `network-live-routing-d19af3cba-20260912`, tying the deployment to commit d19af3cba.
  implication: The deployed source provenance is now known and can be compared directly with current HEAD before rollout.

- timestamp: 2026-09-12T18:09:00+08:00
  checked: deployed d19af3cba provider code versus current HEAD
  found: d19af3cba retains `DEFERRED`, `ProviderSpec.scheduled`, and unconditional skipping of every unscheduled provider. Current HEAD removes that mechanism and restores all configured provider specs to normal loading/refresh behavior.
  implication: The source-level correction already exists in the current tree; the remaining engineering work is regression coverage plus a safe immutable API rollout.

- timestamp: 2026-09-12T18:09:00+08:00
  checked: existing runtime tests
  found: Tests verify cache keys and individual ProviderRuntime refresh behavior but do not assert that production Fabric vulnerability/network/change specs are startup-scheduled; the deferral commit deliberately asserted the opposite.
  implication: A focused test is needed to prevent another deployment from silently converting supported operational providers into permanent deferred capabilities.

- timestamp: 2026-09-12T18:18:00+08:00
  checked: focused verification attempt and static checks
  found: Ruff and `git diff --check` pass. Pytest collection was blocked before repository tests ran because globally autoloaded Phoenix is incompatible with the local Python 3.11 dataclass runtime (`mappingproxy` mutable default).
  implication: This is an environment/plugin collection issue unrelated to the change; rerun with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` to exercise repository tests without unrelated global plugins.

- timestamp: 2026-09-12T18:21:00+08:00
  checked: focused provider/runtime suite with plugin autoload disabled
  found: 57 tests passed; the new regression assertion confirms semantic, semantic_graph, network, vulnerability, and change all initialize as scheduled/loading under Fabric configuration. Ruff and diff checks also pass.
  implication: Current HEAD contains the source-level recovery and focused regression protection; proceed to adjacent tests and immutable deployment preparation.

- timestamp: 2026-09-12T18:23:00+08:00
  checked: API deployment constraints
  found: The live API uses Single revision mode with 4 CPU/8Gi and Terraform pins the affected digest; API build inputs are clean at HEAD except the new test file. The first adjacent test command named a nonexistent `tests/test_api_compliance.py` and ran no tests.
  implication: Correct the test file selection before deployment; use an immutable HEAD archive so unrelated planning changes and the uncommitted test do not enter the production image.

- timestamp: 2026-09-12T18:26:00+08:00
  checked: adjacent operational API regression suite
  found: 127 tests passed across compliance, network, vulnerability, and operational-twin routes with third-party pytest plugin autoload disabled.
  implication: Current source preserves adjacent endpoint contracts; proceed to an immutable current-HEAD API-only build.

- timestamp: 2026-09-12T18:34:00+08:00
  checked: ACR immutable build from `git archive HEAD`
  found: `aiops-api:compliance-provider-recovery-39080ceba-20260912T1026Z` built successfully for linux/amd64 from committed HEAD; unrelated working-tree files and the uncommitted regression test were excluded from the build context by construction.
  implication: Resolve and pin the immutable digest, then require a one-resource in-place API-only deployment plan.

- timestamp: 2026-09-12T18:38:00+08:00
  checked: immutable digest and targeted Terraform plan
  found: The new image resolves to `sha256:a2200f11f303bd93920b4ec4e28ff17432396edd2ca265900d02fd6101af9a78`. The saved targeted plan reports exactly 0 additions, 1 in-place `azurerm_container_app.api` image change, and 0 destructions; 66 container blocks and all infrastructure remain unchanged.
  implication: The rollout is within Phase 4 scope and preserves web, MCP, RBAC, identities, secrets, Fabric resources, and unrelated working-tree changes.

- timestamp: 2026-09-12T18:41:00+08:00
  checked: targeted Terraform apply
  found: Apply completed successfully with 0 additions, 1 in-place API update, and 0 destructions, pinning digest `sha256:a2200f11f303bd93920b4ec4e28ff17432396edd2ca265900d02fd6101af9a78`.
  implication: Monitor activation and full provider hydration before accepting the operational fix.

- timestamp: 2026-09-12T18:53:00+08:00
  checked: bounded post-deploy monitoring
  found: Revision 0000296 became latest-ready on the new digest. Responses from hydrated replicas showed vulnerability, network, semantic, and semantic_graph loaded successfully with non-empty attempt/success timestamps and no retry errors; subsequent sampling also observed a newly-starting replica where change was still loading.
  implication: Permanent deferral is removed and loaders execute, but multi-replica startup stability and the exact compliance dependency responses still require verification.

- timestamp: 2026-09-12T19:00:00+08:00
  checked: repeated live health samples and replica state
  found: Revision 0000296 restarted once, repeatedly remained at `change=loading` with no attempt while earlier providers were loaded, then `/health` returned 503/timeouts. The single replica was marked ready but became unresponsive under continued startup hydration.
  implication: The all-at-once source recovery fails the live stability guardrail. Roll back immediately; the final fix must preserve bounded startup while making deferred providers eventually progress.

- timestamp: 2026-09-12T19:14:00+08:00
  checked: rollback to prior immutable digest
  found: Revision 0000297 became latest-ready on digest d818620... and restored stable `/health` readiness. Vulnerability/network/change returned to the known deferred state.
  implication: Service routability is restored while investigation continues; no unstable revision remains serving traffic.

- timestamp: 2026-09-12T19:14:00+08:00
  checked: failed revision console and replica evidence
  found: Revision 0000296 logged a fresh server process at 10:09 after earlier hydration at 10:03, had restartCount at least 1, and then returned readiness 503 continuously while the forced startup refresh had not reached change.
  implication: The hypothesis that simply restoring monolithic eager hydration is safe is eliminated; determine whether the recycle was OOM or readiness/probe policy and design bounded hydration.

- timestamp: 2026-09-12T19:19:00+08:00
  checked: Container Apps system logs for revision 0000296
  found: The API process was terminated with exit code 137 twice, at 10:02:46Z and 10:08:42Z, after roughly five to six minutes of hydration each time; readiness failed throughout.
  implication: The failed fix deterministically exhausts the container memory budget. Any accepted fix must retain bounded provider loading and cannot eagerly hydrate the full ontology provider set.

- timestamp: 2026-09-12T19:27:00+08:00
  checked: authenticated live requests for all Compliance page dependencies
  found: Unscoped network topology/gaps/rule-findings all return 200 because the network router derives active onboarded subscriptions. Unscoped vulnerability exposures returns 503 deferred, while the identical request with an explicit subscription returns 200 via the hybrid provider. All four governed compliance/change routes return 503 deferred.
  implication: The precise route gaps are isolated: vulnerability lacks network's safe unscoped fallback, and change needs a bounded scheduled provider; full provider hydration is unnecessary.

- timestamp: 2026-09-12T19:27:00+08:00
  checked: change provider construction
  found: `_fabric_change_intelligence` delegates to `runtime.operations_agent()`, which eagerly constructs patch, lifecycle, incident, change, predictive, and remediation domains. `ChangeIntelligence.from_semantic_engine` can instead consume only `change_intelligence_snapshot()` plus the shared semantic engine.
  implication: Change can be decoupled from the monolithic memory path and scheduled independently.

- timestamp: 2026-09-12T19:41:00+08:00
  checked: bounded fix focused verification
  found: 188 focused tests passed across provider runtime, compliance, network, and vulnerability; Ruff and diff checks pass. Tests cover intentional defer-without-I/O, lightweight change construction without `operations_agent`, and active-only unscoped network/vulnerability fallback.
  implication: The bounded design is locally coherent and directly covers both confirmed cause branches; proceed to full regression and live canary.

- timestamp: 2026-09-12T19:48:00+08:00
  checked: full Python suite and full Ruff/compile checks
  found: Ruff and compileall pass. The full suite completed with two performance-only failures: an RSS delta measured exactly zero and network p95 measured 1.062s against a 1.0s threshold; all functional tests passed.
  implication: These failures do not touch changed code and appear load-sensitive from the full parallel workload, but must be rerun independently before classifying them as environmental noise.

- timestamp: 2026-09-12T19:51:00+08:00
  checked: isolated reruns of full-suite failures
  found: Both the 100k Exposure RSS gate and network p95 gate pass when rerun individually with identical code.
  implication: The full-suite failures were transient measurement interference rather than regressions; proceed to scoped canary build.

- timestamp: 2026-09-12T19:56:00+08:00
  checked: final focused suite after preserving ready-state behavior
  found: 188 tests and all scoped Ruff/diff checks pass. The runtime keeps all providers optional for process readiness, schedules only exposure_query and lightweight change in Fabric mode, and leaves full-snapshot providers deferred.
  implication: Build a canary containing exactly the reviewed source overlay.

- timestamp: 2026-09-12T20:02:00+08:00
  checked: bounded canary build and deployment
  found: ACR built immutable digest `sha256:da30c17faaf03def3bb62ed56bf04e1d5173e0d31a81394b6b52c9c6680933cd` from HEAD plus only the four reviewed production files. Machine-checked Terraform plan and apply performed exactly one in-place API update, with 0 additions and 0 destructions.
  implication: Verify the live revision's memory stability and exact Compliance behavior before acceptance.

- timestamp: 2026-09-12T20:48:00+08:00
  checked: bounded canary revision 0000299
  found: Change loaded successfully while network/vulnerability stayed intentionally deferred and the replica remained routable. Network and all four change-compliance endpoints returned 200, but unscoped vulnerability returned a typed 503 because `hybrid_vulnerability` still required the deferred semantic_graph provider.
  implication: The bounded architecture is stable and the remaining failure is a single missed integration line; use the already-supported optional graph enrichment path from d19af3cba.

- timestamp: 2026-09-12T20:48:00+08:00
  checked: optional semantic graph correction
  found: `hybrid_vulnerability` now calls `providers.get("semantic_graph", optional=True)` while graph-required impact/risk paths remain unchanged. The focused 88-test runtime/vulnerability/compliance suite and Ruff/diff checks pass.
  implication: Rebuild and redeploy; live unscoped vulnerability should now match the previously successful explicit-subscription behavior.

## Eliminated

- hypothesis: Commit 39080ceba (`added health for container apps`) directly changed provider scheduling.
  evidence: Its complete diff changes resource-health service/client/web code and tests only; no API provider, startup, health, or deployment files changed.
  timestamp: 2026-09-12T17:53:00+08:00

- hypothesis: Removing permanent deferral and eagerly refreshing every provider in one startup pass is a safe complete fix.
  evidence: Live revision 0000296 restarted and became intermittently unresponsive/503 before the change provider was attempted; rollback was required.
  timestamp: 2026-09-12T19:14:00+08:00

## Resolution

root_cause: "Two code defects in the bounded-hydration cutover: unscoped vulnerability routes fall through to a permanently deferred snapshot provider instead of deriving active onboarded subscriptions for the bounded hybrid path; change compliance is also permanently deferred because its only constructor is coupled to monolithic all-domain `operations_agent` hydration, which exceeds the 8Gi runtime."
fix: "Implemented locally: restored intentional deferral for full-snapshot providers; restored/added active-subscription hybrid fallbacks for unscoped network/vulnerability reads; scheduled only exposure_query and a directly constructed change provider; metadata refresh no longer hydrates semantic state; added regression coverage."
verification: "Rejected first attempt: eager all-provider hydration caused two exit-137 terminations. Final bounded fix pending."
files_changed:
  - src/api/providers.py
  - src/api/runtime.py
  - src/api/routers/network.py
  - src/api/routers/vulnerability.py
  - tests/test_api_providers.py
  - tests/test_api_runtime.py
  - tests/test_api_network.py
  - tests/test_api_vulnerability_router.py
