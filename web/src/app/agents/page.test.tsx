import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

// Manifest-backed catalog: each agent carries its own deployment status, so the
// UI renders configured/unavailable from the API rather than a local card list.
const catalogAgents = [
  { id: "network", name: "Network Agent", role: "Network", tools: ["network_topology"], keywords: ["network"], depends_on: [], foundry: { id: "network", name: "network-agent", version: "1", model: "gpt-4o", status: "ready", configured: true } },
  { id: "vulnerability", name: "Vulnerability Agent", role: "Vulnerability", tools: ["vulnerability_exposure"], keywords: ["cve"], depends_on: [], foundry: { id: "vulnerability", name: "", version: "", model: "gpt-4o", status: "unavailable", configured: false } },
];

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
    catalog.mockResolvedValue(envelope({ agents: catalogAgents }));
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

  it("renders the manifest-backed catalog with explicit configured/unavailable status", async () => {
    renderPage();

    const readyAgent = await screen.findByText("Network Agent");
    const unavailableAgent = await screen.findByText("Vulnerability Agent");

    // The configured agent shows a Ready deployment status; the unconfigured one
    // is explicitly Unavailable — both derived from the API catalog, not the UI.
    const readyStatus = within(readyAgent.closest(".entity-pill") as HTMLElement).getByText(/ready/i);
    const unavailableStatus = within(unavailableAgent.closest(".entity-pill") as HTMLElement).getByText(/unavailable/i);
    expect(readyStatus).toBeInTheDocument();
    expect(unavailableStatus).toBeInTheDocument();
  });

  it("keeps ledger decisions principal-scoped and confers no execution authority", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    expect(await screen.findByRole("heading", { name: "Human-in-the-loop controls" })).toBeInTheDocument();

    // Approving the plan is a governed handoff only — the ledger decision never
    // authorizes a production mutation.
    fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith(
      "mai-123",
      "approve_plan",
      expect.objectContaining({ guardrail: "governed handoff only" }),
      {},
    ));

    // No control on this dedicated surface executes or applies remediation.
    expect(screen.queryByRole("button", { name: /execute|apply remediation|run remediation/i })).toBeNull();
  });
});
