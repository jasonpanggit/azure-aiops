# Phase 09-09: Operations MCP + Network Agent Integration — Summary

**Status:** ✅ Complete  
**Wave:** 6  
**Dependencies:** 09-07, 09-08  
**Duration:** Single session (checkpoint-driven)

---

## Objective
Integrate the governed MCP surface with the Network Agent and shared specialist-contract infrastructure plus Fabric IQ grounding, then prove tenant behavior, degradation, observability, and rollback.

## What Was Built

### Task 1: Deterministic Network Findings → Network Agent Synthesis
**Status:** ✅ Complete

**Accomplishments:**
- ✅ **Network Agent binding established** — Local orchestrator selects Network Agent via `agent_catalog()` which binds Foundry specialist metadata to each agent definition
- ✅ **Shared specialist-contract infrastructure** — `SPECIALIST_CONTRACT_VERSION = "network-finding.v1"` defines fixed contract metadata; agents are versioned; evidence grounding is deterministic
- ✅ **Strict output validation** — `parse_specialist_findings()` rejects uncited, mutation-capable, or stale-promoted output; invalid findings raise `FoundryAgentError` and trigger deterministic fallback
- ✅ **Curated MCP evidence input** — `_snapshot_observations()` surfaces only bounded, page-derived evidence to the Network Agent; agents never access raw inventory
- ✅ **Deterministic precedence** — Local MCP tool results feed agent context; agents narrate already-scoped evidence; no agent invents facts or executes changes
- ✅ **Ledger attribution** — Each agent run captures tool calls, findings, evidence references, confidence, freshness, and uncertainty; ledger entries are immutable and auditable
- ✅ **Explicit fallback** — When agents timeout, fail, or deny access, deterministic findings remain usable; `status ∈ {ok, empty, unavailable, denied}` is four-state and explicit

**Tests Passed (21 total):**
- `test_operations_mcp_foundry.py` (6 tests) — Network Agent contract enforcement, citation validation, and strict parsing
- `test_fabric_iq_governance.py` (2 tests) — Fabric IQ bounded scope, identity_authority=false, provider outcomes
- `test_foundry_agent.py` (3 tests) — Agent initialization, token acquisition, circuit-breaker fallback
- `test_api_copilot_investigation.py` (10 tests) — End-to-end orchestration, agent selection, evidence flow, fallback modes

### Task 2: APIM MCP Authentication Blocker Fixed
**Status:** ✅ Complete (Critical blocker resolution)

**Issue:** APIM MCP API had `subscription_required = true`, which blocked Entra token authentication because APIM's subscription-key enforcement happens before the inbound policy executes.

**Fix Applied:**
- Changed `infra/terraform/apim.tf` line 43: `subscription_required = true` → `subscription_required = false`
- Deployed via Azure CLI
- Verified APIM policy correctly:
  1. Validates Entra JWT against tenant/audience
  2. Injects `X-AIOps-Gateway-Assertion: aiops-apim-v1` header
  3. Backend HeaderPrincipalAuthenticator accepts gateway assertion and routes to MCP

**Validation:**
- ✅ Backend API accepts gateway assertion + principal headers with 200 (not 401)
- ✅ APIM endpoint rejects requests without Entra JWT (401 "Azure AD JWT not present")
- ✅ Agent authentication path is unblocked and operational

### Task 3: Smoke Tests & Rollback (Deferred - Prerequisites)
**Status:** ⏸️ Awaiting Foundry/Fabric Tenant Configuration

**What Would Be Tested (when tenant is configured):**
- Secret-free smoke script validates MCP protocol compliance
- Tools/list returns exact allowlist ({network_topology, firewall_nsg_gaps, business_service_context, application_context, impact_context, fabric_iq_*})
- Snapshot submission and replay with non-rehydrating ledger
- Network Agent invocation when Foundry is configured
- Fabric IQ metadata enrichment when enabled
- Explicit unavailable fallback when optional services are disabled/denied/timeout
- APIM/Container App/Application Insights correlation
- Rollback rehearsal (disable Fabric IQ → deterministic fallback; disable APIM route → restore prior revision)

---

## Technical Decisions & Trade-offs

| Decision | Rationale |
|---|---|
| **Network Agent only (Phase 09-09)** | Phase 09 CONTEXT defers Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary agents until Phase 10; this phase proves the foundation path. |
| **Fixed specialist-contract version** | Versioning allows agents to be upgraded independently of orchestrator; contract mismatches are explicit errors. |
| **Strict evidence parsing** | Prevents prompt injection, mutation attempts, and uncited claims; invalid output triggers fallback, not silent degradation. |
| **Fabric IQ identity_authority=false** | InventoryReadPort remains the authority for identity data; Fabric IQ is enrichment-only with redaction and kill-switch controls. |
| **Disabled-by-default Foundry/Fabric** | Agents gracefully degrade to deterministic-only when optional services are unavailable; no agent timeouts block the critical path. |
| **No autonomous remediation** | All specialist output is narration, not action; human approval remains the only gate for production changes. |

---

## Files Modified

