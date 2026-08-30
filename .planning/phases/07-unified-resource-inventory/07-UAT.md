---
status: partial
phase: 07-unified-resource-inventory
source: 07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md, 07-05-SUMMARY.md, 07-06-SUMMARY.md
started: 2026-08-27T01:15:00Z
updated: 2026-08-27T01:24:00Z
---

## Current Test

[testing paused — 1 item outstanding]

## Tests

### 1. Open Inventory Landing Page
expected: Opening /inventory loads the Inventory view with OS Inventory and Installed Software tabs, a data-trust/provenance area, freshness/source status messaging, and no runtime error. Empty or degraded source data is shown explicitly rather than presented as current complete data.
result: pass

### 2. Review OS Inventory
expected: The OS Inventory tab shows authorized machine coverage, OS grouping, lifecycle/EOL review information, pagination, evidence, freshness, and source availability when data is present.
result: blocked
blocked_by: prior-phase
reason: No OS data is available in the deployed environment, so the data-bearing review cannot be exercised.

### 3. Review Installed Software
expected: The Installed Software tab shows software observations and mappings with exact software/version search, pagination, evidence, freshness, and explicit degraded/absent source status.
result: blocked
blocked_by: prior-phase
reason: No installed-software data is available in the deployed environment, so the data-bearing review cannot be exercised.

### 4. Review PaaS Inventory
expected: The PaaS/resource inventory view exposes grouped resources and drill-down details with subscription scope, identity-plane evidence, freshness, pagination, and no raw provider payload leakage.
result: blocked
blocked_by: prior-phase
reason: The current deployed UI does not expose a PaaS/resource inventory review, so this user-facing checkpoint cannot be exercised.

### 5. Verify Cross-Family Availability and Retention
expected: Family availability distinguishes available, degraded, and absent sources; a failed refresh does not replace the last successful generation, while a successful empty refresh is represented as empty.
result: blocked
blocked_by: prior-phase
reason: Refresh controls and data generations are unavailable in the deployed environment, so retention behavior cannot be exercised.

### 6. Verify Responsive and Keyboard UX
expected: Inventory tabs, filters, details, and export controls remain usable with keyboard navigation and at responsive viewport widths.
result: skipped
reason: User skipped this checkpoint.

## Summary

total: 6
passed: 1
issues: 1
pending: 0
skipped: 1
blocked: 4

## Gaps

- truth: "The deployed Inventory page shows the authorized inventory rows and review controls after the Fabric inventory refresh."
  gap_id: G-07-1
  status: failed
  reason: "User reported: nothing is shown in inventory page"
  severity: major
  test: 2
  root_cause: "The API is configured for Fabric, but the deployed lakehouse has no active inventory snapshot/rows. Its fallback ARG acquisition runs inside Container Apps without an az login, so both native VM and Arc sources are degraded with zero rows."
  artifacts:
    - path: "src/api/runtime.py"
      issue: "Returns no inventory service when Fabric inventory tables are empty, after attempting the Fabric-backed read."
    - path: "infra/terraform/container_apps.tf"
      issue: "Deploys Fabric identifiers but does not itself trigger/populate the inventory refresh."
    - path: ".planning/WINDOWS.md"
      issue: "Existing live-verification ledger records the need to run standalone inventory refresh and the LAW ConfigurationData gap."
  missing:
    - "Run the Fabric Inventory Refresh pipeline successfully for the configured subscription connections and verify non-empty inventory tables."
    - "Confirm the API managed identity can read the refreshed OneLake tables."
    - "Provide a user-visible refresh status/action or explicit onboarding guidance when no active snapshot exists."
  debug_session: ""
