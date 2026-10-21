import type { CopilotInvestigation } from "@/lib/services";
import type { AutonomousAgent, MultiAgentLedger, SearchResult } from "@/lib/types";

/** Builds a bounded fixture catalog with explicit deployment availability. */
export function buildAgentCatalog(): AutonomousAgent[] {
  return [
    { id: "network", name: "Network Agent", role: "Network", tools: ["network_topology"], keywords: ["network"], depends_on: [],
      foundry: { status: "available_inactive", configured: true } },
    { id: "vulnerability", name: "Vulnerability Agent", role: "Vulnerability", tools: ["vulnerability_exposure"], keywords: ["cve"], depends_on: [],
      foundry: { status: "unavailable", configured: false } },
  ];
}

/** Builds a source-qualified investigation ledger with visible review conditions. */
export function buildAgentLedger(): MultiAgentLedger {
  return {
    ledger_id: "mai-layout", objective: "Investigate Payments risk", scope: {},
    created_by: "test-operator", created_at: "2026-09-20T12:00:00Z",
    updated_at: "2026-09-20T12:00:01Z", status: "synthesized",
    selected_agents: buildAgentCatalog(),
    agent_runs: [{
      agent_id: "network", agent_name: "Network Agent", status: "ok",
      started_at: "2026-09-20T12:00:00Z", completed_at: "2026-09-20T12:00:01Z", duration_ms: 100,
      tool_calls: [{ tool: "network_topology", arguments: {}, status: "ok", warning: "", attempts: 1 }],
      findings: [{ finding_id: "network:1", agent_id: "network", summary: "Payments dependencies require operator review.",
        status: "ok", confidence: "medium", evidence_count: 1 }],
      evidence: [], confidence: "medium", hidden_reasoning_exposed: false,
    }],
    reconciliation: {
      conflicts: ["Provider records disagree; review source evidence before acting."],
      stale_evidence: [], missing_providers: [{
        tool: "vulnerability_exposure", arguments: {}, status: "unavailable",
        warning: "The vulnerability provider is unavailable; absence of exposure is not established.", attempts: 1,
      }],
      unsupported_conclusions: [], evidence_count: 1, reconciled_confidence: "medium",
    },
    synthesis: {
      summary: "Validate Payments dependencies with the service owner.",
      recommended_plan: "Review the proposed plan before any governed handoff.",
      required_decision: "Accept the finding or request current evidence.",
      unresolved_questions: ["Current vulnerability coverage remains unknown."], confidence: "medium",
      narration_warning: "Narration is unavailable; deterministic findings remain visible.",
    },
    human_controls: { available_actions: ["assign_owner", "approve_plan", "request_more_evidence", "accept_finding", "reject_finding", "stop_investigation"] },
    decisions: [], approvals: [], outcome: "", stop_reason: "",
    evaluation: { groundedness: 1, scope_isolation: "enforced", tool_correctness: 1,
      convergence: "converged", latency_ms: 100, cost: { tool_calls: 1, agent_runs: 1, llm_calls: 0 } },
  };
}

/** Builds a canonical fallback with citations and a dense supporting tool result. */
export function buildCanonicalReply(): CopilotInvestigation {
  return {
    question: "Review Payments", answer: null, fact_status: "partial",
    tool_calls: [
      { tool: "inventory_resources", arguments: {}, status: "ok", evidence: [],
        warning: "Inventory evidence is stale; validate current state.",
        data: Array.from({ length: 40 }, (_, index) => ({ id: `resource-${index}`, name: `Payments worker ${index}` })) },
      { tool: "vulnerability_exposure", arguments: {}, status: "unavailable", evidence: [], data: null,
        warning: "The vulnerability provider is unavailable; absence of exposure is not established." },
    ],
    warnings: ["Only the visible subset was inspected; coverage is incomplete."],
    contract_version: "1", thread_id: `thr-${"b".repeat(32)}`, thread_revision: 2,
    policy_status: "fallback", fallback_reason: "planner_unavailable",
    coverage: { visible_count: 1, total_count: 2, complete: false },
    citations: [{ citation_id: "tool:0:resource-0", source: "Azure Resource Graph", status: "ok",
      observed_at: "2026-09-20T12:00:00Z", resource_id: "resource-0" }],
    synthesis: { status: "degraded", reason: "narration_unavailable", domain_count: 2, claims: [],
      warning: "Specialist evidence is shown; narration is unavailable." },
  };
}

/** Builds loaded search records distinct from a larger, truncated source count. */
export function buildSearchRecords(count = 23): SearchResult {
  return {
    intent: "resources_missing_ownership", count: 200, truncated: true,
    results: Array.from({ length: count }, (_, index) => {
      const entityType = ["BusinessService", "Incident", "CVE", "Resource"][index % 4];
      return {
        id: index === 0 ? "Payments API" : `${entityType}-${index}`, entity_type: entityType,
        title: `Payments authorized record ${index}`,
        subscription_id: "sub-authorized-production-payments",
        source: "Azure Resource Graph", freshness: "stale", owner: "Not observed",
        properties: { notes: Array.from({ length: 30 }, (__, note) => ({ note, detail: "Supporting source record, not execution authority." })) },
      };
    }),
  };
}
