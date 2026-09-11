---
status: resolved
trigger: "Corrected execution aiops-dev-exposure-publication-j40c4yc passed ontology validation and completed 53/458 tables, then exited 137 while entering the 151,561-row silver_container_vulnerability_observations APPEND preflight."
created: 2026-09-10T01:30:00+08:00
updated: 2026-09-10T02:32:00+08:00
---

## Current Focus

hypothesis: confirmed — replay-aware APPEND comparison has only a 10,000-row limit, so high-byte container source payloads make the filtered Arrow/Python/canonicalization working set exceed the 8 GiB job's remaining headroom
known_pattern_candidate: phase031-plan19-delta-append-memory and exposure-observation-mutation — the current failure enters the bounded APPEND preflight added by the former with the replay canonicalization added by the latter
bug_class: heisenbug-mandelbug
test: TDD RED/GREEN, boundary, adjacent, full-suite, revert-and-reconfirm, and local human verification all pass
expecting: the later authorized controlled immutable build/deploy/retry supplies the intentionally deferred production-scale 4 CPU / 8 GiB evidence
next_action: archived locally with durable knowledge-base fallback; do not perform cloud operations from this debug session
reasoning_checkpoint:
  hypothesis: "DeltaWriter groups replay comparison solely by append_batch_size=10000; because container observations retain large source_event_payload_json and provenance_json as immutable semantics, one filtered target read plus to_pylist and dual canonical JSON construction creates a payload-proportional transient working set that crosses the job's roughly 1.5 GiB remaining headroom."
  confirming_evidence:
    - "The live process exited 137 inside the first unresolved 151561-row container observation write after an observed 6.54 GiB peak under an 8 GiB limit."
    - "Complete source inspection shows one row-count-only batch owns incoming references, filter values, the filtered Arrow table, all converted Python rows, and canonical JSON copies."
    - "The agent-authored minimal RED test sets a one-byte preflight budget but observes one two-key target materialization, proving payload bytes currently do not constrain the comparison batch."
  falsification_test: "The hypothesis is false if current code keeps every target-comparison request within the configured payload-byte budget (except one indivisible oversized row), or if the live failure occurs without entering this allocation path."
  fix_rationale: "Batch the same immutable comparisons by a conservative per-row byte estimate in addition to the existing row ceiling; this directly caps each target materialization without removing semantic fields or weakening conflict detection."
  blind_spots: "Local Delta cannot reproduce the exact OneLake/Rust allocator peak or production source-payload distribution; remote end-to-end verification still requires an authorized image build and job retry."
  candidate_causes:
    - "code: APPEND preflight limits row count but has no payload-byte limit"
    - "data: container observations retain comparatively large source event and provenance JSON strings"
    - "environment: 8 GiB cgroup has only roughly 1.5 GiB free when table 54 starts"
    - "config: append_batch_size remains the generic 10000-row default for this high-payload table"
  and_gate: "yes — the fatal kill requires the unbounded-by-byte code path together with high-byte replay data and limited cgroup headroom; none alone explains exit 137"
tdd_checkpoint:
  test_file: tests/test_delta_tables.py
  test_name: test_delta_writer_append_bounds_replay_preflight_by_payload_bytes
  status: green
  failure_output: "assert [2] == [1, 1]; current preflight issued one filtered comparison for both 1024-byte-payload replay rows despite append_preflight_batch_bytes=1"

## Symptoms

expected: after unchanged cross-generation container observations are canonicalized, the 151,561-row APPEND preflight deduplicates existing immutable events and publication proceeds past table 54
actual: execution completes 53 earlier tables, then the container exits 137 before any completion event for silver_container_vulnerability_observations
errors: Azure Container Apps system log reports exit code 137; no application exception or failed ingestion-state row is persisted
reproduction: run the corrected image sha256:57392a48f00789d24f8286e377dd7cbd03d67bacbc86112c299dd493085da734 against the live 151,561-row container observation projection in a 4 CPU / 8 GiB Job
started: first full-cardinality live run after commit 1361b1c42 removed the earlier immutable replay conflict

## Eliminated

- hypothesis: Fabric capacity suspension caused the resumed failure.
  evidence: ARM and Fabric control planes remained Active; activity log contains only the successful user resume at 16:41:32Z and no later suspension.
  timestamp: 2026-09-10T01:30:00+08:00

- hypothesis: ontology validation or graph bounds failed.
  evidence: ontology validation completed in 45.3 seconds with zero failures before table publication began.
  timestamp: 2026-09-10T01:30:00+08:00

