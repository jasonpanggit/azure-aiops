---
phase: 09-consumer-pivot
plan: 08
subsystem: infra
tags: [azure-api-management, apim, mcp, terraform, entra, rollback]

requires:
  - phase: 09-consumer-pivot
    provides: governed read-only Operations MCP endpoint and API-side scope enforcement
provides:
  - Dedicated APIM MCP gateway with Entra validation, throttling, correlation, and redaction
  - Credential-safe deployment, validation, snapshot, and rollback controls
  - Live-validated Australia East Developer APIM endpoint for the public MCP Container App backend
affects: [09-09, operations-mcp, deployment, observability]

actuals:
  tokens: 10200
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns: [Terraform-managed APIM gateway, policy-based trust boundary, secret-safe reversible rollout]

key-files:
  created:
    - infra/terraform/apim-policies/mcp-backend.xml
    - infra/scripts/rollback-apim-mcp.sh
    - .planning/phases/09-consumer-pivot/09-APIM-ROLLBACK.md
    - tests/test_gateway_identity_boundary.py
  modified:
    - infra/terraform/apim.tf
    - infra/terraform/apim-policies/mcp-inbound.xml
    - infra/terraform/apim-policies/mcp-outbound.xml
    - infra/scripts/deploy.sh
    - infra/scripts/validate-apim-mcp.sh
    - src/api/runtime.py
    - tests/test_apim_iac.py

key-decisions:
  - "Use a dedicated Developer-tier APIM instance in Australia East for isolated MCP gateway ownership and rollback."
  - "Keep API-side effective-scope enforcement authoritative; APIM subscription and caller headers are never authorization grants."
  - "Use the public API Container App backend for this rollout, with bearer tokens supplied only through the environment."

patterns-established:
  - "APIM strips or overwrites client identity, scope, grant, subscription, and principal headers before forwarding a validated gateway assertion."
  - "Deployment snapshots contain only non-secret gateway identifiers and policy/backend state; Terraform state remains under backend/operator control."

requirements-completed: [INV-09, INV-10]

coverage:
  - id: D1
    description: "Terraform-managed authenticated, throttled, observable APIM proxy for the reviewed read-only MCP catalog"
    requirement: INV-09
    verification:
      - kind: unit
        ref: "terraform -chdir=infra/terraform fmt -check && terraform -chdir=infra/terraform validate"
        status: pass
      - kind: unit
        ref: "uv run python -m pytest tests/test_apim_iac.py tests/test_gateway_identity_boundary.py -q"
        status: pass
    human_judgment: false
  - id: D2
    description: "Credential-safe live APIM MCP validation and reversible rollback runbook"
    requirement: INV-10
    verification:
      - kind: manual_procedural
        ref: "AIOPS_APIM_MCP_URL=https://aiops-dev-apim.azure-api.net/mcp; ./infra/scripts/validate-apim-mcp.sh"
        status: pass
    human_judgment: true
    rationale: "The live APIM endpoint, tenant consent, backend reachability, and rollback behavior are external deployment facts; operator supplied successful smoke-test confirmation."

duration: 25min
completed: 2026-08-28
status: complete
---

# Phase 9 Plan 8: APIM MCP Gateway Summary

**Dedicated Australia East Developer APIM now governs the read-only Operations MCP endpoint with Entra validation, trusted gateway identity, quotas, telemetry correlation, secret-safe rollout, and rollback controls.**

## Performance

- **Duration:** approximately 25 min including continuation and live deployment validation
- **Started:** 2026-08-28T18:08:25+08:00
- **Completed:** 2026-08-28
- **Tasks:** 2 plan tasks completed; the deployment-target decision checkpoint was resolved as part of the approved dedicated-instance rollout
- **Files modified by the implementation commits:** 12 unique files

## Accomplishments

- Added the declarative APIM MCP proxy and policies for JWT validation, correlation, request limits, quotas, backend authentication, redaction, and exact tool exposure.
- Preserved the API as the final authorization boundary and added regression coverage against forged scope, identity, grant, subscription, and principal headers.
- Added deployment planning/apply/output support, secret-safe snapshots, live smoke validation, and an idempotent rollback runbook.
- Provisioned and validated `https://aiops-dev-apim.azure-api.net/mcp` in the approved Developer/Australia East deployment with the web SPN client-credentials bearer token supplied through the environment.

## Task Commits

1. **Task 1: Trace APIM OAuth request through MCP proxy and backend response** - `ea9d3a1c` (feat)
2. **Task 2: Add stateful deployment, live gateway validation, and rollback controls** - `55282b6b` (feat)

## Validation

- `terraform -chdir=infra/terraform fmt -check` — passed.
- `terraform -chdir=infra/terraform validate` — passed.
- `uv run python -m pytest tests/test_apim_iac.py tests/test_gateway_identity_boundary.py -q` — 6 passed.
- `bash -n infra/scripts/deploy.sh infra/scripts/rollback-apim-mcp.sh infra/scripts/validate-apim-mcp.sh` — passed.
- Operator-confirmed `./infra/scripts/validate-apim-mcp.sh` with `AIOPS_APIM_MCP_URL` and `AIOPS_MCP_BEARER_TOKEN` — passed against the provisioned APIM endpoint.

## Decisions Made

- Selected a dedicated APIM instance rather than sharing an existing gateway, isolating ownership and rollback.
- Confirmed the public Container App backend is the approved backend for this deployment.
- Kept credentials out of command output and artifacts; only the endpoint and bearer-token environment contract is documented.

## Deviations from Plan

None - plan executed as written. The planned deployment-target checkpoint was resolved using the operator-confirmed dedicated APIM instance and supported Developer/Australia East target.

## Issues Encountered

The prior Azure CLI consent blocker recorded in `STATE.md` was cleared by using the web SPN client-credentials token through `AIOPS_MCP_BEARER_TOKEN`. No credentials were committed or written to artifacts.

## User Setup Required

The deployed gateway requires the target tenant/subscription credentials and environment-supplied bearer token for future smoke tests. Do not place tokens in Terraform variables, state, shell history, or committed files.

## Next Phase Readiness

Plan 09-08 is complete and the APIM gateway is live and validated. Plan 09-09 was intentionally not executed. Remaining phase/state caveat: Phase 9 still has the unexecuted 09-09 plan and requires its own execution and verification before the phase can be considered complete.

---
*Phase: 09-consumer-pivot*
*Completed: 2026-08-28*

## Self-Check: PASSED

- Summary file exists.
- Task commits `ea9d3a1c` and `55282b6b` exist in git history.
- Terraform, focused tests, shell syntax checks, and the operator-confirmed live APIM validation passed.