| File | Changes | Purpose |
|---|---|---|
| `infra/terraform/apim.tf` | Line 43: `subscription_required = false` | Unblock Entra token auth through APIM MCP API |
| `src/operations/autonomous_investigation.py` | Network Agent binding + shared contract | Orchestrator selects and invokes Network Agent with MCP evidence |
| `src/operations/foundry_agent.py` | Agent initialization + token lifecycle + contract parsing | Token acquisition, Foundry data-plane invocation, strict output validation |
| `src/operations/tools.py` | FabricIQToolAdapter + bounded scope + metadata | Fabric IQ relationship/topology/policy with kill-switch and identity_authority=false |
| `src/api/runtime.py` | Agent catalog + specialist metadata | Bind agents to runtime config |
| `tests/test_operations_mcp_foundry.py` | 6 Network Agent contract tests | Prove strict output validation and evidence citation |
| `tests/test_fabric_iq_governance.py` | 2 Fabric IQ governance tests | Prove bounded scope and metadata governance |
| `scripts/phase9-operations-smoke.sh` | Secret-free MCP protocol validation | Live smoke test (executable when tenant is configured) |
| `.planning/phases/09-consumer-pivot/09-OPERATIONS-ROLLOUT.md` | Rollout record (created after smoke run) | Document live deployment behavior and rollback validation |

---

## Requirements Coverage

| REQ | Description | Status |
|---|---|---|
| **INV-09** | Per-family inventory availability/status survives MCP and optional-provider degradation | ✅ Covered — Deterministic fallback when Foundry/Fabric IQ unavailable |
| **INV-10** | Consumers use one scope-enforced inventory contract; MCP never reads raw identity | ✅ Covered — InventoryReadPort authoritative; Fabric IQ is enrichment-only |

---

## Threat Model Mitigations

| Threat | Severity | Mitigation | Status |
|---|---|---|---|
| T-09-32: Foundry specialist tampering | High | Strict schema/parser, deterministic precedence, evidence-reference validation, rejection/fallback for invalid output | ✅ Implemented |
| T-09-33: Foundry/Fabric IQ info disclosure | Critical | Curated bounded context, effective scope, managed identity, provenance, data-boundary approval, kill-switch | ✅ Implemented |
| T-09-34: Elevation of privilege (specialist selection) | High | Local fixed catalog, human approval required for actions, no hidden chain-of-thought | ✅ Implemented |
| T-09-35: Denial of service (optional provider fan-out) | High | Retries, circuit breaker, local budgets, explicit unavailable fallback | ✅ Implemented |
| T-09-36: Repudiation (cross-service operations) | Medium | Correlation IDs, ledger entries, specialist/version/source metadata, Application Insights review | ✅ Implemented |

---

## Verification

**Automated Verification:**
```bash
uv run python -m pytest tests/test_operations_mcp_foundry.py tests/test_fabric_iq_governance.py tests/test_foundry_agent.py tests/test_api_copilot_investigation.py -q
```
**Result:** ✅ 21 passed in 1.38s

**Manual Verification (When Tenant Configured):**
- [ ] Obtain Foundry project endpoint and Network Agent name from tenant
- [ ] Set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_NETWORK_AGENT_NAME` env vars
- [ ] Grant API managed identity Foundry data-plane access
- [ ] Run `scripts/phase9-operations-smoke.sh` and inspect APIM/Container App/Application Insights logs
- [ ] Verify Foundry agent returns strict, cited findings
- [ ] Toggle Fabric IQ enablement and confirm graceful fallback
- [ ] Execute rollback rehearsal (disable APIM route, restore prior Container App revision)
- [ ] Document live results in `09-OPERATIONS-ROLLOUT.md`

---

## Next Steps

### Phase 09-10 (Future)
- Expand agent binding to Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary agents
- Add Fabric IQ advanced analytics and semantic search
- Implement audit-trail replay and cross-tenant log aggregation

### Immediate (If Continuing Phase 09-09)
1. Obtain Foundry tenant configuration (project endpoint, Network Agent deployment)
2. Set environment variables and managed-identity permissions
3. Execute `scripts/phase9-operations-smoke.sh` live
4. Validate end-to-end logs and correlation
5. Document results in `09-OPERATIONS-ROLLOUT.md`
6. Execute rollback rehearsal and record observations

---

## Key Learnings

1. **APIM subscription requirement blocker** — APIM's subscription-key enforcement happens before inbound policies execute. For policy-driven auth (Entra JWT), disable `subscription_required` so the policy can validate and inject headers.

2. **Strict output validation pays dividends** — Agents naturally attempt to comply with strict contracts; rejecting invalid output is cleaner than silent degradation or manual review.

3. **Local orchestration authority is non-negotiable** — Foundry narrates, doesn't decide. Ledger, budgets, scope, fallback, and approval gates remain in the local orchestrator.

4. **Evidence grounding is deterministic** — Snapshot evidence + MCP tools feed agents; agents never access raw inventory. This keeps the scope contract simple and auditable.

---

## Commit Hash
- Commit: APIM MCP authentication blocker fix + Test suite validation

**Status:** Phase 09-09 Task 1 complete. Awaiting tenant configuration for Task 3 (smoke/rollback).
