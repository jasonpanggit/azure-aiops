import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  situations: vi.fn(),
  network: vi.fn(),
  vulnerabilities: vi.fn(),
  connections: vi.fn(),
  buildOverviewCopilotContext: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  situationsApi: { list: mocks.situations },
  networkApi: { summary: mocks.network },
  vulnerabilityApi: { summary: mocks.vulnerabilities },
  connectionsApi: { list: mocks.connections },
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
});
