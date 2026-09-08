---
phase: 13-autonomous-ontology-discovery-and-fabric-synchronization
verified: 2026-09-07T04:20:09Z
status: gaps_found
verdict: failed
score: 0/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "A durable scheduled coordinator refreshes every eligible connection without an open browser and shares the same durable publisher path with Manual Sync."
    status: failed
    reason: "The deployed Job runs ontology_discovery.cli, whose main() still constructs _RecordOnlyProcessor. It neither discovers eligible connections nor invokes evidence, curator, policy, validation, publisher, Fabric sync, or rollback. It also ignores AIOPS_HOME and opens the default container-local .aiops-local JSON path."
    artifacts:
      - path: "src/ontology_discovery/cli.py"
        issue: "Production entry point completes work at checkpoint intake_recorded through _RecordOnlyProcessor."
      - path: "infra/terraform/ontology_discovery_job.tf"
        issue: "Scheduled Job invokes the record-only CLI without a shared --store and merely exports AIOPS_HOME, which the CLI does not read."
      - path: "src/ontology_discovery/store.py"
        issue: "OntologyRunStore is pathlib/local-file only; it is not backed by OneLakeDocumentStore or another cross-replica CAS store."
      - path: "src/onboarding/service.py"
        issue: "The API-side store is rooted separately; construction with an abfss OneLake root raises TypeError."
    missing:
      - "Build a production run-once composition that enumerates eligible connections and constructs the evidence -> curator -> policy -> validator -> dedicated publisher pipeline."
      - "Use one shared OneLake-backed run/pending/proposal store for scheduled and manual triggers with service-enforced CAS."
      - "Add an integration test that invokes cli.main(), processes an eligible connection, and proves a durable non-empty checkpoint/publication result after restart."
  - truth: "A separate least-privilege publisher performs fenced immutable publication, Fabric synchronization, and rollback in the production path."
    status: failed
    reason: "OntologyGenerationPublisher, PublisherDispatchProcessor, BoundedEvidenceProcessor, OntologyCurator, and DedicatedOntologyPublisherAdapter are substantive but have no non-test construction site. The default API explicitly sets rollback_action=None."
    artifacts:
      - path: "src/ontology_discovery/publisher.py"
        issue: "Substantive publisher implementation is orphaned from a production composition root."
      - path: "src/fabric/sync_service.py"
        issue: "DedicatedOntologyPublisherAdapter is defined but never instantiated outside tests."
      - path: "src/api/runtime.py"
        issue: "Default ontology API provider sets rollback_action=None, so the live action surface cannot perform rollback."
    missing:
      - "Construct the dedicated publisher worker under the publisher managed identity and connect it to coordinator dispatch."
      - "Provide a narrow authenticated rollback transport/service to the API without giving the API publisher credentials."
      - "Deploy and prove deterministic generation promotion, Fabric materialization, consumer cutover, stale-writer rejection, and rollback from the deployed runtime."
  - truth: "Scope-enforced ontology lifecycle APIs and the Connections UI are deployed and expose actual durable runtime state."
    status: failed
    reason: "Local API/UI code and tests pass, but the live API OpenAPI document contains zero /ontology-discovery paths. The UI therefore cannot be accepted as a deployed operational surface, and its local data flow terminates at an API facade whose default rollback action is unavailable."
    artifacts:
      - path: "src/api/routers/ontology_discovery.py"
        issue: "Implemented and locally registered, but absent from the live API OpenAPI document."
      - path: "web/src/components/ontology/OntologyAutomationPanel.tsx"
        issue: "Substantive local UI, but no functioning deployed ontology API was found behind it."
    missing:
      - "Deploy API and web images containing the Phase 13 routes and Connections tab."
      - "Verify authenticated, scoped lifecycle reads and mutations against the shared durable store, including reload and rollback."
  - truth: "Live evaluation proves deployed no-click refresh, zero authoritative model edges, deterministic publication/consumers/rollback, and complete audit without substituting local contract tests."
    status: failed
    reason: "The retained report confirms Job executions and cloud configuration, but derives duplicate suppression, scope/injection, authoritative edge counts, promotion order, consumer cutover, rollback, API audit, and UI audit from local pytest/UI contracts. A successful execution of the record-only Job is therefore reported as no-click refresh without proving that discovery or publication occurred."
    artifacts:
      - path: "scripts/validate_ontology_discovery_live.py"
        issue: "_collect_shadow_evidence runs local contract tests and assigns their PASS to deployed generation/security fields; _schedule_evidence checks platform execution status but not run checkpoints or ontology output."
      - path: ".planning/eval/ontology-discovery-shadow-2026-09-07.json"
        issue: "authoritative_model_edges.source is executable-publication-contract and generation evidence is artifact:test-ontology-discovery-e2e.py, not deployed Fabric state."
      - path: ".planning/phases/13-autonomous-ontology-discovery-and-fabric-synchronization/13-07-LIVE-RBAC.json"
        issue: "The artifact is not fully sanitized to its declared contract: it retains a raw subscription GUID, resource group, image/job names, and omits per-row timestamp/evidence_kind/role-definition hash."
    missing:
      - "Have the live validator inspect durable run checkpoints and non-empty discovery outcomes from the scheduled Job."
      - "Read candidate/stage/active/consumer model-edge counts and generation lineage from the isolated deployed Fabric/OneLake state."
      - "Exercise deployed deterministic publish and rollback through the real publisher path, then verify all five deployed consumer families."
      - "Regenerate the RBAC evidence with only the declared sanitized fields and opaque hashes."
