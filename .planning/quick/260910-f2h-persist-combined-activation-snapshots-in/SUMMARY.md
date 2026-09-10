---
phase: quick-260910-f2h
plan: "01"
subsystem: activation-recovery
tags: [python, fabric, onelake, replay, activation, tdd]
requires:
  - phase: quick-260909-032
    provides: Activation progress schema and established Fabric/Gold pointer-order transaction
provides:
  - Durable combined activation generations in the production OneLake lakehouse
  - Exact activate replay without Azure connection validation or discovery
  - URI-safe Fabric source-root configuration for local paths and OneLake
  - Fail-closed combined provenance, manifest, dataset, ontology, row-count, semantic-hash, and full-content integrity validation before Fabric publication
  - Intentional unbounded remote generation retention for race-free exact replay
  - Historical replay coverage through tables, ontology, Gold, completion, shortcuts, and pointer activation
  - Backward-compatible normal config-load failure attribution to the combined-snapshot stage
affects: [activation-cli, fabric-publication, exposure-gold, production-recovery]
actuals:
  tokens: 16294
  tasks: 2
  commits: 12
tech-stack:
  added: []
  patterns:
    - Exact immutable generation replay through DatasetStore.generation_path
    - Activation-scoped integrity verification through DatasetStore.verify_combined_activation_generation
    - Separate semantic change hashes and full-content replay integrity hashes
    - Remote immutable generations retained until separately governed deletion
    - URI-preserving source-root configuration with local Path compatibility
    - Activation-owned Exposure pointer-store forwarding
key-files:
  created: []
  modified:
    - src/storage/datasets.py
    - src/fabric/config.py
    - src/onboarding/activation.py
    - tests/test_storage.py
    - tests/test_onelake_fs.py
    - src/onboarding/cli.py
    - fabric.config.deploy.yaml
    - tests/test_fabric_commands.py
    - tests/test_fabric_sync_service.py
    - tests/test_onboarding_activation.py
    - tests/test_subscription_cli.py
key-decisions:
  - "Exact activation replay resolves only generations/<requested-id>; it never consults the current generation pointer."
  - "Replay enters FabricSyncService directly with the activation-owned OneLakeDocumentStore so the established Gold completion and pointer transaction remains authoritative."
  - "Fabric source roots remain resolved Path objects locally and normalized strings for valid OneLake URIs."
  - "Normal Fabric config loading remains inside the combined_snapshot stage boundary; replay config loading remains outside that skipped stage."
  - "Exact replay trusts a generation only after DatasetStore verifies every declared JSONL/ontology artifact and the manifest's complete semantic hash chain."
  - "Combined activation replay requires the exact query version plus unique, non-empty source connection/run lists with one source run per connection."
  - "Semantic contentHash remains the change-detection contract; integrityHash authenticates every persisted value plus immutable run metadata for replay."
  - "Remote DatasetStore generations are not automatically deleted because exact replay requires stable immutable inputs; local cleanup remains bounded."
patterns-established:
  - "Replay provenance: terminal connections come from the persisted combined manifest while skipped validation and discovery results remain empty mappings."
  - "Fail-closed replay: unsafe, absent, incomplete, unreadable, malformed, truncated, or hash-mismatched generation input is rejected before runtime construction or Fabric publication."
requirements-completed: [QUICK-260910-F2H]
coverage:
  - id: D1
    description: Normal activation persists combined generations to a URI-safe configured source root and production uses the exact OneLake inventory-source path
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_fabric_commands.py and tests/test_onboarding_activation.py"
        status: pass
    human_judgment: false
  - id: D2
    description: Activate exact replay skips upstream discovery and preserves result, progress, publication, Gold, completion, shortcut, and pointer contracts
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_onboarding_activation.py, tests/test_subscription_cli.py, and tests/test_fabric_sync_service.py"
        status: pass
    human_judgment: false
  - id: D3
    description: Unsafe, missing, unreadable, and malformed exact generations fail before Fabric publication without latest fallback
    requirement: QUICK-260910-F2H
    verification:
      - kind: integration
        ref: "tests/test_onboarding_activation.py and tests/test_fabric_sync_service.py"
        status: pass
    human_judgment: false
