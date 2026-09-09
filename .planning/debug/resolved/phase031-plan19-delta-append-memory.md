---
status: resolved
trigger: "Phase 03.1 Plan 19 isolated atomic publication execution mbeu6qc deterministically exits 137 when beginning table 54, believed to be the first 154k-row APPEND write through DeltaWriter's unbounded Python/Arrow copy and existing-target scan path."
created: 2026-09-09T18:29:40.797+08:00
updated: 2026-09-09T20:10:00.000+08:00
---

# Phase 03.1 Plan 19 Delta APPEND Memory

## Current Focus

reasoning_checkpoint:
  hypothesis: "The corrected GREEN candidate is still incorrect in two deterministic failure windows: independently committing each APPEND chunk exposes earlier chunks when a later chunk permanently fails, and retrying after a commit-then-transient-error loses invocation-level commit accounting because the retry observes the row as pre-existing."
  confirming_evidence:
    - "Independent review reports a batch-size-2 permanent-failure reproduction that leaves the first two rows committed at Delta version 0 after `DeltaWriter.write` raises."
    - "Independent review reports a commit-then-transient-error reproduction whose retry returns `rows_added=0`, `skipped=True`, `version=0` even though this invocation committed one row."
    - "Agent-authored RED tests reproduced both states exactly: later batch materialization advanced an existing table from version 0 to 1 before raising, and commit-then-error returned rows_added=0/skipped=True."
    - "A pinned 1.6.2 probe showed a lazy RecordBatchReader failing after its first batch creates no Delta transaction, while a successful three-batch reader creates exactly one version; custom commit metadata is readable from history."
  falsification_test: "Finding 1 is false if an agent-authored late-chunk permanent-failure test leaves no newly published table/rows after `write` raises. Finding 2 is false if an agent-authored commit-then-error retry returns rows_added equal to the rows committed by this invocation, skipped false, and the actual committed version."
  fix_rationale: "Feed lazily constructed, configured-size RecordBatches through one RecordBatchReader to one `write_deltalake` call, so no batch is Delta-visible until all batches commit atomically. Stamp that transaction with one random invocation ID and intended added-row count; on retry, recover the matching latest history entry before deduplication so a post-commit exception returns the committed version/count instead of a final-attempt skip."
  blind_spots: "Remote OneLake Arrow-stream and commit-history behavior is not end-to-end exercised; concurrent writers outside FabricSyncService's exclusive lease could interleave history, so recovery must scan a bounded recent history window by unique invocation ID rather than assume the latest commit."
  candidate_causes:
    - "code: one APPEND invocation is split into independently visible Delta transactions without rollback when a later chunk fails"
    - "data: inputs larger than `_append_batch_size` activate the partial-publication window"
    - "environment: a permanent later-chunk storage failure exposes the partial transaction sequence"
    - "code: retry accounting is derived only from the final attempt rather than invocation-level committed state"
    - "environment: a transport/storage exception raised after a successful commit activates the ambiguous-success retry path"
  and_gate: "yes for each manifestation — partial publication requires a multi-chunk input plus a later permanent failure; false retry accounting requires a successful commit plus a post-commit transient exception. The two reviewer findings are otherwise independent and both must be corrected."
hypothesis: "RESOLVED — one lazy bounded Arrow stream maps one APPEND invocation to one Delta transaction, and unique commit metadata recovers truthful results after a post-commit transient exception."
test: "Human verification is confirmed after all automated round-2 target, boundary, adjacent, causality, full-suite, static, build, and diff-scope checks passed."
expecting: "The resolved session and prevention pattern are archived in scoped documentation commits with the required coauthor trailer; no protected path is staged and nothing is pushed."
next_action: "Move this resolved session to `.planning/debug/resolved/`, commit that exact archive document, then append and commit the matching knowledge-base prevention entry."
build_run_safety:
  build: "SAFE — final local sdist/wheel build and 4047-test backend suite completed successfully"
  local_run: "SAFE — focused atomicity/accounting, no-stat/preflight, boundary, adjacent, causality, full-suite, Ruff, and diff checks pass"
  cloud_run: "NOT AUTHORIZED OR END-TO-END VERIFIED — no push, deployment, Fabric, Azure, or OneLake mutation was performed; a later isolated production-like run requires explicit authorization"
tdd_checkpoint:
  test_file: tests/test_delta_tables.py
  test_name: "atomic late-batch failure and truthful commit-then-error accounting"
  status: "green"
  failure_output: "2 failed: later batch failure advanced table version 0 to 1; commit-then-error returned rows_added=0 instead of 1"
bug_class: bohrbug
goal: find_and_fix
tdd_mode: true
candidate_causes:
  - code/memory: `DeltaWriter.write` eagerly copies every incoming row with `normalized=[dict(row) for row in rows]`
  - code/memory: `_write_once` builds one giant `pa.Table.from_pylist(rows, schema=schema)`
  - code/memory/io: existing APPEND converts the entire target through `to_pyarrow_table().to_pylist()` before deduplication, including an empty existing target
  - data/scale: the first temporal product contains roughly 154000 observations and is materially larger than the preceding 53 tables
  - environment: the isolated writer begins table 54 with only approximately 1.9 GiB cgroup headroom
  - alternative/concurrency: competing writers or writer concurrency amplify memory
and_gate: yes — the concrete exit 137 requires the resource-unbounded APPEND implementation together with the valid 154k-row input and the deployed process's approximately 1.9 GiB remaining headroom; concurrency is not required
review_rejection:
  finding_1: "Both APPEND validation gates use approximate `table.count() > 0`; active files lacking `num_records` can make a non-empty table look empty and bypass immutable-conflict validation and retry-time deduplication."
  finding_2: "APPEND existence detection, DeltaTable construction, emptiness checks, and preflight filtered reads occur outside `_retry()`, regressing the prior operation-level retry envelope for transient preflight failures."
  scope: "Only the existing four-file scoped diff may be changed; protected Data Agent, Gold-grounding, and `.azure` paths remain excluded."
review_rejection_round_2:
  finding_1: "Each bounded APPEND chunk commits independently; a later exhausted retry raises without giving FabricSyncService a version to restore, leaving earlier chunks visible."
  finding_2: "A commit-then-transient-error retry deduplicates the committed row but returns final-attempt-only rows_added=0/skipped=True accounting."
  confirmed_closed: "Active-file presence replaces approximate count; complete bounded preflight is retried."
  scope: "Only the existing four-file scoped diff may be changed; protected Data Agent, Gold-grounding, and `.azure` paths remain excluded."

## Scope and Safety Constraints

