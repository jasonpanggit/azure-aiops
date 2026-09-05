# Phase 11 Review: Operations Copilot and Specialist Agents

**Reviewed:** 2026-09-03
**Scope:** All 28 Next.js route pages, shared Copilot UI/services, API orchestration paths, specialist runtime contracts, Foundry/Terraform grants, governed MCP tools, and evaluation behavior.

## Current Phase and Blockers

Phase 10 is complete. Its remaining operational blockers are outside this phase but affect Copilot grounding:

- Fabric Gold-grounding Data Agent readiness remains unknown until `FABRIC_GOLD_GROUNDING_AGENT_ID` and `FABRIC_DELEGATED_TOKEN` are configured.
- The live 23-case baseline has 0.87 routing accuracy and 0.283 mean groundedness; tool correctness is 1.0, so narration/grounding rather than tool execution is the main quality gap.
- Long inventory refresh operations can still exceed HTTP stream timeouts; Phase 10 made status observable but did not remove the timeout behavior.

Phase 11 must degrade safely when these optional providers are unavailable and must not make them prerequisites for core routing.

## Web Coverage Review

| Integration state | Routes | Assessment |
|---|---|---|
| Contextual drawer using snapshot API | `/`, `/network`, `/compliance`, `/exposure`, `/exposure/cves/[id]`, `/situations` | Strongest pattern, but only 6/28 routes. Evidence construction, freshness, selected entities, and starter-tool semantics vary by page. |
| Dedicated Copilot surfaces | `/copilot`, `/investigate`, `/agents` | Three separate experiences use different contracts: generic investigation, inline workspace investigation, and autonomous multi-agent ledger. |
| Link only | `/services/[name]` | Loses the visible page snapshot and opens generic Copilot with only a query parameter. |
| Redirect | `/vulnerabilities` | Correctly delegates to `/exposure`; no separate integration needed. |
| No Copilot integration | `/changes`, `/changes/predeploy`, `/connections`, `/connections/fabric`, `/exposure/defender-posture`, `/exposure/kbs/[id]`, `/exposure/patch-priorities`, `/finops`, `/governance`, `/identity`, `/inventory`, `/remediation`, `/resource-health`, `/search`, `/services`, `/situations/[id]`, `/twin` | 17 routes include high-value evidence or decisions that cannot be analyzed in place. Utility/search routes may be explicitly excluded, but evidence-heavy domain and detail pages need adapters. |

## Architecture Findings

1. **Three orchestration paths drift.** `/copilot/investigate` uses the heuristic `_plan()` and optional single specialist narration; `/copilot/investigate-context` uses page snapshots, a separate specialist selector, bounded local tool execution, and coordinator narration; `/agents/investigations` uses a third autonomous ledger flow. The same question can therefore choose different tools, specialists, freshness rules, and audit persistence.
2. **"MAF" selection is still deterministic keyword matching.** `select_specialists_for_turn()` is a useful safe fallback, but it does not reason over structured intent or candidate plans. The generic Operations Copilot narrates after routing rather than producing a validated delegation plan.
3. **Contracts can drift across layers.** `AGENTS` in Python, `foundry_specialist_tools` and Azure MCP grants in Terraform, prompt text, MCP allowlists, API catalog output, and UI agent cards are separate representations. The patch agent is the clearest gap: local runtime tools include CVE/remediation context while the Foundry operations-MCP grant is generic-only.
4. **The existing eight agents do not cover major pages.** Network, vulnerability, patch, incident, change, governance, remediation, and executive summary exist. Inventory/data health, identity/access, FinOps/cost, and resource health/observability lack bounded specialists despite dedicated pages and provider data.
5. **Snapshot v1 is bounded but semantically lossy.** It truncates to 200 rows, does not deduplicate or prioritize, drops non-ARM selected entities, does not represent page-result total versus visible subset, and receives freshness inconsistently. A model can mistake a visible page for the complete dataset.
6. **Starter tools are bypasses, not orchestration hints.** Contextual drawer requests always use `/investigate-context`; the `tool` and `toolArguments` on starter questions are ignored whenever a snapshot exists. Several labels therefore imply deterministic tool binding that does not happen.
7. **Cross-page continuity is absent.** Drawer state is local to each mounted page and the standalone/full investigation surfaces have separate session models. A CVE-to-service-to-remediation investigation loses its prior authorized context at navigation boundaries.
8. **Executive synthesis is inconsistent.** The autonomous `/agents` flow appends an executive synthesis record, but contextual turns select a narrator rather than invoking a distinct executive aggregation contract over cited specialist findings.
9. **Freshness and confidence are not uniformly propagated.** The snapshot schema supports freshness, but page adapters rarely populate it; non-network page findings are mostly visible-row observations, while network pages get extra deterministic checks.
10. **Evaluation is not page-complete.** Existing routing and grounding tests cover important paths, but there is no route-to-adapter coverage gate, specialist contract drift gate, full page/question matrix, or cross-page continuity evaluation.