- hypothesis: the original silver_exposure_observations bounded APPEND regressed.
  evidence: the process died after table 53, before either large observation table emitted completion; dataset ordering and the prior run identify silver_container_vulnerability_observations as the first unresolved future.
  timestamp: 2026-09-10T01:30:00+08:00

## Evidence

- timestamp: 2026-09-10T01:30:00+08:00
  checked: corrected live execution structured progress
  found: tables 1-53 completed; table 53 was metadata_workload_source_checkpoints and no later table completion was emitted
  implication: the hard process death occurred inside the next serialized table write

- timestamp: 2026-09-10T01:30:00+08:00
  checked: source dataset cardinality and preceding failed run
  found: silver_container_vulnerability_observations contains 151,561 rows; before replay canonicalization this same future failed early with one immutable conflict and the executor later drained the remaining queued tables
  implication: the corrected run is the first one to execute the entire existing-row comparison for this high-cardinality table

- timestamp: 2026-09-10T01:30:00+08:00
  checked: Azure Container Apps system logs and metrics
  found: exit code 137, zero restarts, observed peak 6.54 GiB before the unobserved kill spike, with an 8 GiB cgroup limit
  implication: a transient allocation above roughly 1.5 GiB caused the kill

- timestamp: 2026-09-10T01:30:00+08:00
  checked: DeltaWriter replay preflight
  found: each 10,000-row batch builds incoming key/reference structures, materializes filtered existing rows through Arrow and Python, then constructs replay-filtered dictionaries and canonical JSON strings for both sides
  implication: row-count bounding alone does not bound memory for large provenance payloads

- timestamp: 2026-09-10T01:30:00+08:00
  checked: publication safety state
  found: Gold pointer remains absent, Job contract restoration hash matches exactly, and competing ontology schedule remains dormant
  implication: diagnosis and local fix can proceed without live-state repair or another retry

- timestamp: 2026-09-10T01:30:49.362+08:00
  checked: active planning scope in .planning/STATE.md
  found: Phase 03.1 Exposure Reliability and Scale is active and Plan 03.1-19 remains blocked on exact live publication evidence
  implication: diagnosing and fixing the container observation publication failure is within the active phase scope

- timestamp: 2026-09-10T01:30:49.362+08:00
  checked: durable debug knowledge base
  found: exact related patterns exist for the earlier full-input Delta APPEND OOM and for cross-generation container replay canonicalization; the present failure is the first production-scale intersection of those two paths
  implication: treat their interaction as the leading candidate, but reproduce its memory behavior before confirming it

- timestamp: 2026-09-10T01:33:00+08:00
  checked: semantic knowledge-base recall
  found: MemPalace is not installed or configured, so recall degraded to the durable knowledge-base keyword/identifier match
  implication: the exact Delta APPEND and container replay entries remain hypothesis candidates rather than a diagnosis

- timestamp: 2026-09-10T01:33:00+08:00
  checked: complete DeltaWriter APPEND implementation
  found: each preflight batch is bounded only by append_batch_size=10000 and simultaneously holds an incoming row list, incoming-by-key dictionary, filter values, a filtered Arrow table converted wholesale to Python rows, two canonical content dictionaries, and two canonical JSON strings per compared row
  implication: the current bound controls row count but permits payload-dependent transient allocations large enough to exceed fixed container headroom

- timestamp: 2026-09-10T01:36:00+08:00
  checked: container APPEND schema and table-scoped replay policy
  found: every observation persists both source_event_payload_json and provenance_json; only timestamp/change_version/ingested_at plus nested provenance ingested_at are replay metadata, so the potentially large source event payload remains intentionally part of immutable comparison
  implication: reducing semantic comparison columns would violate the immutable event contract; comparison requests themselves need a payload-byte bound

- timestamp: 2026-09-10T01:36:00+08:00
  checked: Spectrum-based fault localization prerequisites
  found: no local failing test currently reproduces the production-scale payload-memory defect and no per-test pass/fail coverage spectrum exists
  implication: SBFL is skipped; TDD behavioral reproduction at DeltaWriter._validate_append_target is the deterministic fault-localization signal

- timestamp: 2026-09-10T01:36:00+08:00
  checked: taxonomy routing
  found: the kill depends on resource headroom and payload volume rather than interleaving; exact peak timing may vary but the allocation mechanism is deterministic
  implication: retain heisenbug-mandelbug classification for the environment-dependent OOM and use bounded resource-stress plus direct allocation-behavior assertions rather than flaky coverage

