---
phase: 09-consumer-pivot
fixed_at: 2026-09-01T07:58:25Z
review_path: .planning/phases/09-consumer-pivot/09-REVIEW.md
iteration: 7
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 09: Code Review Fix Report

**Fixed at:** 2026-09-01T07:58:25Z
**Source review:** `.planning/phases/09-consumer-pivot/09-REVIEW.md` (deep, final independent re-verification / post-iteration-6 pass)
**Iteration:** 7

**Summary:**
- Findings in scope: 1 (CR-05 — WR-05/IN-02 are not independently actionable: WR-05 is the same gap as CR-05 from the test-coverage side and is closed by the same fix; IN-02 is informational only)
- Fixed: 1
- Skipped: 0
- Commits: None, as explicitly requested — changes remain in the working tree, unstaged (`git status`/`git diff --cached` confirm nothing staged; see Verification)

## Fixed Issues

### CR-05: `_resource_scope`/business-context attribution for Defender alerts, attack paths, and attack-path nodes is never populated on real (production) data in either the Fabric-backed or the non-Fabric loader

**Files modified:** `src/api/runtime.py`, `tests/test_api_vulnerability_router.py`
**Commit:** Not committed (per request)
**Applied fix:**

Root cause confirmed exactly as the review described: `InventoryDatasetMapper.load()` maps all six Defender signal families (`alerts`, `attack_paths`, `attack_path_nodes`, `attack_path_connections`, `secure_scores`, `secure_score_controls`) through the generic `_entity_row()` helper (`src/fabric/dataset_mapper.py`), whose output schema exposes only `entity_type`/`name`/`resource_type`/`location`/`payload_json` as top-level columns — every Defender-specific field (`resourceIds`, `resourceId`, `attackPathId`, `title`, etc.) is serialized *inside* the `payload_json` string. `_attach_defender_signal_context()` (`src/api/runtime.py`) read `row.get("resourceIds")`/`row.get("resourceId")` directly on these still-nested rows, found nothing, and populated no `_resource_scope`/aggregate dimension fields — for both the Fabric-backed path (`_fabric_vulnerability_service`) and the onboarding/non-Fabric path (`_build_vulnerability_service` via `_load_snapshot_tables()`), since both funnel through the same `_build_vulnerability_service()` function.

Went with the review's fix option **(a)**: unpack `payload_json` before scope attribution runs, reusing the exact same unpacking logic (`_defender_payload()`) that `VulnerabilityIntelligenceService.__init__` already uses, rather than option (b) (giving the six datasets dedicated flattening mappers) — option (a) is the smaller, surgical change and does not touch the mapper/schema layer or any Delta table shape.

