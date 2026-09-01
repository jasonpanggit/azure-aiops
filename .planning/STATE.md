---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: verifying
stopped_at: Completed 10-01-PLAN.md
last_updated: "2026-09-01T07:51:08.161Z"
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 64
  completed_plans: 39
---

# Phase 09-11: Centralized Azure MCP Server in ACA

## Current Phase Status

**Completed Plan:** 09-11-AZURE-MCP-ACA-PLAN  
**Scope:** Deploy Azure MCP server as standalone container in ACA. All 8 specialist agents delegate tool calls through APIM proxy with governed multi-subscription credential management.  
**Status:** ✅ COMPLETE — Microsoft's official Azure MCP Server deployed standalone in ACA behind APIM, authenticating via a dedicated user-assigned managed identity (`azurerm_user_assigned_identity.azure_mcp`) with per-subscription role assignments (`local.azure_mcp_subscriptions` for-each), rather than the originally-scoped SPN+AKV credential model — achieves the same governed multi-subscription access with less credential-rotation surface. Per-specialist tool registry (`foundry_tool_registry`, 32 entries) and explicit dual-MCP routing rule (operations-mcp = curated/Fabric, azure-mcp = live/authoritative) are wired into all 8 specialist instructions. This session additionally: gave the network specialist `arm_execute_query` (Resource Graph) as a live fallback tool, and fixed classic Azure Firewall inline rule-collection ingestion so the network agent can see application/network rules without needing the fallback in the common case. Built, deployed, and verified live on ACA (`main-20260831-110941`).

## Previous Phase Status (09-10)

**Completed Plan:** 09-10-MAF-PIVOT-PLAN  
**Scope:** Operations Copilot as the orchestrator, with MAF-style question-first specialist delegation across Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, and Executive Summary agents.  
**Status:** ✅ COMPLETE — MAF is the default Operations Copilot orchestration mode; deterministic routing remains available as an explicit rollback.

## Previous Phase Status

**Completed Plan:** 09-09-EXPANSION-PLAN (all 8 specialist agents)  
**Scope:** Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary agents  
**Status:** ✅ COMPLETE — all 8 agents verified working end-to-end via APIM → MCP → Fabric/backend.

## Completed Work

- **Phase 8 (Terraform):** ✅ All 8 specialist agents deployed to container app with env vars
- **Test Cleanup:** ✅ Fixed test_foundry_agent.py (15/15 passing); removed outdated test_investigation_specialist_routing.py
- **Wave 4 (Orchestration):** ✅ Extended routing to support all 8 page_kinds
  - Updated page_specialists mapping in autonomous_investigation.py
  - Enabled answer_findings() for all page_kinds (not just network)
  - Added per-agent contract validation via agent_id parameter
  - Created 7 foundry prompt templates (change, executive_summary, governance, incident, patch, remediation, vulnerability)
- **Wave 1 (Foundry Agent Creation):** ✅ All 8 agents created/recreated in Foundry with native MCP tool-calling wiring
  - Fixed a pre-existing Python f-string syntax bug in `create-foundry-agent.sh` (invalid on Python <3.12) blocking `terraform_data.foundry_agent` local-exec
  - Per-specialist `tools` allocation confirmed live: network (4 dedicated + 6 generic), vulnerability (3+6), incident (1+6), remediation (2+6), patch/change/governance/executive_summary (6 generic only)
- **Wave 5 (APIM + MCP wiring):** ✅ Complete
  - Created `azapi_resource.foundry_mcp_connection` — Foundry project → APIM native `/mcp-server` MCP connection (ProjectManagedIdentity auth)
  - Attached `mcp-inbound.xml` auth policy to the native `/mcp-server` API surface (previously unauthenticated gap, now closed)
  - Fixed APIM `/mcp-server` HTTP 500 (JWT claim null-ref + header handling bugs in the MCP dispatcher)
  - Fixed MCP tool-call response format so isError/tool-error results don't crash the Foundry .NET MCP client
  - Raised APIM's self-imposed rate-limit policy from 60→300 calls/60s (multi-tool-call agent turns were tripping it)
  - Fixed `MAX_CALLS=25` bug: was a lifetime, per-process singleton cap on the MCP dispatcher (not per-request) — any container would permanently break after 25 total tool calls across all users. Raised to 100,000 as a coarse safety net; real per-caller throttling lives in APIM's rate-limit-by-key/quota-by-key policies.
  - Fixed empty-string (`""`) optional tool argument handling: Pydantic's `min_length=1` rejected the common LLM pattern of sending `""` to mean "no filter" on an optional field. Blank strings are now stripped before validation.
  - Granted the Foundry project's managed identity `reader` role via `AIOPS_ENTRA_GRANTS_JSON`, propagated to the live API container.
