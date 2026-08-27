import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { action, catalog, investigate } = vi.hoisted(() => ({
  action: vi.fn(),
  catalog: vi.fn(),
  investigate: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  multiAgentApi: { action, catalog, investigate },
}));

import MultiAgentInvestigationPage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{ source_engine: "operations.MultiAgentInvestigationOrchestrator", source_table: "investigation_ledger", timestamp: "2026-01-01T10:00:00Z", confidence: "medium", freshness: "fresh" }],
  scope: {},
  knowledge_version: "graph-1",
});

const ledger = {
  ledger_id: "mai-123",
  objective: "Investigate Payroll risk",
  scope: {},
  created_by: "operator@example.com",
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
  status: "synthesized",
  selected_agents: [{ id: "network", name: "Network Agent", role: "Network", tools: ["network_topology"], keywords: ["network"], depends_on: [] }],
  agent_runs: [{
    agent_id: "network",
    agent_name: "Network Agent",
    status: "ok",
    started_at: "2026-01-01T10:00:00Z",
    completed_at: "2026-01-01T10:00:01Z",
    duration_ms: 100,
    tool_calls: [{ tool: "network_topology", arguments: {}, status: "ok", warning: "", attempts: 1 }],
    findings: [{ finding_id: "network:1", agent_id: "network", summary: "network_topology returned 2 scoped fields", status: "ok", confidence: "high", evidence_count: 1 }],
    evidence: [{ source_engine: "network.NetworkIntelligenceService", source_table: "ontology_entities", timestamp: "2026-01-01T10:00:00Z", confidence: "high", freshness: "fresh" }],
    confidence: "high",
    hidden_reasoning_exposed: false,
  }],
  reconciliation: { conflicts: [], stale_evidence: [], missing_providers: [], unsupported_conclusions: [], evidence_count: 1, reconciled_confidence: "high" },
  synthesis: { summary: "1 evidence-backed finding was produced", recommended_plan: "Assign owner and approve governed remediation.", required_decision: "Accept or request more evidence.", unresolved_questions: [], confidence: "high" },
  human_controls: { available_actions: ["assign_owner"] },
  decisions: [],
  approvals: [],
  outcome: "",
  stop_reason: "",
  evaluation: { groundedness: 1, scope_isolation: "enforced", tool_correctness: 1, convergence: "converged", latency_ms: 100, cost: { tool_calls: 1, agent_runs: 1, llm_calls: 0 } },
};

function renderPage() {
  return render(
    <ScopeProvider>
      <MultiAgentInvestigationPage />
    </ScopeProvider>
  );
}

describe("Multi-Agent Autonomous Investigation workspace", () => {
  beforeEach(() => {
    catalog.mockResolvedValue(envelope({ agents: ledger.selected_agents }));
    investigate.mockResolvedValue(envelope(ledger));
    action.mockImplementation((_ledgerId, actionName, payload) => Promise.resolve(envelope({
      ...ledger,
      status: "human_review_in_progress",
      decisions: [{ at: "2026-01-01T10:05:00Z", action: actionName, payload }],
    })));
  });

  it("runs agents, shows evidence-backed synthesis, and records human decisions", async () => {
    renderPage();

    expect(await screen.findByText("Network Agent")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Investigation objective"), { target: { value: "Investigate Payroll risk" } });
    fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));

    expect(await screen.findByRole("heading", { name: "Agent activity" })).toBeInTheDocument();
    expect(screen.getAllByText("network_topology returned 2 scoped fields").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Assign owner and approve governed remediation.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Groundedness").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Finance Ops" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign owner" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith("mai-123", "assign_owner", { owner: "Finance Ops" }, {}));
  });
});
