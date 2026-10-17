import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";
import { SCOPE_DIMENSIONS } from "@/lib/scope";

const { action, catalog, investigate, readLedger, readJob, searchParams } = vi.hoisted(() => ({
  action: vi.fn(),
  catalog: vi.fn(),
  investigate: vi.fn(),
  readLedger: vi.fn(),
  readJob: vi.fn(),
  searchParams: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => searchParams.current }));
vi.mock("@/lib/services", () => ({
  multiAgentApi: { action, catalog, investigate, ledger: readLedger, job: readJob },
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
    vi.clearAllMocks();
    searchParams.current = new URLSearchParams();
    readLedger.mockResolvedValue(envelope(ledger));
    catalog.mockResolvedValue(envelope({ agents: catalogAgents }));
    investigate.mockResolvedValue(envelope(ledger));
    action.mockImplementation((_ledgerId, actionName, payload) => Promise.resolve(envelope({
      ...ledger,
      status: "human_review_in_progress",
      decisions: [{ at: "2026-01-01T10:05:00Z", action: actionName, payload }],
    })));
  });

  it("opens an exact retained ledger without starting tools and reloads only on request", async () => {
    searchParams.current = new URLSearchParams({ ledger_id: "mai-123", region: "west" });
    renderPage();
    expect(await screen.findByRole("heading", { name: "Specialist plan activity" })).toBeVisible();
    expect(readLedger).toHaveBeenCalledWith("mai-123", { region: ["west"] });
    expect(investigate).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Run deterministic investigation" })).toBeDisabled();
    expect(screen.getByLabelText("Investigation objective")).toHaveAttribute("readonly");
    fireEvent.click(screen.getByRole("button", { name: "Reload retained investigation" }));
    await waitFor(() => expect(readLedger).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("link", { name: "Start a different investigation" })).toHaveAttribute("href", "/agents?region=west");
    expect(action).not.toHaveBeenCalled();
  });

  it("hides the prior completed ledger immediately when another exact job or a fresh workspace is selected", async () => {
    const first = `job-${"a".repeat(32)}`, second = `job-${"b".repeat(32)}`;
    const job = {
      revision: 4, job_id: first, scope: {}, objective: ledger.objective,
      timeout_seconds: 30, created_at: 1800000000, updated_at: 1800000001,
      status: "completed", stage: "ledger_retained", stop_requested: false,
      ledger_id: ledger.ledger_id, durability: "durable",
      liveness: "not_established", cancellation: "scheduling_only",
    };
    readJob.mockResolvedValueOnce(envelope(job));
    searchParams.current = new URLSearchParams({ job_id: first });
    const rendered = renderPage();
    expect(await screen.findByRole("heading", { name: "Specialist plan activity" })).toBeVisible();
    readJob.mockReturnValueOnce(new Promise(() => {}));
    searchParams.current = new URLSearchParams({ job_id: second });
    rendered.rerender(<ScopeProvider><MultiAgentInvestigationPage /><ScopeSwitcher /></ScopeProvider>);
    expect(screen.queryByRole("heading", { name: "Specialist plan activity" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run deterministic investigation" })).toBeDisabled();
    expect(investigate).not.toHaveBeenCalled();
    searchParams.current = new URLSearchParams();
    rendered.rerender(<ScopeProvider><MultiAgentInvestigationPage /><ScopeSwitcher /></ScopeProvider>);
    expect(screen.queryByRole("heading", { name: "Specialist plan activity" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Start background investigation" })).toBeEnabled();
  });

  it.each(SCOPE_DIMENSIONS)("rejects a wider %s bookmark before any acquisition", dimension => {
    searchParams.current = new URLSearchParams({ ledger_id: "mai-123", [dimension]: "outside" });
    render(<ScopeProvider initialScope={{ [dimension]: ["authorized"] }}><MultiAgentInvestigationPage /></ScopeProvider>);
    expect(screen.getByText("Investigation bookmark unavailable")).toBeVisible();
    expect(readLedger).not.toHaveBeenCalled();
    expect(catalog).not.toHaveBeenCalled();
  });

  it.each(["ledger_id=", "ledger_id=../private", "ledger_id=first&ledger_id=second", `ledger_id=${"a".repeat(129)}`,
    "job_id=", "job_id=../private", `job_id=job-${"A".repeat(32)}`,
    `job_id=job-${"a".repeat(32)}&job_id=job-${"b".repeat(32)}`,
    `ledger_id=mai-123&job_id=job-${"a".repeat(32)}`,
  ])("refuses malformed exact ledger selection: %s", query => {
    searchParams.current = new URLSearchParams(query);
    renderPage();
    expect(screen.getByText("Investigation bookmark unavailable")).toBeVisible();
    expect(readLedger).not.toHaveBeenCalled();
    expect(catalog).not.toHaveBeenCalled();
  });

  it("does not substitute a foreign ledger response or silently restart a missing investigation", async () => {
    searchParams.current = new URLSearchParams({ ledger_id: "missing-ledger" });
    renderPage();
    expect(await screen.findByText(/response did not match the exact retained/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Specialist plan activity" })).not.toBeInTheDocument();
    expect(investigate).not.toHaveBeenCalled();
  });

  it("keeps not-found or unauthorized retained ledgers unavailable without starting another run", async () => {
    readLedger.mockRejectedValueOnce(new Error("Investigation ledger not found"));
    searchParams.current = new URLSearchParams({ ledger_id: "missing-ledger" });
    renderPage();
    expect(await screen.findByText("Investigation ledger not found")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Specialist plan activity" })).not.toBeInTheDocument();
    expect(investigate).not.toHaveBeenCalled();
    expect(action).not.toHaveBeenCalled();
  });

  it("rejects a review result for another ledger without losing the retained identity", async () => {
    searchParams.current = new URLSearchParams({ ledger_id: "mai-123" });
    action.mockResolvedValueOnce(envelope({ ...ledger, ledger_id: "foreign-ledger" }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Assign owner" }));
    expect(await screen.findByText(/action response did not match this retained/)).toBeVisible();
    expect(screen.getByRole("region", { name: "Retained investigation continuation" })).toHaveTextContent("mai-123");
    expect(screen.getByRole("button", { name: "Assign owner" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained investigation" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Assign owner" })).toBeEnabled());
    expect(action).toHaveBeenCalledOnce();
    expect(investigate).not.toHaveBeenCalled();
  });

  it("preserves every bookmarked scope dimension in a new retained link", async () => {
    searchParams.current = new URLSearchParams(SCOPE_DIMENSIONS.map(key => [key, `${key}-value`]));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Run deterministic investigation" }));
    const link = await screen.findByRole("link", { name: "Open retained investigation" });
    const query = new URL(link.getAttribute("href")!, "http://localhost").searchParams;
    expect(query.get("ledger_id")).toBe("mai-123");
    for (const dimension of SCOPE_DIMENSIONS) expect(query.get(dimension)).toBe(`${dimension}-value`);
    expect(readLedger).not.toHaveBeenCalled();
  });

  it("discards a retained read after its bookmarked scope is replaced", async () => {
    let resolve!: (value: ReturnType<typeof envelope<typeof ledger>>) => void;
    readLedger.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    searchParams.current = new URLSearchParams({ ledger_id: "mai-123" });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Switch scope" }));
    await waitFor(() => expect(readLedger).toHaveBeenLastCalledWith("mai-123", { subscription: ["sub-b"] }));
    await screen.findByRole("heading", { name: "Specialist plan activity" });
    await act(async () => resolve(envelope({ ...ledger, objective: "Old scope response" })));
    expect(screen.getByLabelText("Investigation objective")).not.toHaveValue("Old scope response");
    expect(investigate).not.toHaveBeenCalled();
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
