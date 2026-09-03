---
status: resolved
trigger: "Retest deployed /connections Fabric Medallion page: Bronze, Silver, and Gold render 0/0 despite Phase 10 expecting Bronze 18/18 and Silver 21/21."
created: 2026-09-02T13:58:32Z
updated: 2026-09-02T14:46:00Z
---

## Symptoms

- Expected: The selected subscription shows live Bronze/Silver/Gold layer counts from the Phase 10 rollout.
- Actual: The authenticated deployed page shows Bronze 0/0, Silver 0/0, and Gold 0/0 with no datasets registered.
- Errors: None in the browser console; authenticated `/layers` returns HTTP 200.
- Timeline: Observed during the 2026-09-02 live retest after the earlier Phase 10 validation.
- Reproduction: Open `/connections`, select `Fabric Medallion`, select subscription `demo`, and click `Refresh Fabric health`.

## Current Focus

- reasoning_checkpoint:
    hypothesis: "The sync publisher hard-codes every metadata_source_status row to system scope, so subscription-scoped /layers requests discard all generated Bronze/Silver/Gold status rows even though their data tables were written."
    confirming_evidence:
      - "`_table_source_status_rows()` was directly observed emitting subscription_id=system and requested_scope_json={} for mapped tables whose data rows carry sub-1."
      - "The route's scope matcher uses requested_scope_json first, so a selected subscription such as demo cannot match those rows; the route then reports 0/0 while manifest and ingestion endpoints still succeed."
      - "The sync writer and route fallback resolve the same metadata_source_status Delta table, and the focused existing sync/API tests pass because API rows are hand-authored as scoped and sync tests do not assert publisher scope."
    falsification_test: "Generate a sync source-status row with an explicit subscription scope and call the real scoped /layers route; if the row remains invisible or the route still returns zero, the publisher scope is not the root cause."
    fix_rationale: "Pass the subscriptions selected by the multi-connection refresh into sync and publish one status row per table/subscription, preserving per-row identities and assigning empty tables to the requested subscription so scope filtering can see healthy-empty datasets."
    blind_spots: "The browser session was not re-authenticated after deployment, so live verification used an Azure CLI bearer token against the protected route."
    candidate_causes:
      - "code: source-status publisher overwrites dataset scope with system identities"
      - "config: a workspace/lakehouse mismatch could make the route read a different Delta table"
      - "environment: deployed registry/connection state could be absent or stale"
      - "data: the selected subscription could genuinely have no Bronze/Silver rows"
    and_gate: "no — the observed 0/0 requires only the publisher's scope defect because the route and writer agree on the table URI; config/environment/data alternatives were checked as independent alternatives, not required co-factors."
  hypothesis: "The sync publisher hard-codes every metadata_source_status row to system scope, so subscription-scoped /layers requests discard all generated Bronze/Silver/Gold status rows."
  test: "The fix-acceptance guardrail and full regression suite have completed; request end-to-end confirmation from the deployed Fabric Medallion workflow."
  expecting: "A deployed refresh writes subscription-scoped metadata_source_status rows and the selected subscription renders the Bronze/Silver/Gold counts rather than 0/0."
  next_action: "Resolved by deploying the scoped publisher fix and verifying the protected live route."

## Evidence

- timestamp: 2026-09-02T14:03:00Z
  source: repository knowledge base and planning configuration
  observation: "No prior knowledge-base entry matches the Fabric Medallion layer-count symptom; the active Phase 10 scope is complete and explicitly includes the route fallback, early source-status publication, and scope preservation."
  implication: "Treat this as a new deterministic/configuration investigation and verify the Phase 10 implementation directly rather than assuming the prior topology rollout cause."

- timestamp: 2026-09-02T14:08:00Z
  source: route and UI implementation
  observation: "`/layers` derives its table set only from scoped metadata_source_status rows; the UI independently uses capabilities lineage only to load dataset detail cards. The route first reads per-connection JSON snapshots and only falls back to the configured lakehouse Delta table when the combined snapshot rows are empty."
  implication: "A successful manifest/ingestion response does not prove the layer source rows are visible; the fault can be isolated to source-status storage, Delta URI resolution, or subscription filtering."

- timestamp: 2026-09-02T14:08:00Z
  source: route and scope implementation
  observation: "Scope attributes prefer requested_scope/requested_scope_json values and only use subscription_id/subscription_connection as fallback. The working-tree route change always overwrites those two identity fields from the current connection registry, but it does not rewrite a stale requested_scope_json."
  implication: "Stale requested_scope_json is a candidate filtering defect, but it remains unconfirmed until the published row shape and selected subscription identity are observed."

- timestamp: 2026-09-02T14:13:00Z
  source: sync publication implementation
  observation: "`_table_source_status_rows()` emits every generated dataset status row with `tenant_id=system`, `subscription_id=system`, and `requested_scope_json={}`, while `/layers` applies the requested subscription scope to those rows."
  implication: "A selected subscription such as `demo` cannot match these rows: `_row_visible()` sees the `system` fallback identity, so every Bronze/Silver/Gold status row is excluded and the route returns 0/0."

- timestamp: 2026-09-02T13:57:03Z
  source: authenticated browser
  observation: "Fabric Medallion tab rendered and selected subscription demo."
- timestamp: 2026-09-02T13:57:03Z
  source: browser network response
  observation: "/layers returned 200 with Bronze/Silver/Gold all 0/0 and empty evidence timestamp."
- timestamp: 2026-09-02T13:57:03Z
  source: browser network response
  observation: "/manifest returned 200 with 15 entries; /ingestion-history returned a succeeded run."
