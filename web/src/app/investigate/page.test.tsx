import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { ThreadContinuityContextValue } from "@/lib/copilot/thread-context";

const navigation = vi.hoisted(() => ({ query: "" }));
const continuity = vi.hoisted<{ value: ThreadContinuityContextValue | null }>(() => ({ value: null }));

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
  investigateCanonical,
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
  investigateCanonical: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
}));

vi.mock("@/lib/copilot/thread-context", () => ({
  useOptionalThreadContinuity: () => continuity.value,
}));

vi.mock("@/components/network/TopologyWorkspace", () => ({
  TopologyWorkspace: ({ gaps }: { gaps: Array<{ gap_id: string; title?: string }> }) => (
    <div data-testid="topology-workspace">
      Topology canvas
      {gaps.map((gap) => <span key={gap.gap_id}>{gap.title ?? gap.gap_id}</span>)}
    </div>
  ),
}));

// Keep the real presentation converter so this test exercises the shared
// canonical semantics, overriding only provider calls.
vi.mock("@/lib/services", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/services")>();
  return {
    ...actual,
    contextApi: { businessService, risk, impact, application: vi.fn(), environment: vi.fn(), subscriptionConnectionContext: vi.fn() },
    operationsApi: { incidents, incident, remediationPlans },
    networkApi: { topology, gaps, ruleFindings },
    vulnerabilityApi: { summary, exposures, cve, attackPath },
  };
});

vi.mock("@/lib/copilot/page-adapters", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/copilot/page-adapters")>();
  return { ...actual, investigateCanonical };
});

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

function ScopeSwitcher() {
  const { setScope } = useScope();
  return <button onClick={() => setScope({ subscription: ["sub-b"] })}>Switch operating scope</button>;
}

function renderWorkspace(initialScope?: ScopeSelection) {
  return render(
    <ScopeProvider initialScope={initialScope}>
      <ScopeSwitcher />
      <InvestigationWorkspacePage />
    </ScopeProvider>
  );
}

