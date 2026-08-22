import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createIncidentFinding } from "@/test/incident-fixture";

const { incident } = vi.hoisted(() => ({ incident: vi.fn() }));

vi.mock("@/lib/services", () => ({
  operationsApi: { incident },
}));

import SituationDetailPage from "./page";

describe("Situation investigation", () => {
  beforeEach(() => {
    const finding = createIncidentFinding();
    finding.root_cause_analysis.contradicting_evidence = [
      { evidence_id: "ALT-1", summary: "Patch installed successfully", evidence_type: "Patch Success" },
    ];
    finding.root_cause_analysis.unknowns = ["network_change_evidence_unavailable:vm-payments"];
    finding.root_cause_analysis.next_steps = ["Review NSG, firewall, and route-change evidence for vm-payments."];
    finding.blast_radius.subscriptions = ["sub-1"];
    finding.blast_radius.network_paths = ["nic-payments is in a spoke VNet peered with hub-vnet"];
    finding.blast_radius.hub_dependencies = ["hub-vnet"];
    finding.blast_radius.firewall_impact = [{ finding_id: "fw-1", title: "Firewall rule changed" }];
    finding.blast_radius.nsg_impact = [{ finding_id: "nsg-1", title: "NSG rule changed" }];
    finding.blast_radius.downstream_services = ["Checkout API"];
    incident.mockResolvedValue({
      data: {
        finding,
        read_only: true,
        freshness: "2025-03-01T10:05:00Z",
      },
      evidence: [
        {
          source_engine: "intelligence.IncidentEngine",
          source_table: "incident_projection",
          timestamp: "2025-03-01T10:05:00Z",
          confidence: "medium",
        },
      ],
      scope: {},
      knowledge_version: "snapshot-42",
    });
  });

  it("answers the operator questions and renders the new investigation panels", async () => {
    render(<SituationDetailPage params={{ id: "INC-1001" }} />);

    expect(await screen.findByRole("heading", { name: "What failed?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What is at risk?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Who owns it?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What changed?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How do I fix it?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Root-cause candidates" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Network-aware blast radius" })).toBeInTheDocument();
    expect(screen.getByText("Patch installed successfully")).toBeInTheDocument();
    expect(screen.getByText("network_change_evidence_unavailable:vm-payments")).toBeInTheDocument();
    expect(screen.getByText("sub-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create action plan" })).toHaveAttribute("href", "/remediation?incident=INC-1001");
  });

  it("opens the evidence drawer from a cause", async () => {
    render(<SituationDetailPage params={{ id: "INC-1001" }} />);
    fireEvent.click(await screen.findByRole("button", { name: "View evidence" }));
    expect(screen.getByRole("heading", { name: "Evidence drawer" })).toBeInTheDocument();
  });
});
