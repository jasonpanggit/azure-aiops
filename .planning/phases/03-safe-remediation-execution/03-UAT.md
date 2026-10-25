---
status: partial
phase: 03-safe-remediation-execution
source: 03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md, 03-05-SUMMARY.md, 03-06-SUMMARY.md
started: 2026-09-01T16:02:55Z
updated: 2026-10-25T15:48:00+08:00
---

## Current Test

[testing paused — 1 test remains blocked because the approved live target is unavailable]

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
blocked_by: server
observed: The user explicitly authorized the one-time operation for Arc-enabled server `vm1` and patch IDs `4589210`, `5120236`, `5120418`, and `890830`. A fresh read of the deployed API returned one current `controlled-patch-recovery` plan, `live-patch-4fbe971799931701`, titled `Patch migrate-repl-01`, under subscription `890c9bfc-d09c-4143-9ce5-465e75e3eecc`; it is `not_approved`. A scoped read for vm1's previously recorded subscription returned HTTP 400, `No active connection matches the requested subscription scope` (correlation ID `5818c8c8bcc348d4a05143e1962597b6`). No preview, approval, execution, or Azure mutation was performed.
reason: The current live plan targets `migrate-repl-01`, not the explicitly authorized `vm1`, and the previously recorded vm1 subscription has no active connection. Its target and patch snapshot therefore cannot be treated as the approved action. Stop without approval or execution until vm1 is again available and a fresh preview matches the authorized target and exact patch IDs; live ARM/provider terminal polling remains unperformed.

## Summary

total: 4
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 1

## Gaps

[none — the remaining live state-changing test is blocked pending an active connection and a fresh preview matching the explicitly authorized vm1 target and patch IDs]
