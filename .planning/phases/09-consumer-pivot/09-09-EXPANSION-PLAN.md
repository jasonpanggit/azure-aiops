# Phase 09-09-EXPANDED: All Specialist Agents

**Status:** Planning phase expansion from Network Agent only → All 8 Specialists  
**Scope Change:** User requested all agents (Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, Executive Summary)  
**Date:** 2026-08-29

---

## Current State (Network Agent Only)

✅ **Completed:**
- APIM MCP authentication blocker fixed
- Network Agent binding + shared specialist-contract infrastructure
- 21 tests passing (Network Agent validation, Fabric IQ governance, foundry agent behavior)
- Deterministic Network findings validated

⏸️ **Deferred to Phase 10 (Original Plan):**
- Vulnerability Agent — CVE exposure, reachability, exploitability
- Patch Agent — Patch priorities, KB remediation, validation
- Incident Agent — Incident timeline, root-cause, unknowns
- Change Agent — Recent changes, correlation to symptoms
- Governance Agent — Owners, scope, approvals, exceptions, policy
- Remediation Agent — Safe remediation options, rollback, validation
- Executive Summary Agent — Synthesizes findings into business impact/decisions

---

## Expansion Plan

### Phase 1: Create Foundry Specialist Agents (All 7)
**Deliverable:** Create Foundry prompt agents for each specialist domain

1. **Vulnerability Agent** — Analyze CVE exposure, exploitability, affected services
   - Tools: cve_exposure, risk_context
   - Prompt: Analyze CVE data against affected assets and reachability
   - Contract: cve_id, affected_services[], exploitability_score, remediation_impact

2. **Patch Agent** — Analyze patch priorities, KB remediation, validation
   - Tools: cve_exposure, remediation_plans
   - Prompt: Analyze patch urgency, KB recommendations, validation scope
   - Contract: kb_id, patch_priority, validation_steps[], rollback_plan

3. **Incident Agent** — Analyze incident timeline, root-cause candidates
   - Tools: incidents
   - Prompt: Synthesize incident data, timeline, root-cause hypotheses, unknowns
   - Contract: incident_id, timeline[], root_causes[], unknowns[], validation_steps[]

4. **Change Agent** — Correlate changes to operational symptoms
   - Tools: incidents, search
   - Prompt: Link recent changes to observed incidents and symptoms
   - Contract: change_id, deployment_date, affected_services[], correlation_confidence

5. **Governance Agent** — Analyze owners, scope, approvals, policy
   - Tools: business_service_context, application_context, risk_context
   - Prompt: Identify ownership, approval requirements, policy/exception context
   - Contract: owner_id, approval_required[], scope[], policy_violations[]

6. **Remediation Agent** — Safe remediation options, rollback, validation
   - Tools: remediation_opportunities, remediation_plans
   - Prompt: Evaluate safe remediation options with rollback/validation plans
   - Contract: remediation_id, option[], rollback_plan, validation_steps[], risk_assessment

7. **Executive Summary Agent** — Synthesize findings into business impact
   - Tools: (receives findings from all other agents)
   - Prompt: Synthesize specialist findings into executive narrative, decisions, plan
   - Contract: business_impact, priority, recommended_actions[], stakeholder_communication

### Phase 2: Implement Per-Agent Output Validation
**Deliverable:** Extend parse_specialist_findings() to validate each agent's contract

- Each agent's output must include: resource_id, evidence_references[], confidence/uncertainty, freshness, actionable_state
- Reject uncited, mutation-capable, or stale-promoted output
- Each agent has domain-specific fields (cve_id, kb_id, incident_id, change_id, owner_id, remediation_id, business_impact)
- Strict schema validation per agent

### Phase 3: Extend Test Coverage
**Deliverable:** Test suite for all 7 agents (parallel to Network Agent tests)

- test_vulnerability_agent.py — CVE exposure contract, exploitation analysis
- test_patch_agent.py — KB remediation, priority assessment
- test_incident_agent.py — Timeline construction, root-cause synthesis
- test_change_agent.py — Change correlation, symptom matching
- test_governance_agent.py — Ownership, approval context
- test_remediation_agent.py — Safe options, rollback validation
- test_executive_summary_agent.py — Finding synthesis, business impact narrative

### Phase 4: Wire Environment Variables
**Deliverable:** Support per-agent Foundry configuration

