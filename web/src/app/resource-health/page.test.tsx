import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScopeSelection } from "@/lib/scope";
import { RESOURCE_HEALTH_INSIGHT_QUESTION } from "@/lib/copilot/page-adapters";
import type {
  Envelope,
  FlatInventoryResource,
  FlatResourceCollection,
  ResourceHealthSnapshot,
  ResourceUtilization,
} from "@/lib/types";

const mocks = vi.hoisted(() => ({
  inventoryResources: vi.fn(),
  resourceHealth: vi.fn(),
  retainedHealth: vi.fn(),
  captureRetainedHealth: vi.fn(),
  copilotInsights: vi.fn(() => null),
  scope: { current: { subscription: ["sub-a"] } as ScopeSelection },
}));

vi.mock("@/lib/services", () => ({
  inventoryApi: { resources: mocks.inventoryResources },
  resourceHealthApi: {
    resource: mocks.resourceHealth,
    history: mocks.retainedHealth,
    captureHistory: mocks.captureRetainedHealth,
  },
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: mocks.scope.current }),
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

vi.mock("@/components/ui/CopilotDrawerButton", () => ({
  CopilotDrawerButton: () => null,
}));

vi.mock("@/components/ui/CopilotInsights", () => ({
  CopilotInsights: mocks.copilotInsights,
}));

vi.mock("@/lib/copilot/page-adapters", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/copilot/page-adapters")>(),
  buildResourceHealthCopilotContext: () => ({
    requestedScope: {},
    snapshot: {},
    starterQuestions: [],
  }),
}));

import ResourceHealthPage from "./page";

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
}

interface HealthCall {
  resourceId: string;
  scope: ScopeSelection;
  forceRefresh: boolean;
  signal: AbortSignal;
  deferred: Deferred<Envelope<ResourceHealthSnapshot>>;
  settled: boolean;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function inventoryResource(index: number, subscription = "sub-a"): FlatInventoryResource {
  return {
    family: "compute",
    resource_id: `/subscriptions/${subscription}/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-${index}`,
    resource_name: `vm-${index}`,
    resource_type: "microsoft.compute/virtualmachines",
    subscription_id: subscription,
    resource_group: "rg",
    environment: "test",
  };
}

function inventoryEnvelope(
  resources: FlatInventoryResource[],
): Envelope<FlatResourceCollection> {
  return {
    data: {
      resources,
      family_availability: {},
      requested_scope: {},
      query_version: "inventory-resources-v1",
    },
    evidence: [],
    scope: {},
    warnings: [],
    pagination: {
      offset: 0,
      limit: 500,
      total: resources.length,
      next_offset: null,
    },
  };
}

function utilization(resource: FlatInventoryResource, cpu = 42): ResourceUtilization {
  return {
    resource_id: resource.resource_id,
    resource_name: resource.resource_name,
    resource_type: resource.resource_type,
    subscription_id: resource.subscription_id,
    resource_group: resource.resource_group,
    connection_id: "conn-1",
    cpu_percent: cpu,
    network_in_bytes: 1024,
    network_out_bytes: 2048,
    disk_read_bytes: 4096,
    disk_write_bytes: 8192,
    os_disk_queue_depth: 1,
    memory_percent: null,
    disk_free_percent: null,
    status: "healthy",
    observed_at: "2026-09-20T16:00:00Z",
    error: "",
    unavailable_metrics: [],
    cpu_series: [],
  };
}

function healthEnvelope(
  resource: FlatInventoryResource,
): Envelope<ResourceHealthSnapshot> {
  return {
    data: {
      resources: [utilization(resource)],
      summary: {
        total: 1,
        critical: 0,
        warning: 0,
        healthy: 1,
        unknown: 0,
      },
      observed_at: "2026-09-20T16:00:00Z",
      warnings: [],
      unavailable_metrics: ["memory_percent", "disk_free_percent"],
      cached: false,
      cache_ttl_seconds: 120,
    },
    evidence: [],
    scope: {},
    warnings: [],
  };
}

function installDeferredHealthMock() {
  const calls: HealthCall[] = [];
  let active = 0;
  let peak = 0;

  mocks.resourceHealth.mockImplementation(
    (
      resourceId: string,
      scope: ScopeSelection,
      forceRefresh: boolean,
      options: { signal?: AbortSignal },
    ) => {
      const request = deferred<Envelope<ResourceHealthSnapshot>>();
      const signal = options.signal;
      if (!signal) throw new Error("resource health request requires an AbortSignal");
      active += 1;
      peak = Math.max(peak, active);
      const call: HealthCall = {
        resourceId,
        scope,
        forceRefresh,
        signal,
        deferred: request,
        settled: false,
      };
      calls.push(call);
      return request.promise;
    },
  );

  const settle = (
    call: HealthCall,
    outcome: { value: Envelope<ResourceHealthSnapshot> } | { error: Error },
  ) => {
    if (call.settled) throw new Error("request already settled");
    call.settled = true;
    active -= 1;
    if ("value" in outcome) call.deferred.resolve(outcome.value);
    else call.deferred.reject(outcome.error);
  };

  return {
    calls,
    settle,
    get active() {
      return active;
    },
    get peak() {
      return peak;
    },
  };
}

describe("ResourceHealthPage inventory-first hydration", () => {
  beforeEach(() => {
    mocks.copilotInsights.mockClear();
    mocks.inventoryResources.mockReset();
    mocks.resourceHealth.mockReset();
    mocks.retainedHealth.mockReset();
    mocks.captureRetainedHealth.mockReset();
    mocks.scope.current = { subscription: ["sub-a"] };
  });

  it("binds automatic insights to the Health page-only evidence intent", () => {
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope([]));
    render(<ResourceHealthPage />);
    expect(mocks.copilotInsights).toHaveBeenCalledWith(
      expect.objectContaining({ question: RESOURCE_HEALTH_INSIGHT_QUESTION }),
      expect.anything(),
    );
  });

  it("reports missing guest readings without claiming that no workspaces were discovered", async () => {
    const resource = inventoryResource(1);
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope([resource]));
    mocks.resourceHealth.mockResolvedValue(healthEnvelope(resource));
    render(<ResourceHealthPage />);

    const message = await screen.findByText(/Usable VM memory % and disk free % readings were not returned/);
    expect(message).toHaveTextContent("This does not mean no workspaces exist");
    expect(message).toHaveTextContent("guest counters may be missing");
    expect(message).toHaveTextContent("workspace queries may have failed");
    expect(message).toHaveTextContent("telemetry workspace may be outside the selected subscriptions");
    expect(message).toHaveTextContent("Container Apps use platform memory metrics");
    expect(screen.queryByText(/neither was discovered/)).not.toBeInTheDocument();
  });