- timestamp: 2026-09-10T01:40:00+08:00
  checked: agent-authored minimized TDD reproduction
  found: RED — with two unchanged 1024-byte-payload replay rows, append_batch_size=10, and append_preflight_batch_bytes=1, DeltaWriter performs one two-key filtered target read; expected one indivisible row per comparison read
  implication: target comparison is directly proven to ignore payload bytes; two rows are the minimal counterexample because a singleton cannot demonstrate missing batch separation

- timestamp: 2026-09-10T01:44:00+08:00
  checked: active planning scope and skill bootstrap
  found: STATE keeps Phase 03.1 Exposure Reliability and Scale active with Plan 03.1-19 blocked on exact live publication evidence; no debugger agent skills are configured, while project skill indexes exist under .github/skills and .agents/skills
  implication: the GREEN fix remains in active scope; relevant project skill rules must be checked before production changes

- timestamp: 2026-09-10T01:46:00+08:00
  checked: project skill indexes and git worktree
  found: gsd-debug adds no production-code rules and archify is unrelated; the worktree contains numerous pre-existing modifications unrelated to this debug session, while the only session-authored change is the RED test in tests/test_delta_tables.py
  implication: constrain edits to DeltaWriter, its focused regression test, and the debug session file; do not overwrite or stage unrelated work

- timestamp: 2026-09-10T01:49:00+08:00
  checked: complete DeltaWriter implementation and adjacent tests
  found: both the no-write preflight and the append-attempt revalidation call _validate_append_target from _batched_indices(..., append_batch_size); no payload-byte option or estimator exists, and immutable comparison remains centralized in _canonical_row
  implication: add one shared byte-and-row bounded index iterator and use it at both validation call sites; do not remove source_event_payload_json, weaken canonical comparison, or bypass the conflict-before-first-write preflight

- timestamp: 2026-09-10T01:52:00+08:00
  checked: DeltaWriter history and constructor call sites
  found: commit 340cb9ddb intentionally made APPEND row-bounded, single-transaction, retry-accounted, and conflict-atomic; production call sites use default construction and expose no table-specific safe override
  implication: retain the row bound and transaction/retry design, add a safe default byte bound at DeltaWriter construction, and avoid relying on a deployment-only configuration change

- timestamp: 2026-09-10T01:55:00+08:00
  checked: prior durable RCA and all remaining DeltaWriter tests
  found: the prior guard explicitly requires N-1/N/N+1 materialization boundaries and full immutable preflight; exact container replay must continue comparing every provider-semantic field, and end-to-end cloud retry remains reserved for a later authorized controlled build/deploy phase
  implication: implement a local production default and boundary tests only; do not resize cloud resources, trigger a job, alter publication order, or exclude semantic payload columns

- timestamp: 2026-09-10T02:02:00+08:00
  checked: first focused GREEN test invocation
  found: pytest aborted before collection because globally auto-loaded Phoenix raises a Python 3.11 dataclass mappingproxy compatibility error
  implication: this is an unrelated test-environment plugin failure; rerun with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 so the project test itself can execute

- timestamp: 2026-09-10T02:04:00+08:00
  checked: isolated target and boundary regressions
  found: GREEN — the original one-byte test and all exact aggregate byte boundaries N-1, N, and N+1 pass (4 cases total)
  implication: the implementation now separates indivisible oversized rows and admits an exact-budget pair without weakening replay deduplication

- timestamp: 2026-09-10T02:07:00+08:00
  checked: exact fix diff and mutation-tool availability
  found: the production diff is additive and routes both existing comparison loops through the same bounded iterator; no branch, semantic field, conflict check, transaction, or assertion was deleted, and no Stryker or other mutation runner is configured
  implication: no-op/deletion signal passes; mutation signal must be explicitly skipped per guardrail degradation while exact-boundary tests still exercise the fix condition

- timestamp: 2026-09-10T02:10:00+08:00
  checked: adjacent tests and static lint
  found: all 38 tests in tests/test_delta_tables.py pass, the cross-generation container replay integration test passes, and Ruff reports no findings in either changed file
  implication: byte bounding preserves Delta APPEND atomicity/retry/conflict behavior and the table-scoped immutable replay contract

- timestamp: 2026-09-10T02:13:00+08:00
  checked: first revert-and-reconfirm baseline run
  found: baseline failed before the behavioral assertion because the GREEN edit changed the RED test to pass append_preflight_batch_bytes through the new constructor
  implication: this run does not prove the original bug returned; preserve the original test's dynamic attribute assignment and repeat the guardrail without coupling the reproduction to the new constructor API

