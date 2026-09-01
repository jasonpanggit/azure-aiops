---
status: partial
phase: 03-safe-remediation-execution
source: 03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md, 03-05-SUMMARY.md, 03-06-SUMMARY.md
started: 2026-09-01T16:02:55Z
updated: 2026-09-01T16:02:55Z
---

## Current Test

[testing paused - live dataset has no executable remediation candidates]

## Tests

### 1. Deployed remediation page loads
expected: The production web remediation page responds successfully and can initialize the operator workspace.
result: pass
observed: `GET https://aiops-dev-web.greenpond-732382e3.australiaeast.azurecontainerapps.io/remediation` returned HTTP 200.

### 2. Deployed API readiness and remediation provider health
expected: The deployed API is healthy and reports remediation, patching, vulnerability, semantic, and required runtime providers ready.
result: pass
observed: `GET https://aiops-dev-api.greenpond-732382e3.australiaeast.azurecontainerapps.io/health` returned `status: ok`, `readiness: ready`, and `remediation`, `patching`, `vulnerability`, `semantic`, and `semantic_graph` providers in `ready` state.

### 3. Least-privileged authenticated remediation plan read
expected: A bearer token for the deployed API audience can read the scoped remediation plan list.
result: pass
observed: `GET /api/v1/remediation/plans` with an Entra access token for `api://306c1437-0e7d-43bd-940b-79b878166331` returned HTTP 200 and an evidence-wrapped response.

### 4. Preview, approve, execute, and observe a controlled patch remediation
expected: A least-privileged operator selects a subscription-scoped `controlled-patch-recovery` plan, previews the exact target/patch snapshot, approves the current preview hash, executes once, and polls until ARM/provider verification supplies the terminal outcome and audit history.
result: blocked
blocked_by: live-data
reason: The deployed remediation plan list returned zero plans (`plan_count: 0`), so there is no live `controlled-patch-recovery` candidate to preview, approve, execute, or observe.

## Summary

total: 4
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 1

## Gaps

- truth: "A live least-privileged Azure operator can complete preview -> approval -> execute -> observe for one subscription-scoped controlled patch remediation."
  status: failed
  reason: "The deployed API is reachable and authenticated, but the current live ontology/provider snapshot contains zero remediation plans."
  severity: blocker
  test: 4
  root_cause: "Live data does not currently include an executable remediation candidate; code-level and TestClient regression verification covers the behavior, but deployed UAT needs at least one eligible controlled-patch-recovery plan."
  artifacts:
    - path: ".planning/phases/03-safe-remediation-execution/03-UAT.md"
      issue: "Live UAT blocked by empty remediation plan dataset."
  missing:
    - "Publish or ingest a live snapshot that produces at least one eligible controlled-patch-recovery remediation plan, then rerun Phase 3 live UAT."
  debug_session: ""
