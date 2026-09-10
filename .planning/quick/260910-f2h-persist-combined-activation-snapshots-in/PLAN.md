---
phase: quick-260910-f2h
quick_task: 260910-f2h
plan: 01
type: execute
wave: 1
depends_on: []
scope: "Durable combined activation snapshots and exact generation replay"
files_modified:
  - src/onboarding/activation.py
  - src/onboarding/cli.py
  - src/fabric/config.py
  - fabric.config.deploy.yaml
  - tests/test_onboarding_activation.py
  - tests/test_subscription_cli.py
  - tests/test_fabric_commands.py
  - tests/test_fabric_sync_service.py
autonomous: true
requirements:
  - QUICK-260910-F2H
estimate:
  tokens: 22000
  raw_tokens: 22000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - "Normal activation publishes its combined immutable generation beneath the configured source root, and the production source root is the exact deployment lakehouse OneLake URI under Files/aiops/inventory-source (D-01, D-07)."
    - "An operator can invoke `activate --replay-source-run-id <exact-id>` and publish exactly that persisted generation without connection enumeration, connection validation, connection discovery, or combined snapshot publication (D-02)."
    - "Replay calls the existing Fabric sync transaction directly with the exact requested generation and the activation-owned exposure pointer store, preserving table/ontology publication, Gold staging, the completed-version marker, shortcuts, and atomic pointer activation (D-03)."
    - "Replay never resolves `current` or another latest generation; an invalid, absent, or unreadable exact generation fails before Fabric publication and leaves the Exposure Gold pointer untouched (D-04)."
    - "Normal activation retains its existing result and progress behavior; replay retains the same terminal result keys while omitting upstream progress stages that did not run and streaming only truthful activation/Fabric lifecycle events (D-05)."
    - "FabricRuntimeConfig represents `source_data_root` as `Path | str`, resolves local paths relative to the config file, and preserves a valid OneLake URI without pathlib mangling (D-06)."
    - "All implementation and verification remain local and surgical: no Azure mutation, D4 execution stop, Job/profile/schedule change, or unrelated dirty Fabric Data Agent file access/change occurs (D-09, D-10)."
  artifacts:
    - path: "src/onboarding/activation.py"
      provides: "Normal durable snapshot publication plus exact-generation replay branch that preserves activation and pointer contracts"
    - path: "src/onboarding/cli.py"
      provides: "Exact replay argument parsing and forwarding through the existing activate command"
    - path: "src/fabric/config.py"
      provides: "Local Path or OneLake URI source-root configuration without URI corruption"
    - path: "fabric.config.deploy.yaml"
      provides: "Production combined-snapshot root in the existing workspace and lakehouse"
    - path: "tests/test_onboarding_activation.py"
      provides: "No-upstream-call, exact-generation, pointer-store, progress/result, and fail-closed replay regressions"
    - path: "tests/test_subscription_cli.py"
      provides: "Activate CLI exact replay argument forwarding and output compatibility coverage"
    - path: "tests/test_fabric_commands.py"
      provides: "Fabric runtime config local-path and OneLake-URI resolution coverage"
    - path: "tests/test_fabric_sync_service.py"
      provides: "Exact historical generation replay through the full Fabric/Gold/pointer transaction and missing-generation refusal"
  key_links:
    - from: "fabric.config.deploy.yaml"
      to: "src/fabric/config.py"
      via: "FabricRuntimeConfig.load preserves the configured abfss OneLake source root as a string"
      pattern: "source_data_root"
    - from: "src/onboarding/cli.py"
      to: "src/onboarding/activation.py"
      via: "activate forwards replay_source_run_id only when the operator supplies the exact CLI value"
      pattern: "replay_source_run_id"
    - from: "src/onboarding/activation.py"
      to: "storage.datasets.DatasetStore"
      via: "replay resolves the requested immutable generation directly and reads its manifest without consulting current_generation"
      pattern: "generation_path"
    - from: "src/onboarding/activation.py"
      to: "src/fabric/sync_service.py"
      via: "activate_runtime passes both replay_source_run_id and OneLakeDocumentStore(service.registry.root) to runtime.service.sync"
      pattern: "exposure_pointer_store"
    - from: "src/fabric/sync_service.py"
      to: "ExposureGoldFabricPublisher.activate"
      via: "existing transaction stages the exact replayed generation and activates the pointer only after publication, completed state, and shortcuts"
      pattern: "replay_source_run_id|_write_state|_create_shortcuts|activate"
