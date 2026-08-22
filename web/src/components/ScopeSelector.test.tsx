import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { listAll } = vi.hoisted(() => ({ listAll: vi.fn() }));

vi.mock("@/lib/services", () => ({
  connectionsApi: { listAll },
}));

import { ScopeSelector } from "./ScopeSelector";

describe("ScopeSelector", () => {
  beforeEach(() => {
    listAll.mockReset();
    listAll.mockResolvedValue({
      data: [
        {
          connection_id: "prod-east",
          name: "Production East",
          subscription_id: "sub-001",
          tenant_id: "tenant-001",
          scope_key: "prod-east",
          is_active: true,
          business_service: "Payments",
          application: "Checkout",
          environment: "prod",
          owner: "Platform",
          support_team: "SRE",
          criticality: "critical",
          region: "eastus",
          sync_status: "succeeded",
          health_status: "healthy",
        },
      ],
      evidence: [],
      scope: {},
    });
  });

  it("selects business services and subscription connections from dropdown menus", async () => {
    render(
      <ScopeProvider>
        <ScopeSelector />
      </ScopeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /All operations/i }));
    await waitFor(() => expect(listAll).toHaveBeenCalled());

    const valueMenu = await screen.findByLabelText("Business Service");
    fireEvent.change(valueMenu, { target: { value: "Payments" } });
    expect(screen.getAllByText("Payments")).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("Filter by"), {
      target: { value: "subscription_connection" },
    });
    fireEvent.change(screen.getByLabelText("Subscription Connection"), {
      target: { value: "prod-east" },
    });

    expect(screen.getByText("prod-east")).toBeInTheDocument();
  });
});
