---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
verified: 2026-09-08T09:02:47Z
status: gaps_found
verdict: implementation_complete_deployed_acceptance_blocked
score: 6/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 3/7
  gaps_closed:
    - "The coordinator CLI now constructs and runs the production OneLake-backed inventory, curator, governance, reconciliation, and dispatch pipeline."
    - "The separate publisher is now constructed as a finite production worker with isolated credentials, ordered Fabric materialization, fenced pointer CAS, consumer checks, and rollback."
    - "The default API and Connections UI now use the durable four-root command/read topology without acquiring publisher authority."
    - "The reviewed infrastructure and deployment evidence establish fixed templates, distinct capability roots, separated identities, and no runtime Job-start grants."
  gaps_remaining:
    - "The retained deployed lifecycle has only passed preflight; lifecycle fails closed with coordinator_retry_rotation_unavailable."
    - "Publication, rollback, five-consumer convergence, deployed API/UI, and final effective-RBAC audit evidence are not complete because the lifecycle gate did not advance."
  regressions: []
gaps:
  - truth: "Offline and live evaluations demonstrate the complete no-click refresh, recovery, publication, rollback, consumer, security, and audit contract."
    status: failed
    reason: "The current authoritative deployed lifecycle artifact is FAIL/BLOCKED/PENDING. Only preflight completed; lifecycle stopped at coordinator_retry_rotation_unavailable, so publication and finalize were not accepted."
    artifacts:
      - path: ".planning/eval/ontology-deployed-lifecycle.json"
        issue: "status=FAIL, completed_stages=[preflight], lifecycle last_failure.closed_reason=coordinator_retry_rotation_unavailable, release_status=BLOCKED/PENDING."
      - path: ".planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-20-SUMMARY.md"
        issue: "Stale narrative claims all four deployed stages passed; it is contradicted by the current retained lifecycle artifact and is not verification evidence."
      - path: ".planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-21-PLAN.md"
        issue: "Final deployed API/UI/RBAC/shadow closeout remains unexecuted and has no summary."
    missing:
      - "Direct deployed three-record coordinator evidence showing one record per pass, retry rotation behind a later member, at least one process replacement, restart-preserved epoch/cursor lineage, and complete terminal drain."
      - "After lifecycle passes, direct deployed maintenance, ordered publication, stale-writer rejection, automatic and explicit rollback, old/new/old convergence, and all-five-consumer receipts."
      - "Deployed, authenticated API and Connections UI audit without interception or local substitution."
      - "Fresh effective-role/RBAC and no-override saved-template closeout evidence, followed by a deployed-only final shadow report."
deferred: []
---

# Phase 13: Autonomous Ontology Discovery and Fabric Synchronization Verification Report

**Phase Goal:** Keep the Fabric ontology current without an open browser or
manual Sync click by running durable, incremental discovery on a schedule,
using a scoped Microsoft Foundry agent to propose evidence-backed
relationships, and publishing only relationships that pass deterministic
governance, validation, concurrency, and audit controls.

**Verified:** 2026-09-08T09:02:47Z
**Status:** `gaps_found`
**Verdict:** **Implementation complete; deployed acceptance blocked.**
**Re-verification:** Yes — after Plans 13-16 through 13-21 implementation and
integration work.

## Executive Finding

Phase 13's production implementation is now substantive and wired. The earlier
record-only coordinator, orphaned publisher, and local-only API findings are no
longer accurate:

- `ontology_discovery.cli` calls `build_production_runtime()` and executes a
  one-member coordinator pass.
- The coordinator reads the explicit connection/command/state/dispatch roots,
  refreshes inventory, invokes the version-bound curator, applies hard-shadow
  governance, validates the candidate, commits reconciliation, and creates an
  immutable publisher dispatch.
- A separate publisher CLI/worker consumes dispatches with the publisher
  identity, materializes Fabric before pointer CAS, checks all five consumer
  families, and performs newer-fence rollback.
- Manual Sync, run-now, maintenance, and rollback use immutable command intake;
  fresh-process tests reconstruct API → coordinator → publisher → API state.
- Terraform and the applied deployment artifact record distinct roots,
  separated identities, fixed Job templates, and no runtime Job-start grants.

That is **implementation completeness**, not deployed end-to-end proof. The
current retained lifecycle artifact truthfully reports:

```text
status: FAIL
completed_stages: [preflight]
last_failure.stage: lifecycle
last_failure.closed_reason: coordinator_retry_rotation_unavailable
release_status: BLOCKED/PENDING
activation_interface_present: false
```

