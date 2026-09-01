---
phase: 09-consumer-pivot
reviewed: 2026-09-01T08:14:59Z
depth: deep
files_reviewed: 20
files_reviewed_list:
  - src/onboarding/defender_normalize.py
  - src/onboarding/query_catalog.py
  - src/onboarding/graph_normalize.py
  - src/ontology/relationship_builder.py
  - src/fabric/dataset_mapper.py
  - src/fabric/schema_registry.py
  - src/fabric/sync_service.py
  - src/api/runtime.py
  - src/api/routers/vulnerability.py
  - src/intelligence/vulnerability/service.py
  - src/intelligence/vulnerability/models.py
  - web/src/lib/types.ts
  - web/src/lib/services.ts
  - web/src/app/exposure/page.tsx
  - tests/test_queries.py
  - tests/test_normalize.py
  - tests/test_relationship_builder.py
  - tests/test_api_vulnerability_router.py
  - tests/test_vulnerability_intelligence.py
  - tests/test_api_runtime_vulnerability_correlation.py
  - tests/test_incremental_sync.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: clean
---

# Phase 09: Code Review Report (Absolute Final Independent Verification — Post-Iteration-7)

**Reviewed:** 2026-09-01T08:14:59Z
**Depth:** deep
**Files Reviewed:** 20
**Status:** clean

## Summary

This is an independent, adversarial re-verification of `09-REVIEW-FIX.md` iteration 7, which claims CR-05 (the finding raised by the previous iteration of this same review) is fixed, backed by a "real end-to-end regression test through the actual `InventoryDatasetMapper`/`_entity_row`/`FabricSyncService` pipeline." Nothing in iteration 7's report was taken on faith: the code change was re-derived directly from `git diff`, the new test was read in full and its imports/pipeline traced to confirm it uses the real production classes (not a hand-flattened stand-in), the exact mechanism CR-05 identified as broken was re-traced end to end through `_build_vulnerability_service` → `_attach_defender_signal_context` → `_project_defender_row`, and every command iteration 7 cites (targeted suite, `ruff check`, `tsc --noEmit`, exposure page test) was re-run verbatim against the current working tree — several times, to check for reproducibility.