---

<objective>
Persist normal activation's combined generations in durable OneLake storage and let an operator republish one exact generation without repeating Azure connection work (D-01, D-02, D-04).

Purpose: A failed or intentionally repeated Fabric publication must be recoverable from the exact immutable activation input while retaining the established Gold completion and pointer safety transaction (D-03, D-05).
Output: URI-safe Fabric source-root configuration, the production OneLake source root, exact activate replay, and focused local regression coverage (D-06, D-07, D-08).
</objective>

<execution_context>
@~/.copilot/gsd-core/workflows/execute-plan.md
@~/.copilot/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260909-032-add-stage-level-progress-logging-and-bou/260909-032-SUMMARY.md
@src/onboarding/activation.py
@src/onboarding/cli.py
@src/fabric/config.py
@src/fabric/runtime.py
@src/fabric/sync_service.py
@src/storage/fs.py
@src/storage/datasets.py
@src/storage/onelake_documents.py
@fabric.config.deploy.yaml
@tests/test_onboarding_activation.py
@tests/test_subscription_cli.py
@tests/test_fabric_commands.py
@tests/test_fabric_sync_service.py

This is source-only parallel work (D-09, D-10). Do not invoke Azure CLI, Fabric/Azure APIs, Terraform, deployment scripts, Container Apps Job commands, schedule/profile commands, or networked tests. Do not stop or otherwise interact with the current D4 execution. Before each commit, stage only the files named by the current task and inspect `git diff --cached --name-only`; never stage or edit pre-existing dirty `.azure` files, `infra/terraform/fabric.tf`, Fabric Data Agent/Gold-grounding files, or any other unrelated working-tree path.

The prior progress quick task established the exact progress schema and publication ordering. Replay should omit `connection_validation`, `connection_discovery`, and `combined_snapshot` events because those operations do not execute; do not add a new status to the closed progress vocabulary. Keep `activation`, `fabric_publication`, downstream Fabric stages, table progress, sanitized `ActivationFailure`, stderr JSON Lines, and terminal stdout JSON behavior unchanged.

<interfaces>
From `src/storage/fs.py`:
- `is_onelake_uri(root: object) -> bool`
- `resolve_root(root: str) -> Path | str` preserves an `abfss://`/`abfs://` OneLake URI and resolves a local path.
- `resolve_fs(root: str) -> tuple[Any, str]` validates the OneLake host and supplies the filesystem used by DatasetStore/FabricSyncService.

From `src/storage/datasets.py`:
- `DatasetStore(root: Path | str)` supports local and OneLake roots.
- `publish(...) -> dict[str, Any]` writes `generations/<runId>` and atomically updates `current`/`current.json`.
- `generation_path(generation_id: str) -> Path | str | None` validates one safe generation segment and resolves only that immutable generation.
- `current_generation()` is intentionally not part of exact replay.

From `src/fabric/sync_service.py`:
- `FabricSyncService.sync(*, replay_source_run_id: str = "", progress_callback=None, stage_progress_callback=None, exposure_pointer_store: OneLakeDocumentStore | None = None) -> FabricSyncResult`
- A non-empty `replay_source_run_id` resolves `generations/<exact-id>`; `exposure_pointer_store` enables the established Exposure Gold stage/finalize/activate path.

From `src/onboarding/activation.py`:
- `activate_runtime(service, *, fabric_config, connection_ids=None, progress_callback=None, heartbeat_interval=60.0, progress_clock=time.monotonic, progress_wait=None) -> dict[str, Any]`
- Existing terminal keys are `status`, `connections`, `validations`, `discovery_syncs`, `combined_snapshot`, `fabric_publication`, `ontology_version`, and `freshness`.
</interfaces>
</context>

