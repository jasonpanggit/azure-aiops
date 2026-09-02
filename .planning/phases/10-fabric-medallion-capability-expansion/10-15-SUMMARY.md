---
phase: 10-fabric-medallion-capability-expansion
plan: 15
type: execute
wave: 9
depends_on: ["10-14"]
provides:
  - Live Fabric lakehouse reconciliation for Phase 10 medallion rollout.
  - Real gold-grounding evaluation baseline artifact.
  - Deployed API/web validation evidence for Fabric medallion visibility.
requirements-completed: [MED-02, MED-08, MED-10]
actuals:
  tasks: 3
  commits: 0
key-files:
  created:
    - .planning/eval/gold-grounding-baseline.json
  modified:
    - .planning/ROADMAP.md
    - .planning/STATE.md
status: complete
completed: 2026-09-02
---

# Phase 10 Plan 15: Live rollout validation and evaluation baseline Summary

**Phase 10 is live-validated against the deployed Fabric workspace and API/web surfaces.**

## Accomplishments

- Reconciled the live `operational_context_graph_v2` lakehouse: 444 tables present, 62 present code-declared tables, 383 generated ontology tables, 0 present-unknown tables, 13 code-declared missing tables, and 0 undispositioned expected-missing tables.
- Restored live medallion metadata visibility by reading metadata from Delta fallback tables and publishing `metadata_source_status` rows for actual Bronze/Silver/metadata/ontology table outputs.
- Deployed API/web/MCP images through Terraform and recovered the API readiness path so optional provider degradation does not block Container Apps routing.
- Validated live medallion endpoints:
  - `/api/v1/fabric-medallion/layers`: Bronze 18/18 healthy, Silver 21/21 healthy, Gold 0/0 healthy/total with explicit absence rather than silent unknown.
  - `/api/v1/fabric-medallion/capabilities`: Fabric capacity healthy, F4 SKU, lineage dataset count 358, semantic readiness explicitly `deployment-blocked`, Data Agent unconfigured/unknown.
  - `/manifest`: 15 publication manifest entries.
  - `/governance`: 5120 ownership gaps, 3157 tag gaps, 0 referential-integrity blockers, 436 detailed gaps.
  - `/ingestion-history`: 359 run entries sourced from live source-status/ingestion metadata.
- Established a real `.planning/eval/gold-grounding-baseline.json` run against the deployed API: 23 cases, 0 errors, 0 timeouts, 20/23 routing pass, routing rate 0.87, groundedness mean 0.283, tool correctness mean 1.0, median latency 1828.2 ms.
- Completed the blocking human web gate after approval of the deployed `/connections` Fabric medallion tab evidence.

## Deviations from Plan

### Auto-fixed Issues

**1. Live metadata source mismatch**
- **Issue:** Deployed medallion routes initially read connection-generation JSON metadata, while live Fabric sync had populated Delta metadata tables.
- **Fix:** Added Delta-backed fallback reads for source status, publication manifest, and quality reports.
- **Impact:** Medallion API now serves live Fabric metadata when JSON snapshot metadata is absent.

**2. Runtime Fabric capacity configuration missing from API capability checks**
- **Issue:** Capacity health and related helpers did not consistently honor `AIOPS_FABRIC_CONFIG`, leaving live capacity status unknown.
- **Fix:** Added typed capacity metadata to Fabric runtime config and made capacity/role/maintenance helpers load runtime config.
- **Impact:** `/capabilities` now reports the real `aiopsdevcapg6ludc` capacity as healthy.

**3. Remote OneLake generation path resolution**
- **Issue:** API-triggered refresh passed the combined snapshot root rather than the resolved generation and then mangled OneLake paths through local `Path.resolve()`.
- **Fix:** Added URI-preserving/current-generation handling and handed Fabric sync the resolved remote filesystem path plus filesystem object.
- **Impact:** Live refresh can read the combined OneLake generation instead of failing with `/app/<workspace>/<lakehouse>/Files/aiops/generations`.

**4. Source-status publication arrived too late for long live refreshes**
- **Issue:** The HTTP refresh path could time out before medallion layer rows were visible.
- **Fix:** Published `metadata_source_status` before slower catalog/ontology publication steps.
- **Impact:** Live Bronze/Silver layer health now appears even when full refresh work exceeds the HTTP stream timeout.

**5. Optional provider failures blocked Container Apps readiness**
- **Issue:** Non-core Fabric intelligence loaders could make `/ready` return 503, preventing the API revision from becoming routable despite health and medallion endpoints being usable.
- **Fix:** Limited readiness-required providers to core semantic providers; optional provider failures remain visible in provider health.
- **Impact:** API revision `fix-ontology-sync-publish-20260902-024618` is healthy and routable.

## Verification

- `./.venv/bin/python -m ruff check src/api/runtime.py src/api/providers.py src/api/inventory_orchestration.py src/storage/datasets.py src/fabric/sync_service.py tests/test_api_providers.py tests/test_inventory_refresh_multi_connection.py tests/test_incremental_sync.py` - pass
- `./.venv/bin/python -m pytest tests/test_api_providers.py tests/test_inventory_refresh_multi_connection.py tests/test_incremental_sync.py::test_mapper_reads_remote_snapshot_via_provided_filesystem tests/test_incremental_sync.py::test_incremental_sync_writes_bronze_silver_ontology_and_state tests/test_api_http.py::test_fabric_medallion_reads_live_delta_metadata_when_json_snapshot_is_empty -q` - 10 passed
- `set -a && source web/.env.local && set +a && ./.venv/bin/python scripts/validate-lakehouse-tables.py --config fabric.config.yaml --json-out /tmp/gold-audit-final.json` - pass
- `./.venv/bin/python scripts/evaluate_agents.py --out .planning/eval/gold-grounding-baseline.json` - completed real 23-case baseline with 0 errors and 0 timeouts; process exited non-zero because 3 routing cases missed their expected governance specialist.
- Authenticated deployed API checks returned HTTP 200 for `/health`, `/ready`, `/api/v1/fabric-medallion/layers`, `/capabilities`, `/manifest`, `/governance`, and `/ingestion-history`.
- Deployed web `/connections` returned HTTP 200 and the Fabric medallion web gate was approved by the user.

## Known Live Dispositions

- Gold layer currently reports 0/0 tables in medallion layer status because the live `metadata_source_status` rows contain Bronze, Silver, metadata, assessment, and ontology families, but no `gold_*` source-status family rows.
- Semantic readiness is truthfully `deployment-blocked` due the recorded Fabric semantic-model lease mismatch.
- Data Agent readiness is truthfully `unknown`/unconfigured because the deployment lacks `FABRIC_GOLD_GROUNDING_AGENT_ID` and `FABRIC_DELEGATED_TOKEN`.
- The gold-grounding baseline intentionally records the degraded current state: Foundry narration unavailable, deterministic findings returned, and 3/23 routing misses.

## Next Phase Readiness

- Phase 10 live validation is complete.
- Future work should start from the recorded baseline rather than treating the degraded Data Agent/narration state as a fabricated pass.

## Self-Check: PASSED

- Summary file exists on disk.
- Live lakehouse reconciliation has zero undispositioned expected-missing gaps.
- Live medallion API and deployed web surfaces are reachable.
- Real gold-grounding baseline artifact exists.
- Blocking human web gate was approved.