---

# Phase 13: Autonomous Ontology Discovery and Fabric Synchronization Verification Report

**Phase Goal:** Keep the Fabric ontology current without an open browser or
manual Sync click by running durable, incremental discovery on a schedule,
using a scoped Microsoft Foundry agent to propose evidence-backed
relationships, and publishing only relationships that pass deterministic
governance, validation, concurrency, and audit controls.

**Verified:** 2026-09-07T04:20:09Z
**Status:** `gaps_found`
**Verdict:** **FAILED — component implementations are substantial, but the
production composition and deployed end-to-end data flow do not exist.**
**Re-verification:** No — initial verification.

## Executive Finding

The phase built and thoroughly unit-tested most intended components. It did not
connect them into the command actually run by the scheduled Container Apps Job.
The deployed Job runs:

```text
python -m ontology_discovery.cli run-once --limit 10
```

That entry point still constructs `_RecordOnlyProcessor`, which immediately
marks a pre-existing run complete at `intake_recorded`. It does not enumerate
eligible connections, collect incremental evidence, call the Foundry curator,
apply proposal policy, publish a generation, synchronize Fabric, or roll back.
It also defaults to `.aiops-local/state/ontology_discovery_runs.json` and does
not consume the Job's `AIOPS_HOME` OneLake setting.

An isolated execution of the exact CLI composition returned:

```json
{"selected": 0, "processed": 0, "retrying": 0, "failed": 0, "timed_out": 0}
```

Therefore the observed Azure Job `Succeeded` statuses prove only that the
finite process exited successfully. They do not prove that an ontology refresh
occurred.

## Goal Achievement

### Observable Truths

| # | Roadmap truth | Status | Actual evidence |
|---|---|---|---|
| 1 | Durable scheduled refresh, restart safety, writer exclusion, bounded recovery, and Manual Sync parity | ✗ FAILED | Azure confirms a healthy 15-minute Job and recent successful executions, but `src/ontology_discovery/cli.py:18-31,67-73` wires `_RecordOnlyProcessor`; `get_or_create_run()` has no scheduled production caller, and the CLI ignores `AIOPS_HOME`. |
| 2 | Incremental discovery emits only added/changed/retired/unresolved/stale work and full reconciliation detects drift | ✗ FAILED | `incremental.py` and its tests are substantive, but `BoundedEvidenceProcessor` has no non-test construction site and is not reached by the Job. |
| 3 | Scoped proposal-only Foundry curator receives bounded evidence through exactly four read-only tools | ✗ FAILED | The deployed-agent report says active `gpt-5.4-mini`, four tools, and read-only; source/Terraform list the exact four names. No production code constructs `OntologyCurator`, and the scheduled Job never invokes it. |
| 4 | Every proposal is content-addressed, governed, audited, and blocked by hard shadow admission | ✗ FAILED | Policy/store tests pass and production-default bypass scans are clean, but no production flow creates proposals or invokes `ProposalPolicyCoordinator`; the critical coordinator → policy link is absent. |
| 5 | Dedicated publisher performs validated immutable generation promotion with ETag/fence checks, consumer compatibility, Fabric sync, and rollback | ✗ FAILED | The classes and tests are substantive, and live RBAC canaries prove publisher authorization. No production composition constructs the publisher/adapter/dispatch chain; API rollback is deliberately `None`. |
| 6 | Runs, pending edges, proposals, leases, attempts, metrics, and EvaluationSnapshots survive restart and are visible through scoped API/UI | ✗ FAILED | Local stores/API/UI pass tests, but the scheduled store is container-local, the API/store OneLake construction is incompatible, and the live OpenAPI document has zero ontology-discovery routes. |
| 7 | Offline and deployed evaluation prove no-click refresh, safety, bounds, recovery, cutover, rollback, and audit | ✗ FAILED | Offline Promptfoo/Phoenix/evaluator and 299 Python tests pass. The “live” report substitutes local tests for generation, edge-count, consumer, rollback, API, and UI outcomes; it does not prove those behaviors in the deployed runtime. |

