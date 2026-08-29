# Phase 9: Consumer Pivot — Research

**Researched:** 2026-08-28  
**Domain:** Governed Operations MCP, Azure API Management, Microsoft Foundry specialists, Fabric IQ  
**Confidence:** MEDIUM (repository seams HIGH; APIM/Fabric IQ preview and tenant behavior MEDIUM)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
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

### Deferred Ideas (OUT OF SCOPE)
- Moving delegation, workflow state, or approvals into Foundry-managed orchestration/Agent Service workflows.
- Replacing `/agents` with only a universal side panel.
- Autonomous production remediation or unreviewed execution of suggested changes.
- Letting Foundry evaluate raw infrastructure/policy data without deterministic checks and evidence references.
- Expanding to every specialist domain before the Network Agent path and shared contracts are proven.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|---|---|---|
| INV-09 | Inventory availability and source status are reported per family. | Preserve the read-port family status and warnings through MCP and Copilot responses; never collapse one unavailable family into a provider-wide empty result. `[VERIFIED: src/intelligence/inventory/read_port.py:10-42]` |
| INV-10 | Consumers use one scope-enforced Fabric-backed inventory contract. | Keep resource identity behind `InventoryReadPort`; MCP tools must call the API/provider seam, not read OneLake files or raw datasets. `[VERIFIED: src/api/runtime.py:1128-1135,1364-1369]` |
</phase_requirements>

## Summary

Add a separate governed Operations MCP server surface over the existing API/domain seams; do not make Foundry or Fabric IQ the authorization boundary. The server should expose a deliberately small, read-only tool catalog first, with JSON-schema contracts, bounded arguments/results, effective-scope enforcement, evidence metadata, and explicit `ok`, `empty`, `unavailable`, and `denied` outcomes. The current registry already centralizes these semantics and has Network, vulnerability, incident, remediation, search, and Fabric IQ entries. `[VERIFIED: src/operations/tools.py:39-107,653-796]`

Put Azure API Management in front of that server as the externally consumed MCP endpoint. Microsoft documents two APIM patterns: expose selected managed REST operations as MCP tools, or proxy an existing remote MCP server. The latter is the correct fit if the server speaks MCP natively; APIM can govern authentication, policies, rate limits, products/subscriptions, and monitoring. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/mcp-server-overview]` `[CITED: https://learn.microsoft.com/en-us/azure/api-management/expose-existing-mcp-server]`

Keep local orchestration responsible for scope, deterministic network checks, specialist selection, budgets, ledger, and fallback. Foundry prompt agents receive curated tool results, not credentials, raw datasets, or authority to select arbitrary tools. Fabric IQ is optional relationship/policy enrichment only. Microsoft currently labels Fabric IQ ontology grounding preview and warns that data may cross compliance/geographic boundaries; tenant validation and an explicit kill switch are mandatory before production use. `[CITED: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq]` `[CITED: https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq]`

**Primary recommendation:** Plan 09-07 as an API contract and MCP adapter, then APIM gateway/IaC, then specialist tool binding, then tenant smoke tests; split APIM/Fabric IQ rollout into a follow-on plan if the APIM service or preview tenant prerequisites are not already available.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Resource identity and family availability | Database/Storage (Fabric inventory) | API/Backend | Inventory owns identity; consumers use the scope-enforcing read port. `[VERIFIED: src/intelligence/inventory/read_port.py:10-42]` |
| MCP protocol and tool dispatch | API/Backend | APIM gateway | The server adapts the existing governed registry; APIM is the external gateway, not the domain owner. |
| Inbound authentication and throttling | APIM gateway | API/Backend | APIM validates/limits external calls; API still derives effective authorization and rejects forged scope. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/secure-mcp-servers]` |
| Deterministic network policy checks | API/Backend | Fabric IQ | Known rules must be machine-verifiable before narration. `[VERIFIED: src/operations/tools.py:336-439]` |
| Relationship/policy enrichment | Fabric IQ/OneLake | API/Backend | Fabric IQ can enrich semantics, but API scope/evidence contracts remain authoritative. `[CITED: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq]` |
| Specialist reasoning | Foundry project | API/Backend | Foundry narrates curated results; the local service owns selection, budgets, and fallback. `[VERIFIED: src/operations/foundry_agent.py:375-413]` |
| Audit and human actions | API/Backend | OneLake persistence | The existing investigation ledger remains the system of record. `[VERIFIED: src/api/routers/multi_agent.py:58-105]` |

## Standard Stack

### Core

| Component | Version | Purpose | Recommendation |
|---|---|---|---|
| FastAPI + Pydantic | Existing Python `>=3.11`; FastAPI `>=0.115,<1` | MCP adapter endpoint and strict contracts | Reuse; do not create a second service. `[VERIFIED: pyproject.toml:4-6,20-22]` |
| Existing `TOOL_REGISTRY` | In-repo | Allowlisted handlers and evidence/status contract | Reuse as the only backend dispatch seam. `[VERIFIED: src/operations/tools.py:653-796]` |
| `FoundryPromptAgent` | In-repo; data-plane API `v1` | Specialist narration | Reuse its Entra token scope, retry, timeout, and circuit breaker. `[VERIFIED: src/operations/foundry_agent.py:44-81,217-255]` |
| Azure API Management | Service capability | Public MCP gateway, auth, policy, quotas, telemetry | Add only after confirming an APIM instance and supported tier. APIM supports MCP on Developer, Basic, Basic v2, Standard, Standard v2, Premium, and Premium v2. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/mcp-server-overview]` |