**Bottom line: iteration 7's claim holds.** `_defender_payload()` (imported from `intelligence.vulnerability.service`) is now called on all six Defender signal families (`alerts`, `attack_paths`, `attack_path_nodes`, `attack_path_connections`, `secure_scores`, `secure_score_controls`) in `_build_vulnerability_service` *before* `_attach_defender_signal_context` runs (`src/api/runtime.py:946-957`), confirmed via `git diff` to be a clean, minimal, additive change (40 insertions / 4 deletions, no unrelated edits) against the exact code CR-05 identified as broken. The new regression test (`test_fabric_vulnerability_service_scopes_real_mapper_attack_paths_end_to_end`, `tests/test_api_vulnerability_router.py:916-1112`) genuinely imports and drives the real `onboarding.graph_normalize.Normalizer`, `onboarding.ingestion_storage.DatasetStore`, and `fabric.sync_service.FabricSyncService` — not a fake/stub — and its own sanity-check assertions (`"resourceIds" not in raw_attack_paths[0]` / `"resourceIds" in json.loads(raw_attack_paths[0]["payload_json"])`) independently prove the row really is `payload_json`-wrapped before the fix's unpacking runs. No new defect was found in the CR-05 fix itself: the double-unpack (once in `runtime.py`, again inside `VulnerabilityIntelligenceService.__init__`) is safe and idempotent (traced through `_defender_payload`'s `dict(row)` + `result.update(payload)` merge and confirmed, by reading every `normalize_*` function in `onboarding/defender_normalize.py`, that no normalized Defender payload ever contains a literal `"payload_json"`, `"_resource_scope"`, `"environment"`, or other aggregate-dimension key that could be clobbered on the second pass), and the unpack loop only ever touches the six `defender_signals[name]` lists — never `findings`, `defender_assessments`, or any non-Defender row — so no other code path is put at risk.

CR-01 (revoke_risk_exception CVE-wide/scope gates), WR-02 (`risk_exception_list` unfiltered-contract comment + restricted-scope 404 gate), CR-02 (`_project_defender_row`'s per-resource authorized/unsafe-subscription tracking), CR-03 (`_canonical_global_attack_path_node`'s "every label must be canonical or drop, never spoof" behavior), and WR-03/WR-04 (docstrings/lint) were all re-read directly in the current working tree and remain intact and unchanged in substance from what iterations 6/7 described. (WR-01 could not be independently re-verified: it is not described anywhere in the current `09-REVIEW.md`/`09-REVIEW-FIX.md` artifacts — it appears to have been fully resolved and dropped from the finding set in an earlier iteration whose report was overwritten by later iterations, so there is nothing left to check it against.)

**One environmental observation, not a code defect:** this repository has an actively running concurrent session (files under `src/fabric/data_quality.py`, `src/fabric/telemetry.py`, `src/onboarding/sync.py`, `src/ontology/publication_state.py`, plus new `.planning/phases/10-*` artifacts were observed changing mtimes and git-status state *during* this review, unrelated to Defender/CR-05). One out of roughly six full-suite runs during this session transiently failed with 19 unrelated failures (`test_incremental_sync.py` data-quality-validation errors); every other run — including the run immediately before finalizing this report — passed clean at 121/121. This is recorded as IN-01 below and does not affect the CR-05 finding, since the two files CR-05 touches (`src/api/runtime.py`, `tests/test_api_vulnerability_router.py`) were confirmed stable (identical diff stat and checksum) across the entire review.

## Verification Results (tasks 1–6 from this review's brief)

| # | Task | Result |
|---|---|---|
| 1 | Does `_defender_payload` unpacking genuinely happen before scope attribution reads `resourceIds`/`attackPathId` for all six Defender signal families in `runtime.py`? | **Yes, confirmed by direct read and `git diff`.** `src/api/runtime.py:42-45` imports `_defender_payload` from `intelligence.vulnerability.service`. `src/api/runtime.py:946-957` loops over all six signal names, replaces each with `[_defender_payload(row) for row in defender_signals[name]]`, then calls `_attach_defender_signal_context(defender_signals[name], semantic)` — unpack strictly precedes attribution, for every family, on both the Fabric-backed path (`_fabric_vulnerability_service`, `runtime.py:1690-1728`) and the onboarding/non-Fabric path (`_build_vulnerability_service` called at `runtime.py:1241`), since both funnel through the single `_build_vulnerability_service` function. `git diff src/api/runtime.py` shows only this change (40 insertions, 4 deletions; the 4 deletions are the 3 old direct calls to `_attach_defender_signal_context` plus one docstring line reflow) — no unrelated edits. |
| 2 | Does the new test genuinely exercise the real `InventoryDatasetMapper`/`_entity_row`/`payload_json`-wrapped shape (not a bypassed/hand-flattened fixture)? | **Yes.** `tests/test_api_vulnerability_router.py:916-1112` imports and calls the real `onboarding.graph_normalize.Normalizer`, `onboarding.ingestion_storage.DatasetStore`, `fabric.sync_service.FabricSyncService`, `storage.delta_writer.DeltaWriter`, `storage.onelake_writer.OneLakeWriter` — no fakes. It builds a raw ARG-shaped `defender_attack_paths` payload (mixed-subscription 3-node graph), runs it through the real pipeline, and asserts (before touching the API) that the synced row is genuinely `payload_json`-wrapped (`"resourceIds" not in raw_attack_paths[0]`, `"resourceIds" in json.loads(raw_attack_paths[0]["payload_json"])`). It then wires a real `FabricRuntime`/`ApiContext`/`TestClient` and asserts a subscription-restricted caller's `GET /api/v1/defender/attack-paths` returns exactly the authorized VM's resource id and never leaks the unauthorized one. `git diff --stat tests/test_api_vulnerability_router.py` → 206 insertions, 0 deletions (purely additive; the pre-existing `FakeFabricSyncService`-based test above it is untouched). |
| 3 | Full targeted suite, literal final summary line | `uv run pytest tests/test_queries.py tests/test_normalize.py tests/test_relationship_builder.py tests/test_api_vulnerability_router.py tests/test_vulnerability_intelligence.py tests/test_api_runtime_vulnerability_correlation.py tests/test_incremental_sync.py -v` → **`121 passed, 3 warnings in 40.79s`** (final re-run, immediately before finalizing this report). Re-run 5 additional times during this session for reproducibility: 4 more runs at 121/121, plus one transient run at `19 failed, 102 passed` traced to an actively-running concurrent session mutating unrelated files mid-run (see IN-01). |
| 4 | `ruff check`; `cd web && npx tsc --noEmit`; `npm test -- --run src/app/exposure/page.test.tsx` | `uv run ruff check <11 touched src files> tests/test_api_vulnerability_router.py` → **`All checks passed!`**. `npx tsc --noEmit` → **clean, exit 0, no output.** `npm test -- --run src/app/exposure/page.test.tsx` → **`Test Files 1 passed (1)`, `Tests 2 passed (2)`**. |
| 5 | Re-verify CR-01–CR-04, WR-01–WR-04 remain intact given concurrent edits to shared files like `runtime.py` | **CR-01/WR-02, CR-02, CR-03, WR-03, WR-04 all confirmed intact by direct read** (see Summary and Critical/Info sections below for exact line citations). **WR-01 cannot be independently re-verified** — no description of it survives in the current phase artifacts (only `09-REVIEW-FIX.md` iteration 7 and the now-replaced `09-REVIEW.md` iteration-6-summary exist; both are silent on WR-01, meaning it was resolved and dropped from the finding set in an earlier, overwritten iteration). No regression symptoms consistent with a reopened WR-01 were observed. |
| 6 | Look for any new defect introduced by the CR-05 fix itself | **None found.** Traced double-unpack safety (`_defender_payload` called once in `runtime.py`, again inside `VulnerabilityIntelligenceService.__init__`) by reading every `normalize_*` function in `onboarding/defender_normalize.py` and `_entity_row`/`_base` in `fabric/dataset_mapper.py`: no normalized Defender payload ever contains a literal `payload_json`, `_resource_scope`, or aggregate-dimension key, so the second unpack cannot clobber the first pass's attribution. Confirmed the unpack loop (`runtime.py:946-957`) only mutates `defender_signals[name]` for the six named Defender families — `findings`, `defender_assessments`, and all patch/CVE rows are untouched, so no non-Defender code path is at risk. Performance (repeated unpacking) is out of v1 review scope per this review's own rules and is negligible regardless (single extra `json.loads` per row, already acknowledged by the fix report). |

## Info

### IN-01: Active concurrent editing session observed during this review (environmental, not a CR-05 defect)

**Classification:** INFO
**Issue:** During this review, `src/fabric/data_quality.py`, `src/fabric/telemetry.py`, `src/onboarding/sync.py`, and a new `src/ontology/publication_state.py` were observed with actively changing mtimes and shifting `git status --short` state (e.g. `data_quality.py` went from modified → no longer listed as modified between two checks minutes apart), consistent with an unrelated, still-running concurrent session (apparently Phase 10 "Fabric medallion capability expansion" work — new `.planning/phases/10-fabric-medallion-capability-expansion/*` artifacts also appeared mid-review). This produced one transient full-suite failure (`19 failed, 102 passed`, all in `test_incremental_sync.py` plus the new CR-05 test) that could not be reproduced on five subsequent re-runs (all 121/121), and is best explained by this review's test run catching an in-progress, momentarily-inconsistent edit to `data_quality.py`/`sync.py` rather than any defect in the reviewed Defender/CR-05 code. The two files CR-05 actually touches (`src/api/runtime.py`, `tests/test_api_vulnerability_router.py`) had an identical `git diff --stat` and file checksum at the start and end of this review, confirming they were not part of the concurrent activity.
**Fix:** N/A for this review — informational. Future reviewers/CI runs against this working tree should be aware the tree is not exclusively owned by the Defender/CR-05 workstream and a single flaky run should be re-run before treating it as a regression signal.

---

_Reviewed: 2026-09-01T08:14:59Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
