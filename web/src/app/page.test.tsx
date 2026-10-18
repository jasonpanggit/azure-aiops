import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider, useScope } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  situations: vi.fn(),
  network: vi.fn(),
  vulnerabilities: vi.fn(),
  connections: vi.fn(),
  history: vi.fn(),
  buildOverviewCopilotContext: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  situationsApi: { list: mocks.situations },
  networkApi: { summary: mocks.network },
  vulnerabilityApi: { summary: mocks.vulnerabilities },
  connectionsApi: { list: mocks.connections },
  overviewApi: { history: mocks.history },
  buildCopilotSnapshot: vi.fn((input) => input),
  copilotEvidenceRows: vi.fn(() => []),
}));

vi.mock("@/lib/copilot/page-adapters", () => ({
  buildOverviewCopilotContext: mocks.buildOverviewCopilotContext,
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

import Home from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [],
  scope: {},
  knowledge_version: "overview-test",
  warnings: [],
  pagination: { offset: 0, limit: 100, total: Array.isArray(data) ? data.length : 1, next_offset: null },
});

const situation = (id: string, priority: "P1" | "P3", startedAt: string) => ({
  situation_id: id,
  resource_id: "",
  title: id,
  situation_type: "availability",
  lifecycle_state: "open",
  severity: priority === "P1" ? "critical" : "medium",
  priority,
  scope: {},
  owner: "",
  support_team: "",
  affected_resource_ids: [],
  linked_evidence_ids: [],
  started_at: startedAt,
  last_observed_at: startedAt,
  evidence_state: "partial",
  warnings: [],
  contradiction_ids: [],
  unknowns: [],
  run_id: `run-${id}`,
});

const overviewConnection = {
  connection_id: "fixture-connection", name: "Fixture connection", tenant_id: "fixture-tenant",
  subscription_id: "fixture-sub", scope_key: "fixture", is_active: true, business_service: "Payments",
  environment: "prod", owner: "Fixture owner", criticality: "high", sync_status: "succeeded",
  health_status: "healthy", last_successful_sync_at: "2026-10-16T00:00:00Z",
};

describe("Overview Copilot adapter integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.situations.mockResolvedValue(envelope([]));
    mocks.network.mockResolvedValue(envelope({
      gap_count: 0,
      rule_finding_count: 0,
    }));
    mocks.vulnerabilities.mockResolvedValue(envelope({
      internet_exposed_count: 0,
      reachable_server_count: 0,
    }));
    mocks.connections.mockResolvedValue(envelope([]));
    mocks.history.mockResolvedValue(envelope({ revision: 0, observations: [] }));
    mocks.buildOverviewCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {
        version: "1",
        page_kind: "resource",
        page_id: "operations-overview",
        selected_resources: [],
        filters: {},
        freshness: [],
        scope: { declared: {}, authorized: true },
        evidence: [],
        question: "Summarize the visible page evidence.",
        rechecks: [],
      },
      starterQuestions: [],
    });
  });

  it("passes already-loaded authorized Overview envelopes to the pure adapter", async () => {
    render(
      <ScopeProvider>
        <Home />
      </ScopeProvider>,
    );

    await waitFor(() => expect(mocks.buildOverviewCopilotContext).toHaveBeenCalledTimes(1));
    expect(mocks.buildOverviewCopilotContext).toHaveBeenCalledWith({
      scope: {},
      situations: expect.objectContaining({ data: [] }),
      network: expect.objectContaining({ data: expect.objectContaining({ gap_count: 0 }) }),
      vulnerabilities: expect.objectContaining({
        data: expect.objectContaining({ internet_exposed_count: 0 }),
      }),
      connections: expect.objectContaining({ data: [] }),
      visibleSituationIds: [],
    });
  });

  it("passes the same ranked situations rendered by the page", async () => {
    mocks.situations.mockResolvedValue(envelope([
      situation("p3-raw-first", "P3", "2026-01-03T00:00:00Z"),
      situation("p1-ranked-first", "P1", "2026-01-01T00:00:00Z"),
    ]));

    render(
      <ScopeProvider>
        <Home />
      </ScopeProvider>,
    );

    await waitFor(() =>
      expect(mocks.buildOverviewCopilotContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          visibleSituationIds: ["p1-ranked-first", "p3-raw-first"],
        }),
      ),
    );
  });

  it("does not assert healthy posture or a clean queue when a source fails", async () => {
    mocks.situations.mockRejectedValueOnce(new Error("provider unavailable"));
    mocks.connections.mockRejectedValueOnce(new Error("registry unavailable"));
    render(<ScopeProvider><Home /></ScopeProvider>);

    expect(await screen.findByLabelText("Posture score unavailable")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Operational posture is not assessed/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Situation evidence unavailable" })).toBeInTheDocument();
    expect(screen.queryByText("No active situations in this scope")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Posture score 100 out of 100")).not.toBeInTheDocument();
    expect(screen.getByText("Connection coverage is unavailable.")).toBeInTheDocument();
  });

  it("explains bounded contributors, raw saturation and finding units", async () => {
    mocks.situations.mockResolvedValue({ ...envelope([situation("p1", "P1", "2026-01-01T00:00:00Z")]),
      pagination: { offset: 0, limit: 100, total: 350, next_offset: 100 } });
    mocks.network.mockResolvedValue(envelope({ gap_count: 30, rule_finding_count: 0 }));
    mocks.vulnerabilities.mockResolvedValue(envelope({ internet_exposed_count: 2, reachable_server_count: 1 }));
    render(<ScopeProvider initialScope={{ environment: ["prod"], owner: ["A&B"] }}><Home /></ScopeProvider>);
    const region = await screen.findByRole("region", { name: "Overview score and evidence" });
    expect(within(region).getByText(/Raw deduction: 152; displayed score: 0/)).toBeInTheDocument();
    expect(within(region).getByText("1 loaded / 350 reported; partial page")).toBeInTheDocument();
    expect(within(region).getByText(/A vulnerability finding is not a distinct CVE/)).toBeInTheDocument();
    const href = within(region).getByRole("link", { name: "Review situations" }).getAttribute("href")!;
    expect(new URL(href, "http://local").searchParams.get("owner")).toBe("A&B");
    expect(screen.getAllByText("Internet-exposed findings").length).toBeGreaterThan(0);
  });

  it("puts actionable unknown and disabled connections before healthy registry rows", async () => {
    mocks.connections.mockResolvedValue(envelope([
      { ...overviewConnection, connection_id: "healthy", name: "A healthy" },
      { ...overviewConnection, connection_id: "unknown&bookmark", name: "Z unknown", health_status: "unknown", owner: "" },
      { ...overviewConnection, connection_id: "disabled", name: "B disabled", is_active: false },
    ]));
    render(<ScopeProvider><Home /></ScopeProvider>);
    await screen.findByRole("region", { name: "Overview score and evidence" });
    expect(screen.getByRole("img", { name: "1 healthy connection and 2 connections needing attention" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Review Z unknown" });
    expect(new URL(link.getAttribute("href")!, "http://local").searchParams.get("connection")).toBe("unknown&bookmark");
    expect(screen.getByText(/Registry health: unknown · Owner unmapped/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review B disabled" })).toHaveAttribute("href", "/connections");
  });

  it("discards prior-scope data immediately rather than evaluating it under a new scope", async () => {
    function Switcher() {
      const { setScope } = useScope();
      return <button onClick={() => setScope({ environment: ["prod"] })}>Change scope</button>;
    }
    mocks.situations.mockResolvedValueOnce(envelope([situation("old-private", "P1", "2026-01-01T00:00:00Z")]));
    render(<ScopeProvider><Switcher /><Home /></ScopeProvider>);
    await screen.findByRole("link", { name: "old-private" });
    mocks.situations.mockReturnValueOnce(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Change scope" }));
    expect(screen.queryByRole("link", { name: "old-private" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Overview score and evidence" })).not.toBeInTheDocument();
    expect(screen.getByText("Building your operational picture")).toBeInTheDocument();
  });
});
