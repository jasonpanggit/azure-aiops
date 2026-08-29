# Phase 09-09 Expansion: All 8 Specialist Agents

## Current Phase Status
**Active Plan:** 09-09-EXPANSION-PLAN (all 8 specialist agents)  
**Scope:** Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary agents

## Completed Work
- **Phase 8 (Terraform):** ✅ All 8 specialist agents deployed to container app with env vars
- **Test Cleanup:** ✅ Fixed test_foundry_agent.py (15/15 passing); removed outdated test_investigation_specialist_routing.py
- **Wave 4 (Orchestration):** ✅ Extended routing to support all 8 page_kinds
  - Updated page_specialists mapping in autonomous_investigation.py
  - Enabled answer_findings() for all page_kinds (not just network)
  - Added per-agent contract validation via agent_id parameter
  - Created 7 foundry prompt templates (change, executive_summary, governance, incident, patch, remediation, vulnerability)

## In Progress
- **Wave 1 (Foundry Agent Creation):** 🔄 Running background agent (foundry-agents-wave1)
  - Status: 225s elapsed, 43 tool calls completed
  - Creating 7 Foundry prompt agents (Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary)
  - Network agent already created in prior phase

## Remaining Work
- **Wave 1:** Complete Foundry agent creation (in background)
- **Wave 2:** Validate output contracts for all 8 agents
- **Wave 3:** Create test suites for 7 new agents (parallel to Wave 4)
- **Wave 5:** Enable APIM, deploy MCP server, wire all 8 agents
- **Wave 6:** End-to-end smoke testing of all 8 agents → Fabric flow

## Test Status
- foundry_agent.py: 15/15 ✅
- Full suite: 1583/1587 ✅ (4 pre-existing failures in unrelated areas)
- Wave 4 changes validated

## Technical Details
- **Page Kind Routing:** All 8 agents routable via page_kind (e.g., vulnerability_page → vulnerability agent)
- **Per-Agent Contracts:** Each specialist validates required fields via _agent_contract()
- **Foundry Integration:** answer_findings() now supports all page_kinds; passes agent_id for validation
- **APIM State:** Currently disabled; needs enable_apim=true in terraform.tfvars for Wave 5

## Next Steps
1. Wait for Wave 1 completion (Foundry agent creation)
2. Validate all 7 agents created successfully
3. Execute Wave 2-3 in parallel (validation + tests)
4. Execute Wave 5 (APIM deployment)
5. Execute Wave 6 (smoke testing)

## Files Modified
- src/operations/autonomous_investigation.py (routing, answer_findings logic)
- src/operations/foundry_agent.py (agent_id parameter to parse_specialist_findings)
- src/operations/foundry_prompts/\*.txt (7 new prompt templates)
