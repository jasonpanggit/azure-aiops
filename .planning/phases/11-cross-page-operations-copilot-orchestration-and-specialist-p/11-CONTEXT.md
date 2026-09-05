# Phase 11 Context: Cross-Page Operations Copilot Orchestration and Specialist Parity

## Goal

Make Operations Copilot the single governed reasoning orchestrator across the web experience, with consistent page context, complete specialist/tool parity, cited cross-domain synthesis, and measurable behavior.

## Locked Decisions

1. **Hybrid orchestration, not unconstrained autonomy.** The Operations Copilot coordinator may produce a structured intent and delegation plan, but deterministic policy validates specialist IDs, tool grants, scope, budgets, dependencies, and mutation boundaries before execution. Existing keyword routing remains the safe fallback.
2. **One request/result contract.** Standalone chat, contextual drawer, investigation workspace, and multi-agent ledger converge on one orchestration service instead of maintaining separate planners.
3. **Typed page adapters.** Route components do not hand-build arbitrary snapshots. A registry defines page kinds, evidence mapping, selected entities, freshness, coverage, starter questions, and default specialist hints.
4. **Evidence snapshot v2.** Preserve stable Azure and non-Azure entity identities, evidence priority/deduplication, visible/total coverage, freshness, conflict, uncertainty, and citations.
5. **One specialist manifest.** Runtime definitions, prompts, Operations MCP grants, Azure MCP grants, Foundry deployment settings, API catalog, and UI metadata must be generated from or validated against one versioned contract.
6. **Specialist portfolio.** Retain the existing eight specialists; close their parity gaps; add Inventory & Data Health, Identity & Access, FinOps, and Resource Health & Observability specialists. Do not create one agent per page.
7. **Executive synthesis is conditional.** Invoke it for cross-domain or explicitly executive questions, using cited specialist outputs; do not spend its latency/cost on every single-domain turn.
8. **Cross-page continuity is bounded and authorized.** Preserve a principal-scoped investigation thread across navigation without widening scope or carrying stale evidence as current fact.
9. **Safe degradation.** Foundry, Fabric IQ, Azure AI Search, Azure MCP, and Gold Data Agent are optional enrichments. Missing providers yield explicit uncertainty and deterministic evidence/results, not fabricated answers or blank pages.
10. **No autonomous production mutation.** Copilot may prepare governed handoffs, but approval and execution remain existing server-side workflows.

## Implementation Priorities

1. End-to-end tracer: one currently unsupported evidence-heavy page uses the unified contract, adapter registry, coordinator plan, specialist execution, citations, and continuity.
2. Consolidate orchestration paths and add compatibility adapters for existing clients.
3. Introduce snapshot v2 and migrate current drawer pages.
4. Establish specialist manifest/parity validation and add the four missing domain specialists.
5. Expand page adapters, executive synthesis, continuity, telemetry, and evaluation gates.

## Page Coverage Policy

- **Must integrate:** evidence-heavy operational pages and detail/action pages: overview, network, compliance, exposure, CVE, Defender posture, KB, patch priorities, situations list/detail, changes, predeploy, inventory, connections/Fabric, governance, identity, FinOps, remediation, resource health, services list/detail, twin.
- **Dedicated surfaces:** `/copilot`, `/investigate`, and `/agents` must use the unified contract while keeping their distinct presentation.
- **Explicit exclusion allowed:** redirect-only `/vulnerabilities` and pure navigation/search surfaces when no stable evidence snapshot exists. Exclusions require a tested registry disposition.

## Requirements

- COP-01: unified governed orchestration contract.
- COP-02: typed cross-page page-adapter registry and eligible-page integration.
- COP-03: versioned specialist contract parity and missing-domain specialists.
- COP-04: evidence snapshot v2.
- COP-05: cross-page continuity, executive synthesis, telemetry, and evaluations.

## Review Evidence

See `11-REVIEW.md` for the full page-coverage matrix, architecture findings, recommendations, specialist portfolio, current Phase 10 blockers, and scope fences.