**Score:** 0/7 roadmap truths verified.

The score reflects complete observable truths, not the number of useful
components. Many components pass in isolation; all seven roadmap truths depend
on the missing production wiring.

## Required Artifacts

| Artifact group | Exists | Substantive | Wired to production | Status |
|---|---:|---:|---:|---|
| Durable run/pending/proposal stores | Yes | Yes | No shared OneLake-backed Job/API composition | ⚠ ORPHANED |
| Incremental classifier/batcher | Yes | Yes | No production processor construction | ⚠ ORPHANED |
| Curator, strict contracts, prompt, four MCP tools | Yes | Yes | Agent deployed; application invocation absent | ⚠ PARTIAL |
| Proposal policy and shadow exclusion | Yes | Yes | No production proposal/candidate flow | ⚠ ORPHANED |
| Generation resolver, CAS/fencing publisher, rollback | Yes | Yes | No production publisher construction; API rollback unavailable | ⚠ ORPHANED |
| `ontology_discovery.cli` | Yes | No for final-phase purpose | Deployed directly | ✗ STUB |
| Scoped API and Connections UI | Yes | Yes | Local only; live API lacks routes | ⚠ NOT DEPLOYED |
| Promptfoo/Phoenix/evaluator | Yes | Yes | Runnable synthetic evaluation | ✓ VERIFIED |
| Telemetry/alerts/live validator | Yes | Mostly | Live validator overstates local contracts as deployed evidence | ⚠ PARTIAL |
| Terraform scheduled Job/identity/workspaces | Yes | Yes | Job is wired to the record-only CLI | ✗ WRONG TARGET |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| ACA schedule | durable coordinator | `python -m ontology_discovery.cli run-once` | ✗ BROKEN | Reaches a local store and `_RecordOnlyProcessor`, not eligible-connection discovery. |
| Manual Sync | scheduled worker | shared durable run store | ✗ BROKEN | API and Job do not use one deployed store; Job CLI ignores `AIOPS_HOME`. |
| Coordinator | incremental evidence | `BoundedEvidenceProcessor` | ✗ NOT WIRED | No non-test construction. |
| Evidence | Foundry curator | `OntologyCurator` | ✗ NOT WIRED | No non-test construction. |
| Reviewed proposal | hard shadow policy | `ProposalPolicyCoordinator` | ✗ NOT WIRED | No non-test construction. |
| Validated candidate | dedicated publisher | `PublisherDispatchProcessor` → `DedicatedOntologyPublisherAdapter` | ✗ NOT WIRED | Classes are only composed in tests. |
| Publisher | Fabric | `OntologyGenerationPublisher` then `FabricSyncService` | ✗ NOT WIRED | Adapter exists but is never constructed in runtime code. |
| API rollback | publisher | narrow rollback action | ✗ NOT WIRED | `src/api/runtime.py:256` passes `rollback_action=None`. |
| Web panel | scoped ontology API | typed `/ontology-discovery/*` calls | ⚠ LOCAL ONLY | Source wiring exists and tests pass; live OpenAPI exposes zero matching paths. |
| Evaluator | durable snapshot | `EvaluationSnapshotStore` | ✓ WIRED | Synthetic evaluator wrote and reconstructed a BLOCKED/PENDING snapshot. |

