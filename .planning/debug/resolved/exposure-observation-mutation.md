---
status: resolved
trigger: "The first bounded-append live Exposure Gold publication completed 451 of 452 base Delta tables but failed before Gold staging with `Append row mutation for key ('vulnerability-observation:v1:32c17d9c20aeb31ed18ad544817820ee375ebf97471efdcc5183b28fc40d7310',)`."
created: 2026-09-09T21:18:46+08:00
updated: 2026-09-09T23:06:00+08:00
---

## Current Focus

hypothesis: resolved — container observations embedded acquisition-generation metadata in rows keyed by a provider-stable v1 identity, so unchanged evidence became a false immutable APPEND mutation on a later onboarding generation
bug_class: bohrbug
pattern_candidate: data-shape/API-contract mismatch between immutable observation identity and append payload
known_pattern_candidate: `phase031-plan19-publication-atomicity` — a supposedly stable ontology identity included/omitted mutable interval semantics and produced false immutable-history conflicts
reasoning_checkpoint:
  hypothesis: "`normalize_container_image_products` carries acquisition time/generation into a provider-stable v1 observation row; `InventoryDatasetMapper` persists those values, and generic APPEND canonical comparison therefore rejects an unchanged provider event normalized in a later generation."
  confirming_evidence:
    - "An unchanged synthetic Defender event normalized in two generations produced the same observation ID but different timestamp, change_version, ingestion_run_id, ingested_at, and provenance_json."
    - "Appending those two mapped rows locally reproduced the exact `Append row mutation for key (...)` exception."
    - "The accepted Plan 03.1-10 contract says source event + digest + CVE + provider event time define the immutable observation and Fabric retry/run IDs are lineage, not provider identity."
  falsification_test: "If an unchanged provider event normalized under different acquisition times/generations appends idempotently without excluding any semantic evidence, this hypothesis is false."
  fix_rationale: "Use a table-scoped APPEND comparison policy that ignores only acquisition replay metadata (including only the nested provenance ingestion timestamp) for container observations; retain the first accepted row and continue comparing every provider-semantic field so real mutations still fail."
  blind_spots: "The exact live existing/incoming row diff was not fetched; verification must cover pre-fix-shaped retained rows, missing provider time, and a semantic severity/payload mutation."
  candidate_causes:
    - "code: the mapper/APPEND boundary compares acquisition metadata as immutable provider content"
    - "data: Defender changed severity/package payload under the same source identity and event time"
  and_gate: "no — unchanged provider data reproduces the failure, so an upstream data mutation is not required"
test: human accepted the locally verified source fix without authorizing live deployment or retry
expecting: deferred controlled build/deploy/retry verifies the fix against the original live OneLake row and completes publication before any Gold pointer activation
next_action: archive and commit only the scoped local source/test/debug artifacts; preserve live verification as a future requirement

## Symptoms

expected: the serialized 8 GiB publication completes all 452 base table writes, stages six Gold artifacts, writes the completed marker, finalizes shortcuts, and atomically activates the first Gold pointer
actual: all other base tables drain successfully, but one base table future fails; the run terminates before Gold staging and the pointer remains absent
errors: "Append row mutation for key ('vulnerability-observation:v1:32c17d9c20aeb31ed18ad544817820ee375ebf97471efdcc5183b28fc40d7310',)"
reproduction: run `python -m onboarding.cli activate --config /app/config.yaml --fabric-config /app/fabric.config.yaml --connection-id demo` using immutable image digest `sha256:1167a42ca5e3355781552b7ad4971749d92bcb39d8ccce8f1b29af403735bdfb` against the live OneLake data; execution `aiops-dev-exposure-publication-n4qc1c3` reproduces the failure
started: observed in the live publication on 2026-09-09 at 13:45:47Z after earlier atomicity and bounded-APPEND fixes

## Eliminated

- hypothesis: The bounded APPEND implementation still OOMs at `silver_exposure_observations`.
  evidence: table 54 `silver_exposure_observations` completed with 77,489 rows; the job reached 451 successful base tables, exited code 1 rather than 137, peaked at 6.64 GiB, and recorded zero restarts.
  timestamp: 2026-09-09T21:18:46+08:00

- hypothesis: Gold staging or pointer activation failed.
  evidence: total table count 458 consists of 452 base publish items plus five Gold tables and one Gold-generation metadata table; only 451 base completions were recorded and no Gold table completion or pointer activation occurred.
  timestamp: 2026-09-09T21:18:46+08:00