<source_audit>
| Source | ID | Feature/requirement | Plan | Status | Notes |
|---|---|---|---|---|---|
| GOAL | — | Persist combined activation snapshots in OneLake and replay one exact generation without repeating upstream work while preserving the full Fabric/Gold activation transaction | 01 | COVERED | Tasks 1–2 |
| REQ | QUICK-260910-F2H | Durable combined snapshots and exact activation replay | 01 | COVERED | Tasks 1–2 |
| RESEARCH | — | `storage.fs.resolve_root` preserves OneLake URIs while pathlib mangles them; DatasetStore and FabricSyncService already support local/remote roots | 01 | COVERED | Task 1 reuses these seams |
| RESEARCH | — | `DatasetStore.generation_path` validates one exact generation segment; `current_generation` is the latest-pointer path and must not be used for replay | 01 | COVERED | Task 1 |
| RESEARCH | — | `FabricSyncService.sync` already accepts exact replay ID plus `exposure_pointer_store`; the generic Fabric CLI does not supply the pointer store | 01 | COVERED | Task 1 calls the service through activation |
| RESEARCH | — | Existing sync tests prove shortcuts/completed state precede pointer activation, but exact historical replay lacks full-transaction coverage | 01 | COVERED | Task 2 |
| CONTEXT | D-01 | Normal activate persists combined snapshots under durable production OneLake source root | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-02 | Exact activate replay skips validation, discovery, and combined publication, then runs Fabric sync | 01 | COVERED | Task 1 |
| CONTEXT | D-03 | Replay forwards exposure pointer store and preserves all normal Fabric/Gold finalization side effects | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-04 | Exact ID only; no latest fallback; missing/unreadable generation fails closed | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-05 | Preserve normal activation and terminal/progress contracts; replay telemetry is truthful | 01 | COVERED | Task 1 |
| CONTEXT | D-06 | FabricRuntimeConfig supports local Path or OneLake URI using storage.fs patterns | 01 | COVERED | Task 1 |
| CONTEXT | D-07 | Deploy config uses existing workspace/lakehouse URI under Files/aiops/inventory-source | 01 | COVERED | Task 2 |
| CONTEXT | D-08 | Focused CLI/config/activation tests cover upstream skips, exact forwarding, pointer forwarding, and fail-closed absence | 01 | COVERED | Tasks 1–2 |
| CONTEXT | D-09 | No Azure mutation, D4 stop, or Job/profile/schedule changes; no unrelated dirty Fabric Data Agent files | 01 | COVERED | Context fence and local-only verification |
| CONTEXT | D-10 | Source-only surgical parallel work with atomic conventional commits | 01 | COVERED | Two scoped TDD commits; planning artifact is not bundled with source commits |
</source_audit>

