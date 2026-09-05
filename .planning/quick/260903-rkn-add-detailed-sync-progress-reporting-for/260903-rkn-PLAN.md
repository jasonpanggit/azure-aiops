---
quick_task: 260903-rkn
type: execute
scope: "Detailed progress reporting for Fabric table writes"
autonomous: true
files_modified:
  - src/fabric/sync_service.py
  - src/onboarding/runtime.py
  - src/onboarding/sync.py
  - web/src/lib/types.ts
  - web/src/app/connections/page.tsx
  - tests/test_subscription_onboarding.py
  - tests/test_fabric_sync_service.py
  - web/src/app/connections/page.test.tsx
---

<objective>
Replace the opaque `writing_fabric_tables (85%)` status with live, persisted
table-write progress such as `Writing Fabric tables: 17/42 tables written
(89%)`, while retaining useful stage text until the background sync reaches a
terminal state.

The root cause is a contract gap: `ConnectionSyncCoordinator.run()` emits the
single `writing_fabric_tables` callback at 85% immediately before
`_InventoryRefreshRunner.run()` calls `FabricSyncService.sync()`, but
`FabricSyncService` writes tables concurrently without exposing completion
events. The coordinator therefore has no intermediate message or count to
persist, and the UI only renders the static stage and percentage.
</objective>

<context>
- `.planning/STATE.md` says Phase 10 is complete and explicitly notes that
  long synchronous inventory refreshes can outlive HTTP streams; this quick
  task is narrowly limited to observability, not changing sync ownership,
  timeout behavior, or Fabric publication semantics.
- Preserve all current working-tree changes, especially the existing
  uncommitted changes in `src/onboarding/sync.py`, `src/onboarding/config.py`,
  `src/onboarding/discovery_source.py`, `src/intelligence/patch/patch_intelligence.py`,
  `tests/test_patch_v2_hardening.py`, and `web/src/app/globals.css`.
- Existing contracts: `SyncState` already persists `stage`,
  `stage_message`, and `progress_pct`; `GET /{connection_id}/health` already
  returns that state; `connections/page.tsx` already polls it every 1.5s for
  up to 20 minutes.
</context>

<dependency_graph>

1. `FabricSyncService.sync()` / `_sync_locked()` needs a progress callback and
   emits completed-table events from the `as_completed()` loop.
2. `_InventoryRefreshRunner` passes that callback into `FabricSyncService.sync()`;
   `ConnectionSyncCoordinator` supplies the callback that converts write
   events into persisted `SyncState`.
3. Backend tests establish callback ordering/counts and persisted messages before
   frontend tests assert the rendered copy and terminal-state behavior.