- hypothesis: The publication Job contract was not restored after the terminal execution.
  evidence: the monitor reported the exact pre-run full contract hash `629145b933b15d3ca4c514db59c056a38190c7995acc753df7b862fbc4431159`, and a structural diff of current configuration/template against `job-before.json` is empty.
  timestamp: 2026-09-09T21:18:46+08:00

- hypothesis: An upstream Defender severity/package/source-payload mutation is required to produce the conflict.
  evidence: an unchanged Defender input row reproduced the exact APPEND mutation solely by changing onboarding observation time and source generation.
  timestamp: 2026-09-09T22:34:41+08:00

## Evidence

- timestamp: 2026-09-09T21:18:46+08:00
  checked: Azure Container Apps execution and system logs
  found: execution `aiops-dev-exposure-publication-n4qc1c3` failed with process exit code 1 and `ACTIVATION_FAILED`; it was not killed by the cgroup and did not restart
  implication: this is a deterministic application invariant failure rather than resource exhaustion

- timestamp: 2026-09-09T21:18:46+08:00
  checked: structured publication progress
  found: 451 successful base table completions were recorded; `silver_exposure_observations` completed, while `silver_container_vulnerability_observations` has no completion event
  implication: the missing successful future is the container vulnerability observation APPEND

- timestamp: 2026-09-09T21:18:46+08:00
  checked: authoritative `metadata_ingestion_state`
  found: run `91333a67-5a58-49c0-8ae6-8945465bb498` persisted the exact error `Append row mutation for key ('vulnerability-observation:v1:32c17d9c20aeb31ed18ad544817820ee375ebf97471efdcc5183b28fc40d7310',)`
  implication: an existing immutable observation row and the newly projected row share an identity but differ canonically

- timestamp: 2026-09-09T21:18:46+08:00
  checked: live resource metrics
  found: peak memory was 6.64 GiB of 8 GiB and restart count was zero
  implication: the bounded APPEND memory fix succeeded at its original failure boundary

- timestamp: 2026-09-09T22:10:05+08:00
  checked: repository working tree before investigation
  found: the pre-existing dirty paths match the frozen Fabric Data Agent ownership list; the only additional untracked path is this debug session file
  implication: the investigation must avoid all listed dirty production/test/script paths and can detect any new local change precisely

- timestamp: 2026-09-09T22:10:05+08:00
  checked: repository-wide search for the exact conflicting observation key
  found: the live key hash is not embedded in local files; only a synthetic versioned observation ID appears in `tests/test_exposure_ontology_roundtrip.py`
  implication: reproduction must derive the collision from durable row artifacts or construct the minimal differing payload from the projection contract

- timestamp: 2026-09-09T22:10:05+08:00
  checked: configured `gsd-debugger` agent skills
  found: the agent-skills query returned no configured skill block
  implication: no additional configured debugger skill needs loading

- timestamp: 2026-09-09T22:12:01+08:00
  checked: active Phase 03.1 decisions and scope in `.planning/STATE.md`
  found: v1 Exposure observations and the additive container contract are explicitly immutable; identity changes require additive versioning, migration/backfill, dual readers, relationship regeneration, and pointer rollback
  implication: a safe fix must preserve immutable conflict detection and should correct the producer contract locally unless evidence proves that a versioned identity migration is required

- timestamp: 2026-09-09T22:12:01+08:00
  checked: active Phase 03.1 status
  found: exact supported Defender digest-to-workload evidence remains blocked and the user has prohibited any live retry or pointer mutation
  implication: investigation and verification must use local durable evidence and focused tests only

- timestamp: 2026-09-09T22:14:10+08:00
  checked: debug knowledge base semantic/keyword fallback
  found: the closest prior pattern is `phase031-plan19-publication-atomicity`, where mutable event intervals were incorrectly coupled to stable ontology relationship identity; no entry names this exact observation conflict
  implication: identity-versus-mutable-payload drift is a high-priority candidate but remains unconfirmed until the container observation contract is traced

- timestamp: 2026-09-09T22:14:10+08:00
  checked: Spectrum-based fault localization prerequisites
  found: there is no existing failing local test for this live-row conflict, so there is no failing/passing per-test coverage spectrum to rank
  implication: SBFL is skipped until a focused deterministic regression test exists; working backwards from the exact APPEND key is the appropriate first local move