1. **Import.** `src/api/runtime.py` now imports `_defender_payload` alongside `VulnerabilityIntelligenceService` from `intelligence.vulnerability.service` (precedent for importing an underscore-prefixed cross-module helper already exists in this file, e.g. `from onboarding.sync import _slug`).
2. **Unpack-before-attach.** In `_build_vulnerability_service`, immediately before the existing `_attach_defender_signal_context` calls, each of the six signal families' rows is now replaced with `[_defender_payload(row) for row in defender_signals[name]]` — flattening `payload_json` onto each row (idempotent: rows that already have flat keys, or no `payload_json` at all, e.g. hand-built test fixtures, pass through unchanged) — before `_attach_defender_signal_context` reads `resourceIds`/`resourceId` off them.
3. **Consistency across all six families.** The review explicitly called out `alerts`, `attack_paths`, `attack_path_nodes`, `attack_path_connections`, `secure_scores`, `secure_score_controls` as needing the same treatment "wherever they flow through runtime.py's context-attachment path." Previously only `alerts`/`attack_paths`/`attack_path_nodes` were passed to `_attach_defender_signal_context` at all; the fix now calls it for all six. (Verified by inspection that `attack_path_connections`/`secure_scores`/`secure_score_controls` carry no `resourceId`/`resourceIds` field in their normalized shape — `onboarding/defender_normalize.py`'s `normalize_secure_score`/`normalize_secure_score_control`/the connection-building loop in `normalize_attack_path` — so this is a harmless, consistency-only no-op for those three; their subscription-level scoping already worked because `subscription_id` is flattened onto every row by `dataset_mapper._base()`, independent of `payload_json`.)
4. **`source_status` intentionally excluded** — its rows are never passed through `_defender_payload` anywhere (including inside `VulnerabilityIntelligenceService.__init__`), so unpacking it here would be inconsistent with how it is consumed everywhere else; left untouched.
5. **Double-unpack is safe.** `VulnerabilityIntelligenceService.__init__` still calls `_defender_payload()` on every Defender row it receives (unchanged). Since `_defender_payload()` is idempotent (re-parsing the same `payload_json` string and re-merging the same fields produces the same result), running it once here and again inside `from_rows()`/`__init__` is redundant but not incorrect.

**Real end-to-end regression test (new, added this iteration):** `test_fabric_vulnerability_service_scopes_real_mapper_attack_paths_end_to_end` in `tests/test_api_vulnerability_router.py`. Unlike the pre-existing `test_fabric_vulnerability_service_scopes_attack_paths_end_to_end` (whose `FakeFabricSyncService.defender_intelligence_snapshot()` hand-returns already-flat dicts with `resourceIds`/`attackPathId`/`title` as top-level keys — exactly the gap CR-05 identified in that test), the new test:

1. Builds a raw ARG-shaped `defender_attack_paths` payload (one attack path with a `graphComponent` of three nodes — an unresolved "Internet" node plus two `VirtualMachine` nodes in two different subscriptions, `sub-prod` and `sub-other`) alongside two ARG `resources` rows for those VMs and their `resource_containers` (subscriptions).
2. Runs it through the **real** production pipeline: `onboarding.graph_normalize.Normalizer.normalize()` → `onboarding.ingestion_storage.DatasetStore.publish()` → `fabric.sync_service.FabricSyncService.sync()` (which internally calls `fabric.dataset_mapper.InventoryDatasetMapper.load()`, the real `_entity_row()` mapper) → a real `FabricSyncService.defender_intelligence_snapshot()` Delta round-trip.
3. Asserts (sanity check, before exercising the API) that the synced attack-path row is genuinely `payload_json`-wrapped and not hand-flattened: `"resourceIds" not in raw_attack_paths[0]` and `"resourceIds" in json.loads(raw_attack_paths[0]["payload_json"])`.
4. Wires a real `fabric.runtime.FabricRuntime` around that `FabricSyncService` into `api.runtime._fabric_vulnerability_service()` behind a `subscription=["sub-prod"]`-restricted `Grant`, and asserts a live `GET /api/v1/defender/attack-paths` call returns **HTTP 200 with a non-empty, correctly-narrowed `resourceIds`** (only the `sub-prod` VM; the `sub-other` VM's resource id does not appear anywhere in the response body).

**Confirmed the test is a genuine regression test, not vacuously true:** ran it against the pre-fix `src/api/runtime.py` (via `git stash push -- src/api/runtime.py`, i.e. with `_attach_defender_signal_context` still reading `resourceIds`/`resourceId` directly off the still-`payload_json`-wrapped rows) — it **failed** with `AssertionError: expected the caller's authorized attack path to be surfaced, not empty / assert []`, reproducing exactly the CR-05 defect end-to-end. Restored the fix (`git stash pop`) and the test passes again (see Verification for the literal full-suite run with the fix restored).

## Not Independently Actioned

### WR-05: `/defender/*` scoped-response behavior for non-admin callers is entirely untested against real mapper output

Same underlying gap as CR-05, viewed from the test-coverage side; the review itself says "this is the same fix recommended under CR-05." Closed by the same `test_fabric_vulnerability_service_scopes_real_mapper_attack_paths_end_to_end` test added above, which is exactly the "one test per Defender signal family that runs the full pipeline" pattern the review's Fix section asked for (this iteration adds it for the `attack_paths`/`attack_path_nodes` family, the one CR-05's own reproduction targeted; the remaining families — `alerts`, `attack_path_connections`, `secure_scores`, `secure_score_controls` — are covered by the CR-05 code fix but not yet each given their own dedicated full-pipeline test, since the CR-05 finding scoped its "add a regression test" instruction to attack paths specifically. Not marked skipped since it is not separately in-scope for this iteration; the production fix itself does apply uniformly to all six families per item 3 above).

### IN-02: Working tree stability confirmed

Informational only; no fix required.

## Verification

Ran directly in the main checkout against the retained uncommitted working tree (per the explicit "do not stage or commit" instruction; no worktree isolation was used, consistent with the prior iteration's operating mode for this same reason).

Literal final summary lines, re-run immediately before writing this report:

- `uv run pytest tests/test_queries.py tests/test_normalize.py tests/test_relationship_builder.py tests/test_api_vulnerability_router.py tests/test_vulnerability_intelligence.py tests/test_api_runtime_vulnerability_correlation.py tests/test_incremental_sync.py -v`
  → **`121 passed, 3 warnings in 34.05s`** (final re-run, immediately before this report was finalized; the review's iteration-6 baseline was 120; +1 is the new `test_fabric_vulnerability_service_scopes_real_mapper_attack_paths_end_to_end`).
- `uv run ruff check src/api/runtime.py tests/test_api_vulnerability_router.py`
  → **`All checks passed!`** (final re-run, immediately before this report was finalized).
- `python3 -c "import ast; ast.parse(open('src/api/runtime.py').read())"` and the same for `tests/test_api_vulnerability_router.py`
  → both exit 0 (syntax-valid) after edits.
- **Regression-proof re-run against pre-fix code** (`git stash push -- src/api/runtime.py`, then `uv run pytest tests/test_api_vulnerability_router.py -k test_fabric_vulnerability_service_scopes_real_mapper_attack_paths_end_to_end -v`):
  → **`1 failed`** — `AssertionError: expected the caller's authorized attack path to be surfaced, not empty / assert []` at `tests/test_api_vulnerability_router.py:1110`. Fix restored via `git stash pop`; re-ran the same targeted test → **`1 passed, 29 deselected, 1 warning in 7.85s`**.
- No files outside `src/api/runtime.py` (the CR-05 import + unpack-before-attach fix) and `tests/test_api_vulnerability_router.py` (new imports + new end-to-end regression test) were modified by this iteration. `git status --short` / `git diff --stat` confirm exactly those two files were touched by this iteration's own edits; `git diff --cached` is empty (nothing staged); all pre-existing untracked artifacts in the repository (`.agents/`, `.github/worktrees/`, `.planning/debug/`, `.planning/phases/09-consumer-pivot/09-REVIEW.md`, `skills-lock.json`) are preserved exactly as found and untouched by this iteration.
- **Operational note — concurrent session detected mid-session:** a `git status --short` check (run immediately before this report was finalized) additionally showed `src/fabric/data_quality.py`, `src/onboarding/sync.py`, `tests/test_data_quality.py` modified and a new untracked `src/ontology/publication_state.py`, none of which this iteration touched (confirmed by content review — no reference to `_attach_defender_signal_context`, `_defender_payload`, `InventoryDatasetMapper`, or any Defender/CR-05 symbol in any of them) and by the fact that this iteration never opened or wrote any of those files. They are left exactly as found; a final re-run of the full targeted suite and `ruff check` on this iteration's two touched files (immediately below) confirms the CR-05 fix is unaffected by this concurrent activity.

## Final Assessment

CR-05 is resolved: `_attach_defender_signal_context` now sees flattened Defender rows (via `_defender_payload()`, reused from `intelligence.vulnerability.service`) for all six signal families before deriving `_resource_scope`/aggregate dimension attribution, on both the Fabric-backed and onboarding/non-Fabric production paths (both route through the single `_build_vulnerability_service()` function that was patched). A new regression test proves this end-to-end through the real `InventoryDatasetMapper`/`_entity_row` mapper output — not a hand-flattened fixture — and was confirmed to fail against the pre-fix code and pass against the fix, ruling out a vacuous assertion. The full targeted suite (121 tests) and `ruff check` on both touched files are clean.

---

_Fixed: 2026-09-01T07:58:25Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 7_
