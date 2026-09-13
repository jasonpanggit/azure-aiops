import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  snapshot: vi.fn(),
  buildResourceHealthCopilotContext: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  resourceHealthApi: { snapshot: mocks.snapshot },
}));

vi.mock("@/lib/copilot/page-adapters", () => ({
  buildResourceHealthCopilotContext: mocks.buildResourceHealthCopilotContext,
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

import ResourceHealthPage from "./page";

function resource(
  resourceName: string,
  resourceType: string,
) {
  return {
    resource_id: `/subscriptions/sub-1/resourceGroups/rg/providers/${resourceType}/${resourceName}`,
    resource_name: resourceName,
    resource_type: resourceType,
    subscription_id: "sub-1",
    resource_group: "rg",
    connection_id: "connection-1",
    cpu_percent: 12,
    network_in_bytes: 100,
    network_out_bytes: 50,
    disk_read_bytes: null,
    disk_write_bytes: null,
    os_disk_queue_depth: null,
    memory_percent: 25,
    disk_free_percent: null,
    status: "healthy",
    observed_at: "2026-09-12T00:00:00Z",
    error: "",
    unavailable_metrics: [],
    cpu_series: [],
  };
}

describe("Resource Health resource cards", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.snapshot.mockResolvedValue({
      data: {
        resources: [
          resource("api", "microsoft.app/containerapps"),
          resource("vm-1", "microsoft.compute/virtualmachines"),
        ],
        summary: {
          total: 2,
          critical: 0,
          warning: 0,
          healthy: 2,
          unknown: 0,
        },
        observed_at: "2026-09-12T00:00:00Z",
        warnings: [],
        unavailable_metrics: [],
        cached: false,
        cache_ttl_seconds: 120,
      },
      evidence: [],
      scope: {},
    });
    mocks.buildResourceHealthCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: null,
      starterQuestions: [],
    });
  });

  it("shows a friendly resource-type pill on every resource card", async () => {
    render(
      <ScopeProvider>
        <ResourceHealthPage />
      </ScopeProvider>,
    );

    expect(
      await screen.findByText("Container App", { selector: ".status-badge" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Virtual Machine", { selector: ".status-badge" }),
    ).toBeInTheDocument();
  });
});