- timestamp: 2026-09-09T22:17:18+08:00
  checked: `normalize_container_image_products` observation identity and payload construction
  found: `vulnerability-observation:v1` hashes tenant, subscription, digest, CVE, source-event ID, and provider-event time, but the emitted row also carries acquisition-owned `ingestedAt`, `sourceGeneration`, and provenance `ingested_at`
  implication: replaying identical provider evidence in a later acquisition can preserve the identity while changing fields later persisted in the immutable APPEND row

- timestamp: 2026-09-09T22:17:18+08:00
  checked: `_container_vulnerability_observation_row` and the table schema
  found: the mapper persists `sourceGeneration` as `ingestion_run_id` and persists both `ingestedAt` and canonical provenance; all are included in the Delta row alongside the identity
  implication: run-scoped acquisition metadata is currently part of the canonical immutable comparison even though it is absent from identity

- timestamp: 2026-09-09T22:17:18+08:00
  checked: `DeltaWriter._validate_append_target`
  found: immutable APPEND correctly compares the full canonical existing and incoming rows and raises the exact observed error when any field differs
  implication: weakening conflict detection would hide a producer-contract defect; the reproduction should target the projected row rather than alter DeltaWriter

- timestamp: 2026-09-09T22:20:14+08:00
  checked: in-memory two-generation differential reproduction using one unchanged Defender row
  found: the two projections have the same `vulnerability_observation_id`, but mapped fields `timestamp`, `change_version`, `ingestion_run_id`, `ingested_at`, and `provenance_json` differ; the second local Delta APPEND raises the exact `Append row mutation for key (...)` error
  implication: unchanged provider evidence alone reproduces the production failure whenever it is normalized in a later acquisition generation

- timestamp: 2026-09-09T22:20:14+08:00
  checked: `DeltaWriter._canonical_row`
  found: `ingestion_run_id` is already deliberately excluded as physical write metadata, but acquisition time also changes `timestamp`, `change_version`, `ingested_at`, and nested provenance and those remain canonical
  implication: excluding only run ID is insufficient; the producer currently embeds replay-variant acquisition facts in an identity-stable immutable event

- timestamp: 2026-09-09T22:29:08+08:00
  checked: first execution of the focused cross-generation sync regression
  found: pytest collection was blocked before the test ran by the unrelated auto-loaded Phoenix plugin on Python 3.11 (`mappingproxy` dataclass mutable-default error)
  implication: this run is not a RED product result; rerun with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, the repository's isolation setting for optional third-party plugins

- timestamp: 2026-09-09T22:31:02+08:00
  checked: isolated execution of the initial minimal end-to-end fixture
  found: the first sync stopped at seven baseline data-quality failures before any replay; the intentionally tiny snapshot omitted unrelated required ontology context
  implication: the test harness is invalid rather than the hypothesis being falsified; compose the container row into the repository's known-valid source fixture

- timestamp: 2026-09-09T22:32:20+08:00
  checked: focused fixture composed into the repository's normal source snapshot
  found: adding a synthetic container graph still produces seven unrelated ontology quality findings before table publication
  implication: bypass only the quality-report gate in this narrow APPEND regression so it reaches the invariant under test without weakening production validation

- timestamp: 2026-09-09T22:33:28+08:00
  checked: APPEND-isolated full sync fixture
  found: the imported image helper omitted `tenantId`, causing the first write to fail Delta's non-null partition constraint before the replay
  implication: supply the tenant key present in live Defender rows; this is a fixture defect, not evidence against the root cause

- timestamp: 2026-09-09T22:34:41+08:00
  checked: focused end-to-end two-generation Fabric sync regression after fixture isolation
  found: the first sync completes and the second deterministically fails in `DeltaWriter._validate_append_target` with `Append row mutation for key ('vulnerability-observation:v1:...',)`
  implication: the automated RED test now reproduces the production failure through the real Normalizer → DatasetStore → InventoryDatasetMapper → FabricSyncService → DeltaWriter path

- timestamp: 2026-09-09T22:42:16+08:00
  checked: first GREEN attempt with table-scoped container replay canonicalization
  found: the original container key no longer failed, but the broad synthetic fixture then exposed an unrelated `metadata_audit_events` replay conflict on generation 2 before test completion
  implication: the container fix is taking effect; isolate audit writes in this focused regression rather than widening the production change beyond the reported table