- FOUNDRY_PROJECT_ENDPOINT (shared across all agents)
- FOUNDRY_NETWORK_AGENT_NAME, FOUNDRY_NETWORK_AGENT_VERSION
- FOUNDRY_VULNERABILITY_AGENT_NAME, FOUNDRY_VULNERABILITY_AGENT_VERSION
- FOUNDRY_PATCH_AGENT_NAME, FOUNDRY_PATCH_AGENT_VERSION
- FOUNDRY_INCIDENT_AGENT_NAME, FOUNDRY_INCIDENT_AGENT_VERSION
- FOUNDRY_CHANGE_AGENT_NAME, FOUNDRY_CHANGE_AGENT_VERSION
- FOUNDRY_GOVERNANCE_AGENT_NAME, FOUNDRY_GOVERNANCE_AGENT_VERSION
- FOUNDRY_REMEDIATION_AGENT_NAME, FOUNDRY_REMEDIATION_AGENT_VERSION
- FOUNDRY_EXECUTIVE_SUMMARY_AGENT_NAME, FOUNDRY_EXECUTIVE_SUMMARY_AGENT_VERSION

### Phase 5: End-to-End Agent Orchestration Tests
**Deliverable:** Validate complete agent selection, execution, and synthesis flow

- Agent selection based on objective/keywords
- Deterministic precedence (MCP tools → agents → findings)
- Parallel agent execution (Vulnerability, Patch, Incident, Change, Governance, Remediation in parallel)
- Executive Summary synthesis from all specialist findings
- Ledger attribution per agent
- Fabric IQ enrichment per agent (bounded scope, kill switch)
- Graceful degradation when agents timeout/fail/deny

### Phase 6: Smoke Tests & Rollback (Live Tenant)
**Deliverable:** Validate live end-to-end flow with all agents

- Run scripts/phase9-operations-smoke.sh with all agents enabled
- Verify each agent returns properly-cited findings
- Test Fabric IQ availability/denial fallback per agent
- Execute rollback rehearsal (disable per-agent, enable/disable APIM MCP route)

---

## Task Breakdown

| Task | Effort | Dependencies | Deliverables |
|------|--------|---|---|
| Create 7 Foundry agents | 2-3h | Foundry tenant access, agent creation script | Agent deployments + names/versions |
| Implement per-agent validation | 4-5h | Foundry agent specs | Extended parse_specialist_findings() |
| Extend test coverage | 3-4h | Agent validation logic | 7 new test modules, 28+ test cases |
| Wire env vars & catalog | 1h | Validation logic | Updated specialist_catalog(), config docs |
| E2E orchestration tests | 3-4h | All above + autonomous_investigation.py | Full agent flow tests + ledger validation |
| Smoke tests & rollback | 1-2h | Live Foundry agents configured | 09-OPERATIONS-ROLLOUT.md updated |
| **Total** | **14-19h** | Tenant configuration | Full 8-agent Operations Copilot |

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| Foundry agents not available | Graceful fallback to deterministic findings + MCP tools |
| Agent output doesn't match contract | Strict parsing rejects invalid output, triggers fallback |
| Latency/timeouts with 8 agents | Parallel execution, per-agent timeouts, circuit breaker |
| Fabric IQ enrichment failures | Kill switch + explicit unavailable state per agent |
| Agent conflicts/contradictions | Ledger surfaces all specialist findings separately; human decides |

---

## Success Criteria

- [ ] All 7 specialist agents created in Foundry and deployed
- [ ] Per-agent output validation implemented and tested
- [ ] All agents can receive curated MCP evidence and produce cited findings
- [ ] Parallel orchestration of 8 agents completes within 10-15s (SLO)
- [ ] Executive Summary synthesizes findings from all specialists
- [ ] 50+ automated tests passing (21 Network + 29 new agents)
- [ ] Live smoke test validates end-to-end flow with all agents
- [ ] Graceful degradation when agents unavailable/timeout/deny
- [ ] Complete ledger attribution and audit trail for all agents
- [ ] 09-09-SUMMARY.md updated with all agents + learnings

---

## Next Steps

1. Obtain Foundry tenant access (if not already configured)
2. Run agent creation script for all 7 agents
3. Implement per-agent output validation
4. Expand test suite
5. Wire environment variables
6. Execute E2E orchestration tests
7. Run live smoke tests
8. Document 09-OPERATIONS-ROLLOUT.md with all agents