<dependency_graph>
1. Task 1 is the production-quality tracer: it creates URI-safe source configuration and one exact replay route from CLI through activation to the existing Fabric transaction, with local fake-service tests proving all critical arguments and observable contracts.
2. Task 2 expands the tracer to the production deployment root and executes the real local FabricSyncService transaction against an older exact generation, proving the existing publication/finalization/pointer behavior and missing-generation refusal.
3. Task 2 depends on Task 1's `Path | str` config contract and replay entry point. The tasks stay in one plan because they share the exact source-root/replay contract and must land atomically without exposing a production URI before the runtime can preserve it.
</dependency_graph>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Replay one exact persisted activation generation end to end</name>
  <files>src/fabric/config.py, src/onboarding/activation.py, src/onboarding/cli.py, tests/test_onboarding_activation.py, tests/test_subscription_cli.py</files>
  <reversibility rating="costly">The activation CLI/result and progress contracts are consumed by operational scripts, so undo requires coordinated source and regression changes.</reversibility>
  <behavior>
    - A local relative `source_data_root` still resolves relative to the Fabric config file and remains a `Path`; an absolute local root remains a resolved `Path` (D-05, D-06).
    - A valid OneLake `abfss://...@onelake.dfs.fabric.microsoft.com/...` source root remains an unchanged, trailing-slash-normalized string rather than becoming a local `abfss:/...` path (D-06).
    - Normal activation still enumerates selected/active connections, validates and discovers each one, publishes one combined DatasetStore generation into `config.source_data_root`, passes its generated run ID and `OneLakeDocumentStore(service.registry.root)` to Fabric sync, emits the existing upstream stages, and returns the existing terminal shape (D-01, D-03, D-05).
    - `activate --replay-source-run-id exact-generation` forwards that exact value to `activate_runtime`; omitting the option retains normal activation (D-02, D-04).
    - Replay loads the configured source root, validates and resolves only `generations/exact-generation`, reads its manifest, and calls the existing runtime service with `replay_source_run_id="exact-generation"` plus the same activation-owned pointer store (D-02, D-03, D-04).
    - Replay does not call registry active-list enumeration, service validation, service discovery sync, or `publish_combined_snapshot`; tests install fail-on-call doubles for every upstream boundary (D-02, D-08).
    - Replay returns the same terminal keys as normal activation. `connections` comes from the persisted manifest's `sourceConnectionIds`, `validations` and `discovery_syncs` are empty mappings, and `combined_snapshot` is the persisted manifest; Fabric publication, ontology version, and freshness use the normal runtime results (D-05).
    - Replay emits `activation`, `fabric_publication`, downstream Fabric lifecycle/table events, and terminal completion/failure only. It emits no validation, discovery, or combined-snapshot event because those operations did not run (D-05).
    - Unsafe, missing, malformed, or unreadable exact generations raise the existing sanitized `ActivationFailure`, do not call Fabric sync, and do not consult the active/current pointer (D-04, D-08).
  </behavior>
  <action>Start with failing tests. In `src/fabric/config.py`, change only `FabricRuntimeConfig.source_data_root` to `Path | str` and introduce a source-root resolver that delegates OneLake detection/preservation to `storage.fs.is_onelake_uri`/`resolve_root` while retaining `_resolve_path(config_path.parent, ...)` for local values. Do not broaden `local_onelake_root` or lifecycle catalog types. Keep URI validation at the existing DatasetStore/FabricSyncService `resolve_fs` boundary, avoiding credential creation during config parsing.

Add `--replay-source-run-id` to the existing `activate` parser and forward it directly into `activate_runtime`; do not route replay through `FabricCommandService` because that path does not provide the Exposure pointer store (D-03). Extend `activate_runtime` with a default-empty keyword parameter. Load FabricRuntimeConfig once before the normal/replay branch. In normal mode, preserve the current connection selection, validation/discovery loop, combined publication, event order, values, and terminal result unchanged (D-01, D-05).

