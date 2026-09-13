import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

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

function renderPage() {
  return render(
    <ScopeProvider>
      <ServicesPage />
    </ScopeProvider>,
  );
}

describe("Services catalog provider states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
        "Service catalog rows are available, but active situation data is unavailable: The incidents provider is deferred",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Data warnings")).toHaveTextContent(
      "The incidents provider is deferred",
    );
    expect(screen.getAllByText("Payments").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No active situation").length).toBeGreaterThan(0);
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
              operationalState: "No active situation",
            }),
          ],
        }),
      ),
    );
  });
});
