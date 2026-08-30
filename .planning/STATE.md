# Phase 09-09 Expansion: All 8 Specialist Agents

## Current Phase Status
**Active Plan:** 09-09-EXPANSION-PLAN (all 8 specialist agents)
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
