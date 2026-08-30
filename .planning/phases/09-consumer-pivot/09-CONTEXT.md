# Phase 9: Consumer Pivot - Context

**Gathered:** 2026-08-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Pivot resource-identity consumers to the unified inventory read port while extending the existing multi-agent surface into a page-aware Operations Copilot. Deliver a shared contextual Copilot entry point, a versioned page-context contract, governed specialist delegation, and cited policy-grounded analysis beginning with Network Agent. Preserve existing investigation ledger, human controls, scope isolation, explicit evidence/freshness/uncertainty, and deterministic fallback behavior.

</domain>

<decisions>
## Implementation Decisions

### Page context contract
- Each supported page sends a bounded snapshot envelope representing the state the user actually saw: selected resource or resources, page/view context, active filters, source freshness, scope authorization, and explicitly named evidence rows.
- The envelope is versioned and typed, with a small shared core plus named evidence sections; it is not arbitrary page JSON.
- The backend analyzes the supplied snapshot directly for reproducible citations and replay. Identifiers may be included for explicit recheck/freshness operations, but routine analysis must not silently rehydrate a different view.

### Orchestration and Foundry boundary
- Use hybrid governed orchestration. The local service remains responsible for authorization and scope, context validation, specialist selection, bounded concurrency, timeouts, retries, ledger/audit state, human actions, and Foundry-unavailable fallback.
- Operations Copilot is agentic within explicit controls: it may plan, choose allowlisted governed tools, request additional evidence, delegate multiple specialists, and reassess results in a bounded loop. Enforce step and time budgets, evidence requirements, scope checks, and human approval gates.
- Foundry prompt agents provide specialist reasoning and synthesis over curated evidence; they do not acquire ungoverned data or perform production changes.
- Use separate named Foundry prompt agents per domain (Network, Vulnerability, Patch, Incident, Change, Governance, Remediation, and Executive Summary) so prompts, ownership, evaluation, and releases can be controlled independently.
- Keep `/agents` as the full investigation workspace and shared ledger view; page-level Copilot invokes the same orchestrator rather than creating separate agent UX.

### Fabric IQ integration
- Use Fabric IQ as a governed semantic/tool plane: its ontology and OneLake-backed data may provide relationship-aware queries, topology context, and policy/domain context to the agentic loop.
- The unified inventory read port remains the operational identity authority. Fabric IQ must not silently replace resource identity resolution or bypass the API scope and evidence contracts.
- Treat Fabric IQ responses as explicitly sourced evidence with freshness, authorization, and provenance metadata, and preserve the page snapshot as the primary citation context.

### Policy-grounded analysis and findings
- Policy compliance is evaluated through deterministic, machine-verifiable policy/check outcomes wherever rules are known. Foundry interprets, prioritizes, explains, and synthesizes those outcomes rather than replacing the check layer.
- Network Agent is the first concrete specialist: it may analyze observed topology against design policy and Azure best-practice checks, including NSG, route, firewall, segmentation, and blast-radius concerns, only from supplied evidence.
- A finding must include resource IDs, policy/check IDs, evidence references, confidence or uncertainty, and a bounded suggested next check. Unsupported claims remain hypotheses and cannot silently become remediation actions.
- The response must distinguish verified findings, hypotheses, stale/partial evidence, and next checks; no hidden chain-of-thought is exposed.

### Copilot entry-point UX
- Add a persistent compact, icon-first Copilot launcher on supported pages that opens a contextual side panel using the current page snapshot.
- Keep the full `/agents` page for investigation activity, reconciliation, ledger, evaluation, and human controls rather than replacing it with the side panel.
- Use one concise visual treatment consistently across pages while retaining accessible names/tooltips, keyboard and screen-reader support, discoverability, and theme-aligned hover/focus states.
- Show explicit staged states for loading/progress, partial evidence, Foundry-unavailable deterministic fallback, retry, and failures; never imply an LLM result was produced when it was not.
- Fold the pending UI todo `.planning/todos/pending/2026-08-27-refine-ui-copilot-visual-language.md` into this phase.

### the agent's Discretion
- Exact envelope field names, schema technology, payload size limits, and compatibility/version negotiation, provided the typed/versioned and bounded decisions above hold.
- Exact Foundry prompt text, model/deployment selection, and provisioning/IaC mechanism, provided prompts are independently versioned and outputs satisfy the finding contract.
- Exact specialist execution order and batching, provided local orchestration enforces bounded latency, failure isolation, and ledger visibility.
- Exact side-panel dimensions, icon, copy, and responsive breakpoints, provided the shared accessibility and staged-state requirements hold.
- Exact split between API read-port tools and Fabric IQ ontology tools, provided each tool is allowlisted, scope-checked, provenance-bearing, and represented in the ledger.

