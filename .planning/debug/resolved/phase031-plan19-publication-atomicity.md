---
status: resolved
trigger: "Phase 03.1 Plan 19 initial Gold publication is not retry-safe after a hard process death: canonical ontology tables can be partially replaced before the authoritative Gold pointer exists, and the next service instance may consume that non-authoritative head as its predecessor."
created: 2026-09-09T14:01:04.955+08:00
updated: 2026-09-09T16:48:02+08:00
---

# Phase 03.1 Plan 19 Publication Atomicity

## Current Focus

hypothesis: resolved — only completed canonical Delta version pairs are authoritative predecessors, relationship lifecycle identity is endpoint-stable, and publication is serialized without active-lease breaking
test: complete — target, focused, full backend, Ruff, revert/reapply, side-effect order, independent offline review, human workflow verification, and archive integrity checks accepted the fix and record
expecting: create one path-scoped archival commit without touching production code, tests, cloud state, or unrelated working-tree files
next_action: stage only the deleted active record path, resolved record path, and knowledge base; commit with the required conventional subject and coauthor trailer; do not push
bug_class: bohrbug
goal: find_and_fix
candidate_causes:
  - code: mutable canonical head is consumed without a completed-publication/version qualifier
  - code/data-model: relationship IDs include mutable event intervals even though validator uniqueness and documented identity are endpoint-triple based
  - code/concurrency: the remote synchronization lock breaks any active infinite lease and explicitly permits overlapping writers
  - data: high but valid current and partial-prior relationship graphs have enough identity delta for retirement union to cross 250000
  - environment: hard exit 137 bypasses in-process rollback and lease release
and_gate: yes — the production overflow requires an uncommitted head to survive hard death, that head to be selected as predecessor, and mutable-evidence identity churn plus high cardinality to make false tombstones exceed the bound; unsafe scheduled-refresh overlap is an additional independent concurrency defect, not a required trigger
reasoning_checkpoint:
  hypothesis: "A hard exit leaves per-table canonical Delta versions newer than the last completed publication; `_synchronize_ontology` reads those mutable heads, while `_relationship_id` includes mutable event intervals, so unchanged semantic edges churn identity and are retired en masse."
  confirming_evidence:
    - "A fresh local service over only `started` + partial version-0 canonical tables reproduced the bound failure; the same candidate against a clean lakehouse completed."
    - "Exact live reconstruction produced 234024 current + 233424 prior-only IDs = 467448, but only 1434 prior endpoint triples were truly absent."
    - "231990 shared endpoint triples had changed resource IDs solely under the evidence-sensitive identity scheme; endpoint-stable identity predicts 235458, below 250000."
  falsification_test: "The hypothesis would be false if a no-marker fresh service supplied zero predecessor rows yet still overflowed, or if endpoint-triple overlap were as low as resource-ID overlap; both observations were directly contradicted."
  fix_rationale: "Record exact canonical Delta versions only after finalization, read predecessor/semantic snapshots at those versions, use endpoint-triple relationship identity while retaining evidence in payload/change_version/Delta history, and make the OneLake writer lease exclusive so the completion record cannot describe interleaved writes."
  blind_spots: "Remote lease renewal failure during an in-flight Delta transaction and future Delta vacuum of referenced versions need explicit guards/operational retention; no cloud mutation will be used to validate them in this session."
  candidate_causes:
    - "code: unqualified mutable-head predecessor reads and evidence-sensitive relationship identity"
    - "environment: exit 137 bypasses process-local rollback"
    - "data: 234024 valid current relationships amplify 231990 false identity changes past the 250000 bound"
    - "config/concurrency: remote lock breaks active infinite leases, allowing scheduled refresh overlap"
  and_gate: "yes — mutable-head selection, hard-death persistence, mutable identity churn, and production cardinality jointly produce the observed overflow; unsafe lock overlap is independently unsafe but not required by the reproduced failure"
tdd_checkpoint:
  test_file: "tests/test_fabric_sync_service.py; tests/test_operational_context_graph_v2_hardening.py"
  test_name: "test_initial_gold_retry_ignores_partial_canonical_head_from_dead_process; test_post_pointer_retry_reads_last_completed_versions_after_partial_write; test_relationship_identity_excludes_mutable_evidence_interval"
  status: "green"
  failure_output: "Original RED was FFF: initial retry received 16 uncommitted predecessor entities; post-pointer retry received the partial relationship head missing one completed ID; evidence-interval-only changes produced different relationship resource IDs. Final exact rerun: 3 passed."

## Scope and Safety Constraints

- This session is the sole priority for active Phase 03.1 Plan 19.
- Do not start another cloud execution.
- Prohibited: Azure/cloud mutation, Terraform plan/apply, ACR build, Container Apps Job start/update, pointer repair, Fabric/OneLake table restore or write, traffic/revision change, or capacity change.
- Read-only Azure, OneLake, and Log Analytics queries are allowed only when needed to establish evidence.
- Source, test, and debug-document edits are allowed after a reproduced hypothesis.
- Preserve `.planning/debug/phase031-plan19-live-oom.md`.
- Do not touch, stage, or commit the unrelated `infra/terraform/fabric.tf` working-tree change.
- Do not touch, stage, or commit `.azure/deployment-plan.md` or `.azure/validate-status.json`.
- Keep validation fail-closed. Do not fabricate or repair a pointer, truncate data, lower the 100,000/250,000 active ontology bounds, or discard the lifecycle audit contract.
- Make atomic conventional commits with the repository-required coauthor trailer. Do not push.