- **Wave 6 (End-to-end smoke testing):** ✅ Complete — all 8 specialists confirmed HTTP 200 via the Responses API (`agent_reference` + `/openai/v1/responses`), each autonomously calling its assigned MCP tools and returning evidence-cited output. `network-agent` spot-checked with full structured `findings` JSON (real resource IDs, real policy gaps, correctly-bounded `next_check`). `vulnerability-agent` spot-checked with real CVE/KB evidence citations.
  - `src/operations/foundry_agent.py` (production Python client) verified compatible with the tool-calling response shape with no changes needed: `_extract_text` correctly parses `mcp_call`/`mcp_list_tools`/`message` output items; `_post_once`/`_post` surface tool-calling errors (400s, retryable 5xxs) as clear exceptions.
- **Environment fixes (unrelated to code, discovered during testing):**
  - Fabric capacity (`aiopsdevcapg6ludc`) was paused — resumed via `az resource invoke-action ... resume`.
  - `deploy.sh`'s `apim_publisher_email` env var was unset, causing a confusing "publisher_email may only be up to 100 characters" Terraform error (empty string tripped that validator instead of a "required" one). Permanently set in `web/.env.local`.
  - `deploy.sh` didn't wire `foundry_model_capacity`, so a manual TPM quota increase (50→1000) was silently reverted by every `terraform apply`. Added `AIOPS_FOUNDRY_MODEL_CAPACITY` env var wiring to `deploy.sh` + `.env.local` to make the increase durable.

## Verification Constraint Honored

**Zero changes to `azurerm_api_management.main` across all applies this phase** — user's explicit "don't destroy APIM" requirement was maintained throughout (confirmed via `terraform show`/plan diffs on every apply).

## Test Status

- foundry_agent.py: 15/15 ✅ (plus manual live verification against real tool-calling responses this session)
- Full suite: 1583/1587 ✅ (4 pre-existing failures in unrelated areas, last checked pre-session)
- All 8 specialist agents: ✅ manually verified end-to-end via curl against the live Foundry Responses API this session

## Technical Details

- **Page Kind Routing:** All 8 agents routable via page_kind (e.g., vulnerability_page → vulnerability agent)
- **Per-Agent Contracts:** Each specialist validates required fields via _agent_contract()
- **Foundry Integration:** answer_findings() now supports all page_kinds; passes agent_id for validation
- **APIM State:** Enabled and fully wired — native `/mcp-server` MCP API + plain-HTTP `/mcp` proxy API both live, both policy-protected
- **Real agent names** (Foundry-registered, used in `agent_reference.name`): `aiops-{specialist_id}-agent` (e.g. `aiops-network-agent`), all on version matching the latest `terraform_data.foundry_agent` apply.

## Next Steps

Phase 09-09 objectives are met. Suggested follow-ups (not blocking):

1. Commit the accumulated code fixes (mcp_server.py, apim-policies/mcp-inbound.xml, deploy.sh, web/.env.local) — currently uncommitted working-tree changes.
2. Consider whether Foundry's "single tool error hard-fails the whole turn" behavior (seen when a model calls a tool with genuinely invalid/missing required args) warrants further prompt tuning per specialist, since it can't be fixed server-side.
3. Clean up now-unused container app revisions (multiple test-tag revisions accumulated this session: mcp-toolerror-fix, mcp-maxcalls-fix, mcp-emptystr-fix).

## Active Pivot: Microsoft Agent Framework Orchestrator

**Status:** Complete — MAF default cutover implemented and validated.  
**Decision:** Adopt MAF as the forward orchestration model because users ask arbitrary cross-domain questions from any page, so page-scoped specialist routing is the wrong UX contract.  
**Guardrail:** MAF is now the default. Use `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic` only for rollback to the legacy page-anchored flow.

### Current Slice