## Data-Flow Trace

| Flow | Actual terminal source/result | Status |
|---|---|---|
| Scheduled Job → refresh | `_RecordOnlyProcessor` → `intake_recorded`; usually selects zero runs | ✗ DISCONNECTED |
| Job state → OneLake | CLI default `.aiops-local/...`; exported `AIOPS_HOME` unused | ✗ LOCAL/EPHEMERAL |
| Incremental evidence → curator | No production constructor | ✗ DISCONNECTED |
| Curator proposals → policy → candidate | No production constructor | ✗ DISCONNECTED |
| Candidate → generation → Fabric → consumers | Local test fixture only | ✗ DISCONNECTED |
| Live report generation/rollback facts | SHA-256 of `test_ontology_discovery_e2e.py` plus local pytest result | ⚠ STATIC/SUBSTITUTED |
| Evaluation snapshot | Synthetic corpus → evaluator → durable snapshot contract | ✓ FLOWING for synthetic evaluation |

## Live Deployment Evidence

### Confirmed

- Azure read-only inspection found `aiops-dev-ontology-discovery` provisioned
  successfully with schedule `*/15 * * * *`, timeout 900 seconds, retry limit
  2, user-assigned identity, and the expected finite command.
- The five most recent listed Job executions were `Succeeded`, including the
  scheduled execution at `2026-09-07T04:15:00Z`.
- `13-07-LIVE-RBAC.json` records API/coordinator stage and pointer denials,
  publisher stage/pointer/rollback/cleanup authorization, publisher
  Contributor, and absent writer roles for API/coordinator/curator.
- Terraform/source and live report metadata agree that the curator has four
  read-only tools; source names are exactly
  `list_changed_entities`, `get_entity_evidence`,
  `get_ontology_vocabulary`, and `search_relationship_history`.
- The final report contains 253/253 pairs at `BLOCKED/PENDING`, zero expert
  labels, both missing release predicates, and
  `activation_interface_present: false`.
- Static production-code scan found no `shadow_mode=False`,
  `allow_pair_release_testing=True`, or production invocation of
  `activate_admission_release()`. The expected 30-day/200-label block is a
  successful safety result.

### Not confirmed by deployed behavior

- The successful Job executions performed discovery or publication.
- Zero model edges in deployed candidate, stage, pointer, or consumers.
- Deployed deterministic publication, five-family consumer cutover, or
  rollback.
- Deployed lifecycle API/UI behavior.

The retained report explicitly identifies the model-edge source as
`executable-publication-contract` and the generation evidence as
`artifact:test-ontology-discovery-e2e.py`. Those are valid offline checks, not
deployed-state evidence.

## Behavioral Spot-Checks

| Behavior | Command/result | Status |
|---|---|---|
| Phase 13 Python contracts | 27 targeted files; **299 passed** | ✓ PASS |
| Connections ontology UI/type contracts | Vitest **16 passed**; `tsc --noEmit` passed | ✓ PASS |
| Terraform | `fmt -check` and `validate`; configuration valid | ✓ PASS |
| Dependency gate | `preflight_phase_13.py`; Phase 10/12 evidence passed | ✓ PASS |
| Promptfoo | Exact config validation and no-cache eval; **8/8 passed** | ✓ PASS |
| Phoenix | Loopback inspection; **7 spans**, zero violations | ✓ PASS |
| Repository evaluator | Synthetic corpus passed; snapshot written under `/tmp`; release `BLOCKED/PENDING` | ✓ PASS |
| Targeted Ruff | All Phase 13 Python implementation files passed | ✓ PASS |
| Exact deployed CLI composition | Isolated run returned `selected=0`, `processed=0` | ✗ FAIL |
| Live API route presence | Live OpenAPI contains **0** `/ontology-discovery` paths | ✗ FAIL |

## Probe Execution

| Probe | Result | Status |
|---|---|---|
| `.planning/scripts/preflight_phase_13.py` | Phase 10 and Phase 12 complete and independently verified | PASS |
| Conventional `probe-*.sh` | No Phase 13 probe declared; applicable executable gates were run directly | N/A |