## Required Reading

- `.planning/STATE.md`
- `.planning/phases/03.1-exposure-reliability-and-scale/03.1-19-PLAN.md`
- `.planning/debug/phase031-plan19-live-oom.md`
- Current Fabric synchronization, ontology lifecycle/publication, ingestion scheduling, lock, pointer, and reader code
- Relevant existing tests and repository commit conventions

## Symptoms

expected: an initial Gold publication either becomes authoritative atomically or leaves retry input indistinguishable from the last authoritative publication; a hard death before pointer activation must not poison the next sync
actual: ordinary and canonical ontology tables are mutated before Gold pointer activation; an exit-137 bypasses the in-memory rollback journal; a fresh retry reads the partial canonical ontology head as predecessor and fails relationship-bound validation
errors: latest caught failure was `Ontology synchronized relationship graph exceeds bound`; earlier corrected failures included raw ontology merge collisions, one-generation tombstone growth, and a coarse semantic source bound
reproduction: deterministically combine the current candidate graph with the partial canonical ontology tables written by failed execution `tdcserp`, or an exact compact equivalent preserving the active/retired/intersection cardinalities
active_publication: none; the initial Gold pointer is `{}`/absent and Exposure Gold APIs fail closed

## Required Scientific Work

- Quantify current active entities/relationships, partial-prior active/retired rows, identity intersection, newly generated tombstones, and exact resulting synchronized sizes.
- Prove or falsify that persisted canonical head is an invalid predecessor when its producing sync did not reach an authoritative completion marker/pointer.
- Trace ordering of metadata-started state, 458 ordinary table writes, canonical ontology writes, catalogs, `data_committed`, ontology publication, Gold staging, completed state, shortcuts, and pointer activation.
- Distinguish caught-exception rollback from exit-137/process-death behavior across a new service instance.
- Trace all relevant readers and identify the marker that selects the last authoritative predecessor.
- Assess correctness and failure modes of: (A) no predecessor without Gold pointer; (B) predecessor selected by last completed ingestion/generation/version; (C) durable before-version transaction journal/recovery; (D) generation-qualified staging plus CAS; and (E) separate retirement event history from active graph.
- Determine exactly whether scheduled inventory refreshes mutate shared source/Fabric state and whether the synchronization lock serializes them.
- Add process-death/partial-write failure-injection tests across fresh service instances, pointer-finalization tests, relevant refresh-lock tests, and count-only overflow diagnostics.
- Run focused tests, the full backend suite, Ruff, a targeted diff check, and independent review.

## Eliminated

- hypothesis: pointer-only repair is a valid recovery.
  evidence: the initial Gold pointer is absent, ordinary/canonical publication did not complete atomically, and user safety constraints prohibit fabricated activation.
  timestamp: 2026-09-09T14:01:04.955+08:00

- hypothesis: increasing writer parallelism or memory alone fixes the publication lifecycle.
  evidence: both 12-writer and 4-writer runs died at nearly the same early table-publication point, while the later single-writer retry exposed durable partial-head poisoning rather than completing safely.
  timestamp: 2026-09-09T14:01:04.955+08:00

## Evidence

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: active project state
  found: `.planning/STATE.md` identifies Phase 03.1 Plan 19 as the next active blocked plan, awaiting exact live source evidence after successful Fabric publication.
  implication: this debug cycle is within active scope and must finish before another execution.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: initial Gold state
  found: the Gold pointer is absent/`{}` and Exposure Gold APIs fail closed.
  implication: there is no authoritative initial Gold publication and pointer-only repair is invalid.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: execution `xejd3lo`
  found: base and granular ontology graphs were independently valid, but their raw union contained 8 duplicate entities and 7 duplicate relationships; a collision-aware merge was implemented.
  implication: the initial validation failure was explained and is distinct from publication atomicity.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: next ontology lifecycle failure
  found: a predecessor table had 23,162 entities, of which 23,029 were already retired; one-generation tombstone handling was changed so raw predecessor validates first, old retired rows are excluded from the latest graph, and reactivation remains interval-safe.
  implication: retained historical tombstones were a prior independent amplification and are not permission to discard lifecycle history.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: semantic mapping failure
  found: ontology construction reached approximately 83,266 entities and 235,180 relationships before `Semantic entities exceeds configured source bound`; limits were made granular at 100,000 entities, 250,000 relationships, 50,000 for other fact collections, with streaming fingerprinting.
  implication: the current active bounds are intentional contracts and must not be raised to hide retry poisoning.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: execution `5wuglm3`
  found: with 12 writers it reached ordinary-table publication 50/458 and exited 137; the Job was restored and no pointer was activated.
  implication: hard process death can occur after durable table mutation but before publication finalization.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: execution `tdcserp`
  found: with 4 writers it reached 53/458 and exited 137 at an observed peak near 6.6 GiB; the Job was restored and no pointer was activated.
  implication: reducing concurrency did not provide transaction safety.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: execution `7nyjitk` and durable ingestion state
  found: with source `write_workers=1`, temporal and container projections completed, then caught ontology construction failed with `Ontology synchronized relationship graph exceeds bound`; the Job configuration was restored exactly and the pointer remained `{}`.
  implication: the retry was poisoned before ordinary table publication and provides a deterministic validation target.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: canonical ontology tables after `tdcserp`
  found: before its hard OOM, `tdcserp` had already written canonical `ontology_entities` with 83,392 rows and `ontology_relationships` with 235,281 rows; ordinary/canonical tables precede Gold pointer activation and hard kill bypassed in-process rollback.
  implication: a new service instance can observe durable non-authoritative canonical state.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: synchronization rollback model
  found: `FabricSyncService` tracks `written_versions` only in memory, rolls back caught exceptions before `data_committed`, and sets `data_committed=True` after normal table writes/catalog work but before ontology publication, Gold finalization, and pointer activation.
  implication: neither the journal nor `data_committed` survives exit 137, so current rollback is not crash recovery.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: overlapping scheduled refresh observation
  found: completed scheduled inventory refresh state rows appeared during publication executions.
  implication: exact shared-state mutation and lock coverage remain unresolved and must be traced before ruling out interleaving.

