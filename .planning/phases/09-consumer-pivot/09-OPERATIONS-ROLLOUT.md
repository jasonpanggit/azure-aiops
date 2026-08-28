# Phase 09 Operations MCP / Network Agent Rollout

## Configuration

- APIM MCP endpoint: `https://aiops-dev-apim.azure-api.net/mcp`
- APIM revision: dedicated Australia East Developer gateway from Plan 09-08
- Network specialist contract: `network-finding.v1`
- Network Agent name/version: supplied by `FOUNDRY_NETWORK_AGENT_NAME` and
  `FOUNDRY_NETWORK_AGENT_VERSION`; no deferred domain specialist is bound here.
- Fabric IQ: disabled by default (`AIOPS_ENABLE_FABRIC_IQ=false`). When approved,
  the existing scoped adapter exposes only relationships, topology, and policy
  enrichment and stamps `identity_authority=false`.

## Smoke and rollback procedure

Run with credentials supplied only by the operator environment:

```text
AIOPS_APIM_MCP_URL=https://aiops-dev-apim.azure-api.net/mcp \
  ./scripts/phase9-operations-smoke.sh
```

The script validates initialize, the exact ten-tool allowlist, typed Network
calls, snapshot submission, citation-bearing findings, and byte-identical
non-rehydrating replay. Inspect the same correlation ID in APIM, Container App,
and Application Insights. Logs and artifacts must not contain bearer tokens or
raw snapshot payloads.

Rollback is reversible and read-only from MCP: set `AIOPS_ENABLE_FABRIC_IQ=false`,
remove Network Foundry configuration to force deterministic fallback, disable
the APIM MCP route, and restore the prior Container App/APIM revision using
`infra/scripts/rollback-apim-mcp.sh`. Re-run the smoke contract after each
change. Do not delete or mutate production resources through MCP.

## Validation record

| Check | Result | Evidence |
|---|---|---|
| Focused Network/Fabric IQ tests | PASS | 21 passed |
| Smoke shell syntax | PENDING | Requires operator-run tenant credentials |
| Live APIM → MCP → specialist path | PENDING | Requires `AIOPS_MCP_BEARER_TOKEN` |
| APIM/Container App/Application Insights correlation | PENDING | Operator telemetry review |
| Fabric IQ approved enablement | DISABLED | Tenant governance decision required |
| Rollback rehearsal | PENDING | Must be run by deployment operator |

No credentials, tenant tokens, or raw live payloads are recorded in this
document.