- timestamp: 2026-09-10T02:17:00+08:00
  checked: corrected revert-and-reconfirm baseline run
  found: with only src/storage/delta_writer.py reverted, the unchanged agent-authored test reaches the behavioral oracle and fails exactly as RED: compared_key_counts is [2] instead of [1, 1]
  implication: the original missing byte-bound behavior returns without the production change; reapply and require GREEN to complete causal confirmation

- timestamp: 2026-09-10T02:20:00+08:00
  checked: corrected revert-and-reconfirm reapplied run
  found: after reapplying only src/storage/delta_writer.py, the exact unchanged target passes
  implication: this production change causally removes the reproduced defect; signal 5 passes

- timestamp: 2026-09-10T02:27:00+08:00
  checked: full isolated project pytest suite
  found: the suite completed at 100% with zero failures and one pre-existing skip; only existing FastAPI deprecation warnings were emitted
  implication: no project-wide regression is detected with the fix reapplied

- timestamp: 2026-09-10T02:30:00+08:00
  checked: final patch hygiene and cloud-safety boundary
  found: git diff --check passes, only src/storage/delta_writer.py and tests/test_delta_tables.py belong to this fix, both temporary guardrail stashes were dropped, and no cloud build, deployment, resource resize, or job execution was performed
  implication: the local guardrail is accepted without disturbing unrelated work or violating the checkpoint's cloud prohibitions; real 8 GiB verification remains a human-authorized checkpoint

- timestamp: 2026-09-10T02:31:00+08:00
  checked: human-verification checkpoint response
  found: the user confirmed the fix locally and authorized only a later controlled immutable build/deploy/retry after Fabric restart
  implication: resolve and archive the local debug session without cloud operations; preserve production-scale 4 CPU / 8 GiB verification as deferred evidence rather than claiming it passed

- timestamp: 2026-09-10T02:32:00+08:00
  checked: archive semantic indexing
  found: MemPalace is neither configured nor installed, while the durable knowledge-base entry was written and committed successfully
  implication: semantic indexing is skipped explicitly; .planning/debug/knowledge-base.md remains the durable keyword-recall fallback

- timestamp: 2026-09-10T03:10:00+08:00
  checked: independent post-resolution review and live payload sample
  found: review confirmed the preflight ceiling preserves atomicity and immutable semantics but found write-side Arrow/schema materialization remained row-only bounded; 1000 live rows averaged 3046 bytes, projecting 14 filtered scans at the 32 MiB ceiling
  implication: extend the same byte ceiling to every payload-proportional APPEND materialization before another live retry, while retaining a practical remote-scan count

- timestamp: 2026-09-10T03:25:00+08:00
  checked: follow-up hardening tests, full backend suite, lint, package build, and second independent review
  found: schema inference, Arrow record batches, initial preflight, and retry preflight are byte-bounded; payload size is estimated once per unique row; 100 adjacent tests and the full 4046-test backend suite pass with one pre-existing skip; scoped Ruff, diff hygiene, and source/wheel builds pass; independent review reports no blocking issue
  implication: all known payload-proportional APPEND allocations are now governed by the same bounded contract and the retry may proceed through the controlled immutable deployment workflow

- timestamp: 2026-09-10T04:15:00+08:00
  checked: exact live Delta filtered-read and per-file Parquet profiles after a second 8 GiB exit 137
  found: requesting only 100 keys and returning 253 KiB through DeltaTable.to_pyarrow_table increased RSS by 718 MiB because the single 149899-row Parquet row group was decoded; iterating that exact file with ParquetFile.iter_batches increased RSS by 76.6 MiB and completed all rows in 7 seconds
  implication: caller-side byte batches cannot constrain Delta's filtered to_pyarrow_table allocation; large replay validation must stream within the active Parquet file instead

- timestamp: 2026-09-10T04:45:00+08:00
  checked: converged per-file streaming implementation, schema/partition/version invariants, adjacent/full tests, package build, lint, and code review
  found: every active file is scanned in row batches bounded by target uncompressed row width; evolved columns are normalized to the Delta schema; encoded partition paths and typed partition values are preserved; every duplicate occurrence is checked; an unchanged target version skips a redundant second scan while a changed version revalidates; 108 adjacent tests and the full backend suite pass; final code review found no significant issue
  implication: the actual row-group decoder amplification and the prior semantic/order edge cases are covered before another controlled live retry