- timestamp: 2026-09-02T13:58:32Z
  source: authenticated browser
  observation: "Clicking Refresh Fabric health did not change the 0/0 layer result."

- timestamp: 2026-09-02T14:27:00Z
  source: local mapped snapshot and sync publisher
  observation: "The mapper produced 357 datasets; populated Bronze/Silver rows carried sub-1, but `_table_source_status_rows()` emitted 356 status rows all with subscription_id=system and requested_scope_json={} including empty tables."
  implication: "The defect is in publication scope, and empty-table handling must be included in the fix or healthy-empty datasets will remain absent for scoped requests."

- timestamp: 2026-09-02T14:27:00Z
  source: focused existing tests and deployment configuration
  observation: "The focused existing test selection passed (38 tests). The deployment image copies fabric.config.deploy.yaml to the configured `/app/fabric.config.yaml`; its workspace/lakehouse IDs match the route/writer configuration path, with no URI mismatch evidence."
  implication: "Existing tests provide a regression baseline but do not cover publisher scope; deployment wiring is not the leading cause."

- timestamp: 2026-09-02T14:29:00Z
  source: test harness direct probe
  observation: "A standalone route import failed because the shell lacked the test/runtime module path for `agents.operations`; this is a harness invocation issue, not an application assertion, since the same route tests passed through pytest."
  implication: "Use pytest for route verification and do not treat the standalone import failure as evidence against the scope diagnosis."

- timestamp: 2026-09-02T14:36:00Z
  source: new scoped route regression
  observation: "The generated scoped rows were registered by the route (Bronze and Silver total each became 1), but the fixed-date test rows were classified unhealthy because their freshness was stale in the current clock."
  implication: "The scope fix is exercising the intended route path; make the test timestamp current so it asserts scope visibility rather than freshness behavior."

- timestamp: 2026-09-02T14:48:00Z
  source: fix-acceptance revert-and-reconfirm
  observation: "Only the five fix files were stashed and restored, preserving unrelated working-tree changes. The new scoped route test was absent while reverted, and restoring the stash reinstated it; the full incremental-sync, multi-connection, and API suites passed after reapplication."
  implication: "The fix is isolated from unrelated user changes; a direct pre-fix publisher probe is still run below to record the actual bug-returning output."

- timestamp: 2026-09-02T14:55:00Z
  source: fix-acceptance revert-and-reconfirm publisher probe
  observation: "With only `src/fabric/sync_service.py` reverted, the publisher emitted `[('bronze_resources', 'system', '{}', 1), ('silver_incidents', 'system', '{}', 0)]`; after restoring the fix, the same input emits subscription-scoped rows when requested scope is supplied."
  implication: "The defect returns when the publisher change is removed and disappears when reapplied, satisfying the causal revert-and-reconfirm signal."

- timestamp: 2026-09-02T15:00:00Z
  source: restored targeted and touched test suites
  observation: "The scoped publisher, empty-table, multi-connection propagation, and generated-row route regressions passed; the complete touched incremental-sync, multi-connection, and API suites also passed. Ruff and git diff checks passed."
  implication: "The fix is behaviorally covered across publication, orchestration, route filtering, and adjacent touched functionality."

- timestamp: 2026-09-02T15:10:00Z
  source: held-out repository regression suite
  observation: "The full repository suite passed: 2267 tests passed with 7 dependency warnings in 107.78 seconds."
  implication: "No unrelated regression was detected in the complete available automated suite."

- timestamp: 2026-09-02T14:45:00Z
  source: deployed API with Azure CLI bearer token
  observation: "After deployment, /api/v1/fabric-medallion/layers returned HTTP 200 with Bronze 18/18, Silver 21/21, and Gold 0/0."
  implication: "The deployed scope-propagation fix restored the expected Phase 10 live layer counts."

## Eliminated

## Resolution

root_cause: "The Fabric sync source-status publisher discarded dataset and refresh scope by hard-coding subscription_id=system and requested_scope_json={}; subscription-scoped /layers filtering therefore excluded every generated Bronze/Silver/Gold status row."
fix: "Propagate the successful connection subscriptions from multi-connection orchestration into FabricSyncService.sync(), emit one scoped metadata_source_status row per table/subscription (including empty tables and multi-subscription row counts), and retain the legacy key for the first scoped row to replace stale pre-fix system rows."
verification:
  target_test:
    result: pass
    details: "Scoped publisher, empty-table, multi-connection propagation, and generated-row /layers regressions passed."
  mutation_check:
    result: skipped
    reason_if_skipped: "No Stryker or Python mutation-testing tool is configured in this repository."
    mutant_killed: null
  no_op_deletion:
    result: pass
    deletion_justified_by_rca: false
    details: "The fix is additive scope propagation and per-subscription status publication; no behavior-deleting hunk was introduced."
  adjacent_tests:
    result: pass
    suites_run:
      - "tests/test_incremental_sync.py"
      - "tests/test_inventory_refresh_multi_connection.py"
      - "tests/test_api_http.py"
      - "full repository pytest suite: 2267 passed"
  revert_and_reconfirm:
    result: pass
    bug_returned_on_revert: true
    fixed_on_reapply: true
    details: "Reverting only the publisher emitted system-scoped populated and empty rows; restoring it emitted requested subscription-scoped rows and all regressions passed."
  guardrail_verdict: accepted
  live_verification:
    result: pass
    details: "Deployed protected route returned Bronze 18/18, Silver 21/21, and Gold 0/0 after the new API image and refresh."
files_changed:
  - src/fabric/sync_service.py
  - src/api/inventory_orchestration.py
  - tests/test_incremental_sync.py
  - tests/test_inventory_refresh_multi_connection.py
  - tests/test_api_http.py