- timestamp: 2026-09-09T14:01:04.955+08:00
  checked: repository/deployment state
  found: origin/main `e3fb8344bb03bf130878627812028dd0628c47ba` includes collision handling, tombstone exclusion, progress logging, granular semantic limits, and single-writer configuration; the Job is restored to the old image with timeout 3600 and retries 0, the API serves the single-writer image, and no Job is running.
  implication: investigation can proceed entirely from source, tests, durable local evidence, and optional read-only queries.

- timestamp: 2026-09-09T14:05:30+08:00
  checked: debug knowledge base
  found: no prior entry matches hard-death partial canonical publication, non-authoritative ontology predecessor selection, or retry overflow.
  implication: there is no known-pattern shortcut; the current predecessor hypothesis must be reproduced and tested directly.

- timestamp: 2026-09-09T14:05:30+08:00
  checked: repository status and commit convention
  found: branch `main` is aligned with `origin/main` at `e3fb8344b`; numerous pre-existing unrelated modifications and untracked files exist, including explicitly protected `infra/terraform/fabric.tf`, `.azure/deployment-plan.md`, and `.azure/validate-status.json`. Recent commits use a conventional subject and `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>`.
  implication: every later edit, stage, diff, and commit must be path-scoped; unrelated working-tree state must remain untouched.

- timestamp: 2026-09-09T14:05:30+08:00
  checked: project and agent skill configuration
  found: `.planning/config.json` has no configured `agent_skills`; the repository exposes the `gsd-debug` command skill and no additional debugger-specific skill was injected.
  implication: follow the repository `gsd-debug` skill plus debugger protocol; no additional agent skill rules apply.

- timestamp: 2026-09-09T14:12:00+08:00
  checked: `FabricSyncService.sync` and `_sync_locked` publication ordering
  found: one `OneLakeWriter.sync_lock()` encloses the entire sync. The service writes `metadata_ingestion_state=started`, maps/builds/validates the candidate, concurrently replaces ordinary and canonical ontology tables, registers assets and writes the normal catalog, sets only the in-memory `data_committed=True`, publishes ontology, stages Gold, registers/writes the Gold catalog, writes `metadata_ingestion_state=completed`, finalizes shortcuts, and activates the Gold pointer last.
  implication: pointer immutability is intentional, but the canonical ontology head becomes durable well before the only authoritative initial Gold activation; neither `data_committed` nor `written_versions` survives process death.

- timestamp: 2026-09-09T14:12:00+08:00
  checked: canonical ontology predecessor selection in `FabricSyncService._synchronize_ontology`
  found: predecessor entities and relationships are read unconditionally from the latest Delta versions of `Tables/ontology_entities` and `Tables/ontology_relationships`; no ingestion-completion row, Gold pointer, generation ID, or table-version marker qualifies those reads.
  implication: any partial canonical head left by a hard-killed run is lifecycle input to a fresh process even when no publication is authoritative.

- timestamp: 2026-09-09T14:12:00+08:00
  checked: caught-exception rollback and reader behavior
  found: caught failures before `data_committed` restore/delete only table versions captured in the current process; caught failures after `data_committed` deliberately retain graph tables for retry. Hard death executes neither path. Semantic readers select freshness/version from completed ingestion rows but still read the unqualified current canonical tables, with entity timestamps or ingestion IDs as fallback.
  implication: ingestion metadata and canonical graph state can disagree; current tests prove pointer non-activation on caught exceptions but do not prove a fresh instance ignores partial canonical data.

- timestamp: 2026-09-09T14:12:00+08:00
  checked: existing Fabric sync lifecycle tests
  found: tests lock exact side-effect order, all caught pre-activation failpoints leaving the pointer empty, deterministic repeat publication, and shortcut failure non-activation. No test simulates process death by bypassing the exception rollback, reopens the same lakehouse through a new `FabricSyncService`, or asserts authoritative predecessor selection.
  implication: the crash-recovery equivalence class is unguarded despite strong ordinary exception and pointer-order coverage.