duration: 45min
completed: 2026-09-10
status: complete
---

# Quick Task 260910-f2h: Durable Combined Activation Snapshots and Exact Replay Summary

**Durable OneLake activation generations with exact-ID replay through the established Fabric, Gold, completion, shortcut, and atomic pointer transaction**

## Performance

- **Duration:** 45 min across initial execution, verifier-gap remediation, and both final code-review closures
- **Started:** 2026-09-10T03:00:39Z
- **Completed:** 2026-09-10T03:58:43Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Made `FabricRuntimeConfig.source_data_root` URI-safe: config-relative local roots remain resolved `Path` values, while valid OneLake roots remain normalized strings.
- Added `activate --replay-source-run-id <exact-id>` and an activation replay branch that reads only the requested immutable manifest, skips all connection enumeration/validation/discovery and combined publication, and preserves the established terminal result shape.
- Bound production combined snapshots to the exact existing workspace/lakehouse OneLake root under `Files/aiops/inventory-source`.
- Proved a historical generation is used even when a different generation is current, including normal table and ontology publication, Gold staging/writes, shortcut finalization, completed-version state, and final pointer activation.
- Added fail-closed coverage for traversal-shaped IDs and absent, unreadable, malformed, or provenance-invalid manifests before Fabric runtime construction.
- Added activation-scoped `DatasetStore.verify_combined_activation_generation()` validation for the exact combined query version, completed status, exact run identity, unique non-empty source connection/run IDs with matching cardinality, declared dataset names/artifacts, ontology shape, row counts, per-artifact semantic hashes, and the overall manifest hash before runtime construction.
- Added a separate canonical `integrityHash` to every dataset/ontology declaration and the manifest. Unlike semantic `contentHash`, it includes volatile timestamps, row provenance, and all immutable manifest metadata.
- Disabled automatic cleanup for remote DatasetStore generations while preserving the existing three-generation local cleanup policy, removing the publish-versus-replay deletion race.
- Added a second exact-generation verification after runtime construction and immediately before Fabric sync/mapping.
- Added local corruption coverage for missing/malformed/altered datasets, missing/invalid ontology, dataset and ontology count/hash mismatches, overall hash mismatch, incomplete status, wrong run ID, missing/wrong-type/empty/blank/non-string/duplicate source provenance, cardinality mismatch, wrong query version, and invalid dataset names; all assert no runtime or pointer construction.
- Restored the prior normal-mode progress boundary so a Fabric config-load failure emits `combined_snapshot/started` followed by sanitized `combined_snapshot/failed`, while replay still emits no combined-snapshot events.

## Task Commits

TDD RED and GREEN gates were committed separately:

1. **Task 1 RED: Define exact activation replay contract** — `9174fe567`
2. **Task 1 GREEN: Replay exact activation generations** — `a59bfa3c5`
3. **Task 2 RED: Cover durable replay finalization** — `48a730dbe`
4. **Task 2 GREEN: Persist activation snapshots in OneLake** — `d1bc7e6db`
5. **Task 2 verification closure: Complete replay input safety cases** — `29fe08814`
6. **Verifier gap remediation: Restore snapshot failure stage** — `132893d3e`
7. **Code-review RED: Expose corrupt replay artifacts** — `faeaa5db1`
8. **Code-review GREEN: Verify exact replay integrity** — `29591f64e`
9. **Final verifier RED: Expose incomplete combined provenance checks** — `7cf710216`
10. **Final verifier GREEN: Reject invalid combined replay provenance** — `6c93a8fd1`
11. **Final code-review RED: Expose full-integrity and retention gaps** — `80bbc4e98`
12. **Final code-review GREEN: Add full integrity and race-free retention** — `89fcb0102`

## Files Created/Modified