## Requirements Coverage

| Requirement | Verdict | Evidence and exact remediation |
|---|---|---|
| AUTO-ONT-01 | ✗ BLOCKED | Durable algorithms exist, but the deployed scheduler is record-only, does not enqueue eligible work, and uses no shared durable store. Replace the CLI composition and add deployed checkpoint/output verification. |
| AUTO-ONT-02 | ✗ BLOCKED | Incremental logic passes tests but is orphaned from the production coordinator. Wire an authoritative evidence provider and full-reconciliation schedule into the run-once pipeline. |
| AUTO-ONT-03 | ✗ BLOCKED | Curator/tool boundary is deployed and least-privilege evidence exists, but no runtime invokes the curator. Construct and execute the scoped curator adapter from persisted bounded batches. |
| AUTO-ONT-04 | ✗ BLOCKED | Policy, identity, review CAS, and hard shadow checks pass in isolation, but no production proposal flow reaches them. Wire proposal persistence/review/policy/candidate assembly while retaining shadow-only defaults. |
| AUTO-ONT-05 | ✗ BLOCKED | CAS/fence/publisher/rollback code and RBAC canaries pass, but the publisher adapter is never constructed and API rollback is unavailable. Add the dedicated publisher service composition and deployed rollback proof. |
| AUTO-ONT-06 | ✗ BLOCKED | Local persistence/API/UI contracts pass; deployed Job state is ephemeral/separate, OneLake-root construction fails, and live APIs are absent. Implement a shared remote store and deploy the routes/UI. |
| AUTO-ONT-07 | ✗ BLOCKED | Offline evaluation is strong, but “live” publication/edge/consumer/rollback facts are local test substitutions. Make the validator inspect deployed checkpoints, pointers, stages, consumers, and rollback outcomes. |

No later roadmap phase explicitly owns these gaps; nothing was deferred.

## Anti-Patterns and Warnings

| File | Pattern | Severity | Impact |
|---|---|---|---|
| `src/ontology_discovery/cli.py` | Explicit “Later Phase 13 plans replace this composition” record-only implementation remained at phase completion | 🛑 BLOCKER | The deployed schedule is a successful no-op, not ontology discovery. |
| `scripts/validate_ontology_discovery_live.py` | Local test PASS is projected into deployed edge-count/generation/consumer fields | 🛑 BLOCKER | Produces a false-positive live closeout report. |
| `src/onboarding/service.py` | `resolve_root(abfss://...)` returns `str`, then code uses `/ "state"` | 🛑 BLOCKER | A direct OneLake-root construction raises `TypeError`; remote durability is not implemented. |
| `13-07-LIVE-RBAC.json` | Raw scoped identifiers and missing declared evidence fields | ⚠ WARNING | Retained evidence violates the phase's sanitization/audit shape. |
| `13-VALIDATION.md` | Frontmatter remains `in_progress` and many implemented task rows remain `pending` | ⚠ WARNING | Validation metadata does not accurately represent phase completion. |

The only generic stub-pattern match in the UI was a conditional
`return null` while status is loading/error; inspection showed it is not a
user-visible stub. No unreferenced `TODO`, `FIXME`, or `XXX` marker was found
in the Phase 13 implementation surfaces.

## Human Verification Required

The UI-SPEC keyboard/focus/assistive-technology/390px backstop remains
unperformed in this verification. It is not the current release gate because
the production-wiring and deployment blockers above must be fixed first.

## Gaps Summary

This is not a case where the expected shadow-only release block should be
treated as failure. The 30-day/200-label `BLOCKED/PENDING` result and absence
of an activation bypass are correct and verified.

The failure is earlier in the flow: the deployed scheduled command never
executes the implementation that Phase 13 built. The live validator then
accepts successful no-op Job exits and local contract tests as evidence for
deployed discovery, publication, consumer cutover, rollback, and zero
authoritative model edges. Until the production composition, shared durable
store, publisher/rollback transport, deployment, and genuine live assertions
are added, the phase goal is not achieved.

---

_Verified: 2026-09-07T04:20:09Z_
_Verifier: the agent (gsd-verifier)_
