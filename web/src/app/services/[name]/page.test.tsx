import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  buildServiceDetailCopilotContext: vi.fn(),
  businessService: vi.fn(),
  impact: vi.fn(),
  risk: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  contextApi: {
    businessService: mocks.businessService,
    impact: mocks.impact,
    risk: mocks.risk,
  },
}));

vi.mock("@/lib/copilot/page-adapters", () => ({
  buildServiceDetailCopilotContext: mocks.buildServiceDetailCopilotContext,
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

import ServiceDetailPage from "./page";

const envelope = (
  data: Record<string, unknown>,
  warnings: string[],
) => ({
  data,
  evidence: [],
  scope: {},
  knowledge_version: "service-detail-test",
  warnings,
});

function renderPage() {
  return render(
    <ScopeProvider>
      <ServiceDetailPage params={{ name: "Demo" }} />
    </ScopeProvider>,
  );
}

describe("Service detail independent degradation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.businessService.mockResolvedValue(envelope({
      subject: {
        entity_type: "BusinessService",
        name: "Demo",
        owner: "Service owner",
      },
      sections: {
        subscription_connections: [{ subscription_id: "sub-a" }],
      },
      source_status: {
        "semantic-graph": "unavailable",
        "subscription-connections": "ok",
      },
    }, [
      "Semantic graph service context is unavailable; only retained subscription-connection facts are shown.",
    ]));
    mocks.risk.mockResolvedValue(envelope({
      subject: { name: "Demo" },
      risk: {},
      sections: {},
      source_status: { "semantic-graph": "unavailable" },
    }, [
      "Service risk evidence is unavailable; no service-specific risk facts are asserted.",
    ]));
    mocks.impact.mockResolvedValue(envelope({
      root: { name: "Demo" },
      sections: {},
      source_status: { "semantic-graph": "unavailable" },
    }, [
      "Dependency evidence is unavailable; no dependency facts are asserted.",
    ]));
    mocks.buildServiceDetailCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {},
      starterQuestions: [],
    });
  });

  it("preserves an already-decoded name containing a literal percent sign", async () => {
    render(<ScopeProvider><ServiceDetailPage params={{ name: "Demo 50% rollout" }} /></ScopeProvider>);
    await waitFor(() => expect(mocks.businessService).toHaveBeenCalledWith("Demo 50% rollout", {}));
    expect(screen.getByRole("heading", { name: "Demo 50% rollout" })).toBeInTheDocument();
  });

  it("keeps all sections visible and passes explicit degradation into Copilot", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Service context" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Aggregated risk" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Dependency impact" })).toBeInTheDocument();
    expect(screen.queryByText("Service view is unavailable")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(mocks.buildServiceDetailCopilotContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          name: "Demo",
          context: expect.objectContaining({
            available: true,
            freshness: "partial",
          }),
          risk: expect.objectContaining({
            available: false,
            freshness: "unavailable",
            warnings: [
              "Service risk evidence is unavailable; no service-specific risk facts are asserted.",
            ],
          }),
          impact: expect.objectContaining({
            available: false,
            freshness: "unavailable",
            warnings: [
              "Dependency evidence is unavailable; no dependency facts are asserted.",
            ],
          }),
          dependencies: [],
        }),
      ),
    );
  });
});