</decisions>

<specifics>
## Specific Ideas

- The desired interaction is “ask the copilot about this page,” not “open a different agent app.”
- A topology page should be able to ask Network Agent to compare what is visible against design policy and Azure best practices, flag gaps with cited evidence, explain evidence quality, and recommend bounded validation steps.
- The page snapshot should preserve the context that generated the answer so a later reviewer can understand what the operator saw and which sources were fresh at that time.
- Foundry-unavailable behavior should be explicit and useful: deterministic evidence/check output remains available, but the UI identifies that LLM synthesis was not produced.
- Fabric IQ should strengthen relationship-aware and cross-domain reasoning without becoming an ungoverned second identity source.

</specifics>

<canonical_refs>
## Canonical References

### Phase constraints and inventory ownership
- `.planning/ROADMAP.md` §Phase 9: Consumer Pivot — phase scope, existing agent seams, and success criteria.
- `.planning/STATE.md` — current API-triggered Hermes/Fabric migration boundary and phase status.
- `.planning/phases/08-resource-identity-plane/08-CONTEXT.md` — locked identity ownership, topology, evidence, provenance, freshness, uncertainty, and authorization decisions.
- `.planning/phases/07-unified-resource-inventory/07-CONTEXT.md` — unified inventory read-port contract and consumer migration constraints.
- Official Microsoft guidance: [Connect agents to Microsoft Fabric with Fabric IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq) — ontology/tool integration, authentication, and preview constraints to verify during research.
- Official Microsoft guidance: [Create an Ontology Agent with Foundry IQ](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq) — Fabric ontology agent patterns to evaluate for relationship-aware operations analysis.

### Existing agent and UI implementation
- `src/api/routers/multi_agent.py` — current agent catalog, investigation, ledger, and human-action API contract.
- `src/operations/autonomous_investigation.py` — deterministic specialist orchestration, bounded execution, synthesis, evaluation, and ledger behavior.
- `src/operations/foundry_agent.py` — current Foundry prompt-agent client, retries, circuit breaker, and deterministic fallback.
- `web/src/app/agents/page.tsx` — existing full investigation workspace and reference interaction model.
- `web/src/lib/services.ts` — frontend service wrappers for the multi-agent API.
- `.planning/todos/pending/2026-08-27-refine-ui-copilot-visual-language.md` — folded visual-language and accessibility requirements.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/operations/autonomous_investigation.py` already defines specialist roles, governed tool calls, bounded parallel execution, synthesis, evaluation, and human-ledger actions; extend its seam rather than creating a second orchestrator.
- `src/operations/foundry_agent.py` already supplies Entra-authenticated Foundry REST invocation, timeout/retry/circuit-breaker behavior, and explicit degradation.
- `web/src/app/agents/page.tsx` provides the full investigation workspace, including activity, reconciliation, synthesis, evaluation, and ledger display.
- `web/src/lib/services.ts` is the established client boundary for agent API calls.

### Established Patterns
- API routers depend on registered providers through `runtime.py`; resource identity should move to the inventory read port without changing route contracts.
- Evidence, provenance, freshness, uncertainty, authorization, and resource IDs are first-class constraints from prior phases.
- Human actions are recorded in the investigation ledger; production remediation is not autonomous.

### Integration Points
- Add a page-context/orchestrator request path alongside the existing `/api/v1/agents/*` contract, or evolve that contract without breaking the full investigation workspace.
- Wire resource identity consumers, especially `hermes_arg_connector/agent_queries.py`, to the inventory read port while keeping patch assessment reads in the patch domain.
- Add a shared web Copilot launcher/side panel usable by supported pages and pass their typed snapshot to the backend.
- Connect deterministic policy/check results and Foundry specialist outputs into the existing evidence, reconciliation, evaluation, and ledger model.

</code_context>

<deferred>
## Deferred Ideas

- Moving delegation, workflow state, or approvals into Foundry-managed orchestration/Agent Service workflows.
- Replacing `/agents` with only a universal side panel.
- Autonomous production remediation or unreviewed execution of suggested changes.
- Letting Foundry evaluate raw infrastructure/policy data without deterministic checks and evidence references.
- Expanding to every specialist domain before the Network Agent path and shared contracts are proven.

</deferred>

---

*Phase: 09-consumer-pivot*
*Context gathered: 2026-08-28*