- timestamp: 2026-09-09T14:22:00+08:00
  checked: `OntologyGraphSynchronizer.synchronize`
  found: it validates current and active previous relationship sources independently against the 250000 source bound, drops older retired rows, then inserts one retirement tombstone for every previous active identity absent from current and checks the bound again on the union. The final size is exactly `|current identities| + |previous-active identities - current identities|`.
  implication: a valid current graph near the bound can deterministically overflow solely because a non-authoritative partial prior head has stale-only identities.

- timestamp: 2026-09-09T14:22:00+08:00
  checked: Delta write/version and Gold pointer semantics
  found: canonical ontology tables use atomic per-table `OVERWRITE`, Delta exposes current versions and restore but the service has no version-qualified read API. Gold tables are generation-partitioned and pointer-CAS activated last; the Gold metadata row records its own generation and prior Gold generation but does not record canonical ontology table versions.
  implication: the Gold pointer safely gates Gold readers but cannot reconstruct the authoritative canonical ontology predecessor after a later partial overwrite.

- timestamp: 2026-09-09T14:22:00+08:00
  checked: scheduled inventory refresh publication and remote lock
  found: scheduled/API refresh republishes inventory-owned tables and then calls the same full `FabricSyncService.sync` against bronze/silver/canonical ontology without an Exposure pointer store. The full sync does enter `OneLakeWriter.sync_lock`, but the remote lock uses an infinite lease and unconditionally breaks `LeaseAlreadyPresent`; its tests explicitly accept a concurrent writer invalidating the first holder.
  implication: refresh can mutate the shared canonical head independently of Gold activation, and the intended serialization boundary is not exclusive in production. This overlap is not yet proven necessary for the observed overflow, but it must be fixed or fenced before any completed-version marker can be authoritative.

- timestamp: 2026-09-09T14:22:00+08:00
  checked: available completion and publication markers
  found: `metadata_ingestion_state` completed rows identify source runs but not canonical table Delta versions; the ontology publication-attempt document tracks only latest REST publication outcome; the publication manifest tracks table disposition, not a graph generation. None can recover exact predecessor rows after the canonical head is overwritten.
  implication: robust post-pointer recovery needs an atomic durable association between a completed canonical publication and exact entity/relationship versions, or generation-qualified immutable canonical storage; merely checking that any Gold pointer exists is insufficient.

- timestamp: 2026-09-09T14:25:00+08:00
  checked: compact lifecycle overflow experiment
  found: with a relationship bound of 2, both current and partial-prior sources contained exactly 2 valid rows, their identity intersection was 1, and the partial prior contributed exactly 1 retirement tombstone. The predicted synchronized count was 3 and the real synchronizer raised `Ontology synchronized relationship graph exceeds bound`.
  implication: unqualified predecessor selection plus identity delta is sufficient for the exact error mechanism; no concurrent refresh is required for the arithmetic overflow.

- timestamp: 2026-09-09T14:27:00+08:00
  checked: first shared-lakehouse fresh-service experiment setup
  found: the harness stopped before writing canonical tables because `_state_row` was called with `status` positionally even though it is keyword-only.
  implication: this is a harness construction error and provides no evidence for or against fresh-process poisoning; rerun with the corrected call.

- timestamp: 2026-09-09T14:30:00+08:00
  checked: corrected shared-lakehouse fresh-service experiment
  found: a first service persisted version-0 canonical entity/relationship tables and only a `started` ingestion row, with the Gold pointer still `{}`. A newly constructed service over the same lakehouse raised `Ontology synchronized relationship graph exceeds bound`; the same current candidate against a clean lakehouse completed with exactly 2 relationships.
  implication: process-local memory and rollback state are irrelevant after restart; the durable mutable head alone causes the retry failure, and ignoring non-authoritative predecessor rows is a causal counterfactual that removes it.

- timestamp: 2026-09-09T14:36:00+08:00
  checked: read-only retained production canonical Delta heads
  found: `ontology_entities` Delta version 73 has 83392 rows: 83304 active and 88 retired. `ontology_relationships` Delta version 71 has 235281 rows: all 235281 active. Each table contains exactly one ontology version, confirming a full per-table replacement rather than mixed rows inside either table.
  implication: the hard-killed publication left a coherent partial-run canonical pair at individual table granularity, but neither table is qualified by a completed publication marker; exact current/prior identity intersection is the remaining production count discriminator.

- timestamp: 2026-09-09T14:51:00+08:00
  checked: first bounded read-only production candidate reconstruction
  found: the current DatasetStore pointer now resolves to a later small scheduled-refresh snapshot with 201 ontology entities and 83 relationships before lifecycle synchronization. Against the retained partial head it would produce 83293 entity tombstones and 235281 relationship tombstones, totaling 83494 entities and 235364 relationships, so it does not reproduce the 250000 overflow.
  implication: mutable `current.json` no longer identifies the failed activation input. The failed ingestion state's immutable `source_run_id` must be replayed for exact arithmetic; this also confirms scheduled refreshes mutate the shared source-generation pointer.

- timestamp: 2026-09-09T14:51:00+08:00
  checked: activation versus scheduled-refresh source selection
  found: scheduled refresh pins its just-published combined generation by passing `replay_source_run_id`; `activate_runtime` publishes a combined generation but calls Fabric sync without that ID, leaving a window where another refresh can change `current.json` before `_resolve_snapshot`.
  implication: source-generation selection has an independent order race. It did not cause the compact overflow, but activation must pin its own immutable generation and refresh publication must serialize with Fabric publication to make failure-injection tests deterministic.

