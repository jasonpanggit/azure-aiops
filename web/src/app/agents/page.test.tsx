import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";

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

// Manifest-backed catalog: each agent carries catalog availability separately
// from runtime activation, so the UI never infers execution from a candidate.
const catalogAgents = [
  { id: "network", name: "Network Agent", role: "Network", tools: ["network_topology"], keywords: ["network"], depends_on: [], foundry: { id: "network", name: "network-agent", version: "1", model: "gpt-4o", status: "active", configured: true } },
  { id: "vulnerability", name: "Vulnerability Agent", role: "Vulnerability", tools: ["vulnerability_exposure"], keywords: ["cve"], depends_on: [], foundry: { id: "vulnerability", name: "vulnerability-agent", version: "1", model: "gpt-4o", status: "available_inactive", configured: false, candidate: { name: "vulnerability-agent", provider_version_id: "provider-vulnerability-1", candidate_version: "2026.09.1", validated_at: "2026-09-20T00:00:00+00:00", source: "validated_candidate_artifact", source_revision: "0123456789abcdef", release: "2026.09" } } },
];

const ledger = {
  ledger_id: "mai-123",
  objective: "Investigate Payroll risk",
  scope: {},
  created_by: "operator@example.com",
  created_at: "2026-01-01T10:00:00Z",
  updated_at: "2026-01-01T10:00:00Z",
  status: "synthesized",
  activation: { mode: "deterministic_degraded", source: "legacy_unversioned", foundry_ready: 0, selected_specialists: 1, version_pinning_required: true },
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
    activation: { configured: true, status: "ready", activation_source: "terraform", degraded_reason: "" },
    execution_mode: "deterministic_local",
  }],
  reconciliation: { conflicts: [], stale_evidence: [], missing_providers: [], unsupported_conclusions: [], evidence_count: 1, reconciled_confidence: "high" },
  synthesis: { summary: "1 evidence-backed finding was produced", recommended_plan: "Assign owner and approve governed remediation.", required_decision: "Accept or request more evidence.", unresolved_questions: [], confidence: "high" },
  human_controls: { available_actions: ["assign_owner"] },
  decisions: [],
  approvals: [],
  outcome: "",
  stop_reason: "",
  evaluation: { groundedness: 1, scope_isolation: "enforced", tool_correctness: 1, convergence: "converged", latency_ms: 100, cost: { tool_calls: 1, agent_runs: 1, llm_calls: 0 } },
  citations: [{ citation_id: "tool:network:1", source: "azure-resource-graph", status: "ok", observed_at: "2026-01-01T10:00:00Z", resource_id: "" }],
  mutation_authorized: false,
};

function ScopeSwitcher() {
  const { setScope } = useScope();
  return <button onClick={() => setScope({ subscription: ["sub-b"] })}>Switch scope</button>;
}

function renderPage() {
  return render(
    <ScopeProvider>
      <MultiAgentInvestigationPage />
      <ScopeSwitcher />
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

  it("distinguishes catalog failures from confirmed Foundry unavailability", async () => {
    catalog.mockRejectedValueOnce(new Error("Catalog request denied"));
    renderPage();
    expect(await screen.findByText("Catalog request denied")).toBeInTheDocument();
    expect(screen.getByText("Foundry status unknown")).toBeInTheDocument();
    expect(screen.queryByText("Foundry unavailable · deterministic fallback")).not.toBeInTheDocument();
  });

  it("rejects an investigation response belonging to a previous scope", async () => {
    let resolve!: (value: ReturnType<typeof envelope<typeof ledger>>) => void;
    investigate.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run deterministic investigation" }));
    fireEvent.click(screen.getByRole("button", { name: "Switch scope" }));
    await act(async () => { resolve(envelope(ledger)); });
    expect(screen.queryByRole("heading", { name: "Specialist plan activity" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run deterministic investigation" })).toBeEnabled();
  });

  it("surfaces failed operator actions and retains the investigation for retry", async () => {
    action.mockRejectedValueOnce(new Error("Owner assignment denied"));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run deterministic investigation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Assign owner" }));
    expect(await screen.findByText("Owner assignment denied")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign owner" })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Specialist plan activity" })).toBeInTheDocument();
  });

  it("requires an explicit finding and reason and submits that exact identity", async () => {
    investigate.mockResolvedValueOnce(envelope({
      ...ledger,
      agent_runs: [{ ...ledger.agent_runs[0], findings: [
        ...ledger.agent_runs[0].findings,
        { ...ledger.agent_runs[0].findings[0], finding_id: "network:2", summary: "Second finding" },
      ] }],
    }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run deterministic investigation" }));
    expect(await screen.findByRole("button", { name: "Reject finding" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Finding to review"), { target: { value: "network:2" } });
    expect(screen.getByRole("button", { name: "Reject finding" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Finding decision reason"), { target: { value: "Contradicted by current route evidence" } });
    fireEvent.click(screen.getByRole("button", { name: "Reject finding" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith("mai-123", "reject_finding", {
      finding_id: "network:2", reason: "Contradicted by current route evidence",
    }, {}));
    expect(screen.getByRole("button", { name: "Reject finding" })).toBeDisabled();
  });

  it("runs agents, shows evidence-backed synthesis, and records human decisions", async () => {
    renderPage();

    expect(await screen.findByText("Network Agent")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Investigation objective"), { target: { value: "Investigate Payroll risk" } });
    fireEvent.click(screen.getByRole("button", { name: /Run (deterministic )?investigation/ }));

    expect(await screen.findByRole("heading", { name: "Specialist plan activity" })).toBeInTheDocument();
    expect(screen.getAllByText("network_topology returned 2 scoped fields").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Assign owner and approve governed remediation.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Groundedness").length).toBeGreaterThan(0);
    expect(screen.getByText("Deterministic specialist plans")).toBeInTheDocument();
    expect(screen.getByText("Deterministic local fallback")).toBeInTheDocument();
    expect(screen.queryByText("Foundry agent")).toBeNull();
    expect(screen.getAllByText(/Foundry available - inactive/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("Specialists coordinated")).toBeNull();

    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "Finance Ops" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign owner" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith("mai-123", "assign_owner", { owner: "Finance Ops" }, {}));
  });

  it("renders active and available-inactive as distinct catalog states", async () => {
    renderPage();

    const readyAgent = await screen.findByText("Network Agent");
    const unavailableAgent = await screen.findByText("Vulnerability Agent");

    const activeStatus = within(readyAgent.closest(".entity-pill") as HTMLElement).getByText(/Foundry active/i);
    const inactiveStatus = within(unavailableAgent.closest(".entity-pill") as HTMLElement).getByText(/Foundry available - inactive/i);
    expect(activeStatus).toBeInTheDocument();
    expect(inactiveStatus).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run deterministic investigation" })).toBeInTheDocument();
    expect(screen.queryByText("Foundry agent")).toBeNull();
  });

  it("labels an all-unavailable catalog as deterministic fallback, never ready agents", async () => {
    catalog.mockResolvedValue(envelope({
      agents: catalogAgents.map((agent) => ({
        ...agent,
        foundry: {
          ...agent.foundry,
          configured: false,
          status: "unavailable",
          activation_source: "legacy_unversioned",
          degraded_reason: "Pinned Foundry activation is unavailable.",
        },
      })),
    }));
    renderPage();

    expect(await screen.findByText(/Foundry unavailable · deterministic fallback/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run deterministic investigation" })).toBeInTheDocument();
    expect(screen.queryByText("Foundry active")).toBeNull();
  });

  it("keeps ledger decisions principal-scoped and confers no execution authority", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /Run (deterministic )?investigation/ }));
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