Therefore the phase goal is not yet accepted. The prior simplified claim that
all four deployed stages passed is a false positive and is not preserved here.
No Azure commands, deployments, Job starts, or cloud mutations were performed
during this verification.

## Goal Achievement

### Observable Truths

| # | Roadmap truth | Status | Codebase and evidence |
|---|---|---|---|
| 1 | Durable scheduled coordinator, one member per pass, restart-safe fair rotation, writer exclusion, bounded recovery, and audited Manual Sync parity | ✓ VERIFIED (implementation) | `EligibleConnectionScheduler.run_once()` enforces `limit == 1`, durable epoch/cursor outcomes, retry rotation, leases/fences, and terminal exclusions. Manual intake is reauthorized. The named restart/fairness test passed in this verification. Deployed fairness acceptance remains part of failed Truth 7. |
| 2 | Incremental added/changed/retired/unresolved/stale processing plus authoritative full reconciliation and drift detection | ✓ VERIFIED (implementation) | `ProductionConnectionProcessor` constructs `BoundedEvidenceProcessor`, records bounded evidence, and commits reconciliation only after dispatch. The named full-reconciliation convergence test passed. |
| 3 | Scoped proposal-only Foundry curator with bounded evidence, exactly four read-only tools, citations/confidence, and no authoritative write path | ✓ VERIFIED (implementation) | Production runtime constructs `OntologyCurator`; tests define and exercise the exact four-tool boundary. Terraform preflight records the configured tools and separated identity. No curator publication capability is present. |
| 4 | Content-addressed, deduplicated, validated, audited proposals with hard server-side shadow exclusion | ✓ VERIFIED | `ProposalPolicy(shadow_mode=True)` is hard-wired in the production processor. The named durable-review test passed while proving accepted model proposals never enter the authoritative candidate. Release records start `BLOCKED/PENDING`; activation is test-only and guarded by `_allow_pair_release_testing`. |
| 5 | Exact capability matrix and separate least-privilege publisher with ordered validation, Fabric sync, fencing, five-consumer checks, and rollback | ✓ VERIFIED (implementation) | Production publisher CLI/worker and dispatch view are wired. Materialization precedes pointer CAS; stale pointer/fence checks and compensating rollback are substantive. The named newer-fence post-check rollback test passed. Deployment preflight confirms distinct roots/identities, but deployed drill receipts remain required by Truth 7. |
| 6 | Runs, proposals, pending edges, leases, attempts, metrics, publication and EvaluationSnapshot state survive restart; stale writers/evidence cannot authorize release | ✓ VERIFIED (implementation) | OneLake document stores and fresh-process topology reconstruct command/run/generation/publication/rollback state. The named API → coordinator → publisher → API reconstruction test passed. |
| 7 | Offline **and live** evaluation proves no-click refresh, bounds, isolation, injection resistance, publisher separation, deployment allowlists, credential isolation, alerts, degradation, rollback, cutover, and complete sanitized audit | ✗ FAILED | Offline/local gates are strong and deployment preflight passes, but `.planning/eval/ontology-deployed-lifecycle.json` stops after preflight with `coordinator_retry_rotation_unavailable`. No accepted lifecycle, publication, finalize, live API/UI, or final effective-RBAC evidence follows. |

**Score:** 6/7 roadmap truths verified at implementation level; the mandatory
live-evaluation truth failed.

## Required Artifacts

