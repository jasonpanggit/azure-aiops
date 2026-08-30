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
| Live APIM → MCP → specialist path (all 8 agents) | PASS | Manually verified via curl against `/openai/v1/responses` for `aiops-network-agent`, `aiops-vulnerability-agent`, `aiops-incident-agent`, `aiops-remediation-agent`, `aiops-patch-agent`, `aiops-change-agent`, `aiops-governance-agent`, `aiops-executive-summary-agent` — all returned HTTP 200 with tool-backed, evidence-cited output |
| Native `/mcp-server` APIM auth policy | PASS | `mcp-inbound.xml` now attached; unauthenticated-gap closed |
| `foundry_agent.py` production client compatibility | PASS | `_extract_text` verified against a real live tool-calling response (`mcp_call`/`mcp_list_tools`/`message` items); error surfacing verified via `_post_once` |
| APIM/Container App/Application Insights correlation | PENDING | Operator telemetry review |
| Fabric IQ approved enablement | DISABLED | Tenant governance decision required |
| Rollback rehearsal | PENDING | Must be run by deployment operator |

Bugs found and fixed during this validation pass (see `.planning/STATE.md` for
full detail): APIM `/mcp-server` 500 (JWT/header handling), MCP tool-error
response format (was crashing the Foundry .NET MCP client), a per-process
lifetime `MAX_CALLS=25` cap on the MCP dispatcher (raised to 100,000 — real
throttling is APIM's rate-limit-by-key/quota-by-key), and Pydantic rejecting
empty-string optional tool arguments (a common LLM "no filter" pattern).

No credentials, tenant tokens, or raw live payloads are recorded in this
document.
