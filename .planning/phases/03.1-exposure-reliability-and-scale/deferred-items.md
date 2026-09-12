# Phase 03.1 Deferred Items

## 2026-09-05 — Plan 03.1-05

- `uv run ruff check .` reports 27 pre-existing findings in unrelated infrastructure
  and maintenance scripts, including `infra/scripts/generate_digital_twin_builder.py`,
  `infra/scripts/push_digital_twin_builder.py`,
  `infra/scripts/push_inventory_refresh_pipeline.py`,
  `scripts/delete-lakehouse-tables.py`,
  `scripts/deploy-relationship-suggestion-agent.py`, and
  `scripts/validate-lakehouse-tables.py`. All Plan 03.1-05 changed Python files pass
  Ruff; the unrelated findings were not modified.

## 2026-09-07 — Plan 03.1-25

- The requested broad snapshot/Exposure/remediation/network regression selection
  passed all tests except the pre-existing
  `tests/test_graph_network_traversal.py::test_private_endpoint_exposure_path_reaches_the_backing_resource`.
  `OntologyQueryService` rejects that fixture during graph validation before the
  traversal assertion. Plan 03.1-25 changes only web detail routes, query
  continuity, shared web types/services, and tests; no ontology, network, backend,
  or deployment file was modified, so the unrelated failure was not changed.

## 2026-09-12 — Phase 03.1 closeout

- The operator directed Phase 03.1 closeout after the durable replay published
  458/458 tables, activated Gold generation
  `exposure-gold-4d85d1e59c660c2636edf8ce`, and the authenticated Exposure page
  loaded successfully. A closeout probe returned HTTP 200 for the web page,
  API health, and API readiness; API revision `aiops-dev-api--0000293` was the
  ready revision on Consumption (4 CPU/8 GiB) with one ready running replica
  and zero restarts.
- The qualified 100k Fabric SQL benchmark was not rerun against the final Gold
  generation. It remains a Phase 4 entry gate and must not be represented as a
  Phase 03.1 pass.
- The exact supported Defender digest to Container Insights workload
  forward/reverse ontology traversal remains unproven for the authorized live
  scope. Phase 4 must remain blocked until the executable gate in
  `docs/phase-4-exposure-evidence-gate.md` passes.
- A promoted-candidate shadow canary and live non-destructive rollback exercise
  was not run after the final publication. The rollback contract is tested, but
  the live exercise remains a Phase 4 entry gate.
- The global cloud/source-write freeze is released. Shared Fabric, ontology,
  Container Apps, and deployment mutations still require explicit ownership
  coordination between active sessions.

## 2026-09-12 — Post-closeout authenticated Playwright review

- The Overview, Defender exposure, Patch priorities, KB detail, and CVE detail
  routes render authenticated scoped data. All observed core Exposure/Fabric
  API requests returned HTTP 200, CVE cursor pagination advanced from rows
  1–50 to 51–93, and browser console output stayed clean outside the two
  failing CVE provider requests below.
- Current data is degraded rather than current. Overview and Defender exposure
  report partial evidence observed at `2026-09-10T04:48:09Z` against the
  1,800-second AUM freshness threshold. Patch priorities and KB metadata show
  last-known-good stale evidence from `2026-09-11T02:57:08Z` because the latest
  refresh failed.
- `GET /api/v1/cves/CVE-2025-49796/attack-path` returns HTTP 503. The UI
  correctly isolates the failure and reports that the vulnerability provider
  is deferred, but retrying the section reproduces the 503.
- `GET /api/v1/vulnerabilities/exposure/external-catalog/CVE-2025-49796`
  returns HTTP 404 for the accepted Gold generation. NVD/CVSS, EPSS, CISA KEV,
  and MSRC KB mapping therefore render unavailable.
- The KB detail route loads metadata and one affected finding, but MSRC CVE
  associations remain unavailable with `provider_unavailable`.
- Responsive checks at 375x812, 768x1024, and 1440x900 found no document-level
  horizontal overflow. The 375px Exposure tab strip is horizontally scrollable
  (`337px` client width, `410px` scroll width), so Patch priorities is initially
  clipped but reachable by horizontal scrolling.