| Artifact group | Exists | Substantive | Wired | Status | Details |
|---|---:|---:|---:|---|---|
| Coordinator runtime and CLI | Yes | Yes | Yes | ✓ VERIFIED | Explicit roots → registry/state/intake/dispatch → inventory/curator/policy/reconciliation. |
| Incremental and reconciliation stores | Yes | Yes | Yes | ✓ VERIFIED | Durable cadence, watermarks, parity, epochs, cursor, leases, retries, and exclusions. |
| Curator and four-tool boundary | Yes | Yes | Yes | ✓ VERIFIED | Constructed by production runtime; proposal-only and scope-bound. |
| Hard-shadow proposal policy | Yes | Yes | Yes | ✓ VERIFIED | Production processor forces `shadow_mode=True`; model proposals remain excluded. |
| Publisher CLI/worker and Fabric adapter | Yes | Yes | Yes | ✓ VERIFIED | Dispatch claim → stage/validate/materialize/CAS/post-check; rollback uses a newer fence. |
| Four-root API and Connections UI | Yes | Yes | Yes | ✓ VERIFIED (implementation) | UI calls typed ontology APIs; API reads durable stores and only creates isolated commands. |
| Terraform identities, Jobs, roots, and fixed fixtures | Yes | Yes | Yes | ✓ VERIFIED (deployment preflight) | Applied artifact has zero deletes/replacements, fixed hashes, distinct roots, and no runtime Job-start grants. |
| Deployed lifecycle evidence | Yes | Yes | N/A | ✗ FAILED | Honest fail-closed artifact; only preflight completed. |
| Final deployed-only audit | No completed result | — | — | ✗ MISSING | Plan 13-21 has no summary or accepted final report. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Scheduled coordinator Job | production coordinator | `python -m ontology_discovery.cli run-once` → `build_production_runtime()` | ✓ WIRED | No record-only processor remains in the production composition. |
| Coordinator | bounded inventory/curator pipeline | `ProductionConnectionProcessor` | ✓ WIRED | Real inventory refresh, bounded evidence, curator, policy, validation, and reconciliation. |
| Coordinator | publisher | dispatch-only `PublisherDispatchStore.coordinator()` | ✓ WIRED | Coordinator creates immutable dispatch and has no publication root. |
| Publisher Job | publication/Fabric | `publisher_cli` → `PublisherWorker` → `OntologyGenerationPublisher` | ✓ WIRED | Publisher identity is required and rebound into Fabric runtime. |
| API/Manual Sync | authoritative workers | immutable command intake and worker reauthorization | ✓ WIRED | API has no dispatch, stage, pointer, fence, Fabric-write, or publisher credential capability. |
| Connections UI | ontology API | typed run/rollback/status requests and durable projections | ✓ WIRED (source) | Local frontend coverage passes; deployed authenticated browser proof remains absent. |
| Deployed coordinator execution | complete three-record drain | lifecycle evidence derivation | ✗ NOT PROVEN | Direct evidence cannot establish retry rotation; lifecycle fails closed. |
| Deployed drain | publication/finalize/audit | ordered deployed stage machine | ✗ BLOCKED | Later stages cannot be accepted before lifecycle passes. |

## Data-Flow Trace

| Flow | Source → sink | Status |
|---|---|---|
| Scheduled discovery | ConnectionRegistry → inventory pipeline → bounded evidence → curator → shadow policy → validation → dispatch | ✓ FLOWING in production code |
| Incremental reconciliation | authoritative inventory → delta/full graph → parity → post-dispatch watermark commit | ✓ FLOWING in production code |
| Publication | immutable dispatch → publisher validation → generation-scoped Fabric materialization → pointer CAS → five consumer checks | ✓ FLOWING in production code |
| Rollback | immutable rollback command → publisher reauthorization → newer fence → conditional predecessor restore → consumer verification | ✓ FLOWING in production code |
| API/UI state | OneLake state/publication/command roots → scoped API projections → Connections panel | ✓ FLOWING in production code |
| Deployed acceptance | fixed prepare/coordinator lifecycle → retry-rotation receipt → publication/finalize | ✗ STOPPED at retry-rotation evidence |

## Behavioral Spot-Checks

The user-provided post-merge focused gates are accepted as integration evidence:

| Gate | Result | Status |
|---|---:|---|
| Phase 13 backend tests | 161 passed | ✓ PASS |
| Frontend tests | 596 passed | ✓ PASS |
| Ruff | passed | ✓ PASS |
| Terraform fmt/validate | passed | ✓ PASS |
| TypeScript | passed | ✓ PASS |
| ESLint | passed | ✓ PASS |

Five critical named tests were also rerun locally without cloud access:

| Behavior | Test | Result |
|---|---|---|
| Restart-safe fair retry rotation | `test_eligible_epoch_rotates_retrying_head_and_survives_every_restart` | ✓ PASS |
| Full reconciliation converges to clean rebuild | `test_complete_reconciliation_converges_to_clean_rebuild` | ✓ PASS |
| Failed post-check restores predecessor under newer fence | `test_failed_post_check_automatically_restores_predecessor_with_newer_fence` | ✓ PASS |
| Manual publish and rollback survive process reconstruction | `test_manual_publish_and_rollback_survive_every_process_reconstruction` | ✓ PASS |
| Accepted review remains shadow-excluded | `test_accepted_review_is_durable_but_shadow_never_admits_model_edge` | ✓ PASS |

These tests prove implementation behavior. They do not substitute for the
missing deployed lifecycle evidence.

## Deployment and Probe Evidence