- Added a MAF orchestration boundary that records `microsoft-agent-framework` when the SDK is present and `maf-compatible` otherwise.
- In MAF mode, Operations Copilot selects specialists from the operator's question first, then falls back to page context only if no specialist intent matches.
- Contextual investigation ledgers now expose `selected_agents` and an `orchestration` decision for evaluation.
- Regression tests cover the Network drawer delegating an ownership/policy question to Governance without changing pages.
- Added `agent-framework` and compatible `azure-ai-projects>=2.0,<3` dependencies to the API optional dependency group and refreshed `uv.lock`.
- Added a Microsoft Agent Framework Foundry adapter that invokes hosted/prompt agents through `agent_framework.foundry.FoundryAgent` when the MAF pivot flag is enabled.
- Extended `scripts/evaluate_agents.py` so deterministic and MAF-mode runs are compared against their respective routing contracts.
- Deployed API/web image tag `maf-pivot-20260830-234852` with `AIOPS_AGENT_ORCHESTRATION_MODE=maf`; Terraform updated only Container Apps in place (`0 added, 2 changed, 0 destroyed`).
- Live revisions `aiops-dev-api--0000140` and `aiops-dev-web--0000107` are healthy and serve `maf-pivot-20260830-234852`.
- Live MAF evaluation artifact `.planning/eval/maf-full-20260831.json` passed 10/10 narration, 10/10 tool correctness, and 100% scored routing with `microsoft-agent-framework` recorded for all 10 cases. The two full-pass wall-clock timeouts passed on focused rerun in `.planning/eval/maf-timeout-rerun-20260831.json`.
- Browser validation passed on the deployed Network drawer for `What depends on demo-vnet?`: Operations Copilot returned a direct Foundry-narrated dependency answer, no duplicated findings dump, no browser console warnings, and response metadata recorded `microsoft-agent-framework` + `question_first` + `selected_ids=["network"]`.
- Parity review: MAF matches deterministic baseline on routing, narration, and tool correctness, and improves median latency, but the full pass had 2 wall-clock timeouts versus 1 baseline timeout. Decision: keep MAF enabled for guarded validation; do not make it the default until a clean full pass or timeout-budget mitigation lands.
- Timeout mitigation landed: optional Fabric IQ enrichment now runs only after required specialist delegation, and completed contextual runs are no longer mislabeled as wall-clock timeouts after successful specialist/narration work. Deployed image tag `maf-timeoutfix-20260831-002339`; live full evaluation `.planning/eval/maf-timeoutfix-full-20260831.json` passed 10/10 cases with 0 errors, 0 timeouts, 100% routing, 100% narration, 100% tool correctness, and `microsoft-agent-framework` recorded for all cases.
- Default cutover approved and implemented: code defaults to MAF, Terraform defaults `agent_orchestration_mode` to `maf`, and `deploy.sh` preserves MAF unless explicitly overridden with `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`.

### Blockers / Open Items

- Deterministic rollback remains available with `AIOPS_AGENT_ORCHESTRATION_MODE=deterministic`.

## Files Modified (this session)

- `infra/scripts/create-foundry-agent.sh` (Python f-string syntax fix)
- `infra/terraform/apim.tf` (mcp_server_policy resource — attached auth policy to native `/mcp-server`)
- `infra/terraform/apim-policies/mcp-inbound.xml` (rate limit 60→300 calls/60s)
- `infra/scripts/deploy.sh` (wired `AIOPS_FOUNDRY_MODEL_CAPACITY` env var)
- `web/.env.local` (added `AIOPS_ENTRA_GRANTS_JSON` Foundry principal grant, `AIOPS_APIM_PUBLISHER_EMAIL`, `AIOPS_FOUNDRY_MODEL_CAPACITY`)
- `src/operations/mcp_server.py` (JWT/header fixes, MCP-spec-compliant error responses, MAX_CALLS lifetime-cap fix, empty-string argument handling)

## Files Modified (prior sessions, unchanged this session)

- src/operations/autonomous_investigation.py (routing, answer_findings logic)
- src/operations/foundry_agent.py (agent_id parameter to parse_specialist_findings) — re-verified compatible this session, no changes needed
- src/operations/foundry_prompts/*.txt (7 new prompt templates)
- infra/terraform/foundry.tf (per-specialist tool allocation, MCP connection resource, prompts)

## Accumulated Context

### Roadmap Evolution

- Phase 10 added: Fabric Medallion Capability Expansion

## Performance Metrics

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 10 P01 | 32min | 3 tasks | 63 files |

## Decisions

- [Phase ?]: Phase 10 Plan 1: stabilized and committed the fix-ontology-sync-publish working tree in 5 reviewable git slices; reconciled ontology-schema.md as sole canonical ontology schema doc

## Session

**Last session:** 2026-09-01T07:51:08.146Z
**Stopped at:** Completed 10-01-PLAN.md
**Resume file:** None