### Supporting

| Component | Purpose | When to use |
|---|---|---|
| Fabric IQ Ontology | Relationship-aware semantic grounding | Opt-in `relationships`, `topology`, and `policy` tools only; it is preview and not an identity authority. `[VERIFIED: src/operations/tools.py:125-153,751-767]` `[CITED: https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq]` |
| APIM OAuth/JWT policy | Validate Entra bearer tokens at the gateway | Use `validate-azure-ad-token`; retain API-side authorization. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/secure-mcp-servers]` |
| APIM products/subscriptions | Consumer onboarding and quotas | Use for controlled clients; do not treat a subscription key as an RBAC grant. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/export-rest-mcp-server]` |

**Installation:** No new Python package is recommended. MCP should be implemented with the existing HTTP stack or a vetted protocol implementation only after a separate legitimacy review. Do not add an unverified “MCP server” package by name alone.

## Package Legitimacy Audit

No external package installation is recommended for the research-backed path. Existing dependencies are reused. If implementation selects an MCP SDK, run the package-legitimacy gate, correct-ecosystem registry verification, and postinstall review before adding it; package existence alone is not legitimacy. `[VERIFIED: pyproject.toml:4-22]`

## Architecture Patterns

### System Architecture Diagram

```text
Foundry specialist / approved MCP client
                 |
                 v
       APIM MCP endpoint (OAuth/JWT + quota + trace)
                 |
                 v
  Operations MCP adapter (tools/list, tools/call, bounded JSON)
                 |
                 v
  API auth -> effective Scope -> existing TOOL_REGISTRY
                 |
        +--------+---------+
        |                  |
        v                  v
Inventory/API read ports  Fabric IQ adapter (optional)
        |                  |
        +--------+---------+
                 v
 deterministic findings + evidence/status + ledger
                 |
                 v
 local orchestrator -> named Foundry specialist -> cited result/fallback
```

### Pattern 1: MCP facade over governed handlers

Expose only a curated subset initially: `network_topology`, `hub_dependents`, `traffic_flow`, `firewall_nsg_gaps`, `business_service_context`, `application_context`, `impact_context`, and the three explicitly governed Fabric IQ operations. The adapter must translate MCP arguments into `call_tool(name, args, context, scope)`, never call providers directly. `[VERIFIED: src/operations/tools.py:773-796]`

The wire response should preserve `ToolResult.to_dict()` fields exactly: `"status"`, `"data"`, `"evidence"`, and `"warning"`. The source definition reads: `return {"status": self.status, "data": self.data, "evidence": [item.to_dict() for item in self.evidence], "warning": self.warning}`. `[VERIFIED: src/operations/tools.py:87-107]` Use MCP `isError` only for protocol/validation failures; an operational `empty`, `unavailable`, or `denied` result must remain inspectable data.

### Pattern 2: Effective scope is server-derived

Authenticate the caller, derive the effective scope from Entra/API grants, and reject any client-supplied scope wider than that scope. The current gateway resolver explicitly says gateway headers establish identity, not authorization and returns only roles asserted by the request. `[VERIFIED: src/api/runtime.py:159-187]` MCP arguments may identify a subject, but must not carry an authoritative subscription/resource scope.

