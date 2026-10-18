import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  buildServiceDetailCopilotContext: vi.fn(),
  businessService: vi.fn(),
  impact: vi.fn(),
  risk: vi.fn(),
}));

vi.mock("@/lib/services", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/services")>(),
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

describe("Service detail independent degradation", () => {
it("shows typed facts, object dependencies, separate impact identities and honest readiness", async () => {
  mocks.businessService.mockResolvedValue(envelope({
    subject: { entity_type: "BusinessService", name: "Demo", owner: "SRE", support_team: "On call" },
    sections: {
      applications: [{ entity_type: "Application", name: "Checkout" }],
      dependencies: [{ entity_type: "Application", name: "Payments" }, "legacy unknown"],
    },
  }, []));
  mocks.impact.mockResolvedValue(envelope({
    root: { name: "Demo" }, impacted_resources: [{
      name: "vm", entity_type: "Resource",
      resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm",
    }],
  }, []));
  renderPage();
  const brief = await screen.findByRole("region", { name: "Typed service brief" });
  expect(within(brief).getByText("SRE")).toBeInTheDocument();
  expect(within(brief).getAllByText("Unreported or ambiguous").length).toBeGreaterThan(0);
  const dependencies = screen.getByRole("region", { name: "Navigable service dependencies" });
  expect(within(dependencies).getByRole("link", { name: "Payments" })).toHaveAttribute("href", "/investigate?type=Application&value=Payments");
  expect(within(dependencies).getByRole("link", { name: "vm" })).toHaveAttribute("href", expect.stringContaining("/inventory/assets?resource_id="));
  expect(within(dependencies).getByText(/4 matching \/ 4 loaded/)).toBeInTheDocument();
  fireEvent.change(within(dependencies).getByRole("textbox", { name: "Find dependency" }), { target: { value: "Payments" } });
  expect(within(dependencies).queryByRole("link", { name: "vm" })).not.toBeInTheDocument();
  expect(within(dependencies).getByText(/1 matching \/ 4 loaded/)).toBeInTheDocument();
  await waitFor(() => expect(mocks.buildServiceDetailCopilotContext).toHaveBeenLastCalledWith(expect.objectContaining({
    context: expect.objectContaining({ freshness: "partial" }),
    dependencies: expect.arrayContaining([expect.objectContaining({ name: "Payments", relation: "dependencies" })]),
  })));
});

function renderPage() {
  return render(
    <ScopeProvider>
      <ServiceDetailPage params={{ name: "Demo" }} />
    </ScopeProvider>,
  );
}

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/services/Demo");
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