</dependency_graph>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Emit completed Fabric table-write progress from the publisher</name>
  <files>src/fabric/sync_service.py, src/onboarding/runtime.py, tests/test_fabric_sync_service.py</files>
  <behavior>
    - A successful table write emits one event after its `DeltaWriteResult` is
      recorded, with the completed count, total table count, table name, and
      write result available to the caller.
    - Concurrent completion order is accepted, but the completed count is
      monotonic and never exceeds the total.
    - A failed table write does not falsely increment the completed count;
      existing error collection and rollback behavior remains unchanged.
    - The existing no-argument publisher adapter remains compatible for callers
      that do not provide a progress callback.
  </behavior>
  <action>
    Add an optional, typed progress callback to `FabricSyncService.sync()` and
    `_sync_locked()` and invoke it from the `as_completed(futures)` loop in
    `src/fabric/sync_service.py` after each successful `table_results` insertion.
    Define the event payload explicitly (for example
    `completed_tables`, `total_tables`, `table_name`, and `DeltaWriteResult`)
    rather than making callers inspect private executor state. Count the exact
    `datasets.items()` write set, including any already-established
    `metadata_source_status` handling according to the service's actual write
    path; do not count a table before its write succeeds. Keep callback
    exceptions from changing the sync outcome, matching the existing
    best-effort progress convention.

    Extend `_InventoryRefreshRunner` in `src/onboarding/runtime.py` to accept
    the optional callback and pass it to `build_runtime(fabric_config).service.sync()`.
    Keep `fabric_publication` result construction and all existing runtime
    arguments unchanged. Add focused unit coverage in
    `tests/test_fabric_sync_service.py` (create the file only if the repository
    has no suitable existing Fabric service test module) using a fake Delta
    writer/publisher to prove successful concurrent writes, failure behavior,
    total calculation, and callback-exception isolation.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_fabric_sync_service.py tests/test_inventory_fabric_contract.py</automated>
  </verify>
  <done>
    Fabric publication exposes deterministic, successful-write-only progress
    events without changing table contents, write modes, rollback, or terminal
    result behavior.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Persist detailed counts and useful active status through connection sync</name>
  <files>src/onboarding/sync.py, src/onboarding/runtime.py, tests/test_subscription_onboarding.py</files>
  <behavior>
    - Once Fabric writes begin, persisted `SyncState.stage` remains
      `writing_fabric_tables` and `stage_message` identifies the completed
      count, total, and most recently completed table.
    - `progress_pct` advances monotonically from the existing 85% baseline to
      below 100% while writes remain active, then the existing terminal
      callback sets 100%.
    - A long-running publisher produces observable intermediate state through
      `service.detail()` / `health_report()` rather than leaving the state at
      one static 85% message.
    - A failed or timed-out publish still reaches the existing failed terminal
      state and does not report all tables written.
  </behavior>
  <action>
    In `src/onboarding/sync.py`, make the publish adapter callback-aware while
    preserving the current uncommitted daemon-thread timeout implementation.
    Have the coordinator translate each Fabric write event into a message such
    as `Writing Fabric tables: {completed}/{total} tables written (latest:
    {table_name})`, retaining `stage="writing_fabric_tables"` and mapping the
    active interval between the existing 85% report and terminal 100% without
    reaching 100% early. Persist each update through the existing
    `_save_operation_state()` path, tolerate registry conflict/callback errors
    as existing progress code does, and ensure the callback is bound to the
    current `run_id` so stale updates cannot overwrite a newer run. If the
    publisher has no table events (empty input or an early failure), retain an
    honest count such as `0/0` or `0/{total}` and the existing failure message.

    Update `tests/test_subscription_onboarding.py` with a publisher fake that
    emits multiple write events (including a blocked event to inspect state
    while active), then assert persisted stage, message, monotonic percentage,
    run identity, final success, and timeout/failure behavior. Add a regression
    for callback errors not breaking the underlying sync. Do not alter the
    existing timeout default or the user's concurrent changes.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_subscription_onboarding.py tests/test_ontology_publish_durability.py</automated>
  </verify>
  <done>
    The health API's existing `sync` object reports truthful written/total
    counts and a changing in-progress message throughout Fabric writes, while
    terminal success/failure and timeout semantics remain unchanged.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Render detailed active progress in the connections UI</name>
  <files>web/src/lib/types.ts, web/src/app/connections/page.tsx, web/src/app/connections/page.test.tsx</files>
  <behavior>
    - A running state with `stage_message` renders that message and its current
      percentage; it does not reduce the display to the opaque stage key.
    - The UI continues to render a useful fallback for older/null
      `stage_message` or `progress_pct` responses.
    - Poll updates replace the displayed message/counts, and terminal success
      still shows the existing completion message and record count.
    - Failed state continues to use the critical callout and displays the
      server-provided failure text without unsafe HTML interpretation.
  </behavior>
  <action>
    Extend `SyncState` in `web/src/lib/types.ts` only as needed to mirror the
    backend event/state contract (counts should be numeric and nullable where
    older persisted records may omit them). In
    `web/src/app/connections/page.tsx`, update the callout rendering near the
    existing `Sync in progress` text to prefer `stage_message`, append the
    current percentage when present, and use a readable stage-derived fallback
    when it is absent. Preserve the current polling interval, 20-minute
    deadline, terminal detection, error precedence, accessibility `role=status`,
    and existing completed/failed wording. Use plain React text interpolation,
    not HTML injection.

    Add cases to `web/src/app/connections/page.test.tsx` with mocked
    `connectionsApi.sync` and sequential `health` responses proving the exact
    `Writing Fabric tables: 3/12 tables written` copy updates while a sync is
    active, fallback rendering for legacy state, and terminal success/failure
    behavior. Keep tests deterministic by using fake timers or a controlled
    health promise rather than waiting for the full polling timeout.
  </action>
  <verify>
    <automated>cd web && npm test -- --run src/app/connections/page.test.tsx && npx tsc --noEmit</automated>
  </verify>
  <done>
    Operators watching `/connections` see live written/total Fabric table
    progress and meaningful in-progress copy until the existing terminal
    result is reached, with backward-compatible and accessible rendering.
  </done>
</task>

</tasks>

<edge_cases>
- Zero tables: render a truthful `0/0` or an explicit no-table message and do
  not divide by zero or jump to terminal progress.
- One table: first successful completion must remain below terminal 100% until
  the publisher/coordinator emits its normal terminal event.
- Concurrent writes: events may arrive in any table order; counts, not table
  ordering, are authoritative.
- Partial failure and timeout: show the last successful count plus failure
  reason; never claim all tables were written.
- Empty or missing legacy `stage_message`, counts, or percentage: preserve a
  readable stage fallback and current polling behavior.
- Multiple runs / stale callbacks: only the active `run_id` may update its
  persisted state.
- Callback/persistence failure: telemetry/logging may record it, but progress
  reporting must never abort or alter the Fabric sync itself.
</edge_cases>

<verification>
Run the focused backend tests, focused frontend test, and TypeScript check from
the task verifies. Then run the broader relevant suites:

`uv run pytest -q tests/test_subscription_onboarding.py tests/test_ontology_publish_durability.py tests/test_inventory_fabric_contract.py`

`cd web && npm test -- --run src/app/connections/page.test.tsx && npx tsc --noEmit`

Inspect `git diff --check` and `git status --short` to confirm only the planned
product/test files changed and all pre-existing user modifications remain
untouched. No product code is changed by this planning task and no commit is
requested here.
</verification>