- `src/fabric/config.py` — Preserves OneLake source URIs while retaining config-relative local path resolution.
- `src/storage/datasets.py` — Publishes and verifies separate semantic/full-content hash contracts and retains remote immutable generations for exact replay.
- `src/onboarding/activation.py` — Adds exact replay resolution, pre-runtime and pre-sync integrity verification, truthful progress, and direct Fabric transaction invocation.
- `src/onboarding/cli.py` — Parses and conditionally forwards `--replay-source-run-id`.
- `fabric.config.deploy.yaml` — Uses the production OneLake combined-snapshot root.
- `tests/test_fabric_commands.py` — Covers local/OneLake runtime config types and the production URI.
- `tests/test_fabric_sync_service.py` — Proves historical selection and the full Fabric/Gold/finalization/pointer transaction.
- `tests/test_onboarding_activation.py` — Covers no-upstream replay, valid multi-connection provenance, pointer-store forwarding, result/progress compatibility, and fail-closed provenance/manifest/artifact corruption.
- `tests/test_subscription_cli.py` — Covers exact replay argument forwarding and terminal output compatibility.
- `tests/test_storage.py` — Proves semantic hashes remain stable while full-content hashes detect every reviewed volatile field, and local cleanup stays bounded.
- `tests/test_onelake_fs.py` — Proves remote publication retains more than three immutable replay generations.

## Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_onboarding_activation.py::test_activate_runtime_config_load_failure_is_combined_snapshot_failure tests/test_onboarding_activation.py::test_activate_runtime_replays_exact_generation_without_upstream_work tests/test_onboarding_activation.py::test_activate_runtime_replay_refuses_unreadable_or_malformed_manifest tests/test_onboarding_activation.py::test_activate_runtime_replay_refuses_missing_or_unsafe_exact_generation` — **8 passed**.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_onboarding_activation.py -k 'replays_exact_generation_without_upstream_work or replay_refuses_corrupt_generation_before_runtime'` — all 30 focused provenance and corruption cases passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_storage.py` — all DatasetStore regression tests passed.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_OFFLINE=1 uv run pytest -q tests/test_storage.py tests/test_onelake_fs.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py` — all 176 collected quick-task tests passed.
- `UV_OFFLINE=1 uv run ruff check src/storage/datasets.py src/onboarding/activation.py tests/test_storage.py tests/test_onelake_fs.py tests/test_onboarding_activation.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_subscription_cli.py` — passed.
- `UV_OFFLINE=1 uv run python -m compileall -q` over the same Python scope — passed.
- `git diff --check 80bbc4e98^..89fcb0102` — passed.
- No Azure CLI, Fabric/Azure API, Terraform, deployment, networked test, Container Apps Job/profile/schedule, or D4 operation was invoked.

## Decisions Made

- Reused `DatasetStore.generation_path()` as the single safe exact-ID resolver and deliberately excluded `current_generation()` from replay.
- Loaded and validated the persisted combined manifest before runtime construction so malformed or unreadable replay input cannot begin Fabric publication.
- Kept the normal activation branch's validation, discovery, combined publication, progress order, result fields, and pointer-store behavior unchanged.
- Kept `FabricRuntimeConfig.load()` inside the normal `combined_snapshot` stage so load failures retain prior stage attribution, without moving replay config validation into a stage replay does not execute.
- Reused the publication `_sorted_rows()` and `_semantic_hash()` implementation in the verifier so integrity checks follow the exact semantic contract that produced each manifest hash.
- Preserved semantic `contentHash` for change detection and added independent streaming canonical SHA-256 hashes for exact replay, rather than changing the established semantic contract.
- Authenticated the complete artifact declaration map and all non-derived run metadata so future subscription-scope/provenance fields are covered automatically.
- Kept remote immutable generations indefinitely; any future remote retention policy must be an explicit governed operation rather than publish-time cleanup.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Disabled unrelated third-party pytest plugin auto-loading**
- **Found during:** Task 1 RED verification
- **Issue:** An installed Phoenix pytest entry point crashes during pytest startup on Python 3.11 because of an incompatible mutable dataclass default, before repository tests are collected.
- **Fix:** Ran the scoped local pytest commands with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; no project dependency or test behavior was changed.
- **Files modified:** None.
- **Verification:** All 99 planned tests pass with repository tests collected normally.
- **Committed in:** Not applicable (environment-only invocation).