- timestamp: 2026-09-09T15:04:00+08:00
  checked: immutable replay of the exact failed activation source
  found: `metadata_ingestion_state` still identifies the source generation for the exact relationship-bound failure, but its root generation directory has already been removed by DatasetStore retention, so `_resolve_snapshot_remote` rejects the now-missing path before mapping.
  implication: the failed candidate cannot be replayed from the combined-generation root directly. Exact reconstruction must use a still-retained per-connection source generation or be limited to the durable prior-head and logged candidate counts; this does not weaken the fresh-instance causal reproduction.

- timestamp: 2026-09-09T15:29:00+08:00
  checked: retained source-generation inventory
  found: three per-connection discovery generations remain, including the 04:58 generation immediately preceding the failed Fabric run. Each has 64 datasets and approximately 199431-202944 aggregate rows, dominated by 151222-151248 vulnerability observations plus 23542-23554 source-partition rows. Only later small 209-row combined generations remain at the root; the failed high-cardinality combined generation was pruned.
  implication: the exact discovery payload is still available, but it must be rewrapped through the activation combiner because mapping a connection manifest directly is not equivalent to mapping the combined activation manifest.

- timestamp: 2026-09-09T15:29:00+08:00
  checked: direct read-only mapping of the retained 04:58 connection generation
  found: before lifecycle synchronization it produced 84580 unique active entities and 235497 unique active relationships. Against the current partial head, entity intersection was 83182 with 122 new entity tombstones; all 235281 partial-prior relationships were present, so the predicted relationship size remained 235497 and did not overflow.
  implication: the high-volume source alone does not inevitably fail, and the direct-connection mapping is not the exact failed input. This falsifies any hypothesis that relationship volume by itself, without the publication-envelope/predecessor identity delta, explains the observed error.

- timestamp: 2026-09-09T15:38:00+08:00
  checked: first temporary combined-envelope reconstruction harness
  found: the harness assumed a separate `started` ingestion row existed for the failed run, but `_write_state` MERGEs by run resource ID, so the terminal `failed` row overwrites that run's started status and no matching started row remains.
  implication: use the nearest retained combined completion time only as projection-time metadata; source identity and payload remain tied to the failed row and retained 04:58 discovery generation.

- timestamp: 2026-09-09T16:02:00+08:00
  checked: locally rewrapped 04:58 discovery input through the exact activation combiner
  found: the 50-dataset combined envelope produced 83372 unique current entities and 235364 unique current relationships. It would add 122 prior-only entity tombstones but zero relationship tombstones because all 235281 partial-prior relationship identities were still present.
  implication: this earlier generation does not reproduce the terminal error and is eliminated as the failed Fabric input. The retained 05:19 connection generation, completed after long connection discovery and before the 05:54 failure, is the remaining exact source candidate.

- timestamp: 2026-09-09T16:25:00+08:00
  checked: locally rewrapped retained 05:19 discovery input through the exact activation combiner
  found: using a provisional 05:40 projection timestamp, the candidate had 81160 unique active entities and 234024 unique active relationships. The partial head intersected on 80936 entities but only 1857 relationships, yielding 2368 entity tombstones and 233424 relationship tombstones. The exact predicted synchronized sizes were 83528 entities and 467448 relationships.
  implication: this retained input deterministically reproduces the production error by a wide margin and proves the partial head is lifecycle-incompatible. Only the removed combined manifest's exact completion time remains uncertain; it can affect temporal row counts but cannot reduce a 217448-row overflow enough to change causality.

- timestamp: 2026-09-09T16:30:00+08:00
  checked: read-only retained stage logs for execution `7nyjitk`
  found: combined snapshot started at 05:24:58Z and completed with 50 datasets at 05:26:11.5473124Z; Fabric publication began immediately, temporal projection completed with 154729 aggregate rows at 05:52:59Z, container projection completed with 77357 at 05:53:05Z, and ontology construction failed 49.2 seconds after starting at 05:53:39Z.
  implication: the removed combined manifest's exact `completedAt` is recoverable. One final reconstruction at that cutoff can provide exact current/intersection/tombstone/result counts without cloud mutation.

- timestamp: 2026-09-09T16:55:00+08:00
  checked: exact failed production candidate reconstruction at the retained 05:26:11.5473124Z combined completion cutoff
  found: current candidate = 81160 unique active entities and 234024 unique active relationships. Partial prior = 83392 entity rows (83304 active, 88 retired) and 235281 active relationships. Active identity intersections = 80936 entities and 1857 relationships. New tombstones = 2368 entities and 233424 relationships. Exact synchronized predictions = 83528 entities and 467448 relationships, so entities remain under 100000 while relationships exceed 250000 by 217448.
  implication: this reproduces the precise failure class and quantifies every requested set. The relationship identity collapse from 235281 prior rows to only 1857 overlaps is too large to attribute to the modest source-row delta and points directly to mutable evidence in `_relationship_id`.

