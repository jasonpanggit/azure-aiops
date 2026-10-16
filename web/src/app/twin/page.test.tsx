import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { compare, graph, scenario, traverse, twinExport } = vi.hoisted(() => ({
  compare: vi.fn(),
  graph: vi.fn(),
  scenario: vi.fn(),
  traverse: vi.fn(),
  twinExport: vi.fn(),
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return {
    twinApi: { compare, graph, scenario, traverse, export: twinExport },
    buildCopilotSnapshot: actual.buildCopilotSnapshot,
    copilotEvidenceRows: () => [],
  };
});

import OperationalTwinPage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{ source_engine: "twin", source_table: "live", timestamp: "2026-01-01T10:00:00Z", confidence: "medium", freshness: "fresh" }],
  scope: {},
  knowledge_version: "graph-1",
  live_observed_at: "2026-01-01T10:00:00Z",
  source_status: { live_operational_sources: "request_time" },
});

const snapshot = {
  twin_id: "operational-twin",
  version: "v1",
  previous_version: null,
  observed_at: "2026-01-01T10:00:00Z",
  scope: {},
  entities: [
    { id: "resource:vm-payroll-1", kind: "resource", name: "payroll-vm", version: "r1", state: "current", confidence: "high", provenance: [], properties: { business_service: "Payroll" } },
    { id: "business_service:Payroll", kind: "business_service", name: "Payroll", version: "b1", state: "current", confidence: "high", provenance: [], properties: {} },
    { id: "application:Payroll API", kind: "application", name: "Payroll API", version: "a1", state: "current", confidence: "high", provenance: [], properties: {} },
    { id: "vulnerability:CVE-2026-0001", kind: "vulnerability", name: "CVE-2026-0001", version: "c1", state: "current", confidence: "medium", provenance: [], properties: {} },
  ],
  relationships: [
    { id: "rel-1", source: "resource:vm-payroll-1", target: "business_service:Payroll", type: "supports", confidence: "high", provenance: [] },
  ],
  timeline: [{ timestamp: "2026-01-01T10:00:00Z", type: "vulnerability_observed", entity: "vulnerability:CVE-2026-0001", summary: "CVE-2026-0001" }],
  provenance: [],
  confidence: "medium",
  temporal: {
    current_state_version: "v1",
    previous_state_version: null,
    change_history: [],
    risk_trend: [{ risk_score: 32 }],
    dependency_evolution: [{ relationship_type: "supports", current_count: 1, previous_count: null }],
  },
};

function renderPage() {
  return render(
    <ScopeProvider>
      <OperationalTwinPage />
    </ScopeProvider>
  );
}