**2. [Rule 1 - Bug] Restored normal config-load failure stage attribution**
- **Found during:** Post-execution verifier
- **Issue:** Normal mode loaded Fabric configuration before starting `combined_snapshot`, changing config-load failures from `combined_snapshot/failed` to `activation/failed`.
- **Fix:** Started `combined_snapshot` immediately before the normal-mode config load and added a focused sanitized-failure regression; replay remains on its separate no-combined-snapshot branch.
- **Files modified:** `src/onboarding/activation.py`, `tests/test_onboarding_activation.py`
- **Verification:** Focused 8-case replay/stage run, complete 100-test quick-task suite, Ruff, and diff checks passed.
- **Committed in:** `132893d3e`

**3. [Rule 1 - Security bug] Closed incomplete exact-generation integrity validation**
- **Found during:** Post-verification code review
- **Issue:** Replay validated only manifest shape, run ID, and source IDs, allowing missing, malformed, truncated, or hash-mismatched declared artifacts to reach Fabric mapping as empty or modified rows.
- **Fix:** Added centralized exact-generation verification in `DatasetStore` and made activation require it before `build_runtime`; Fabric sync remains pinned to the requested immutable generation ID.
- **Files modified:** `src/storage/datasets.py`, `src/onboarding/activation.py`, `tests/test_onboarding_activation.py`
- **Verification:** Focused corruption tests, DatasetStore tests, the complete quick-task suite, Ruff, Python compilation, and diff checks passed.
- **Committed in:** `faeaa5db1`, `29591f64e`

**4. [Rule 1 - Security bug] Closed incomplete combined-snapshot provenance validation**
- **Found during:** Final verifier re-verification
- **Issue:** Exact replay accepted missing or malformed `sourceRunIds`, duplicate provenance IDs, mismatched source-list cardinality, and missing or wrong `queryVersion` values because the overall content hash covers artifacts only.
- **Fix:** Renamed the verifier for its activation-specific scope and required the exact combined query version plus unique, non-empty source connection/run lists with matching cardinality before artifact validation or runtime construction.
- **Files modified:** `src/storage/datasets.py`, `src/onboarding/activation.py`, `tests/test_onboarding_activation.py`
- **Verification:** The 30-case focused replay matrix, all 142 quick-task tests, Ruff, Python compilation, and diff checks passed.
- **Committed in:** `7cf710216`, `6c93a8fd1`

**5. [Rule 1 - Security bug] Added exact full-content replay integrity**
- **Found during:** Final code review finding F-01.
- **Issue:** Semantic hashes intentionally omitted volatile/provenance fields, so replay could not detect changes to values consumed by Fabric.
- **Fix:** Added canonical per-artifact and manifest integrity hashes, fail-closed legacy handling, metadata coverage, and a second verification immediately before Fabric sync.
- **Files modified:** `src/storage/datasets.py`, `src/onboarding/activation.py`, `tests/test_storage.py`, `tests/test_onboarding_activation.py`
- **Verification:** Volatile-field, metadata, legacy-manifest, and second-check regressions plus the full quick-task suite passed.
- **Committed in:** `80bbc4e98`, `89fcb0102`

**6. [Rule 1 - Concurrency bug] Removed remote generation cleanup race**
- **Found during:** Final code review finding F-02.
- **Issue:** Publish-time three-generation cleanup could delete a previously verified remote generation while exact replay was constructing or mapping it.
- **Fix:** Disabled automatic remote cleanup, documented governed retention intent, and retained the existing three-generation local cleanup behavior.
- **Files modified:** `src/storage/datasets.py`, `tests/test_storage.py`, `tests/test_onelake_fs.py`
- **Verification:** Five remote generations remain replay-resolvable while five local generations are reduced to the newest three.
- **Committed in:** `80bbc4e98`, `89fcb0102`