- timestamp: 2026-09-09T22:43:22+08:00
  checked: isolated generation-2 sync after the production change
  found: generation 2 completed without a container APPEND conflict; the test then failed only because it referenced an unimported `_delta_rows` helper
  implication: the target symptom is removed; repair the test assertion plumbing and continue to the held-out semantic-mutation check

- timestamp: 2026-09-09T22:44:16+08:00
  checked: focused cross-generation regression after fixing assertion plumbing
  found: PASS — generation 2 deduplicates one unchanged observation, retains exactly one row, and generation 3 with changed severity still raises `Append row mutation`
  implication: the fix addresses replay-only drift without disabling immutable semantic conflict detection

- timestamp: 2026-09-09T22:46:08+08:00
  checked: focused diff and initial lint
  found: the production diff is additive and table-scoped with no behavior deletion; Ruff found only import ordering in the new regression test
  implication: guardrail no-op/deletion signal is provisionally clear; fix import order before adjacent verification

- timestamp: 2026-09-09T22:46:08+08:00
  checked: repository JavaScript validation scripts and mutation tooling
  found: no root `package.json` exists; only the unrelated `web/package.json` has npm scripts, and no Stryker/mutmut/cosmic-ray configuration is present
  implication: root-level mandated `npm run lint:fix && npm test` is not applicable to this Python-only fix; mutation testing will be recorded as skipped unless a configured tool is found

- timestamp: 2026-09-09T22:48:10+08:00
  checked: Ruff lint and format gates on the three touched Python files
  found: `ruff check` passes; `ruff format --check` reports broad pre-existing formatting drift across all three files, including many untouched lines, and stopped the chained command before pytest
  implication: do not rewrite unrelated code; validate changed hunks with lint plus `git diff --check`, and run tests in a separate command

- timestamp: 2026-09-09T22:50:03+08:00
  checked: adjacent storage, container, and Fabric sync suites
  found: 92 targeted tests pass across `test_delta_tables.py`, `test_container_image_exposure.py`, and `test_fabric_sync_service.py`
  implication: generic APPEND invariants, container normalization/projection, and neighboring Fabric publication paths remain green

- timestamp: 2026-09-09T22:50:03+08:00
  checked: focused diff whitespace
  found: `git diff --check` passes for all intended code, test, and debug-session files
  implication: changed hunks contain no whitespace errors

- timestamp: 2026-09-09T22:51:32+08:00
  checked: revert-and-reconfirm guardrail, reverted half
  found: after path-scoped stashing only the two production changes, the focused regression again fails on generation 2 with the exact container `Append row mutation` exception
  implication: the production change, not the test harness or environment, is necessary to remove the reported failure

- timestamp: 2026-09-09T22:52:36+08:00
  checked: revert-and-reconfirm guardrail, reapplied half
  found: after restoring the same two production changes, the focused replay-plus-semantic-mutation regression passes
  implication: the fix is causally linked to the resolution and the revert/reconfirm guardrail passes

- timestamp: 2026-09-09T23:01:10+08:00
  checked: full isolated Python suite
  found: PASS — the complete backend test suite completed with one intentional skip and only pre-existing FastAPI deprecation warnings
  implication: the fix does not regress the repository's Python behavior

- timestamp: 2026-09-09T23:01:10+08:00
  checked: repository-wide Ruff
  found: FAIL outside the fix — 27 pre-existing findings are confined to unrelated `infra/scripts` and `scripts` files; touched-file Ruff had already passed
  implication: do not alter unrelated/frozen work; record the global lint baseline failure while retaining the passing scoped lint result

- timestamp: 2026-09-09T23:03:02+08:00
  checked: hardened focused regression and final touched-file static checks
  found: PASS — generation 3 is asserted to fail on the exact retained container observation key; touched-file Ruff and focused `git diff --check` both pass
  implication: the regression oracle distinguishes accepted replay drift from a real semantic mutation on the same identity

- timestamp: 2026-09-09T23:04:20+08:00
  checked: final worktree and stash audit
  found: only `src/fabric/sync_service.py`, `src/storage/delta_writer.py`, `tests/test_fabric_sync_service.py`, and this debug file were added to the pre-existing dirty set; the temporary debug stash was removed and older unrelated user stashes remain untouched
  implication: frozen Fabric Data Agent files were not modified, no commit was made, and the session is ready for human verification

