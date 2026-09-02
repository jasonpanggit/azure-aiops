---
phase: 10-fabric-medallion-capability-expansion
reviewed: 2026-09-02T03:58:00Z
status: fixed
depth: standard
critical: 2
warnings: 2
open_findings: 0
---

# Phase 10 Code Review

## Summary

Standard review found two critical findings and two warnings in the Phase 10 Fabric medallion and Gold-grounding changes. All findings were fixed and covered with targeted regressions.

## Findings

| ID | Severity | File | Status | Resolution |
|----|----------|------|--------|------------|
| CR-01 | Critical | `src/api/routers/fabric_medallion.py` | Fixed | Delta fallback quality-report rows are filtered through `_row_visible(scope, row)` before governance aggregation. |
| CR-02 | Critical | `src/api/routers/fabric_medallion.py` | Fixed | Capabilities now returns sanitized role summaries only: role name and permission count; principals/raw role payloads are not exposed. |
| WR-01 | Warning | `web/src/app/connections/page.tsx` | Fixed | Replaced the inert retry button with non-clickable retry guidance. |
| WR-02 | Warning | `src/operations/gold_grounding_specialist.py` | Fixed | Non-empty, unparseable Gold-grounding responses now degrade with `unparseable Gold evidence` instead of proceeding as successful empty evidence. |

## Verification

- `./.venv/bin/python -m ruff check src/api/routers/fabric_medallion.py src/operations/gold_grounding_specialist.py tests/test_api_http.py tests/test_gold_grounding_specialist.py` - pass
- `./.venv/bin/python -m pytest tests/test_api_http.py::test_fabric_medallion_reads_live_delta_metadata_when_json_snapshot_is_empty tests/test_api_http.py::test_fabric_medallion_governance_delta_fallback_filters_scope tests/test_api_http.py::TestFabricMedallionRouterTask2::test_fabric_medallion_capabilities_compose_read_only_signals_and_lineage tests/test_gold_grounding_specialist.py::test_unparseable_gold_response_degrades_without_claiming_gold_success -q` - 4 passed
- `cd web && npx tsc --noEmit && npx vitest run src/app/connections/page.test.tsx` - 10 passed

## Result

No open Critical or Warning findings remain.