- This debug cycle is in scope for active Phase 03.1 Plan 19, confirmed by `.planning/STATE.md`.
- Run a full scientific find-and-fix cycle with a mandatory TDD RED checkpoint before GREEN.
- No Azure, Fabric, or OneLake mutation and no retry of the publication execution.
- Do not run Terraform, ACR, Azure Container Apps, Job, pointer, table, schedule, traffic, capacity, or networked write commands.
- Read-only cloud evidence is allowed only if essential; prefer repository source, deterministic local services, and tests.
- Do not touch, stage, or commit unrelated dirty Gold-grounding/Data Agent work, including:
  - `docs/ontology-generation-consumer-inventory.md`
  - `infra/terraform/fabric.tf`
  - `src/fabric/data_agent_manager.py`
  - `src/fabric/fabric_client.py`
  - `src/ontology_discovery/generation_resolver.py`
  - `src/operations/gold_grounding_specialist.py`
  - related tests, new scripts/files, and `.azure/*`
- All other debug sessions remain frozen.
- Stage specific files only. Make atomic conventional commits with the repository-required coauthor trailer. Do not push.
- Preserve immutable APPEND semantics: matching keys with changed content fail closed; retries after partial writes append only missing rows; no rows may be silently dropped.
- Production APPEND must not use one giant Arrow table or `to_pyarrow_table().to_pylist()` over the full target.
- Do not use RSS thresholds as the primary test oracle, and do not use blind garbage collection as the primary fix.

## Required Scientific Work

1. Prove table 54 identity and insertion order with a focused deterministic test or instrumented local service.
2. Reproduce the APPEND memory/copy defect with behavioral tests:
   - existing empty APPEND does not scan the target;
   - first large APPEND emits bounded Arrow/write batches;
   - retry after partial chunk writes appends only missing rows;
   - matching incoming/existing keys with different immutable content fail closed;
   - no test relies on fragile RSS thresholds.
3. Evaluate production-safe designs, preferring bounded chunked Arrow writes plus filtered reads of only incoming keys.
4. Preserve table-absent, existing-empty, invalid/partial no-files log, empty-incoming, local/remote Delta, retry/transient error, version, and result-count behavior. Specify and test fail-closed or explicit recovery behavior for a corrupt no-files log.
5. Add Arrow allocator release only if evidence proves it necessary and safe.
6. Add sanitized table-started progress with name/count if useful, so death before completion identifies the active table.
7. Run focused tests, full backend, Ruff, targeted diff inspection, causality revert/reapply, and independent review.
8. Return exact root cause, falsified alternatives, implementation, bounded batch size, test totals, commits, remaining risk, and build/run safety verdict.

## Eliminated

- hypothesis: concurrent writer amplification is sufficient to explain the latest failure.
  evidence: isolated execution `mbeu6qc` used one writer under an exclusive renewable lease, no competing writer ran, and memory still rose deterministically only after table 53 completed.
  timestamp: 2026-09-09T18:29:40.797+08:00

- hypothesis: the atomicity/predecessor/relationship-identity defect remains the immediate blocker.
  evidence: the atomicity fix is committed and pushed at HEAD `dcd523059` with runtime code commit `1132705ff`; completed-version predecessor selection, stable relationship identity, and exclusive renewable lease are green across 4028 CI tests.
  timestamp: 2026-09-09T18:29:40.797+08:00

- hypothesis: the failed run activated a partial Gold publication.
  evidence: execution `mbeu6qc` left pointer `{}` and no completed version marker.
  timestamp: 2026-09-09T18:29:40.797+08:00

## Evidence

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: active project scope
  found: `.planning/STATE.md` names Phase 03.1, Plan 03.1-19 as the current next plan, blocked on exact live evidence after Fabric publication.
  implication: this bounded publication-memory repair is in active phase scope.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: atomicity repair baseline
  found: the atomicity repair is at HEAD `dcd523059` and runtime commit `1132705ff`; completed-version predecessor selection, stable relationship identity, and exclusive renewable lease passed 4028 CI tests.
  implication: preserve those semantics and diagnose the subsequent isolated memory failure independently.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: production scheduling and writer isolation
  found: duplicate Inventory Refresh schedules and the ontology publisher cron are paused, the old API revision was restarted, an orphan infinite lease was broken, a finite lease probe passed, and no competing writer ran.
  implication: overlapping publication is falsified as a sufficient cause of this execution's memory curve.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: isolated execution `mbeu6qc`
  found: the run used exact image `sha256:df2a...`, 4 CPU/8 GiB, one writer, timeout 7200, zero retries, and an exclusive lease; it exited 137 at 10:25Z. Job image and timeout were restored exactly, pointer remained `{}`, and no completed version marker exists.
  implication: the process died before publication completion and no retry or cloud recovery action is authorized.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: deterministic table progress
  found: tables 1 through 53 completed; table 53 was `metadata_workload_source_checkpoints`; the process died before a completion event for table 54.
  implication: the active table boundary is narrow and can be proved from deterministic insertion order.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: dataset construction order
  found: `_load_workload_products` adds checkpoints before `temporal.write_tables()`, whose first item is `silver_exposure_observations`; `_synchronize_ontology` later deletes and re-adds typed ontology tables.
  implication: table 54 is strongly predicted to be `silver_exposure_observations`, but a focused deterministic test must prove it rather than assume it.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: temporal projection volume and existing target state
  found: temporal projection completed with roughly 154000 observations; reading the existing Delta table raised `TableNotFoundError: No files in log segment`, consistent with an absent or partial first table.
  implication: publication likely attempts a high-cardinality first write and must define explicit fail-closed/recovery behavior for a no-files log.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: execution memory curve
  found: memory stayed approximately 6.10-6.12 GiB through table 53, then rose through 6.44 and 6.77 GiB to an observed 6.93 GiB before cgroup exit 137.
  implication: the fatal growth begins at the first uncompleted table rather than accumulating materially over the preceding 53 table writes.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: current `DeltaWriter.write` incoming-row path
  found: it eagerly executes `normalized=[dict(row) for row in rows]`, and `_write_once` then executes `pa.Table.from_pylist(rows, schema=schema)`.
  implication: a large first write creates an unbounded Python duplicate followed by a large Arrow materialization.

- timestamp: 2026-09-09T18:29:40.797+08:00
  checked: current existing-target APPEND path
  found: APPEND with an existing target executes `table.to_pyarrow_table().to_pylist()` over the entire target before deduplication, and even an empty existing target is scanned before returning skipped.
  implication: retries and long-lived append tables have target-size-dependent memory, violating bounded publication and making empty-target work needlessly unsafe.

- timestamp: 2026-09-09T18:33:05.000+08:00
  checked: source and focused-test localization
  found: the writer is isolated in `src/storage/delta_writer.py`; temporal table ordering originates in `src/fabric_pipelines/vulnerability_pipeline.py::write_tables` and is merged by `src/fabric/sync_service.py::_load_workload_products`; focused coverage exists in `tests/test_delta_tables.py`, `tests/test_vulnerability_pipeline.py`, and `tests/test_fabric_sync_service.py`.
  implication: deterministic contract-level RED tests can target local code without rerunning the unsafe cloud publication.