- timestamp: 2026-09-09T17:15:00+08:00
  checked: relationship resource-ID versus semantic-key differential
  found: the current and partial-prior graphs share 233847 `(subject_id, predicate, object_id)` keys but only 1857 resource IDs. Of shared semantic keys, 231990 changed ID and only 1857 retained ID; there are only 1434 true prior-only semantic keys and 177 true current-only keys. Endpoint-stable identity predicts 235458 synchronized relationships, 14542 below the 250000 bound.
  implication: mutable `event_interval` in `_relationship_id` manufactures 231990 false lifecycle transitions. Keeping interval evidence in payload/change-version and Delta history while deriving identity from the validator's unique endpoint triple preserves audit and prevents future post-pointer sync poisoning.

- timestamp: 2026-09-09T17:18:00+08:00
  checked: spectrum fault localization eligibility and common-pattern routing
  found: no pre-existing failing local test or per-test coverage spectrum represented process death, so SBFL was skipped. The matching common patterns are state-management invalid transition/dual truth (pointer versus mutable head), async/order publication-before-finalization, and environment hard-death bypass.
  implication: deterministic reproduction, working backwards, differential identity analysis, and failure injection are the appropriate Bohrbug route; no flaky spectrum ranking is being used.

- timestamp: 2026-09-09T17:22:00+08:00
  checked: recovery design analysis A-E
  found: "(A) No predecessor without a Gold pointer is safe only for initial bootstrap and fails after a post-pointer partial overwrite. (B) Last completed publication plus exact entity/relationship Delta versions is the smallest robust recovery and supports both initial-empty and post-pointer time-travel. (C) A durable before-version transaction journal can recover but needs crash-idempotent rollback for every table and is much broader. (D) Generation-qualified staging plus CAS is strongest but requires schema/query/binding migration across canonical consumers. (E) Separate retirement-event history avoids active-graph growth but does not by itself stop partial-head reads; endpoint-stable IDs already separate changing evidence from semantic lifecycle while existing Delta versions retain audit."
  implication: select B, combined with endpoint-stable relationship identity. Add exclusive finite renewable locking and activation source pinning as necessary boundary hardening, not as substitutes for authoritative version selection.

- timestamp: 2026-09-09T17:28:00+08:00
  checked: first focused TDD invocation
  found: pytest did not collect or execute tests because the unrelated auto-loaded Phoenix plugin raises a Python 3.11 dataclass mutable-default error during startup.
  implication: this is test-runner environment noise, not red evidence. Disable third-party plugin autoload and rerun the exact tests.

- timestamp: 2026-09-09T17:32:00+08:00
  checked: focused TDD red gate with third-party plugin autoload disabled
  found: all 3 tests failed exactly as predicted. Initial fresh retry received 16 uncommitted predecessor entities; post-pointer retry read the partial relationship head and missed one ID from the completed graph; changing only `event_interval.to` changed all three generated relationship resource IDs while their endpoint triples remained identical.
  implication: the automated oracle directly exercises both initial and post-pointer crash recovery plus mutable identity churn. Production implementation may now begin only in the continuation green phase.

- timestamp: 2026-09-09T17:50:00+08:00
  checked: exact TDD GREEN gate
  found: all 3 specified-oracle tests pass after adding version-qualified Delta reads, recording exact canonical entity/relationship versions only in the completed ingestion-state row after pointer activation, reading lifecycle input from that marker, and deriving relationship IDs from endpoint triples only.
  implication: the root-cause counterfactual is now automated: absent markers yield no predecessor, later partial heads cannot displace the completed pair, and mutable interval evidence changes relationship content without changing semantic identity.

- timestamp: 2026-09-09T18:10:00+08:00
  checked: focused publication, Delta, lock, activation, scheduled-refresh, and ontology suites
  found: 118 focused tests passed. Coverage includes version 0 and invalid version neighbors, fresh-service process-death partial heads, pre/post-pointer predecessor selection, semantic-reader time travel, marker-after-pointer ordering, pointer failure and shortcut failure, immutable activation/refresh source pins, finite lease renewal/loss, active-lease refusal without break, stable endpoint identity, and count-only entity/relationship overflow diagnostics. Scoped Ruff passed.
  implication: the hardening paths are locally green and the global backend regression gate can begin without cloud execution.

- timestamp: 2026-09-09T18:25:00+08:00
  checked: first full backend and repository-wide Ruff gates
  found: the backend suite had exactly one failure: a valid workload-only snapshot produced empty canonical ontology tables, which the existing publication loop skipped when no prior table existed, so no exact versions were available for the completed marker. Repository-wide Ruff reported 27 pre-existing errors exclusively in out-of-scope infra/scripts and scripts files; scoped Ruff remained clean.
  implication: the marker must materialize schema-valid empty canonical tables at version 0 rather than allow an unversioned completed publication. Full-tree Ruff debt is unrelated and will be recorded without editing those files.

- timestamp: 2026-09-09T18:35:00+08:00
  checked: second full backend gate after empty-table correction
  found: JUnit reports 4027 collected, 4026 passed, 1 skipped, 0 failed, and 0 errors in 254.662 seconds. Schema-valid empty canonical tables now publish at version 0. Scoped Ruff remains clean; repository-wide Ruff still has only the same 27 unrelated pre-existing script findings.
  implication: the production change has no backend regression in the complete local suite and preserves the exact marker contract at the empty lower boundary.

