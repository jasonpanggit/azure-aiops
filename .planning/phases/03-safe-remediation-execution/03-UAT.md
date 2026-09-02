---
status: partial
phase: 03-safe-remediation-execution
source: 03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 03-04-SUMMARY.md, 03-05-SUMMARY.md, 03-06-SUMMARY.md
started: 2026-09-01T16:02:55Z
updated: 2026-09-01T23:59:00Z
---

## Current Test

[testing paused - live mutating patch execution declined by operator]

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
result: partial
blocked_by: operator-deferred-live-mutation
observed: The hardened live API returned one subscription-scoped `controlled-patch-recovery` plan for Arc-enabled server `vm1`; preview returned HTTP 200 with operation `install_patches`, patch IDs `4589210`, `5120236`, `5120418`, `890830`, snapshot hash `f55dadce0b6feffffc61124eae3034b3ae54d1e2b5f9f0064fa340f42454cc82`, and `not_approved` eligibility before approval.
reason: The operator declined the mutating approval-and-execute step, so live execution and ARM/provider terminal polling were not performed.

## Summary

total: 4
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0
partial: 1

## Gaps

- truth: "A live least-privileged Azure operator can complete preview -> approval -> execute -> observe for one subscription-scoped controlled patch remediation."
  status: partial
  reason: "The deployed API is reachable, authenticated, and now produces an eligible live preview candidate, but the operator declined the mutating approval-and-execute step."
  severity: blocker
  test: 4
  root_cause: "Live execution remains intentionally unverified because installing patches on the Arc-enabled server requires explicit operator approval."
  artifacts:
    - path: ".planning/phases/03-safe-remediation-execution/03-UAT.md"
      issue: "Live UAT preview passes, but approval/execution/polling remains deferred."
  missing:
    - "When approved, run the exact preview-bound approval, execute the controlled patch remediation, and poll to ARM/provider terminal outcome."
  debug_session: ""