describe("Operational Digital Twin workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    graph.mockResolvedValue(envelope(snapshot));
    compare.mockResolvedValue(envelope({
      current_version: "v1",
      previous_version: null,
      comparison_available: false,
      added: [],
      removed: [],
      changed: [],
      summary: "No retained baseline selected. Current observations are not historical differences.",
    }));
    scenario.mockResolvedValue(envelope({
      scenario: "firewall_failure",
      target: "vm-payroll-1",
      version: "v1",
      likely_impact: "Traffic inspection and hub dependencies degrade.",
      risk_delta: null,
      analysis_kind: "bounded_topology_review",
      authority: "none",
      impacted_total: 30,
      truncated: true,
      traversal: { direction: "undirected", max_hops: 3, max_entities: 500 },
      impacted_entities: snapshot.entities,
      assumptions: ["Operator validation required"],
    }));
    traverse.mockResolvedValue(envelope({
      resource_id: "vm-payroll-1",
      path: snapshot.entities.slice(0, 3),
      relationships: snapshot.relationships,
      business_consequence: ["Payroll", "Payroll API"],
    }));
    twinExport.mockResolvedValue(envelope({ format: "operational-twin-export", exported_at: "2026-01-01T10:00:00Z", snapshot }));
  });

  it("shows current twin, temporal comparison, scenario, traversal, and export context", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Twin model" })).toBeInTheDocument();
    expect(screen.getAllByText("Payroll").length).toBeGreaterThan(0);
    expect(screen.getByText(/No retained baseline selected/)).toBeInTheDocument();
    expect(screen.getByText("Prior count unavailable")).toBeInTheDocument();
    expect(scenario).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Resource for impact analysis"), { target: { value: "resource:vm-payroll-1" } });
    expect(await screen.findByText("Traffic inspection and hub dependencies degrade.")).toBeInTheDocument();
    expect(screen.getByText(/Consequence: Payroll -> Payroll API/)).toBeInTheDocument();
    expect(screen.getByText(/Partial projection: traversal or display bounds reached/)).toHaveTextContent("Showing 4 of 30");
    expect(screen.getByText("Not established by mapped links")).toBeInTheDocument();
    expect(screen.getByText("Operator validation required")).toBeInTheDocument();
    expect(screen.getByText("operational-twin-export")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "cve_exploitation" } });
    await waitFor(() => expect(scenario).toHaveBeenLastCalledWith("cve_exploitation", "vm-payroll-1", {}));
  });

  it("offers a read-only Copilot entry point that opens the shared drawer in place", async () => {
    renderPage();
    const trigger = await screen.findByRole("button", { name: "Ask Copilot about the twin" });
    fireEvent.click(trigger);
    expect(await screen.findByRole("dialog", { name: "Operations Copilot" })).toBeInTheDocument();
  });

  it("passes Twin provider degradation into the contextual snapshot", async () => {
    graph.mockResolvedValueOnce({
      ...envelope(snapshot),
      source_status: {
        semantic_graph: "unavailable",
        live_operational_sources: "partial",
        snapshot_materialization: "disabled",
      },
      warnings: ["semantic unavailable: Unavailable"],
    });

    renderPage();

    expect(await screen.findByRole("heading", { name: "Twin model" })).toBeInTheDocument();
    expect(screen.getByLabelText("Data warnings")).toHaveTextContent(
      "semantic unavailable",
    );
  });

  it("reports failed refreshes without retaining the prior snapshot or export", async () => {
    renderPage();
    expect(await screen.findByText("operational-twin-export")).toBeInTheDocument();
    graph.mockRejectedValueOnce(new Error("Twin refresh unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh current state" }));
    expect(await screen.findByText("Twin refresh unavailable")).toBeInTheDocument();
    expect(screen.queryByText("operational-twin-export")).not.toBeInTheDocument();
    expect(screen.queryByText("payroll-vm")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy export" })).toBeDisabled();
    expect(screen.getByText(/Risk evidence unavailable/)).toBeInTheDocument();
  });

  it("does not turn absent risk or failed supplemental reads into zero-risk evidence", async () => {
    graph.mockResolvedValueOnce(envelope({
      ...snapshot, temporal: { ...snapshot.temporal, risk_trend: [] },
    }));
    scenario.mockRejectedValueOnce(new Error("scenario unavailable"));
    renderPage();
    await screen.findByRole("option", { name: /payroll-vm/ });
    fireEvent.change(screen.getByLabelText("Resource for impact analysis"), { target: { value: "resource:vm-payroll-1" } });
    expect(await screen.findByText(/Scenario analysis is unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Risk evidence unavailable/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Scenario-weighted risk.*0/)).not.toBeInTheDocument();
  });

  it("targets only the explicitly selected resource and clears selection-bound results", async () => {
    graph.mockResolvedValueOnce(envelope({ ...snapshot, entities: [
      ...snapshot.entities,
      { ...snapshot.entities[0], id: "resource:vm-second", name: "second-vm" },
    ] }));
    renderPage();
    await screen.findByRole("option", { name: /second-vm/ });
    expect(scenario).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Resource for impact analysis"), { target: { value: "resource:vm-second" } });
    await waitFor(() => expect(scenario).toHaveBeenCalledWith("firewall_failure", "vm-second", {}));
    expect(traverse).toHaveBeenCalledWith("vm-second", {});
    await screen.findByText("Traffic inspection and hub dependencies degrade.");
    fireEvent.change(screen.getByLabelText("Resource for impact analysis"), { target: { value: "" } });
    expect(screen.queryByText("Traffic inspection and hub dependencies degrade.")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Scenario")).toBeDisabled();
  });
});