- timestamp: 2026-09-09T18:35:30.000+08:00
  checked: complete current `DeltaWriter` control flow
  found: `write()` always copies all incoming mappings into one Python list; APPEND on an existing table always calls `DeltaTable.to_pyarrow_table().to_pylist()` before knowing whether the target is empty; APPEND then rebuilds two key dictionaries/lists; and every non-skipped write reaches one `pa.Table.from_pylist(rows)` and one `write_deltalake` call.
  implication: the current implementation has direct deterministic observables for all three unbounded materializations; no RSS-based oracle is required.

- timestamp: 2026-09-09T18:35:30.000+08:00
  checked: existing focused APPEND coverage
  found: current tests prove retry idempotency and immutable conflict rejection only against small real Delta tables; they do not constrain source batch size, target projection/filtering, empty-target scans, partial chunk retries, or no-files-log behavior.
  implication: regression tests must strengthen the existing specified immutable APPEND contract rather than merely duplicate current happy-path assertions.

- timestamp: 2026-09-09T18:38:10.000+08:00
  checked: production dataset assembly and publication order
  found: `FabricSyncService.sync` preserves insertion order while calling `datasets.update(workload_products)` and then `datasets.update(temporal.write_tables())`; workload products declare `metadata_workload_source_checkpoints` last, temporal tables declare `silver_exposure_observations` first, and publication iterates `datasets.items()` without sorting.
  implication: when all preceding production datasets are non-empty, `silver_exposure_observations` follows the workload checkpoint table exactly; an instrumented local fixture can turn the predicted ordinal into direct evidence.

- timestamp: 2026-09-09T18:38:10.000+08:00
  checked: common-pattern and taxonomy routing
  found: the closest common patterns are resource growth from retained/eager materializations and data-volume boundary behavior; the failure remains deterministic under one writer and the same large input, so it is classified as a Bohrbug rather than concurrency or transient timing.
  implication: deterministic behavioral reproduction and focused fault localization are valid; flaky-spectrum techniques are unnecessary.

- timestamp: 2026-09-09T18:42:15.000+08:00
  checked: pinned Delta API capabilities
  found: `deltalake` 1.6.2 exposes `DeltaTable.count()` and `to_pyarrow_table(columns=..., filters=...)`.
  implication: APPEND can detect valid-empty targets without a row scan and compare only target rows matching a bounded incoming-key batch.

- timestamp: 2026-09-09T18:42:15.000+08:00
  checked: local sync completion trace with the repository default fixture
  found: the fixture completed 62 tables but did not enable temporal projection or load non-empty workload products, so no `silver_exposure_observations` table appeared; publication also uses a `ThreadPoolExecutor`, making completion ordinal equal insertion ordinal only when `write_workers` is one.
  implication: the first trace does not prove production table 54; the next test must control the exact exposure/workload preconditions and worker count.

- timestamp: 2026-09-09T18:42:15.000+08:00
  checked: temporal publication caller behavior
  found: both `TemporalExposureFabricWriter.publish` and the main sync path fully read persisted observation history before projection; independently, the later `DeltaWriter` APPEND path scans that target again. The main sync needs full prior history for current-state projection, but the second writer scan is redundant and occurs at the observed write boundary.
  implication: the immediate write-boundary growth can be removed without changing temporal projection semantics; broader projection-memory redesign is a separate residual risk.

- timestamp: 2026-09-09T18:42:15.000+08:00
  checked: Phase 1.25 SBFL preconditions
  found: no failing regression test exists yet, so the suite does not currently provide the required at-least-one-failing/at-least-one-passing spectrum.
  implication: SBFL is skipped with a logged reason; the TDD RED will provide direct fault-localization evidence instead.

- timestamp: 2026-09-09T18:46:20.000+08:00
  checked: deployed publication concurrency
  found: `fabric.config.deploy.yaml` explicitly sets `write_workers: 1`, and runtime construction passes that value into `FabricSyncService`; the default is four only outside the deployed configuration.
  implication: deployed table completion order equals queued insertion order, so direct-successor dataset ordering can prove the missing table ordinal.

- timestamp: 2026-09-09T18:46:20.000+08:00
  checked: valid-empty and malformed Delta-log distinction
  found: a valid schema-only Delta target is a Delta table at version 0 with `count() == 0`; an `_delta_log` containing no protocol or metadata is still reported by `is_deltatable()` but `DeltaTable(...)` raises `DeltaError` before any write.
  implication: APPEND can avoid row scans for valid-empty targets while retaining fail-closed behavior for malformed logs; the missing-active-file variant still needs an explicit probe.

- timestamp: 2026-09-09T18:49:40.000+08:00
  checked: active-file corruption probe
  found: after deleting the only active Parquet file, `DeltaTable.version()` and `count()` still return normally from log metadata, so `count()` alone is not a general active-file integrity check.
  implication: target-key filtered reads remain fail-closed when a required matching file is unreadable, but unrelated pruned files are not validated by APPEND; the no-files-log contract must explicitly distinguish malformed logs from schema-valid empty tables rather than claim full-table integrity validation.

- timestamp: 2026-09-09T18:49:40.000+08:00
  checked: historical introduction
  found: the full incoming normalization and single Arrow-table write date to the initial Delta writer commit; full-target APPEND idempotency scanning was added later in `f36696a45`, and neither path was introduced by the latest atomicity repair.
  implication: the failure is a latent scale defect exposed by the new 154k-row workload, not a regression in the just-completed publication atomicity fix.

- timestamp: 2026-09-09T18:55:30.000+08:00
  checked: root-cause falsification threshold
  found: source inspection directly establishes three simultaneous full-row materializations, production telemetry localizes growth to the first large APPEND boundary, deployed concurrency is one, and the memory curve is repeatable under the same valid scale. The hypothesis would be false if current behavioral spies observed per-batch row conversion/Arrow writes and key-filtered target reads.
  implication: the mechanism is understood and falsifiable, alternatives in concurrency/recent atomicity are contradicted, and the session may enter the mandatory TDD RED phase.

