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

  it("selects one or more subscriptions from the dropdown menu", async () => {
    render(
      <ScopeProvider>
        <ScopeSelector />
      </ScopeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: /All subscriptions/i }));
    await waitFor(() => expect(listAll).toHaveBeenCalled());

    const subscriptionMenu = await screen.findByLabelText("Subscription");
    fireEvent.change(subscriptionMenu, { target: { value: "sub-001" } });
    expect(screen.getAllByText("sub-001")).toHaveLength(2);
  });
});
