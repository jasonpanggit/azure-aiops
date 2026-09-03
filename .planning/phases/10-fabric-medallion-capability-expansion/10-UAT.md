---
status: complete
phase: 10-fabric-medallion-capability-expansion
source: 10-01-SUMMARY.md, 10-02-SUMMARY.md, 10-03-SUMMARY.md, 10-04-SUMMARY.md, 10-05-SUMMARY.md, 10-06-SUMMARY.md, 10-07-SUMMARY.md, 10-08-SUMMARY.md, 10-09-SUMMARY.md, 10-10-SUMMARY.md, 10-11-SUMMARY.md, 10-12-SUMMARY.md, 10-13-SUMMARY.md, 10-14-SUMMARY.md, 10-15-SUMMARY.md
started: 2026-09-02T05:45:00Z
updated: 2026-09-02T14:46:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live `/connections` page availability
expected: The deployed `/connections` page loads and points to the deployed API backend.
result: pass
evidence: Web endpoint returned HTTP 200 and `/api/config` identified the deployed API base URL.
latest_validation: 2026-09-02T06:15:27Z - Web endpoint returned HTTP 200 and `/api/config` returned `https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io`.

### 2. Fabric Bronze/Silver/Gold status respects subscription scope
expected: Bronze, Silver, and Gold medallion APIs receive the selected subscription scope and show only scoped datasets.
result: pass
evidence: Frontend Fabric API calls now pass the global subscription scope to layers, dataset details, manifest, governance, ingestion history, and capabilities. Backend manifest filtering now uses the same row visibility rules as layer, dataset, governance, ingestion, and capability endpoints.
latest_validation: 2026-09-02T06:15:27Z - Deployed JavaScript bundle contains the subscription-level Fabric status and dataset-card UI. Direct live payload inspection remains blocked by bearer-token authentication.

### 3. Fabric metadata persists subscription-level ownership
expected: Fabric metadata rows retain subscription context for scope filtering and visible ownership.
result: pass
evidence: Existing ingestion stores canonical `requested_scope_json` per subscription; manifest responses now derive `subscription_id` and `subscription_connection` from that canonical scope when explicit columns are absent.

### 4. Lifecycle and governance gaps are visible at subscription level
expected: Lifecycle dispositions and governance gaps are summarized for the selected subscription rather than buried only in detailed tables.
result: pass
evidence: The Fabric tab now includes a subscription-level summary card covering medallion health, active/inactive lifecycle contracts, and open governance gap counts.

### 5. Fabric UI/UX avoids table-only presentation
expected: Users can understand Fabric medallion health without relying only on dense tables or pill-heavy displays.
result: pass
evidence: Dataset health now appears as scannable cards above the detailed filterable tables, and the summary card leads with subscription, medallion, lifecycle, and governance signals.

### 6. Authenticated live payload inspection
expected: Live Fabric medallion API payloads can be inspected end-to-end against the deployed environment.
result: pass
evidence: Protected Fabric medallion API payload was inspected with an Azure CLI bearer token after deployment.
latest_validation: 2026-09-02T14:45:00Z - `/api/v1/fabric-medallion/layers` returned HTTP 200.

### 7. Retest deployed Fabric medallion rendering
expected: The selected subscription shows the live Bronze/Silver/Gold layer counts documented by Phase 10, with explicit healthy-empty or unavailable states only where applicable.
result: pass
evidence: The deployed protected route returned Bronze `18/18`, Silver `21/21`, and Gold `0/0`, matching the Phase 10 expectation.
latest_validation: 2026-09-02T14:45:00Z - API and web deployments served the new image tag; `/health`, `/ready`, and `/connections` returned HTTP 200, and the authenticated layers payload matched expected counts.

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

No unresolved gaps remain for this retest.