### Pattern 3: deterministic-first Network Agent

Run `network_topology`/`firewall_nsg_gaps` and deterministic policy evaluation first; then pass bounded findings to the Network Foundry agent. Findings must carry canonical resource IDs, policy/check IDs, evidence references, confidence, freshness/uncertainty, and one bounded next check. `[VERIFIED: src/operations/tools.py:336-439]` `[VERIFIED: .planning/phases/09-consumer-pivot/09-CONTEXT.md:33-37]`

### Pattern 4: snapshot plus explicit recheck

For page Copilot, preserve the typed page snapshot as primary evidence. A tool call triggered by a named recheck must be separately recorded with tool, arguments, actor, scope, freshness, result status, and ledger correlation. Do not silently replace the visible page state with a newer provider response.

### Pattern 5: independent specialist releases

The existing specialist IDs are the exact values `"network"`, `"vulnerability"`, `"patch"`, `"incident"`, `"change"`, `"governance"`, `"remediation"`, and `"executive_summary"`. `[VERIFIED: src/operations/foundry_agent.py:47-56]` Keep each agent name/version independently configurable; existing Terraform passes `FOUNDRY_SPECIALISTS_JSON` and creates prompt-agent versions through a data-plane script. `[VERIFIED: infra/terraform/foundry.tf:12-39,198-231]`

### APIM implementation constraint

APIM supports an existing remote MCP backend over Streamable HTTP or SSE, and supports REST APIs exposed as MCP tools. For a native server, use the existing-MCP-server resource path; for a REST facade, explicitly select only safe operations. APIM currently supports tools for REST-imported MCP servers but not MCP resources or prompts; external MCP servers support tools/resources but not prompts. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/export-rest-mcp-server]` `[CITED: https://learn.microsoft.com/en-us/azure/api-management/expose-existing-mcp-server]`

Manage APIM declaratively through its MCP server/API-tool/policy resources using the documented ARM API, Bicep, CLI, or Terraform path. The documented management API example uses `2025-09-01-preview`; pin and verify the API version in the target subscription rather than assuming provider support. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/manage-mcp-servers-rest-api]`

### Anti-Patterns to Avoid

- **Raw dataset MCP tool:** never expose OneLake paths, Fabric SQL, ARG, or ontology traversal directly; use the API read port and governed handlers.
- **Client-declared scope:** APIM subscription keys identify a consumer but do not replace Entra/RBAC scope.
- **MCP tool explosion:** do not publish the whole REST API or every registry entry before tool-level review, schemas, and threat tests.
- **LLM policy decision:** Foundry may explain deterministic checks, never invent a pass/fail result or approve a mutation.
- **Silent Foundry success:** a fallback answer must carry explicit `foundry_unavailable`/not-produced state.
- **Preview-as-production:** Fabric IQ is preview, has no implied SLA, and may create compliance/data-boundary implications. `[CITED: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq]`

## Don't Hand-Roll

| Problem | Don't build | Use instead |
|---|---|---|
| Scope filtering | A second MCP-specific filter | Existing `Scope`, `scope_attributes`, and `call_tool` path. `[VERIFIED: src/operations/tools.py:49-85]` |
| Provider outage semantics | Convert failures to empty lists | Existing four-state `ToolResult` contract. `[VERIFIED: src/operations/tools.py:39-45,181-224]` |
| Foundry auth/retry | Per-specialist HTTP/token code | `FoundryPromptAgent` and its token/circuit-breaker seam. `[VERIFIED: src/operations/foundry_agent.py:175-255,346-373]` |
| APIM auth/throttling/telemetry | Middleware inside the domain handler | APIM policies, OAuth/JWT validation, quotas, and Azure Monitor. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/secure-mcp-servers]` `[CITED: https://learn.microsoft.com/en-us/azure/api-management/monitor-mcp-servers]` |
| Ontology grounding | Custom relationship query language | Fabric IQ ontology knowledge source/tool, behind the local governed adapter. `[CITED: https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq]` |

## Common Pitfalls