**Total deviations:** 6 auto-fixed issues (5 Rule 1 bugs, 1 Rule 3 blocking issue).
**Impact on plan:** The additional fail-closed check fulfills the original exact-replay threat model without changing normal activation, replay results/progress, or publication ordering.

## Issues Encountered

- The environment's auto-loaded Phoenix pytest plugin is incompatible with the active Python runtime. Disabling external plugin auto-loading allowed the repository's own tests to run without bypassing any project test.
- Initial verification found one normal-mode progress compatibility regression; `132893d3e` restored the exact pre-task boundary and closed the gap.
- Post-verification review found artifact integrity was not enforced before runtime construction; `29591f64e` now rejects every tested corruption class locally.
- Final re-verification found artifact hashes did not authenticate activation provenance; `6c93a8fd1` now validates the full combined-snapshot provenance contract before runtime construction.
- Final code review found semantic hashes omitted Fabric-consumed volatile values and remote publish cleanup could race exact replay; `89fcb0102` closes both gaps.

## Verification Gap Closure

- Normal mode now starts `combined_snapshot` before the fallible `FabricRuntimeConfig.load()` call, restoring the established started/failed event pair and sanitized `ActivationFailure.stage`.
- Replay still loads and validates config/source only on its replay branch before Fabric publication and emits no `combined_snapshot` event.
- Replay now obtains its returned manifest from `DatasetStore.verify_combined_activation_generation()`, which resolves only the requested immutable path and verifies complete combined provenance plus every declared artifact before `build_runtime`.
- Every new artifact declaration now carries both semantic `contentHash` and full canonical `integrityHash`; the manifest integrity hash covers complete declarations plus all immutable run metadata.
- Replay verifies once before runtime construction and again immediately before sync; remote normal publication no longer deletes immutable generations.
- Missing, wrong-type, empty, blank, non-string, duplicate, mismatched-cardinality, and wrong-version provenance cases all fail through fail-on-call runtime and pointer doubles.
- Re-verification records no remaining implementation or behavioral gaps; the live OneLake and historical no-cloud/no-D4 checks remain operator-confirmation warnings only.

## Known Stubs

None.

## Security and Threat Review

- Replay IDs pass through the existing safe single-segment generation validator.
- Exact replay never falls back to `current`; legacy no-integrity generations, wrong query version, missing/malformed/duplicate/mismatched source provenance, immutable metadata changes, incomplete status, unsafe dataset names, missing/invalid artifacts, count mismatches, semantic-hash mismatches, full-content changes, and overall-integrity mismatches fail before publication.
- The production configuration contains only a non-secret OneLake URI.
- Exposure pointer authority remains in the existing transaction and activates only after publication, Gold staging, shortcut finalization, and completed state.
- No security-relevant surface outside the plan threat model was introduced.

## User Setup Required

None — no dependency, credential, or external service change is required.

## Next Phase Readiness

- Operators can recover or intentionally repeat Fabric publication from one exact durable activation generation without repeating Azure connection work.
- Newly published remote generations remain available for exact replay until an explicit future retention operation removes them.
- Active Phase 03.1 ownership, status, blocker, and resume state remain unchanged.
- All unrelated dirty Fabric Data Agent, Gold-grounding, Terraform, `.azure`, documentation, and test paths remain untouched and unstaged.

## Self-Check: PASSED

- The required summary exists at the quick-task path.
- All eleven scoped source/config/test files exist.
- All twelve recorded task/remediation commits exist in Git history.
- No tracked file was deleted by a task commit.
- No unrelated dirty or untracked path was staged or committed.

---
*Quick task: 260910-f2h*
*Completed: 2026-09-10*
