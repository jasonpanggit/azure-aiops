import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const {
  businessService,
  risk,
  impact,
  incidents,
  incident,
  remediationPlans,
  topology,
  gaps,
  ruleFindings,
  summary,
  exposures,
  cve,
  attackPath,
  investigate,
} = vi.hoisted(() => ({
  businessService: vi.fn(),
  risk: vi.fn(),
  impact: vi.fn(),
  incidents: vi.fn(),
  incident: vi.fn(),
  remediationPlans: vi.fn(),
  topology: vi.fn(),
  gaps: vi.fn(),
  ruleFindings: vi.fn(),
  summary: vi.fn(),
  exposures: vi.fn(),
  cve: vi.fn(),
  attackPath: vi.fn(),
  investigate: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("type=BusinessService&value=Payments"),
}));

vi.mock("@/components/network/TopologyWorkspace", () => ({
  TopologyWorkspace: ({ gaps }: { gaps: Array<{ gap_id: string; title?: string }> }) => (
    <div data-testid="topology-workspace">
      Topology canvas
      {gaps.map((gap) => <span key={gap.gap_id}>{gap.title ?? gap.gap_id}</span>)}
    </div>
  ),
}));

vi.mock("@/lib/services", () => ({
  contextApi: { businessService, risk, impact, application: vi.fn(), environment: vi.fn(), subscriptionConnectionContext: vi.fn() },
  operationsApi: { incidents, incident, remediationPlans },
  networkApi: { topology, gaps, ruleFindings },
  vulnerabilityApi: { summary, exposures, cve, attackPath },
  copilotApi: { investigate },
}));

import InvestigationWorkspacePage from "./page";

const evidence = [
  {
    source_engine: "ARG",
    source_table: "securityresources",
    timestamp: "2026-01-01T10:00:00Z",
    confidence: "high",
    freshness: "fresh",
  },
];

const envelope = <T,>(data: T) => ({
  data,
  evidence,
  scope: {},
  knowledge_version: "graph-1",
  graph_freshness: "2026-01-01T09:59:00Z",
  live_observed_at: "2026-01-01T10:00:00Z",
  source_status: { ARG: "live" },
});

function renderWorkspace() {
  return render(
    <ScopeProvider>
      <InvestigationWorkspacePage />
    </ScopeProvider>
  );
}

describe("Executive Investigation Workspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
    businessService.mockResolvedValue(envelope({
      subject: { name: "Payments", owner: "Payments SRE", entity_type: "business_service" },
      sections: { ownership: [{ name: "Payments SRE" }] },
    }));
    risk.mockResolvedValue(envelope({
      subject: { name: "Payments", entity_type: "business_service" },
      sections: {},
      risk: { score: 82 },
    }));
    impact.mockResolvedValue(envelope({
      subject: { name: "Payments", entity_type: "business_service" },
      sections: { dependencies: [{ name: "Checkout API" }] },
    }));
    incidents.mockResolvedValue(envelope({
      report_type: "summary",
      audience_summaries: {},
      incidents: [{
        incident: { incident_id: "INC-1", title: "Payment latency", severity: "high", status: "active", started_at: "2026-01-01T09:00:00Z" },
        root_cause_analysis: { timeline: [], probable_causes: [], contributing_factors: [], confidence: 0.7, evidence: [], impacted_systems: [], reasoning_chain: [], contradicting_evidence: [], unknowns: [], next_steps: [], confirmed_cause: false, conclusion: "Investigating" },
        blast_radius: { applications: ["Checkout"], services: [], business_services: ["Payments"], owners: ["Payments SRE"], support_teams: [], subscriptions: ["sub-1"], network_paths: [], hub_dependencies: [], firewall_impact: [], nsg_impact: [], downstream_services: [], application_count: 1, service_count: 0, business_service_count: 1 },
        timeline: [{ event_id: "evt-1", event_type: "Alert", timestamp: "2026-01-01T10:00:00Z", summary: "Latency breach", source: "Monitor", evidence: ["ARG"] }],
        business_impact: { applications: ["Checkout"], services: [], business_services: ["Payments"], owners: ["Payments SRE"], support_teams: [] },
      }],
      operational_patterns: [],
      freshness: "2026-01-01T10:00:00Z",
      read_only: true,
    }));
    topology.mockResolvedValue(envelope({
      topology: { hubs: [], spokes: [], isolated: [], links: [], shared_services: [], unresolved_peer_vnet_ids: [], connection_ids: [], counts: {} },
      summary: {},
    }));
    gaps.mockResolvedValue(envelope({
      gaps: [{ gap_id: "gap-1", title: "Firewall bypass", category: "routing", severity: "high" }],
      intended_design_declared: true,
      summary: {},
    }));
    ruleFindings.mockResolvedValue(envelope({ findings: [], summary: {} }));
    summary.mockResolvedValue(envelope({
      cve_count: 1,
      finding_count: 2,
      affected_server_count: 2,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      internet_exposed_count: 1,
      critical_count: 1,
      top_priority: [],
      freshness: "2026-01-01T10:00:00Z",
      metadata_source: "ARG",
    }));
    exposures.mockResolvedValue(envelope([{
      cve_id: "CVE-2026-0001",
      severity: "critical",
      missing_kb: "KB500",
      affected_server_count: 2,
      affected_application_count: 1,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      exploit_signal: "known exploited",
      internet_exposed: true,
      critical_business_count: 1,
      priority_score: 91,
      expected_risk_reduction: 60,
      recommended_patch: "Install KB500",
      epss_score: 0.9,
      is_known_exploited: true,
      finding_ids: ["finding-1"],
    }]));
    remediationPlans.mockResolvedValue(envelope({
      plans: [{ plan_id: "plan-1", title: "Patch payment servers", status: "candidate", simulation_result: { risk_reduction_percent: 60 } }],
      generated_at: "2026-01-01T10:00:00Z",
    }));
    incident.mockResolvedValue(envelope({ finding: {}, read_only: true, freshness: "2026-01-01T10:00:00Z" }));
    cve.mockResolvedValue(envelope({}));
    attackPath.mockResolvedValue(envelope({ cve_id: "CVE-2026-0001", nodes: [], edges: [], reachable_server_count: 1, internet_exposed: true }));
    investigate.mockResolvedValue(envelope({
      question: "why",
      tool_calls: [],
      answer: { text: "Payments is at risk because CVE-2026-0001 is reachable; approve patch plan-1.", agent_name: "ops", model: "test", grounded: true },
      fact_status: "ok",
      warnings: [],
    }));
  });

  it("connects service risk, topology, vulnerability, evidence, Copilot conclusion, and remediation in one flow", async () => {
    renderWorkspace();

    expect(await screen.findByRole("heading", { name: "Business impact and dependency context" })).toBeInTheDocument();
    expect(screen.getAllByText("Payments SRE").length).toBeGreaterThan(0);
    expect(screen.getByTestId("topology-workspace")).toHaveTextContent("Firewall bypass");
    expect(screen.getByText("CVE-2026-0001")).toBeInTheDocument();
    expect(screen.getAllByText("securityresources").length).toBeGreaterThan(0);
    expect(screen.getByText("Patch payment servers")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    expect(await screen.findByText(/approve patch plan-1/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save view locally" }));
    await waitFor(() => expect(window.localStorage.getItem("aiops.investigations.v1")).toContain("BusinessService: Payments"));
  });
});