- timestamp: 2026-09-09T23:05:00+08:00
  checked: human-verification checkpoint response
  found: the user confirmed the locally verified source fix and explicitly prohibited deployment, Azure mutation, publication retry, Gold pointer changes, schedule changes, and unrelated dirty-file changes
  implication: the local debug session may be finalized, while end-to-end live verification remains deferred to the later controlled build/deploy/retry phase

- timestamp: 2026-09-09T23:06:00+08:00
  checked: semantic knowledge-base indexing availability
  found: the `mempalace` CLI is unavailable in this environment; the durable knowledge-base entry was written successfully
  implication: semantic indexing was skipped explicitly and `.planning/debug/knowledge-base.md` remains the fallback for future recall

## Resolution

root_cause: `normalize_container_image_products` and `_container_vulnerability_observation_row` persist acquisition-generation metadata (`timestamp`, derived `change_version`, `ingested_at`, provenance `ingested_at`, and `ingestion_run_id`) under a v1 key defined only by stable provider evidence; although `ingestion_run_id` is excluded, generic Delta APPEND compares the other replay fields and falsely reports a mutation on later source generations
fix: added opt-in APPEND replay-metadata canonicalization and configured it only for `silver_container_vulnerability_observations` to exclude acquisition envelope fields plus nested provenance `ingested_at`; all provider-semantic columns remain immutable and compared
verification:
  target_test: { result: pass }
  mutation_check: { result: skipped, reason_if_skipped: "No Stryker or Python mutation-test configuration is present", mutant_killed: null }
  no_op_deletion: { result: pass, deletion_justified_by_rca: false }
  adjacent_tests: { result: pass, suites_run: ["tests/test_delta_tables.py", "tests/test_container_image_exposure.py", "tests/test_fabric_sync_service.py", "full `uv run pytest -q` backend suite"] }
  revert_and_reconfirm: { result: pass, bug_returned_on_revert: true, fixed_on_reapply: true }
  scoped_lint: { result: pass, command: "uv run ruff check src/storage/delta_writer.py src/fabric/sync_service.py tests/test_fabric_sync_service.py" }
  repository_lint: { result: baseline_fail, evidence: "27 findings only in unrelated infra/scripts and scripts paths" }
  npm_validation: { result: not_applicable, reason: "No root package.json; web package is unrelated to this Python fix" }
  guardrail_verdict: accepted
  human_verification: { result: accepted, scope: "locally verified source fix only" }
  deferred_live_verification: { status: required, requirement: "During the later authorized controlled build/deploy/retry phase, deploy the scoped fix, retry the original publication against live OneLake data, confirm all 452 base tables and six Gold artifacts complete, and confirm the Gold pointer activates atomically; no live operation was authorized or performed during this debug finalization." }
files_changed:
  - src/storage/delta_writer.py
  - src/fabric/sync_service.py
  - tests/test_fabric_sync_service.py
oracle_type: derived — the accepted Plan 03.1-10 immutable-observation/idempotent-replay contract plus the exact Delta APPEND invariant

## Prevention

branched_five_whys:
  code:
    - "Why did replay fail? Generic APPEND canonicalization compared acquisition-time fields as immutable event content."
    - "Why were those fields compared? The container observation mapper persisted acquisition metadata under a provider-stable observation identity without a table-specific replay policy."
    - "Why was that possible? The generic writer had only a global `ingestion_run_id` exclusion and no explicit contract for nested or table-scoped replay metadata."
  data:
    - "Why did the defect appear only on a later publication? The same valid provider event was acquired in a new source generation, changing the acquisition envelope while preserving provider evidence."
    - "Why did valid data trigger an invariant? Identity followed provider semantics, while canonical payload comparison also included acquisition semantics."
  and_gate: "No upstream provider mutation was required; valid cross-generation replay was sufficient, while the data timing exposed the code-contract mismatch."
why_not_caught: "Existing APPEND and container tests covered same-generation idempotency and semantic mutation, but no integration gate replayed one unchanged provider observation across acquisition generations through the full Normalizer-to-Delta path."
recurrence_guard: "`tests/test_fabric_sync_service.py::test_sync_deduplicates_unchanged_container_observation_across_source_generations` proves unchanged generation N/N+1 replay deduplicates to one retained row and a severity mutation on the same identity still fails."