- timestamp: 2026-09-09T19:04:05.000+08:00
  checked: first focused RED invocation
  found: pytest did not collect tests because auto-loaded third-party Phoenix raises a Python 3.11 dataclass `mappingproxy` error during plugin import.
  implication: this is an unrelated test-runner environment failure, not a regression result; rerun with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` before evaluating the hypothesis.

- timestamp: 2026-09-09T19:06:20.000+08:00
  checked: focused TDD RED suite with third-party plugin autoload disabled
  found: 22 tests passed and exactly 4 new APPEND constraints failed. At batch boundary N+1 the current writer emitted `[3]` rather than `[2, 1]`; valid-empty APPEND invoked `to_pyarrow_table()`; existing-target APPEND passed no filter; and the second-chunk transient failure was unreachable because all five rows were written in one call. The N-1/N boundary cases, direct-successor publication ordering, pre-write immutable conflict refusal, malformed-log fail-closed behavior, and existing adjacent Delta contracts passed.
  implication: the RED tests reproduce each root-cause mechanism directly without RSS thresholds and protect the required order, idempotency, immutability, empty-target, and corruption boundaries.

- timestamp: 2026-09-09T19:14:00.000+08:00
  checked: continuation scope, worktree, and project skills
  found: `.planning/STATE.md` still identifies 03.1-19 as the next active plan; only `tests/test_delta_tables.py` and the 31-line ordering addition in `tests/test_fabric_sync_service.py` belong to this debug cycle, while all listed Data Agent, Gold-grounding, and `.azure` changes remain unrelated and unstaged. No additional debugger agent skill is configured; the repository `gsd-debug` skill delegates to this persistent scientific workflow.
  implication: GREEN may modify only `src/storage/delta_writer.py` plus the already-authored scoped regression tests and debug state, and must use path-specific staging later.

- timestamp: 2026-09-09T19:14:00.000+08:00
  checked: complete DeltaWriter and RED test implementation
  found: non-APPEND modes share `_write_once`, while APPEND can be safely routed before full normalization; the RED oracle observes `dict(row)` copies via `Mapping.keys()`, Arrow/write batch sizes, filtered target reads, valid-empty behavior, conflict-before-write ordering, and partial-chunk retry result counts.
  implication: the minimal design is an APPEND-specific two-pass flow: validate all immutable conflicts in bounded key batches before any write, then copy and write one bounded first-occurrence batch at a time with retry-time target revalidation.

- timestamp: 2026-09-09T19:18:00.000+08:00
  checked: pinned deltalake 1.6.2 filtered-read behavior
  found: local temporary-table probes returned only requested rows for a single-column `in` predicate and exact composite DNF predicates; `DeltaTable.to_pyarrow_table` accepts a `filters` argument and `count()` is available. The short probe printed correct results but retained Arrow worker state at process exit and was terminated after bounded observation.
  implication: production APPEND can issue non-null exact incoming-key filters without a full target read; the writer should keep each predicate batch bounded and continue using the existing Delta API for local/remote parity.

- timestamp: 2026-09-09T19:22:00.000+08:00
  checked: first GREEN implementation pass
  found: APPEND now bypasses full normalization, validates all immutable conflicts before writes, revalidates each chunk on retry, skips valid-empty reads via `count()`, and creates at most one configured-size Arrow table; review caught an unnecessary whole-input `index_batches` container before tests.
  implication: remove that metadata accumulation now so the implementation matches the intended bounded materialization design rather than merely satisfying the RED spies.

- timestamp: 2026-09-09T19:25:00.000+08:00
  checked: exact four previously failing GREEN constraints
  found: all six parametrized test cases passed. N-1/N/N+1 emitted bounded batches, valid-empty APPEND performed no target row scan, existing-target reads carried filters, and partial-chunk retry produced the required idempotent write sequence.
  implication: the minimal runtime change directly reverses every RED observation; adjacent contract tests and static review are now required before acceptance.

- timestamp: 2026-09-09T19:28:00.000+08:00
  checked: complete GREEN source and targeted diff
  found: the old unfiltered APPEND target scan and dead unbounded APPEND route are removed; only filtered target materialization and one chunk Arrow construction remain. Review found `_validate_columns(rows[1:])` still creates a shallow whole-input reference slice and identified schema inference across chunks as the next compatibility risk to check.
  implication: eliminate the slice before claiming bounded behavior and verify caller/test schema semantics before broad acceptance.

- timestamp: 2026-09-09T19:31:00.000+08:00
  checked: full Delta module and APPEND caller audit
  found: all 25 Delta writer tests passed after validation was made index-iterative. The production `FabricSyncService.write_table` passes `schema_for(table_name)` for every table, including the 154k-row temporal APPEND; direct audit and specialized pipeline writers use small batches or their own registry schemas.
  implication: the production fix does not rely on cross-chunk Arrow inference, and the complete adjacent writer contract remains green; table-start observability is the remaining scoped implementation decision.

- timestamp: 2026-09-09T19:34:00.000+08:00
  checked: normal publication executor and progress contracts
  found: completion progress is emitted only after `future.result()` returns, so an exit during a table write identifies only the prior completed table. The stage callback intentionally permits no table payload, while `write_table` has the internal allowlisted table name and exact row count before any version lookup or Delta call.
  implication: a fixed-message INFO record with structured `table_name` and bounded `row_count` is materially diagnostic and avoids expanding callback/API contracts or exposing row content.

- timestamp: 2026-09-09T19:36:00.000+08:00
  checked: table-start observability implementation
  found: `FabricSyncService.write_table` now emits fixed message `fabric_table_write_started` with only structured internal `table_name` and bounded `row_count` before URI/version/Delta work; the existing completion-order test now checks start-record coverage and count bounds.
  implication: a future abrupt death can identify `silver_exposure_observations` and its input size directly while preserving best-effort completion callbacks and publication ordering.

- timestamp: 2026-09-09T19:38:00.000+08:00
  checked: focused publication tests and first scoped Ruff run
  found: both the completion/start-record test and deterministic workload-checkpoint-to-observation successor test passed. Ruff found one B023 warning because the retry lambda closes over loop variable `batch`, even though `_retry` executes synchronously.
  implication: runtime behavior is currently deterministic, but explicitly bind the batch in the closure to remove future refactor risk and satisfy the static gate.

- timestamp: 2026-09-09T19:40:00.000+08:00
  checked: closure correction and static retry regression
  found: binding `batch=batch` removed Ruff B023; scoped Ruff is clean and the partial-chunk retry regression still passes with the exact idempotent sequence.
  implication: the scoped implementation now passes its static gate; exercise all APPEND callers and broader sync behavior next.

- timestamp: 2026-09-09T19:45:00.000+08:00
  checked: schema-less boundary probe and APPEND/publication import graph
  found: a bounded local two-chunk APPEND with an initially null optional field followed by a string value wrote and read both rows successfully. All 101 tests across Delta tables, audit APPEND, vulnerability publication, incremental sync, and Fabric sync passed.
  implication: both registry-schema production paths and the principal schema-less compatibility edge remain functional; proceed to full-suite verification.

- timestamp: 2026-09-09T19:52:00.000+08:00
  checked: complete backend pytest suite
  found: the full backend suite reached 100% with exit code 0; all tests passed except the repository's one expected skip, with only pre-existing FastAPI `on_event` deprecation warnings.
  implication: no backend regression is observable across the complete repository; static and causality guardrails remain.

- timestamp: 2026-09-09T19:55:00.000+08:00
  checked: test collection, full Ruff, and scoped diff hygiene
  found: exactly 4038 tests collect, so the full run was 4037 passed and 1 skipped. Repository-wide Ruff reports 27 pre-existing violations confined to unrelated `infra/scripts/*` and `scripts/*`; scoped Ruff for all four changed files passes, and scoped `git diff --check` passes.
  implication: the fix itself is lint/whitespace clean; frozen unrelated lint debt must not be edited and is a disclosed repository-wide gate limitation rather than evidence against this change.

- timestamp: 2026-09-09T20:00:00.000+08:00
  checked: revert-and-reconfirm causality guardrail
  found: path-specific stashing removed only `src/storage/delta_writer.py` and `src/fabric/sync_service.py`. With regression tests retained, the unchanged baseline produced the original four APPEND failures plus the missing start-log failure (2 boundary neighbors still passed); after popping that exact stash, all 7 selected cases passed.
  implication: the runtime changes, not an environmental or unrelated worktree change, are necessary and sufficient for the specified GREEN behavior.

- timestamp: 2026-09-09T20:03:00.000+08:00
  checked: mutation tooling, package build, and stash/worktree hygiene
  found: no Python mutation framework or Stryker configuration exists, so automated mutation scoring is unavailable and must be recorded as skipped; revert-and-reconfirm already killed the unchanged implementation. `uv build` successfully produced both sdist and wheel. The causality stash was dropped, the prior unrelated stash stack is intact, and only the four scoped files are changed for this fix.
  implication: build safety is proven locally and mutation degrades transparently; one real default-boundary replay and final review remain before the human checkpoint.

- timestamp: 2026-09-09T20:06:00.000+08:00
  checked: real default 10000-row boundary
  found: a 10001-row local APPEND added all rows across Delta versions 0 and 1; replay at the same configured boundary added zero, reported skipped, and retained an exact target count of 10001.
  implication: the actual default limit and pinned Delta filtered-read path work beyond the minimal N+1 test, including idempotent replay.

- timestamp: 2026-09-09T20:08:00.000+08:00
  checked: final deep review rubric over the four explicit files
  found: no correctness, security, secret, debug-artifact, or maintainability finding was identified. The required O(key cardinality) key-to-source-index map is the only whole-request metadata; row copies, target rows, predicates, and Arrow tables are batch-bounded. No independent-agent execution tool is available in this continuation, so review independence is explicitly degraded to a fresh rubric-based pass plus Ruff, full tests, and causality evidence.
  implication: no review blocker remains, but the lack of a separately instantiated reviewer and absence of production-scale cloud execution are disclosed limitations for human acceptance.

- timestamp: 2026-09-09T20:10:00.000+08:00
  checked: independent review rejection finding 1
  found: the reviewer reports that pinned deltalake 1.6.2 `count()` is approximate and may return zero for non-empty active files without `num_records`; both candidate APPEND validation gates currently use `table.count() > 0`.
  implication: treat valid-empty detection as untrusted until independently reproduced; if confirmed, active-file presence must replace row-statistics-based emptiness and receive a no-stat regression.

- timestamp: 2026-09-09T20:10:00.000+08:00
  checked: independent review rejection finding 2
  found: the reviewer reports that APPEND existence detection, DeltaTable construction, emptiness checks, and preflight filtered reads execute outside `_retry()`, whereas the pre-change operation retried the complete attempt.
  implication: compare old and candidate retry boundaries and add fail-once tests for existence lookup and filtered reads before revising the retry envelope.

- timestamp: 2026-09-09T20:14:00.000+08:00
  checked: complete current `DeltaWriter` APPEND control flow
  found: `_write_append` performs its initial `exists()`, `DeltaTable(...)`, `table.count()`, all-key filtered validation, and initial `table.version()` before any `_retry()` call; `_write_append_chunk_once` performs its retry-time existence, construction, second `table.count()`, filtered deduplication, write, and final table construction inside a per-chunk `_retry()`.
  implication: finding 2 is confirmed for the mandatory conflict-before-first-write preflight, while per-chunk retry-time operations are already bounded; the correction must retry preflight without moving conflict detection after writes or reverting to whole-input materialization.

- timestamp: 2026-09-09T20:14:00.000+08:00
  checked: both candidate APPEND emptiness gates
  found: the all-key preflight at line 146 and retry-time chunk deduplication at line 222 condition filtered reads on `table.count() > 0`.
  implication: finding 1 affects both immutable-conflict refusal and replay deduplication if pinned Delta can expose active files without row-count statistics.

- timestamp: 2026-09-09T20:18:00.000+08:00
  checked: pinned deltalake 1.6.2 no-stat active-file probe
  found: after removing only `stats` from a one-row Delta add action, `get_add_actions(flatten=True)` reported one action, `file_uris()` reported one active file, the table remained readable with one row, and `count()` returned zero.
  implication: finding 1 is directly reproduced; row-count statistics cannot be used as an emptiness gate, while active-file presence distinguishes this table from a schema-valid empty target.

- timestamp: 2026-09-09T20:18:00.000+08:00
  checked: baseline retry boundary at repository HEAD
  found: before the bounded candidate, `write()` passed the complete `_write_once` operation to `_retry()`, so APPEND existence lookup, table construction, and target reads all inherited bounded retry handling.
  implication: finding 2 is a candidate regression; the revised chunked design must add a bounded retry around the all-key preflight while retaining per-chunk retries after partial commits.

- timestamp: 2026-09-09T20:22:00.000+08:00
  checked: TDD RED for independent-review findings
  found: all four focused regressions failed against the unchanged first candidate. A no-stat conflicting row did not raise, a no-stat identical replay produced a duplicate, fail-once `exists()` propagated its OSError, and fail-once filtered preflight read propagated its OSError.
  implication: both findings are behaviorally reproduced with specified state/result oracles; the proposed active-file and retry-envelope changes are required rather than speculative.

- timestamp: 2026-09-09T20:25:00.000+08:00
  checked: minimal review-finding correction
  found: both APPEND gates now use the pinned table's active file URI view; the all-key conflict preflight is a single retryable operation returning the initial version; per-chunk retry-time deduplication remains unchanged except for the active-file predicate; `_retry` is type-generalized without changing behavior.
  implication: the implementation addresses the two reproduced causes without restoring whole-target reads, moving conflict checks after commits, or widening scope beyond the existing Delta writer.

- timestamp: 2026-09-09T20:27:00.000+08:00
  checked: focused GREEN for independent-review findings
  found: all four exact RED regressions now pass: no-stat immutable mutation is rejected, no-stat replay is deduplicated, and fail-once existence and filtered-preflight errors each recover through bounded retry.
  implication: the minimal runtime revision directly reverses all four independently reproduced failures; adjacent and guardrail verification can proceed.

- timestamp: 2026-09-09T20:30:00.000+08:00
  checked: complete Delta writer module and scoped static gates after review correction
  found: all 29 Delta writer tests pass; Ruff reports no issue in the revised writer/test files; scoped `git diff --check` passes. The total four-file candidate remains isolated from protected paths.
  implication: active-file/no-stat and retry corrections preserve the existing valid-empty, bounded batching, conflict-before-write, partial-retry, malformed-log, and non-APPEND contracts at module scope.

- timestamp: 2026-09-09T20:34:00.000+08:00
  checked: fresh scoped diff review and five-suite APPEND import graph
  found: all adjacent Delta, audit, vulnerability, incremental-sync, and Fabric-sync tests pass. Every APPEND target interaction is now in retryable preflight or per-chunk retry, and APPEND contains no `count()` gate. Review found one duplicated `wrote_chunk = False` assignment with no behavioral effect.
  implication: retry and active-file coverage is structurally complete; remove the duplicate assignment before final verification to keep the candidate minimal.

- timestamp: 2026-09-09T20:37:00.000+08:00
  checked: post-review cleanup regression
  found: the duplicate no-op assignment was removed and all four independent-review regressions still pass.
  implication: the candidate is minimal at the corrected site and ready for complete backend verification.

- timestamp: 2026-09-09T20:45:00.000+08:00
  checked: complete backend suite after independent-review corrections
  found: the full pytest run reached 100% with exit code 0 and only the repository's expected skip plus pre-existing FastAPI `on_event` deprecation warnings.
  implication: no backend regression is observable; exact collection count and causality guardrail remain before acceptance.

- timestamp: 2026-09-09T20:48:00.000+08:00
  checked: pre-causality worktree and stash hygiene
  found: the only runtime paths selected for revert are the scoped `src/storage/delta_writer.py` and `src/fabric/sync_service.py`; regression tests remain unstashed, protected Data Agent/Gold/`.azure` work remains dirty but excluded, and the existing top stash is `preserve remaining exposure split-view files before PR20 build`.
  implication: a named path-specific stash can test causality without altering unrelated work or losing track of the prior stash stack.

- timestamp: 2026-09-09T20:53:00.000+08:00
  checked: first whole-runtime causality revert with all tests retained
  found: repository HEAD restored the four original APPEND failures and missing table-start log while the two N-1/N boundary neighbors passed. The no-stat tests passed because the old implementation always scanned the full target, and the existence retry recovered in two calls rather than the candidate's three-call structure.
  implication: the total candidate remains causal for the original defect, but correction-specific causality must compare against the rejected first GREEN rather than HEAD; exact call-count three is an over-specific test oracle and must become a minimum retry assertion.

- timestamp: 2026-09-09T20:57:00.000+08:00
  checked: causality restoration and retry-oracle hardening
  found: the named runtime stash restored both scoped source files cleanly and was dropped without disturbing the prior stash stack. Retry assertions now require at least one retry rather than the candidate-specific total of three calls, and all four review regressions pass.
  implication: the specified oracle verifies recovery and correctness without overfitting internal call structure; final target/static/build checks can proceed.

- timestamp: 2026-09-09T21:01:00.000+08:00
  checked: final selected causality, static, and build gates
  found: all 11 selected cases pass on the restored final runtime; scoped Ruff and `git diff --check` pass; `uv build` produced both sdist and wheel. A summary-text grep did not yield a collection count, so no count is inferred from that command.
  implication: target, no-op/static, adjacent-causality, and build signals are green; one final full-suite replay and explicit node-ID count remain.

- timestamp: 2026-09-09T21:10:00.000+08:00
  checked: final complete backend replay and exact collection count
  found: 4042 tests collect; the final suite completed at 100% with 4041 passing and one expected skip, with only pre-existing FastAPI `on_event` deprecation warnings.
  implication: the four new regressions account exactly for the increase from the first candidate's 4038 tests, and the final corrected runtime has no observable backend regression.

- timestamp: 2026-09-09T21:14:00.000+08:00
  checked: final corrected-source and scoped-worktree review
  found: APPEND has no `count()` gate; active-file detection uses `file_uris()` at both validation points; initial existence, table construction, active-file inspection, filtered reads, and version lookup all execute inside the retryable preflight; per-chunk operations remain inside their own retry; the two retry regressions assert recovery rather than an exact internal call count. Scoped diff checks name only the intended four files, while all protected dirty paths remain excluded.
  implication: both independent-review findings are corrected without weakening immutable APPEND semantics, reintroducing target-row scans, or touching unrelated work.

- timestamp: 2026-09-09T19:37:56.021+08:00
  checked: independent review rejection round 2 and active phase scope
  found: "The reviewer independently reproduced two deterministic defects in the corrected candidate: earlier chunks remain committed after a later permanent failure, and commit-then-error retry reports zero added/skipped despite this invocation committing a row. `.planning/STATE.md` still identifies Phase 03.1 Plan 19 as the active blocked plan; protected Data Agent, Gold-grounding, and `.azure` files remain outside the four-file diff."
  implication: "Reopen investigation in the existing session. Preserve the active-file/preflight corrections, bounded memory, immutable conflict behavior, and four-file scope while adding direct regressions for method-level atomicity and truthful retry accounting."

- timestamp: 2026-09-09T19:45:00.000+08:00
  checked: complete current DeltaWriter APPEND implementation, existing regressions, and pinned API signatures
  found: "`_write_append` calls `_retry(_write_append_chunk_once)` once per configured-size chunk; `_write_append_chunk_once` creates one Arrow table and invokes `write_deltalake` immediately, so each chunk is a separate visible transaction. `rows_added` and `wrote_chunk` are accumulated only from returned retry results, so an exception raised after commit discards that attempt's contribution and the deduplicating retry returns zero/skipped. Pinned deltalake 1.6.2 accepts Arrow stream exports and `CommitProperties(custom_metadata=...)`; PyArrow exposes `RecordBatchReader.from_batches(schema, batches)`."
  implication: "Both round-2 findings follow directly from deterministic control flow. A one-call lazy RecordBatchReader is a viable atomicity candidate, while commit metadata may provide reliable attribution after an ambiguous post-commit exception; both need direct local probes before test/fix design."

- timestamp: 2026-09-09T19:52:00.000+08:00
  checked: pinned deltalake 1.6.2 lazy-stream transaction probe, commit history, schema unification, and FabricSyncService rollback boundary
  found: "A `RecordBatchReader` yielded one batch and then raised; `write_deltalake` raised `DeltaError` and created no Delta transaction. A successful three-batch reader produced exactly one version containing all six rows. `CommitProperties(custom_metadata={...})` surfaced the invocation marker in `DeltaTable.history(limit=1)`. `pa.unify_schemas` unified null-to-string and additive-field batch schemas. FabricSyncService records `written_versions` only after `DeltaWriter.write` returns, so it cannot register or restore chunks committed before that call raises."
  implication: "The root causes are confirmed and the alternatives are differentiated. One lazy bounded Arrow stream per APPEND invocation supplies transaction atomicity; a stable per-invocation commit marker supplies reliable post-commit retry attribution. Tests must first reproduce both defects against the unchanged candidate."

- timestamp: 2026-09-09T20:00:00.000+08:00
  checked: round-2 TDD RED regressions against the unchanged corrected candidate
  found: "Both focused tests failed with the predicted specified-oracle states. At N+1 with batch size 2, a materialization exception left the first two incoming rows committed and advanced the existing table from version 0 to 1. A write that committed version 0 and then raised OSError retried as a deduplicated skip and returned rows_added=0/skipped=True."
  implication: "The reviewer findings are independently and deterministically reproduced. Root cause is confirmed; proceed with the one-transaction bounded-stream and invocation-marker correction."

- timestamp: 2026-09-09T20:08:00.000+08:00
  checked: exact round-2 GREEN regressions
  found: "Both tests pass after the minimal writer refactor. An exception while materializing batch N+1 leaves the existing table at its original version with only its original row, and a one-row commit followed by OSError is recovered from invocation-marked history as rows_added=1/skipped=False/version=0 with one physical write."
  implication: "The implementation directly reverses both RED observations. Module-wide compatibility, static checks, adjacent suites, mutation degradation, and revert/reapply causality remain required."

- timestamp: 2026-09-09T20:12:00.000+08:00
  checked: complete Delta writer module, scoped Ruff, and scoped whitespace
  found: "All 31 tests in tests/test_delta_tables.py pass. Ruff reports all checks passed for the writer and tests, and `git diff --check` is clean across the four scoped files."
  implication: "The new atomicity/accounting behavior preserves module-level active-file, immutable conflict, retry, valid-empty, malformed-log, schema-less, merge, overwrite, and historical-read contracts; fresh source review and adjacent suites remain."

- timestamp: 2026-09-09T20:18:00.000+08:00
  checked: complete revised source/diff and local compatibility probes
  found: "Fresh review finds one `write_deltalake` call fed by lazy RecordBatches, with no per-batch transaction and no full target scan. A schema-less three-row N+1 append unified first-batch nulls with a later string and committed all rows at version 0; empty APPEND with explicit schema created a valid zero-row version 0; a 10001-row default-boundary append committed all rows in version 0 and identical replay remained at version 0 with rows_added=0/skipped=True."
  implication: "Atomic streaming preserves the key schema-less, empty-table, default-boundary, and replay contracts. Persist the newly touched schema/empty compatibility as held-out tests before broader verification."

- timestamp: 2026-09-09T20:21:00.000+08:00
  checked: Delta module after adding held-out schema-less and empty-table tests
  found: "The empty-table test and all prior tests passed. The schema-less test observed all expected values and three added rows, but failed because it asserted physical Delta row order (`later, null, null` versus input order), which Delta does not guarantee."
  implication: "This is a test-oracle defect, not a runtime regression. Compare optional values by the immutable resource_id key and retain exact count/version assertions."

- timestamp: 2026-09-09T20:24:00.000+08:00
  checked: corrected held-out compatibility tests and complete Delta module
  found: "All 33 Delta writer tests pass. Schema-less N+1 unification is asserted by resource key rather than physical order, and empty explicit-schema APPEND creates a valid zero-row version with skipped=False."
  implication: "The atomic stream preserves newly touched compatibility boundaries; proceed to adjacent caller suites."

- timestamp: 2026-09-09T20:29:00.000+08:00
  checked: five-suite APPEND/publication import graph
  found: "All tests pass across tests/test_delta_tables.py, tests/test_situations_audit.py, tests/test_vulnerability_pipeline.py, tests/test_incremental_sync.py, and tests/test_fabric_sync_service.py."
  implication: "No adjacent regression is observed in audit writers, temporal publication, incremental sync, Fabric table progress, or publication rollback. Run path-specific causality next."

- timestamp: 2026-09-09T20:37:00.000+08:00
  checked: path-specific revert-and-reconfirm causality
  found: "Only src/storage/delta_writer.py was stashed; regression tests and all protected dirty files remained in place. Repository HEAD reproduced commit-then-error rows_added=0 exactly and lacked the bounded-batch constructor needed by the atomic N+1 test. The same session had already run both tests RED against the rejected corrected candidate immediately before implementation. Popping and dropping the exact named stash restored the runtime; both round-2 tests then passed. The pre-existing stash head returned unchanged."
  implication: "The round-2 runtime refactor is causal, and restoration/worktree hygiene is intact. Combined exact pre-fix RED plus post-restore GREEN satisfies causality despite repository HEAD predating the entire bounded-batch API."

- timestamp: 2026-09-09T20:47:00.000+08:00
  checked: complete backend regression suite after round-2 correction
  found: "The full pytest run reached 100% with exit code 0 and one expected skip; only the pre-existing FastAPI `on_event` deprecation warnings were emitted."
  implication: "No repository-wide backend regression is observable. Exact collection count and remaining static/build/review signals are still required."

- timestamp: 2026-09-09T20:55:00.000+08:00
  checked: final build, test collection, static checks, mutation availability, and worktree scope
  found: "The build produced both sdist and wheel; 4046 backend tests collect; scoped Ruff and diff whitespace checks pass. Repository-wide Ruff retains the same 27 unrelated violations in infra/scripts and scripts. No Python mutation framework or Stryker configuration is present. The scoped diff names exactly the intended four files, protected dirty paths are unchanged, and the pre-existing stash head is restored."
  implication: "All applicable acceptance signals pass or degrade explicitly. Before checkpoint, strengthen the atomic failure regression to cover the reviewer's exact absent-target version-0 case in addition to the existing-target rollback boundary."

- timestamp: 2026-09-09T20:59:00.000+08:00
  checked: hardened absent/present atomicity boundary and focused static checks
  found: "All three selected cases pass: later N+1 materialization failure creates no Delta table from an absent target and leaves a present target's version/rows unchanged; commit-then-error accounting remains truthful. Scoped Ruff and diff whitespace are clean."
  implication: "The regression now directly covers the reviewer's exact absent-target partial-publication scenario and the adjacent existing-target rollback boundary. Replay the full suite once after this final test-only change."

- timestamp: 2026-09-09T21:08:00.000+08:00
  checked: final post-hardening full suite, collection count, guardrail synthesis, and scoped worktree
  found: "The final backend suite completed at 100% with exit code 0; 4047 tests collect, yielding 4046 passes and one expected skip. The two atomicity boundary cases plus commit-then-error accounting pass, scoped Ruff/diff checks pass, build artifacts succeed, the four-file diff remains isolated, and protected paths/stashes are unchanged."
  implication: "All applicable automated guardrail signals accept the round-2 correction. Cloud execution remains unauthorized and unverified, so the session returns to human/independent-review checkpoint rather than being archived or committed."

- timestamp: 2026-09-09T20:08:00.000+08:00
  checked: human verification checkpoint
  found: "The user explicitly responded `confirmed fixed` and authorized only atomic scoped code/test and debug-document commits with the repository-required coauthor trailer, with no push, cloud mutation, or protected Data Agent/Gold-grounding/`.azure` changes."
  implication: "The fix is end-to-end accepted for this debug cycle and the session may be resolved, archived, and recorded in the durable prevention knowledge base."

## Resolution

root_cause: "Original failure: `DeltaWriter` APPEND eagerly duplicated the complete input, created one full Arrow table, and converted the complete target to Python rows; the approximately 154k-row first temporal APPEND with approximately 1.9 GiB cgroup headroom triggered deterministic OOM. First-review defects: approximate `DeltaTable.count()` was used as authoritative emptiness and mandatory preflight escaped `_retry()`. Round-2 defects: bounded chunks were committed as independent Delta transactions, so later failure exposed a partial invocation that FabricSyncService could not register for rollback; retry results represented only the final attempt, so a successful commit followed by a transient exception was misreported as rows_added=0/skipped=True."
fix: "APPEND now preflights immutable conflicts through bounded key filters, derives only missing source indices, and supplies lazily materialized configured-size RecordBatches to one `write_deltalake` transaction. Each attempted transaction carries a unique invocation ID and added-row count in Delta commit metadata; retries search bounded recent history for that marker before deduplication, recovering the actual committed version/count after a post-commit exception."
verification:
  target_test:
    result: pass
    detail: "Both new round-2 regressions pass: later N+1 batch failure creates no absent target and leaves a present target unchanged, while commit-then-error returns rows_added=1/skipped=False/version=0 from one physical commit. All prior no-stat/preflight regressions and the real 10001-row default-boundary append/replay also pass."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker or Python mutation framework is configured; exact pre-fix RED plus path-specific revert/reapply testing supplies the available causality signal."
    mutant_killed:
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: true
    detail: "Per-chunk commit behavior is replaced by one lazy bounded stream/transaction and durable retry attribution; behavior is not deleted or short-circuited."
  adjacent_tests:
    result: pass
    suites_run:
      - tests/test_delta_tables.py
      - tests/test_situations_audit.py
      - tests/test_vulnerability_pipeline.py
      - tests/test_incremental_sync.py
      - tests/test_fabric_sync_service.py
      - full backend suite
    detail: "All five adjacent suites pass; final full suite: 4046 passed, 1 skipped from 4047 collected."
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    detail: "Both round-2 tests were exact RED on the rejected corrected candidate and GREEN after implementation. A later path-specific stash of only the writer restored HEAD's commit-then-error undercount (HEAD predates the bounded-batch constructor), and exact stash restoration returned all three hardened cases to GREEN without disturbing protected work or prior stashes."
  lint:
    scoped: "pass — Ruff and git diff --check on all four changed files"
    repository: "limited — 27 pre-existing violations only in unrelated infra/scripts and scripts files"
  build:
    result: pass
    detail: "uv build produced sdist and wheel."
  review:
    result: pass_after_correction
    detail: "Both round-2 findings were reproduced, corrected, and covered. Final line-by-line review finds one Delta transaction consuming bounded RecordBatches, bounded filtered target reads, complete retryable immutable preflight, and invocation-marked recovery before retry deduplication. A separately instantiated reviewer remains the requested human checkpoint."
  guardrail_verdict: accepted
human_verification:
  result: confirmed_fixed
  timestamp: 2026-09-09T20:08:00.000+08:00
  detail: "The user confirmed the corrected four-file candidate resolves the reported issue and authorized scoped local commits only."
code_commit: 340cb9ddb3e46586651008033b9c6fb9e451e44b
falsified_alternatives:
  - "Concurrent writer amplification: isolated writer, exclusive lease, deployed write_workers=1."
  - "Recent publication atomicity repair regression: unbounded paths predate that repair."
  - "Cumulative leak across tables 1-53: memory remained flat until the first large temporal APPEND boundary."
remaining_risk:
  - "No 8 GiB production container/Fabric run was authorized, so exact peak RSS and cloud filter behavior remain end-to-end unverified."
  - "The temporal projection caller still materializes prior observation history independently; this fix removes the redundant writer-side scan only."
  - "Pinned deltalake 1.6.2 local tests prove lazy-stream transaction behavior and commit metadata recovery; remote OneLake behavior remains unexercised."
  - "Commit recovery scans the latest 32 history entries by an unguessable invocation ID; production's exclusive publication lease prevents same-table commits from displacing that marker during the immediate retry window."
  - "Filtered reads fail closed for matching missing/corrupt files but do not validate unrelated pruned target files."
prevention: "Specified regressions enforce N-1/N/N+1 bounded RecordBatches in one transaction, absent/present target atomicity on later batch failure, truthful commit-then-error result recovery, schema-less cross-batch unification, empty-schema table creation, valid-empty no-scan behavior, active-file handling without row statistics, filtered target access, conflict-before-write, fail-once preflight retries, malformed-log fail-closed handling, deterministic table ordering, and table-start diagnostics."
oracle_type: specified
investigation_cycles: 1
fix_cycles: 3
files_changed:
  - src/storage/delta_writer.py
  - src/fabric/sync_service.py
  - tests/test_delta_tables.py
  - tests/test_fabric_sync_service.py

## Prevention

blameless_5_whys:
  code_branch:
    - "The publication process was killed because APPEND duplicated the complete incoming collection, materialized one full Arrow table, and converted the complete target to Python rows."
    - "Those source- and target-sized allocations existed because APPEND reused a small-table implementation with no enforced materialization bound."
    - "The first bounded correction still exposed partial results because each chunk was mapped to a separate Delta transaction rather than treating one writer invocation as the atomic unit."
    - "A commit followed by a transient exception was misreported because retry accounting described only the final attempt and the transaction carried no invocation identity that could prove an earlier attempt committed."
    - "The actionable condition was the absence of a method-level contract requiring bounded batches inside one transaction plus durable attribution for ambiguous commit outcomes."
  data_environment_branch:
    - "The latent allocation defect became fatal when the first temporal APPEND supplied approximately 154000 rows while the deployed process had approximately 1.9 GiB cgroup headroom."
    - "The partial-publication and accounting windows required multi-batch input with a later materialization/storage failure, or a successful Delta commit followed by a transient transport/storage exception."
    - "These are valid production-scale and failure-mode conditions, so the implementation must remain bounded and correct rather than relying on smaller data, more memory, or failure-free storage."
  and_gate: "Yes: the original OOM required the unbounded code path plus production-scale data and constrained headroom; the two atomicity/accounting manifestations each required the corresponding code defect plus a later-batch or post-commit failure window."
why_not_caught: "The existing test/verify gate exercised only small APPENDs, happy-path idempotency, and caught publication exceptions. It did not assert N-1/N/N+1 materialization bounds, one transaction across multiple batches, absent/present target atomicity after a later batch failure, post-commit retry attribution, active files without row statistics, or complete preflight retry coverage."
recurrence_guard: "Specified regressions in `tests/test_delta_tables.py` — `test_delta_writer_append_bounds_python_and_arrow_materialization`, `test_delta_writer_append_is_atomic_when_later_batch_materialization_fails`, `test_delta_writer_append_reports_commit_that_raised_transient_error`, `test_delta_writer_append_rejects_conflict_when_active_file_lacks_statistics`, `test_delta_writer_append_deduplicates_active_file_without_statistics`, and both transient-preflight retry tests — lock the bounded, atomic, immutable, and truthfully attributed APPEND contract. `tests/test_fabric_sync_service.py::test_deployed_publication_orders_observations_after_workload_checkpoint` and `::test_sync_reports_successful_table_writes_in_completion_order` lock the table-54 ordering evidence and sanitized table-start diagnostic."