- timestamp: 2026-09-09T18:45:00+08:00
  checked: fix-acceptance revert-and-reconfirm
  found: after a path-scoped temporary revert of all seven production files while retaining the agent-authored tests, all three specified oracles failed at the original assertions; restoring the exact backed-up production files made all three pass. No Stryker configuration exists, so framework mutation testing is unavailable; the full production revert served as a stronger manual causal mutation.
  implication: the fix, not test weakening or unrelated working-tree state, causes the GREEN result.

- timestamp: 2026-09-09T18:50:00+08:00
  checked: publication side-effect order during scoped review
  found: the first GREEN implementation wrote the completed canonical-version marker after Gold pointer activation, which made the pointer no longer the absolute final side effect and left a hard-death window with an activated pointer but no matching marker.
  implication: place the marker after shortcut/canonical finalization but before pointer activation. Before-marker death remains uncommitted; after-marker death leaves a fully finalized canonical graph; pointer activation stays last.

- timestamp: 2026-09-09T19:05:00+08:00
  checked: final marker-order focused and full-suite regression gates
  found: 120 focused tests passed with pointer activation restored as the final successful side effect. Final JUnit reports 4029 collected, 4028 passed, 1 skipped, 0 failed, and 0 errors in 355.067 seconds; scoped Ruff remains clean.
  implication: the ordering correction is regression-safe and explicitly covers no-marker partial death, finalized pre-pointer canonical state, post-pointer partial overwrite, pointer failure, and semantic-reader time travel.

- timestamp: 2026-09-09T19:20:00+08:00
  checked: independent offline code review and direct finding verification
  found: a locally installed offline qwen coder reviewed the scoped production/test diff without sending repository content to a third party. It reported no critical/high/medium concrete defect; its only cautions were intentional fail-closed behavior for legacy null markers, linear completed-state lookup cost, and one bounded renewal thread per exclusive sync. Direct source review confirmed the active lease is never broken, lease loss prevents rollback/failure-marker writes and is checked around consequential publication boundaries, and the worker is stopped/joined.
  implication: there is no unresolved high-confidence review finding. Legacy-marker availability and Delta retention remain operational rollout risks, not correctness escapes.

- timestamp: 2026-09-09T19:25:00+08:00
  checked: scoped diff and working-tree ownership
  found: `git diff --check` passed. The 12 owned code/test files contain 872 added and 89 deleted lines including the pre-existing RED tests; the protected Terraform/Azure files remain modified exactly as pre-existing and unstaged, while `.planning/debug/phase031-plan19-live-oom.md` has no diff. No cloud command, build, pointer/table write, deployment, or push occurred.
  implication: the verified patch is ready for a path-scoped atomic commit without disturbing concurrent work.

- timestamp: 2026-09-09T19:35:00+08:00
  checked: atomic code/test commit
  found: commit `1132705ff003d969af4c1c57699402169ffe6ce4` contains exactly the 12 owned production/test paths, 872 insertions and 89 deletions, conventional subject `fix(fabric): make ontology predecessor publication atomic`, and the required `Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>` trailer. Protected and unrelated paths remain unstaged; no push occurred.
  implication: the validated implementation is durably isolated in one atomic commit and the live debug record can be committed separately without mixing concurrent work.

- timestamp: 2026-09-09T19:45:00+08:00
  checked: post-commit identity and ownership verification
  found: `git show` confirms code/test commit `1132705ff003d969af4c1c57699402169ffe6ce4` and initial debug-record commit `044f1115aa09986e6c2aff6e098b91b81774ed9d`, both with the required trailer. All 12 owned code/test paths and this debug path are clean against HEAD; only the same pre-existing unrelated changes remain; branch is ahead by local commits and nothing was pushed.
  implication: commit identity, atomic scope, trailer, preserved working tree, and no-push constraints are directly verified.

- timestamp: 2026-09-09T16:48:00.796+08:00
  checked: human verification checkpoint
  found: the user confirmed the code-level result fixed and explicitly authorized archival resolution plus the prevention-pattern append.
  implication: the session may be marked resolved and archived; no production, test, cloud, or unrelated working-tree mutation is authorized.

- timestamp: 2026-09-09T16:48:02+08:00
  checked: archival integrity and prevention artifacts
  found: the active record is absent, the resolved record is present with `status: resolved`, the knowledge base contains exactly one matching entry, scoped `git diff --check` passes, and the named crash-recovery, endpoint-identity, lease, and immutable-source regression tests exist. GSD state reports `commit_docs: true`; MemPalace is unavailable, so semantic indexing is skipped with the durable Markdown knowledge base retained as fallback.
  implication: the archive and recurrence guard are concrete and internally consistent; only the three archival/debug paths need staging, and no test rerun or production edit is warranted.

## Resolution