describe("Executive Investigation Workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.query = "type=BusinessService&value=Payments";
    continuity.value = null;
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
        timeline: [
          { event_id: "evt-1", event_type: "Alert", timestamp: "2026-01-01T10:00:00Z", summary: "Latency breach", source: "Monitor", evidence: ["ARG"] },
          { event_id: "evt-1", event_type: "Alert", timestamp: "2026-01-01T09:59:00Z", summary: "Repeated signal", source: "Monitor", evidence: ["ARG"] },
        ],
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
    investigateCanonical.mockResolvedValue(envelope({
      status: "ok",
      selected_specialists: ["incident", "vulnerability"],
      selected_tools: ["incidents", "cve_exposure"],
      tool_results: [
        { call_id: "call-1", specialist_id: "vulnerability", tool: "cve_exposure", status: "ok", data: { cve_id: "CVE-2026-0001" }, evidence: [], warning: "" },
      ],
      contract_version: "1",
      thread_id: `thr-${"a".repeat(32)}`,
      thread_revision: 1,
      policy_status: "fallback",
      fallback_reason: "planner_unavailable",
      coverage: { visible_count: 1, total_count: 2, complete: false },
      uncertainty: [
        "Visible subset is incomplete; widen scope for full coverage.",
        "Visible subset is incomplete; widen scope for full coverage.",
      ],
      citations: [
        { citation_id: "tool:0:vulnerability:1", source: "azure-resource-graph", status: "ok", observed_at: "2026-01-01T10:00:00Z", resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1" },
      ],
      synthesis: {
        status: "degraded",
        reason: "multi_domain",
        domain_count: 2,
        claims: [
          { finding_id: "f1", summary: "Payments is at risk because CVE-2026-0001 is reachable; approve patch plan-1.", evidence_refs: ["tool:0:vulnerability:1"], confidence: "high", freshness: "fresh", uncertainty: [] },
        ],
        warning: "",
      },
      mutation_authorized: false,
    }));
  });

  it("connects service risk, topology, vulnerability, evidence, Copilot conclusion, and remediation in one flow", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderWorkspace();

    expect(await screen.findByRole("heading", { name: "Business impact and dependency context" })).toBeInTheDocument();
    expect(screen.getAllByText("Payments SRE").length).toBeGreaterThan(0);
    expect(screen.getByTestId("topology-workspace")).toHaveTextContent("Firewall bypass");
    expect(screen.getByText("CVE-2026-0001")).toBeInTheDocument();
    expect(screen.getAllByText("securityresources").length).toBeGreaterThan(0);
    expect(screen.getByText("Patch payment servers")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));

    // Canonical synthesis narration is rendered as the conclusion.
    expect(await screen.findByText(/approve patch plan-1/i)).toBeInTheDocument();

    expect(investigateCanonical).toHaveBeenCalledWith(
      expect.objectContaining({
        question: expect.stringContaining("Summarize the investigation"),
        requested_scope: expect.anything(),
        snapshot: expect.objectContaining({
          version: "2",
          page_kind: "investigate",
          page_id: "investigate",
          coverage: expect.objectContaining({ complete: true }),
          evidence: expect.arrayContaining([
            expect.objectContaining({ source: "investigate/incidents" }),
            expect.objectContaining({ source: "investigate/vulnerabilities" }),
            expect.objectContaining({ source: "investigate/remediation" }),
          ]),
        }),
      }),
      expect.anything(),
    );
    expect(investigateCanonical.mock.calls[0][0]).not.toHaveProperty("mutation_authorized");

    // Canonical degradation, citations, and uncertainty render consistently.
    expect(screen.getByLabelText("Investigation degradation")).toHaveTextContent(/deterministic|narration was not produced/i);
    expect(screen.getByLabelText("Investigation citations")).toHaveTextContent("azure-resource-graph");
    expect(screen.getByLabelText("Investigation uncertainty")).toHaveTextContent(/visible subset is incomplete/i);

    fireEvent.click(screen.getByRole("button", { name: "Save view locally" }));
    await waitFor(() => expect(window.localStorage.getItem("aiops.investigations.v1")).toContain("BusinessService: Payments"));
    expect(
      consoleError.mock.calls.some((call) =>
        call.some((value) => String(value).includes("same key"))),
    ).toBe(false);
    consoleError.mockRestore();
  });

  it.each([
    "type=Unknown", "mode=unsupported", "mode=", "type=CVE&type=Incident",
    "value=one&value=two", "mode=engineer&mode=executive", "value=bad%0Avalue",
    `value=${"x".repeat(513)}`,
    "workspace_id=invalid", `workspace_id=wrk-${"a".repeat(32)}&workspace_revision=0`,
    `workspace_id=wrk-${"a".repeat(32)}&workspace_revision=41`, "workspace_revision=1",
    `workspace_id=wrk-${"a".repeat(32)}&workspace_revision=01`,
    `workspace_id=wrk-${"a".repeat(32)}&workspace_revision=1&workspace_revision=2`,
  ])("rejects malformed entry bookmarks before loading sources: %s", async query => {
    navigation.query = query;
    renderWorkspace();
    expect(screen.getByText("Investigation bookmark unavailable")).toBeInTheDocument();
    expect(incidents).not.toHaveBeenCalled();
    expect(businessService).not.toHaveBeenCalled();
    expect(investigateCanonical).not.toHaveBeenCalled();
  });

  it.each(SCOPE_DIMENSIONS)("passes bookmarked %s to every source and Copilot", async dimension => {
    navigation.query += `&${dimension}=narrow`;
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    const effective = { [dimension]: ["narrow"] };
    for (const source of [incidents, topology, gaps, ruleFindings, summary, exposures, remediationPlans]) {
      expect(source.mock.calls[0][0]).toEqual(effective);
    }
    expect(businessService).toHaveBeenCalledWith("Payments", effective);
    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    await screen.findByText(/approve patch plan-1/i);
    expect(investigateCanonical.mock.calls[0][0].requested_scope).toEqual(effective);
    expect(investigateCanonical.mock.calls[0][1]).toEqual(effective);
  });

  it.each(SCOPE_DIMENSIONS)("rejects a bookmarked %s outside the current selection", dimension => {
    navigation.query += `&${dimension}=outside`;
    renderWorkspace({ [dimension]: ["permitted"] });
    expect(screen.getByText("Investigation bookmark unavailable")).toBeInTheDocument();
    expect(incidents).not.toHaveBeenCalled();
  });

  it("preserves all nine scope dimensions in shared links without executing Copilot", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, [`${dimension}-a`, `${dimension}-b`]]));
    renderWorkspace(scope);
    await screen.findByText("Patch payment servers");
    const copy = vi.fn().mockResolvedValue(undefined);
    const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: copy } });
    const originalUrl = window.location.href;
    try {
      fireEvent.click(screen.getByRole("button", { name: "Copy current entry link" }));
      await waitFor(() => expect(copy).toHaveBeenCalledOnce());
      const shared = new URL(copy.mock.calls[0][0]);
      for (const dimension of SCOPE_DIMENSIONS) {
        expect(shared.searchParams.getAll(dimension)).toEqual(scope[dimension]);
      }
      expect(shared.searchParams.get("type")).toBe("BusinessService");
      expect(shared.searchParams.get("value")).toBe("Payments");
      expect(shared.searchParams.get("mode")).toBe("executive");
      expect(investigateCanonical).not.toHaveBeenCalled();
    } finally {
      if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
      else Reflect.deleteProperty(navigator, "clipboard");
      window.history.replaceState(null, "", originalUrl);
    }
  });

  it("surfaces clipboard failure with a usable entry link and no false copy audit", async () => {
    renderWorkspace({ subscription: ["sub-a"] });
    await screen.findByText("Patch payment servers");
    const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error("clipboard unavailable")) },
    });
    try {
      fireEvent.click(screen.getByRole("button", { name: "Copy current entry link" }));
      await screen.findByText(/Clipboard copy unavailable/);
      expect(screen.getByRole("link", { name: "Open current entry link" })).toHaveAttribute(
        "href", expect.stringContaining("subscription=sub-a"),
      );
      expect(screen.queryByText("Copied current entry link")).not.toBeInTheDocument();
      expect(investigateCanonical).not.toHaveBeenCalled();
    } finally {
      if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
      else Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it.each(["success", "failure"] as const)("discards late Copilot %s after operating scope changes", async outcome => {
    let resolve!: (value: unknown) => void;
    let reject!: (error: Error) => void;
    const answer = await investigateCanonical();
    investigateCanonical.mockClear();
    investigateCanonical.mockReturnValueOnce(new Promise((accept, fail) => { resolve = accept; reject = fail; }));
    const acceptServerState = vi.fn();
    continuity.value = {
      thread: null, generation: 0, requiresServerRevalidation: false, resetReason: null,
      acceptServerState, resetContinuity: vi.fn(),
    };
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    expect(investigateCanonical).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Generate conclusion" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Switch operating scope" }));
    await screen.findByText("Patch payment servers");
    await act(async () => {
      if (outcome === "success") resolve(answer);
      else reject(new Error("old scope unavailable"));
    });
    expect(screen.queryByText(/approve patch plan-1/i)).not.toBeInTheDocument();
    expect(screen.queryByText("copilot unavailable")).not.toBeInTheDocument();
    expect(acceptServerState).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Generate conclusion" })).toBeEnabled();
  });

  it("clears prior subject evidence while replacement sources are pending", async () => {
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    incidents.mockReturnValueOnce(new Promise(() => {}));
    fireEvent.change(screen.getByRole("textbox", { name: "Subject" }), { target: { value: "Another service" } });
    await waitFor(() => expect(businessService).toHaveBeenCalledWith("Another service", {}));
    expect(screen.queryByText("Patch payment servers")).not.toBeInTheDocument();
    expect(screen.queryByText("CVE-2026-0001")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate conclusion" })).toBeDisabled();
    expect(screen.getByLabelText("Current signals value")).toHaveTextContent("—");
    expect(screen.queryByText("Quiet")).not.toBeInTheDocument();
  });

  it("does not infer quiet or a historical trend from unavailable sources", async () => {
    exposures.mockRejectedValueOnce(new Error("provider unavailable"));
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    expect(screen.getByLabelText("Current signals value")).toHaveTextContent("—");
    expect(screen.getByText("Incident or exposure evidence unavailable; no activity conclusion is available")).toBeInTheDocument();
    expect(screen.queryByText("Quiet")).not.toBeInTheDocument();
  });

  it("does not reuse or rebind root conversation continuity for a narrowed bookmark", async () => {
    navigation.query += "&subscription=sub-a";
    const acceptServerState = vi.fn();
    continuity.value = {
      thread: { threadId: `thr-${"b".repeat(32)}`, threadRevision: 3 },
      generation: 0, requiresServerRevalidation: false, resetReason: null,
      acceptServerState, resetContinuity: vi.fn(),
    };
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    await screen.findByText(/approve patch plan-1/i);
    expect(investigateCanonical.mock.calls[0][0]).not.toHaveProperty("thread_id");
    expect(investigateCanonical.mock.calls[0][0]).not.toHaveProperty("expected_thread_revision");
    expect(acceptServerState).not.toHaveBeenCalled();
  });

  it("continues and accepts the root conversation only in the matching effective scope", async () => {
    const acceptServerState = vi.fn();
    continuity.value = {
      thread: { threadId: `thr-${"b".repeat(32)}`, threadRevision: 3 },
      generation: 7, requiresServerRevalidation: false, resetReason: null,
      acceptServerState, resetContinuity: vi.fn(),
    };
    const result = await investigateCanonical();
    investigateCanonical.mockClear();
    investigateCanonical.mockResolvedValueOnce({
      ...result, data: { ...result.data, thread_id: `thr-${"b".repeat(32)}`, thread_revision: 4 },
    });
    renderWorkspace({ subscription: ["sub-a"] });
    await screen.findByText("Patch payment servers");
    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    await screen.findByText(/approve patch plan-1/i);
    expect(investigateCanonical.mock.calls[0][0]).toMatchObject({
      thread_id: `thr-${"b".repeat(32)}`, expected_thread_revision: 3,
    });
    expect(acceptServerState).toHaveBeenCalledWith({ threadId: `thr-${"b".repeat(32)}`, threadRevision: 4 }, 7);
  });

  it("rejects a response targeting a different root conversation", async () => {
    const acceptServerState = vi.fn();
    continuity.value = {
      thread: { threadId: `thr-${"b".repeat(32)}`, threadRevision: 3 },
      generation: 7, requiresServerRevalidation: false, resetReason: null,
      acceptServerState, resetContinuity: vi.fn(),
    };
    renderWorkspace();
    await screen.findByText("Patch payment servers");
    fireEvent.click(screen.getByRole("button", { name: "Generate conclusion" }));
    await screen.findByText("copilot unavailable");
    expect(screen.queryByText(/approve patch plan-1/i)).not.toBeInTheDocument();
    expect(acceptServerState).not.toHaveBeenCalled();
  });
});