In replay mode, require the supplied non-empty exact ID, construct `DatasetStore(config.source_data_root)`, call `generation_path(exact_id)`, and fail if it returns no immutable generation. Read that generation's manifest with the existing local/remote-aware manifest helper and reject invalid/unreadable content before building or invoking Fabric publication. Do not call `current_generation`, active connection listing, `service.validate`, `service.sync`, or `publish_combined_snapshot` on this branch (D-02, D-04). Start `fabric_publication`, build the runtime, and call `runtime.service.sync` with the exact CLI value, existing progress adapters, and `OneLakeDocumentStore(service.registry.root)` exactly as normal activation does (D-03). Build the established result keys from persisted manifest provenance and publication/semantic output, with empty upstream-result mappings. Keep exception sanitization and stdout/stderr behavior intact. Use atomic conventional TDD commits for RED and GREEN, staging only this task's five files (D-09, D-10).</action>
  <verify>
    <automated>uv run pytest -q tests/test_onboarding_activation.py tests/test_subscription_cli.py &amp;&amp; uv run ruff check src/fabric/config.py src/onboarding/activation.py src/onboarding/cli.py tests/test_onboarding_activation.py tests/test_subscription_cli.py</automated>
  </verify>
  <done>Normal activation remains contract-compatible, while exact replay reaches the existing Fabric transaction with the requested immutable generation and pointer store, no upstream call occurs, missing/unreadable input fails before publication, and progress never claims skipped work ran (D-01 through D-06, D-08).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Bind production storage and prove full exact-replay finalization</name>
  <files>fabric.config.deploy.yaml, tests/test_fabric_commands.py, tests/test_fabric_sync_service.py, tests/test_onboarding_activation.py</files>
  <reversibility rating="costly">Changing the production snapshot root after generations exist requires coordinated retention or data movement and deploy-config rollback.</reversibility>
  <behavior>
    - `fabric.config.deploy.yaml` uses `abfss://1c328da7-2490-48dc-9ba6-de8c1f333756@onelake.dfs.fabric.microsoft.com/6317eaf6-e597-4b4e-a07d-c53027c01feb/Files/aiops/inventory-source` with no secret material (D-01, D-07).
    - A focused config test proves the deployment-shaped URI loads byte-for-byte apart from trailing-slash normalization, and an existing local-path case still resolves to `Path` (D-06, D-07, D-08).
    - Given two immutable local source generations where the second is active/current, `FabricSyncService.sync(replay_source_run_id=first_id, exposure_pointer_store=...)` reads and reports the first generation, never the second (D-03, D-04).
    - Exact replay performs the existing normal table publication, ontology publication, Gold staging/writes, Fabric registration/catalog, shortcut finalization, completed ingestion-state marker, and final Exposure pointer activation; the result has `replay=True` and the exact source run ID (D-03).
    - Given a valid active/current generation plus a nonexistent requested ID, sync fails instead of falling back to active/current, publishes no completed marker for that attempt, and leaves a fresh pointer store empty (D-04, D-08).
    - Activation's missing and unreadable exact-generation tests assert that the Fabric service and pointer activation boundary are never reached (D-04, D-08).
  </behavior>
  <action>Write focused regressions first. In `tests/test_fabric_commands.py`, add FabricRuntimeConfig loading tests for both a local path and a OneLake URI without touching the already-dirty `tests/test_fabric_client.py` (D-09). Assert value and runtime type, not implementation internals. Change only `fabric.config.deploy.yaml`'s `source_data_root` to the exact existing workspace/lakehouse URI in the behavior block (D-01, D-07); retain all auth, capacity, publication, Gold, shortcut, and scheduling-related configuration unchanged.

In `tests/test_fabric_sync_service.py`, use the existing local OneLakeWriter/DeltaWriter service factory and DatasetStore fixtures to create distinguishable immutable source generations. Keep the later generation active, invoke the real `FabricSyncService.sync` with the earlier exact ID and a real local `OneLakeDocumentStore`, and assert the existing transaction publishes facts from the earlier source, records replay/exact source identity, writes the completed ontology-version marker, finalizes shortcuts through the established hook, and activates the Exposure pointer last (D-03, D-04). Add the converse missing-ID test with a valid current generation to prove there is no fallback; assert no completed row for the failed invocation and no pointer document. Do not change `src/fabric/runtime.py` or `src/fabric/sync_service.py` unless a failing behavior test demonstrates a real defect in their already-present `Path | str`, exact resolver, or pointer transaction; if a defect is proven, keep the fix within those existing interfaces and add the source file to the scoped commit explicitly.

Complete `tests/test_onboarding_activation.py` fail-closed coverage for malformed/unreadable exact manifests and prove no runtime sync call or pointer write occurs. Run only local tests and lint. Create atomic conventional RED/GREEN commits containing this task's files only; use `git diff --cached --name-only` before each commit and preserve every unrelated dirty/untracked path (D-09, D-10).</action>
  <verify>
    <automated>uv run pytest -q tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py &amp;&amp; uv run ruff check src/fabric/config.py src/onboarding/activation.py src/onboarding/cli.py tests/test_fabric_commands.py tests/test_fabric_sync_service.py tests/test_onboarding_activation.py tests/test_subscription_cli.py &amp;&amp; git diff --check</automated>
  </verify>
  <done>The deploy profile stores combined snapshots in the exact durable OneLake root, config preserves local and remote roots correctly, and a real local Fabric transaction proves exact historical replay retains every established completion/shortcut/Gold/pointer effect while a missing or unreadable requested generation fails closed without latest fallback (D-01, D-03, D-04, D-06 through D-10).</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|---|---|
