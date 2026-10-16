import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider, useScope } from "@/lib/scope-context";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  buildServicesCopilotContext: vi.fn(),
  incidents: vi.fn(),
  listAll: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  connectionsApi: { listAll: mocks.listAll },
  operationsApi: { incidents: mocks.incidents },
}));

vi.mock("@/lib/copilot/page-adapters", () => ({
  buildServicesCopilotContext: mocks.buildServicesCopilotContext,
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

import ServicesPage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [],
  scope: {},
  knowledge_version: "services-test",
  warnings: [],
  pagination: {
    offset: 0,
    limit: 100,
    total: Array.isArray(data) ? data.length : 1,
    next_offset: null,
  },
});

function renderPage(scope: ScopeSelection = {}) {
  return render(
    <ScopeProvider initialScope={scope}>
      <ServicesPage />
    </ScopeProvider>,
  );
}

function SwitchScope() {
  const { setScope } = useScope();
  return <button onClick={() => setScope({ subscription: ["new-sub"] })}>Change scope</button>;
}

describe("Services catalog provider states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/services");
    mocks.listAll.mockResolvedValue(envelope([
      {
        connection_id: "prod",
        name: "Production",
        subscription_id: "sub-1",
        tenant_id: "tenant-1",
        scope_key: "subscription:sub-1",
        is_active: true,
        business_service: "Payments",
        environment: "production",
        criticality: "critical",
        sync_status: "completed",
        health_status: "healthy",
      },
    ]));
    mocks.incidents.mockRejectedValue(new Error("The incidents provider is deferred"));
    mocks.buildServicesCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {},
      starterQuestions: [],
    });
  });

  it("keeps connection-backed catalog rows visible when incidents are deferred", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Incident data deferred" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Service catalog rows are available, but incident evidence is unavailable: The incidents provider is deferred",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Data warnings")).toHaveTextContent(
      "The incidents provider is deferred",
    );
    expect(screen.getAllByText("Payments").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Incident evidence unavailable").length).toBeGreaterThan(0);
    expect(screen.queryByText("No active situation")).not.toBeInTheDocument();
    expect(screen.getByText("Not assessed")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Service catalog is incomplete" })).not.toBeInTheDocument();

    expect(mocks.listAll).toHaveBeenCalledWith({});
    await waitFor(() =>
      expect(mocks.buildServicesCopilotContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          connectionsAvailable: true,
          incidentsAvailable: false,
          services: [
            expect.objectContaining({
              name: "Payments",
              situationCount: 0,
              criticalCount: 0,
              operationalState: "Incident evidence unavailable",
            }),
          ],
        }),
      ),
    );
  });

  it("reports real loaded mapping gaps and a scoped corrective connection link", async () => {
    renderPage({ subscription: ["sub-1"], owner: ["Team"] });
    expect(await screen.findByRole("heading", { name: "Mapping completeness" })).toBeInTheDocument();
    expect(screen.getByText(/1\/1 loaded connection rows/)).toBeInTheDocument();
    expect(screen.getByText("0/1 mapped registry rows")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Production" });
    expect(link).toHaveAttribute("href", "/connections?subscription=sub-1&owner=Team&tab=subscriptions&connection=prod");
    expect(screen.getByRole("link", { name: "Payments" })).toHaveAttribute("href", "/services/Payments?subscription=sub-1&owner=Team");
  });

  it("does not turn a complete empty incident report into a service health claim", async () => {
    mocks.incidents.mockResolvedValue(envelope({ incidents: [] }));
    renderPage();
    expect((await screen.findAllByText("No incident associations in loaded report")).length).toBeGreaterThan(0);
    expect(screen.queryByText("No active situation")).not.toBeInTheDocument();
    const state = screen.getByRole("combobox", { name: "Filter by State" });
    fireEvent.change(state, { target: { value: "No incident associations in loaded report" } });
    expect(screen.getByRole("link", { name: "Payments" })).toBeInTheDocument();
  });

  it("drops prior-scope rows and Copilot observations while replacement providers are pending", async () => {
    render(<ScopeProvider><SwitchScope /><ServicesPage /></ScopeProvider>);
    expect(await screen.findByRole("link", { name: "Payments" })).toBeInTheDocument();
    mocks.listAll.mockReturnValue(new Promise(() => {}));
    mocks.incidents.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Change scope" }));
    expect(screen.queryByRole("link", { name: "Payments" })).not.toBeInTheDocument();
    expect(mocks.buildServicesCopilotContext).toHaveBeenLastCalledWith(expect.objectContaining({
      scope: { subscription: ["new-sub"] }, services: [], incidentsAvailable: false,
    }));
  });
});
