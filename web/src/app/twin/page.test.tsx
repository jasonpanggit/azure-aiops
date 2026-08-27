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

vi.mock("@/lib/services", () => ({
  twinApi: { compare, graph, scenario, traverse, export: twinExport },
}));

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
  previous_version: "v0",
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
    previous_state_version: "v0",
    change_history: [{ change_type: "vulnerability_observed" }],
    risk_trend: [{ risk_score: 32 }],
    dependency_evolution: [{ relationship_type: "supports", current_count: 1, previous_count: 0 }],
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
    graph.mockResolvedValue(envelope(snapshot));
    compare.mockResolvedValue(envelope({
      current_version: "v1",
      previous_version: "v0",
      added: [snapshot.entities[0]],
      removed: [],
      changed: [],
      summary: "4 current entities; prior state retained as v0 for temporal comparison.",
    }));
    scenario.mockResolvedValue(envelope({
      scenario: "firewall_failure",
      target: "vm-payroll-1",
      version: "v1",
      likely_impact: "Traffic inspection and hub dependencies degrade.",
      risk_delta: 20,
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
    expect(screen.getByText(/prior state retained/)).toBeInTheDocument();
    expect(await screen.findByText("Traffic inspection and hub dependencies degrade.")).toBeInTheDocument();
    expect(screen.getByText(/Consequence: Payroll -> Payroll API/)).toBeInTheDocument();
    expect(screen.getByText("operational-twin-export")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: "cve_exploitation" } });
    await waitFor(() => expect(scenario).toHaveBeenLastCalledWith("cve_exploitation", "vm-payroll-1", {}));
  });
});