  it("does not show the guest-metrics banner when no metrics are marked unavailable", async () => {
    const resource = inventoryResource(1);
    const response = healthEnvelope(resource);
    response.data.unavailable_metrics = [];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope([resource]));
    mocks.resourceHealth.mockResolvedValue(response);
    render(<ResourceHealthPage />);

    await screen.findByRole("heading", { name: "CPU comparison" });
    expect(screen.queryByText("Some metrics are unavailable")).not.toBeInTheDocument();
  });

  it("distinguishes health responses from quantified CPU samples and preserves unknowns", async () => {
    const rows = [inventoryResource(1), inventoryResource(2)];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(rows));
    const harness = installDeferredHealthMock();
    render(<ResourceHealthPage />);
    await waitFor(() => expect(harness.calls).toHaveLength(2));
    const unknown = healthEnvelope(rows[0]);
    unknown.data.resources[0].cpu_percent = null;
    unknown.data.resources[0].status = "unknown";
    unknown.data.resources[0].unavailable_metrics = ["cpu_percent", "memory_percent", "disk_free_percent"];
    const populated = healthEnvelope(rows[1]);
    populated.data.resources[0].cpu_percent = 0;
    await act(async () => {
      harness.settle(harness.calls[0], { value: unknown });
      harness.settle(harness.calls[1], { value: populated });
    });
    expect(screen.getByText("2 health responses")).toBeInTheDocument();
    expect(screen.getByText("1 with CPU samples")).toBeInTheDocument();
    expect(screen.queryByText(/returned metrics/)).not.toBeInTheDocument();
    expect(screen.getByText(/1 unknown/)).toBeInTheDocument();
  });

  it("opens history independently of live hydration and restores the invoking card focus", async () => {
    const rows = [inventoryResource(1), inventoryResource(2)];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(rows));
    mocks.retainedHealth.mockRejectedValue(new Error("Retained store is offline"));
    const harness = installDeferredHealthMock();
    render(<ResourceHealthPage />);
    await waitFor(() => expect(harness.calls).toHaveLength(2));
    expect(mocks.retainedHealth).not.toHaveBeenCalled();
    const trigger = screen.getByRole("button", { name: "Review retained health for vm-1" });
    fireEvent.click(trigger);
    expect(await screen.findByRole("alert")).toHaveTextContent("Retained store is offline");
    expect(mocks.retainedHealth).toHaveBeenCalledWith(rows[0].resource_id, mocks.scope.current, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(mocks.captureRetainedHealth).not.toHaveBeenCalled();
    expect(harness.calls).toHaveLength(2);
    expect(harness.calls.every(call => !call.signal.aborted)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close retained health" }));
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("region", { name: "Retained health for vm-1" })).not.toBeInTheDocument();
    await act(async () => {
      harness.settle(harness.calls[0], { value: healthEnvelope(rows[0]) });
      harness.settle(harness.calls[1], { value: healthEnvelope(rows[1]) });
    });
    expect(screen.getByText(/2 of 2 resources returned health evidence/)).toBeInTheDocument();
  });

  it("returns focus to resource search if filtering removed the invoking card", async () => {
    const rows = [inventoryResource(1), inventoryResource(2)];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(rows));
    mocks.retainedHealth.mockRejectedValue(new Error("Retained store is offline"));
    installDeferredHealthMock();
    render(<ResourceHealthPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review retained health for vm-1" }));
    await screen.findByRole("alert");
    const search = screen.getByRole("searchbox", { name: "Find compute resource" });
    fireEvent.change(search, { target: { value: "vm-2" } });
    expect(screen.queryByRole("button", { name: "Review retained health for vm-1" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close retained health" }));
    expect(search).toHaveFocus();
  });

  it("filters coverage states without starting new hydration requests and explains absent metrics", async () => {
    const rows = [inventoryResource(1), inventoryResource(2)];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(rows));
    const harness = installDeferredHealthMock();
    render(<ResourceHealthPage />);
    await waitFor(() => expect(harness.calls).toHaveLength(2));
    const result = healthEnvelope(rows[0]);
    result.data.resources[0].unavailable_metrics = ["memory_percent", "disk_free_percent"];
    await act(async () => {
      harness.settle(harness.calls[0], { value: result });
      harness.settle(harness.calls[1], { error: new Error("Metrics permission denied") });
    });
    expect(screen.getByText(/1 of 2 resources returned health evidence/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Health state"), { target: { value: "failed" } });
    expect(screen.queryByText("vm-1")).not.toBeInTheDocument();
    expect(screen.getByText("vm-2")).toBeInTheDocument();
    expect(harness.calls).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Health state"), { target: { value: "healthy" } });
    expect(screen.getByText("Missing metric diagnostics")).toBeInTheDocument();
    expect(screen.getByText(/checks to perform, not confirmed causes/)).toBeInTheDocument();
  });

  it("shows a friendly resource-type pill on every resource card", async () => {
    const virtualMachine = inventoryResource(1);
    const containerApp: FlatInventoryResource = {
      ...inventoryResource(2),
      resource_id:
        "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.App/containerApps/api",
      resource_name: "api",
      resource_type: "microsoft.app/containerapps",
    };
    mocks.inventoryResources.mockResolvedValue(
      inventoryEnvelope([containerApp, virtualMachine]),
    );
    installDeferredHealthMock();

    render(<ResourceHealthPage />);

    expect(
      await screen.findByText("Container App", { selector: ".status-badge" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Virtual Machine", { selector: ".status-badge" }),
    ).toBeInTheDocument();
  });

  it("renders cards before metrics resolve and starts at most six requests", async () => {
    const resources = Array.from({ length: 8 }, (_, index) =>
      inventoryResource(index + 1),
    );
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(resources));
    const tracker = installDeferredHealthMock();

    render(<ResourceHealthPage />);

    expect(await screen.findByText("vm-1")).toBeInTheDocument();
    expect(screen.getByText("vm-8")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Resource utilization" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "vm-1", level: 3 })).toBeVisible();
    expect(screen.getByText("0 of 8 health responses · 0 resources with CPU samples")).toBeVisible();
    expect(screen.getByRole("status", { name: "Loading health for vm-1" })).toBeInTheDocument();
    expect(tracker.calls).toHaveLength(6);
    expect(tracker.peak).toBe(6);
    expect(mocks.inventoryResources).toHaveBeenCalledWith(
      { subscription: ["sub-a"] },
      0,
      500,
    );

    await act(async () => {
      tracker.settle(tracker.calls[0], {
        value: healthEnvelope(resources[0]),
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(tracker.calls).toHaveLength(7));
    expect(tracker.peak).toBe(6);
  });

  it("isolates a failed card and retries only that resource", async () => {
    const resources = [
      inventoryResource(1),
      inventoryResource(2),
      inventoryResource(3),
    ];
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(resources));
    const tracker = installDeferredHealthMock();

    render(<ResourceHealthPage />);
    await waitFor(() => expect(tracker.calls).toHaveLength(3));

    await act(async () => {
      tracker.settle(tracker.calls[0], { error: new Error("Metrics unavailable") });
      tracker.settle(tracker.calls[1], {
        value: healthEnvelope(resources[1]),
      });
      await Promise.resolve();
    });

    expect(
      await screen.findByRole("alert", { name: "Health error for vm-1" }),
    ).toHaveTextContent("Metrics unavailable");
    expect(screen.getByText("42.0%")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 health responses · 1 resources with CPU samples")).toBeVisible();
    const resourcesRegion = screen.getByRole("region", { name: "Resource utilization" });
    const comparison = screen.getByRole("region", { name: "CPU comparison" });
    expect(resourcesRegion.compareDocumentPosition(comparison) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(
      screen.getByRole("status", { name: "Loading health for vm-3" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry health for vm-1" }));

    await waitFor(() => expect(tracker.calls).toHaveLength(4));
    expect(tracker.calls[3].resourceId).toBe(resources[0].resource_id);
    expect(tracker.calls[3].forceRefresh).toBe(true);
    expect(screen.getByRole("status", { name: "Loading health for vm-1" })).toBeInTheDocument();
  });

  it.each(["scope change", "refresh"] as const)(
    "keeps the global request ceiling while obsolete work settles after %s",
    async (transition) => {
      const oldResources = Array.from({ length: 8 }, (_, index) =>
        inventoryResource(index + 1),
      );
      const newResources = [inventoryResource(20, "sub-b")];
      mocks.inventoryResources
        .mockResolvedValueOnce(inventoryEnvelope(oldResources))
        .mockResolvedValueOnce(inventoryEnvelope(newResources));
      const tracker = installDeferredHealthMock();

      const { rerender } = render(<ResourceHealthPage />);
      await waitFor(() => expect(tracker.calls).toHaveLength(6));

      if (transition === "scope change") {
        mocks.scope.current = { subscription: ["sub-b"] };
        rerender(<ResourceHealthPage />);
        expect(await screen.findByText("vm-20")).toBeInTheDocument();
        expect(screen.queryByText("vm-1")).not.toBeInTheDocument();
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
      }

      expect(tracker.calls.slice(0, 6).every((call) => call.signal.aborted)).toBe(true);
      expect(tracker.calls).toHaveLength(6);

      await act(async () => {
        tracker.settle(tracker.calls[0], {
          value: healthEnvelope(oldResources[0]),
        });
        await Promise.resolve();
      });

      await waitFor(() => expect(tracker.calls).toHaveLength(7));
      expect(tracker.peak).toBe(6);
      expect(tracker.calls[6].forceRefresh).toBe(transition === "refresh");
      expect(tracker.calls[6].scope).toEqual(
        transition === "scope change"
          ? { subscription: ["sub-b"] }
          : { subscription: ["sub-a"] },
      );

      if (transition === "scope change") {
        expect(screen.queryByText("vm-1")).not.toBeInTheDocument();
      }
    },
  );

  it("aborts all active health requests on unmount", async () => {
    const resources = Array.from({ length: 6 }, (_, index) =>
      inventoryResource(index + 1),
    );
    mocks.inventoryResources.mockResolvedValue(inventoryEnvelope(resources));
    const tracker = installDeferredHealthMock();

    const { unmount } = render(<ResourceHealthPage />);
    await waitFor(() => expect(tracker.calls).toHaveLength(6));

    unmount();

    expect(tracker.calls.every((call) => call.signal.aborted)).toBe(true);
    expect(tracker.active).toBe(6);
  });
});