## Five Recommendations

### 1. Unify Operations Copilot behind one governed orchestration contract

Create a single `InvestigationRequest`/`InvestigationResult` used by standalone chat, contextual drawers, the investigation workspace, and autonomous ledger runs. Let the coordinator produce a structured intent and candidate specialist/tool plan, then validate it against scope, tool grants, budgets, dependency rules, and mutation policy. Keep current deterministic routing as the explicit fallback.

### 2. Add a typed cross-page Copilot adapter registry

Replace ad hoc page snapshot construction with a registry keyed by route/page kind. Each adapter declares eligible evidence, selected entities, filters, freshness, result coverage, starter questions, and default specialist hints. Add contextual drawers to evidence-heavy pages and record explicit exclusions for redirects and pure navigation/utility routes.

### 3. Establish one versioned specialist contract and close domain gaps

Define each specialist once: purpose, intent examples, dependencies, local governed tools, Azure MCP tools, knowledge policy, page mappings, response schema, and deployment version. Generate or validate Python, Terraform, API, and UI representations from it. Fix patch/change/governance parity and add bounded specialists for inventory/data health, identity, FinOps, and resource health.

### 4. Introduce evidence snapshot v2

Add stable entity references for Azure resources and non-ARM entities, evidence deduplication/prioritization, visible/total coverage metadata, freshness and quality propagation, conflict representation, and deterministic insufficiency rules. Ensure every material narrated claim can cite a retained evidence reference.

### 5. Add cross-page continuity, executive synthesis, and evaluation gates

Persist a bounded principal-scoped investigation thread across navigation; pass cited specialist outputs through an executive synthesis stage only when cross-domain synthesis is needed. Add route coverage, routing, tool-grant parity, groundedness, stale/partial/unavailable behavior, continuity, latency, and cost evaluations with release thresholds.

## Recommended Specialist Portfolio

| Specialist | Disposition | Primary page/domain coverage |
|---|---|---|
| Network | Retain and align | Network, twin network relationships |
| Vulnerability | Retain and align | Exposure, CVE, Defender posture |
| Patch | Retain; fix tool parity | KB detail, patch priorities, patch inventory |
| Incident | Retain and align | Situations list/detail, investigation workspace |
| Change | Retain; add correlation contract | Changes, predeploy assessment, incident correlation |
| Governance | Retain; add policy/identity collaboration | Compliance, governance, ownership |
| Remediation | Retain; bind to governed handoff | Remediation review/approval/execution context |
| Executive Summary | Retain as aggregation stage | Overview, cross-domain and leadership summaries |
| Inventory & Data Health | Add | Inventory, connections, Fabric medallion |
| Identity & Access | Add | Identity, RBAC, stale privilege, service principals |
| FinOps | Add | Cost, waste, Advisor economics, business tradeoffs |
| Resource Health & Observability | Add | Resource health, metrics, availability, telemetry |

## Scope Fences

- No autonomous production mutation; approval and execution remain governed server-side workflows.
- No raw chain-of-thought exposure.
- No specialist may bypass caller scope or query arbitrary tools.
- No claim of full-dataset coverage from a paginated visible subset.
- Optional Foundry, Fabric IQ, Azure AI Search, and Azure MCP failures must be explicit and must not remove deterministic evidence access.
- Do not create one specialist per route; specialists represent stable operational domains.