| CLI operator → activation replay | The requested generation is untrusted path input and must remain one safe immutable generation segment. |
| Fabric config → local/OneLake storage | A OneLake URI must not be interpreted as a container-local path or redirected to a non-OneLake host. |
| Persisted generation → Fabric publisher | Missing, malformed, or unreadable manifests must fail before consequential publication. |
| Activation → Fabric sync | The exact replay ID and Exposure pointer store must cross together; omitting either changes recovery or activation semantics. |
| Fabric finalization → Exposure pointer | Pointer activation is authority-changing and must remain after tables, ontology, Gold, shortcuts, and the completed marker. |
| Parallel source work → dirty repository | Scoped commits must not absorb unrelated Fabric Data Agent, Terraform, `.azure`, or live-operation changes. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|---|---|---|---|---|---|
| T-F2H-01 | Tampering | replay generation ID | high | mitigate | Resolve with DatasetStore.generation_path safe-segment validation and add traversal/missing-ID tests; never join unchecked path text. |
| T-F2H-02 | Spoofing | latest/current generation | high | mitigate | Replay always addresses `generations/<exact-id>` and tests keep a different current generation to prove no fallback. |
| T-F2H-03 | Tampering | source_data_root parsing | high | mitigate | Preserve only recognized OneLake URI schemes through storage.fs and retain config-relative Path resolution for local roots; test both types. |
| T-F2H-04 | Information disclosure | deploy configuration and terminal failure | medium | mitigate | Store only the non-secret OneLake URI; retain sanitized ActivationFailure and existing bounded progress/result fields. |
| T-F2H-05 | Elevation of privilege | Exposure Gold pointer | high | mitigate | Always pass activation's OneLakeDocumentStore to the existing sync transaction and verify pointer activation remains last. |
| T-F2H-06 | Repudiation | replay provenance | medium | mitigate | Preserve exact source_run_id/replay state, completed marker, Fabric publication result, and immutable source manifest in the terminal result. |
| T-F2H-07 | Denial of service | unreadable remote generation | medium | mitigate | Fail before projection/publication, without retrying another generation or repeating Azure discovery. |
| T-F2H-08 | Tampering | parallel dirty working tree | high | mitigate | Stage explicit task file lists, inspect cached names before commits, and prohibit all unrelated dirty paths. |
| T-F2H-SC | Tampering | package-manager installs | low | accept | No dependency or package-manager operation is planned. |
</threat_model>

<verification>
Execute both task-level commands locally. Then run `git status --short` and `git diff --cached --name-only` to prove commits contain only planned files; compare the final dirty-path list with the pre-task list and leave unrelated entries unchanged. Do not run full tests that require live credentials, Azure/Fabric commands, Terraform, deployment scripts, Job/profile/schedule operations, or any D4 process action (D-09, D-10).
</verification>

<success_criteria>
- Normal activation writes the combined immutable generation through DatasetStore at a URI-safe configured source root, and production config names the exact existing OneLake workspace/lakehouse path (D-01, D-06, D-07).
- Exact activate replay makes zero validation/discovery/recombination calls and forwards the operator's exact ID plus activation's pointer store to Fabric sync (D-02, D-03, D-08).
- A different current generation cannot influence replay; unsafe, absent, malformed, or unreadable exact input fails before publication and pointer activation (D-04).
- Replay preserves table and ontology publication, Gold staging/writes, completed-version state, shortcut finalization, and final atomic pointer activation (D-03).
- Normal result/progress behavior remains unchanged; replay returns the same terminal keys and emits no false upstream progress (D-05).
- Focused CLI, config, activation, and sync tests plus Ruff and diff checks pass locally without cloud interaction or unrelated file changes (D-08, D-09, D-10).
</success_criteria>

<output>
Create `.planning/quick/260910-f2h-persist-combined-activation-snapshots-in/SUMMARY.md` when done.
</output>