root_cause: "AND-gate: canonical ontology publication had no durable completed-version marker, so hard exit 137 left newer per-table heads that a fresh service consumed as predecessor; relationship IDs also included mutable event intervals, making 231990 unchanged semantic edges look retired/recreated; at 234024 current relationships this produced 233424 false tombstones and a 467448-row synchronized graph. The remote sync lock's break-active-lease behavior and unpinned activation source were independent publication-order defects that permitted interleaving."
fix: "Record exact canonical entity/relationship Delta versions in the completed ingestion-state row only after shortcut/canonical finalization; read lifecycle and semantic graph rows at that authoritative pair; always materialize empty canonical tables at version 0; derive relationship IDs only from `(subject_id,predicate,object_id)` while preserving interval/evidence in payload/change_version/Delta history; use an exclusive 60-second renewable OneLake lease that never breaks an active peer and fails closed on renewal loss; pin activation to its immutable combined source run; emit count-only overflow cardinalities."
verification:
  target_test:
    result: pass
    tests: "3/3 specified RED oracles green"
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker or Python mutation framework is configured; a full path-scoped production revert was used as a manual mutation."
    mutant_killed: "manual equivalent yes — all 3 target tests failed without the production fix"
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    evidence: "The patch adds authoritative version selection, lease enforcement, source pinning, diagnostics, and tests; the only semantic removal is mutable evidence from relationship identity, explicitly required by the confirmed RCA while evidence remains in payload/change_version/history."
  adjacent_tests:
    result: pass
    suites_run:
      - "focused publication/Delta/lock/activation/refresh/ontology: 120 passed"
      - "full backend: 4029 collected, 4028 passed, 1 skipped, 0 failed, 0 errors"
      - "scoped Ruff: passed"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
  guardrail_verdict: accepted
  human_verify: "confirmed fixed at the 2026-09-09 human verification checkpoint"
  repository_ruff: "27 pre-existing findings only in out-of-scope scripts; no owned-file finding"
  independent_review: "offline qwen coder plus direct finding verification: no unresolved critical/high/medium finding"
prevention:
  causal_branches:
    - "code/publication: canonical tables were individually durable before authority was recorded, and readers selected mutable heads rather than an exact completed Delta version pair."
    - "code/data-model: relationship identity included mutable evidence intervals, turning evidence updates into false retire-and-recreate lifecycle events."
    - "environment/data: exit 137 bypassed process-local rollback, while production-scale relationship cardinality amplified false identity churn beyond the validated bound."
    - "config/concurrency: the remote lock treated an active infinite lease as breakable and activation did not pin its source generation, independently permitting publication interleaving."
  why_not_caught: "No gate modeled hard process death across fresh service instances or asserted a canonical completed-version pair; existing tests covered caught exceptions and pointer non-activation only. Relationship tests asserted row validity but not identity stability across mutable evidence intervals. The lock test explicitly encoded unsafe active-lease breaking."
  recurrence_guard: "Specified regression tests in tests/test_fabric_sync_service.py cover pre-marker partial death, finalized pre-pointer versions, post-pointer partial overwrite, semantic-reader time travel, and finalization order; tests/test_operational_context_graph_v2_hardening.py locks endpoint-stable identity and count-only bounds; tests/test_onelake_writer.py locks exclusive finite renewal/loss semantics; tests/test_onboarding_activation.py and tests/test_inventory_refresh_multi_connection.py lock immutable source selection."
mutation_order:
  - "Acquire exclusive finite renewable lakehouse lease; refuse an active peer."
  - "Write started ingestion state, resolve the pinned immutable source, map/project/build, and validate fail closed."
  - "Write quality/source status, then ordinary and canonical Delta tables; canonical empty tables still receive exact version 0."
  - "Register assets, write catalog, publish ontology, stage/reconcile generation-qualified Gold tables, register Gold assets, and write Gold catalog."
  - "Finalize shortcuts, then write the completed ingestion-state marker containing the exact canonical entity/relationship Delta versions."
  - "Activate the Gold pointer last; any earlier death leaves either no marker or a fully finalized canonical predecessor, and never mutates the pointer."
design_comparison: "A/no predecessor without a pointer handles bootstrap only; C/durable rollback journal is broader and crash-idempotence-heavy; D/generation-qualified canonical staging plus CAS is strongest but requires consumer/schema migration; E/separate retirement history does not stop partial-head reads. Selected B/exact last-completed Delta versions is the smallest robust predecessor fix, combined with endpoint-stable identity and exclusive locking."
remaining_risks:
  - "Delta vacuum/retention must preserve versions referenced by completed markers; missing historical files fail closed but require operational retention."
  - "Legacy completed rows have null version fields and intentionally fail closed until one new completed sync publishes the authoritative pair."
  - "Lease loss is detected at guarded publication boundaries rather than fenced into each Delta transaction; partial work remains unmarked and therefore non-authoritative."
safe_to_build: "yes — local source/test/lint/review gates pass; no build was started under the freeze"
safe_to_run: "implementation is retry-safe, but cloud execution remains NOT AUTHORIZED while the global cloud/source freeze is active; a future run requires freeze release and normal immutable-image/template preflight"
commits:
  code_and_tests: "1132705ff003d969af4c1c57699402169ffe6ce4"
  debug_record: "044f1115aa09986e6c2aff6e098b91b81774ed9d (initial complete verification record; exact-hash correction committed separately and reported at the human checkpoint)"
oracle_type: specified
files_changed:
  - "src/fabric/schema_registry.py"
  - "src/fabric/sync_service.py"
  - "src/onboarding/activation.py"
  - "src/ontology/ontology_sync.py"
  - "src/ontology/relationship_builder.py"
  - "src/storage/delta_writer.py"
  - "src/storage/onelake_writer.py"
  - "tests/test_delta_tables.py"
  - "tests/test_fabric_sync_service.py"
  - "tests/test_onboarding_activation.py"
  - "tests/test_onelake_writer.py"
  - "tests/test_operational_context_graph_v2_hardening.py"
investigation_cycles: 0
fix_cycles: 2