- timestamp: 2026-09-10T05:30:00+08:00
  checked: complete live 149899-row replay preflight outside the 8 GiB publication process after a third table-54 exit 137
  found: loading all incoming rows used 978 MiB RSS and the complete immutable replay preflight added only 76 MiB, returning skipped at Delta version 0; therefore the corrected Delta path itself fits comfortably, while the production process enters it with approximately 6.7 GiB already resident
  implication: the remaining fatal headroom loss is duplicate temporal/Gold row ownership and retained Arrow/Python allocator pages before table publication, not target comparison

- timestamp: 2026-09-10T06:00:00+08:00
  checked: resident-memory ownership changes and full validation
  found: internal publication now shares new temporal observation dicts between append and Gold history, avoids copy-on-write-table conversion, releases persisted/temporary projections promptly, and runs Python GC plus Arrow release_unused before table publication; default public write_tables behavior still returns copies; 122 adjacent tests, full backend suite, scoped Ruff, diff hygiene, and package build pass
  implication: publication reaches the bounded Delta path with materially more headroom without weakening external mutability safety or Gold input completeness

## Resolution

root_cause: the replay-aware APPEND preflight used DeltaTable.to_pyarrow_table filters that decoded the target's entire 149899-row Parquet row group for every incoming-key batch; each nominal 100-key lookup allocated 718 MiB, and repeated decoder allocations plus a roughly 6.55 GiB resident publication graph exceeded the 8 GiB cgroup
fix:
  DeltaWriter retains the 32 MiB/10000-row bounds for incoming materialization and uses a single true per-file Parquet batch scan for large target replays; target batches derive from uncompressed row-group width, partition values are reattached from Delta actions, schema-evolved columns are normalized, all duplicate occurrences are checked, and redundant revalidation is skipped only while the Delta version is unchanged. Fabric publication also shares validated temporal rows between append and Gold history, drops transient projection owners promptly, and releases unused Python/Arrow memory before serialized table writes.
verification:
  target_test: {result: pass}
  mutation_check: {result: skipped, reason_if_skipped: "no Stryker or other mutation runner is configured", mutant_killed: null}
  no_op_deletion: {result: pass, deletion_justified_by_rca: false}
  adjacent_tests: {result: pass, suites_run: ["Delta/container/Fabric/temporal adjacent suites (122 passed)", "full project pytest suite (zero failures, one pre-existing skip)", "complete live 149899-row replay preflight (76 MiB increment, skipped successfully)", "ruff check on all changed Python files", "git diff --check", "uv build", "final code review"]}
  revert_and_reconfirm: {result: pass, bug_returned_on_revert: true, fixed_on_reapply: true}
  human_verification: {result: pass, scope: "local"}
  production_scale_verification: {result: deferred, scope: "later authorized controlled immutable build/deploy/retry on 4 CPU / 8 GiB", reason: "cloud operations are excluded from this debug session"}
  guardrail_verdict: accepted
oracle_type: derived — under a configured one-byte aggregate comparison budget, two indivisible oversized rows must be issued as two one-row target reads while retaining replay deduplication
files_changed:
  - src/storage/delta_writer.py
  - tests/test_delta_tables.py

## Prevention

blameless_branches:
  - "code: the replay-aware APPEND preflight inherited a row-count bound, but retained all payload-proportional Arrow, Python, and canonical JSON materializations without an aggregate byte bound"
  - "data: container observations correctly retain large source-event and provenance JSON as immutable semantics, making row count a poor proxy for transient allocation"
  - "environment/config: the generic 10000-row batch entered this high-payload table with only roughly 1.5 GiB of remaining headroom inside an 8 GiB cgroup"
and_gate: "all three conditions were required for the fatal exit 137; the code path was latent at small payloads, and the payload was valid until fixed memory headroom amplified it"
why_not_caught: "No existing test or verify gate asserted payload-byte boundaries for replay preflight; prior APPEND tests covered row-count bounds, atomicity, retries, and immutable semantics only with small rows."
recurrence_guard: "The 32 MiB safe default in src/storage/delta_writer.py and tests/test_delta_tables.py::{test_delta_writer_append_bounds_replay_preflight_by_payload_bytes,test_delta_writer_append_preflight_payload_byte_boundary} lock indivisible-row behavior and exact N-1/N/N+1 aggregate-byte boundaries; the later controlled immutable retry remains required for production-scale evidence."