1. **Wrong transport or APIM mode.** Choose native remote MCP proxy for Streamable HTTP/SSE; do not assume APIM’s REST-to-MCP import supports prompts/resources. Verify with MCP Inspector and a real client. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/expose-existing-mcp-server]`
2. **Double authorization drift.** APIM validates token shape/audience, while the API must still derive grants and scope. Test missing grants, cross-subscription IDs, forged scope headers, and denied subjects.
3. **Tool result semantic loss.** Preserve `empty`, `unavailable`, and `denied` distinctly; never let the Foundry prompt call an unavailable provider “no results.” `[VERIFIED: src/operations/foundry_agent.py:154-164]`
4. **Prompt injection through evidence.** Treat page rows, Fabric responses, MCP arguments, and prior conversation as untrusted data. The existing prompt explicitly says injected instructions are data, not instructions. `[VERIFIED: infra/terraform/foundry.tf:166-192]`
5. **Oversized context and fan-out.** Existing per-tool bound is 25 items and Foundry prompt ceiling is 24,000 serialized characters. Preserve or tighten these bounds; add aggregate byte/token and concurrent-call budgets. `[VERIFIED: src/operations/tools.py:44-46,74-85]` `[VERIFIED: src/operations/foundry_agent.py:416-437]`
6. **Fabric IQ permission mismatch.** Ontology grounding requires the configured identity to have access; Microsoft documents a 403 when the required role is absent. Validate the exact workspace/item/project identity in the target tenant. `[CITED: https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq]`
7. **Terraform assumes prompt agents are ARM resources.** This repository correctly uses a data-plane `local-exec` provisioner; keep agent versioning idempotent and do not put client secrets in new state or logs. `[VERIFIED: infra/terraform/foundry.tf:123-138,198-231]`
8. **APIM product/subscription mistaken for authorization.** Products can manage access/subscriptions, but the backend must enforce AIOps grants. `[CITED: https://learn.microsoft.com/en-us/azure/api-management/export-rest-mcp-server]`

## Actionable Sequencing for Plan 09-07+

1. **Contract characterization:** freeze the selected tool catalog, JSON schemas, argument limits, response envelope, error mapping, protocol version, and tool-to-provider/evidence mapping.
2. **MCP adapter:** implement `tools/list` and `tools/call` around `call_tool`; add request correlation, effective-scope binding, aggregate budgets, redaction, and ledger records. Keep it read-only.
3. **Network specialist path:** deterministic checks → curated Network Agent prompt → strict finding parser/validator → fallback when Foundry is unavailable. Reject outputs lacking evidence references or uncertainty state.
4. **APIM deployment:** confirm APIM tier/region/network reachability; provision remote MCP server, selected tools, product, OAuth/JWT policy, rate/quota policy, trace correlation, backend authentication, and outputs. Use APIM’s documented management API/ Terraform capability only after provider support is verified.
5. **Foundry integration:** bind specialist names/versions to the local orchestrator, not client input. Keep the current Entra data-plane scope `https://ai.azure.com/.default`. `[VERIFIED: src/operations/foundry_agent.py:59-61]`
6. **Fabric IQ:** validate preview availability, ontology permissions, data boundary, identity, freshness, and disable/fallback behavior. Keep `identity_authority=false` in every enrichment response. `[VERIFIED: src/operations/tools.py:125-153]`
7. **Tenant smoke and human gate:** exercise `tools/list`, allowed/denied calls, stale/partial/unavailable providers, APIM auth/429 behavior, Foundry fallback, Fabric IQ 403/timeout, and exact page snapshot replay.

## Code Examples

### Governed MCP dispatch (pseudocode)

```python
def handle_tools_call(name, arguments, request):
    principal, scope = authenticate_and_derive_scope(request)
    if name not in PUBLIC_TOOL_ALLOWLIST:
        return protocol_error("tool_not_found")
    args = validate_tool_schema(name, arguments)
    result = call_tool(name, args, context=api_context, scope=scope)
    ledger.record_tool_call(principal, name, args, result, scope)
    return {"content": [{"type": "text", "text": json.dumps(result.to_dict())}],
            "isError": False}
```

This skeleton is an implementation shape, not a claim about an existing function. The existing callable is `call_tool(name, args, *, context, scope)` and unknown names return `STATUS_DENIED`; the adapter must preserve that behavior. `[VERIFIED: src/operations/tools.py:773-788]`

### Foundry grounded request

```python
answer = specialist.answer(
    question=question,
    context={"snapshot": snapshot, "facts": governed_facts,
             "contract": "network-finding-v1"},
)
```

The current client posts a Responses request with `agent_reference`, passes context in the user turn, and extracts text only after a non-empty response. `[VERIFIED: src/operations/foundry_agent.py:379-405]`

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Backend | pytest via `uv run python -m pytest` |
| Web | Vitest via `cd web && npm test -- --run` |
| Focused backend | `uv run python -m pytest tests/test_api_copilot*.py tests/test_foundry_agent.py tests/test_fabric_client.py -q` |
| Full backend | `uv run python -m pytest -q` |
| Web lint/build | `cd web && npm run lint`; `cd web && npm run build` |
| External MCP/APIM | MCP Inspector/client plus credentialed tenant smoke tests; not replaceable by unit tests |

### Phase Requirements → Test Map

| Behavior | Test |
|---|---|
| `tools/list` exposes only reviewed schemas | Contract test; assert exact allowlist and required/maximum fields |
| `tools/call` enforces effective scope | API integration tests for allowed, denied, forged scope, and cross-subscription calls |
| Status/evidence contract survives MCP | Unit tests for `ok`, `empty`, `unavailable`, `denied`, bounded payload, and evidence serialization |
| Network finding contract | Deterministic tests for resource/check/evidence IDs, stale downgrade, hypothesis/non-actionable output |
| Foundry fallback and specialist version | Existing transport tests plus response-schema tests and circuit-open fallback |
| Fabric IQ governance | Adapter tests for allowlist, scope, metadata, `identity_authority=false`, timeout/403/unavailable |
| APIM gateway | Tenant smoke: OAuth, invalid audience, quota/429, tool visibility, backend correlation, and no secret leakage |
| Exact visible snapshot replay | Browser/manual test on all supported pages; compare rendered state, request payload, and ledger |

### Wave 0 Gaps

- [ ] Add MCP contract tests and a protocol fixture for `initialize`, `tools/list`, and `tools/call`.
- [ ] Add an APIM IaC validation fixture or deployment test that proves the selected APIM resource/API version is supported.
- [ ] Add contract tests for the strict Network finding schema and invalid Foundry output.
- [ ] Add a credentialed tenant smoke script with secrets supplied only by environment/managed identity.

## Environment Availability

| Dependency | Required by | Available now | Fallback |
|---|---|---|---|
| Python/uv | Backend and tests | Repository uses `uv`; verify at execution | None for backend |
| Azure CLI | Existing Foundry data-plane provisioning | Required by `create-foundry-agent.sh`; tenant availability not verified | Manual Foundry provisioning |
| APIM instance | MCP gateway | No APIM Terraform resources were found in the audited `infra/terraform` files | Add APIM resource/IaC or use a temporary non-production endpoint |
| Fabric IQ ontology/permissions | Grounding | Tenant-dependent; not verifiable locally | Disable IQ and retain deterministic/API evidence |
| Foundry project/agent | Specialist narration | Configurable via `FOUNDRY_PROJECT_ENDPOINT` and specialist variables | Deterministic fallback |
| MCP Inspector/real MCP host | Protocol smoke | Not present in repository audit | Use an approved MCP client or APIM test console |

## Security Domain

### Applicable ASVS Categories

| Category | Applies | Control |
|---|---|---|
| V2 Authentication | Yes | APIM Entra JWT validation plus API authentication; reject missing/invalid audience |
| V3 Session Management | Yes | Short-lived bearer tokens, no token logging, correlation IDs without caller secrets |
| V4 Access Control | Yes | API-derived `Scope`/grants; APIM subscription is not sufficient authorization |
| V5 Input Validation | Yes | Strict Pydantic/MCP JSON schemas, allowlist, bounded strings/lists/bytes, canonical resource IDs |
| V6 Cryptography | Yes | Entra/OAuth and managed identity; never hand-roll token validation or crypto |

### Known Threat Patterns

| Threat | STRIDE | Mitigation |
|---|---|---|
| Forged scope/resource argument | Elevation of privilege | Derive scope server-side; validate every returned entity |
| Prompt injection in evidence | Tampering | Treat all tool/page/Fabric data as untrusted; fixed system prompts and strict output parser |
| Tool abuse/fan-out | Denial of service | APIM quota/rate limit plus local step, byte, timeout, and concurrency budgets |
| Data leakage in errors/traces | Information disclosure | Redact tokens, tenant IDs where appropriate, raw provider payloads, and arguments containing secrets |
| Fabric IQ boundary crossing | Information disclosure | Tenant data-flow review, explicit opt-in, managed identity, provenance/freshness, kill switch |
| Unsafe mutation discovery | Elevation/tampering | Publish read-only tools only; no remediation execution through MCP in this plan |

## Sources

### Primary (HIGH/MEDIUM)

- [Azure API Management MCP overview](https://learn.microsoft.com/en-us/azure/api-management/mcp-server-overview) — supported APIM patterns, tiers, governance.
- [Expose REST API as MCP server](https://learn.microsoft.com/en-us/azure/api-management/export-rest-mcp-server) — operation selection and REST-to-tool limitations.
- [Expose existing MCP server](https://learn.microsoft.com/en-us/azure/api-management/expose-existing-mcp-server) — Streamable HTTP/SSE and external backend constraints.
- [Secure MCP servers](https://learn.microsoft.com/en-us/azure/api-management/secure-mcp-servers) — Entra OAuth/JWT, subscription keys, policies.
- [Manage MCP servers programmatically](https://learn.microsoft.com/en-us/azure/api-management/manage-mcp-servers-rest-api) — ARM/API/IaC management and API version.
- [Monitor MCP servers](https://learn.microsoft.com/en-us/azure/api-management/monitor-mcp-servers) — MCP telemetry and tool-call monitoring.
- [Connect Foundry agents to Fabric IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/fabric-iq) — preview status, authentication, compliance warning.
- [Create an Ontology Agent with Foundry IQ](https://learn.microsoft.com/en-us/fabric/iq/ontology/how-to-create-agent-foundry-iq) — ontology knowledge source and permissions.
- In-repo `src/operations/tools.py`, `src/operations/foundry_agent.py`, `src/api/runtime.py`, `infra/terraform/foundry.tf` — opened and line-cited above.

## Assumptions Log

| # | Claim | Risk if wrong |
|---|---|---|
| A1 | An APIM instance is not already provisioned outside the audited Terraform tree. `[ASSUMED]` | Plan may duplicate or mis-target existing gateway infrastructure; confirm with owner/Azure inventory. |
| A2 | A native MCP adapter is preferable to APIM REST-to-MCP import for preserving existing tool statuses/evidence. `[ASSUMED]` | Could require a REST facade if APIM/client compatibility is better; validate with target clients. |
| A3 | The target tenant permits Fabric IQ preview integration and required ontology permissions. `[ASSUMED]` | Fabric grounding may remain disabled or require a separate tenant rollout. |

## Open Questions (RESOLVED)

1. **Where should the MCP server run?** It will run as a read-only surface in the existing API Container App first, reusing its provider registry, scope enforcement, evidence contracts, and managed identity. APIM will be the only public gateway; direct MCP ingress remains disabled or restricted to the APIM backend path.
2. **Does the target APIM tier/provider support the documented MCP management resources?** No APIM resource currently exists in `aiops-dev-rg`, so Phase 9 will provision a conventional APIM API/policy facade through the supported AzureRM resources rather than depending on preview-native MCP management resources. MCP protocol compatibility is implemented and tested by the backend contract, while APIM provides HTTPS routing, Entra validation, quotas, and observability.
3. **Should Foundry call APIM MCP directly or should local orchestration call the registry?** Local orchestration remains canonical in Phase 9. It invokes the governed in-process registry for the page Copilot and Foundry specialists; APIM exposes the same read-only contracts for separately authorized external/agent consumers after identity propagation is validated.
4. **Which Fabric IQ identity reads ontology data?** The API Container App's existing user-assigned managed identity is the runtime identity. Fabric IQ remains optional and must use the existing governed Fabric connection/configuration, with workspace/item permissions and geography validated by the live smoke test before enablement. No specialist receives direct unrestricted Fabric credentials.

## Metadata

**Confidence breakdown:**
- Existing code seams: HIGH — source files were opened this session and line-cited.
- APIM implementation: MEDIUM — current Microsoft documentation was fetched; exact preview/IaC support is tenant/provider dependent.
- Fabric IQ: MEDIUM — official docs confirm the integration shape but label it preview and require tenant permission validation.
- Security and sequencing: MEDIUM — prescribed from locked project constraints and official gateway controls.

**Research date:** 2026-08-28  
**Valid until:** 2026-09-04 for preview/APIM details; 30 days for repository seams.