| Evidence | Result | Status |
|---|---|---|
| `.planning/eval/ontology-gap-deployment.json` | `status=applied`; zero deletes/replacements; reviewed roots/templates/images; no runtime Job-start grants | ✓ PASS for deployment topology |
| `.planning/eval/ontology-deployed-lifecycle.json` preflight | Template/root/tag/credential boundary accepted | ✓ PASS |
| Deployed lifecycle stage | `coordinator_retry_rotation_unavailable` | ✗ FAIL |
| Publication stage | Not completed in current artifact | ✗ BLOCKED |
| Finalize stage | Not completed in current artifact | ✗ BLOCKED |
| Plan 13-21 final deployed-only audit | No completed summary/report | ✗ MISSING |

No Azure command or probe was run during this verification.

## Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| AUTO-ONT-01 | ✓ IMPLEMENTED / deployment acceptance pending | Durable one-per-pass epoch/cursor/retry/restart behavior passes local integration tests; direct deployed retry rotation is the current blocker. |
| AUTO-ONT-02 | ✓ SATISFIED in implementation | Incremental/full reconciliation and drift convergence are wired and behavior-tested. |
| AUTO-ONT-03 | ✓ SATISFIED in implementation | Scoped proposal-only curator, exact four read-only tools, and no publication authority. |
| AUTO-ONT-04 | ✓ SATISFIED | Content addressing, review/audit, deterministic validation, and hard-shadow exclusion are enforced. |
| AUTO-ONT-05 | ✓ IMPLEMENTED / deployed drill pending | Exact publisher capability boundary, ordered visibility, fencing, consumers, and rollback are behavior-tested. |
| AUTO-ONT-06 | ✓ SATISFIED in implementation | Durable shared roots and fresh-process API/worker reconstruction are tested. |
| AUTO-ONT-07 | ✗ BLOCKED | Complete deployed lifecycle, publication/rollback, UI/API, and final sanitized audit evidence is absent. |

No later roadmap phase owns these gaps. Plans 13-20 and 13-21 are the explicit
Phase 13 closeout work; the roadmap still marks Plans 13-19 through 13-21
unexecuted.

## Safety and Security Outcome

`13-SECURITY.md` truthfully closes the implementation threat register and notes
that security closure does not promote the feature. The retained safety
outcome is correct:

- `activation_interface_present: false`
- `release_status: BLOCKED/PENDING`
- zero accepted authoritative model promotion
- production policy uses `shadow_mode=True`
- `activate_admission_release()` is a guarded synthetic-test seam, not a
  production API/UI or runtime invocation
- API, coordinator, curator, and evidence identities have no Job-start
  authority; API/coordinator have no publisher authority

The deployed evidence failure is therefore fail-closed. It does not create a
release or privilege bypass.

## Anti-Patterns and Evidence Integrity

| File | Finding | Severity | Impact |
|---|---|---|---|
| `13-20-SUMMARY.md` | Claims all four deployed stages passed | ⚠ WARNING | Contradicted by the current lifecycle artifact; must not be used for closeout. |
| `OntologyAutomationPanel.tsx` | Conditional `return null` in a status helper | ℹ INFO | Inspection shows a loading/error suppression branch, not a user-visible feature stub. |

No unreferenced `TBD`, `FIXME`, or `XXX` marker was found in the inspected
Phase 13 integration surfaces. No production activation call or UI/API release
control was found.

## Exact Remaining Blockers

1. **Coordinator deployed retry rotation:** retain direct before/after snapshots
   and execution receipts proving one member per pass, a retrying member rotates
   behind later work, at least one process replacement occurs, epoch/cursor
   lineage survives restart, and all three prepared members terminate.
2. **Publication and rollback deployed drill:** only after blocker 1 closes,
   capture immutable stage, validation, five-family compatibility, Fabric
   materialization, final preconditions, pointer CAS, post-check, stale-writer
   rejection, automatic/explicit rollback, and old/new/old receipts.
3. **Final deployed-only audit:** run the authenticated API and live Connections
   UI audit without interception, regenerate effective RBAC/no-override
   evidence, prove cleanup and retained audit, and issue the final sanitized
   shadow report.

## Ship / Integration Recommendation

**Integrate the implementation branch only as fail-closed shadow
infrastructure; do not declare Phase 13 complete and do not enable or promote
model-derived ontology relationships.**

The code and local quality gates are suitable for integration because the
authoritative path remains hard-shadowed and the deployed validator fails
closed. Shipping as a completed operational capability is blocked until the
current lifecycle artifact reaches genuine deployed PASS through lifecycle,
publication, and finalize, followed by the Plan 13-21 API/UI/RBAC audit.

---

_Verified: 2026-09-08T09:02:47Z_
_Verifier: the agent (gsd-verifier)_
